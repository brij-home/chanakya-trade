"""
engine/index_adaptive_regime.py
───────────────────────────────
Institutional Adaptive Index Trading Strategy & Regime Engine.

Implements the Three Pillars of Institutional Trading Excellence:
  1. 🦅 EAGLE EYE (Macro & Multi-Timeframe Radar):
     - Choppiness Index (CHOP, E.W. Dreiss formula): Detects consolidation vs expansion regimes.
     - Wilder's Average Directional Index (ADX-14): Quantifies directional momentum strength.
     - Multi-Timeframe Structural Trend Alignment: Evaluates 15m trend structure vs 5m execution bar.
     - Heavyweight Locomotive Confluence & Divergence: HDFCBANK, RELIANCE, ICICIBANK, etc.
     - Time-of-Day (TOD) Market Phase: Filters opening auction discovery and midday theta traps.
     - India VIX Volatility Environment: Low-VIX (<13.0) theta bleed vs High-VIX (>18.0) crush risk.

  2. 🐅 TIGER STALKING (Regime-Adaptive Strategy Selection):
     - Stalking Mode: In non-trending, choppy, or midday lull duration, ROUTINE breakouts are
       COMPLETELY SUPPRESSED to prevent whipsaw bleeding and theta destruction. Cash is a position!
     - Pounce Mode: Strikes decisively ONLY when institutional expansion thrust, high RVOL,
       or high-conviction liquidity sweep occurs.
     - Strategy Adaptation:
         * Trending Expansion  -> Momentum Sniper (ORB, High/Low Breakout, Trend Retest).
         * Rangebound Chop     -> Capital Preservation (Stalk) or Turtle Soup Extreme Fade.
         * Low VIX / Expiry PM -> Defined-Risk Hedged Spreads Mandatory.

  3. 🎯 SNIPER ENTRY (Exact Killzone, Pullback Timing, Zero FOMO Chase):
     - Optimal Trade Entry (OTE): Retest limit orders anchored to broken structure / VWAP / OB.
     - Strict No-Chase Boundary: Hard mathematical ceiling beyond which entry is disqualified.
     - Asymmetric Stop-Loss: Structural invalidation yielding R:R >= 1:2.5 to 1:3.0+.
     - 20-Minute Time-Stop: Kills stagnant options trades before theta grinds away capital.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, time as dtime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

logger = logging.getLogger("chanakya.index_adaptive_regime")
IST = ZoneInfo("Asia/Kolkata")


# ── Data Models ───────────────────────────────────────────────────────────────


@dataclass
class MultiTimeframeTrend:
    """Multi-timeframe trend alignment (15m vs 5m)."""

    bias: str  # "BULLISH_ALIGNED" | "BEARISH_ALIGNED" | "CONTRARIAN_DIVERGENT" | "RANGE_BOUND"
    trend_15m: str  # "BULLISH" | "BEARISH" | "RANGING"
    trend_5m: str  # "BULLISH" | "BEARISH" | "RANGING"
    ema20_15m: float
    ema50_15m: float
    vwap_15m: float
    summary: str


@dataclass
class EagleRegime:
    """Pillar 1: 🦅 Eagle Eye — High-altitude multi-dimensional regime radar."""

    symbol: str
    spot: float
    chop_index: float  # 0.0 to 100.0 (>=61.8 = severe chop, <=38.2 = strong trend)
    chop_status: str  # "SEVERE_CHOP" | "TRENDING_EXPANSION" | "NEUTRAL_DRIFT"
    adx_14: float  # < 20 = non-trending, >= 25 = trending
    adx_status: str  # "NON_TRENDING" | "MODERATE_TREND" | "STRONG_TREND"
    multi_tf: MultiTimeframeTrend
    heavyweights_alignment: (
        str  # "STRONG_BULLISH" | "STRONG_BEARISH" | "POLARIZED_DIVIDED" | "NEUTRAL"
    )
    heavyweights_detail: str
    market_phase: str  # "OPENING_AUCTION" | "MORNING_EXPANSION" | "MIDDAY_THETA_CHOP" | "AFTERNOON_EXPANSION" | "POWER_HOUR"
    is_midday_chop_window: bool
    vix_val: Optional[float]
    vix_regime: str  # "LOW_VIX_THETA_BURDEN" | "NORMAL_VIX" | "HIGH_VIX_CRUSH_RISK"
    overall_environment: (
        str  # "OPTIMAL_TREND_EXPANSION" | "WHIPSAW_CHOP_TRAP" | "SELECTIVE_FADE" | "BALANCED_RANGE"
    )
    summary: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


@dataclass
class TigerStrategyMandate:
    """Pillar 2: 🐅 Tiger Stalking — Regime-adaptive strategy & patience filter."""

    mandate: str  # "MOMENTUM_EXPANSION" | "TIGER_STALKING_PRESERVE_CAPITAL" | "TURTLE_SOUP_RANGE_FADE" | "DEFINED_RISK_SPREAD_ONLY" | "NORMAL_ADAPTIVE"
    allow_routine_breakouts: bool  # False during chop/midday unless verified institutional thrust
    allow_thrust_only: bool  # True when in chop/stalking mode
    suggested_strategy: str  # "BUY_MOMENTUM" | "WAIT_IN_CASH" | "FADE_BOUNDARY" | "HEDGED_SPREAD"
    reason: str
    action_guidance: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SniperExecutionPlan:
    """Pillar 3: 🎯 Sniper Entry — Exact killzone, retest timing, tight SL & no-chase boundary."""

    setup_name: str
    direction: str  # "BULLISH" | "BEARISH"
    spot: float
    trigger_level: float  # Key structural pivot / breakout level
    entry_zone_min: float  # Limit pullback min
    entry_zone_max: float  # Limit pullback max
    no_chase_boundary: float  # Strict price beyond which entry is prohibited
    structural_invalidation: float  # Structure-anchored SL
    risk_points: float  # Invalidation distance in points
    target_1: float  # +1.8R to +2.0R (Book 50%, SL to Breakeven)
    target_2: float  # +3.5R to +4.0R
    target_3: float  # Runner
    risk_reward_t1: float
    is_chasing: bool
    entry_instruction: str
    time_stop_minutes: int = 20

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AdaptiveIndexDecision:
    """Complete synthesized evaluation combining Eagle, Tiger, and Sniper."""

    symbol: str
    spot: float
    eagle: EagleRegime
    tiger: TigerStrategyMandate
    sniper: Optional[SniperExecutionPlan] = None
    evaluated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "spot": self.spot,
            "eagle": self.eagle.to_dict(),
            "tiger": self.tiger.to_dict(),
            "sniper": self.sniper.to_dict() if self.sniper else None,
            "evaluated_at": self.evaluated_at,
        }


# ── Thread-safe TTL Cache for Regime Decisions ────────────────────────────────

_REGIME_CACHE_LOCK = threading.Lock()
_REGIME_CACHE: dict[str, tuple[float, AdaptiveIndexDecision]] = {}
_REGIME_CACHE_TTL = 15.0  # 15s refresh interval


# ── Mathematical Indicators: Choppiness Index & ADX ──────────────────────────


def compute_choppiness_index(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """
    Computes standard Choppiness Index (CHOP) developed by E.W. Dreiss.

    Formula:
        CHOP = 100 * log10(Sum(TR, period) / (MaxHigh(period) - MinLow(period))) / log10(period)

    Interpretation:
        - CHOP >= 61.8 (Fibonacci upper boundary): Consolidation / Severe sideways chop.
          Directional breakouts have >75% failure rate.
        - CHOP <= 38.2 (Fibonacci lower boundary): Strong directional trend / Expansion.
        - 38.2 < CHOP < 61.8: Transition / Neutral consolidation.
    """
    if df is None or len(df) < period:
        return None
    try:
        col_h = "high" if "high" in df.columns else "High"
        col_l = "low" if "low" in df.columns else "Low"
        col_c = "close" if "close" in df.columns else "Close"

        highs = df[col_h].astype(float).values
        lows = df[col_l].astype(float).values
        closes = df[col_c].astype(float).values

        n = len(df)
        tr = [float(highs[0] - lows[0])]
        for i in range(1, n):
            tr.append(
                max(
                    float(highs[i] - lows[i]),
                    abs(float(highs[i] - closes[i - 1])),
                    abs(float(lows[i] - closes[i - 1])),
                )
            )

        tr_sum = sum(tr[-period:])
        max_high = max(highs[-period:])
        min_low = min(lows[-period:])
        hl_range = max_high - min_low

        if hl_range <= 0.0:
            return 100.0  # Stagnant flat bars = infinite chop

        ratio = tr_sum / hl_range
        if ratio <= 0.0:
            return 0.0

        chop = 100.0 * (math.log10(ratio) / math.log10(period))
        return round(max(0.0, min(100.0, chop)), 2)
    except Exception as exc:
        logger.debug("[AdaptiveRegime] Choppiness calculation failed: %s", exc)
        return None


def compute_adx(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """
    Computes standard 14-period Wilder's Average Directional Index (ADX).

    Interpretation:
        - ADX < 20.0: Non-trending, weak directional momentum, rangebound drift.
        - 20.0 <= ADX < 25.0: Emerging or consolidating trend.
        - ADX >= 25.0: Healthy directional trend.
        - ADX >= 40.0: Strong or parabolic impulse trend.
    """
    if df is None or len(df) < period + 2:
        return None
    try:
        col_h = "high" if "high" in df.columns else "High"
        col_l = "low" if "low" in df.columns else "Low"
        col_c = "close" if "close" in df.columns else "Close"

        h = df[col_h].astype(float)
        l = df[col_l].astype(float)
        c = df[col_c].astype(float)

        up_move = h - h.shift(1)
        down_move = l.shift(1) - l

        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        prev_c = c.shift(1)
        tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)

        # Exponential moving average / Wilder smoothing
        atr = tr.ewm(alpha=1.0 / period, min_periods=period).mean()
        atr_clean = atr.replace(0, np.nan)
        plus_di = 100.0 * (
            pd.Series(plus_dm, index=df.index).ewm(alpha=1.0 / period, min_periods=period).mean()
            / atr_clean
        )
        minus_di = 100.0 * (
            pd.Series(minus_dm, index=df.index).ewm(alpha=1.0 / period, min_periods=period).mean()
            / atr_clean
        )

        di_sum = (plus_di + minus_di + 1e-9).replace(0, np.nan)
        dx = (abs(plus_di - minus_di) / di_sum) * 100.0
        adx = dx.ewm(alpha=1.0 / period, min_periods=period).mean()

        val = float(adx.iloc[-1])
        return round(val, 2) if not np.isnan(val) and val >= 0 else None
    except Exception as exc:
        logger.debug("[AdaptiveRegime] ADX calculation failed: %s", exc)
        return None


# ── Market Phase & Time of Day Analysis ──────────────────────────────────────


def get_time_of_day_phase(dt: Optional[datetime] = None) -> tuple[str, bool]:
    """
    Classifies the session time into standard Indian institutional phases (IST).

    Returns:
        (phase_name, is_midday_chop_window)
    """
    now_dt = dt or datetime.now(IST)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=IST)
    else:
        now_dt = now_dt.astimezone(IST)

    t = now_dt.time()
    if t < dtime(9, 15) or t > dtime(15, 30):
        return "MARKET_CLOSED", False
    if t < dtime(9, 25):
        return "OPENING_AUCTION", False
    if t < dtime(11, 30):
        return "MORNING_EXPANSION", False
    if t <= dtime(13, 15):
        # 11:30 - 13:15 IST: Prime Midday Theta Decay / European Pre-Open Lull
        return "MIDDAY_THETA_CHOP", True
    if t <= dtime(14, 30):
        return "AFTERNOON_EXPANSION", False
    if t <= dtime(15, 15):
        return "POWER_HOUR_EXPIRY", False
    return "POST_MARKET_CLOSING", False


# ── Multi-Timeframe Structural Trend Extraction ──────────────────────────────


def evaluate_multi_timeframe_trend(
    df_5m: Optional[pd.DataFrame],
    df_15m: Optional[pd.DataFrame] = None,
    spot: float = 0.0,
) -> MultiTimeframeTrend:
    """
    Evaluates higher-timeframe (15m) trend structure against 5m execution bar.
    """
    if df_5m is None or len(df_5m) < 4:
        return MultiTimeframeTrend(
            bias="NEUTRAL",
            trend_15m="RANGING",
            trend_5m="RANGING",
            ema20_15m=spot,
            ema50_15m=spot,
            vwap_15m=spot,
            summary="Insufficient OHLCV for Multi-TF structure",
        )

    col_c = "close" if "close" in df_5m.columns else "Close"
    col_h = "high" if "high" in df_5m.columns else "High"
    col_l = "low" if "low" in df_5m.columns else "Low"

    # Resample or construct 15m from 5m if 15m is not directly provided
    active_15m = df_15m
    if active_15m is None:
        try:
            if isinstance(df_5m.index, pd.DatetimeIndex) and len(df_5m) >= 6:
                active_15m = (
                    df_5m.resample("15min")
                    .agg({col_h: "max", col_l: "min", col_c: "last"})
                    .dropna()
                )
            elif len(df_5m) >= 6:
                # Rolling 3-bar chunks
                c_15 = []
                for i in range(0, len(df_5m) - 2, 3):
                    c_15.append(float(df_5m[col_c].iloc[i + 2]))
                if c_15:
                    active_15m = pd.DataFrame({"close": c_15})
        except Exception:
            active_15m = None

    # 1. 5m Trend
    closes_5m = df_5m[col_c].astype(float)
    ema9_5m = float(closes_5m.ewm(span=9, adjust=False).mean().iloc[-1])
    ema20_5m = float(closes_5m.ewm(span=20, adjust=False).mean().iloc[-1])
    cur_c = float(closes_5m.iloc[-1])

    trend_5m = "RANGING"
    if cur_c >= ema9_5m and ema9_5m >= ema20_5m * 0.999:
        trend_5m = "BULLISH"
    elif cur_c <= ema9_5m and ema9_5m <= ema20_5m * 1.001:
        trend_5m = "BEARISH"

    # 2. 15m Trend
    trend_15m = "RANGING"
    ema20_15m = cur_c
    ema50_15m = cur_c

    if active_15m is not None and len(active_15m) >= 4:
        c15_col = "close" if "close" in active_15m.columns else col_c
        closes_15m = active_15m[c15_col].astype(float)
        ema20_15m = float(
            closes_15m.ewm(span=20, adjust=False).mean().iloc[-1]
            if len(closes_15m) >= 20
            else closes_15m.mean()
        )
        ema50_15m = float(
            closes_15m.ewm(span=50, adjust=False).mean().iloc[-1]
            if len(closes_15m) >= 50
            else closes_15m.mean()
        )
        last_c15 = float(closes_15m.iloc[-1])

        if last_c15 >= ema20_15m and ema20_15m >= ema50_15m * 0.998:
            trend_15m = "BULLISH"
        elif last_c15 <= ema20_15m and ema20_15m <= ema50_15m * 1.002:
            trend_15m = "BEARISH"

    # 3. Multi-TF Alignment
    if trend_15m == "BULLISH" and trend_5m == "BULLISH":
        bias = "BULLISH_ALIGNED"
        summary = "🦅 Strong Bullish Alignment: 15m & 5m both in uptrend above 20-EMA"
    elif trend_15m == "BEARISH" and trend_5m == "BEARISH":
        bias = "BEARISH_ALIGNED"
        summary = "🦅 Strong Bearish Alignment: 15m & 5m both in downtrend below 20-EMA"
    elif trend_15m != trend_5m and trend_15m != "RANGING" and trend_5m != "RANGING":
        bias = "CONTRARIAN_DIVERGENT"
        summary = f"⚠️ Multi-TF Divergence: 15m {trend_15m} vs 5m {trend_5m} (Trap Risk)"
    else:
        bias = "RANGE_BOUND"
        summary = (
            "Neutral Multi-TF: Market consolidating inside range without clear higher-TF slope"
        )

    return MultiTimeframeTrend(
        bias=bias,
        trend_15m=trend_15m,
        trend_5m=trend_5m,
        ema20_15m=round(ema20_15m, 2),
        ema50_15m=round(ema50_15m, 2),
        vwap_15m=round(ema20_15m, 2),
        summary=summary,
    )


# ── Heavyweight Posture Evaluation ───────────────────────────────────────────


def evaluate_heavyweight_confluence(underlying: str) -> tuple[str, str, dict[str, Any]]:
    """
    Fetches real-time heavyweight posture and returns alignment status.
    """
    try:
        from market.indices import get_heavyweights_posture

        hw = get_heavyweights_posture(underlying)
        if not hw or hw.get("summary") == "UNAVAILABLE":
            return "NEUTRAL", "Heavyweight feeds pending", hw

        summary = hw.get("summary", "MIXED")
        bull_cnt = hw.get("bull_count", 0)
        bear_cnt = hw.get("bear_count", 0)
        tot = hw.get("total_heavyweights", 0)

        detail_items = []
        for h in hw.get("heavyweights", []):
            detail_items.append(f"{h.get('symbol')} {h.get('change_pct', 0):+.2f}%")
        detail_str = f"({bull_cnt} Bull / {bear_cnt} Bear of {tot}): " + ", ".join(detail_items)

        if summary == "ALL_BULLISH":
            return "STRONG_BULLISH", detail_str, hw
        elif summary == "ALL_BEARISH":
            return "STRONG_BEARISH", detail_str, hw
        elif bull_cnt > 0 and bear_cnt > 0:
            return "POLARIZED_DIVIDED", detail_str, hw
        elif bull_cnt > bear_cnt:
            return "MODERATE_BULLISH", detail_str, hw
        elif bear_cnt > bull_cnt:
            return "MODERATE_BEARISH", detail_str, hw
        return "NEUTRAL", detail_str, hw
    except Exception as exc:
        logger.debug("[AdaptiveRegime] Heavyweights check error: %s", exc)
        return "NEUTRAL", "Heavyweights unavailable", {}


# ── Pillar 1: Eagle Eye Regime Radar Evaluator ───────────────────────────────


def evaluate_eagle_regime(
    symbol: str,
    spot: float,
    ohlcv_5m: Optional[pd.DataFrame],
    df_15m: Optional[pd.DataFrame] = None,
    ref_time: Optional[datetime] = None,
    vix_override: Optional[float] = None,
) -> EagleRegime:
    """
    Evaluates the full high-altitude Eagle Eye market regime.
    """
    clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").replace("BSE:", "").strip()

    # 1. Choppiness & ADX
    chop = compute_choppiness_index(ohlcv_5m, period=14)
    adx = compute_adx(ohlcv_5m, period=14)

    chop_val = chop if chop is not None else 50.0
    adx_val = adx if adx is not None else 22.0

    if chop_val >= 61.8:
        chop_status = "SEVERE_CHOP"
    elif chop_val <= 38.2:
        chop_status = "TRENDING_EXPANSION"
    else:
        chop_status = "NEUTRAL_DRIFT"

    if adx_val < 20.0:
        adx_status = "NON_TRENDING"
    elif adx_val >= 30.0:
        adx_status = "STRONG_TREND"
    else:
        adx_status = "MODERATE_TREND"

    # 2. Time-of-day phase
    phase, is_midday = get_time_of_day_phase(ref_time)

    # 3. Multi-TF trend
    mtf = evaluate_multi_timeframe_trend(ohlcv_5m, df_15m, spot=spot)

    # 4. Heavyweights
    hw_align, hw_detail, _ = evaluate_heavyweight_confluence(clean_sym)

    # 5. India VIX
    vix_val = vix_override
    if vix_val is None:
        try:
            from market.indices import get_vix

            raw_vix = get_vix()
            vix_val = float(raw_vix) if raw_vix and float(raw_vix) > 0 else None
        except Exception:
            vix_val = None

    if vix_val is not None:
        if vix_val < 13.0:
            vix_regime = "LOW_VIX_THETA_BURDEN"
        elif vix_val >= 18.0:
            vix_regime = "HIGH_VIX_CRUSH_RISK"
        else:
            vix_regime = "NORMAL_VIX"
    else:
        vix_regime = "NORMAL_VIX"

    # Overall environment synthesis
    if (chop_status == "SEVERE_CHOP" or adx_status == "NON_TRENDING" or is_midday) and (
        hw_align == "POLARIZED_DIVIDED" or mtf.bias == "CONTRARIAN_DIVERGENT"
    ):
        overall_env = "WHIPSAW_CHOP_TRAP"
    elif chop_status == "TRENDING_EXPANSION" and adx_status in ("STRONG_TREND", "MODERATE_TREND"):
        overall_env = "OPTIMAL_TREND_EXPANSION"
    elif chop_status == "SEVERE_CHOP" or is_midday:
        overall_env = "SELECTIVE_FADE"
    else:
        overall_env = "BALANCED_RANGE"

    summary = (
        f"🦅 Eagle Radar: {clean_sym} {overall_env} | CHOP: {chop_val:.1f} ({chop_status}) | "
        f"ADX: {adx_val:.1f} ({adx_status}) | Phase: {phase} | Multi-TF: {mtf.bias}"
    )

    return EagleRegime(
        symbol=clean_sym,
        spot=spot,
        chop_index=chop_val,
        chop_status=chop_status,
        adx_14=adx_val,
        adx_status=adx_status,
        multi_tf=mtf,
        heavyweights_alignment=hw_align,
        heavyweights_detail=hw_detail,
        market_phase=phase,
        is_midday_chop_window=is_midday,
        vix_val=vix_val,
        vix_regime=vix_regime,
        overall_environment=overall_env,
        summary=summary,
    )


# ── Pillar 2: Tiger Stalking Strategy Mandate ────────────────────────────────


def evaluate_tiger_mandate(
    eagle: EagleRegime,
    is_institutional_thrust: bool = False,
    is_liquidity_sweep: bool = False,
) -> TigerStrategyMandate:
    """
    Determines the operational trading mandate under the Tiger Stalking discipline.

    Rules:
      1. Institutional Expansion Thrust: Tiger Pounces immediately regardless of chop.
      2. Midday Theta Window (11:30 - 13:15 IST) or Severe Chop (CHOP >= 58 or ADX < 18):
         STALK ONLY. Suppress routine breakout setups to prevent whipsaw bleeding!
      3. Extreme Range Boundary Sweep (Turtle Soup): Allow boundary fades back to VWAP.
      4. Strong Trend: Execute Momentum Breakout & Retest cleanly.
    """
    # Rule 1: Exceptional Institutional Thrust Override — The Tiger Pounces!
    if is_institutional_thrust:
        return TigerStrategyMandate(
            mandate="MOMENTUM_EXPANSION",
            allow_routine_breakouts=True,
            allow_thrust_only=False,
            suggested_strategy="BUY_MOMENTUM",
            reason="🚀 Verified Institutional Expansion Thrust: High-velocity volume & ATR expansion ignited.",
            action_guidance="Tiger Pounce: Instant execution authorized with tight structural invalidation.",
        )

    # Rule 2: Liquidity Sweep of extreme boundaries in chop — Turtle Soup Reversal
    if is_liquidity_sweep and (eagle.chop_status == "SEVERE_CHOP" or eagle.is_midday_chop_window):
        return TigerStrategyMandate(
            mandate="TURTLE_SOUP_RANGE_FADE",
            allow_routine_breakouts=False,
            allow_thrust_only=False,
            suggested_strategy="FADE_BOUNDARY",
            reason="⚡ Range Boundary Sweep (Turtle Soup): False breakout rejected with absorption wick.",
            action_guidance="Execute mean-reversion scalp back to VWAP with stop just beyond the sweep wick.",
        )

    # Rule 3: Low VIX Mandatory Spreads
    if eagle.vix_regime == "LOW_VIX_THETA_BURDEN":
        return TigerStrategyMandate(
            mandate="DEFINED_RISK_SPREAD_ONLY",
            allow_routine_breakouts=True,
            allow_thrust_only=False,
            suggested_strategy="HEDGED_SPREAD",
            reason="🛡️ Low-VIX Regime (India VIX < 13.0): Naked option buying prohibited due to theta decay.",
            action_guidance="Execute defined-risk vertical debit spread only (Bull Call / Bear Put Spread).",
        )

    # Rule 4: Tiger Stalking & Capital Preservation Filter (Midday Lull or Severe Chop)
    is_severe_chop = eagle.chop_index >= 58.0 or eagle.adx_14 < 18.0
    if eagle.is_midday_chop_window or is_severe_chop:
        reason_parts = []
        if eagle.is_midday_chop_window:
            reason_parts.append("Midday Lull Window (11:30–13:15 IST) theta sink")
        if eagle.chop_index >= 58.0:
            reason_parts.append(f"Choppiness Index elevated ({eagle.chop_index:.1f} >= 58.0)")
        if eagle.adx_14 < 18.0:
            reason_parts.append(f"ADX directional strength depleted ({eagle.adx_14:.1f} < 18.0)")
        if eagle.heavyweights_alignment == "POLARIZED_DIVIDED":
            reason_parts.append("Heavyweights in tug-of-war polarization")

        combined_reason = "; ".join(reason_parts)
        return TigerStrategyMandate(
            mandate="TIGER_STALKING_PRESERVE_CAPITAL",
            allow_routine_breakouts=False,
            allow_thrust_only=True,
            suggested_strategy="WAIT_IN_CASH",
            reason=combined_reason,
            action_guidance=(
                "🐅 Tiger Stalking: Market in non-trending / chop duration. "
                "Routine breakout entries suspended to prevent whipsaw bleeding. "
                "Wait patiently for verified institutional expansion thrust or range boundary sweep."
            ),
        )

    # Rule 5: Healthy Trending Phase
    if (
        eagle.chop_status == "TRENDING_EXPANSION"
        or eagle.adx_14 >= 24.0
        or eagle.multi_tf.bias in ("BULLISH_ALIGNED", "BEARISH_ALIGNED")
    ):
        return TigerStrategyMandate(
            mandate="MOMENTUM_EXPANSION",
            allow_routine_breakouts=True,
            allow_thrust_only=False,
            suggested_strategy="BUY_MOMENTUM",
            reason=f"Strong Trending Expansion (CHOP={eagle.chop_index:.1f}, ADX={eagle.adx_14:.1f}, Multi-TF={eagle.multi_tf.bias})",
            action_guidance="Eagle Eye confirms directional impulse. Execute on OTE pullback with asymmetric targets.",
        )

    # Rule 6: Normal Adaptive Mode
    return TigerStrategyMandate(
        mandate="NORMAL_ADAPTIVE",
        allow_routine_breakouts=True,
        allow_thrust_only=False,
        suggested_strategy="SELECTIVE_SNIPER",
        reason="Normal market fluidity; standard confluence checks active.",
        action_guidance="Execute only with verified OTE pullback limit and strict zero-chase discipline.",
    )


# ── Pillar 3: Sniper Entry & Execution Planner ───────────────────────────────


def compute_sniper_execution_plan(
    symbol: str,
    direction: str,  # "BULLISH" | "BEARISH"
    spot: float,
    trigger_level: float,
    invalidation_level: float,
    target_1: float,
    opt_ltp: float = 0.0,
    target_2: Optional[float] = None,
    target_3: Optional[float] = None,
    setup_name: str = "SETUP",
    lot_size: int = 1,
) -> SniperExecutionPlan:
    """
    Computes institutional sniper execution plan with exact OTE pullback limits,
    strict no-chase boundaries, and risk-reward milestones.
    """
    clean_dir = direction.upper()
    is_bull = clean_dir == "BULLISH"

    # Calibration of step sizes and noise tolerance per index
    step_tolerance = {
        "NIFTY": 15.0,
        "BANKNIFTY": 40.0,
        "FINNIFTY": 18.0,
        "MIDCPNIFTY": 10.0,
        "SENSEX": 60.0,
        "BANKEX": 60.0,
    }.get(symbol.upper(), 25.0)

    # 1. Structural Invalidation & Risk Points
    if is_bull:
        risk_pts = max(step_tolerance * 0.8, spot - invalidation_level)
        t1 = target_1 if target_1 > spot else round(spot + (risk_pts * 1.8), 1)
        t2 = target_2 if (target_2 and target_2 > t1) else round(spot + (risk_pts * 3.5), 1)
        t3 = target_3 if (target_3 and target_3 > t2) else round(spot + (risk_pts * 5.0), 1)

        # OTE Pullback Range (Buy limit zone near trigger / VWAP)
        entry_min = round(max(invalidation_level + 2.0, trigger_level - (step_tolerance * 0.4)), 1)
        entry_max = round(trigger_level + (step_tolerance * 0.35), 1)
        no_chase = round(trigger_level + (step_tolerance * 0.85), 1)
        is_chase = spot > no_chase
        entry_instr = (
            f"🎯 Sniper Limit Buy on Pullback to ₹{entry_min:,.1f} – ₹{entry_max:,.1f}. "
            f"Strict Invalidation SL: ₹{invalidation_level:,.1f}. DO NOT CHASE above ₹{no_chase:,.1f}."
        )
    else:
        risk_pts = max(step_tolerance * 0.8, invalidation_level - spot)
        t1 = target_1 if target_1 < spot else round(spot - (risk_pts * 1.8), 1)
        t2 = target_2 if (target_2 and target_2 < t1) else round(spot - (risk_pts * 3.5), 1)
        t3 = target_3 if (target_3 and target_3 < t2) else round(spot - (risk_pts * 5.0), 1)

        # OTE Pullback Range (Sell/Put limit zone on retest of broken support)
        entry_max = round(min(invalidation_level - 2.0, trigger_level + (step_tolerance * 0.4)), 1)
        entry_min = round(trigger_level - (step_tolerance * 0.35), 1)
        no_chase = round(trigger_level - (step_tolerance * 0.85), 1)
        is_chase = spot < no_chase
        entry_instr = (
            f"🎯 Sniper Limit Buy PE on Bounce to ₹{entry_min:,.1f} – ₹{entry_max:,.1f}. "
            f"Strict Invalidation SL: ₹{invalidation_level:,.1f}. DO NOT CHASE below ₹{no_chase:,.1f}."
        )

    rr_t1 = round(abs(t1 - spot) / max(1.0, risk_pts), 2)

    return SniperExecutionPlan(
        setup_name=setup_name,
        direction=clean_dir,
        spot=spot,
        trigger_level=trigger_level,
        entry_zone_min=entry_min,
        entry_zone_max=entry_max,
        no_chase_boundary=no_chase,
        structural_invalidation=invalidation_level,
        risk_points=round(risk_pts, 1),
        target_1=t1,
        target_2=t2,
        target_3=t3,
        risk_reward_t1=rr_t1,
        is_chasing=is_chase,
        entry_instruction=entry_instr,
        time_stop_minutes=20,
    )


# ── Unified Evaluator: Eagle + Tiger + Sniper ────────────────────────────────


def evaluate_index_adaptive_regime(
    underlying: str,
    spot: float,
    ohlcv_5m: Optional[pd.DataFrame] = None,
    df_15m: Optional[pd.DataFrame] = None,
    ref_time: Optional[datetime] = None,
    is_institutional_thrust: bool = False,
    is_liquidity_sweep: bool = False,
    vix_override: Optional[float] = None,
    force_refresh: bool = False,
) -> AdaptiveIndexDecision:
    """
    Universal Single Source of Truth for Index Adaptive Trading.
    Returns cached decision if fresh (<15s) unless force_refresh=True.
    """
    clean_sym = (
        underlying.upper().replace(".NS", "").replace("NSE:", "").replace("BSE:", "").strip()
    )
    now_ts = time.time()
    is_testing = bool(
        os.environ.get("CHANAKYA_TESTING")
        or os.environ.get("PYTEST_CURRENT_TEST")
        or os.environ.get("DEPLOY_MODE") == "test"
    )

    if not force_refresh and not is_testing:
        with _REGIME_CACHE_LOCK:
            cached = _REGIME_CACHE.get(clean_sym)
            if cached and (now_ts - cached[0]) < _REGIME_CACHE_TTL:
                return cached[1]

    eagle = evaluate_eagle_regime(
        symbol=clean_sym,
        spot=spot,
        ohlcv_5m=ohlcv_5m,
        df_15m=df_15m,
        ref_time=ref_time,
        vix_override=vix_override,
    )

    tiger = evaluate_tiger_mandate(
        eagle=eagle,
        is_institutional_thrust=is_institutional_thrust,
        is_liquidity_sweep=is_liquidity_sweep,
    )

    now_iso = (ref_time or datetime.now(IST)).strftime("%Y-%m-%d %H:%M:%S IST")
    decision = AdaptiveIndexDecision(
        symbol=clean_sym,
        spot=spot,
        eagle=eagle,
        tiger=tiger,
        sniper=None,
        evaluated_at=now_iso,
    )

    with _REGIME_CACHE_LOCK:
        _REGIME_CACHE[clean_sym] = (now_ts, decision)

    return decision
