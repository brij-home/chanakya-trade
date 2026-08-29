"""
tests/test_order_lifecycle.py
─────────────────────────────
Unit tests for Order Lifecycle State Machine and Idempotency Engine.
"""

from engine.order_lifecycle import preview_order_intent, execute_order_intent


def test_preview_order_intent_and_idempotency():
    order1 = preview_order_intent(
        symbol="TCS",
        side="BUY",
        quantity=10,
        price=4000.0,
        idempotency_key="IDEMP-TEST-12345",
    )
    assert order1.status == "PREVIEW"
    assert order1.charges["total_charges"] > 0
    assert order1.idempotency_key == "IDEMP-TEST-12345"

    # Repeated request with same idempotency key should return the existing order
    order2 = preview_order_intent(
        symbol="TCS",
        side="BUY",
        quantity=10,
        price=4000.0,
        idempotency_key="IDEMP-TEST-12345",
    )
    assert order2.order_id == order1.order_id


def test_execute_order_intent():
    preview = preview_order_intent(
        symbol="INFY",
        side="BUY",
        quantity=5,
        price=1800.0,
    )
    executed = execute_order_intent(order_id=preview.order_id)
    assert executed.status in ("FILLED", "OPEN", "REJECTED")
    assert executed.order_id == preview.order_id
