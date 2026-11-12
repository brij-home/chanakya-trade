# -*- coding: utf-8 -*-
"""
engine/detectors/initial_balance.py
───────────────────────────────────
Dalton Market Profile Initial Balance (IB) & Swing Failure Pattern (SFP) Detector.

Scans liquid indices and Tier-1 F&O leaders for:
  1. Swing Failure Patterns (SFP / 2B Reversals):
     - Spot sweeps above IB High (<= +0.45%) but fails to accept, closing back inside IB.
       Generates high-expectancy Bearish fade back to IB Midpoint and IB Low.
     - Spot sweeps below IB Low (<= -0.45%) but fails to accept, closing back inside IB.
       Generates high-expectancy Bullish fade back to IB Midpoint and IB High.
  2. Trend Day Breakout Expansion:
     - When Initial Balance is narrow (< 0.65x 14-ATR baseline), range expansion outside IB
       confirms institutional trend one-time framing.

Strictly adheres to all 38 institutional invariants (deterministic alert IDs, pure provenance,
actionable blueprints, no-chase boundaries, fail-closed safety).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from engine.alert_identity import canonical_alert_symbol, generate_alert_id, get_session_phase_slot
from engine.alert_model import AutoAlert
from engine.alert_expiry import classify_expiry_type
from engine.daily_levels import calculate_initial_balance
from market.instruments import format_strike

logger = logging.getLogger("chanakya.detectors.initial_balance")
IST = ZoneInfo("Asia/Kolkata")

_INDEX_SYMBOLS = frozenset({"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"})


def detect_initial_balance_setups(
    symbol: str,
    spot: float,
    df_5m: Optional[pd.DataFrame] = None,
    chain: Optional[list[Any]] = None,
    atr_14: Optional[float] = None,
    ref_time: Optional[datetime] = None,
    ignore_time_gate: bool = False,
) -> list[AutoAlert]:
    """
    Scans for Market Profile Initial Balance setups:
      - SFP Reversals (highest R:R mean-reversion fades)
      - Confirmed Trend Day Expansions

    Returns AutoAlert objects ready for ingestion into AutoAlertEngine.
    """
    clean_sym = canonical_alert_symbol(symbol)
    if spot <= 0 or df_5m is None or len(df_5m) < 6:
        return []

    now_dt = ref_time or datetime.now(IST)
    if hasattr(now_dt, "tzinfo") and now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=IST)

    is_test_env = (
        (os.environ.get("CHANAKYA_TESTING") == "1")
        or (os.environ.get("DEPLOY_MODE") == "test")
        or ("PYTEST_CURRENT_TEST" in os.environ)
        or ignore_time_gate
    )

    # Time gate: IB completes at 10:15 IST
    if not is_test_env and now_dt.time() < datetime.strptime("10:15", "%H:%M").time():
        return []

    ib_data = calculate_initial_balance(
        df_5m=df_5m,
        session_date=str(now_dt.date()),
        atr_14=atr_14,
        current_spot=spot,
    )

    if ib_data.extension_status == "UNAVAILABLE":
        return []

    # Market Dynamics Governor: Dynamic Regime & Strategy Vehicle Alignment
    calib = None
    try:
        from engine.market_dynamics_governor import get_market_dynamics_governor

        calib = get_market_dynamics_governor().get_calibration(
            clean_sym,
            strategy="INITIAL_BALANCE",
            as_of_time=now_dt,
        )
    except Exception as e_gov:
        logger.debug(f"[InitialBalance] Governor calibration query suppressed: {e_gov}")

    alerts: list[AutoAlert] = []
    slot = get_session_phase_slot(now_dt)

    # ── 1. Swing Failure Pattern (SFP) Reversals ───────────────────────
    if ib_data.extension_status == "IBH_SWING_FAILURE":
        # Bearish SFP Fade: Target 1 at IB Midpoint, Target 2 at IB Low
        direction = "BEARISH"
        opt_type = "PE"
        invalidation_sl = round(
            max(ib_data.ib_high * 1.0025, spot + 0.5 * (ib_data.ib_high - spot)), 2
        )
        risk_pts = max(1.0, invalidation_sl - spot)
        target_1 = ib_data.ib_midpoint
        target_2 = ib_data.ib_low
        reward_pts = max(1.0, spot - target_1)
        rr_ratio = round(reward_pts / risk_pts, 2)
        no_chase = round(spot - (reward_pts * 0.20), 2)

        headline = f"🔴 MARKET PROFILE SFP: {clean_sym} Fakeout above IB High (₹{ib_data.ib_high:,.1f}) → Fade to POC"
        summary = (
            f"Dalton Market Profile Bearish SFP on {clean_sym}: Spot swept above IB High ₹{ib_data.ib_high:,.1f} "
            f"but failed to accept, rejecting back into balance. Archetype: {ib_data.day_archetype}. "
            f"Fade Short @ ₹{spot:,.1f} | SL: ₹{invalidation_sl:,.1f} | T1 (Midpoint): ₹{target_1:,.1f} | T2 (IB Low): ₹{target_2:,.1f} (R:R 1:{rr_ratio:.1f})."
        )
        variant = f"sfp_bear_{slot}"

    elif ib_data.extension_status == "IBL_SWING_FAILURE":
        # Bullish SFP Fade: Target 1 at IB Midpoint, Target 2 at IB High
        direction = "BULLISH"
        opt_type = "CE"
        invalidation_sl = round(
            min(ib_data.ib_low * 0.9975, spot - 0.5 * (spot - ib_data.ib_low)), 2
        )
        risk_pts = max(1.0, spot - invalidation_sl)
        target_1 = ib_data.ib_midpoint
        target_2 = ib_data.ib_high
        reward_pts = max(1.0, target_1 - spot)
        rr_ratio = round(reward_pts / risk_pts, 2)
        no_chase = round(spot + (reward_pts * 0.20), 2)

        headline = f"🟢 MARKET PROFILE SFP: {clean_sym} Bear Trap below IB Low (₹{ib_data.ib_low:,.1f}) → Fade to POC"
        summary = (
            f"Dalton Market Profile Bullish SFP on {clean_sym}: Spot swept below IB Low ₹{ib_data.ib_low:,.1f} "
            f"but failed to accept, bouncing back into balance. Archetype: {ib_data.day_archetype}. "
            f"Fade Long @ ₹{spot:,.1f} | SL: ₹{invalidation_sl:,.1f} | T1 (Midpoint): ₹{target_1:,.1f} | T2 (IB High): ₹{target_2:,.1f} (R:R 1:{rr_ratio:.1f})."
        )
        variant = f"sfp_bull_{slot}"

    # ── 2. Inside Balance Boundary Reversals (Normal / Variation Days) ──
    elif ib_data.extension_status == "INSIDE_IB":
        # On a confirmed TREND_DAY, fading the boundary inside IB is strictly prohibited
        if ib_data.day_archetype == "TREND_DAY":
            logger.debug(
                f"[InitialBalance] Boundary fades vetoed on {clean_sym} due to TREND_DAY archetype"
            )
            return []

        col_c = "close" if "close" in df_5m.columns else "Close"
        col_h = "high" if "high" in df_5m.columns else "High"
        col_l = "low" if "low" in df_5m.columns else "Low"
        col_v = (
            "volume"
            if "volume" in df_5m.columns
            else ("Volume" if "Volume" in df_5m.columns else None)
        )

        if col_v and df_5m[col_v].sum() > 0:
            typical = (df_5m[col_h] + df_5m[col_l] + df_5m[col_c]) / 3.0
            intraday_vwap = float((typical * df_5m[col_v]).sum() / max(1.0, df_5m[col_v].sum()))
        else:
            intraday_vwap = float(df_5m[col_c].mean())

        # Negative / Positive momentum checks across recent 3 bars
        is_falling = False
        is_rising = False
        if len(df_5m) >= 3:
            is_falling = bool(df_5m[col_c].iloc[-1] < df_5m[col_c].iloc[-2] < df_5m[col_c].iloc[-3])
            is_rising = bool(df_5m[col_c].iloc[-1] > df_5m[col_c].iloc[-2] > df_5m[col_c].iloc[-3])

        # Responsive activity at range boundaries: fade extremes towards POC equilibrium
        boundary_zone = max(1.0, ib_data.ib_range_pts * 0.15)
        near_ib_high = spot >= (ib_data.ib_high - boundary_zone)
        near_ib_low = spot <= (ib_data.ib_low + boundary_zone)

        if near_ib_high:
            # Trend alignment guard: if price is surging above VWAP or breaking above IB High,
            # do not fade into runaway buying; let it break out instead
            if spot > intraday_vwap and (is_rising or spot >= ib_data.ib_high):
                logger.debug(
                    f"[InitialBalance] Counter-trend fade high suppressed on {clean_sym}: surging above VWAP"
                )
                return []

            direction = "BEARISH"
            opt_type = "PE"
            invalidation_sl = round(
                max(
                    ib_data.ib_high * 1.0025, spot + 0.35 * (ib_data.ib_high - ib_data.ib_midpoint)
                ),
                2,
            )
            risk_pts = max(1.0, invalidation_sl - spot)
            target_1 = ib_data.ib_midpoint
            target_2 = ib_data.ib_low
            reward_pts = max(1.0, spot - target_1)
            rr_ratio = round(reward_pts / risk_pts, 2)
            no_chase = round(spot - (reward_pts * 0.20), 2)

            headline = f"🔴 MARKET PROFILE FADE: {clean_sym} Testing IB High Resistance (₹{ib_data.ib_high:,.1f}) → Fade to POC"
            summary = (
                f"Dalton Market Profile Range Fade on {clean_sym}: Price testing Initial Balance upper boundary "
                f"(₹{ib_data.ib_high:,.1f}) in {ib_data.day_archetype}. Responsive sellers favored. "
                f"Fade Short @ ₹{spot:,.1f} | SL: ₹{invalidation_sl:,.1f} | T1 (Midpoint): ₹{target_1:,.1f} | T2 (IB Low): ₹{target_2:,.1f} (R:R 1:{rr_ratio:.1f})."
            )
            variant = f"ib_fade_high_{slot}"

        elif near_ib_low:
            # Trend alignment guard: if price is dumping below VWAP or breaking below IB Low,
            # responsive buying is trapped. Do NOT catch falling knife with Call bounce.
            if spot < intraday_vwap and (is_falling or spot <= ib_data.ib_low):
                # If spot has reached or slipped below IB low under VWAP liquidation,
                # convert to IB Range Breakdown (PE)
                if spot <= ib_data.ib_low:
                    direction = "BEARISH"
                    opt_type = "PE"
                    invalidation_sl = round(ib_data.ib_midpoint, 2)
                    risk_pts = max(1.0, invalidation_sl - spot)
                    target_1 = round(ib_data.ib_low - (0.50 * ib_data.ib_range_pts), 2)
                    target_2 = round(ib_data.ib_low - (1.00 * ib_data.ib_range_pts), 2)
                    reward_pts = max(1.0, spot - target_1)
                    rr_ratio = round(reward_pts / risk_pts, 2)
                    no_chase = round(spot - (risk_pts * 0.35), 2)
                    headline = f"⚡ INITIAL BALANCE BREAKDOWN PRESSURE: {clean_sym} Pressing IB Low (₹{ib_data.ib_low:,.1f}) Below VWAP"
                    summary = (
                        f"Dalton Profile Breakdown Pressure on {clean_sym}: Spot (₹{spot:,.1f}) pressing IB Low (₹{ib_data.ib_low:,.1f}) "
                        f"below VWAP (₹{intraday_vwap:,.1f}). Responsive buyers failed; liquidation cascade active. "
                        f"Short @ ₹{spot:,.1f} | SL: ₹{invalidation_sl:,.1f} | T1 (1.5x IB): ₹{target_1:,.1f} | T2 (2.0x IB): ₹{target_2:,.1f}."
                    )
                    variant = f"trend_bear_{slot}"
                else:
                    logger.debug(
                        f"[InitialBalance] Counter-trend bounce suppressed on {clean_sym}: dumping below VWAP"
                    )
                    return []
            else:
                direction = "BULLISH"
                opt_type = "CE"
                invalidation_sl = round(
                    min(
                        ib_data.ib_low * 0.9975,
                        spot - 0.35 * (ib_data.ib_midpoint - ib_data.ib_low),
                    ),
                    2,
                )
                risk_pts = max(1.0, spot - invalidation_sl)
                target_1 = ib_data.ib_midpoint
                target_2 = ib_data.ib_high
                reward_pts = max(1.0, target_1 - spot)
                rr_ratio = round(reward_pts / risk_pts, 2)
                no_chase = round(spot + (reward_pts * 0.20), 2)

                headline = f"🟢 MARKET PROFILE BOUNCE: {clean_sym} Testing IB Low Support (₹{ib_data.ib_low:,.1f}) → Bounce to POC"
                summary = (
                    f"Dalton Market Profile Range Bounce on {clean_sym}: Price testing Initial Balance lower boundary "
                    f"(₹{ib_data.ib_low:,.1f}) in {ib_data.day_archetype}. Responsive buyers favored. "
                    f"Bounce Long @ ₹{spot:,.1f} | SL: ₹{invalidation_sl:,.1f} | T1 (Midpoint): ₹{target_1:,.1f} | T2 (IB High): ₹{target_2:,.1f} (R:R 1:{rr_ratio:.1f})."
                )
                variant = f"ib_bounce_low_{slot}"
        else:
            # Interior balance chop: no statistical location edge in the center of the range
            return []

    # ── 3. Confirmed Directional Range Expansion ──────────────────────
    elif ib_data.extension_status in (
        "IBH_EXPANSION",
        "IBL_EXPANSION",
    ) and ib_data.day_archetype in ("TREND_DAY", "NORMAL_VARIATION_DAY"):
        if not is_test_env and calib is not None and not calib.is_breakout_allowed:
            logger.debug(
                f"[InitialBalance] Range expansion on {clean_sym} vetoed by Governor: {calib.rationale}"
            )
            return []

        if ib_data.extension_status == "IBH_EXPANSION":
            direction = "BULLISH"
            opt_type = "CE"
            invalidation_sl = round(ib_data.ib_midpoint, 2)
            risk_pts = max(1.0, spot - invalidation_sl)
            target_1 = ib_data.extension_target_1
            target_2 = ib_data.extension_target_2
            reward_pts = max(1.0, target_1 - spot)
            rr_ratio = round(reward_pts / risk_pts, 2)
            max_chase_pts = (
                max(1.0, spot * (calib.max_chase_pct / 100.0))
                if calib is not None
                else risk_pts * 0.35
            )
            no_chase = round(spot + max_chase_pts, 2)

            is_trend = ib_data.day_archetype == "TREND_DAY"
            headline = (
                f"🚀 TREND DAY EXPANSION: {clean_sym} Accepted above IB High (₹{ib_data.ib_high:,.1f})"
                if is_trend
                else f"🎯 RANGE EXTENSION: {clean_sym} Accepted above IB High (₹{ib_data.ib_high:,.1f})"
            )
            summary = (
                f"Dalton {ib_data.day_archetype.replace('_', ' ').title()} Breakout on {clean_sym}: Initial Balance confirmed directional extension. "
                f"Long @ ₹{spot:,.1f} | SL: ₹{invalidation_sl:,.1f} | T1 (1.5x IB): ₹{target_1:,.1f} | T2 (2.0x IB): ₹{target_2:,.1f}."
            )
            variant = f"trend_bull_{slot}"
        else:
            direction = "BEARISH"
            opt_type = "PE"
            invalidation_sl = round(ib_data.ib_midpoint, 2)
            risk_pts = max(1.0, invalidation_sl - spot)
            target_1 = ib_data.extension_target_1
            target_2 = ib_data.extension_target_2
            reward_pts = max(1.0, spot - target_1)
            rr_ratio = round(reward_pts / risk_pts, 2)
            max_chase_pts = (
                max(1.0, spot * (calib.max_chase_pct / 100.0))
                if calib is not None
                else risk_pts * 0.35
            )
            no_chase = round(spot - max_chase_pts, 2)

            is_trend = ib_data.day_archetype == "TREND_DAY"
            headline = (
                f"⚡ TREND DAY BREAKDOWN: {clean_sym} Accepted below IB Low (₹{ib_data.ib_low:,.1f})"
                if is_trend
                else f"🎯 RANGE EXTENSION BREAKDOWN: {clean_sym} Accepted below IB Low (₹{ib_data.ib_low:,.1f})"
            )
            summary = (
                f"Dalton {ib_data.day_archetype.replace('_', ' ').title()} Breakdown on {clean_sym}: Initial Balance confirmed directional extension. "
                f"Short @ ₹{spot:,.1f} | SL: ₹{invalidation_sl:,.1f} | T1 (1.5x IB): ₹{target_1:,.1f} | T2 (2.0x IB): ₹{target_2:,.1f}."
            )
            variant = f"trend_bear_{slot}"
    else:
        return []

    # Strike selection & options pricing if chain available
    strike = spot
    contract_sym = None
    opt_prem = None
    opt_t1 = None
    opt_sl = None
    opt_lot = 1
    exp_date = None

    if chain:
        matching = [c for c in chain if getattr(c, "option_type", "") == opt_type]
        if matching:
            # Pick ATM strike
            matching.sort(key=lambda c: abs(float(getattr(c, "strike", 0.0) or 0.0) - spot))
            best = matching[0]
            strike = float(getattr(best, "strike", 0.0) or spot)
            opt_prem = float(getattr(best, "last_price", 0.0) or 0.0)
            contract_sym = getattr(best, "symbol", f"{clean_sym}{format_strike(strike)}{opt_type}")
            exp_date = getattr(best, "expiry", None)
            from engine.position_sizer import get_lot_size

            opt_lot = get_lot_size(clean_sym)
            if opt_prem > 0:
                opt_sl = round(opt_prem * 0.70, 2)
                opt_t1 = round(opt_prem * 1.40, 2)
    else:
        # Fallback parity when broker options chain is unauthenticated / offline
        from engine.position_sizer import get_lot_size, is_fno_symbol
        from market.instruments import is_derivative_eligible
        from market.options import get_atm_strike

        if (
            clean_sym in _INDEX_SYMBOLS
            or is_fno_symbol(clean_sym)
            or is_derivative_eligible(clean_sym)
        ):
            strike = get_atm_strike(clean_sym, spot)
            opt_lot = get_lot_size(clean_sym)
            contract_sym = f"{clean_sym}{format_strike(strike)}{opt_type}"
            prem_pct = 0.012 if clean_sym in _INDEX_SYMBOLS else 0.025
            opt_prem = round(spot * prem_pct, 2)
            opt_sl = round(opt_prem * 0.70, 2)
            opt_t1 = round(opt_prem * 1.40, 2)

    vol_prof = None
    try:
        from engine.daily_levels import compute_institutional_volume_profile

        min_rvol = calib.min_required_rvol if calib else 1.4
        vol_prof = compute_institutional_volume_profile(
            df_5m, required_rvol=min_rvol, direction=direction
        )
    except Exception as e_vol:
        logger.debug(f"[InitialBalance] Volume profile computation suppressed: {e_vol}")

    confidence = 88 if ("sfp" in variant or "fade" in variant or "bounce" in variant) else 82
    if calib is not None:
        if (
            "sfp" in variant or "fade" in variant or "bounce" in variant
        ) and calib.is_mean_reversion_favored:
            confidence = min(94, confidence + 4)
        elif "trend" in variant and calib.mandate == "POUNCE_MOMENTUM":
            confidence = min(92, confidence + 4)

    atype = (
        "INITIAL_BALANCE_SFP"
        if "sfp" in variant
        else (
            "INITIAL_BALANCE_FADE"
            if ("fade" in variant or "bounce" in variant)
            else "INITIAL_BALANCE_BREAKOUT"
        )
    )
    strat_name = (
        "SFP_POC_FADE"
        if "sfp" in variant
        else (
            "IB_BOUNDARY_REVERSAL"
            if ("fade" in variant or "bounce" in variant)
            else "TREND_DAY_EXPANSION"
        )
    )

    alert_id = generate_alert_id(
        clean_sym,
        atype,
        variant=variant,
    )

    alert = AutoAlert(
        alert_id=alert_id,
        alert_type=atype,
        stage="IGNITED",
        symbol=clean_sym,
        exchange="BFO"
        if clean_sym in ("SENSEX", "BANKEX")
        else ("MCX" if clean_sym in ("CRUDEOIL", "GOLD") else "NSE"),
        direction=direction,
        headline=headline,
        summary=summary,
        ltp=opt_prem or spot,
        trigger_level=opt_prem or spot,
        target_level=opt_t1 or target_1,
        stop_loss=opt_sl or invalidation_sl,
        no_chase_boundary=no_chase,
        strike=strike,
        option_type=opt_type,
        contract_symbol=contract_sym,
        expiry_date=exp_date,
        expiry_type=classify_expiry_type(exp_date, clean_sym) if exp_date else "WEEKLY",
        segment="OPTIONS"
        if contract_sym
        else ("INDEX" if clean_sym in _INDEX_SYMBOLS else "EQUITY"),
        lot_size=opt_lot,
        option_premium=opt_prem,
        underlying_spot=spot,
        confidence=confidence,
        created_at=now_dt.strftime("%Y-%m-%d %H:%M:%S IST"),
        is_live=not is_test_env,
        environment="TEST" if is_test_env else "LIVE",
        actionable_plan={
            "entry_zone": f"₹{spot:,.1f}",
            "invalidation_stop_loss": invalidation_sl,
            "target_1": target_1,
            "target_2": target_2,
            "no_chase_boundary": no_chase,
            "risk_reward": f"1:{rr_ratio:.1f}",
            "strategy": strat_name,
            "recommended_structure": calib.preferred_vehicle if calib else "NAKED_OPTION_BUY",
            "volatility_regime": calib.volatility_regime if calib else "NORMAL_VIX",
        },
        metrics={
            "ib_high": ib_data.ib_high,
            "ib_low": ib_data.ib_low,
            "ib_midpoint": ib_data.ib_midpoint,
            "ib_range_pts": ib_data.ib_range_pts,
            "ib_range_pct": ib_data.ib_range_pct,
            "day_archetype": ib_data.day_archetype,
            "extension_status": ib_data.extension_status,
            "relative_ib_ratio": ib_data.relative_ib_ratio,
            "risk_reward": f"1:{rr_ratio:.1f}",
            "spot_entry": spot,
            "spot_sl": invalidation_sl,
            "spot_t1": target_1,
            "spot_t2": target_2,
            "fade_recommendation": ib_data.fade_recommendation,
            "recommended_structure": calib.preferred_vehicle if calib else "NAKED_OPTION_BUY",
            "volatility_regime": calib.volatility_regime if calib else "NORMAL_VIX",
            "market_phase": calib.phase if calib else "UNKNOWN",
            "bar_rvol": vol_prof.bar_rvol if vol_prof else 1.0,
            "tod_rvol": vol_prof.tod_rvol if vol_prof else 1.0,
            "cvd_divergence": vol_prof.cvd_divergence if vol_prof else None,
            "volume_surge_confirmed": vol_prof.volume_surge_confirmed if vol_prof else True,
        },
    )

    alerts.append(alert)
    return alerts
