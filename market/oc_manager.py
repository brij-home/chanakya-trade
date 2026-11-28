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
        equity_refresh_interval_live: float = 120.0,
        max_dynamic_equities: int = 25,
        dynamic_equity_ttl: float = 900.0,
    ) -> None:
        self._refresh_interval_live = refresh_interval_live
        self._refresh_interval_closed = refresh_interval_closed
        self._equity_refresh_interval_live = max(
            refresh_interval_live, equity_refresh_interval_live
        )
        self._max_dynamic_equities = max(1, int(max_dynamic_equities))
        self._dynamic_equity_ttl = max(60.0, float(dynamic_equity_ttl))
        self._subscribed: set[str] = set(_DEFAULT_INDEX_SUBSCRIPTIONS)
        self._dynamic_equity_ts: dict[str, float] = {}
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_refresh_ts: dict[str, float] = {}

    def subscribe(self, underlying: str) -> None:
        """Subscribe an underlying symbol (index or stock) for background chain refreshes."""
        clean = (
            underlying.upper().replace("NSE:", "").replace("BSE:", "").replace("-INDEX", "").strip()
        )
        if not clean:
            return
        now = time.time()
        with self._lock:
            self._subscribed.add(clean)
            if clean not in _DEFAULT_INDEX_SUBSCRIPTIONS:
                self._dynamic_equity_ts[clean] = now
                if len(self._dynamic_equity_ts) > self._max_dynamic_equities:
                    oldest_sym = min(self._dynamic_equity_ts, key=self._dynamic_equity_ts.get)
                    self._dynamic_equity_ts.pop(oldest_sym, None)
                    self._subscribed.discard(oldest_sym)
        logger.debug(f"[OCM] Subscribed {clean} to options chain refresh manager")

    def unsubscribe(self, underlying: str) -> None:
        """Unsubscribe an underlying symbol (indices are permanently protected)."""
        clean = (
            underlying.upper().replace("NSE:", "").replace("BSE:", "").replace("-INDEX", "").strip()
        )
        if clean in _DEFAULT_INDEX_SUBSCRIPTIONS:
            return
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

    def get_cached_chain(
        self,
        underlying: str,
        expiry: Optional[str] = None,
        max_age_sec: float = 600.0,
    ) -> list[Any]:
        """Read directly from memory cache with live quote overlay. Never triggers synchronous broker REST calls."""
        from market.options import (
            _CHAIN_CACHE,
            _CHAIN_CACHE_LOCK,
            get_chain_cache_ttl,
            _overlay_live_quotes_on_chain,
        )
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
            prior = _CHAIN_CACHE.get(cache_key) or _CHAIN_CACHE.get(f"{clean_sym}:nearest")
            if prior and prior[1]:
                cached_at, cached_chain = prior
                ttl = get_chain_cache_ttl(
                    is_broker=True, is_empty=not bool(cached_chain), symbol=clean_sym
                )
                if (now - cached_at) < max(ttl, max_age_sec):
                    _overlay_live_quotes_on_chain(cached_chain)
                    return cached_chain
        return []

    def refresh_symbol(self, symbol: str, *, bypass_cache: bool = False) -> bool:
        """Refresh options chain for a single symbol and populate unified cache."""
        try:
            from market.fyers_circuit_breaker import get_fyers_circuit_breaker
            from brokers.session import get_all_brokers, get_data_broker_key

            if get_fyers_circuit_breaker().is_tripped():
                all_brks = get_all_brokers()
                pri_key = get_data_broker_key() or "fyers"
                has_secondary = any(
                    k != pri_key and not getattr(b, "_is_mock", False) for k, b in all_brks.items()
                )
                if not has_secondary:
                    return False

            from market.options import get_options_chain

            chain = get_options_chain(symbol, bypass_cache=bypass_cache)
            self._last_refresh_ts[symbol] = time.time()
            if chain:
                self._record_chain_iv_observation(symbol, chain)
            return bool(chain)
        except Exception as exc:
            logger.debug(f"[OCM] Options chain refresh error for {symbol}: {exc}")
            return False

    def _record_chain_iv_observation(self, symbol: str, chain: list[Any]) -> None:
        """Persist real daily constant-tenor 30D IV observation from refreshed chain."""
        try:
            from engine.iv_surface import (
                build_iv_surface_snapshot,
                compute_symbol_realized_vol_20d,
                extract_surface_inputs_from_chain,
                load_historical_30d_ivs,
                record_iv_observation,
            )
            from market.quotes import get_ltp

            clean = (
                symbol.upper().replace("NSE:", "").replace("BSE:", "").replace("-INDEX", "").strip()
            )
            exch = "BSE" if clean in ("SENSEX", "BANKEX") else "NSE"
            spot = float(get_ltp(f"{exch}:{clean}") or 0.0)
            if spot <= 0:
                return
            inputs = extract_surface_inputs_from_chain(chain, spot)
            if not inputs or not inputs.get("near_atm_iv"):
                return
            snap = build_iv_surface_snapshot(
                symbol=clean,
                near_atm_iv=inputs.get("near_atm_iv"),
                near_dte=inputs.get("near_dte"),
                next_atm_iv=inputs.get("next_atm_iv"),
                next_dte=inputs.get("next_dte"),
                iv_25d_put=inputs.get("iv_25d_put"),
                iv_25d_call=inputs.get("iv_25d_call"),
                historical_30d_ivs=load_historical_30d_ivs(clean),
                near_expiry=inputs.get("near_expiry"),
                next_expiry=inputs.get("next_expiry"),
                realized_vol_20d=compute_symbol_realized_vol_20d(clean),
            )
            record_iv_observation(snap)
            if clean not in _DEFAULT_INDEX_SUBSCRIPTIONS:
                try:
                    from market.fno_ban import update_intraday_futeq_for_symbol

                    update_intraday_futeq_for_symbol(clean, chain, spot=spot)
                except Exception as exc_fq:
                    logger.debug(f"[OCM] FutEq MWPL check skipped for {clean}: {exc_fq}")
        except Exception as exc_iv:
            logger.debug(f"[OCM] IV surface recording skipped for {symbol}: {exc_iv}")

    def _refresh_worker(self) -> None:
        """Sequential background loop refreshing all subscribed underlyings with rate-pacing."""
        while self._running:
            try:
                from market.calendar import is_market_open
                from config.market_universes import MCX_COMMODITY_SYMBOLS

                now_prune = time.time()
                with self._lock:
                    expired_eq = [
                        s
                        for s, touched_ts in list(self._dynamic_equity_ts.items())
                        if (now_prune - touched_ts) > self._dynamic_equity_ttl
                    ]
                    for s in expired_eq:
                        self._dynamic_equity_ts.pop(s, None)
                        self._subscribed.discard(s)
                    symbols_to_refresh = list(self._subscribed)

                for sym in symbols_to_refresh:
                    if not self._running:
                        break

                    clean_sym = (
                        sym.upper()
                        .replace("MCX:", "")
                        .replace("NSE:", "")
                        .replace("BSE:", "")
                        .strip()
                    )
                    is_commodity = clean_sym in MCX_COMMODITY_SYMBOLS or sym.upper().startswith(
                        "MCX:"
                    )
                    market_open = (
                        is_market_open("MCX")
                        if is_commodity
                        else (is_market_open("NFO") or is_market_open("NSE"))
                    )
                    if market_open:
                        interval = (
                            self._refresh_interval_live
                            if clean_sym in _DEFAULT_INDEX_SUBSCRIPTIONS
                            else self._equity_refresh_interval_live
                        )
                    else:
                        interval = self._refresh_interval_closed

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
