"""
market/kotak_websocket.py
─────────────────────────
Real-time market data WebSocket client and tick cache for Kotak Securities Neo API.

Features:
  - Subscribes to real-time quotes via Kotak Neo WebSocket streaming feed
  - Caches latest tick snapshot for instant quote retrieval (0ms latency)
  - Auto-subscribes to major market indices (NIFTY 50, BANK NIFTY, INDIA VIX, SENSEX)
  - Supports on-demand subscriptions for stocks and F&O option contracts
  - Provides thread-safe tick registry and price change alert callbacks
  - Automatic reconnection on network interruption

Usage:
    from market.kotak_websocket import kotak_ws

    # Start WebSocket client with broker session credentials
    kotak_ws.start(
        feed_url="wss://feed.kotaksecurities.com",
        access_token="...",
        sid="...",
    )

    # Fetch instant tick
    tick = kotak_ws.get_tick("NSE:NIFTY 50")
    if tick:
        print(tick.ltp)
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Canonical index token mapping
KNOWN_TOKENS: dict[str, str] = {
    "26000": "NSE:NIFTY 50",
    "26009": "NSE:NIFTY BANK",
    "26017": "NSE:INDIA VIX",
    "26037": "NSE:NIFTY FIN SERVICE",
    "26014": "NSE:NIFTY MIDCAP 100",
    "26013": "NSE:NIFTY IT",
    "1": "BSE:SENSEX",
    "2885": "NSE:RELIANCE",
    "11536": "NSE:TCS",
    "1594": "NSE:INFY",
    "1333": "NSE:HDFCBANK",
    "4963": "NSE:ICICIBANK",
    "3045": "NSE:SBIN",
    "1922": "NSE:KOTAKBANK",
    "5900": "NSE:AXISBANK",
    "11483": "NSE:LT",
    "1660": "NSE:ITC",
}

SYMBOL_TO_TOKEN: dict[str, str] = {sym.upper(): tok for tok, sym in KNOWN_TOKENS.items()}
for tok, sym in KNOWN_TOKENS.items():
    clean = sym.split(":")[-1].upper()
    SYMBOL_TO_TOKEN[clean] = tok
    SYMBOL_TO_TOKEN[clean.replace(" ", "")] = tok


@dataclass
class KotakTick:
    """Parsed real-time quote tick from Kotak Neo feed."""

    symbol: str
    ltp: float
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: int = 0
    change: float = 0.0
    change_pct: float = 0.0
    timestamp: float = field(default_factory=time.time)
    depth: Optional[dict] = None


class KotakWebSocketManager:
    """
    Manages Kotak Neo live streaming WebSocket connection,
    packet parsing, and tick caching.
    """

    def __init__(self) -> None:
        self._feed_url: str = ""
        self._access_token: str = ""
        self._sid: str = ""
        self._session_token: str = ""
        self._running: bool = False
        self._connected: bool = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Cache: instrument key / symbol -> KotakTick
        self._ticks: dict[str, KotakTick] = {}

        # Subscribed tokens
        self._subscribed_tokens: set[str] = set()

        # Callbacks
        self._callbacks: list[Callable[[KotakTick], None]] = []

    def is_connected(self) -> bool:
        return self._connected

    def start(
        self,
        feed_url: str = "",
        access_token: str = "",
        session_token: str = "",
        sid: str = "",
    ) -> None:
        """Start streaming thread."""
        with self._lock:
            if self._running:
                return
            self._feed_url = feed_url or "wss://feed.kotaksecurities.com"
            self._access_token = access_token
            self._session_token = session_token
            self._sid = sid
            self._running = True

        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="kotak_ws_thread")
        self._thread.start()
        logger.info("Kotak Neo WebSocket client started.")

    def stop(self) -> None:
        """Stop streaming thread."""
        with self._lock:
            self._running = False
            self._connected = False
        logger.info("Kotak Neo WebSocket client stopped.")

    def subscribe(self, instruments: list[str]) -> None:
        """Subscribe to live quotes for a list of instruments."""
        with self._lock:
            for inst in instruments:
                clean = inst.strip().upper()
                tok = SYMBOL_TO_TOKEN.get(clean) or SYMBOL_TO_TOKEN.get(clean.split(":")[-1]) or clean
                self._subscribed_tokens.add(tok)

    def unsubscribe(self, instruments: list[str]) -> None:
        """Unsubscribe instruments."""
        with self._lock:
            for inst in instruments:
                clean = inst.strip().upper()
                tok = SYMBOL_TO_TOKEN.get(clean) or SYMBOL_TO_TOKEN.get(clean.split(":")[-1]) or clean
                self._subscribed_tokens.discard(tok)

    def get_tick(self, instrument: str) -> Optional[KotakTick]:
        """Fetch instantaneous cached tick for an instrument."""
        clean = instrument.strip().upper()
        symbol_only = clean.split(":")[-1].strip()

        with self._lock:
            return (
                self._ticks.get(instrument)
                or self._ticks.get(clean)
                or self._ticks.get(symbol_only)
                or self._ticks.get(symbol_only.replace(" ", ""))
            )

    def on_tick(self, callback: Callable[[KotakTick], None]) -> None:
        """Register a callback for real-time price updates."""
        with self._lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)

    def _notify(self, tick: KotakTick) -> None:
        with self._lock:
            cbs = list(self._callbacks)
        for cb in cbs:
            try:
                cb(tick)
            except Exception as e:
                logger.error(f"Error in Kotak tick callback: {e}")

    def update_tick(self, tick: KotakTick) -> None:
        """Directly insert/update a tick in cache (used by external feed or parser)."""
        with self._lock:
            self._ticks[tick.symbol] = tick
            clean = tick.symbol.split(":")[-1]
            self._ticks[clean] = tick
            self._ticks[clean.replace(" ", "")] = tick
        self._notify(tick)

    def _parse_packet(self, data: Any) -> None:
        """Parse JSON or binary packet from Kotak WebSocket."""
        try:
            if isinstance(data, (bytes, bytearray)):
                # If JSON encoded in bytes
                try:
                    data = json.loads(data.decode("utf-8"))
                except Exception:
                    return

            if isinstance(data, str):
                data = json.loads(data)

            if isinstance(data, list):
                for item in data:
                    self._process_tick_dict(item)
            elif isinstance(data, dict):
                self._process_tick_dict(data)
        except Exception as e:
            logger.debug(f"Kotak packet parsing error: {e}")

    def _process_tick_dict(self, d: dict) -> None:
        tok = str(d.get("tk") or d.get("token") or d.get("instrument_token") or "")
        sym = d.get("ts") or d.get("symbol") or KNOWN_TOKENS.get(tok, tok)

        ltp = float(d.get("ltp") or d.get("lastPrice") or d.get("lp") or 0.0)
        if ltp <= 0:
            return

        open_p = float(d.get("open") or d.get("o") or 0.0) or None
        high_p = float(d.get("high") or d.get("h") or 0.0) or None
        low_p = float(d.get("low") or d.get("l") or 0.0) or None
        close_p = float(d.get("close") or d.get("c") or 0.0) or None
        vol = int(d.get("volume") or d.get("v") or 0)
        chg = float(d.get("change") or d.get("ch") or 0.0)
        chg_pct = float(d.get("changePct") or d.get("chp") or 0.0)

        tick = KotakTick(
            symbol=sym,
            ltp=ltp,
            open=open_p,
            high=high_p,
            low=low_p,
            close=close_p,
            volume=vol,
            change=chg,
            change_pct=chg_pct,
            timestamp=time.time(),
        )
        self.update_tick(tick)

    def _run_loop(self) -> None:
        """WebSocket connection loop using websockets library."""
        try:
            import websockets
            from websockets.sync.client import connect
        except ImportError:
            logger.warning("websockets library not available for Kotak WS feed.")
            return

        # Auto-subscribe default indices
        self.subscribe(["NSE:NIFTY 50", "NSE:NIFTY BANK", "NSE:INDIA VIX", "BSE:SENSEX"])

        while self._running:
            try:
                headers = {}
                if self._session_token:
                    headers["Authorization"] = f"Bearer {self._session_token}"
                if self._sid:
                    headers["Sid"] = self._sid

                ws_url = self._feed_url
                if not ws_url.startswith("ws"):
                    ws_url = "wss://feed.kotaksecurities.com"

                with connect(ws_url, additional_headers=headers, close_timeout=5) as ws:
                    with self._lock:
                        self._connected = True
                    logger.info("Connected to Kotak Neo WebSocket feed.")

                    # Send initial subscription if tokens available
                    with self._lock:
                        toks = list(self._subscribed_tokens)
                    if toks:
                        sub_msg = json.dumps({"action": "subscribe", "params": {"tokens": toks}})
                        ws.send(sub_msg)

                    while self._running:
                        try:
                            msg = ws.recv(timeout=1.0)
                            self._parse_packet(msg)
                        except TimeoutError:
                            # Heartbeat check
                            continue
                        except Exception:
                            break
            except Exception as e:
                logger.debug(f"Kotak WebSocket connection error: {e}")

            with self._lock:
                self._connected = False

            if self._running:
                time.sleep(3.0)  # Reconnect backoff


# Singleton export
kotak_ws = KotakWebSocketManager()
