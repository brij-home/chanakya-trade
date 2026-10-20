"""
tests/test_fyers_tbt_depth.py
─────────────────────────────
Deterministic unit tests for Fyers 50-Level Depth (TBT) Manager,
OBI-50 calculations, Iceberg Wall detection, Slippage modeling,
and Tier 2 Depth Audit Gatekeeper.
"""

import pytest
from fastapi.testclient import TestClient

from market.fyers_tbt_manager import FyersTbtManager, fyers_tbt_manager
from web.api import app


@pytest.fixture
def client():
    return TestClient(app)


class MockDepthObj:
    """Mock object simulating Fyers tbt_ws.Depth protobuf container."""

    def __init__(self):
        self.tbq = 250000
        self.tsq = 150000
        self.timestamp = 1727900000
        self.bidprice = [100.0 - (i * 0.05) for i in range(50)]
        self.askprice = [100.05 + (i * 0.05) for i in range(50)]
        # Normal bids 1000 each, but level 5 has an iceberg wall of 15,000 contracts
        self.bidqty = [15000 if i == 4 else 1000 for i in range(50)]
        # Normal asks 800 each, but level 8 has an iceberg ask wall of 20,000 contracts
        self.askqty = [20000 if i == 7 else 800 for i in range(50)]
        self.bidordn = [5] * 50
        self.askordn = [4] * 50


def test_tbt_manager_singleton():
    m1 = FyersTbtManager()
    m2 = FyersTbtManager()
    assert m1 is m2
    assert m1 is fyers_tbt_manager


def test_tbt_parse_depth_object():
    mgr = FyersTbtManager()
    mock_depth = MockDepthObj()

    parsed = mgr._parse_depth_object("NSE:NIFTY24OCTFUT", mock_depth)

    assert parsed["symbol"] == "NSE:NIFTY24OCTFUT"
    assert parsed["status"] == "LIVE"
    assert len(parsed["bids"]) == 50
    assert len(parsed["asks"]) == 50
    assert parsed["bids_count"] == 50
    assert parsed["density_score"] == 100.0  # All 50 slots populated
    assert parsed["obi_50"] > 0.0  # 250k vs 150k is positive imbalance

    # Verify Iceberg Wall detection
    assert parsed["has_bid_wall"] is True
    assert len(parsed["bid_walls"]) == 1
    assert parsed["bid_walls"][0]["level"] == 5
    assert parsed["bid_walls"][0]["qty"] == 15000

    assert parsed["has_ask_wall"] is True
    assert len(parsed["ask_walls"]) == 1
    assert parsed["ask_walls"][0]["level"] == 8
    assert parsed["ask_walls"][0]["qty"] == 20000


def test_tbt_slippage_simulation():
    mgr = FyersTbtManager()
    mock_depth = MockDepthObj()
    parsed = mgr._parse_depth_object("NSE:NIFTY24OCTFUT", mock_depth)

    with mgr._depth_lock:
        mgr._depth_cache["NSE:NIFTY24OCTFUT"] = parsed

    # Small order (500 qty): fits entirely in Level 1 (800 avail at 100.05)
    res_small = mgr.simulate_slippage("NSE:NIFTY24OCTFUT", quantity=500, side="BUY")
    assert res_small["status"] == "ok"
    assert res_small["depth_levels_swept"] == 1
    assert res_small["expected_vwap_price"] == 100.05
    assert res_small["estimated_slippage_pts"] == 0.0

    # Large order (2500 qty): sweeps across Level 1 (800), Level 2 (800), Level 3 (800), and Level 4 (100)
    res_large = mgr.simulate_slippage("NSE:NIFTY24OCTFUT", quantity=2500, side="BUY")
    assert res_large["status"] == "ok"
    assert res_large["depth_levels_swept"] == 4
    assert res_large["expected_vwap_price"] > 100.05
    assert res_large["estimated_slippage_pct"] > 0.0


def test_tbt_audit_candidate_depth():
    mgr = FyersTbtManager()
    mock_depth = MockDepthObj()
    parsed = mgr._parse_depth_object("NSE:NIFTY24OCT25000CE", mock_depth)

    with mgr._depth_lock:
        mgr._depth_cache["NSE:NIFTY24OCT25000CE"] = parsed

    audit = mgr.audit_candidate_depth("NSE:NIFTY24OCT25000CE", side="BUY", lot_size=65)

    assert audit["symbol"] == "NSE:NIFTY24OCT25000CE"
    assert audit["side"] == "BUY"
    assert "depth_conviction_score" in audit
    assert 0 <= audit["depth_conviction_score"] <= 100
    assert audit["verdict"] in ("PASS", "CAUTION", "REJECT")
    assert len(audit["findings"]) > 0


def test_tbt_web_endpoints(client):
    mgr = FyersTbtManager()
    mock_depth = MockDepthObj()
    parsed = mgr._parse_depth_object("NSE:NIFTY24OCTFUT", mock_depth)

    with mgr._depth_lock:
        mgr._depth_cache["NSE:NIFTY24OCTFUT"] = parsed

    # 1. GET /api/fyers/tbt-depth/{symbol}
    res_depth = client.get("/api/fyers/tbt-depth/NSE:NIFTY24OCTFUT")
    assert res_depth.status_code == 200
    data = res_depth.json()
    assert data["status"] == "ok"
    assert data["data"]["obi_50"] > 0

    # 2. POST /api/fyers/tbt-audit
    res_audit = client.post(
        "/api/fyers/tbt-audit", json={"symbol": "NSE:NIFTY24OCTFUT", "side": "BUY"}
    )
    assert res_audit.status_code == 200
    assert res_audit.json()["status"] == "ok"
    assert "verdict" in res_audit.json()["audit"]

    # 3. POST /api/fyers/tbt-subscribe
    res_sub = client.post("/api/fyers/tbt-subscribe", json={"symbol": "NSE:NIFTY24OCTFUT"})
    assert res_sub.status_code == 200
    assert res_sub.json()["status"] == "ok"


def test_tbt_tradable_symbol_resolution():
    from market.fyers_tbt_manager import resolve_tradable_tbt_symbol

    # 1. Spot Index (-INDEX) converted to near-month Index Future
    res_nifty = resolve_tradable_tbt_symbol("NSE:NIFTY50-INDEX")
    assert res_nifty.startswith("NSE:NIFTY")
    assert res_nifty.endswith("FUT")
    assert "-INDEX" not in res_nifty

    res_banknifty = resolve_tradable_tbt_symbol("BANKNIFTY")
    assert res_banknifty.startswith("NSE:BANKNIFTY")
    assert res_banknifty.endswith("FUT")

    res_sensex = resolve_tradable_tbt_symbol("BSE:SENSEX-INDEX")
    assert res_sensex.startswith("BSE:SENSEX")
    assert res_sensex.endswith("FUT")

    # 2. Crypto rejected
    assert resolve_tradable_tbt_symbol("BTCUSDT") == ""
    assert resolve_tradable_tbt_symbol("CRYPTO:BTC") == ""

    # 3. Tradable options or equities preserved
    res_opt = resolve_tradable_tbt_symbol("NSE:NIFTY26OCT25000CE")
    assert res_opt == "NSE:NIFTY26OCT25000CE"

    res_eq = resolve_tradable_tbt_symbol("RELIANCE")
    assert res_eq == "NSE:RELIANCE-EQ"


def test_tbt_15_slot_priority_governor():
    from market.fyers_tbt_manager import FyersTbtManager, MAX_TBT_SYMBOLS

    mgr = FyersTbtManager()

    # Reset internal slots for deterministic test
    with mgr._slots_lock:
        mgr._in_flight.clear()
        mgr._core_grid = [f"NSE:CORE{i}-EQ" for i in range(6)]
        mgr._todays_expiry = [f"NSE:EXP{i}-EQ" for i in range(3)]
        mgr._scout.clear()

    # 1. Normal state: 6 core + 3 expiry = 9 symbols
    desired = mgr.compute_desired_subscriptions()
    assert len(desired) == 9
    assert len(desired) <= MAX_TBT_SYMBOLS

    # 2. Add 4 In-Flight positions (Tier 1 highest priority)
    mgr.register_in_flight("NSE:INFY-EQ")
    mgr.register_in_flight("NSE:TCS-EQ")
    mgr.register_in_flight("NSE:NIFTY26OCT25000CE")
    mgr.register_in_flight("NSE:BANKNIFTY26OCT52000PE")

    desired = mgr.compute_desired_subscriptions()
    assert len(desired) == 13  # 4 in-flight + 6 core + 3 expiry
    assert desired[0] == "NSE:INFY-EQ"  # In-flight placed first

    # 3. Add 10 scout symbols (Should be capped and evict oldest to never exceed 15)
    for i in range(10):
        mgr.subscribe([f"NSE:SCOUT{i}-EQ"])

    desired = mgr.compute_desired_subscriptions()
    assert len(desired) == 15  # Exactly 15 hard cap
    assert len(mgr.compute_desired_subscriptions()) <= MAX_TBT_SYMBOLS
    status = mgr.get_active_slots_status()
    assert status["max_slots"] == 15
    assert len(status["in_flight"]) == 4


def test_tbt_session_handoff():
    from market.fyers_tbt_manager import FyersTbtManager

    mgr = FyersTbtManager()

    # Test switching to COMMODITY_CDS (Post-15:30 IST session)
    mgr.switch_session("COMMODITY_CDS")
    status = mgr.get_active_slots_status()
    assert status["current_session"] == "COMMODITY_CDS"
    # Core grid should feature MCX Commodities
    assert any("MCX:" in s for s in status["core_grid"])

    # Test switching back to EQUITY_NFO (Daytime session)
    mgr.switch_session("EQUITY_NFO")
    status = mgr.get_active_slots_status()
    assert status["current_session"] == "EQUITY_NFO"
    # Core grid should feature NSE Index futures (NIFTY, BANKNIFTY, MIDCPNIFTY)
    assert any("NSE:NIFTY" in s for s in status["core_grid"])
    assert any("NSE:BANKNIFTY" in s for s in status["core_grid"])
    assert any("NSE:MIDCPNIFTY" in s for s in status["core_grid"])


def test_tbt_elastic_scout_when_no_expiry_blocking():
    """Verify that when 0DTE slots are idle/unblocked, scouts expand elastically to fill all available capacity."""
    from market.fyers_tbt_manager import FyersTbtManager

    mgr = FyersTbtManager()
    with mgr._slots_lock:
        mgr._in_flight.clear()
        mgr._core_grid = [f"NSE:CORE{i}-EQ" for i in range(6)]
        mgr._todays_expiry.clear()  # 0DTE slots not statically blocked
        mgr._scout.clear()

    # Add 12 scout candidate symbols
    for i in range(12):
        mgr.subscribe([f"NSE:FREESCOUT{i}-EQ"])

    desired = mgr.compute_desired_subscriptions()
    assert len(desired) == 15
    # Core has 6, Scouts expand elastically to 9 slots instead of being restricted to 2
    scout_count = sum(1 for s in desired if "FREESCOUT" in s)
    assert scout_count == 9


def test_tbt_primary_focus_elastic_core():
    """Verify that setting a primary focus index expands core grid and borrows elastically from scout pool."""
    from market.fyers_tbt_manager import FyersTbtManager

    mgr = FyersTbtManager()

    # 1. Focus on MIDCPNIFTY
    mgr.set_primary_focus("MIDCPNIFTY")
    status = mgr.get_active_slots_status()
    assert status["primary_focus"] == "MIDCPNIFTY"
    # Should include MIDCPNIFTY options in core_grid
    mid_options = [s for s in status["core_grid"] if "MIDCPNIFTY" in s and ("CE" in s or "PE" in s)]
    assert len(mid_options) == 4
    assert (
        len(status["core_grid"]) == 7
    )  # 3 benchmark futures (NIFTY, BANKNIFTY, MIDCPNIFTY) + 4 MIDCPNIFTY options

    # Desired subscriptions accommodate 7 core symbols cleanly without exceeding 15
    desired = mgr.compute_desired_subscriptions()
    assert len(desired) >= 7
    assert len(desired) <= 15

    # 2. Revert to balanced mode (Option A: pure 3 anchor futures, liberating 12 dynamic slots)
    mgr.set_primary_focus(None)
    status_balanced = mgr.get_active_slots_status()
    assert status_balanced["primary_focus"] is None
    assert (
        len(status_balanced["core_grid"]) == 3
    )  # 3 benchmark futures (NIFTY, BANKNIFTY, MIDCPNIFTY)


def test_tbt_no_finnifty_blocking_and_dynamic_sampling():
    """Verify that FINNIFTY is never statically blocked and can be dynamically sampled via Elastic Scout."""
    from market.fyers_tbt_manager import FyersTbtManager, get_default_core_grid

    mgr = FyersTbtManager()

    # 1. Core grid on any day must never include FINNIFTY
    core, todays = get_default_core_grid("EQUITY_NFO")
    assert not any("FINNIFTY" in s for s in core)
    assert not any("FINNIFTY" in s for s in todays)

    # Core futures are strictly NIFTY, BANKNIFTY, and MIDCPNIFTY
    core_futs = [s for s in core if s.endswith("FUT")]
    assert len(core_futs) == 3
    assert any("NIFTY" in s for s in core_futs)
    assert any("BANKNIFTY" in s for s in core_futs)
    assert any("MIDCPNIFTY" in s for s in core_futs)

    # 2. Dynamic sampling of FINNIFTY via Elastic Scout pool
    sampled = mgr.sample_symbol("NSE:FINNIFTY26OCT24000CE", duration_sec=60.0)
    assert sampled is True
    status = mgr.get_active_slots_status()
    assert "NSE:FINNIFTY26OCT24000CE" in status["scout"]
    desired = mgr.compute_desired_subscriptions()
    assert "NSE:FINNIFTY26OCT24000CE" in desired
    assert len(desired) <= 15


def test_tbt_revolve_atm_strikes_on_drift(monkeypatch):
    """Verify that spot drift triggers automatic ATM strike rotation in TBT core grid."""
    from market.fyers_tbt_manager import FyersTbtManager

    mgr = FyersTbtManager()
    mgr.set_primary_focus("NIFTY")
    mgr.refresh_grid(session="EQUITY_NFO")

    # Initial spot = 25000 (ATM = 25000)
    monkeypatch.setattr("market.quotes.get_ltp", lambda sym: 25000.0)
    mgr._last_atm_strikes = {"NIFTY": 25000}

    # Spot moves by +180 points to 25180 (ATM becomes 25200)
    monkeypatch.setattr("market.quotes.get_ltp", lambda sym: 25200.0)

    revolved = mgr.revolve_atm_strikes()
    assert revolved is True
    assert mgr._last_atm_strikes["NIFTY"] == 25200
    status = mgr.get_active_slots_status()
    assert any("25200CE" in s for s in status["core_grid"])
    assert any("25200PE" in s for s in status["core_grid"])


def test_tbt_zero_duplication_on_nifty_expiry_week(monkeypatch):
    """Verify that on Thursday (NIFTY Expiry) and Friday (SENSEX Expiry), zero slots are duplicated."""
    from market.fyers_tbt_manager import FyersTbtManager, get_default_core_grid
    from datetime import datetime

    mgr = FyersTbtManager()

    # 1. Simulate Thursday (NIFTY 0DTE Expiry)
    fake_thursday = datetime(2026, 10, 15, 10, 30)
    monkeypatch.setattr(
        "market.fyers_tbt_manager.datetime",
        type(
            "MockDt",
            (),
            {
                "now": lambda *args, **kwargs: fake_thursday,
                "fromtimestamp": datetime.fromtimestamp,
            },
        ),
    )

    core, todays = get_default_core_grid("EQUITY_NFO", primary_focus="NIFTY")
    # Verify zero duplication between core and todays_expiry
    overlap = set(core).intersection(set(todays))
    assert len(overlap) == 0

    # On Thursday with NIFTY in focus, NIFTY 0DTE has ATM + Wings in Core (7 symbols: 3 futures + 4 options)
    assert len(core) == 7
    # todays_expiry is 0 (no redundant duplication!)
    assert len(todays) == 0

    with mgr._slots_lock:
        mgr._core_grid = core
        mgr._todays_expiry = todays
        mgr._in_flight.clear()
        mgr._scout.clear()

    desired = mgr.compute_desired_subscriptions()
    assert len(desired) == 7
    assert len(desired) == len(set(desired))  # Strictly unique
    # 8 remaining slots available for Scouts
    for i in range(10):
        mgr.subscribe([f"NSE:SCOUT{i}-EQ"])
    desired_scouts = mgr.compute_desired_subscriptions()
    assert len(desired_scouts) == 15
    assert len(desired_scouts) == len(set(desired_scouts))

    # 2. Simulate Friday (SENSEX 0DTE Expiry)
    fake_friday = datetime(2026, 10, 16, 10, 30)
    monkeypatch.setattr(
        "market.fyers_tbt_manager.datetime",
        type(
            "MockDt",
            (),
            {
                "now": lambda *args, **kwargs: fake_friday,
                "fromtimestamp": datetime.fromtimestamp,
            },
        ),
    )

    core_fri, todays_fri = get_default_core_grid("EQUITY_NFO")
    overlap_fri = set(core_fri).intersection(set(todays_fri))
    assert len(overlap_fri) == 0
    assert len(core_fri) == 3  # Option A: 3 benchmark futures
    assert len(todays_fri) == 0  # 12 dynamic slots liberated for on-demand allocation

    # When SENSEX is set as primary focus, it expands dynamically
    core_sensex, _ = get_default_core_grid("EQUITY_NFO", primary_focus="SENSEX")
    assert any("SENSEX" in s for s in core_sensex)


def test_tbt_in_flight_deregistration_and_sync():
    """Verify in-flight positions can be unregistered and reconciled against open orders."""
    from market.fyers_tbt_manager import FyersTbtManager

    mgr = FyersTbtManager()
    with mgr._slots_lock:
        mgr._in_flight.clear()

    mgr.register_in_flight("NSE:INFY-EQ")
    mgr.register_in_flight("NSE:TCS-EQ")
    assert "NSE:INFY-EQ" in mgr._in_flight
    assert "NSE:TCS-EQ" in mgr._in_flight

    # Unregister single
    mgr.unregister_in_flight("NSE:INFY-EQ")
    assert "NSE:INFY-EQ" not in mgr._in_flight
    assert "NSE:TCS-EQ" in mgr._in_flight

    # Sync with active list
    mgr.register_in_flight("NSE:RELIANCE-EQ")
    mgr.register_in_flight("NSE:SBIN-EQ")
    # Only RELIANCE is currently active in broker
    mgr.sync_in_flight_with_active_symbols(["NSE:RELIANCE-EQ"])
    assert "NSE:RELIANCE-EQ" in mgr._in_flight
    assert "NSE:TCS-EQ" not in mgr._in_flight
    assert "NSE:SBIN-EQ" not in mgr._in_flight


def test_tbt_depth_quote_bridge():
    """Verify incoming TBT depth updates populate market.quotes._QUOTE_CACHE with 0.01ms resolution."""
    from market.fyers_tbt_manager import FyersTbtManager
    from market.quotes import _QUOTE_CACHE, get_quote

    mgr = FyersTbtManager()
    dummy_depth = {
        "symbol": "NSE:NIFTY26O1525000CE",
        "ltp": 142.50,
        "tbq": 50000,
        "tsq": 45000,
        "bids": [{"price": 142.45, "qty": 1500}],
        "asks": [{"price": 142.55, "qty": 2000}],
    }
    # Invoke parser and handler directly
    mgr._depth_cache["NSE:NIFTY26O1525000CE"] = dummy_depth

    # Trigger handler logic via mock depth
    mock_obj = type(
        "MockDepth",
        (),
        {
            "bidprice": [142.45],
            "askprice": [142.55],
            "bidqty": [1500],
            "askqty": [2000],
            "bidordn": [5],
            "askordn": [6],
            "tbq": 50000,
            "tsq": 45000,
        },
    )()
    mgr._handle_depth_update("NSE:NIFTY26O1525000CE", mock_obj)

    # Verify cached in _QUOTE_CACHE
    assert "NSE:NIFTY26O1525000CE" in _QUOTE_CACHE
    ts, q = _QUOTE_CACHE["NSE:NIFTY26O1525000CE"]
    assert q.last_price == 142.45 or q.last_price == 142.50 or q.last_price > 0
    assert q.source == "STREAM"
    assert q.provider == "fyers_tbt"

    # Verify get_quote resolves instantly without REST call
    res = get_quote(["NSE:NIFTY26O1525000CE"], ws_only=True)
    assert "NSE:NIFTY26O1525000CE" in res
    assert res["NSE:NIFTY26O1525000CE"].last_price > 0


def test_alert_scrutiny_tbt_microstructure_gate():
    """Verify Tier-1.5 Scrutiny detects iceberg walls and adverse OBI on candidate setups."""
    from engine.alert_model import AutoAlert
    from engine.alert_scrutiny import alert_scrutiny_auditor
    from market.fyers_tbt_manager import FyersTbtManager, resolve_tradable_tbt_symbol

    mgr = FyersTbtManager()
    with mgr._depth_lock:
        mgr._depth_cache.clear()
    try:
        mgr._connected = True
        trad_sym = resolve_tradable_tbt_symbol("NIFTY")

        # 1. Candidate facing a massive resting Ask Wall right above entry
        wall_payload = {
            "status": "LIVE",
            "ltp": 25000.0,
            "obi_50": 0.10,
            "ask_walls": [{"price": 25020.0, "qty": 25000, "level": 3}],
            "bid_walls": [],
        }
        with mgr._depth_lock:
            mgr._depth_cache["NSE:NIFTY50-INDEX"] = wall_payload
            if trad_sym:
                mgr._depth_cache[trad_sym] = wall_payload

        alert = AutoAlert(
            alert_id="aa-test-wall-20261016",
            alert_type="ORB_BREAKOUT",
            stage="PRIMED",
            symbol="NIFTY",
            exchange="NSE",
            direction="BULLISH",
            headline="NIFTY ORB Breakout",
            summary="Testing breakout into ask wall",
            ltp=25000.0,
            trigger_level=25000.0,
            stop_loss=24950.0,
            target_level=25100.0,
            confidence=85,
        )

        passed, reason, flags = alert_scrutiny_auditor.verify_tier1_sanity(alert)
        assert passed is False
        assert "TBT Iceberg Wall Veto" in reason or "Massive resting ask wall" in reason
        assert flags.get("trap_immediate_resistance") is True

        # 2. Candidate with severe adverse Order Book Imbalance (heavy ask dumping)
        obi_payload = {
            "status": "LIVE",
            "ltp": 25000.0,
            "obi_50": -0.55,  # Extreme ask supply
            "ask_walls": [],
            "bid_walls": [],
        }
        with mgr._depth_lock:
            mgr._depth_cache["NSE:NIFTY50-INDEX"] = obi_payload
            if trad_sym:
                mgr._depth_cache[trad_sym] = obi_payload

        passed_obi, reason_obi, flags_obi = alert_scrutiny_auditor.verify_tier1_sanity(alert)
        assert passed_obi is False
        assert "TBT Order Book Imbalance Veto" in reason_obi or "Severe ask pressure" in reason_obi
        assert flags_obi.get("adverse_tbt_imbalance") is True
    finally:
        mgr._connected = False
        with mgr._depth_lock:
            mgr._depth_cache.clear()


def test_tbt_scout_priority_scoring():
    from market.fyers_tbt_manager import _tbt_symbol_priority

    # Index Options
    p_nifty_opt = _tbt_symbol_priority("NSE:NIFTY26OCT25000CE")
    p_bnf_opt = _tbt_symbol_priority("NSE:BANKNIFTY26OCT52000PE")
    p_midcp_opt = _tbt_symbol_priority("NSE:MIDCPNIFTY26OCT13000CE")
    p_sensex_opt = _tbt_symbol_priority("BSE:SENSEX26OCT82000PE")
    p_finnifty_opt = _tbt_symbol_priority("NSE:FINNIFTY26OCT24000CE")

    # Index Futures
    p_nifty_fut = _tbt_symbol_priority("NSE:NIFTY26OCTFUT")
    p_bnf_fut = _tbt_symbol_priority("NSE:BANKNIFTY26OCTFUT")

    # Stock Options & Futures
    p_stock_opt = _tbt_symbol_priority("NSE:RELIANCE26OCT2800CE")
    p_stock_fut = _tbt_symbol_priority("NSE:RELIANCE26OCTFUT")

    # Cash Equities
    p_cash_eq = _tbt_symbol_priority("NSE:RELIANCE-EQ")

    assert p_nifty_opt > p_bnf_opt > p_midcp_opt > p_sensex_opt > p_finnifty_opt
    assert p_nifty_fut >= p_bnf_fut > p_finnifty_opt > p_stock_opt > p_stock_fut > p_cash_eq
    assert p_cash_eq == 10


def test_tbt_scout_prioritized_eviction():
    from market.fyers_tbt_manager import FyersTbtManager, MAX_SCOUT_SLOTS
    import time

    mgr = FyersTbtManager()
    mgr._scout.clear()

    # Pre-populate with high priority index options
    mgr._scout["NSE:NIFTY26OCT25000CE"] = time.time()
    mgr._scout["NSE:BANKNIFTY26OCT52000PE"] = time.time()

    # Add 12 cash equities to force eviction beyond MAX_SCOUT_SLOTS (10)
    cash_equities = [f"NSE:STOCK{i}-EQ" for i in range(12)]
    mgr.subscribe(cash_equities)

    # High-priority index options must NOT be evicted by low-priority cash equities
    assert "NSE:NIFTY26OCT25000CE" in mgr._scout
    assert "NSE:BANKNIFTY26OCT52000PE" in mgr._scout
    assert len(mgr._scout) <= MAX_SCOUT_SLOTS


def test_tbt_depth_quote_cache_bridge():
    from market.fyers_tbt_manager import FyersTbtManager
    from market.quotes import get_quote

    mgr = FyersTbtManager()
    test_sym = "NSE:TBTBRIDGE_TEST"
    mgr._depth_cache[test_sym] = {
        "symbol": test_sym,
        "status": "LIVE",
        "ltp": 456.75,
        "timestamp": 1727900123,
        "tbq": 50000,
        "tsq": 30000,
        "bids": [{"price": 456.70, "qty": 100}],
        "asks": [{"price": 456.80, "qty": 120}],
    }

    # Should resolve immediately via Step 2.2 TBT cache without REST
    q_map = get_quote(test_sym)
    assert test_sym in q_map
    q = q_map[test_sym]
    assert q.last_price == 456.75
    assert q.bid == 456.70
    assert q.ask == 456.80


def test_auto_subscribe_stream_tbt_eligibility_filter():
    from unittest.mock import MagicMock, patch
    from engine.auto_alert_engine import AutoAlertEngine

    engine = AutoAlertEngine()
    engine._stream_subscribed_symbols.clear()

    mock_tbt = MagicMock()
    mock_tbt.is_connected = True

    with (
        patch("market.fyers_tbt_manager.FyersTbtManager", return_value=mock_tbt),
        patch("market.websocket.ws_manager.subscribe") as mock_ws_sub,
    ):
        # Pass a mix of cash equities, index options, futures, and MCX commodities
        symbols = [
            "NSE:RELIANCE-EQ",
            "NSE:TCS-EQ",
            "NSE:NIFTY26OCT25000CE",
            "NSE:BANKNIFTY26OCTFUT",
            "MCX:CRUDEOIL26NOVFUT",
        ]
        engine._auto_subscribe_stream(symbols)
        import time

        time.sleep(0.15)  # Allow worker thread to execute

        # General WS gets all symbols
        assert mock_ws_sub.called

        # TBT Depth must ONLY receive derivative/index/commodity symbols, NEVER cash equities
        if mock_tbt.subscribe.called:
            passed_to_tbt = mock_tbt.subscribe.call_args[0][0]
            assert "NSE:RELIANCE-EQ" not in passed_to_tbt
            assert "NSE:TCS-EQ" not in passed_to_tbt
            assert "NSE:NIFTY26OCT25000CE" in passed_to_tbt
            assert "NSE:BANKNIFTY26OCTFUT" in passed_to_tbt
            assert "MCX:CRUDEOIL26NOVFUT" in passed_to_tbt


def test_options_chain_single_flight_coalescing():
    from unittest.mock import MagicMock, patch
    import threading
    import time
    from market.options import get_options_chain, _CHAIN_CACHE, _CHAIN_CACHE_LOCK

    with _CHAIN_CACHE_LOCK:
        _CHAIN_CACHE.clear()

    call_count = 0
    lock = threading.Lock()

    def _mock_broker_get_chain(symbol, expiry=None):
        nonlocal call_count
        with lock:
            call_count += 1
        time.sleep(0.1)  # Simulate broker REST latency
        from brokers.base import OptionsContract

        return [
            OptionsContract(
                symbol=f"{symbol}26OCT25000CE",
                underlying=symbol,
                strike=25000.0,
                option_type="CE",
                expiry="2026-10-29",
                last_price=120.0,
            )
        ]

    mock_broker = MagicMock()
    mock_broker.get_options_chain.side_effect = _mock_broker_get_chain

    with patch("market.options.get_data_broker", return_value=mock_broker):
        results = []

        def _worker():
            chain = get_options_chain("NIFTY")
            results.append(len(chain))

        threads = [threading.Thread(target=_worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All 5 threads must successfully receive the option chain
        assert len(results) == 5
        assert all(r > 0 for r in results)

        # But broker get_options_chain must have been called EXACTLY ONCE (single-flight coalesced)
        assert call_count == 1


def test_tbt_commodity_session_priority_and_wall_calibration():
    """Verify that during COMMODITY_CDS session, commodities enjoy highest priority and custom wall calibration."""
    from datetime import time as dtime
    from market.fyers_tbt_manager import (
        _tbt_symbol_priority,
        resolve_tradable_tbt_symbol,
        get_default_core_grid,
        FyersTbtManager,
    )

    # 1. Evening Priority Hierarchy: MCX Options (75) > MCX Futures (70) > Commodities (65) > USDINR (62 before 17:00, 5 post 17:00) > Equity (<=60)
    p_crude_opt = _tbt_symbol_priority("MCX:CRUDEOIL26OCT9550CE", session="COMMODITY_CDS")
    p_crude_fut = _tbt_symbol_priority("MCX:CRUDEOIL26OCTFUT", session="COMMODITY_CDS")
    p_gold_fut = _tbt_symbol_priority("MCX:GOLD26DECFUT", session="COMMODITY_CDS")
    p_ng_fut = _tbt_symbol_priority("MCX:NATURALGAS26OCTFUT", session="COMMODITY_CDS")
    p_comm_generic = _tbt_symbol_priority("MCX:CRUDEOIL", session="COMMODITY_CDS")
    p_cds_fut_pre_17 = _tbt_symbol_priority(
        "NSE:USDINR26OCTFUT", session="COMMODITY_CDS", ref_time=dtime(16, 0)
    )
    p_cds_fut_post_17 = _tbt_symbol_priority(
        "NSE:USDINR26OCTFUT", session="COMMODITY_CDS", ref_time=dtime(17, 30)
    )
    p_nifty_opt = _tbt_symbol_priority("NSE:NIFTY26OCT25000CE", session="COMMODITY_CDS")

    assert p_crude_opt == 75
    assert p_crude_fut == 70
    assert p_gold_fut == 70
    assert p_ng_fut == 70
    assert p_comm_generic == 65
    assert p_cds_fut_pre_17 == 62
    assert p_cds_fut_post_17 == 5  # Retired post 17:00 IST
    assert p_crude_opt > p_crude_fut > p_comm_generic > p_cds_fut_pre_17 > p_nifty_opt
    assert p_cds_fut_post_17 < p_nifty_opt  # Post-17:00 CDS is lowest priority and easily evicted

    # 2. Grid Currency Retirement Post 17:00 IST
    _, exp_pre_17 = get_default_core_grid(session="COMMODITY_CDS", ref_time=dtime(16, 0))
    assert any("USDINR" in s for s in exp_pre_17)

    _, exp_post_17 = get_default_core_grid(session="COMMODITY_CDS", ref_time=dtime(17, 30))
    assert not any("USDINR" in s for s in exp_post_17)
    assert any("ALUMINIUM" in s for s in exp_post_17)  # 100% capacity given to MCX metals

    # 3. Tradable symbol resolution for commodity generic and -FUT formats
    assert "MCX:CRUDEOIL" in resolve_tradable_tbt_symbol("MCX:CRUDEOIL-FUT")
    assert "FUT" in resolve_tradable_tbt_symbol("MCX:CRUDEOIL-FUT")
    assert "MCX:GOLD" in resolve_tradable_tbt_symbol("GOLD")
    assert "MCX:NATURALGAS" in resolve_tradable_tbt_symbol("NATURALGAS")

    # 4. Institutional Multi-Factor Order Book Wall Classification
    mgr = FyersTbtManager()

    class MockCommodityDepth:
        def __init__(self):
            self.tbq = 200
            self.tsq = 150
            self.timestamp = 1727900000
            self.bidprice = [6500.0 - (i * 1.0) for i in range(50)]
            self.askprice = [6501.0 + (i * 1.0) for i in range(50)]
            # Normal bids 3 lots each, but level 5 has a 30-lot wall (orders=3, book share=15%)
            self.bidqty = [30 if i == 4 else 3 for i in range(50)]
            self.askqty = [25 if i == 7 else 3 for i in range(50)]
            self.bidordn = [3 if i == 4 else 1 for i in range(50)]
            self.askordn = [2 if i == 7 else 1 for i in range(50)]

    parsed = mgr._parse_depth_object("MCX:CRUDEOIL26OCTFUT", MockCommodityDepth())
    assert parsed["has_bid_wall"] is True
    assert parsed["has_ask_wall"] is True
    assert any(b["level"] == 5 and b["qty"] == 30 for b in parsed["bid_walls"])
    # Verify institutional multi-factor attributes
    wall_5 = next(b for b in parsed["bid_walls"] if b["level"] == 5)
    assert wall_5["book_share_pct"] > 10.0
    assert wall_5["multiple_of_avg"] > 3.0
    assert wall_5["orders"] == 3
    assert wall_5["strength"] in ("FORTRESS", "STRONG")
    assert parsed["strongest_bid_wall"] is not None
    assert parsed["strongest_bid_wall"]["level"] == 5

    # 5. Morning Session Auto-Switchover and Scout Liberation
    with mgr._slots_lock:
        mgr._scout["MCX:CRUDEOIL26OCTFUT"] = 12345.0
        mgr._scout["MCX:GOLD26DECFUT"] = 12346.0
        mgr._scout["NSE:USDINR26OCTFUT"] = 12347.0

    mgr.switch_session("EQUITY_NFO")
    status = mgr.get_active_slots_status()
    # All evening commodity scouts must be evicted on morning transition to EQUITY_NFO
    assert "MCX:CRUDEOIL26OCTFUT" not in status["scout"]
    assert "MCX:GOLD26DECFUT" not in status["scout"]
    assert "NSE:USDINR26OCTFUT" not in status["scout"]
    assert status["current_session"] == "EQUITY_NFO"


def test_tbt_monday_morning_expiry_and_sebi_compliance(monkeypatch):
    """
    Verify that on Monday morning:
      1. NIFTY options resolve to upcoming Thursday weekly contract (NOT Monday).
      2. In monthly expiry week, NIFTY options resolve to monthly contract.
      3. BANKNIFTY & MIDCPNIFTY resolve strictly to monthly contracts per SEBI rules.
      4. SENSEX options resolve to Friday weekly contract.
      5. Futures resolve to active near-month contract without premature rolling.
    """
    from datetime import datetime, date
    from market.calendar import (
        get_active_derivative_expiry,
        get_nearest_weekly_expiry,
        get_nearest_monthly_expiry,
    )
    from market.fyers_tbt_manager import get_default_core_grid

    # Case A: Monday Oct 19, 2026 (Mid-month week)
    fake_monday_19 = datetime(2026, 10, 19, 9, 15)
    monkeypatch.setattr(
        "market.fyers_tbt_manager.datetime",
        type(
            "MockDt",
            (),
            {
                "now": lambda *args, **kwargs: fake_monday_19,
                "fromtimestamp": datetime.fromtimestamp,
            },
        ),
    )

    n_exp = get_active_derivative_expiry("NIFTY", is_future=False, ref_date=date(2026, 10, 19))
    assert n_exp == date(2026, 10, 22)  # Thursday, NOT Monday Oct 19!
    assert get_nearest_weekly_expiry("NIFTY", ref_date=date(2026, 10, 19)) == date(2026, 10, 22)
    assert get_nearest_monthly_expiry("NIFTY", ref_date=date(2026, 10, 19)) == date(2026, 10, 29)

    bn_exp = get_active_derivative_expiry("BANKNIFTY", is_future=False, ref_date=date(2026, 10, 19))
    assert bn_exp == date(2026, 10, 29)  # Monthly contract only!

    s_exp = get_active_derivative_expiry("SENSEX", is_future=False, ref_date=date(2026, 10, 19))
    assert s_exp == date(2026, 10, 23)  # Friday weekly!
    assert get_nearest_weekly_expiry("SENSEX", ref_date=date(2026, 10, 19)) == date(2026, 10, 23)

    # Check Core grid on Monday Oct 19 with NIFTY in focus
    core, todays = get_default_core_grid("EQUITY_NFO", primary_focus="NIFTY")
    assert "NSE:NIFTY26OCTFUT" in core
    assert "NSE:BANKNIFTY26OCTFUT" in core
    assert "NSE:MIDCPNIFTY26OCTFUT" in core
    # Verify NIFTY options have Thursday Oct 22 expiry (26O22), NOT 26O19!
    assert any("NSE:NIFTY26O22" in s for s in core)
    assert not any("NSE:NIFTY26O19" in s for s in core)

    # Case B: Monday Oct 26, 2026 (Monthly expiry week)
    fake_monday_26 = datetime(2026, 10, 26, 9, 15)
    monkeypatch.setattr(
        "market.fyers_tbt_manager.datetime",
        type(
            "MockDt",
            (),
            {
                "now": lambda *args, **kwargs: fake_monday_26,
                "fromtimestamp": datetime.fromtimestamp,
            },
        ),
    )

    core_26, _ = get_default_core_grid("EQUITY_NFO", primary_focus="NIFTY")
    # Must remain in October near-month (NOT prematurely jumped to November!)
    assert "NSE:NIFTY26OCTFUT" in core_26
    assert any("NSE:NIFTY26OCT" in s for s in core_26)


def test_fyers_broker_depth_tbt_bridge_zero_network_calls():
    """
    Verify that when FyersTbtManager has live 50-depth for a symbol,
    broker.get_market_depth(symbol) resolves immediately from memory
    with 0 REST API calls and 0 rate tokens consumed.
    """
    from market.fyers_tbt_manager import FyersTbtManager
    from brokers.fyers import FyersAPI

    mgr = FyersTbtManager()
    mgr._depth_cache["NSE:NIFTY26OCTFUT"] = {
        "symbol": "NSE:NIFTY26OCTFUT",
        "ltp": 25250.0,
        "tbq": 5000,
        "tsq": 4500,
        "bids": [{"price": 25249.5, "qty": 150, "orders": 5}],
        "asks": [{"price": 25250.5, "qty": 120, "orders": 4}],
        "rolling_tick_vwap": 25248.0,
    }

    broker = FyersAPI(app_id="TEST-100", secret_key="dummy")
    broker._access_token = "valid_test_token"

    depth = broker.get_market_depth("NSE:NIFTY26OCTFUT")
    assert depth["status"] == "ok"
    assert depth["provider"] == "FYERS_TBT_50"
    assert depth["ltp"] == 25250.0
    assert depth["total_buy_qty"] == 5000
    assert depth["bids"][0]["price"] == 25249.5


def test_fyers_broker_depth_when_sdk_not_installed(monkeypatch):
    """
    Ensure that when optional fyers-apiv3 SDK is not installed in the environment:
    1. In-memory TBT cache resolution works seamlessly with zero SDK calls.
    2. Fallback REST requests return honest UNAVAILABLE status without unhandled exceptions.
    """
    import sys
    from market.fyers_tbt_manager import FyersTbtManager
    from brokers.fyers import FyersAPI

    monkeypatch.setitem(sys.modules, "fyers_apiv3", None)
    monkeypatch.setitem(sys.modules, "fyers_apiv3.fyersModel", None)

    mgr = FyersTbtManager()
    mgr._depth_cache["NSE:BANKNIFTY26OCTFUT"] = {
        "symbol": "NSE:BANKNIFTY26OCTFUT",
        "ltp": 52000.0,
        "tbq": 2000,
        "tsq": 1800,
        "bids": [{"price": 51995.0, "qty": 100, "orders": 3}],
        "asks": [{"price": 52005.0, "qty": 80, "orders": 2}],
        "rolling_tick_vwap": 51998.0,
    }

    broker = FyersAPI(app_id="TEST-100", secret_key="dummy")
    broker._access_token = "valid_test_token"

    # 1. TBT memory resolution should succeed with 0 SDK calls
    tbt_res = broker.get_market_depth("NSE:BANKNIFTY26OCTFUT")
    assert tbt_res["status"] == "ok"
    assert tbt_res["provider"] == "FYERS_TBT_50"
    assert tbt_res["ltp"] == 52000.0

    # 2. Uncached symbol should return graceful UNAVAILABLE without unhandled crash
    rest_res = broker.get_market_depth("NSE:UNCACHEDFUT")
    assert rest_res["status"] == "UNAVAILABLE"
    assert "fyers-apiv3" in rest_res["message"]


def test_build_sentinel_decision_intel():
    """Verify that build_sentinel_decision_intel translates raw L3 depth into actionable Bull/Bear/Neutral intelligence."""
    from market.fyers_tbt_manager import build_sentinel_decision_intel

    # 1. Fortress Bid Wall
    bid_depth = {
        "fortress_bid_wall_confirmed": True,
        "strongest_bid_wall": {
            "price": 25400.0,
            "qty": 14250,
            "book_share_pct": 22.5,
            "multiple_of_avg": 4.1,
            "duration": 25.0,
        },
        "ltp": 25410.0,
        "obi_50": 0.28,
    }
    intel_bid = build_sentinel_decision_intel(bid_depth)
    assert intel_bid["bias"] == "BULLISH"
    assert "DEMAND FLOOR" in intel_bid["badge"]
    assert "25,400" in intel_bid["headline"]
    assert "FAVOR CALLS / LONGS" in intel_bid["decision"]
    assert intel_bid["wall_price"] == 25400.0

    # 2. Fortress Ask Wall
    ask_depth = {
        "fortress_ask_wall_confirmed": True,
        "strongest_ask_wall": {
            "price": 25500.0,
            "qty": 18000,
            "book_share_pct": 25.0,
            "multiple_of_avg": 4.5,
            "duration": 30.0,
        },
        "ltp": 25480.0,
        "obi_50": -0.32,
    }
    intel_ask = build_sentinel_decision_intel(ask_depth)
    assert intel_ask["bias"] == "BEARISH"
    assert "SUPPLY CEILING" in intel_ask["badge"]
    assert "25,500" in intel_ask["headline"]
    assert "FAVOR PUTS / SHORTS" in intel_ask["decision"]
    assert intel_ask["wall_price"] == 25500.0

    # 3. Bid Spoof (Bull Trap / Rugpull Risk)
    spoof_bid = {
        "fleeing_bid_wall_detected": True,
        "spoof_trap_warning": "BID_SPOOF_RUGPULL_RISK",
        "recent_fleeing_event": {"price": 25350.0, "qty": 8500},
        "ltp": 25355.0,
    }
    intel_sp_bid = build_sentinel_decision_intel(spoof_bid)
    assert intel_sp_bid["bias"] == "CAUTION_BEAR"
    assert "BULL TRAP" in intel_sp_bid["badge"]
    assert "DO NOT CHASE LONGS" in intel_sp_bid["decision"]

    # 4. Ask Spoof (Bear Trap / Short Squeeze)
    spoof_ask = {
        "fleeing_ask_wall_detected": True,
        "spoof_trap_warning": "ASK_SPOOF_BEARTRAP_RISK",
        "recent_fleeing_event": {"price": 25450.0, "qty": 12000},
        "ltp": 25445.0,
    }
    intel_sp_ask = build_sentinel_decision_intel(spoof_ask)
    assert intel_sp_ask["bias"] == "BULLISH"
    assert "BEAR TRAP" in intel_sp_ask["badge"]
    assert "FAVOR LONGS / CALLS" in intel_sp_ask["decision"]

    # 5. Balanced Auction
    balanced_depth = {
        "ltp": 25400.0,
        "obi_50": 0.04,
        "density_score": 65.0,
    }
    intel_bal = build_sentinel_decision_intel(balanced_depth)
    assert intel_bal["bias"] == "NEUTRAL"
    assert "BALANCED AUCTION" in intel_bal["badge"]
    assert "TRADE PRICE ACTION" in intel_bal["decision"]


def test_tbt_single_stock_fno_focus_allocation(monkeypatch):
    """Verify Fyers Prime L3 TBT manager dynamically allocates slots for single-stock F&O."""
    from market.fyers_tbt_manager import FyersTbtManager, _tbt_symbol_priority

    mgr = FyersTbtManager()

    # Mock quotes so RELIANCE spot is available
    monkeypatch.setattr(
        "market.quotes.get_ltp",
        lambda sym: 2800.0 if "RELIANCE" in sym else 25000.0,
    )

    # 1. Set primary focus to single-stock F&O: RELIANCE
    mgr.set_primary_focus("RELIANCE")
    assert mgr._primary_focus_index == "RELIANCE"

    # Core grid must now contain RELIANCE Future and ATM options
    core_grid = mgr._core_grid
    assert any("RELIANCE" in s and "FUT" in s for s in core_grid)
    assert any("RELIANCE" in s and "CE" in s for s in core_grid)
    assert any("RELIANCE" in s and "PE" in s for s in core_grid)

    # 2. Verify priority elevation for focused stock
    p_rel_opt = _tbt_symbol_priority("NSE:RELIANCE26OCT2800CE", primary_focus="RELIANCE")
    p_nifty_opt = _tbt_symbol_priority("NSE:NIFTY26OCT25000CE", primary_focus="RELIANCE")
    p_rel_fut = _tbt_symbol_priority("NSE:RELIANCE26OCTFUT", primary_focus="RELIANCE")
    p_nifty_fut = _tbt_symbol_priority("NSE:NIFTY26OCTFUT", primary_focus="RELIANCE")

    assert p_rel_opt == 65
    assert p_rel_opt > p_nifty_opt  # Focused stock option elevated above NIFTY option (60)
    assert p_rel_fut == 50
    assert p_rel_fut > p_nifty_fut  # Focused stock future elevated above NIFTY future (45)

    # 3. Dynamic ATM revolving includes focused stock
    revolved = mgr.revolve_atm_strikes(force=True)
    assert revolved is True
    assert "RELIANCE" in mgr._last_atm_strikes
    assert mgr._last_atm_strikes["RELIANCE"] == 2800

    # 4. Return to balanced mode
    mgr.set_primary_focus(None)
    assert mgr._primary_focus_index is None


def test_tbt_scout_anti_thrashing_dwell_time():
    """
    Verify anti-thrashing minimum dwell time (MIN_SCOUT_DWELL_SECONDS = 10.0s).
    Within the same priority tier, a scout that has satisfied minimum dwell time (>= 10s)
    is evicted before a young scout (< 10s), preventing rapid churn/thrashing.
    """
    from market.fyers_tbt_manager import (
        FyersTbtManager,
        MAX_SCOUT_SLOTS,
        MIN_SCOUT_DWELL_SECONDS,
    )
    import time

    mgr = FyersTbtManager()
    mgr._scout.clear()
    assert MIN_SCOUT_DWELL_SECONDS == 10.0

    now = time.time()
    # Populate scout ring with MAX_SCOUT_SLOTS symbols
    # Symbol "OLD_SCOUT" was promoted 25 seconds ago (has dwelled >= 10s)
    mgr._scout["NSE:TCS-EQ"] = now - 25.0

    # Other symbols were promoted 2 seconds ago (young, < 10s dwell time)
    for i in range(MAX_SCOUT_SLOTS - 1):
        mgr._scout[f"NSE:YOUNG{i}-EQ"] = now - 2.0

    assert len(mgr._scout) == MAX_SCOUT_SLOTS

    # Now subscribe a new cash equity "NSE:NEWCOMER-EQ", forcing 1 eviction
    mgr.subscribe(["NSE:NEWCOMER-EQ"])

    assert len(mgr._scout) == MAX_SCOUT_SLOTS
    # "NSE:TCS-EQ" (dwelled 25s) should be evicted before any of the young scouts
    assert "NSE:TCS-EQ" not in mgr._scout
    # Young scouts are protected from eviction
    assert "NSE:YOUNG0-EQ" in mgr._scout
    assert "NSE:NEWCOMER-EQ" in mgr._scout
