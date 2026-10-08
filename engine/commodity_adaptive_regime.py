"""
engine/commodity_adaptive_regime.py
───────────────────────────────────
Institutional Adaptive Commodity Trading Strategy & Regime Engine for MCX.

Implements the Three Pillars of Institutional Trading Excellence for Indian Commodities
(Crude Oil, Natural Gas, Gold, Silver, Copper, Zinc):

  1. 🦅 EAGLE EYE (Macro, Multi-Timeframe & Intermarket Regime Radar):
     - Choppiness Index (CHOP, E.W. Dreiss formula): Quantifies consolidation vs expansion regimes.
     - Wilder's Average Directional Index (ADX-14): Quantifies directional momentum strength.
     - 5-Phase MCX Session Clock:
         * Asian Initial Balance (09:00 – 11:30 IST)
         * Midday Volume Lull & Whipsaw Trap (11:30 – 15:30 IST)
         * European Pre-Market Transition (15:30 – 17:30 IST)
         * US Pit & NYMEX/COMEX Active Session ("Golden Hours", 17:30 – 22:30 IST)
         * Terminal Square-Off Window (22:30 – 23:30 IST)
     - Cross-Asset Intermarket Flows: DXY Dollar Surge Veto for Bullion, Brent/WTI Divergence for Energy.
     - Microstructure CVD & Trap Candle Guard: Detects seller/buyer absorption delta divergence.

  2. 🐅 TIGER STALKING (Regime-Adaptive Patience & Trap Annihilation):
     - Stalking Mode: During Midday Volume Lulls (11:30–15:30) or High Chop (CHOP >= 61.8 / ADX < 20),
       routine breakouts are STRICTLY SUPPRESSED. Prevents whipsaw bleeding and premature stop-outs.
     - Pounce Mode: Strikes decisively ONLY when institutional expansion thrust, RVOL >= 1.8x,
       or high-conviction order flow delta aggression occurs.
     - Strategy Selection:
         * Trending Expansion    -> Momentum Sniper (Donchian Expansion, SMC BOS Retest).
         * Rangebound Midday Chop -> Tiger Stalking (Preserve Capital in Cash).
         * Extreme Wick Exhaustion -> Turtle Soup Fade / Liquidity Sweep Reclaim.

  3. 🎯 SNIPER ENTRY (Optimal Trade Entry, Pullback Timing, Zero FOMO Chase):
     - Optimal Trade Entry (OTE): Retest limit orders anchored to 50%–61.8% pullback into broken structure / VWAP.
     - Strict No-Chase Boundary: Hard mathematical ceiling (+0.15R) beyond which entry is disqualified.
     - Coupled Option Blueprint: ATM option delta coupling (Delta ≈ 0.52), defined-risk capped outlay.
     - 25-Minute Time-Stop Invariant: Kills stagnant options trades before theta and IV decay erode capital.
     - Rule 12 Asymmetry: Target 1 calibrated to +3.0R (Scale 50%, Move SL to Cost), T2 (+5.0R), Runner (+7.5R).
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import asdict, dataclass
from datetime import datetime, time as dtime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from market.instruments import COMMODITY_SYMBOLS

logger = logging.getLogger("chanakya.commodity_adaptive_regime")
IST = ZoneInfo("Asia/Kolkata")

# Canonical noise tolerance & step scale per commodity
COMMODITY_STEP_TOLERANCES: dict[str, float] = {
    "CRUDEOIL": 15.0,
    "CRUDEOILM": 15.0,
    "NATURALGAS": 1.5,
    "NATGASMINI": 1.5,
    "GOLD": 75.0,
    "GOLDM": 75.0,
    "SILVER": 150.0,
    "SILVERM": 150.0,
    "COPPER": 1.2,
    "ZINC": 0.8,
    "ALUMINIUM": 0.8,
    "LEAD": 0.8,
}


# ── Data Models ───────────────────────────────────────────────────────────────


@dataclass
class CommodityEagleRegime:
    """Pillar 1: 🦅 Eagle Eye — High-altitude multi-dimensional commodity regime radar."""

    symbol: str
    spot: float
    chop_index: float  # 0.0 to 100.0 (>=61.8 = severe chop, <=38.2 = strong trend)
    chop_status: str  # "SEVERE_CHOP" | "TRENDING_EXPANSION" | "NEUTRAL_DRIFT"
    adx_14: float  # < 20 = non-trending, >= 25 = trending
    adx_status: str  # "NON_TRENDING" | "MODERATE_TREND" | "STRONG_TREND"
    session_phase: str  # "ASIAN_DISCOVERY" | "MIDDAY_VOLUME_LULL" | "EUROPEAN_PRE_MARKET" | "US_GOLDEN_HOURS" | "TERMINAL_CLOSE"
    is_golden_hours: bool
    is_midday_lull: bool
    macro_alignment: str  # "TAILWIND" | "HEADWIND_VETO" | "NEUTRAL"
    macro_detail: str
    cvd_ratio: float
    trap_detected: bool
    trap_reason: Optional[str]
    overall_environment: str  # "OPTIMAL_TREND_EXPANSION" | "WHIPSAW_CHOP_TRAP" | "SELECTIVE_FADE" | "BALANCED_RANGE"
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CommodityTigerMandate:
    """Pillar 2: 🐅 Tiger Stalking — Regime-adaptive strategy selection & trap filter."""

    mandate: str  # "MOMENTUM_EXPANSION" | "TIGER_STALKING_PRESERVE_CAPITAL" | "TURTLE_SOUP_FADE" | "DEFINED_RISK_SPREAD_MANDATORY"
    allow_routine_breakouts: bool  # False during chop/midday lull unless institutional surge verified
    allow_thrust_only: bool  # True when in stalking mode
    suggested_strategy: str  # "BUY_MOMENTUM" | "WAIT_IN_CASH" | "FADE_BOUNDARY" | "HEDGED_SPREAD"
    reason: str
    action_guidance: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CommoditySniperPlan:
    """Pillar 3: 🎯 Sniper Entry — Exact killzone, pullback timing, tight SL & no-chase boundary."""

    setup_name: str
    direction: str  # "BULLISH" | "BEARISH"
    spot: float
    trigger_level: float
    entry_zone_min: float  # Limit pullback min
    entry_zone_max: float  # Limit pullback max
    no_chase_boundary: float  # Strict price beyond which entry is prohibited
    structural_invalidation: float  # Structure-anchored SL
    risk_points: float  # Invalidation distance in points
    target_1: float  # +3.0R (Rule 12 compliant)
    target_2: float  # +5.0R
    target_3: float  # +7.5R Runner
    risk_reward_t1: float
    is_chasing: bool
    entry_instruction: str
    time_stop_minutes: int = 25
    option_contract: Optional[str] = None
    option_entry_range: Optional[str] = None
    option_stop_loss: Optional[float] = None
    option_target_1: Optional[float] = None
    option_target_2: Optional[float] = None
    option_max_loss_capped: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AdaptiveCommodityDecision:
    """Complete synthesized evaluation combining Eagle, Tiger, and Sniper."""

    symbol: str
    spot: float
    eagle: CommodityEagleRegime
    tiger: CommodityTigerMandate
    sniper: Optional[CommoditySniperPlan] = None
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


# ── Pillar 1: Eagle Eye Calculations ──────────────────────────────────────────


def compute_commodity_choppiness_index(
    df: Optional[pd.DataFrame], period: int = 14
) -> Optional[float]:
    """
    Computes E.W. Dreiss Choppiness Index (CHOP) on commodity OHLCV bars.

    Formula:
        CHOP = 100 * LOG10(Sum(TrueRange, period) / (MaxHigh(period) - MinLow(period))) / LOG10(period)

    Interpretation:
        - CHOP >= 61.8: Severe consolidation / chop. High false breakout risk!
        - CHOP <= 38.2: Strong trending expansion. Real directional thrust!
        - 38.2 < CHOP < 61.8: Transitional consolidation or mature trend.
    """
    if df is None or len(df) < period + 1:
        return None
    try:
        col_h = "high" if "high" in df.columns else "High"
        col_l = "low" if "low" in df.columns else "Low"
        col_c = "close" if "close" in df.columns else "Close"

        highs = df[col_h].astype(float).values
        lows = df[col_l].astype(float).values
        closes = df[col_c].astype(float).values

        tr_list = []
        for i in range(1, len(df)):
            tr1 = highs[i] - lows[i]
            tr2 = abs(highs[i] - closes[i - 1])
            tr3 = abs(lows[i] - closes[i - 1])
            tr_list.append(max(tr1, tr2, tr3))

        if len(tr_list) < period:
            return None

        tr_sum = sum(tr_list[-period:])
        max_high = max(highs[-period:])
        min_low = min(lows[-period:])
        hl_range = max_high - min_low

        if hl_range <= 0.0:
            return 100.0  # Zero range = complete stagnation

        ratio = tr_sum / hl_range
        if ratio <= 0.0:
            return 0.0

        chop = 100.0 * (math.log10(ratio) / math.log10(period))
        return round(max(0.0, min(100.0, chop)), 2)
    except Exception as exc:
        logger.debug("[CommodityAdaptiveRegime] Choppiness calculation failed: %s", exc)
        return None


def compute_commodity_adx(
    df: Optional[pd.DataFrame], period: int = 14
) -> Optional[float]:
    """
    Computes 14-period Wilder's Average Directional Index (ADX) on commodity bars.

    Interpretation:
        - ADX < 20.0: Non-trending, weak directional momentum, rangebound drift.
        - 20.0 <= ADX < 25.0: Emerging or consolidating trend.
        - ADX >= 25.0: Healthy directional trend.
        - ADX >= 40.0: Parabolic or explosive impulse trend.
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
        logger.debug("[CommodityAdaptiveRegime] ADX calculation failed: %s", exc)
        return None


def get_commodity_session_phase(
    dt: Optional[datetime] = None,
) -> tuple[str, bool, bool]:
    """
    Classifies the MCX commodity trading clock into institutional liquidity windows.

    Returns:
        (phase_name, is_golden_hours, is_midday_lull)
    """
    now_dt = dt or datetime.now(IST)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=IST)
    else:
        now_dt = now_dt.astimezone(IST)

    if now_dt.weekday() >= 5:
        return "WEEKEND_CLOSED", False, False

    t = now_dt.time()
    if t < dtime(9, 0) or t > dtime(23, 30):
        return "SESSION_CLOSED", False, False
    if t < dtime(11, 30):
        # 09:00 - 11:30 IST: Domestic opening & Asian balance discovery
        return "ASIAN_DISCOVERY", False, False
    if t < dtime(15, 30):
        # 11:30 - 15:30 IST: Midday Volume Lull (European pre-open, low institutional participation)
        return "MIDDAY_VOLUME_LULL", False, True
    if t < dtime(17, 30):
        # 15:30 - 17:30 IST: European open transition & preliminary London flow
        return "EUROPEAN_PRE_MARKET", False, False
    if t <= dtime(22, 30):
        # 17:30 - 22:30 IST: US Pit & NYMEX/COMEX Active Session (Golden Hours)
        return "US_GOLDEN_HOURS", True, False
    # 22:30 - 23:30 IST: Terminal close & intraday square-off phase
    return "TERMINAL_CLOSE", False, False


def evaluate_commodity_eagle_regime(
    symbol: str,
    spot: float,
    df_5m: Optional[pd.DataFrame] = None,
    ref_time: Optional[datetime] = None,
    cvd_ratio: float = 1.0,
    trap_detected: bool = False,
    trap_reason: Optional[str] = None,
) -> CommodityEagleRegime:
    """
    Synthesizes Pillar 1: Eagle Eye high-altitude regime radar for commodities.
    """
    clean_sym = symbol.upper().replace("MCX:", "").strip()
    now_dt = ref_time or datetime.now(IST)

    phase_name, is_golden, is_lull = get_commodity_session_phase(now_dt)

    chop_val = compute_commodity_choppiness_index(df_5m)
    if chop_val is None:
        chop_val = 50.0

    if chop_val >= 61.8:
        chop_status = "SEVERE_CHOP"
    elif chop_val <= 38.2:
        chop_status = "TRENDING_EXPANSION"
    else:
        chop_status = "NEUTRAL_DRIFT"

    adx_val = compute_commodity_adx(df_5m)
    if adx_val is None:
        adx_val = 22.0

    if adx_val < 20.0:
        adx_status = "NON_TRENDING"
    elif adx_val >= 35.0:
        adx_status = "STRONG_TREND"
    else:
        adx_status = "MODERATE_TREND"

    # Global Macro Intermarket Alignment Check
    macro_align = "NEUTRAL"
    macro_detail = "Normal macro backdrop"
    try:
        from market.macro import get_macro_snapshot

        snap = get_macro_snapshot()
        if snap:
            if clean_sym in ("GOLD", "GOLDM", "SILVER", "SILVERM"):
                dxy = snap.dxy_change
                if dxy is not None and dxy >= 0.25:
                    macro_align = "HEADWIND_VETO"
                    macro_detail = f"Surging DXY (+{dxy:.2f}%) creates strong headwind for bullion longs"
                elif dxy is not None and dxy <= -0.25:
                    macro_align = "TAILWIND"
                    macro_detail = f"Declining DXY ({dxy:.2f}%) provides bullish monetary tailwind"
            elif clean_sym in ("CRUDEOIL", "CRUDEOILM"):
                crude_chg = snap.crude_change
                if crude_chg is not None and crude_chg <= -1.2:
                    macro_align = "HEADWIND_VETO"
                    macro_detail = f"Collapsing international Brent ({crude_chg:.2f}%) vetoes domestic crude longs"
                elif crude_chg is not None and crude_chg >= 1.2:
                    macro_align = "TAILWIND"
                    macro_detail = f"Surging Brent (+{crude_chg:.2f}%) confirms institutional energy demand"
    except Exception as e_mac:
        logger.debug("[CommodityAdaptiveRegime] Macro snapshot check error: %s", e_mac)

    # Environment Classification
    if trap_detected:
        env = "COUNTER_TREND_EXHAUSTION"
        summary = f"Trap detected: {trap_reason or 'Delta absorption divergence'}. High failure risk."
    elif is_lull and (chop_status == "SEVERE_CHOP" or adx_status == "NON_TRENDING"):
        env = "WHIPSAW_CHOP_TRAP"
        summary = "Midday Volume Lull (11:30–15:30) with non-trending chop. Routine breakouts strictly suppressed."
    elif is_golden and chop_status == "TRENDING_EXPANSION" and adx_status in ("MODERATE_TREND", "STRONG_TREND"):
        env = "OPTIMAL_TREND_EXPANSION"
        summary = "US Golden Hours (17:30–22:30) active with strong directional trend expansion. High follow-through probability."
    elif is_golden:
        env = "BALANCED_RANGE"
        summary = "US Active session active with moderate momentum. Selective sniper setups permitted."
    else:
        env = "BALANCED_RANGE"
        summary = f"Standard {phase_name.replace('_', ' ').title()} conditions with {chop_status.lower().replace('_', ' ')}."

    return CommodityEagleRegime(
        symbol=clean_sym,
        spot=spot,
        chop_index=chop_val,
        chop_status=chop_status,
        adx_14=adx_val,
        adx_status=adx_status,
        session_phase=phase_name,
        is_golden_hours=is_golden,
        is_midday_lull=is_lull,
        macro_alignment=macro_align,
        macro_detail=macro_detail,
        cvd_ratio=cvd_ratio,
        trap_detected=trap_detected,
        trap_reason=trap_reason,
        overall_environment=env,
        summary=summary,
    )


# ── Pillar 2: Tiger Stalking Strategy Selection ───────────────────────────────


def evaluate_commodity_tiger_mandate(
    eagle: CommodityEagleRegime,
    is_institutional_thrust: bool = False,
    rvol: float = 1.0,
    has_smc_confluence: bool = False,
) -> CommodityTigerMandate:
    """
    Synthesizes Pillar 2: Tiger Stalking discipline for commodities.
    """
    # 1. Trap / Severe Headwind -> Complete suppression
    if eagle.trap_detected:
        return CommodityTigerMandate(
            mandate="TIGER_STALKING_PRESERVE_CAPITAL",
            allow_routine_breakouts=False,
            allow_thrust_only=False,
            suggested_strategy="WAIT_IN_CASH",
            reason=f"🛑 Trap candle detected: {eagle.trap_reason or 'Delta absorption'}.",
            action_guidance="Do not enter. Institutional sellers absorbing breakout orders.",
        )

    if eagle.macro_alignment == "HEADWIND_VETO" and not is_institutional_thrust:
        return CommodityTigerMandate(
            mandate="TIGER_STALKING_PRESERVE_CAPITAL",
            allow_routine_breakouts=False,
            allow_thrust_only=False,
            suggested_strategy="WAIT_IN_CASH",
            reason=f"🛑 Macro Veto: {eagle.macro_detail}.",
            action_guidance="Preserve capital. Cross-market macro flow strongly opposes trade direction.",
        )

    # 2. Midday Volume Lull (11:30 – 15:30 IST) or Severe Chop
    if eagle.is_midday_lull or eagle.chop_status == "SEVERE_CHOP" or eagle.adx_status == "NON_TRENDING":
        # Exception: Only exceptional institutional expansion thrust (RVOL >= 1.8x and SMC confluence) can break out
        if is_institutional_thrust and rvol >= 1.8 and has_smc_confluence:
            return CommodityTigerMandate(
                mandate="MOMENTUM_EXPANSION",
                allow_routine_breakouts=True,
                allow_thrust_only=True,
                suggested_strategy="BUY_MOMENTUM",
                reason=f"🚀 Exceptional Institutional Thrust (RVOL {rvol:.1f}x) piercing midday lull with verified SMC confluence.",
                action_guidance="Execute with discipline on retest limit order.",
            )
        return CommodityTigerMandate(
            mandate="TIGER_STALKING_PRESERVE_CAPITAL",
            allow_routine_breakouts=False,
            allow_thrust_only=True,
            suggested_strategy="WAIT_IN_CASH",
            reason="🐅 TIGER STALKING: Midday volume lull / sideways chop. Routine breakouts suppressed to prevent whipsaw bleeding.",
            action_guidance="Remain in cash or wait for US Pit Golden Hours (17:30 IST) when real institutional liquidity expands.",
        )

    # 3. US Golden Hours Expansion
    if eagle.is_golden_hours and eagle.chop_status == "TRENDING_EXPANSION":
        return CommodityTigerMandate(
            mandate="MOMENTUM_EXPANSION",
            allow_routine_breakouts=True,
            allow_thrust_only=False,
            suggested_strategy="BUY_MOMENTUM",
            reason="🎯 US Pit Golden Hours expansion confirmed with clean trend alignment and low chop.",
            action_guidance="Pounce decisively on high-conviction breakout or structural pullback retest.",
        )

    # 4. Standard Active Market
    return CommodityTigerMandate(
        mandate="MOMENTUM_EXPANSION" if is_institutional_thrust else "NORMAL_ADAPTIVE",
        allow_routine_breakouts=True,
        allow_thrust_only=False,
        suggested_strategy="BUY_MOMENTUM" if is_institutional_thrust else "SELECTIVE_SNIPER",
        reason="Standard liquid trading session with moderate momentum.",
        action_guidance="Execute on verified OTE pullback retest with strict stop loss.",
    )


# ── Pillar 3: Sniper Entry Planner ───────────────────────────────────────────


def compute_commodity_sniper_plan(
    symbol: str,
    direction: str,
    spot: float,
    trigger_level: float,
    invalidation_level: float,
    opt_recommendation: Optional[dict[str, Any]] = None,
    lot_size: int = 1,
    setup_name: str = "COMMODITY_MOMENTUM",
    retest_anchor: Optional[float] = None,
) -> CommoditySniperPlan:
    """
    Computes institutional sniper execution plan for MCX Commodities:
      - Optimal Trade Entry (OTE) pullback zone (50%–61.8% retracement into broken structure / VWAP)
      - Strict No-Chase boundary (+0.15R)
      - Defined Option Blueprint with coupled SL and Delta
      - 25-minute Time-Stop Invariant
      - Rule 12 compliant targets (T1 +3.0R scale 50% & SL to breakeven, T2 +5.0R, T3 Runner +7.5R).
    """
    clean_sym = symbol.upper().replace("MCX:", "").strip()
    is_bull = direction.upper() in ("BULLISH", "LONG", "BUY")

    step = COMMODITY_STEP_TOLERANCES.get(clean_sym, 10.0)

    # 1. Structural Invalidation Distance
    raw_risk = abs(spot - invalidation_level)
    risk_pts = max(step * 0.8, raw_risk)

    # 2. Rule 12 Asymmetry Targets
    if is_bull:
        sl_price = round(invalidation_level, 2)
        t1_price = round(spot + (3.0 * risk_pts), 2)
        t2_price = round(spot + (5.0 * risk_pts), 2)
        t3_price = round(spot + (7.5 * risk_pts), 2)
        no_chase = round(spot + (0.15 * risk_pts), 2)

        anchor = retest_anchor if (retest_anchor and retest_anchor > 0) else trigger_level
        # OTE Bracket: Limit pullback into broken level or 50% impulse retracement
        entry_min = round(max(sl_price + 0.5, anchor - (0.05 * risk_pts)), 1)
        entry_max = round(min(no_chase - 0.1, anchor + (0.20 * risk_pts)), 1)
        if entry_max <= entry_min:
            entry_min = round(max(sl_price + 0.5, anchor - (0.05 * risk_pts)), 1)
            entry_max = round(max(entry_min + 0.5, anchor + (0.15 * risk_pts)), 1)

        is_chase = bool(spot > (anchor + 0.30 * risk_pts))
        entry_instr = (
            f"🎯 Sniper Limit Buy on Pullback into ₹{entry_min:,.1f} – ₹{entry_max:,.1f}. "
            f"Structural SL: ₹{sl_price:,.1f}. DO NOT CHASE above ₹{no_chase:,.1f}."
        )
    else:
        sl_price = round(invalidation_level, 2)
        t1_price = round(spot - (3.0 * risk_pts), 2)
        t2_price = round(spot - (5.0 * risk_pts), 2)
        t3_price = round(spot - (7.5 * risk_pts), 2)
        no_chase = round(spot - (0.15 * risk_pts), 2)

        anchor = retest_anchor if (retest_anchor and retest_anchor > 0) else trigger_level
        entry_max = round(min(sl_price - 0.5, anchor + (0.05 * risk_pts)), 1)
        entry_min = round(max(no_chase + 0.1, anchor - (0.20 * risk_pts)), 1)
        if entry_min >= entry_max:
            entry_max = round(min(sl_price - 0.5, anchor + (0.05 * risk_pts)), 1)
            entry_min = round(min(entry_max - 0.5, anchor - (0.15 * risk_pts)), 1)

        is_chase = bool(spot < (anchor - 0.30 * risk_pts))
        entry_instr = (
            f"🎯 Sniper Limit Sell/Short on Bounce into ₹{entry_min:,.1f} – ₹{entry_max:,.1f}. "
            f"Structural SL: ₹{sl_price:,.1f}. DO NOT CHASE below ₹{no_chase:,.1f}."
        )

    rr_t1 = round(abs(t1_price - spot) / max(0.01, risk_pts), 1)

    # 3. Option Blueprint Integration
    opt_contract = None
    opt_entry_range = None
    opt_sl = None
    opt_t1 = None
    opt_t2 = None
    opt_max_loss = None

    if opt_recommendation and isinstance(opt_recommendation, dict):
        opt_prem = float(opt_recommendation.get("ltp", 0.0) or 0.0)
        opt_contract = opt_recommendation.get("readable_contract") or opt_recommendation.get("contract")
        if opt_prem > 0:
            opt_risk = round(max(1.0, min(opt_prem * 0.35, risk_pts * 0.52)), 1)
            opt_sl = round(max(0.05, opt_prem - opt_risk), 1)
            opt_t1 = round(opt_prem + (3.0 * opt_risk), 1)
            opt_t2 = round(opt_prem + (5.0 * opt_risk), 1)
            opt_entry_min = round(max(0.5, opt_prem - 0.15 * opt_risk), 1)
            opt_entry_max = round(opt_prem + 0.10 * opt_risk, 1)
            opt_entry_range = f"₹{opt_entry_min:,.1f} – ₹{opt_entry_max:,.1f}"
            opt_max_loss = round(opt_prem * lot_size, 0)

    return CommoditySniperPlan(
        setup_name=setup_name,
        direction="BULLISH" if is_bull else "BEARISH",
        spot=spot,
        trigger_level=trigger_level,
        entry_zone_min=entry_min,
        entry_zone_max=entry_max,
        no_chase_boundary=no_chase,
        structural_invalidation=sl_price,
        risk_points=round(risk_pts, 1),
        target_1=t1_price,
        target_2=t2_price,
        target_3=t3_price,
        risk_reward_t1=rr_t1,
        is_chasing=is_chase,
        entry_instruction=entry_instr,
        time_stop_minutes=25,
        option_contract=opt_contract,
        option_entry_range=opt_entry_range,
        option_stop_loss=opt_sl,
        option_target_1=opt_t1,
        option_target_2=opt_t2,
        option_max_loss_capped=opt_max_loss,
    )


# ── Unified Evaluator: Eagle + Tiger + Sniper ────────────────────────────────


def evaluate_commodity_adaptive_regime(
    symbol: str,
    spot: float,
    df_5m: Optional[pd.DataFrame] = None,
    ref_time: Optional[datetime] = None,
    trigger_level: Optional[float] = None,
    invalidation_level: Optional[float] = None,
    direction: str = "BULLISH",
    is_institutional_thrust: bool = False,
    rvol: float = 1.0,
    has_smc_confluence: bool = False,
    cvd_ratio: float = 1.0,
    trap_detected: bool = False,
    trap_reason: Optional[str] = None,
    opt_recommendation: Optional[dict[str, Any]] = None,
    lot_size: int = 1,
    retest_anchor: Optional[float] = None,
) -> AdaptiveCommodityDecision:
    """
    Unified entry point evaluating Eagle Eye, Tiger Stalking, and Sniper Execution for MCX.
    """
    now_dt = ref_time or datetime.now(IST)
    evaluated_at_str = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")

    # 1. Eagle Eye Radar
    eagle = evaluate_commodity_eagle_regime(
        symbol=symbol,
        spot=spot,
        df_5m=df_5m,
        ref_time=now_dt,
        cvd_ratio=cvd_ratio,
        trap_detected=trap_detected,
        trap_reason=trap_reason,
    )

    # 2. Tiger Stalking Mandate
    tiger = evaluate_commodity_tiger_mandate(
        eagle=eagle,
        is_institutional_thrust=is_institutional_thrust,
        rvol=rvol,
        has_smc_confluence=has_smc_confluence,
    )

    # 3. Sniper Execution Plan (if valid trade direction and levels provided)
    sniper = None
    if trigger_level and invalidation_level:
        sniper = compute_commodity_sniper_plan(
            symbol=symbol,
            direction=direction,
            spot=spot,
            trigger_level=trigger_level,
            invalidation_level=invalidation_level,
            opt_recommendation=opt_recommendation,
            lot_size=lot_size,
            retest_anchor=retest_anchor,
        )

    return AdaptiveCommodityDecision(
        symbol=symbol.upper().replace("MCX:", "").strip(),
        spot=spot,
        eagle=eagle,
        tiger=tiger,
        sniper=sniper,
        evaluated_at=evaluated_at_str,
    )
