"""
market/ws_subscription_manager.py
─────────────────────────────────
Persistent WebSocket Subscription Manager with LRU Capacity Management.

Guarantees:
  1. Never exceeds Fyers 200 WebSocket subscription limit (safe ceiling: 180).
  2. Permanently maintains core benchmarks, commodities, and top F&O equities.
  3. Evicts least-recently-used dynamic scanner additions when limit is approached.
  4. Persists subscription state to disk so service restarts restore all feeds instantly.
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

MAX_WS_SUBSCRIPTIONS = 180

# Permanent base set: 10 indices/commodities + top 40 liquid F&O equities
CORE_BASE_SYMBOLS: list[str] = [
    "NSE:NIFTY50-INDEX",
    "NSE:NIFTYBANK-INDEX",
    "NSE:FINNIFTY-INDEX",
    "NSE:MIDCPNIFTY-INDEX",
    "BSE:SENSEX-INDEX",
    "NSE:INDIAVIX-INDEX",
    "MCX:CRUDEOIL",
    "MCX:NATURALGAS",
    "MCX:GOLD",
    "MCX:SILVER",
    # Top tier institutional equities
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


def _get_cache_path() -> Path:
    base = Path(os.environ.get("TRADING_PLATFORM_DATA") or (Path.home() / ".trading_platform"))
    cache_dir = base / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "ws_active_subscriptions.json"


class WsSubscriptionManager:
    """
    Manages WebSocket subscriptions with persistent state and LRU eviction.
    """

    def __init__(self, max_subscriptions: int = MAX_WS_SUBSCRIPTIONS) -> None:
        self._max_subscriptions = max_subscriptions
        self._lock = threading.Lock()
        self._core_symbols: set[str] = set(CORE_BASE_SYMBOLS)
        # Dynamic subscriptions tracked in OrderedDict for LRU eviction: symbol -> timestamp
        self._dynamic_symbols: OrderedDict[str, float] = OrderedDict()
        self._load_from_disk()

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
            with self._lock:
                for sym in loaded_dynamic:
                    if sym not in self._core_symbols:
                        self._dynamic_symbols[sym] = now
            logger.info(
                f"[WsSubManager] Restored {len(self._dynamic_symbols)} dynamic subscriptions from disk"
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
                    except Exception:
                        pass
        except Exception as exc:
            logger.warning(f"[WsSubManager] Failed saving disk subscriptions: {exc}", exc_info=True)

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
        from market.websocket import _to_ws_symbol

        now = time.time()
        to_add: list[str] = []
        to_evict: list[str] = []

        with self._lock:
            for s in symbols:
                ws_sym = _to_ws_symbol(s)
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
                ws_client.subscribe(desired)
                logger.info(
                    f"[WsSubManager] Restored {len(desired)} WebSocket subscriptions on connection"
                )
            except Exception as exc:
                logger.warning(f"[WsSubManager] Error subscribing on connect: {exc}", exc_info=True)


# Global singleton
ws_subscription_manager = WsSubscriptionManager()


def get_ws_subscription_manager() -> WsSubscriptionManager:
    return ws_subscription_manager
