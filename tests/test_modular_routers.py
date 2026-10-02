"""
tests/test_modular_routers.py
──────────────────────────────
Verification suite for modular FastAPI routers (alerts_router, market_router)
and async event loop offloading.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from web.api import app


@pytest.fixture
def client():
    return TestClient(app)


def test_market_regime_endpoint(client):
    resp = client.get("/api/market/regime")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "is_edgeless" in data
    assert "prefer_spreads" in data


def test_alerts_auto_endpoint(client):
    resp = client.get("/api/alerts/auto?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert isinstance(data["data"], list)


def test_telegram_destinations_endpoint(client):
    resp = client.get("/api/alerts/auto/telegram-destinations")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert isinstance(data["data"], dict)


def test_ticker_snapshot_endpoint(client):
    resp = client.get("/api/ticker/snapshot")
    assert resp.status_code == 200
    data = resp.json()
    assert "tickers" in data
