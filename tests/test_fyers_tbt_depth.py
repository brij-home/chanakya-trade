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
