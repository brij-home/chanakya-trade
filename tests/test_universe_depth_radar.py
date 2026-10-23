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


def test_l2_l3_wall_correlation_and_trap_avoidance():
    """
    Verifies that L2/L3 wall correlation eliminates false signals:
    1. Bid wall + negative OBI is classified as FRAGILE BID WALL / TRAP, not DEMAND FLOOR.
    2. Bid wall + L3 TBT spoof is classified as BULL TRAP / RUGPULL RISK.
    3. Ask wall + L3 TBT spoof is classified as BEAR TRAP / SHORT SQUEEZE.
    4. Ask wall + positive OBI is classified as FRAGILE ASK WALL / SQUEEZE.
    """
    # 1. Bid wall with negative OBI (-27% like MIDCPNIFTY) -> Fragile Bid Wall
    fragile_bid = _build_l2_decision_intel(
        symbol="NSE:MIDCPNIFTY26OCTFUT",
        ltp=13287.0,
        obi=-0.27,
        spread_bps=5.3,
        micro_skew_bps=2.0,
        has_resting_wall=True,
        wall_side="BID",
        wall_price=13287.0,
        wall_ratio=3.8,
        iceberg_detected=False,
        iceberg_side=None,
    )
    assert fragile_bid["bias"] == "CAUTION_BEAR"
    assert "FRAGILE BID WALL" in fragile_bid["badge"]
    assert "AVOID CALLS" in fragile_bid["decision"]

    # 2. Bid wall with active L3 TBT Spoof (Fake Bids Pulled like NIFTY) -> Bull Trap
    tbt_spoof_bid = {
        "status": "LIVE_STREAM_TBT_50",
        "obi_50": -0.42,
        "fleeing_bid_wall_detected": True,
        "recent_fleeing_event": {"price": 22740.0, "qty": 4500},
    }
    bull_trap = _build_l2_decision_intel(
        symbol="NSE:NIFTY26OCTFUT",
        ltp=22744.8,
        obi=-0.42,
        spread_bps=6.2,
        micro_skew_bps=2.1,
        has_resting_wall=True,
        wall_side="BID",
        wall_price=22744.7,
        wall_ratio=3.5,
        iceberg_detected=False,
        iceberg_side=None,
        tbt_depth=tbt_spoof_bid,
    )
    assert bull_trap["bias"] == "CAUTION_BEAR"
    assert "BULL TRAP / RUGPULL RISK" in bull_trap["badge"]
    assert "Fake Bids Pulled" in bull_trap["headline"]
    assert "DO NOT CHASE LONGS" in bull_trap["decision"]

    # 3. Ask wall with active L3 TBT Spoof (Fake Asks Pulled) -> Short Squeeze
    tbt_spoof_ask = {
        "status": "LIVE_STREAM_TBT_50",
        "obi_50": 0.35,
        "fleeing_ask_wall_detected": True,
        "recent_fleeing_event": {"price": 22850.0, "qty": 3800},
    }
    bear_trap = _build_l2_decision_intel(
        symbol="NSE:NIFTY26OCTFUT",
        ltp=22840.0,
        obi=0.35,
        spread_bps=4.0,
        micro_skew_bps=-1.0,
        has_resting_wall=True,
        wall_side="ASK",
        wall_price=22850.0,
        wall_ratio=3.0,
        iceberg_detected=False,
        iceberg_side=None,
        tbt_depth=tbt_spoof_ask,
    )
    assert bear_trap["bias"] == "BULLISH"
    assert "BEAR TRAP / SHORT SQUEEZE" in bear_trap["badge"]
    assert "Fake Asks Pulled" in bear_trap["headline"]

    # 4. Ask wall with positive OBI (+25%) -> Fragile Ask Wall
    fragile_ask = _build_l2_decision_intel(
        symbol="NSE:BANKNIFTY26OCTFUT",
        ltp=55000.0,
        obi=0.25,
        spread_bps=2.0,
        micro_skew_bps=-1.0,
        has_resting_wall=True,
        wall_side="ASK",
        wall_price=55020.0,
        wall_ratio=3.2,
        iceberg_detected=False,
        iceberg_side=None,
    )
    assert fragile_ask["bias"] == "BULLISH"
    assert "FRAGILE ASK WALL" in fragile_ask["badge"]
    assert "DO NOT SHORT" in fragile_ask["decision"]


def test_fno_stocks_resolution_and_radar_depth():
    """Verify that F&O stocks resolve to valid near-month derivatives and return structured depth."""
    from market.universe_depth_radar import _get_active_fno_stock_symbols, get_universe_depth_radar
    from market.fyers_tbt_manager import resolve_stock_future

    # 1. Canonical F&O Stock Future resolution
    symbols = _get_active_fno_stock_symbols()
    assert len(symbols) >= 25
    assert any("RELIANCE" in s and s.endswith("FUT") for s in symbols)
    assert any("HDFCBANK" in s and s.endswith("FUT") for s in symbols)
    assert any("TMPV" in s and s.endswith("FUT") for s in symbols)

    # 2. Corporate demerger mapping
    assert resolve_stock_future("TATAMOTORS").startswith("NSE:TMPV")

    # 3. Depth radar query on STOCKS segment
    rows = get_universe_depth_radar(segment="STOCKS", limit=5, allow_rest_fallback=False)
    assert len(rows) > 0
    first = rows[0]
    assert first["segment"] == "STOCK_FNO"
    assert first["symbol"].startswith("NSE:")
    assert "FUT" in first["symbol"] or "-EQ" in first["symbol"]
    assert "decision_intel" in first
    assert "badge" in first["decision_intel"]


def test_fno_stock_futures_tbt_slot_allocation_and_cached_depth(monkeypatch):
    """Verify that FyersTbtManager allocates available slots up to 15 to liquid F&O stock futures during open market."""
    monkeypatch.setattr("market.calendar.is_market_open", lambda exch="NSE", ref_dt=None: True)
    monkeypatch.setattr("market.fyers_tbt_manager.get_market_session", lambda: "EQUITY_NFO")

    from market.fyers_tbt_manager import FyersTbtManager
    from market.order_book import get_depth_book, analyze_symbol_order_book

    tbt = FyersTbtManager()
    tbt.reset_for_testing()
    tbt.refresh_grid("EQUITY_NFO")
    # Query Depth Radar for STOCKS to dynamically subscribe top F&O stocks to TBT scout pool
    from market.universe_depth_radar import get_universe_depth_radar, clear_radar_cache

    clear_radar_cache()
    get_universe_depth_radar(segment="STOCKS", limit=15, allow_rest_fallback=False)
    desired = tbt.compute_desired_subscriptions()

    # Verify that desired slots are populated up to 15 with index + stock futures
    assert len(desired) == 15
    assert desired[0].startswith("NSE:") and "NIFTY" in desired[0]
    assert any("RELIANCE" in s for s in desired)
    assert any("HDFCBANK" in s for s in desired)
    assert any("ICICIBANK" in s for s in desired)

    # Seed depth book for RELIANCE future to simulate live streaming L2
    rel_fut = [s for s in desired if "RELIANCE" in s][0]
    clean_rel = rel_fut.replace("NSE:", "")
    book = get_depth_book(clean_rel)
    book.batch_update(
        [
            {"price": 1205.0, "quantity": 1000, "orders": 5},
            {"price": 1204.5, "quantity": 500, "orders": 2},
        ],
        [
            {"price": 1205.5, "quantity": 800, "orders": 4},
            {"price": 1206.0, "quantity": 600, "orders": 3},
        ],
    )

    snap = analyze_symbol_order_book(rel_fut, allow_rest_fallback=False)
    assert snap.total_bid_qty > 0
    assert snap.total_ask_qty > 0
    assert snap.spread > 0
    assert len(snap.bids) > 0
    assert len(snap.asks) > 0
    assert snap.provenance == "LIVE_STREAM_L2"


def test_evening_session_tbt_standby_and_radar_mcx_prioritization(monkeypatch):
    """Verify that during evening session (15:30-23:30 IST):
    1. TBT enters STANDBY_EOD with zero closed daytime dynamic subscriptions.
    2. Depth Radar with segment=ALL prioritizes active MCX Commodities and CDS Currencies.
    3. Closed daytime stocks return is_market_open=False and EOD_SETTLEMENT provenance.
    """
    monkeypatch.setattr(
        "market.calendar.is_market_open",
        lambda exch="NSE", ref_dt=None: False if exch in ("NSE", "NFO") else True,
    )
    monkeypatch.setattr("market.fyers_tbt_manager.get_market_session", lambda: "COMMODITY_CDS")

    from market.fyers_tbt_manager import FyersTbtManager
    from market.universe_depth_radar import get_universe_depth_radar

    tbt = FyersTbtManager()
    tbt.switch_session("COMMODITY_CDS")
    status = tbt.get_active_slots_status()

    # 1. TBT enters Standby EOD
    assert status["session_state"] == "STANDBY_EOD"
    assert "15:30 IST" in status["session_note"]
    assert len(status["scout"]) == 0
    assert len(status["in_flight"]) == 0

    # 2. Depth Radar with segment=ALL contains MCX and CDS
    rows_all = get_universe_depth_radar(segment="ALL", limit=20, allow_rest_fallback=False)
    symbols_all = [r["symbol"] for r in rows_all]
    assert any("MCX:" in s or "CRUDEOIL" in s or "GOLD" in s for s in symbols_all)
    assert any("CDS:" in s or "USDINR" in s for s in symbols_all)

    # 3. Explicit query on STOCKS segment returns EOD settlement
    rows_stocks = get_universe_depth_radar(segment="STOCKS", limit=5, allow_rest_fallback=False)
    assert len(rows_stocks) > 0
    for r in rows_stocks:
        assert r["is_market_open"] is False
        assert r["provenance"] == "EOD_SETTLEMENT"
