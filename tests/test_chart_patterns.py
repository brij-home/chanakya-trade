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


def test_completed_double_bottom_not_emitted():
    # Trough 1 at 100, peak at 110, trough 2 at 100.5 -> measured target = 120.0.
    # Current price at 125 has already exceeded target and must not be emitted.
    closes = [120, 115, 110, 105, 100, 100, 103, 106, 110, 108, 105, 102, 100.5, 103, 112, 118, 125]
    highs = [c + 1.0 for c in closes]
    lows = [c - 1.0 for c in closes]
    df = pd.DataFrame({"close": closes, "high": highs, "low": lows, "volume": [1000] * len(closes)})

    patterns = detect_chart_patterns(df)
    db_patterns = [p for p in patterns if p.name == "DOUBLE_BOTTOM"]
    assert db_patterns == []


def test_chart_pattern_detector_skips_inverted_target_before_option_resolution(monkeypatch):
    from analysis.chart_patterns import ChartPattern
    from engine.detectors import chart_pattern_detector

    called = {"resolve": 0}

    def _fail_if_called(**kwargs):
        called["resolve"] += 1
        raise AssertionError("resolve_option_contract should not be called for inverted targets")

    monkeypatch.setattr(chart_pattern_detector, "resolve_option_contract", _fail_if_called)
    monkeypatch.setattr(
        chart_pattern_detector,
        "detect_chart_patterns",
        lambda df: [
            ChartPattern(
                name="DOUBLE_BOTTOM",
                bias="BULLISH",
                pattern_type="REVERSAL",
                confidence=82,
                neckline_or_pivot=110.0,
                breakout_level=110.0,
                measured_target=120.0,
                invalidation_stop=99.5,
                risk_reward_ratio=2.0,
                status="CONFIRMED",
                summary="Already exceeded target",
            )
        ],
    )

    closes = [100 + i for i in range(25)]
    df = pd.DataFrame(
        {
            "close": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "volume": [1000] * 25,
        }
    )
    alerts = chart_pattern_detector.detect_chart_pattern_setups(
        symbol="AXISBANK",
        df=df,
        ltp=125.0,
        exchange="NSE",
        timeframe="15m",
    )
    assert alerts == []
    assert called["resolve"] == 0
