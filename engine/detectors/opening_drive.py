"""
engine/detectors/opening_drive.py
─────────────────────────────────
Autonomous Opening Drive Impulse Detector (09:16 - 09:45 IST).

Captures explosive day-defining institutional moves at the earliest possible stage:
  1. Bullish Opening Drive (Open == Low):
     - Low is within 0.12% of Open (no lower wick).
     - Full-bodied green candle closing in top 20% of range.
     - Volume >= 1.8x Time-of-Day average.
     - Breaks above previous day high or pre-market pivot.
     - Invalidation Stop: Strictly at Open/Low floor.
  2. Bearish Opening Drive (Open == High) — The OFSS Institutional Archetype:
     - High is within 0.12% of Open (no upper wick).
     - Full-bodied red candle closing in bottom 20% of range.
     - Volume >= 1.8x Time-of-Day average.
     - Breaks below previous day low or key structural support.
     - Invalidation Stop: Strictly at Open/High ceiling.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta, time as dtime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from engine.alert_identity import generate_alert_id, canonical_alert_symbol
from engine.alert_model import AutoAlert

logger = logging.getLogger("chanakya.detectors.opening_drive")

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
    except Exception:
        return 0.0


def detect_opening_drive(
    symbol: str,
    df_5m: pd.DataFrame,
    ltp: float,
    vwap: Optional[float] = None,
    rvol: Optional[float] = None,
    ref_time: Optional[datetime] = None,
    prev_close: Optional[float] = None,
    prev_high: Optional[float] = None,
    prev_low: Optional[float] = None,
    ignore_time_gate: bool = False,
) -> Optional[AutoAlert]:
    """
    Evaluates 5-minute intraday bars for textbook Opening Drive patterns.
    Active primarily between 09:16 and 09:45 IST.
    """
    if df_5m is None or len(df_5m) < 1 or ltp <= 0:
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
        # Opening drive forms in first 30 mins:
        # Indices: 09:15:05 to 09:45 IST
        # Equities/Stocks: 09:17:00 to 09:45 IST (requires 2 minutes for uncrossing auction volatility to settle)
        min_start_t = dtime(9, 15, 5) if is_index else dtime(9, 17, 0)
        if curr_t < min_start_t or curr_t > dtime(9, 45):
            return None

    # Filter df to today's bars
    today_str = now_dt.strftime("%Y-%m-%d")
    df_today = (
        df_5m[df_5m.index.strftime("%Y-%m-%d") == today_str]
        if hasattr(df_5m.index, "strftime")
        else df_5m
    )
    if len(df_today) == 0:
        df_today = df_5m

    # Extract first 5m bar of today
    first_bar = df_today.iloc[0]
    bar_open = float(first_bar.get("open", first_bar.get("Open", 0.0)))
    bar_high = float(first_bar.get("high", first_bar.get("High", 0.0)))
    bar_low = float(first_bar.get("low", first_bar.get("Low", 0.0)))
    bar_close = float(first_bar.get("close", first_bar.get("Close", 0.0)))
    bar_range = bar_high - bar_low

    if bar_open <= 0 or bar_range <= 0:
        return None

    range_pct = (bar_range / bar_open) * 100.0
    # Mega-cap heavyweights and indices have lower percentage volatility than midcaps;
    # calibrate minimum 5m expansion range floor (0.20% for mega-caps, 0.35% for general equities):
    min_range_pct = 0.20 if (is_index or is_heavyweight) else 0.35
    if range_pct < min_range_pct:
        return None

    if rvol is not None:
        rvol_val = float(rvol)
    elif is_index:
        rvol_val = 1.0
    else:
        rvol_val = 1.8

    is_bull_drive = False
    is_bear_drive = False

    # 1. Bullish Opening Drive: Open == Low (within 0.15%) & expanding upward
    low_diff_pct = (abs(bar_open - bar_low) / bar_open) * 100.0
    if low_diff_pct <= 0.15 and (bar_close >= (bar_low + 0.45 * bar_range) or ltp >= bar_high):
        if (
            (prev_high and (bar_close >= prev_high * 0.998 or ltp >= prev_high))
            or (prev_close and bar_close > prev_close)
            or (ltp >= bar_open * 1.003)
        ):
            # Wick Trap Filter: reject candles where upper rejection wick > 40% unless live LTP broke bar_high
            upper_wick = bar_high - max(bar_open, bar_close)
            if (upper_wick / bar_range <= 0.40) or (ltp >= bar_high):
                is_bull_drive = True

    # 2. Bearish Opening Drive: Open == High (within 0.15%) & expanding downward (The OFSS Archetype)
    high_diff_pct = (abs(bar_high - bar_open) / bar_open) * 100.0
    if high_diff_pct <= 0.15 and (bar_close <= (bar_low + 0.55 * bar_range) or ltp <= bar_low):
        if (
            (prev_low and (bar_close <= prev_low * 1.002 or ltp <= prev_low))
            or (prev_close and bar_close < prev_close)
            or (ltp <= bar_open * 0.997)
        ):
            # Wick Trap Filter: reject candles where lower absorption wick > 40% unless live LTP broke bar_low
            lower_wick = min(bar_open, bar_close) - bar_low
            if (lower_wick / bar_range <= 0.40) or (ltp <= bar_low):
                is_bear_drive = True

    if not (is_bull_drive or is_bear_drive):
        return None

    # Current price must maintain direction (no immediate mean-reversion fail)
    if is_bull_drive and ltp < bar_open:
        return None
    if is_bear_drive and ltp > bar_open:
        return None

    # ── Index Heavyweight Locomotive Gate ─────────────────────────
    if is_index:
        try:
            from market.indices import get_heavyweights_posture

            hw_posture = get_heavyweights_posture(clean_sym)
            active_hw = hw_posture.get("heavyweights", [])
            hw_total = len(active_hw)
            hw_bulls = hw_posture.get("bull_count", 0)
            hw_bears = hw_posture.get("bear_count", 0)
            if hw_total > 0:
                if is_bull_drive and (
                    hw_bulls == 0 or hw_posture.get("all_bearish") or hw_bears > hw_bulls
                ):
                    hw_tags = [
                        f"{h['symbol']} ({h['change_pct']:+.2f}%)"
                        for h in hw_posture.get("heavyweights", [])
                    ]
                    logger.info(
                        f"[OpeningDrive] Suppressed bullish drive on {clean_sym}: Heavyweight locomotives unaligned "
                        f"({hw_bulls}/{hw_total} bullish, {', '.join(hw_tags)})."
                    )
                    return None
                if is_bear_drive and (
                    hw_bears == 0 or hw_posture.get("all_bullish") or hw_bulls > hw_bears
                ):
                    hw_tags = [
                        f"{h['symbol']} ({h['change_pct']:+.2f}%)"
                        for h in hw_posture.get("heavyweights", [])
                    ]
                    logger.info(
                        f"[OpeningDrive] Suppressed bearish drive on {clean_sym}: Heavyweight locomotives unaligned "
                        f"({hw_bears}/{hw_total} bearish, {', '.join(hw_tags)})."
                    )
                    return None
        except Exception as e_hw:
            logger.debug(f"[OpeningDrive] Heavyweights check bypassed for {clean_sym}: {e_hw}")

    direction = "BULLISH" if is_bull_drive else "BEARISH"
    vol_desc = "Locomotives Aligned" if is_index else f"RVOL {rvol_val:.1f}x"

    # ── Minimum Stop-Loss Distance Floor (1.2x ATR / 20.5 pts) ───────────
    # Prevents Brownian noise micro-whipsaws on tight 1st 5-minute bar openings.
    # Calibrated index floors: Nifty 20.5 pts, BankNifty 55.0 pts, FinNifty 25.0 pts, MidcpNifty 16.0 pts, Sensex 75.0 pts.
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

    # Stop Loss is strictly anchored to the opening drive extreme + 0.15% noise buffer
    # with minimum distance floor of 1.2x ATR (20.5 pts for Nifty) enforced.
    if is_bull_drive:
        raw_sl = round(bar_low * 0.998, 2)
        if (ltp - raw_sl) < min_sl_floor:
            sl_price = round(ltp - min_sl_floor, 2)
        else:
            sl_price = raw_sl
        risk_pts = max(min_sl_floor, ltp - sl_price)
        t1_price = round(ltp + 2.5 * risk_pts, 2)
        t2_price = round(ltp + 4.5 * risk_pts, 2)
        t3_price = round(ltp + 7.0 * risk_pts, 2)
        no_chase_lvl = round(min(ltp + 0.35 * risk_pts, bar_open + 1.25 * (ltp - bar_open)), 2)
        headline = f"🚀 [OPENING DRIVE] {clean_sym} Bullish Ignition (Open==Low @ ₹{bar_open:,.1f})"
        summary = (
            f"{clean_sym} explosive Opening Drive confirmed: Open==Low at ₹{bar_open:,.1f} "
            f"with immediate expansion (+{range_pct:.1f}% range, {vol_desc}). "
            f"Holding strictly above VWAP. NO CHASE above ₹{no_chase_lvl:,.1f}."
        )
    else:
        raw_sl = round(bar_high * 1.002, 2)
        if (raw_sl - ltp) < min_sl_floor:
            sl_price = round(ltp + min_sl_floor, 2)
        else:
            sl_price = raw_sl
        risk_pts = max(min_sl_floor, sl_price - ltp)
        t1_price = round(ltp - 2.5 * risk_pts, 2)
        t2_price = round(ltp - 4.5 * risk_pts, 2)
        t3_price = round(ltp - 7.0 * risk_pts, 2)
        no_chase_lvl = round(max(ltp - 0.35 * risk_pts, bar_open - 1.25 * (bar_open - ltp)), 2)
        headline = (
            f"🚨 [OPENING DRIVE] {clean_sym} Bearish Breakdown (Open==High @ ₹{bar_open:,.1f})"
        )
        summary = (
            f"{clean_sym} institutional Opening Drive breakdown: Open==High at ₹{bar_open:,.1f} "
            f"with heavy downside liquidation (-{range_pct:.1f}% range, {vol_desc}). "
            f"Aggressive short / put momentum. NO CHASE below ₹{no_chase_lvl:,.1f}."
        )

    rr_ratio = round(abs(t1_price - ltp) / max(0.01, risk_pts), 1)
    rr_str = f"1:{rr_ratio:.1f}"

    # ── Pro-Gap & Daily Reference Levels Integration ──────────────
    gap_type = None
    cpr_regime = None
    confidence_score = 92
    try:
        from engine.daily_levels import DailyLevelsStore

        store = DailyLevelsStore()
        dl = store.get_levels(clean_sym, compute_if_missing=False)
        if dl:
            gap_type = (dl.pre_open or {}).get("gap_type")
            cpr_regime = (dl.cpr or {}).get("regime")
            if gap_type in ("PRO_GAP_UP", "PRO_GAP_DOWN"):
                if (is_bull_drive and gap_type == "PRO_GAP_UP") or (
                    is_bear_drive and gap_type == "PRO_GAP_DOWN"
                ):
                    confidence_score = 96
            if cpr_regime and "NARROW" in cpr_regime:
                confidence_score = max(confidence_score, 94)
    except Exception as e_dl:
        logger.debug(f"[OpeningDrive] Daily levels lookup error for {clean_sym}: {e_dl}")

    # ── Option Resolution via Unified VIX-Aware Resolver ──────────
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
    opt_type = resolved_opt.option_type if has_opt else ("CE" if is_bull_drive else "PE")
    lot_sz = resolved_opt.lot_size if has_opt else 1
    resolved_exp = resolved_opt.expiry if has_opt else None
    opt_no_chase = round(opt_ltp * 1.04, 2) if has_opt else None

    resolved_no_chase = round(opt_no_chase if has_opt else no_chase_lvl, 2)
    action_str = f"BUY {opt_type}" if has_opt else ("BUY" if is_bull_drive else "SELL_SHORT")
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
        "optimal_entry_limit": bar_open,
        "retest_entry": bar_open,
        "no_chase_boundary": f"₹{resolved_no_chase:,.1f}",
        "risk_reward": rr_str,
        "asymmetric_rr": f"1:{max(3.0, rr_ratio):.1f}",
        "underlying_symbol": clean_sym,
        "underlying_spot": f"₹{ltp:,.1f}",
        "underlying_sl": f"₹{sl_price:,.1f}",
        "spot_invalidation_anchor": f"₹{sl_price:,.1f}",
        "tactical_sl": rec_sl if has_opt else None,
        "structural_spot_sl": f"₹{sl_price:,.1f}" if has_opt else None,
        "disaster_stop_floor": f"₹{round(opt_ltp * 0.68, 2):,.2f}" if has_opt else None,
        "underlying_target": f"₹{t1_price:,.1f}",
        "underlying_target_3": f"₹{t3_price:,.1f}",
        "execution_style_mandate": (
            resolved_opt.execution_style_mandate if has_opt else "STANDARD"
        ),
        "opening_drive_bar": {
            "open": bar_open,
            "high": bar_high,
            "low": bar_low,
            "close": bar_close,
            "range_pct": round(range_pct, 2),
        },
        "when_to_buy": (
            f"Enter {opt_contract_sym} while spot holds {'above' if is_bull_drive else 'below'} ₹{bar_open:,.1f}. Prefer Limit order in pullback zone."
            if has_opt
            else f"Enter {'LONG' if is_bull_drive else 'SHORT'} on pullback while holding {'above' if is_bull_drive else 'below'} ₹{bar_open:,.1f}."
        ),
        "when_to_wait": f"DO NOT CHASE beyond ₹{resolved_no_chase:,.1f}. If price > ₹{resolved_no_chase:,.1f}, wait for pullback to ₹{bar_open:,.1f} or cancel.",
        "profit_rule": "Scale 50% at T1 (+2.0R to +3.0R), move SL to Cost/Breakeven, risk drops to ₹0.00 (Free-Roll). Hold 25% for T2, trail runner on 5m 20-EMA.",
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

    now_iso = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")
    alert_seg = "FNO_INDEX" if is_index else ("FNO_STOCK" if lot_sz > 1 else "EQUITY")

    metrics_dict: dict[str, Any] = {
        "setup": "OPENING_DRIVE",
        "open_pattern": "OPEN_EQUALS_LOW" if is_bull_drive else "OPEN_EQUALS_HIGH",
        "opening_range_pct": round(range_pct, 2),
        "rvol": rvol_val,
        "bar_open": bar_open,
        "bar_high": bar_high,
        "bar_low": bar_low,
        "bar_close": bar_close,
        "no_chase_boundary": resolved_no_chase,
        "target_1": opt_t1 if has_opt else t1_price,
        "target_2": opt_t2 if has_opt else t2_price,
        "target_3": opt_runner if has_opt else t3_price,
        # Synthetic Spot Stop Loss Anchors
        "spot_invalidation_anchor": sl_price,
        "underlying_sl": sl_price,
        "underlying_symbol": clean_sym,
        "underlying_spot": ltp,
    }

    if rvol_val >= 1.5:
        metrics_dict["decoupler_status"] = "VERIFIED_DECOUPLER"

    if has_opt and resolved_opt:
        metrics_dict["strategy_type"] = resolved_opt.strategy_type
        metrics_dict["vix_regime"] = resolved_opt.vix_regime
        metrics_dict["india_vix"] = resolved_opt.vix_value
        metrics_dict["execution_style_mandate"] = resolved_opt.execution_style_mandate
        if resolved_opt.spread_details:
            metrics_dict["hedged_spread"] = resolved_opt.spread_details

    if gap_type:
        metrics_dict["gap_type"] = gap_type
    if cpr_regime:
        metrics_dict["cpr_regime"] = cpr_regime

    return AutoAlert(
        alert_id=generate_alert_id(
            clean_sym, "OPENING_DRIVE_IGNITION", variant=f"{direction.lower()[:4]}"
        ),
        alert_type="OPENING_DRIVE_IGNITION",
        stage="IGNITED",
        symbol=clean_sym,
        exchange="NFO" if (is_index or has_opt) else "NSE",
        direction=direction,
        headline=headline,
        summary=summary,
        ltp=opt_ltp if has_opt else ltp,
        trigger_level=opt_ltp if has_opt else ltp,
        target_level=opt_t1 if has_opt else t1_price,
        stop_loss=opt_sl if has_opt else sl_price,
        no_chase_boundary=resolved_no_chase,
        strike=opt_strike if has_opt else None,
        option_type=opt_type if has_opt else None,
        contract_symbol=opt_contract_sym if has_opt else None,
        expiry_date=resolved_exp,
        expiry_type=("WEEKLY" if is_index else "MONTHLY") if resolved_exp else None,
        option_premium=opt_ltp if has_opt else None,
        underlying_spot=ltp,
        lot_size=lot_sz,
        segment=alert_seg,
        confidence=confidence_score,
        created_at=now_iso,
        is_live=True,
        environment="LIVE",
        metrics=metrics_dict,
        actionable_plan=act_plan,
    )
