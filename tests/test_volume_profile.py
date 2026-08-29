"""
tests/test_volume_profile.py
────────────────────────────
Unit tests for Volume Profile, RVOL & Volume Spread Analysis (VSA) engine.
Runs offline using deterministic synthetic OHLCV data.
"""

import numpy as np
import pandas as pd
import pytest

from analysis.volume_profile import (
    analyze_volume_profile,
    analyze_vsa,
    compute_volume_profile,
)


@pytest.fixture
def volume_surge_df():
    dates = pd.date_range(start="2025-01-01", periods=30, freq="D")
    opens, highs, lows, closes, vols = [], [], [], [], []

    for i in range(29):
        c = 500.0 + i * 2.0
        o = c - 1.0
        h = c + 3.0
        l = o - 2.0
        opens.append(o)
        highs.append(h)
        lows.append(l)
        closes.append(c)
        vols.append(50000)

    # 30th bar: Massive volume surge with wide spread close at high
    c = 580.0
    o = 560.0
    h = 582.0
    l = 558.0
    opens.append(o)
    highs.append(h)
    lows.append(l)
    closes.append(c)
    vols.append(150000)  # 3x volume surge

    return pd.DataFrame(
        {"date": dates, "open": opens, "high": highs, "low": lows, "close": closes, "volume": vols}
    )


def test_compute_volume_profile(volume_surge_df):
    poc, vah, val, buckets = compute_volume_profile(volume_surge_df, num_bins=8)
    assert poc > 0
    assert vah >= poc >= val
    assert len(buckets) == 8
    assert any(b.is_poc for b in buckets)


def test_analyze_vsa(volume_surge_df):
    signals = analyze_vsa(volume_surge_df)
    assert isinstance(signals, list)
    assert any(s.bias == "BULLISH" for s in signals)


def test_analyze_volume_profile_report(volume_surge_df):
    report = analyze_volume_profile("SURGE_STOCK", df=volume_surge_df)
    assert report.symbol == "SURGE_STOCK"
    assert report.rvol_20d >= 2.0
    assert report.volume_tier in ("HIGH", "ULTRA_HIGH")
    assert report.poc_price > 0
    assert report.footprint_bias in ("ACCUMULATION", "NEUTRAL")
