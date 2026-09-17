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


import threading
import time

_CHAIN_CACHE: dict[str, tuple[float, list[OptionsContract]]] = {}
_CHAIN_CACHE_TTL_DEFAULT = 180.0  # Off-market hours fallback
_CHAIN_CACHE_TTL_LIVE = 15.0     # 15s during live market hours for real-time gamma/OI shifts
_CHAIN_CACHE_TTL_SCRAPER = 30.0  # 30s for scraper fallback

def get_chain_cache_ttl(is_broker: bool = True) -> float:
    """Returns dynamic cache TTL: 15s live broker / 30s scraper during market hours, 180s when closed."""
    try:
        from market.calendar import is_market_open
        if is_market_open("NFO") or is_market_open("NSE"):
            return _CHAIN_CACHE_TTL_LIVE if is_broker else _CHAIN_CACHE_TTL_SCRAPER
    except Exception:
        pass
    return _CHAIN_CACHE_TTL_DEFAULT

_SNAPSHOT_CACHE: dict[str, tuple[float, tuple[list[OptionsContract], Optional[float], list[str], dict[str, Any]]]] = {}
_SNAPSHOT_LOCK = threading.Lock()
_SNAPSHOT_TTL = 3.0  # 3.0-second coalescing cache

_STRIKE_BASELINE_OI: dict[str, int] = {}
_BASELINE_DATE: Optional[str] = None
_BASELINE_LOCK = threading.Lock()


def enrich_options_chain_deltas(
    chain: list[OptionsContract],
    underlying: str,
    expiry: Optional[str] = None,
) -> list[OptionsContract]:
    """
    Enriches option contracts with real-time Open Interest changes (ΔOI) and %ΔOI.
    If broker returns 0 oi_change (e.g. m.Stock), this resolves:
      1. Cross-enrichment from NSE v3 public option chain scraper (changeinOpenInterest).
      2. Persistent session opening baseline delta: ΔOI = current_oi - baseline_oi.
    """
    if not chain:
        return chain

    clean_und = (
        underlying.upper()
        .replace("NSE:", "")
        .replace("NFO:", "")
        .replace("MCX:", "")
        .replace("CDS:", "")
        .strip()
    )
    from datetime import date

    today_str = date.today().isoformat()

    with _BASELINE_LOCK:
        global _BASELINE_DATE
        if _BASELINE_DATE != today_str:
            _STRIKE_BASELINE_OI.clear()
            _BASELINE_DATE = today_str

    # 1. If broker returned 0 oi_change for all strikes, cross-enrich from NSE public API scraper
    needs_enrichment = all(getattr(c, "oi_change", 0) == 0 for c in chain)

    if needs_enrichment and clean_und not in (
        "GOLD", "GOLDM", "SILVER", "SILVERM", "CRUDEOIL", "CRUDEOILM", "NATURALGAS", "COPPER", "ZINC", "ALUMINIUM"
    ):
        try:
            from market.nse_scraper import nse_get_options_chain

            nse_chain = nse_get_options_chain(clean_und, expiry)
            if nse_chain:
                nse_map = {(int(c.strike), c.option_type): c for c in nse_chain}
                for c in chain:
                    k = (int(c.strike), c.option_type)
                    if k in nse_map:
                        nse_c = nse_map[k]
                        if nse_c.oi_change != 0:
                            c.oi_change = nse_c.oi_change
                            if hasattr(nse_c, "pchange_oi") and nse_c.pchange_oi:
                                c.pchange_oi = nse_c.pchange_oi
                        if not getattr(c, "iv", None) and getattr(nse_c, "iv", None):
                            c.iv = nse_c.iv
        except Exception:
            pass

    # 2. Baseline tracking fallback: calculate delta against session opening baseline
    with _BASELINE_LOCK:
        for c in chain:
            b_key = f"{clean_und}_{c.expiry}_{int(c.strike)}_{c.option_type}"
            c_oi = int(getattr(c, "oi", 0) or 0)
            if c_oi > 0:
                if b_key not in _STRIKE_BASELINE_OI:
                    _STRIKE_BASELINE_OI[b_key] = c_oi
                elif getattr(c, "oi_change", 0) == 0:
                    delta = c_oi - _STRIKE_BASELINE_OI[b_key]
                    c.oi_change = delta
                    base = _STRIKE_BASELINE_OI[b_key]
                    if base > 0:
                        c.pchange_oi = round((delta / base) * 100.0, 2)

    return chain


def get_options_chain(
    underlying: str,
    expiry: Optional[str] = None,
) -> list[OptionsContract]:
    """
    Full options chain for an underlying index, stock, or MCX commodity.

    Fallback chain:
      1. Data broker (live, full Greeks) — supports NFO, MCX, CDS
      2. For MCX commodities: Black-76 theoretical options chain using live continuous futures quote
      3. For NSE equities/indices: NSE public API scraper (delayed, basic Greeks)
      4. Empty list (silent — never raises)

    Args:
        underlying: e.g. "NIFTY", "BANKNIFTY", "RELIANCE", "CRUDEOIL", "GOLD"
        expiry:     "YYYY-MM-DD" — nearest expiry if None

    Returns:
        List of OptionsContract sorted by strike then type (CE/PE).
    """
    from market.instruments import COMMODITY_SYMBOLS

    clean_sym = (
        underlying.upper()
        .replace("MCX:", "")
        .replace("CDS:", "")
        .replace("NFO:", "")
        .replace("NSE:", "")
        .strip()
    )
    is_commodity = clean_sym in COMMODITY_SYMBOLS or underlying.upper().startswith("MCX:")

    cache_key = f"{underlying.upper()}:{expiry or 'nearest'}"
    now = time.time()
    if cache_key in _CHAIN_CACHE:
        cached_at, cached_chain = _CHAIN_CACHE[cache_key]
        ttl = get_chain_cache_ttl(is_broker=True) if cached_chain else 15.0
        if (now - cached_at) < ttl:
            return cached_chain

    # Tier 1: data broker (live broker feed)
    try:
        chain = get_data_broker().get_options_chain(underlying, expiry)
        record_source("options", "broker")
        if chain and any(float(getattr(c, "last_price", 0.0) or 0.0) > 0 for c in chain):
            chain = enrich_options_chain_deltas(chain, underlying, expiry)
            _CHAIN_CACHE[cache_key] = (now, chain)
            return chain
    except Exception as e:
        warn_fallback("options", str(e), "commodity_black76" if is_commodity else "nse_scraper")

    # Tier 2: For MCX commodities, build Black-76 theoretical option chain from live futures quote
    if is_commodity:
        try:
            from market.quotes import get_ltp
            from engine.greeks_manager import build_commodity_option_chain_synthetic

            fut_ltp = get_ltp(f"MCX:{clean_sym}") or get_ltp(clean_sym) or 0.0
            if fut_ltp > 0:
                chain = build_commodity_option_chain_synthetic(
                    clean_sym, futures_price=fut_ltp, expiry_date=expiry
                )
                if chain:
                    record_source("options", "black_76_synthetic")
                    _CHAIN_CACHE[cache_key] = (now, chain)
                    return chain
        except Exception as e:
            warn_fallback("options", str(e), "none")

        _CHAIN_CACHE[cache_key] = (now, [])
        return []

    # Tier 3: NSE public scraper for equities and indices
    chain = nse_get_options_chain(underlying, expiry)
    if chain:
        chain = enrich_options_chain_deltas(chain, underlying, expiry)
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
    from market.calendar import is_market_open

    clean_u = underlying.replace("NSE:", "").replace("BSE:", "").upper().strip()
    is_bse = clean_u in ("SENSEX", "BANKEX")
    market_open = is_market_open("BSE" if is_bse else "NSE")
    now_utc = datetime.now(timezone.utc).isoformat()
    now_ist = datetime.now().strftime("%I:%M:%S %p IST")

    cache_key = f"{clean_u}:{expiry or 'nearest'}"
    now_ts = time.time()
    with _SNAPSHOT_LOCK:
        if cache_key in _SNAPSHOT_CACHE:
            cached_at, cached_res = _SNAPSHOT_CACHE[cache_key]
            if (now_ts - cached_at) < _SNAPSHOT_TTL:
                return cached_res

    # Tier 1: Primary Data Broker (m.Stock, Fyers, Shoonya, Zerodha)
    try:
        broker = get_data_broker()
        broker_name = get_data_broker_key() or getattr(broker, "name", "broker")
        if broker:
            chain = broker.get_options_chain(underlying, expiry)
            if chain and any(float(getattr(c, "last_price", 0.0) or 0.0) > 0 for c in chain):
                spot = 0.0
                try:
                    spot_fn = getattr(broker, "get_ltp", None)
                    if callable(spot_fn):
                        spot = float(spot_fn(underlying) or 0.0)
                except Exception:
                    pass
                if not spot or spot <= 0:
                    try:
                        from market.quotes import get_ltp as _mkt_ltp
                        spot = float(_mkt_ltp(underlying) or 0.0)
                    except Exception:
                        spot = 0.0
                expiries = getattr(broker, "get_expiries", lambda _: [])(underlying)
                if not expiries:
                    expiries = sorted({c.expiry for c in chain if c.expiry})
                source_info = {
                    "provider": broker_name,
                    "source": "BROKER_REST",
                    "data_state": "LIVE" if market_open else "OFF_MARKET",
                    "is_realtime": bool(market_open),
                    "is_market_open": market_open,
                    "as_of": now_utc,
                    "as_of_display": now_ist,
                    "source_label": (
                        f"{broker_name.upper()} Direct Real-Time Feed"
                        if market_open
                        else f"{broker_name.upper()} Settled Previous EOD (Market Closed)"
                    ),
                }
                res = (chain, spot, expiries, source_info)
                with _SNAPSHOT_LOCK:
                    _SNAPSHOT_CACHE[cache_key] = (now_ts, res)
                return res
    except Exception as exc:
        import logging
        logging.warning("[market.options] Tier 1 primary broker options fetch failed: %s", exc)

    # Tier 2: Upgraded NSE Scraper v3 (Delayed Fallback)
    try:
        from market.nse_scraper import nse_fetch_full_snapshot

        contracts, spot, expiries = nse_fetch_full_snapshot(underlying, expiry)
        if contracts:
            source_info = {
                "provider": "nse_scraper",
                "source": "SCRAPER_FALLBACK",
                "data_state": "DELAYED" if market_open else "OFF_MARKET",
                "is_realtime": False,
                "is_market_open": market_open,
                "as_of": now_utc,
                "as_of_display": now_ist,
                "source_label": (
                    "NSE Public Scraper (~15m Delayed Fallback)"
                    if market_open
                    else "NSE Public Settled Previous EOD (Market Closed)"
                ),
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
        "is_market_open": market_open,
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


# ── Human-Readable Option Formatting ──────────────────────────


def parse_option_symbol(symbol: str) -> dict[str, Any]:
    """
    Parses Indian exchange option symbols (MCX, NFO, BFO, CDS) into components.
    e.g. 'MCX:CRUDEOIL26SEP6500CE' ->
         {'exchange': 'MCX', 'underlying': 'CRUDEOIL', 'expiry_tag': '26SEP', 'strike': 6500.0, 'option_type': 'CE'}
    """
    import re

    clean = symbol.strip()
    exchange = ""
    if ":" in clean:
        parts = clean.split(":", 1)
        exchange = parts[0].upper()
        clean = parts[1]

    # Pattern 1: Underlying + Expiry(2 digits day/year + 3 letters month or digits) + Strike + (CE|PE)
    # e.g., CRUDEOIL26SEP6500CE or GOLD26OCT75000PE or NIFTY24DEC24000CE
    m = re.match(
        r"^([A-Z]+?)(\d{2}[A-Z]{3}|\d{4,8})?(\d+(?:\.\d+)?)(CE|PE)$",
        clean,
        re.IGNORECASE,
    )
    if m:
        underlying = m.group(1).upper()
        expiry_tag = m.group(2) or ""
        strike_val = float(m.group(3))
        opt_type = m.group(4).upper()
        return {
            "exchange": exchange,
            "underlying": underlying,
            "expiry_tag": expiry_tag,
            "strike": strike_val,
            "option_type": opt_type,
            "raw_symbol": symbol,
        }

    # Fallback: simple extraction of trailing CE/PE
    m2 = re.match(r"^(.*?)(?:(\d+(?:\.\d+)?))(CE|PE)$", clean, re.IGNORECASE)
    if m2:
        prefix = m2.group(1)
        strike_val = float(m2.group(2))
        opt_type = m2.group(3).upper()
        return {
            "exchange": exchange,
            "underlying": prefix.upper(),
            "expiry_tag": "",
            "strike": strike_val,
            "option_type": opt_type,
            "raw_symbol": symbol,
        }

    return {
        "exchange": exchange,
        "underlying": clean,
        "expiry_tag": "",
        "strike": 0.0,
        "option_type": "",
        "raw_symbol": symbol,
    }


def format_readable_option_symbol(
    symbol: str,
    strike: Optional[float] = None,
    option_type: Optional[str] = None,
    expiry: Optional[str] = None,
) -> str:
    """
    Formats raw exchange option tokens into clean, institutional, human-readable labels.
    Examples:
      'MCX:CRUDEOIL26SEP6500CE' -> 'CRUDEOIL 6500 CE (26 Sep)'
      'NATURALGAS26SEP240PE'    -> 'NATURALGAS 240 PE (26 Sep)'
      'GOLD26OCT75000CE'        -> 'GOLD 75000 CE (26 Oct)'
      'NIFTY24DEC24000CE'       -> 'NIFTY 24000 CE (24 Dec)'
    """
    import re
    from datetime import datetime

    if not symbol:
        return ""

    parsed = parse_option_symbol(symbol)
    underlying = parsed.get("underlying") or symbol.replace("MCX:", "").replace("NFO:", "").strip()
    s_val = strike if (strike is not None and strike > 0) else parsed.get("strike", 0.0)
    o_type = option_type if option_type else parsed.get("option_type", "")

    # Format strike nicely (int if whole number, float otherwise)
    if s_val and s_val > 0:
        strike_str = f"{int(s_val)}" if s_val == int(s_val) else f"{s_val:g}"
    else:
        strike_str = ""

    # Format expiry cleanly
    exp_display = ""
    if expiry:
        try:
            d = datetime.strptime(expiry, "%Y-%m-%d")
            exp_display = d.strftime("%d %b")
        except Exception:
            exp_display = str(expiry)
    elif parsed.get("expiry_tag"):
        tag = parsed["expiry_tag"]
        # If tag is like '26SEP' -> '26 Sep'
        m_exp = re.match(r"^(\d{2})([A-Z]{3})$", tag, re.IGNORECASE)
        if m_exp:
            exp_display = f"{m_exp.group(1)} {m_exp.group(2).capitalize()}"
        else:
            exp_display = tag

    parts = [underlying]
    if strike_str:
        parts.append(strike_str)
    if o_type:
        parts.append(o_type)
    base = " ".join(parts).strip()

    if exp_display:
        return f"{base} ({exp_display})"
    return base
