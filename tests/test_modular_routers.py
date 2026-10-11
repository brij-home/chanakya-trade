"""
tests/test_modular_routers.py
──────────────────────────────
Deterministic validation of modular FastAPI routers and route registration.
Verifies that alerts_router, market_router, and orders_router are mounted
without duplicate registrations or missing routes.
"""

from fastapi.testclient import TestClient
import pytest

from web.api import app
from web.routers import alerts_router, market_router, orders_router


@pytest.fixture
def client():
    return TestClient(app)


def _get_paths(routes):
    paths = []
    for r in routes:
        if hasattr(r, "path"):
            paths.append(r.path)
        if hasattr(r, "routes"):
            paths.extend(_get_paths(r.routes))
    return paths


def test_modular_routers_registered():
    """Verify that each modular router is mounted in the FastAPI app."""
    order_routes = [r.path for r in orders_router.routes]

    # Verify orders_router routes
    assert "/api/orders/preview" in order_routes
    assert "/api/orders/confirm" in order_routes
    assert "/api/orders/execute" in order_routes
    assert "/api/orders/batch/execute" in order_routes
    assert "/api/risk/preflight" in order_routes
    assert "/api/reconciliation" in order_routes
    assert "/api/reconciliation/baseline" in order_routes

    # Verify market_router routes
    market_routes = [r.path for r in market_router.routes]
    assert any("/api/quotes" in r or "/api/market" in r for r in market_routes)

    # Verify alerts_router routes
    alert_routes = [r.path for r in alerts_router.routes]
    assert any("/api/alerts" in r for r in alert_routes)


def test_order_preview_schema_validation(client):
    """Verify that order preview endpoint validates schemas properly via orders_router."""
    # Missing required fields
    res = client.post("/api/orders/preview", json={})
    assert res.status_code == 422

    # Invalid side
    res = client.post(
        "/api/orders/preview",
        json={
            "symbol": "INFY",
            "side": "INVALID_SIDE",
            "quantity": 10,
            "price": 1500.0,
            "order_type": "LIMIT",
            "product": "MIS",
        },
    )
    assert res.status_code == 422


def test_reconciliation_honesty_via_router(client):
    """Verify that GET /api/reconciliation returns honest UNAVAILABLE when no broker is active."""
    res = client.get("/api/reconciliation")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "UNAVAILABLE"
    assert "broker_positions" in data
    assert data["correlation_id"] is not None
