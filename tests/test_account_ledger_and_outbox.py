"""
tests/test_account_ledger_and_outbox.py
───────────────────────────────────────
Verifies:
1. Account-scoped execution fill persistence, monotonic sequencing, and honest
   internal ledger snapshot calculation (R03).
2. Transactional alert outbox persistence, status transitions (PENDING, DISPATCHED,
   ACKNOWLEDGED, FAILED_RETRY), retry budgeting, and channel filtering (R03).
"""

from __future__ import annotations

import pytest

from engine.order_lifecycle import (
    set_ledger_cash_baseline,
    record_execution_fill,
    get_internal_ledger_snapshot,
)
from engine.storage.alert_repository import AlertOutbox


def test_account_ledger_snapshot_and_fill_accounting(tmp_path):
    import uuid

    account_id = f"test-acc-{uuid.uuid4().hex[:8]}"

    # 1. Without baseline, snapshot is strictly None (reconciliation unavailable)
    assert get_internal_ledger_snapshot("uninitialized-acc") is None

    # 2. Establish opening cash baseline
    set_ledger_cash_baseline(account_id, 200000.0, actor="SYSTEM_TEST")

    # Before any fills, cash balance matches opening cash, zero positions
    snap0 = get_internal_ledger_snapshot(account_id)
    assert snap0 is not None
    assert snap0["status"] == "AVAILABLE"
    assert snap0["cash_balance"] == 200000.0
    assert snap0["positions"] == []
    assert snap0["total_fills_count"] == 0

    # 3. Record Buy Fill: Buy 100 shares of RELIANCE @ 2500, charges = 50.0
    # Cost = 250,000 + 50.0. Cash balance: 200,000 - 250,050 = -50,050
    f1 = record_execution_fill(
        account_id=account_id,
        broker_name="FYERS",
        order_id="ord-001",
        broker_order_id="brk-ord-1",
        broker_trade_id="trade-001",
        symbol="RELIANCE",
        exchange="NSE",
        segment="EQUITY_INTRADAY",
        side="BUY",
        quantity=100,
        fill_price=2500.0,
        charges=50.0,
    )
    assert f1["sequence_num"] == 1

    # 4. Record second fill for monotonic sequencing: Buy 50 shares of INFY @ 1800, charges = 25.0
    f2 = record_execution_fill(
        account_id=account_id,
        broker_name="FYERS",
        order_id="ord-002",
        broker_order_id="brk-ord-2",
        broker_trade_id="trade-002",
        symbol="INFY",
        exchange="NSE",
        segment="EQUITY_INTRADAY",
        side="BUY",
        quantity=50,
        fill_price=1800.0,
        charges=25.0,
    )
    assert f2["sequence_num"] == 2

    # Verify ledger snapshot with open positions
    snap1 = get_internal_ledger_snapshot(account_id)
    assert snap1["total_fills_count"] == 2
    sym_map = {p["symbol"]: p for p in snap1["positions"]}
    assert sym_map["RELIANCE"]["quantity"] == 100
    assert sym_map["RELIANCE"]["average_price"] == 2500.0
    assert sym_map["INFY"]["quantity"] == 50
    assert sym_map["INFY"]["average_price"] == 1800.0

    # 5. Sell 100 shares of RELIANCE @ 2600 (full exit), charges = 50.0
    # Proceeds = 260,000 - 50.0
    f3 = record_execution_fill(
        account_id=account_id,
        broker_name="FYERS",
        order_id="ord-003",
        broker_order_id="brk-ord-3",
        broker_trade_id="trade-003",
        symbol="RELIANCE",
        exchange="NSE",
        segment="EQUITY_INTRADAY",
        side="SELL",
        quantity=100,
        fill_price=2600.0,
        charges=50.0,
    )
    assert f3["sequence_num"] == 3

    # Snapshot should show RELIANCE fully closed (not in active positions) and only INFY remaining
    snap2 = get_internal_ledger_snapshot(account_id)
    active_syms = [p["symbol"] for p in snap2["positions"]]
    assert "RELIANCE" not in active_syms
    assert "INFY" in active_syms
    assert snap2["total_fills_count"] == 3

    # 6. Duplicate trade ID must raise IntegrityError
    with pytest.raises(ValueError, match="Conflicting duplicate broker execution retry"):
        record_execution_fill(
            account_id=account_id,
            broker_name="FYERS",
            order_id="ord-dup",
            broker_order_id="brk-dup",
            broker_trade_id="trade-001",  # Duplicate trade ID
            symbol="RELIANCE",
            exchange="NSE",
            segment="EQUITY_INTRADAY",
            side="BUY",
            quantity=10,
            fill_price=2500.0,
        )


def test_transactional_alert_outbox(tmp_path):
    outbox_file = tmp_path / "test_alerts_outbox.json"
    outbox = AlertOutbox(target_file_fn=lambda: outbox_file)

    # 1. Stage alert for TELEGRAM and SSE
    id_tg = outbox.stage_alert(
        alert_id="aa-orb-nifty-20261101",
        channel="TELEGRAM",
        payload={"symbol": "NIFTY", "headline": "ORB Breakout"},
        max_attempts=2,
    )
    id_sse = outbox.stage_alert(
        alert_id="aa-orb-nifty-20261101",
        channel="SSE",
        payload={"symbol": "NIFTY", "headline": "ORB Breakout"},
        max_attempts=3,
    )

    pending = outbox.get_pending_entries()
    assert len(pending) == 2

    pending_tg = outbox.get_pending_entries(channel="TELEGRAM")
    assert len(pending_tg) == 1
    assert pending_tg[0]["outbox_id"] == id_tg
    assert pending_tg[0]["status"] == "PENDING"

    # 2. Mark TELEGRAM dispatched -> acknowledged
    outbox.mark_dispatched(id_tg)
    entry_tg = outbox.get_entry(id_tg)
    assert entry_tg["status"] == "DISPATCHED"
    assert entry_tg["attempts"] == 1
    assert entry_tg["dispatched_at"] is not None

    outbox.mark_acknowledged(id_tg)
    assert outbox.get_entry(id_tg)["status"] == "ACKNOWLEDGED"

    # Dispatched/Acked entries are no longer pending
    assert len(outbox.get_pending_entries(channel="TELEGRAM")) == 0

    # 3. Simulate failure on SSE
    outbox.mark_failed(id_sse, error="Network timeout (504)")
    entry_sse = outbox.get_entry(id_sse)
    assert entry_sse["status"] == "FAILED_RETRY"
    assert entry_sse["attempts"] == 1
    assert entry_sse["last_error"] == "Network timeout (504)"

    # FAILED_RETRY is still returned by get_pending_entries
    assert len(outbox.get_pending_entries(channel="SSE")) == 1

    # Second failure (attempts reach max_attempts = 3)
    outbox.mark_failed(id_sse, error="Network timeout (504)")
    outbox.mark_failed(id_sse, error="Gateway unroutable (502)")
    entry_sse_final = outbox.get_entry(id_sse)
    assert entry_sse_final["attempts"] == 3
    assert entry_sse_final["status"] == "FAILED"

    # Terminal FAILED is no longer pending
    assert len(outbox.get_pending_entries()) == 0
