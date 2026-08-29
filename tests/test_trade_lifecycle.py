"""
tests/test_trade_lifecycle.py
─────────────────────────────
Unit tests for Position Lifecycle, 2R Breakeven Pivot, and Dynamic Trailing Stop-Loss Engine.
Runs offline using deterministic synthetic data.
"""

import numpy as np
import pandas as pd
import pytest

from engine.trade_lifecycle import audit_position_lifecycle


@pytest.fixture
def progressing_trade_df():
    """Trade entered at 1000, current price 1150 (initial stop 950 -> initial risk 50, profit +150 = +3R)."""
    dates = pd.date_range(start="2025-01-01", periods=20, freq="D")
    opens, highs, lows, closes = [], [], [], []

    for i in range(20):
        c = 1000.0 + i * 8.0  # ends at 1152
        o = c - 2.0
        h = c + 4.0
        l = o - 3.0
        opens.append(o)
        highs.append(h)
        lows.append(l)
        closes.append(c)

    return pd.DataFrame({"date": dates, "open": opens, "high": highs, "low": lows, "close": closes})


def test_audit_position_lifecycle_3r(progressing_trade_df):
    report = audit_position_lifecycle(
        symbol="WINNING_TRADE",
        entry_price=1000.0,
        initial_stop_loss=950.0,
        df=progressing_trade_df,
    )
    assert report.symbol == "WINNING_TRADE"
    assert report.current_r_multiple >= 2.5
    assert report.breakeven_reached is True
    assert report.health_status == "HEALTHY_ACCELERATING"
    assert report.trailing_stops is not None
    assert report.trailing_stops.recommended_active_stop >= 1000.0  # Stop raised above entry
    assert any(m.reached for m in report.milestones if m.r_multiple == 2.0)


def test_audit_position_lifecycle_underwater():
    report = audit_position_lifecycle(
        symbol="LOSING_TRADE",
        entry_price=1000.0,
        initial_stop_loss=950.0,
        current_ltp=960.0,  # -0.8R
    )
    assert report.symbol == "LOSING_TRADE"
    assert report.current_r_multiple < 0
    assert report.breakeven_reached is False
    assert report.trailing_stops.recommended_active_stop == 950.0  # Keep initial stop
