import pytest
from web.skills import skill_dashboard_snapshot, DashboardSnapshotRequest


@pytest.mark.anyio
async def test_dashboard_snapshot_contract():
    req = DashboardSnapshotRequest(symbol="NIFTY", exchange="NSE", timeframe="15m")
    res = await skill_dashboard_snapshot(req)
    assert res is not None
    assert "status" in res and res["status"] == "ok"
    data = res["data"]
    assert data["terminal_contract_version"] == 2
    assert data["symbol"] == "NIFTY"
    assert data["ltp"] > 0
    setup = data["automated_setup"]
    assert setup is not None
    for field in ["entry", "stop_loss", "target_1", "target_2"]:
        assert field in setup
        assert setup[field] is not None
        assert setup[field] > 0


@pytest.mark.anyio
async def test_dashboard_snapshot_resilience_when_no_history(monkeypatch):
    """
    Regression test ensuring that when historical data is unavailable or insufficient,
    vol_pct and atr_val are handled defensively without raising UnboundLocalError or TypeError.
    """
    import market.history
    monkeypatch.setattr(market.history, "get_historical_data", lambda *args, **kwargs: None)

    req = DashboardSnapshotRequest(symbol="RELIANCE", exchange="NSE", timeframe="15m", force_refresh=True)
    res = await skill_dashboard_snapshot(req)
    assert res is not None
    assert "status" in res and res["status"] == "ok"
    data = res["data"]
    assert "personas" in data
    personas = data["personas"]
    assert len(personas) >= 1
    # Check Taleb persona
    taleb = next((p for p in personas if p["id"] == "taleb"), None)
    if taleb:
        assert taleb["verdict"] in ["VOLATILITY PENDING", "POSITIVE CONVEXITY", "HIGH VOLATILITY (SPREADS ONLY)"]
        assert "ATR Vol" in taleb["metrics"]

