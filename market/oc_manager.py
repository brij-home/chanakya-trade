"""
market/oc_manager.py
────────────────────
Centralized Options Chain Manager (Single Authority Refresher).

Decouples scanner loops and multi-agent detectors from direct broker REST calls.
Maintains scheduled background refresh for subscribed index & equity option chains,
populating the unified in-memory cache in market/options.py.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

logger = logging.getLogger("chanakya.market.oc_manager")

_DEFAULT_INDEX_SUBSCRIPTIONS = frozenset(
    {
        "NIFTY",
        "BANKNIFTY",
        "FINNIFTY",
        "MIDCPNIFTY",
        "SENSEX",
        "BANKEX",
    }
)


class OptionsChainManager:
    """
    Singleton authority managing scheduled background options chain refreshes.
    Prevents thundering herds from concurrent scanners and detectors.
    """

    def __init__(
        self,
        refresh_interval_live: float = 45.0,
        refresh_interval_closed: float = 180.0,
    ) -> None:
        self._refresh_interval_live = refresh_interval_live
        self._refresh_interval_closed = refresh_interval_closed
        self._subscribed: set[str] = set(_DEFAULT_INDEX_SUBSCRIPTIONS)
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_refresh_ts: dict[str, float] = {}

    def subscribe(self, underlying: str) -> None:
        """Subscribe an underlying symbol (index or stock) for background chain refreshes."""
        clean = (
            underlying.upper().replace("NSE:", "").replace("BSE:", "").replace("-INDEX", "").strip()
        )
        with self._lock:
            self._subscribed.add(clean)
        logger.debug(f"[OCM] Subscribed {clean} to options chain refresh manager")

    def unsubscribe(self, underlying: str) -> None:
        """Unsubscribe an underlying symbol."""
        clean = (
            underlying.upper().replace("NSE:", "").replace("BSE:", "").replace("-INDEX", "").strip()
        )
        with self._lock:
            self._subscribed.discard(clean)
        logger.debug(f"[OCM] Unsubscribed {clean} from options chain refresh manager")

    @property
    def subscribed_symbols(self) -> set[str]:
        with self._lock:
            return set(self._subscribed)

    def start(self) -> None:
        """Start the background refresh daemon thread."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(
                target=self._refresh_worker, daemon=True, name="OptionsChainManager-Worker"
            )
            self._thread.start()
            logger.info("[OCM] Options Chain Manager background worker started")

    def stop(self) -> None:
        """Stop the background refresh worker."""
        with self._lock:
            self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            logger.info("[OCM] Options Chain Manager background worker stopped")

    def get_cached_chain(self, underlying: str, expiry: Optional[str] = None) -> list[Any]:
        """Read directly from memory cache. Never triggers synchronous broker REST calls."""
        from market.options import _CHAIN_CACHE, _CHAIN_CACHE_LOCK, get_chain_cache_ttl
        from market.instruments import resolve_corporate_alias

        clean_sym = (
            underlying.upper()
            .replace("MCX:", "")
            .replace("CDS:", "")
            .replace("NFO:", "")
            .replace("NSE:", "")
            .replace("BSE:", "")
            .replace("-INDEX", "")
            .strip()
        )
        clean_sym = resolve_corporate_alias(clean_sym)
        cache_key = f"{clean_sym}:{expiry or 'nearest'}"
        now = time.time()
        with _CHAIN_CACHE_LOCK:
            if cache_key in _CHAIN_CACHE:
                cached_at, cached_chain = _CHAIN_CACHE[cache_key]
                ttl = get_chain_cache_ttl(
                    is_broker=True, is_empty=not bool(cached_chain), symbol=clean_sym
                )
                if (now - cached_at) < ttl:
                    return cached_chain
        return []

    def refresh_symbol(self, symbol: str) -> bool:
        """Refresh options chain for a single symbol and populate unified cache."""
        try:
            from market.fyers_circuit_breaker import get_fyers_circuit_breaker

            if get_fyers_circuit_breaker().is_tripped():
                return False

            from market.options import get_options_chain

            chain = get_options_chain(symbol, bypass_cache=True)
            self._last_refresh_ts[symbol] = time.time()
            return bool(chain)
        except Exception as exc:
            logger.debug(f"[OCM] Options chain refresh error for {symbol}: {exc}")
            return False

    def _refresh_worker(self) -> None:
        """Sequential background loop refreshing all subscribed underlyings with rate-pacing."""
        while self._running:
            try:
                from market.calendar import is_market_open

                market_open = is_market_open("NFO") or is_market_open("NSE")
                interval = (
                    self._refresh_interval_live if market_open else self._refresh_interval_closed
                )

                symbols_to_refresh = list(self.subscribed_symbols)

                for sym in symbols_to_refresh:
                    if not self._running:
                        break

                    now = time.time()
                    last_ts = self._last_refresh_ts.get(sym, 0.0)
                    if now - last_ts >= interval:
                        self.refresh_symbol(sym)
                        # Micro-pacing between consecutive options chains (0.5s)
                        time.sleep(0.5)

            except Exception as e:
                logger.warning(f"[OCM] Refresh loop error: {e}", exc_info=True)

            # Sleep short intervals to remain responsive to stop()
            for _ in range(10):
                if not self._running:
                    break
                time.sleep(1.0)


_oc_manager = OptionsChainManager()


def get_oc_manager() -> OptionsChainManager:
    return _oc_manager
