"""
market/nse_scraper.py
─────────────────────
NSE public API scraper — live options chain feed using modern NSE v3 endpoints.

Endpoints:
  - Contract info (active expiries & strikes): /api/option-chain-contract-info?symbol={sym}
  - Full Option Chain v3:                      /api/option-chain-v3?type={Indices|Equity}&symbol={sym}&expiry={exp}

Uses curl_cffi with browser TLS impersonation to reliably navigate Akamai Edge WAF.
Falls back to requests.Session if curl_cffi is unavailable.
Returns data in the institutional OptionsContract schema with real bids, asks, depth, and volume.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Optional

from brokers.base import OptionsContract
from engine.greeks_manager import LOT_SIZES

log = logging.getLogger(__name__)

_NSE_BASE = "https://www.nseindia.com"
_NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}

_INDEX_UNDERLYINGS = {
    "NIFTY",
    "BANKNIFTY",
    "FINNIFTY",
    "MIDCPNIFTY",
    "NIFTYNXT50",
}

# Session state with thread lock and TTL
_session = None
_session_created_at = 0.0
_SESSION_TTL = 300.0  # 5 minutes
_session_lock = threading.Lock()

# Short in-memory cache for raw responses to prevent duplicate bursts
_CACHE: dict[str, tuple[float, list[OptionsContract], Optional[float], list[str]]] = {}
_CACHE_TTL = 15.0  # 15s cache


def _is_index_underlying(underlying: str) -> bool:
    """Return True if underlying is an index."""
    clean = underlying.upper().replace("NSE:", "").replace("NFO:", "").strip()
    return clean in _INDEX_UNDERLYINGS


def _get_session():
    """Return an active session with valid NSE session cookies."""
    global _session, _session_created_at
    now = time.time()
    with _session_lock:
        if _session is not None and (now - _session_created_at) < _SESSION_TTL:
            return _session

        # Try curl_cffi for TLS impersonation first
        try:
            from curl_cffi import requests as c_requests

            sess = c_requests.Session(impersonate="chrome124")
            sess.headers.update(_NSE_HEADERS)
            # Warm up session with cookies from option-chain page
            r = sess.get(f"{_NSE_BASE}/option-chain", timeout=10)
            if r.status_code == 200:
                sess.headers.update(
                    {
                        "Referer": f"{_NSE_BASE}/option-chain",
                        "Accept": "application/json, text/plain, */*",
                    }
                )
                _session = sess
                _session_created_at = now
                return _session
        except Exception as e:
            log.debug(f"curl_cffi session init failed, trying requests: {e}")

        # Fallback to requests.Session
        import requests

        sess = requests.Session()
        sess.headers.update(_NSE_HEADERS)
        try:
            r = sess.get(f"{_NSE_BASE}/option-chain", timeout=10)
            if r.status_code == 200:
                sess.headers.update(
                    {
                        "Referer": f"{_NSE_BASE}/option-chain",
                        "Accept": "application/json, text/plain, */*",
                    }
                )
        except Exception:
            pass
        _session = sess
        _session_created_at = now
        return _session


def _nse_expiry_to_iso(nse_date: str) -> str:
    """
    Convert NSE expiry format "08-Sep-2026" or "08-09-2026" to ISO "2026-09-08".
    Returns original string on parse failure.
    """
    if not nse_date:
        return ""
    try:
        # Standard NSE text format: 08-Sep-2026
        return datetime.strptime(nse_date, "%d-%b-%Y").strftime("%Y-%m-%d")
    except Exception:
        pass
    try:
        # Alternative numeric format: 08-09-2026
        return datetime.strptime(nse_date, "%d-%m-%Y").strftime("%Y-%m-%d")
    except Exception:
        pass
    return nse_date


def _iso_to_nse_expiry(iso_date: str, available_expiries: list[str]) -> Optional[str]:
    """Find matching NSE date string from ISO date string."""
    clean_iso = iso_date.strip()
    for nse_exp in available_expiries:
        if _nse_expiry_to_iso(nse_exp) == clean_iso:
            return nse_exp
        if nse_exp.upper() == clean_iso.upper():
            return nse_exp
    return None


def nse_get_contract_info(underlying: str) -> dict:
    """
    Fetch active expiry dates and strike price range from NSE.
    Returns {"expiryDates": [...], "strikePrice": [...]}.
    """
    clean_sym = underlying.upper().replace("NSE:", "").replace("NFO:", "").strip()
    session = _get_session()
    url = f"{_NSE_BASE}/api/option-chain-contract-info?symbol={clean_sym}"
    try:
        resp = session.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        log.debug(f"nse_get_contract_info failed for {clean_sym}: {e}")
    return {}


def _parse_v3_chain(
    raw_data: dict,
    underlying: str,
    lot_size: int,
) -> list[OptionsContract]:
    """
    Parse NSE v3 JSON records into structured OptionsContract list.
    Extracts real bids, asks, quantities, volumes, and open interests.
    """
    contracts: list[OptionsContract] = []
    records = raw_data.get("records", {})
    rows = records.get("data", [])

    for row in rows:
        strike = float(row.get("strikePrice", 0) or 0)
        if strike <= 0:
            continue

        raw_exp = row.get("expiryDates") or ""
        iso_exp = _nse_expiry_to_iso(raw_exp)

        for opt_type in ("CE", "PE"):
            leg = row.get(opt_type)
            if not isinstance(leg, dict):
                continue

            last_price = float(leg.get("lastPrice", 0) or 0)
            oi = int(leg.get("openInterest", 0) or 0)
            oi_change = int(leg.get("changeinOpenInterest", 0) or 0)
            volume = int(leg.get("totalTradedVolume", 0) or 0)
            iv = float(leg.get("impliedVolatility", 0) or 0)

            # Extract real bid/ask quotes and book depth
            bid = float(leg.get("buyPrice1", 0) or 0) or None
            ask = float(leg.get("sellPrice1", 0) or 0) or None
            bid_qty = int(leg.get("buyQuantity1", 0) or 0)
            ask_qty = int(leg.get("sellQuantity1", 0) or 0)
            tot_buy_qty = int(leg.get("totalBuyQuantity", 0) or 0)
            tot_sell_qty = int(leg.get("totalSellQuantity", 0) or 0)

            pchange = float(leg.get("pChange", 0) or 0)
            pchange_oi = float(leg.get("pchangeinOpenInterest", 0) or 0)

            sym = f"{underlying.upper()}{int(strike)}{opt_type}"

            contracts.append(
                OptionsContract(
                    symbol=sym,
                    underlying=underlying.upper(),
                    strike=strike,
                    option_type=opt_type,
                    expiry=iso_exp or raw_exp,
                    last_price=last_price,
                    oi=oi,
                    oi_change=oi_change,
                    volume=volume,
                    iv=iv if iv > 0 else None,
                    bid=bid,
                    ask=ask,
                    bid_qty=bid_qty,
                    ask_qty=ask_qty,
                    total_buy_qty=tot_buy_qty,
                    total_sell_qty=tot_sell_qty,
                    pchange=pchange,
                    pchange_oi=pchange_oi,
                    lot_size=lot_size,
                    exchange="NFO",
                )
            )

    return sorted(contracts, key=lambda c: (c.strike, c.option_type))


def nse_fetch_full_snapshot(
    underlying: str,
    expiry: Optional[str] = None,
) -> tuple[list[OptionsContract], Optional[float], list[str]]:
    """
    Fetch full live options chain snapshot with live spot price and available expiries.

    Returns:
        (contracts, spot_price, expiries_iso_list)
    """
    clean_sym = underlying.upper().replace("NSE:", "").replace("NFO:", "").strip()
    cache_key = f"{clean_sym}:{expiry or 'nearest'}"
    now = time.time()

    if cache_key in _CACHE:
        cached_at, cached_chain, cached_spot, cached_exp = _CACHE[cache_key]
        if (now - cached_at) < _CACHE_TTL:
            return cached_chain, cached_spot, cached_exp

    try:
        # Step 1: Get active contract expiries
        contract_info = nse_get_contract_info(clean_sym)
        nse_expiries = contract_info.get("expiryDates", [])
        if not nse_expiries:
            return [], None, []

        iso_expiries = [_nse_expiry_to_iso(e) for e in nse_expiries]

        # Step 2: Resolve target expiry parameter
        selected_nse_exp = nse_expiries[0]
        if expiry:
            matched = _iso_to_nse_expiry(expiry, nse_expiries)
            if matched:
                selected_nse_exp = matched

        # Step 3: Fetch Option Chain v3
        is_idx = _is_index_underlying(clean_sym)
        endpoint_type = "Indices" if is_idx else "Equity"
        session = _get_session()

        url = (
            f"{_NSE_BASE}/api/option-chain-v3?"
            f"type={endpoint_type}&symbol={clean_sym}&expiry={selected_nse_exp}"
        )
        resp = session.get(url, timeout=12)
        if resp.status_code != 200:
            return [], None, iso_expiries

        raw_json = resp.json()
        records = raw_json.get("records", {})
        live_spot = records.get("underlyingValue")
        if live_spot is not None:
            try:
                live_spot = float(live_spot)
            except (ValueError, TypeError):
                live_spot = None

        lot_sz = LOT_SIZES.get(clean_sym, 75 if is_idx else 250)
        contracts = _parse_v3_chain(raw_json, clean_sym, lot_sz)

        if contracts:
            _CACHE[cache_key] = (now, contracts, live_spot, iso_expiries)

        return contracts, live_spot, iso_expiries

    except Exception as e:
        log.warning(f"Failed to fetch live NSE options chain for {clean_sym}: {e}")
        return [], None, []


def nse_get_options_chain(
    underlying: str,
    expiry: Optional[str] = None,
) -> list[OptionsContract]:
    """
    Fetch options chain from NSE public API v3.

    Args:
        underlying: Symbol e.g. "NIFTY", "BANKNIFTY", "RELIANCE"
        expiry:     ISO date "YYYY-MM-DD" or NSE format; None = nearest expiry

    Returns:
        List of OptionsContract sorted by strike then type.
    """
    contracts, _, _ = nse_fetch_full_snapshot(underlying, expiry)
    return contracts


def nse_get_expiries(underlying: str) -> list[str]:
    """
    Fetch all available active expiry dates in ISO 'YYYY-MM-DD' format.
    """
    contract_info = nse_get_contract_info(underlying)
    raw_exp = contract_info.get("expiryDates", [])
    if raw_exp:
        return [_nse_expiry_to_iso(e) for e in raw_exp]
    _, _, expiries = nse_fetch_full_snapshot(underlying)
    return expiries


def nse_available() -> bool:
    """Check if NSE option chain service is currently reachable."""
    try:
        session = _get_session()
        resp = session.get(f"{_NSE_BASE}/api/option-chain-contract-info?symbol=NIFTY", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False
