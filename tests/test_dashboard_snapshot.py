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
