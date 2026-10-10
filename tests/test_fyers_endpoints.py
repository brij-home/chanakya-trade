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


def test_fyers_attach_position_legs_endpoint(client):
    mock_broker = MagicMock()
    mock_broker.attach_position_legs.return_value = {"s": "ok", "message": "Legs attached"}

    with patch("brokers.session.get_execution_broker", return_value=mock_broker):
        res = client.post(
            "/api/fyers/positions/attach-legs",
            json={
                "position_id": "NSE:SBIN-EQ-INTRADAY",
                "take_profit": 15.0,
                "stop_loss": 5.0,
                "leg_type": 1,
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        mock_broker.attach_position_legs.assert_called_once_with(
            position_id="NSE:SBIN-EQ-INTRADAY",
            take_profit=15.0,
            stop_loss=5.0,
            leg_type=1,
            qty=None,
        )


def test_fyers_convert_position_endpoint(client):
    mock_broker = MagicMock()
    mock_broker.convert_position.return_value = {"s": "ok", "message": "Position converted"}

    with patch("brokers.session.get_execution_broker", return_value=mock_broker):
        res = client.post(
            "/api/fyers/positions/convert",
            json={
                "symbol": "NSE:SBIN-EQ",
                "position_side": 1,
                "convert_qty": 25,
                "convert_from": "INTRADAY",
                "convert_to": "MARGIN",
            },
        )
        assert res.status_code == 200
        assert res.json()["status"] == "ok"
        mock_broker.convert_position.assert_called_once_with(
            symbol="NSE:SBIN-EQ",
            position_side=1,
            convert_qty=25,
            convert_from="INTRADAY",
            convert_to="MARGIN",
        )


def test_fyers_smart_orders_and_smartexit_endpoints(client):
    mock_broker = MagicMock()
    mock_broker.create_smart_order_limit.return_value = {"s": "ok", "id": "SMART-L-1"}
    mock_broker.create_smart_order_step.return_value = {"s": "ok", "id": "SMART-S-1"}
    mock_broker.create_smartexit_trigger.return_value = {"s": "ok", "id": "FLOW-1"}
    mock_broker.get_smartexit_triggers.return_value = [{"flowId": "FLOW-1", "name": "ProfitGuard"}]

    with patch("brokers.session.get_execution_broker", return_value=mock_broker):
        # 1. Smart limit
        r_lim = client.post(
            "/api/fyers/smart-orders/limit",
            json={"symbol": "RELIANCE", "qty": 10, "side": 1, "limit_price": 2500.0},
        )
        assert r_lim.status_code == 200
        assert r_lim.json()["status"] == "ok"

        # 2. Smart step
        r_step = client.post(
            "/api/fyers/smart-orders/step",
            json={"symbol": "RELIANCE", "qty": 50, "side": 1, "avg_qty": 10, "avg_diff": 2.0},
        )
        assert r_step.status_code == 200
        assert r_step.json()["status"] == "ok"

        # 3. Create smartexit
        r_se_post = client.post(
            "/api/fyers/smart-exit/triggers",
            json={"name": "ProfitGuard", "type": 2, "profit_rate": 5000},
        )
        assert r_se_post.status_code == 200
        assert r_se_post.json()["status"] == "ok"

        # 4. Get smartexit
        r_se_get = client.get("/api/fyers/smart-exit/triggers")
        assert r_se_get.status_code == 200
        assert len(r_se_get.json()["triggers"]) == 1


def test_fyers_skills_screeners_endpoints(client):
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
        # 1. Technical screener skill
        r_tech = client.post("/skills/fyers_technical_screener", json={"screener": "cs004"})
        assert r_tech.status_code == 200
        assert r_tech.json()["status"] == "ok"
        assert r_tech.json()["data"]["screener"] == "cs004"

        # 2. Candlestick screener skill
        r_candle = client.post("/skills/fyers_candlestick_screener", json={"pattern": "hammer"})
        assert r_candle.status_code == 200
        assert r_candle.json()["status"] == "ok"
        assert r_candle.json()["data"]["pattern"] == "hammer"


def test_fyers_audit_and_accounting_endpoints(client):
    mock_broker = MagicMock()
    mock_broker.get_charges_history.return_value = {"s": "ok", "charges": [{"brokerage": 20.0}]}
    mock_broker.get_realised_pnl_history.return_value = {"s": "ok", "realised_pnl": 1500.0}
    mock_broker.get_tax_pnl_history.return_value = {"s": "ok", "tax_pnl": {"stt": 12.5}}
    mock_broker.get_ledger_history.return_value = {"s": "ok", "ledger": [{"balance": 50000.0}]}

    with patch("brokers.session.get_execution_broker", return_value=mock_broker):
        # 1. Charges
        r_charges = client.get("/api/fyers/charges?from_date=2026-01-01&to_date=2026-03-31")
        assert r_charges.status_code == 200
        assert r_charges.json()["status"] == "ok"
        assert r_charges.json()["data"]["charges"][0]["brokerage"] == 20.0

        # 2. Realised P&L
        r_realised = client.get("/api/fyers/realised-pnl")
        assert r_realised.status_code == 200
        assert r_realised.json()["status"] == "ok"
        assert r_realised.json()["data"]["realised_pnl"] == 1500.0

        # 3. Tax P&L
        r_tax = client.get("/api/fyers/tax-pnl")
        assert r_tax.status_code == 200
        assert r_tax.json()["status"] == "ok"
        assert r_tax.json()["data"]["tax_pnl"]["stt"] == 12.5

        # 4. Ledger
        r_ledger = client.get("/api/fyers/ledger")
        assert r_ledger.status_code == 200
        assert r_ledger.json()["status"] == "ok"
        assert r_ledger.json()["data"]["ledger"][0]["balance"] == 50000.0


def test_fyers_postback_webhook_endpoint(client):
    with patch("web.sse.event_bus.publish_sync") as mock_pub:
        # 1. /api/fyers/postback
        r1 = client.post(
            "/api/fyers/postback",
            json={
                "order": {
                    "id": "241010000123",
                    "status": 2,
                    "symbol": "NSE:SBIN-EQ",
                    "qty": 50,
                }
            },
        )
        assert r1.status_code == 200
        assert r1.json()["status"] == "ok"
        mock_pub.assert_called_with(
            "orders",
            {
                "source": "fyers_webhook_postback",
                "order_id": "241010000123",
                "status": 2,
                "symbol": "NSE:SBIN-EQ",
                "raw": {
                    "order": {
                        "id": "241010000123",
                        "status": 2,
                        "symbol": "NSE:SBIN-EQ",
                        "qty": 50,
                    }
                },
            },
        )

        # 2. /fyers/postback fallback alias
        r2 = client.post(
            "/fyers/postback",
            json={"id": "241010000456", "status": 1, "symbol": "NSE:NIFTY24OCTFUT"},
        )
        assert r2.status_code == 200
        assert r2.json()["status"] == "ok"


def test_fyers_api_direct_methods():
    from brokers.fyers import FyersAPI

    fyers_api = FyersAPI(app_id="TEST-100", secret_key="test_secret")
    fyers_api._access_token = "mock_token"

    mock_fyers_model = MagicMock()
    mock_fyers_model.attach_position_legs.return_value = {"s": "ok", "message": "Legs attached"}
    mock_fyers_model.convert_position.return_value = {"s": "ok", "message": "Position converted"}
    mock_fyers_model.create_smart_order_limit.return_value = {"s": "ok", "id": "SMART-1"}
    mock_fyers_model.create_smart_order_step.return_value = {"s": "ok", "id": "STEP-1"}
    mock_fyers_model.create_smartexit_trigger.return_value = {"s": "ok", "id": "EXIT-1"}
    mock_fyers_model.get_smartexit_triggers.return_value = {"data": [{"flowId": "EXIT-1"}]}
    mock_fyers_model.charges_history.return_value = {"s": "ok", "data": []}
    mock_fyers_model.realised_profit_history.return_value = {"s": "ok", "data": []}
    mock_fyers_model.tax_pnl_history.return_value = {"s": "ok", "data": []}
    mock_fyers_model.ledger_history.return_value = {"s": "ok", "data": []}

    fyers_api._fyers = mock_fyers_model

    # 1. attach_position_legs
    res_legs = fyers_api.attach_position_legs(
        "NSE:SBIN-EQ-INTRADAY", take_profit=10.0, stop_loss=5.0
    )
    assert res_legs["s"] == "ok"
    mock_fyers_model.attach_position_legs.assert_called_once_with(
        {
            "positionId": "NSE:SBIN-EQ-INTRADAY",
            "legType": 1,
            "takeProfit": 10.0,
            "stopLoss": 5.0,
        }
    )

    # 2. convert_position
    res_conv = fyers_api.convert_position("SBIN", 1, 10, "INTRADAY", "MARGIN")
    assert res_conv["s"] == "ok"
    mock_fyers_model.convert_position.assert_called_once_with(
        {
            "symbol": "NSE:SBIN-EQ",
            "positionSide": 1,
            "convertQty": 10,
            "convertFrom": "INTRADAY",
            "convertTo": "MARGIN",
        }
    )

    # 3. create_smart_order_limit
    res_sol = fyers_api.create_smart_order_limit("RELIANCE", 10, 1, 2500.0, end_time=1700000000)
    assert res_sol["s"] == "ok"

    # 4. create_smart_order_step
    res_step = fyers_api.create_smart_order_step(
        "TCS", 50, 1, 10, 2.0, start_time=1700000000, end_time=1700010000
    )
    assert res_step["s"] == "ok"

    # 5. smartexit
    res_se = fyers_api.create_smartexit_trigger("AutoGuard", 2, profit_rate=5000.0)
    assert res_se["s"] == "ok"
    triggers = fyers_api.get_smartexit_triggers()
    assert len(triggers) == 1

    # 6. audit & accounting
    assert fyers_api.get_charges_history()["s"] == "ok"
    assert fyers_api.get_realised_pnl_history()["s"] == "ok"
    assert fyers_api.get_tax_pnl_history()["s"] == "ok"
    assert fyers_api.get_ledger_history()["s"] == "ok"
