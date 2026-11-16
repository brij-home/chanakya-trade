"""
tests/test_proactive_confluence_and_pullback_engine.py
──────────────────────────────────────────────────────
Institutional test suite validating the shift from defensive vetoes
to proactive asymmetric confluence, multi-bar opening ignition,
pullback-to-value limit entry resolution, and trapped liquidity inversion.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd

from engine.detectors.opening_drive import detect_opening_drive
from engine.detectors.liquidity_inversion import detect_liquidity_inversion
from engine.pullback_level_resolver import resolve_pullback_entry, PullbackLevelPlan
from engine.confluence_engine import evaluate_confluence

IST = ZoneInfo("Asia/Kolkata")


def test_opening_drive_multi_bar_ignition_catches_bar_1_runner():
    """
    Validates that when Bar 0 is an uncrossing consolidation, and Bar 1 (09:20-09:25 IST)
    ignites with an Open == Low breakout above Bar 0 high, OpeningDrive detects it as an IGNITION_BAR_1.
    """
    dates = [
        datetime(2026, 11, 16, 9, 15, tzinfo=IST),
        datetime(2026, 11, 16, 9, 20, tzinfo=IST),
    ]
    # Bar 0: Small consolidation (open 530, low 528.5 -> low_diff 0.28% > 0.15%, high 532, close 531)
    # Bar 1: Explosive ignition (open 531, low 531.0 -> Open == Low!, high 541, close 540)
    df_5m = pd.DataFrame(
        {
            "open": [530.0, 531.0],
            "high": [532.0, 541.0],
            "low": [528.5, 531.0],
            "close": [531.0, 540.0],
            "volume": [50000.0, 350000.0],
        },
        index=dates,
    )

    alert = detect_opening_drive(
        symbol="KALYANKJIL",
        df_5m=df_5m,
        ltp=540.0,
        vwap=535.0,
        rvol=2.8,
        ref_time=datetime(2026, 11, 16, 9, 23, tzinfo=IST),
        prev_close=526.0,
        prev_high=532.0,
        prev_low=518.0,
        ignore_time_gate=True,
    )

    assert alert is not None
    assert alert.direction == "BULLISH"
    assert "KALYANKJIL" in alert.symbol
    assert alert.metrics.get("matched_bar_idx") == 1
    assert alert.metrics.get("open_pattern") == "IGNITION_BAR_1"
    assert alert.metrics.get("bar_open") == 531.0
    assert alert.underlying_spot == 540.0
    # Must attach pullback limit zone
    assert "limit_entry_zone" in alert.actionable_plan


def test_opening_drive_multi_bar_breakdown_catches_bar_1_liquidation():
    """
    Validates that when Bar 1 breaks down below Bar 0 low with Open == High,
    OpeningDrive detects it as a BREAKDOWN_BAR_1.
    """
    dates = [
        datetime(2026, 11, 16, 9, 15, tzinfo=IST),
        datetime(2026, 11, 16, 9, 20, tzinfo=IST),
    ]
    df_5m = pd.DataFrame(
        {
            "open": [270.0, 269.0],
            "high": [271.0, 269.0],  # Open == High on Bar 1
            "low": [268.0, 262.0],
            "close": [269.0, 263.0],
            "volume": [80000.0, 450000.0],
        },
        index=dates,
    )

    alert = detect_opening_drive(
        symbol="TMPV",
        df_5m=df_5m,
        ltp=263.0,
        vwap=266.5,
        rvol=3.1,
        ref_time=datetime(2026, 11, 16, 9, 23, tzinfo=IST),
        prev_close=274.0,
        prev_high=276.0,
        prev_low=269.5,
        ignore_time_gate=True,
    )

    assert alert is not None
    assert alert.direction == "BEARISH"
    assert "TMPV" in alert.symbol
    assert alert.metrics.get("matched_bar_idx") == 1
    assert alert.metrics.get("open_pattern") == "BREAKDOWN_BAR_1"
    assert alert.underlying_spot == 263.0


def test_pullback_level_resolver_bullish():
    """
    Validates that resolve_pullback_entry computes an institutional limit entry band
    anchored to VWAP and Fibonacci OTE, preventing breakout chasing at CMP.
    """
    plan = resolve_pullback_entry(
        symbol="KALYANKJIL",
        direction="BULLISH",
        spot=542.0,
        vwap=537.5,
        day_high=543.0,
        day_low=530.0,
        atr_5m=3.5,
        prefer_options=False,
    )

    assert isinstance(plan, PullbackLevelPlan)
    assert plan.direction == "BULLISH"
    # Entry zone must be discounted below current market peak (542.0)
    assert plan.entry_zone_mid < 542.0
    assert plan.entry_zone_min >= 530.0
    # Invalidation stop must be below entry zone and below or near VWAP
    assert plan.stop_loss < plan.entry_zone_mid
    assert plan.stop_loss <= plan.vwap
    # R:R must be mathematically asymmetric
    assert plan.rr_t1 >= 1.8
    assert plan.rr_t2 >= 3.5
    assert plan.no_chase_price > plan.day_high if hasattr(plan, "day_high") else True


def test_pullback_level_resolver_bearish():
    """
    Validates bearish pullback (bounce) limit entry level calculation.
    """
    plan = resolve_pullback_entry(
        symbol="TMPV",
        direction="BEARISH",
        spot=263.0,
        vwap=266.0,
        day_high=272.0,
        day_low=262.0,
        atr_5m=2.0,
        prefer_options=False,
    )

    assert plan.direction == "BEARISH"
    # Entry zone must be a bounce above current low (263.0) towards VWAP
    assert plan.entry_zone_mid > 263.0
    assert plan.stop_loss > plan.entry_zone_mid
    assert plan.stop_loss >= plan.vwap
    assert plan.target_1 < plan.entry_zone_mid
    assert plan.rr_t1 >= 1.8


def test_liquidity_inversion_converts_bear_trap_into_bullish_alert():
    """
    Validates that a failed bearish sweep on a strong leader holding above VWAP
    is converted into a high-conviction BULLISH LIQUIDITY_INVERSION alert (Short Squeeze).
    """
    dates = [
        datetime(2026, 11, 16, 9, 20, tzinfo=IST),
        datetime(2026, 11, 16, 9, 25, tzinfo=IST),
        datetime(2026, 11, 16, 9, 30, tzinfo=IST),
    ]
    df = pd.DataFrame(
        {
            "open": [535.0, 538.0, 539.0],
            "high": [539.0, 542.0, 541.5],
            "low": [534.5, 537.0, 538.5],
            "close": [538.0, 539.5, 541.0],
            "volume": [100000, 150000, 180000],
        },
        index=dates,
    )

    alert = detect_liquidity_inversion(
        symbol="KALYANKJIL",
        df=df,
        ltp=541.0,
        vwap=537.0,  # Firmly above VWAP
        change_pct=2.85,  # Strong leader
        rvol=2.2,
        failed_sweep_type="BEARISH_UPTHRUST",
        day_high=542.0,
        day_low=530.0,
    )

    assert alert is not None
    assert alert.direction == "BULLISH"
    assert alert.alert_type == "LIQUIDITY_INVERSION"
    assert alert.metrics.get("variant") == "BEAR_TRAP_SQUEEZE"
    assert "Bear Trap Short Squeeze" in alert.headline
    assert alert.actionable_plan.get("entry_type") == "PULLBACK_LIMIT_ZONE"


def test_confluence_engine_scores_high_on_aligned_market_leader():
    """
    Validates that a market leader with pre-open gap, volume acceleration, VWAP alignment,
    leading sector, and derivatives Put writing scores >= 75 and qualifies as an ARMED setup.
    """
    report = evaluate_confluence(
        symbol="KALYANKJIL",
        direction="BULLISH",
        ltp=541.0,
        vwap=537.0,
        rvol=2.4,
        change_pct=2.85,
        pre_open_gap_pct=1.45,
        sector_quadrant="LEADING",
        call_oi_change_pct=-12.0,  # Call unwinding
        put_oi_change_pct=22.0,  # Massive Put writing
        market_structure_signal="BOS",
        day_high=542.0,
        day_low=530.0,
    )

    assert report.is_qualified is True
    assert report.total_score >= 80.0
    assert report.direction == "BULLISH"
    assert report.pullback_plan is not None
    assert len(report.factors) == 6
    # All major factors confirmed
    confirmed_factors = [f for f in report.factors if f.status == "CONFIRMED"]
    assert len(confirmed_factors) >= 5


def test_confluence_engine_rejects_choppy_unaligned_symbol():
    """
    Validates that an unaligned, low-volume, choppy symbol scores < 60 and fails qualification.
    """
    report = evaluate_confluence(
        symbol="FLATSTOCK",
        direction="BULLISH",
        ltp=500.0,
        vwap=501.5,  # Submerged below VWAP
        rvol=0.7,  # Low volume
        change_pct=0.10,
        pre_open_gap_pct=0.0,
        sector_quadrant="LAGGING",
        call_oi_change_pct=30.0,  # Heavy Call writing overhead
        put_oi_change_pct=-5.0,
        market_structure_signal=None,
    )

    assert report.is_qualified is False
    assert report.total_score < 50.0
