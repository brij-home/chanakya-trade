"""
market/mstock_websocket.py
──────────────────────────
Real-time market data WebSocket client and binary packet parser for m.Stock (Mirae Asset).
Supports official m.Stock Type B binary quote packets:
  - 379-byte Full Quote packet with 5-level market depth (L2 bid/ask orders)
  - 179-byte Standard Quote packet
  - 51-byte LTP packet
Auto-registers ticks into the shared `market.websocket.ws_manager` tick registry.
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Union

logger = logging.getLogger(__name__)

MSTOCK_WS_URL = "wss://ws.mstock.trade"

# Exchange type mapping
EXCHANGE_NSE_CASH = 1
EXCHANGE_NSE_FNO = 2
EXCHANGE_NSE_CD = 3
EXCHANGE_BSE_CASH = 4
EXCHANGE_BSE_FNO = 5
EXCHANGE_BSE_CD = 6
EXCHANGE_MCX = 7

# Canonical index & stock token mapping for NSE Cash / Indices
KNOWN_TOKENS: dict[str, str] = {
    # Indices
    "26000": "NSE:NIFTY 50",
    "26009": "NSE:NIFTY BANK",
    "26017": "NSE:INDIA VIX",
    "26037": "NSE:NIFTY FIN SERVICE",
    "26014": "NSE:NIFTY MIDCAP 100",
    "26013": "NSE:NIFTY IT",
    # BSE Indices
    "1": "BSE:SENSEX",
    # Equities
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
    "317": "NSE:BAJFINANCE",
    "10604": "NSE:BHARTIARTL",
    "10999": "NSE:MARUTI",
    "3456": "NSE:TATAMOTORS",
    "3787": "NSE:WIPRO",
    "11540": "NSE:COFORGE",
    "1964": "NSE:TRENT",
    "7229": "NSE:HCLTECH",
    "10940": "NSE:DIVISLAB",
    "13538": "NSE:TECHM",
}

# Reverse mapping: symbol -> token
SYMBOL_TO_TOKEN: dict[str, str] = {sym.upper(): tok for tok, sym in KNOWN_TOKENS.items()}
for tok, sym in KNOWN_TOKENS.items():
    clean = sym.split(":")[-1].upper()
    SYMBOL_TO_TOKEN[clean] = tok


@dataclass
class MarketDepthLevel:
    """Single level of market depth (bid or ask)."""

    flag: int
    quantity: int
    price: float
    orders: int


@dataclass
class MStockTick:
    """Parsed real-time quote packet from m.Stock WebSocket."""

    mode: int
    exchange_type: int
    token: str
    symbol: str
    sequence: int
    timestamp: float
    ltp: float
    last_traded_qty: int = 0
    atp: float = 0.0
    volume: int = 0
    total_buy_qty: float = 0.0
    total_sell_qty: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    last_traded_ts: float = 0.0
    open_interest: int = 0
    open_interest_pct: float = 0.0
    bids: list[MarketDepthLevel] = field(default_factory=list)
    asks: list[MarketDepthLevel] = field(default_factory=list)
    upper_circuit: float = 0.0
    lower_circuit: float = 0.0
    fifty_two_week_high: float = 0.0
    fifty_two_week_low: float = 0.0

    @property
    def change(self) -> float:
        return round(self.ltp - self.close, 2) if self.close > 0 else 0.0

    @property
    def change_pct(self) -> float:
        return round((self.change / self.close) * 100.0, 2) if self.close > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "token": self.token,
            "exchange_type": self.exchange_type,
            "ltp": self.ltp,
            "change": self.change,
            "change_pct": self.change_pct,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "atp": self.atp,
            "oi": self.open_interest,
            "oi_pct": self.open_interest_pct,
            "timestamp": self.timestamp,
            "bids": [{"price": b.price, "qty": b.quantity, "orders": b.orders} for b in self.bids],
            "asks": [{"price": a.price, "qty": a.quantity, "orders": a.orders} for a in self.asks],
            "upper_circuit": self.upper_circuit,
            "lower_circuit": self.lower_circuit,
            "fifty_two_week_high": self.fifty_two_week_high,
            "fifty_two_week_low": self.fifty_two_week_low,
        }


# Struct formats:
# 379-byte Quote packet (MODE_SNAP = 3, with 5-level market depth)
# >BB25sQqqqqqddqqqqqqq200sqqqq
# 1 + 1 + 25 + 8*6 + 8*2 + 8*7 + 200 + 8*4 = 379 bytes
_QUOTE_379_FMT = ">BB25sQqqqqqddqqqqqqq200sqqqq"
_DEPTH_ITEM_FMT = ">hqqh"  # 2 + 8 + 8 + 2 = 20 bytes

# 123-byte Quote packet (MODE_QUOTE = 2, OHLC & volume without market depth)
# >BB25sQqqqqqddqqqq
# 1 + 1 + 25 + 8 (seq) + 8 (ts) + 8 (ltp) + 8 (qty) + 8 (atp) + 8 (vol) + 8 (buy) + 8 (sell) + 8*4 (ohlc) = 123 bytes
_QUOTE_123_FMT = ">BB25sQqqqqqddqqqq"


def parse_market_depth(depth_bytes: bytes) -> tuple[list[MarketDepthLevel], list[MarketDepthLevel]]:
    """Parse 200 bytes of 5-level market depth (5 bids + 5 asks)."""
    bids: list[MarketDepthLevel] = []
    asks: list[MarketDepthLevel] = []
    if len(depth_bytes) < 200:
        return bids, asks

    for i in range(5):
        offset = i * 20
        flag, qty, raw_price, orders = struct.unpack_from(_DEPTH_ITEM_FMT, depth_bytes, offset)
        bids.append(
            MarketDepthLevel(flag=flag, quantity=qty, price=raw_price / 100.0, orders=orders)
        )

    for i in range(5):
        offset = 100 + i * 20
        flag, qty, raw_price, orders = struct.unpack_from(_DEPTH_ITEM_FMT, depth_bytes, offset)
        asks.append(
            MarketDepthLevel(flag=flag, quantity=qty, price=raw_price / 100.0, orders=orders)
        )

    return bids, asks


def parse_quote_packet(
    data: bytes, token_map: Optional[dict[str, str]] = None
) -> Optional[MStockTick]:
    """Parse a single 379-byte m.Stock quote packet (MODE_SNAP with depth)."""
    if len(data) < 379:
        return None

    try:
        unpacked = struct.unpack(_QUOTE_379_FMT, data[:379])
        mode = unpacked[0]
        exchange_type = unpacked[1]
        raw_token = unpacked[2].decode("utf-8", errors="replace").strip("\x00 \t\r\n")
        seq = unpacked[3]
        ex_ts = unpacked[4]
        ltp = unpacked[5] / 100.0
        lt_qty = unpacked[6]
        atp = unpacked[7] / 100.0
        vol = unpacked[8]
        buy_qty = unpacked[9]
        sell_qty = unpacked[10]
        opn = unpacked[11] / 100.0
        high = unpacked[12] / 100.0
        low = unpacked[13] / 100.0
        cls = unpacked[14] / 100.0
        lt_ts = unpacked[15]
        oi = unpacked[16]
        oi_pct = unpacked[17] / 100.0
        depth_raw = unpacked[18]
        uc = unpacked[19] / 100.0
        lc = unpacked[20] / 100.0
        w52_h = unpacked[21] / 100.0
        w52_l = unpacked[22] / 100.0

        bids, asks = parse_market_depth(depth_raw)

        mapping = token_map or KNOWN_TOKENS
        symbol = mapping.get(raw_token, f"TOKEN:{raw_token}")

        return MStockTick(
            mode=mode,
            exchange_type=exchange_type,
            token=raw_token,
            symbol=symbol,
            sequence=seq,
            timestamp=float(ex_ts if ex_ts > 0 else time.time()),
            ltp=ltp,
            last_traded_qty=lt_qty,
            atp=atp,
            volume=vol,
            total_buy_qty=buy_qty,
            total_sell_qty=sell_qty,
            open=opn,
            high=high,
            low=low,
            close=cls,
            last_traded_ts=float(lt_ts),
            open_interest=oi,
            open_interest_pct=oi_pct,
            bids=bids,
            asks=asks,
            upper_circuit=uc,
            lower_circuit=lc,
            fifty_two_week_high=w52_h,
            fifty_two_week_low=w52_l,
        )
    except Exception as e:
        logger.debug(f"Failed to unpack m.Stock quote packet: {e}")
        return None


def parse_quote_123_packet(
    data: bytes, token_map: Optional[dict[str, str]] = None
) -> Optional[MStockTick]:
    """Parse a single 123-byte m.Stock quote packet (MODE_QUOTE with OHLC & volume)."""
    if len(data) < 123:
        return None

    try:
        unpacked = struct.unpack(_QUOTE_123_FMT, data[:123])
        mode = unpacked[0]
        exchange_type = unpacked[1]
        raw_token = unpacked[2].decode("utf-8", errors="replace").strip("\x00 \t\r\n")
        seq = unpacked[3]
        ex_ts = unpacked[4]
        ltp = unpacked[5] / 100.0
        lt_qty = unpacked[6]
        atp = unpacked[7] / 100.0
        vol = unpacked[8]
        buy_qty = unpacked[9]
        sell_qty = unpacked[10]
        opn = unpacked[11] / 100.0
        high = unpacked[12] / 100.0
        low = unpacked[13] / 100.0
        cls = unpacked[14] / 100.0

        mapping = token_map or KNOWN_TOKENS
        symbol = mapping.get(raw_token, f"TOKEN:{raw_token}")

        return MStockTick(
            mode=mode,
            exchange_type=exchange_type,
            token=raw_token,
            symbol=symbol,
            sequence=seq,
            timestamp=float(ex_ts if ex_ts > 0 else time.time()),
            ltp=ltp,
            last_traded_qty=lt_qty,
            atp=atp,
            volume=vol,
            total_buy_qty=buy_qty,
            total_sell_qty=sell_qty,
            open=opn,
            high=high,
            low=low,
            close=cls,
        )
    except Exception as e:
        logger.debug(f"Failed to unpack 123-byte quote packet: {e}")
        return None


def parse_ltp_packet(
    data: bytes, token_map: Optional[dict[str, str]] = None
) -> Optional[MStockTick]:
    """Parse a 51-byte mode 1 LTP packet."""
    if len(data) < 51:
        return None
    try:
        mode, exch, raw_token, seq, ex_ts, raw_ltp = struct.unpack(">BB25sQqq", data[:51])
        token = raw_token.decode("utf-8", errors="replace").strip("\x00 \t\r\n")
        mapping = token_map or KNOWN_TOKENS
        symbol = mapping.get(token, f"TOKEN:{token}")
        return MStockTick(
            mode=mode,
            exchange_type=exch,
            token=token,
            symbol=symbol,
            sequence=seq,
            timestamp=float(ex_ts if ex_ts > 0 else time.time()),
            ltp=raw_ltp / 100.0,
        )
    except Exception as e:
        logger.debug(f"Failed to unpack LTP packet: {e}")
        return None


def parse_binary_frame(data: bytes, token_map: Optional[dict[str, str]] = None) -> list[MStockTick]:
    """
    Parse a binary WebSocket message frame which may contain:
    - Exactly 379 bytes or multiple 379-byte packets (MODE_SNAP)
    - Exactly 123 bytes or multiple 123-byte packets (MODE_QUOTE)
    - Exactly 51 bytes or multiple 51-byte LTP packets (MODE_LTP)
    - Length/count-prefixed packets
    """
    ticks: list[MStockTick] = []
    if not data:
        return ticks

    # Check for 2-byte packet count prefix
    offset = 0
    if len(data) > 2:
        try:
            (pkt_count,) = struct.unpack_from(">H", data, 0)
            if pkt_count > 0 and (
                2 + pkt_count * 379 == len(data)
                or 2 + pkt_count * 123 == len(data)
                or 2 + pkt_count * 51 == len(data)
            ):
                offset = 2
        except Exception:
            offset = 0

    remaining = len(data) - offset

    # Case A: 379-byte chunks (SNAP mode with depth)
    if remaining >= 379 and remaining % 379 == 0:
        for i in range(offset, len(data), 379):
            tick = parse_quote_packet(data[i : i + 379], token_map=token_map)
            if tick:
                ticks.append(tick)
        return ticks

    # Case B: 123-byte chunks (QUOTE mode with OHLC & volume)
    if remaining >= 123 and remaining % 123 == 0:
        for i in range(offset, len(data), 123):
            tick = parse_quote_123_packet(data[i : i + 123], token_map=token_map)
            if tick:
                ticks.append(tick)
        return ticks

    # Case C: 51-byte chunks (LTP mode)
    if remaining >= 51 and remaining % 51 == 0:
        for i in range(offset, len(data), 51):
            tick = parse_ltp_packet(data[i : i + 51], token_map=token_map)
            if tick:
                ticks.append(tick)
        return ticks

    # Case D: Single 379-byte packet anywhere
    if remaining >= 379:
        tick = parse_quote_packet(data[offset : offset + 379], token_map=token_map)
        if tick:
            ticks.append(tick)
            return ticks

    # Case E: Single 123-byte packet anywhere
    if remaining >= 123:
        tick = parse_quote_123_packet(data[offset : offset + 123], token_map=token_map)
        if tick:
            ticks.append(tick)
            return ticks

    # Case F: Single 51-byte packet anywhere
    if remaining >= 51:
        tick = parse_ltp_packet(data[offset : offset + 51], token_map=token_map)
        if tick:
            ticks.append(tick)
            return ticks

    return ticks


class MStockWebSocket:
    """
    Manages live streaming connection to m.Stock WebSocket (wss://ws.mstock.trade).
    Unpacks binary quote packets and notifies listeners & central tick manager.
    """

    def __init__(self, api_key: str = "", access_token: str = "") -> None:
        self.api_key = api_key
        self.access_token = access_token
        self._connected = False
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws: Any = None
        self._subscribed_tokens: dict[int, set[str]] = {
            EXCHANGE_NSE_CASH: set(),
            EXCHANGE_NSE_FNO: set(),
            EXCHANGE_BSE_CASH: set(),
            EXCHANGE_MCX: set(),
        }
        self._token_map: dict[str, str] = dict(KNOWN_TOKENS)
        self._ticks: dict[str, MStockTick] = {}
        self._callbacks: list[Callable[[MStockTick], None]] = []
        self._lock = threading.Lock()

    @property
    def connected(self) -> bool:
        return self._connected

    def register_token_mapping(self, token: str, symbol: str) -> None:
        """Register a custom token to symbol mapping."""
        with self._lock:
            self._token_map[str(token)] = symbol

    def on_tick(self, callback: Callable[[MStockTick], None]) -> None:
        """Register a callback for every received tick."""
        self._callbacks.append(callback)

    def get_tick(self, symbol_or_token: str) -> Optional[MStockTick]:
        """Get latest tick by symbol or token."""
        with self._lock:
            if symbol_or_token in self._ticks:
                return self._ticks[symbol_or_token]
            # Try reverse lookup
            tok = SYMBOL_TO_TOKEN.get(symbol_or_token.upper())
            if tok and tok in self._ticks:
                return self._ticks[tok]
            # Try finding by symbol field
            for t in self._ticks.values():
                if t.symbol.upper() == symbol_or_token.upper():
                    return t
        return None

    def get_all_ticks(self) -> dict[str, MStockTick]:
        """Get all cached ticks."""
        with self._lock:
            return dict(self._ticks)

    def start(self, api_key: str = "", access_token: str = "") -> None:
        """Start the WebSocket in a background daemon thread."""
        if api_key:
            self.api_key = api_key
        if access_token:
            self.access_token = access_token

        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        # Wait briefly for connection
        for _ in range(25):
            if self._connected:
                break
            time.sleep(0.2)

    def stop(self) -> None:
        """Disconnect and stop background thread."""
        self._running = False
        self._connected = False
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._ws = None

    def _run_loop(self) -> None:
        """Event loop thread target."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._connect_and_listen())

    async def _connect_and_listen(self) -> None:
        """Async connection loop with exponential reconnect backoff."""
        try:
            import websockets
        except ImportError:
            logger.error("websockets package not available for m.Stock WS")
            return

        reconnect_delay = 2.0
        while self._running:
            try:
                url = f"{MSTOCK_WS_URL}?API_KEY={self.api_key}&ACCESS_TOKEN={self.access_token}"
                logger.info(f"Connecting to m.Stock WebSocket: {MSTOCK_WS_URL}")
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    self._ws = ws
                    self._connected = True
                    reconnect_delay = 2.0
                    logger.info("m.Stock WebSocket connected successfully")

                    # Step 1: Send LOGIN frame
                    if self.access_token:
                        await ws.send(f"LOGIN:{self.access_token}")

                    # Step 2: Auto-subscribe to default Indian indices
                    self._resubscribe_all()

                    # Step 3: Message read loop
                    async for message in ws:
                        if not self._running:
                            break
                        self._handle_message(message)

            except Exception as e:
                self._connected = False
                logger.warning(
                    f"m.Stock WebSocket connection dropped ({e}), retrying in {reconnect_delay:.1f}s..."
                )
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(30.0, reconnect_delay * 1.5)

    def _handle_message(self, message: Union[bytes, str]) -> None:
        """Handle incoming binary or text frame."""
        if isinstance(message, bytes):
            ticks = parse_binary_frame(message, token_map=self._token_map)
            for tick in ticks:
                self._process_tick(tick)
        elif isinstance(message, str):
            try:
                data = json.loads(message)
                logger.debug(f"m.Stock WS text message: {data}")
            except Exception:
                pass

    def _process_tick(self, tick: MStockTick) -> None:
        """Store tick in cache and dispatch to callbacks & ws_manager."""
        with self._lock:
            self._ticks[tick.token] = tick
            self._ticks[tick.symbol] = tick

        # Also push into central ws_manager tick registry for seamless unified consumption
        try:
            from market.websocket import Tick, _to_ws_symbol, ws_manager

            compat_tick = Tick(
                symbol=tick.symbol,
                ltp=tick.ltp,
                open=tick.open,
                high=tick.high,
                low=tick.low,
                close=tick.close,
                volume=tick.volume,
                change=tick.change,
                change_pct=tick.change_pct,
                timestamp=tick.timestamp,
                bid=tick.bids[0].price if tick.bids else 0.0,
                ask=tick.asks[0].price if tick.asks else 0.0,
            )
            with ws_manager._lock:
                ws_manager._ticks[tick.symbol] = compat_tick
                ws_manager._ticks[tick.token] = compat_tick
                ws_sym = _to_ws_symbol(tick.symbol)
                if ws_sym:
                    ws_manager._ticks[ws_sym] = compat_tick
        except Exception:
            pass

        # Dispatch registered callbacks
        for cb in self._callbacks:
            try:
                cb(tick)
            except Exception as e:
                logger.debug(f"Tick callback error: {e}")

    def subscribe(
        self,
        tokens_or_symbols: list[str],
        exchange_type: int = EXCHANGE_NSE_CASH,
        mode: int = 3,
    ) -> None:
        """
        Subscribe to real-time quotes for tokens or symbols.
        mode: 1 (LTP), 2 (Quote), 3 (Full with Market Depth).
        """
        resolved_tokens: list[str] = []
        for item in tokens_or_symbols:
            item_str = str(item).strip()
            # If item is already numeric token
            if item_str.isdigit():
                resolved_tokens.append(item_str)
            else:
                tok = SYMBOL_TO_TOKEN.get(item_str.upper())
                if tok:
                    resolved_tokens.append(tok)
                else:
                    resolved_tokens.append(item_str)

        if not resolved_tokens:
            return

        with self._lock:
            if exchange_type not in self._subscribed_tokens:
                self._subscribed_tokens[exchange_type] = set()
            self._subscribed_tokens[exchange_type].update(resolved_tokens)

        if self._connected and self._loop and self._ws:
            payload = {
                "action": 1,
                "params": {
                    "mode": mode,
                    "tokenList": [
                        {
                            "exchangeType": exchange_type,
                            "tokens": resolved_tokens,
                        }
                    ],
                },
            }
            asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps(payload)), self._loop)

    def unsubscribe(
        self,
        tokens_or_symbols: list[str],
        exchange_type: int = EXCHANGE_NSE_CASH,
        mode: int = 3,
    ) -> None:
        """Unsubscribe from tokens."""
        resolved_tokens: list[str] = []
        for item in tokens_or_symbols:
            item_str = str(item).strip()
            if item_str.isdigit():
                resolved_tokens.append(item_str)
            else:
                tok = SYMBOL_TO_TOKEN.get(item_str.upper())
                if tok:
                    resolved_tokens.append(tok)
                else:
                    resolved_tokens.append(item_str)

        with self._lock:
            if exchange_type in self._subscribed_tokens:
                self._subscribed_tokens[exchange_type].difference_update(resolved_tokens)

        if self._connected and self._loop and self._ws:
            payload = {
                "action": 2,
                "params": {
                    "mode": mode,
                    "tokenList": [
                        {
                            "exchangeType": exchange_type,
                            "tokens": resolved_tokens,
                        }
                    ],
                },
            }
            asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps(payload)), self._loop)

    def _resubscribe_all(self) -> None:
        """Resubscribe to all tokens on reconnect or initial connect."""
        # Ensure default indices are subscribed
        default_indices = ["26000", "26009", "26017"]
        with self._lock:
            self._subscribed_tokens[EXCHANGE_NSE_CASH].update(default_indices)

        for exch_type, tokens in self._subscribed_tokens.items():
            if tokens and self._ws and self._loop:
                payload = {
                    "action": 1,
                    "params": {
                        "mode": 3,
                        "tokenList": [
                            {
                                "exchangeType": exch_type,
                                "tokens": list(tokens),
                            }
                        ],
                    },
                }
                asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps(payload)), self._loop)


# Global singleton instance
mstock_ws = MStockWebSocket()
