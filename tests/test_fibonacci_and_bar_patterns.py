"""
tests/test_fibonacci_and_bar_patterns.py
────────────────────────────────────────
Unit tests for Fibonacci engine and Bar Patterns (The Strat, NR4/NR7, Hikkake).
"""

import pandas as pd

from analysis.fibonacci import (
    compute_fib_levels,
    evaluate_fib_proximity,
    find_fib_clusters,
)
from analysis.bar_patterns import (
    classify_bar_strat,
    analyze_bar_patterns,
)


def test_fibonacci_levels_bullish():
    """Verify bullish Fibonacci retracements and extensions from a 24000 to 25000 impulse."""
    fl = compute_fib_levels(swing_high=25000.0, swing_low=24000.0, direction="BULLISH")
    assert fl.span == 1000.0
    assert fl.level_0 == 25000.0
    assert fl.level_100 == 24000.0
    assert fl.level_500 == 24500.0
    assert round(fl.level_618, 1) == 24382.0
    assert round(fl.level_705, 1) == 24295.0
    assert round(fl.level_786, 1) == 24214.0
    assert round(fl.ext_1272, 1) == 25272.0
    assert round(fl.ext_1618, 1) == 25618.0
    assert fl.golden_pocket_range[0] < fl.golden_pocket_range[1]


def test_fibonacci_levels_bearish():
    """Verify bearish Fibonacci retracements and extensions from a 25000 to 24000 markdown."""
    fl = compute_fib_levels(swing_high=25000.0, swing_low=24000.0, direction="BEARISH")
    assert fl.span == 1000.0
    assert fl.level_0 == 24000.0
    assert fl.level_100 == 25000.0
    assert fl.level_500 == 24500.0
    assert round(fl.level_618, 1) == 24618.0
    assert round(fl.ext_1272, 1) == 23728.0
    assert round(fl.ext_1618, 1) == 23382.0


def test_fibonacci_proximity_golden_pocket():
    """Verify detection when LTP enters the Golden Pocket (0.618 - 0.786)."""
    fl = compute_fib_levels(swing_high=25000.0, swing_low=24000.0, direction="BULLISH")
    res = evaluate_fib_proximity(ltp=24350.0, fib=fl, proximity_pct=1.0)
    assert res["in_golden_pocket"] is True
    assert "0.618" in res["nearest_fib_level"] or "0.705" in res["nearest_fib_level"]
    assert res["target_1_ext_1272"] == 25272.0


def test_fibonacci_clusters():
    """Verify multi-swing confluence detection across HTF and LTF swings."""
    # Swing 1: 20000 to 25000 (5000 pt span), 0.618 = 25000 - 0.618*5000 = 21910
    # Swing 2: 21000 to 23000 (2000 pt span), 0.500 = 23000 - 0.500*2000 = 22000
    swings = [
        (25000.0, 20000.0, "BULLISH"),
        (23000.0, 21000.0, "BULLISH"),
    ]
    clusters = find_fib_clusters(swings, tolerance_pct=1.0)
    assert len(clusters) >= 1
    c = clusters[0]
    assert c.count >= 2
    assert any("0." in r for r in c.ratios)


def test_bar_strat_classification():
    """Verify accurate 1, 2U, 2D, 3 classification."""
    p_bar = pd.Series({"open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0})

    # Inside Bar (1)
    c_inside = pd.Series({"open": 98.0, "high": 105.0, "low": 95.0, "close": 102.0})
    res_1 = classify_bar_strat(c_inside, p_bar)
    assert res_1.strat_type == 1
    assert res_1.direction == "INSIDE"

    # Directional Up (2U)
    c_2u = pd.Series({"open": 105.0, "high": 115.0, "low": 95.0, "close": 112.0})
    res_2u = classify_bar_strat(c_2u, p_bar)
    assert res_2u.strat_type == 2
    assert res_2u.direction == "UP"

    # Directional Down (2D)
    c_2d = pd.Series({"open": 95.0, "high": 105.0, "low": 85.0, "close": 88.0})
    res_2d = classify_bar_strat(c_2d, p_bar)
    assert res_2d.strat_type == 2
    assert res_2d.direction == "DOWN"

    # Outside Bar (3)
    c_3 = pd.Series({"open": 95.0, "high": 118.0, "low": 82.0, "close": 115.0})
    res_3 = classify_bar_strat(c_3, p_bar)
    assert res_3.strat_type == 3
    assert res_3.direction == "OUTSIDE"


def test_strat_2_1_2_bullish_continuation():
    """Verify The Strat 2-1-2 Bullish Continuation pattern trigger."""
    # Bar -3: Normal bar
    # Bar -2: 2 Up (100 -> 115, high 115, low 98)
    # Bar -1: 1 Inside bar (high 112, low 104)
    # Bar 0: 2 Up breaking inside bar high (open 110, high 120, low 108, close 118)
    df = pd.DataFrame(
        {
            "open": [95.0, 100.0, 108.0, 110.0],
            "high": [102.0, 115.0, 112.0, 120.0],
            "low": [92.0, 98.0, 104.0, 108.0],
            "close": [100.0, 114.0, 110.0, 118.0],
            "volume": [1000, 2500, 800, 3000],
        }
    )
    # Pad to 5 bars
    df_padded = pd.concat([df.iloc[:1], df]).reset_index(drop=True)

    sig = analyze_bar_patterns(df_padded, symbol="NIFTY", atr_val=10.0)
    assert sig is not None
    assert sig.pattern_name == "STRAT_2_1_2_BULLISH"
    assert sig.bias == "BULLISH"
    assert sig.confidence >= 80
    assert sig.entry_trigger > sig.stop_loss
    assert sig.target_1 > sig.entry_trigger


def test_hikkake_bullish_trap_reversal():
    """Verify Dan Chesler's Bullish Hikkake false-breakdown trap reversal."""
    # Bar -4: Base
    # Bar -3: Mother Bar (high 100, low 80)
    # Bar -2: Inside Bar (high 95, low 85)
    # Bar -1: False Breakdown Bar (pierces below 85 to 82, closes at 83 - traps retail shorts)
    # Bar 0: Violent Reversal (opens 84, rallies to 98, closes 97 > inside bar high 95)
    df = pd.DataFrame(
        {
            "open": [90.0, 85.0, 90.0, 86.0, 84.0],
            "high": [92.0, 100.0, 95.0, 87.0, 98.0],
            "low": [85.0, 80.0, 85.0, 82.0, 83.0],
            "close": [88.0, 95.0, 90.0, 83.0, 97.0],
            "volume": [1000, 1200, 800, 2200, 4500],
        }
    )
    sig = analyze_bar_patterns(df, symbol="RELIANCE", atr_val=5.0)
    assert sig is not None
    assert sig.pattern_name == "HIKKAKE_BULLISH"
    assert sig.bias == "BULLISH"
    assert sig.confidence == 85
    assert sig.entry_trigger > sig.stop_loss


def test_outside_bar_absorption():
    """Verify Outside Bar Bullish Absorption when Bar 3 closes in top quartile."""
    # Prior bar: high 100, low 90
    # Current bar: sweeps low to 85, sweeps high to 105, closes at 104 (top quartile)
    df = pd.DataFrame(
        {
            "open": [92.0, 92.0, 92.0, 95.0, 88.0],
            "high": [96.0, 96.0, 96.0, 100.0, 105.0],
            "low": [88.0, 88.0, 88.0, 90.0, 85.0],
            "close": [94.0, 94.0, 94.0, 95.0, 104.0],
            "volume": [1000, 1000, 1000, 1200, 3500],
        }
    )
    sig = analyze_bar_patterns(df, symbol="BANKNIFTY", atr_val=10.0)
    assert sig is not None
    assert sig.pattern_name == "OUTSIDE_BAR_BULLISH_ABSORPTION"
    assert sig.bias == "BULLISH"
    assert sig.confidence == 82
