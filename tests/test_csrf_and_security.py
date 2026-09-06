"""
tests/test_csrf_and_security.py
───────────────────────────────
Security and Auth integration tests:
  - CSRF protection in self-hosted deployment mode (valid, missing, invalid tokens)
  - Cryptographic strength check for CSRF_SECRET on startup
  - Protection of /api/reconciliation and audit logs from public unauthenticated access
  - Real /api/reconciliation endpoint contract with typed broker data
"""

import hmac
import hashlib
import pytest
from dataclasses import dataclass
from fastapi.testclient import TestClient
from web.api import app, get_csrf_secret
from web.auth import init_db, create_user, create_session


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_file = tmp_path / "auth_test.db"
    monkeypatch.setenv("AUTH_DB_PATH", str(db_file))
    init_db()
    return TestClient(app, raise_server_exceptions=False)


def test_csrf_secret_enforcement_in_self_hosted_mode(monkeypatch):
    """DEPLOY_MODE=self-hosted must raise RuntimeError if CSRF_SECRET is missing or weak (<32 chars)."""
    monkeypatch.setenv("DEPLOY_MODE", "self-hosted")

    # Missing secret
    monkeypatch.delenv("CSRF_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="cryptographically strong CSRF_SECRET"):
        get_csrf_secret()

    # Too short secret
    monkeypatch.setenv("CSRF_SECRET", "short-secret-key-1234")
    with pytest.raises(RuntimeError, match="cryptographically strong CSRF_SECRET"):
        get_csrf_secret()

    # Insecure default
    monkeypatch.setenv("CSRF_SECRET", "chanakya-csrf-secret-change-in-production")
    with pytest.raises(RuntimeError, match="cryptographically strong CSRF_SECRET"):
        get_csrf_secret()

    # Valid strong secret
    strong_secret = "a" * 64
    monkeypatch.setenv("CSRF_SECRET", strong_secret)
    assert get_csrf_secret() == strong_secret


def test_csrf_protection_in_self_hosted_mode(monkeypatch, client):
    """
    In self-hosted mode:
      - GET /api/csrf-token issues a valid HMAC token for the active session.
      - Mutating requests (POST, PUT, DELETE) with valid X-CSRF-Token proceed.
      - Mutating requests without X-CSRF-Token return 403.
      - Mutating requests with tampered/invalid X-CSRF-Token return 403.
    """
    strong_secret = "super-secret-key-for-testing-purposes-only-64chars-long-value-here"
    monkeypatch.setenv("DEPLOY_MODE", "self-hosted")
    monkeypatch.setenv("CSRF_SECRET", strong_secret)

    # 1. Create a user and active session
    create_user("admin@test.com", "password123")
    session_id = create_session(user_id=1, email="admin@test.com")
    client.cookies.set("session_id", session_id)

    # 2. Fetch CSRF token
    res = client.get("/api/csrf-token")
    assert res.status_code == 200
    token = res.json()["csrf_token"]
    assert token is not None

    # Expected HMAC
    expected_token = hmac.new(
        strong_secret.encode(), session_id.encode(), hashlib.sha256
    ).hexdigest()
    assert token == expected_token

    # 3. Post with valid token -> passes CSRF check
    res_valid = client.post(
        "/api/orders/preview",
        json={"symbol": "INFY", "side": "BUY", "quantity": 10, "price": 1800.0},
        headers={"X-CSRF-Token": token},
    )
    assert res_valid.status_code == 200

    # 4. Post with missing token -> 403
    res_missing = client.post(
        "/api/orders/preview",
        json={"symbol": "INFY", "side": "BUY", "quantity": 10, "price": 1800.0},
        headers={},
    )
    assert res_missing.status_code == 403
    assert "CSRF" in res_missing.json().get("detail", "")

    # 5. Post with invalid / tampered token -> 403
    res_invalid = client.post(
        "/api/orders/preview",
        json={"symbol": "INFY", "side": "BUY", "quantity": 10, "price": 1800.0},
        headers={"X-CSRF-Token": "tampered-bad-token-value"},
    )
    assert res_invalid.status_code == 403


def test_reconciliation_and_audit_routes_require_auth_in_self_hosted(monkeypatch, client):
    """
    Follow-up Invariant: /api/reconciliation, /api/audit/logs, /api/audit/verify
    must not be publicly exposed without authentication in self-hosted deployments.
    """
    strong_secret = "super-secret-key-for-testing-purposes-only-64chars-long-value-here"
    monkeypatch.setenv("DEPLOY_MODE", "self-hosted")
    monkeypatch.setenv("CSRF_SECRET", strong_secret)

    # Ensure user exists so self-hosted mode enforces auth
    create_user("owner@test.com", "password123")

    # Unauthenticated call to /api/reconciliation -> 401
    client.cookies.clear()
    res_rec = client.get("/api/reconciliation")
    assert res_rec.status_code == 401, f"Expected 401, got {res_rec.status_code}"

    # Unauthenticated call to /api/audit/logs -> 401
    res_audit = client.get("/api/audit/logs")
    assert res_audit.status_code == 401, f"Expected 401, got {res_audit.status_code}"


def test_self_hosted_setup_fails_closed_until_initial_account_exists(monkeypatch, client):
    monkeypatch.setenv("DEPLOY_MODE", "self-hosted")
    monkeypatch.setenv("CSRF_SECRET", "s" * 64)

    res = client.get("/api/reconciliation")
    assert res.status_code == 503
    assert "setup" in res.json()["detail"].lower()


@pytest.mark.parametrize(
    "payload",
    [
        {"symbol": "INFY", "side": "HOLD", "quantity": 1, "price": 1800},
        {"symbol": "INFY", "side": "BUY", "quantity": 0, "price": 1800},
        {"symbol": "INFY", "side": "SELL", "quantity": 1, "price": 0},
        {"symbol": "INFY", "side": "BUY", "quantity": 1, "price": 1800, "order_type": "GUESS"},
    ],
)
def test_malformed_order_preview_is_rejected_not_coerced(client, payload):
    res = client.post("/api/orders/preview", json=payload)
    assert res.status_code == 422


def test_real_reconciliation_endpoint_with_typed_broker(monkeypatch, client):
    """
    Follow-up Invariant: Real /api/reconciliation endpoint execution with
    typed dataclass positions and funds from broker adapter.
    """

    @dataclass
    class MockPosition:
        symbol: str
        quantity: int
        average_price: float
        pnl: float = 0.0
        product: str = "MIS"

    @dataclass
    class MockFunds:
        available_cash: float
        used_margin: float = 0.0
        total_collateral: float = 0.0

    class MockLiveBroker:
        account_id = "ACC-TEST-999"

        def get_positions(self):
            return [
                MockPosition(symbol="INFY", quantity=100, average_price=1850.0, pnl=2500.0),
                MockPosition(symbol="TCS", quantity=50, average_price=3500.0, pnl=1200.0),
            ]

        def get_funds(self):
            return MockFunds(available_cash=500000.0)

    monkeypatch.setattr("brokers.session.get_execution_broker", lambda: MockLiveBroker())

    # Call endpoint directly in local desktop mode (auth bypassed for localhost)
    monkeypatch.delenv("DEPLOY_MODE", raising=False)
    res = client.get("/api/reconciliation")
    assert res.status_code == 200

    data = res.json()
    assert "status" in data
    # A broker snapshot alone is intentionally insufficient: the pilot must
    # establish its independent local opening balance before reconciliation.
    assert data["status"] == "UNAVAILABLE"
    assert "baseline" in data["reason"].lower()
    assert data["broker_account_id"] == "ACC-TEST-999"
    assert data["correlation_id"] is not None
    assert data["broker_positions"] is not None


def test_orders_confirm_endpoint_integration(tmp_path, monkeypatch, client):
    """
    POST /api/orders/confirm transitions PREVIEW to CONFIRMED.
    Returns HTTP 409 on state/hash mismatch, HTTP 403 on mode violation.
    """
    orders_db = tmp_path / "orders.db"
    monkeypatch.setattr("engine.order_lifecycle._get_db_path", lambda: orders_db)
    monkeypatch.delenv("DEPLOY_MODE", raising=False)
    monkeypatch.setenv("TRADING_MODE", "SIMULATE")

    # 1. Create order preview
    res_prev = client.post(
        "/api/orders/preview",
        json={"symbol": "RELIANCE", "side": "BUY", "quantity": 10, "price": 2850.0},
    )
    assert res_prev.status_code == 200
    prev_data = res_prev.json()
    order_id = prev_data["order_id"]
    preview_hash = prev_data["preview_hash"]

    # 2. Confirm with bad hash -> 409
    res_bad_hash = client.post(
        "/api/orders/confirm",
        json={"order_id": order_id, "preview_hash": "wrong-hash-1234"},
    )
    assert res_bad_hash.status_code == 409

    # 3. Confirm with valid hash -> 200 & CONFIRMED status
    res_confirm = client.post(
        "/api/orders/confirm",
        json={"order_id": order_id, "preview_hash": preview_hash},
    )
    assert res_confirm.status_code == 200
    assert res_confirm.json()["status"] == "CONFIRMED"


def test_orders_execute_endpoint_error_codes(tmp_path, monkeypatch, client):
    """
    POST /api/orders/execute returns 409 for unconfirmed live orders and 403 for mode mismatches.
    """
    orders_db = tmp_path / "orders.db"
    monkeypatch.setattr("engine.order_lifecycle._get_db_path", lambda: orders_db)
    monkeypatch.delenv("DEPLOY_MODE", raising=False)
    monkeypatch.setenv("TRADING_MODE", "EXECUTE")
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "1")

    # 1. Preview order under EXECUTE mode
    res_prev = client.post(
        "/api/orders/preview",
        json={
            "symbol": "INFY",
            "side": "BUY",
            "quantity": 5,
            "price": 1800.0,
            "idempotency_key": "IDEMP-LIVE-TEST-1",
        },
    )
    assert res_prev.status_code == 200
    order_id = res_prev.json()["order_id"]

    # 2. Direct execute without confirm -> 409 Conflict
    res_exec_unconfirmed = client.post(
        "/api/orders/execute",
        json={"order_id": order_id},
    )
    assert res_exec_unconfirmed.status_code == 409
    assert "must be CONFIRMED before live execution" in res_exec_unconfirmed.json()["detail"]

    # 3. Switch mode to SIMULATE -> execution of LIVE order returns 403 Forbidden
    monkeypatch.setenv("TRADING_MODE", "SIMULATE")
    res_cross_mode = client.post(
        "/api/orders/execute",
        json={"order_id": order_id},
    )
    assert res_cross_mode.status_code == 403
    assert "Cross-mode" in res_cross_mode.json()["detail"]


@pytest.mark.anyio
async def test_lifespan_startup_csrf_secret_validation(monkeypatch):
    """
    FastAPI lifespan startup strictly validates CSRF_SECRET in self-hosted mode.
    """
    from web.api import lifespan, app

    monkeypatch.setenv("DEPLOY_MODE", "self-hosted")
    monkeypatch.delenv("CSRF_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="cryptographically strong CSRF_SECRET"):
        async with lifespan(app):
            pass
