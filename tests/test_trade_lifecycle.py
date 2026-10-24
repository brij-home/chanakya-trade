"""
tests/test_trade_lifecycle.py
─────────────────────────────
Unit tests for Position Lifecycle, 2R Breakeven Pivot, and Dynamic Trailing Stop-Loss Engine.
Runs offline using deterministic synthetic data.
"""

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


def test_audit_position_lifecycle_stall_kill_switch():
    """Verify that a trade hovering near entry for 4+ bars triggers MOMENTUM_STALLING and SCRATCH_POSITION."""
    report = audit_position_lifecycle(
        symbol="STALLED_TRADE",
        entry_price=1000.0,
        initial_stop_loss=950.0,
        current_ltp=1005.0,  # +0.1R (hovering near entry)
        bars_held=5,
        duration_minutes=25.0,
    )
    assert report.symbol == "STALLED_TRADE"
    assert report.health_status == "MOMENTUM_STALLING"
    assert report.health_score == 40
    assert report.recommended_action == "SCRATCH_POSITION"
    assert any("Momentum Stalled" in d for d in report.diagnostic_bullet_points)


def test_chandelier_convexity_ratchet_long_and_short():
    """
    Verifies that as profit expands:
    1. At +1.2R, stop moves to HALF_RISK_LOCKED (cuts initial risk by 50%).
    2. At +2.8R, stop moves to CHANDELIER_CONVEXITY_RATCHET locking at least +1.0R.
    3. Short trades symmetrically ratchet DOWNWARDS below entry.
    """
    # 1. Long at +1.2R (Entry: 1000, Initial SL: 950 -> risk: 50. LTP: 1060)
    rep_long_1r = audit_position_lifecycle(
        symbol="TCS",
        entry_price=1000.0,
        initial_stop_loss=950.0,
        current_ltp=1060.0,
        position_type="LONG",
    )
    assert rep_long_1r.current_r_multiple == pytest.approx(1.2, abs=0.05)
    assert rep_long_1r.trailing_stops.stop_method == "HALF_RISK_LOCKED"
    assert rep_long_1r.trailing_stops.recommended_active_stop == 975.0  # entry - 0.5 * 50

    # 2. Long at +2.8R (LTP: 1140 -> R = 2.8)
    rep_long_28r = audit_position_lifecycle(
        symbol="TCS",
        entry_price=1000.0,
        initial_stop_loss=950.0,
        current_ltp=1140.0,
        position_type="LONG",
    )
    assert rep_long_28r.current_r_multiple == pytest.approx(2.8, abs=0.05)
    assert "CHANDELIER" in rep_long_28r.trailing_stops.stop_method
    assert (
        rep_long_28r.trailing_stops.recommended_active_stop >= 1050.0
    )  # Locked at least +1R (1050.0)

    # 3. Short at +2.8R (Entry: 1000, Initial SL: 1050 -> risk: 50. LTP: 860)
    rep_short_28r = audit_position_lifecycle(
        symbol="TCS",
        entry_price=1000.0,
        initial_stop_loss=1050.0,
        current_ltp=860.0,
        position_type="SHORT",
    )
    assert rep_short_28r.current_r_multiple == pytest.approx(2.8, abs=0.05)
    assert "CHANDELIER" in rep_short_28r.trailing_stops.stop_method
    assert (
        rep_short_28r.trailing_stops.recommended_active_stop <= 950.0
    )  # Trailed DOWN to lock at least +1R (950.0)


def test_exhaustion_wick_harvest_detection():
    """Verify that a position at +3R printing a massive upper wick triggers EXHAUSTION_HARVEST."""
    dates = pd.date_range(start="2025-01-01", periods=15, freq="D")
    df = pd.DataFrame(
        {
            "date": dates,
            "open": [1000.0] * 14 + [1140.0],
            "high": [1010.0] * 14 + [1180.0],  # 40-point range, peak at 1180
            "low": [990.0] * 14 + [1140.0],
            "close": [1005.0] * 14
            + [1145.0],  # Close near bottom (wick = 1180-1145 = 35 / 40 = 87.5% wick)
        }
    )
    rep = audit_position_lifecycle(
        symbol="RELIANCE",
        entry_price=1000.0,
        initial_stop_loss=950.0,  # Risk = 50
        df=df,
        current_ltp=1145.0,  # +2.9R
        position_type="LONG",
    )
    assert rep.recommended_action == "EXHAUSTION_HARVEST"
    assert rep.health_status == "EXHAUSTION_CLIMAX"
    assert any("Exhaustion" in d for d in rep.diagnostic_bullet_points)
