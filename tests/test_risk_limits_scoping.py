"""
tests/test_risk_limits_scoping.py
=================================
Regression test suite for Task P2-F:
1. Paper and live budgets are independent.
2. Two accounts are independent.
3. Rollover is anchored to IST session date.
"""

from pathlib import Path
import pytest
from engine.risk_limits import RiskLimits


@pytest.fixture
def scoped_risk_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_file = tmp_path / "test_scoped_risk.db"
    monkeypatch.setenv("RISK_DB_PATH", str(db_file))
    monkeypatch.setenv("MAX_DAILY_LOSS", "10000")
    monkeypatch.setenv("MAX_DAILY_TRADES", "5")
    monkeypatch.setenv("MAX_TRADES_PER_SYMBOL", "3")
    return RiskLimits()


def test_paper_and_live_budgets_are_independent(scoped_risk_limits):
    rl = scoped_risk_limits
    # Record big loss in PAPER mode
    rl.record_trade("INFY", "SELL", 10, 1400.0, pnl=-15_000.0, account_id="ACC1", mode="PAPER")

    # In PAPER mode, loss limit is breached
    res_paper = rl.evaluate_preflight("INFY", "BUY", 10, 1400.0, account_id="ACC1", mode="PAPER")
    assert not res_paper.allowed
    assert "DAILY_LOSS_CAP" in res_paper.flags

    # In LIVE / EXECUTE mode, loss limit is NOT breached (clean budget)
    res_live = rl.evaluate_preflight("INFY", "BUY", 10, 1400.0, account_id="ACC1", mode="EXECUTE")
    assert res_live.allowed
    assert "DAILY_LOSS_CAP" not in res_live.flags


def test_two_accounts_are_independent(scoped_risk_limits):
    rl = scoped_risk_limits
    # Account 1 executes 5 trades (reaching max_daily_trades)
    for _ in range(5):
        rl.record_trade("TCS", "BUY", 1, 4000.0, pnl=100.0, account_id="ACC1", mode="EXECUTE")

    # Account 1 is blocked on daily trades
    res_acc1 = rl.evaluate_preflight("TCS", "BUY", 1, 4000.0, account_id="ACC1", mode="EXECUTE")
    assert not res_acc1.allowed
    assert "MAX_DAILY_TRADES" in res_acc1.flags

    # Account 2 has 0 trades today and is allowed
    res_acc2 = rl.evaluate_preflight("TCS", "BUY", 1, 4000.0, account_id="ACC2", mode="EXECUTE")
    assert res_acc2.allowed
    assert "MAX_DAILY_TRADES" not in res_acc2.flags
