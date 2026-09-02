"""
web/auth.py
───────────
User authentication for web mode (login/signup with email + password).

Uses SQLite for user storage and in-memory sessions.
"""

from __future__ import annotations

import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
import hashlib
from config.paths import app_data_path

# ── Database ─────────────────────────────────────────────────────

DB_PATH = Path(os.environ.get("AUTH_DB_PATH", app_data_path("users.db")))


def _db_path() -> Path:
    """Return the active auth DB path, allowing tests/containers to override it."""
    return Path(os.environ.get("AUTH_DB_PATH", DB_PATH))


def init_db() -> None:
    """Create the users table if it doesn't exist."""
    db_path = _db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            email       TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at  TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
    except Exception:
        pass
    return conn


def user_count() -> int:
    """Return the total number of registered users."""
    if not _db_path().exists():
        return 0
    conn = _get_conn()
    try:
        row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


# ── User CRUD & Password Security ───────────────────────────────

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PBKDF2_ITERATIONS = 100_000
SESSION_TTL_SECONDS = 7 * 24 * 3600  # 7 days


def _hash_password(password: str) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 with a random salt."""
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ITERATIONS,
    ).hex()
    return f"pbkdf2:{PBKDF2_ITERATIONS}:{salt}:{hashed}"


def _verify_password(stored_hash: str, password: str) -> tuple[bool, bool]:
    """
    Verify password against stored hash.
    Returns (is_valid, needs_upgrade).
    Supports PBKDF2-HMAC-SHA256 and legacy single-pass SHA-256 with salt.
    """
    if stored_hash.startswith("pbkdf2:"):
        parts = stored_hash.split(":", 3)
        if len(parts) == 4:
            _, iters_str, salt, expected_hash = parts
            try:
                iters = int(iters_str)
                computed = hashlib.pbkdf2_hmac(
                    "sha256",
                    password.encode("utf-8"),
                    salt.encode("utf-8"),
                    iters,
                ).hex()
                return secrets.compare_digest(computed, expected_hash), False
            except Exception:
                return False, False
        return False, False

    # Legacy format: salt:sha256_hex
    if ":" in stored_hash:
        salt, expected_hash = stored_hash.split(":", 1)
        computed = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
        is_valid = secrets.compare_digest(computed, expected_hash)
        # Needs upgrade to PBKDF2 if password is valid
        return is_valid, is_valid

    return False, False


def create_user(email: str, password: str) -> dict:
    """
    Create a new user account.
    Validates email format and password length (>= 8 chars).
    Hashes password with PBKDF2-HMAC-SHA256 (100k iterations).
    """
    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise ValueError("Invalid email format")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")

    password_hash = _hash_password(password)
    now = datetime.now(timezone.utc).isoformat()

    conn = _get_conn()
    try:
        cursor = conn.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, password_hash, now),
        )
        conn.commit()
        return {"id": cursor.lastrowid, "email": email, "created_at": now}
    except sqlite3.IntegrityError:
        raise ValueError("An account with this email already exists")
    finally:
        conn.close()


def create_initial_user(email: str, password: str) -> dict:
    """Atomically create the one account allowed during self-hosted setup."""
    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise ValueError("Invalid email format")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")

    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
            raise PermissionError(
                "Initial setup is already complete. Sign in with an existing account."
            )
        cursor = conn.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, _hash_password(password), now),
        )
        conn.commit()
        return {"id": cursor.lastrowid, "email": email, "created_at": now}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def verify_user(email: str, password: str) -> dict | None:
    """
    Verify credentials and lazily upgrade legacy password hashes.
    Returns user dict {id, email, created_at} or None.
    """
    email = email.strip().lower()
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT id, email, password_hash, created_at FROM users WHERE email = ?",
            (email,),
        ).fetchone()
        if not row:
            return None

        stored_hash = row["password_hash"]
        is_valid, needs_upgrade = _verify_password(stored_hash, password)
        if not is_valid:
            return None

        # Transparent lazy upgrade from legacy SHA-256 to PBKDF2
        if needs_upgrade:
            try:
                new_hash = _hash_password(password)
                conn.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (new_hash, row["id"]),
                )
                conn.commit()
            except Exception:
                pass

        return {"id": row["id"], "email": row["email"], "created_at": row["created_at"]}
    finally:
        conn.close()


# ── Login Rate Limiting (Throttling) ────────────────────────────

_login_attempts: dict[str, list[float]] = {}
MAX_LOGIN_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 60.0


def check_rate_limit(key: str) -> bool:
    """Check if the key (IP or email) is within allowed login attempt limits."""
    import time

    now = time.time()
    attempts = _login_attempts.get(key, [])
    # Filter attempts within window
    recent = [t for t in attempts if now - t < LOGIN_WINDOW_SECONDS]
    _login_attempts[key] = recent
    return len(recent) < MAX_LOGIN_ATTEMPTS


def record_login_failure(key: str) -> None:
    """Record a failed login attempt for rate limiting."""
    import time

    now = time.time()
    attempts = _login_attempts.setdefault(key, [])
    attempts.append(now)


def reset_login_failures(key: str) -> None:
    """Clear failed login attempts upon successful authentication."""
    _login_attempts.pop(key, None)


# ── Session store with TTL & Expiration ─────────────────────────

_sessions: dict[str, dict] = {}


def create_session(user_id: int, email: str, ttl_seconds: int = SESSION_TTL_SECONDS) -> str:
    """Generate a secure random session ID with expiration."""
    from datetime import timedelta

    if len(_sessions) >= 1000:
        oldest_key = next(iter(_sessions))
        _sessions.pop(oldest_key, None)

    session_id = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ttl_seconds)

    _sessions[session_id] = {
        "user_id": user_id,
        "email": email,
        "created_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
    }
    return session_id


def get_session(session_id: str) -> dict | None:
    """Return active session dict or None if expired/not found."""
    session = _sessions.get(session_id)
    if not session:
        return None

    # Check expiration
    expires_str = session.get("expires_at")
    if expires_str:
        try:
            expires_at = datetime.fromisoformat(expires_str)
            if datetime.now(timezone.utc) > expires_at:
                delete_session(session_id)
                return None
        except Exception:
            pass

    return session


def delete_session(session_id: str) -> None:
    """Remove a session."""
    _sessions.pop(session_id, None)


# ── FastAPI router ───────────────────────────────────────────────

auth_router = APIRouter(prefix="/auth", tags=["Auth"])


class AuthBody(BaseModel):
    email: str
    password: str


@auth_router.post("/signup")
async def signup(body: AuthBody, response: Response, request: Request):
    """Create a new account, start a session, set cookie."""
    if "@" not in body.email:
        raise HTTPException(400, "Invalid email — must contain @")
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")

    try:
        if os.environ.get("DEPLOY_MODE", "") == "self-hosted":
            user = create_initial_user(body.email, body.password)
        else:
            user = create_user(body.email, body.password)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))

    session_id = create_session(user["id"], user["email"])
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        samesite="lax",
        max_age=SESSION_TTL_SECONDS,
    )
    return {"ok": True, "email": user["email"]}


@auth_router.post("/login")
async def login(body: AuthBody, response: Response, request: Request):
    """Verify credentials with rate limiting, start a session, set cookie."""
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"{client_ip}:{body.email.strip().lower()}"

    if not check_rate_limit(rate_key):
        raise HTTPException(
            429,
            f"Too many failed login attempts. Please wait {int(LOGIN_WINDOW_SECONDS)} seconds before retrying.",
        )

    user = verify_user(body.email, body.password)
    if not user:
        record_login_failure(rate_key)
        raise HTTPException(401, "Invalid email or password")

    reset_login_failures(rate_key)
    session_id = create_session(user["id"], user["email"])
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        samesite="lax",
        max_age=SESSION_TTL_SECONDS,
    )
    return {"ok": True, "email": user["email"]}


@auth_router.post("/logout")
async def logout(request: Request, response: Response):
    """Delete session and clear cookie."""
    session_id = request.cookies.get("session_id")
    if session_id:
        delete_session(session_id)
    response.delete_cookie("session_id")
    return {"ok": True}


@auth_router.get("/me")
async def me(request: Request):
    """Return current user info from session cookie."""
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(401, "Not authenticated")
    session = get_session(session_id)
    if not session:
        raise HTTPException(401, "Session expired")
    return {"email": session["email"], "user_id": session["user_id"]}


# ── Auth dependency ──────────────────────────────────────────────


async def require_auth(request: Request) -> dict:
    """Dependency that checks for valid session cookie."""
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(401, "Not authenticated")
    session = get_session(session_id)
    if not session:
        raise HTTPException(401, "Session expired")
    return session
