"""
tests/test_api_contracts.py
────────────────────────────
P0-C API Contract Verification Matrix.
Ensures that all required backend routes, methods, and OpenAPI definitions
match frontend contracts to prevent silent route mismatches.
"""

import pytest
from fastapi.testclient import TestClient
from web.api import app


@pytest.fixture
def client():
    return TestClient(app)


def test_api_openapi_spec_generation(client):
    """Verify OpenAPI JSON schema generates cleanly without schema errors."""
    res = client.get("/openapi.json")
    assert res.status_code == 200
    schema = res.json()
    assert "paths" in schema
    assert "openapi" in schema
    paths = schema["paths"]

    # Critical P0-A, P0-B, P1-A, P1-B & P1-C API Endpoints must be present in schema
    assert "/api/mode" in paths
    assert "/api/preflight" in paths
    assert "/api/orders/preview" in paths
    assert "/api/orders/execute" in paths
    assert "/api/risk/preflight" in paths
    assert "/skills/market_overview" in paths
    assert "/skills/global_macro" in paths
    assert "/skills/tax/estimate" in paths
    assert "/skills/tax/calculate" in paths
    assert "/skills/instruments/resolve" in paths
    assert "/skills/market_session" in paths
    assert "/skills/models/list" in paths
    assert "/skills/models/manifest" in paths
    assert "/skills/reconcile" in paths
    assert "/skills/journal/list" in paths
    assert "/skills/journal/add" in paths
    assert "/skills/journal/stats" in paths
    assert "/skills/security_360" in paths


def test_mode_endpoint_contract(client):
    """Verify /api/mode returns expected schema and fields."""
    res = client.get("/api/mode")
    assert res.status_code == 200
    data = res.json()
    assert "mode" in data
    assert "allowed_modes" in data
    assert "description" in data
    assert data["mode"] in ("PAPER", "DEMO", "LIVE")


def test_market_overview_contract(client):
    """Verify /skills/market_overview returns data envelope with truthful metadata."""
    res = client.get("/skills/market_overview")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    payload = data["data"]
    assert "_status" in payload
    assert "_source_name" in payload
    assert "_as_of" in payload
    assert "vix" in payload
    assert "fii_net" in payload
    assert "dii_net" in payload
    assert "sectors" in payload


def test_tax_calculate_alias_contract(client):
    """Verify /skills/tax/calculate alias properly computes statutory capital gains."""
    res = client.post(
        "/skills/tax/calculate",
        json={
            "gross_pnl": 50000.0,
            "holding_period_days": 90,
            "segment": "EQUITY_DELIVERY",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    payload = data["data"]
    assert payload["tax_type"] == "STCG"
    assert payload["tax_rate_pct"] == 20.0
    assert payload["estimated_tax"] == 10000.0


def test_instruments_resolve_contract(client):
    """Verify /skills/instruments/resolve normalizes symbol queries into CanonicalInstrument."""
    res = client.post("/skills/instruments/resolve", json={"query": "RELIANCE"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    instr = data["data"]
    assert instr["instrument_id"] == "NSE:RELIANCE:EQUITY"
    assert instr["exchange"] == "NSE"
    assert instr["segment"] == "EQUITY"
    assert instr["lot_size"] == 1
    assert instr["tick_size"] == 0.05


def test_market_session_contract(client):
    """Verify /skills/market_session returns live operational session state."""
    res = client.get("/skills/market_session?exchange=NSE")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    session_info = data["data"]
    assert "exchange" in session_info
    assert "session_state" in session_info
    assert session_info["session_state"] in ("PRE_OPEN", "OPEN", "POST_CLOSE", "CLOSED")
    assert "current_time_ist" in session_info
    assert "IST" in session_info["current_time_ist"]


def test_models_list_and_manifest_contract(client):
    """Verify /skills/models/list and /skills/models/manifest return registered model specs."""
    res_list = client.get("/skills/models/list")
    assert res_list.status_code == 200
    data_list = res_list.json()
    assert data_list["status"] == "ok"
    assert data_list["data"]["total_models"] >= 5

    res_manifest = client.get("/skills/models/manifest?model_id=options.black_scholes.v1")
    assert res_manifest.status_code == 200
    data_m = res_manifest.json()
    assert data_m["status"] == "ok"
    manifest = data_m["data"]
    assert manifest["model_id"] == "options.black_scholes.v1"
    assert manifest["version"] == "1.1.0"
    assert len(manifest["assumptions"]) > 0


def test_reconcile_and_journal_endpoints_contract(client):
    """Verify /skills/reconcile, /skills/journal/list, /skills/journal/add, and /skills/journal/stats contracts."""
    res_rec = client.post(
        "/skills/reconcile",
        json={
            "internal_positions": [{"symbol": "TCS", "qty": 10, "avg_price": 4000.0}],
            "broker_positions": [{"symbol": "TCS", "qty": 10, "avg_price": 4000.0}],
            "internal_cash": 100000.0,
            "broker_cash": 100000.0,
        },
    )
    assert res_rec.status_code == 200
    assert res_rec.json()["status"] == "ok"
    rec_data = res_rec.json()["data"]
    assert rec_data["status"] == "COMPLETE"
    assert rec_data["is_reconciled"] is True
    assert rec_data["allow_trading"] is True

    # Test Journal Add & List & Stats
    res_add = client.post(
        "/skills/journal/add",
        json={
            "symbol": "BAJFINANCE",
            "direction": "BUY",
            "entry_price": 7200.0,
            "qty": 5,
            "stop_loss": 7000.0,
            "target": 7600.0,
            "thesis": "Earnings acceleration",
        },
    )
    assert res_add.status_code == 200
    assert res_add.json()["status"] == "ok"
    assert res_add.json()["data"]["symbol"] == "BAJFINANCE"

    res_stats = client.get("/skills/journal/stats")
    assert res_stats.status_code == 200
    assert res_stats.json()["status"] == "ok"
    assert "win_rate_pct" in res_stats.json()["data"]


def test_security_360_endpoint_contract(client):
    """Verify /skills/security_360 returns comprehensive multi-lens intelligence dossier."""
    res = client.post("/skills/security_360", json={"symbol": "INFY", "current_price": 1850.0})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    dossier = data["data"]
    assert dossier["symbol"] == "INFY"
    assert dossier["canonical_symbol"] == "NSE:INFY:EQUITY"
    assert len(dossier["methodology_lenses"]) >= 4
    assert dossier["decision"]["action_eligibility"] == "ELIGIBLE"
    assert dossier["_status"] == "READY"
    assert "_as_of" in dossier


def test_strategy_manifest_endpoint_contract(client):
    """Verify /skills/strategy_manifest creates an immutable sealed run manifest."""
    res = client.post(
        "/skills/strategy_manifest",
        json={
            "strategy_id": "rsi_reversal_v1",
            "strategy_name": "RSI Reversal",
            "strategy_version": "1.0.0",
            "universe": ["RELIANCE", "TCS"],
            "data_snapshot_start": "2022-01-01",
            "data_snapshot_end": "2024-01-01",
            "benchmark": "NIFTY50",
            "parameters": {"rsi_buy": 30, "rsi_sell": 70},
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    manifest = data["data"]
    assert manifest["strategy_id"] == "rsi_reversal_v1"
    assert len(manifest["manifest_hash"]) == 64  # SHA-256 hex
    assert len(manifest["run_id"]) == 36          # UUID4
    assert manifest["bias_prevention"]["look_ahead_guard_active"] is True
    assert manifest["bias_prevention"]["survivorship_bias_guard_active"] is True
    # Reproducibility: same inputs must produce same manifest_hash
    res2 = client.post(
        "/skills/strategy_manifest",
        json={
            "strategy_id": "rsi_reversal_v1",
            "strategy_name": "RSI Reversal",
            "strategy_version": "1.0.0",
            "universe": ["RELIANCE", "TCS"],
            "data_snapshot_start": "2022-01-01",
            "data_snapshot_end": "2024-01-01",
            "benchmark": "NIFTY50",
            "parameters": {"rsi_buy": 30, "rsi_sell": 70},
        },
    )
    assert res2.json()["data"]["manifest_hash"] == manifest["manifest_hash"]


def test_options_chain_integrity_eligible_chain(client):
    """Verify /skills/options_chain_integrity approves a valid, fresh chain."""
    # Build a synthetic 25-strike clean chain
    chain_rows = []
    for i in range(-12, 13):
        strike = 22000 + i * 50
        for opt_type in ("CE", "PE"):
            chain_rows.append({
                "strike": strike,
                "option_type": opt_type,
                "bid": max(1.0, 100.0 + i * 5),
                "ask": max(2.0, 102.0 + i * 5),
                "iv_pct": 15.5 + abs(i) * 0.3,
                "oi": 50000,
                "volume": 5000,
            })

    res = client.post(
        "/skills/options_chain_integrity",
        json={
            "symbol": "NIFTY",
            "expiry": "2027-09-25",
            "underlying_price": 22000.0,
            "chain_rows": chain_rows,
            "chain_timestamp_utc": None,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    report = data["data"]
    assert report["is_actionable"] is True
    assert report["action_eligibility"] == "ELIGIBLE"
    assert report["quality_score"] >= 70.0
    assert report["atm_strike"] == 22000.0


def test_options_chain_integrity_stale_chain_blocked(client):
    """Verify /skills/options_chain_integrity blocks stale chain."""
    chain_rows = []
    for i in range(-12, 13):
        strike = 22000 + i * 50
        chain_rows.append({
            "strike": strike, "option_type": "CE",
            "bid": 100.0, "ask": 102.0, "iv_pct": 15.0, "oi": 50000, "volume": 5000,
        })

    res = client.post(
        "/skills/options_chain_integrity",
        json={
            "symbol": "NIFTY",
            "expiry": "2027-09-25",
            "underlying_price": 22000.0,
            "chain_rows": chain_rows,
            "chain_timestamp_utc": "2020-01-01T00:00:00Z",  # artificially stale
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    report = data["data"]
    assert report["is_actionable"] is False
    assert report["action_eligibility"] in ("UNAVAILABLE", "RESTRICTED")

