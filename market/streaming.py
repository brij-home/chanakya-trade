"""Small, provider-neutral real-time stream boundary for the local pilot.

It deliberately avoids a broker failover engine.  Its job is to preserve event
provenance, bounded delivery, reconnect visibility and safe degradation.
"""

from __future__ import annotations
import logging

logger = logging.getLogger("market.streaming")


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
    except (TypeError, ValueError, OSError) as e_suppressed:
        logger.debug(f"[market.streaming] Non-fatal exception suppressed: {e_suppressed}")
    return None


def normalize_noren_tick(
    raw: dict[str, Any],
    *,
    provider: str = "noren",
    correlation_id: Optional[str] = None,
) -> Optional[MarketDataEvent]:
    """Normalize a Noren protocol tick (used by Flattrade, Shoonya) without assuming sequence field."""
    price = raw.get("lp") or raw.get("ltp")
    try:
        last_price = float(price)
    except (TypeError, ValueError):
        return None
    exchange = str(raw.get("e") or raw.get("exch") or "NSE").upper()
    provider_symbol = str(raw.get("ts") or "")
    if not provider_symbol and raw.get("tk"):
        try:
            from market.symbol_facade import get_symbol_facade

            provider_symbol = get_symbol_facade().get_symbol_by_token(
                str(raw["tk"]), exchange
            ) or str(raw["tk"])
        except Exception:
            provider_symbol = str(raw["tk"])
    if not provider_symbol:
        return None
    atp = _float_or_none(raw.get("ap") or raw.get("atp") or raw.get("vwap"))
    return MarketDataEvent(
        canonical_instrument_id=f"{exchange}:{provider_symbol}",
        provider=provider,
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
        atp=atp,
        quality_flags=() if last_price > 0 else ("NON_POSITIVE_PRICE",),
        correlation_id=correlation_id,
    )


def normalize_flattrade_tick(
    raw: dict[str, Any], *, correlation_id: Optional[str] = None
) -> Optional[MarketDataEvent]:
    """Normalize a Flattrade (Noren API) WebSocket tick with provider='flattrade'."""
    return normalize_noren_tick(raw, provider="flattrade", correlation_id=correlation_id)


def normalize_shoonya_tick(
    raw: dict[str, Any], *, correlation_id: Optional[str] = None
) -> Optional[MarketDataEvent]:
    """Backwards-compatible normalizer for legacy Shoonya (Noren API) ticks with provider='shoonya'."""
    return normalize_noren_tick(raw, provider="shoonya", correlation_id=correlation_id)


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
            except ValueError as e_suppressed:
                logger.debug(f"[market.streaming] Non-fatal exception suppressed: {e_suppressed}")
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
            try:
                from market.calendar import is_market_open

                exch = (
                    event.canonical_instrument_id.split(":")[0]
                    if ":" in event.canonical_instrument_id
                    else "NSE"
                )
                if is_market_open(exch):
                    get_registry().record_provider_error(event.provider, is_stale=True)
            except Exception as e_suppressed:
                logger.debug(f"[market.streaming] Non-fatal exception suppressed: {e_suppressed}")
        else:
            get_registry().record_provider_success(event.provider)
        try:
            from market.tick_store import tick_archive

            tick_archive.record(event)
        except Exception as e_suppressed:
            # Recording is best-effort and must not affect the market-data path.
            logger.debug(f"[market.streaming] Non-fatal exception suppressed: {e_suppressed}")
        try:
            from engine.market_matrix import get_market_matrix

            get_market_matrix().on_tick(event)
        except Exception as e_suppressed:
            logger.debug(f"[market.streaming] MarketMatrix ingestion error: {e_suppressed}")
        with self._lock:
            self._latest[event.canonical_instrument_id] = event
            callbacks = tuple(self._callbacks)
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(event)
            except queue.Empty as e_suppressed:
                logger.debug(f"[market.streaming] Non-fatal exception suppressed: {e_suppressed}")
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


def start_noren_stream(broker: Any, *, provider: str = "flattrade") -> None:
    """Start the selected Noren protocol (Flattrade / Shoonya) data stream."""

    def on_quote(raw: dict[str, Any]) -> None:
        event = normalize_noren_tick(raw, provider=provider)
        if event:
            market_streams.publish(event)

    broker.start_websocket(on_quote=on_quote)


def start_flattrade_stream(broker: Any) -> None:
    """Start Flattrade streaming."""
    start_noren_stream(broker, provider="flattrade")


def start_shoonya_stream(broker: Any) -> None:
    """Legacy Shoonya stream wrapper."""
    start_noren_stream(broker, provider="shoonya")
