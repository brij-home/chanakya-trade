"""
tests/test_risk_limits_central_order_path.py
─────────────────────────────────────────────
Regression tests for RISK-01, RISK-02, RISK-04, RISK-13 and TASK P2-A/P2-B:
  - Giant notional orders (e.g. ₹10 Crore) are rejected at preview_order_intent.
  - Hitting daily loss cap blocks execute_order_intent with PermissionError.
  - Tilt / consecutive losses blocks execute_order_intent with PermissionError.
  - remaining_loss_room has positive sign while loss is within room.
"""

import pytest
from engine.order_lifecycle import (
    preview_order_intent,
    confirm_order_intent,
    execute_order_intent,
)
from engine.risk_limits import risk_limits


@pytest.fixture(autouse=True)
def clean_risk_db(tmp_path, monkeypatch):
    db_file = tmp_path / "risk_test.db"
    monkeypatch.setenv("RISK_DB_PATH", str(db_file))
    orders_db = tmp_path / "orders_test.db"
    monkeypatch.setattr("engine.order_lifecycle._get_db_path", lambda: orders_db)
    risk_limits._db = db_file
    risk_limits._init_db()
    risk_limits.reset_all()


def test_giant_notional_order_rejected_at_preview(monkeypatch):
    """An order exceeding MAX_ORDER_NOTIONAL (e.g. ₹10 Crore) must be rejected at preview."""
    monkeypatch.setenv("MAX_ORDER_NOTIONAL", "2500000.0")  # 25 Lakh limit

    with pytest.raises(ValueError, match="Order notional.*exceeds institutional threshold"):
        preview_order_intent(
            symbol="RELIANCE",
            side="BUY",
            quantity=40_000,
            price=2500.0,  # 10 Crore notional
        )


def test_daily_loss_cap_blocks_execution(monkeypatch):
    """When daily loss limit is reached, execute_order_intent must block."""
    monkeypatch.setenv("MAX_DAILY_LOSS", "10000.0")  # 10k daily loss cap

    # 1. Create and confirm order BEFORE loss occurs
    order = preview_order_intent(
        symbol="INFY",
        side="BUY",
        quantity=5,
        price=1500.0,
        idempotency_key="IDEMP-LOSS-CAP-1",
    )
    confirm_order_intent(order.order_id, preview_hash=order.preview_hash)

    # 2. Record 15k loss in daily_trades, breaching the 10k daily loss cap
    risk_limits.record_trade("INFY", "BUY", 10, 1500.0, pnl=-15000.0)

    # 3. Attempt execution -> must be blocked with PermissionError
    with pytest.raises(PermissionError, match="violates risk limits"):
        execute_order_intent(order.order_id)


def test_consecutive_losses_tilt_lockout_blocks_execution(monkeypatch):
    """When consecutive losses reach MAX_CONSECUTIVE_LOSSES (default 3), execution must block."""
    monkeypatch.setenv("MAX_CONSECUTIVE_LOSSES", "3")
    monkeypatch.setenv("MAX_DAILY_LOSS", "100000.0")

    # 1. Create and confirm order BEFORE streak occurs
    order = preview_order_intent(
        symbol="TCS",
        side="BUY",
        quantity=1,
        price=3500.0,
        idempotency_key="IDEMP-TILT-1",
    )
    confirm_order_intent(order.order_id, preview_hash=order.preview_hash)

    # 2. Record 3 consecutive losses
    risk_limits.record_trade("TCS", "BUY", 1, 3500.0, pnl=-100.0)
    risk_limits.record_trade("TCS", "BUY", 1, 3500.0, pnl=-150.0)
    risk_limits.record_trade("TCS", "BUY", 1, 3500.0, pnl=-200.0)

    # 3. Attempt execution -> must be blocked by tilt lockout
    with pytest.raises(PermissionError, match="Tilt & revenge trading alert"):
        execute_order_intent(order.order_id)


def test_remaining_loss_room_sign_is_positive(monkeypatch):
    """remaining_loss_room must be positive when within the loss room (RISK-13 fix)."""
    monkeypatch.setenv("MAX_DAILY_LOSS", "20000.0")

    # Record 5k loss
    risk_limits.record_trade("SBIN", "BUY", 10, 600.0, pnl=-5000.0)

    status = risk_limits.get_status()
    assert status["daily_loss"] == -5000.0
    # Room remaining must be +15000, NOT negative -15000
    assert status["remaining_loss_room"] == 15000.0
    assert status["limits_hit"] is False
