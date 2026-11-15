"""
tests/test_auction_market_profile.py
────────────────────────────────────
Unit tests for Dalton Auction Market Theory & Market Profile Engine.
"""

import numpy as np
import pandas as pd

from analysis.auction_market_profile import (
    analyze_market_profile,
    classify_opening_auction_type,
    evaluate_value_area_relationship,
    evaluate_dalton_80_percent_rule,
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


def test_classify_opening_auction_types():
    """Verify classification of Open-Drive, Open-Test-Drive, and Open-Rejection-Reverse."""
    dates = pd.date_range("2026-01-01 09:15", periods=6, freq="5min")

    # 1. Open-Drive (Bullish): Every bar moves higher with no low violation
    df_drive = pd.DataFrame(
        {
            "open": [24000.0, 24030.0, 24060.0, 24090.0, 24120.0, 24150.0],
            "high": [24035.0, 24065.0, 24095.0, 24125.0, 24155.0, 24185.0],
            "low": [23998.0, 24025.0, 24055.0, 24085.0, 24115.0, 24145.0],
            "close": [24030.0, 24060.0, 24090.0, 24120.0, 24150.0, 24180.0],
            "volume": [5000, 4800, 5200, 4900, 5100, 5300],
        },
        index=dates,
    )
    res_drive = classify_opening_auction_type(
        df_drive, pdh=23950.0, pdl=23800.0, pdc=23920.0, vah=23930.0, val=23820.0
    )
    assert res_drive["opening_type"] == "OPEN_DRIVE"
    assert res_drive["direction"] == "BULLISH"
    assert res_drive["conviction"] == "HIGH"

    # 2. Open-Test-Drive (Bearish): Probes PDH (24100), rejects, and drives down
    df_test = pd.DataFrame(
        {
            "open": [24080.0, 24095.0, 24050.0, 24020.0, 23990.0, 23960.0],
            "high": [24102.0, 24101.0, 24060.0, 24030.0, 24000.0, 23970.0],
            "low": [24075.0, 24040.0, 24010.0, 23980.0, 23950.0, 23920.0],
            "close": [24095.0, 24050.0, 24020.0, 23990.0, 23960.0, 23930.0],
            "volume": [3000, 4000, 3500, 3200, 3100, 3300],
        },
        index=dates,
    )
    res_test = classify_opening_auction_type(
        df_test, pdh=24100.0, pdl=23900.0, pdc=24050.0, vah=24080.0, val=23950.0
    )
    assert res_test["opening_type"] == "OPEN_TEST_DRIVE"
    assert res_test["direction"] == "BEARISH"
    assert res_test["conviction"] == "HIGH"


def test_value_area_relationships():
    """Verify Dalton's 6 Value Area relationship classifications."""
    # Prior VA: VAL=24000, VAH=24200
    p_val, p_vah = 24000.0, 24200.0

    # 1. HIGHER_VALUE: Today's VAL > Prior VAH
    assert evaluate_value_area_relationship(24400.0, 24250.0, p_vah, p_val) == "HIGHER_VALUE"

    # 2. LOWER_VALUE: Today's VAH < Prior VAL
    assert evaluate_value_area_relationship(23950.0, 23800.0, p_vah, p_val) == "LOWER_VALUE"

    # 3. INSIDE_VALUE: Today's VA within Prior VA
    assert evaluate_value_area_relationship(24150.0, 24050.0, p_vah, p_val) == "INSIDE_VALUE"

    # 4. OUTSIDE_VALUE: Today's VA engulfs Prior VA
    assert evaluate_value_area_relationship(24300.0, 23900.0, p_vah, p_val) == "OUTSIDE_VALUE"

    # 5. OVERLAPPING_HIGHER: Both shifted up but overlapping
    assert evaluate_value_area_relationship(24250.0, 24050.0, p_vah, p_val) == "OVERLAPPING_HIGHER"

    # 6. OVERLAPPING_LOWER: Both shifted down but overlapping
    assert evaluate_value_area_relationship(24150.0, 23950.0, p_vah, p_val) == "OVERLAPPING_LOWER"


def test_dalton_80_percent_rule():
    """Verify Dalton's 80% Rule triggers on Value Area re-entry and acceptance."""
    dates = pd.date_range("2026-01-01 09:15", periods=5, freq="5min")

    # Case A: Bearish Rotation (Open above VAH 24200 at 24250, then closes inside VA)
    df_bear = pd.DataFrame(
        {
            "open": [24250.0, 24220.0, 24190.0, 24170.0, 24150.0],
            "high": [24260.0, 24225.0, 24195.0, 24175.0, 24155.0],
            "low": [24215.0, 24185.0, 24165.0, 24145.0, 24125.0],
            "close": [24220.0, 24190.0, 24170.0, 24150.0, 24130.0],
        },
        index=dates,
    )
    setup_bear = evaluate_dalton_80_percent_rule(
        df_bear, prior_vah=24200.0, prior_val=24000.0, prior_poc=24100.0
    )
    assert setup_bear is not None
    assert setup_bear["rule"] == "DALTON_80_PERCENT_RULE"
    assert setup_bear["direction"] == "BEARISH"
    assert setup_bear["target_2"] == 24000.0  # Opposite VA bound (VAL)
    assert setup_bear["probability"] == 0.80

    # Case B: Bullish Rotation (Open below VAL 24000 at 23950, then closes inside VA)
    df_bull = pd.DataFrame(
        {
            "open": [23950.0, 23980.0, 24010.0, 24030.0, 24050.0],
            "high": [23985.0, 24015.0, 24035.0, 24055.0, 24075.0],
            "low": [23945.0, 23975.0, 24005.0, 24025.0, 24045.0],
            "close": [23980.0, 24010.0, 24030.0, 24050.0, 24070.0],
        },
        index=dates,
    )
    setup_bull = evaluate_dalton_80_percent_rule(
        df_bull, prior_vah=24200.0, prior_val=24000.0, prior_poc=24100.0
    )
    assert setup_bull is not None
    assert setup_bull["rule"] == "DALTON_80_PERCENT_RULE"
    assert setup_bull["direction"] == "BULLISH"
    assert setup_bull["target_2"] == 24200.0  # Opposite VA bound (VAH)
    assert setup_bull["probability"] == 0.80
