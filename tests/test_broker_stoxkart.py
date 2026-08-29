"""
tests/test_broker_stoxkart.py
─────────────────────────────
Unit tests for Stoxkart broker integration.
"""

import pytest
from unittest.mock import patch, MagicMock
from brokers.stoxkart import StoxkartAPI
from brokers.base import OrderRequest


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


def test_stoxkart_auth_flow():
    broker = StoxkartAPI(api_key="key", api_secret="sec", client_code="C123")
    res = broker.authenticate(api_key="key", api_secret="sec", client_code="C123")
    assert res is True
    assert broker.is_authenticated is True


def test_stoxkart_funds_and_order():
    broker = StoxkartAPI(client_code="STOX789")
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
