"""
tests/test_broker_mstock.py
───────────────────────────
Comprehensive unit tests for m.Stock (Mirae Asset) broker integration.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from brokers import mstock
from brokers.base import OrderRequest
from brokers.mstock import MStockAPI


@pytest.fixture(autouse=True)
def isolated_mstock_token_file(tmp_path, monkeypatch):
    """Isolate token persistence to temporary directory during tests."""
    fake_token = tmp_path / "mstock.json"
    monkeypatch.setattr(mstock, "TOKEN_FILE", fake_token)
    return fake_token


def test_mstock_init():
    broker = MStockAPI(
        api_key="mstock_key_123",
        api_secret="mstock_sec_456",
        client_code="M12345",
        password="pass",
        redirect_uri="http://103.149.127.88:8765/mstock/callback",
    )
    assert broker._client_code == "M12345"
    assert broker._api_key == "mstock_key_123"
    assert broker._redirect_uri == "http://103.149.127.88:8765/mstock/callback"
    assert "platform_key=mstock_key_123" in broker.get_login_url()
    assert "redirect_url=http://103.149.127.88:8765/mstock/callback" in broker.get_login_url()


def test_mstock_profile():
    broker = MStockAPI(client_code="M98765")
    profile = broker.get_profile()
    assert profile.user_id == "M98765"
    assert profile.broker == "MSTOCK"


def test_mstock_complete_login_token():
    broker = MStockAPI(client_code="M98765")
    profile = broker.complete_login(token="jwt_token_sample_abc")
    assert broker.is_authenticated() is True
    assert broker._token == "jwt_token_sample_abc"
    assert profile.user_id == "M98765"


def test_mstock_auth_flow():
    broker = MStockAPI(api_key="key", api_secret="sec", client_code="M101", password="pwd")
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {"result": {"token": "dummy_jwt_123"}}
    broker._client.post = MagicMock(return_value=mock_resp)

    res = broker.authenticate(api_key="key", api_secret="sec", client_code="M101")
    assert res is True
    assert broker.is_authenticated() is True
    assert broker._token == "dummy_jwt_123"


def test_mstock_auth_failure_raises():
    broker = MStockAPI(api_key="key", api_secret="sec", client_code="M101")
    broker._client.post = MagicMock(side_effect=OSError("connection refused"))

    assert broker.authenticate() is False
    assert broker.is_authenticated() is False
    with pytest.raises(RuntimeError, match="m.Stock authentication failed"):
        broker.complete_login()


def test_mstock_funds():
    broker = MStockAPI(client_code="M202")
    broker._token = "valid_token"

    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {
        "result": {
            "availableMargin": 250000.0,
            "usedMargin": 50000.0,
            "totalMargin": 300000.0,
        }
    }
    broker._client.get = MagicMock(return_value=mock_resp)

    funds = broker.get_funds()
    assert funds.available_cash == 250000.0
    assert funds.used_margin == 50000.0
    assert funds.total_balance == 300000.0


def test_mstock_holdings_and_positions():
    broker = MStockAPI(client_code="M202")
    broker._token = "valid_token"

    mock_holdings = MagicMock(status_code=200)
    mock_holdings.json.return_value = {
        "result": [
            {
                "symbol": "TCS",
                "exchange": "NSE",
                "quantity": 10,
                "avgPrice": 3500.0,
                "lastPrice": 3600.0,
                "dayChange": 25.0,
            }
        ]
    }

    mock_positions = MagicMock(status_code=200)
    mock_positions.json.return_value = {
        "result": [
            {
                "symbol": "INFY",
                "exchange": "NSE",
                "product": "MIS",
                "quantity": 20,
                "buyAvgPrice": 1500.0,
                "lastPrice": 1520.0,
            }
        ]
    }

    def _mock_get(url, **kwargs):
        if "holdings" in url:
            return mock_holdings
        if "positions" in url:
            return mock_positions
        return MagicMock(status_code=404)

    broker._client.get = MagicMock(side_effect=_mock_get)

    holdings = broker.get_holdings()
    assert len(holdings) == 1
    assert holdings[0].symbol == "TCS"
    assert holdings[0].quantity == 10
    assert holdings[0].pnl == 1000.0

    positions = broker.get_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "INFY"
    assert positions[0].quantity == 20


def test_mstock_quote():
    broker = MStockAPI(client_code="M303")
    broker._token = "valid_token"

    mock_quote = MagicMock(status_code=200)
    mock_quote.json.return_value = {
        "result": {
            "ltp": 2500.0,
            "open": 2480.0,
            "high": 2510.0,
            "low": 2470.0,
            "close": 2475.0,
            "volume": 123456,
        }
    }
    broker._client.get = MagicMock(return_value=mock_quote)

    quote = broker.get_quote("RELIANCE")
    assert quote.symbol == "RELIANCE"
    assert quote.last_price == 2500.0
    assert quote.change == 25.0


def test_mstock_order_live_gate(monkeypatch):
    broker = MStockAPI(client_code="M404")
    broker._token = "valid_token"

    req = OrderRequest(
        symbol="RELIANCE",
        exchange="NSE",
        transaction_type="BUY",
        order_type="LIMIT",
        product="CNC",
        quantity=5,
        price=2500.0,
    )

    # 1. Gate closed: ALLOW_LIVE_TRADING=0
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "0")
    with pytest.raises(PermissionError, match="Live trading disabled"):
        broker.place_order(req)

    # 2. Gate open: ALLOW_LIVE_TRADING=1
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "1")
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {"result": {"orderId": "MSTOCK_ORD_777"}}
    broker._client.post = MagicMock(return_value=mock_resp)

    resp = broker.place_order(req)
    assert resp.status == "PLACED"
    assert resp.order_id == "MSTOCK_ORD_777"


# ── Web API Callback Tests ──────────────────────────────────────────


@pytest.fixture
def web_client():
    with (
        patch.dict(
            os.environ,
            {
                "DEPLOY_MODE": "desktop",
                "AUTH_DB_PATH": str(Path(tempfile.mkdtemp()) / "test.db"),
            },
        ),
        patch("config.credentials.load_all", return_value=None),
        patch("dotenv.load_dotenv", return_value=None),
    ):
        from web.api import app

        yield TestClient(app)


def test_mstock_login_endpoint(web_client):
    def _mock_env(key):
        if key == "MSTOCK_API_KEY":
            return "test_key"
        if key == "MSTOCK_REDIRECT_URL":
            return "http://103.149.127.88:8765/mstock/callback"
        return ""

    with (
        patch("web.api._has_mstock", return_value=True),
        patch("web.api._env", side_effect=_mock_env),
    ):
        resp = web_client.get("/mstock/login", follow_redirects=False)
        assert resp.status_code == 307
        assert "api.mstock.trade" in resp.headers["location"]
        assert "platform_key=test_key" in resp.headers["location"]


def test_mstock_callback_endpoint_success(web_client):
    from brokers.base import Funds, UserProfile

    mock_broker = MagicMock()
    mock_broker.complete_login.return_value = UserProfile(
        user_id="M123", name="Pilot Trader", email="pilot@mstock.in", broker="MSTOCK"
    )
    mock_broker.get_funds.return_value = Funds(
        available_cash=100000.0, used_margin=0.0, total_balance=100000.0
    )

    with (
        patch("brokers.mstock.MStockAPI", return_value=mock_broker),
        patch("brokers.session.register_broker") as mock_reg,
        patch("web.api._invalidate_auth_cache"),
    ):
        resp = web_client.get(
            "/mstock/callback?token=test_jwt_success_token&client_code=M123",
            headers={"Host": "103.149.127.88:8765"},
        )
        assert resp.status_code == 200
        assert "m.Stock connected!" in resp.text
        assert "103.149.127.88:8765/mstock/callback" in resp.text
        mock_broker.complete_login.assert_called_once()
        mock_reg.assert_called_once_with("mstock", mock_broker)


def test_mstock_callback_endpoint_missing_token(web_client):
    resp = web_client.get("/mstock/callback")
    assert resp.status_code == 400
    assert "m.Stock login failed" in resp.text


def test_mstock_in_api_status(web_client):
    with patch("web.api._require_localhost"):
        resp = web_client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "mstock" in data
        assert "configured" in data["mstock"]
        assert "authenticated" in data["mstock"]


def test_mstock_option_chain_master():
    broker = MStockAPI(client_code="M999")
    broker._token = "jwt_test_token"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": True,
        "message": "SUCCESS",
        "data": {
            "dctExp": {"1": 1795876200, "2": 1740000000},
            "OPTIDX": ["NIFTY,26000,1,2", "BANKNIFTY,26009,1,2"],
            "OFSTK": ["ACC,22,1,2"],
            "FUTIDX": ["NIFTY,26000,1,2"],
        },
    }

    with patch.object(broker._client, "get", return_value=mock_resp):
        master = broker.get_option_chain_master(exchange=2)
        assert "dctExp" in master
        assert "OPTIDX" in master
        assert master["dctExp"]["1"] == 1795876200


def test_mstock_options_chain_live():
    broker = MStockAPI(client_code="M999")
    broker._token = "jwt_test_token"

    master_mock = {
        "dctExp": {"1": 1795876200, "2": 1740000000},
        "OPTIDX": ["NIFTY,26000,1,2"],
        "OFSTK": ["ACC,22,1,2"],
    }
    chain_mock = MagicMock()
    chain_mock.status_code = 200
    chain_mock.json.return_value = {
        "status": True,
        "data": {
            "contractModel": {"sym": "NIFTY", "exp": 1795876200},
            "call": ["10001,2400000,5000", "10002,2410000,6000"],
            "put": ["10003,2400000,4500", "10004,2410000,4000"],
        },
    }

    quote_mock = MagicMock()
    quote_mock.status_code = 200
    quote_mock.json.return_value = {
        "status": "true",
        "data": {
            "fetched": [
                {"symbolToken": "10001", "ltp": 150.5},
                {"symbolToken": "10003", "ltp": 120.0},
            ]
        },
    }

    with (
        patch.object(broker, "get_option_chain_master", return_value=master_mock),
        patch.object(broker._client, "get", return_value=chain_mock),
        patch.object(broker._client, "request", return_value=quote_mock),
    ):
        contracts = broker.get_options_chain("NIFTY")
        assert len(contracts) == 4
        calls = [c for c in contracts if c.option_type == "CE"]
        puts = [c for c in contracts if c.option_type == "PE"]
        assert len(calls) == 2
        assert len(puts) == 2
        assert calls[0].strike == 24000.0
        assert calls[0].oi == 5000
        assert calls[0].last_price == 150.5


def test_mstock_calculate_order_margin():
    broker = MStockAPI(client_code="M999")
    broker._token = "jwt_test_token"

    margin_mock = MagicMock()
    margin_mock.status_code = 200
    margin_mock.json.return_value = {
        "status": "true",
        "data": {
            "summary": {
                "total_charges": 15200.0,
                "breakup": [{"name": "SPANMARGIN", "amount": 12000.0}],
            }
        },
    }

    with patch.object(broker._client, "post", return_value=margin_mock):
        res = broker.calculate_order_margin(
            [
                {
                    "exchange": "NSE",
                    "qty": "25",
                    "price": "24000",
                    "productType": "MIS",
                    "token": "26000",
                    "tradeType": "BUY",
                }
            ]
        )
        assert res["summary"]["total_charges"] == 15200.0


def test_mstock_gainers_losers():
    broker = MStockAPI(client_code="M999")
    broker._token = "jwt_test_token"

    gl_mock = MagicMock()
    gl_mock.status_code = 200
    gl_mock.json.return_value = {
        "status": True,
        "data": [
            {"symbol": "INDUSINDBK", "ltp": 732.2, "per_change": 6.19},
            {"symbol": "LT", "ltp": 3259.0, "per_change": 4.59},
        ],
    }

    with patch.object(broker._client, "post", return_value=gl_mock):
        res = broker.get_gainers_losers(type_flag="G")
        assert len(res) == 2
        assert res[0]["symbol"] == "INDUSINDBK"
        assert res[0]["per_change"] == 6.19


def test_mstock_basket_orders():
    broker = MStockAPI(client_code="M999")
    broker._token = "jwt_test_token"

    cb_mock = MagicMock(
        status_code=200,
        json=lambda: {"status": True, "message": "Basket Created Successfully"},
    )
    fb_mock = MagicMock(
        status_code=200,
        json=lambda: {"status": True, "data": [{"BaskName": "TestBasket"}]},
    )
    rb_mock = MagicMock(status_code=200, json=lambda: {"status": True, "message": "Basket Renamed"})
    db_mock = MagicMock(status_code=200, json=lambda: {"status": True, "message": "Basket Deleted"})
    calc_mock = MagicMock(status_code=200, json=lambda: {"status": True, "data": {"margin": 50000}})

    with (
        patch.object(broker._client, "post", side_effect=[cb_mock, db_mock]),
        patch.object(broker._client, "put", return_value=fb_mock),
        patch.object(broker._client, "delete", return_value=rb_mock),
        patch.object(broker._client, "get", return_value=calc_mock),
    ):
        created = broker.create_basket("TestBasket", "Desc")
        assert created.get("status") is True

        baskets = broker.fetch_baskets()
        assert len(baskets) == 1
        assert baskets[0]["BaskName"] == "TestBasket"

        renamed = broker.rename_basket("TestBasket", "NewBasket")
        assert renamed.get("status") is True

        deleted = broker.delete_basket("NewBasket")
        assert deleted.get("status") is True

        calc = broker.calculate_basket("TestBasket")
        assert calc.get("data", {}).get("margin") == 50000


def test_mstock_modify_order(monkeypatch):
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "1")
    broker = MStockAPI(client_code="M999")
    broker._token = "jwt_test_token"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": True, "data": {"orderId": "ORD_123"}}

    with patch.object(broker._client, "put", return_value=mock_resp):
        res = broker.modify_order("ORD_123", quantity=50, price=2500.0)
        assert res.status == "MODIFIED"
        assert res.order_id == "ORD_123"


def test_mstock_convert_position(monkeypatch):
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "1")
    broker = MStockAPI(client_code="M999")
    broker._token = "jwt_test_token"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": True, "message": "Position Converted"}

    with patch.object(broker._client, "post", return_value=mock_resp):
        res = broker.convert_position("NSE", "RELIANCE", "MIS", "CNC", 10)
        assert res.get("status") is True
