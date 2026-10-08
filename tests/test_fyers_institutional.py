"""
tests/test_fyers_institutional.py
─────────────────────────────────
Deterministic unit tests for institutional Fyers API v3 enhancements:
  1. Multi-segment symbol conversion (Equity, Index, MCX Commodities, NSE Currencies, Options)
  2. Level 2 Market Depth (5 bids/asks, order imbalance, circuit limits, VWAP)
  3. Market status across segments
  4. Options Chain with live Greeks (delta, gamma, theta, vega, iv, PCR)
  5. Expiry resolution via Fyers native expiryData
  6. Basket / Multi-leg order helpers
  7. WebSocket symbol conversion & tick caching
"""

from unittest.mock import MagicMock, patch
import pytest

from brokers.base import OptionsContract, Quote
from brokers.fyers import FyersAPI, _to_fyers_symbol
from market.websocket import _to_ws_symbol, Tick, WebSocketManager


def test_multi_segment_symbol_resolution():
    """Verify symbol mapping across all supported Indian market segments."""
    # Indices
    assert _to_fyers_symbol("NSE:NIFTY 50") == "NSE:NIFTY50-INDEX"
    assert _to_fyers_symbol("NIFTY") == "NSE:NIFTY50-INDEX"
    assert _to_fyers_symbol("BANKNIFTY") == "NSE:NIFTYBANK-INDEX"
    assert _to_fyers_symbol("SENSEX") == "BSE:SENSEX-INDEX"
    assert _to_fyers_symbol("INDIA VIX") == "NSE:INDIAVIX-INDEX"

    # Equities
    assert _to_fyers_symbol("RELIANCE") == "NSE:RELIANCE-EQ"
    assert _to_fyers_symbol("NSE:TCS") == "NSE:TCS-EQ"
    assert _to_fyers_symbol("BSE:INFY") == "BSE:INFY"

    # MCX Commodities
    assert _to_fyers_symbol("MCX:CRUDEOIL").startswith("MCX:CRUDEOIL")
    assert _to_fyers_symbol("GOLD") in ("MCX:GOLD26OCTFUT", "MCX:GOLD26DECFUT")
    assert _to_fyers_symbol("SILVER") in ("MCX:SILVER26DECFUT", "MCX:SILVER27MARFUT")
    assert _to_fyers_symbol("NATURALGAS").startswith("MCX:NATURALGAS")

    # NSE Currencies
    assert _to_fyers_symbol("USDINR").startswith("NSE:USDINR")
    assert _to_fyers_symbol("EURINR").startswith("NSE:EURINR")

    # BSE / BFO Derivatives (SENSEX, BANKEX)
    assert _to_fyers_symbol("BSE:SENSEX26O0872000PE") == "BSE:SENSEX26O0872000PE"
    assert _to_fyers_symbol("SENSEX26O0872000PE") == "BSE:SENSEX26O0872000PE"
    assert _to_fyers_symbol("BANKEX26O0872000CE") == "BSE:BANKEX26O0872000CE"

    # Pass-through for already formatted contracts
    assert _to_fyers_symbol("NSE:NIFTY26OCT25000CE") == "NSE:NIFTY26OCT25000CE"
    assert _to_fyers_symbol("MCX:GOLD26OCTFUT") == "MCX:GOLD26OCTFUT"


def test_ws_symbol_delegation():
    """Verify WebSocket symbol mapping uses institutional converter."""
    assert _to_ws_symbol("GOLD") in ("MCX:GOLD26OCTFUT", "MCX:GOLD26DECFUT")
    assert _to_ws_symbol("USDINR").startswith("NSE:USDINR")
    assert _to_ws_symbol("NSE:NIFTY 50") == "NSE:NIFTY50-INDEX"
    assert _to_ws_symbol("RELIANCE") == "NSE:RELIANCE-EQ"
    assert _to_ws_symbol("BSE:SENSEX26O0872000PE") == "BSE:SENSEX26O0872000PE"


def test_fyers_market_depth():
    """Verify L2 market depth parsing from Fyers depth response."""
    fyers = FyersAPI(app_id="TEST-100", secret_key="dummy")
    mock_sdk = MagicMock()
    mock_sdk.depth.return_value = {
        "s": "ok",
        "d": {
            "NSE:RELIANCE-EQ": {
                "bids": [
                    {"price": 2500.0, "volume": 100, "order": 3},
                    {"price": 2499.5, "volume": 200, "order": 5},
                ],
                "ask": [
                    {"price": 2500.5, "volume": 150, "order": 4},
                    {"price": 2501.0, "volume": 250, "order": 6},
                ],
                "totalbuyqty": 300,
                "totalsellqty": 400,
                "ltp": 2500.25,
                "atp": 2498.50,
                "lower_ckt": 2250.0,
                "upper_ckt": 2750.0,
            }
        },
    }
    fyers._fyers = mock_sdk
    fyers._access_token = "token"

    depth = fyers.get_market_depth("RELIANCE")
    assert depth["status"] == "ok"
    assert depth["symbol"] == "RELIANCE"
    assert depth["fyers_symbol"] == "NSE:RELIANCE-EQ"
    assert depth["ltp"] == 2500.25
    assert depth["atp"] == 2498.50
    assert len(depth["bids"]) == 2
    assert len(depth["asks"]) == 2
    assert depth["total_buy_qty"] == 300
    assert depth["total_sell_qty"] == 400
    assert depth["order_book_imbalance_ratio"] == 0.75
    assert depth["upper_circuit"] == 2750.0
    assert depth["lower_circuit"] == 2250.0


def test_fyers_market_status():
    """Verify market status parsing across segments."""
    fyers = FyersAPI(app_id="TEST-100", secret_key="dummy")
    mock_sdk = MagicMock()
    mock_sdk.market_status.return_value = {
        "s": "ok",
        "marketStatus": [
            {"exchange": "NSE", "segment": "Capital Market", "status": "OPEN"},
            {"exchange": "NSE", "segment": "Futures & Options", "status": "OPEN"},
            {"exchange": "MCX", "segment": "Commodity", "status": "OPEN"},
        ],
    }
    fyers._fyers = mock_sdk
    fyers._access_token = "token"

    status = fyers.get_market_status()
    assert status["status"] == "ok"
    assert len(status["marketStatus"]) == 3
    assert status["marketStatus"][0]["exchange"] == "NSE"


def test_fyers_options_chain_with_greeks():
    """Verify options chain extraction with live Greeks (delta, gamma, theta, vega)."""
    fyers = FyersAPI(app_id="TEST-100", secret_key="dummy")
    mock_sdk = MagicMock()
    mock_sdk.optionchain.return_value = {
        "s": "ok",
        "data": {
            "expiryData": [{"date": "29-10-2026", "expiry": 1793232000}],
            "callOi": 1500000,
            "putOi": 1800000,
            "optionsChain": [
                {
                    "symbol": "NSE:NIFTY26OCT25000CE",
                    "strike_price": 25000,
                    "option_type": "CE",
                    "ltp": 120.5,
                    "oi": 50000,
                    "doi": 5000,
                    "pdoi": 10.0,
                    "volume": 200000,
                    "greeks": {
                        "delta": 0.52,
                        "gamma": 0.0012,
                        "theta": -12.5,
                        "vega": 18.2,
                        "iv": 14.5,
                    },
                },
                {
                    "symbol": "NSE:NIFTY26OCT25000PE",
                    "strike_price": 25000,
                    "option_type": "PE",
                    "ltp": 95.0,
                    "oi": 60000,
                    "doi": -3000,
                    "pdoi": -5.0,
                    "volume": 180000,
                    "greeks": {
                        "delta": -0.48,
                        "gamma": 0.0011,
                        "theta": -11.0,
                        "vega": 17.8,
                        "iv": 14.8,
                    },
                },
            ],
        },
    }
    fyers._fyers = mock_sdk
    fyers._access_token = "token"

    chain = fyers.get_options_chain("NIFTY")
    assert len(chain) == 2

    call = [c for c in chain if c.option_type == "CE"][0]
    assert call.strike == 25000
    assert call.last_price == 120.5
    assert call.delta == 0.52
    assert call.gamma == 0.0012
    assert call.theta == -12.5
    assert call.vega == 18.2
    assert call.iv == 14.5
    assert call.oi == 50000
    assert call.oi_change == 5000
    assert call.pchange_oi == 10.0

    put = [c for c in chain if c.option_type == "PE"][0]
    assert put.delta == -0.48
    assert put.oi_change == -3000


def test_fyers_get_expiries():
    """Verify get_expiries returns sorted ISO date strings."""
    fyers = FyersAPI(app_id="TEST-100", secret_key="dummy")
    mock_sdk = MagicMock()
    mock_sdk.optionchain.return_value = {
        "s": "ok",
        "data": {
            "expiryData": [
                {"date": "29-10-2026", "expiry": 1793232000},
                {"date": "05-11-2026", "expiry": 1793836800},
                {"date": "22-10-2026", "expiry": 1792627200},
            ]
        },
    }
    fyers._fyers = mock_sdk
    fyers._access_token = "token"

    expiries = fyers.get_expiries("NIFTY")
    assert expiries == ["2026-10-22", "2026-10-29", "2026-11-05"]


def test_fyers_modify_order():
    """Verify modify_order dispatches patch call to SDK."""
    fyers = FyersAPI(app_id="TEST-100", secret_key="dummy")
    mock_sdk = MagicMock()
    mock_sdk.modify_order.return_value = {"s": "ok", "id": "24100200001234", "message": "Order modified successfully"}
    fyers._fyers = mock_sdk
    fyers._access_token = "token"

    res = fyers.modify_order(order_id="24100200001234", price=2550.0, qty=100)
    assert res.status == "OPEN"
    assert res.order_id == "24100200001234"
    mock_sdk.modify_order.assert_called_once_with({"id": "24100200001234", "limitPrice": 2550.0, "qty": 100})


def test_fyers_place_multileg_order():
    """Verify place_multileg_order packages legs with canonical symbols."""
    fyers = FyersAPI(app_id="TEST-100", secret_key="dummy")
    mock_sdk = MagicMock()
    mock_sdk.place_multileg_order.return_value = {"s": "ok", "id": "ML-998877", "message": "Spread order placed"}
    fyers._fyers = mock_sdk
    fyers._access_token = "token"

    legs = [
        {"symbol": "NSE:NIFTY26OCT25000CE", "qty": 65, "side": "BUY", "type": "LIMIT", "limitPrice": 120.0},
        {"symbol": "NSE:NIFTY26OCT25200CE", "qty": 65, "side": "SELL", "type": "LIMIT", "limitPrice": 50.0},
    ]
    res = fyers.place_multileg_order(legs=legs, order_type="2L", product_type="MARGIN")
    assert res.status == "SUBMITTED"
    assert res.order_id == "ML-998877"
    mock_sdk.place_multileg_order.assert_called_once()


def test_fyers_gtt_orders():
    """Verify place_gtt_order and cancel_gtt_order payloads."""
    fyers = FyersAPI(app_id="TEST-100", secret_key="dummy")
    mock_sdk = MagicMock()
    mock_sdk.place_gtt_order.return_value = {"s": "ok", "id": "GTT-1001", "message": "GTT order placed"}
    mock_sdk.cancel_gtt_order.return_value = {"s": "ok"}
    mock_sdk.gtt_orderbook.return_value = {"orderBook": [{"id": "GTT-1001", "status": "ACTIVE"}]}
    fyers._fyers = mock_sdk
    fyers._access_token = "token"

    # Place GTT
    gtt_res = fyers.place_gtt_order(symbol="RELIANCE", qty=10, side=1, trigger_price=2450.0, limit_price=2455.0)
    assert gtt_res["id"] == "GTT-1001"

    # Orderbook
    orders = fyers.get_gtt_orders()
    assert len(orders) == 1
    assert orders[0]["id"] == "GTT-1001"

    # Cancel GTT
    assert fyers.cancel_gtt_order("GTT-1001") is True


def test_fyers_order_stream_subscription():
    """Verify FyersOrderStreamManager starts with app_id and subscribes to events."""
    from market.fyers_order_stream import FyersOrderStreamManager

    manager = FyersOrderStreamManager()
    mock_order_ws = MagicMock()

    with patch("fyers_apiv3.FyersWebsocket.order_ws.FyersOrderSocket", return_value=mock_order_ws):
        manager.start(access_token="test_token", app_id="APP-100")
        assert manager._access_token == "APP-100:test_token"

        # Trigger on_connect callback
        manager._handle_connect()
        mock_order_ws.subscribe.assert_called_once_with(data_type="OnOrders,OnTrades,OnPositions,OnGeneral")
        manager.stop()

