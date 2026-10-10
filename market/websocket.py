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
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional


logger = logging.getLogger(__name__)


# ── Default symbols to subscribe ─────────────────────────────

DEFAULT_SYMBOLS = [
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
]

# Map our instrument format to Fyers WebSocket format
_SYMBOL_MAP = {
    "NSE:NIFTY 50": "NSE:NIFTY50-INDEX",
    "NSE:NIFTY BANK": "NSE:NIFTYBANK-INDEX",
    "NSE:INDIA VIX": "NSE:INDIAVIX-INDEX",
    "BSE:SENSEX": "BSE:SENSEX-INDEX",
    "NSE:NIFTY FIN SERVICE": "NSE:FINNIFTY-INDEX",
    "NSE:NIFTY MIDCAP 100": "NSE:NIFTYMIDCAP100-INDEX",
    "NSE:MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX",
    "NSE:NIFTY MID SELECT": "NSE:MIDCPNIFTY-INDEX",
    "BSE:BANKEX": "BSE:BANKEX-INDEX",
    "NSE:NIFTY IT": "NSE:NIFTYIT-INDEX",
    "NSE:NIFTY PHARMA": "NSE:NIFTYPHARMA-INDEX",
    "NSE:NIFTY AUTO": "NSE:NIFTYAUTO-INDEX",
    "NSE:NIFTY FMCG": "NSE:NIFTYFMCG-INDEX",
    "NSE:NIFTY REALTY": "NSE:NIFTYREALTY-INDEX",
    "NSE:NIFTY METAL": "NSE:NIFTYMETAL-INDEX",
    "NSE:NIFTY ENERGY": "NSE:NIFTYENERGY-INDEX",
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
    try:
        from brokers.fyers import _to_fyers_symbol

        return _to_fyers_symbol(instrument)
    except Exception:
        pass

    # Direct map lookup
    if instrument in _SYMBOL_MAP:
        return _SYMBOL_MAP[instrument]

    # Try uppercase version
    if instrument.upper() in _SYMBOL_MAP:
        return _SYMBOL_MAP[instrument.upper()]

    if ":" in instrument:
        exch, sym = instrument.split(":", 1)
        # Already in Fyers format (has -EQ, -INDEX, etc.)
        if "-" in sym:
            return instrument

        sym_upper = sym.upper().strip()

        # Check full map with constructed key
        map_key = f"{exch.upper()}:{sym_upper}"
        if map_key in _SYMBOL_MAP:
            return _SYMBOL_MAP[map_key]

        # Check if it's an index by explicit prefixes
        clean = sym_upper.replace(" ", "")
        if clean.startswith(_INDEX_PREFIXES) or clean in ("VIX", "INDIAVIX"):
            return f"{exch}:{clean}-INDEX"

        return f"{exch}:{sym}-EQ"
    return f"NSE:{instrument}-EQ"


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


class WebSocketManager:
    """
    Manages the Fyers WebSocket connection for real-time market data.

    Singleton — one connection per session, shared across all modules.
    """

    def __init__(self) -> None:
        self._ws = None
        self._connected = False
        self._access_token = ""
        self._app_id = ""
        self._ticks: dict[str, Tick] = {}  # symbol → latest tick
        self._callbacks: list[Callable] = []
        self._subscribed: set[str] = set()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    @property
    def connected(self) -> bool:
        return self._connected

    def start(self, access_token: str, app_id: str) -> None:
        """
        Start the WebSocket connection in a background thread.
        Call this after successful broker login.
        """
        if self._connected:
            logger.info("WebSocket already connected")
            return

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
            # Auto-subscribe to default symbols
            self.subscribe(DEFAULT_SYMBOLS)
        else:
            logger.warning("WebSocket connection timed out — will use REST fallback")

    def stop(self, timeout: float = 1.0) -> None:
        """Disconnect the WebSocket and gracefully shut down without blocking."""
        ws_to_close = self._ws
        self._connected = False
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
                        except Exception:
                            pass
                    # Close underlying websocket
                    ws_obj = getattr(ws_to_close, "_FyersDataSocket__ws_object", None)
                    if ws_obj and hasattr(ws_obj, "close"):
                        try:
                            ws_obj.close()
                        except Exception:
                            pass
                    # Clear reference so ping thread exits its while loop
                    setattr(ws_to_close, "_FyersDataSocket__ws_object", None)
                except Exception:
                    pass

            t = threading.Thread(target=_close, daemon=True)
            t.start()
            t.join(timeout=timeout)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None

    def subscribe(self, symbols: list[str]) -> None:
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

        # Convert to Fyers format
        ws_symbols = [_to_ws_symbol(s) for s in filtered]
        new_symbols = [s for s in ws_symbols if s not in self._subscribed]

        if not new_symbols:
            return

        try:
            self._ws.subscribe(new_symbols)
            self._subscribed.update(new_symbols)
            logger.info(f"Subscribed to {len(new_symbols)} symbols")
            try:
                from market.ws_subscription_manager import get_ws_subscription_manager

                get_ws_subscription_manager().add_subscriptions(new_symbols)
            except Exception as exc:
                logger.warning(f"[WebSocket] Could not persist subscription update: {exc}")
        except Exception as e:
            logger.error(f"Subscribe failed: {e}", exc_info=True)

    def unsubscribe(self, symbols: list[str]) -> None:
        """Unsubscribe from symbols."""
        if not self._ws or not self._connected:
            return
        ws_symbols = [_to_ws_symbol(s) for s in symbols]
        try:
            self._ws.unsubscribe(ws_symbols)
            self._subscribed -= set(ws_symbols)
        except Exception:
            pass

    def get_tick(self, instrument: str) -> Optional[Tick]:
        """
        Get the latest cached tick for a symbol (instant, no API call).
        Returns None if no tick received yet.
        """
        ws_sym = _to_ws_symbol(instrument)
        with self._lock:
            return self._ticks.get(ws_sym)

    def get_ltp(self, instrument: str) -> Optional[float]:
        """Get cached LTP for a symbol. Returns None if not available."""
        tick = self.get_tick(instrument)
        return tick.ltp if tick else None

    def on_tick(self, callback: Callable[[Tick], None]) -> None:
        """Register a callback that fires on every tick. Used by alerts."""
        self._callbacks.append(callback)

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
                litemode=False,
                write_to_file=True,
                reconnect=True,
                on_connect=self._on_connect,
                on_close=self._on_close,
                on_error=self._on_error,
                on_message=self._on_message,
            )
            self._ws.connect()
        except ImportError:
            logger.error("fyers-apiv3 not installed — WebSocket unavailable")
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")

    def _on_connect(self) -> None:
        self._connected = True
        logger.info("WebSocket: connected")
        try:
            from market.ws_subscription_manager import get_ws_subscription_manager

            get_ws_subscription_manager().on_ws_connected(self)
        except Exception as exc:
            logger.warning(
                f"[WebSocket] Failed to restore subscriptions on connect: {exc}",
                exc_info=True,
            )

    def _on_close(self, *args, **kwargs) -> None:
        self._connected = False
        logger.info("WebSocket: disconnected")

    def _on_error(self, *args, **kwargs) -> None:
        if args:
            err = args[0]
            logger.debug(f"WebSocket error: {err}")
            err_str = str(err).lower()
            if "token is expired" in err_str or "code': -99" in err_str or 'code": -99' in err_str:
                logger.warning(
                    "[WebSocket] Fyers WebSocket token expired (-99). Triggering broker re-authentication..."
                )

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
                            self.connect(access_token=fresh_token, app_id=app_id)
                    except Exception as e_recon:
                        logger.warning(f"[WebSocket] Auto-reconnect failed: {e_recon}")

                threading.Thread(
                    target=_async_reconnect, daemon=True, name="WsTokenRefresh"
                ).start()

    def _on_message(self, message) -> None:
        """Process incoming tick data."""
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

                symbol = data.get("symbol", data.get("n", ""))
                if not symbol:
                    continue

                tick = Tick(
                    symbol=symbol,
                    ltp=float(data.get("ltp", data.get("lp", 0))),
                    open=float(data.get("open_price", data.get("open", 0))),
                    high=float(data.get("high_price", data.get("high", 0))),
                    low=float(data.get("low_price", data.get("low", 0))),
                    close=float(data.get("prev_close_price", data.get("close", 0))),
                    volume=int(data.get("vol_traded_today", data.get("volume", 0))),
                    change=float(data.get("ch", 0)),
                    change_pct=float(data.get("chp", 0)),
                    timestamp=float(data.get("exch_feed_time", time.time())),
                    bid=float(data.get("bid", 0)),
                    ask=float(data.get("ask", 0)),
                    atp=float(data.get("atp", data.get("avg_traded_price", 0.0)) or 0.0),
                )

                with self._lock:
                    self._ticks[symbol] = tick
                    # Index under clean aliases so caller queries hit cache without format transformation
                    if ":" in symbol:
                        clean = symbol.split(":", 1)[1]
                        self._ticks[clean] = tick
                        if "-" in clean:
                            self._ticks[clean.split("-")[0]] = tick

                # Fire callbacks
                for cb in self._callbacks:
                    try:
                        cb(tick)
                    except Exception:
                        pass

        except Exception as e:
            logger.debug(f"Tick parse error: {e}")


# ── Singleton ────────────────────────────────────────────────

ws_manager = WebSocketManager()
