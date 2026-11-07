"""
tests/test_fyers_token_resilience.py
───────────────────────────────────
Deterministic unit tests for Fyers session boundary token expiration (06:30 AM IST),
self-healing auto-reauthentication upon auth rejection (-16 Token Invalid or Expired),
fail-closed profile and funds contracts, and WebSocket 403 Forbidden halt protection.
"""

from unittest.mock import MagicMock, patch
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest

from brokers.fyers import FyersAPI, _is_fyers_auth_error

IST = ZoneInfo("Asia/Kolkata")


def test_token_expired_on_earlier_calendar_day():
    """Verify tokens generated on a previous calendar day are marked expired."""
    api = FyersAPI(app_id="TEST-100", secret_key="secret")
    old_ts = time.time() - (2 * 86400)
    assert api._is_token_expired(old_ts) is True


def test_token_expired_across_0630_ist_boundary():
    """
    Token generated at 00:01:57 IST is expired after the documented 06:30 AM cutoff.
    """
    api = FyersAPI(app_id="TEST-100", secret_key="secret")

    token_dt = datetime(2026, 10, 27, 0, 1, 57, tzinfo=IST)
    now_dt = datetime(2026, 10, 27, 6, 32, 51, tzinfo=IST)

    with patch("brokers.fyers.time.time", return_value=now_dt.timestamp()):
        assert api._is_token_expired(token_dt.timestamp()) is True


def test_token_valid_before_0630_ist_boundary():
    """Verify midnight session token remains valid immediately before daily cutoff."""
    api = FyersAPI(app_id="TEST-100", secret_key="secret")

    token_dt = datetime(2026, 10, 27, 0, 1, 57, tzinfo=IST)
    now_dt = datetime(2026, 10, 27, 6, 29, 59, tzinfo=IST)

    with patch("brokers.fyers.time.time", return_value=now_dt.timestamp()):
        assert api._is_token_expired(token_dt.timestamp()) is False


def test_token_valid_same_day_after_0630_ist():
    """Verify token generated after 06:30 AM IST remains valid during the session."""
    api = FyersAPI(app_id="TEST-100", secret_key="secret")

    token_dt = datetime(2026, 10, 27, 8, 30, 0, tzinfo=IST)
    now_dt = datetime(2026, 10, 27, 11, 45, 0, tzinfo=IST)

    with patch("brokers.fyers.time.time", return_value=now_dt.timestamp()):
        assert api._is_token_expired(token_dt.timestamp()) is False


def test_token_expired_next_day_after_0630_ist():
    """Verify daytime token expires at the next 06:30 AM IST cutoff."""
    api = FyersAPI(app_id="TEST-100", secret_key="secret")

    token_dt = datetime(2026, 10, 27, 8, 30, 0, tzinfo=IST)
    now_dt = datetime(2026, 10, 28, 6, 35, 0, tzinfo=IST)

    with patch("brokers.fyers.time.time", return_value=now_dt.timestamp()):
        assert api._is_token_expired(token_dt.timestamp()) is True


def test_token_remains_valid_more_than_twelve_hours_before_daily_cutoff():
    """A valid same-day token must not be rejected by an obsolete 12-hour TTL."""
    api = FyersAPI(app_id="TEST-100", secret_key="secret")
    token_dt = datetime(2026, 10, 27, 8, 30, 0, tzinfo=IST)
    now_dt = datetime(2026, 10, 27, 22, 0, 0, tzinfo=IST)

    with patch("brokers.fyers.time.time", return_value=now_dt.timestamp()):
        assert api._is_token_expired(token_dt.timestamp()) is False


def test_is_fyers_auth_error_classifier():
    """Verify _is_fyers_auth_error correctly identifies all Fyers session error formats."""
    assert (
        _is_fyers_auth_error({"s": "error", "code": -16, "message": "Token is Invalid or Expired"})
        is True
    )
    assert (
        _is_fyers_auth_error(
            {"s": "error", "code": -15, "message": "Could not authenticate the user"}
        )
        is True
    )
    assert _is_fyers_auth_error({"s": "error", "code": -14, "message": "Token expired"}) is True
    assert _is_fyers_auth_error({"s": "error", "code": -17, "message": "Invalid token"}) is True
    assert (
        _is_fyers_auth_error({"s": "error", "code": -99, "message": "Authentication failed"})
        is True
    )
    assert _is_fyers_auth_error({"s": "error", "code": 401, "message": "Unauthorized"}) is True
    assert _is_fyers_auth_error({"s": "error", "code": 403, "message": "Forbidden"}) is True
    assert _is_fyers_auth_error({"s": "error", "code": -300, "message": "Invalid symbol"}) is False
    assert _is_fyers_auth_error({"s": "ok", "data": {}}) is False


def test_get_profile_raises_on_code_minus_16_without_totp():
    """
    RCA Verification: get_profile must raise PermissionError on -16 and NEVER cache an empty UserProfile.
    """
    api = FyersAPI(app_id="TEST-100", secret_key="secret")
    api._access_token = "stale_token"
    api._token_ts = time.time()
    mock_sdk = MagicMock()
    mock_sdk.get_profile.return_value = {
        "s": "error",
        "code": -16,
        "message": "Token is Invalid or Expired",
    }
    api._fyers = mock_sdk

    with pytest.raises(PermissionError) as exc_info:
        api.get_profile()

    assert "rejected" in str(exc_info.value).lower() or "expired" in str(exc_info.value).lower()
    assert api._profile is None
    assert api._access_token == ""


def test_get_profile_auto_reauths_with_totp():
    """Verify get_profile catches code -16 and retries after auto-reauthentication when credentials present."""
    api = FyersAPI(
        app_id="TEST-100",
        secret_key="secret",
        fy_id="FAK999",
        totp_secret="BASE32SECRET",
        pin="1234",
    )
    api._access_token = "stale_token"
    api._token_ts = time.time()

    mock_sdk_1 = MagicMock()
    mock_sdk_1.get_profile.return_value = {
        "s": "error",
        "code": -16,
        "message": "Token is Invalid or Expired",
    }
    api._fyers = mock_sdk_1

    mock_sdk_2 = MagicMock()
    mock_sdk_2.get_profile.return_value = {
        "s": "ok",
        "data": {
            "fy_id": "FAK999",
            "name": "Arjun Quant",
            "email_id": "arjun@chanakya.in",
        },
    }

    with patch.object(api, "_handle_auth_failure") as mock_reauth:

        def fake_reauth(failed_ts=None):
            api._access_token = "fresh_token"
            api._token_ts = time.time()
            api._fyers = mock_sdk_2
            return True

        mock_reauth.side_effect = fake_reauth

        profile = api.get_profile()
        assert mock_reauth.called
        assert profile.user_id == "FAK999"
        assert profile.name == "Arjun Quant"
        assert profile.broker == "Fyers"


def test_handle_auth_failure_halts_sockets_and_cleans_token_file(tmp_path, monkeypatch):
    """Verify _handle_auth_failure halts all WebSockets and unlinks token file when re-auth not possible."""
    token_file = tmp_path / "fyers.json"
    token_file.write_text('{"access_token": "expired_xyz", "timestamp": 12345}')
    monkeypatch.setattr("brokers.fyers.TOKEN_FILE", token_file)

    api = FyersAPI(app_id="TEST-100", secret_key="secret")
    api._access_token = "expired_xyz"
    api._token_ts = 12345.0

    with (
        patch("market.fyers_order_stream.fyers_order_stream.stop") as mock_order_stop,
        patch("market.websocket.ws_manager.stop") as mock_ws_stop,
        patch("market.fyers_tbt_manager.fyers_tbt_manager.stop") as mock_tbt_stop,
        patch("web.api._invalidate_auth_cache") as mock_cache_inv,
    ):
        res = api._handle_auth_failure()
        assert res is False
        assert api._access_token == ""
        assert not token_file.exists()
        assert mock_order_stop.called
        assert mock_ws_stop.called
        assert mock_tbt_stop.called
        assert mock_cache_inv.called


def test_fyers_order_stream_403_halts_reconnect_loop():
    """Verify that receiving 403 Forbidden in _handle_error immediately halts the reconnect loop."""
    from market.fyers_order_stream import fyers_order_stream

    with (
        patch.object(fyers_order_stream, "stop") as mock_stop,
        patch("brokers.session.get_data_broker") as mock_get_broker,
    ):
        mock_broker = MagicMock()
        mock_get_broker.return_value = mock_broker

        fyers_order_stream._handle_error(
            "Handshake status 403 Forbidden -+-+- {'date': 'Tue, 27 Oct 2026'}"
        )

        assert mock_stop.called
        assert mock_broker._handle_auth_failure.called


def test_fyers_socket_patch_sets_restart_flag_false_on_403():
    """Verify that patched On_error sets restart_flag=False on 403 Forbidden handshake rejections."""
    pytest.importorskip("fyers_apiv3", reason="fyers_apiv3 is an optional broker SDK")
    from fyers_apiv3.FyersWebsocket import order_ws, data_ws

    dummy_order_sock = MagicMock()
    dummy_order_sock.restart_flag = True
    dummy_order_sock.onerror = MagicMock()
    dummy_order_sock.order_logger = MagicMock()

    order_ws.FyersOrderSocket.On_error(dummy_order_sock, "Handshake status 403 Forbidden")
    assert dummy_order_sock.restart_flag is False

    dummy_data_sock = MagicMock()
    dummy_data_sock.restart_flag = True
    dummy_data_sock.onerror = MagicMock()
    dummy_data_sock.data_logger = MagicMock()

    data_ws.FyersDataSocket.On_error(dummy_data_sock, "Handshake status 403 Forbidden")
    assert dummy_data_sock.restart_flag is False


def test_fyers_headless_auto_login_429_triggers_cooldown_and_suppresses_repeat_calls():
    """Verify that HTTP 429 during headless auto-login trips circuit breaker, sets cooldown, and blocks repeated attempts."""
    from brokers.fyers import _reset_auth_backoff, _get_auth_backoff_remaining
    from market.fyers_circuit_breaker import get_fyers_circuit_breaker

    _reset_auth_backoff()
    api = FyersAPI(
        app_id="TEST-100",
        secret_key="secret",
        fy_id="FAK999",
        totp_secret="BASE32SECRET",
        pin="1234",
    )
    api._access_token = ""
    api._token_ts = 0.0

    cb = get_fyers_circuit_breaker()
    cb.record_success()

    with patch.object(api, "_auto_login_totp") as mock_totp:
        mock_totp.side_effect = RuntimeError(
            'Fyers auto-login step 1 failed (HTTP 429): {"s": "error", "code": 429, "message": "Too many requests. Please try again later."}'
        )

        assert api.is_authenticated() is False
        assert mock_totp.call_count == 1
        assert _get_auth_backoff_remaining() > 0

        # Subsequent 10 calls during cooldown window MUST NOT call _auto_login_totp
        for _ in range(10):
            assert api.is_authenticated() is False

        assert mock_totp.call_count == 1

    _reset_auth_backoff()


def test_fyers_headless_auto_login_success_clears_backoff():
    """Verify that successful headless login resets backoff and records auth success."""
    from brokers.fyers import _reset_auth_backoff, _get_auth_backoff_remaining

    _reset_auth_backoff()
    api = FyersAPI(
        app_id="TEST-100",
        secret_key="secret",
        fy_id="FAK999",
        totp_secret="BASE32SECRET",
        pin="1234",
    )
    api._access_token = ""
    api._token_ts = 0.0

    mock_profile = MagicMock()
    mock_profile.user_id = "FAK999"

    with (
        patch.object(api, "_auto_login_totp", return_value="fresh_token_123"),
        patch.object(api, "_save_token"),
        patch.object(api, "get_profile", return_value=mock_profile),
        patch("web.api._invalidate_auth_cache") as mock_inv,
    ):
        res = api.complete_login()
        assert res.user_id == "FAK999"
        assert api._access_token == "fresh_token_123"
        assert _get_auth_backoff_remaining() == 0.0
        assert mock_inv.called

    _reset_auth_backoff()
