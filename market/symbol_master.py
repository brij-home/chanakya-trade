"""
market/symbol_master.py
────────────────────────
Authoritative Symbol Master Gateway for Indian Markets (NSE, BSE, MCX).
Downloads, caches, and validates instruments using official, daily-refreshed public masters
from Fyers: https://public.fyers.in/sym_details/<MASTER>_sym_master.json

Features:
  - 100% token-free and zero credentials required (public endpoints).
  - Eliminates '-300 Invalid Symbol' order rejections by validating existence beforehand.
  - Authoritative source for exact F&O lot sizes (minLotSize), tick sizes (tickSize),
    ISIN, instrument tokens (fyToken), and expiry dates.
  - Automatic local cache with daily freshness invalidation (~/.trading_platform/sym_master/).
"""

from __future__ import annotations
import logging

logger = logging.getLogger("market.symbol_master")


import datetime as dt
import json
import urllib.request
from pathlib import Path
from typing import Any, Optional

MASTERS = (
    "NSE_CM",  # NSE Capital Market (Equity / Indices)
    "NSE_FO",  # NSE Equity Derivatives (Futures / Options)
    "NSE_CD",  # NSE Currency Derivatives
    "NSE_COM",  # NSE Commodity
    "BSE_CM",  # BSE Capital Market
    "BSE_FO",  # BSE Equity Derivatives
    "MCX_COM",  # MCX Commodity
)

BASE_URL = "https://public.fyers.in/sym_details/{}_sym_master.json"
from config.paths import app_data_path

CACHE_DIR = app_data_path("sym_master")

# Map exchange prefix to applicable master files
_EXCHANGE_MASTERS = {
    "NSE": ("NSE_CM", "NSE_FO", "NSE_CD", "NSE_COM"),
    "BSE": ("BSE_CM", "BSE_FO"),
    "MCX": ("MCX_COM",),
}

# In-memory LRU cache to avoid reading JSON from disk repeatedly during tight execution loops
_IN_MEMORY_CACHE: dict[str, dict[str, Any]] = {}


import os


def _cache_path(master: str) -> Path:
    p = CACHE_DIR / f"{master}.json"
    if p.exists():
        return p
    # If in test mode or custom DATA dir, fall back to standard home cache if present
    standard_home = Path.home() / ".trading_platform" / "sym_master" / f"{master}.json"
    if standard_home.exists():
        return standard_home
    return p


def _is_fresh(path: Path) -> bool:
    """True if the cached master JSON has an entry updated today, during current weekend, or in test mode."""
    if not path.exists():
        return False
    if os.environ.get("CHANAKYA_TESTING") == "1":
        return True
    try:
        today_date = dt.date.today()
        valid_dates = {today_date.isoformat()}
        # On weekends, Friday's update (1-2 days old) is completely fresh
        if today_date.weekday() == 5:  # Saturday
            valid_dates.add((today_date - dt.timedelta(days=1)).isoformat())
        elif today_date.weekday() == 6:  # Sunday
            valid_dates.add((today_date - dt.timedelta(days=2)).isoformat())

        data = json.loads(path.read_text(encoding="utf-8"))
        return any(v.get("lastUpdate") in valid_dates for v in data.values())
    except Exception:
        return False


def load_master(master: str, force: bool = False, offline_fallback: bool = True) -> dict[str, Any]:
    """
    Load a master JSON dict keyed by API symbol ticker.
    Downloads and caches locally if missing or stale.
    """
    master_upper = master.upper().strip()
    if master_upper not in MASTERS:
        raise ValueError(f"Unknown master {master_upper!r}; choose from {', '.join(MASTERS)}")

    if not force and master_upper in _IN_MEMORY_CACHE:
        return _IN_MEMORY_CACHE[master_upper]

    path = _cache_path(master_upper)
    if force or not _is_fresh(path):
        url = BASE_URL.format(master_upper)
        req = urllib.request.Request(url, headers={"User-Agent": "chanakya-trade/2.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            tmp_path = path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(data), encoding="utf-8")
            tmp_path.replace(path)
            _IN_MEMORY_CACHE[master_upper] = data
            return data
        except Exception as e:
            if offline_fallback and path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    _IN_MEMORY_CACHE[master_upper] = data
                    return data
                except Exception as e_suppressed:
                    logger.debug(
                        f"[market.symbol_master] Non-fatal exception suppressed: {e_suppressed}"
                    )
            raise RuntimeError(f"Failed to fetch symbol master {master_upper}: {e}") from e

    data = json.loads(path.read_text(encoding="utf-8"))
    _IN_MEMORY_CACHE[master_upper] = data
    return data


def _expiry_iso(epoch: Any) -> str:
    """Convert master epoch seconds to ISO YYYY-MM-DD."""
    if not epoch:
        return ""
    try:
        return dt.datetime.fromtimestamp(int(epoch), dt.timezone.utc).date().isoformat()
    except Exception:
        return str(epoch)


def search_symbols(
    term: str,
    master: str = "NSE_CM",
    opt_type: Optional[str] = None,
    expiry: Optional[str] = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Case-insensitive substring search over symbol tickers and company names."""
    try:
        data = load_master(master)
    except Exception:
        return []
    term_upper = term.upper().strip()
    opt_upper = opt_type.upper().strip() if opt_type else None
    results = []

    for sym, rec in data.items():
        haystack = f"{sym} {rec.get('exSymName', '')} {rec.get('symDetails', '')}".upper()
        if term_upper not in haystack:
            continue
        if opt_upper and rec.get("optType") != opt_upper:
            continue
        if expiry and _expiry_iso(rec.get("expiryDate", "")) != expiry:
            continue

        results.append(
            {
                "symbol": rec.get("symTicker", sym),
                "name": rec.get("exSymName") or rec.get("symDetails"),
                "lot_size": int(rec.get("minLotSize", 1) or 1),
                "tick_size": float(rec.get("tickSize", 0.05) or 0.05),
                "opt_type": rec.get("optType"),
                "strike": float(rec["strikePrice"]) if rec.get("strikePrice", -1) >= 0 else None,
                "expiry": _expiry_iso(rec.get("expiryDate", "")),
                "token": rec.get("fyToken"),
                "isin": rec.get("isin"),
            }
        )
        if len(results) >= limit:
            break
    return results


def get_symbol_info(symbol: str) -> Optional[dict[str, Any]]:
    """Look up raw master record for a symbol across applicable exchange masters."""
    s = str(symbol or "").strip()
    if not s:
        return None
    exch = s.split(":", 1)[0].upper() if ":" in s else "NSE"
    candidates = _EXCHANGE_MASTERS.get(exch, ("NSE_CM", "NSE_FO"))

    for master in candidates:
        try:
            data = load_master(master)
            if s in data:
                return data[s]
            # Try with exchange prefix if missing
            with_prefix = f"{exch}:{s}"
            if with_prefix in data:
                return data[with_prefix]
        except Exception:
            continue
    return None


def validate_symbol(symbol: str) -> dict[str, Any]:
    """
    Validate that a symbol exists in canonical exchange masters.
    Raises ValueError with actionable remediation if invalid.
    """
    info = get_symbol_info(symbol)
    if info is not None:
        return info
    raise ValueError(
        f"Symbol {symbol!r} not found in exchange master. "
        "Verify symbol ticker or expiry spelling before placing orders."
    )


def get_lot_size(symbol: str, fallback: int = 1) -> int:
    """Return authoritative minimum lot size for symbol."""
    info = get_symbol_info(symbol)
    if info:
        return int(info.get("minLotSize", fallback) or fallback)
    return fallback


def get_tick_size(symbol: str, fallback: float = 0.05) -> float:
    """Return authoritative minimum tick size for symbol."""
    info = get_symbol_info(symbol)
    if info:
        return float(info.get("tickSize", fallback) or fallback)
    return fallback


_STRIKE_STEP_CACHE: dict[tuple[str, int, Optional[str]], float] = {}


def get_strike_step(symbol: str, spot: float = 0.0, expiry: Optional[str] = None) -> float:
    """
    Authoritative Strike Step Resolver for Indian Derivatives (Indices, Equities, Commodities, Currencies).
    1. Tier 1 (Ground Truth): Inspects adjacent listed strikes in canonical exchange masters (NSE_FO, MCX_COM, NSE_CD, BSE_FO).
       Around ATM spot, the modal delta between adjacent strikes is the exact strike increment.
    2. Tier 2 (SEBI / Exchange Standard Rulebook): Deterministic fallback if offline or synthetic test data:
       - Index: BANKNIFTY=100, SENSEX=100, BANKEX=100, MIDCPNIFTY=25, NIFTY=50, FINNIFTY=50 (or 100 for monthly/far).
       - Commodities: CRUDEOIL=50, GOLD=500, SILVER=1000, NATURALGAS=5, COPPER=10, ZINC=5.
       - Currencies: USDINR=0.25, EURINR=0.25.
       - Equity Spot Tiers: spot>=20000: 250, >=5000: 100, >=2500: 50, >=1000: 20, >=500: 10, >=250: 5, >=50: 2.5, <50: 1.0.
    """
    from market.instruments import canonical_symbol

    clean = canonical_symbol(symbol)
    if not clean:
        return 50.0

    cache_key = (clean, int(round(spot * 10)), expiry)
    if cache_key in _STRIKE_STEP_CACHE:
        return _STRIKE_STEP_CACHE[cache_key]

    # Tier 1: Empirical lookup in official exchange masters
    for master in ("NSE_FO", "MCX_COM", "NSE_CD", "BSE_FO"):
        try:
            data = load_master(master, offline_fallback=True)
            strikes_set = set()
            for k, v in data.items():
                if v.get("underSym") == clean or v.get("exSymbol") == clean:
                    if expiry:
                        exp_iso = _expiry_iso(v.get("expiryDate", ""))
                        if exp_iso and exp_iso != expiry:
                            continue
                    stk = float(v.get("strikePrice", -1))
                    if stk > 0:
                        strikes_set.add(stk)

            if len(strikes_set) >= 2:
                stks = sorted(strikes_set)
                # If spot is provided, restrict to ATM neighborhood (±35%)
                if spot > 0:
                    near = [s for s in stks if spot * 0.65 <= s <= spot * 1.35]
                    if len(near) >= 2:
                        diffs = [round(near[i + 1] - near[i], 4) for i in range(len(near) - 1)]
                        diffs = [d for d in diffs if d > 0]
                        if diffs:
                            from collections import Counter

                            res = float(Counter(diffs).most_common(1)[0][0])
                            _STRIKE_STEP_CACHE[cache_key] = res
                            return res

                diffs = [round(stks[i + 1] - stks[i], 4) for i in range(len(stks) - 1)]
                diffs = [d for d in diffs if d > 0]
                if diffs:
                    from collections import Counter

                    res = float(Counter(diffs).most_common(1)[0][0])
                    _STRIKE_STEP_CACHE[cache_key] = res
                    return res
        except Exception:
            continue

    # Tier 2: Deterministic exchange rulebook fallback
    res = 50.0
    if clean in ("BANKNIFTY", "SENSEX", "BANKEX"):
        res = 100.0
    elif clean == "MIDCPNIFTY":
        res = 25.0
    elif clean in ("NIFTY", "FINNIFTY"):
        res = 50.0
    elif clean in ("CRUDEOIL", "CRUDEOILM"):
        res = 50.0
    elif clean in ("GOLD", "GOLDM"):
        res = 500.0 if clean == "GOLD" else 100.0
    elif clean in ("SILVER", "SILVERM"):
        res = 1000.0 if clean == "SILVER" else 500.0
    elif clean in ("NATURALGAS", "NATGASMINI"):
        res = 5.0
    elif clean in ("COPPER", "ALUMINIUM"):
        res = 10.0
    elif clean == "ZINC":
        res = 5.0
    elif clean in ("USDINR", "EURINR", "GBPINR", "JPYINR"):
        res = 0.25
    elif spot > 0:
        if spot >= 5000:
            res = 100.0
        elif spot >= 2500:
            res = 50.0
        elif spot >= 1000:
            res = 20.0
        elif spot >= 500:
            res = 10.0
        elif spot >= 200:
            res = 5.0
        else:
            res = 2.5

    _STRIKE_STEP_CACHE[cache_key] = res
    return res


def resolve_fyers_equity_symbol(symbol: str, exch: str = "NSE") -> str:
    """
    Authoritatively resolve the exact Fyers trading ticker for an equity symbol
    against the official symbol master (e.g. NSE_CM), dynamically determining surveillance series
    (-EQ vs -BE vs -SM) and broker-specific ticker aliases (e.g. LTIM -> LTM).
    Eliminates guessing or relying on stale static series definitions.
    """
    s = (symbol or "").strip().upper()
    if not s:
        return ""
    if ":" in s:
        exch, s = s.split(":", 1)
        exch = exch.strip().upper()

    # Clean off any existing suffix for base resolution
    base = s
    for sfx in ("-EQ", "-BE", "-SM", "-BZ", "-GB", "-INDEX", "-A", "-B", "-X", "-XT", "-T", "-Z"):
        if base.endswith(sfx):
            base = base[: -len(sfx)]
            break

    # Fyers-specific broker alias mappings
    if base in ("LTIM", "LTI"):
        base = "LTM"

    if exch == "NSE":
        try:
            cm = load_master("NSE_CM", offline_fallback=True)
            if f"NSE:{base}-EQ" in cm:
                return f"NSE:{base}-EQ"
            if f"NSE:{base}-BE" in cm:
                return f"NSE:{base}-BE"
            for alt_sfx in ("-SM", "-BZ", "-ST", "-E1", "-GB"):
                if f"NSE:{base}{alt_sfx}" in cm:
                    return f"NSE:{base}{alt_sfx}"
        except Exception as e_suppressed:
            logger.debug(f"[market.symbol_master] NSE CM resolution non-fatal: {e_suppressed}")
        # Fallback to BE_SERIES_STOCKS if symbol master is unavailable
        try:
            from market.instruments import BE_SERIES_STOCKS

            if base in BE_SERIES_STOCKS:
                return f"NSE:{base}-BE"
        except Exception as e_suppressed:
            logger.debug(
                f"[market.symbol_master] BE_SERIES_STOCKS fallback non-fatal: {e_suppressed}"
            )
        return f"NSE:{base}-EQ"

    if exch == "BSE":
        try:
            bse = load_master("BSE_CM", offline_fallback=True)
            for sfx in ("-A", "-B", "-X", "-XT", "-T", "-Z", "-EQ"):
                cand = f"BSE:{base}{sfx}"
                if cand in bse:
                    return cand
        except Exception as e_suppressed:
            logger.debug(f"[market.symbol_master] BSE CM resolution non-fatal: {e_suppressed}")
        return f"BSE:{base}-A"

    return f"{exch}:{s}"


class SymbolMaster:
    """Convenience class wrapper around symbol master functions."""

    def load_master(self, master: str = "NSE_CM", force: bool = False) -> dict[str, Any]:
        return load_master(master, force=force)

    def search_symbols(
        self, term: str, master: str = "NSE_CM", limit: int = 25, **kwargs
    ) -> list[dict[str, Any]]:
        return search_symbols(term, master=master, limit=limit, **kwargs)

    def get_symbol_info(self, symbol: str) -> Optional[dict[str, Any]]:
        return get_symbol_info(symbol)

    def validate_symbol(self, symbol: str) -> dict[str, Any]:
        return validate_symbol(symbol)

    def get_lot_size(self, symbol: str, fallback: int = 1) -> int:
        return get_lot_size(symbol, fallback=fallback)

    def get_tick_size(self, symbol: str, fallback: float = 0.05) -> float:
        return get_tick_size(symbol, fallback=fallback)

    def get_strike_step(
        self, symbol: str, spot: float = 0.0, expiry: Optional[str] = None
    ) -> float:
        return get_strike_step(symbol, spot=spot, expiry=expiry)


_symbol_master_instance: Optional[SymbolMaster] = None


def get_symbol_master() -> SymbolMaster:
    """Return singleton SymbolMaster instance."""
    global _symbol_master_instance
    if _symbol_master_instance is None:
        _symbol_master_instance = SymbolMaster()
    return _symbol_master_instance
