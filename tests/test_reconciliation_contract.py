"""
tests/test_reconciliation_contract.py
──────────────────────────────────────
Regression tests for EXEC-04, EXEC-05, EXEC-06, and TASK P1-D:
  - Internal ledger emitting 'quantity'/'average_price' matches broker 'qty'/'avg_price' (no false DISPUTED).
  - Missing cash (None) returns status='UNAVAILABLE' and allow_trading=False (no 10-lakh fabrication).
  - Large cash difference (> 500) returns status='DISPUTED' and allow_trading=False.
"""

from engine.reconciliation import reconcile_ledger


def test_reconciliation_supports_quantity_and_average_price_keys():
    """Internal positions emitting 'quantity' and 'average_price' must match broker 'qty' and 'avg_price'."""
    internal = [
        {"symbol": "INFY", "quantity": 100, "average_price": 1850.0},
        {"symbol": "TCS", "quantity": 50, "average_price": 3800.0},
    ]
    broker = [
        {"symbol": "INFY", "qty": 100, "avg_price": 1850.0},
        {"symbol": "TCS", "qty": 50, "avg_price": 3800.0},
    ]

    report = reconcile_ledger(
        internal_positions=internal,
        broker_positions=broker,
        internal_cash=500_000.0,
        broker_cash=500_000.0,
    )

    assert report.status == "COMPLETE"
    assert report.is_reconciled is True
    assert report.allow_trading is True
    assert report.discrepancies_count == 0
    assert report.matched_positions_count == 2


def test_reconciliation_missing_cash_returns_unavailable():
    """Missing cash (None) must return status='UNAVAILABLE' and allow_trading=False."""
    report = reconcile_ledger(
        internal_positions=[],
        broker_positions=[],
        internal_cash=None,
        broker_cash=500_000.0,
    )

    assert report.status == "UNAVAILABLE"
    assert report.allow_trading is False
    assert report.is_reconciled is False


def test_reconciliation_broker_cash_zero_returns_disputed():
    """When broker cash parses as 0 or has large gap, status must be DISPUTED, never PARTIAL."""
    report = reconcile_ledger(
        internal_positions=[{"symbol": "RELIANCE", "quantity": 10, "average_price": 2500.0}],
        broker_positions=[{"symbol": "RELIANCE", "qty": 10, "avg_price": 2500.0}],
        internal_cash=500_000.0,
        broker_cash=0.0,  # e.g. funds API parse failure
    )

    assert report.status == "DISPUTED"
    assert report.allow_trading is False
    assert report.is_reconciled is False
    assert report.cash_diff == 500_000.0
