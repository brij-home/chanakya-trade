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

import datetime as dt
import json
import os
import urllib.request
from pathlib import Path
from typing import Any, Optional

MASTERS = (
    "NSE_CM",   # NSE Capital Market (Equity / Indices)
    "NSE_FO",   # NSE Equity Derivatives (Futures / Options)
    "NSE_CD",   # NSE Currency Derivatives
    "NSE_COM",  # NSE Commodity
    "BSE_CM",   # BSE Capital Market
    "BSE_FO",   # BSE Equity Derivatives
    "MCX_COM",  # MCX Commodity
)

BASE_URL = "https://public.fyers.in/sym_details/{}_sym_master.json"
CACHE_DIR = Path.home() / ".trading_platform" / "sym_master"

# Map exchange prefix to applicable master files
_EXCHANGE_MASTERS = {
    "NSE": ("NSE_CM", "NSE_FO", "NSE_CD", "NSE_COM"),
    "BSE": ("BSE_CM", "BSE_FO"),
    "MCX": ("MCX_COM",),
}

# In-memory LRU cache to avoid reading JSON from disk repeatedly during tight execution loops
_IN_MEMORY_CACHE: dict[str, dict[str, Any]] = {}


def _cache_path(master: str) -> Path:
    return CACHE_DIR / f"{master}.json"


def _is_fresh(path: Path) -> bool:
    """True if the cached master JSON has an entry updated today."""
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        today = dt.date.today().isoformat()
        return any(v.get("lastUpdate") == today for v in data.values())
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
                except Exception:
                    pass
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


class SymbolMaster:
    """Convenience class wrapper around symbol master functions."""

    def load_master(self, master: str = "NSE_CM", force: bool = False) -> dict[str, Any]:
        return load_master(master, force=force)

    def search_symbols(self, term: str, master: str = "NSE_CM", limit: int = 25, **kwargs) -> list[dict[str, Any]]:
        return search_symbols(term, master=master, limit=limit, **kwargs)

    def get_symbol_info(self, symbol: str) -> Optional[dict[str, Any]]:
        return get_symbol_info(symbol)

    def validate_symbol(self, symbol: str) -> dict[str, Any]:
        return validate_symbol(symbol)

    def get_lot_size(self, symbol: str, fallback: int = 1) -> int:
        return get_lot_size(symbol, fallback=fallback)

    def get_tick_size(self, symbol: str, fallback: float = 0.05) -> float:
        return get_tick_size(symbol, fallback=fallback)


_symbol_master_instance: Optional[SymbolMaster] = None


def get_symbol_master() -> SymbolMaster:
    """Return singleton SymbolMaster instance."""
    global _symbol_master_instance
    if _symbol_master_instance is None:
        _symbol_master_instance = SymbolMaster()
    return _symbol_master_instance

