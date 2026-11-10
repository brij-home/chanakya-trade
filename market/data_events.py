"""Provider-neutral market-data events and quality semantics.

The UI and risk engine must be able to distinguish a current streamed quote
from a delayed fallback. Broker SDK payloads differ, so this small contract is
the only shape that crosses the market-data boundary.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional


DataState = Literal["LIVE", "DELAYED", "EOD", "DEGRADED", "UNAVAILABLE"]
DataSource = Literal["STREAM", "REST", "EOD_SNAPSHOT", "FALLBACK", "CACHE", "SYNTHETIC"]

VERIFIED_LIVE_PROVIDERS = {
    "fyers",
    "zerodha",
    "angelone",
    "upstox",
    "shoonya",
    "mstock",
    "kotak",
    "dhan",
    "groww",
    "stoxkart",
    "flattrade",
}


def utc_now_iso() -> str:
    """Return an unambiguous UTC timestamp suitable for persisted events."""
    return datetime.now(timezone.utc).isoformat()


def parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO timestamp defensively, returning ``None`` for unknown input."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class MarketDataEvent:
    """Normalized, timestamped snapshot from one provider.

    ``sequence`` is optional because several Indian retail broker feeds do not
    supply one. Consumers must not infer sequence continuity when it is absent.
    """

    canonical_instrument_id: str
    provider: str
    provider_symbol: str
    source: DataSource
    data_state: DataState
    last_price: float
    received_at: str = field(default_factory=utc_now_iso)
    received_monotonic_ns: int = field(default_factory=time.monotonic_ns)
    exchange_timestamp: Optional[str] = None
    sequence: Optional[str] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume: Optional[int] = None
    oi: Optional[int] = None
    atp: Optional[float] = None
    quality_flags: tuple[str, ...] = ()
    correlation_id: Optional[str] = None

    @property
    def symbol(self) -> str:
        """Convenience symbol name for downstream consumers."""
        if self.provider_symbol:
            return self.provider_symbol
        return (
            self.canonical_instrument_id.split(":")[-1]
            if ":" in self.canonical_instrument_id
            else self.canonical_instrument_id
        )

    @property
    def age_seconds(self) -> Optional[float]:
        """Age since local receipt; never use request duration as market age."""
        received = parse_timestamp(self.received_at)
        if received is None:
            return None
        return max(0.0, (datetime.now(timezone.utc) - received).total_seconds())

    @property
    def is_fresh_live(self) -> bool:
        """True only for recently received data explicitly marked as live."""
        age = self.age_seconds
        return self.data_state == "LIVE" and age is not None and age <= 60.0


def classify_data_state(*, source: DataSource, provider: str, price: float) -> DataState:
    """Apply conservative source-state defaults at provider adapters."""
    if price <= 0:
        return "UNAVAILABLE"
    if source == "EOD_SNAPSHOT":
        return "EOD"
    prov = provider.lower()
    if source in ("FALLBACK", "SYNTHETIC"):
        if prov in {"yfinance", "yahoo"}:
            return "DELAYED"
        return "DEGRADED"
    if source == "CACHE":
        return "DEGRADED"
    if prov in {"yfinance", "yahoo", "cache", "unknown"}:
        return "DELAYED" if source != "CACHE" else "DEGRADED"
    if source in ("STREAM", "REST"):
        if prov in VERIFIED_LIVE_PROVIDERS or any(vp in prov for vp in VERIFIED_LIVE_PROVIDERS):
            return "LIVE"
        return "DEGRADED"
    return "DEGRADED"
