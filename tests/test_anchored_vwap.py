"""
tests/test_anchored_vwap.py
───────────────────────────
Unit tests for analysis.anchored_vwap calculations, volatility bands, and anchor detection.
"""

import numpy as np
import pandas as pd
import pytest
from analysis.anchored_vwap import (
    compute_anchored_vwap,
    detect_structural_anchors,
    AnchoredVWAPResult,
)


@pytest.fixture
def synthetic_ohlcv():
    np.random.seed(42)
    n = 50
    dates = pd.date_range("2026-08-01", periods=n, freq="D")
    base_price = 100.0
    drift = np.linspace(0, 20, n)
    noise = np.random.normal(0, 1.5, n)
    closes = base_price + drift + noise
    highs = closes + np.random.uniform(0.5, 2.0, n)
    lows = closes - np.random.uniform(0.5, 2.0, n)
    volumes = np.random.uniform(10000, 50000, n)

    # Insert a volume spike at bar 25
    volumes[25] = 180000

    df = pd.DataFrame(
        {
            "date": dates,
            "open": closes - 0.2,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )
    return df


def test_compute_anchored_vwap_calculates_bands(synthetic_ohlcv):
    res = compute_anchored_vwap(synthetic_ohlcv, anchor_index=10, anchor_type="SWING_LOW")
    assert res is not None
    assert isinstance(res, AnchoredVWAPResult)
    assert res.current_avwap > 0
    assert res.upper_band_1 > res.current_avwap
    assert res.lower_band_1 < res.current_avwap
    assert res.upper_band_2 > res.upper_band_1
    assert res.lower_band_2 < res.lower_band_1
    assert res.confluence_status in (
        "AT_SUPPORT_BOUNCE",
        "AT_RESISTANCE_REJECTION",
        "ABOVE_BULLISH",
        "BELOW_BEARISH",
    )


def test_detect_structural_anchors_finds_anchors(synthetic_ohlcv):
    anchors = detect_structural_anchors(synthetic_ohlcv)
    assert len(anchors) >= 1
    anchor_types = [a.anchor_type for a in anchors]
    assert any("SWING" in t or "CATALYST" in t for t in anchor_types)
