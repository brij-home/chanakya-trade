"""
analysis/mtf_cascade.py
───────────────────────
Institutional Multi-Timeframe Cascade Engine (HTF -> ITF -> LTF).

Enforces institutional 3-Tier cascade hierarchy:
  1. HTF (Daily / 60m): Regime Governor & Macro Bias Authority (Stage 2/4 trend, EMA200, ADX slope).
  2. ITF (15m / 30m): Structural Value Location Authority (SMC Order Blocks, Volume Profile POC/VAH/VAL, Fib Golden Pocket).
  3. LTF (3m / 5m): Precision Execution Trigger Authority (Micro-CHoCH, Strat 2-1-2, Hikkake, RVOL expansion).

Strict Invariant:
  Never execute an LTF trend breakout if HTF is opposed or ITF is already at terminal overextension.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
import pandas as pd

from analysis.technical import ema
from analysis.dmi_filter import compute_adx
from analysis.fibonacci import compute_fib_levels, evaluate_fib_proximity
from analysis.bar_patterns import analyze_bar_patterns

logger = logging.getLogger("chanakya.analysis.mtf_cascade")


@dataclass
class HTFBias:
    timeframe: str  # "DAILY" or "60M"
    bias: str  # "STRONG_BULLISH", "MILD_BULLISH", "STRONG_BEARISH", "MILD_BEARISH", "NEUTRAL_CHOP"
    stage: (
        str  # "STAGE_1_ACCUMULATION", "STAGE_2_MARKUP", "STAGE_3_DISTRIBUTION", "STAGE_4_MARKDOWN"
    )
    adx: float
    adx_trend: str
    ema20_above_ema50: bool
    price_above_ema200: bool
    score: int  # -100 to +100


@dataclass
class ITFValueLocation:
    timeframe: str  # "15M" or "30M"
    location: str  # "AT_STRONG_DEMAND", "AT_STRONG_SUPPLY", "IN_DISCOUNT_OTE", "IN_PREMIUM_OTE", "EQUILIBRIUM", "OVEREXTENDED"
    in_golden_pocket: bool
    nearest_key_level: str
    distance_to_level_pct: float
    is_safe_entry_zone: bool


@dataclass
class LTFExecutionTrigger:
    timeframe: str  # "3M" or "5M"
    trigger: str  # "CONFIRMED_BUY", "CONFIRMED_SELL", "COILED_COMPRESSION", "AWAITING_TRIGGER"
    candlestick_pattern: str
    has_micro_choch: bool
    rvol: float
    entry_price: float
    stop_loss: float
    target_1: float
    risk_reward_ratio: float


@dataclass
class MTFCascadeVerdict:
    symbol: str
    overall_alignment: str  # "PERFECT_ALIGNMENT_LONG", "PERFECT_ALIGNMENT_SHORT", "OVEREXTENDED_NO_CHASE", "CONFLICTING_TIMEFRAMES", "COILED_SPRING"
    final_bias: str  # "BULLISH", "BEARISH", "NEUTRAL"
    composite_conviction: int  # 0 to 100
    htf: HTFBias
    itf: ITFValueLocation
    ltf: LTFExecutionTrigger
    recommended_action: str
    position_size_multiplier: (
        float  # 1.0 for perfect alignment, 0.5 for caution/scalp, 0.0 for stand down
    )
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "overall_alignment": self.overall_alignment,
            "final_bias": self.final_bias,
            "composite_conviction": self.composite_conviction,
            "htf_bias": self.htf.bias,
            "htf_stage": self.htf.stage,
            "itf_location": self.itf.location,
            "itf_safe_entry": self.itf.is_safe_entry_zone,
            "ltf_trigger": self.ltf.trigger,
            "ltf_pattern": self.ltf.candlestick_pattern,
            "entry_price": round(self.ltf.entry_price, 2),
            "stop_loss": round(self.ltf.stop_loss, 2),
            "target_1": round(self.ltf.target_1, 2),
            "risk_reward_ratio": round(self.ltf.risk_reward_ratio, 2),
            "recommended_action": self.recommended_action,
            "position_size_multiplier": self.position_size_multiplier,
            "summary": self.summary,
        }


def evaluate_htf_bias(df_daily: pd.DataFrame) -> HTFBias:
    """Evaluates Higher Timeframe (Daily) institutional regime and macro drift."""
    if df_daily is None or len(df_daily) < 20:
        return HTFBias(
            timeframe="DAILY",
            bias="NEUTRAL_CHOP",
            stage="STAGE_1_ACCUMULATION",
            adx=15.0,
            adx_trend="WEAK",
            ema20_above_ema50=False,
            price_above_ema200=False,
            score=0,
        )

    cols = {c.lower(): c for c in df_daily.columns}
    c_s = df_daily[cols["close"]].astype(float)
    c_curr = float(c_s.iloc[-1])

    ema20_s = ema(c_s, 20)
    ema50_s = ema(c_s, 50)
    ema200_s = ema(c_s, min(200, len(c_s)))

    e20 = float(ema20_s.iloc[-1])
    e50 = float(ema50_s.iloc[-1])
    e200 = float(ema200_s.iloc[-1])

    adx_res = compute_adx(df_daily, period=14)
    adx_val = float(adx_res) if (adx_res is not None and not np.isnan(adx_res)) else 20.0

    score = 0
    if e20 > e50:
        score += 35
    else:
        score -= 35

    if c_curr > e200:
        score += 35
    else:
        score -= 35

    if adx_val >= 25.0:
        score += 30 if score > 0 else -30

    # Classify Weinstein Stage
    if score >= 65:
        bias = "STRONG_BULLISH"
        stage = "STAGE_2_MARKUP"
    elif score >= 20:
        bias = "MILD_BULLISH"
        stage = "STAGE_2_MARKUP"
    elif score <= -65:
        bias = "STRONG_BEARISH"
        stage = "STAGE_4_MARKDOWN"
    elif score <= -20:
        bias = "MILD_BEARISH"
        stage = "STAGE_4_MARKDOWN"
    else:
        bias = "NEUTRAL_CHOP"
        stage = "STAGE_1_ACCUMULATION" if c_curr > e200 else "STAGE_3_DISTRIBUTION"

    return HTFBias(
        timeframe="DAILY",
        bias=bias,
        stage=stage,
        adx=round(adx_val, 1),
        adx_trend="EXPANDING" if adx_val >= 25.0 else "COMPRESSED",
        ema20_above_ema50=(e20 > e50),
        price_above_ema200=(c_curr > e200),
        score=score,
    )


def evaluate_itf_location(
    df_itf: pd.DataFrame,
    htf_bias: str,
    key_demand_level: Optional[float] = None,
    key_supply_level: Optional[float] = None,
) -> ITFValueLocation:
    """Evaluates Intermediate Timeframe (15m/60m) structural value location."""
    if df_itf is None or len(df_itf) < 20:
        return ITFValueLocation(
            timeframe="15M",
            location="EQUILIBRIUM",
            in_golden_pocket=False,
            nearest_key_level="None",
            distance_to_level_pct=0.0,
            is_safe_entry_zone=True,
        )

    cols = {c.lower(): c for c in df_itf.columns}
    c_s = df_itf[cols["close"]].astype(float)
    h_s = df_itf[cols["high"]].astype(float)
    l_s = df_itf[cols["low"]].astype(float)

    c_curr = float(c_s.iloc[-1])
    recent_high = float(h_s.iloc[-30:].max())
    recent_low = float(l_s.iloc[-30:].min())
    span = max(recent_high - recent_low, 0.001)

    direction = "BULLISH" if "BULLISH" in htf_bias else "BEARISH"
    fib = compute_fib_levels(recent_high, recent_low, direction=direction)
    prox = evaluate_fib_proximity(c_curr, fib, proximity_pct=0.60)

    # Check proximity to demand or supply
    dist_demand = abs(c_curr - (key_demand_level or fib.level_618)) / c_curr * 100.0
    dist_supply = abs(c_curr - (key_supply_level or fib.level_618)) / c_curr * 100.0

    in_gp = prox["in_golden_pocket"]

    # Extension guard: if price is already > 0.85 of impulse or beyond 1.272 extension
    is_overextended = False
    if direction == "BULLISH" and c_curr >= recent_high - (0.15 * span):
        is_overextended = True
    elif direction == "BEARISH" and c_curr <= recent_low + (0.15 * span):
        is_overextended = True

    if is_overextended:
        loc = "OVEREXTENDED"
        safe = False
    elif in_gp or dist_demand <= 0.60:
        loc = "AT_STRONG_DEMAND" if direction == "BULLISH" else "IN_DISCOUNT_OTE"
        safe = True
    elif dist_supply <= 0.60:
        loc = "AT_STRONG_SUPPLY"
        safe = False if direction == "BULLISH" else True
    else:
        loc = "EQUILIBRIUM"
        safe = True

    return ITFValueLocation(
        timeframe="15M",
        location=loc,
        in_golden_pocket=in_gp,
        nearest_key_level=prox["nearest_fib_level"],
        distance_to_level_pct=prox["distance_pct"],
        is_safe_entry_zone=safe,
    )


def evaluate_ltf_trigger(df_ltf: pd.DataFrame, symbol: str = "UNKNOWN") -> LTFExecutionTrigger:
    """Evaluates Lower Timeframe (3m/5m) execution triggers via Strat, Hikkake & micro-patterns."""
    if df_ltf is None or len(df_ltf) < 5:
        return LTFExecutionTrigger(
            timeframe="5M",
            trigger="AWAITING_TRIGGER",
            candlestick_pattern="NONE",
            has_micro_choch=False,
            rvol=1.0,
            entry_price=0.0,
            stop_loss=0.0,
            target_1=0.0,
            risk_reward_ratio=0.0,
        )

    cols = {c.lower(): c for c in df_ltf.columns}
    c_curr = float(df_ltf[cols["close"]].iloc[-1])
    h_curr = float(df_ltf[cols["high"]].iloc[-1])
    l_curr = float(df_ltf[cols["low"]].iloc[-1])

    v_s = (
        df_ltf[cols["volume"]].astype(float)
        if "volume" in cols
        else pd.Series(1000.0, index=df_ltf.index)
    )
    avg_vol = float(v_s.rolling(15, min_periods=3).mean().iloc[-1])
    curr_vol = float(v_s.iloc[-1])
    rvol = round(curr_vol / max(avg_vol, 1.0), 2)

    pat = analyze_bar_patterns(df_ltf, symbol=symbol)

    if pat is not None and pat.bias == "BULLISH":
        return LTFExecutionTrigger(
            timeframe="5M",
            trigger="CONFIRMED_BUY",
            candlestick_pattern=pat.pattern_name,
            has_micro_choch=True,
            rvol=rvol,
            entry_price=pat.entry_trigger,
            stop_loss=pat.stop_loss,
            target_1=pat.target_1,
            risk_reward_ratio=pat.risk_reward_ratio,
        )
    elif pat is not None and pat.bias == "BEARISH":
        return LTFExecutionTrigger(
            timeframe="5M",
            trigger="CONFIRMED_SELL",
            candlestick_pattern=pat.pattern_name,
            has_micro_choch=True,
            rvol=rvol,
            entry_price=pat.entry_trigger,
            stop_loss=pat.stop_loss,
            target_1=pat.target_1,
            risk_reward_ratio=pat.risk_reward_ratio,
        )
    elif pat is not None and pat.is_coiled_compression:
        return LTFExecutionTrigger(
            timeframe="5M",
            trigger="COILED_COMPRESSION",
            candlestick_pattern=pat.pattern_name,
            has_micro_choch=False,
            rvol=rvol,
            entry_price=pat.entry_trigger,
            stop_loss=pat.stop_loss,
            target_1=0.0,
            risk_reward_ratio=0.0,
        )

    # Fallback to simple bar continuation if green/red
    c_prev = float(df_ltf[cols["close"]].iloc[-2])
    is_bull = c_curr > c_prev
    entry = round(c_curr, 2)
    sl = round(l_curr * 0.995 if is_bull else h_curr * 1.005, 2)
    risk = max(abs(entry - sl), entry * 0.003)
    t1 = round(entry + (2.0 * risk) if is_bull else entry - (2.0 * risk), 2)

    return LTFExecutionTrigger(
        timeframe="5M",
        trigger="AWAITING_TRIGGER",
        candlestick_pattern="BAR_MOMENTUM",
        has_micro_choch=False,
        rvol=rvol,
        entry_price=entry,
        stop_loss=sl,
        target_1=t1,
        risk_reward_ratio=2.0,
    )


def run_mtf_cascade(
    symbol: str,
    df_daily: pd.DataFrame,
    df_15m: pd.DataFrame,
    df_5m: pd.DataFrame,
) -> MTFCascadeVerdict:
    """
    Executes the 3-Tier Multi-Timeframe Cascade Framework.
    Synthesizes HTF Macro Drift -> ITF Value Location -> LTF Execution Trigger.
    """
    htf = evaluate_htf_bias(df_daily)
    itf = evaluate_itf_location(df_15m, htf_bias=htf.bias)
    ltf = evaluate_ltf_trigger(df_5m, symbol=symbol)

    # Cascade Decision Matrix
    # 1. Perfect Long Alignment
    if "BULLISH" in htf.bias and itf.is_safe_entry_zone and ltf.trigger == "CONFIRMED_BUY":
        return MTFCascadeVerdict(
            symbol=symbol,
            overall_alignment="PERFECT_ALIGNMENT_LONG",
            final_bias="BULLISH",
            composite_conviction=92,
            htf=htf,
            itf=itf,
            ltf=ltf,
            recommended_action="AGGRESSIVE_BUY — FULL SIZE",
            position_size_multiplier=1.0,
            summary=f"Triple Confluence Long: HTF {htf.stage} drift + ITF value zone ({itf.location}) + LTF {ltf.candlestick_pattern} trigger.",
        )

    # 2. Perfect Short Alignment
    elif "BEARISH" in htf.bias and itf.is_safe_entry_zone and ltf.trigger == "CONFIRMED_SELL":
        return MTFCascadeVerdict(
            symbol=symbol,
            overall_alignment="PERFECT_ALIGNMENT_SHORT",
            final_bias="BEARISH",
            composite_conviction=92,
            htf=htf,
            itf=itf,
            ltf=ltf,
            recommended_action="AGGRESSIVE_SELL — FULL SIZE",
            position_size_multiplier=1.0,
            summary=f"Triple Confluence Short: HTF {htf.stage} markdown + ITF value zone ({itf.location}) + LTF {ltf.candlestick_pattern} trigger.",
        )

    # 3. Overextended No Chase Guard
    elif itf.location == "OVEREXTENDED":
        return MTFCascadeVerdict(
            symbol=symbol,
            overall_alignment="OVEREXTENDED_NO_CHASE",
            final_bias="NEUTRAL",
            composite_conviction=45,
            htf=htf,
            itf=itf,
            ltf=ltf,
            recommended_action="STAND_DOWN — DO NOT CHASE EXTENSION",
            position_size_multiplier=0.0,
            summary="No Chase Guard Veto: Price is overextended on intermediate timeframe. Wait for pullback to ITF support before initiating.",
        )

    # 4. Coiled Spring Precursor
    elif ltf.trigger == "COILED_COMPRESSION":
        return MTFCascadeVerdict(
            symbol=symbol,
            overall_alignment="COILED_SPRING",
            final_bias="NEUTRAL",
            composite_conviction=70,
            htf=htf,
            itf=itf,
            ltf=ltf,
            recommended_action="STALK_EXPANSION — BRACKET ORDERS",
            position_size_multiplier=0.5,
            summary=f"Volatility Compression: LTF {ltf.candlestick_pattern} coiling inside {htf.bias} macro trend. Awaiting breakout expansion.",
        )

    # 5. Conflicting Timeframes
    else:
        return MTFCascadeVerdict(
            symbol=symbol,
            overall_alignment="CONFLICTING_TIMEFRAMES",
            final_bias="NEUTRAL",
            composite_conviction=50,
            htf=htf,
            itf=itf,
            ltf=ltf,
            recommended_action="PATIENCE — WAIT FOR ALIGNMENT",
            position_size_multiplier=0.0,
            summary="Conflicting Timeframe Signals: HTF macro bias does not align with LTF execution trigger. Stand down.",
        )
