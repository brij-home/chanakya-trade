"""
tests/test_phantom_wall_and_micro_price.py
──────────────────────────────────────────
Deterministic unit tests for:
1. Micro-Price Skew & Order Flow Posture (FyersTbtManager).
2. Fleeing / Phantom Wall Spoofing Detection (FyersTbtManager).
3. Fortress Wall Absorption Confirmation (FyersTbtManager).
4. Anti-Spoof Rug-Pull Veto in OrderBookThrustDetector.
"""

from __future__ import annotations

import time

from engine.detection_context import build_detection_context
from engine.detectors.order_book_thrust import detect_order_book_thrust
from market.fyers_tbt_manager import FyersTbtManager


class MockProtoDepth:
    def __init__(
        self,
        bid_prices: list[float],
        bid_qtys: list[int],
        ask_prices: list[float],
        ask_qtys: list[int],
    ) -> None:
        self.bidprice = bid_prices
        self.bidqty = bid_qtys
        self.bidordn = [3] * len(bid_prices)
        self.askprice = ask_prices
        self.askqty = ask_qtys
        self.askordn = [3] * len(ask_prices)
        self.tbq = sum(bid_qtys)
        self.tsq = sum(ask_qtys)
        self.timestamp = int(time.time())


def test_micro_price_skew_computation():
    """Verify micro-price calculation and basis-points skew against LTP."""
    mgr = FyersTbtManager()
    sym = "NSE:TEST_SKEW-EQ"

    # Synthetic depth: heavy bid qty close to LTP -> micro_price > LTP (bullish skew)
    proto = MockProtoDepth(
        bid_prices=[25000.0],
        bid_qtys=[10000],
        ask_prices=[25001.0],
        ask_qtys=[2000],
    )
    mgr._handle_depth_update(sym, proto)

    res = mgr.get_50_depth(sym)
    assert res is not None
    assert res["micro_price_skew_bps"] > 0.25
    assert res["order_flow_posture"] == "BULLISH_PRESSURE"


def test_fleeing_bid_wall_spoof_detection():
    """
    Verify that a substantial bid wall disappearing right near spot (distance <= 0.15%)
    triggers a fleeing wall spoof alert.
    """
    mgr = FyersTbtManager()
    sym = "NSE:TEST_SPOOF-EQ"

    # Step 1: Substantial bid wall at 2498.0 (distance 0.08% from 2500.0)
    proto_1 = MockProtoDepth(
        bid_prices=[2499.5, 2499.0, 2498.0],
        bid_qtys=[500, 500, 15000],  # Big Wall at level 3
        ask_prices=[2500.5, 2501.0, 2502.0],
        ask_qtys=[500, 500, 500],
    )
    mgr._handle_depth_update(sym, proto_1)

    # First call stamps the active wall
    res_1 = mgr.get_50_depth(sym)
    assert res_1["has_bid_wall"] is True
    assert res_1["fleeing_bid_wall_detected"] is False

    # Step 2: In the very next tick, the 15,000 wall at 2498.0 vanishes! (Spoof fled)
    proto_2 = MockProtoDepth(
        bid_prices=[2499.5, 2499.0, 2498.0],
        bid_qtys=[500, 500, 100],  # Vanished down to 100
        ask_prices=[2500.5, 2501.0, 2502.0],
        ask_qtys=[500, 500, 500],
    )
    mgr._handle_depth_update(sym, proto_2)

    res_2 = mgr.get_50_depth(sym)
    assert res_2["fleeing_bid_wall_detected"] is True
    assert "BID_SPOOF_RUGPULL_RISK" in res_2["spoof_trap_warning"]


def test_fortress_wall_absorption_confirmation():
    """Verify that a fortress wall persisting >= 15 seconds gets confirmed as real absorption."""
    mgr = FyersTbtManager()
    sym = "NSE:TEST_FORTRESS-EQ"

    # Inject an active wall with first_seen 16 seconds ago
    now = time.time()
    state = mgr._wall_history.setdefault(sym, {"active_walls": {}, "recent_fleeing": []})
    state["active_walls"]["BID:25000.00"] = {
        "side": "BID",
        "price": 25000.0,
        "first_seen": now - 16.0,
        "last_seen": now,
        "peak_qty": 50000,
        "last_qty": 50000,
        "distance_pct": 0.10,
        "duration": 16.0,
        "strength": "FORTRESS",
    }

    proto = MockProtoDepth(
        bid_prices=[25002.0, 25001.0, 25000.0, 24999.0, 24998.0],
        bid_qtys=[100, 100, 50000, 100, 100],
        ask_prices=[25003.0, 25004.0],
        ask_qtys=[100, 100],
    )
    mgr._handle_depth_update(sym, proto)

    res = mgr.get_50_depth(sym)
    assert res["fortress_bid_wall_confirmed"] is True
    assert "FORTRESS_BID_ABSORPTION" in res["absorption_note"]


def test_order_book_thrust_vetoed_on_fleeing_bid_spoof():
    """
    Bullish order book thrust must be vetoed if fleeing_bid_wall_detected is True,
    protecting traders from buying into a spoofed rug-pull.
    """
    ctx = build_detection_context(
        symbol="NSE:RELIANCE",
        ltp=2500.0,
        vwap=2495.0,
    )
    # Synthetic depth with strong OBI (+0.60), but with fleeing_bid_wall_detected = True
    ctx.extra_metrics["depth_50"] = {
        "symbol": "NSE:RELIANCE",
        "status": "LIVE",
        "ltp": 2500.0,
        "obi_50": 0.60,
        "tbq": 80000,
        "tsq": 20000,
        "density_score": 35.0,
        "bids": [{"price": 2499.5, "qty": 5000}],
        "asks": [{"price": 2500.5, "qty": 1000}],
        "bid_walls": [{"price": 2490.0, "qty": 10000, "strength": "STRONG"}],
        "ask_walls": [],
        "fleeing_bid_wall_detected": True,  # SPOOF DETECTED!
        "fleeing_ask_wall_detected": False,
        "fortress_bid_wall_confirmed": False,
        "fortress_ask_wall_confirmed": False,
        "micro_price_skew_bps": 2.0,
    }

    alerts = detect_order_book_thrust(ctx)
    assert len(alerts) == 0  # Rug-pull spoof prevented!


def test_order_book_thrust_boosted_on_fortress_and_fleeing_ask():
    """
    When fortress bid wall is confirmed and fleeing ask wall occurs,
    bullish order book thrust confidence is boosted and noted in summary.
    """
    ctx = build_detection_context(
        symbol="NSE:RELIANCE",
        ltp=2500.0,
        vwap=2495.0,
    )
    ctx.extra_metrics["depth_50"] = {
        "symbol": "NSE:RELIANCE",
        "status": "LIVE",
        "ltp": 2500.0,
        "obi_50": 0.65,
        "tbq": 80000,
        "tsq": 20000,
        "density_score": 35.0,
        "bids": [{"price": 2499.5, "qty": 5000}],
        "asks": [{"price": 2500.5, "qty": 1000}],
        "bid_walls": [{"price": 2490.0, "qty": 10000, "strength": "FORTRESS"}],
        "ask_walls": [],
        "fleeing_bid_wall_detected": False,
        "fleeing_ask_wall_detected": True,  # Sellers' ask wall fled!
        "fortress_bid_wall_confirmed": True,  # Fortress bid floor verified!
        "micro_price_skew_bps": 4.5,
    }

    alerts = detect_order_book_thrust(ctx)
    assert len(alerts) == 1
    a = alerts[0]
    assert a.direction == "BULLISH"
    assert a.confidence >= 94.0
    assert "Fortress Bid Floor Verified" in a.summary
    assert "Ask Resistance Fled" in a.summary
