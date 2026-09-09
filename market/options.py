"""
market/options.py
─────────────────
Options chain and expiry utilities — broker-agnostic.

Fallback chain:
  1. Data broker (Fyers/Zerodha) — live, full Greeks
  2. NSE public API scraper    — free, ~15 min delayed, no key required
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from brokers.base import OptionsContract
from brokers.session import get_data_broker
from market.nse_scraper import nse_get_options_chain
from market.source_tracker import record_source, warn_fallback


import time

_CHAIN_CACHE: dict[str, tuple[float, list[OptionsContract]]] = {}
_CHAIN_CACHE_TTL = 180.0  # 3 minutes for valid chains, 60s for empty


def get_options_chain(
    underlying: str,
    expiry: Optional[str] = None,
) -> list[OptionsContract]:
    """
    Full options chain for an underlying index or stock.

    Fallback chain:
      1. Data broker (live, full Greeks)
      2. NSE public API scraper (delayed, basic Greeks)
      3. Empty list (silent — never raises)

    Args:
        underlying: e.g. "NIFTY", "BANKNIFTY", "RELIANCE"
        expiry:     "YYYY-MM-DD" — nearest expiry if None

    Returns:
        List of OptionsContract sorted by strike then type (CE/PE).
    """
    cache_key = f"{underlying.upper()}:{expiry or 'nearest'}"
    now = time.time()
    if cache_key in _CHAIN_CACHE:
        cached_at, cached_chain = _CHAIN_CACHE[cache_key]
        ttl = _CHAIN_CACHE_TTL if cached_chain else 60.0
        if (now - cached_at) < ttl:
            return cached_chain

    # Tier 1: data broker
    try:
        chain = get_data_broker().get_options_chain(underlying, expiry)
        record_source("options", "broker")
        if chain:
            _CHAIN_CACHE[cache_key] = (now, chain)
            return chain
    except Exception as e:
        warn_fallback("options", str(e), "nse_scraper")

    # Tier 2: NSE scraper
    chain = nse_get_options_chain(underlying, expiry)
    record_source("options", "nse_scraper" if chain else "none")
    _CHAIN_CACHE[cache_key] = (now, chain or [])
    return chain or []


def get_expiries(underlying: str) -> list[str]:
    """
    All available expiry dates for an underlying (sorted ascending).
    Returns dates as "YYYY-MM-DD" strings.
    """
    try:
        broker = get_data_broker()
        if hasattr(broker, "get_expiries"):
            exp = broker.get_expiries(underlying)
            if exp:
                return exp
    except Exception:
        pass

    try:
        from market.nse_scraper import nse_get_expiries

        exp = nse_get_expiries(underlying)
        if exp:
            return exp
    except Exception:
        pass

    chain = get_options_chain(underlying)
    dates = sorted({c.expiry for c in chain if c.expiry})
    return dates


def get_options_snapshot(
    underlying: str,
    expiry: Optional[str] = None,
) -> tuple[list[OptionsContract], Optional[float], list[str], dict[str, Any]]:
    """
    Unified options snapshot returning (contracts, live_spot_price, available_expiries, source_info).
    source_info conveys transparent provenance: provider, source, data_state, is_realtime, and as_of timestamps.
    """
    from datetime import datetime, timezone
    from brokers.session import get_data_broker, get_data_broker_key

    clean_u = underlying.replace("NSE:", "").replace("BSE:", "").upper().strip()
    is_bse = clean_u in ("SENSEX", "BANKEX")
    now_utc = datetime.now(timezone.utc).isoformat()
    now_ist = datetime.now().strftime("%I:%M:%S %p IST")

    # Tier 1: Primary Data Broker (m.Stock, Fyers, Shoonya, Zerodha)
    try:
        broker = get_data_broker()
        broker_name = get_data_broker_key() or getattr(broker, "name", "broker")
        chain = broker.get_options_chain(underlying, expiry)
        if chain:
            spot = getattr(broker, "get_ltp", lambda _: None)(underlying)
            expiries = sorted({c.expiry for c in chain if c.expiry})
            source_info = {
                "provider": broker_name,
                "source": "BROKER_REST",
                "data_state": "LIVE",
                "is_realtime": True,
                "as_of": now_utc,
                "as_of_display": now_ist,
                "source_label": f"{broker_name.upper()} Direct Real-Time Feed",
            }
            return chain, spot, expiries, source_info
    except Exception:
        pass

    # Tier 2: Upgraded NSE Scraper v3 (Delayed Fallback)
    try:
        from market.nse_scraper import nse_fetch_full_snapshot

        contracts, spot, expiries = nse_fetch_full_snapshot(underlying, expiry)
        if contracts:
            source_info = {
                "provider": "nse_scraper",
                "source": "SCRAPER_FALLBACK",
                "data_state": "DELAYED",
                "is_realtime": False,
                "as_of": now_utc,
                "as_of_display": now_ist,
                "source_label": "NSE Public Scraper (~15m Delayed Fallback)",
            }
            return contracts, spot, expiries, source_info
    except Exception:
        pass

    # Tier 3: Honest Disconnected / Broker Required
    source_info = {
        "provider": "none",
        "source": "UNAVAILABLE",
        "data_state": "BROKER_REQUIRED" if is_bse else "UNAVAILABLE",
        "is_realtime": False,
        "as_of": now_utc,
        "as_of_display": now_ist,
        "source_label": f"BSE {clean_u} Broker Required for BFO"
        if is_bse
        else "Data Feed Unavailable",
    }
    return [], None, [], source_info


def chain_to_dataframe(contracts: list[OptionsContract]) -> pd.DataFrame:
    """
    Convert options chain list to a pivot-style DataFrame
    matching the standard market display format:

        Strike | CE LTP | CE OI | CE IV | PE LTP | PE OI | PE IV
    """
    if not contracts:
        return pd.DataFrame()

    rows: dict[float, dict] = {}
    for c in contracts:
        strike = c.strike
        if strike not in rows:
            rows[strike] = {"strike": strike}
        prefix = c.option_type  # "CE" or "PE"
        rows[strike][f"{prefix}_ltp"] = c.last_price
        rows[strike][f"{prefix}_oi"] = c.oi
        rows[strike][f"{prefix}_oi_chg"] = c.oi_change
        rows[strike][f"{prefix}_volume"] = c.volume
        rows[strike][f"{prefix}_iv"] = c.iv or 0.0
        rows[strike][f"{prefix}_symbol"] = c.symbol

    df = pd.DataFrame(list(rows.values()))
    df = df.sort_values("strike").reset_index(drop=True)

    # Ensure all columns exist even if one side is missing
    for side in ("CE", "PE"):
        for col in ("ltp", "oi", "oi_chg", "volume", "iv"):
            full = f"{side}_{col}"
            if full not in df.columns:
                df[full] = 0.0

    col_order = [
        "strike",
        "CE_ltp",
        "CE_oi",
        "CE_oi_chg",
        "CE_volume",
        "CE_iv",
        "PE_ltp",
        "PE_oi",
        "PE_oi_chg",
        "PE_volume",
        "PE_iv",
    ]
    return df[[c for c in col_order if c in df.columns]]


def get_atm_strike(underlying: str, spot: float) -> float:
    """
    Return the at-the-money strike closest to spot price.
    """
    chain = get_options_chain(underlying)
    strikes = sorted({c.strike for c in chain})
    if not strikes:
        return round(spot / 50) * 50  # fallback
    return min(strikes, key=lambda s: abs(s - spot))


def get_pcr(underlying: str, expiry: Optional[str] = None) -> Optional[float]:
    """
    Put-Call Ratio by Open Interest for the given expiry.
    PCR > 1.2 → bearish sentiment; PCR < 0.8 → bullish.
    Returns None if no options contracts exist for this underlying.
    """
    chain = get_options_chain(underlying, expiry)
    if not chain:
        return None
    ce_oi = sum(c.oi for c in chain if c.option_type == "CE")
    pe_oi = sum(c.oi for c in chain if c.option_type == "PE")
    if ce_oi == 0 and pe_oi == 0:
        return None
    if ce_oi == 0:
        return 999.0
    return round(pe_oi / ce_oi, 3)


def get_max_pain(underlying: str, expiry: Optional[str] = None) -> Optional[float]:
    """
    Max pain strike — the strike where total options losses for buyers
    are maximised (i.e. where writers profit most).

    Calculated by summing ITM losses across all strikes for CE + PE.
    Returns None if no options contracts exist for this underlying.
    """
    chain = get_options_chain(underlying, expiry)
    if not chain:
        return None
    strikes = sorted({c.strike for c in chain})
    if not strikes:
        return None

    # Build quick lookup: strike → {CE: contract, PE: contract}
    lookup: dict[float, dict[str, OptionsContract]] = {}
    for c in chain:
        lookup.setdefault(c.strike, {})[c.option_type] = c

    pain: dict[float, float] = {}
    for test_strike in strikes:
        total_pain = 0.0
        for s, contracts in lookup.items():
            ce = contracts.get("CE")
            pe = contracts.get("PE")
            # CE holders lose if test_strike < s (their CE expires worthless)
            if ce and test_strike < s:
                total_pain += max(0, s - test_strike) * ce.oi
            # PE holders lose if test_strike > s
            if pe and test_strike > s:
                total_pain += max(0, test_strike - s) * pe.oi
        pain[test_strike] = total_pain

    return min(pain, key=pain.get)  # type: ignore[arg-type]
