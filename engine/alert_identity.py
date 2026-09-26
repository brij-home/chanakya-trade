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
from datetime import date, datetime
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


def canonical_alert_symbol(raw_sym: str) -> str:
    """
    Normalizes any asset symbol into its canonical clean uppercase identifier.
    Strips broker and exchange routing prefixes across all supported market venues.
    """
    if not raw_sym:
        return ""
    s = str(raw_sym).strip().upper()
    for pfx in _KNOWN_PREFIXES:
        if s.startswith(pfx):
            s = s[len(pfx) :]
            break
    return s.strip()


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
    type_slug = (
        alert_type.lower()
        .replace("crypto_", "crypto-")
        .replace("_", "-")
        .strip("-")
    )
    if not type_slug.startswith("aa-"):
        prefix = "aa"
    else:
        prefix = ""

    d = session_date or datetime.now(IST).date()
    date_str = d.strftime("%Y%m%d")

    parts = [p for p in (prefix, type_slug, clean_sym) if p]
    if variant:
        clean_var = re.sub(r"[^a-zA-Z0-9-]", "", str(variant).lower().strip().replace(" ", "-"))
        if clean_var:
            parts.append(clean_var)
    parts.append(date_str)

    return "-".join(parts)


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
