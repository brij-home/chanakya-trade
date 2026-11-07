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
from functools import lru_cache
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
    "NFO": ("NSE_FO",),
    "BFO": ("BSE_FO",),
    "MCX": ("MCX_COM",),
}

# In-memory LRU cache to avoid reading JSON from disk repeatedly during tight execution loops
_IN_MEMORY_CACHE: dict[str, dict[str, Any]] = {}


import os
import threading
from config.constants import IST

_MASTER_CHECKED_ON: dict[str, dt.date] = {}
_DEGRADED_MASTERS: set[str] = set()
_MASTER_CACHE_PATHS: dict[str, Path] = {}
_MASTER_LOCKS = {name: threading.RLock() for name in MASTERS}


def _cache_path(master: str) -> Path:
    # Runtime overrides must never fall through to user-home or bundled test data.
    return app_data_path("sym_master", f"{master}.json")


def _is_fresh(path: Path) -> bool:
    """Check local snapshot retrieval date; row lastUpdate is not fetch freshness."""
    if not path.exists():
        return False
    if os.environ.get("CHANAKYA_TESTING") == "1":
        return True
    try:
        fetched_day = dt.datetime.fromtimestamp(path.stat().st_mtime, IST).date()
        return fetched_day == dt.datetime.now(IST).date()
    except OSError as exc:
        logger.warning("[SymbolMaster] Could not inspect snapshot freshness %s: %s", path, exc)
        return False


def load_master(master: str, force: bool = False, offline_fallback: bool = True) -> dict[str, Any]:
    name = master.upper().strip()
    if name not in _MASTER_LOCKS:
        raise ValueError(f"Unknown master {name!r}")
    with _MASTER_LOCKS[name]:
        return _load_master_snapshot(name, force=force, offline_fallback=offline_fallback)


def _load_master_snapshot(
    master: str, force: bool = False, offline_fallback: bool = True
) -> dict[str, Any]:
    """
    Load a master JSON dict keyed by API symbol ticker.
    Downloads and caches locally if missing or stale.
    """
    master_upper = master.upper().strip()
    if master_upper not in MASTERS:
        raise ValueError(f"Unknown master {master_upper!r}; choose from {', '.join(MASTERS)}")

    checked_today = _MASTER_CHECKED_ON.get(master_upper) == dt.datetime.now(IST).date()
    if (
        not force
        and checked_today
        and master_upper in _IN_MEMORY_CACHE
        and _MASTER_CACHE_PATHS.get(master_upper) == _cache_path(master_upper)
    ):
        if offline_fallback or master_upper not in _DEGRADED_MASTERS:
            return _IN_MEMORY_CACHE[master_upper]

    path = _cache_path(master_upper)
    must_refresh = (
        force or not _is_fresh(path) or (not offline_fallback and master_upper in _DEGRADED_MASTERS)
    )
    if must_refresh:
        url = BASE_URL.format(master_upper)
        req = urllib.request.Request(url, headers={"User-Agent": "chanakya-trade/2.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            dest_cache = _cache_path(master_upper)
            dest_cache.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = dest_cache.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(data), encoding="utf-8")
            tmp_path.replace(dest_cache)
            _IN_MEMORY_CACHE[master_upper] = data
            _MASTER_CACHE_PATHS[master_upper] = _cache_path(master_upper)
            _MASTER_CHECKED_ON[master_upper] = dt.datetime.now(IST).date()
            _DEGRADED_MASTERS.discard(master_upper)
            globals().get("_UNDERLYING_STRIKES_INDEX", {}).pop(master_upper, None)
            return data
        except Exception as e:
            if offline_fallback and path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    _IN_MEMORY_CACHE[master_upper] = data
                    _MASTER_CACHE_PATHS[master_upper] = _cache_path(master_upper)
                    _MASTER_CHECKED_ON[master_upper] = dt.datetime.now(IST).date()
                    _DEGRADED_MASTERS.add(master_upper)
                    logger.warning(
                        "[SymbolMaster] Using DEGRADED offline snapshot for %s: %s", master_upper, e
                    )
                    return data
                except Exception as e_suppressed:
                    logger.debug(
                        f"[market.symbol_master] Non-fatal exception suppressed: {e_suppressed}"
                    )
            raise RuntimeError(f"Failed to fetch symbol master {master_upper}: {e}") from e

    data = json.loads(path.read_text(encoding="utf-8"))
    _IN_MEMORY_CACHE[master_upper] = data
    _MASTER_CACHE_PATHS[master_upper] = _cache_path(master_upper)
    _MASTER_CHECKED_ON[master_upper] = dt.datetime.now(IST).date()
    _DEGRADED_MASTERS.discard(master_upper)
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


def get_symbol_info(symbol: str, *, require_fresh: bool = False) -> Optional[dict[str, Any]]:
    """Look up raw master record for a symbol across applicable exchange masters.

    Returns the raw master record dict if found, or None if the symbol is genuinely
    absent from all applicable exchange masters.  A None return due to a *transient*
    master-load failure (network/cache miss) is explicitly logged as DEGRADED so that
    callers can distinguish "truly invalid" from "temporarily unavailable".
    """
    s = str(symbol or "").strip()
    if not s:
        return None
    # Determine exchange prefix for master selection
    exch = s.split(":", 1)[0].upper() if ":" in s else "NSE"
    # The bare symbol name without any exchange prefix (used for prefix-free lookups)
    bare = s.split(":", 1)[1] if ":" in s else s
    candidates = _EXCHANGE_MASTERS.get(exch, ("NSE_CM", "NSE_FO"))
    master_exchange = {"NFO": "NSE", "BFO": "BSE"}.get(exch, exch)
    master_qualified = f"{master_exchange}:{bare}"

    for master in candidates:
        try:
            data = load_master(master, offline_fallback=not require_fresh)
            if require_fresh and master in _DEGRADED_MASTERS:
                raise RuntimeError(f"{master} is using a degraded snapshot")
        except Exception as e:
            # Master unavailable (network/cache miss) — log DEGRADED, do NOT silently
            # treat this as "symbol not in master"; the caller's guard must not drop
            # a valid symbol just because the cache is stale.
            logger.warning(
                f"[market.symbol_master] DEGRADED: could not load {master} while looking up"
                f" '{s}': {e}. Skipping master — symbol will not be dropped by upstream callers."
            )
            continue

        # Primary lookup: full qualified key (e.g. "NSE:ICICIPRULI-EQ")
        if s in data:
            return data[s]
        # Broker derivative segments use NFO/BFO prefixes, while the FYERS
        # instrument master keys derivative rows under NSE/BSE. Resolve only
        # within the matching derivatives master selected above.
        if master_qualified in data:
            return data[master_qualified]
        # Fallback: bare symbol without prefix (only for symbols that arrived prefix-free)
        if bare != s and bare in data:
            return data[bare]
        # Fallback: construct fully-qualified key from bare symbol + exchange prefix
        # (only when the input symbol had no prefix, i.e. bare == s)
        if bare == s:
            with_prefix = f"{exch}:{s}"
            if with_prefix in data:
                return data[with_prefix]

        # Fallback: resolve alias / broker ticker (e.g. ICICIPRULI -> ICICILIFE, ZOMATO -> ETERNAL)
        if exch in ("NSE", "BSE"):
            try:
                resolved = resolve_fyers_equity_symbol(s, exch=exch)
                if resolved and resolved in data:
                    return data[resolved]
            except Exception as e_suppressed:
                logger.debug(
                    f"[market.symbol_master] Alias lookup in get_symbol_info non-fatal: {e_suppressed}"
                )
    return None


def get_quantity_freeze_info(symbol: str, *, segment: str | None = None) -> dict[str, Any]:
    """Resolve the current single-order quantity freeze from a fresh F&O master.

    Unlike lot size, exchange quantity-freeze limits change independently and must
    never be inferred from an underlying or a historical constant. Exact contracts
    use their own active master row. An underlying-only lookup is accepted only when
    every active derivative row has the same published limit.
    """
    raw = str(symbol or "").strip().upper()
    if not raw:
        raise ValueError("A derivative symbol is required to resolve quantity freeze")

    prefix, body = raw.split(":", 1) if ":" in raw else ("", raw)
    from market.instruments import canonical_symbol
    from market.indices import INDEX_INSTRUMENTS

    contract_like = body.endswith(("CE", "PE", "FUT")) and any(char.isdigit() for char in body)
    clean_underlying = canonical_symbol(body)
    explicit_segment = str(segment or "").upper()
    if prefix in {"MCX", "MCX_COM"} or explicit_segment == "COMMODITY":
        exchange, master = "MCX", "MCX_COM"
    elif prefix in {"BFO"} or (
        prefix == "BSE" and explicit_segment in {"FNO", "OPTIONS", "FUTURES"}
    ):
        exchange, master = "BSE", "BSE_FO"
    elif prefix in {"NFO"} or explicit_segment in {
        "FNO",
        "FNO_INDEX",
        "FNO_STOCK",
        "OPTIONS",
        "FUTURES",
    }:
        exchange, master = "NSE", "NSE_FO"
    elif prefix == "NSE" and explicit_segment.startswith("EQUITY"):
        exchange, master = "NSE", "NSE_CM"
    elif prefix == "BSE" and explicit_segment.startswith("EQUITY"):
        exchange, master = "BSE", "BSE_CM"
    elif prefix == "BSE" and not contract_like and clean_underlying not in INDEX_INSTRUMENTS:
        exchange, master = "BSE", "BSE_CM"
    elif prefix == "NSE" and body.endswith(("-EQ", "-BE", "-SM", "-BZ", "-GB", "-ST")):
        exchange, master = "NSE", "NSE_CM"
    elif prefix in {"BSE"} or clean_underlying in {"SENSEX", "BANKEX"}:
        exchange, master = "BSE", "BSE_FO"
    elif prefix == "NSE" or clean_underlying in INDEX_INSTRUMENTS or contract_like:
        exchange, master = "NSE", "NSE_FO"
    else:
        raise ValueError(
            f"Ambiguous instrument {raw}; supply an exact derivative contract or exchange cash symbol"
        )

    # A stale offline snapshot can be useful for research, but it is not valid
    # authority for an order-size or execution plan.
    records = load_master(master, offline_fallback=False)
    if master in _DEGRADED_MASTERS:
        raise RuntimeError(f"{master} is using a degraded snapshot; quantity freeze unavailable")

    aliases = {raw, body, f"{exchange}:{body}"}
    exact_rows = [
        row
        for key, row in records.items()
        if isinstance(row, dict)
        and (str(key).upper() in aliases or str(row.get("symTicker", "")).upper() in aliases)
    ]

    def _active_limit(row: dict[str, Any]) -> int | None:
        if row.get("tradeStatus") not in (1, "1"):
            return None
        try:
            value = float(row.get("qtyFreeze"))
        except (TypeError, ValueError):
            return None
        if not value.is_integer() or value <= 0:
            return None
        return int(value)

    def _active_lot_size(row: dict[str, Any]) -> int | None:
        if row.get("tradeStatus") not in (1, "1"):
            return None
        try:
            value = float(row.get("minLotSize"))
        except (TypeError, ValueError):
            return None
        if not value.is_integer() or value <= 0:
            return None
        return int(value)

    if exact_rows:
        exact_limits = [_active_limit(row) for row in exact_rows]
        exact_lot_sizes = [_active_lot_size(row) for row in exact_rows]
        if (
            any(quantity is None for quantity in exact_limits)
            or len(set(exact_limits)) != 1
            or any(size is None for size in exact_lot_sizes)
            or len(set(exact_lot_sizes)) != 1
        ):
            raise RuntimeError(
                f"No unambiguous active published quantity freeze or lot size for {raw}"
            )
        row = exact_rows[0]
        quantity = exact_limits[0]
        lot_size = exact_lot_sizes[0]
        assert quantity is not None
        assert lot_size is not None
        return {
            "quantity": quantity,
            "lot_size": lot_size,
            "exchange": exchange,
            "symbol": str(row.get("symTicker") or raw),
            "source": "FYERS_PUBLISHED_EXCHANGE_MASTER",
            "master": master,
            "source_last_update": row.get("lastUpdate"),
            "retrieved_on": _MASTER_CHECKED_ON.get(master),
        }

    # Contract-looking input must not fall through to another expiry's row.
    if contract_like:
        raise RuntimeError(f"Contract {raw} is absent from the current {master} master")

    underlying = clean_underlying
    candidates = [
        row
        for row in records.values()
        if isinstance(row, dict)
        and row.get("tradeStatus") in (1, "1")
        and canonical_symbol(str(row.get("underSym") or row.get("exSymbol") or "")) == underlying
    ]
    candidate_limits = [_active_limit(row) for row in candidates]
    candidate_lot_sizes = [_active_lot_size(row) for row in candidates]
    if (
        not candidate_limits
        or any(quantity is None for quantity in candidate_limits)
        or any(size is None for size in candidate_lot_sizes)
    ):
        raise RuntimeError(
            f"Current quantity freeze is missing or ambiguous for {exchange}:{underlying}"
        )
    limits = set(candidate_limits)
    if len(limits) != 1:
        raise RuntimeError(
            f"Current quantity freeze is missing or ambiguous for {exchange}:{underlying}"
        )
    lot_sizes = set(candidate_lot_sizes)
    if len(lot_sizes) != 1:
        raise RuntimeError(f"Current lot size is missing or ambiguous for {exchange}:{underlying}")
    return {
        "quantity": limits.pop(),
        "lot_size": lot_sizes.pop(),
        "exchange": exchange,
        "symbol": f"{exchange}:{underlying}",
        "source": "FYERS_PUBLISHED_EXCHANGE_MASTER",
        "master": master,
        "source_last_update": max(
            (str(row.get("lastUpdate") or "") for row in candidates), default=None
        ),
        "retrieved_on": _MASTER_CHECKED_ON.get(master),
    }


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
_UNDERLYING_STRIKES_INDEX: dict[str, dict[str, set[float]]] = {}

_KNOWN_BENCHMARK_STRIKE_STEPS: dict[str, float] = {
    "BANKNIFTY": 100.0,
    "SENSEX": 100.0,
    "BANKEX": 100.0,
    "MIDCPNIFTY": 25.0,
    "NIFTY": 50.0,
    "FINNIFTY": 50.0,
    "NIFTYIT": 100.0,
    "CRUDEOIL": 50.0,
    "CRUDEOILM": 50.0,
    "GOLD": 500.0,
    "GOLDM": 100.0,
    "SILVER": 1000.0,
    "SILVERM": 500.0,
    "NATURALGAS": 5.0,
    "NATGASMINI": 5.0,
    "COPPER": 10.0,
    "ALUMINIUM": 10.0,
    "ZINC": 5.0,
    "USDINR": 0.25,
    "EURINR": 0.25,
    "GBPINR": 0.25,
    "JPYINR": 0.25,
}


def _get_underlying_strikes_index(master: str) -> dict[str, set[float]]:
    """Build or return an in-memory inverted index of underlying -> set of strike prices once per master."""
    if master in _UNDERLYING_STRIKES_INDEX:
        return _UNDERLYING_STRIKES_INDEX[master]
    data = load_master(master, offline_fallback=True)
    idx: dict[str, set[float]] = {}
    for v in data.values():
        u = v.get("underSym") or v.get("exSymbol")
        if u:
            stk = float(v.get("strikePrice", -1))
            if stk > 0:
                if u not in idx:
                    idx[u] = set()
                idx[u].add(stk)
    _UNDERLYING_STRIKES_INDEX[master] = idx
    return idx


def get_strike_step(symbol: str, spot: float = 0.0, expiry: Optional[str] = None) -> float:
    """
    Authoritative Strike Step Resolver for Indian Derivatives (Indices, Equities, Commodities, Currencies).
    1. Tier 0: O(1) SEBI/Exchange Standard Benchmark specifications (NIFTY=50, BANKNIFTY=100, SENSEX=100, etc.).
    2. Tier 1: Inverted index lookup in canonical exchange masters (NSE_FO, MCX_COM, NSE_CD, BSE_FO).
    3. Tier 2: Deterministic spot-tier rulebook fallback.
    """
    from market.instruments import canonical_symbol

    clean = canonical_symbol(symbol)
    if not clean:
        return 50.0

    cache_key = (clean, int(round(spot * 10)), expiry)
    if cache_key in _STRIKE_STEP_CACHE:
        return _STRIKE_STEP_CACHE[cache_key]

    # Tier 0: Direct O(1) resolution for standard benchmark indices and commodities
    if clean in _KNOWN_BENCHMARK_STRIKE_STEPS:
        res = _KNOWN_BENCHMARK_STRIKE_STEPS[clean]
        _STRIKE_STEP_CACHE[cache_key] = res
        return res

    # Tier 1: Inverted index empirical lookup in official exchange masters
    for master in ("NSE_FO", "MCX_COM", "NSE_CD", "BSE_FO"):
        try:
            idx = _get_underlying_strikes_index(master)
            strikes_set = idx.get(clean)
            if not strikes_set or len(strikes_set) < 2:
                continue

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


@lru_cache(maxsize=4096)
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
    if exch == "NSE":
        for sfx in ("-EQ", "-BE", "-SM", "-BZ", "-GB", "-ST", "-E1", "-INDEX"):
            if base.endswith(sfx):
                base = base[: -len(sfx)]
                break
    elif exch == "BSE":
        for sfx in ("-A", "-B", "-X", "-XT", "-T", "-Z", "-EQ", "-INDEX"):
            if base.endswith(sfx):
                base = base[: -len(sfx)]
                break
    else:
        for sfx in ("-EQ", "-BE", "-INDEX"):
            if base.endswith(sfx):
                base = base[: -len(sfx)]
                break

    # Apply corporate aliases first (e.g. ZOMATO -> ETERNAL, TATAMOTORS -> TMPV, ICICIPRULI -> ICICILIFE)
    try:
        from market.instruments import resolve_corporate_alias

        base = resolve_corporate_alias(base)
    except Exception as e_suppressed:
        logger.debug(f"[market.symbol_master] Corporate alias resolution non-fatal: {e_suppressed}")

    # Fyers-specific broker alias mappings
    if base in ("LTIM", "LTI"):
        base = "LTM"
    elif base in ("ICICIPRULI", "ICICI_PRU"):
        base = "ICICILIFE"
    elif base in ("NMDCSTEEL", "NSLNISP"):
        base = "NSLNISP"
    elif base == "HEG":
        base = "HEGAM"
    elif base == "SILLYMONKS":
        base = "CRESTO"

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


def resolve_active_future(
    symbol: str, exch: Optional[str] = None, ref_date: Optional[dt.date] = None
) -> str:
    """
    Authoritatively resolve the active near-month tradable Future ticker for any index or stock
    directly from canonical exchange masters (NSE_FO / BSE_FO).
    Eliminates date-arithmetic guessing or attempting to subscribe to expired/non-existent contracts.

    Examples:
      'NIFTY' -> 'NSE:NIFTY26NOVFUT'
      'BANKNIFTY' -> 'NSE:BANKNIFTY26NOVFUT'
      'SENSEX' -> 'BSE:SENSEX26OCTFUT'
      'TATAMOTORS' -> 'NSE:TMPV26NOVFUT'
      'RELIANCE' -> 'NSE:RELIANCE26NOVFUT'
    """
    s = str(symbol or "").strip().upper()
    if not s:
        return ""
    if ":" in s:
        pfx, s = s.split(":", 1)
        if not exch:
            exch = pfx.strip().upper()

    clean = (
        s.replace("-INDEX", "")
        .replace("-EQ", "")
        .replace("-BE", "")
        .replace("-SM", "")
        .replace(":EQ", "")
        .strip()
    )
    if clean in ("NIFTY50", "NIFTY_50"):
        clean = "NIFTY"
    elif clean == "NIFTYBANK":
        clean = "BANKNIFTY"
    elif clean in ("NIFTYFINSERVICE", "FIN_NIFTY"):
        clean = "FINNIFTY"
    elif clean in ("NIFTYMIDCAP100", "NIFTYMIDSELECT", "MIDCAP"):
        clean = "MIDCPNIFTY"

    try:
        from market.instruments import resolve_corporate_alias

        clean = resolve_corporate_alias(clean)
    except Exception as e_suppressed:
        logger.debug(
            f"[market.symbol_master] Corporate alias in resolve_active_future: {e_suppressed}"
        )

    target_exch = exch or ("BSE" if clean in ("SENSEX", "BANKEX") else "NSE")

    # If a historical reference date is explicitly requested (e.g. backtesting or simulated test),
    # live exchange master only holds current/future active contracts; construct historical contract.
    if ref_date is not None and ref_date < dt.date.today():
        from market.calendar import get_nearest_monthly_expiry

        exp_d = get_nearest_monthly_expiry(clean, ref_date=ref_date)
        return f"{target_exch}:{clean}{exp_d.strftime('%y%b').upper()}FUT"

    master = "BSE_FO" if target_exch == "BSE" else "NSE_FO"

    try:
        m = load_master(master, offline_fallback=True)
        now_ts = int(dt.datetime.now().timestamp())
        cands = []
        for v in m.values():
            if v.get("optType") in ("XX", "", None) and v.get("symTicker", "").endswith("FUT"):
                u = v.get("underSym") or v.get("exSymbol")
                if u == clean:
                    exp = int(v.get("expiryDate", 0))
                    if exp >= now_ts - 86400:
                        cands.append((exp, v.get("symTicker", "")))
        if cands:
            cands.sort(key=lambda x: x[0])
            return cands[0][1]
    except Exception as e:
        logger.warning(
            f"[market.symbol_master] Exception resolving active future for '{symbol}': {e}"
        )

    # Fallback to date arithmetic if symbol master is offline
    from market.calendar import get_nearest_monthly_expiry

    exp_d = get_nearest_monthly_expiry(clean)
    return f"{target_exch}:{clean}{exp_d.strftime('%y%b').upper()}FUT"


def get_active_expiries(underlying: str, exch: Optional[str] = None) -> list[dt.date]:
    """Return all active, upcoming contract expiry dates directly from official exchange masters."""
    s = str(underlying or "").strip().upper()
    if not s:
        return []
    if ":" in s:
        pfx, s = s.split(":", 1)
        if not exch:
            exch = pfx.strip().upper()

    clean = s.replace("-INDEX", "").replace("-EQ", "").replace("-BE", "").strip()
    if clean in ("NIFTY50", "NIFTY_50"):
        clean = "NIFTY"
    elif clean == "NIFTYBANK":
        clean = "BANKNIFTY"
    elif clean in ("NIFTYFINSERVICE", "FIN_NIFTY"):
        clean = "FINNIFTY"
    elif clean in ("NIFTYMIDCAP100", "NIFTYMIDSELECT", "MIDCAP"):
        clean = "MIDCPNIFTY"

    try:
        from market.instruments import resolve_corporate_alias

        clean = resolve_corporate_alias(clean)
    except Exception as e_alias:
        logger.debug("[SymbolMaster] resolve_corporate_alias skipped for %s: %s", clean, e_alias)

    target_exch = exch or ("BSE" if clean in ("SENSEX", "BANKEX") else "NSE")
    master = "BSE_FO" if target_exch == "BSE" else "NSE_FO"

    try:
        m = load_master(master, offline_fallback=True)
        now_ts = int(dt.datetime.now().timestamp())
        exps = set()
        for v in m.values():
            u = v.get("underSym") or v.get("exSymbol")
            if u == clean:
                ep = v.get("expiryDate")
                if ep and int(ep) >= now_ts - 86400:
                    d = dt.datetime.fromtimestamp(int(ep), dt.timezone.utc).date()
                    exps.add(d)
        return sorted(list(exps))
    except Exception as e:
        logger.debug(f"[market.symbol_master] get_active_expiries failed: {e}")
        return []


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

    def get_quantity_freeze_info(self, symbol: str) -> dict[str, Any]:
        return get_quantity_freeze_info(symbol)

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

    def resolve_active_future(self, symbol: str, exch: Optional[str] = None) -> str:
        return resolve_active_future(symbol, exch=exch)

    def get_active_expiries(self, underlying: str, exch: Optional[str] = None) -> list[dt.date]:
        return get_active_expiries(underlying, exch=exch)


_symbol_master_instance: Optional[SymbolMaster] = None


def get_symbol_master() -> SymbolMaster:
    """Return singleton SymbolMaster instance."""
    global _symbol_master_instance
    if _symbol_master_instance is None:
        _symbol_master_instance = SymbolMaster()
    return _symbol_master_instance
