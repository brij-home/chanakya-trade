"""
tests/test_chart_patterns.py
─────────────────────────────
Unit tests for Classical & Geometric Chart Pattern Recognition Engine.
"""

import pandas as pd

from analysis.chart_patterns import detect_chart_patterns


def test_double_bottom_detection():
    # Construct synthetic double bottom (trough 1 at 100, peak at 110, trough 2 at 100.5, current at 108)
    closes = [120, 115, 110, 105, 100, 100, 103, 106, 110, 108, 105, 102, 100.5, 101, 104, 107, 109]
    highs = [c + 1.0 for c in closes]
    lows = [c - 1.0 for c in closes]
    df = pd.DataFrame({"close": closes, "high": highs, "low": lows, "volume": [1000] * len(closes)})

    patterns = detect_chart_patterns(df)
    db_patterns = [p for p in patterns if p.name == "DOUBLE_BOTTOM"]
    assert len(db_patterns) >= 1
    p = db_patterns[0]
    assert p.bias == "BULLISH"
    assert p.measured_target > p.neckline_or_pivot
    assert p.invalidation_stop < 101.0


def test_double_top_detection():
    # Construct synthetic double top (peak 1 at 200, trough at 185, peak 2 at 199.5, current at 188)
    closes = [175, 180, 190, 198, 200, 199, 195, 190, 185, 186, 192, 196, 199.5, 198, 193, 187, 184]
    highs = [c + 1.0 for c in closes]
    lows = [c - 1.0 for c in closes]
    df = pd.DataFrame({"close": closes, "high": highs, "low": lows, "volume": [1000] * len(closes)})

    patterns = detect_chart_patterns(df)
    dt_patterns = [p for p in patterns if p.name == "DOUBLE_TOP"]
    assert len(dt_patterns) >= 1
    p = dt_patterns[0]
    assert p.bias == "BEARISH"
    assert p.measured_target < p.neckline_or_pivot
    assert p.invalidation_stop > 199.0
