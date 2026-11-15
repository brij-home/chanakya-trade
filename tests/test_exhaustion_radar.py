# -*- coding: utf-8 -*-
"""
tests/test_exhaustion_radar.py
──────────────────────────────
Deterministic unit test suite for the Institutional Exhaustion Radar.
"""

from __future__ import annotations

import pandas as pd

from analysis.exhaustion_radar import (
    audit_headroom,
    compute_extension_zscore,
    evaluate_exhaustion,
    evaluate_vsa_climax,
)


def _create_sample_ohlcv(
    n_bars: int = 30,
    base_price: float = 24000.0,
    vol: float = 1000.0,
    spread: float = 20.0,
) -> pd.DataFrame:
    """Creates a deterministic OHLCV dataframe without synthetic randomness."""
    rows = []
    price = base_price
    for i in range(n_bars):
        o = price
        h = o + spread * 0.7
        l = o - spread * 0.3
        c = o + spread * 0.4
        rows.append({"open": o, "high": h, "low": l, "close": c, "volume": vol})
        price = c
    return pd.DataFrame(rows)


def test_extension_zscore_calculation():
    df = _create_sample_ohlcv(30, 24000.0, spread=50.0)
    # Price is 24200, VWAP is 24000, ATR is 50 -> Z_ext = 200 / 50 = 4.0
    z_ext = compute_extension_zscore(ltp=24200.0, vwap=24000.0, atr_val=50.0, df=df)
    assert round(z_ext, 1) == 4.0

    # Price at VWAP -> Z_ext = 0.0
    z_zero = compute_extension_zscore(ltp=24000.0, vwap=24000.0, atr_val=50.0, df=df)
    assert z_zero == 0.0


def test_vsa_buying_climax_detection():
    df = _create_sample_ohlcv(25, 24000.0, vol=1000.0, spread=40.0)
    # Add a buying climax bar: massive volume (3000), large upper wick
    # High: 25100, Open: 25000, Close: 25020 (Upper wick = 80, body = 20, range = 100)
    climax_bar = pd.DataFrame(
        [{"open": 25000.0, "high": 25100.0, "low": 24980.0, "close": 25020.0, "volume": 3000.0}]
    )
    df_climax = pd.concat([df, climax_bar], ignore_index=True)

    sig, is_dryup, flags = evaluate_vsa_climax(df_climax, direction="BULLISH", is_pullback=False)
    assert sig == "BUYING_CLIMAX"
    assert is_dryup is False
    assert any("Buying Climax Wick" in f for f in flags)


def test_vsa_volume_dryup_on_pullback():
    df = _create_sample_ohlcv(25, 24000.0, vol=1000.0, spread=40.0)
    # Pullback bar with very low volume (400 vs 1000 avg -> RVOL = 0.40x)
    dryup_bar = pd.DataFrame(
        [{"open": 24500.0, "high": 24510.0, "low": 24480.0, "close": 24490.0, "volume": 400.0}]
    )
    df_dryup = pd.concat([df, dryup_bar], ignore_index=True)

    sig, is_dryup, flags = evaluate_vsa_climax(df_dryup, direction="BULLISH", is_pullback=True)
    assert sig == "VOLUME_DRYUP"
    assert is_dryup is True


def test_vsa_high_volume_churn_on_pullback():
    df = _create_sample_ohlcv(25, 24000.0, vol=1000.0, spread=40.0)
    # Pullback bar with very high volume (2000 vs 1000 avg -> RVOL = 2.0x) - indicates distribution
    churn_bar = pd.DataFrame(
        [{"open": 24500.0, "high": 24510.0, "low": 24460.0, "close": 24470.0, "volume": 2000.0}]
    )
    df_churn = pd.concat([df, churn_bar], ignore_index=True)

    sig, is_dryup, flags = evaluate_vsa_climax(df_churn, direction="BULLISH", is_pullback=True)
    assert sig == "HIGH_VOL_CHURN"
    assert is_dryup is False


def test_audit_headroom_choked():
    # Long trade with entry = 24500, SL = 24450 (Risk = 50 pts).
    # Explicit barrier at 24530 (Headroom = 30 pts -> Multiple = 30 / 50 = 0.6R < 1.0R)
    headroom_pts, multiple, details = audit_headroom(
        symbol="NIFTY",
        direction="BULLISH",
        entry_price=24500.0,
        stop_loss=24450.0,
        explicit_barriers=[24530.0],
    )
    assert headroom_pts == 30.0
    assert multiple == 0.6


def test_audit_headroom_open_air():
    # Long trade with entry = 24500, SL = 24450 (Risk = 50 pts).
    # Explicit barrier far away at 24800 (Headroom = 300 pts -> Multiple = 6.0R)
    headroom_pts, multiple, details = audit_headroom(
        symbol="NIFTY",
        direction="BULLISH",
        entry_price=24500.0,
        stop_loss=24450.0,
        explicit_barriers=[24800.0],
    )
    assert headroom_pts == 300.0
    assert multiple == 6.0


def test_evaluate_exhaustion_pipeline_clean():
    df = _create_sample_ohlcv(25, 24000.0, vol=1000.0, spread=40.0)
    verdict = evaluate_exhaustion(
        symbol="NIFTY",
        direction="BULLISH",
        ltp=24050.0,
        entry_price=24050.0,
        stop_loss=24000.0,
        target_1=24200.0,
        df=df,
        vwap=24040.0,  # Z_ext = (24050 - 24040) / 40 = 0.25
    )
    assert verdict.is_exhausted is False
    assert verdict.severity == "NONE"
    assert verdict.recommended_action == "PROCEED"
    assert verdict.no_chase_limit > 24050.0


def test_evaluate_exhaustion_pipeline_veto_on_extension():
    df = _create_sample_ohlcv(25, 24000.0, vol=1000.0, spread=40.0)
    # LTP is 24250, VWAP is 24000 (Z_ext = 250 / 40 = 6.25 >= 2.5) -> Hard Veto
    verdict = evaluate_exhaustion(
        symbol="NIFTY",
        direction="BULLISH",
        ltp=24250.0,
        entry_price=24250.0,
        stop_loss=24200.0,
        target_1=24400.0,
        df=df,
        vwap=24000.0,
    )
    assert verdict.is_exhausted is True
    assert verdict.severity == "CRITICAL_VETO"
    assert verdict.recommended_action == "HARD_VETO"
    assert verdict.trap_type == "EXTENSION_CLIMAX"


def test_audit_headroom_round_strike_magnet():
    # Long trade with entry = 24485 (15 pts below round strike 24500), SL = 24440 (Risk = 45 pts).
    # The 24500 round number acts as a magnet/barrier -> Headroom = 15 pts -> 15/45 = 0.33R < 1.0R
    headroom_pts, multiple, details = audit_headroom(
        symbol="NIFTY",
        direction="BULLISH",
        entry_price=24485.0,
        stop_loss=24440.0,
    )
    assert headroom_pts == 15.0
    assert multiple < 1.0
    assert any("Psychological Round Strike Magnet" in d for d in details)


def test_evaluate_exhaustion_midday_lull():
    df = _create_sample_ohlcv(25, 24000.0, vol=1000.0, spread=40.0)
    # Entry at 12:15 IST (midday lull) without being a pullback -> demotes to LIMIT_PULLBACK_REQUIRED
    verdict = evaluate_exhaustion(
        symbol="NIFTY",
        direction="BULLISH",
        ltp=24050.0,
        entry_price=24050.0,
        stop_loss=24000.0,
        target_1=24200.0,
        df=df,
        vwap=24040.0,
        is_pullback=False,
        current_hour=12,
        current_minute=15,
    )
    assert verdict.recommended_action == "LIMIT_PULLBACK_REQUIRED"
    assert any("Midday Lull Window" in f for f in verdict.flags)
