"""
tests/test_delivery_accumulation.py
───────────────────────────────────
Unit tests for Cumulative Free-Float Absorption Index (CFAI) & Stealth Delivery Accumulation Engine.
"""

import numpy as np
import pandas as pd
import pytest

from analysis.delivery_accumulation import compute_cfai, CFAIReport


def _create_synthetic_accumulation_df(n_bars: int = 30) -> pd.DataFrame:
    """Creates a synthetic DataFrame representing an institutional consolidation base with rising delivery."""
    dates = pd.date_range("2026-08-01", periods=n_bars, freq="B")
    
    # Coiling price action between 1000 and 1050 (tightness ~5%)
    base_price = 1000.0
    noise = np.sin(np.linspace(0, 3 * np.pi, n_bars)) * 15.0
    closes = base_price + noise
    highs = closes + 5.0
    lows = closes - 5.0
    opens = closes - 2.0
    
    # Volume steady around 500k
    volumes = np.full(n_bars, 500_000.0)
    
    # Delivery starts at 35% and jumps to 65%-75% over the last 15 bars
    deliv_pcts = np.full(n_bars, 35.0)
    deliv_pcts[15:] = 68.0  # Massive accumulation phase!
    
    return pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        "delivery_pct": deliv_pcts,
    }, index=dates)


def test_cfai_stealth_accumulation_detected():
    df = _create_synthetic_accumulation_df(n_bars=30)
    
    report = compute_cfai(
        symbol="MAZDOCK",
        df=df,
        total_shares=100_000_000,
        promoter_holding_pct=60.0,  # Free float = 40M shares
        ltp=1010.0,
    )

    assert isinstance(report, CFAIReport)
    assert report.symbol == "MAZDOCK"
    assert report.ltp == 1010.0
    assert report.current_delivery_pct == 68.0
    assert report.is_delivery_spike is True
    assert report.cfai_pct > 3.0  # Demonstrates significant float absorption
    assert report.float_exhaustion_detected is True
    assert report.verdict in ("HIGH_STEALTH_ACCUMULATION", "MODERATE_ABSORPTION")
    assert report.accumulation_score >= 75
    assert len(report.insights) >= 2


def test_cfai_minimal_fallback_no_crash():
    report = compute_cfai(symbol="TRENT", df=None, ltp=7200.0)
    assert report.symbol == "TRENT"
    assert report.ltp == 7200.0
    assert report.verdict == "NEUTRAL"
    assert report.float_exhaustion_detected is False


def test_cfai_distribution_detection():
    # Construct a distribution pattern: High volume, high delivery, but closing near lows
    n_bars = 25
    closes = np.linspace(1000, 950, n_bars)
    lows = closes - 1.0  # Close right at bottom
    highs = closes + 20.0
    opens = highs - 2.0
    volumes = np.full(n_bars, 1_000_000.0)
    deliv_pcts = np.full(n_bars, 65.0)  # Heavy delivery dumping

    df = pd.DataFrame({
        "open": opens, "high": highs, "low": lows, "close": closes,
        "volume": volumes, "delivery_pct": deliv_pcts
    })

    report = compute_cfai("ABC", df=df, ltp=950.0)
    assert report.symbol == "ABC"
    # Should penalize closing at day's low with heavy delivery
    assert report.accumulation_score < 70
