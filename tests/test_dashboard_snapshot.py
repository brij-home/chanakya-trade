import pytest
from web.skills import skill_dashboard_snapshot, DashboardSnapshotRequest


@pytest.mark.anyio
async def test_dashboard_snapshot_contract(monkeypatch):
    import numpy as np
    import pandas as pd
    from brokers.base import Quote

    dates = pd.date_range("2026-10-01", periods=30, freq="15min")
    df = pd.DataFrame(
        {
            "open": np.linspace(24800, 25000, 30),
            "high": np.linspace(24850, 25050, 30),
            "low": np.linspace(24750, 24950, 30),
            "close": np.linspace(24820, 25020, 30),
            "volume": [100000] * 30,
        },
        index=dates,
    )
    q = Quote(symbol="NIFTY", last_price=25020.0, change=120.0, change_pct=0.48, volume=500000)
    monkeypatch.setattr("market.quotes.get_ltp", lambda *a, **kw: 25020.0)
    monkeypatch.setattr(
        "market.quotes.get_quote",
        lambda *a, **kw: {"NSE:NIFTY 50": q, "NIFTY": q, "NSE:NIFTY": q},
    )
    monkeypatch.setattr("market.history.get_historical_data", lambda *a, **kw: df)

    req = DashboardSnapshotRequest(
        symbol="NIFTY", exchange="NSE", timeframe="15m", force_refresh=True
    )
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
    from brokers.base import Quote

    q = Quote(symbol="RELIANCE", last_price=2850.0, change=15.0, change_pct=0.5, volume=100000)
    monkeypatch.setattr("market.quotes.get_ltp", lambda *a, **kw: 2850.0)
    monkeypatch.setattr(
        "market.quotes.get_quote",
        lambda *a, **kw: {"NSE:RELIANCE": q, "RELIANCE": q},
    )
    monkeypatch.setattr(market.history, "get_historical_data", lambda *args, **kwargs: None)
    monkeypatch.setattr("analysis.fundamental.analyse", lambda *a, **kw: None)
    monkeypatch.setattr("analysis.forensic.audit_forensics", lambda *a, **kw: None)
    monkeypatch.setattr("analysis.multibagger.scan_multibagger_opportunity", lambda *a, **kw: None)

    req = DashboardSnapshotRequest(
        symbol="RELIANCE", exchange="NSE", timeframe="15m", force_refresh=True
    )
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
        assert taleb["verdict"] in [
            "VOLATILITY PENDING",
            "POSITIVE CONVEXITY",
            "HIGH VOLATILITY (SPREADS ONLY)",
        ]
        assert "ATR Vol" in taleb["metrics"]
