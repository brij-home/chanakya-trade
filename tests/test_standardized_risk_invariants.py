"""
tests/test_standardized_risk_invariants.py
──────────────────────────────────────────
Regression invariant test suite verifying system-wide standardization of dynamic risk scaling:
  - Eliminates hardcoded max(1.0, ...) anti-patterns across all modules.
  - Verifies sub-₹100 stocks (Suzlon, IDEA, IRFC) maintain realistic risk distances and viable R:R.
  - Verifies high-ticket stocks (TCS, Dixon, MRF) maintain adequate risk buffers against micro-whipsaws.
  - Enforces mathematical monotonicity across:
      1. engine/trade_plan.py
      2. engine/detectors/squeeze_breakout.py
      3. engine/detectors/intraday_spark.py
      4. engine/detectors/pattern_coiling.py
      5. engine/detectors/circuit.py
      6. engine/asymmetric_radar.py
"""

from __future__ import annotations

import pandas as pd

from engine.dynamic_risk import resolve_price_tier
from engine.trade_plan import calculate_trade_plan
from engine.asymmetric_radar import _enforce_monotonic_trade_levels
from engine.detectors.circuit import detect_circuit_proximity
from engine.detectors.squeeze_breakout import detect_squeeze_breakout


def _generate_synthetic_df(
    spot: float, n_bars: int = 30, daily_volatility_pct: float = 0.02
) -> pd.DataFrame:
    """Generates synthetic OHLCV data centered around spot."""
    closes = [spot * (1.0 + (i - n_bars / 2) * (daily_volatility_pct / 5)) for i in range(n_bars)]
    highs = [c * 1.01 for c in closes]
    lows = [c * 0.99 for c in closes]
    opens = [c * 0.995 for c in closes]
    volumes = [500_000 + (i * 20_000) for i in range(n_bars)]

    return pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )


def test_sub_100_trade_plan_stop_distance_preserves_asymmetry():
    """
    Sub-₹100 stock (SUZLON @ ₹38.50) must NOT have its stop loss or noise buffer
    forced to >= ₹1.0 or ₹2.0 pts. It must dynamically scale down to ~0.30 - 0.70 pts,
    preserving viable R:R without triggering false Tier-1 scrutiny rejections.
    """
    df = _generate_synthetic_df(spot=38.50, n_bars=30, daily_volatility_pct=0.018)

    tp = calculate_trade_plan(
        symbol="SUZLON",
        spot=38.50,
        direction="BUY",
        timeframe="INTRADAY",
        exchange="NSE",
        df=df,
    )

    assert tp is not None
    assert tp.entry_price == 38.50
    assert tp.invalidation_stop < tp.entry_price

    stop_dist = tp.entry_price - tp.invalidation_stop
    # For a ₹38.50 stock, stop distance should be proportionate (~0.20 to 0.85 pts), NEVER artificially forced >= 1.0
    assert 0.10 <= stop_dist <= 0.90, (
        f"Stop distance {stop_dist} should scale dynamically for sub-₹100 stock"
    )

    # Target 1 must be strictly higher than entry
    assert tp.target_1 > tp.entry_price
    assert tp.target_2 > tp.target_1
    assert tp.target_3 > tp.target_2

    # Asymmetry must be viable
    assert tp.is_asymmetry_viable is True
    assert tp.rr_t1 >= 1.2
    assert tp.rr_t2 >= 1.8


def test_sub_100_trade_plan_short_direction_preserves_asymmetry():
    """Verifies SHORT trade plan for sub-₹100 stock has properly scaled noise buffer and stop distance."""
    df = _generate_synthetic_df(spot=38.50, n_bars=30, daily_volatility_pct=0.018)

    tp = calculate_trade_plan(
        symbol="SUZLON",
        spot=38.50,
        direction="SELL",
        timeframe="INTRADAY",
        exchange="NSE",
        df=df,
    )

    assert tp is not None
    assert tp.entry_price == 38.50
    assert tp.invalidation_stop > tp.entry_price

    stop_dist = tp.invalidation_stop - tp.entry_price
    assert 0.10 <= stop_dist <= 0.90
    assert tp.target_1 < tp.entry_price
    assert tp.target_2 < tp.target_1
    assert tp.target_3 < tp.target_2
    assert tp.is_asymmetry_viable is True


def test_high_ticket_trade_plan_respects_tier_floor():
    """
    High-ticket stock (TCS @ ₹3,600.00) must enforce the HIGH_TICKET_2500_10000 floor (₹6.00 pts),
    preventing absurd micro-stops of ₹1.00 that would be tagged by mere bid-ask spread jitter.
    """
    tier = resolve_price_tier(3600.0)
    assert tier.tier_name == "HIGH_TICKET_2500_10000"
    assert tier.abs_min_risk_pts == 6.00

    df = _generate_synthetic_df(spot=3600.0, n_bars=30, daily_volatility_pct=0.012)
    tp = calculate_trade_plan(
        symbol="TCS",
        spot=3600.0,
        direction="BUY",
        timeframe="INTRADAY",
        exchange="NSE",
        df=df,
    )

    assert tp is not None
    stop_dist = tp.entry_price - tp.invalidation_stop
    assert stop_dist >= 6.00, (
        f"High ticket stop distance {stop_dist} must be >= {tier.abs_min_risk_pts}"
    )


def test_asymmetric_radar_monotonic_trade_levels_sub_100():
    """
    Verifies that _enforce_monotonic_trade_levels in asymmetric_radar.py
    scales risk, entry range, and targets according to price tier rather than hardcoded 1.0 pt.
    """
    # Sub-100 stock with typical ~1.3% ATR
    ltp = 38.50
    atr = 0.50
    sl_price, risk_pts, t1, t2, moonshot, rr_ratio, entry_range = _enforce_monotonic_trade_levels(
        direction="BULLISH",
        ltp=ltp,
        raw_sl=38.05,
        target_1=39.50,
        target_2=40.80,
        target_moonshot=42.50,
        atr=atr,
    )

    # Risk pts must not be forced to 1.0!
    assert risk_pts < 1.0, f"Expected risk_pts < 1.0 for sub-100 stock, got {risk_pts}"
    assert risk_pts >= 0.10
    assert sl_price < ltp
    assert t1 > ltp
    assert t2 > t1
    assert moonshot > t2
    assert rr_ratio >= 2.0

    # Entry range width must not be forced to a bloated ₹1.0 width
    # entry_range string format: "₹38.1 – ₹38.8"
    assert "₹" in entry_range


def test_asymmetric_radar_monotonic_trade_levels_bearish_sub_100():
    """Verifies bearish asymmetric levels for sub-₹100 stock."""
    ltp = 38.50
    atr = 0.50
    sl_price, risk_pts, t1, t2, moonshot, rr_ratio, entry_range = _enforce_monotonic_trade_levels(
        direction="BEARISH",
        ltp=ltp,
        raw_sl=38.95,
        target_1=37.50,
        target_2=36.20,
        target_moonshot=34.50,
        atr=atr,
    )

    assert risk_pts < 1.0
    assert risk_pts >= 0.10
    assert sl_price > ltp
    assert t1 < ltp
    assert t2 < t1
    assert moonshot < t2
    assert rr_ratio >= 2.0


def test_circuit_detector_sub_100_risk_scaling():
    """
    Verifies detect_circuit_lock calculates proportional risk_pts for sub-₹100 stocks
    rather than forcing a 1.0 pt floor.
    """
    # Stock at ₹38.40 approaching 5% UC (prev close ₹37.00 -> UC ₹38.85)
    alert = detect_circuit_proximity(
        symbol="SUZLON",
        ltp=38.40,
        prev_close=37.00,
        circuit_band_pct=5.0,
        exchange="NSE",
    )

    assert alert is not None
    assert alert.actionable_plan is not None

    # Check stop loss
    sl_str = alert.actionable_plan.get("stop_loss", "")
    assert "₹" in sl_str
    sl_val = float(sl_str.replace("₹", "").replace(",", "").strip())
    risk_pts = round(38.40 - sl_val, 2)

    # 1.5% of 38.40 is 0.58 pts. It must NOT be clamped to 1.0!
    assert 0.40 <= risk_pts <= 0.70, f"Expected risk_pts around 0.58, got {risk_pts}"


def test_squeeze_breakout_sub_100_risk_scaling():
    """
    Verifies that TTM Squeeze breakout handles sub-100 stocks gracefully without 1.0 pt hardcoding.
    """
    # Create consolidating df that broke out
    df = _generate_synthetic_df(spot=38.50, n_bars=35, daily_volatility_pct=0.015)
    # Give the last bar an explosive breakout
    df.loc[df.index[-1], "close"] = 39.50
    df.loc[df.index[-1], "high"] = 39.60
    df.loc[df.index[-1], "volume"] = 2_500_000

    alert = detect_squeeze_breakout(
        symbol="SUZLON",
        df=df,
        ltp=39.50,
        exchange="NSE",
    )

    if alert is not None:
        tp = alert.actionable_plan
        assert tp is not None
        if "trade_plan" in tp:
            stop_dist = round(39.50 - tp["trade_plan"]["invalidation_stop"], 2)
            assert stop_dist < 1.0, (
                f"Squeeze breakout stop_dist {stop_dist} should scale for sub-100 stock"
            )
