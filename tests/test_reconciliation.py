"""
tests/test_reconciliation.py
────────────────────────────
Unit tests for Broker Statement & Internal Ledger Reconciliation Engine.
"""

from engine.reconciliation import reconcile_ledger


def test_reconciliation_complete():
    positions = [{"symbol": "INFY", "qty": 100, "avg_price": 1850.0, "pnl": 5000.0}]
    report = reconcile_ledger(
        internal_positions=positions,
        broker_positions=positions,
        internal_cash=500000.0,
        broker_cash=500000.0,
    )
    assert report.status == "COMPLETE"
    assert report.discrepancies_count == 0
    assert report.matched_positions_count == 1


def test_reconciliation_disputed_qty_mismatch():
    int_pos = [{"symbol": "RELIANCE", "qty": 100, "avg_price": 2400.0}]
    brk_pos = [{"symbol": "RELIANCE", "qty": 50, "avg_price": 2400.0}]
    report = reconcile_ledger(
        internal_positions=int_pos,
        broker_positions=brk_pos,
        internal_cash=500000.0,
        broker_cash=500000.0,
    )
    assert report.status == "DISPUTED"
    assert report.discrepancies_count == 1
    assert report.discrepancies[0].discrepancy_type == "QTY_MISMATCH"


def test_reconciliation_partial_cash_diff():
    positions = [{"symbol": "TCS", "qty": 20, "avg_price": 4100.0}]
    report = reconcile_ledger(
        internal_positions=positions,
        broker_positions=positions,
        internal_cash=500000.0,
        broker_cash=499950.0,  # ₹50 minor brokerage/fee difference
    )
    assert report.status == "PARTIAL"
    assert report.cash_diff == 50.0
