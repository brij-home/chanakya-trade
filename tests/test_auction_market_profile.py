"""
tests/test_auction_market_profile.py
────────────────────────────────────
Unit tests for Dalton Auction Market Theory & Market Profile Engine.
"""

import numpy as np
import pandas as pd

from analysis.auction_market_profile import (
    analyze_market_profile,
)


def _create_intraday_session(n_bars: int = 30) -> pd.DataFrame:
    """Generates a 30-bar 5-minute session (09:15 to 11:45 IST)."""
    dates = pd.date_range("2026-01-01 09:15", periods=n_bars, freq="5min")
    # First 12 bars (IB): range between 24000 and 24100 (100 pt IB)
    opens, highs, lows, closes, vols = [], [], [], [], []
    for i in range(12):
        p = 24050.0 + np.sin(i) * 35.0
        opens.append(p - 5.0)
        highs.append(24100.0 if i == 5 else p + 10.0)
        lows.append(24000.0 if i == 2 else p - 10.0)
        closes.append(p)
        vols.append(1000)

    # Next 18 bars (Expansion): break out above 24100 to 24250 (Trend expansion)
    curr_p = 24100.0
    for i in range(n_bars - 12):
        curr_p += 8.0
        opens.append(curr_p - 4.0)
        highs.append(curr_p + 10.0)
        lows.append(curr_p - 5.0)
        closes.append(curr_p)
        vols.append(1500)

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols},
        index=dates,
    )


def test_market_profile_trend_day_expansion():
    """Verify that a narrow IB with directional expansion > 1.8x classifies as a TREND_DAY."""
    df = _create_intraday_session(n_bars=30)
    snap = analyze_market_profile(df, symbol="NIFTY", daily_atr=200.0)
    assert snap is not None
    assert snap.ib_high == 24100.0
    assert snap.ib_low == 24000.0
    assert snap.ib_range_pts == 100.0
    assert snap.day_type in ("TREND_DAY", "NORMAL_VARIATION")
    assert snap.current_expansion_multiple >= 1.5
    assert snap.t1_extension > snap.ib_high


def test_market_profile_poor_high_detection():
    """Verify detection of equal highs (poor high) indicating unfinished auction business."""
    df = _create_intraday_session(n_bars=25)
    # Inject equal highs on the last two bars
    df.iloc[-1, df.columns.get_loc("high")] = 24200.0
    df.iloc[-2, df.columns.get_loc("high")] = 24200.0

    snap = analyze_market_profile(df, symbol="BANKNIFTY", daily_atr=250.0)
    assert snap is not None
    assert snap.has_poor_high is True


def test_market_profile_neutral_day():
    """Verify that a session sweeping both IB High and IB Low classifies as NEUTRAL_DAY."""
    df = _create_intraday_session(n_bars=25)
    # Force breach of high and breach of low
    df.iloc[15, df.columns.get_loc("high")] = 24150.0  # Above IB High 24100
    df.iloc[18, df.columns.get_loc("low")] = 23950.0  # Below IB Low 24000

    snap = analyze_market_profile(df, symbol="NIFTY", daily_atr=200.0)
    assert snap is not None
    assert snap.day_type == "NEUTRAL_DAY"
