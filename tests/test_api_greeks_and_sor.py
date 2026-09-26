"""
tests/test_api_greeks_and_sor.py
────────────────────────────────
Unit tests for /api/portfolio/greeks and /api/execution/smart-route endpoints.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from web.api import app

client = TestClient(app)


def test_api_smart_route_endpoint():
    """Verify /api/execution/smart-route calculates valid iceberg/passive plan."""
    payload = {
        "symbol": "NIFTY",
        "side": "BUY",
        "quantity": 100,  # 4 lots (lot size 25)
        "ltp": 24500.0,
        "bid_price": 24495.0,
        "ask_price": 24505.0,
        "lot_size": 25,
        "urgency": "NORMAL",
    }

    resp = client.post("/api/execution/smart-route", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "NIFTY"
    assert data["side"] == "BUY"
    assert data["total_lots"] == 4
    assert data["routing_mode"] == "ICEBERG"
    assert len(data["tranches"]) >= 2
    assert data["estimated_spread_savings_inr"] > 0


def test_api_portfolio_greeks_endpoint():
    """Verify /api/portfolio/greeks returns structured Greek surface."""
    resp = client.get("/api/portfolio/greeks?source=paper")
    assert resp.status_code == 200
    data = resp.json()
    assert "net_delta_nifty_eq" in data
    assert "net_gamma" in data
    assert "net_theta_daily_inr" in data
    assert "stress_tests" in data
    assert "gap_down_2_5_pct" in data["stress_tests"]
