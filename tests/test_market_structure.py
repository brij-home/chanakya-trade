"""
tests/test_market_structure.py
───────────────────────────────
Unit tests for Market Structure & Smart Money Concepts (SMC) engine.
Runs completely offline using deterministic synthetic OHLCV data.
"""

import numpy as np
import pandas as pd
import pytest

from analysis.market_structure import (
    analyze_market_structure,
    detect_fair_value_gaps,
    detect_liquidity_sweeps,
    detect_order_blocks,
    find_swing_points,
)


@pytest.fixture
def uptrend_df():
    """Generates 60 bars of clean Higher Highs and Higher Lows."""
    dates = pd.date_range(start="2025-01-01", periods=60, freq="D")
    base_price = 1000.0
    opens, highs, lows, closes, vols = [], [], [], [], []

    for i in range(60):
        trend = i * 2.0
        wave = 30.0 * np.sin(i / 2.5)
        c = base_price + trend + wave
        o = c - 3.0
        h = max(o, c) + 6.0
        l = min(o, c) - 5.0
        v = 100000 + int(i * 1000)
        opens.append(o)
        highs.append(h)
        lows.append(l)
        closes.append(c)
        vols.append(v)

    return pd.DataFrame(
        {"date": dates, "open": opens, "high": highs, "low": lows, "close": closes, "volume": vols}
    )


@pytest.fixture
def choch_reversal_df():
    """Generates a downtrend followed by a sharp Bullish CHoCH breakout."""
    dates = pd.date_range(start="2025-01-01", periods=40, freq="D")
    opens, highs, lows, closes, vols = [], [], [], [], []

    # 25 bars of downtrend with swings: 1000 down to 700
    for i in range(25):
        c = 1000.0 - (i * 12.0) + (20.0 * np.sin(i / 2.0))
        o = c + 4.0
        h = max(o, c) + 6.0
        l = min(o, c) - 6.0
        opens.append(o)
        highs.append(h)
        lows.append(l)
        closes.append(c)
        vols.append(50000)

    # 15 bars of explosive upward reversal breaking prior lower highs
    for i in range(15):
        c = 700.0 + (i * 25.0)
        o = c - 15.0
        h = c + 5.0
        l = o - 2.0
        opens.append(o)
        highs.append(h)
        lows.append(l)
        closes.append(c)
        vols.append(150000)

    return pd.DataFrame(
        {"date": dates, "open": opens, "high": highs, "low": lows, "close": closes, "volume": vols}
    )


def test_find_swing_points(uptrend_df):
    swings = find_swing_points(uptrend_df, window=2)
    assert len(swings) >= 4
    high_count = sum(1 for s in swings if s.type == "HIGH")
    low_count = sum(1 for s in swings if s.type == "LOW")
    assert high_count >= 2
    assert low_count >= 2


def test_detect_order_blocks(uptrend_df):
    swings = find_swing_points(uptrend_df, window=2)
    demand_obs, supply_obs = detect_order_blocks(uptrend_df, swings)
    assert isinstance(demand_obs, list)
    assert isinstance(supply_obs, list)


def test_detect_fair_value_gaps(choch_reversal_df):
    fvgs = detect_fair_value_gaps(choch_reversal_df)
    assert isinstance(fvgs, list)
    bullish_fvgs = [f for f in fvgs if f.type == "BULLISH"]
    assert len(bullish_fvgs) >= 1


def test_analyze_market_structure_bullish(uptrend_df):
    report = analyze_market_structure("TEST_BULL", df=uptrend_df)
    assert report.symbol == "TEST_BULL"
    assert report.regime in ("BULLISH", "RANGING")
    assert report.nearest_support > 0
    assert report.nearest_resistance > report.nearest_support


def test_analyze_market_structure_choch(choch_reversal_df):
    report = analyze_market_structure("TEST_CHOCH", df=choch_reversal_df)
    assert report.symbol == "TEST_CHOCH"
    assert report.structure_score > 0 or report.choch_detected is True

