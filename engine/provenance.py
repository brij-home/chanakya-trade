"""
engine/provenance.py
────────────────────
Universal Data Provenance & Freshness Engine for Indian Markets.

Every analytical, market quote, options chain, and agent insight carries
a strict DataProvenance envelope to ensure transparency, traceability,
and disclosure of proxy approximations.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Literal, Optional

# Canonical Asia/Kolkata timezone offset (+05:30)
IST_OFFSET = timezone(timedelta(hours=5, minutes=30))

ProvenanceSource = Literal[
    "LIVE_BROKER",  # Real-time WebSocket or REST tick from connected broker (Fyers, Zerodha, etc.)
    "LIVE_TICK",  # Direct live exchange quote
    "NSE_SCRAPER",  # Official NSE live scraper feed
    "HISTORICAL_EOD",  # Verified End-of-Day historical bar dataset
    "SYNTHETIC_PROXY",  # Black-Scholes / Monte Carlo calculated synthetic proxy
    "FALLBACK_CACHE",  # Stored SQLite / in-memory cache fallback
]


@dataclass
class DataProvenance:
    """Canonical metadata envelope attached to all data responses."""

    data_source: ProvenanceSource
    as_of: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    as_of_ist: str = ""
    freshness_seconds: float = 0.0
    completeness_pct: float = 100.0
    is_indicative_proxy: bool = False
    is_tradable: bool = True
    venue: str = "NSE"
    fallback_reason: Optional[str] = None

    def __post_init__(self):
        if not self.as_of_ist:
            try:
                # Parse as_of timestamp and convert accurately to IST (+05:30)
                dt = datetime.fromisoformat(self.as_of)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                ist_dt = dt.astimezone(IST_OFFSET)
                self.as_of_ist = ist_dt.strftime("%d %b %Y, %H:%M:%S IST")
            except Exception:
                ist_dt = datetime.now(timezone.utc).astimezone(IST_OFFSET)
                self.as_of_ist = ist_dt.strftime("%d %b %Y, %H:%M:%S IST")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def create_provenance(
    source: ProvenanceSource,
    freshness_seconds: float = 0.0,
    is_proxy: bool = False,
    is_tradable: bool = True,
    venue: str = "NSE",
    completeness: float = 100.0,
    fallback_reason: Optional[str] = None,
) -> DataProvenance:
    """Helper to instantiate a standardized DataProvenance contract."""
    return DataProvenance(
        data_source=source,
        freshness_seconds=max(0.0, float(freshness_seconds)),
        completeness_pct=min(100.0, max(0.0, float(completeness))),
        is_indicative_proxy=is_proxy or (source == "SYNTHETIC_PROXY"),
        is_tradable=is_tradable and not (is_proxy or source == "SYNTHETIC_PROXY"),
        venue=venue,
        fallback_reason=fallback_reason,
    )


def attach_provenance(
    payload: dict[str, Any],
    source: ProvenanceSource = "LIVE_TICK",
    is_proxy: bool = False,
    is_tradable: bool = True,
    venue: str = "NSE",
    fallback_reason: Optional[str] = None,
) -> dict[str, Any]:
    """Attaches a _provenance block to an existing dictionary payload."""
    if not isinstance(payload, dict):
        return payload
    prov = create_provenance(
        source=source,
        is_proxy=is_proxy,
        is_tradable=is_tradable,
        venue=venue,
        fallback_reason=fallback_reason,
    )
    payload["_provenance"] = prov.to_dict()
    return payload
