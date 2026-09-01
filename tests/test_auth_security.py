"""
tests/test_auth_security.py
────────────────────────────
Unit and integration tests for P0-B security enhancements:
  - PBKDF2-HMAC-SHA256 password hashing
  - Lazy hash migration from legacy single-pass SHA256 to PBKDF2
  - Session TTL, expiration, and deletion
  - Login attempt rate limiting / throttling
"""

import hashlib
import secrets
import time
import pytest
from web.auth import (
    create_user,
    verify_user,
    create_session,
    get_session,
    delete_session,
    check_rate_limit,
    record_login_failure,
    reset_login_failures,
    _hash_password,
    _verify_password,
    _get_conn,
)


@pytest.fixture(autouse=True)
def clean_auth_state(tmp_path, monkeypatch):
    """Isolate auth DB and session store per test."""
    db_file = tmp_path / "test_users.db"
    monkeypatch.setenv("AUTH_DB_PATH", str(db_file))
    from web.auth import init_db, _sessions, _login_attempts
    init_db()
    _sessions.clear()
    _login_attempts.clear()
    yield
    _sessions.clear()
    _login_attempts.clear()


def test_pbkdf2_password_hashing():
    """Verify passwords are saved with pbkdf2:100000: prefix."""
    user = create_user("trader@example.com", "SecurePassword123!")
    assert user["email"] == "trader@example.com"

    conn = _get_conn()
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
    conn.close()

    stored_hash = row["password_hash"]
    assert stored_hash.startswith("pbkdf2:100000:")
    parts = stored_hash.split(":")
    assert len(parts) == 4
    assert len(parts[2]) == 32  # 16-byte hex salt


def test_verify_user_success_and_failure():
    """Verify correct credentials authenticate and bad credentials fail."""
    create_user("alice@example.com", "CorrectPassword123")

    # Correct credentials
    user = verify_user("alice@example.com", "CorrectPassword123")
    assert user is not None
    assert user["email"] == "alice@example.com"

    # Wrong password
    bad_user = verify_user("alice@example.com", "WrongPassword!")
    assert bad_user is None

    # Non-existent user
    unknown_user = verify_user("nobody@example.com", "CorrectPassword123")
    assert unknown_user is None


def test_lazy_hash_migration_from_legacy_sha256():
    """Verify that a legacy salt:sha256 hash is upgraded to PBKDF2 on successful login."""
    # Insert a legacy user directly with salt:sha256 format
    legacy_salt = secrets.token_hex(16)
    legacy_hash = legacy_salt + ":" + hashlib.sha256((legacy_salt + "LegacyPassword123").encode("utf-8")).hexdigest()

    conn = _get_conn()
    cursor = conn.execute(
        "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
        ("legacy@example.com", legacy_hash, "2026-01-01T00:00:00Z"),
    )
    user_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # Verify user logs in successfully
    verified = verify_user("legacy@example.com", "LegacyPassword123")
    assert verified is not None
    assert verified["id"] == user_id

    # Check that the hash in the DB was upgraded to PBKDF2
    conn = _get_conn()
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()

    upgraded_hash = row["password_hash"]
    assert upgraded_hash.startswith("pbkdf2:100000:")


def test_session_lifecycle_and_expiration():
    """Verify sessions expire and are cleaned up after TTL."""
    # Create a session with a 1-second TTL
    session_id = create_session(1, "test@example.com", ttl_seconds=1)
    session = get_session(session_id)
    assert session is not None
    assert session["email"] == "test@example.com"

    # Wait for session to expire
    time.sleep(1.2)

    # Expired session should return None and be pruned
    expired = get_session(session_id)
    assert expired is None


def test_login_rate_limiting():
    """Verify that after MAX_LOGIN_ATTEMPTS failures, rate limit blocks attempts."""
    key = "127.0.0.1:target@example.com"
    assert check_rate_limit(key) is True

    # Record 5 failures
    for _ in range(5):
        record_login_failure(key)

    # 6th attempt should be blocked
    assert check_rate_limit(key) is False

    # Reset failures clears the block
    reset_login_failures(key)
    assert check_rate_limit(key) is True
