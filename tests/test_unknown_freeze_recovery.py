"""
tests/test_unknown_freeze_recovery.py
─────────────────────────────────────
Regression tests for EXEC-02, EXEC-27, and TASK P1-C:
  - Recovery worker reconciles UNKNOWN_FREEZE orders when found on broker order book.
  - Recovery worker ingests fills and transitions order to FILLED or OPEN.
  - Submissions stranded in SUBMITTING (>60s) without broker match are frozen (UNKNOWN_FREEZE).
  - has_active_unknown_freeze blocks new live executions on the account until resolved.
"""

import pytest
import sqlite3
from datetime import datetime, timezone, timedelta
from engine.order_lifecycle import (
    _get_orders_db,
    set_ledger_cash_baseline,
    preview_order_intent,
    confirm_order_intent,
    execute_order_intent,
)
from engine.recovery_worker import (
    run_recovery_cycle,
    has_active_unknown_freeze,
)


def test_recovery_worker_reconciles_unknown_freeze_with_broker_id(tmp_path, monkeypatch):
    """When an UNKNOWN_FREEZE order with broker_order_id matches on the broker, it recovers to FILLED."""
    db_path = tmp_path / "orders.db"
    monkeypatch.setattr("engine.order_lifecycle._get_db_path", lambda: db_path)

    account_id = "ACC_REC_001"
    set_ledger_cash_baseline(account_id, 500_000.0, actor="TEST")

    with _get_orders_db() as conn:
        conn.execute(
            """
            INSERT INTO orders_ledger (
                order_id, idempotency_key, symbol, exchange, segment, side,
                quantity, price, order_type, product, status, mode,
                broker_order_id, account_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ORD-FREEZE-1",
                "IDEMP-FREEZE-1",
                "RELIANCE",
                "NSE",
                "EQUITY_INTRADAY",
                "BUY",
                10,
                2400.0,
                "LIMIT",
                "MIS",
                "UNKNOWN_FREEZE",
                "EXECUTE",
                "BRK-REAL-888",
                account_id,
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()

    assert has_active_unknown_freeze(account_id) is True

    class _MockBrokerOrder:
        order_id = "BRK-REAL-888"
        status = "COMPLETE"
        filled_quantity = 10
        average_price = 2400.0
        trades = [
            {
                "trade_id": "20261103998877",
                "quantity": 10,
                "price": 2400.0,
                "trade_time": datetime.now(timezone.utc).isoformat(),
            }
        ]

    class _MockBroker:
        def __init__(self, acc):
            self.account_id = acc

        def get_orders(self):
            return [_MockBrokerOrder()]

    mock_b = _MockBroker(account_id)
    monkeypatch.setattr("brokers.session.get_execution_broker", lambda: mock_b)
    monkeypatch.setattr("brokers.session.get_execution_broker_key", lambda: "mock_broker")

    res = run_recovery_cycle()
    assert res["status"] == "OK"
    assert res["recovered_count"] == 1

    # Verify orders_ledger status is recovered to FILLED
    with _get_orders_db() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM orders_ledger WHERE order_id = 'ORD-FREEZE-1'").fetchone()
        assert row["status"] == "FILLED"
        assert row["filled_quantity"] == 10

    # Invariant: UNKNOWN_FREEZE is now resolved
    assert has_active_unknown_freeze(account_id) is False


def test_recovery_worker_matches_by_client_tag(tmp_path, monkeypatch):
    """When broker_order_id was missing (e.g. timeout during submission), matches by client tag."""
    db_path = tmp_path / "orders.db"
    monkeypatch.setattr("engine.order_lifecycle._get_db_path", lambda: db_path)

    account_id = "ACC_REC_002"
    set_ledger_cash_baseline(account_id, 500_000.0, actor="TEST")

    with _get_orders_db() as conn:
        conn.execute(
            """
            INSERT INTO orders_ledger (
                order_id, idempotency_key, symbol, exchange, segment, side,
                quantity, price, order_type, product, status, mode,
                broker_order_id, account_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ORD-TAG-MATCH-1",
                "IDEMP-TAG-1",
                "SBIN",
                "NSE",
                "EQUITY_INTRADAY",
                "BUY",
                25,
                750.0,
                "LIMIT",
                "MIS",
                "UNKNOWN_FREEZE",
                "EXECUTE",
                None,  # No broker order ID stored
                account_id,
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()

    class _MockBrokerOrderWithTag:
        order_id = "BRK-DISCOVERED-123"
        tag = "ORD-TAG-MATCH-1"
        status = "OPEN"
        filled_quantity = 0
        average_price = 0.0

    class _MockBroker:
        def __init__(self, acc):
            self.account_id = acc

        def get_orders(self):
            return [_MockBrokerOrderWithTag()]

    mock_b = _MockBroker(account_id)
    monkeypatch.setattr("brokers.session.get_execution_broker", lambda: mock_b)
    monkeypatch.setattr("brokers.session.get_execution_broker_key", lambda: "mock_broker")

    res = run_recovery_cycle()
    assert res["status"] == "OK"
    assert res["recovered_count"] == 1

    with _get_orders_db() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM orders_ledger WHERE order_id = 'ORD-TAG-MATCH-1'"
        ).fetchone()
        assert row["status"] == "OPEN"
        assert row["broker_order_id"] == "BRK-DISCOVERED-123"


def test_stale_submitting_order_without_match_freezes(tmp_path, monkeypatch):
    """A SUBMITTING order older than 60s without a broker match transitions to UNKNOWN_FREEZE."""
    db_path = tmp_path / "orders.db"
    monkeypatch.setattr("engine.order_lifecycle._get_db_path", lambda: db_path)

    account_id = "ACC_REC_003"
    from engine.order_lifecycle import _init_orders_db

    _init_orders_db()
    old_time = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()

    with _get_orders_db() as conn:
        conn.execute(
            """
            INSERT INTO orders_ledger (
                order_id, idempotency_key, symbol, exchange, segment, side,
                quantity, price, order_type, product, status, mode,
                broker_order_id, account_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ORD-STUCK-SUBMITTING",
                "IDEMP-STUCK-1",
                "WIPRO",
                "NSE",
                "EQUITY_INTRADAY",
                "BUY",
                10,
                450.0,
                "LIMIT",
                "MIS",
                "SUBMITTING",
                "EXECUTE",
                None,
                account_id,
                old_time,
                old_time,
            ),
        )
        conn.commit()

    class _EmptyBroker:
        def __init__(self, acc):
            self.account_id = acc

        def get_orders(self):
            return []

    mock_b = _EmptyBroker(account_id)
    monkeypatch.setattr("brokers.session.get_execution_broker", lambda: mock_b)
    monkeypatch.setattr("brokers.session.get_execution_broker_key", lambda: "mock_broker")

    res = run_recovery_cycle()
    assert res["status"] == "OK"
    assert res["recovered_count"] == 0

    with _get_orders_db() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM orders_ledger WHERE order_id = 'ORD-STUCK-SUBMITTING'"
        ).fetchone()
        assert row["status"] == "UNKNOWN_FREEZE"
        assert "timed out" in str(row["rejection_reason"])


def test_active_unknown_freeze_blocks_new_live_order(tmp_path, monkeypatch):
    """has_active_unknown_freeze blocks execution of new live orders on that account."""
    monkeypatch.setenv("TRADING_MODE", "EXECUTE")
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "1")
    monkeypatch.setenv("LIVE_EXECUTION_QUALIFIED", "1")

    db_path = tmp_path / "orders.db"
    monkeypatch.setattr("engine.order_lifecycle._get_db_path", lambda: db_path)
    monkeypatch.setattr("engine.modes.assert_live_execution_allowed", lambda: None)
    monkeypatch.setattr("engine.pilot_safety.assert_pilot_execution_allowed", lambda **kw: None)

    account_id = "ACC_REC_BLOCK_004"
    set_ledger_cash_baseline(account_id, 500_000.0, actor="TEST")

    # Insert an UNKNOWN_FREEZE order for this account
    with _get_orders_db() as conn:
        conn.execute(
            """
            INSERT INTO orders_ledger (
                order_id, idempotency_key, symbol, exchange, segment, side,
                quantity, price, order_type, product, status, mode,
                broker_order_id, account_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ORD-EXISTING-FROZEN",
                "IDEMP-EXISTING-FROZEN",
                "ITC",
                "NSE",
                "EQUITY_INTRADAY",
                "BUY",
                10,
                400.0,
                "LIMIT",
                "MIS",
                "UNKNOWN_FREEZE",
                "EXECUTE",
                "BRK-FROZEN-1",
                account_id,
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()

    class _MockBroker:
        def __init__(self, acc):
            self.account_id = acc

        def get_funds(self):
            return {"available_cash": 200_000.0}

    from brokers.base import Quote

    quote = Quote(
        symbol="NSE:INFY",
        last_price=1500.0,
        open=1500.0,
        high=1500.0,
        low=1500.0,
        close=1500.0,
        volume=1000,
        provider="test",
        source="REST",
        data_state="LIVE",
    )

    mock_b = _MockBroker(account_id)
    monkeypatch.setattr("brokers.session.get_execution_broker", lambda: mock_b)
    monkeypatch.setattr("market.quotes.get_quote", lambda instruments: {instruments[0]: quote})

    class _PassPretrade:
        is_eligible = True
        blocking_reasons = []

    monkeypatch.setattr("engine.pretrade.validate_pretrade", lambda **kw: _PassPretrade())

    order = preview_order_intent(
        symbol="INFY",
        side="BUY",
        quantity=5,
        price=1500.0,
        idempotency_key="IDEMP-NEW-ORDER-ATTEMPT",
    )
    confirm_order_intent(order.order_id, preview_hash=order.preview_hash)

    with pytest.raises(PermissionError, match="has active UNKNOWN_FREEZE orders"):
        execute_order_intent(order.order_id)
