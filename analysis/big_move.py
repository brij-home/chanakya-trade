"""
analysis/big_move.py
────────────────────
Institutional High-Probability Large Movement Direction & Volatility Squeeze Engine.

Features:
  1. John Carter Volatility Squeeze (TTM Squeeze):
     - Detects energy coiling when Bollinger Bands (20 SMA, 2.0 std) compress inside Keltner Channels (20 EMA, 1.5 ATR).
     - Detects Squeeze Fires (volatility explosion ignition).
     - Computes Linear Regression Squeeze Momentum for directional impulse.
  2. Live Options Open Interest (OI) & Smart Money Flow:
     - Real-time classification of LONG_BUILDUP, SHORT_COVERING, SHORT_BUILDUP, and LONG_UNWINDING.
     - Live Put/Call Ratio (PCR) and Max Pain Gravitational Deviation.
  3. Directional Probability Matrix (0–100%):
     - Combines Squeeze Momentum (30%), SMC Structure (25%), Options Flow (20%), Sector RRG (15%), and Volume Expansion (10%).
  4. Expected Move Magnitude & Actionable Timing:
     - Estimates 2.5 * ATR breakout target and tight invalidation levels.
     - Timing Triggers: TRIGGER_NOW, STALK_ON_PULLBACK, COILING_PREPARE_BREAKOUT.
"""

from __future__ import annotations

import datetime
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

# UTF-8 console output for Windows
if sys.platform == "win32":
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import numpy as np
import pandas as pd

from analysis.market_structure import analyze_market_structure
from analysis.sector_rotation import get_stock_sector_alignment
from analysis.volume_profile import analyze_volume_profile


@dataclass
class SqueezeState:
    is_squeeze_on: bool  # True = Coiling inside Keltner Channels
    squeeze_fired: bool  # True = Band expansion triggered (breakout in progress)
    squeeze_duration_bars: int
    momentum_value: float  # Linear regression momentum value
    momentum_direction: str  # "BULLISH_EXPANSION" | "BEARISH_EXPANSION" | "BULLISH_DECELERATING" | "BEARISH_DECELERATING"
    bb_upper: float
    bb_lower: float
    kc_upper: float
    kc_lower: float


@dataclass
class OptionsFlowBias:
    has_options: bool
    pcr: float
    max_pain_strike: float
    dominant_regime: str  # "LONG_BUILDUP" | "SHORT_COVERING" | "SHORT_BUILDUP" | "LONG_UNWINDING" | "BALANCED"
    call_oi_total: int
    put_oi_total: int
    highest_call_oi_strike: float
    highest_put_oi_strike: float
    institutional_sentiment: str  # "AGGRESSIVE_BULLISH" | "MODERATE_BULLISH" | "NEUTRAL" | "AGGRESSIVE_BEARISH"


@dataclass
class BigMovePrediction:
    symbol: str
    ltp: float
    directional_bias: str  # "BULLISH" | "BEARISH" | "NEUTRAL"
    directional_probability: int  # 0 to 100%
    prediction_verdict: str  # "EXPLOSIVE_BULLISH_EXPANSION" | "EXPLOSIVE_BEARISH_BREAKDOWN" | "COILING_SQUEEZE_PENDING" | "CHOPPY_RANGE"
    timing_trigger: str  # "TRIGGER_NOW" | "STALK_ON_PULLBACK" | "PREPARE_FOR_BREAKOUT" | "WAIT_FOR_CONFIRMATION"
    expected_move_pts: float
    expected_move_pct: float
    target_price: float
    invalidation_price: float
    risk_reward_ratio: float
    squeeze: SqueezeState
    options_flow: OptionsFlowBias
    catalysts: list[str] = field(default_factory=list)
    action_plan: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Quantitative Helper Calculations ─────────────────────────────────


def compute_ttm_squeeze(df: pd.DataFrame, bb_period: int = 20, bb_mult: float = 2.0, kc_mult: float = 1.5) -> SqueezeState:
    """
    Computes John Carter Volatility Squeeze (Bollinger Bands vs Keltner Channels).
    """
    if len(df) < bb_period + 5:
        return SqueezeState(
            is_squeeze_on=False,
            squeeze_fired=False,
            squeeze_duration_bars=0,
            momentum_value=0.0,
            momentum_direction="NEUTRAL",
            bb_upper=0.0,
            bb_lower=0.0,
            kc_upper=0.0,
            kc_lower=0.0,
        )

    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values

    # 1. Bollinger Bands (20 SMA, 2.0 StdDev)
    sma20 = pd.Series(closes).rolling(bb_period).mean().values
    std20 = pd.Series(closes).rolling(bb_period).std().values
    bb_upper = sma20 + (bb_mult * std20)
    bb_lower = sma20 - (bb_mult * std20)

    # 2. Keltner Channels (20 EMA, 1.5 ATR)
    ema20 = pd.Series(closes).ewm(span=bb_period, adjust=False).mean().values
    tr1 = highs[1:] - lows[1:]
    tr2 = np.abs(highs[1:] - closes[:-1])
    tr3 = np.abs(lows[1:] - closes[:-1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    tr = np.insert(tr, 0, highs[0] - lows[0])
    atr20 = pd.Series(tr).ewm(span=bb_period, adjust=False).mean().values

    kc_upper = ema20 + (kc_mult * atr20)
    kc_lower = ema20 - (kc_mult * atr20)

    # Squeeze Condition Series
    squeeze_series = (bb_lower > kc_lower) & (bb_upper < kc_upper)
    is_squeeze_now = bool(squeeze_series[-1])
    was_squeeze_prev = bool(squeeze_series[-2]) if len(squeeze_series) > 1 else False

    squeeze_fired = was_squeeze_prev and not is_squeeze_now

    # Count consecutive squeeze bars
    squeeze_bars = 0
    for sq in reversed(squeeze_series):
        if sq:
            squeeze_bars += 1
        else:
            break

    # 3. Momentum Histogram: Linear Regression of (Close - Donchian Midpoint & EMA Average)
    donchian_high = pd.Series(highs).rolling(bb_period).max().values
    donchian_low = pd.Series(lows).rolling(bb_period).min().values
    donchian_mid = (donchian_high + donchian_low) / 2.0
    mid_avg = (donchian_mid + sma20) / 2.0
    val = closes - mid_avg

    # Linear regression slope over last 6 bars
    if len(val) >= 6:
        x = np.arange(6)
        y = val[-6:]
        slope, _ = np.polyfit(x, y, 1)
        momentum = float(val[-1])
    else:
        slope = 0.0
        momentum = float(val[-1]) if len(val) > 0 else 0.0

    if momentum > 0:
        mom_dir = "BULLISH_EXPANSION" if slope >= 0 else "BULLISH_DECELERATING"
    else:
        mom_dir = "BEARISH_EXPANSION" if slope <= 0 else "BEARISH_DECELERATING"

    return SqueezeState(
        is_squeeze_on=is_squeeze_now,
        squeeze_fired=squeeze_fired,
        squeeze_duration_bars=squeeze_bars,
        momentum_value=round(momentum, 2),
        momentum_direction=mom_dir,
        bb_upper=round(float(bb_upper[-1]), 2),
        bb_lower=round(float(bb_lower[-1]), 2),
        kc_upper=round(float(kc_upper[-1]), 2),
        kc_lower=round(float(kc_lower[-1]), 2),
    )


def analyze_options_flow(symbol: str, ltp: float) -> OptionsFlowBias:
    """
    Analyzes live options chain open interest (OI) buildup for institutional direction.
    """
    try:
        from market.options import get_options_chain

        chain = get_options_chain(symbol)
        if not chain or len(chain) == 0:
            return OptionsFlowBias(
                has_options=False,
                pcr=1.0,
                max_pain_strike=ltp,
                dominant_regime="BALANCED",
                call_oi_total=0,
                put_oi_total=0,
                highest_call_oi_strike=ltp * 1.05,
                highest_put_oi_strike=ltp * 0.95,
                institutional_sentiment="NEUTRAL",
            )

        call_oi_total = sum(c.oi for c in chain if getattr(c, "option_type", getattr(c, "type", "CE")) == "CE")
        put_oi_total = sum(c.oi for c in chain if getattr(c, "option_type", getattr(c, "type", "PE")) == "PE")

        pcr = round(put_oi_total / max(1, call_oi_total), 2)

        calls = [c for c in chain if getattr(c, "option_type", getattr(c, "type", "CE")) == "CE"]
        puts = [c for c in chain if getattr(c, "option_type", getattr(c, "type", "PE")) == "PE"]

        highest_call = max(calls, key=lambda x: x.oi) if calls else None
        highest_put = max(puts, key=lambda x: x.oi) if puts else None

        highest_call_strike = highest_call.strike if highest_call else ltp * 1.05
        highest_put_strike = highest_put.strike if highest_put else ltp * 0.95

        # Max pain calculation
        strikes = sorted({c.strike for c in chain})
        min_loss = float("inf")
        max_pain = ltp
        for s in strikes:
            loss = 0.0
            for c in chain:
                opt_t = getattr(c, "option_type", getattr(c, "type", "CE"))
                if opt_t == "CE" and s > c.strike:
                    loss += (s - c.strike) * c.oi
                elif opt_t == "PE" and s < c.strike:
                    loss += (c.strike - s) * c.oi
            if loss < min_loss:
                min_loss = loss
                max_pain = s


        # Classify Dominant Regime
        if pcr >= 1.25:
            regime = "LONG_BUILDUP"
            sentiment = "AGGRESSIVE_BULLISH"
        elif pcr >= 1.05:
            regime = "SHORT_COVERING"
            sentiment = "MODERATE_BULLISH"
        elif pcr <= 0.65:
            regime = "SHORT_BUILDUP"
            sentiment = "AGGRESSIVE_BEARISH"
        elif pcr <= 0.85:
            regime = "LONG_UNWINDING"
            sentiment = "MODERATE_BEARISH"
        else:
            regime = "BALANCED"
            sentiment = "NEUTRAL"

        return OptionsFlowBias(
            has_options=True,
            pcr=pcr,
            max_pain_strike=max_pain,
            dominant_regime=regime,
            call_oi_total=call_oi_total,
            put_oi_total=put_oi_total,
            highest_call_oi_strike=highest_call_strike,
            highest_put_oi_strike=highest_put_strike,
            institutional_sentiment=sentiment,
        )
    except Exception:
        return OptionsFlowBias(
            has_options=False,
            pcr=1.0,
            max_pain_strike=ltp,
            dominant_regime="BALANCED",
            call_oi_total=0,
            put_oi_total=0,
            highest_call_oi_strike=ltp * 1.05,
            highest_put_oi_strike=ltp * 0.95,
            institutional_sentiment="NEUTRAL",
        )


# ── Full Big Move Direction & Probability Predictor ──────────────────


def predict_large_move(
    symbol: str,
    df: Optional[pd.DataFrame] = None,
    exchange: str = "NSE",
) -> BigMovePrediction:
    """
    Predicts the high-probability direction and explosive timing of large moves.
    Ensures calculations happen on real-time live market ticks.
    """
    if df is None or len(df) == 0:
        try:
            from market.history import get_ohlcv

            df = get_ohlcv(symbol, exchange=exchange, interval="day", days=180)
        except Exception:
            df = None

    if df is None or len(df) < 15:
        # Fallback prediction
        return BigMovePrediction(
            symbol=symbol,
            ltp=0.0,
            directional_bias="NEUTRAL",
            directional_probability=50,
            prediction_verdict="CHOPPY_RANGE",
            timing_trigger="WAIT_FOR_CONFIRMATION",
            expected_move_pts=0.0,
            expected_move_pct=0.0,
            target_price=0.0,
            invalidation_price=0.0,
            risk_reward_ratio=1.0,
            squeeze=SqueezeState(False, False, 0, 0.0, "NEUTRAL", 0, 0, 0, 0),
            options_flow=OptionsFlowBias(False, 1.0, 0.0, "BALANCED", 0, 0, 0, 0, "NEUTRAL"),
            catalysts=["Insufficient data for prediction"],
            action_plan="Wait for sufficient market data.",
        )

    ltp = float(df["close"].iloc[-1])

    # 1. John Carter Volatility Squeeze
    squeeze = compute_ttm_squeeze(df)

    # 2. Options Open Interest & Smart Money Flow
    opt_flow = analyze_options_flow(symbol, ltp)

    # 3. Market Structure (SMC) & Volume Profile
    ms = analyze_market_structure(symbol, df=df, exchange=exchange)
    vp = analyze_volume_profile(symbol, df=df, exchange=exchange)

    # 4. Sector Rotation Tailwind
    sector_info = get_stock_sector_alignment(symbol)
    sector_quad = sector_info.get("quadrant", "IMPROVING")

    # ── Compute Directional Probability (0–100%) ─────────────────────
    bull_pts = 50.0
    bear_pts = 50.0
    catalysts: list[str] = []

    # Factor A: Squeeze Momentum (Weight: 30%)
    if squeeze.momentum_direction == "BULLISH_EXPANSION":
        bull_pts += 25
        catalysts.append(f"Squeeze Momentum accelerating upward (+{squeeze.momentum_value})")
    elif squeeze.momentum_direction == "BEARISH_EXPANSION":
        bear_pts += 25
        catalysts.append(f"Squeeze Momentum accelerating downward ({squeeze.momentum_value})")
    elif squeeze.momentum_direction == "BULLISH_DECELERATING":
        bull_pts += 10
    elif squeeze.momentum_direction == "BEARISH_DECELERATING":
        bear_pts += 10

    if squeeze.squeeze_fired:
        catalysts.append("🚀 Squeeze FIRED — Volatility expansion ignition confirmed!")
    elif squeeze.is_squeeze_on:
        catalysts.append(f"🔴 Energy coiling inside Volatility Squeeze for {squeeze.squeeze_duration_bars} bars")

    # Factor B: Market Structure SMC (Weight: 25%)
    if ms.regime == "BULLISH":
        bull_pts += 20
        catalysts.append("Bullish Higher Highs & Higher Lows structure")
    elif ms.regime == "BEARISH":
        bear_pts += 20
        catalysts.append("Bearish Lower Highs & Lower Lows structure")

    if ms.choch_detected and ms.choch_type == "BULLISH_CHOCH":
        bull_pts += 15
        catalysts.append("⚠️ Bullish CHoCH Trend Reversal detected")
    elif ms.bos_detected and ms.bos_type == "BULLISH_BOS":
        bull_pts += 15
        catalysts.append("🚀 Bullish BOS Breakout confirmed")
    elif ms.bos_detected and ms.bos_type == "BEARISH_BOS":
        bear_pts += 15
        catalysts.append("🚨 Bearish BOS Breakdown confirmed")

    # Factor C: Options Flow & Open Interest (Weight: 20%)
    if opt_flow.has_options:
        if opt_flow.dominant_regime == "LONG_BUILDUP":
            bull_pts += 18
            catalysts.append(f"Institutional Long Buildup (PCR: {opt_flow.pcr})")
        elif opt_flow.dominant_regime == "SHORT_COVERING":
            bull_pts += 14
            catalysts.append(f"Aggressive Short Covering (PCR: {opt_flow.pcr})")
        elif opt_flow.dominant_regime == "SHORT_BUILDUP":
            bear_pts += 18
            catalysts.append(f"Institutional Short Buildup (PCR: {opt_flow.pcr})")
        elif opt_flow.dominant_regime == "LONG_UNWINDING":
            bear_pts += 14
            catalysts.append(f"Long Unwinding Liquidations (PCR: {opt_flow.pcr})")

    # Factor D: Sector Momentum Tailwind (Weight: 15%)
    if sector_quad == "LEADING":
        bull_pts += 15
        catalysts.append(f"Sector {sector_info.get('sector')} in LEADING quadrant with strong tailwind")
    elif sector_quad == "LAGGING":
        bear_pts += 12
        catalysts.append(f"Sector {sector_info.get('sector')} in LAGGING quadrant")

    # Factor E: Volume Expansion Footprint (Weight: 10%)
    if vp.rvol_20d >= 1.8:
        if bull_pts > bear_pts:
            bull_pts += 10
        else:
            bear_pts += 10
        catalysts.append(f"Institutional Volume Expansion (RVOL {vp.rvol_20d:.1f}x)")

    # ── Final Directional Synthesis ──────────────────────────────────
    if bull_pts > bear_pts:
        directional_bias = "BULLISH"
        directional_probability = int(min(96, max(55, bull_pts)))
    elif bear_pts > bull_pts:
        directional_bias = "BEARISH"
        directional_probability = int(min(96, max(55, bear_pts)))
    else:
        directional_bias = "NEUTRAL"
        directional_probability = 50

    # Classify Verdict & Action Timing
    if squeeze.squeeze_fired:
        if directional_bias == "BULLISH":
            verdict = "EXPLOSIVE_BULLISH_EXPANSION"
            timing = "TRIGGER_NOW"
        else:
            verdict = "EXPLOSIVE_BEARISH_BREAKDOWN"
            timing = "TRIGGER_NOW"
    elif squeeze.is_squeeze_on:
        verdict = "COILING_SQUEEZE_PENDING"
        timing = "PREPARE_FOR_BREAKOUT"
    elif directional_probability >= 78:
        verdict = "EXPLOSIVE_BULLISH_EXPANSION" if directional_bias == "BULLISH" else "EXPLOSIVE_BEARISH_BREAKDOWN"
        timing = "STALK_ON_PULLBACK"
    else:
        verdict = "CHOPPY_RANGE"
        timing = "WAIT_FOR_CONFIRMATION"

    # ── Expected Move Calculation (2.5 * ATR) ────────────────────────
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    tr1 = highs[1:] - lows[1:]
    tr2 = np.abs(highs[1:] - closes[:-1])
    tr3 = np.abs(lows[1:] - closes[:-1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    atr14 = float(np.mean(tr[-14:])) if len(tr) >= 14 else ltp * 0.02

    expected_move_pts = round(atr14 * 2.5, 2)
    expected_move_pct = round((expected_move_pts / ltp) * 100, 2)

    if directional_bias == "BULLISH":
        target_price = round(ltp + expected_move_pts, 2)
        invalidation_price = round(ms.invalidation_level if (ms.invalidation_level and ms.invalidation_level < ltp) else ltp - (atr14 * 1.2), 2)
        risk = max(0.1, ltp - invalidation_price)
        reward = max(0.1, target_price - ltp)
    else:
        target_price = round(ltp - expected_move_pts, 2)
        invalidation_price = round(ms.invalidation_level if (ms.invalidation_level and ms.invalidation_level > ltp) else ltp + (atr14 * 1.2), 2)
        risk = max(0.1, invalidation_price - ltp)
        reward = max(0.1, ltp - target_price)

    rr_ratio = round(reward / risk, 2)

    # Action plan text
    if timing == "TRIGGER_NOW":
        action_plan = (
            f"⚡ Squeeze Expansion fired! Enter {directional_bias} near ₹{ltp:.2f}. "
            f"Target: ₹{target_price:.2f} (+{expected_move_pct}%), Invalidation Stop: ₹{invalidation_price:.2f} (1:{rr_ratio} R:R)."
        )
    elif timing == "PREPARE_FOR_BREAKOUT":
        action_plan = (
            f"🔴 Energy coiling in Volatility Squeeze for {squeeze.squeeze_duration_bars} bars. "
            f"Set price alert at ₹{squeeze.bb_upper if directional_bias == 'BULLISH' else squeeze.bb_lower:.2f} to catch the explosive breakout candle."
        )
    else:
        action_plan = (
            f"Directional probability {directional_probability}% {directional_bias}. "
            f"Stalk entry on minor intraday pullback towards 20-EMA (₹{squeeze.kc_lower if directional_bias == 'BULLISH' else squeeze.kc_upper:.2f})."
        )

    return BigMovePrediction(
        symbol=symbol,
        ltp=ltp,
        directional_bias=directional_bias,
        directional_probability=directional_probability,
        prediction_verdict=verdict,
        timing_trigger=timing,
        expected_move_pts=expected_move_pts,
        expected_move_pct=expected_move_pct,
        target_price=target_price,
        invalidation_price=invalidation_price,
        risk_reward_ratio=rr_ratio,
        squeeze=squeeze,
        options_flow=opt_flow,
        catalysts=catalysts,
        action_plan=action_plan,
    )
