"""
market/ws_subscription_manager.py
─────────────────────────────────
Persistent WebSocket Subscription Manager with LRU Capacity Management.

Fyers API Hard Constraints & Architecture:
  - WebSocket Data Socket supports up to 5,000 symbols concurrent real-time stream.
  - REST API rate limit is strictly 10 requests / sec, 200 requests / min.
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
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

MAX_WS_SUBSCRIPTIONS = 5000  # FYERS API v3 Data Socket supports up to 5,000 symbols concurrently

# Permanent base set: key indices/commodities + top liquid institutional equities
CORE_BASE_SYMBOLS: list[str] = [
    # Benchmark & Sectoral Indices
    "NSE:NIFTY50-INDEX",
    "NSE:NIFTYBANK-INDEX",
    "NSE:FINNIFTY-INDEX",
    "NSE:MIDCPNIFTY-INDEX",
    "BSE:SENSEX-INDEX",
    "BSE:BANKEX-INDEX",
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
    "NSE:TATAMOTORS-EQ",
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

# Dynamically populate liquid taxonomy equities from analysis.universe if available
try:
    from analysis.universe import SECTOR_TAXONOMY

    for _sec_info in SECTOR_TAXONOMY.values():
        for _s in _sec_info.get("symbols", []):
            _eq_sym = f"NSE:{_s}-EQ"
            if _eq_sym not in CORE_BASE_SYMBOLS:
                CORE_BASE_SYMBOLS.append(_eq_sym)
except Exception as e:
    logger.warning(f"Could not load SECTOR_TAXONOMY into CORE_BASE_SYMBOLS: {e}")

from config.paths import app_data_path


import re

_VALID_OPTION_RE = re.compile(
    r"^[A-Za-z0-9_&]+?(\d{2})([A-Za-z]{3}|[1-9ONDond]\d{2}|\d{4})(\d+)(CE|PE)$"
)

# Known blacklisted/delisted symbols that Fyers socket rejects with -300
_WS_SYMBOL_BLACKLIST = {
    "NSE:NIFTYFPI-INDEX",
    "NSE:ZOMATO-EQ",
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
    if (s.startswith("NSE:") or s.startswith("BSE:")) and "-" in clean_name:
        if not clean_name.endswith(("-EQ", "-INDEX", "-BE", "-SM", "-BZ", "-GB")):
            return False

    return True


def get_active_index_options_grid(num_strikes_per_side: int = 8) -> list[str]:
    """
    Generate active Index Options contracts for NIFTY, BANKNIFTY, MIDCPNIFTY, SENSEX, and FINNIFTY.
    Generates ATM ± num_strikes_per_side strikes for each index (~170 contracts).
    """
    from datetime import datetime, timedelta

    now = datetime.now()
    target_dt = now if now.day <= 24 else now + timedelta(days=10)
    month_suffix = target_dt.strftime("%y%b").upper()

    estimated_spots = {
        "NIFTY": ("NSE", 25000.0, 50, num_strikes_per_side),
        "BANKNIFTY": ("NSE", 52000.0, 100, num_strikes_per_side),
        "MIDCPNIFTY": ("NSE", 13200.0, 25, num_strikes_per_side),
        "SENSEX": ("BSE", 81500.0, 100, max(4, num_strikes_per_side - 2)),
        "FINNIFTY": ("NSE", 24000.0, 50, max(4, num_strikes_per_side - 3)),
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

    grid: list[str] = []
    for idx_name, (exch, spot, step, n_stk) in estimated_spots.items():
        atm_strike = int(round(spot / float(step)) * step)
        for offset in range(-n_stk, n_stk + 1):
            strike = atm_strike + (offset * step)
            grid.append(f"{exch}:{idx_name}{month_suffix}{strike}CE")
            grid.append(f"{exch}:{idx_name}{month_suffix}{strike}PE")

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

    return grid


def get_active_commodity_grid() -> list[str]:
    """
    Generate active MCX Commodity and Currency CDS futures and near ATM options.
    """
    from datetime import datetime, timedelta

    now = datetime.now()
    c_dt = now if now.day <= 18 else now + timedelta(days=20)
    c_suffix = c_dt.strftime("%y%b").upper()

    from brokers.fyers import _resolve_commodity_contract, _resolve_currency_contract

    comm_symbols = [
        _resolve_commodity_contract("CRUDEOIL"),
        _resolve_commodity_contract("NATURALGAS"),
        _resolve_commodity_contract("GOLD"),
        _resolve_commodity_contract("SILVER"),
        _resolve_commodity_contract("COPPER"),
        _resolve_commodity_contract("ZINC"),
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

    for offset in (-2, -1, 0, 1, 2):
        stk = crude_atm + (offset * 50)
        comm_symbols.append(f"MCX:CRUDEOIL{c_suffix}{stk}CE")
        comm_symbols.append(f"MCX:CRUDEOIL{c_suffix}{stk}PE")

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
        """Load persisted subscriptions from previous run."""
        path = _get_cache_path()
        if not path.exists():
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            loaded_dynamic = data.get("dynamic", [])
            import time

            now = time.time()
            sanitized_needed = False
            with self._lock:
                for sym in loaded_dynamic:
                    if not is_valid_ws_symbol(sym):
                        sanitized_needed = True
                        continue
                    if sym not in self._core_symbols:
                        self._dynamic_symbols[sym] = now
            if sanitized_needed:
                self._save_to_disk()
            logger.info(
                f"[WsSubManager] Restored {len(self._dynamic_symbols)} dynamic subscriptions from disk (sanitized={sanitized_needed})"
            )
        except Exception as exc:
            logger.warning(
                f"[WsSubManager] Failed loading disk subscriptions from {path}: {exc}",
                exc_info=True,
            )

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
                if s in self._dynamic_symbols:
                    del self._dynamic_symbols[s]
                    changed = True
                if s in self._core_symbols:
                    self._core_symbols.discard(s)
                    changed = True
            if changed:
                self._save_to_disk()
                logger.info(
                    f"[WsSubManager] Purged {len(invalid_symbols)} invalid symbols from subscription registry: {invalid_symbols}"
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
            }


# Global singleton
ws_subscription_manager = WsSubscriptionManager()


def get_ws_subscription_manager() -> WsSubscriptionManager:
    return ws_subscription_manager
