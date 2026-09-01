"""
tests/test_order_lifecycle.py
──────────────────────────────
Tests for P0-B Paper Order Management System (OMS):
  - Order preview generation with statutory Indian charges
  - Idempotency deduplication across duplicate submits
  - Explicit PAPER- order ID prefixing (no fake broker IDs)
  - Execution routing to PaperBroker and state transitions
  - Observe mode mutation rejection
"""

import pytest
from engine.order_lifecycle import preview_order_intent, execute_order_intent


@pytest.fixture(autouse=True)
def clean_order_db(tmp_path, monkeypatch):
    """Use isolated orders.db per test."""
    db_file = tmp_path / "test_orders.db"
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    from config.paths import app_data_path
    monkeypatch.setattr("engine.order_lifecycle._get_db_path", lambda: db_file)
    yield


def test_order_preview_generation_and_charges():
    """Verify preview generates PAPER- ID and statutory charges breakdown."""
    intent = preview_order_intent(
        symbol="TCS",
        side="BUY",
        quantity=10,
        price=3500.0,
        order_type="LIMIT",
        product="MIS",
        segment="EQUITY_INTRADAY",
    )
    assert intent.order_id.startswith("PAPER-")
    assert intent.status == "PREVIEW"
    assert intent.symbol == "TCS"
    assert intent.charges is not None
    assert "total_charges" in intent.charges
    assert intent.charges["notional_turnover"] == 35000.0


def test_order_preview_idempotency():
    """Duplicate requests with same idempotency key return the existing intent without creating duplicate."""
    key = "test-idempotency-key-12345"
    intent1 = preview_order_intent(
        symbol="INFY",
        side="BUY",
        quantity=20,
        price=1800.0,
        idempotency_key=key,
    )
    intent2 = preview_order_intent(
        symbol="INFY",
        side="BUY",
        quantity=20,
        price=1800.0,
        idempotency_key=key,
    )
    assert intent1.order_id == intent2.order_id
    assert intent1.idempotency_key == intent2.idempotency_key


def test_order_execution_paper_flow(monkeypatch):
    """Verify execution transitions to FILLED_PAPER with PAPER-EXEC ID."""
    from engine.modes import ModeInfo, TradingMode
    monkeypatch.setattr(
        "engine.order_lifecycle.get_trading_mode",
        lambda: ModeInfo(mode=TradingMode.SIMULATE, is_observe=False, is_simulate=True, is_execute=False, description="Simulate"),
    )

    intent = preview_order_intent(
        symbol="RELIANCE",
        side="BUY",
        quantity=5,
        price=2800.0,
        order_type="MARKET",
    )

    executed = execute_order_intent(intent.order_id)
    assert executed.order_id == intent.order_id
    assert executed.status == "FILLED_PAPER"
    assert executed.broker_order_id.startswith("PAPER-")


def test_order_execution_blocked_in_observe_mode(monkeypatch):
    """Verify execution is rejected when system is in OBSERVE mode."""
    from engine.modes import ModeInfo, TradingMode
    monkeypatch.setattr(
        "engine.order_lifecycle.get_trading_mode",
        lambda: ModeInfo(mode=TradingMode.OBSERVE, is_observe=True, is_simulate=False, is_execute=False, description="Observe"),
    )

    intent = preview_order_intent(
        symbol="HDFCBANK",
        side="BUY",
        quantity=10,
        price=1600.0,
    )

    executed = execute_order_intent(intent.order_id)
    assert executed.status == "REJECTED"
    assert "OBSERVE" in executed.rejection_reason
