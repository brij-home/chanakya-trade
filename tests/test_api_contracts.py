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

    # Critical P0-A, P0-B & P1-A API Endpoints must be present in schema
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
