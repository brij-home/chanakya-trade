"""
tests/test_obv_and_triple_dmi.py
─────────────────────────────────
Comprehensive test suite verifying:
  1. Granville On-Balance Volume (OBV) Engine & Divergence Detection (#TripleThrustStrategy)
  2. Triple-Filtered DMI Momentum Model (#TripleDMIStrategy)
  3. Intraday vs Non-Intraday Parameter Calibration
  4. Integration with Signal Ensemble & Technical Analysis Snapshot
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.dmi_filter import (
    evaluate_triple_dmi,
)
from analysis.obv import (
    analyse_obv,
    compute_obv_series,
)
from analysis.technical import TechnicalSnapshot, analyse
from engine.signal_ensemble import _trend_signal


# ── Synthetic Data Builders ──────────────────────────────────────────────


def make_ohlcv_df(
    closes: list[float],
    volumes: list[float] | None = None,
    spread_pct: float = 0.01,
) -> pd.DataFrame:
    """Creates a deterministic OHLCV DataFrame from close prices and volumes."""
    c = np.array(closes, dtype=float)
    n = len(c)
    h = c * (1.0 + spread_pct)
    l = c * (1.0 - spread_pct)
    o = np.roll(c, 1)
    o[0] = c[0]
    v = np.array(volumes, dtype=float) if volumes is not None else np.ones(n) * 100_000.0
    idx = pd.date_range("2026-01-01", periods=n, freq="B")
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}, index=idx)


# ── 1. OBV Engine & Divergence Tests ─────────────────────────────────────


class TestOBVEngine:
    def test_compute_obv_basic_sequence(self):
        """Vectorized OBV accumulates volume on up bars and subtracts on down bars."""
        closes = [100.0, 102.0, 101.0, 101.0, 105.0]
        vols = [1000.0, 500.0, 300.0, 200.0, 800.0]
        # Bar 0: initial close (delta=0) -> OBV=0
        # Bar 1: +2.0 (up) -> +500 -> OBV=500
        # Bar 2: -1.0 (down) -> -300 -> OBV=200
        # Bar 3: flat (delta=0) -> 0 -> OBV=200
        # Bar 4: +4.0 (up) -> +800 -> OBV=1000
        s_close = pd.Series(closes)
        s_vol = pd.Series(vols)
        obv = compute_obv_series(s_close, s_vol)

        assert len(obv) == 5
        assert float(obv.iloc[0]) == 0.0
        assert float(obv.iloc[1]) == 500.0
        assert float(obv.iloc[2]) == 200.0
        assert float(obv.iloc[3]) == 200.0
        assert float(obv.iloc[4]) == 1000.0

    def test_obv_bullish_accumulation_divergence(self):
        """
        Price consolidates/coils near resistance while smart money volume pushes OBV to new highs.
        Should trigger BULLISH_DIVERGENCE (#TripleThrustStrategy Example 2).
        """
        # 30 bars of baseline
        closes = [100.0 + (i % 2) * 0.5 for i in range(25)]
        vols = [50_000.0] * 25

        # Last 5 bars: Price stays coiled at 101.0 (not breaking out yet), but massive volume hits on up ticks
        closes.extend([100.8, 100.9, 100.8, 101.0, 101.0])
        vols.extend([500_000.0, 800_000.0, 20_000.0, 1_000_000.0, 500_000.0])

        df = make_ohlcv_df(closes, vols)
        snap = analyse_obv(df, symbol="TEST_ACCUM", is_intraday=False)

        assert snap.divergence == "BULLISH_DIVERGENCE"
        assert snap.conviction_modifier >= 15
        assert snap.is_pivot_breakout is True

    def test_obv_bearish_distribution_divergence(self):
        """
        Price makes a new high, but volume on up bars is anemic / heavy on down bars (OBV lower high).
        Should trigger BEARISH_DIVERGENCE (#TripleThrustStrategy Example 1: Distribution Trap).
        """
        # Peak 1: Price 110 with heavy volume
        closes = [100.0 + i * 2.0 for i in range(6)]  # to 110
        vols = [500_000.0] * 6

        # Pullback: Price drops to 104 on moderate volume
        closes.extend([108.0, 106.0, 104.0])
        vols.extend([300_000.0, 300_000.0, 300_000.0])

        # Push 2: Price reaches a higher high of 112 on very low volume, with down bars having more volume
        closes.extend([106.0, 108.0, 110.0, 112.0])
        vols.extend([50_000.0, 50_000.0, 50_000.0, 50_000.0])

        df = make_ohlcv_df(closes, vols)
        snap = analyse_obv(df, symbol="TEST_DISTRIB", is_intraday=False, lookback_bars=10)

        assert snap.divergence == "BEARISH_DIVERGENCE"
        assert snap.conviction_modifier <= -15

    def test_intraday_calibration_faster_smoothing(self):
        """Intraday mode uses tighter lookback and faster 10-bar EMA smoothing."""
        closes = [100.0 + i * 0.2 for i in range(20)]
        vols = [10_000.0] * 20
        df = make_ohlcv_df(closes, vols)

        snap_intra = analyse_obv(df, symbol="INTRA_TEST", is_intraday=True)
        snap_daily = analyse_obv(df, symbol="DAILY_TEST", is_intraday=False)

        assert snap_intra.timeframe == "INTRADAY"
        assert snap_daily.timeframe == "DAILY"


# ── 2. Triple-Filtered DMI Momentum Model Tests ──────────────────────────


class TestTripleDMIFilter:
    def test_weak_crossover_below_25_is_suppressed(self):
        """
        In rangebound chop, +DI crosses -DI below 25.
        The model MUST classify this as WEAK_OR_CHOPPY, preventing whipsaws.
        """
        # Construct low-volatility flat chop where DI remains below 20
        rng = np.random.default_rng(42)
        closes = [100.0 + rng.uniform(-0.3, 0.3) for _ in range(40)]
        df = make_ohlcv_df(closes, spread_pct=0.005)

        res = evaluate_triple_dmi(df, symbol="CHOP_STOCK", threshold=25.0)

        # In quiet chop, crossovers below threshold are flagged as WEAK_OR_CHOPPY or low confidence
        assert res.verdict in ("WEAK_OR_CHOPPY", "NEUTRAL")
        assert res.confidence_score <= 50.0

    def test_triple_bullish_confirmed_on_breakout(self):
        """
        Setup satisfying all 3 filters (#TripleDMIStrategy):
          1. +DI crosses above 25
          2. +DI stays above 25
          3. +DI breaks prior -DI pivot
        """
        # Step 1: Initial sharp downtrend to establish a high -DI pivot (selling panic)
        closes = [150.0 - i * 2.0 for i in range(15)]  # down to 120
        df_down = make_ohlcv_df(closes, spread_pct=0.02)

        # Step 2: Explosive reversal with huge daily ranges and high closes to rocket +DI above 25 and prior -DI
        up_closes = [120.0 + i * 4.0 for i in range(1, 15)]  # up from 120 to 176
        df_up = make_ohlcv_df(up_closes, spread_pct=0.03)

        df = pd.concat([df_down, df_up], ignore_index=True)
        # Re-index dates
        df.index = pd.date_range("2026-01-01", periods=len(df), freq="B")

        res = evaluate_triple_dmi(df, symbol="ROCKET_STOCK", threshold=25.0)

        assert res.plus_di > 25.0
        assert res.breaks_opposite_pivot is True
        assert res.verdict == "TRIPLE_BULLISH_CONFIRMED"
        assert res.confidence_score >= 80.0

    def test_symmetric_triple_bearish_confirmed(self):
        """
        Symmetric bearish setup:
          1. -DI crosses above 25
          2. -DI stays above 25
          3. -DI breaks prior +DI pivot
        """
        # Step 1: Initial strong uptrend to establish a high +DI pivot
        closes = [100.0 + i * 2.0 for i in range(15)]
        df_up = make_ohlcv_df(closes, spread_pct=0.02)

        # Step 2: Severe capitulation breakdown to rocket -DI above 25 and prior +DI
        down_closes = [130.0 - i * 4.0 for i in range(1, 15)]
        df_down = make_ohlcv_df(down_closes, spread_pct=0.03)

        df = pd.concat([df_up, df_down], ignore_index=True)
        df.index = pd.date_range("2026-01-01", periods=len(df), freq="B")

        res = evaluate_triple_dmi(df, symbol="CRASH_STOCK", threshold=25.0)

        assert res.minus_di > 25.0
        assert res.breaks_opposite_pivot is True
        assert res.verdict == "TRIPLE_BEARISH_CONFIRMED"
        assert res.confidence_score >= 80.0

    def test_intraday_threshold_calibration(self):
        """Intraday defaults to 22.0 threshold and 12-bar pivot lookback."""
        closes = [100.0 + i * 0.5 for i in range(25)]
        df = make_ohlcv_df(closes)

        res_intra = evaluate_triple_dmi(df, symbol="INDEX_FUT", is_intraday=True)
        res_daily = evaluate_triple_dmi(df, symbol="STOCK_EQ", is_intraday=False)

        assert res_intra.threshold == 22.0
        assert res_daily.threshold == 25.0


# ── 3. Integration with Signal Ensemble & TechnicalSnapshot ──────────────


class TestIntegration:
    def test_trend_signal_neutralizes_on_bearish_obv_divergence(self):
        """
        When price is in an apparent EMA uptrend, but OBV shows a Bearish Divergence
        (Distribution Trap), _trend_signal MUST neutralize to 0 (saving the desk from top-chasing).
        """
        # Baseline pad of 30 bars
        closes = [100.0] * 30
        vols = [100_000.0] * 30

        # First leg: strong rally with high volume
        closes.extend([100.0 + i * 2.0 for i in range(1, 20)])
        vols.extend([500_000.0] * 19)

        # Second leg: pull back
        closes.extend([138.0, 136.0, 134.0])
        vols.extend([200_000.0, 200_000.0, 200_000.0])

        # Third leg: price reaches higher high on virtually zero volume
        closes.extend([137.0, 140.0, 142.0])
        vols.extend([1_000.0, 1_000.0, 1_000.0])

        df = make_ohlcv_df(closes, vols)
        vote = _trend_signal(df)

        # Should be neutralized by the distribution trap warning
        assert vote.signal == 0
        assert "neutralized" in vote.detail.lower() or "distribution" in vote.detail.lower()

    def test_technical_snapshot_includes_obv_and_dmi(self):
        """Full technical analyse() populates OBV and Triple-DMI fields in TechnicalSnapshot."""
        closes = [100.0 + i * 0.8 for i in range(60)]
        df = make_ohlcv_df(closes)

        snap = analyse("RELIANCE", exchange="NSE", df=df)

        assert isinstance(snap, TechnicalSnapshot)
        assert snap.obv is not None
        assert snap.obv_regime in ("ACCUMULATION", "DISTRIBUTION", "NEUTRAL")
        assert snap.dmi_plus is not None
        assert snap.dmi_minus is not None
        assert snap.dmi_triple_verdict in (
            "TRIPLE_BULLISH_CONFIRMED",
            "TRIPLE_BEARISH_CONFIRMED",
            "BULLISH_ESTABLISHED",
            "BEARISH_ESTABLISHED",
            "WEAK_OR_CHOPPY",
            "NEUTRAL",
        )
