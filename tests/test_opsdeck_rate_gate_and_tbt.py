"""
tests/test_opsdeck_rate_gate_and_tbt.py
───────────────────────────────────────
Unit and integration tests for OpsDeck Fyers REST Rate Metering,
15-Slot L3 TBT Depth Governor, Slot Eviction, Grid Rebalance,
and unified Health-Hub API integration.
"""

import time
import pytest
from fastapi.testclient import TestClient

from market.fyers_rate_gate import get_fyers_rate_gate
from market.fyers_tbt_manager import FyersTbtManager, fyers_tbt_manager
from web.api import app


@pytest.fixture
def client():
    return TestClient(app)


def test_rate_gate_diagnostics_structure():
    """Verify rate gate diagnostics expose all sliding-window telemetry."""
    rg = get_fyers_rate_gate()
    diag = rg.get_diagnostics()

    assert "plan" in diag
    assert "max_per_sec" in diag
    assert "max_per_min" in diag
    assert "max_per_day" in diag
    assert "requests_last_sec" in diag
    assert "requests_last_min" in diag
    assert "utilization_pct" in diag
    assert "daily_requests" in diag
    assert "daily_budget_remaining" in diag
    assert "status" in diag
    assert diag["status"] in ("HEALTHY", "WARNING", "SATURATED", "EXHAUSTED")


def test_tbt_evict_symbol():
    """Verify operator eviction removes symbol from slots, unregisters it, and applies cooldown."""
    mgr = FyersTbtManager()
    sym = "NSE:NIFTY26OCT23200CE"

    # Subscribe symbol via scout
    mgr.subscribe([sym])
    status_before = mgr.get_active_slots_status()
    assert sym in status_before["subscribed"] or sym in status_before["scout"]

    # Evict symbol with 300s cooldown
    res = mgr.evict_symbol(sym, cooldown_sec=300.0)
    assert res["status"] == "ok"
    assert res["evicted_symbol"] == sym
    assert res["cooldown_seconds"] == 300.0

    # Verify symbol is no longer in active slots
    status_after = mgr.get_active_slots_status()
    assert sym not in status_after["subscribed"]
    assert sym not in status_after["scout"]
    assert sym in status_after["cooldowns"]
    assert status_after["cooldowns"][sym] > 0


def test_tbt_cooldown_prevents_immediate_resubscription():
    """Verify a symbol with active eviction cooldown is not immediately re-added by compute_desired_subscriptions."""
    mgr = FyersTbtManager()
    sym = "NSE:TESTCOOLDOWN"

    with mgr._slots_lock:
        mgr._core_grid.append(sym)
        mgr._evicted_cooldowns[sym] = time.time() + 100.0

    desired = mgr.compute_desired_subscriptions()
    assert sym not in desired

    # Clean up test symbol
    with mgr._slots_lock:
        if sym in mgr._core_grid:
            mgr._core_grid.remove(sym)
        mgr._evicted_cooldowns.pop(sym, None)


def test_tbt_rebalance_grid_now():
    """Verify operator rebalance cleanses stale scouts, recalculates ATM strikes, and returns valid payload."""
    mgr = FyersTbtManager()
    res = mgr.rebalance_grid_now()

    assert res["status"] == "ok"
    assert "cleansed_scouts_count" in res
    assert "revolved" in res
    assert "active_total" in res
    assert "free_slots" in res
    assert res["free_slots"] == max(0, 15 - res["active_total"])


def test_tbt_get_active_slots_status_enriched():
    """Verify get_active_slots_status returns per-slot metadata table."""
    mgr = FyersTbtManager()
    status = mgr.get_active_slots_status()

    assert "max_slots" in status
    assert status["max_slots"] == 15
    assert "active_total" in status
    assert "free_slots" in status
    assert "slots" in status
    assert isinstance(status["slots"], list)

    for slot in status["slots"]:
        assert "slot_number" in slot
        assert "symbol" in slot
        assert "role" in slot
        assert "duration_seconds" in slot
        assert "is_stale" in slot
        assert "obi_50" in slot


def test_api_fyers_rate_gate_status_endpoint(client):
    """Verify GET /api/fyers/rate-gate-status endpoint."""
    res = client.get("/api/fyers/rate-gate-status")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "data" in data
    assert "requests_last_min" in data["data"]


def test_api_fyers_tbt_status_endpoint(client):
    """Verify GET /api/fyers/tbt-status endpoint."""
    res = client.get("/api/fyers/tbt-status")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "data" in data
    assert "slots" in data["data"]


def test_api_fyers_tbt_evict_endpoint(client):
    """Verify POST /api/fyers/tbt-evict endpoint."""
    sym = "NSE:BANKNIFTY26OCT55000CE"
    fyers_tbt_manager.subscribe([sym])

    res = client.post(
        "/api/fyers/tbt-evict",
        json={"symbol": sym, "cooldown_seconds": 120},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["evicted_symbol"] == sym
    assert data["cooldown_seconds"] == 120.0


def test_api_fyers_tbt_rebalance_endpoint(client):
    """Verify POST /api/fyers/tbt-rebalance endpoint."""
    res = client.post("/api/fyers/tbt-rebalance", json={})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "active_total" in data


def test_api_fyers_tbt_focus_endpoint(client):
    """Verify POST /api/fyers/tbt-focus endpoint."""
    res = client.post("/api/fyers/tbt-focus", json={"focus": "BANKNIFTY"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["primary_focus"] == "BANKNIFTY"


def test_api_system_health_hub_includes_rate_gate_and_tbt(client):
    """Verify GET /api/system/health-hub includes both rate_gate and tbt telemetry."""
    res = client.get("/api/system/health-hub")
    assert res.status_code == 200
    data = res.json()

    assert "rate_gate" in data
    assert "tbt" in data
    assert "overall_status" in data
    assert "circuit_breaker" in data
    assert "websocket" in data

    # Verify rate gate fields
    rg = data["rate_gate"]
    assert "requests_last_min" in rg
    assert "max_per_min" in rg
    assert "requests_last_sec" in rg

    # Verify TBT fields
    tbt = data["tbt"]
    assert "max_slots" in tbt
    assert tbt["max_slots"] == 15
    assert "slots" in tbt


def test_tbt_multi_socket_worker_pool_partitioning():
    """Verify that TbtSocketWorker pool partitions 15 desired symbols across 3 workers with 5 per worker."""
    from market.fyers_tbt_manager import FyersTbtManager, TbtSocketWorker

    mgr = FyersTbtManager()
    status = mgr.get_active_slots_status()

    assert "pool_status" in status
    assert "workers_active" in status
    assert "workers_total" in status
    assert status["max_slots"] == 15

    # Mock workers to verify partitioning without live network
    mock_workers = []
    received_depths = []
    for i in range(3):
        w = TbtSocketWorker(
            worker_id=i,
            auth_token_getter=lambda: "MOCK:TOKEN",
            on_depth=lambda s, d: received_depths.append(s),
            on_status=lambda wid, st: None,
        )
        w.connected = True
        mock_workers.append(w)

    mgr._workers = mock_workers

    # Populate 15 desired symbols
    symbols_15 = [f"NSE:MOCKSYM{i}FUT" for i in range(15)]
    mgr._core_grid = symbols_15[:6]
    mgr._todays_expiry = symbols_15[6:9]
    mgr._scout = {s: time.time() for s in symbols_15[9:15]}

    mgr.sync_subscriptions()

    # Verify each worker got exactly 5 symbols
    assert len(mock_workers[0].desired) == 5
    assert len(mock_workers[1].desired) == 5
    assert len(mock_workers[2].desired) == 5

    # Worker 0 gets 0..4, Worker 1 gets 5..9, Worker 2 gets 10..14
    assert mock_workers[0].desired == symbols_15[0:5]
    assert mock_workers[1].desired == symbols_15[5:10]
    assert mock_workers[2].desired == symbols_15[10:15]

    pool_status = mgr.get_active_slots_status()["pool_status"]
    assert len(pool_status) == 3
    assert pool_status[0]["worker_id"] == 0
    assert pool_status[1]["worker_id"] == 1
    assert pool_status[2]["worker_id"] == 2


def test_api_subscriptions_cleanse_and_revolve_endpoints():
    """Verify that /api/market/subscriptions/cleanse and /revolve endpoints return valid JSON responses."""
    from web.api import app

    client = TestClient(app)

    # 1. Test Cleanse Endpoint
    res_cleanse = client.post("/api/market/subscriptions/cleanse")
    assert res_cleanse.status_code == 200
    data_cleanse = res_cleanse.json()
    assert data_cleanse["status"] == "SUCCESS"
    assert "purged_contracts_count" in data_cleanse
    assert "purged_stale_ticks_count" in data_cleanse
    assert "current_total_subscribed" in data_cleanse
    assert "utilization_pct" in data_cleanse

    # 2. Test Revolve Endpoint
    res_revolve = client.post("/api/market/subscriptions/revolve?drift_pct=2.0")
    assert res_revolve.status_code == 200
    data_revolve = res_revolve.json()
    assert data_revolve["status"] == "SUCCESS"
    assert "drift_detected" in data_revolve
    assert "anchored_spots" in data_revolve
    assert "total_subscribed" in data_revolve


def test_radar_and_slot_status_zero_rest_api_calls():
    """Verify that radar scans and TBT slot telemetry resolve in memory with ZERO broker REST calls."""
    from unittest.mock import MagicMock, patch
    from market.fyers_tbt_manager import FyersTbtManager
    from market.universe_depth_radar import get_universe_depth_radar

    mock_broker = MagicMock()
    mock_broker.get_market_depth.side_effect = AssertionError(
        "REST get_market_depth should NOT be called!"
    )
    mock_broker.get_quote.side_effect = AssertionError("REST get_quote should NOT be called!")

    with (
        patch("brokers.session.get_data_broker", return_value=mock_broker),
        patch("brokers.session.get_execution_broker", return_value=mock_broker),
    ):
        # 1. TBT slot telemetry must not invoke broker REST
        tbt = FyersTbtManager()
        slots_status = tbt.get_active_slots_status()
        assert "slots" in slots_status
        assert mock_broker.get_market_depth.call_count == 0

        # 2. Universe depth radar must not invoke broker REST
        radar_rows = get_universe_depth_radar(limit=20)
        assert isinstance(radar_rows, list)
        assert mock_broker.get_market_depth.call_count == 0
