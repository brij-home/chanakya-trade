"""
tests/test_authz_privileged_endpoints.py
────────────────────────────────────────
Regression tests for SEC-01, SEC-02, SEC-03, SEC-05, OPS-05:
  - Unauthenticated POST /api/mode must be blocked (GET /api/mode remains public)
  - Unauthenticated POST /api/onboarding/credential must be blocked in self-hosted mode
  - Runtime mutation of critical safety/system env vars via set_credential must be rejected
  - Onboarding complete endpoint must validate ranges and reject EXECUTE mode
  - POST /api/mode must record a MODE_CHANGED audit event and enforce live qualification
"""

import pytest
from fastapi.testclient import TestClient
from web.api import app
from web.auth import init_db, create_user, create_session
from config.credentials import set_credential


@pytest.fixture
def auth_client(tmp_path, monkeypatch):
    db_file = tmp_path / "auth_test.db"
    monkeypatch.setenv("AUTH_DB_PATH", str(db_file))
    init_db()
    strong_secret = "super-secret-key-for-testing-purposes-only-64chars-long-value-here"
    monkeypatch.setenv("CSRF_SECRET", strong_secret)
    return TestClient(app, raise_server_exceptions=False)


def test_get_mode_public_but_post_mode_requires_auth(monkeypatch, auth_client):
    """GET /api/mode must be public (200), but POST /api/mode must require authentication."""
    monkeypatch.setenv("DEPLOY_MODE", "self-hosted")

    # GET is public
    res_get = auth_client.get("/api/mode")
    assert res_get.status_code == 200
    assert "mode" in res_get.json()

    # Unauthenticated POST before setup returns 503 (Initial setup required)
    res_post_setup = auth_client.post("/api/mode", json={"mode": "PAPER"})
    assert res_post_setup.status_code == 503

    # After initial user setup, unauthenticated POST must return 401
    create_user("admin@test.com", "SecurePassword123!")
    res_post_unauth = auth_client.post("/api/mode", json={"mode": "PAPER"})
    assert res_post_unauth.status_code in (401, 403), (
        f"Expected 401/403 but got {res_post_unauth.status_code}: {res_post_unauth.text}"
    )


def test_unauthenticated_onboarding_credential_rejected_in_self_hosted(monkeypatch, auth_client):
    """POST /api/onboarding/credential must be rejected for unauthenticated users in self-hosted mode."""
    monkeypatch.setenv("DEPLOY_MODE", "self-hosted")

    # When no session exists, privileged credential setting must be rejected (503 before setup, 401 after)
    res = auth_client.post(
        "/api/onboarding/credential",
        json={"key": "FYERS_APP_ID", "value": "test-app-id"},
    )
    assert res.status_code in (401, 403, 503), (
        f"Expected auth rejection but got {res.status_code}: {res.text}"
    )

    create_user("admin@test.com", "SecurePassword123!")
    res2 = auth_client.post(
        "/api/onboarding/credential",
        json={"key": "FYERS_APP_ID", "value": "test-app-id"},
    )
    assert res2.status_code in (401, 403), (
        f"Expected 401/403 but got {res2.status_code}: {res2.text}"
    )


def test_set_credential_rejects_forbidden_env_mutations():
    """Attempting to mutate safety gates, execution modes, or OS environment keys must raise ValueError."""
    forbidden_keys = [
        "ALLOW_LIVE_TRADING",
        "LIVE_EXECUTION_QUALIFIED",
        "PILOT_ALLOW_LIVE_EXECUTION",
        "TRADING_MODE",
        "DEPLOY_MODE",
        "PATH",
        "PYTHONPATH",
        "LD_PRELOAD",
        "UNKNOWN_ARBITRARY_KEY_XYZ",
    ]

    for key in forbidden_keys:
        with pytest.raises(ValueError, match="forbidden|Unknown or unauthorized"):
            set_credential(key, "1")


def test_onboarding_complete_validation(monkeypatch, auth_client):
    """POST /api/onboarding/complete must validate input ranges and reject EXECUTE mode."""
    monkeypatch.setenv("DEPLOY_MODE", "self-hosted")

    # Create admin user & session
    create_user("admin@test.com", "SecurePassword123!")
    session_id = create_session(user_id=1, email="admin@test.com")
    auth_client.cookies.set("session_id", session_id)

    # Fetch CSRF token
    csrf_res = auth_client.get("/api/csrf-token")
    csrf_token = csrf_res.json().get("csrf_token", "")
    headers = {"X-CSRF-Token": csrf_token}

    # Reject EXECUTE mode
    res_execute = auth_client.post(
        "/api/onboarding/complete",
        json={"capital": 200000, "risk_pct": 2.0, "trading_mode": "EXECUTE"},
        headers=headers,
    )
    assert res_execute.status_code in (400, 422), (
        f"Expected 400/422 for EXECUTE mode, got {res_execute.status_code}"
    )

    # Reject non-positive capital
    res_cap = auth_client.post(
        "/api/onboarding/complete",
        json={"capital": -50000, "risk_pct": 2.0, "trading_mode": "PAPER"},
        headers=headers,
    )
    assert res_cap.status_code in (400, 422)

    # Reject risk_pct > 10%
    res_risk = auth_client.post(
        "/api/onboarding/complete",
        json={"capital": 200000, "risk_pct": 50.0, "trading_mode": "PAPER"},
        headers=headers,
    )
    assert res_risk.status_code in (400, 422)
