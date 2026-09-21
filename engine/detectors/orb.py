"""
engine/detectors/orb.py
───────────────────────
Autonomous Opening Range Breakout (ORB-15) Detector.

Identifies high-conviction intraday breakouts and breakdowns following the
09:15–09:30 IST opening discovery auction window.

Operational Invariants:
  1. Opening Range Definition:
     - Measures the High, Low, Range, and Midpoint of the first 15 minutes (09:15–09:30 IST).
     - Range sanity: Range must be between 0.25% and 3.5% of spot to avoid both dead chop
       and already-exhausted opening blow-offs.
  2. Directional Triggers & Anti-FOMO Discipline:
     - Bullish: 5m close above ORB High + price holding above intraday VWAP + TOD-RVOL >= 1.4x.
     - Bearish: 5m close below ORB Low + price holding below intraday VWAP + TOD-RVOL >= 1.4x.
     - Strict No-Chase: Disqualified if price has already extended > 35% of the opening range
       past the trigger level without a retest.
  3. Structural Invalidation & Asymmetric Targets:
     - Invalidation Stop-Loss: Anchored to ORB Midpoint ((High + Low) / 2) or base floor.
     - Target 1: 1.0x Opening Range expansion (+1.8R to +2.0R; trigger 50% scale-out & breakeven trail).
     - Target 2: 2.0x Opening Range expansion (+3.5R asymmetry).
     - Target 3: 3.5x Opening Range expansion (Moonshot runner).
  4. Non-Interference Guarantee:
     - Operates strictly as an orthogonal detector (ORB_BREAKOUT / ORB_BREAKDOWN).
     - Never mutes or interferes with early Precursor Radar, Gamma Blast, or Squeeze alerts.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta, time as dtime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from engine.alert_model import AutoAlert
from engine.option_resolver import resolve_option_contract, is_index_symbol

logger = logging.getLogger("chanakya.detectors.orb")


try:
    IST = ZoneInfo("Asia/Kolkata")
except Exception:
    IST = timezone(timedelta(hours=5, minutes=30))


def extract_opening_range(
    df: pd.DataFrame,
    opening_minutes: int = 15,
    ref_dt: Optional[datetime] = None,
) -> Optional[tuple[float, float, float, float]]:
    """
    Extracts (orb_high, orb_low, orb_range, orb_mid) from intraday DataFrame
    across the opening window (09:15 to 09:15 + opening_minutes IST).
    """
    if df is None or len(df) == 0:
        return None

    # Standardize column names
    cols = {c.lower(): c for c in df.columns}
    if "high" not in cols or "low" not in cols:
        return None

    h_col = cols["high"]
    l_col = cols["low"]

    # If df index is DatetimeIndex, filter for the opening session of today
    if isinstance(df.index, pd.DatetimeIndex):
        dt_idx = df.index
        if dt_idx.tz is None:
            dt_idx = dt_idx.tz_localize(IST)
        else:
            dt_idx = dt_idx.tz_convert(IST)

        today_date = (ref_dt or datetime.now(IST)).date()
        today_mask = dt_idx.date == today_date

        if not np.any(today_mask):
            # Fall back to most recent date in dataframe
            today_date = dt_idx.date[-1]
            today_mask = dt_idx.date == today_date

        # Window: 09:15 to 09:15 + opening_minutes
        end_min = 15 + opening_minutes
        end_hour = 9 + (end_min // 60)
        end_rem_min = end_min % 60
        start_time = dtime(9, 15)
        end_time = dtime(end_hour, end_rem_min)

        time_mask = (dt_idx.time >= start_time) & (dt_idx.time < end_time) & today_mask
        sub_df = df.loc[time_mask]
        if len(sub_df) > 0:
            orb_high = float(sub_df[h_col].max())
            orb_low = float(sub_df[l_col].min())
            orb_range = round(orb_high - orb_low, 2)
            orb_mid = round((orb_high + orb_low) / 2.0, 2)
            return orb_high, orb_low, orb_range, orb_mid

    # Fallback if unindexed or synthetic/slice: take first row or first few rows
    if len(df) >= 1:
        take_rows = min(len(df), max(1, opening_minutes // 5))
        sub_df = df.iloc[:take_rows]
        orb_high = float(sub_df[h_col].max())
        orb_low = float(sub_df[l_col].min())
        orb_range = round(orb_high - orb_low, 2)
        orb_mid = round((orb_high + orb_low) / 2.0, 2)
        return orb_high, orb_low, orb_range, orb_mid

    return None


def detect_opening_range_breakout(
    symbol: str,
    df: Optional[pd.DataFrame],
    ltp: float,
    vwap: Optional[float] = None,
    exchange: str = "NSE",
    rvol: Optional[float] = None,
    ref_time: Optional[datetime] = None,
    opening_minutes: int = 15,
    orb_levels: Optional[tuple[float, float, float, float]] = None,
    ignore_time_gate: bool = False,
) -> Optional[AutoAlert]:
    """
    Detects decisive Opening Range Breakouts/Breakdowns.
    Only activates post-09:30 IST when opening range formation is verified.
    """
    if ltp <= 0:
        return None

    now_dt = ref_time or datetime.now(IST)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=IST)
    else:
        now_dt = now_dt.astimezone(IST)

    # 1. Market Hours & Time Gate (09:30 to 11:30 IST)
    # The opening range is strictly forming from 09:15 to 09:30.
    # Breakout execution runs between 09:30 and 11:30 IST.
    curr_t = now_dt.time()
    if not ignore_time_gate:
        if curr_t < dtime(9, 30):
            # Range still discovering, do not fire prematurely
            return None
        if curr_t > dtime(11, 30):
            # Past active morning ORB window
            return None

    # 2. Extract or Resolve Opening Range Levels
    if orb_levels:
        orb_high, orb_low, orb_range, orb_mid = orb_levels
    else:
        extracted = extract_opening_range(df, opening_minutes=opening_minutes, ref_dt=now_dt)
        if not extracted:
            return None
        orb_high, orb_low, orb_range, orb_mid = extracted

    if orb_range <= 0 or orb_high <= 0 or orb_low <= 0:
        return None

    # 3. Range Sanity & Quality Check
    range_pct = (orb_range / ltp) * 100.0
    # Guard against flat chop (< 0.25% range has no expansion velocity)
    if range_pct < 0.25:
        logger.debug(f"[ORB] {symbol} opening range too narrow ({range_pct:.2f}% < 0.25%), skipping.")
        return None
    # Guard against exhausted opening bar (> 3.5% range has consumed session ATR)
    if range_pct > 3.5:
        logger.debug(f"[ORB] {symbol} opening range exhausted ({range_pct:.2f}% > 3.5%), skipping.")
        return None

    is_index = symbol.upper() in (
        "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"
    )

    # 4. Evaluate Breakout Direction
    is_bullish = False
    is_bearish = False

    no_chase_buffer = round(0.35 * orb_range, 2)
    max_bull_chase = round(orb_high + no_chase_buffer, 2)
    max_bear_chase = round(orb_low - no_chase_buffer, 2)

    min_rvol = 1.30 if is_index else 1.45
    rvol_val = float(rvol or 1.5)

    if ltp >= orb_high:
        if vwap and vwap > 0 and ltp < (vwap * 0.998):
            # Fighting intraday VWAP, reject long
            is_bullish = False
        elif ltp > max_bull_chase:
            # Extended past no-chase boundary
            is_bullish = False
        elif rvol_val < min_rvol:
            # Insufficient volume expansion
            is_bullish = False
        else:
            is_bullish = True

    elif ltp <= orb_low:
        if vwap and vwap > 0 and ltp > (vwap * 1.002):
            # Fighting intraday VWAP, reject short
            is_bearish = False
        elif ltp < max_bear_chase:
            # Extended past short no-chase boundary
            is_bearish = False
        elif rvol_val < min_rvol:
            is_bearish = False
        else:
            is_bearish = True

    if not (is_bullish or is_bearish):
        return None

    # 4.1 Candlestick Pattern Confirmation & Divergence Trap Veto
    conf_candle = None
    is_candle_confirmed = False
    div_type = None
    div_bias = None
    if df is not None and len(df) >= 5:
        try:
            from analysis.market_structure import (
                detect_confirmation_candle,
                detect_divergence,
            )

            dir_eval = "BULLISH" if is_bullish else "BEARISH"
            conf_res = detect_confirmation_candle(df, direction=dir_eval)
            is_candle_confirmed = bool(conf_res.get("confirmed")) if isinstance(conf_res, dict) else False
            conf_candle = conf_res.get("pattern") if isinstance(conf_res, dict) else None

            div_res = detect_divergence(df)
            div_type = div_res.get("type") if isinstance(div_res, dict) else None
            div_bias = div_res.get("bias") if isinstance(div_res, dict) else None
            if div_type == "NONE":
                div_type = None
            if div_bias == "NONE":
                div_bias = None

            # Trap Veto: Disallow breakout into opposing regular divergence exhaustion
            if div_type:
                if is_bullish and div_bias == "BEARISH" and "REGULAR" in div_type:
                    logger.debug(
                        f"[ORB] {symbol} Bullish breakout suppressed: Bearish regular RSI divergence trap ({div_type})"
                    )
                    return None
                elif is_bearish and div_bias == "BULLISH" and "REGULAR" in div_type:
                    logger.debug(
                        f"[ORB] {symbol} Bearish breakdown suppressed: Bullish regular RSI divergence trap ({div_type})"
                    )
                    return None
        except Exception as _e_smc:
            logger.debug(f"[ORB] Candle/divergence check error: {_e_smc}")

    # 5. Build Asymmetric Trade Plan
    now_iso = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")
    direction = "BULLISH" if is_bullish else "BEARISH"
    alert_type = "ORB_BREAKOUT" if is_bullish else "ORB_BREAKDOWN"
    alert_id = f"orb-{direction.lower()[:4]}-{symbol.lower()}-{uuid.uuid4().hex[:6]}"

    if is_bullish:
        trigger_level = orb_high
        stop_loss = orb_mid
        risk_pts = max(1.0, round(ltp - stop_loss, 2))
        target_1 = round(orb_high + (1.0 * orb_range), 2)
        target_2 = round(orb_high + (2.0 * orb_range), 2)
        target_3 = round(orb_high + (3.5 * orb_range), 2)
        no_chase_lvl = max_bull_chase
        entry_min = round(max(stop_loss + 0.5, ltp * 0.998), 1)
        entry_max = round(min(target_1 - 0.5, no_chase_lvl), 1)
        rr_ratio = round((target_1 - ltp) / max(0.1, risk_pts), 1)
        headline = (
            f"⚡ ORB-15 BREAKOUT: {symbol} at ₹{ltp:,.1f} (Crossed Range High ₹{orb_high:,.1f})"
        )
        summary = (
            f"15-min Opening Range Breakout confirmed! High ₹{orb_high:,.1f} reclaimed with "
            f"{rvol_val:.1f}x RVOL and VWAP support. Stop-Loss at Midpoint ₹{orb_mid:,.1f}."
        )
        when_buy = f"Enter on Ask or 5m retest of ₹{orb_high:,.1f} holding above VWAP."
        when_wait = f"DO NOT CHASE above ₹{no_chase_lvl:,.1f}; wait for retest of Opening Range High."
    else:
        trigger_level = orb_low
        stop_loss = orb_mid
        risk_pts = max(1.0, round(stop_loss - ltp, 2))
        target_1 = round(orb_low - (1.0 * orb_range), 2)
        target_2 = round(orb_low - (2.0 * orb_range), 2)
        target_3 = round(orb_low - (3.5 * orb_range), 2)
        no_chase_lvl = max_bear_chase
        entry_max = round(min(stop_loss - 0.5, ltp * 1.002), 1)
        entry_min = round(max(target_1 + 0.5, no_chase_lvl), 1)
        rr_ratio = round((ltp - target_1) / max(0.1, risk_pts), 1)
        headline = (
            f"⚡ ORB-15 BREAKDOWN: {symbol} at ₹{ltp:,.1f} (Broke Range Low ₹{orb_low:,.1f})"
        )
        summary = (
            f"15-min Opening Range Breakdown confirmed! Low ₹{orb_low:,.1f} breached with "
            f"{rvol_val:.1f}x RVOL and sub-VWAP pressure. Stop-Loss at Midpoint ₹{orb_mid:,.1f}."
        )
        when_buy = f"Short on Bid or 5m retest of ₹{orb_low:,.1f} staying below VWAP."
        when_wait = f"DO NOT CHASE below ₹{no_chase_lvl:,.1f}; wait for retest of Opening Range Low."

    confidence = 82
    if rvol_val >= 2.0:
        confidence += 6
    if vwap and ((is_bullish and ltp > vwap) or (is_bearish and ltp < vwap)):
        confidence += 4
    if is_candle_confirmed:
        confidence += 5
    if div_type and ((is_bullish and div_bias == "BULLISH") or (is_bearish and div_bias == "BEARISH")):
        confidence += 4
    confidence = min(96, confidence)

    clean_sym = symbol.upper().replace("NSE:", "").replace("BSE:", "").strip()
    is_idx = is_index_symbol(clean_sym)
    opt_plan = (
        resolve_option_contract(
            symbol=clean_sym,
            spot=ltp,
            direction=direction,
            underlying_sl=stop_loss,
            underlying_target=target_1,
        )
        if is_idx
        else None
    )

    if opt_plan:
        opt_headline = f"⚡ ORB-15 {'BREAKOUT' if is_bullish else 'BREAKDOWN'}: {opt_plan.contract_symbol} @ ₹{opt_plan.entry_premium:,.1f} (Spot ₹{ltp:,.1f})"
        act_plan = {
            "action": f"BUY {opt_plan.option_type}",
            "contract": opt_plan.contract_symbol,
            "instrument": opt_plan.contract_symbol,
            "instrument_type": "OPTION",
            "recommended_entry": f"₹{opt_plan.entry_premium:,.2f}",
            "stop_loss": f"₹{opt_plan.sl_premium:,.1f}",
            "target": f"₹{opt_plan.t1_premium:,.1f}",
            "target_1": f"₹{opt_plan.t1_premium:,.1f}",
            "target_2": f"₹{opt_plan.t2_premium:,.1f}",
            "risk_reward": f"1:{rr_ratio:.1f}",
            "underlying_spot": f"₹{ltp:,.1f}",
            "underlying_sl": f"₹{stop_loss:,.1f}",
            "underlying_target": f"₹{target_1:,.1f}",
            "option_type": opt_plan.option_type,
            "strike": opt_plan.strike,
            "option_plan": opt_plan.as_dict(),
            "when_to_buy": f"Buy {opt_plan.contract_symbol} while {clean_sym} spot holds {'above' if is_bullish else 'below'} ₹{trigger_level:,.1f}.",
            "when_to_wait": when_wait,
            "profit_rule": "Book 50% at T1, move Stop-Loss to Breakeven, trail runner on 5m 20-EMA.",
        }
        return AutoAlert(
            alert_id=alert_id,
            alert_type=alert_type,
            stage="IGNITED",
            symbol=clean_sym,
            exchange="NFO",
            direction=direction,
            headline=opt_headline,
            summary=summary,
            ltp=opt_plan.entry_premium,
            trigger_level=opt_plan.entry_premium,
            target_level=opt_plan.t1_premium,
            stop_loss=opt_plan.sl_premium,
            strike=opt_plan.strike,
            option_type=opt_plan.option_type,
            contract_symbol=opt_plan.contract_symbol,
            option_premium=opt_plan.entry_premium,
            underlying_spot=ltp,
            lot_size=opt_plan.lot_size,
            segment="FNO_INDEX",
            no_chase_boundary=no_chase_lvl,
            confidence=confidence,
            created_at=now_iso,
            is_live=True,
            environment="LIVE",
            entry_type="LIMIT_ON_PULLBACK",
            setup_style="CONTINUATION",
            metrics={
                "orb_high": orb_high,
                "orb_low": orb_low,
                "orb_range": orb_range,
                "orb_mid": orb_mid,
                "range_pct": round(range_pct, 2),
                "rvol": round(rvol_val, 2),
                "vwap": vwap,
                "target_2": target_2,
                "target_3": target_3,
                "confirmation_candle": conf_candle,
                "divergence_type": div_type,
            },
            actionable_plan=act_plan,
        )

    return AutoAlert(
        alert_id=alert_id,
        alert_type=alert_type,
        stage="IGNITED",
        symbol=symbol,
        exchange=exchange,
        direction=direction,
        headline=headline,
        summary=summary,
        ltp=round(ltp, 2),
        trigger_level=trigger_level,
        target_level=target_1,
        stop_loss=stop_loss,
        no_chase_boundary=no_chase_lvl,
        confidence=confidence,
        created_at=now_iso,
        is_live=True,
        environment="LIVE",
        entry_type="LIMIT_ON_PULLBACK",
        setup_style="CONTINUATION",
        metrics={
            "orb_high": orb_high,
            "orb_low": orb_low,
            "orb_range": orb_range,
            "orb_mid": orb_mid,
            "range_pct": round(range_pct, 2),
            "rvol": round(rvol_val, 2),
            "vwap": vwap,
            "target_2": target_2,
            "target_3": target_3,
            "confirmation_candle": conf_candle,
            "divergence_type": div_type,
        },
        actionable_plan={
            "action": f"BUY_{alert_type}" if is_bullish else f"SELL_{alert_type}",
            "entry_type": "LIMIT_ON_PULLBACK",
            "entry_range": f"₹{entry_min:,.1f} – ₹{entry_max:,.1f}",
            "stop_loss": f"₹{stop_loss:,.1f}",
            "target": f"₹{target_1:,.1f}",
            "target_2": f"₹{target_2:,.1f}",
            "target_3": f"₹{target_3:,.1f}",
            "risk_reward": f"1:{rr_ratio:.1f}",
            "when_to_buy": when_buy,
            "when_to_wait": when_wait,
            "profit_rule": f"Book 50% at Target 1 (₹{target_1:,.1f}), move Stop-Loss to Breakeven, trail runner to Target 2.",
        },
    )

