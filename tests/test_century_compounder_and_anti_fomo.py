"""
tests/test_century_compounder_and_anti_fomo.py
──────────────────────────────────────────────
Deterministic unit and integration tests for:
  1. Century Compounder Twin Engines Math & 7 Pillars (analysis/century_compounder.py)
  2. Anti-FOMO Fair Value Accumulation Blueprint & No-Chase Limits
  3. Pre-Inflection Volume Dry-Up Detector (engine/detectors/pre_inflection_dryup.py)
  4. AutoAlertEngine Pre-Inflection & Incubation Integration
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analysis.century_compounder import (
    calculate_twin_engines,
    evaluate_century_compounder,
    scan_century_compounders,
)
from engine.detectors.pre_inflection_dryup import detect_pre_inflection_dryup


def _build_synthetic_coiling_df(n: int = 50, dry_up: bool = True) -> pd.DataFrame:
    """Generates synthetic daily OHLCV dataframe with dry-up or expansion volume."""
    base_price = 500.0
    dates = pd.date_range("2026-01-01", periods=n, freq="B")
    
    # Flat horizontal coiling price
    closes = [base_price + (i % 3) * 1.5 - 1.0 for i in range(n)]
    highs = [c + 2.0 for c in closes]
    lows = [c - 2.0 for c in closes]
    
    # 50-day average volume = 100,000
    volumes = [100000.0] * n
    if dry_up:
        # Last 5 days volume dries up to 25,000 (25% of average)
        for i in range(1, 6):
            volumes[-i] = 25000.0
            # Narrow range
            highs[-i] = closes[-i] + 0.8
            lows[-i] = closes[-i] - 0.8
            
    return pd.DataFrame({
        "date": dates,
        "open": closes,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })


def test_twin_engines_calculation_century_tier():
    """Verify Twin Engines mathematical compounding formula produces expected multipliers."""
    # Microcap ₹1,500 Cr with P/E 18x, 26% sales growth, 28% ROCE, completed capex
    fe = calculate_twin_engines(
        market_cap_cr=1500.0,
        pe=18.0,
        sales_growth_pct=26.0,
        pat_margin_pct=16.0,
        roce_pct=28.0,
        gross_block_growth_pct=30.0,
        tam_cr=200000.0,
    )
    
    # PE re-rating: from 18x to 55x terminal PE = ~3.06x
    assert fe.pe_expansion_multiple >= 2.5
    # Operating leverage boost: 26% sales growth -> ~37.7% PAT CAGR -> 10Y ~27x to 35x PAT expansion
    assert fe.pat_expansion_multiple >= 15.0
    # Total multiple = PAT multiple * PE multiple
    assert fe.total_projected_multiple >= 50.0
    assert fe.compounder_tier in ("100X_CENTURY", "1000X_POTENTIAL")
    assert fe.target_market_cap_cr > fe.current_market_cap_cr


def test_evaluate_century_compounder_pillars():
    """Test 7-pillar evaluation and anti-FOMO execution blueprint."""
    df = _build_synthetic_coiling_df(40, dry_up=True)
    report = evaluate_century_compounder("TRENT", df=df, ltp=500.0)
    
    assert report.symbol == "TRENT"
    assert report.century_score >= 60
    assert report.runway_score >= 0
    assert report.reinvestment_score >= 0
    assert report.operating_leverage_score >= 0
    assert len(report.pillar_notes) > 0
    
    # Anti-FOMO Blueprint Checks
    af = report.anti_fomo
    assert af.fair_value_anchor > 0
    assert af.accumulate_low < af.accumulate_high
    assert af.no_chase_boundary > af.pivot_trigger
    # Price is right around 500, so it should be in prime accumulation or stalking
    assert af.action_directive in ("ACCUMULATE_FAIR_VALUE", "STALK_PIVOT", "WAIT_FOR_PULLBACK")


def test_detect_pre_inflection_dryup_success():
    """Test that pre-inflection detector triggers when volume contracts and range squeezes."""
    df = _build_synthetic_coiling_df(50, dry_up=True)
    ltp = float(df["close"].iloc[-1])
    
    alert = detect_pre_inflection_dryup("KAYNES", df=df, ltp=ltp)
    assert alert is not None
    assert alert.alert_type == "PRE_INFLECTION_DRYUP"
    assert alert.stage == "EARLY_WARNING"
    assert "PRE-INFLECTION DRY-UP" in alert.headline
    assert alert.confidence >= 70
    
    plan = alert.actionable_plan
    assert "entry_range" in plan
    assert "do_not_chase_above" in plan
    assert "pullback_limit_order" in plan
    assert "anti_fomo_rule" in plan


def test_detect_pre_inflection_dryup_rejection_on_expansion():
    """Test that high-volume or wide-swing assets are rejected (no premature alert)."""
    # Create non-dryup high-volume DataFrame
    df = _build_synthetic_coiling_df(50, dry_up=False)
    # Add huge volatility and volume in last 3 bars
    for i in range(1, 4):
        df.loc[df.index[-i], "volume"] = 300000.0  # 3x volume
        df.loc[df.index[-i], "high"] = df.loc[df.index[-i], "close"] + 25.0  # 5% daily range
        df.loc[df.index[-i], "low"] = df.loc[df.index[-i], "close"] - 25.0
        
    ltp = float(df["close"].iloc[-1])
    alert = detect_pre_inflection_dryup("VOLATILE_SYM", df=df, ltp=ltp)
    assert alert is None, "Should reject assets with high volume and wide price swings"


def test_scan_century_compounders_deterministic():
    """Verify scanning returns ranked compounders without exceptions."""
    results = scan_century_compounders(universe=["TRENT", "DIXON", "KAYNES"], min_score=50, top_n=3)
    assert isinstance(results, list)
    assert len(results) > 0
    top = results[0]
    assert top.century_score >= 50
    assert top.twin_engines.total_projected_multiple > 1.0
