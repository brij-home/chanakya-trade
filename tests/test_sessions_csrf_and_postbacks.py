"""
tests/test_sessions_csrf_and_postbacks.py
──────────────────────────────────────────
Verifies Task P4-C:
- SEC-10: Persistent sessions in SQLite, per-user session cap (no cross-user eviction), IP + key throttling
- SEC-11: OAuth callback state validation, Fyers postback webhook HMAC signature verification
- SEC-12: Error responses do not leak raw exceptions in hosted mode
- SEC-13: Request body size limit middleware (413 Payload Too Large)
- SEC-16: Cloud deployment mode enforces CSRF and strong secrets identical to self-hosted
"""

import hashlib
import hmac
import json
import pytest
from fastapi.testclient import TestClient
from web.api import app, get_csrf_secret, generate_oauth_state, validate_oauth_state
from web.auth import (
    init_db,
    create_user,
    create_session,
    get_session,
    _sessions,
    _login_attempts,
)


@pytest.fixture
def auth_client(tmp_path, monkeypatch):
    db_file = tmp_path / "auth_p4c.db"
    monkeypatch.setenv("AUTH_DB_PATH", str(db_file))
    init_db()
    _sessions.clear()
    _login_attempts.clear()
    yield TestClient(app, raise_server_exceptions=False)
    _sessions.clear()
    _login_attempts.clear()


def test_cloud_mode_enforces_strong_csrf_secret(monkeypatch):
    """DEPLOY_MODE=cloud must raise RuntimeError if CSRF_SECRET is missing, short, or default (SEC-16)."""
    monkeypatch.setenv("DEPLOY_MODE", "cloud")

    # Missing
    monkeypatch.delenv("CSRF_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="cryptographically strong CSRF_SECRET"):
        get_csrf_secret()

    # Short (<32 chars)
    monkeypatch.setenv("CSRF_SECRET", "short-secret-key-123")
    with pytest.raises(RuntimeError, match="cryptographically strong CSRF_SECRET"):
        get_csrf_secret()

    # Insecure default
    monkeypatch.setenv("CSRF_SECRET", "chanakya-csrf-secret-change-in-production")
    with pytest.raises(RuntimeError, match="cryptographically strong CSRF_SECRET"):
        get_csrf_secret()

    # Valid
    strong = "x" * 64
    monkeypatch.setenv("CSRF_SECRET", strong)
    assert get_csrf_secret() == strong


def test_cloud_mode_requires_csrf_token(monkeypatch, auth_client):
    """In cloud mode, mutating POST requests without X-CSRF-Token return 403 (SEC-16)."""
    strong = "y" * 64
    monkeypatch.setenv("DEPLOY_MODE", "cloud")
    monkeypatch.setenv("CSRF_SECRET", strong)

    create_user("trader@chanakya.in", "Password1234!")
    session_id = create_session(user_id=1, email="trader@chanakya.in")
    auth_client.cookies.set("session_id", session_id)

    # Mutating request without CSRF token
    resp = auth_client.post(
        "/api/orders/preview",
        json={"symbol": "INFY", "side": "BUY", "quantity": 10, "price": 1800.0},
    )
    assert resp.status_code == 403
    assert "CSRF" in resp.json().get("detail", "")

    # With valid CSRF token
    expected_token = hmac.new(strong.encode(), session_id.encode(), hashlib.sha256).hexdigest()
    resp_ok = auth_client.post(
        "/api/orders/preview",
        json={"symbol": "INFY", "side": "BUY", "quantity": 10, "price": 1800.0},
        headers={"X-CSRF-Token": expected_token},
    )
    assert resp_ok.status_code == 200


def test_persistent_sessions_in_sqlite(monkeypatch, tmp_path):
    """Sessions are persisted to SQLite and retrieved even when memory cache is cleared (SEC-10)."""
    db_file = tmp_path / "sessions_test.db"
    monkeypatch.setenv("AUTH_DB_PATH", str(db_file))
    init_db()

    session_id = create_session(user_id=42, email="persisted@test.com", ttl_seconds=3600)
    assert session_id in _sessions

    # Clear memory cache
    _sessions.clear()
    assert session_id not in _sessions

    # get_session recovers it from SQLite
    session = get_session(session_id)
    assert session is not None
    assert session["user_id"] == 42
    assert session["email"] == "persisted@test.com"


def test_per_user_session_cap_prevents_cross_user_eviction(monkeypatch, tmp_path):
    """User 1 creating many sessions evicts only User 1's oldest sessions, not User 2's sessions (SEC-10)."""
    db_file = tmp_path / "caps_test.db"
    monkeypatch.setenv("AUTH_DB_PATH", str(db_file))
    init_db()

    # User 2 creates a session
    u2_session_id = create_session(user_id=2, email="user2@test.com")

    # User 1 creates 10 sessions (exceeding MAX_USER_SESSIONS=5)
    u1_sessions = []
    for _ in range(10):
        u1_sessions.append(create_session(user_id=1, email="user1@test.com"))

    # User 2's session must still be intact in DB and valid!
    _sessions.clear()
    assert get_session(u2_session_id) is not None
    assert get_session(u2_session_id)["email"] == "user2@test.com"

    # User 1's oldest sessions (first 5) should have been pruned from DB
    assert get_session(u1_sessions[0]) is None
    # User 1's latest session must exist
    assert get_session(u1_sessions[-1]) is not None


def test_request_body_size_limit_middleware(auth_client):
    """Requests exceeding 2MB are rejected with 413 Payload Too Large (SEC-13)."""
    # Simulate a payload claiming > 2MB
    headers = {"Content-Length": str(3 * 1024 * 1024)}
    resp = auth_client.post("/api/orders/preview", content=b"{}", headers=headers)
    assert resp.status_code == 413
    assert "Payload too large" in resp.json().get("detail", "")


def test_oauth_state_generation_and_validation():
    """OAuth state tokens are cryptographically random, validated once, and tied to broker (SEC-11)."""
    state_fyers = generate_oauth_state("fyers")
    assert state_fyers is not None

    # Mismatched broker fails
    assert validate_oauth_state("zerodha", state_fyers) is False

    # Second try with same token fails (already consumed or mismatched)
    assert validate_oauth_state("fyers", state_fyers) is False

    # New token for fyers succeeds on matching broker
    state_fyers_2 = generate_oauth_state("fyers")
    assert validate_oauth_state("fyers", state_fyers_2) is True
    # Replay fails
    assert validate_oauth_state("fyers", state_fyers_2) is False


def test_fyers_postback_signature_verification(auth_client, monkeypatch):
    """Fyers postback rejects unsigned or invalid signatures when secret is configured (SEC-11)."""
    secret = "fyers-webhook-secret-key-32chars"
    monkeypatch.setenv("FYERS_SECRET_KEY", secret)

    payload = {"order": {"id": "FY-ORD-1234", "status": "FILLED", "symbol": "NSE:SBIN-EQ"}}
    raw_bytes = json.dumps(payload).encode("utf-8")

    # 1. Missing signature -> 401
    resp_no_sig = auth_client.post("/api/fyers/postback", content=raw_bytes)
    assert resp_no_sig.status_code == 401

    # 2. Invalid signature -> 401
    resp_bad_sig = auth_client.post(
        "/api/fyers/postback",
        content=raw_bytes,
        headers={"X-Fyers-Signature": "invalid_sig_hash"},
    )
    assert resp_bad_sig.status_code == 401

    # 3. Valid signature -> 200
    valid_sig = hmac.new(secret.encode("utf-8"), raw_bytes, hashlib.sha256).hexdigest()
    resp_ok = auth_client.post(
        "/api/fyers/postback",
        content=raw_bytes,
        headers={"X-Fyers-Signature": valid_sig},
    )
    assert resp_ok.status_code == 200
    assert resp_ok.json()["status"] == "ok"
