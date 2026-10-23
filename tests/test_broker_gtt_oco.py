"""
tests/test_broker_gtt_oco.py
──────────────────────────────
Comprehensive unit and integration tests for institutional native broker-side
Good-Till-Triggered (GTT) and One-Cancels-Other (OCO) conditional order synchronization.
Verifies disconnect immunity, auto-arming upon entry fill, and price trigger evaluation.
"""

import pytest
from unittest.mock import MagicMock
from brokers.base import GTTLeg, GTTRequest
from engine.paper import PaperBroker
from engine.order_lifecycle import (
    preview_order_intent,
    confirm_order_intent,
    execute_order_intent,
    _get_orders_db,
)


def test_gtt_request_dataclasses():
    """Verify GTTLeg and GTTRequest data structures."""
    leg1 = GTTLeg(price=98.0, trigger_price=98.5, quantity=100)
    leg2 = GTTLeg(price=105.0, trigger_price=105.0, quantity=100)

    req = GTTRequest(
        symbol="TATAMOTORS",
        exchange="NSE",
        transaction_type="SELL",
        trigger_type="OCO",
        product="MIS",
        leg1=leg1,
        leg2=leg2,
    )

    assert req.symbol == "TATAMOTORS"
    assert req.trigger_type == "OCO"
    assert req.leg1.price == 98.0
    assert req.leg2.trigger_price == 105.0


def test_paper_broker_gtt_lifecycle():
    """Verify PaperBroker can place, query, cancel, and evaluate GTT orders."""
    broker = PaperBroker()

    # 1. Place GTT OCO order
    leg_sl = GTTLeg(price=950.0, trigger_price=950.0, quantity=10)
    leg_tgt = GTTLeg(price=1050.0, trigger_price=1050.0, quantity=10)
    req = GTTRequest(
        symbol="INFY",
        exchange="NSE",
        transaction_type="SELL",
        trigger_type="OCO",
        product="MIS",
        leg1=leg_sl,
        leg2=leg_tgt,
    )

    res = broker.place_gtt(req)
    assert res.status == "ACTIVE"
    assert res.gtt_id.startswith("GTT-PAPER-")

    # 2. Query active GTTs
    active_gtts = broker.get_gtts()
    found = [g for g in active_gtts if g["gtt_id"] == res.gtt_id]
    assert len(found) == 1
    assert found[0]["symbol"] == "INFY"
    assert found[0]["trigger_type"] == "OCO"

    # 3. Simulate market ticks - no trigger when within range
    triggered = broker.evaluate_gtts({"INFY": 1000.0})
    assert len(triggered) == 0

    # 4. Simulate market tick hitting Stop Loss
    triggered = broker.evaluate_gtts({"INFY": 945.0})
    assert res.gtt_id in triggered

    # 5. Verify GTT marked TRIGGERED and no longer in active query
    active_now = broker.get_gtts()
    assert not any(g["gtt_id"] == res.gtt_id for g in active_now)


def test_paper_broker_gtt_cancel():
    """Verify cancelling an active GTT in PaperBroker."""
    broker = PaperBroker()
    req = GTTRequest(
        symbol="RELIANCE",
        exchange="NSE",
        transaction_type="SELL",
        trigger_type="SINGLE",
        product="MIS",
        leg1=GTTLeg(price=1200.0, trigger_price=1200.0, quantity=5),
    )
    res = broker.place_gtt(req)
    assert res.status == "ACTIVE"

    cancelled = broker.cancel_gtt(res.gtt_id)
    assert cancelled is True

    # Cannot cancel again
    cancelled_again = broker.cancel_gtt(res.gtt_id)
    assert cancelled_again is False


def test_preview_order_intent_validates_stop_loss_and_target():
    """Verify input validation for stop_loss and target levels."""
    # BUY order with SL >= price must raise ValueError
    with pytest.raises(ValueError, match="strictly below order price"):
        preview_order_intent(
            symbol="SBIN",
            side="BUY",
            quantity=10,
            price=800.0,
            stop_loss=805.0,
        )

    # BUY order with Target <= price must raise ValueError
    with pytest.raises(ValueError, match="strictly above order price"):
        preview_order_intent(
            symbol="SBIN",
            side="BUY",
            quantity=10,
            price=800.0,
            stop_loss=790.0,
            target=795.0,
        )

    # Valid preview with stop_loss and target
    preview = preview_order_intent(
        symbol="SBIN",
        side="BUY",
        quantity=10,
        price=800.0,
        stop_loss=785.0,
        target=830.0,
        auto_gtt_oco=True,
    )
    assert preview.stop_loss == 785.0
    assert preview.target == 830.0
    assert preview.auto_gtt_oco is True


def test_execute_order_intent_auto_arms_gtt_oco_on_fill():
    """Verify that filled order intent automatically arms server-side GTT OCO order."""
    # 1. Preview order with SL and Target
    intent = preview_order_intent(
        symbol="TCS",
        side="BUY",
        quantity=5,
        price=3500.0,
        order_type="MARKET",
        product="MIS",
        stop_loss=3400.0,
        target=3700.0,
        auto_gtt_oco=True,
    )
    assert intent.status == "PREVIEW"

    # 2. Confirm order
    confirmed = confirm_order_intent(intent.order_id, intent.preview_hash)
    assert confirmed.status == "CONFIRMED"

    # 3. Execute order in SIMULATE/PAPER mode
    executed = execute_order_intent(confirmed.order_id)
    assert executed.status == "FILLED_PAPER"
    assert executed.gtt_order_id is not None
    assert executed.gtt_order_id.startswith("GTT-PAPER-")

    # 4. Verify GTT order is persisted in ledger
    with _get_orders_db() as conn:
        row = conn.execute(
            "SELECT gtt_order_id, stop_loss, target, auto_gtt_oco FROM orders_ledger WHERE order_id = ?",
            (executed.order_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == executed.gtt_order_id
        assert row[1] == 3400.0
        assert row[2] == 3700.0
        assert row[3] == 1


def test_fyers_broker_place_gtt_mapping():
    """Verify FyersAPI maps GTTRequest correctly to Fyers API payload."""
    from brokers.fyers import FyersAPI

    broker = FyersAPI()
    mock_sdk = MagicMock()
    mock_sdk.place_gtt_order.return_value = {"s": "ok", "id": "FYERS-GTT-9988"}
    broker._fyers = mock_sdk

    req = GTTRequest(
        symbol="RELIANCE",
        exchange="NSE",
        transaction_type="SELL",
        trigger_type="OCO",
        product="CNC",
        leg1=GTTLeg(price=2900.0, trigger_price=2900.0, quantity=25),
        leg2=GTTLeg(price=3200.0, trigger_price=3200.0, quantity=25),
    )

    res = broker.place_gtt(req)
    assert res.status == "ACTIVE"
    assert res.gtt_id == "FYERS-GTT-9988"

    mock_sdk.place_gtt_order.assert_called_once()
    payload = mock_sdk.place_gtt_order.call_args[0][0]
    assert payload["side"] == -1
    assert payload["productType"] == "CNC"
    assert "leg1" in payload["orderInfo"]
    assert "leg2" in payload["orderInfo"]
    assert payload["orderInfo"]["leg1"]["triggerPrice"] == 2900.0
    assert payload["orderInfo"]["leg2"]["triggerPrice"] == 3200.0


def test_zerodha_broker_place_gtt_mapping():
    """Verify ZerodhaAPI maps GTTRequest correctly to KiteConnect API."""
    from brokers.zerodha import ZerodhaAPI

    broker = ZerodhaAPI(api_key="mock_key", api_secret="mock_secret")
    mock_kite = MagicMock()
    mock_kite.GTT_TYPE_OCO = "two-leg"
    mock_kite.ORDER_TYPE_LIMIT = "LIMIT"
    mock_kite.place_gtt.return_value = {"trigger_id": 123456}
    broker.kite = mock_kite

    req = GTTRequest(
        symbol="INFY",
        exchange="NSE",
        transaction_type="SELL",
        trigger_type="OCO",
        product="MIS",
        leg1=GTTLeg(price=1450.0, trigger_price=1450.0, quantity=50),
        leg2=GTTLeg(price=1600.0, trigger_price=1600.0, quantity=50),
    )

    res = broker.place_gtt(req)
    assert res.status == "ACTIVE"
    assert res.gtt_id == "123456"

    mock_kite.place_gtt.assert_called_once()
    args = mock_kite.place_gtt.call_args[1]
    assert args["trigger_type"] == "two-leg"
    assert args["tradingsymbol"] == "INFY"
    assert len(args["trigger_values"]) == 2
    assert args["trigger_values"] == [1450.0, 1600.0]
    assert len(args["orders"]) == 2


@pytest.mark.anyio
async def test_fastapi_gtt_endpoints():
    """Verify /api/orders/gtt and /api/orders/gtt/{id} FastAPI endpoints."""
    from web.routers.orders_api import api_get_gtts, api_cancel_gtt

    # Query GTTs
    get_res = await api_get_gtts()
    assert get_res["status"] == "ok"
    assert "gtts" in get_res

    # Cancel a mock ID in paper
    del_res = await api_cancel_gtt("GTT-NONEXISTENT")
    assert del_res["status"] == "error"
    assert del_res["cancelled"] is False
