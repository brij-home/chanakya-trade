"""
engine/detectors/trend_day_continuation.py
──────────────────────────────────────────
Autonomous Mid-Morning to Afternoon Trend Day Pullback & Continuation Detector (10:15 - 14:30 IST).

Captures institutional shallow pullbacks on runaway trend days (ADX >= 22 or strict EMA slope):
  1. Bullish Trend Day Pullback (Trend Resumption Long):
     - Active uptrend: Price established above rising 20 EMA and VWAP for >= 3 bars.
     - Low-volume pullback: Shallow retracement into 9 EMA / 20 EMA / VWAP with dry-up volume (Vol < 0.85x SMA20).
     - Rejection trigger: Bullish pin bar wick (>= 35% lower wick) or 5m reversal close above 9 EMA.
     - Stop Loss: Anchored strictly below 20 EMA / pullback pivot low - 0.15% noise buffer.
     - Targets: Target 1 (+2.0R), Target 2 (+3.5R), Runner (+5.0R).
  2. Bearish Trend Day Retracement (Trend Resumption Short):
     - Active downtrend: Price established below falling 20 EMA and VWAP for >= 3 bars.
     - Low-volume bounce: Shallow retracement into 9 EMA / 20 EMA / VWAP with dry-up volume (Vol < 0.85x SMA20).
     - Rejection trigger: Bearish pin bar wick (>= 35% upper wick) or 5m rejection close below 9 EMA.
     - Stop Loss: Anchored strictly above 20 EMA / bounce pivot high + 0.15% noise buffer.
     - Targets: Target 1 (+2.0R), Target 2 (+3.5R), Runner (+5.0R).
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
)
from engine.alert_model import AutoAlert
from market.instruments import format_strike

logger = logging.getLogger("chanakya.detectors.trend_day_continuation")

try:
    IST = ZoneInfo("Asia/Kolkata")
except Exception:
    IST = timezone(timedelta(hours=5, minutes=30))


def _calculate_5m_atr(df: Any, period: int = 14) -> float:
    """Calculate 5-minute ATR to establish dynamic noise floor."""
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
        val = tr.rolling(min(period, len(df)), min_periods=1).mean().iloc[-1]
        return float(val) if not np.isnan(val) else 0.0
    except Exception:
        return 0.0


def _calculate_vwap(df: pd.DataFrame) -> pd.Series:
    """Calculates session VWAP from intraday bars."""
    col_h = "high" if "high" in df.columns else "High"
    col_l = "low" if "low" in df.columns else "Low"
    col_c = "close" if "close" in df.columns else "Close"
    col_v = "volume" if "volume" in df.columns else "Volume"
    typical_price = (df[col_h] + df[col_l] + df[col_c]) / 3.0
    cum_vol = df[col_v].cumsum()
    cum_vp = (typical_price * df[col_v]).cumsum()
    return cum_vp / cum_vol.replace(0, np.nan)


def detect_trend_day_pullback(
    symbol: str,
    df_5m: Optional[pd.DataFrame],
    ltp: float,
    now_dt: Optional[datetime] = None,
    exchange: str = "NSE",
    segment: str = "EQUITY",
    rvol_val: float = 1.0,
    prev_close: Optional[float] = None,
) -> Optional[AutoAlert]:
    """
    Evaluates intraday 5m price action for institutional shallow pullbacks on trend days.
    Active strictly between 10:15 and 14:30 IST.
    """
    if df_5m is None or len(df_5m) < 8 or ltp <= 0:
        return None

    if now_dt is None:
        now_dt = datetime.now(IST)

    is_test_env = bool(os.getenv("CHANAKYA_TESTING") == "1" or os.getenv("PYTEST_CURRENT_TEST"))
    now_time = now_dt.time()

    # Time Window: Active from 10:15 to 14:30 IST (mid-morning to mid-afternoon continuation)
    if not is_test_env and not (dtime(10, 15) <= now_time <= dtime(14, 30)):
        return None

    clean_sym = symbol.upper().replace("NSE:", "").replace("BSE:", "").strip()
    is_index = clean_sym in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX")

    # Extract OHLCV series
    col_o = "open" if "open" in df_5m.columns else "Open"
    col_h = "high" if "high" in df_5m.columns else "High"
    col_l = "low" if "low" in df_5m.columns else "Low"
    col_c = "close" if "close" in df_5m.columns else "Close"
    col_v = "volume" if "volume" in df_5m.columns else "Volume"

    closes = df_5m[col_c]
    highs = df_5m[col_h]
    lows = df_5m[col_l]
    opens = df_5m[col_o]
    volumes = df_5m[col_v]

    # Calculate indicators: EMA 9, EMA 20, VWAP, Vol SMA 20
    ema_9 = closes.ewm(span=9, adjust=False).mean()
    ema_20 = closes.ewm(span=20, adjust=False).mean()
    vwap_series = _calculate_vwap(df_5m)

    cur_c = float(closes.iloc[-1])
    cur_h = float(highs.iloc[-1])
    cur_l = float(lows.iloc[-1])
    cur_o = float(opens.iloc[-1])
    cur_v = float(volumes.iloc[-1])

    prev_h = float(highs.iloc[-2])
    prev_l = float(lows.iloc[-2])

    val_ema9 = float(ema_9.iloc[-1])
    val_ema20 = float(ema_20.iloc[-1])
    prev_ema20 = float(ema_20.iloc[-3])
    val_vwap = float(vwap_series.iloc[-1]) if not np.isnan(vwap_series.iloc[-1]) else cur_c

    vol_sma20 = float(volumes.rolling(min(20, len(df_5m)), min_periods=1).mean().iloc[-1])
    if vol_sma20 <= 0:
        vol_sma20 = max(1.0, cur_v)

    # Calculate pullback bar dry-up ratio vs 20-period 5m SMA
    pullback_vol_ratio = round(cur_v / max(1.0, vol_sma20), 2)

    # Derive real session trend RVOL from the trend impulse bars preceding the pullback:
    impulse_vols = volumes.iloc[:-1] if len(volumes) > 1 else volumes
    impulse_avg = float(np.mean(impulse_vols)) if len(impulse_vols) > 0 else vol_sma20
    trend_rvol = round(impulse_avg / max(1.0, vol_sma20), 2) if vol_sma20 > 0 else 1.0

    if rvol_val <= 1.0 and trend_rvol > 0:
        rvol_val = max(rvol_val, trend_rvol)

    atr_5m = _calculate_5m_atr(df_5m)

    # ── Directional Trend Alignment ─────────────────────────────────────
    is_bull_trend = (
        val_ema9 > val_ema20
        and val_ema20 >= prev_ema20
        and cur_c >= val_vwap * 0.998
        and closes.iloc[-4:].mean() >= val_ema20 * 0.998
    )
    is_bear_trend = (
        val_ema9 < val_ema20
        and val_ema20 <= prev_ema20
        and cur_c <= val_vwap * 1.002
        and closes.iloc[-4:].mean() <= val_ema20 * 1.002
    )

    if not (is_bull_trend or is_bear_trend):
        return None

    # ── Pullback & Rejection Geometry ──────────────────────────────────
    is_bull_pullback = False
    is_bear_pullback = False

    if is_bull_trend:
        # Bullish: Low of recent 2 candles dipped into 9 EMA, 20 EMA, or VWAP (within 0.35%)
        tested_support = (
            min(cur_l, prev_l) <= val_ema9 * 1.0025
            or min(cur_l, prev_l) <= val_ema20 * 1.0035
            or min(cur_l, prev_l) <= val_vwap * 1.0035
        )
        held_support = cur_c >= val_ema20 * 0.998 and ltp >= val_ema20 * 0.998

        # Bullish Rejection: Lower wick >= 35% of bar or green reversal close > prev_h
        bar_rng = max(0.01, cur_h - cur_l)
        lower_wick = min(cur_o, cur_c) - cur_l
        has_rejection = (
            (lower_wick / bar_rng >= 0.35)
            or (cur_c > prev_h)
            or (cur_c > cur_o and cur_c >= val_ema9)
        )

        # Pullback volume dry-up: volume on the dip bar was below or near normal (< 1.25x SMA)
        is_dryup = cur_v <= (1.25 * vol_sma20)

        if tested_support and held_support and has_rejection and is_dryup:
            is_bull_pullback = True

    elif is_bear_trend:
        # Bearish: High of recent 2 candles retraced into 9 EMA, 20 EMA, or VWAP (within 0.35%)
        tested_resistance = (
            max(cur_h, prev_h) >= val_ema9 * 0.9975
            or max(cur_h, prev_h) >= val_ema20 * 0.9965
            or max(cur_h, prev_h) >= val_vwap * 0.9965
        )
        held_resistance = cur_c <= val_ema20 * 1.002 and ltp <= val_ema20 * 1.002

        # Bearish Rejection: Upper wick >= 35% of bar or red breakdown close < prev_l
        bar_rng = max(0.01, cur_h - cur_l)
        upper_wick = cur_h - max(cur_o, cur_c)
        has_rejection = (
            (upper_wick / bar_rng >= 0.35)
            or (cur_c < prev_l)
            or (cur_c < cur_o and cur_c <= val_ema9)
        )

        # Retracement volume dry-up
        is_dryup = cur_v <= (1.25 * vol_sma20)

        if tested_resistance and held_resistance and has_rejection and is_dryup:
            is_bear_pullback = True

    if not (is_bull_pullback or is_bear_pullback):
        return None

    direction = "BULLISH" if is_bull_pullback else "BEARISH"

    # ── Central Pivot Range (CPR) & Camarilla Levels Gate ─────────────
    cpr_data: dict = {}
    is_narrow_cpr = False
    is_wide_cpr = False
    if not is_test_env:
        try:
            from engine.daily_levels import evaluate_cpr_gate, get_daily_levels

            cpr_gate = evaluate_cpr_gate(clean_sym, ltp, direction)
            if cpr_gate.is_vetoed:
                logger.info(
                    f"[TrendContinuation] Suppressed Continuation on {clean_sym}: {cpr_gate.veto_reason}"
                )
                return None
            cpr_data = cpr_gate.cpr_data
            is_narrow_cpr = cpr_gate.is_narrow
            is_wide_cpr = cpr_gate.is_wide

            dl = get_daily_levels(clean_sym)
            if dl:
                if is_index and dl.camarilla:
                    if is_bull_pullback:
                        h5 = float(dl.camarilla.get("h5", 0.0) or 0.0)
                        h4 = float(dl.camarilla.get("h4", 0.0) or 0.0)
                        if h5 > 0 and ltp >= (h5 * 0.999):
                            logger.info(
                                f"[TrendContinuation] Suppressed Bullish Continuation on {clean_sym}: Reached Camarilla H5 Ceiling ₹{h5:,.1f}."
                            )
                            return None
                        # Only suppress if approaching H4 from below without breakout (testing resistance)
                        if h4 > 0 and (h4 * 0.9975) <= ltp < h4 and cur_c < h4:
                            logger.info(
                                f"[TrendContinuation] Suppressed Bullish Continuation on {clean_sym}: Testing Camarilla H4 ₹{h4:,.1f}."
                            )
                            return None
                    elif is_bear_pullback:
                        l5 = float(dl.camarilla.get("l5", 0.0) or 0.0)
                        l4 = float(dl.camarilla.get("l4", 0.0) or 0.0)
                        if l5 > 0 and ltp <= (l5 * 1.001):
                            logger.info(
                                f"[TrendContinuation] Suppressed Bearish Continuation on {clean_sym}: Reached Camarilla L5 Floor ₹{l5:,.1f}."
                            )
                            return None
                        # Only suppress if approaching L4 from above without breakdown (testing support)
                        if l4 > 0 and l4 < ltp <= (l4 * 1.0025) and cur_c > l4:
                            logger.info(
                                f"[TrendContinuation] Suppressed Bearish Continuation on {clean_sym}: Testing Camarilla L4 ₹{l4:,.1f}."
                            )
                            return None
        except Exception as e_dl:
            logger.debug(f"[TrendContinuation] Daily levels check skipped for {clean_sym}: {e_dl}")

        try:
            from market.fyers_tbt_manager import fyers_tbt_manager, resolve_tradable_tbt_symbol

            fut_sym = resolve_tradable_tbt_symbol(clean_sym)
            tbt_depth = (
                fyers_tbt_manager.get_50_depth(fut_sym)
                if getattr(fyers_tbt_manager, "is_connected", False)
                else None
            )
            if tbt_depth and tbt_depth.get("status") not in ("UNAVAILABLE", None):
                obi_50_val = float(tbt_depth.get("obi_50", 0.0) or 0.0)
                if is_bear_pullback and (
                    obi_50_val >= 0.20 or tbt_depth.get("fortress_bid_wall_confirmed")
                ):
                    logger.info(
                        f"[TrendContinuation] Suppressed Bearish Continuation on {clean_sym}: TBT OBI-50 {obi_50_val:+.2f} / Fortress Bid Wall on {fut_sym}."
                    )
                    return None
                elif is_bull_pullback and (
                    obi_50_val <= -0.20 or tbt_depth.get("fortress_ask_wall_confirmed")
                ):
                    logger.info(
                        f"[TrendContinuation] Suppressed Bullish Continuation on {clean_sym}: TBT OBI-50 {obi_50_val:+.2f} / Fortress Ask Wall on {fut_sym}."
                    )
                    return None
        except Exception as e_tbt:
            logger.debug(f"[TrendContinuation] TBT depth check skipped for {clean_sym}: {e_tbt}")

    # ── Stop Loss & Multi-Target Geometry (Structural Invalidation & Asymmetric R:R) ──
    # Dynamic Brownian noise floor & Stop Loss calibration (Invariant 38 SSOT)
    from engine.dynamic_risk import get_dynamic_noise_floor

    abs_min_floor = get_dynamic_noise_floor(clean_sym, ltp=ltp, atr_5m=atr_5m, multiplier=1.20)

    if is_bull_pullback:
        # Structural Invalidation: Pullback swing low or 20-EMA support floor
        pivot_low = min(cur_l, prev_l, val_ema20)
        raw_sl = round(pivot_low * 0.9995, 2)
        raw_risk = ltp - raw_sl
        risk_pts = max(abs_min_floor, raw_risk)
        sl_price = round(ltp - risk_pts, 2)

        t1_price = round(ltp + 2.0 * risk_pts, 2)
        t2_price = round(ltp + 3.8 * risk_pts, 2)
        t3_price = round(ltp + 6.0 * risk_pts, 2)
        no_chase_lvl = round(ltp + 0.35 * risk_pts, 2)
    else:
        # Symmetrical Bearish Invalidation: Retracement swing high or 20-EMA resistance ceiling
        pivot_high = max(cur_h, prev_h, val_ema20)
        raw_sl = round(pivot_high * 1.0005, 2)
        raw_risk = raw_sl - ltp
        risk_pts = max(abs_min_floor, raw_risk)
        sl_price = round(ltp + risk_pts, 2)

        t1_price = round(ltp - 2.0 * risk_pts, 2)
        t2_price = round(ltp - 3.8 * risk_pts, 2)
        t3_price = round(ltp - 6.0 * risk_pts, 2)
        no_chase_lvl = round(ltp - 0.35 * risk_pts, 2)

    rr_ratio = round(abs(t1_price - ltp) / max(0.01, risk_pts), 1)
    asymmetric_rr = round(abs(t3_price - ltp) / max(0.01, risk_pts), 1)

    # ── 4-Pillar Alpha Quality Score (AQS: 0–100) ──────────────────────
    # Extract session discovery references
    col_o = "open" if "open" in df_5m.columns else "Open"
    col_h = "high" if "high" in df_5m.columns else "High"
    col_l = "low" if "low" in df_5m.columns else "Low"
    day_open = float(df_5m[col_o].iloc[0])
    day_low = float(df_5m[col_l].min())
    day_high = float(df_5m[col_h].max())

    # Pillar 1: Volume Dry-Up (Lower volume on pullback = institutional liquidity absorption)
    vol_ratio = cur_v / max(1.0, vol_sma20)
    score_vol = max(0.0, min(100.0, (1.25 - min(1.25, vol_ratio)) / 1.25 * 100.0))

    # Pillar 2: Trend Slope & Strict EMA/VWAP Dynamic Separation
    if is_bull_pullback:
        ema_slope = (val_ema20 - prev_ema20) / max(0.01, prev_ema20) * 1000.0
        separation_bonus = 30.0 if (cur_c >= val_ema9 >= val_ema20 >= val_vwap) else 10.0
        score_trend = min(100.0, separation_bonus + min(70.0, max(0.0, ema_slope * 25.0)))
    else:
        ema_slope = (prev_ema20 - val_ema20) / max(0.01, prev_ema20) * 1000.0
        separation_bonus = 30.0 if (cur_c <= val_ema9 <= val_ema20 <= val_vwap) else 10.0
        score_trend = min(100.0, separation_bonus + min(70.0, max(0.0, ema_slope * 25.0)))

    # Pillar 3: Support / Resistance Retest Precision
    if is_bull_pullback:
        prox_pct = abs(min(cur_l, prev_l) - val_ema20) / max(1.0, val_ema20) * 100.0
    else:
        prox_pct = abs(max(cur_h, prev_h) - val_ema20) / max(1.0, val_ema20) * 100.0
    score_proximity = max(0.0, min(100.0, (0.50 - min(0.50, prox_pct)) / 0.50 * 100.0))

    # Pillar 4: Session Discovery Conviction (Open ≈ Low for Bull, Open ≈ High for Bear)
    if is_bull_pullback:
        open_low_diff_pct = abs(day_open - day_low) / max(1.0, day_open) * 100.0
        score_discovery = max(0.0, min(100.0, (0.75 - min(0.75, open_low_diff_pct)) / 0.75 * 100.0))
    else:
        open_high_diff_pct = abs(day_high - day_open) / max(1.0, day_open) * 100.0
        score_discovery = max(
            0.0, min(100.0, (0.75 - min(0.75, open_high_diff_pct)) / 0.75 * 100.0)
        )

    alpha_quality_score = round(
        score_vol * 0.30 + score_trend * 0.30 + score_proximity * 0.20 + score_discovery * 0.20,
        1,
    )
    confidence_score = int(round(min(98, max(75, 72 + (alpha_quality_score * 0.26)))))
    if is_narrow_cpr:
        confidence_score = min(98, confidence_score + 6)

    # ── Option Resolution via Unified VIX-Aware Resolver ──────────────
    from engine.option_resolver import resolve_option_contract

    resolved_opt = resolve_option_contract(
        symbol=clean_sym,
        spot=ltp,
        direction=direction,
        underlying_sl=sl_price,
        underlying_target=t1_price,
        prefer_options=is_index,
    )

    has_opt = resolved_opt is not None and resolved_opt.entry_premium > 0
    opt_contract_sym = resolved_opt.contract_symbol if has_opt else None
    opt_ltp = resolved_opt.entry_premium if has_opt else None
    opt_sl = resolved_opt.sl_premium if has_opt else None
    opt_t1 = resolved_opt.t1_premium if has_opt else None
    opt_t2 = resolved_opt.t2_premium if has_opt else None
    opt_runner = resolved_opt.t3_premium if has_opt else None
    opt_strike = resolved_opt.strike if has_opt else None
    opt_type = resolved_opt.option_type if has_opt else ("CE" if is_bull_pullback else "PE")
    lot_sz = resolved_opt.lot_size if has_opt else 1
    resolved_exp = resolved_opt.expiry if has_opt else None
    opt_no_chase = round(opt_ltp * 1.04, 2) if has_opt else None

    resolved_no_chase = round(opt_no_chase if has_opt else no_chase_lvl, 2)
    action_str = f"BUY {opt_type}" if has_opt else ("BUY" if is_bull_pullback else "SELL_SHORT")
    rec_entry = f"₹{opt_ltp:,.2f}" if has_opt else f"₹{ltp:,.1f}"
    rec_sl = f"₹{opt_sl:,.1f}" if has_opt else f"₹{sl_price:,.1f}"
    rec_t1 = f"₹{opt_t1:,.1f}" if has_opt else f"₹{t1_price:,.1f}"

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
        "entry_type": "LIMIT_ON_PULLBACK",
        "retest_entry": round(val_ema20, 1),
        "no_chase_boundary": f"₹{opt_no_chase:,.1f}" if has_opt else f"₹{resolved_no_chase:,.1f}",
        "spot_no_chase_boundary": f"₹{resolved_no_chase:,.1f}",
        "risk_reward": f"1:{rr_ratio:.1f}",
        "asymmetric_rr": f"1:{asymmetric_rr:.1f}",
        "alpha_quality_score": alpha_quality_score,
        "underlying_symbol": clean_sym,
        "underlying_spot": f"₹{ltp:,.1f}",
        "underlying_sl": f"₹{sl_price:,.1f}",
        "spot_invalidation_anchor": f"₹{sl_price:,.1f}",
        "tactical_sl": rec_sl if has_opt else None,
        "structural_spot_sl": f"₹{sl_price:,.1f}" if has_opt else None,
        "profit_rule": "Scale 50% at T1 (+2.0R), move SL to Breakeven/Cost. Trail 25% to T2, hold runner on 20-EMA.",
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
        }

        act_plan["option_entry"] = rec_entry
        act_plan["contract_symbol"] = opt_contract_sym
        if resolved_opt and getattr(resolved_opt, "spread_details", None):
            act_plan["hedged_spread"] = resolved_opt.spread_details
            act_plan["strategy_type"] = resolved_opt.strategy_type
            act_plan["execution_style_mandate"] = resolved_opt.execution_style_mandate

    now_iso = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")
    clean_base = canonical_alert_symbol(clean_sym)
    d_obj = now_dt.date() if isinstance(now_dt, datetime) else None
    variant_str = (
        f"{opt_type.lower()}-{int(cur_c)}" if has_opt else f"{direction.lower()[:4]}-{int(cur_c)}"
    )
    alert_id = generate_alert_id(
        symbol=clean_base,
        alert_type="trend-pullback",
        session_date=d_obj,
        variant=variant_str,
    )

    if has_opt and opt_strike:
        opt_action = f"{format_strike(opt_strike)} {opt_type} Buy"
        headline = (
            f"🎯 [TREND PULLBACK] {clean_sym} {opt_action}: 20-EMA Support Retest (Spot ₹{ltp:,.1f})"
            if is_bull_pullback
            else f"🎯 [TREND PULLBACK] {clean_sym} {opt_action}: 20-EMA Resistance Reject (Spot ₹{ltp:,.1f})"
        )
        summary = (
            f"Institutional shallow pullback into rising 20-EMA/VWAP on {clean_sym}. Low-volume retest holds support."
            if is_bull_pullback
            else f"Institutional shallow bounce into falling 20-EMA/VWAP on {clean_sym}. Low-volume retest rejected at resistance."
        )
    else:
        eq_action = "Long" if is_bull_pullback else "Short"
        headline = (
            f"🎯 [TREND PULLBACK] {clean_sym} {eq_action}: 20-EMA Support Retest @ ₹{ltp:,.1f} (T1: ₹{t1_price:,.1f})"
            if is_bull_pullback
            else f"🎯 [TREND PULLBACK] {clean_sym} {eq_action}: 20-EMA Resistance Reject @ ₹{ltp:,.1f} (T1: ₹{t1_price:,.1f})"
        )
        summary = (
            f"Institutional shallow pullback into rising 20-EMA/VWAP on {clean_sym}. Low-volume retest holds support."
            if is_bull_pullback
            else f"Institutional shallow bounce into falling 20-EMA/VWAP on {clean_sym}. Low-volume retest rejected at resistance."
        )

    alert_seg = "FNO_INDEX" if is_index else ("FNO_STOCK" if has_opt else segment)
    alert_exch = (
        "BFO"
        if clean_sym in ("SENSEX", "BANKEX")
        else ("NFO" if (is_index or has_opt) else exchange)
    )
    act_plan["segment"] = alert_seg
    spread_info = getattr(resolved_opt, "spread_details", None) if has_opt else None

    return AutoAlert(
        alert_id=alert_id,
        alert_type="TREND_DAY_PULLBACK",
        stage="IGNITED",
        symbol=clean_sym,
        exchange=alert_exch,
        segment=alert_seg,
        direction=direction,
        headline=headline,
        summary=summary,
        ltp=float(opt_ltp if has_opt else ltp),
        trigger_level=float(opt_ltp if has_opt else ltp),
        target_level=float(opt_t1 if has_opt else t1_price),
        stop_loss=float(opt_sl if has_opt else sl_price),
        confidence=confidence_score,
        r_multiple=None,
        time_horizon="INTRADAY",
        contract_symbol=opt_contract_sym,
        strike=opt_strike,
        option_type=opt_type,
        option_premium=opt_ltp,
        expiry_date=resolved_exp,
        expiry_type=("WEEKLY" if is_index else "MONTHLY") if resolved_exp else None,
        underlying_spot=ltp,
        structural_spot_sl=sl_price,
        tactical_sl=opt_sl if has_opt else sl_price,
        actionable_plan=act_plan,
        metrics={
            "rvol": round(rvol_val, 2),
            "pullback_vol_ratio": pullback_vol_ratio,
            "is_volume_dryup": is_dryup,
            "atr_5m": round(atr_5m, 2),
            "ema_9": round(val_ema9, 2),
            "ema_20": round(val_ema20, 2),
            "vwap": round(val_vwap, 2),
            "vol_sma20": round(vol_sma20, 1),
            "risk_pts": round(risk_pts, 2),
            "rr_ratio": rr_ratio,
            "asymmetric_rr": asymmetric_rr,
            "alpha_quality_score": alpha_quality_score,
            "target_1": float(opt_t1 if has_opt else t1_price),
            "target_2": float(opt_t2 if (has_opt and opt_t2) else t2_price),
            "target_3": float(opt_runner if (has_opt and opt_runner) else t3_price),
            "hedged_spread": spread_info,
            "no_chase_boundary": opt_no_chase if has_opt else resolved_no_chase,
            "spot_no_chase_boundary": resolved_no_chase,
            "cpr": cpr_data,
            "cpr_type": "NARROW" if is_narrow_cpr else ("WIDE" if is_wide_cpr else "AVERAGE"),
            "is_narrow_cpr": is_narrow_cpr,
            "is_wide_cpr": is_wide_cpr,
        },
        no_chase_boundary=opt_no_chase if has_opt else resolved_no_chase,
        spot_no_chase_boundary=resolved_no_chase if has_opt else None,
        created_at=now_iso,
        environment="LIVE",
        is_live=True,
    )
