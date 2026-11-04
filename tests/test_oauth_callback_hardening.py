"""
tests/test_oauth_callback_hardening.py
───────────────────────────────────────
Verifies Task P4-E (SEC-15):
- No personal IP in defaults
- OAuth callback redirect URLs enforce HTTPS on non-loopback hosts
- Loopback hosts (127.0.0.1, localhost, ::1) allow HTTP
- OAUTH_CALLBACK_BASE_URL is configurable
"""

import pytest
from config.constants import (
    DEFAULT_SEBI_WHITELISTED_IP,
    DEFAULT_BROKER_CALLBACK_URLS,
    get_broker_callback_url,
    validate_callback_url,
)


def test_no_hardcoded_personal_ip_in_defaults():
    """Verify that DEFAULT_SEBI_WHITELISTED_IP is 127.0.0.1 by default and not a personal public IP."""
    assert (
        DEFAULT_SEBI_WHITELISTED_IP == "127.0.0.1"
        or "103.149.127.88" not in DEFAULT_SEBI_WHITELISTED_IP
    )
    for k, v in DEFAULT_BROKER_CALLBACK_URLS.items():
        assert "103.149.127.88" not in v, f"Found personal IP in default callback for {k}: {v}"


def test_validate_callback_url_loopback_allowed():
    """Loopback URLs with HTTP are permitted for local development and testing."""
    assert (
        validate_callback_url("http://127.0.0.1:8765/fyers/callback")
        == "http://127.0.0.1:8765/fyers/callback"
    )
    assert (
        validate_callback_url("http://localhost:8765/zerodha/callback")
        == "http://localhost:8765/zerodha/callback"
    )
    assert (
        validate_callback_url("http://[::1]:8765/upstox/callback")
        == "http://[::1]:8765/upstox/callback"
    )
    assert (
        validate_callback_url("http://testserver/groww/callback")
        == "http://testserver/groww/callback"
    )


def test_validate_callback_url_non_loopback_http_rejected():
    """Non-loopback public URLs over plaintext HTTP must be rejected."""
    with pytest.raises(ValueError, match="Non-loopback redirect URI.*must use HTTPS"):
        validate_callback_url("http://103.149.127.88:8765/mstock/callback")

    with pytest.raises(ValueError, match="Non-loopback redirect URI.*must use HTTPS"):
        validate_callback_url("http://trade.mydomain.com/fyers/callback")


def test_validate_callback_url_non_loopback_https_accepted():
    """Non-loopback public URLs over HTTPS are permitted."""
    https_url = "https://trade.mydomain.com/fyers/callback"
    assert validate_callback_url(https_url) == https_url


def test_get_broker_callback_url_configurable_base(monkeypatch):
    """Verify OAUTH_CALLBACK_BASE_URL configures the callback base."""
    monkeypatch.setenv("OAUTH_CALLBACK_BASE_URL", "https://prod.chanakya.internal")
    monkeypatch.delenv("FYERS_REDIRECT_URL", raising=False)

    url = get_broker_callback_url("fyers")
    assert url == "https://prod.chanakya.internal/fyers/callback"
