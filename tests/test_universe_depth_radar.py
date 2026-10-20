"""
tests/test_universe_depth_radar.py
──────────────────────────────────
Unit tests for Institutional L2 Universe Depth Radar & decision intelligence.
"""

from market.universe_depth_radar import (
    get_universe_depth_radar,
    _build_l2_decision_intel,
)


def test_build_l2_decision_intel_scenarios():
    # 1. Resting Bid Wall
    bid_wall = _build_l2_decision_intel(
        symbol="RELIANCE",
        ltp=2950.0,
        obi=0.45,
        spread_bps=1.2,
        micro_skew_bps=2.1,
        has_resting_wall=True,
        wall_side="BID",
        wall_price=2940.0,
        wall_ratio=3.5,
        iceberg_detected=False,
        iceberg_side=None,
    )
    assert bid_wall["bias"] == "BULLISH"
    assert "DEMAND FLOOR" in bid_wall["badge"]
    assert "FAVOR CALLS / LONGS" in bid_wall["decision"]

    # 2. Resting Ask Wall
    ask_wall = _build_l2_decision_intel(
        symbol="INFY",
        ltp=1850.0,
        obi=-0.50,
        spread_bps=1.5,
        micro_skew_bps=-3.0,
        has_resting_wall=True,
        wall_side="ASK",
        wall_price=1860.0,
        wall_ratio=4.0,
        iceberg_detected=False,
        iceberg_side=None,
    )
    assert ask_wall["bias"] == "BEARISH"
    assert "SUPPLY CEILING" in ask_wall["badge"]
    assert "FAVOR PUTS / SHORTS" in ask_wall["decision"]

    # 3. Iceberg Buy
    iceberg = _build_l2_decision_intel(
        symbol="HDFCBANK",
        ltp=1680.0,
        obi=0.20,
        spread_bps=1.0,
        micro_skew_bps=1.0,
        has_resting_wall=False,
        wall_side=None,
        wall_price=None,
        wall_ratio=1.0,
        iceberg_detected=True,
        iceberg_side="BUY",
    )
    assert iceberg["bias"] == "BULLISH"
    assert "STEALTH BUY" in iceberg["badge"]

    # 4. Spread Shock
    spread_shock = _build_l2_decision_intel(
        symbol="MIDCPNIFTY",
        ltp=12500.0,
        obi=0.05,
        spread_bps=8.5,
        micro_skew_bps=0.2,
        has_resting_wall=False,
        wall_side=None,
        wall_price=None,
        wall_ratio=1.0,
        iceberg_detected=False,
        iceberg_side=None,
    )
    assert spread_shock["bias"] == "CAUTION"
    assert "SPREAD FRICTION" in spread_shock["badge"]
    assert "AVOID MARKET ORDERS" in spread_shock["decision"]

    # 5. Balanced Auction
    balanced = _build_l2_decision_intel(
        symbol="TCS",
        ltp=4100.0,
        obi=0.02,
        spread_bps=1.1,
        micro_skew_bps=0.1,
        has_resting_wall=False,
        wall_side=None,
        wall_price=None,
        wall_ratio=1.0,
        iceberg_detected=False,
        iceberg_side=None,
    )
    assert balanced["bias"] == "NEUTRAL"
    assert "BALANCED AUCTION" in balanced["badge"]


def test_get_universe_depth_radar_structure():
    rows = get_universe_depth_radar(segment="INDICES", limit=10)
    assert isinstance(rows, list)
    assert len(rows) > 0

    first = rows[0]
    required_keys = [
        "symbol",
        "segment",
        "ltp",
        "spread",
        "spread_bps",
        "spread_status",
        "total_bid_qty",
        "total_ask_qty",
        "bid_notional_cr",
        "ask_notional_cr",
        "obi",
        "obi_pct",
        "micro_price",
        "micro_skew_bps",
        "decision_intel",
        "bids",
        "asks",
        "provenance",
    ]
    for k in required_keys:
        assert k in first, f"Missing key: {k}"

    assert first["decision_intel"]["bias"] in ("BULLISH", "BEARISH", "CAUTION", "NEUTRAL")


def test_api_depth_radar_endpoint():
    from fastapi.testclient import TestClient
    from web.api import app

    client = TestClient(app)
    res = client.get("/api/market/depth-radar?segment=INDICES&limit=5")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "data" in data
    assert isinstance(data["data"], list)
    assert len(data["data"]) > 0
