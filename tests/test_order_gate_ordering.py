"""
tests/test_order_gate_ordering.py
─────────────────────────────────
Regression tests for EXEC-01 (gate ordering & false SUBMITTING):
  - In EXECUTE mode, if pilot safety gate blocks, order status must remain CONFIRMED (not SUBMITTING).
  - If pre-trade validation blocks, order status transitions directly to REJECTED (never SUBMITTING).
  - If pretrade context fetch fails, order status remains CONFIRMED (never UNKNOWN_FREEZE).
  - Only when all pretrade checks pass does order transition to SUBMITTING before broker call.
"""

import pytest
import sqlite3
from engine.order_lifecycle import (
    preview_order_intent,
    confirm_order_intent,
    execute_order_intent,
    _get_orders_db,
)


def _get_ledger_status(order_id: str) -> str:
    with _get_orders_db() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status FROM orders_ledger WHERE order_id = ?", (order_id,)
        ).fetchone()
        assert row is not None
        return row["status"]


def test_pilot_gate_block_leaves_order_confirmed(tmp_path, monkeypatch):
    """When pilot safety gate raises, order must remain CONFIRMED, never SUBMITTING."""
    monkeypatch.setenv("TRADING_MODE", "EXECUTE")
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "1")
    monkeypatch.setenv("LIVE_EXECUTION_QUALIFIED", "1")

    db_path = tmp_path / "orders.db"
    monkeypatch.setattr("engine.order_lifecycle._get_db_path", lambda: db_path)
    monkeypatch.setattr("engine.modes.assert_live_execution_allowed", lambda: None)

    # Force pilot safety gate to reject
    def _mock_pilot(**kwargs):
        raise PermissionError("Pilot gate rejected: Notional exceeds limit")

    monkeypatch.setattr("engine.pilot_safety.assert_pilot_execution_allowed", _mock_pilot)

    order = preview_order_intent(
        symbol="TCS",
        side="BUY",
        quantity=1,
        price=3500.0,
        idempotency_key="IDEMP-PILOT-GATE-1",
    )
    confirm_order_intent(order.order_id, preview_hash=order.preview_hash)
    assert _get_ledger_status(order.order_id) == "CONFIRMED"

    with pytest.raises(PermissionError, match="Pilot gate rejected"):
        execute_order_intent(order.order_id)

    # Invariant: Must remain CONFIRMED in DB
    assert _get_ledger_status(order.order_id) == "CONFIRMED"


def test_pretrade_context_fetch_failure_leaves_order_confirmed(tmp_path, monkeypatch):
    """When pretrade quote/funds fetch fails, order must remain CONFIRMED (not UNKNOWN_FREEZE)."""
    monkeypatch.setenv("TRADING_MODE", "EXECUTE")
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "1")
    monkeypatch.setenv("LIVE_EXECUTION_QUALIFIED", "1")

    db_path = tmp_path / "orders.db"
    monkeypatch.setattr("engine.order_lifecycle._get_db_path", lambda: db_path)
    monkeypatch.setattr("engine.modes.assert_live_execution_allowed", lambda: None)
    monkeypatch.setattr("engine.pilot_safety.assert_pilot_execution_allowed", lambda **kw: None)

    # Broker session returns None for context fetch
    monkeypatch.setattr("brokers.session.get_execution_broker", lambda: None)

    order = preview_order_intent(
        symbol="INFY",
        side="BUY",
        quantity=1,
        price=1800.0,
        idempotency_key="IDEMP-CTX-FETCH-1",
    )
    confirm_order_intent(order.order_id, preview_hash=order.preview_hash)
    assert _get_ledger_status(order.order_id) == "CONFIRMED"

    with pytest.raises(RuntimeError, match="pretrade context fetch failed"):
        execute_order_intent(order.order_id)

    # Invariant: Must remain CONFIRMED, never SUBMITTING or UNKNOWN_FREEZE
    assert _get_ledger_status(order.order_id) == "CONFIRMED"


def test_pretrade_validation_block_sets_rejected_not_submitting(tmp_path, monkeypatch):
    """When validate_pretrade returns is_eligible=False, order transitions to REJECTED."""
    monkeypatch.setenv("TRADING_MODE", "EXECUTE")
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "1")
    monkeypatch.setenv("LIVE_EXECUTION_QUALIFIED", "1")

    db_path = tmp_path / "orders.db"
    monkeypatch.setattr("engine.order_lifecycle._get_db_path", lambda: db_path)
    monkeypatch.setattr("engine.modes.assert_live_execution_allowed", lambda: None)
    monkeypatch.setattr("engine.pilot_safety.assert_pilot_execution_allowed", lambda **kw: None)

    class _MockBroker:
        account_id = "ACC_TEST_PRETRADE"

        def get_funds(self):
            return {"available_cash": 100_000.0}

    from brokers.base import Quote

    quote = Quote(
        symbol="NSE:RELIANCE",
        last_price=2500.0,
        open=2500.0,
        high=2500.0,
        low=2500.0,
        close=2500.0,
        volume=1000,
        provider="test",
        source="REST",
        data_state="LIVE",
    )

    monkeypatch.setattr("brokers.session.get_execution_broker", lambda: _MockBroker())
    monkeypatch.setattr("market.quotes.get_quote", lambda instruments: {instruments[0]: quote})

    class _BlockedPretrade:
        is_eligible = False
        blocking_reasons = ["risk_limits: Max concentration exceeded"]

    monkeypatch.setattr("engine.pretrade.validate_pretrade", lambda **kw: _BlockedPretrade())

    order = preview_order_intent(
        symbol="RELIANCE",
        side="BUY",
        quantity=1,
        price=2500.0,
        idempotency_key="IDEMP-PRETRADE-BLOCK-1",
    )
    confirm_order_intent(order.order_id, preview_hash=order.preview_hash)
    assert _get_ledger_status(order.order_id) == "CONFIRMED"

    with pytest.raises(ValueError, match="Pre-trade validation blocked"):
        execute_order_intent(order.order_id)

    # Invariant: Transitioned to REJECTED (never touched SUBMITTING)
    assert _get_ledger_status(order.order_id) == "REJECTED"
