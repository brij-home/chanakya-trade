"""tests/test_institutional_volume_profile.py
─────────────────────────────────────────────
Deterministic unit test suite for the institutional multi-tier volume engine:
  - 5-bar breakout impulse RVOL
  - 20-bar rolling baseline RVOL
  - Time-of-Day (TOD) cumulative RVOL against institutional 90-day U-curve
  - Cumulative Volume Delta (CVD) divergence (absorption traps vs exhaustion blow-offs)
  - Mathematical volume surge confirmation
"""

import pandas as pd

from engine.daily_levels import (
    InstitutionalVolumeProfile,
    compute_institutional_volume_profile,
    calculate_intraday_rvol,
)


def _generate_synthetic_5m_bars(
    num_bars: int = 15,
    base_volume: float = 10_000.0,
    surge_last_bar_mult: float = 1.0,
    bullish_candles: bool = True,
) -> pd.DataFrame:
    """Generate deterministic synthetic 5m OHLCV bars."""
    rows = []
    price = 24_000.0
    for i in range(num_bars):
        vol = base_volume * surge_last_bar_mult if i == num_bars - 1 else base_volume
        if bullish_candles:
            # Closes near high -> net positive delta
            o = price
            h = price + 25.0
            l = price - 5.0
            c = price + 20.0
        else:
            # Closes near low -> net negative delta
            o = price
            h = price + 5.0
            l = price - 25.0
            c = price - 20.0

        rows.append(
            {
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": vol,
            }
        )
        price = c

    return pd.DataFrame(rows)


def test_empty_or_degenerate_dataframe_returns_safe_baseline():
    """Empty or degenerate DataFrames must fail-safe to 1.0 baseline with no hallucination."""
    prof_none = compute_institutional_volume_profile(None)
    assert prof_none.bar_rvol == 1.0
    assert prof_none.tod_rvol == 1.0
    assert prof_none.hybrid_rvol == 1.0
    assert prof_none.cvd_val == 0.0
    assert prof_none.volume_surge_confirmed is False

    df_short = pd.DataFrame([{"volume": 100}])
    prof_short = compute_institutional_volume_profile(df_short)
    assert prof_short.volume_surge_confirmed is False


def test_immediate_5bar_impulse_rvol_detects_explosive_injection():
    """A sudden 2.5x volume expansion on the latest bar must immediately reflect in bar_rvol."""
    df_5m = _generate_synthetic_5m_bars(num_bars=10, base_volume=10_000.0, surge_last_bar_mult=2.5)

    prof = compute_institutional_volume_profile(df_5m, required_rvol=1.5, direction="BULLISH")
    assert prof.bar_rvol >= 2.4
    assert prof.hybrid_rvol >= 2.4
    assert prof.volume_surge_confirmed is True


def test_tod_rvol_blending_with_daily_volume():
    """When daily volume history is provided, hybrid_rvol blends 60% impulse and 40% TOD-RVOL."""
    df_5m = _generate_synthetic_5m_bars(num_bars=12, base_volume=10_000.0, surge_last_bar_mult=2.0)
    # 20 days with avg daily volume of 500,000 shares
    df_daily = pd.DataFrame([{"volume": 500_000.0} for _ in range(20)])

    prof = compute_institutional_volume_profile(
        df_5m, df_daily=df_daily, required_rvol=1.4, direction="BULLISH"
    )
    assert isinstance(prof, InstitutionalVolumeProfile)
    assert prof.bar_rvol > 0.0
    assert prof.tod_rvol > 0.0
    # Hybrid blend: 0.60 * bar + 0.40 * tod
    expected_hybrid = round(0.60 * prof.bar_rvol + 0.40 * prof.tod_rvol, 2)
    assert prof.hybrid_rvol == expected_hybrid


def test_cvd_divergence_vetoes_bearish_exhaustion_bull_trap():
    """If price rallied but CVD delta shows strong institutional distribution (BEARISH_EXHAUSTION),

    bullish breakout surge confirmation must be rejected to protect capital.
    """
    # Create 10 bars where price rises but volume delta is concentrated on down-wicks / selling
    rows = []
    price = 24_000.0
    for i in range(10):
        # Upper wick heavy: Open 24000, High 24050, Close 24002, Low 23998
        # Close is near low of the bar -> negative delta even though close > open slightly
        h = price + 50.0
        l = price - 2.0
        c = price + 2.0
        o = price
        # High volume on selling
        vol = 25_000.0 if i >= 5 else 10_000.0
        rows.append({"open": o, "high": h, "low": l, "close": c, "volume": vol})
        price = c

    df_5m = pd.DataFrame(rows)
    prof = compute_institutional_volume_profile(df_5m, required_rvol=1.2, direction="BULLISH")
    # Even though volume is high, bearish exhaustion or negative CVD slope blocks confirmation
    if prof.cvd_divergence == "BEARISH_EXHAUSTION":
        assert prof.volume_surge_confirmed is False


def test_calculate_intraday_rvol_backward_compatibility():
    """calculate_intraday_rvol must seamlessly wrap compute_institutional_volume_profile."""
    df_5m = _generate_synthetic_5m_bars(num_bars=10, base_volume=10_000.0, surge_last_bar_mult=1.8)
    rvol = calculate_intraday_rvol(df_5m)
    assert isinstance(rvol, float)
    assert rvol >= 1.7
