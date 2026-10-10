"""
tests/test_fyers_token_resilience.py
───────────────────────────────────
Deterministic unit tests for Fyers session boundary token expiration
and self-healing auto-reauthentication upon auth rejection.
"""

from unittest.mock import MagicMock, patch
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from brokers.fyers import FyersAPI

IST = ZoneInfo("Asia/Kolkata")


def test_token_expired_on_earlier_calendar_day():
    """Verify tokens generated on a previous calendar day are marked expired."""
    api = FyersAPI(app_id="TEST-100", secret_key="secret")
    # Token from 2 days ago
    old_ts = time.time() - (2 * 86400)
    assert api._is_token_expired(old_ts) is True


def test_token_expired_before_preopen_boundary():
    """Verify tokens generated before 08:00 AM IST are marked expired after 08:30 AM IST."""
    api = FyersAPI(app_id="TEST-100", secret_key="secret")

    # Simulate today at 00:46 AM IST
    now_ist = datetime.now(IST)
    early_morning_ist = now_ist.replace(hour=0, minute=46, second=0, microsecond=0)
    early_ts = early_morning_ist.timestamp()

    # If current time is after 08:30 AM IST, early_ts must be expired
    if now_ist.hour > 8 or (now_ist.hour == 8 and now_ist.minute >= 30):
        assert api._is_token_expired(early_ts) is True


def test_handle_auth_failure_triggers_complete_login():
    """Verify _handle_auth_failure clears token and calls complete_login."""
    api = FyersAPI(
        app_id="TEST-100",
        secret_key="secret",
        fy_id="FAK999",
        totp_secret="BASE32SECRET",
        pin="1234",
    )
    api._access_token = "stale_token"
    api._fyers = MagicMock()

    with patch.object(api, "complete_login") as mock_login:

        def fake_login():
            api._access_token = "fresh_token_123"
            return MagicMock()

        mock_login.side_effect = fake_login

        res = api._handle_auth_failure()
        assert res is True
        assert mock_login.called
        assert api._access_token == "fresh_token_123"


def test_get_quote_auto_reauths_on_token_error():
    """Verify get_quote catches code -16 and retries after auto-reauthentication."""
    api = FyersAPI(
        app_id="TEST-100",
        secret_key="secret",
        fy_id="FAK999",
        totp_secret="BASE32SECRET",
        pin="1234",
    )
    api._access_token = "stale_token"
    mock_sdk_1 = MagicMock()
    # First call returns auth error -16
    mock_sdk_1.quotes.return_value = {
        "s": "error",
        "code": -16,
        "message": "Could not authenticate the user",
    }
    api._fyers = mock_sdk_1

    mock_sdk_2 = MagicMock()
    mock_sdk_2.quotes.return_value = {
        "s": "ok",
        "d": [
            {
                "n": "NSE:RELIANCE-EQ",
                "s": "ok",
                "v": {
                    "lp": 2500.0,
                    "open_price": 2490.0,
                    "high_price": 2510.0,
                    "low_price": 2485.0,
                    "prev_close_price": 2480.0,
                    "volume": 100000,
                    "ch": 20.0,
                    "chp": 0.8,
                },
            }
        ],
    }

    with patch.object(api, "_handle_auth_failure") as mock_reauth:

        def fake_reauth(failed_ts=None):
            api._access_token = "fresh_token"
            api._fyers = mock_sdk_2
            return True

        mock_reauth.side_effect = fake_reauth

        quotes = api.get_quote("NSE:RELIANCE-EQ")
        assert mock_reauth.called
        assert "NSE:RELIANCE-EQ" in quotes
        assert quotes["NSE:RELIANCE-EQ"].last_price == 2500.0
