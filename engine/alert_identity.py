"""
engine/alert_identity.py
────────────────────────
Centralized alert identity factory for ChanakyaTrade.

Institutional Invariants:
1. Single Authority: All detectors MUST generate alert IDs through generate_alert_id().
2. Daily Determinism: Alert IDs are strictly tied to calendar session date (%Y%m%d),
   NEVER to minute/second timestamps or random UUIDs.
3. Canonical Symbol Normalization: Uniformly strips exchange prefixes (NSE, BSE, MCX, NFO, CDS, CRYPTO, BINANCE).
"""

from __future__ import annotations

import re
from datetime import date, datetime, time as dtime
from functools import lru_cache
from typing import Optional

from config.constants import IST

_KNOWN_PREFIXES = (
    "NSE:",
    "BSE:",
    "MCX:",
    "NFO:",
    "BFO:",
    "CDS:",
    "CRYPTO:",
    "BINANCE:",
    "DERIBIT:",
)

# Regex matching banned volatile suffixes (e.g. 12+ digit minute timestamps or random UUID hexes)
_VOLATILE_ID_PATTERN = re.compile(
    r"-\d{12,}$|-(?=[0-9a-f]*[a-f])[0-9a-f]{6,}$|-[0-9a-f]{8}-[0-9a-f]{4}-",
    re.IGNORECASE,
)


_INDEX_ALIAS_MAP = {
    "NIFTY 50": "NIFTY",
    "NIFTY50": "NIFTY",
    "BANK NIFTY": "BANKNIFTY",
    "BANKNIFTY": "BANKNIFTY",
    "FIN NIFTY": "FINNIFTY",
    "FINNIFTY": "FINNIFTY",
    "MIDCAP NIFTY": "MIDCPNIFTY",
    "MIDCP NIFTY": "MIDCPNIFTY",
    "MIDCPNIFTY": "MIDCPNIFTY",
    "NIFTY BANK": "BANKNIFTY",
    "NIFTYBANK": "BANKNIFTY",
    "NIFTY IT": "NIFTYIT",
    "INDIA VIX": "INDIAVIX",
    "INDIAVIX": "INDIAVIX",
}


@lru_cache(maxsize=2048)
def canonical_alert_symbol(raw_sym: str) -> str:
    """
    Normalizes any asset symbol into its canonical clean uppercase identifier.
    Delegates to institutional SSOT market.instruments.canonical_symbol.
    """
    from market.instruments import canonical_symbol

    return canonical_symbol(raw_sym)


def generate_alert_id(
    symbol: str,
    alert_type: str,
    *,
    session_date: Optional[date] = None,
    variant: Optional[str] = None,
) -> str:
    """
    Deterministic institutional alert ID generator.
    Guarantees consistent in-session deduplication across all market segments.

    Format: aa-{alert_type_slug}-{canonical_symbol}[-{variant}]-{YYYYMMDD}
    Example: aa-crypto-squeeze-btcusdt-20260926
             aa-gamma-blast-nifty-24500ce-20260926
             aa-orb-reliance-bull-20260926
    """
    clean_sym = canonical_alert_symbol(symbol).lower().replace(" ", "-")
    type_slug = alert_type.lower().replace("crypto_", "crypto-").replace("_", "-").strip("-")
    if not type_slug.startswith("aa-"):
        prefix = "aa"
    else:
        prefix = ""

    d = session_date or datetime.now(IST).date()
    date_str = d.strftime("%Y%m%d")

    parts = [p for p in (prefix, type_slug, clean_sym) if p]
    if variant:
        clean_var = str(variant).lower().strip().replace(" ", "-").replace(".", "p")
        clean_var = re.sub(r"[^a-zA-Z0-9-]", "", clean_var)
        if clean_var:
            parts.append(clean_var)
    parts.append(date_str)

    return "-".join(parts)


# ── Session Phase Slot ─────────────────────────────────────────────────────

_SLOT_BOUNDARIES = (
    (dtime(13, 15), "1315"),  # Power Hour + Closing (13:15 – 15:30 IST)
    (dtime(11, 30), "1130"),  # Midday Consolidation (11:30 – 13:14 IST)
)


def get_session_phase_slot(ref_dt: Optional[datetime] = None) -> str:
    """
    Maps the current (or given) IST datetime to a deterministic 24hr market phase slot.

    Used as the time-block variant in alert IDs so that structurally distinct setups
    in different session phases receive distinct IDs, enabling PM re-evaluation without
    violating Invariant #17 (no volatile minute/second timestamps).

    Slots (3 per trading day, 24hr IST notation):
        '0915'  — Opening + Morning     (09:15 – 11:29 IST)
        '1130'  — Midday Consolidation  (11:30 – 13:14 IST)
        '1315'  — Power Hour + Closing  (13:15 – 15:30 IST)

    Returns the slot label, e.g. '1315'.
    Invariant compliant: same minute always maps to the same label; no randomness.
    """
    now_ist = (ref_dt or datetime.now(IST)).astimezone(IST)
    t = now_ist.time()
    for boundary, label in _SLOT_BOUNDARIES:
        if t >= boundary:
            return label
    return "0915"


def validate_alert_id(alert_id: str) -> tuple[bool, str]:
    """
    Validates that an alert ID satisfies institutional determinism invariants.
    Returns (True, "OK") or (False, failure_reason).
    """
    if not alert_id or len(alert_id) < 8:
        return False, "Alert ID is empty or too short"

    if _VOLATILE_ID_PATTERN.search(alert_id):
        return (
            False,
            f"Alert ID '{alert_id}' contains banned minute-level timestamp or random UUID suffix. "
            f"Must use daily session date YYYYMMDD.",
        )

    return True, "OK"
