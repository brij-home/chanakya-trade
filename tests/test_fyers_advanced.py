"""
tests/test_fyers_advanced.py
────────────────────────────
Deterministic unit tests for advanced Fyers API v3 institutional capabilities:
  1. GTT Order Management (Single-leg & OCO triggers)
  2. Smart Trailing Stop-Loss Order creation
  3. Emergency Panic Square-Off (exit_all_positions)
  4. Server-Side Technical Screeners & Tradebook Audit
  5. Real-Time Order & Trade WebSocket Stream (order_ws)
  6. FastAPI Market Data / Fyers Endpoints
"""

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from brokers.fyers import FyersAPI
from market.fyers_order_stream import FyersOrderStreamManager
from web.api import app


@pytest.fixture
def mock_fyers():
    """Create a FyersAPI instance with mocked client."""
    api = FyersAPI(app_id="MOCK-100", secret_key="mock_secret")
    api._fyers = MagicMock()
    api._access_token = "mock_token"
    api._app_id = "MOCK-100"
    return api


def test_place_gtt_order_single(mock_fyers):
    """Verify single-leg GTT order placement."""
    mock_fyers._fyers.place_gtt_order.return_value = {
        "s": "ok",
        "code": 1101,
        "message": "GTT order placed successfully",
        "id": "GTT-12345",
    }

    res = mock_fyers.place_gtt_order(
        symbol="RELIANCE",
        side=1,
        qty=10,
        trigger_price=1200.0,
        limit_price=1202.0,
        product="CNC",
    )

    assert res["s"] == "ok"
    assert res["id"] == "GTT-12345"
    mock_fyers._fyers.place_gtt_order.assert_called_once()
    call_args = mock_fyers._fyers.place_gtt_order.call_args[0][0]
    assert call_args["symbol"] == "NSE:RELIANCE-EQ"
    assert call_args["side"] == 1
    assert call_args["productType"] == "CNC"
    assert call_args["orderInfo"]["leg1"]["qty"] == 10
    assert call_args["orderInfo"]["leg1"]["triggerPrice"] == 1200.0
    assert call_args["orderInfo"]["leg1"]["price"] == 1202.0


def test_get_and_cancel_gtt_orders(mock_fyers):
    """Verify GTT order retrieval and cancellation."""
    mock_fyers._fyers.gtt_orderbook.return_value = {
        "s": "ok",
        "orderBook": [{"id": "GTT-1", "symbol": "NSE:RELIANCE-EQ", "status": "ACTIVE"}],
    }
    mock_fyers._fyers.cancel_gtt_order.return_value = {"s": "ok", "message": "Cancelled"}

    orders = mock_fyers.get_gtt_orders()
    assert isinstance(orders, list)
    assert len(orders) == 1
    assert orders[0]["id"] == "GTT-1"

    cancel_res = mock_fyers.cancel_gtt_order("GTT-1")
    assert cancel_res is True
    mock_fyers._fyers.cancel_gtt_order.assert_called_once_with({"id": "GTT-1"})


def test_create_smart_trailing_order(mock_fyers):
    """Verify Smart Order trailing stop loss setup."""
    mock_fyers._fyers.create_smart_order_trail.return_value = {
        "s": "ok",
        "id": "SMART-777",
    }

    res = mock_fyers.create_smart_trailing_order(
        symbol="TCS",
        qty=25,
        side=1,
        stop_price=3450.0,
        trail_amount=5.0,
        limit_price=3500.0,
        product="INTRADAY",
    )

    assert res["s"] == "ok"
    assert res["id"] == "SMART-777"
    call_args = mock_fyers._fyers.create_smart_order_trail.call_args[0][0]
    assert call_args["symbol"] == "NSE:TCS-EQ"
    assert call_args["qty"] == 25
    assert call_args["side"] == 1
    assert call_args["stopPrice"] == 3450.0
    assert call_args["jump_diff"] == 5.0
    assert call_args["limitPrice"] == 3500.0


def test_exit_all_positions(mock_fyers):
    """Verify panic exit / square off across all positions."""
    mock_fyers._fyers.exit_positions.return_value = {
        "s": "ok",
        "message": "All positions closed successfully",
    }

    res = mock_fyers.exit_all_positions()
    assert res["s"] == "ok"
    mock_fyers._fyers.exit_positions.assert_called_once_with({"exit_all": 1})

    # Segment specific exit
    mock_fyers.exit_all_positions(segment="11")
    mock_fyers._fyers.exit_positions.assert_called_with({"segment": "11"})


def test_fyers_screener_technical(mock_fyers):
    """Verify server-side technical screener querying."""
    mock_fyers._fyers.screeners_technical.return_value = {
        "s": "ok",
        "screener": [{"symbol": "NSE:RELIANCE-EQ", "rsi": 68.4}],
    }

    data = mock_fyers.get_screener_technical("cs004")
    assert data["s"] == "ok"
    mock_fyers._fyers.screeners_technical.assert_called_once_with({"screener": "cs004"})


def test_fyers_trade_history(mock_fyers):
    """Verify retrieval of execution tradebook."""
    mock_fyers._fyers.tradebook.return_value = {
        "s": "ok",
        "tradeBook": [{"tradeNumber": "T-100", "tradePrice": 1200.5, "symbol": "NSE:RELIANCE-EQ"}],
    }

    trades = mock_fyers.get_trade_history()
    assert isinstance(trades, list)
    assert len(trades) == 1
    assert trades[0]["tradeNumber"] == "T-100"


def test_fyers_order_stream_manager():
    """Verify order stream event routing and callback execution."""
    mgr = FyersOrderStreamManager()

    received_orders = []
    received_trades = []

    mgr.on_order(lambda m: received_orders.append(m))
    mgr.on_trade(lambda m: received_trades.append(m))

    mgr._handle_orders({"order_id": "ORD-1", "status": "FILLED"})
    mgr._handle_trades({"trade_id": "TRD-1", "fill_price": 1200.0})

    assert len(received_orders) == 1
    assert received_orders[0]["order_id"] == "ORD-1"
    assert len(received_trades) == 1
    assert received_trades[0]["fill_price"] == 1200.0


def test_api_fyers_routes(mock_fyers):
    """Verify FastAPI routes delegate to Fyers broker methods."""
    client = TestClient(app)

    with (
        patch("brokers.session.get_execution_broker", return_value=mock_fyers),
        patch("brokers.session.get_data_broker", return_value=mock_fyers),
    ):
        # GET /api/fyers/gtt
        mock_fyers._fyers.gtt_orderbook.return_value = {"s": "ok", "orderBook": []}
        resp = client.get("/api/fyers/gtt")
        assert resp.status_code == 200
        assert resp.json().get("status") == "ok"
        assert resp.json().get("orders") == []

        # POST /api/fyers/gtt
        mock_fyers._fyers.place_gtt_order.return_value = {"s": "ok", "id": "GTT-API-1"}
        resp = client.post(
            "/api/fyers/gtt",
            json={
                "symbol": "RELIANCE",
                "side": 1,
                "qty": 10,
                "trigger_price": 1200.0,
                "limit_price": 1201.0,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["response"]["id"] == "GTT-API-1"

        # DELETE /api/fyers/gtt/GTT-API-1
        mock_fyers._fyers.cancel_gtt_order.return_value = {"s": "ok"}
        resp = client.delete("/api/fyers/gtt/GTT-API-1")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["cancelled"] is True

        # POST /api/fyers/panic-exit
        mock_fyers._fyers.exit_positions.return_value = {"s": "ok", "message": "Exited all"}
        resp = client.post("/api/fyers/panic-exit", json={})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # GET /api/fyers/trades
        mock_fyers._fyers.tradebook.return_value = {"s": "ok", "tradeBook": []}
        resp = client.get("/api/fyers/trades")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # GET /api/fyers/screener/cs004
        mock_fyers._fyers.screeners_technical.return_value = {"s": "ok", "screener": []}
        resp = client.get("/api/fyers/screener/cs004")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # POST /api/fyers/multileg
        mock_fyers._fyers.place_multileg_order.return_value = {"s": "ok", "id": "ML-99"}
        resp = client.post(
            "/api/fyers/multileg",
            json={
                "order_type": "2L",
                "legs": [
                    {
                        "symbol": "NSE:NIFTY26OCT25000CE",
                        "qty": 50,
                        "side": 1,
                        "type": 1,
                        "limit_price": 150.0,
                    },
                    {
                        "symbol": "NSE:NIFTY26OCT25500CE",
                        "qty": 50,
                        "side": -1,
                        "type": 1,
                        "limit_price": 50.0,
                    },
                ],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # POST /api/fyers/alerts
        mock_fyers._fyers.create_alert.return_value = {"s": "ok", "id": "ALT-1"}
        resp = client.post(
            "/api/fyers/alerts",
            json={
                "symbol": "RELIANCE",
                "name": "Rel Breakout",
                "target_price": 1250.0,
                "condition": "GT",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # GET /api/fyers/alerts
        mock_fyers._fyers.get_alert.return_value = {"s": "ok", "data": [{"id": "ALT-1"}]}
        resp = client.get("/api/fyers/alerts")
        assert resp.status_code == 200
        assert len(resp.json()["alerts"]) == 1

        # DELETE /api/fyers/alerts/ALT-1
        mock_fyers._fyers.delete_alert.return_value = {"s": "ok"}
        resp = client.delete("/api/fyers/alerts/ALT-1")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

        # GET /api/fyers/sector-heatmap
        with patch.object(
            mock_fyers,
            "get_quote",
            return_value={
                "NSE:NIFTYIT-INDEX": MagicMock(change_pct=1.5, last_price=28000.0, change=400.0),
                "NSE:NIFTYBANK-INDEX": MagicMock(
                    change_pct=-0.5, last_price=54000.0, change=-250.0
                ),
            },
        ):
            resp = client.get("/api/fyers/sector-heatmap")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["leading_sector"] == "IT"
            assert data["advances"] == 1
            assert data["declines"] == 1


def test_fyers_get_historical_data(mock_fyers):
    """Verify historical OHLCV data normalization from Fyers API."""
    mock_fyers._fyers.history.return_value = {
        "s": "ok",
        "candles": [
            [1700000000, 100.0, 105.0, 99.0, 104.0, 50000],
            [1700000300, 104.0, 106.0, 103.0, 105.5, 45000],
        ],
    }

    rows = mock_fyers.get_historical_data("RELIANCE", interval="5minute")
    assert len(rows) == 2
    assert rows[0]["open"] == 100.0
    assert rows[0]["high"] == 105.0
    assert rows[0]["volume"] == 50000
    mock_fyers._fyers.history.assert_called_once()
    payload = mock_fyers._fyers.history.call_args[0][0]
    assert payload["symbol"] == "NSE:RELIANCE-EQ"
    assert payload["resolution"] == "5"


def test_fyers_place_multileg_order(mock_fyers):
    """Verify multi-leg spread execution payload."""
    mock_fyers._fyers.place_multileg_order.return_value = {
        "s": "ok",
        "id": "ML-1234",
    }

    legs = [
        {"symbol": "NSE:NIFTY26OCT25000CE", "qty": 50, "side": 1, "type": 1, "limit_price": 120.0},
        {"symbol": "NSE:NIFTY26OCT25500CE", "qty": 50, "side": -1, "type": 1, "limit_price": 40.0},
    ]

    res = mock_fyers.place_multileg_order("2L", legs, product="MARGIN")
    assert res["s"] == "ok"
    assert res["id"] == "ML-1234"
    call_args = mock_fyers._fyers.place_multileg_order.call_args[0][0]
    assert call_args["orderType"] == "2L"
    assert call_args["productType"] == "MARGIN"
    assert call_args["legs"]["leg1"]["qty"] == 50
    assert call_args["legs"]["leg1"]["side"] == 1
    assert call_args["legs"]["leg2"]["side"] == -1


def test_fyers_server_alerts(mock_fyers):
    """Verify server-side 24x7 alert creation and deletion."""
    mock_fyers._fyers.create_alert.return_value = {"s": "ok", "id": "ALT-9"}
    mock_fyers._fyers.get_alert.return_value = {"s": "ok", "data": [{"id": "ALT-9"}]}
    mock_fyers._fyers.delete_alert.return_value = {"s": "ok"}

    create_res = mock_fyers.create_server_alert("TCS", "TCS Target", 3600.0, condition="GT")
    assert create_res["s"] == "ok"

    alerts = mock_fyers.get_server_alerts()
    assert len(alerts) == 1
    assert alerts[0]["id"] == "ALT-9"

    del_ok = mock_fyers.delete_server_alert("ALT-9")
    assert del_ok is True
