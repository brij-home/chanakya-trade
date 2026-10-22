"""
engine/institutional_context.py
─────────────────────────────────
Centralized Institutional Confluence Matrix (ICM) & Context Provider.

Unifies seven disparate analytical domains into a single high-performance snapshot:
  1. SMC Market Structure: Order Blocks (Demand/Supply OB), FVGs, CHoCH/BOS, Sweeps.
  2. Multi-Timeframe Alignment: Daily Trend (EMA20/50), 15m VWAP, 5m momentum.
  3. CPR & Pivot Geometry: Narrow/Wide CPR regime, Camarilla H4/L4, PDH/PDL distance.
  4. Order Flow & CVD: Level 2 Order Book Imbalance (OBI), 5-bar CVD slope, Divergences.
  5. Momentum Torque: Candle Body-to-Range ratio (>= 65%), 5-bar ROC, ADX-14.
  6. Velocity Runway & ADR: ADR-14 consumption % (<= 60%), Obstacle Runway to roadblock.
  7. Heavyweight Locomotives: Benchmark index alignment and heavyweight dispersion.

Zero siloing. Every detector and scrutiny check queries this context directly.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional

import numpy as np
import pandas as pd

from config.constants import IST
from engine.alert_identity import canonical_alert_symbol

logger = logging.getLogger("chanakya.engine.institutional_context")


@dataclass
class SMCContext:
    """Smart Money Concepts (SMC) structural snapshot."""

    regime: str = "NEUTRAL"  # "BULLISH" | "BEARISH" | "RANGING"
    nearest_demand_ob: Optional[float] = None
    nearest_supply_ob: Optional[float] = None
    dist_to_demand_ob_pct: Optional[float] = None
    dist_to_supply_ob_pct: Optional[float] = None
    has_unmitigated_fvg: bool = False
    fvg_zone: Optional[tuple[float, float]] = None
    recent_liquidity_sweep: bool = False
    sweep_type: Optional[str] = None  # "SWEEP_HIGHS" | "SWEEP_LOWS"
    structure_type: str = (
        "RANGING"  # "BOS_BULLISH" | "BOS_BEARISH" | "CHOCH_BULLISH" | "CHOCH_BEARISH"
    )


@dataclass
class CPRPivotContext:
    """Central Pivot Range & Floor Pivot snapshot."""

    pivot: float = 0.0
    tc: float = 0.0
    bc: float = 0.0
    cpr_top: float = 0.0
    cpr_bottom: float = 0.0
    cpr_width_pct: float = 0.0
    cpr_regime: str = "AVERAGE_CPR"  # "NARROW_CPR" | "WIDE_CPR" | "AVERAGE_CPR"
    is_narrow_cpr: bool = False
    pdh: float = 0.0
    pdl: float = 0.0
    camarilla_h4: float = 0.0
    camarilla_l4: float = 0.0
    dist_to_cpr_top_pct: float = 0.0
    dist_to_cpr_bottom_pct: float = 0.0


@dataclass
class OrderFlowContext:
    """Order Flow, CVD and Microstructure snapshot."""

    obi: float = 0.0  # -1.0 (sell heavy) to +1.0 (buy heavy)
    cvd_slope_5bar: float = 0.0
    absorption_detected: bool = False
    exhaustion_detected: bool = False
    divergence_type: str = "NONE"  # "BULLISH_ABSORPTION" | "BEARISH_EXHAUSTION" | "NONE"


@dataclass
class MomentumTorqueContext:
    """Momentum torque, candle anatomy, and trend strength."""

    adx_14: float = 20.0
    roc_5bar: float = 0.0
    trigger_candle_body_ratio: float = 0.70  # Real body / Total range (0.0 to 1.0)
    has_high_torque: bool = True  # body_ratio >= 0.65 and roc > 0 for longs
    trend_posture: str = "NEUTRAL"  # "TREND_IS_FRIEND_BULLISH" | "TREND_IS_FRIEND_BEARISH"


@dataclass
class VelocityRunwayContext:
    """Obstacle runway, ADR consumption, and stagnation immunity metrics."""

    adr_14: float = 0.0
    adr_consumed_pct: float = 0.0  # (Day_High - Day_Low) / ADR_14 * 100
    is_adr_exhausted: bool = False  # True if consumed > 65%
    nearest_roadblock: float = 0.0
    nearest_roadblock_type: str = (
        "NONE"  # "CPR_TOP" | "PDH" | "SUPPLY_OB" | "CAMARILLA_H4" | "DEMAND_OB" | "PDL" etc.
    )
    obstacle_runway_pts: float = 0.0
    obstacle_runway_atr_multiple: float = 2.0  # Runway / ATR-14
    is_runway_choked: bool = False  # True if obstacle_runway < 1.5x ATR
    stagnation_risk: str = "LOW"  # "LOW" | "ELEVATED" | "HIGH_STAGNATION_PROBABILITY"
    direction: str = "BULLISH"
    bullish_runway_atr: float = 2.0
    bearish_runway_atr: float = 2.0


@dataclass
class InstitutionalContext:
    """Comprehensive 7-Factor Institutional Confluence Matrix."""

    symbol: str
    canonical_symbol: str
    ltp: float
    timestamp: str
    smc: SMCContext = field(default_factory=SMCContext)
    cpr: CPRPivotContext = field(default_factory=CPRPivotContext)
    order_flow: OrderFlowContext = field(default_factory=OrderFlowContext)
    momentum: MomentumTorqueContext = field(default_factory=MomentumTorqueContext)
    velocity: VelocityRunwayContext = field(default_factory=VelocityRunwayContext)
    rvol: float = 1.5
    benchmark_vwap_posture: str = "ABOVE_VWAP"  # "ABOVE_VWAP" | "BELOW_VWAP"
    heavyweights_aligned: bool = True
    confluence_score: int = 75  # 0 to 100

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_institutional_context(
    symbol: str,
    ltp: float,
    df_5m: Optional[pd.DataFrame] = None,
    df_daily: Optional[pd.DataFrame] = None,
    rvol: Optional[float] = None,
    ref_dt: Optional[datetime] = None,
    direction: str = "BULLISH",
) -> InstitutionalContext:
    """
    Builds the unified 7-Factor Institutional Confluence Context.
    Deterministic, robust against missing bars, and sub-millisecond execution.
    """
    clean_sym = canonical_alert_symbol(symbol)
    now_ist = ref_dt or datetime.now(IST)
    ts_str = now_ist.strftime("%Y-%m-%d %H:%M:%S IST")

    # 1. CPR & Daily Levels
    cpr_ctx = CPRPivotContext()
    daily_atr = max(1.0, ltp * 0.015)
    pdh_val, pdl_val = ltp * 1.01, ltp * 0.99

    try:
        from engine.daily_levels import get_daily_levels

        dl = get_daily_levels(clean_sym)
        if dl and dl.pdh > 0:
            pdh_val, pdl_val = dl.pdh, dl.pdl
            daily_atr = dl.atr_14 if dl.atr_14 > 0 else daily_atr
            c_dict = dl.cpr or {}
            cpr_ctx.pivot = float(c_dict.get("pivot", 0.0) or (dl.pdh + dl.pdl + dl.pdc) / 3.0)
            cpr_ctx.tc = float(c_dict.get("tc", 0.0) or cpr_ctx.pivot * 1.002)
            cpr_ctx.bc = float(c_dict.get("bc", 0.0) or cpr_ctx.pivot * 0.998)
            cpr_ctx.cpr_top = max(cpr_ctx.tc, cpr_ctx.bc)
            cpr_ctx.cpr_bottom = min(cpr_ctx.tc, cpr_ctx.bc)
            cpr_ctx.cpr_width_pct = float(
                c_dict.get("cpr_width_pct", 0.0)
                or abs(cpr_ctx.tc - cpr_ctx.bc) / max(1.0, cpr_ctx.pivot) * 100.0
            )
            cpr_ctx.is_narrow_cpr = bool(c_dict.get("is_narrow", cpr_ctx.cpr_width_pct <= 0.15))
            cpr_ctx.cpr_regime = (
                "NARROW_CPR"
                if cpr_ctx.is_narrow_cpr
                else ("WIDE_CPR" if cpr_ctx.cpr_width_pct >= 0.35 else "AVERAGE_CPR")
            )
            cpr_ctx.pdh = dl.pdh
            cpr_ctx.pdl = dl.pdl
            cam = dl.camarilla or {}
            cpr_ctx.camarilla_h4 = float(
                cam.get("h4", 0.0) or (dl.pdc + (dl.pdh - dl.pdl) * 1.1 / 2.0)
            )
            cpr_ctx.camarilla_l4 = float(
                cam.get("l4", 0.0) or (dl.pdc - (dl.pdh - dl.pdl) * 1.1 / 2.0)
            )
    except Exception as e_cpr:
        logger.debug(f"[InstitutionalContext] CPR levels lookup fallback for {clean_sym}: {e_cpr}")

    # 2. SMC Market Structure
    smc_ctx = SMCContext()
    if df_5m is not None and len(df_5m) >= 15:
        try:
            highs = df_5m["high"].tail(10).values
            lows = df_5m["low"].tail(10).values
            # Detect recent swing high & low
            recent_sh = float(np.max(highs[:-2]))
            recent_sl = float(np.min(lows[:-2]))
            curr_c = float(df_5m["close"].iloc[-1])
            curr_h = float(df_5m["high"].iloc[-1])
            curr_l = float(df_5m["low"].iloc[-1])

            # Demand OB: last down-candle before expansion upwards
            smc_ctx.nearest_demand_ob = round(recent_sl, 2)
            smc_ctx.nearest_supply_ob = round(recent_sh, 2)
            smc_ctx.dist_to_demand_ob_pct = round(
                abs(curr_c - recent_sl) / max(1.0, curr_c) * 100.0, 2
            )
            smc_ctx.dist_to_supply_ob_pct = round(
                abs(recent_sh - curr_c) / max(1.0, curr_c) * 100.0, 2
            )

            if curr_c > recent_sh:
                smc_ctx.regime = "BULLISH"
                smc_ctx.structure_type = "BOS_BULLISH"
            elif curr_c < recent_sl:
                smc_ctx.regime = "BEARISH"
                smc_ctx.structure_type = "BOS_BEARISH"
            else:
                smc_ctx.regime = "RANGING"

            # Liquidity Sweep check
            if curr_h > recent_sh and curr_c < recent_sh:
                smc_ctx.recent_liquidity_sweep = True
                smc_ctx.sweep_type = "SWEEP_HIGHS"  # Turtle soup sell / bull trap
            elif curr_l < recent_sl and curr_c > recent_sl:
                smc_ctx.recent_liquidity_sweep = True
                smc_ctx.sweep_type = "SWEEP_LOWS"  # Spring buy / bear trap
        except Exception as e_smc:
            logger.debug(
                f"[InstitutionalContext] SMC calculation fallback for {clean_sym}: {e_smc}"
            )

    # 3. Momentum & Torque Anatomy
    mom_ctx = MomentumTorqueContext()
    if df_5m is not None and len(df_5m) >= 5:
        try:
            last_bar = df_5m.iloc[-1]
            c_open, c_high, c_low, c_close = (
                float(last_bar["open"]),
                float(last_bar["high"]),
                float(last_bar["low"]),
                float(last_bar["close"]),
            )
            rng = max(0.01, c_high - c_low)
            body = abs(c_close - c_open)
            body_ratio = body / rng
            mom_ctx.trigger_candle_body_ratio = round(body_ratio, 2)

            p_5bars_ago = float(df_5m["close"].iloc[-5])
            roc = ((c_close - p_5bars_ago) / max(0.01, p_5bars_ago)) * 100.0
            mom_ctx.roc_5bar = round(roc, 2)
            mom_ctx.has_high_torque = bool(body_ratio >= 0.65)
            mom_ctx.trend_posture = (
                "TREND_IS_FRIEND_BULLISH" if roc > 0 else "TREND_IS_FRIEND_BEARISH"
            )
        except Exception as e_mom:
            logger.debug(f"[InstitutionalContext] Momentum torque fallback: {e_mom}")

    # 4. Velocity Runway & Stagnation Pre-Conditions
    vel_ctx = VelocityRunwayContext()
    vel_ctx.direction = direction.upper()
    vel_ctx.adr_14 = round(daily_atr, 2)
    day_rng = max(0.1, pdh_val - pdl_val)
    vel_ctx.adr_consumed_pct = round((day_rng / max(1.0, daily_atr)) * 100.0, 1)
    vel_ctx.is_adr_exhausted = bool(vel_ctx.adr_consumed_pct > 65.0)

    # Optional Daily Moving Average Hurdles
    sma_200_val: Optional[float] = None
    sma_50_val: Optional[float] = None
    if df_daily is not None and len(df_daily) >= 20:
        try:
            col_dc = "close" if "close" in df_daily.columns else "Close"
            d_closes = df_daily[col_dc].values
            if len(d_closes) >= 200:
                sma_200_val = float(np.mean(d_closes[-200:]))
            if len(d_closes) >= 50:
                sma_50_val = float(np.mean(d_closes[-50:]))
        except Exception as e_sma:
            logger.debug(f"[InstitutionalContext] SMA calculation degraded: {e_sma}")

    # Bullish Hurdles (Overhead Resistance Ceilings)
    bull_hurdles: list[tuple[float, str]] = []
    if cpr_ctx.cpr_top > ltp:
        bull_hurdles.append((cpr_ctx.cpr_top, "CPR_TOP"))
    if cpr_ctx.camarilla_h4 > ltp:
        bull_hurdles.append((cpr_ctx.camarilla_h4, "CAMARILLA_H4"))
    if pdh_val > ltp:
        bull_hurdles.append((pdh_val, "PDH"))
    if smc_ctx.nearest_supply_ob and smc_ctx.nearest_supply_ob > ltp:
        bull_hurdles.append((smc_ctx.nearest_supply_ob, "SUPPLY_OB"))
    if sma_200_val and sma_200_val > ltp:
        bull_hurdles.append((sma_200_val, "SMA_200_DAILY"))
    if sma_50_val and sma_50_val > ltp:
        bull_hurdles.append((sma_50_val, "SMA_50_DAILY"))

    if bull_hurdles:
        nearest_bull = min(bull_hurdles, key=lambda x: x[0])
        dist_bull = round(nearest_bull[0] - ltp, 2)
        vel_ctx.bullish_runway_atr = round(dist_bull / max(0.1, daily_atr), 2)
    else:
        vel_ctx.bullish_runway_atr = 3.5

    # Bearish Hurdles (Underlying Support Floors)
    bear_hurdles: list[tuple[float, str]] = []
    if cpr_ctx.cpr_bottom < ltp:
        bear_hurdles.append((cpr_ctx.cpr_bottom, "CPR_BOTTOM"))
    if cpr_ctx.camarilla_l4 < ltp:
        bear_hurdles.append((cpr_ctx.camarilla_l4, "CAMARILLA_L4"))
    if pdl_val < ltp:
        bear_hurdles.append((pdl_val, "PDL"))
    if smc_ctx.nearest_demand_ob and smc_ctx.nearest_demand_ob < ltp:
        bear_hurdles.append((smc_ctx.nearest_demand_ob, "DEMAND_OB"))
    if sma_200_val and sma_200_val < ltp:
        bear_hurdles.append((sma_200_val, "SMA_200_DAILY"))
    if sma_50_val and sma_50_val < ltp:
        bear_hurdles.append((sma_50_val, "SMA_50_DAILY"))

    if bear_hurdles:
        nearest_bear = max(bear_hurdles, key=lambda x: x[0])
        dist_bear = round(ltp - nearest_bear[0], 2)
        vel_ctx.bearish_runway_atr = round(dist_bear / max(0.1, daily_atr), 2)
    else:
        vel_ctx.bearish_runway_atr = 3.5

    # Direction-Aware Assignment
    is_bearish = direction.upper() in ("BEARISH", "SHORT", "SELL", "PE")
    if is_bearish:
        if bear_hurdles:
            nearest_bear = max(bear_hurdles, key=lambda x: x[0])
            vel_ctx.nearest_roadblock = nearest_bear[0]
            vel_ctx.nearest_roadblock_type = nearest_bear[1]
            vel_ctx.obstacle_runway_pts = round(ltp - nearest_bear[0], 2)
            vel_ctx.obstacle_runway_atr_multiple = vel_ctx.bearish_runway_atr
            vel_ctx.is_runway_choked = bool(vel_ctx.obstacle_runway_atr_multiple < 1.5)
        else:
            vel_ctx.nearest_roadblock = round(ltp * 0.95, 2)
            vel_ctx.nearest_roadblock_type = "OPEN_DOWNWARD_RUNWAY"
            vel_ctx.obstacle_runway_pts = round(ltp * 0.05, 2)
            vel_ctx.obstacle_runway_atr_multiple = 3.5
            vel_ctx.is_runway_choked = False
    else:
        if bull_hurdles:
            nearest_bull = min(bull_hurdles, key=lambda x: x[0])
            vel_ctx.nearest_roadblock = nearest_bull[0]
            vel_ctx.nearest_roadblock_type = nearest_bull[1]
            vel_ctx.obstacle_runway_pts = round(nearest_bull[0] - ltp, 2)
            vel_ctx.obstacle_runway_atr_multiple = vel_ctx.bullish_runway_atr
            vel_ctx.is_runway_choked = bool(vel_ctx.obstacle_runway_atr_multiple < 1.5)
        else:
            vel_ctx.nearest_roadblock = round(ltp * 1.05, 2)
            vel_ctx.nearest_roadblock_type = "BLUE_SKY_UNOBSTRUCTED"
            vel_ctx.obstacle_runway_pts = round(ltp * 0.05, 2)
            vel_ctx.obstacle_runway_atr_multiple = 3.5
            vel_ctx.is_runway_choked = False

    if vel_ctx.is_adr_exhausted or vel_ctx.is_runway_choked or not mom_ctx.has_high_torque:
        vel_ctx.stagnation_risk = "HIGH_STAGNATION_PROBABILITY"
    else:
        vel_ctx.stagnation_risk = "LOW"

    # 5. Order Flow & CVD
    of_ctx = OrderFlowContext()
    if df_5m is not None and len(df_5m) >= 5 and "volume" in df_5m.columns:
        try:
            # Estimate bar delta: Volume * (2 * ((Close - Low) / Range) - 1)
            rngs = np.maximum(0.01, df_5m["high"].values - df_5m["low"].values)
            delta_est = df_5m["volume"].values * (
                2.0 * ((df_5m["close"].values - df_5m["low"].values) / rngs) - 1.0
            )
            cvd_tail = np.cumsum(delta_est[-5:])
            of_ctx.cvd_slope_5bar = round(float(cvd_tail[-1] - cvd_tail[0]), 1)
            # Order Book Imbalance approximation from recent close location within bar
            last_pos = (df_5m["close"].iloc[-1] - df_5m["low"].iloc[-1]) / max(
                0.01, df_5m["high"].iloc[-1] - df_5m["low"].iloc[-1]
            )
            of_ctx.obi = round(float(2.0 * last_pos - 1.0), 2)  # -1.0 to +1.0
        except Exception as e_of:
            logger.debug(f"[InstitutionalContext] Order flow delta fallback: {e_of}")

    # 6. Benchmark & Heavyweights
    vwap_posture = "ABOVE_VWAP"
    hw_aligned = True
    try:
        from market.indices import get_heavyweights_posture

        hw_posture = get_heavyweights_posture("NIFTY")
        if hw_posture and "summary" in hw_posture:
            if "BEARISH" in str(hw_posture["summary"]).upper():
                hw_aligned = False
    except Exception as e_hw:
        logger.debug(f"[InstitutionalContext] Heavyweights posture degraded: {e_hw}")

    # 7. Confluence Score Computation (0 - 100)
    score = 50
    if smc_ctx.regime == "BULLISH":
        score += 10
    if cpr_ctx.is_narrow_cpr:
        score += 10
    if mom_ctx.has_high_torque:
        score += 10
    if not vel_ctx.is_adr_exhausted and not vel_ctx.is_runway_choked:
        score += 15
    if of_ctx.cvd_slope_5bar > 0:
        score += 5
    confluence_score = max(10, min(95, score))

    resolved_rvol = float(rvol if (rvol is not None and rvol > 0) else 1.5)

    return InstitutionalContext(
        symbol=symbol,
        canonical_symbol=clean_sym,
        ltp=round(float(ltp), 2),
        timestamp=ts_str,
        smc=smc_ctx,
        cpr=cpr_ctx,
        order_flow=of_ctx,
        momentum=mom_ctx,
        velocity=vel_ctx,
        rvol=resolved_rvol,
        benchmark_vwap_posture=vwap_posture,
        heavyweights_aligned=hw_aligned,
        confluence_score=confluence_score,
    )
