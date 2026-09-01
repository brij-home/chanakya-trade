"""
tests/test_preflight_endpoint.py
────────────────────────────────
Integration tests for /api/preflight, /api/mode, and /api/charges/calculate.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from web.api import app


@pytest.fixture
def client():
    return TestClient(app)


def test_api_preflight_endpoint(client):
    res = client.get("/api/preflight")
    assert res.status_code == 200
    data = res.json()
    assert "healthy" in data
    assert "mode" in data
    assert "checks" in data
    assert "masked_env" in data
    assert len(data["checks"]) >= 5


def test_api_mode_endpoint(client):
    """P0-A: /api/mode returns server-authoritative mode with allowed_modes and description."""
    res = client.get("/api/mode")
    assert res.status_code == 200
    data = res.json()
    # P0-A schema: mode, allowed_modes, description
    assert "mode" in data
    assert data["mode"] in ("PAPER", "DEMO", "LIVE")
    assert "allowed_modes" in data
    assert isinstance(data["allowed_modes"], list)
    assert set(data["allowed_modes"]) == {"PAPER", "DEMO", "LIVE"}
    assert "description" in data
    # Default (no CHANAKYA_TRADE_MODE env) must be PAPER for safety
    assert data["mode"] == "PAPER"


def test_api_calculate_charges_delivery(client):
    res = client.post(
        "/api/charges/calculate",
        json={
            "price": 2500.0,
            "quantity": 100,
            "segment": "EQUITY_DELIVERY",
            "side": "BUY",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["notional_turnover"] == 250000.0
    assert data["stt"] == 250.0  # 0.1%
    assert data["stamp_duty"] == 37.5  # 0.015%
    assert data["total_charges"] > 280.0


def test_api_calculate_charges_options(client):
    res = client.post(
        "/api/charges/calculate",
        json={
            "price": 100.0,
            "quantity": 1500,
            "segment": "OPTIONS",
            "side": "SELL",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["notional_turnover"] == 150000.0
    assert data["stt"] == 150.0  # 0.1% on sell premium
    assert data["brokerage"] == 20.0  # Capped at ₹20
