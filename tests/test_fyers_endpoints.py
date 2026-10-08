"""
tests/test_fyers_endpoints.py
─────────────────────────────
Deterministic unit tests for Fyers advanced API endpoints.
"""

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from web.api import app


@pytest.fixture
def client():
    return TestClient(app)


def test_fyers_gtt_endpoints(client):
    mock_broker = MagicMock()
    mock_broker.get_gtt_orders.return_value = [
        {"id": "GTT-101", "symbol": "NSE:RELIANCE-EQ", "status": "ACTIVE"}
    ]
    mock_broker.place_gtt_order.return_value = {
        "s": "ok",
        "id": "GTT-102",
        "message": "GTT order placed",
    }
    mock_broker.cancel_gtt_order.return_value = True

    with patch("brokers.session.get_execution_broker", return_value=mock_broker):
        # 1. GET GTT
        res = client.get("/api/fyers/gtt")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert len(data["orders"]) == 1
        assert data["orders"][0]["id"] == "GTT-101"

        # 2. POST GTT
        res_post = client.post(
            "/api/fyers/gtt",
            json={
                "symbol": "RELIANCE",
                "qty": 10,
                "side": "BUY",
                "trigger_price": 2500.0,
                "limit_price": 2505.0,
            },
        )
        assert res_post.status_code == 200
        assert res_post.json()["id"] == "GTT-102"

        # 3. DELETE GTT
        res_del = client.delete("/api/fyers/gtt/GTT-102")
        assert res_del.status_code == 200
        assert res_del.json()["cancelled"] is True


def test_fyers_exit_all_endpoint(client):
    mock_broker = MagicMock()
    mock_broker.exit_all_positions.return_value = {"s": "ok", "message": "Positions squared off"}

    with patch("brokers.session.get_execution_broker", return_value=mock_broker):
        res = client.post("/api/fyers/exit-all", json={"segment": "EQUITY"})
        assert res.status_code == 200
        assert res.json()["s"] == "ok"
        mock_broker.exit_all_positions.assert_called_once_with(segment="EQUITY")


def test_fyers_screeners_endpoints(client):
    mock_broker = MagicMock()
    mock_broker.get_screener_technical.return_value = {
        "s": "ok",
        "screener": "cs004",
        "data": [{"symbol": "TCS"}],
    }
    mock_broker.get_screener_candlestick.return_value = {
        "s": "ok",
        "pattern": "hammer",
        "data": [{"symbol": "INFY"}],
    }

    with patch("brokers.session.get_data_broker", return_value=mock_broker):
        res_tech = client.get("/api/fyers/screeners/technical?screener=cs004")
        assert res_tech.status_code == 200
        assert res_tech.json()["s"] == "ok"

        res_candle = client.get("/api/fyers/screeners/candlestick?pattern=hammer")
        assert res_candle.status_code == 200
        assert res_candle.json()["s"] == "ok"


def test_fyers_patch_order_endpoint(client):
    from brokers.base import OrderResponse

    mock_broker = MagicMock()
    mock_broker.modify_order.return_value = OrderResponse(
        order_id="ORD-101", status="OPEN", message="Modified"
    )

    with patch("brokers.session.get_execution_broker", return_value=mock_broker):
        res = client.patch("/api/fyers/orders/ORD-101", json={"price": 2550.0, "qty": 50})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["order_id"] == "ORD-101"
        assert data["broker_status"] == "OPEN"
