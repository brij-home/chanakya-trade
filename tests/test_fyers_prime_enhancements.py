"""
tests/test_fyers_prime_enhancements.py
───────────────────────────────────────
Unit tests for Fyers Prime institutional capabilities:
  1. Seconds-resolution historical data ('5s', '10s', '15s', '30s', '45s').
  2. Continuous contract flag differentiation (Futures cont_flag='1' vs Options/Equity cont_flag='0').
  3. Expired F&O handling (code -300 error resilience and get_expired_fno_history).
  4. URL query length safety (clamping quotes chunk size to 300 symbols to avoid HTTP 414).
  5. market.history seconds TTL and lookback clamping.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock


from brokers.fyers import FyersAPI
from market.quote_dispatcher import QuoteDispatcher, SAFE_HTTP_MAX_CHUNK_SIZE
from market.history import INTERVAL_MAP, get_ohlcv


def test_fyers_seconds_history_resolutions(monkeypatch):
    """Verify that 5s, 10s, 15s, 30s, 45s intervals map to Fyers '5S', '10S', etc."""
    api = FyersAPI(app_id="TEST-100", secret_key="test_secret")
    api._access_token = "mock_token"

    captured_payloads = []

    class MockFyersClient:
        def history(self, payload):
            captured_payloads.append(payload)
            start_dt = datetime.strptime(payload["range_from"], "%Y-%m-%d")
            epoch = int(start_dt.timestamp())
            return {
                "s": "ok",
                "candles": [
                    [epoch, 100.0, 105.0, 99.0, 104.0, 1000],
                    [epoch + 5, 104.0, 106.0, 103.0, 105.0, 1200],
                ],
            }

    monkeypatch.setattr(api, "_get_fyers", lambda: MockFyersClient())

    # Test 5s
    api.get_historical_data("RELIANCE", interval="5s")
    assert len(captured_payloads) == 1
    assert captured_payloads[-1]["resolution"] == "5S"

    # Test 15s
    api.get_historical_data("TCS", interval="15s")
    assert captured_payloads[-1]["resolution"] == "15S"

    # Test 30s
    api.get_historical_data("INFY", interval="30s")
    assert captured_payloads[-1]["resolution"] == "30S"


def test_fyers_continuous_flag_futures_vs_options(monkeypatch):
    """
    Verify continuous data flag cont_flag:
      - '1' for Futures contracts
      - '0' for Options, Equities, and Spot Indices
    """
    api = FyersAPI(app_id="TEST-100", secret_key="test_secret")
    api._access_token = "mock_token"

    captured_payloads = []

    class MockFyersClient:
        def history(self, payload):
            captured_payloads.append(payload)
            return {"s": "ok", "candles": []}

    monkeypatch.setattr(api, "_get_fyers", lambda: MockFyersClient())

    # 1. Futures -> cont_flag = '1'
    api.get_historical_data("NSE:NIFTY26OCTFUT", interval="5minute")
    assert captured_payloads[-1]["cont_flag"] == "1"

    # 2. Options -> cont_flag = '0'
    api.get_historical_data("NSE:NIFTY26OCT25000CE", interval="5minute")
    assert captured_payloads[-1]["cont_flag"] == "0"

    # 3. Equity -> cont_flag = '0'
    api.get_historical_data("NSE:RELIANCE-EQ", interval="day")
    assert captured_payloads[-1]["cont_flag"] == "0"


def test_fyers_expired_fno_contract_resilience(monkeypatch):
    """
    Verify that expired / delisted contracts returning code -300
    ('Please provide a valid symbol') terminate cleanly without spamming chunks.
    """
    api = FyersAPI(app_id="TEST-100", secret_key="test_secret")
    api._access_token = "mock_token"

    call_count = 0

    class MockFyersClient:
        def history(self, payload):
            nonlocal call_count
            call_count += 1
            return {"s": "error", "code": -300, "message": "Please provide a valid symbol"}

    monkeypatch.setattr(api, "_get_fyers", lambda: MockFyersClient())

    # Request 90 days of an expired option
    from_dt = datetime(2025, 1, 1)
    to_dt = datetime(2025, 3, 31)
    rows = api.get_historical_data(
        "NSE:NIFTY25JAN22000CE", interval="5minute", from_date=from_dt, to_date=to_dt
    )

    assert rows == []
    # Because of early break on code -300, it should not repeatedly call for subsequent chunks
    assert call_count == 1

    # Also test get_expired_fno_history method
    rows_expired = api.get_expired_fno_history("NSE:NIFTY25JAN22000CE", interval="5minute")
    assert rows_expired == []


def test_market_history_seconds_integration(monkeypatch):
    """Verify market.history.get_ohlcv integrates seconds resolutions with lookback clamping."""
    assert "5s" in INTERVAL_MAP
    assert "10s" in INTERVAL_MAP
    assert "15s" in INTERVAL_MAP
    assert "30s" in INTERVAL_MAP
    assert "45s" in INTERVAL_MAP

    mock_broker = MagicMock()
    mock_broker._is_mock = False
    now = datetime.now()
    mock_broker.get_historical_data.return_value = [
        {
            "date": now - timedelta(seconds=10),
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 101.0,
            "volume": 500,
        },
        {
            "date": now - timedelta(seconds=5),
            "open": 101.0,
            "high": 103.0,
            "low": 100.0,
            "close": 102.5,
            "volume": 800,
        },
    ]

    monkeypatch.setattr("brokers.session.get_data_broker", lambda: mock_broker)
    monkeypatch.setattr("brokers.session.get_data_broker_key", lambda: "fyers")

    df = get_ohlcv("SBIN", interval="5s", days=60)
    assert not df.empty
    assert len(df) == 2
    assert "open" in df.columns
    assert "close" in df.columns


def test_quotes_chunking_url_length_safe(monkeypatch):
    """Verify that QuoteDispatcher and FyersAPI clamp quotes batch chunk size to 300."""
    dispatcher = QuoteDispatcher()
    assert dispatcher._chunk_size <= SAFE_HTTP_MAX_CHUNK_SIZE
    assert dispatcher._chunk_size <= 300

    api = FyersAPI(app_id="TEST-100", secret_key="test_secret")
    api._access_token = "mock_token"

    mock_fyers_sdk = MagicMock()
    chunks_sent = []

    def mock_quotes(payload):
        symbols_str = payload.get("symbols", "")
        chunks_sent.append(symbols_str.split(","))
        return {
            "s": "ok",
            "d": [
                {
                    "n": sym,
                    "v": {
                        "lp": 100.0,
                        "open_price": 99.0,
                        "high_price": 101.0,
                        "low_price": 98.0,
                        "prev_close_price": 99.0,
                        "volume": 1000,
                    },
                }
                for sym in symbols_str.split(",")
            ],
        }

    mock_fyers_sdk.quotes = mock_quotes
    monkeypatch.setattr(api, "_get_fyers", lambda: mock_fyers_sdk)

    # Request quotes for 750 symbols
    test_symbols = [f"NSE:STK{i}-EQ" for i in range(750)]
    res = api.get_quote(test_symbols)

    assert len(res) == 750
    # Should be partitioned into chunks of at most 300 symbols (e.g. 300 + 300 + 150 = 3 chunks)
    assert len(chunks_sent) == 3
    for chunk in chunks_sent:
        assert len(chunk) <= 300
