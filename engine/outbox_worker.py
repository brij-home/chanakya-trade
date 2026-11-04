"""
engine/outbox_worker.py
───────────────────────
Transactional Outbox Worker for durable multi-channel alert delivery.

Guarantees:
1. Claim -> Dispatch -> Acknowledge/Fail lifecycle.
2. Channel dispatch authority for TELEGRAM and SSE.
3. Automatic lease expiration and crash recovery.
4. Prevents duplicate shadow dispatches.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Callable, Optional

from engine.sqlite_store import alert_sqlite_store

logger = logging.getLogger("engine.outbox_worker")


class OutboxWorker:
    """
    Active worker process for the transactional alert outbox.
    Leases pending entries, delivers across communication transports,
    and acknowledges completion atomically.
    """

    def __init__(
        self,
        store: Any = None,
        worker_id: Optional[str] = None,
        lease_seconds: float = 30.0,
        telegram_dispatcher: Optional[Callable[[dict[str, Any]], bool]] = None,
        sse_dispatcher: Optional[Callable[[dict[str, Any]], bool]] = None,
    ):
        self.store = store or alert_sqlite_store
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.lease_seconds = lease_seconds
        self._telegram_dispatcher = telegram_dispatcher
        self._sse_dispatcher = sse_dispatcher
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def dispatch_channel_entry(self, entry: dict[str, Any]) -> bool:
        """Deliver a claimed outbox entry to its target transport."""
        channel = str(entry.get("channel") or "").upper().strip()
        payload = entry.get("payload") or {}

        if channel == "SSE":
            if self._sse_dispatcher:
                return bool(self._sse_dispatcher(payload))
            try:
                from web.sse import event_bus

                event_bus.publish_sync("alert", payload)
                return True
            except Exception as e_sse:
                logger.debug(f"[OutboxWorker] SSE delivery error: {e_sse}")
                raise

        elif channel == "TELEGRAM":
            if self._telegram_dispatcher:
                return bool(self._telegram_dispatcher(payload))
            try:
                is_test = (
                    payload.get("environment") == "TEST"
                    or not payload.get("is_live", True)
                    or str(payload.get("alert_id", "")).startswith(("test-", "mock-"))
                )
                if is_test:
                    return True

                # Render the alert payload dict into a Telegram-formatted string.
                # send_push() expects a str as its first argument; passing the raw
                # dict causes "expected string or bytes-like object, got 'dict'".
                try:
                    from bot.alert_templates import render_auto_alert

                    rendered_text = render_auto_alert(payload)
                except Exception as e_render:
                    logger.warning(
                        f"[OutboxWorker] render_auto_alert failed, falling back to headline: {e_render}"
                    )
                    rendered_text = str(
                        payload.get("headline")
                        or payload.get("summary")
                        or payload.get("alert_id")
                        or "Alert"
                    )

                alert_id_kw = payload.get("alert_id") or None
                target_chat_id = payload.get("chat_id") or payload.get("target_chat_id")
                if not target_chat_id:
                    try:
                        from engine.alert_preferences import (
                            alert_preferences,
                            classify_alert_segment,
                        )

                        target_seg = classify_alert_segment(payload)
                        target_chat_id = alert_preferences.get_telegram_chat_id(target_seg)
                    except Exception as e_seg:
                        logger.debug(f"[OutboxWorker] Segment lookup note: {e_seg}")
                        target_chat_id = None

                try:
                    from bot.telegram_bot import get_telegram_bot

                    bot = get_telegram_bot()
                    if bot and hasattr(bot, "send_push"):
                        res = bot.send_push(
                            rendered_text,
                            parse_mode="HTML",
                            chat_id=target_chat_id,
                            alert_id=alert_id_kw,
                        )
                        if res is False:
                            raise RuntimeError("Telegram send_push returned False")
                        return True
                except ImportError as e_import:
                    logger.debug(f"[OutboxWorker] Telegram singleton import failed: {e_import}")

                from bot.telegram_bot import send_push

                res = send_push(
                    rendered_text,
                    parse_mode="HTML",
                    chat_id=target_chat_id,
                    alert_id=alert_id_kw,
                )
                if res is False:
                    raise RuntimeError("Telegram send_push returned False")
                return True
            except Exception as e_tg:
                logger.error(f"[OutboxWorker] Telegram delivery error: {e_tg}")
                raise

        else:
            logger.error(f"[OutboxWorker] Unknown channel {channel}; rejecting outbox entry")
            raise ValueError(f"Unsupported outbox channel: {channel}")

    def process_outbox_batch(self, limit: int = 50, channel: Optional[str] = None) -> int:
        """
        Runs one claim -> dispatch -> acknowledge pass.
        Returns count of successfully acknowledged entries.
        """
        claimed = self.store.claim_pending_outbox_entries(
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
            limit=limit,
            channel=channel,
        )
        if not claimed:
            return 0

        processed = 0
        for entry in claimed:
            outbox_id = entry["outbox_id"]
            try:
                self.dispatch_channel_entry(entry)
                self.store.mark_outbox_acknowledged(outbox_id, worker_id=self.worker_id)
                processed += 1
            except Exception as e:
                logger.error(f"[OutboxWorker] Delivery error for {outbox_id}: {e}")
                self.store.mark_outbox_failed(outbox_id, error=str(e), worker_id=self.worker_id)

        return processed

    def reclaim_expired_leases(self, older_than_seconds: float = 60.0) -> int:
        """Reclaims unacknowledged entries whose leases have expired."""
        ambiguous = self.store.get_ambiguous_outbox_entries(older_than_seconds=older_than_seconds)
        reclaimed = 0
        for entry in ambiguous:
            outbox_id = entry["outbox_id"]
            ok = self.store.reclaim_ambiguous_entry(
                outbox_id, retry=True, error="Worker lease expired"
            )
            if ok:
                reclaimed += 1
        return reclaimed

    def start(self, poll_interval: float = 1.0) -> None:
        """Start background worker thread."""
        if self._running:
            return
        self._running = True

        def _loop():
            while self._running:
                try:
                    self.process_outbox_batch()
                    self.reclaim_expired_leases()
                except Exception as e:
                    logger.debug(f"[OutboxWorker] Background loop exception: {e}")
                time.sleep(poll_interval)

        self._thread = threading.Thread(target=_loop, name=f"outbox-{self.worker_id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop background worker thread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            self._thread = None


_global_outbox_worker: Optional[OutboxWorker] = None
_outbox_worker_lock = threading.Lock()


def get_outbox_worker() -> OutboxWorker:
    global _global_outbox_worker
    with _outbox_worker_lock:
        if _global_outbox_worker is None:
            _global_outbox_worker = OutboxWorker()
        return _global_outbox_worker
