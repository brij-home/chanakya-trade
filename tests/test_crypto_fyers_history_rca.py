"""
tests/test_crypto_fyers_history_rca.py
───────────────────────────────────────
Regression tests for Fyers API code -300 and Binance crypto interval RCA:
  1. BINANCE_INTERVAL_MAP covers all multi-timeframe intervals (week, day, 3m, 30m, etc.).
  2. market.history.get_ohlcv never calls Indian equity brokers (Fyers/Zerodha) for crypto assets.
  3. FyersAPI.get_historical_data proactively guards and drops crypto instruments without network calls.
  4. Telemetry properly classifies Fyers SDK code -300 / 'Invalid symbol provided' as P3 INFO instead of P1.
"""

from __future__ import annotations

import logging
import threading
import time
from unittest.mock import MagicMock, patch

import pandas as pd

from brokers.fyers import FyersAPI
from engine.telemetry import TelemetryLogHandler, derive_priority
from market.crypto_stream import BINANCE_INTERVAL_MAP, crypto_stream
from market.history import get_ohlcv


def test_binance_interval_mapping_completeness():
    """Verify BINANCE_INTERVAL_MAP correctly normalizes diverse interval aliases to Binance standard."""
    expected_mappings = {
        "1m": "1m",
        "minute": "1m",
        "1minute": "1m",
        "3m": "3m",
        "3minute": "3m",
        "5m": "5m",
        "5minute": "5m",
        "15m": "15m",
        "15minute": "15m",
        "30m": "30m",
        "30minute": "30m",
        "1h": "1h",
        "60m": "1h",
        "60minute": "1h",
        "day": "1d",
        "1day": "1d",
        "daily": "1d",
        "week": "1w",
        "1w": "1w",
        "weekly": "1w",
        "month": "1M",
        "1mo": "1M",
    }
    for alias, expected in expected_mappings.items():
        assert BINANCE_INTERVAL_MAP.get(alias.lower()) == expected, f"Failed for {alias}"


def test_crypto_stream_fetch_klines_rest_uses_mapped_interval():
    """Verify fetch_klines_rest sends valid Binance interval even when passed 'week' or '3minute'."""
    captured_params = {}

    class MockResp:
        status_code = 200

        def json(self):
            return []

    class MockClient:
        def get(self, url, params=None, timeout=None):
            captured_params.update(params or {})
            return MockResp()

    with patch("market.crypto_stream.get_binance_client", return_value=MockClient()):
        # Test 'week'
        crypto_stream.fetch_klines_rest("SOLUSDT", interval="week", limit=50)
        assert captured_params.get("interval") == "1w"

        # Test '3minute'
        crypto_stream.fetch_klines_rest("SOLUSDT", interval="3minute", limit=50)
        assert captured_params.get("interval") == "3m"

        # Test '1M'
        crypto_stream.fetch_klines_rest("SOLUSDT", interval="1M", limit=50)
        assert captured_params.get("interval") == "1M"


def test_market_history_never_routes_crypto_to_equity_broker():
    """Verify get_ohlcv never calls Indian equity broker (e.g. Fyers) for crypto assets."""
    mock_broker = MagicMock()
    mock_broker._is_mock = False

    with patch("market.crypto_stream.crypto_stream.get_klines", return_value=pd.DataFrame()):
        with patch("brokers.session.get_data_broker", return_value=mock_broker):
            with patch("market.history._yfinance_fallback", return_value=[]):
                # Request for SOLUSDT (default exchange="NSE" or "CRYPTO")
                get_ohlcv("SOLUSDT", exchange="NSE", interval="15m")
                get_ohlcv("CRYPTO:BTCUSDT", interval="day")

                # The broker's get_historical_data MUST NOT have been called
                assert mock_broker.get_historical_data.call_count == 0


def test_fyers_get_historical_data_proactively_guards_crypto():
    """Verify FyersAPI.get_historical_data immediately drops crypto assets without invoking Fyers client."""
    api = FyersAPI(app_id="TEST-100", secret_key="test_secret")
    api._access_token = "mock_token"

    mock_client = MagicMock()
    with patch.object(api, "_get_fyers", return_value=mock_client):
        # 1. Plain crypto ticker
        res1 = api.get_historical_data("SOLUSDT", interval="day")
        assert res1 == []

        # 2. Accidental NSE-prefixed crypto ticker
        res2 = api.get_historical_data("NSE:SOLUSDT", interval="day")
        assert res2 == []

        # 3. Explicit CRYPTO venue
        res3 = api.get_historical_data("BTCUSDT", exchange="CRYPTO", interval="15m")
        assert res3 == []

        # Zero API calls should have been dispatched to Fyers client
        assert mock_client.history.call_count == 0


def test_telemetry_fyers_invalid_symbol_classification():
    """
    Verify that Fyers SDK code -300 ('Invalid symbol provided') ERROR log
    is recognized as benign/audit P3 INFO and not escalated to P1.
    """
    error_msg = "{'API': '/history', 'Error': {'code': -300, 'message': 'Invalid symbol provided', 's': 'error'}}"

    # 1. derive_priority direct classification
    prio = derive_priority("SYSTEM_LOG", "FyersAPI", "ERROR", error_msg)
    assert prio == "P3", f"Expected P3, got {prio}"

    # 2. TelemetryLogHandler emit classification
    handler = TelemetryLogHandler()
    record = logging.LogRecord(
        name="FyersAPI",
        level=logging.ERROR,
        pathname="fyersModel.py",
        lineno=170,
        msg=error_msg,
        args=(),
        exc_info=None,
    )

    with patch("engine.telemetry.record_event") as mock_record:
        handler.emit(record)
        assert mock_record.called
        kwargs = mock_record.call_args[1]
        assert kwargs["priority"] == "P3"
        assert kwargs["severity"] == "INFO"


def test_fyers_headless_auto_login_step5_transient_retry():
    """
    Verify that if Fyers auto-login Step 5 returns HTTP 400 (invalid auth code) on attempt 1,
    the method logs a warning, waits, retries Step 1-5, and successfully returns the token on attempt 2.
    """
    api = FyersAPI(
        app_id="APP-100",
        secret_key="secret",
        fy_id="USER123",
        totp_secret="JBSWY3DPEHPK3PXP",
        pin="1234",
    )

    call_count = {"step5": 0}

    def mock_post(url, **kwargs):
        mock_resp = MagicMock()
        if "send_login_otp" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"request_key": "rk1"}
        elif "verify_otp" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"request_key": "rk2"}
        elif "verify_pin" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"data": {"access_token": "intermediate_token"}}
        elif "/token" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "Url": "https://trade.fyers.in/callback?auth_code=sample_code"
            }
        elif "validate-authcode" in url:
            call_count["step5"] += 1
            if call_count["step5"] == 1:
                mock_resp.status_code = 400
                mock_resp.text = '{"code":-1,"message":"invalid auth code","s":"error"}'
            else:
                mock_resp.status_code = 200
                mock_resp.json.return_value = {"access_token": "VALID_FINAL_TOKEN"}
        return mock_resp

    with patch("requests.post", side_effect=mock_post), patch("time.sleep", return_value=None):
        token = api._auto_login_totp()
        assert token == "VALID_FINAL_TOKEN"
        assert call_count["step5"] == 2


def test_fyers_is_authenticated_concurrent_deduplication():
    """
    Verify that concurrent threads calling is_authenticated() when token is expired
    synchronize on _GLOBAL_FYERS_AUTH_LOCK so that complete_login / auto-login is
    executed exactly once.
    """
    import concurrent.futures

    api = FyersAPI(
        app_id="APP-100",
        secret_key="secret",
        fy_id="USER123",
        totp_secret="JBSWY3DPEHPK3PXP",
        pin="1234",
    )
    api._access_token = ""
    api._token_ts = 0.0

    login_call_count = 0
    login_lock = threading.Lock()

    def mock_complete_login(*args, **kwargs):
        nonlocal login_call_count
        with login_lock:
            login_call_count += 1
        time.sleep(0.02)  # simulate network roundtrip
        api._access_token = "THREAD_SAFE_TOKEN"
        api._token_ts = time.time()
        mock_prof = MagicMock()
        return mock_prof

    with (
        patch.object(api, "complete_login", side_effect=mock_complete_login),
        patch.object(api, "_load_token", return_value=None),
        patch.object(api, "_is_token_expired", side_effect=lambda ts: ts <= 0),
    ):
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(api.is_authenticated) for _ in range(5)]
            results = [f.result() for f in futures]

        assert all(results)
        # Thanks to _GLOBAL_FYERS_AUTH_LOCK and double-checked locking, login runs exactly once
        assert login_call_count == 1
        assert api._access_token == "THREAD_SAFE_TOKEN"


def test_fyers_handle_auth_failure_preserves_fresh_session():
    """
    Verify that _handle_auth_failure skips re-login and preserves session if token was
    already refreshed after the failure timestamp.
    """
    api = FyersAPI(
        app_id="APP-100",
        secret_key="secret",
        fy_id="USER123",
        totp_secret="JBSWY3DPEHPK3PXP",
        pin="1234",
    )
    api._access_token = "FRESH_TOKEN"
    api._token_ts = 2000.0

    with patch.object(api, "complete_login") as mock_login:
        # failed_ts is older than _token_ts
        res = api._handle_auth_failure(failed_ts=1000.0)
        assert res is True
        assert mock_login.call_count == 0
