# -*- coding: utf-8 -*-
"""
tests/test_initial_balance_and_sfp.py
─────────────────────────────────────
Test suite for Dalton Market Profile Initial Balance (IB) calculation,
Day Archetype classification, Swing Failure Pattern (SFP / 2B) reversals,
and the automated Initial Balance detector.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd

from engine.daily_levels import calculate_initial_balance
from engine.detectors.initial_balance import detect_initial_balance_setups

IST = ZoneInfo("Asia/Kolkata")


def _generate_synthetic_5m_bars(
    session_date: str = "2026-10-30",
    ib_high: float = 24500.0,
    ib_low: float = 24400.0,
    post_ib_moves: list[tuple[float, float, float, float]] | None = None,
) -> pd.DataFrame:
    """
    Generates 5-minute bars from 09:15 to 15:25 IST.
    09:15 to 10:15 (12 bars) forms the Initial Balance within [ib_low, ib_high].
    """
    timestamps = pd.date_range(
        start=f"{session_date} 09:15:00",
        end=f"{session_date} 15:25:00",
        freq="5min",
        tz=IST,
    )
    rows = []
    span = ib_high - ib_low
    # 1. 09:15 - 10:15 (first 12 bars)
    for i in range(12):
        ts = timestamps[i]
        frac1 = (i % 4) / 4.0
        frac2 = ((i + 1) % 4) / 4.0
        o = ib_low + span * frac1
        c = ib_low + span * frac2
        h = ib_high if i == 5 else max(o, c)
        l = ib_low if i == 2 else min(o, c)
        rows.append({"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "volume": 10000})

    # 2. Post-IB bars (from 10:15 onward)
    default_post = [
        (ib_low + span * 0.5, ib_low + span * 0.6, ib_low + span * 0.4, ib_low + span * 0.5)
    ] * (len(timestamps) - 12)
    moves = post_ib_moves if post_ib_moves is not None else default_post

    for i, (o, h, l, c) in enumerate(moves):
        idx = 12 + i
        if idx < len(timestamps):
            ts = timestamps[idx]
            rows.append(
                {"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "volume": 12000}
            )

    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def test_initial_balance_normal_day_archetype():
    """Initial Balance wider than 1.25x ATR indicates wide range Normal Day."""
    df = _generate_synthetic_5m_bars(ib_high=24600.0, ib_low=24300.0)
    # Range is 300 pts. ATR is 200 pts. Baseline avg IB = 200 * 0.42 = 84 pts. Ratio = 300/84 = 3.57x (> 1.25x -> NORMAL_DAY)
    ib = calculate_initial_balance(
        df_5m=df, session_date="2026-10-30", atr_14=200.0, current_spot=24450.0
    )

    assert ib.ib_high == 24600.0
    assert ib.ib_low == 24300.0
    assert ib.ib_range_pts == 300.0
    assert ib.ib_midpoint == 24450.0
    assert ib.day_archetype == "NORMAL_DAY"
    assert ib.relative_ib_ratio == 3.57
    assert ib.is_ib_complete is True


def test_initial_balance_trend_day_archetype():
    """Initial Balance narrower than 0.65x ATR indicates coiled Trend Day."""
    df = _generate_synthetic_5m_bars(ib_high=24450.0, ib_low=24400.0)
    # Range is 50 pts. ATR is 200 pts. Baseline avg IB = 200 * 0.42 = 84 pts. Ratio = 50/84 = 0.60x (< 0.65x -> TREND_DAY)
    ib = calculate_initial_balance(
        df_5m=df, session_date="2026-10-30", atr_14=200.0, current_spot=24425.0
    )

    assert ib.ib_high == 24450.0
    assert ib.ib_low == 24400.0
    assert ib.ib_range_pts == 50.0
    assert ib.day_archetype == "TREND_DAY"
    assert ib.relative_ib_ratio == 0.60


def test_initial_balance_bearish_sfp_reversal():
    """
    Spot sweeps above IB High by +0.24% (< +0.45%), but fails to accept
    and closes back inside IB -> IBH_SWING_FAILURE.
    """
    post_moves = [
        (24490.0, 24560.0, 24470.0, 24480.0),
        (24480.0, 24490.0, 24460.0, 24475.0),
    ] + [(24475.0, 24485.0, 24465.0, 24470.0)] * 50

    df = _generate_synthetic_5m_bars(ib_high=24500.0, ib_low=24400.0, post_ib_moves=post_moves)
    ib = calculate_initial_balance(
        df_5m=df, session_date="2026-10-30", atr_14=120.0, current_spot=24475.0
    )

    assert ib.extension_status == "IBH_SWING_FAILURE"
    assert ib.extension_target_1 == ib.ib_midpoint  # 24450
    assert ib.extension_target_2 == ib.ib_low  # 24400
    assert "BEARISH SFP FAKEOUT" in ib.fade_recommendation


def test_initial_balance_bullish_sfp_reversal():
    """
    Spot sweeps below IB Low by -0.25% (<= -0.45%), but closes back inside IB -> IBL_SWING_FAILURE.
    """
    post_moves = [
        (24410.0, 24420.0, 24340.0, 24425.0),
    ] + [(24425.0, 24440.0, 24420.0, 24430.0)] * 50

    df = _generate_synthetic_5m_bars(ib_high=24500.0, ib_low=24400.0, post_ib_moves=post_moves)
    ib = calculate_initial_balance(
        df_5m=df, session_date="2026-10-30", atr_14=120.0, current_spot=24430.0
    )

    assert ib.extension_status == "IBL_SWING_FAILURE"
    assert ib.extension_target_1 == ib.ib_midpoint  # 24450
    assert ib.extension_target_2 == ib.ib_high  # 24500
    assert "BULLISH SFP BEAR TRAP" in ib.fade_recommendation


def test_detect_initial_balance_setups_alert_generation():
    """
    Detector should create fully actionable AutoAlert for an SFP setup with
    deterministic alert ID and institutional blueprint.
    """
    post_moves = [
        (24490.0, 24560.0, 24470.0, 24480.0),
    ] + [(24480.0, 24485.0, 24470.0, 24475.0)] * 20

    df = _generate_synthetic_5m_bars(ib_high=24500.0, ib_low=24400.0, post_ib_moves=post_moves)
    test_time = datetime(2026, 10, 30, 10, 30, tzinfo=IST)

    alerts = detect_initial_balance_setups(
        symbol="NIFTY",
        spot=24475.0,
        df_5m=df,
        atr_14=120.0,
        ref_time=test_time,
        ignore_time_gate=True,
    )

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.symbol == "NIFTY"
    assert alert.alert_type == "INITIAL_BALANCE_SFP"
    assert alert.direction == "BEARISH"
    assert alert.option_type == "PE"
    assert "IBH_SWING_FAILURE" in alert.metrics["extension_status"]
    assert alert.actionable_plan is not None
    assert alert.actionable_plan["entry_zone"] is not None
    assert alert.actionable_plan["invalidation_stop_loss"] > 24475.0
    assert alert.actionable_plan["target_1"] == 24450.0  # Midpoint
    assert alert.actionable_plan["target_2"] == 24400.0  # IB Low
    assert alert.alert_id.startswith("aa-initial-balance-sfp-nifty-")
