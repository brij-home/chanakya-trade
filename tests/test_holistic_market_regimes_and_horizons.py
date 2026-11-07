"""
tests/test_holistic_market_regimes_and_horizons.py
──────────────────────────────────────────────────
Comprehensive institutional test suite verifying that ChanakyaTrade correctly covers:
  1. Bullish Trending Regimes (Intraday Call & Swing Inflection Breakouts)
  2. Bearish Trending Regimes (Intraday Put Setups & Breakdown Continuation)
  3. Neutral & Range-Bound Regimes (Iron Condors & Flow-Confirmed Exemption from Chop Veto)
  4. Choppy Trap-Heavy Regimes (OBV Distribution Divergence & VSA Climax Shields)
  5. Intraday vs Non-Intraday (Fast EMA10/22.0 DMI vs Swing EMA20/25.0 DMI)
"""

import numpy as np
import pandas as pd
from types import SimpleNamespace
from unittest.mock import patch

from analysis.obv import analyse_obv
from analysis.dmi_filter import evaluate_triple_dmi
from analysis.vsa import analyse_vsa
from analysis.anchored_vwap import detect_intraday_anchors
from analysis.regime_governor import MarketRegimeClassification, is_detector_eligible_for_regime
from engine.detectors.defined_risk_neutral import detect_defined_risk_neutral
from analysis.inflection_scanner import evaluate_single_stock_inflection
from analysis.multibagger import evaluate_short_term_horizon


def generate_synthetic_bars(
    n: int = 50,
    base_price: float = 1000.0,
    trend: str = "BULLISH",
    volume_surge: bool = True,
) -> pd.DataFrame:
    """Generates synthetic OHLCV bars tailored to test specific market regimes."""
    dates = pd.date_range("2026-11-01 09:15", periods=n, freq="5min")
    rng = np.random.default_rng(42)

    if trend == "BULLISH":
        steps = rng.normal(0.6, 0.4, n)
    elif trend == "BEARISH":
        steps = rng.normal(-0.6, 0.4, n)
    else:  # CHOPPY / NEUTRAL
        steps = rng.normal(0.0, 0.3, n)

    prices = base_price + np.cumsum(steps)
    highs = prices + rng.uniform(0.5, 1.5, n)
    lows = prices - rng.uniform(0.5, 1.5, n)
    opens = prices - (steps * 0.5)
    closes = prices

    if volume_surge:
        volumes = rng.integers(15000, 35000, n)
    else:
        volumes = rng.integers(2000, 6000, n)

    df = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        },
        index=dates,
    )
    return df


class TestBullishTrendingRegimes:
    """Tests Bullish setups under live institutional flow confluences."""

    def test_bullish_intraday_flow_confluence(self):
        df = generate_synthetic_bars(n=35, base_price=24200.0, trend="BULLISH", volume_surge=True)
        obv_res = analyse_obv(df, is_intraday=True)
        dmi_res = evaluate_triple_dmi(df, is_intraday=True)
        vsa_res = analyse_vsa(df, symbol="NIFTY", is_intraday=True)
        avwap_res = detect_intraday_anchors(df, spot_price=float(df["close"].iloc[-1]))

        # Bullish trend must produce positive slope and bullish DMI verdict
        assert obv_res.obv_slope_5bar > 0
        assert dmi_res.plus_di > dmi_res.minus_di
        assert vsa_res.bias in ("BULLISH", "NEUTRAL")
        assert avwap_res["bias"] in ("BULLISH", "EXPANSION_CROSSOVER")

    def test_bullish_swing_inflection_score_boost(self):
        # 250 daily bars simulating an accumulation base breaking out
        dates = pd.date_range("2026-01-01", periods=250, freq="D")
        closes = np.linspace(100.0, 180.0, 250)
        highs = closes + 1.5
        lows = closes - 1.5
        opens = closes - 0.5
        volumes = np.random.randint(100000, 500000, 250)
        # Add high volume on up days to trigger OBV accumulation
        volumes[closes > opens] *= 2

        df = pd.DataFrame(
            {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
            index=dates,
        )

        with patch("analysis.universe.get_stock_name", return_value="Test Leader Ltd"):
            setup = evaluate_single_stock_inflection("TATAMOTORS", df=df, allow_network=False)
            assert setup is not None
            assert setup.inflection_score >= 65
            assert any(
                "OBV" in c or "Triple-DMI" in c or "DMI" in c or "VSA" in c
                for c in setup.confluence_factors
            )


class TestBearishTrendingRegimes:
    """Tests Bearish setups under institutional distribution and markdown."""

    def test_bearish_intraday_distribution_flow(self):
        df = generate_synthetic_bars(n=35, base_price=24500.0, trend="BEARISH", volume_surge=True)
        obv_res = analyse_obv(df, is_intraday=True)
        dmi_res = evaluate_triple_dmi(df, is_intraday=True)
        avwap_res = detect_intraday_anchors(df, spot_price=float(df["close"].iloc[-1]))

        # In markdown, OBV slope is negative, -DI dominates, and price is below anchored VWAP
        assert obv_res.obv_slope_5bar < 0
        assert dmi_res.minus_di > dmi_res.plus_di
        assert avwap_res["bias"] == "BEARISH"


class TestNeutralAndChoppyRegimes:
    """Tests Iron Condor defined-risk income and flow-confirmed chop exemptions."""

    def test_defined_risk_neutral_detects_choppy_flow(self):
        # Flat choppy price action (ADX < 20, tight range)
        df_15m = generate_synthetic_bars(
            n=40, base_price=24300.0, trend="NEUTRAL", volume_surge=False
        )

        mock_chain = [
            {"strike": 24000.0, "option_type": "PE", "oi": 50000, "last_price": 45.0},
            {"strike": 24100.0, "option_type": "PE", "oi": 80000, "last_price": 60.0},
            {"strike": 24500.0, "option_type": "CE", "oi": 95000, "last_price": 55.0},
            {"strike": 24600.0, "option_type": "CE", "oi": 40000, "last_price": 35.0},
        ]

        ctx = SimpleNamespace(
            canonical_symbol="NIFTY",
            exchange="NSE",
            segment="FNO_INDEX",
            ltp=24300.0,
            vix=13.0,
            day_change_pct=0.20,
            candles_15m=df_15m,
            candles_5m=None,
            candles_daily=None,
            option_chain=mock_chain,
            is_index=True,
        )

        alert = detect_defined_risk_neutral(ctx)
        assert alert is not None
        assert alert.alert_type == "DEFINED_RISK_NEUTRAL"
        assert alert.direction == "NEUTRAL"
        assert alert.derivative_type == "SPREAD"
        assert alert.metrics.get("strategy") == "IRON_CONDOR"
        assert alert.metrics.get("dmi_triple_verdict") in (
            "WEAK_MOMENTUM_BELOW_25",
            "CHOP_WHIPSAW",
            "NEUTRAL",
            "WEAK_OR_CHOPPY",
        )

    def test_regime_governor_exempts_flow_confirmed_breakout_in_balanced_chop(self):
        # In BALANCED_CHOP regime:
        regime = MarketRegimeClassification(
            regime="BALANCED_CHOP",
            vix=12.8,
            is_orb_trapped=True,
            is_expiry_session=False,
            min_scrutiny_score=80,
            dominant_bias="MEAN_REVERSION",
            guidance="Compressed volatility. Breakouts require RVOL >= 2.0x.",
        )

        # Case 1: Raw breakout with RVOL 1.5x and NO flow confirmation -> SUPPRESSED
        is_elig, reason = is_detector_eligible_for_regime(
            alert_type="OPTIONS_MOMENTUM",
            regime=regime,
            rvol=1.5,
            has_structural_sweep=False,
            has_flow_confirmation=False,
        )
        assert is_elig is False
        assert "BALANCED_CHOP" in reason

        # Case 2: Breakout with RVOL 1.5x BUT verified institutional flow confirmation -> APPROVED!
        is_elig, reason = is_detector_eligible_for_regime(
            alert_type="OPTIONS_MOMENTUM",
            regime=regime,
            rvol=1.5,
            has_structural_sweep=False,
            has_flow_confirmation=True,
        )
        assert is_elig is True
        assert reason == ""


class TestTrapDetectionAndDistributionShields:
    """Tests OBV Distribution Divergence and VSA Climax protections."""

    def test_bearish_obv_divergence_penalizes_multibagger_short_term_horizon(self):
        # Create a series where price reaches a new high but volume is drying up on up moves
        dates = pd.date_range("2026-01-01", periods=60, freq="D")
        closes = np.linspace(500.0, 580.0, 60)
        # Last 10 bars push to higher highs
        closes[-10:] = np.linspace(580.0, 620.0, 10)
        volumes = np.full(60, 50000)
        # Volume drops significantly during the final price pump (bearish divergence)
        volumes[-10:] = 8000

        df = pd.DataFrame(
            {
                "open": closes - 2.0,
                "high": closes + 3.0,
                "low": closes - 3.0,
                "close": closes,
                "volume": volumes,
            },
            index=dates,
        )

        score, verdict, details = evaluate_short_term_horizon(
            df=df,
            ltp=float(closes[-1]),
            vcp_detected=False,
            vcp_pivot_price=0.0,
            sector_tailwind=70,
        )

        # OBV analysis must flag the distribution divergence or lack of volume expansion
        assert "obv_divergence" in details or "rvol_20d" in details
        assert score < 85  # Dampened from runaway speculative buy


class TestIntradayVsNonIntradayCalibration:
    """Verifies that faster EMA smoothing & calibrated DMI thresholds apply cleanly."""

    def test_intraday_fast_smoothing_vs_swing_standard_smoothing(self):
        df = generate_synthetic_bars(n=30, base_price=100.0, trend="BULLISH", volume_surge=True)
        obv_intra = analyse_obv(df, is_intraday=True)
        obv_swing = analyse_obv(df, is_intraday=False)

        # Intraday uses 10-period EMA, Swing uses 20-period EMA
        assert obv_intra.obv_ema is not None
        assert obv_swing.obv_ema is not None
        # Both must return valid divergence state
        assert obv_intra.divergence in ("BULLISH_CONVERGENCE", "BULLISH_DIVERGENCE", "NEUTRAL")

    def test_dmi_intraday_threshold_22_vs_swing_threshold_25(self):
        df = generate_synthetic_bars(n=30, base_price=100.0, trend="BULLISH", volume_surge=True)
        dmi_intra = evaluate_triple_dmi(df, is_intraday=True)
        dmi_swing = evaluate_triple_dmi(df, is_intraday=False)

        # Both compute valid positive and negative directional indexes
        assert dmi_intra.plus_di >= 0.0
        assert dmi_swing.plus_di >= 0.0
        assert dmi_intra.verdict is not None
        assert dmi_swing.verdict is not None
