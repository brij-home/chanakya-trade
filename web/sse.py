"""
web/sse.py
──────────
Server-Sent Events bus for real-time price and alert streaming.

Usage:
    from web.sse import event_bus

    event_bus.publish("price", {"symbol": "NIFTY", "ltp": 24500.0})
    event_bus.publish("alert", {"symbol": "INFY", "message": "RSI > 70"})

    # In FastAPI endpoint:
    async for chunk in event_bus.subscribe("price"):
        yield chunk
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict, deque
from typing import Any, AsyncGenerator, Optional

logger = logging.getLogger("web.sse")


class SSEEventBus:
    """
    Production pub/sub bus for SSE streams with bounded monotonic Last-Event-ID replay.

    Each channel (e.g. "price", "alert", "ticker") delivers sequence-tagged envelopes
    so reconnecting clients can pass `last_event_id` to recover missed transitions.
    Max queue size: 100 events per subscriber (oldest dropped if full).
    Heartbeat: sends ": heartbeat\\n\\n" every 15s to keep connections alive.
    """

    HEARTBEAT_INTERVAL = 15  # seconds
    MAX_QUEUE_SIZE = 100
    MAX_SUBSCRIBERS_PER_CHANNEL = 50
    MAX_TOTAL_SUBSCRIBERS = 200
    REPLAY_BUFFER_SIZE = 500

    def __init__(self) -> None:
        self._channels: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._seq: int = 0
        self._replay: dict[str, deque[tuple[int, dict]]] = defaultdict(
            lambda: deque(maxlen=self.REPLAY_BUFFER_SIZE)
        )

    def _dispatch_to_queues(self, channel: str, data: dict) -> int:
        """Assign monotonic seq ID, append to replay buffer, and push to active queues."""
        self._seq += 1
        seq = self._seq
        envelope = {"_sse_seq": seq, "payload": data}
        self._replay[channel].append((seq, data))
        queues = list(self._channels.get(channel, []))
        count = 0
        for q in queues:
            try:
                q.put_nowait(envelope)
                count += 1
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                    q.put_nowait(envelope)
                    count += 1
                except Exception as e_suppressed:
                    logger.debug(f"[web.sse] Non-fatal exception suppressed: {e_suppressed}")
            except Exception as e_suppressed:
                logger.debug(f"[web.sse] Non-fatal exception suppressed: {e_suppressed}")
        if count > 0 or queues:
            logger.debug(
                f"[SSEEventBus] Dispatched {channel}#{seq} event to {count}/{len(queues)} queues"
            )
        return count

    async def publish(self, channel: str, data: dict) -> int:
        """Publish to all subscribers on channel. Returns subscriber count."""
        return self._dispatch_to_queues(channel, data)

    async def subscribe(
        self, channel: str, last_event_id: Optional[int] = None
    ) -> AsyncGenerator[str, None]:
        """Yield SSE-formatted strings with monotonic id: 'id: <seq>\\ndata: {...}\\n\\n'"""
        total_subs = sum(len(qs) for qs in self._channels.values())
        if (
            len(self._channels[channel]) >= self.MAX_SUBSCRIBERS_PER_CHANNEL
            or total_subs >= self.MAX_TOTAL_SUBSCRIBERS
        ):
            logger.warning(
                f"[SSEEventBus] Subscriber rejected: channel '{channel}' cap reached "
                f"(channel={len(self._channels[channel])}/{self.MAX_SUBSCRIBERS_PER_CHANNEL}, "
                f"total={total_subs}/{self.MAX_TOTAL_SUBSCRIBERS})"
            )
            yield f"event: error\ndata: {json.dumps({'error': 'Channel subscriber capacity reached'})}\n\n"
            return

        q: asyncio.Queue = asyncio.Queue(maxsize=self.MAX_QUEUE_SIZE)
        self._channels[channel].append(q)
        logger.info(
            f"[SSEEventBus] Subscriber connected to '{channel}' (total={len(self._channels[channel])})"
        )

        try:
            # Replay missed sequence-indexed events on reconnect when Last-Event-ID is provided
            if last_event_id is not None:
                for seq, missed_data in list(self._replay.get(channel, ())):
                    if seq > last_event_id:
                        yield f"id: {seq}\ndata: {json.dumps(missed_data, default=str)}\n\n"

            while True:
                try:
                    item = await asyncio.wait_for(q.get(), timeout=self.HEARTBEAT_INTERVAL)
                    if isinstance(item, dict) and "_sse_seq" in item and "payload" in item:
                        yield f"id: {item['_sse_seq']}\ndata: {json.dumps(item['payload'], default=str)}\n\n"
                    else:
                        yield f"data: {json.dumps(item, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            try:
                self._channels[channel].remove(q)
                logger.info(
                    f"[SSEEventBus] Subscriber disconnected from '{channel}' (remaining={len(self._channels[channel])})"
                )
            except ValueError as e_suppressed:
                logger.debug(f"[web.sse] Non-fatal exception suppressed: {e_suppressed}")

    def publish_sync(self, channel: str, data: dict) -> None:
        """Thread-safe publish from sync code (e.g. background polling threads)."""
        target_loop = getattr(self, "_main_loop", None)
        if target_loop and target_loop.is_running():
            try:
                target_loop.call_soon_threadsafe(self._dispatch_to_queues, channel, data)
                return
            except Exception as e:
                logger.warning(f"[SSEEventBus] call_soon_threadsafe error: {e}")

        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(self._dispatch_to_queues, channel, data)
        except RuntimeError:
            self._dispatch_to_queues(channel, data)

    def publish_domain_event(self, event: Any) -> None:
        """
        Thread-safe publish for strongly-typed domain events (e.g. AlertDomainEvent).
        Enforces contract serialization and dispatches to 'alert' channel.
        """
        if hasattr(event, "to_sse_dict"):
            data = event.to_sse_dict()
        elif isinstance(event, dict):
            data = event
        else:
            raise TypeError(f"Expected AlertDomainEvent or dict, got {type(event).__name__}")
        self.publish_sync("alert", data)

    async def broadcast(self, data: dict, channel: str = "alert") -> None:
        """Async compatibility alias forwarding cleanly to the canonical SSE bus."""
        await self.publish(channel, data)


event_bus = SSEEventBus()  # module-level singleton
