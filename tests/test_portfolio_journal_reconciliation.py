"""
tests/test_portfolio_journal_reconciliation.py
───────────────────────────────────────────────
Unit tests for P1-C: Broker reconciliation and authoritative trade journal performance stats.
"""

from engine.reconciliation import reconcile_ledger
from engine.journal import TradeJournalManager


def test_reconciliation_complete_match():
    """Verify clean reconciliation when positions and cash match exactly."""
    internal = [{"symbol": "RELIANCE", "qty": 100, "avg_price": 2500.0, "pnl": 5000.0}]
    broker = [{"symbol": "RELIANCE", "qty": 100, "avg_price": 2500.0, "pnl": 5000.0}]

    report = reconcile_ledger(
        internal_positions=internal,
        broker_positions=broker,
        internal_cash=500000.0,
        broker_cash=500000.0,
    )

    assert report.status == "COMPLETE"
    assert report.is_reconciled is True
    assert report.allow_trading is True
    assert report.discrepancies_count == 0


def test_reconciliation_quantity_dispute_blocks_trading():
    """Verify quantity mismatch is marked DISPUTED and blocks high-risk trading."""
    internal = [{"symbol": "INFY", "qty": 200, "avg_price": 1800.0, "pnl": 2000.0}]
    broker = [
        {"symbol": "INFY", "qty": 100, "avg_price": 1800.0, "pnl": 1000.0}
    ]  # 100 share mismatch!

    report = reconcile_ledger(
        internal_positions=internal,
        broker_positions=broker,
        internal_cash=500000.0,
        broker_cash=500000.0,
    )

    assert report.status == "DISPUTED"
    assert report.is_reconciled is False
    assert report.allow_trading is False
    assert report.discrepancies_count == 1
    assert report.discrepancies[0].discrepancy_type == "QTY_MISMATCH"
    assert report.discrepancies[0].severity == "HIGH"


def test_trade_journal_lifecycle_and_statistics(tmp_path):
    """Verify trade journal lifecycle from open to close and mathematical expectancy derivation."""
    journal_file = tmp_path / "test_journal.json"
    mgr = TradeJournalManager(storage_path=journal_file)

    # Trade 1: Win (+2.0R)
    # Entry: 1000, Stop: 950 (Risk: 50 * 10 = 500), Exit: 1100 (+1000 gross - 20 fees = 980 net) -> ~1.96R
    e1 = mgr.add_entry(
        symbol="TATASTEEL",
        direction="BUY",
        entry_price=1000.0,
        qty=10,
        stop_loss=950.0,
        target=1100.0,
        thesis="VCP contraction breakout",
    )
    assert e1.status == "OPEN"
    mgr.close_entry(e1.id, exit_price=1100.0, fees_and_taxes=20.0)

    # Trade 2: Loss (-1.0R)
    # Entry: 500, Stop: 480 (Risk: 20 * 20 = 400), Exit: 480 (-400 gross - 10 fees = -410 net)
    e2 = mgr.add_entry(
        symbol="SBIN",
        direction="BUY",
        entry_price=500.0,
        qty=20,
        stop_loss=480.0,
        target=550.0,
        thesis="Support bounce test",
    )
    mgr.close_entry(e2.id, exit_price=480.0, fees_and_taxes=10.0)

    # Trade 3: Open trade
    mgr.add_entry(
        symbol="HDFCBANK",
        direction="BUY",
        entry_price=1600.0,
        qty=50,
        stop_loss=1550.0,
        target=1700.0,
    )

    stats = mgr.compute_statistics()
    assert stats.total_trades == 3
    assert stats.open_trades == 1
    assert stats.closed_trades == 2
    assert stats.winning_trades == 1
    assert stats.losing_trades == 1
    assert stats.win_rate_pct == 50.0
    assert stats.profit_factor > 1.0
    assert stats.total_realized_pnl == round(980.0 - 410.0, 2)
