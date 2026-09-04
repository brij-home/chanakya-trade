"""
tests/test_mstock_websocket.py
──────────────────────────────
Tests for m.Stock WebSocket client and 379-byte binary quote packet parser.
"""

import struct
import time
from unittest.mock import MagicMock, patch


from market.mstock_websocket import (
    MStockTick,
    MStockWebSocket,
    _DEPTH_ITEM_FMT,
    _QUOTE_379_FMT,
    parse_binary_frame,
    parse_ltp_packet,
    parse_market_depth,
    parse_quote_packet,
)


def _build_synthetic_depth_bytes() -> bytes:
    """Build 200 bytes containing 5 bids and 5 asks."""
    depth = bytearray()
    # 5 bids: prices 24000, 23995, 23990, 23985, 23980 (scaled * 100)
    for i in range(5):
        flag = 1
        qty = (5 - i) * 100
        price = int((24000.0 - i * 5) * 100)
        orders = 5 - i
        depth.extend(struct.pack(_DEPTH_ITEM_FMT, flag, qty, price, orders))

    # 5 asks: prices 24005, 24010, 24015, 24020, 24025 (scaled * 100)
    for i in range(5):
        flag = 2
        qty = (i + 1) * 100
        price = int((24005.0 + i * 5) * 100)
        orders = i + 1
        depth.extend(struct.pack(_DEPTH_ITEM_FMT, flag, qty, price, orders))

    return bytes(depth)


def _build_synthetic_379_packet(
    mode: int = 3,
    exchange_type: int = 1,
    token: str = "26000",
    sequence: int = 101,
    timestamp: int = 1756980000,
    ltp: float = 24500.50,
    volume: int = 1500000,
    open_p: float = 24400.0,
    high_p: float = 24550.0,
    low_p: float = 24350.0,
    close_p: float = 24420.0,
) -> bytes:
    """Build a valid 379-byte m.Stock quote packet."""
    raw_token = token.encode("utf-8").ljust(25, b"\x00")
    depth_bytes = _build_synthetic_depth_bytes()
    assert len(depth_bytes) == 200

    return struct.pack(
        _QUOTE_379_FMT,
        mode,
        exchange_type,
        raw_token,
        sequence,
        timestamp,
        int(ltp * 100),
        50,  # last_traded_qty
        int(ltp * 100),  # atp
        volume,
        500000.0,  # buy qty
        450000.0,  # sell qty
        int(open_p * 100),
        int(high_p * 100),
        int(low_p * 100),
        int(close_p * 100),
        timestamp,  # last_traded_ts
        100000,  # oi
        int(2.5 * 100),  # oi_pct
        depth_bytes,
        int(26800.0 * 100),  # upper circuit
        int(22000.0 * 100),  # lower circuit
        int(25000.0 * 100),  # 52w high
        int(21000.0 * 100),  # 52w low
    )


def test_parse_market_depth():
    depth_bytes = _build_synthetic_depth_bytes()
    assert len(depth_bytes) == 200
    bids, asks = parse_market_depth(depth_bytes)
    assert len(bids) == 5
    assert len(asks) == 5
    assert bids[0].price == 24000.0
    assert bids[0].quantity == 500
    assert asks[0].price == 24005.0
    assert asks[0].quantity == 100


def test_parse_quote_packet():
    data = _build_synthetic_379_packet(
        token="26000",
        ltp=24500.50,
        volume=1234567,
        close_p=24400.0,
    )
    assert len(data) == 379

    tick = parse_quote_packet(data)
    assert tick is not None
    assert tick.token == "26000"
    assert tick.symbol == "NSE:NIFTY 50"
    assert tick.ltp == 24500.50
    assert tick.change == 100.50
    assert tick.change_pct == 0.41
    assert tick.volume == 1234567
    assert len(tick.bids) == 5
    assert tick.bids[0].price == 24000.0
    assert tick.fifty_two_week_high == 25000.0


def test_parse_ltp_packet():
    token_bytes = b"26009".ljust(25, b"\x00")
    data = struct.pack(
        ">BB25sQqq",
        1,  # mode
        1,  # exch
        token_bytes,
        555,  # seq
        1756980000,  # ts
        int(52150.75 * 100),  # ltp
    )
    assert len(data) == 51
    tick = parse_ltp_packet(data)
    assert tick is not None
    assert tick.token == "26009"
    assert tick.symbol == "NSE:NIFTY BANK"
    assert tick.ltp == 52150.75


def test_parse_binary_frame_multiple_packets():
    p1 = _build_synthetic_379_packet(token="26000", ltp=24500.0)
    p2 = _build_synthetic_379_packet(token="26009", ltp=52000.0)
    frame = p1 + p2
    assert len(frame) == 379 * 2

    ticks = parse_binary_frame(frame)
    assert len(ticks) == 2
    assert ticks[0].token == "26000"
    assert ticks[0].ltp == 24500.0
    assert ticks[1].token == "26009"
    assert ticks[1].ltp == 52000.0


def test_mstock_websocket_tick_processing_and_ws_manager_sync():
    client = MStockWebSocket(api_key="key123", access_token="jwt456")
    received_ticks = []
    client.on_tick(lambda t: received_ticks.append(t))

    tick = MStockTick(
        mode=3,
        exchange_type=1,
        token="26000",
        symbol="NSE:NIFTY 50",
        sequence=1,
        timestamp=time.time(),
        ltp=24555.0,
        open=24400.0,
        high=24600.0,
        low=24380.0,
        close=24450.0,
        volume=1000000,
    )

    client._process_tick(tick)
    assert len(received_ticks) == 1
    assert received_ticks[0].ltp == 24555.0

    # Query from client
    queried = client.get_tick("NSE:NIFTY 50")
    assert queried is not None
    assert queried.ltp == 24555.0

    # Query from shared ws_manager
    from market.websocket import ws_manager

    shared_tick = ws_manager.get_tick("NSE:NIFTY 50")
    assert shared_tick is not None
    assert shared_tick.ltp == 24555.0


def test_mstock_websocket_subscription_messages():
    client = MStockWebSocket(api_key="key", access_token="tok")
    client._connected = True
    client._loop = MagicMock()
    client._ws = MagicMock()

    with patch("asyncio.run_coroutine_threadsafe") as mock_coro:
        client.subscribe(["26000", "NIFTY BANK"])
        assert mock_coro.called
        assert "26000" in client._subscribed_tokens[1]
        assert "26009" in client._subscribed_tokens[1]

        client.unsubscribe(["26000"])
        assert "26000" not in client._subscribed_tokens[1]
        assert "26009" in client._subscribed_tokens[1]
