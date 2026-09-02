"""
tests/test_broker_stoxkart.py
─────────────────────────────
Unit tests for Stoxkart broker integration.
"""

import pytest

from brokers import stoxkart
from brokers.stoxkart import StoxkartAPI
from brokers.base import OrderRequest


@pytest.fixture(autouse=True)
def isolated_stoxkart_token_file(tmp_path, monkeypatch):
    """Keep mocked authentication from reading or writing a real broker session."""
    monkeypatch.setattr(stoxkart, "TOKEN_FILE", tmp_path / "stoxkart.json")


def test_stoxkart_init():
    broker = StoxkartAPI(
        api_key="test_key",
        api_secret="test_secret",
        client_code="STOX123",
        password="pass",
    )
    assert broker._client_code == "STOX123"
    assert broker._api_key == "test_key"


def test_stoxkart_profile():
    broker = StoxkartAPI(client_code="STOX456")
    profile = broker.get_profile()
    assert profile.user_id == "STOX456"
    assert profile.broker == "STOXKART"


from unittest.mock import MagicMock


def test_stoxkart_auth_flow():
    broker = StoxkartAPI(api_key="key", api_secret="sec", client_code="C123")
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {"result": {"token": "dummy_token"}}
    broker._client.post = MagicMock(return_value=mock_resp)

    res = broker.authenticate(api_key="key", api_secret="sec", client_code="C123")
    assert res is True
    assert broker.is_authenticated is True


def test_stoxkart_auth_failure_never_creates_a_session():
    broker = StoxkartAPI(api_key="key", api_secret="sec", client_code="C123")
    broker._client.post = MagicMock(side_effect=OSError("network unavailable"))

    assert broker.authenticate() is False
    assert broker.is_authenticated is False
    with pytest.raises(RuntimeError, match="no live or simulated broker session"):
        broker.complete_login()


def test_stoxkart_funds_and_order():
    broker = StoxkartAPI(client_code="STOX789")
    mock_post_resp = MagicMock(status_code=200)
    mock_post_resp.json.return_value = {
        "result": {"token": "dummy_token", "orderId": "STOX_ORD_101"}
    }
    mock_get_resp = MagicMock(status_code=200)
    mock_get_resp.json.return_value = {"result": {"availableMargin": 150000.0, "usedMargin": 0.0}}

    broker._client.post = MagicMock(return_value=mock_post_resp)
    broker._client.get = MagicMock(return_value=mock_get_resp)
    broker.authenticate(api_key="k", api_secret="s", client_code="STOX789")

    funds = broker.get_funds()
    assert funds.available_cash > 0

    req = OrderRequest(
        symbol="RELIANCE",
        exchange="NSE",
        transaction_type="BUY",
        order_type="LIMIT",
        product="MIS",
        quantity=10,
        price=2800.0,
    )
    resp = broker.place_order(req)
    assert resp.status == "PLACED"
    assert resp.order_id != ""


def test_stoxkart_order_failure_is_not_reported_as_a_simulated_order():
    broker = StoxkartAPI(client_code="STOX789")
    broker._token = "verified-token"
    broker._client.post = MagicMock(side_effect=OSError("network unavailable"))

    req = OrderRequest(
        symbol="RELIANCE",
        exchange="NSE",
        transaction_type="BUY",
        order_type="LIMIT",
        product="MIS",
        quantity=10,
        price=2800.0,
    )
    with pytest.raises(RuntimeError, match="order submission failed"):
        broker.place_order(req)
