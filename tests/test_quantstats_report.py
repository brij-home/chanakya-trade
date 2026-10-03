"""
tests/test_quantstats_report.py
───────────────────────────────
Deterministic unit tests for engine/quantstats_report.py.
"""

import pandas as pd
import numpy as np
import pytest
from datetime import datetime, timedelta
from pathlib import Path

from engine.quantstats_report import (
    daily_returns,
    calculate_robustness_score,
    key_metrics,
    generate_html_tear_sheet,
)


def test_daily_returns_intraday_compounding():
    # 2 timestamps on Day 1: +1% and +2% -> (1.01 * 1.02) - 1 = +3.02%
    # 1 timestamp on Day 2: -1%
    dt1_a = datetime(2026, 1, 1, 9, 30)
    dt1_b = datetime(2026, 1, 1, 15, 0)
    dt2 = datetime(2026, 1, 2, 10, 0)

    s = pd.Series([0.01, 0.02, -0.01], index=[dt1_a, dt1_b, dt2])
    daily = daily_returns(s)

    assert len(daily) == 2
    assert pytest.approx(daily.iloc[0], 0.0001) == 0.0302
    assert pytest.approx(daily.iloc[1], 0.0001) == -0.01


def test_calculate_robustness_score():
    # Synthetic 100 days of consistent positive returns
    np.random.seed(42)
    rets = pd.Series(np.random.normal(0.002, 0.01, 100))
    score = calculate_robustness_score(rets, oos_fraction=0.3)
    assert 0.0 <= score <= 1.0


def test_key_metrics_disambiguates_win_rates():
    # 5 days: 3 positive days, 2 negative days -> positive_period_pct = 60.0%
    rets = pd.Series([0.02, 0.01, -0.01, 0.03, -0.02])

    # 4 trades: 1 win, 3 losses -> trade_win_rate = 25.0%
    trades = [
        {"pnl": 500.0},
        {"pnl": -100.0},
        {"pnl": -100.0},
        {"pnl": -100.0},
    ]

    metrics = key_metrics(rets, trades=trades)

    assert metrics["positive_period_pct"] == 60.0
    assert metrics["trade_win_rate"] == 25.0
    assert metrics["trade_count"] == 4
    assert metrics["largest_loss"] == -100.0
    assert metrics["profit_factor"] == pytest.approx(500.0 / 300.0, 0.01)
    assert "robustness_score" in metrics


def test_generate_html_tear_sheet(tmp_path):
    rets = pd.Series([0.01, -0.005, 0.02, 0.003, -0.01])
    out_file = tmp_path / "test_report.html"

    path = generate_html_tear_sheet(rets, output_path=str(out_file), title="Test Algo Report")
    assert Path(path).exists()
    content = Path(path).read_text(encoding="utf-8")
    assert "Test Algo Report" in content
    assert "PROVENANCE: REAL/QUANT" in content
