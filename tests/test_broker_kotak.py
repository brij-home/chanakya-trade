"""
tests/test_broker_kotak.py
──────────────────────────
Deterministic unit tests for Kotak Securities Neo API broker integration.
Requires no live credentials or external network access.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from brokers import kotak
from brokers.base import OrderRequest
from brokers.kotak import KotakNeoAPI
from market.kotak_websocket import KotakTick, kotak_ws


@pytest.fixture(autouse=True)
def isolated_kotak_token_file(tmp_path, monkeypatch):
    """Isolate token persistence to temporary directory during tests."""
    fake_token = tmp_path / "kotak.json"
    monkeypatch.setattr(kotak, "TOKEN_FILE", fake_token)
    return fake_token


class _MockResponse:
    def __init__(self, status_code: int, json_data: dict):
        self.status_code = status_code
        self._json_data = json_data
        self.text = json.dumps(json_data)

    def json(self):
        return self._json_data


def test_kotak_init():
    broker = KotakNeoAPI(
        consumer_key="ck_123",
        consumer_secret="cs_456",
        mobile_number="9876543210",
        ucc="K12345",
        password="secret_pass",
        totp_secret="BASE32SECRET3232",
        mpin="123456",
        environment="prod",
    )
    assert broker._consumer_key == "ck_123"
    assert broker._consumer_secret == "cs_456"
    assert broker._ucc == "K12345"
    assert broker._mpin == "123456"
    assert broker._environment == "prod"
    assert broker.is_authenticated() is False


def test_kotak_profile():
    broker = KotakNeoAPI(ucc="K98765")
    profile = broker.get_profile()
    assert profile.user_id == "K98765"
    assert profile.broker == "KOTAK"


def test_kotak_missing_credentials_fails_closed():
    broker = KotakNeoAPI()
    with pytest.raises(RuntimeError, match="Consumer Key and Consumer Secret are required"):
        broker.complete_login()
    assert broker.is_authenticated() is False


def test_kotak_complete_login_token():
    broker = KotakNeoAPI(ucc="K88888")
    profile = broker.complete_login(token="jwt_sample_token_xyz")
    assert broker.is_authenticated() is True
    assert broker._session_token == "jwt_sample_token_xyz"
    assert profile.user_id == "K88888"


def test_kotak_totp_login_flow(monkeypatch, isolated_kotak_token_file):
    broker = KotakNeoAPI(
        consumer_key="test_ck",
        consumer_secret="test_cs",
        mobile_number="9876543210",
        ucc="KOTAK001",
        password="test_password",
        totp_secret="JBSWY3DPEHPK3PXP",
        mpin="654321",
    )

    def mock_post(url, *args, **kwargs):
        if "oauth/token" in url:
            return _MockResponse(200, {"access_token": "oauth_bearer_123"})
        if "login/v2/validate/mpin" in url or "login/v2/validate/otp" in url:
            return _MockResponse(
                200,
                {
                    "data": {
                        "sessionToken": "live_session_token_999",
                        "sid": "sid_session_abc",
                        "greetingName": "Arjun Sharma",
                        "emailId": "arjun@example.com",
                        "feedUrl": "wss://feed.kotaksecurities.com",
                    }
                },
            )
        if "login/v2/validate" in url:
            return _MockResponse(
                200,
                {
                    "data": {
                        "sid": "sid_session_abc",
                        "token": "temp_auth_token",
                    }
                },
            )
        return _MockResponse(404, {"error": "Not Found"})

    monkeypatch.setattr("httpx.Client.post", lambda self, url, *a, **kw: mock_post(url, *a, **kw))

    profile = broker.complete_login()
    assert broker.is_authenticated() is True
    assert broker._session_token == "live_session_token_999"
    assert broker._sid == "sid_session_abc"
    assert profile.name == "Arjun Sharma"
    assert profile.email == "arjun@example.com"

    # Verify persisted JSON file
    assert isolated_kotak_token_file.exists()
    saved = json.loads(isolated_kotak_token_file.read_text(encoding="utf-8"))
    assert saved["session_token"] == "live_session_token_999"
    assert saved["sid"] == "sid_session_abc"


def test_kotak_funds(monkeypatch):
    broker = KotakNeoAPI(ucc="KOTAK001")
    broker._session_token = "valid_token"
    broker._token_saved_at = datetime.now().timestamp()

    def mock_get(url, *args, **kwargs):
        if "apim/orders/1.0/limits" in url:
            return _MockResponse(
                200,
                {
                    "data": {
                        "netCashAvailable": 450000.0,
                        "marginUsed": 150000.0,
                    }
                },
            )
        return _MockResponse(404, {})

    monkeypatch.setattr("httpx.Client.get", lambda self, url, *a, **kw: mock_get(url, *a, **kw))

    funds = broker.get_funds()
    assert funds.available_cash == 450000.0
    assert funds.used_margin == 150000.0
    assert funds.total_balance == 600000.0


def test_kotak_holdings(monkeypatch):
    broker = KotakNeoAPI(ucc="KOTAK001")
    broker._session_token = "valid_token"
    broker._token_saved_at = datetime.now().timestamp()

    def mock_get(url, *args, **kwargs):
        if "apim/portfolio/1.0/holdings" in url:
            return _MockResponse(
                200,
                {
                    "data": [
                        {
                            "tradingSymbol": "RELIANCE",
                            "exchange": "NSE",
                            "holdingQuantity": 50,
                            "averagePrice": 2800.0,
                            "ltp": 2950.0,
                            "unrealizedGainLoss": 7500.0,
                        }
                    ]
                },
            )
        return _MockResponse(404, {})

    monkeypatch.setattr("httpx.Client.get", lambda self, url, *a, **kw: mock_get(url, *a, **kw))

    holdings = broker.get_holdings()
    assert len(holdings) == 1
    assert holdings[0].symbol == "RELIANCE"
    assert holdings[0].quantity == 50
    assert holdings[0].avg_price == 2800.0
    assert holdings[0].last_price == 2950.0
    assert holdings[0].pnl == 7500.0


def test_kotak_positions(monkeypatch):
    broker = KotakNeoAPI(ucc="KOTAK001")
    broker._session_token = "valid_token"
    broker._token_saved_at = datetime.now().timestamp()

    def mock_get(url, *args, **kwargs):
        if "apim/portfolio/1.0/positions" in url:
            return _MockResponse(
                200,
                {
                    "data": [
                        {
                            "tradingSymbol": "NIFTY24APR22500CE",
                            "exchange": "NFO",
                            "productType": "NRML",
                            "netQuantity": 50,
                            "buyAveragePrice": 120.0,
                            "ltp": 160.0,
                            "unrealizedGainLoss": 2000.0,
                        },
                        {
                            "tradingSymbol": "CLOSED_POS",
                            "netQuantity": 0,
                        },
                    ]
                },
            )
        return _MockResponse(404, {})

    monkeypatch.setattr("httpx.Client.get", lambda self, url, *a, **kw: mock_get(url, *a, **kw))

    positions = broker.get_positions()
    assert len(positions) == 1  # Only open positions with net_qty != 0
    assert positions[0].symbol == "NIFTY24APR22500CE"
    assert positions[0].quantity == 50
    assert positions[0].avg_price == 120.0
    assert positions[0].last_price == 160.0


def test_kotak_quotes(monkeypatch):
    broker = KotakNeoAPI(ucc="KOTAK001")
    broker._session_token = "valid_token"
    broker._token_saved_at = datetime.now().timestamp()

    def mock_post(url, *args, **kwargs):
        if "apim/orders/1.0/quotes" in url:
            return _MockResponse(
                200,
                {
                    "data": [
                        {
                            "instrumentToken": "2885",
                            "tradingSymbol": "RELIANCE",
                            "lastPrice": 2980.5,
                            "open": 2950.0,
                            "high": 3000.0,
                            "low": 2940.0,
                            "prevClose": 2930.0,
                            "volume": 2500000,
                            "change": 50.5,
                            "netPricePercentageChange": 1.72,
                        }
                    ]
                },
            )
        return _MockResponse(404, {})

    monkeypatch.setattr("httpx.Client.post", lambda self, url, *a, **kw: mock_post(url, *a, **kw))

    quotes = broker.get_quote(["NSE:RELIANCE"])
    assert "NSE:RELIANCE" in quotes
    q = quotes["NSE:RELIANCE"]
    assert q.symbol == "RELIANCE"
    assert q.last_price == 2980.5
    assert q.open == 2950.0
    assert q.high == 3000.0
    assert q.low == 2940.0
    assert q.volume == 2500000
    assert q.provider == "kotak"
    assert q.data_state == "LIVE"


def test_kotak_historical_data(monkeypatch):
    broker = KotakNeoAPI(ucc="KOTAK001")
    broker._session_token = "valid_token"
    broker._token_saved_at = datetime.now().timestamp()

    def mock_get(url, *args, **kwargs):
        if "apim/charts" in url:
            return _MockResponse(
                200,
                {
                    "data": [
                        [1714000000, 2900.0, 2950.0, 2880.0, 2940.0, 150000],
                        [1714086400, 2945.0, 2990.0, 2930.0, 2980.0, 220000],
                    ]
                },
            )
        return _MockResponse(404, {})

    monkeypatch.setattr("httpx.Client.get", lambda self, url, *a, **kw: mock_get(url, *a, **kw))

    candles = broker.get_historical_data("RELIANCE", exchange="NSE", interval="day")
    assert len(candles) == 2
    assert candles[0]["open"] == 2900.0
    assert candles[0]["high"] == 2950.0
    assert candles[0]["close"] == 2940.0
    assert candles[0]["volume"] == 150000
    assert isinstance(candles[0]["date"], datetime)


def test_kotak_order_placement(monkeypatch):
    broker = KotakNeoAPI(ucc="KOTAK001")
    broker._session_token = "valid_token"
    broker._token_saved_at = datetime.now().timestamp()

    def mock_post(url, *args, **kwargs):
        if "apim/orders/1.0/orders" in url:
            return _MockResponse(200, {"data": {"orderId": "KOTAK-ORD-98765"}})
        return _MockResponse(404, {})

    monkeypatch.setattr("httpx.Client.post", lambda self, url, *a, **kw: mock_post(url, *a, **kw))

    req = OrderRequest(
        symbol="RELIANCE",
        exchange="NSE",
        transaction_type="BUY",
        quantity=10,
        order_type="LIMIT",
        product="CNC",
        price=2950.0,
    )
    resp = broker.place_order(req)
    assert resp.order_id == "KOTAK-ORD-98765"
    assert resp.status == "OPEN"


def test_kotak_websocket_tick_cache():
    kotak_ws.stop()
    tick = KotakTick(
        symbol="NSE:NIFTY 50",
        ltp=22550.75,
        open=22400.0,
        high=22600.0,
        low=22380.0,
        close=22450.0,
        volume=12000000,
        change=100.75,
        change_pct=0.45,
    )
    kotak_ws.update_tick(tick)

    retrieved = kotak_ws.get_tick("NSE:NIFTY 50")
    assert retrieved is not None
    assert retrieved.ltp == 22550.75
    assert retrieved.change == 100.75

    # Check symbol-only lookup
    retrieved_symbol = kotak_ws.get_tick("NIFTY 50")
    assert retrieved_symbol is not None
    assert retrieved_symbol.ltp == 22550.75


def test_quotes_ws_integration_with_kotak(monkeypatch):
    from market.quotes import _ws_quotes

    monkeypatch.setattr("market.quotes.get_data_broker_key", lambda: "kotak")

    tick = KotakTick(
        symbol="NSE:RELIANCE",
        ltp=2999.0,
        open=2950.0,
        high=3010.0,
        low=2940.0,
        close=2945.0,
        volume=3500000,
        change=54.0,
        change_pct=1.83,
    )
    kotak_ws.update_tick(tick)

    quotes = _ws_quotes(["NSE:RELIANCE"], correlation_id="test-corr-123")
    assert "NSE:RELIANCE" in quotes
    q = quotes["NSE:RELIANCE"]
    assert q.last_price == 2999.0
    assert q.provider == "kotak"
    assert q.source == "STREAM"
