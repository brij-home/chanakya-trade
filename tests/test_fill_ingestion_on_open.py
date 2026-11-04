"""
tests/test_fill_ingestion_on_open.py
────────────────────────────────────
Regression tests for EXEC-03 & TASK P1-B:
  - When sync_execution_orders polls the broker and detects a filled order,
    it ingests execution fills into execution_fills and updates filled_quantity,
    average_fill_price, and last_sync_at on orders_ledger.
  - When execute_order_intent receives an OPEN response with executions,
    it calls ingest_broker_executions immediately.
"""

import sqlite3
from datetime import datetime, timezone
from engine.order_lifecycle import (
    preview_order_intent,
    confirm_order_intent,
    sync_execution_orders,
    _get_orders_db,
    set_ledger_cash_baseline,
    get_internal_ledger_snapshot,
)


def test_sync_execution_orders_ingests_fills_and_updates_ledger(tmp_path, monkeypatch):
    """sync_execution_orders must ingest fills into execution_fills and update orders_ledger."""
    db_path = tmp_path / "orders.db"
    monkeypatch.setattr("engine.order_lifecycle._get_db_path", lambda: db_path)

    test_account_id = "ACC_SYNC_TEST_1"
    set_ledger_cash_baseline(test_account_id, 200_000.0, actor="TEST")

    # Insert a confirmed order in EXECUTE mode that was submitted and is OPEN
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
                "ORD-SYNC-001",
                "IDEMP-SYNC-001",
                "INFY",
                "NSE",
                "EQUITY_INTRADAY",
                "BUY",
                10,
                1500.0,
                "LIMIT",
                "MIS",
                "OPEN",
                "EXECUTE",
                "BROKER-ORD-999",
                test_account_id,
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()

    # Mock broker returning order with COMPLETE / FILLED status and authentic execution trades
    class _MockBrokerOrder:
        order_id = "BROKER-ORD-999"
        status = "COMPLETE"
        filled_quantity = 10
        average_price = 1498.5
        trades = [
            {
                "trade_id": "2026110300123456",  # Authentic exchange trade number
                "quantity": 10,
                "price": 1498.5,
                "trade_time": datetime.now(timezone.utc).isoformat(),
            }
        ]

    class _MockBroker:
        def __init__(self, acc):
            self.account_id = acc

        def get_orders(self):
            return [_MockBrokerOrder()]

    mock_b = _MockBroker(test_account_id)
    monkeypatch.setattr("brokers.session.get_execution_broker", lambda: mock_b)
    monkeypatch.setattr("brokers.session.get_execution_broker_key", lambda: "mock_broker")

    res = sync_execution_orders()
    assert res["ledger_orders_updated"] == 1

    # Verify orders_ledger has updated columns
    with _get_orders_db() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM orders_ledger WHERE order_id = 'ORD-SYNC-001'").fetchone()
        assert row["status"] == "FILLED"
        assert row["filled_quantity"] == 10
        assert row["average_fill_price"] == 1498.5
        assert row["last_sync_at"] is not None

        # Verify execution_fills row was persisted
        fills = conn.execute(
            "SELECT * FROM execution_fills WHERE order_id = 'ORD-SYNC-001'"
        ).fetchall()
        assert len(fills) == 1
        assert fills[0]["broker_trade_id"] == "2026110300123456"
        assert fills[0]["quantity"] == 10
        assert fills[0]["fill_price"] == 1498.5

    # Verify internal ledger snapshot reflects the filled position
    snap = get_internal_ledger_snapshot(test_account_id)
    assert snap is not None
    assert snap["status"] == "AVAILABLE"
    assert len(snap["positions"]) == 1
    assert snap["positions"][0]["symbol"] == "INFY"
    assert snap["positions"][0]["quantity"] == 10


def test_execute_order_intent_open_with_fills_ingests_immediately(tmp_path, monkeypatch):
    """execute_order_intent receiving OPEN with authentic fills must ingest immediately."""
    monkeypatch.setenv("TRADING_MODE", "EXECUTE")
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "1")
    monkeypatch.setenv("LIVE_EXECUTION_QUALIFIED", "1")

    db_path = tmp_path / "orders.db"
    monkeypatch.setattr("engine.order_lifecycle._get_db_path", lambda: db_path)
    monkeypatch.setattr("engine.modes.assert_live_execution_allowed", lambda: None)
    monkeypatch.setattr("engine.pilot_safety.assert_pilot_execution_allowed", lambda **kw: None)

    account_id = "ACC_LIVE_OPEN_1"
    set_ledger_cash_baseline(account_id, 300_000.0, actor="TEST")

    class _MockBrokerRes:
        order_id = "BRK-OPEN-PARTIAL-1"
        status = "OPEN"
        filled_quantity = 5
        average_price = 2500.0
        trades = [
            {
                "trade_id": "98765432101",
                "quantity": 5,
                "price": 2500.0,
                "trade_time": datetime.now(timezone.utc).isoformat(),
            }
        ]

    class _MockBroker:
        def __init__(self, acc):
            self.account_id = acc

        def get_funds(self):
            return {"available_cash": 200_000.0}

        def place_order(self, req):
            return _MockBrokerRes()

    from brokers.base import Quote

    quote = Quote(
        symbol="NSE:TCS",
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

    mock_b = _MockBroker(account_id)
    monkeypatch.setattr("brokers.session.get_execution_broker", lambda: mock_b)
    monkeypatch.setattr("market.quotes.get_quote", lambda instruments: {instruments[0]: quote})

    class _PassPretrade:
        is_eligible = True
        blocking_reasons = []

    monkeypatch.setattr("engine.pretrade.validate_pretrade", lambda **kw: _PassPretrade())

    from engine.order_lifecycle import execute_order_intent

    order = preview_order_intent(
        symbol="TCS",
        side="BUY",
        quantity=10,
        price=2500.0,
        idempotency_key="IDEMP-LIVE-OPEN-PARTIAL",
    )
    confirm_order_intent(order.order_id, preview_hash=order.preview_hash)

    # Set account_id on order ledger row
    with _get_orders_db() as conn:
        conn.execute(
            "UPDATE orders_ledger SET account_id = ? WHERE order_id = ?",
            (account_id, order.order_id),
        )
        conn.commit()

    exec_order = execute_order_intent(order.order_id)
    assert exec_order.status == "OPEN"

    # Verify execution_fills contains the 5 shares
    with _get_orders_db() as conn:
        conn.row_factory = sqlite3.Row
        fills = conn.execute(
            "SELECT * FROM execution_fills WHERE order_id = ?", (order.order_id,)
        ).fetchall()
        assert len(fills) == 1
        assert fills[0]["broker_trade_id"] == "98765432101"
        assert fills[0]["quantity"] == 5
