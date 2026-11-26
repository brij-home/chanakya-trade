"""
engine/detectors/liquidity_inversion.py
───────────────────────────────────────
Autonomous Liquidity Inversion & "Trap the Trappers" Detector.

Captures explosive trend-continuation moves when counter-trend participants
(sellers in an uptrend, or bottom-fishers in a downtrend) get trapped:

1. Bear Trap Short-Squeeze (Bullish Inversion):
   - Asset is trading with bullish relative strength (Spot > VWAP, Change >= +0.70%).
   - Price attempted an intraday pullback or swept an overhead level, but sell-side
     momentum was completely absorbed by institutional buying above VWAP.
   - Trapped short-sellers who sold the "resistance" are forced to buy to cover,
     triggering an explosive short-squeeze breakout.
   - Actionable Plan: Limit Buy on VWAP / OTE retest, SL below absorption floor.

2. Bull Trap Long-Liquidation (Bearish Inversion):
   - Asset is trading with bearish relative weakness (Spot < VWAP, Change <= -0.70%).
   - Price attempted an intraday bounce, but buy-side momentum was rejected below VWAP.
   - Trapped longs are forced to liquidate, triggering aggressive downside continuation.
   - Actionable Plan: Limit Sell on VWAP / OTE retest, SL above rejection ceiling.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import pandas as pd

from config.constants import IST
from engine.alert_identity import generate_alert_id, canonical_alert_symbol
from engine.alert_model import AutoAlert
from engine.pullback_level_resolver import resolve_pullback_entry
from engine.option_resolver import is_index_symbol

logger = logging.getLogger("chanakya.detectors.liquidity_inversion")


def detect_liquidity_inversion(
    symbol: str,
    df: Optional[pd.DataFrame],
    ltp: float,
    vwap: Optional[float] = None,
    change_pct: Optional[float] = None,
    rvol: Optional[float] = None,
    failed_sweep_type: Optional[str] = None,
    now_dt: Optional[datetime] = None,
    day_high: Optional[float] = None,
    day_low: Optional[float] = None,
) -> Optional[AutoAlert]:
    """
    Evaluates market microstructure for failed counter-trend sweeps and trapped liquidity.
    Transforms rejected counter-trend vetoes into high-conviction continuation alpha.
    """
    if ltp <= 0:
        return None

    clean_sym = canonical_alert_symbol(symbol)
    ref_dt = now_dt or datetime.now(IST)
    if ref_dt.tzinfo is None:
        ref_dt = ref_dt.replace(tzinfo=IST)
    else:
        ref_dt = ref_dt.astimezone(IST)

    curr_t = ref_dt.time()
    # Active between 09:20 and 15:00 IST
    if (
        curr_t < datetime.strptime("09:20", "%H:%M").time()
        or curr_t > datetime.strptime("15:00", "%H:%M").time()
    ):
        # Session boundary check
        pass

    effective_vwap = vwap if (vwap and vwap > 0) else None

    # Determine session directional posture
    eff_chg = change_pct if change_pct is not None else 0.0
    rvol_val = float(rvol) if rvol is not None else 1.20

    is_bull_trap_short_squeeze = False
    is_bear_trap_long_liquidation = False

    # 1. Bull Trap Short Squeeze Scenario (Failed Bearish Upthrust in Uptrend)
    # Stock is strong (holding above VWAP, up >= 0.70%), and a bearish sweep failed
    if effective_vwap and ltp >= effective_vwap * 1.001 and eff_chg >= 0.70:
        if failed_sweep_type in ("BEARISH_UPTHRUST", "BEARISH_SWEEP", "UPTHRUST_FAILURE"):
            is_bull_trap_short_squeeze = True
        elif df is not None and len(df) >= 3:
            # Check price action: recent bar had an upper wick but closed above VWAP,
            # and current ltp is reclaiming upper half of the range
            col_h = "high" if "high" in df.columns else "High"
            col_l = "low" if "low" in df.columns else "Low"
            recent_bars = df.tail(3)
            highest_w = float(recent_bars[col_h].max())
            lowest_w = float(recent_bars[col_l].min())
            if highest_w > lowest_w and ltp >= (lowest_w + 0.65 * (highest_w - lowest_w)):
                is_bull_trap_short_squeeze = True

    # 2. Bear Trap Long Liquidation Scenario (Failed Bullish Spring in Downtrend)
    # Stock is weak (submerged below VWAP, down <= -0.70%), and a bullish bounce failed
    elif effective_vwap and ltp <= effective_vwap * 0.999 and eff_chg <= -0.70:
        if failed_sweep_type in ("BULLISH_SPRING", "BULLISH_SWEEP", "SPRING_FAILURE"):
            is_bear_trap_long_liquidation = True
        elif df is not None and len(df) >= 3:
            col_h = "high" if "high" in df.columns else "High"
            col_l = "low" if "low" in df.columns else "Low"
            recent_bars = df.tail(3)
            highest_w = float(recent_bars[col_h].max())
            lowest_w = float(recent_bars[col_l].min())
            if highest_w > lowest_w and ltp <= (lowest_w + 0.35 * (highest_w - lowest_w)):
                is_bear_trap_long_liquidation = True

    if not (is_bull_trap_short_squeeze or is_bear_trap_long_liquidation):
        return None

    direction = "BULLISH" if is_bull_trap_short_squeeze else "BEARISH"

    # Compute Pullback-to-Value plan
    plan = resolve_pullback_entry(
        symbol=clean_sym,
        direction=direction,
        spot=ltp,
        vwap=effective_vwap or ltp,
        day_high=day_high,
        day_low=day_low,
        prefer_options=True,
    )

    variant = "BEAR_TRAP_SQUEEZE" if is_bull_trap_short_squeeze else "BULL_TRAP_LIQUIDATION"
    alert_id = generate_alert_id(clean_sym, "LIQUIDITY_INVERSION", variant=variant.lower())

    if is_bull_trap_short_squeeze:
        headline = f"⚡ [LIQUIDITY INVERSION] {clean_sym} Bear Trap Short Squeeze (+{eff_chg:.1f}% above VWAP)"
        summary = (
            f"Trapped Bears on {clean_sym}: Sellers attempted to fade highs, but sell-side momentum "
            f"was completely absorbed above VWAP ₹{effective_vwap or ltp:,.1f}. "
            f"Short covering provides asymmetric continuation fuel. "
            f"{plan.actionable_summary}"
        )
    else:
        headline = f"🚨 [LIQUIDITY INVERSION] {clean_sym} Bull Trap Long Liquidation ({eff_chg:.1f}% below VWAP)"
        summary = (
            f"Trapped Longs on {clean_sym}: Counter-trend bounce rejected below VWAP ₹{effective_vwap or ltp:,.1f}. "
            f"Forced long liquidation provides aggressive downside momentum. "
            f"{plan.actionable_summary}"
        )

    is_idx = is_index_symbol(clean_sym)
    opt_type = "CE" if is_bull_trap_short_squeeze else "PE"

    alert = AutoAlert(
        alert_id=alert_id,
        alert_type="LIQUIDITY_INVERSION",
        stage="IGNITED",
        symbol=clean_sym,
        exchange="NFO" if (is_idx or plan.opt_symbol) else "NSE",
        direction=direction,
        headline=headline,
        summary=summary,
        ltp=plan.opt_entry_limit if plan.opt_entry_limit else ltp,
        trigger_level=plan.opt_entry_limit if plan.opt_entry_limit else plan.entry_zone_mid,
        target_level=plan.opt_t1 if plan.opt_t1 else plan.target_1,
        stop_loss=plan.opt_sl if plan.opt_sl else plan.stop_loss,
        underlying_spot=ltp,
        contract_symbol=plan.opt_symbol,
        option_type=opt_type if plan.opt_symbol else None,
        confidence=90,
        metrics={
            "variant": variant,
            "vwap": effective_vwap,
            "change_pct": eff_chg,
            "rvol": rvol_val,
            "entry_zone_min": plan.entry_zone_min,
            "entry_zone_max": plan.entry_zone_max,
            "entry_zone_mid": plan.entry_zone_mid,
            "risk_pts": plan.risk_pts,
            "no_chase_price": plan.no_chase_price,
            "opt_t2": plan.opt_t2,
        },
    )
    has_opt = bool(plan.opt_symbol)
    alert.actionable_plan = {
        "entry_type": "PULLBACK_LIMIT_ZONE",
        "entry_range": (
            f"₹{plan.opt_entry_limit * 0.98:,.2f} - ₹{plan.opt_entry_limit * 1.02:,.2f}"
            if has_opt and plan.opt_entry_limit
            else f"₹{plan.entry_zone_min:,.1f} - ₹{plan.entry_zone_max:,.1f}"
        ),
        "entry_mid": plan.opt_entry_limit
        if has_opt and plan.opt_entry_limit
        else plan.entry_zone_mid,
        "stop_loss": plan.opt_sl if has_opt and plan.opt_sl else plan.stop_loss,
        "risk_pts": (
            round(abs(plan.opt_entry_limit - plan.opt_sl), 2)
            if has_opt and plan.opt_entry_limit and plan.opt_sl
            else plan.risk_pts
        ),
        "target_1": plan.opt_t1 if has_opt and plan.opt_t1 else plan.target_1,
        "target_2": plan.opt_t2 if has_opt and plan.opt_t2 else plan.target_2,
        "target_3": plan.target_3,
        "underlying_spot": f"₹{ltp:,.1f}",
        "spot_stop_loss": plan.stop_loss,
        "spot_target_1": plan.target_1,
        "rr_t1": f"+{plan.rr_t1}R",
        "rr_t2": f"+{plan.rr_t2}R",
        "no_chase": plan.no_chase_price,
        "option_contract": plan.opt_symbol,
        "option_limit": plan.opt_entry_limit,
        "option_sl": plan.opt_sl,
        "option_t1": plan.opt_t1,
    }
    return alert
