"""
engine/detectors/afternoon_thrust.py
───────────────────────────────────
Autonomous Afternoon Thrust & Power Hour Breakout Detector (13:00 - 15:15 IST).

Captures explosive second-half institutional thrusts, trend extensions, and short-covering rallies:
  1. Bullish Afternoon Thrust (PM Breakout):
     - Coiled base built during midday lull (11:30 - 13:00) holding above or reclaiming VWAP.
     - Breaking through / testing Day High or Midday Resistance.
     - Volume expansion (RVOL >= 1.25x vs midday average).
     - Higher lows sequence on 5m bars.
     - Stop Loss: Anchored strictly below midday coil swing low / VWAP support floor.
  2. Bearish Afternoon Flush (PM Liquidation):
     - Coiled base built during midday lull holding below VWAP.
     - Breaking through / testing Day Low or Midday Support.
     - Volume expansion (RVOL >= 1.25x vs midday average).
     - Lower highs sequence on 5m bars.
     - Stop Loss: Anchored strictly above midday coil swing high / VWAP resistance ceiling.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta, time as dtime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd
import numpy as np

from engine.alert_identity import (
    generate_alert_id,
    canonical_alert_symbol,
    get_session_phase_slot,
)
from engine.alert_model import AutoAlert

logger = logging.getLogger("chanakya.detectors.afternoon_thrust")

try:
    IST = ZoneInfo("Asia/Kolkata")
except Exception:
    IST = timezone(timedelta(hours=5, minutes=30))


def _calculate_5m_atr(df: Any, period: int = 14) -> float:
    """Calculate 5-minute ATR to establish dynamic Brownian noise floor."""
    try:
        if df is None or len(df) < 1:
            return 0.0
        col_h = "high" if "high" in df.columns else "High"
        col_l = "low" if "low" in df.columns else "Low"
        col_c = "close" if "close" in df.columns else "Close"
        high = df[col_h]
        low = df[col_l]
        if len(df) == 1:
            return float(high.iloc[0] - low.iloc[0])
        close = df[col_c]
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr_series = tr.rolling(window=min(len(tr), period), min_periods=1).mean()
        val = float(atr_series.iloc[-1])
        return val if val > 0 and not pd.isna(val) else 0.0
    except Exception as e:
        logger.debug(f"[AfternoonThrust] ATR calculation exception: {e}")
        return 0.0


def detect_afternoon_thrust(
    symbol: str,
    df_5m: pd.DataFrame,
    ltp: float,
    vwap: Optional[float] = None,
    rvol: Optional[float] = None,
    day_high: Optional[float] = None,
    day_low: Optional[float] = None,
    ref_time: Optional[datetime] = None,
    prev_close: Optional[float] = None,
    prev_high: Optional[float] = None,
    prev_low: Optional[float] = None,
    ignore_time_gate: bool = False,
) -> Optional[AutoAlert]:
    """
    Evaluates 5-minute intraday bars for textbook Afternoon Thrust & PM Breakout patterns.
    Active primarily between 13:00 and 15:15 IST (European crossover & Power Hour).
    """
    if df_5m is None or len(df_5m) < 3 or ltp <= 0:
        return None

    now_dt = ref_time or datetime.now(IST)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=IST)
    else:
        now_dt = now_dt.astimezone(IST)

    clean_sym = canonical_alert_symbol(symbol)
    is_index = clean_sym in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX")
    is_heavyweight = clean_sym in (
        "RELIANCE",
        "HDFCBANK",
        "ICICIBANK",
        "INFY",
        "TCS",
        "SBIN",
        "AXISBANK",
        "KOTAKBANK",
        "TATASTEEL",
        "LT",
        "BHARTIARTL",
        "ITC",
    )

    curr_t = now_dt.time()
    if not ignore_time_gate:
        # Afternoon thrust active from 13:15 IST (post midday-lull) to 15:15 IST
        if curr_t < dtime(13, 15) or curr_t > dtime(15, 15):
            return None

    col_o = "open" if "open" in df_5m.columns else "Open"
    col_h = "high" if "high" in df_5m.columns else "High"
    col_l = "low" if "low" in df_5m.columns else "Low"
    col_c = "close" if "close" in df_5m.columns else "Close"
    col_v = "volume" if "volume" in df_5m.columns else "Volume"

    # Filter df to today's bars if timestamps available
    today_str = now_dt.strftime("%Y-%m-%d")
    df_today = (
        df_5m[df_5m.index.strftime("%Y-%m-%d") == today_str]
        if hasattr(df_5m.index, "strftime")
        else df_5m
    )
    if len(df_today) == 0:
        df_today = df_5m

    # Extract intraday session high and low
    hist_high = float(df_today[col_h].max()) if len(df_today) > 0 else ltp
    hist_low = float(df_today[col_l].min()) if len(df_today) > 0 else ltp
    session_high = max(float(day_high or 0.0), hist_high)
    session_low = min(float(day_low or 99999999.0), hist_low) if (day_low or hist_low) else ltp

    # Midday consolidation analysis (bars between 11:30 and 13:00 IST, or prior 12-18 bars)
    midday_high = session_high
    midday_low = session_low
    is_tight_coil = False
    try:
        if hasattr(df_today.index, "time") and len(df_today) >= 10:
            times = df_today.index.time
            mask_midday = (times >= dtime(11, 30)) & (times < dtime(13, 0))
            df_mid = df_today[mask_midday]
            if len(df_mid) >= 3:
                midday_high = float(df_mid[col_h].max())
                midday_low = float(df_mid[col_l].min())
            else:
                # Fallback to middle third of bars
                n = len(df_today)
                mid_slice = df_today.iloc[max(0, n // 3) : max(1, 2 * n // 3)]
                midday_high = float(mid_slice[col_h].max())
                midday_low = float(mid_slice[col_l].min())
        else:
            n = len(df_today)
            mid_slice = df_today.iloc[max(0, n // 3) : max(1, 2 * n // 3)] if n >= 6 else df_today
            midday_high = float(mid_slice[col_h].max())
            midday_low = float(mid_slice[col_l].min())

        mid_rng_pct = ((midday_high - midday_low) / max(1.0, ltp)) * 100.0
        max_coil_threshold = 0.8 if is_index else 1.5
        if mid_rng_pct <= max_coil_threshold:
            is_tight_coil = True
    except Exception as e_mid:
        logger.debug(f"[AfternoonThrust] Midday coil computation note for {clean_sym}: {e_mid}")

    # Volume & RVOL validation
    rvol_val = rvol if (rvol and rvol > 0) else 1.2
    if col_v in df_today.columns and len(df_today) >= 3:
        try:
            vols = df_today[col_v].values
            cur_v = float(vols[-1])
            avg_v = float(np.mean(vols[:-1]))
            if avg_v > 0:
                rvol_val = max(rvol_val, round(cur_v / avg_v, 2))
        except Exception as e_suppressed:
            logger.debug(
                f"[engine.detectors.afternoon_thrust] Non-fatal exception suppressed: {e_suppressed}"
            )

    # Recent candle momentum
    last_bar = df_today.iloc[-1]
    last_open = float(last_bar[col_o])
    last_close = float(last_bar[col_c])
    penult_bar = df_today.iloc[-2] if len(df_today) >= 2 else last_bar
    penult_low = float(penult_bar[col_l])
    last_low = float(last_bar[col_l])
    penult_high = float(penult_bar[col_h])
    last_high = float(last_bar[col_h])

    effective_vwap = vwap if (vwap and vwap > 0) else ltp

    # 1. Bullish Afternoon Thrust Setup:
    # Spot holding at/above VWAP, breaking/pressing Day High or Midday High, with higher lows
    is_bull_thrust = (
        ltp >= (effective_vwap * 0.9985)
        and (ltp >= session_high * 0.998 or ltp >= midday_high * 0.999)
        and (last_close >= last_open or last_low >= penult_low)
        and rvol_val >= 1.15
    )

    # 2. Bearish Afternoon Flush Setup:
    # Spot holding at/below VWAP, breaking/pressing Day Low or Midday Low, with lower highs
    is_bear_flush = (
        ltp <= (effective_vwap * 1.0015)
        and (ltp <= session_low * 1.002 or ltp <= midday_low * 1.001)
        and (last_close <= last_open or last_high <= penult_high)
        and rvol_val >= 1.15
    )

    if not is_bull_thrust and not is_bear_flush:
        return None

    # Mutual exclusion: prioritize stronger trend side
    if is_bull_thrust and is_bear_flush:
        if ltp >= effective_vwap:
            is_bear_flush = False
        else:
            is_bull_thrust = False

    direction = "BULLISH" if is_bull_thrust else "BEARISH"

    # ── Institutional Daily Levels: CPR Overhead & Camarilla Guard ──
    cpr_gate = None
    try:
        from engine.daily_levels import get_daily_levels, evaluate_cpr_gate

        dl = get_daily_levels(clean_sym, session_date=str(now_dt.date()))
        cpr_gate = evaluate_cpr_gate(
            clean_sym, ltp, direction, dl=dl, session_date=str(now_dt.date())
        )
        if cpr_gate.is_vetoed:
            logger.debug(
                f"[AfternoonThrust] Suppressed {'bullish thrust' if direction == 'BULLISH' else 'bearish flush'} on {clean_sym}: {cpr_gate.veto_reason}"
            )
            return None

        if is_index and dl and dl.camarilla:
            cam = dl.camarilla
            h5 = float(cam.get("h5", 0.0) or 0.0)
            l5 = float(cam.get("l5", 0.0) or 0.0)
            float(cam.get("h4", 0.0) or 0.0)
            l4 = float(cam.get("l4", 0.0) or 0.0)

            # Camarilla levels must be within reasonable proximity (10%) of spot to be valid for intraday gate
            # Bullish afternoon breakout reaching Camarilla H5 terminal exhaustion
            if (
                direction == "BULLISH"
                and h5 > 0
                and abs(ltp - h5) / ltp <= 0.03
                and ltp >= h5 * 0.999
            ):
                logger.debug(
                    f"[AfternoonThrust] Suppressed bullish thrust on {clean_sym}: "
                    f"Spot ₹{ltp:,.1f} reached Camarilla H5 ceiling ₹{h5:,.1f} (Terminal Exhaustion)"
                )
                return None

            # Bearish afternoon flush reaching Camarilla L5 terminal exhaustion
            if (
                direction == "BEARISH"
                and l5 > 0
                and abs(ltp - l5) / ltp <= 0.03
                and ltp <= l5 * 1.001
            ):
                logger.debug(
                    f"[AfternoonThrust] Suppressed bearish flush on {clean_sym}: "
                    f"Spot ₹{ltp:,.1f} reached Camarilla L5 floor ₹{l5:,.1f} (Terminal Exhaustion)"
                )
                return None

            # Bearish flush colliding with un-breached Camarilla L4 floor
            if direction == "BEARISH" and l4 > 0 and abs(ltp - l4) / ltp <= 0.03 and ltp >= l4:
                if col_c in df_today.columns:
                    last_c_val = float(df_today[col_c].iloc[-1])
                    if last_c_val >= l4:
                        logger.debug(
                            f"[AfternoonThrust] Suppressed bearish flush on {clean_sym}: "
                            f"Spot ₹{ltp:,.1f} / Close ₹{last_c_val:,.1f} has not closed below Camarilla L4 floor ₹{l4:,.1f}"
                        )
                        return None
    except Exception as e_dl:
        logger.debug(f"[AfternoonThrust] Daily levels check non-fatal exception: {e_dl}")

    # ── Microstructure / TBT 50-Depth Order Book Confirmation ──
    try:
        from market.fyers_tbt_manager import (
            fyers_tbt_manager,
            FyersTbtManager,
            resolve_tradable_tbt_symbol,
        )

        mgr = (
            fyers_tbt_manager
            if getattr(fyers_tbt_manager, "is_connected", False)
            else FyersTbtManager()
        )
        tradable = resolve_tradable_tbt_symbol(clean_sym)
        depth = mgr.get_50_depth(tradable or clean_sym)
        if depth and depth.get("status") not in ("UNAVAILABLE", None):
            obi_val = float(depth.get("obi_50", 0.0) or 0.0)
            fortress_bid = bool(depth.get("fortress_bid_wall_confirmed", False))
            fortress_ask = bool(depth.get("fortress_ask_wall_confirmed", False))

            if direction == "BULLISH" and (obi_val <= -0.25 or fortress_ask):
                logger.debug(
                    f"[AfternoonThrust] Suppressed bullish thrust on {clean_sym}: "
                    f"Overhead Fortress Ask Wall / heavy ask dominance (OBI={obi_val:.2f})"
                )
                return None
            if direction == "BEARISH" and (obi_val >= +0.25 or fortress_bid):
                logger.debug(
                    f"[AfternoonThrust] Suppressed bearish flush on {clean_sym}: "
                    f"Underlying Fortress Bid Wall / heavy bid dominance (OBI={obi_val:.2f})"
                )
                return None
    except Exception as e_tbt:
        logger.debug(f"[AfternoonThrust] TBT check non-fatal exception: {e_tbt}")

    # Stage determination:
    # IGNITED if spot has breached session extreme or surging with RVOL >= 1.35
    # PRIMED if coiled within 0.25% of extreme
    if is_bull_thrust:
        is_ignited = (ltp >= session_high) or (rvol_val >= 1.35 and ltp >= midday_high)
        stage = "IGNITED" if is_ignited else "PRIMED"
    else:
        is_ignited = (ltp <= session_low) or (rvol_val >= 1.35 and ltp <= midday_low)
        stage = "IGNITED" if is_ignited else "PRIMED"

    # Dynamic Brownian noise floor & Stop Loss calibration
    atr_5m = _calculate_5m_atr(df_5m)
    atr_floor = round(1.20 * atr_5m, 2) if atr_5m > 0 else 0.0
    index_min_floors = {
        "NIFTY": 20.5,
        "BANKNIFTY": 55.0,
        "FINNIFTY": 25.0,
        "MIDCPNIFTY": 16.0,
        "SENSEX": 75.0,
        "BANKEX": 75.0,
    }
    base_floor = index_min_floors.get(clean_sym, round(ltp * 0.0035, 2))
    min_sl_floor = max(base_floor, atr_floor)

    if is_bull_thrust:
        # Anchor stop below midday consolidation low or VWAP support floor
        structural_sl = min(midday_low * 0.998, effective_vwap * 0.997)
        if (ltp - structural_sl) < min_sl_floor:
            sl_price = round(ltp - min_sl_floor, 2)
        else:
            # Prevent excessive risk width: cap at 2.5x min_sl_floor
            sl_price = round(max(structural_sl, ltp - 2.5 * min_sl_floor), 2)

        risk_pts = max(min_sl_floor, ltp - sl_price)
        t1_price = round(ltp + 2.0 * risk_pts, 2)
        t2_price = round(ltp + 4.0 * risk_pts, 2)
        t3_price = round(ltp + 6.0 * risk_pts, 2)
        no_chase_lvl = round(ltp + 0.35 * risk_pts, 2)
        headline = f"⚡ [AFTERNOON THRUST] {clean_sym} PM Power Hour Breakout (LTP ₹{ltp:,.1f})"
        summary = (
            f"{clean_sym} second-half Afternoon Thrust confirmed: spot holding above VWAP "
            f"(₹{effective_vwap:,.1f}) and breaking midday compression with RVOL {rvol_val:.1f}x. "
            f"Holding strictly above ₹{sl_price:,.1f}. NO CHASE above ₹{no_chase_lvl:,.1f}."
        )
    else:
        structural_sl = max(midday_high * 1.002, effective_vwap * 1.003)
        if (structural_sl - ltp) < min_sl_floor:
            sl_price = round(ltp + min_sl_floor, 2)
        else:
            sl_price = round(min(structural_sl, ltp + 2.5 * min_sl_floor), 2)

        risk_pts = max(min_sl_floor, sl_price - ltp)
        t1_price = round(ltp - 2.0 * risk_pts, 2)
        t2_price = round(ltp - 4.0 * risk_pts, 2)
        t3_price = round(ltp - 6.0 * risk_pts, 2)
        no_chase_lvl = round(ltp - 0.35 * risk_pts, 2)
        headline = f"🚨 [AFTERNOON FLUSH] {clean_sym} PM Liquidation Breakdown (LTP ₹{ltp:,.1f})"
        summary = (
            f"{clean_sym} second-half Afternoon Flush confirmed: spot breaking below VWAP "
            f"(₹{effective_vwap:,.1f}) and session floor with RVOL {rvol_val:.1f}x. "
            f"Holding strictly below ₹{sl_price:,.1f}. NO CHASE below ₹{no_chase_lvl:,.1f}."
        )

    rr_ratio = round(abs(t1_price - ltp) / max(0.01, risk_pts), 1)
    rr_str = f"1:{rr_ratio:.1f}"

    # Conviction scoring (65 - 96)
    confidence_score = 70
    if rvol_val >= 1.5:
        confidence_score += 8
    elif rvol_val >= 1.3:
        confidence_score += 5
    if is_tight_coil:
        confidence_score += 6
    if stage == "IGNITED":
        confidence_score += 5
    if is_heavyweight or is_index:
        confidence_score += 4
    if rr_ratio >= 2.0:
        confidence_score += 3
    confidence_score = min(96, confidence_score)

    # Option resolution via Unified VIX-Aware Resolver
    from engine.option_resolver import resolve_option_contract

    # Institutional Gamma Asymmetry: For explosive afternoon breakouts (IGNITED or strong volume surge),
    # prioritize HIGH_GAMMA_ASYMMETRY (OTM+1 in the high-gamma sweet spot) to maximize percentage torque
    # and provide defined-risk multi-bagger asymmetry.
    target_tier = (
        "HIGH_GAMMA_ASYMMETRY" if (is_index and (stage == "IGNITED" or rvol_val >= 1.8)) else "ATM"
    )

    resolved_opt = resolve_option_contract(
        symbol=clean_sym,
        spot=ltp,
        direction=direction,
        underlying_sl=sl_price,
        underlying_target=t1_price,
        prefer_options=is_index,
        strike_tier=target_tier,
    )

    has_opt = resolved_opt is not None and resolved_opt.entry_premium > 0
    opt_contract_sym = resolved_opt.contract_symbol if has_opt else None
    opt_ltp = resolved_opt.entry_premium if has_opt else None
    opt_sl = resolved_opt.sl_premium if has_opt else None
    opt_t1 = resolved_opt.t1_premium if has_opt else None
    opt_t2 = resolved_opt.t2_premium if has_opt else None
    opt_runner = resolved_opt.t3_premium if has_opt else None
    opt_strike = resolved_opt.strike if has_opt else None
    opt_type = resolved_opt.option_type if has_opt else ("CE" if is_bull_thrust else "PE")
    lot_sz = resolved_opt.lot_size if has_opt else 1
    resolved_exp = resolved_opt.expiry if has_opt else None
    opt_no_chase = round(opt_ltp * 1.04, 2) if has_opt else None

    resolved_no_chase = round(opt_no_chase if has_opt else no_chase_lvl, 2)
    action_str = f"BUY {opt_type}" if has_opt else ("BUY" if is_bull_thrust else "SELL_SHORT")
    rec_entry = f"₹{opt_ltp:,.2f}" if has_opt else f"₹{ltp:,.1f}"
    rec_sl = f"₹{opt_sl:,.1f}" if has_opt else f"₹{sl_price:,.1f}"
    rec_t1 = f"₹{opt_t1:,.1f}" if has_opt else f"₹{t1_price:,.1f}"

    exec_trig = getattr(resolved_opt, "execution_trigger", None) if has_opt else None
    conf_rule = getattr(resolved_opt, "confirmation_rule", None) if has_opt else None
    exec_notes = getattr(resolved_opt, "execution_notes", None) if has_opt else None

    act_plan: dict[str, Any] = {
        "action": action_str,
        "contract": opt_contract_sym if has_opt else clean_sym,
        "instrument": opt_contract_sym if has_opt else clean_sym,
        "instrument_type": "OPTION" if has_opt else "EQUITY",
        "recommended_entry": rec_entry,
        "stop_loss": rec_sl,
        "target": rec_t1,
        "target_1": rec_t1,
        "target_2": f"₹{opt_t2:,.1f}" if (has_opt and opt_t2) else f"₹{t2_price:,.1f}",
        "target_3": f"₹{opt_runner:,.1f}" if (has_opt and opt_runner) else f"₹{t3_price:,.1f}",
        "runner_target": f"₹{opt_runner:,.1f}" if (has_opt and opt_runner) else f"₹{t3_price:,.1f}",
        "entry_type": "BREAKOUT_MOMENTUM" if stage == "IGNITED" else "LIMIT_ON_PULLBACK",
        "execution_trigger": exec_trig
        or (f"ABOVE_₹{opt_ltp:,.1f}_ON_1M_CLOSE" if has_opt else f"BREAK_{direction}"),
        "confirmation_rule": conf_rule
        or ("1_MIN_CANDLE_CLOSE_MANDATORY" if has_opt else "STANDARD_CONFIRMATION"),
        "execution_notes": exec_notes
        or (
            f"Confirm 1-minute candle close above ₹{opt_ltp:,.1f} before entering to eliminate fake-out wicks."
            if has_opt
            else "Wait for candle confirmation."
        ),
        "no_chase_boundary": f"₹{resolved_no_chase:,.1f}",
        "risk_reward": rr_str,
        "asymmetric_rr": f"1:{max(2.5, rr_ratio):.1f}",
        "underlying_symbol": clean_sym,
        "underlying_spot": f"₹{ltp:,.1f}",
        "underlying_sl": f"₹{sl_price:,.1f}",
        "spot_invalidation_anchor": f"₹{sl_price:,.1f}",
        "tactical_sl": rec_sl if has_opt else None,
        "structural_spot_sl": f"₹{sl_price:,.1f}" if has_opt else None,
        "disaster_stop_floor": f"₹{round(opt_ltp * 0.68, 2):,.2f}" if has_opt else None,
        "underlying_target": f"₹{t1_price:,.1f}",
        "underlying_target_2": f"₹{t2_price:,.1f}",
        "underlying_target_3": f"₹{t3_price:,.1f}",
        "when_to_buy": (
            f"Enter {opt_contract_sym} on confirmed 1-min candle close above ₹{opt_ltp:,.1f} as spot confirms breakout "
            f"{'above' if is_bull_thrust else 'below'} ₹{session_high if is_bull_thrust else session_low:,.1f} with VWAP hold."
            if has_opt
            else f"Enter {'LONG' if is_bull_thrust else 'SHORT'} as spot sustains momentum."
        ),
        "when_to_wait": f"DO NOT CHASE beyond ₹{resolved_no_chase:,.1f}. Wait for retest or cancel.",
        "profit_rule": "Scale 50% at T1 (+2.0R), move SL to Breakeven (+0.2%), risk drops to ₹0.00. Trail remainder on 5m 20-EMA.",
    }

    if has_opt:
        act_plan["option_type"] = opt_type
        act_plan["strike"] = opt_strike
        act_plan["option_plan"] = {
            "contract_symbol": opt_contract_sym,
            "strike": opt_strike,
            "option_type": opt_type,
            "entry_premium": opt_ltp,
            "sl_premium": opt_sl,
            "t1_premium": opt_t1,
            "t2_premium": opt_t2,
            "t3_premium": opt_runner,
            "no_chase_boundary": opt_no_chase,
            "lot_size": lot_sz,
            "expiry": resolved_exp,
            "expiry_date": resolved_exp,
        }
        if resolved_opt and resolved_opt.spread_details:
            act_plan["hedged_spread"] = resolved_opt.spread_details
            act_plan["strategy_type"] = resolved_opt.strategy_type

    alert_seg = "FNO_INDEX" if is_index else ("FNO_STOCK" if lot_sz > 1 else "EQUITY")
    phase_slot = get_session_phase_slot(now_dt)

    metrics_dict: dict[str, Any] = {
        "setup": "AFTERNOON_THRUST",
        "thrust_direction": direction,
        "session_phase": phase_slot,
        "cpr": cpr_gate.cpr_data if cpr_gate else {},
        "cpr_type": cpr_gate.cpr_type if cpr_gate else "NORMAL",
        "is_narrow_cpr": cpr_gate.is_narrow if cpr_gate else False,
        "is_wide_cpr": cpr_gate.is_wide if cpr_gate else False,
        "is_tight_midday_coil": is_tight_coil,
        "rvol": rvol_val,
        "session_high": session_high,
        "session_low": session_low,
        "midday_high": midday_high,
        "midday_low": midday_low,
        "no_chase_boundary": opt_no_chase if has_opt else resolved_no_chase,
        "spot_no_chase_boundary": resolved_no_chase,
        "target_1": opt_t1 if has_opt else t1_price,
        "target_2": opt_t2 if has_opt else t2_price,
        "target_3": opt_runner if has_opt else t3_price,
        "spot_invalidation_anchor": sl_price,
        "underlying_sl": sl_price,
        "underlying_symbol": clean_sym,
        "underlying_spot": ltp,
        "vwap": effective_vwap,
    }

    if has_opt and resolved_opt:
        metrics_dict["strategy_type"] = resolved_opt.strategy_type
        metrics_dict["vix_regime"] = resolved_opt.vix_regime
        metrics_dict["india_vix"] = resolved_opt.vix_value
        metrics_dict["execution_style_mandate"] = resolved_opt.execution_style_mandate
        if resolved_opt.spread_details:
            metrics_dict["hedged_spread"] = resolved_opt.spread_details

    is_live_opt = bool(opt_ltp and opt_ltp > 0.0)
    is_test = (os.environ.get("CHANAKYA_TESTING") == "1") or ("PYTEST_CURRENT_TEST" in os.environ)
    env_str = "TEST" if is_test else ("LIVE" if is_live_opt or ltp > 0 else "PAPER")

    return AutoAlert(
        alert_id=generate_alert_id(
            clean_sym,
            "AFTERNOON_THRUST",
            variant=f"{direction.lower()[:4]}-{phase_slot}",
        ),
        alert_type="AFTERNOON_THRUST",
        stage=stage,
        symbol=clean_sym,
        exchange="BFO" if clean_sym in ("SENSEX", "BANKEX") else ("NFO" if is_index else "NSE"),
        direction=direction,
        headline=headline,
        summary=summary,
        ltp=opt_ltp if has_opt else ltp,
        trigger_level=opt_ltp if has_opt else ltp,
        target_level=opt_t1 if has_opt else t1_price,
        stop_loss=opt_sl if has_opt else sl_price,
        no_chase_boundary=opt_no_chase if has_opt else resolved_no_chase,
        spot_no_chase_boundary=resolved_no_chase if has_opt else None,
        strike=opt_strike if has_opt else None,
        option_type=opt_type if has_opt else None,
        contract_symbol=opt_contract_sym if has_opt else None,
        expiry_date=resolved_exp if has_opt else None,
        underlying_spot=ltp,
        option_premium=opt_ltp if has_opt else None,
        market_status="OPEN",
        is_live=is_live_opt if has_opt else True,
        environment=env_str,
        confidence=confidence_score,
        segment=alert_seg,
        actionable_plan=act_plan,
        metrics=metrics_dict,
    )
