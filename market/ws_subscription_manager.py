"""
market/ws_subscription_manager.py
─────────────────────────────────
Persistent WebSocket Subscription Manager with LRU Capacity Management.

Fyers API Hard Constraints & Architecture:
  - WebSocket Data Socket supports up to 5,000 symbols concurrent real-time stream.
  - REST API rate limit is 10 requests / sec, 500 requests / min on Prime (500k req/day).
  - Subscription manager maintains up to 5,000 active symbols with LRU eviction for dynamic additions.
  - Permanently maintains core benchmarks, commodities, and top F&O equities.
  - Persists subscription state to disk so service restarts restore all feeds instantly with zero REST calls.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from calendar import monthrange
from collections import OrderedDict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)
from market.instruments import format_strike

MAX_WS_SUBSCRIPTIONS = 5000  # FYERS API v3 Data Socket supports up to 5,000 symbols concurrently

# Permanent base set: key indices/commodities + top liquid institutional equities
CORE_BASE_SYMBOLS: list[str] = [
    # Benchmark & Sectoral Indices
    "NSE:NIFTY50-INDEX",
    "NSE:NIFTYBANK-INDEX",
    "NSE:MIDCPNIFTY-INDEX",
    "NSE:FINNIFTY-INDEX",
    "BSE:SENSEX-INDEX",
    "NSE:INDIAVIX-INDEX",
    "NSE:NIFTYIT-INDEX",
    "NSE:NIFTYAUTO-INDEX",
    "NSE:NIFTYPHARMA-INDEX",
    "NSE:NIFTYFMCG-INDEX",
    "NSE:NIFTYMETAL-INDEX",
    "NSE:NIFTYENERGY-INDEX",
    "NSE:NIFTYREALTY-INDEX",
    "NSE:NIFTYINFRA-INDEX",
    "NSE:NIFTYPSE-INDEX",
    # MCX Commodities
    "MCX:CRUDEOIL",
    "MCX:NATURALGAS",
    "MCX:GOLD",
    "MCX:SILVER",
    "MCX:COPPER",
    "MCX:ZINC",
    # Top Tier Institutional Equities & Liquid F&O
    "NSE:RELIANCE-EQ",
    "NSE:HDFCBANK-EQ",
    "NSE:ICICIBANK-EQ",
    "NSE:INFY-EQ",
    "NSE:TCS-EQ",
    "NSE:ITC-EQ",
    "NSE:LT-EQ",
    "NSE:SBIN-EQ",
    "NSE:BHARTIARTL-EQ",
    "NSE:AXISBANK-EQ",
    "NSE:KOTAKBANK-EQ",
    "NSE:TMPV-EQ",
    "NSE:MARUTI-EQ",
    "NSE:BAJFINANCE-EQ",
    "NSE:HINDUNILVR-EQ",
    "NSE:SUNPHARMA-EQ",
    "NSE:TITAN-EQ",
    "NSE:TATASTEEL-EQ",
    "NSE:NTPC-EQ",
    "NSE:POWERGRID-EQ",
    "NSE:M&M-EQ",
    "NSE:ASIANPAINT-EQ",
    "NSE:ULTRACEMCO-EQ",
    "NSE:COALINDIA-EQ",
    "NSE:BAJAJFINSV-EQ",
    "NSE:ONGC-EQ",
    "NSE:ADANIENT-EQ",
    "NSE:ADANIPORTS-EQ",
    "NSE:HCLTECH-EQ",
    "NSE:WIPRO-EQ",
    "NSE:JSWSTEEL-EQ",
    "NSE:GRASIM-EQ",
    "NSE:HINDALCO-EQ",
    "NSE:DIVISLAB-EQ",
    "NSE:CIPLA-EQ",
    "NSE:DRREDDY-EQ",
    "NSE:BPCL-EQ",
    "NSE:EICHERMOT-EQ",
    "NSE:TATACONSUM-EQ",
    "NSE:HEROMOTOCO-EQ",
]

# Dynamically populate liquid taxonomy equities and benchmarks
try:
    from analysis.universe import SECTOR_TAXONOMY
    from market.instruments import resolve_corporate_alias
    from market.symbol_master import resolve_fyers_equity_symbol
    import json
    from pathlib import Path

    for _sec_info in SECTOR_TAXONOMY.values():
        for _s in _sec_info.get("symbols", []):
            _clean = resolve_corporate_alias(_s)
            _eq_sym = resolve_fyers_equity_symbol(_clean, exch="NSE")
            if _eq_sym and _eq_sym not in CORE_BASE_SYMBOLS:
                CORE_BASE_SYMBOLS.append(_eq_sym)

    # Pre-seed top institutional benchmarks from nifty_total_market.json (up to 750)
    _tot_path = Path("data/universes/nifty_total_market.json")
    if _tot_path.exists():
        _tot_data = json.load(open(_tot_path, "r", encoding="utf-8"))
        for _item in _tot_data:
            _raw_sym = _item.get("symbol", "").strip().upper()
            if _raw_sym:
                _clean = resolve_corporate_alias(_raw_sym)
                _eq_sym = resolve_fyers_equity_symbol(_clean, exch="NSE")
                if _eq_sym and _eq_sym not in CORE_BASE_SYMBOLS:
                    CORE_BASE_SYMBOLS.append(_eq_sym)
except Exception as e:
    logger.warning(f"Could not load universe into CORE_BASE_SYMBOLS: {e}")

from config.paths import app_data_path


import re

_VALID_OPTION_RE = re.compile(
    r"^[A-Za-z0-9_&]+?(\d{2})([A-Za-z]{3}|[1-9ONDond]\d{2}|\d{4})(\d+)(CE|PE)$"
)

WEEKLY_OPT_RE = re.compile(r"^([A-Za-z0-9_&]+?)(\d{2})([1-9ONDond])(\d{2})(\d+)(CE|PE)$")
MONTHLY_OPT_RE = re.compile(r"^([A-Za-z0-9_&]+?)(\d{2})([A-Za-z]{3})(\d+)(CE|PE)$")
FUT_RE = re.compile(r"^([A-Za-z0-9_&]+?)(\d{2})([A-Za-z]{3})FUT$")

WEEKLY_MONTH_MAP: dict[str, int] = {
    "1": 1,
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 7,
    "8": 8,
    "9": 9,
    "O": 10,
    "N": 11,
    "D": 12,
}
MONTH_NAME_MAP: dict[str, int] = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


def _calc_monthly_expiry_date(exch: str, underlying: str, yr: int, mo: int) -> date:
    """Calculate the precise monthly expiry date for NSE, BSE, MCX, or CDS."""
    _, num_days = monthrange(yr, mo)
    exch_up = (exch or "NSE").upper()
    if exch_up == "BSE":
        d = date(yr, mo, num_days)
        while d.weekday() != 4:  # Last Friday
            d -= timedelta(days=1)
    elif exch_up == "MCX":
        if "CRUDE" in underlying.upper():
            exp_day = min(19, num_days)
            d = date(yr, mo, exp_day)
        else:
            d = date(yr, mo, num_days)
    else:
        d = date(yr, mo, num_days)
        while d.weekday() != 3:  # Last Thursday
            d -= timedelta(days=1)
    try:
        from market.calendar import get_adjusted_expiry_date

        return get_adjusted_expiry_date(d, exch_up if exch_up in ("BSE", "MCX") else "NFO")
    except Exception:
        return d


def parse_contract_expiry(symbol: str) -> Optional[date]:
    """
    Parse the official expiry date from any Indian market derivative contract symbol.
    Delegates to institutional SSOT market.instruments.parse_derivative_contract.
    """
    from market.instruments import parse_derivative_contract

    parsed = parse_derivative_contract(symbol)
    return parsed.expiry_date if parsed else None


def is_contract_expired(symbol: str, ref_dt: Optional[datetime] = None) -> bool:
    """
    Determine if a derivative contract is expired relative to current IST market time.
    Delegates to institutional SSOT market.instruments.is_contract_expired.
    """
    from market.instruments import is_contract_expired as _inst_is_contract_expired

    return _inst_is_contract_expired(symbol, ref_dt=ref_dt)


# Known structurally blacklisted symbols: instruments rejected by Fyers Data Socket
# with error -300 that are NOT handled by the CORPORATE_ALIASES rename map.
# Do NOT add renamed/rebranded tickers here — use CORPORATE_ALIASES in market/instruments.py
# (e.g. ZOMATO→ETERNAL is already in CORPORATE_ALIASES so NSE:ZOMATO-EQ never reaches this gate).
_WS_SYMBOL_BLACKLIST = {
    "NSE:NIFTYFPI-INDEX",  # SEBI-suspended index; not available on Fyers Data Socket
}


def is_valid_ws_symbol(symbol: str) -> bool:
    """Validate that symbol conforms to Fyers/Exchange format before dispatching to WebSocket."""
    if not symbol or not isinstance(symbol, str):
        return False
    s = symbol.strip()
    if not s or " " in s or "\t" in s or "\n" in s:
        return False
    if s.count(":") > 1:
        return False
    if s in _WS_SYMBOL_BLACKLIST:
        return False

    clean_name = s.split(":")[-1] if ":" in s else s

    # 1. Any option contract (ending in CE or PE with digits) MUST match valid expiry structure
    if (clean_name.endswith("CE") or clean_name.endswith("PE")) and any(
        c.isdigit() for c in clean_name
    ):
        if not _VALID_OPTION_RE.match(clean_name):
            return False

    # 2. Reject unnormalized NSE/BSE equities that have hyphens without valid segment suffix
    if "-EQ-INDEX" in clean_name or "-INDEX-INDEX" in clean_name or "-BE-INDEX" in clean_name:
        return False
    if (s.startswith("NSE:") or s.startswith("BSE:")) and "-" in clean_name:
        if not clean_name.endswith(("-EQ", "-INDEX", "-BE", "-SM", "-BZ", "-GB")):
            return False

    return True


def get_active_index_options_grid(num_strikes_per_side: int = 8) -> list[str]:
    """
    Generate active Index Options contracts for NIFTY, BANKNIFTY, MIDCPNIFTY, SENSEX, and FINNIFTY.
    Generates ATM ± num_strikes_per_side strikes for each index (~170 contracts).
    """
    from datetime import datetime

    now = datetime.now()
    today = now.date()
    from market.instruments import _calc_monthly_expiry_date

    estimated_spots = {
        "NIFTY": ("NSE", 25000.0, 50, num_strikes_per_side),
        "BANKNIFTY": ("NSE", 52000.0, 100, num_strikes_per_side),
        "MIDCPNIFTY": ("NSE", 13200.0, 25, num_strikes_per_side),
        "SENSEX": ("BSE", 81500.0, 100, max(4, num_strikes_per_side - 2)),
        "FINNIFTY": ("NSE", 24000.0, 100, max(4, num_strikes_per_side - 3)),
    }

    try:
        from market.quotes import get_ltp

        n_p = get_ltp("NSE:NIFTY50-INDEX") or get_ltp("NIFTY")
        if n_p and n_p > 0:
            estimated_spots["NIFTY"] = ("NSE", n_p, 50, num_strikes_per_side)
        bn_p = get_ltp("NSE:NIFTYBANK-INDEX") or get_ltp("BANKNIFTY")
        if bn_p and bn_p > 0:
            estimated_spots["BANKNIFTY"] = ("NSE", bn_p, 100, num_strikes_per_side)
        mid_p = get_ltp("NSE:MIDCPNIFTY-INDEX") or get_ltp("MIDCPNIFTY")
        if mid_p and mid_p > 0:
            estimated_spots["MIDCPNIFTY"] = ("NSE", mid_p, 25, num_strikes_per_side)
        sen_p = get_ltp("BSE:SENSEX-INDEX") or get_ltp("SENSEX")
        if sen_p and sen_p > 0:
            estimated_spots["SENSEX"] = ("BSE", sen_p, 100, max(4, num_strikes_per_side - 2))
        fin_p = get_ltp("NSE:FINNIFTY-INDEX") or get_ltp("FINNIFTY")
        if fin_p and fin_p > 0:
            estimated_spots["FINNIFTY"] = ("NSE", fin_p, 50, max(4, num_strikes_per_side - 3))
    except Exception as e_suppressed:
        logger.debug(
            f"[market.ws_subscription_manager] Non-fatal exception suppressed: {e_suppressed}"
        )

    from market.symbol_master import get_strike_step

    grid: list[str] = []
    for idx_name, (exch, spot, default_step, n_stk) in estimated_spots.items():
        # Institutional expiry resolution: never prematurely roll to next month before actual monthly expiry
        try:
            exp_date = _calc_monthly_expiry_date(exch, idx_name, now.year, now.month)
            if today <= exp_date:
                active_suffixes = [now.strftime("%y%b").upper()]
                # If within 3 calendar days of expiry, also pre-seed next month for seamless rollover
                if (exp_date - today).days <= 3:
                    nm = now.month + 1 if now.month < 12 else 1
                    ny = now.year if now.month < 12 else now.year + 1
                    active_suffixes.append(datetime(ny, nm, 1).strftime("%y%b").upper())
            else:
                nm = now.month + 1 if now.month < 12 else 1
                ny = now.year if now.month < 12 else now.year + 1
                active_suffixes = [datetime(ny, nm, 1).strftime("%y%b").upper()]
        except Exception:
            active_suffixes = [now.strftime("%y%b").upper()]

        step = get_strike_step(idx_name, spot=spot) or default_step
        atm_strike = round(spot / float(step)) * step
        for m_suf in active_suffixes:
            for offset in range(-n_stk, n_stk + 1):
                strike = round(atm_strike + (offset * step), 2)
                grid.append(f"{exch}:{idx_name}{m_suf}{format_strike(strike)}CE")
                grid.append(f"{exch}:{idx_name}{m_suf}{format_strike(strike)}PE")

    # On Thursday (NIFTY 0DTE) and Friday (SENSEX 0DTE), pre-seed active weekly options
    try:
        from brokers.fyers import format_fyers_option_symbol

        weekday = now.weekday()
        if weekday == 3:  # Thursday: NIFTY weekly options
            n_spot = estimated_spots["NIFTY"][1]
            n_atm = int(round(n_spot / 50.0) * 50)
            for offset in range(-num_strikes_per_side, num_strikes_per_side + 1):
                stk = n_atm + (offset * 50)
                ce = format_fyers_option_symbol("NIFTY", now.date(), stk, "CE")
                pe = format_fyers_option_symbol("NIFTY", now.date(), stk, "PE")
                if ce not in grid:
                    grid.append(ce)
                if pe not in grid:
                    grid.append(pe)
        elif weekday == 4:  # Friday: SENSEX weekly options
            s_spot = estimated_spots["SENSEX"][1]
            s_atm = int(round(s_spot / 100.0) * 100)
            for offset in range(-6, 7):
                stk = s_atm + (offset * 100)
                ce = format_fyers_option_symbol("SENSEX", now.date(), stk, "CE")
                pe = format_fyers_option_symbol("SENSEX", now.date(), stk, "PE")
                if ce not in grid:
                    grid.append(ce)
                if pe not in grid:
                    grid.append(pe)
    except Exception as e_suppressed:
        logger.debug(
            f"[market.ws_subscription_manager] Non-fatal exception suppressed: {e_suppressed}"
        )

    # Authoritative Pre-Subscription Filter: validate existence against exchange masters
    try:
        from market.symbol_master import load_master

        nse_fo_data = None
        try:
            nse_fo_data = load_master("NSE_FO", offline_fallback=True)
        except Exception as e_suppressed:
            logger.debug(
                f"[market.ws_subscription_manager] NSE_FO master load non-fatal: {e_suppressed}"
            )

        bse_fo_data = None
        try:
            bse_fo_data = load_master("BSE_FO", offline_fallback=True)
        except Exception as e_suppressed:
            logger.debug(
                f"[market.ws_subscription_manager] BSE_FO master load non-fatal: {e_suppressed}"
            )

        filtered_grid = []
        for s in grid:
            if s.startswith("NSE:") and nse_fo_data is not None:
                if s in nse_fo_data:
                    filtered_grid.append(s)
            elif s.startswith("BSE:") and bse_fo_data is not None:
                if s in bse_fo_data:
                    filtered_grid.append(s)
            else:
                # Retain candidate if master for that exchange was not loaded
                filtered_grid.append(s)

        pruned = len(grid) - len(filtered_grid)
        if pruned > 0:
            logger.info(
                f"[ws_sub_manager] Proactive pre-subscription filter pruned {pruned} phantom option strikes before broker dispatch."
            )
        grid = filtered_grid
    except Exception as e_grid_flt:
        logger.debug(f"[ws_sub_manager] Non-fatal options grid filter: {e_grid_flt}")

    return grid


def get_active_commodity_grid(ref_time: datetime | None = None) -> list[str]:
    """
    Generate active MCX Commodity and Currency CDS futures and near ATM options.
    """
    from datetime import datetime, timedelta

    now = ref_time or datetime.now()
    # Crude Oil options expire ~2 business days before futures; roll on day 15 to guarantee active front-month options.
    c_dt = now if now.day <= 15 else now + timedelta(days=20)
    c_suffix = c_dt.strftime("%y%b").upper()

    from brokers.fyers import _resolve_commodity_contract, _resolve_currency_contract

    comm_symbols = [
        _resolve_commodity_contract("CRUDEOIL", ref_time=now),
        _resolve_commodity_contract("NATURALGAS", ref_time=now),
        _resolve_commodity_contract("GOLD", ref_time=now),
        _resolve_commodity_contract("SILVER", ref_time=now),
        _resolve_commodity_contract("COPPER", ref_time=now),
        _resolve_commodity_contract("ZINC", ref_time=now),
        _resolve_currency_contract("USDINR"),
        _resolve_currency_contract("EURINR"),
    ]

    crude_atm = 6500
    try:
        from market.quotes import get_ltp

        cl = get_ltp("MCX:CRUDEOIL") or 6500.0
        crude_atm = int(round(cl / 50.0) * 50)
    except Exception as e_suppressed:
        logger.debug(
            f"[market.ws_subscription_manager] Non-fatal exception suppressed: {e_suppressed}"
        )

    crude_step = 50.0
    try:
        from market.symbol_master import get_strike_step

        crude_step = get_strike_step("CRUDEOIL", spot=cl)
    except Exception as e_suppressed:
        logger.debug(
            f"[market.ws_subscription_manager] Crude step resolution non-fatal: {e_suppressed}"
        )

    for offset in (-2, -1, 0, 1, 2):
        stk = int(round(crude_atm + (offset * crude_step)))
        comm_symbols.append(f"MCX:CRUDEOIL{c_suffix}{stk}CE")
        comm_symbols.append(f"MCX:CRUDEOIL{c_suffix}{stk}PE")

    # Authoritative Pre-Subscription Filter: validate commodity/CDS contracts when running live (ref_time is None)
    if ref_time is None:
        try:
            from market.symbol_master import load_master

            mcx_data = None
            try:
                mcx_data = load_master("MCX_COM", offline_fallback=True)
            except Exception as e_suppressed:
                logger.debug(
                    f"[market.ws_subscription_manager] MCX_COM master load non-fatal: {e_suppressed}"
                )

            cd_data = None
            try:
                cd_data = load_master("NSE_CD", offline_fallback=True)
            except Exception as e_suppressed:
                logger.debug(
                    f"[market.ws_subscription_manager] NSE_CD master load non-fatal: {e_suppressed}"
                )

            filtered_comm = []
            for s in comm_symbols:
                if s.startswith("MCX:") and mcx_data is not None:
                    if s in mcx_data:
                        filtered_comm.append(s)
                elif s.startswith("NSE:") and cd_data is not None:
                    if s in cd_data:
                        filtered_comm.append(s)
                else:
                    filtered_comm.append(s)

            pruned = len(comm_symbols) - len(filtered_comm)
            if pruned > 0:
                logger.info(
                    f"[ws_sub_manager] Proactive pre-subscription filter pruned {pruned} invalid commodity/CDS contracts before broker dispatch."
                )
            comm_symbols = filtered_comm
        except Exception as e_comm_flt:
            logger.debug(f"[ws_sub_manager] Non-fatal commodity grid filter: {e_comm_flt}")

    return comm_symbols


def _get_cache_path() -> Path:
    cache_dir = app_data_path("cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "ws_active_subscriptions.json"


class WsSubscriptionManager:
    """
    Manages WebSocket subscriptions with persistent state and LRU eviction.
    """

    def __init__(self, max_subscriptions: int = MAX_WS_SUBSCRIPTIONS) -> None:
        self._max_subscriptions = max_subscriptions
        self._lock = threading.RLock()
        self._core_symbols: set[str] = set(CORE_BASE_SYMBOLS)
        # Dynamic subscriptions tracked in OrderedDict for LRU eviction: symbol -> timestamp
        self._dynamic_symbols: OrderedDict[str, float] = OrderedDict()
        self._anchored_spots: dict[str, float] = {}
        self._load_from_disk()

    def seed_active_derivatives(self, ws_client: Optional[Any] = None) -> list[str]:
        """
        Pre-seed active Index Options grid (NIFTY, BANKNIFTY, FINNIFTY, SENSEX)
        and MCX Commodities into the persistent WebSocket subscription registry.
        Leverages Fyers Prime 5,000 capacity to ensure 100% in-memory quote hits.
        """
        options_grid = get_active_index_options_grid()
        commodity_grid = get_active_commodity_grid()
        to_add = [s for s in (options_grid + commodity_grid) if is_valid_ws_symbol(s)]

        with self._lock:
            new_syms = [s for s in to_add if s not in self._core_symbols]
            self._core_symbols.update(to_add)

        if new_syms:
            self._save_to_disk()
            logger.info(
                f"[WsSubManager] Pre-seeded {len(to_add)} active derivatives (Options={len(options_grid)}, Comm={len(commodity_grid)})"
            )

        if ws_client and to_add:
            try:
                if hasattr(ws_client, "subscribe"):
                    import inspect

                    sig = inspect.signature(ws_client.subscribe)
                    if "record_in_manager" in sig.parameters:
                        ws_client.subscribe(to_add, record_in_manager=False)
                    else:
                        ws_client.subscribe(to_add)
            except Exception as exc:
                logger.warning(f"[WsSubManager] Error subscribing pre-seeded derivatives: {exc}")

        return to_add

    def _load_from_disk(self) -> None:
        """Load persisted subscriptions from previous run and auto-cleanse expired contracts."""
        path = _get_cache_path()
        if not path.exists():
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            loaded_dynamic = data.get("dynamic", [])
            loaded_core = data.get("core", [])
            now = time.time()
            sanitized_needed = False

            with self._lock:
                for sym in loaded_dynamic:
                    if not is_valid_ws_symbol(sym) or is_contract_expired(sym):
                        sanitized_needed = True
                        continue
                    if sym not in self._core_symbols:
                        self._dynamic_symbols[sym] = now

                # Also cleanse expired from loaded core (preserve CORE_BASE_SYMBOLS)
                for sym in loaded_core:
                    if sym not in CORE_BASE_SYMBOLS:
                        if is_contract_expired(sym) or not is_valid_ws_symbol(sym):
                            sanitized_needed = True
                            self._core_symbols.discard(sym)
                        else:
                            self._core_symbols.add(sym)

            if sanitized_needed:
                self._save_to_disk()
            logger.info(
                f"[WsSubManager] Restored {len(self._dynamic_symbols)} dynamic and {len(self._core_symbols)} core subscriptions from disk (sanitized={sanitized_needed})"
            )
        except Exception as exc:
            logger.warning(
                f"[WsSubManager] Failed loading disk subscriptions from {path}: {exc}",
                exc_info=True,
            )

    def cleanse_expired_derivatives(self, ws_client: Optional[Any] = None) -> list[str]:
        """
        Scan all registered subscriptions (core derivatives and dynamic symbols),
        identify and unregister expired options and futures contracts.
        Permanent baseline equities and indices are strictly preserved.
        Purges expired ticks from memory and syncs state to disk.
        """
        purged: list[str] = []
        with self._lock:
            # Scan core derivatives (preserve CORE_BASE_SYMBOLS)
            for sym in list(self._core_symbols):
                if sym not in CORE_BASE_SYMBOLS and is_contract_expired(sym):
                    self._core_symbols.discard(sym)
                    purged.append(sym)

            # Scan dynamic symbols
            for sym in list(self._dynamic_symbols.keys()):
                if is_contract_expired(sym):
                    del self._dynamic_symbols[sym]
                    purged.append(sym)

            if purged:
                self._save_to_disk()

        if purged:
            logger.info(
                f"[WsSubManager] Cleanse purged {len(purged)} expired derivative contracts from registry"
            )
            # Unsubscribe from WebSocket
            client = ws_client
            if client is None:
                try:
                    from market.websocket import ws_manager

                    if ws_manager.connected:
                        client = ws_manager
                except Exception:
                    client = None

            if client and hasattr(client, "unsubscribe"):
                try:
                    client.unsubscribe(purged)
                except Exception as exc:
                    logger.warning(f"[WsSubManager] Failed to unsubscribe purged contracts: {exc}")

            # Purge from live tick cache in RAM
            try:
                from market.websocket import ws_manager

                ws_manager.purge_symbols(purged)
            except Exception as e_purge:
                logger.debug(f"[WsSubManager] Tick cache purge error: {e_purge}")

        return purged

    def cleanse_closed_session_derivatives(self, ws_client: Optional[Any] = None) -> list[str]:
        """
        At 15:30 IST market close, evict closed daytime NSE & BSE derivative contracts (CE/PE/FUT)
        from both core derivatives and dynamic subscriptions to liberate WebSocket slots and memory
        for evening commodity and currency trading.
        Permanent baseline equities, indices, and active MCX commodities are strictly preserved.
        """
        try:
            from market.calendar import is_market_open
            import os

            if is_market_open("NSE") and not os.environ.get("CHANAKYA_TESTING"):
                return []
        except Exception as e_mkt_open:
            logger.debug(
                f"[market.ws_subscription_manager] is_market_open suppressed: {e_mkt_open}"
            )

        def _is_closed_daytime_deriv(s: str) -> bool:
            return (s.startswith("NSE:") or s.startswith("BSE:")) and (
                s.endswith("CE") or s.endswith("PE") or s.endswith("FUT")
            )

        purged: list[str] = []
        with self._lock:
            # 1. Cleanse daytime NSE/BSE options and futures from dynamic subscriptions
            for sym in list(self._dynamic_symbols.keys()):
                if _is_closed_daytime_deriv(sym):
                    del self._dynamic_symbols[sym]
                    purged.append(sym)

            # 2. Cleanse daytime NSE/BSE options and futures from core subscriptions
            # (CORE_BASE_SYMBOLS like cash equities and benchmark indices are strictly preserved)
            for sym in list(self._core_symbols):
                if sym not in CORE_BASE_SYMBOLS and _is_closed_daytime_deriv(sym):
                    self._core_symbols.discard(sym)
                    purged.append(sym)

            if purged:
                self._save_to_disk()

        if purged:
            logger.info(
                f"[WsSubManager] Session cleanse purged {len(purged)} closed daytime NSE/BSE derivative contracts from live socket"
            )
            client = ws_client
            if client is None:
                try:
                    from market.websocket import ws_manager

                    if ws_manager.connected:
                        client = ws_manager
                except Exception as e_ws_lookup:
                    logger.debug(f"[WsSubManager] ws_manager lookup error: {e_ws_lookup}")
                    client = None

            if client and hasattr(client, "unsubscribe"):
                try:
                    client.unsubscribe(purged)
                except Exception as exc:
                    logger.warning(
                        f"[WsSubManager] Failed to unsubscribe closed daytime options/futures: {exc}"
                    )

            # Purge from live tick cache in RAM
            try:
                from market.websocket import ws_manager

                ws_manager.purge_symbols(purged)
            except Exception as e_purge:
                logger.debug(f"[WsSubManager] Tick cache purge error: {e_purge}")

        return purged

    def revolve_active_derivatives(
        self, ws_client: Optional[Any] = None, drift_pct_threshold: float = 1.0
    ) -> dict[str, Any]:
        """
        Active spot drift revolver for index options grid.
        Monitors underlying spots (NIFTY, BANKNIFTY, SENSEX, FINNIFTY, MIDCPNIFTY).
        If spot drifts >= drift_pct_threshold (default 1.0%), or upon initial anchor,
        regenerates ATM strike options grid, subscribes new strikes, and prunes stale expired items.
        """
        # Step 1: Always cleanse any expired contracts first
        cleansed = self.cleanse_expired_derivatives(ws_client=ws_client)

        revolved: list[str] = []
        underlying_spots: dict[str, float] = {}
        drift_detected = False

        from market.quotes import get_ltp

        indices = {
            "NIFTY": "NSE:NIFTY50-INDEX",
            "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
            "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX",
            "SENSEX": "BSE:SENSEX-INDEX",
            "FINNIFTY": "NSE:FINNIFTY-INDEX",
        }

        for idx_name, sym in indices.items():
            curr_ltp = get_ltp(sym) or get_ltp(idx_name)
            if not curr_ltp or curr_ltp <= 0:
                continue
            underlying_spots[idx_name] = curr_ltp
            anchored = self._anchored_spots.get(idx_name)
            if anchored is None:
                self._anchored_spots[idx_name] = curr_ltp
                drift_detected = True
                revolved.append(idx_name)
            else:
                pct_drift = abs(curr_ltp - anchored) / anchored * 100.0
                if pct_drift >= drift_pct_threshold:
                    self._anchored_spots[idx_name] = curr_ltp
                    drift_detected = True
                    revolved.append(idx_name)

        if drift_detected or not self._anchored_spots:
            self.seed_active_derivatives(ws_client=ws_client)

        return {
            "cleansed_count": len(cleansed),
            "cleansed_symbols": cleansed,
            "drift_detected": drift_detected,
            "revolved_indices": revolved,
            "anchored_spots": dict(self._anchored_spots),
            "total_subscribed": len(self.get_all_desired_subscriptions()),
        }

    def _save_to_disk(self) -> None:
        """Save active subscription list to disk."""
        path = _get_cache_path()
        try:
            with self._lock:
                payload = {
                    "core": list(self._core_symbols),
                    "dynamic": list(self._dynamic_symbols.keys()),
                }
            temp = path.with_name(f"{path.stem}_{os.getpid()}_{time.time_ns()}.tmp")
            with open(temp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            try:
                temp.replace(path)
            except Exception:
                # Fallback for Windows file locks
                if temp.exists():
                    try:
                        temp.unlink()
                    except Exception as e_suppressed:
                        logger.debug(
                            f"[market.ws_subscription_manager] Non-fatal exception suppressed: {e_suppressed}"
                        )
        except Exception as exc:
            logger.warning(f"[WsSubManager] Failed saving disk subscriptions: {exc}", exc_info=True)

    def remove_invalid_symbols(self, invalid_symbols: list[str]) -> None:
        """Purge invalid symbols returned by broker from core and dynamic subscriptions and persist."""
        with self._lock:
            changed = False
            for s in invalid_symbols:
                _WS_SYMBOL_BLACKLIST.add(s)
                if s in self._dynamic_symbols:
                    del self._dynamic_symbols[s]
                    changed = True
                if s in self._core_symbols:
                    self._core_symbols.discard(s)
                    changed = True
            if changed:
                self._save_to_disk()
                logger.info(
                    f"[WsSubManager] Purged {len(invalid_symbols)} invalid symbols from subscription registry and blacklisted: {invalid_symbols}"
                )

    def get_all_desired_subscriptions(self) -> list[str]:
        """Return full list of desired subscriptions (core + dynamic)."""
        with self._lock:
            all_syms = list(self._core_symbols) + list(self._dynamic_symbols.keys())
            return list(dict.fromkeys(all_syms))

    def add_subscriptions(self, symbols: list[str], ws_client: Optional[Any] = None) -> list[str]:
        """
        Add symbols to desired subscriptions.
        If capacity (180) exceeded, evicts oldest dynamic symbols.
        Subscribes to ws_client if provided.
        Returns list of newly added symbols.
        """
        import time
        from market.websocket import _to_ws_symbol, is_valid_ws_symbol

        now = time.time()
        to_add: list[str] = []
        to_evict: list[str] = []

        with self._lock:
            for s in symbols:
                ws_sym = _to_ws_symbol(s)
                if not is_valid_ws_symbol(ws_sym):
                    continue
                if ws_sym in self._core_symbols:
                    continue

                if ws_sym in self._dynamic_symbols:
                    # Move to end (most recently used)
                    self._dynamic_symbols.move_to_end(ws_sym)
                    self._dynamic_symbols[ws_sym] = now
                else:
                    self._dynamic_symbols[ws_sym] = now
                    to_add.append(ws_sym)

            # Check capacity
            current_total = len(self._core_symbols) + len(self._dynamic_symbols)
            while current_total > self._max_subscriptions and self._dynamic_symbols:
                oldest_sym, _ = self._dynamic_symbols.popitem(last=False)
                to_evict.append(oldest_sym)
                current_total -= 1

        if to_add or to_evict:
            self._save_to_disk()

        if ws_client:
            if to_evict:
                try:
                    ws_client.unsubscribe(to_evict)
                    logger.info(f"[WsSubManager] Evicted {len(to_evict)} LRU subscriptions")
                except Exception as exc:
                    logger.warning(
                        f"[WsSubManager] Failed to unsubscribe evicted: {exc}", exc_info=True
                    )
            if to_add:
                try:
                    if hasattr(ws_client, "subscribe"):
                        import inspect

                        sig = inspect.signature(ws_client.subscribe)
                        if "record_in_manager" in sig.parameters:
                            ws_client.subscribe(to_add, record_in_manager=False)
                        else:
                            ws_client.subscribe(to_add)
                except Exception as exc:
                    logger.warning(
                        f"[WsSubManager] Failed to subscribe new symbols: {exc}", exc_info=True
                    )

        return to_add

    def on_ws_connected(self, ws_client: Any) -> None:
        """Called upon WebSocket connection to restore all active subscriptions."""
        desired = self.get_all_desired_subscriptions()
        if desired and ws_client:
            try:
                if hasattr(ws_client, "subscribe"):
                    import inspect

                    sig = inspect.signature(ws_client.subscribe)
                    if "record_in_manager" in sig.parameters:
                        ws_client.subscribe(desired, record_in_manager=False)
                    else:
                        ws_client.subscribe(desired)
                logger.info(
                    f"[WsSubManager] Restored {len(desired)} WebSocket subscriptions on connection"
                )
            except Exception as exc:
                logger.warning(f"[WsSubManager] Error subscribing on connect: {exc}", exc_info=True)

    def get_diagnostics(self) -> dict[str, Any]:
        """Return WebSocket subscription capacity, metrics, and breakdown."""
        with self._lock:
            core_count = len(self._core_symbols)
            dynamic_count = len(self._dynamic_symbols)
            total = core_count + dynamic_count
            util_pct = (
                round(total / self._max_subscriptions * 100, 1) if self._max_subscriptions else 0.0
            )
            recent_dynamic = list(self._dynamic_symbols.keys())[-10:]
            return {
                "max_capacity": self._max_subscriptions,
                "total_subscribed": total,
                "core_count": core_count,
                "dynamic_count": dynamic_count,
                "utilization_pct": util_pct,
                "recent_symbols": recent_dynamic,
                "anchored_spots": dict(self._anchored_spots),
            }


# Global singleton
ws_subscription_manager = WsSubscriptionManager()


def get_ws_subscription_manager() -> WsSubscriptionManager:
    return ws_subscription_manager
