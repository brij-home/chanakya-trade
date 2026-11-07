"""
tests/test_mtf_and_pullback_engine.py
─────────────────────────────────────
Unit tests for Institutional Pullback Engine and MTF Cascade (HTF -> ITF -> LTF).
"""

import pandas as pd

from analysis.pullback_engine import evaluate_pullback
from analysis.mtf_cascade import (
    evaluate_htf_bias,
    evaluate_itf_location,
    run_mtf_cascade,
    MTFCascadeVerdict,
)


def _generate_synthetic_trend(
    n: int = 50, start: float = 24000.0, step: float = 15.0
) -> pd.DataFrame:
    """Generates an upward trending OHLCV dataframe."""
    dates = pd.date_range("2026-01-01 09:15", periods=n, freq="5min")
    closes = [start + i * step for i in range(n)]
    return pd.DataFrame(
        {
            "open": [c - 5.0 for c in closes],
            "high": [c + 12.0 for c in closes],
            "low": [c - 10.0 for c in closes],
            "close": closes,
            "volume": [1000 + i * 20 for i in range(n)],
        },
        index=dates,
    )


def test_bullish_pullback_with_volume_dryup():
    """Verify that a shallow pullback into 20 EMA with dry-up volume generates a confirmed BULLISH pullback signal."""
    # 25 bars: strong upward impulse from 24000 to 24500
    df = _generate_synthetic_trend(n=25, start=24000.0, step=20.0)

    # Next 3 bars: pullback into EMA20 with dry-up volume (volume 300 vs 1500 avg)
    last_close = df["close"].iloc[-1]
    pullback_rows = [
        {
            "open": last_close,
            "high": last_close + 5.0,
            "low": last_close - 25.0,
            "close": last_close - 20.0,
            "volume": 350.0,
        },
        {
            "open": last_close - 20.0,
            "high": last_close - 15.0,
            "low": last_close - 45.0,
            "close": last_close - 40.0,
            "volume": 300.0,
        },
        # Re-ignition candle: green hammer reclaiming
        {
            "open": last_close - 40.0,
            "high": last_close - 10.0,
            "low": last_close - 50.0,
            "close": last_close - 12.0,
            "volume": 1400.0,
        },
    ]
    df_combined = pd.concat([df, pd.DataFrame(pullback_rows)]).reset_index(drop=True)

    sig = evaluate_pullback(df_combined, symbol="NIFTY", breakout_level=24440.0)
    assert sig is not None
    assert sig.bias == "BULLISH"
    assert sig.confidence >= 75
    assert sig.is_volume_dryup is True
    assert sig.target_1 > sig.entry_zone[1]
    assert sig.stop_loss < sig.entry_zone[0]


def test_htf_bias_evaluation():
    """Verify Daily HTF bias classifies Stage 2 Markup in strong trend."""
    df_daily = _generate_synthetic_trend(n=60, start=20000.0, step=50.0)
    htf = evaluate_htf_bias(df_daily)
    assert htf.bias in ("STRONG_BULLISH", "MILD_BULLISH")
    assert htf.stage == "STAGE_2_MARKUP"
    assert htf.ema20_above_ema50 is True
    assert htf.price_above_ema200 is True


def test_itf_overextended_no_chase():
    """Verify ITF identifies overextended price where buying is vetoed."""
    df_itf = _generate_synthetic_trend(n=35, start=24000.0, step=25.0)
    itf = evaluate_itf_location(df_itf, htf_bias="STRONG_BULLISH")
    assert itf.location == "OVEREXTENDED"
    assert itf.is_safe_entry_zone is False


def test_mtf_cascade_overextension_veto():
    """Verify run_mtf_cascade prevents chasing when ITF is overextended."""
    df_d = _generate_synthetic_trend(n=60, start=20000.0, step=50.0)
    df_15 = _generate_synthetic_trend(n=35, start=24000.0, step=25.0)
    df_5 = _generate_synthetic_trend(n=20, start=24800.0, step=10.0)

    verdict: MTFCascadeVerdict = run_mtf_cascade(
        symbol="NIFTY",
        df_daily=df_d,
        df_15m=df_15,
        df_5m=df_5,
    )
    assert verdict.overall_alignment == "OVEREXTENDED_NO_CHASE"
    assert verdict.position_size_multiplier == 0.0
    assert "DO NOT CHASE" in verdict.recommended_action
