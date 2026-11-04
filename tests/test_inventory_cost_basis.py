"""
tests/test_inventory_cost_basis.py
───────────────────────────────────
Institutional test suite for signed inventory accounting, weighted-average cost basis,
partial closes, crossing zero, product separation, and execution fill integrity.
"""

from __future__ import annotations

import uuid
import pytest

from engine.order_lifecycle import (
    set_ledger_cash_baseline,
    record_execution_fill,
    get_internal_ledger_snapshot,
)


def _new_account_id() -> str:
    return f"acc-{uuid.uuid4().hex[:10]}"


def test_long_partial_close_and_reopen_cost_basis():
    """
    Verify:
    1. Buy 100 @ 100 -> Cost basis 100.
    2. Sell 50 @ 120 -> Remaining 50 units cost basis MUST STAY 100 (not 80!).
    3. Sell 50 @ 110 -> Position fully closed, flat.
    4. Reopen: Buy 100 @ 150 -> Cost basis MUST BE 150 (not contaminated by old P&L).
    """
    acc = _new_account_id()
    set_ledger_cash_baseline(acc, 100000.0)

    # 1. Buy 100 @ 100
    record_execution_fill(
        account_id=acc,
        broker_name="FYERS",
        order_id="ord-1",
        broker_order_id="brk-ord-1",
        broker_trade_id="tr-1",
        symbol="TCS",
        exchange="NSE",
        segment="EQUITY_INTRADAY",
        side="BUY",
        quantity=100,
        fill_price=100.0,
    )
    s1 = get_internal_ledger_snapshot(acc)
    assert len(s1["positions"]) == 1
    pos1 = s1["positions"][0]
    assert pos1["quantity"] == 100
    assert pos1["average_cost_basis"] == 100.0

    # 2. Sell 50 @ 120 (partial close)
    record_execution_fill(
        account_id=acc,
        broker_name="FYERS",
        order_id="ord-2",
        broker_order_id="brk-ord-2",
        broker_trade_id="tr-2",
        symbol="TCS",
        exchange="NSE",
        segment="EQUITY_INTRADAY",
        side="SELL",
        quantity=50,
        fill_price=120.0,
    )
    s2 = get_internal_ledger_snapshot(acc)
    assert len(s2["positions"]) == 1
    pos2 = s2["positions"][0]
    assert pos2["quantity"] == 50
    # Crucial assertion: cost basis remains 100.0, NOT 80.0!
    assert pos2["average_cost_basis"] == 100.0
    assert s2["total_realized_pnl"] == 1000.0  # 50 * (120 - 100)

    # 3. Sell 50 @ 110 (full close)
    record_execution_fill(
        account_id=acc,
        broker_name="FYERS",
        order_id="ord-3",
        broker_order_id="brk-ord-3",
        broker_trade_id="tr-3",
        symbol="TCS",
        exchange="NSE",
        segment="EQUITY_INTRADAY",
        side="SELL",
        quantity=50,
        fill_price=110.0,
    )
    s3 = get_internal_ledger_snapshot(acc)
    assert len(s3["positions"]) == 0
    assert s3["total_realized_pnl"] == 1500.0  # 1000 + 50 * (110 - 100)

    # 4. Reopen: Buy 100 @ 150
    record_execution_fill(
        account_id=acc,
        broker_name="FYERS",
        order_id="ord-4",
        broker_order_id="brk-ord-4",
        broker_trade_id="tr-4",
        symbol="TCS",
        exchange="NSE",
        segment="EQUITY_INTRADAY",
        side="BUY",
        quantity=100,
        fill_price=150.0,
    )
    s4 = get_internal_ledger_snapshot(acc)
    assert len(s4["positions"]) == 1
    pos4 = s4["positions"][0]
    assert pos4["quantity"] == 100
    # Crucial assertion: cost basis is 150.0, clean of old P&L
    assert pos4["average_cost_basis"] == 150.0


def test_crossing_through_zero_long_to_short_and_back():
    """
    Verify crossing zero:
    1. Long 100 @ 100
    2. Sell 150 @ 120 -> Closes 100 Long (+2000 PnL), Opens 50 Short @ 120
    3. Buy 70 @ 100 -> Covers 50 Short (+1000 PnL), Opens 20 Long @ 100
    """
    acc = _new_account_id()
    set_ledger_cash_baseline(acc, 50000.0)

    # 1. Long 100 @ 100
    record_execution_fill(
        account_id=acc,
        broker_name="FYERS",
        order_id="ord-1",
        broker_order_id="b-1",
        broker_trade_id="t-1",
        symbol="INFY",
        exchange="NSE",
        segment="EQUITY_INTRADAY",
        side="BUY",
        quantity=100,
        fill_price=100.0,
    )

    # 2. Sell 150 @ 120 (cross through zero)
    record_execution_fill(
        account_id=acc,
        broker_name="FYERS",
        order_id="ord-2",
        broker_order_id="b-2",
        broker_trade_id="t-2",
        symbol="INFY",
        exchange="NSE",
        segment="EQUITY_INTRADAY",
        side="SELL",
        quantity=150,
        fill_price=120.0,
    )
    s2 = get_internal_ledger_snapshot(acc)
    assert len(s2["positions"]) == 1
    pos2 = s2["positions"][0]
    assert pos2["quantity"] == -50
    assert pos2["side"] == "SHORT"
    assert pos2["average_cost_basis"] == 120.0
    assert s2["total_realized_pnl"] == 2000.0  # 100 * (120 - 100)

    # 3. Buy 70 @ 100 (cross through zero from SHORT to LONG)
    record_execution_fill(
        account_id=acc,
        broker_name="FYERS",
        order_id="ord-3",
        broker_order_id="b-3",
        broker_trade_id="t-3",
        symbol="INFY",
        exchange="NSE",
        segment="EQUITY_INTRADAY",
        side="BUY",
        quantity=70,
        fill_price=100.0,
    )
    s3 = get_internal_ledger_snapshot(acc)
    assert len(s3["positions"]) == 1
    pos3 = s3["positions"][0]
    assert pos3["quantity"] == 20
    assert pos3["side"] == "LONG"
    assert pos3["average_cost_basis"] == 100.0
    # Total PnL: 2000 (from long) + 50 * (120 - 100) = 3000
    assert s3["total_realized_pnl"] == 3000.0


def test_product_separation():
    """Verify MIS and CNC positions on same symbol are tracked as distinct inventories."""
    acc = _new_account_id()
    set_ledger_cash_baseline(acc, 500000.0)

    record_execution_fill(
        account_id=acc,
        broker_name="FYERS",
        order_id="ord-mis",
        broker_order_id="b-mis",
        broker_trade_id="t-mis",
        symbol="RELIANCE",
        exchange="NSE",
        segment="EQUITY_INTRADAY",
        product="MIS",
        side="BUY",
        quantity=10,
        fill_price=2500.0,
    )
    record_execution_fill(
        account_id=acc,
        broker_name="FYERS",
        order_id="ord-cnc",
        broker_order_id="b-cnc",
        broker_trade_id="t-cnc",
        symbol="RELIANCE",
        exchange="NSE",
        segment="EQUITY_DELIVERY",
        product="CNC",
        side="BUY",
        quantity=5,
        fill_price=2520.0,
    )

    s = get_internal_ledger_snapshot(acc)
    assert len(s["positions"]) == 2
    prod_map = {p["product"]: p for p in s["positions"]}
    assert prod_map["MIS"]["quantity"] == 10
    assert prod_map["MIS"]["average_cost_basis"] == 2500.0
    assert prod_map["CNC"]["quantity"] == 5
    assert prod_map["CNC"]["average_cost_basis"] == 2520.0


def test_unsupported_futures_segment_fails_honestly():
    """Verify futures segment rejects with UNAVAILABLE."""
    acc = _new_account_id()
    set_ledger_cash_baseline(acc, 200000.0)

    record_execution_fill(
        account_id=acc,
        broker_name="FYERS",
        order_id="ord-fut",
        broker_order_id="b-fut",
        broker_trade_id="t-fut",
        symbol="NIFTY24NOVFUT",
        exchange="NSE",
        segment="FUTURES",
        side="BUY",
        quantity=50,
        fill_price=24500.0,
    )

    s = get_internal_ledger_snapshot(acc)
    assert s["status"] == "UNAVAILABLE"
    assert "Futures MTM/margin accounting is not supported" in s["rejection_reason"]


def test_fill_validations_and_conflict_handling():
    """Verify input validation and conflicting vs idempotent retries."""
    acc = _new_account_id()
    set_ledger_cash_baseline(acc, 100000.0)

    # 1. Fractional quantity rejected
    with pytest.raises(ValueError, match="quantity must be an integer"):
        record_execution_fill(
            account_id=acc,
            broker_name="FYERS",
            order_id="o1",
            broker_order_id="bo1",
            broker_trade_id="bt1",
            symbol="TCS",
            exchange="NSE",
            segment="EQUITY_INTRADAY",
            side="BUY",
            quantity=10.5,
            fill_price=100.0,
        )

    # 2. Nonfinite price rejected
    with pytest.raises(ValueError, match="fill_price must be a finite positive price"):
        record_execution_fill(
            account_id=acc,
            broker_name="FYERS",
            order_id="o2",
            broker_order_id="bo2",
            broker_trade_id="bt2",
            symbol="TCS",
            exchange="NSE",
            segment="EQUITY_INTRADAY",
            side="BUY",
            quantity=10,
            fill_price=float("nan"),
        )

    # 3. Successful fill
    f1 = record_execution_fill(
        account_id=acc,
        broker_name="FYERS",
        order_id="o3",
        broker_order_id="bo3",
        broker_trade_id="bt-dup",
        symbol="TCS",
        exchange="NSE",
        segment="EQUITY_INTRADAY",
        side="BUY",
        quantity=20,
        fill_price=150.0,
    )
    assert f1["is_idempotent_retry"] is False

    # 4. Idempotent identical retry
    f2 = record_execution_fill(
        account_id=acc,
        broker_name="FYERS",
        order_id="o3",
        broker_order_id="bo3",
        broker_trade_id="bt-dup",
        symbol="TCS",
        exchange="NSE",
        segment="EQUITY_INTRADAY",
        side="BUY",
        quantity=20,
        fill_price=150.0,
    )
    assert f2["is_idempotent_retry"] is True
    assert f2["fill_id"] == f1["fill_id"]

    # 5. Conflicting retry (different price) raises ValueError
    with pytest.raises(ValueError, match="Conflicting duplicate broker execution retry"):
        record_execution_fill(
            account_id=acc,
            broker_name="FYERS",
            order_id="o3",
            broker_order_id="bo3",
            broker_trade_id="bt-dup",
            symbol="TCS",
            exchange="NSE",
            segment="EQUITY_INTRADAY",
            side="BUY",
            quantity=20,
            fill_price=160.0,  # Conflicting price!
        )


def test_baseline_without_fills_reports_incomplete():
    """Verify baseline with 0 fills notes is_complete=False."""
    acc = _new_account_id()
    set_ledger_cash_baseline(acc, 50000.0)

    s = get_internal_ledger_snapshot(acc)
    assert s["status"] == "AVAILABLE"
    assert s["is_complete"] is False
    assert "zero broker fills have been imported" in s["incompleteness_reason"]
