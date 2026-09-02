"""
tests/test_csrf_integration.py
───────────────────────────────
Integration tests for CSRF token generation, strength validation, and self-hosted mutation protection.
"""

import hashlib
import hmac
import uuid
import pytest
from starlette.testclient import TestClient


def test_self_hosted_startup_fails_without_strong_secret(monkeypatch):
    """
    In self-hosted mode (DEPLOY_MODE=self-hosted), starting or calling get_csrf_secret
    without a 32+ char high-entropy CSRF_SECRET must raise RuntimeError.
    """
    from web.api import get_csrf_secret

    monkeypatch.setenv("DEPLOY_MODE", "self-hosted")
    monkeypatch.delenv("CSRF_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="requires a cryptographically strong CSRF_SECRET"):
        get_csrf_secret()


def test_self_hosted_startup_fails_with_insecure_default_secret(monkeypatch):
    """
    In self-hosted mode, using a known placeholder default CSRF_SECRET must raise RuntimeError.
    """
    from web.api import get_csrf_secret

    monkeypatch.setenv("DEPLOY_MODE", "self-hosted")
    monkeypatch.setenv("CSRF_SECRET", "chanakya-csrf-secret-change-in-production")

    with pytest.raises(RuntimeError, match="missing or insecure secret"):
        get_csrf_secret()


def test_self_hosted_startup_succeeds_with_strong_secret(monkeypatch):
    """
    In self-hosted mode, providing a high-entropy 32+ character CSRF_SECRET must succeed.
    """
    from web.api import get_csrf_secret

    strong_secret = "c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8"
    monkeypatch.setenv("DEPLOY_MODE", "self-hosted")
    monkeypatch.setenv("CSRF_SECRET", strong_secret)

    secret = get_csrf_secret()
    assert secret == strong_secret


def test_csrf_token_endpoint_and_validation(tmp_path, monkeypatch):
    """
    GET /api/csrf-token returns valid HMAC token for active session.
    Mutating methods (POST/PUT/DELETE) in self-hosted mode enforce X-CSRF-Token.
    """
    from web.api import app
    from web.auth import init_db, create_user, create_session

    db_path = tmp_path / "auth.db"
    monkeypatch.setenv("AUTH_DB_PATH", str(db_path))
    init_db()
    create_user("test@example.com", "password123")

    strong_secret = "c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8"
    monkeypatch.setenv("DEPLOY_MODE", "self-hosted")
    monkeypatch.setenv("CSRF_SECRET", strong_secret)

    client = TestClient(app)

    # 1. Obtain a valid session
    session_id = create_session(user_id=1, email="test@example.com")

    # 2. Get CSRF token
    res = client.get("/api/csrf-token", cookies={"session_id": session_id})
    assert res.status_code == 200
    token = res.json().get("csrf_token")
    assert token is not None

    expected_hmac = hmac.new(
        strong_secret.encode(), session_id.encode(), hashlib.sha256
    ).hexdigest()
    assert token == expected_hmac

    # 3. Mutating request WITHOUT CSRF header -> 403
    preview_payload = {
        "symbol": "RELIANCE",
        "side": "BUY",
        "quantity": 10,
        "price": 2800.0,
    }
    res_no_csrf = client.post(
        "/api/orders/preview",
        json=preview_payload,
        cookies={"session_id": session_id},
    )
    assert res_no_csrf.status_code == 403
    assert "CSRF token invalid or missing" in res_no_csrf.json()["detail"]

    # 4. Mutating request WITH INVALID CSRF header -> 403
    res_bad_csrf = client.post(
        "/api/orders/preview",
        json=preview_payload,
        headers={"X-CSRF-Token": "bad-token-12345"},
        cookies={"session_id": session_id},
    )
    assert res_bad_csrf.status_code == 403

    # 5. Mutating request WITH VALID CSRF header -> 200
    res_valid_csrf = client.post(
        "/api/orders/preview",
        json=preview_payload,
        headers={"X-CSRF-Token": token},
        cookies={"session_id": session_id},
    )
    assert res_valid_csrf.status_code == 200
    assert "order_id" in res_valid_csrf.json()


def test_order_confirmation_is_required_and_request_metadata_is_not_client_controlled(
    tmp_path, monkeypatch
):
    """Live-capable endpoints reject direct execute and venue/segment overrides."""
    from web.api import app
    from web.auth import create_session, create_user, init_db

    monkeypatch.setenv("AUTH_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv("DEPLOY_MODE", "self-hosted")
    monkeypatch.setenv("CSRF_SECRET", "a" * 64)
    init_db()
    create_user("confirm@example.com", "password123")
    session_id = create_session(user_id=1, email="confirm@example.com")
    client = TestClient(app)
    token = client.get("/api/csrf-token", cookies={"session_id": session_id}).json()["csrf_token"]
    headers = {"X-CSRF-Token": token}
    cookies = {"session_id": session_id}

    override = client.post(
        "/api/orders/preview",
        json={
            "symbol": "MCX:GOLD",
            "side": "BUY",
            "quantity": 1,
            "price": 72000,
            "exchange": "NSE",
        },
        headers=headers,
        cookies=cookies,
    )
    assert override.status_code == 422

    preview = client.post(
        "/api/orders/preview",
        json={
            "symbol": "RELIANCE",
            "side": "BUY",
            "quantity": 1,
            "price": 2800,
            "idempotency_key": f"confirm-test-{uuid.uuid4()}",
        },
        headers=headers,
        cookies=cookies,
    )
    assert preview.status_code == 200
    intent = preview.json()

    direct_execute = client.post(
        "/api/orders/execute",
        json={"order_id": intent["order_id"]},
        headers=headers,
        cookies=cookies,
    )
    assert direct_execute.status_code == 409

    confirmed = client.post(
        "/api/orders/confirm",
        json={"order_id": intent["order_id"], "preview_hash": intent["preview_hash"]},
        headers=headers,
        cookies=cookies,
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "CONFIRMED"
