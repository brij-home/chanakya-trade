"""Small, provider-neutral real-time stream boundary for the local pilot.

It deliberately avoids a broker failover engine.  Its job is to preserve event
provenance, bounded delivery, reconnect visibility and safe degradation.
"""

from __future__ import annotations

import queue
import threading
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from engine.observability import get_registry
from market.data_events import MarketDataEvent


def _timestamp_from_epoch(value: Any) -> Optional[str]:
    try:
        numeric = float(value)
        if numeric > 0:
            return datetime.fromtimestamp(numeric, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        pass
    return None


def normalize_shoonya_tick(
    raw: dict[str, Any], *, correlation_id: Optional[str] = None
) -> Optional[MarketDataEvent]:
    """Normalize a Noren tick without assuming an unavailable sequence field."""
    price = raw.get("lp") or raw.get("ltp")
    try:
        last_price = float(price)
    except (TypeError, ValueError):
        return None
    exchange = str(raw.get("e") or raw.get("exch") or "NSE").upper()
    provider_symbol = str(raw.get("ts") or raw.get("tk") or "")
    if not provider_symbol:
        return None
    return MarketDataEvent(
        canonical_instrument_id=f"{exchange}:{provider_symbol}",
        provider="shoonya",
        provider_symbol=provider_symbol,
        source="STREAM",
        data_state="LIVE" if last_price > 0 else "UNAVAILABLE",
        last_price=last_price,
        exchange_timestamp=_timestamp_from_epoch(raw.get("ft")),
        sequence=str(raw["seq"]) if raw.get("seq") is not None else None,
        bid=_float_or_none(raw.get("bp1")),
        ask=_float_or_none(raw.get("sp1")),
        volume=_int_or_none(raw.get("v")),
        oi=_int_or_none(raw.get("oi")),
        quality_flags=() if last_price > 0 else ("NON_POSITIVE_PRICE",),
        correlation_id=correlation_id,
    )


def _float_or_none(value: Any) -> Optional[float]:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(float(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class StreamStatus:
    provider: str
    state: str  # LIVE | DEGRADED | UNAVAILABLE
    last_event_at: Optional[str]
    dropped_events: int


class MarketDataStreamRegistry:
    """Bounded fan-out registry; a slow UI callback can never block a feed."""

    def __init__(self, max_events: int = 2_000) -> None:
        self._queue: queue.Queue[MarketDataEvent] = queue.Queue(maxsize=max_events)
        self._latest: dict[str, MarketDataEvent] = {}
        self._callbacks: list[Callable[[MarketDataEvent], None]] = []
        self._dropped_events = 0
        self._lock = threading.Lock()

    @staticmethod
    def _jump_threshold_pct() -> float:
        try:
            return max(1.0, float(os.environ.get("MARKET_DATA_JUMP_PCT", "10")))
        except ValueError:
            return 10.0

    def _validate_event(self, event: MarketDataEvent) -> MarketDataEvent:
        """Flag anomalies for display/risk gates without rejecting valid market gaps."""
        with self._lock:
            previous = self._latest.get(event.canonical_instrument_id)
        flags = set(event.quality_flags)
        if event.last_price <= 0:
            flags.add("NON_POSITIVE_PRICE")
        if event.bid is not None and event.ask is not None and event.bid > event.ask:
            flags.add("CROSSED_MARKET")
        if previous and previous.last_price > 0 and event.last_price > 0:
            move_pct = abs(event.last_price - previous.last_price) / previous.last_price * 100
            if move_pct > self._jump_threshold_pct():
                flags.add("UNUSUAL_PRICE_JUMP")
        if previous and previous.sequence and event.sequence:
            try:
                if int(event.sequence) > int(previous.sequence) + 1:
                    flags.add("SEQUENCE_GAP")
            except ValueError:
                pass
        state = (
            "DEGRADED"
            if {"NON_POSITIVE_PRICE", "CROSSED_MARKET"}.intersection(flags)
            else event.data_state
        )
        return replace(event, data_state=state, quality_flags=tuple(sorted(flags)))

    def subscribe(self, callback: Callable[[MarketDataEvent], None]) -> None:
        with self._lock:
            self._callbacks.append(callback)

    def publish(self, event: MarketDataEvent) -> None:
        event = self._validate_event(event)
        if event.data_state == "UNAVAILABLE":
            get_registry().record_provider_error(event.provider, is_stale=True)
        else:
            get_registry().record_provider_success(event.provider)
        try:
            from market.tick_store import tick_archive

            tick_archive.record(event)
        except Exception:
            # Recording is best-effort and must not affect the market-data path.
            pass
        with self._lock:
            self._latest[event.canonical_instrument_id] = event
            callbacks = tuple(self._callbacks)
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(event)
            except queue.Empty:
                pass
            self._dropped_events += 1
        for callback in callbacks:
            try:
                callback(event)
            except Exception:
                # A consumer must not take down the data connection.
                continue

    def latest(self, canonical_instrument_id: str) -> Optional[MarketDataEvent]:
        with self._lock:
            return self._latest.get(canonical_instrument_id)

    def status(self, provider: str) -> StreamStatus:
        with self._lock:
            matching = [event for event in self._latest.values() if event.provider == provider]
            last_event = max(matching, key=lambda event: event.received_at, default=None)
            dropped = self._dropped_events
        return StreamStatus(
            provider=provider,
            state="LIVE"
            if last_event and last_event.is_fresh_live
            else "DEGRADED"
            if last_event
            else "UNAVAILABLE",
            last_event_at=last_event.received_at if last_event else None,
            dropped_events=dropped,
        )


market_streams = MarketDataStreamRegistry()


def start_shoonya_stream(broker: Any) -> None:
    """Start the selected Shoonya data stream, if the optional dependency exists."""

    def on_quote(raw: dict[str, Any]) -> None:
        event = normalize_shoonya_tick(raw)
        if event:
            market_streams.publish(event)

    broker.start_websocket(on_quote=on_quote)
