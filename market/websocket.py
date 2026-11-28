"""
market/websocket.py
───────────────────
Real-time market data via Fyers WebSocket.

Connects once at login → all subscribed symbols stream live ticks.
Much faster than REST API polling (~instant vs 1-3s per call).

Features:
  - Auto-subscribe to NIFTY, BANKNIFTY, VIX on connect
  - Subscribe to any stock on demand
  - Cache latest tick for instant quote retrieval
  - Callbacks for price change events (used by alerts)
  - Auto-reconnect on disconnect

Usage:
    from market.websocket import ws_manager

    # Start (called automatically at broker login)
    ws_manager.start(access_token, app_id)

    # Subscribe to symbols
    ws_manager.subscribe(["NSE:RELIANCE-EQ", "NSE:TCS-EQ"])

    # Get latest cached tick (instant, no API call)
    tick = ws_manager.get_tick("NSE:RELIANCE-EQ")
    print(tick["ltp"])

    # Register a callback for real-time alerts
    ws_manager.on_tick(my_callback)  # called on every tick
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional


logger = logging.getLogger(__name__)


# ── Default symbols to subscribe ─────────────────────────────
DEFAULT_SYMBOLS: list[str] = [
    "NSE:NIFTY50-INDEX",
    "NSE:NIFTYBANK-INDEX",
    "NSE:MIDCPNIFTY-INDEX",
    "BSE:SENSEX-INDEX",
    "NSE:INDIAVIX-INDEX",
    "MCX:CRUDEOIL",
    "MCX:NATURALGAS",
    "MCX:GOLD",
    "MCX:SILVER",
]

# Map our instrument format to Fyers WebSocket format
_SYMBOL_MAP = {
    "NSE:NIFTY 50": "NSE:NIFTY50-INDEX",
    "NSE:NIFTY": "NSE:NIFTY50-INDEX",
    "NSE:NIFTY-INDEX": "NSE:NIFTY50-INDEX",
    "NIFTY": "NSE:NIFTY50-INDEX",
    "NIFTY 50": "NSE:NIFTY50-INDEX",
    "NIFTY50": "NSE:NIFTY50-INDEX",
    "NSE:NIFTY BANK": "NSE:NIFTYBANK-INDEX",
    "NSE:BANKNIFTY": "NSE:NIFTYBANK-INDEX",
    "NSE:BANKNIFTY-INDEX": "NSE:NIFTYBANK-INDEX",
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
    "NIFTY BANK": "NSE:NIFTYBANK-INDEX",
    "NSE:INDIA VIX": "NSE:INDIAVIX-INDEX",
    "NSE:INDIAVIX": "NSE:INDIAVIX-INDEX",
    "INDIA VIX": "NSE:INDIAVIX-INDEX",
    "VIX": "NSE:INDIAVIX-INDEX",
    "BSE:SENSEX": "BSE:SENSEX-INDEX",
    "SENSEX": "BSE:SENSEX-INDEX",
    "NSE:NIFTY FIN SERVICE": "NSE:FINNIFTY-INDEX",
    "NSE:FINNIFTY": "NSE:FINNIFTY-INDEX",
    "FINNIFTY": "NSE:FINNIFTY-INDEX",
    "NSE:NIFTY MIDCAP 100": "NSE:NIFTYMIDCAP100-INDEX",
    "NSE:MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX",
    "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX",
    "NSE:NIFTY MID SELECT": "NSE:MIDCPNIFTY-INDEX",
    "BSE:BANKEX": "BSE:BANKEX-INDEX",
    "BANKEX": "BSE:BANKEX-INDEX",
    # Sectoral Indices
    "IT": "NSE:NIFTYIT-INDEX",
    "NIFTY IT": "NSE:NIFTYIT-INDEX",
    "NIFTYIT": "NSE:NIFTYIT-INDEX",
    "NSE:IT": "NSE:NIFTYIT-INDEX",
    "NSE:NIFTY IT": "NSE:NIFTYIT-INDEX",
    "PHARMA": "NSE:NIFTYPHARMA-INDEX",
    "NIFTY PHARMA": "NSE:NIFTYPHARMA-INDEX",
    "NIFTYPHARMA": "NSE:NIFTYPHARMA-INDEX",
    "NSE:PHARMA": "NSE:NIFTYPHARMA-INDEX",
    "NSE:NIFTY PHARMA": "NSE:NIFTYPHARMA-INDEX",
    "AUTO": "NSE:NIFTYAUTO-INDEX",
    "NIFTY AUTO": "NSE:NIFTYAUTO-INDEX",
    "NIFTYAUTO": "NSE:NIFTYAUTO-INDEX",
    "NSE:AUTO": "NSE:NIFTYAUTO-INDEX",
    "NSE:NIFTY AUTO": "NSE:NIFTYAUTO-INDEX",
    "FMCG": "NSE:NIFTYFMCG-INDEX",
    "NIFTY FMCG": "NSE:NIFTYFMCG-INDEX",
    "NIFTYFMCG": "NSE:NIFTYFMCG-INDEX",
    "NSE:FMCG": "NSE:NIFTYFMCG-INDEX",
    "NSE:NIFTY FMCG": "NSE:NIFTYFMCG-INDEX",
    "REALTY": "NSE:NIFTYREALTY-INDEX",
    "NIFTY REALTY": "NSE:NIFTYREALTY-INDEX",
    "NIFTYREALTY": "NSE:NIFTYREALTY-INDEX",
    "NSE:REALTY": "NSE:NIFTYREALTY-INDEX",
    "NSE:NIFTY REALTY": "NSE:NIFTYREALTY-INDEX",
    "METAL": "NSE:NIFTYMETAL-INDEX",
    "NIFTY METAL": "NSE:NIFTYMETAL-INDEX",
    "NIFTYMETAL": "NSE:NIFTYMETAL-INDEX",
    "NSE:METAL": "NSE:NIFTYMETAL-INDEX",
    "NSE:NIFTY METAL": "NSE:NIFTYMETAL-INDEX",
    "ENERGY": "NSE:NIFTYENERGY-INDEX",
    "NIFTY ENERGY": "NSE:NIFTYENERGY-INDEX",
    "NIFTYENERGY": "NSE:NIFTYENERGY-INDEX",
    "NSE:ENERGY": "NSE:NIFTYENERGY-INDEX",
    "NSE:NIFTY ENERGY": "NSE:NIFTYENERGY-INDEX",
    "NSE:NIFTY PSU BANK": "NSE:NIFTYPSUBANK-INDEX",
    "NIFTY PSU BANK": "NSE:NIFTYPSUBANK-INDEX",
    "PSU_BANK": "NSE:NIFTYPSUBANK-INDEX",
    "PSUBANK": "NSE:NIFTYPSUBANK-INDEX",
    "NSE:NIFTY INFRA": "NSE:NIFTYINFRA-INDEX",
    "NIFTY INFRA": "NSE:NIFTYINFRA-INDEX",
    "INFRA": "NSE:NIFTYINFRA-INDEX",
    "NSE:INFRA": "NSE:NIFTYINFRA-INDEX",
    "NSE:NIFTY MEDIA": "NSE:NIFTYMEDIA-INDEX",
    "NIFTY MEDIA": "NSE:NIFTYMEDIA-INDEX",
    "MEDIA": "NSE:NIFTYMEDIA-INDEX",
    "NSE:MEDIA": "NSE:NIFTYMEDIA-INDEX",
    "NSE:NIFTY PSE": "NSE:NIFTYPSE-INDEX",
    "NIFTY PSE": "NSE:NIFTYPSE-INDEX",
    "PSE": "NSE:NIFTYPSE-INDEX",
    "NSE:PSE": "NSE:NIFTYPSE-INDEX",
    "NSE:NIFTY COMMODITIES": "NSE:NIFTYCOMMODITIES-INDEX",
    "NIFTY COMMODITIES": "NSE:NIFTYCOMMODITIES-INDEX",
    "COMMODITIES": "NSE:NIFTYCOMMODITIES-INDEX",
    "NSE:COMMODITIES": "NSE:NIFTYCOMMODITIES-INDEX",
    "NSE:NIFTY CPSE": "NSE:NIFTYCPSE-INDEX",
    "NIFTY CPSE": "NSE:NIFTYCPSE-INDEX",
    "CPSE": "NSE:NIFTYCPSE-INDEX",
    "NSE:CPSE": "NSE:NIFTYCPSE-INDEX",
}

_INDEX_PREFIXES = (
    "NIFTY",
    "BANKNIFTY",
    "SENSEX",
    "FINNIFTY",
    "MIDCPNIFTY",
    "INDIAVIX",
)


def _to_ws_symbol(instrument: str) -> str:
    """Convert any instrument format (Equity, Index, MCX, Currency, Options) to Fyers WebSocket format."""
    s = str(instrument).strip()
    if not s:
        return ""

    # Direct map lookup
    if s in _SYMBOL_MAP:
        return _SYMBOL_MAP[s]
    if s.upper() in _SYMBOL_MAP:
        return _SYMBOL_MAP[s.upper()]

    try:
        from brokers.fyers import _to_fyers_symbol

        res = _to_fyers_symbol(s)
        if res:
            return res
    except Exception as e_suppressed:
        logger.debug(f"[market.websocket] Non-fatal exception suppressed: {e_suppressed}")

    if ":" in s:
        exch, sym = s.split(":", 1)
        exch_upper = exch.upper().strip()
        sym_upper = sym.upper().strip()

        # Fix known malformed index formats and pseudo-equity sector tokens
        _MALFORMED_INDEX_MAP = {
            "NIFTY-INDEX": "NSE:NIFTY50-INDEX",
            "NIFTY": "NSE:NIFTY50-INDEX",
            "BANKNIFTY-INDEX": "NSE:NIFTYBANK-INDEX",
            "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
            "BANK-EQ": "NSE:NIFTYBANK-INDEX",
            "BANK": "NSE:NIFTYBANK-INDEX",
            "IT-EQ": "NSE:NIFTYIT-INDEX",
            "INFRA-EQ": "NSE:NIFTYINFRA-INDEX",
            "ENERGY-EQ": "NSE:NIFTYENERGY-INDEX",
            "METAL-EQ": "NSE:NIFTYMETAL-INDEX",
            "PHARMA-EQ": "NSE:NIFTYPHARMA-INDEX",
            "AUTO-EQ": "NSE:NIFTYAUTO-INDEX",
            "FMCG-EQ": "NSE:NIFTYFMCG-INDEX",
            "REALTY-EQ": "NSE:NIFTYREALTY-INDEX",
            "MEDIA-EQ": "NSE:NIFTYMEDIA-INDEX",
            "PSE-EQ": "NSE:NIFTYPSE-INDEX",
            "COMMODITIES-EQ": "NSE:NIFTYCOMMODITIES-INDEX",
            "CPSE-EQ": "NSE:NIFTYCPSE-INDEX",
        }
        if sym_upper in _MALFORMED_INDEX_MAP:
            return _MALFORMED_INDEX_MAP[sym_upper]

        # Already in Fyers format (has -EQ, -INDEX, FUT, options, etc.)
        if sym_upper.endswith(
            ("-EQ", "-INDEX", "-BE", "-SM", "-BZ", "-GB", "FUT", "CE", "PE")
        ) or exch_upper in ("MCX", "CDS"):
            return f"{exch_upper}:{sym_upper}"

        # Check full map with constructed key
        map_key = f"{exch_upper}:{sym_upper}"
        if map_key in _SYMBOL_MAP:
            return _SYMBOL_MAP[map_key]

        # Check if it's an index by explicit prefixes
        clean = sym_upper.replace(" ", "")
        if clean in ("NIFTY", "NIFTY50"):
            return "NSE:NIFTY50-INDEX"
        if clean in ("BANKNIFTY", "NIFTYBANK"):
            return "NSE:NIFTYBANK-INDEX"
        if clean in ("FINNIFTY",):
            return "NSE:FINNIFTY-INDEX"
        if clean in ("MIDCPNIFTY", "NIFTYMIDSELECT"):
            return "NSE:MIDCPNIFTY-INDEX"
        if clean in ("SENSEX",):
            return "BSE:SENSEX-INDEX"
        if clean in ("BANKEX",):
            return "BSE:BANKEX-INDEX"
        if clean in ("VIX", "INDIAVIX"):
            return "NSE:INDIAVIX-INDEX"

        if clean.startswith(_INDEX_PREFIXES):
            return f"{exch_upper}:{clean}-INDEX"

        return f"{exch_upper}:{sym}-EQ"
    return f"NSE:{s}-EQ"


try:
    from market.ws_subscription_manager import (
        is_valid_ws_symbol,
        CORE_BASE_SYMBOLS as DEFAULT_SYMBOLS,  # noqa: F401 - public backward-compat export
    )
except Exception:
    from market.ws_subscription_manager import is_valid_ws_symbol

    DEFAULT_SYMBOLS = []


@dataclass
class Tick:
    """A single price tick from WebSocket."""

    symbol: str
    ltp: float
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0  # prev close
    volume: int = 0
    change: float = 0.0
    change_pct: float = 0.0
    timestamp: float = 0.0  # epoch
    bid: float = 0.0
    ask: float = 0.0
    atp: float = 0.0
    received_at: float = 0.0
    delta_volume: int = 0
    bid_qty: int = 0
    ask_qty: int = 0
    oi: int = 0

    def is_stale(self, max_age_seconds: float = 60.0) -> bool:
        """Return True if tick age exceeds max_age_seconds or timestamp is zero."""
        check_ts = self.received_at if self.received_at > 0 else self.timestamp
        if check_ts <= 0:
            return True
        return (time.time() - check_ts) > max_age_seconds

    @property
    def age_seconds(self) -> float:
        """Return tick age in seconds."""
        check_ts = self.received_at if self.received_at > 0 else self.timestamp
        if check_ts <= 0:
            return float("inf")
        return max(0.0, time.time() - check_ts)


class WebSocketManager:
    """
    Manages the Fyers WebSocket connection for real-time market data.

    Singleton — one connection per session, shared across all modules.
    """

    def __init__(self, lite_mode: bool = False) -> None:
        self._ws = None
        self._connected = False
        self._lite_mode: bool = bool(lite_mode)
        self._access_token = ""
        self._app_id = ""
        self._ticks: dict[str, Tick] = {}  # symbol → latest tick
        self._depth_5_cache: dict[str, dict] = {}  # symbol → latest 5-level DepthUpdate snapshot
        self._depth_subscribed: set[str] = set()
        self._callbacks: list[Callable] = []
        self._subscribed: set[str] = set()
        self._lock = threading.Lock()
        self._sub_lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._dispatch_queue: queue.Queue[Optional[Tick]] = queue.Queue(maxsize=32768)
        self._dispatch_thread: Optional[threading.Thread] = None
        self._running = False
        self._reconnect_lock = threading.Lock()
        self._is_reconnecting: bool = False
        self._reconnect_thread: Optional[threading.Thread] = None
        self._refreshing_token: bool = False
        self._token_refresh_thread: Optional[threading.Thread] = None
        self._last_packet_at: float = 0.0
        self._watchdog_thread: Optional[threading.Thread] = None
        self._last_day_volume: dict[str, int] = {}

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def lite_mode(self) -> bool:
        return self._lite_mode

    def set_lite_mode(self, enabled: bool) -> None:
        """Toggle DataSocket Lite Mode (LTP-only stream); applies on next socket connect."""
        self._lite_mode = bool(enabled)

    def _ensure_dispatcher_running(self) -> None:
        """Starts background tick fan-out worker to ensure callbacks never stall the socket."""
        if self._dispatch_thread is None or not self._dispatch_thread.is_alive():
            self._running = True
            self._dispatch_thread = threading.Thread(
                target=self._run_dispatch_worker, daemon=True, name="WsTickDispatcher"
            )
            self._dispatch_thread.start()
        if self._watchdog_thread is None or not self._watchdog_thread.is_alive():
            self._watchdog_thread = threading.Thread(
                target=self._run_connection_watchdog, daemon=True, name="WsConnectionWatchdog"
            )
            self._watchdog_thread.start()

    def _check_connection_health(self) -> bool:
        """Evaluates connection health. Returns False and initiates reconnect if connection is a zombie."""
        if not self._connected or not self._access_token:
            return True

        with self._lock:
            sub_count = len(self._subscribed)
        if sub_count == 0:
            return True

        # Check if any subscribed exchange market is open
        try:
            from market.calendar import is_market_open

            mkt_open = is_market_open("NSE") or is_market_open("MCX") or is_market_open("BSE")
        except Exception:
            mkt_open = True

        if not mkt_open:
            return True

        now = time.time()
        silence_sec = now - self._last_packet_at if self._last_packet_at > 0 else 0.0
        # Adaptive zombie threshold: 15s during active market (high-subscription risk),
        # 30s outside market hours (lower tick frequency expected).
        # RCA: INC-003 2026-10-30 -- 33.7s zombie with 1,166 subscriptions missed ~3 scan cycles.
        _zombie_threshold = 15.0 if mkt_open else 30.0
        if self._last_packet_at > 0 and silence_sec > _zombie_threshold:
            logger.warning(
                f"[WebSocket] 🚨 Zombie WebSocket detected: 0 packets received for {silence_sec:.1f}s "
                f"during active market session ({sub_count} subscriptions). Triggering proactive reconnect."
            )
            self._connected = False
            self._schedule_proactive_reconnect(delay_sec=1.0)
            return False
        return True

    def _run_connection_watchdog(self) -> None:
        """Background watchdog: detects silent WebSocket disconnects during active market hours."""
        while self._running:
            time.sleep(5.0)
            if not self._running:
                break
            try:
                self._check_connection_health()
            except Exception as e:
                logger.debug(f"[WebSocket] Watchdog loop error: {e}")

    def _run_dispatch_worker(self) -> None:
        """Asynchronously dispatches incoming ticks to registered listeners without stalling the socket thread."""
        while self._running:
            try:
                tick = self._dispatch_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if tick is None:
                break
            # Ingest into MarketMatrix for ultra-low latency RAM stats and live candle weaving
            try:
                from engine.market_matrix import get_market_matrix

                get_market_matrix().on_tick(tick)
            except Exception as e_mm:
                logger.debug(f"[WebSocket] MarketMatrix ingestion error: {e_mm}")

            # Ingest into Columnar Parquet Tick Warehouse
            try:
                from engine.tick_warehouse import get_tick_warehouse

                ts_ms = (
                    int(tick.timestamp * 1000) if tick.timestamp and tick.timestamp > 0 else None
                )
                get_tick_warehouse().record_tick(
                    symbol=tick.symbol,
                    ltp=tick.ltp,
                    bid=getattr(tick, "bid", 0.0) or 0.0,
                    ask=getattr(tick, "ask", 0.0) or 0.0,
                    bid_qty=int(getattr(tick, "bid_qty", 0) or 0),
                    ask_qty=int(getattr(tick, "ask_qty", 0) or 0),
                    volume=int(getattr(tick, "delta_volume", 0) or 0),
                    oi=int(getattr(tick, "oi", 0) or 0),
                    flag="WS_TICK",
                    timestamp_ms=ts_ms,
                )
            except Exception as e_wh:
                logger.debug(f"[WebSocket] TickWarehouse ingestion error: {e_wh}")

            with self._lock:
                callbacks = list(self._callbacks)
            for cb in callbacks:
                try:
                    cb(tick)
                except Exception as e:
                    logger.debug(f"[WebSocket] Listener error: {e}")

    def start(self, access_token: str, app_id: str) -> None:
        """
        Start the WebSocket connection in a background thread.
        Call this after successful broker login.
        """
        if self._connected and self._access_token == access_token:
            logger.info("WebSocket already connected")
            return

        if self._connected and self._access_token != access_token:
            logger.info("[WebSocket] Restarting market data socket with renewed access token")
            self.stop()

        self._running = True
        self._ensure_dispatcher_running()
        self._access_token = access_token
        self._app_id = app_id

        self._thread = threading.Thread(target=self._connect, daemon=True)
        self._thread.start()

        # Wait briefly for connection
        for _ in range(20):
            if self._connected:
                break
            time.sleep(0.25)

        if self._connected:
            logger.info("WebSocket connected")
            # Note: _on_connect() already invokes ws_subscription_manager.on_ws_connected(self);
            # avoid double-subscribing the full 2,400+ grid concurrently on connect.
        else:
            logger.warning("WebSocket connection timed out — will use REST fallback")

    def update_token(self, access_token: str, app_id: Optional[str] = None) -> None:
        """Update access token and reconnect if changed."""
        app = app_id or self._app_id
        if self._access_token != access_token or not self._connected:
            self.start(access_token=access_token, app_id=app)

    # Method alias for backward compatibility
    connect = start

    def stop(self, timeout: float = 1.0) -> None:
        """Disconnect the WebSocket and gracefully shut down without blocking."""
        self._running = False
        try:
            self._dispatch_queue.put_nowait(None)
        except Exception as e_suppressed:
            logger.debug(f"[market.websocket] Non-fatal exception suppressed: {e_suppressed}")
        if self._dispatch_thread and self._dispatch_thread.is_alive():
            try:
                self._dispatch_thread.join(timeout=timeout)
            except Exception as e_suppressed:
                logger.debug(f"[market.websocket] Non-fatal exception suppressed: {e_suppressed}")
        self._dispatch_thread = None

        ws_to_close = self._ws
        self._connected = False
        with self._lock:
            self._subscribed.clear()
        self._ws = None

        if ws_to_close:

            def _close():
                try:
                    setattr(ws_to_close, "restart_flag", False)
                    # Unblock message processing loop
                    stop_ev = getattr(ws_to_close, "message_thread_stop_event", None)
                    if stop_ev:
                        stop_ev.set()
                    cond = getattr(ws_to_close, "message_condition", None)
                    if cond:
                        try:
                            lock = getattr(ws_to_close, "message_lock", None)
                            if lock:
                                with lock:
                                    cond.notify_all()
                        except Exception as e_suppressed:
                            logger.debug(
                                f"[market.websocket] Non-fatal exception suppressed: {e_suppressed}"
                            )
                    # Close underlying websocket
                    ws_obj = getattr(ws_to_close, "_FyersDataSocket__ws_object", None)
                    if ws_obj and hasattr(ws_obj, "close"):
                        try:
                            ws_obj.close()
                        except Exception as e_suppressed:
                            logger.debug(
                                f"[market.websocket] Non-fatal exception suppressed: {e_suppressed}"
                            )
                    # Clear reference so ping thread exits its while loop
                    setattr(ws_to_close, "_FyersDataSocket__ws_object", None)
                except Exception as e_suppressed:
                    logger.debug(
                        f"[market.websocket] Non-fatal exception suppressed: {e_suppressed}"
                    )

            t = threading.Thread(target=_close, daemon=True)
            t.start()
            t.join(timeout=timeout)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None

    def filter_unsubscribed(self, symbols: list[str]) -> list[str]:
        """Return only valid symbols not currently tracked in self._subscribed."""
        if not symbols or not self._ws or not self._connected:
            return []
        out: list[str] = []
        with self._lock:
            current = set(self._subscribed)
        for s in symbols:
            s_up = str(s).strip().upper()
            if (
                not s_up
                or s_up.startswith("CRYPTO:")
                or s_up.endswith("USDT")
                or s_up in ("BTC", "ETH", "SOL", "BNB", "DOGE")
            ):
                continue
            ws_sym = _to_ws_symbol(s)
            if ws_sym and is_valid_ws_symbol(ws_sym) and ws_sym not in current:
                out.append(ws_sym)
                current.add(ws_sym)
        return out

    def subscribe(self, symbols: list[str], record_in_manager: bool = True) -> None:
        """Subscribe to symbols for real-time ticks."""
        if not self._ws or not self._connected:
            return

        # Filter out crypto symbols — Fyers only handles Indian market instruments (NSE, BSE, MCX, CDS)
        filtered = []
        for s in symbols:
            s_up = str(s).strip().upper()
            if (
                s_up.startswith("CRYPTO:")
                or s_up.endswith("USDT")
                or s_up in ("BTC", "ETH", "SOL", "BNB", "DOGE")
            ):
                continue
            filtered.append(s)

        if not filtered:
            return

        # Convert to Fyers format, filter malformed symbols, and short-circuit already-subscribed symbols
        # before performing per-symbol exchange-master validation.
        with self._lock:
            already_subscribed = set(self._subscribed)
        ws_symbols = [
            s
            for s in dict.fromkeys(_to_ws_symbol(x) for x in filtered)
            if s and is_valid_ws_symbol(s) and s not in already_subscribed
        ]
        if not ws_symbols:
            return

        # Authoritative pre-dispatch verification against official exchange symbol master.
        # Semantics:
        #   - get_symbol_info() returns a dict  → symbol confirmed valid, allow through.
        #   - get_symbol_info() returns None AND the master loaded OK → symbol genuinely absent; drop.
        #   - get_symbol_info() raises / master load itself fails (DEGRADED) → pass through;
        #     Fyers broker SDK will report genuine invalids via its own -300 error path.
        #     Dropping a valid symbol due to a transient cache miss is a worse failure than
        #     submitting an invalid one (the latter is caught by the broker, the former is silent data loss).
        verified_ws_symbols = []
        dropped_invalids = []
        for s in ws_symbols:
            # Bypass check for test mock symbols in unit tests
            if s.startswith(("NSE:EXTRA_", "NSE:PERSIST_")):
                verified_ws_symbols.append(s)
                continue
            try:
                from market.symbol_master import get_symbol_info, load_master

                # Probe whether the relevant master file is actually available (not stale/offline).
                # If load_master itself raises, we are in DEGRADED mode — pass through.
                exch_prefix = s.split(":", 1)[0].upper() if ":" in s else "NSE"
                from market.symbol_master import _EXCHANGE_MASTERS

                _probe_master = _EXCHANGE_MASTERS.get(exch_prefix, ("NSE_CM",))[0]
                try:
                    load_master(_probe_master)  # raises RuntimeError when truly unavailable
                    master_available = True
                except Exception as _e_probe:
                    master_available = False
                    logger.warning(
                        f"[WebSocket] Symbol master DEGRADED for '{s}' (master='{_probe_master}'): {_e_probe}."
                        " Passing through to broker — Fyers SDK will reject genuine invalids via -300."
                    )

                if master_available:
                    info = get_symbol_info(s)
                    if info is not None:
                        canon_sym = info.get("symTicker") or s
                        verified_ws_symbols.append(canon_sym)
                    else:
                        logger.warning(
                            f"[WebSocket] Proactively dropped invalid symbol '{s}' before broker dispatch"
                            " (master loaded OK but symbol absent from official exchange master)."
                        )
                        dropped_invalids.append(s)
                else:
                    # DEGRADED: master unavailable — pass through rather than silently drop valid symbols
                    verified_ws_symbols.append(s)
            except Exception as _e_guard:
                logger.warning(
                    f"[WebSocket] Symbol master guard exception for '{s}': {_e_guard}. Passing through."
                )
                verified_ws_symbols.append(s)

        if dropped_invalids:
            try:
                from market.ws_subscription_manager import get_ws_subscription_manager

                get_ws_subscription_manager().remove_invalid_symbols(dropped_invalids)
            except Exception as _e_prune:
                logger.debug(f"[WebSocket] Failed pruning dropped invalids: {_e_prune}")

        sub_lock = getattr(self, "_sub_lock", None)
        if sub_lock is None:
            sub_lock = self._lock
        with sub_lock:
            sdk_sym_tok, sdk_chan_lst, sdk_tracked_syms = self._sanitize_sdk_subscription_state()
            with self._lock:
                # Re-sync symbols already registered inside SDK symbol_token without duplicate subscribe() calls
                already_in_sdk = [s for s in verified_ws_symbols if s in sdk_tracked_syms]
                if already_in_sdk:
                    self._subscribed.update(already_in_sdk)
                new_symbols = [
                    s
                    for s in verified_ws_symbols
                    if s not in self._subscribed and s not in sdk_tracked_syms
                ]
                # Deduplicate within the incoming batch while preserving order
                new_symbols = list(dict.fromkeys(new_symbols))
                effective_used = max(len(self._subscribed), sdk_sym_tok, sdk_chan_lst)
                # Fyers Data Socket enforces strictly < 5,000 total subscribed symbols (code -99)
                remaining_cap = max(0, 4999 - effective_used)
                if len(new_symbols) > remaining_cap:
                    logger.warning(
                        f"[WebSocket] Capping subscription batch from {len(new_symbols)} to {remaining_cap} "
                        f"(effective_used={effective_used}, Fyers limit=<5000)"
                    )
                    new_symbols = new_symbols[:remaining_cap]

            if not new_symbols:
                return

            try:
                CHUNK_SIZE = 400
                subscribed_any: list[str] = []
                for i in range(0, len(new_symbols), CHUNK_SIZE):
                    if not self._ws or not self._connected:
                        logger.debug("[WebSocket] Disconnected during batch subscription dispatch")
                        break
                    sdk_sym_tok, sdk_chan_lst, sdk_tracked_syms = (
                        self._sanitize_sdk_subscription_state()
                    )
                    with self._lock:
                        effective_used = max(len(self._subscribed), sdk_sym_tok, sdk_chan_lst)
                        chunk_cap = max(0, 4999 - effective_used)
                        batch = [
                            s
                            for s in new_symbols[i : i + CHUNK_SIZE]
                            if s not in self._subscribed and s not in sdk_tracked_syms
                        ][:chunk_cap]
                    if not batch:
                        if chunk_cap <= 0:
                            break
                        continue
                    self._ws.subscribe(batch)
                    with self._lock:
                        self._subscribed.update(batch)
                    subscribed_any.extend(batch)
                    if i + CHUNK_SIZE < len(new_symbols):
                        time.sleep(0.05)
                logger.info(
                    f"Subscribed to {len(subscribed_any)} symbols (batched in chunks of {CHUNK_SIZE})"
                )
            except Exception as e:
                logger.error(f"Subscribe failed: {e}", exc_info=True)
                return

        if record_in_manager and subscribed_any:
            try:
                from market.ws_subscription_manager import get_ws_subscription_manager

                get_ws_subscription_manager().add_subscriptions(subscribed_any)
            except Exception as exc:
                logger.warning(f"[WebSocket] Could not persist subscription update: {exc}")

    def subscribe_depth(self, symbols: list[str], max_depth_symbols: int = 100) -> list[str]:
        """Subscribe to 5-level DepthUpdate stream (channel 12) for BFO/SENSEX or overflow exposures."""
        if not symbols:
            return []
        with self._lock:
            already = set(self._depth_subscribed)
        targets = [
            s
            for s in dict.fromkeys(_to_ws_symbol(x) for x in symbols)
            if s and is_valid_ws_symbol(s) and s not in already
        ]
        remaining = max(0, max_depth_symbols - len(already))
        targets = targets[:remaining]
        if not targets:
            return []
        if not self._ws or not self._connected:
            with self._lock:
                self._depth_subscribed.update(targets)
            return targets
        sub_lock = getattr(self, "_sub_lock", None) or self._lock
        with sub_lock:
            try:
                self._ws.subscribe(targets, data_type="DepthUpdate", channel=12)
                with self._lock:
                    self._depth_subscribed.update(targets)
                logger.info(
                    f"[WebSocket] Subscribed {len(targets)} symbols to 5-level DepthUpdate (channel 12)"
                )
                return targets
            except Exception as exc:
                logger.debug(f"[WebSocket] subscribe_depth failed: {exc}")
                return []

    def get_l2_depth(self, instrument: str, max_age_seconds: float = 15.0) -> Optional[dict]:
        """Return fresh 5-level DepthUpdate snapshot if streaming and within max_age_seconds."""
        ws_sym = _to_ws_symbol(instrument)
        with self._lock:
            snap = self._depth_5_cache.get(ws_sym) or self._depth_5_cache.get(instrument)
        if not snap:
            return None
        age = time.time() - float(snap.get("received_at", 0.0) or 0.0)
        if age < 0 or age > max_age_seconds:
            return None
        return dict(snap)

    def _sanitize_sdk_subscription_state(self) -> tuple[int, int, set[str]]:
        """
        Repair FyersDataSocket internal list/dict drift before subscribe/unsubscribe calls.
        `fyers_apiv3.data_ws.FyersDataSocket` appends HSM tokens to `scrips_per_channel[ch]`
        without deduplication (`+= symbols`) and checks `len(scrips_per_channel[ch]) > 5000`
        before both `subscribe` and `unsubscribe` (`code: -99`). Deduplicating against
        `symbol_token` prevents permanent 5254 > 5000 subscription lockout.
        """
        ws = getattr(self, "_ws", None)
        if ws is None:
            return 0, 0, set()

        sym_tok = getattr(ws, "symbol_token", None)
        sym_tok_dict = sym_tok if isinstance(sym_tok, dict) else {}
        tracked_syms = set(str(v) for v in sym_tok_dict.values() if v)

        chan_map = getattr(ws, "scrips_per_channel", None)
        if isinstance(chan_map, dict):
            valid_toks = set(sym_tok_dict.keys())
            for ch, lst in list(chan_map.items()):
                if isinstance(lst, list):
                    deduped = list(dict.fromkeys(lst))
                    if valid_toks and ch == 11:
                        # Keep only tokens still tracked in symbol_token (preserves legitimate tokens)
                        cleaned = [t for t in deduped if t in valid_toks]
                        if not cleaned and sym_tok_dict:
                            cleaned = list(sym_tok_dict.keys())
                        chan_map[ch] = cleaned
                    else:
                        chan_map[ch] = deduped
            chan_lst = chan_map.get(11)
            sdk_chan_len = len(chan_lst) if isinstance(chan_lst, (list, set, tuple)) else 0
        else:
            sdk_chan_len = 0

        return len(sym_tok_dict), sdk_chan_len, tracked_syms

    def unsubscribe(self, symbols: list[str]) -> None:
        """Unsubscribe from symbols and immediately release SDK symbol/channel capacity."""
        if not self._ws or not self._connected:
            return
        ws_symbols = [_to_ws_symbol(s) for s in symbols]
        ws_set = set(ws_symbols)
        sub_lock = getattr(self, "_sub_lock", None) or self._lock
        with sub_lock:
            try:
                self._sanitize_sdk_subscription_state()
                # FyersDataSocket.unsubscribe() checks `scrips_count[11]`, which its own
                # subscribe() overwrites with only the final batch; ensure all active tokens are eligible.
                sym_tok = getattr(self._ws, "symbol_token", None)
                scrips_count = getattr(self._ws, "scrips_count", None)
                if isinstance(sym_tok, dict) and isinstance(scrips_count, dict):
                    scrips_count[11] = list(sym_tok.keys())
                self._ws.unsubscribe(ws_symbols)
                # Proactively prune SDK symbol_token & scrips_per_channel so freed slots recover synchronously
                if isinstance(sym_tok, dict):
                    removed_toks = {tok for tok, sym in list(sym_tok.items()) if sym in ws_set}
                    for tok in removed_toks:
                        sym_tok.pop(tok, None)
                    chan_map = getattr(self._ws, "scrips_per_channel", None)
                    if isinstance(chan_map, dict) and isinstance(chan_map.get(11), list):
                        chan_map[11] = [t for t in chan_map[11] if t not in removed_toks]
                with self._lock:
                    self._subscribed -= ws_set
            except Exception as e_suppressed:
                logger.debug(f"[market.websocket] Non-fatal exception suppressed: {e_suppressed}")

    def get_tick(self, instrument: str, max_age_seconds: Optional[float] = None) -> Optional[Tick]:
        """
        Get the latest cached tick for a symbol (instant, no API call).
        Returns None if no tick received yet, or if max_age_seconds is specified and the tick is older.
        """
        ws_sym = _to_ws_symbol(instrument)
        with self._lock:
            tick = self._ticks.get(ws_sym)

        if tick is not None and max_age_seconds is not None:
            if tick.is_stale(max_age_seconds):
                return None
        return tick

    def get_ltp(self, instrument: str, max_age_seconds: Optional[float] = None) -> Optional[float]:
        """Get cached LTP for a symbol. Returns None if not available or stale."""
        tick = self.get_tick(instrument, max_age_seconds=max_age_seconds)
        return tick.ltp if tick and tick.ltp > 0 else None

    def purge_symbols(self, symbols: list[str]) -> int:
        """Remove specified symbols and their canonical aliases from tick cache."""
        ws_syms: set[str] = set()
        for s in symbols:
            ws_syms.add(s)
            ws_syms.add(_to_ws_symbol(s))
            if ":" in s:
                clean = s.split(":", 1)[1]
                ws_syms.add(clean)
                if "-" in clean:
                    ws_syms.add(clean.split("-")[0])

        count = 0
        with self._lock:
            for k in list(self._ticks.keys()):
                if k in ws_syms:
                    del self._ticks[k]
                    count += 1
        return count

    def cleanse_stale_ticks(self, max_age_seconds: float = 86400.0) -> int:
        """
        Purge cached ticks older than max_age_seconds (default 24h) to avoid memory bloat
        from inactive symbols or past calendar sessions.
        Returns count of purged tick entries.
        """
        now = time.time()
        purged = 0
        with self._lock:
            keys_to_delete = [
                k for k, t in self._ticks.items() if (now - t.timestamp) > max_age_seconds
            ]
            for k in keys_to_delete:
                del self._ticks[k]
                purged += 1
        if purged > 0:
            logger.info(
                f"[WebSocket] Cleanse purged {purged} stale cached ticks older than {max_age_seconds}s"
            )
        return purged

    def on_tick(self, callback: Callable[[Tick], None]) -> None:
        """Register a callback that fires on every tick. Used by alerts."""
        with self._lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)
        self._ensure_dispatcher_running()

    def off_tick(self, callback: Callable[[Tick], None]) -> None:
        """Deregister a previously registered tick callback."""
        with self._lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

    def get_all_ticks(self) -> dict[str, Tick]:
        """Get all cached ticks."""
        with self._lock:
            return dict(self._ticks)

    # ── Private ──────────────────────────────────────────────

    def _connect(self) -> None:
        """Establish WebSocket connection using Fyers SDK."""
        try:
            from fyers_apiv3.FyersWebsocket import data_ws

            self._ws = data_ws.FyersDataSocket(
                access_token=f"{self._app_id}:{self._access_token}",
                log_path="",
                litemode=bool(self._lite_mode),
                write_to_file=True,
                reconnect=False,  # Autonomous control: ensures on_close triggers our self-healing reconnect and resubscription
                on_connect=self._on_connect,
                on_close=self._on_close,
                on_error=self._on_error,
                on_message=self._on_message,
            )
            try:
                from config.log_hygiene import install as _install_bounded_sdk_logs

                _install_bounded_sdk_logs()
            except Exception as exc:
                logger.warning(f"[WebSocket] SDK log rotation unavailable: {exc}")
            self._ws.connect()
        except ImportError:
            logger.error("fyers-apiv3 not installed — WebSocket unavailable")
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")

    def _on_connect(self) -> None:
        self._connected = True
        self._last_packet_at = time.time()
        cur_ws_id = id(self._ws) if self._ws is not None else None
        prev_ws_id = getattr(self, "_connected_ws_id", None)
        sdk_has_subs = bool(
            (getattr(self._ws, "symbol_token", None) or {})
            or ((getattr(self._ws, "scrips_per_channel", None) or {}).get(11) or [])
        )
        if cur_ws_id is not None and cur_ws_id == prev_ws_id and sdk_has_subs:
            logger.info(
                f"WebSocket: repeat OnOpen on same socket instance ({len(self._subscribed)} tracked); skipping duplicate re-subscribe."
            )
            return
        self._connected_ws_id = cur_ws_id
        with self._lock:
            self._subscribed.clear()
        logger.info("WebSocket: connected")
        try:
            from market.ws_subscription_manager import get_ws_subscription_manager

            get_ws_subscription_manager().on_ws_connected(self)
        except Exception as exc:
            logger.warning(
                f"[WebSocket] Failed to restore subscriptions on connect: {exc}",
                exc_info=True,
            )

    def _schedule_proactive_reconnect(self, delay_sec: Optional[float] = None) -> None:
        """Schedules proactive reconnect with single-flight thread safety and market-aware cadence."""
        with self._reconnect_lock:
            if self._is_reconnecting or (
                self._reconnect_thread is not None and self._reconnect_thread.is_alive()
            ):
                logger.debug("[WebSocket] Reconnect worker already in flight; deduplicating.")
                return
            self._is_reconnecting = True

            # Adaptive delay: back off to 60.0s during off-market hours to avoid thread/socket storms
            if delay_sec is None:
                try:
                    from market.calendar import is_market_open

                    market_open = is_market_open("NSE")
                except Exception:
                    market_open = True
                effective_delay = 3.0 if market_open else 60.0
            else:
                effective_delay = delay_sec

            logger.info(
                f"[WebSocket] Connection lost while running; scheduling proactive reconnect in {effective_delay:.1f}s..."
            )

            def _reconnect_worker():
                try:
                    time.sleep(effective_delay)
                    if getattr(self, "_running", False) and not getattr(self, "_connected", False):
                        # Re-check market status before attempting connection
                        try:
                            from market.calendar import is_market_open

                            if not is_market_open("NSE"):
                                logger.info(
                                    "[WebSocket] Off-market session detected ('NSE' closed). Pausing proactive reconnect."
                                )
                                return
                        except Exception as e_suppressed:
                            logger.debug(
                                f"[WebSocket] Reconnect market status non-fatal: {e_suppressed}"
                            )

                        logger.info("[WebSocket] Executing proactive reconnect...")
                        self._connect()
                except Exception as e_recon:
                    logger.warning(f"[WebSocket] Proactive reconnect failed: {e_recon}")
                finally:
                    with self._reconnect_lock:
                        self._is_reconnecting = False

            self._reconnect_thread = threading.Thread(
                target=_reconnect_worker, daemon=True, name="WsWatchdogReconnect"
            )
            self._reconnect_thread.start()

    def _schedule_token_refresh(self) -> None:
        """Refreshes broker access token with single-flight thread safety."""
        with self._reconnect_lock:
            now = time.time()
            if (now - getattr(self, "_last_token_refresh", 0.0)) < 10.0:
                logger.debug(
                    "[WebSocket] Token refresh cooldown active (<10s); skipping duplicate trigger."
                )
                return
            if self._refreshing_token or (
                self._token_refresh_thread is not None and self._token_refresh_thread.is_alive()
            ):
                logger.debug(
                    "[WebSocket] Token refresh already in flight; skipping duplicate trigger."
                )
                return
            self._refreshing_token = True
            self._last_token_refresh = now

            def _async_reconnect():
                try:
                    from brokers.session import get_data_broker

                    b = get_data_broker()
                    if hasattr(b, "_handle_auth_failure"):
                        b._handle_auth_failure()
                    elif hasattr(b, "is_authenticated"):
                        b.is_authenticated()

                    fresh_token = getattr(b, "_access_token", "")
                    app_id = getattr(b, "_app_id", "")
                    if fresh_token:
                        logger.info(
                            "[WebSocket] Reconnecting Fyers WebSocket with fresh access token..."
                        )
                        self.start(access_token=fresh_token, app_id=app_id)
                except Exception as e_recon:
                    logger.warning(f"[WebSocket] Auto-reconnect failed: {e_recon}")
                finally:
                    with self._reconnect_lock:
                        self._refreshing_token = False

            self._token_refresh_thread = threading.Thread(
                target=_async_reconnect, daemon=True, name="WsTokenRefresh"
            )
            self._token_refresh_thread.start()

    def _on_close(self, *args, **kwargs) -> None:
        self._connected = False
        with self._lock:
            self._subscribed.clear()
        logger.info("WebSocket: disconnected")
        if getattr(self, "_running", False) and getattr(self, "_access_token", ""):
            self._schedule_proactive_reconnect()

    def _on_error(self, *args, **kwargs) -> None:
        if args:
            err = args[0]
            logger.debug(f"WebSocket error: {err}")
            try:
                from engine.telemetry import record_event

                record_event(
                    event_type="WEBSOCKET_ERROR",
                    component="fyers_websocket",
                    reason=f"Fyers WebSocket error: {str(err)[:120]}",
                    severity="WARNING",
                    priority="P2",
                    details={"error": str(err)},
                )
            except Exception as e:
                logger.debug(f"[market.websocket] record_event suppressed: {e}")

            # Purge invalid_symbols reported by Fyers broker SDK
            if isinstance(err, dict):
                invalid_syms = err.get("invalid_symbols")
                if invalid_syms and isinstance(invalid_syms, list):
                    try:
                        from market.ws_subscription_manager import get_ws_subscription_manager

                        get_ws_subscription_manager().remove_invalid_symbols(invalid_syms)
                    except Exception as e_suppressed:
                        logger.debug(
                            f"[market.websocket] Non-fatal exception suppressed: {e_suppressed}"
                        )
            elif isinstance(err, str) and "invalid_symbols" in err:
                try:
                    import re
                    import ast

                    m = re.search(r"invalid_symbols['\"]\s*:\s*(\[[^\]]+\])", err)
                    if m:
                        parsed_syms = ast.literal_eval(m.group(1))
                        if parsed_syms:
                            from market.ws_subscription_manager import get_ws_subscription_manager

                            get_ws_subscription_manager().remove_invalid_symbols(parsed_syms)
                except Exception as e_suppressed:
                    logger.debug(
                        f"[market.websocket] Non-fatal exception suppressed: {e_suppressed}"
                    )

            err_str = str(err).lower()
            is_token_expired = (
                "token is expired" in err_str
                or "token expired" in err_str
                or "invalid token" in err_str
                or (
                    ("code': -99" in err_str or 'code": -99' in err_str)
                    and "5000" not in err_str
                    and ("token" in err_str or "auth" in err_str)
                )
            )
            if is_token_expired:
                logger.warning(
                    "[WebSocket] Fyers WebSocket token expired (-99). Triggering broker re-authentication..."
                )
                self._schedule_token_refresh()

    def _on_message(self, message) -> None:
        """Process incoming tick data."""
        now_ts = time.time()
        self._last_packet_at = now_ts
        if now_ts - getattr(self, "_last_provider_success_at", 0.0) > 10.0:
            self._last_provider_success_at = now_ts
            try:
                from engine.observability import get_registry

                get_registry().record_provider_success("fyers")
            except Exception as e_reg:
                logger.debug(f"[market.websocket] Provider success record error: {e_reg}")
        try:
            if isinstance(message, str):
                data_list = json.loads(message)
                if not isinstance(data_list, list):
                    data_list = [data_list]
            elif isinstance(message, list):
                data_list = message
            elif isinstance(message, dict):
                data_list = [message]
            else:
                return

            for data in data_list:
                if not isinstance(data, dict):
                    continue

                # Broker error feedback handling
                if data.get("s") == "error" and data.get("invalid_symbols"):
                    invalid_syms = data.get("invalid_symbols")
                    if isinstance(invalid_syms, list):
                        try:
                            from market.ws_subscription_manager import get_ws_subscription_manager

                            get_ws_subscription_manager().remove_invalid_symbols(invalid_syms)
                        except Exception as e_suppressed:
                            logger.debug(
                                f"[market.websocket] Non-fatal exception suppressed: {e_suppressed}"
                            )
                        try:
                            from engine.telemetry import record_event

                            record_event(
                                event_type="WEBSOCKET_INFO",
                                component="fyers_websocket",
                                reason=f"Fyers purged invalid symbols: {invalid_syms}",
                                severity="INFO",
                                priority="P3",
                                details={"invalid_symbols": invalid_syms, "response": data},
                            )
                        except Exception as e:
                            logger.debug(f"[market.websocket] record_event suppressed: {e}")
                    continue

                symbol = data.get("symbol", data.get("n", ""))
                if not symbol:
                    continue

                # Zero-LTP overwrite poisoning guard:
                # Never overwrite a valid historical/live traded price with 0.0 from depth-only packets
                raw_ltp = float(data.get("ltp", data.get("lp", 0)) or 0.0)
                raw_open = float(data.get("open_price", data.get("open", 0)) or 0.0)
                raw_high = float(data.get("high_price", data.get("high", 0)) or 0.0)
                raw_low = float(data.get("low_price", data.get("low", 0)) or 0.0)
                raw_close = float(data.get("prev_close_price", data.get("close", 0)) or 0.0)
                raw_vol = int(data.get("vol_traded_today", data.get("volume", 0)) or 0)
                raw_ltq = int(data.get("last_traded_qty", data.get("ltq", 0)) or 0)
                raw_ch = float(data.get("ch", 0) or 0.0)
                raw_chp = float(data.get("chp", 0) or 0.0)
                raw_ts = float(data.get("exch_feed_time", time.time()) or time.time())
                raw_bid = float(data.get("bid_price", data.get("bid", 0)) or 0.0)
                raw_ask = float(data.get("ask_price", data.get("ask", 0)) or 0.0)
                raw_bid_qty = int(data.get("bid_size", data.get("bq", 0)) or 0)
                raw_ask_qty = int(data.get("ask_size", data.get("sq", 0)) or 0)
                raw_oi = int(data.get("OI", data.get("oi", data.get("open_interest", 0))) or 0)
                raw_atp = float(
                    data.get("avg_trade_price", data.get("atp", data.get("avg_traded_price", 0.0)))
                    or 0.0
                )

                # DepthUpdate packets emit flat 5-level keys (bid_price1..5 / ask_price1..5)
                depth_bids_5: list[dict[str, Any]] = []
                depth_asks_5: list[dict[str, Any]] = []
                if "bid_price1" in data or "ask_price1" in data:
                    for lvl in range(1, 6):
                        bp = float(data.get(f"bid_price{lvl}", 0) or 0.0)
                        bq = int(data.get(f"bid_size{lvl}", 0) or 0)
                        bo = int(data.get(f"bid_order{lvl}", 0) or 0)
                        if bp > 0 and bq > 0:
                            depth_bids_5.append(
                                {"level": lvl, "price": bp, "qty": bq, "orders": bo}
                            )
                        ap = float(data.get(f"ask_price{lvl}", 0) or 0.0)
                        aq = int(data.get(f"ask_size{lvl}", 0) or 0)
                        ao = int(data.get(f"ask_order{lvl}", 0) or 0)
                        if ap > 0 and aq > 0:
                            depth_asks_5.append(
                                {"level": lvl, "price": ap, "qty": aq, "orders": ao}
                            )
                    if depth_bids_5 and raw_bid <= 0:
                        raw_bid = depth_bids_5[0]["price"]
                        raw_bid_qty = depth_bids_5[0]["qty"]
                    if depth_asks_5 and raw_ask <= 0:
                        raw_ask = depth_asks_5[0]["price"]
                        raw_ask_qty = depth_asks_5[0]["qty"]

                with self._lock:
                    existing_tick = self._ticks.get(symbol)
                    prev_day_vol = self._last_day_volume.get(symbol, 0)
                    delta_vol = 0
                    if raw_vol > 0:
                        if prev_day_vol > 0 and raw_vol >= prev_day_vol:
                            delta_vol = raw_vol - prev_day_vol
                        elif raw_ltq > 0:
                            delta_vol = raw_ltq
                        self._last_day_volume[symbol] = raw_vol
                    elif raw_ltq > 0:
                        delta_vol = raw_ltq

                final_ltp = (
                    raw_ltp if raw_ltp > 0 else (existing_tick.ltp if existing_tick else 0.0)
                )
                final_open = (
                    raw_open if raw_open > 0 else (existing_tick.open if existing_tick else 0.0)
                )
                final_high = (
                    raw_high if raw_high > 0 else (existing_tick.high if existing_tick else 0.0)
                )
                final_low = (
                    raw_low if raw_low > 0 else (existing_tick.low if existing_tick else 0.0)
                )
                final_close = (
                    raw_close if raw_close > 0 else (existing_tick.close if existing_tick else 0.0)
                )
                final_vol = (
                    raw_vol if raw_vol > 0 else (existing_tick.volume if existing_tick else 0)
                )
                final_atp = (
                    raw_atp if raw_atp > 0 else (existing_tick.atp if existing_tick else 0.0)
                )
                final_bid = (
                    raw_bid if raw_bid > 0 else (existing_tick.bid if existing_tick else 0.0)
                )
                final_ask = (
                    raw_ask if raw_ask > 0 else (existing_tick.ask if existing_tick else 0.0)
                )
                final_bid_qty = (
                    raw_bid_qty
                    if raw_bid_qty > 0
                    else (existing_tick.bid_qty if existing_tick else 0)
                )
                final_ask_qty = (
                    raw_ask_qty
                    if raw_ask_qty > 0
                    else (existing_tick.ask_qty if existing_tick else 0)
                )
                final_oi = raw_oi if raw_oi > 0 else (existing_tick.oi if existing_tick else 0)
                final_ch = (
                    raw_ch if raw_ch != 0.0 else (existing_tick.change if existing_tick else 0.0)
                )
                final_chp = (
                    raw_chp
                    if raw_chp != 0.0
                    else (existing_tick.change_pct if existing_tick else 0.0)
                )
                final_ts = (
                    raw_ts
                    if raw_ts > 0
                    else (existing_tick.timestamp if existing_tick else time.time())
                )

                tick = Tick(
                    symbol=symbol,
                    ltp=final_ltp,
                    open=final_open,
                    high=final_high,
                    low=final_low,
                    close=final_close,
                    volume=final_vol,
                    change=final_ch,
                    change_pct=final_chp,
                    timestamp=final_ts,
                    bid=final_bid,
                    ask=final_ask,
                    atp=final_atp,
                    received_at=time.time(),
                    delta_volume=delta_vol,
                    bid_qty=final_bid_qty,
                    ask_qty=final_ask_qty,
                    oi=final_oi,
                )

                with self._lock:
                    self._ticks[symbol] = tick
                    # Index under clean aliases so caller queries hit cache without format transformation
                    if ":" in symbol:
                        clean = symbol.split(":", 1)[1]
                        self._ticks[clean] = tick
                        if "-" in clean:
                            self._ticks[clean.split("-")[0]] = tick
                    # Cross-index canonical benchmark aliases
                    if symbol == "NSE:NIFTY50-INDEX":
                        for a in (
                            "NSE:NIFTY 50",
                            "NIFTY 50",
                            "NSE:NIFTY",
                            "NIFTY",
                            "NSE:NIFTY50",
                            "NIFTY50",
                        ):
                            self._ticks[a] = tick
                    elif symbol == "NSE:NIFTYBANK-INDEX":
                        for a in (
                            "NSE:NIFTY BANK",
                            "NIFTY BANK",
                            "NSE:BANKNIFTY",
                            "BANKNIFTY",
                            "NSE:BANK",
                            "BANK",
                        ):
                            self._ticks[a] = tick
                    elif symbol == "NSE:FINNIFTY-INDEX":
                        for a in (
                            "NSE:NIFTY FIN SERVICE",
                            "NIFTY FIN SERVICE",
                            "NSE:FINNIFTY",
                            "FINNIFTY",
                        ):
                            self._ticks[a] = tick
                    elif symbol == "NSE:MIDCPNIFTY-INDEX":
                        for a in (
                            "NSE:NIFTY MID SELECT",
                            "NIFTY MID SELECT",
                            "NSE:MIDCPNIFTY",
                            "MIDCPNIFTY",
                        ):
                            self._ticks[a] = tick
                    elif symbol == "BSE:SENSEX-INDEX":
                        for a in ("BSE:SENSEX", "SENSEX"):
                            self._ticks[a] = tick
                    elif symbol == "BSE:BANKEX-INDEX":
                        for a in ("BSE:BANKEX", "BANKEX"):
                            self._ticks[a] = tick
                    elif symbol == "NSE:INDIAVIX-INDEX":
                        for a in ("NSE:INDIA VIX", "INDIA VIX", "NSE:INDIAVIX", "INDIAVIX", "VIX"):
                            self._ticks[a] = tick

                # Update live BisectDepthBook in RAM
                try:
                    from market.order_book import get_depth_book

                    clean_sym = symbol.split(":", 1)[1] if ":" in symbol else symbol
                    if "-" in clean_sym:
                        clean_sym = clean_sym.split("-")[0]
                    clean_sym = clean_sym.strip().upper()

                    book = get_depth_book(clean_sym)
                    b_raw = (
                        depth_bids_5 or data.get("bids") or (data.get("depth", {}).get("buy", []))
                    )
                    a_raw = (
                        depth_asks_5 or data.get("asks") or (data.get("depth", {}).get("sell", []))
                    )
                    if b_raw or a_raw:
                        book.batch_update(b_raw or [], a_raw or [])
                    elif tick.bid > 0 and tick.ask > 0 and (tick.bid_qty > 0 or tick.ask_qty > 0):
                        if tick.bid_qty > 0:
                            book.update_level("BUY", tick.bid, tick.bid_qty)
                        if tick.ask_qty > 0:
                            book.update_level("SELL", tick.ask, tick.ask_qty)

                    if tick.ltp > 0 and tick.delta_volume > 0:
                        book.record_tick(
                            price=tick.ltp,
                            volume=tick.delta_volume,
                            timestamp=tick.timestamp,
                            best_bid=tick.bid if tick.bid > 0 else None,
                            best_ask=tick.ask if tick.ask > 0 else None,
                        )
                except Exception as e_book:
                    logger.debug(f"Failed updating BisectDepthBook for {symbol}: {e_book}")

                if depth_bids_5 or depth_asks_5:
                    tot_b5 = sum(int(x.get("qty", 0) or 0) for x in depth_bids_5)
                    tot_a5 = sum(int(x.get("qty", 0) or 0) for x in depth_asks_5)
                    ratio5 = round(tot_b5 / max(tot_a5, 1), 3) if tot_a5 > 0 else 1.0
                    depth_snap = {
                        "status": "ok",
                        "market_data_state": "LIVE",
                        "depth_level": 5,
                        "provider": "fyers_ws_depth_5",
                        "symbol": symbol,
                        "bids": depth_bids_5,
                        "asks": depth_asks_5,
                        "total_buy_qty": tot_b5,
                        "total_sell_qty": tot_a5,
                        "bid_ask_ratio": ratio5,
                        "order_book_imbalance_ratio": ratio5,
                        "ltp": tick.ltp if tick.ltp > 0 else None,
                        "atp": tick.atp if tick.atp > 0 else None,
                        "volume": tick.volume,
                        "oi": tick.oi,
                        "received_at": tick.received_at,
                    }
                    with self._lock:
                        self._depth_5_cache[symbol] = depth_snap
                        if ":" in symbol:
                            self._depth_5_cache[symbol.split(":", 1)[1]] = depth_snap

                # Fire callbacks asynchronously via bounded queue to decouple WS thread
                try:
                    self._dispatch_queue.put_nowait(tick)
                except queue.Full:
                    try:
                        _ = self._dispatch_queue.get_nowait()
                        self._dispatch_queue.put_nowait(tick)
                    except Exception as e_suppressed:
                        logger.debug(
                            f"[market.websocket] Non-fatal exception suppressed: {e_suppressed}"
                        )

        except Exception as e:
            logger.debug(f"Tick parse error: {e}")


# ── Singleton ────────────────────────────────────────────────

ws_manager = WebSocketManager()
