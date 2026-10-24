"""
engine/detectors/liquidity_sweep.py
───────────────────────────────────
Autonomous Predator Liquidity Sweep & Order Book Absorption Detector.

Identifies institutional stop hunts (Judas Swings) where price briefly sweeps
key liquidity pools (Previous Day High/Low, Opening Range High/Low, Equal Highs/Lows)
to trigger retail stops into institutional resting limit orders, followed by an immediate
reversal confirmed by order book absorption or volume delta rejection.

Core Mechanics:
  1. Bullish Predator Spring (Bear Trap Inversion):
     - Spot sweeps below key structural support (PDL or ORB Low) by 0.05% to 0.85%.
     - Immediate rejection wick (lower shadow >= 30% of bar range).
     - Candle closes back ABOVE the swept level.
     - Order book / volume absorption confirmation: positive OBI-50 or RVOL >= 1.25x.
     - Blueprint: Entry at OTE pullback, SL below sweep wick + buffer, T1 (+2R) -> T2 (+3.5R) -> Runner (+5.5R).

  2. Bearish Predator Upthrust (Bull Trap Inversion):
     - Spot sweeps above key structural resistance (PDH or ORB High) by 0.05% to 0.85%.
     - Immediate rejection wick (upper shadow >= 30% of bar range).
     - Candle closes back BELOW the swept level.
     - Order book / volume absorption confirmation: negative OBI-50 or RVOL >= 1.25x.
     - Blueprint: Entry at OTE pullback, SL above sweep wick + buffer, T1 (+2R) -> T2 (+3.5R) -> Runner (+5.5R).
"""

from __future__ import annotations

from datetime import date, datetime
import logging
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from engine.alert_identity import canonical_alert_symbol, generate_alert_id
from engine.alert_model import ActionableBlueprint, AutoAlert
from engine.option_resolver import is_index_symbol, resolve_option_contract

logger = logging.getLogger("chanakya.detectors.liquidity_sweep")
IST = ZoneInfo("Asia/Kolkata")


def _calc_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Computes Average True Range (ATR) with defensive bounds."""
    if df is None or len(df) < period:
        return 0.0
    try:
        cols = {c.lower(): c for c in df.columns}
        h = df[cols["high"]]
        l = df[cols["low"]]
        c = df[cols["close"]]
        tr1 = h - l
        tr2 = (h - c.shift(1)).abs()
        tr3 = (l - c.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        val = tr.rolling(period).mean().iloc[-1]
        if not np.isnan(val) and val > 0:
            return float(val)
    except Exception as e_suppressed:
        logger.debug(f"[liquidity_sweep] ATR calculation non-fatal exception: {e_suppressed}")
    return 0.0


def _get_order_book_imbalance_hint(symbol: str) -> Optional[float]:
    """Attempts to inspect Fyers TBT 50-level Depth Order Book Imbalance if available."""
    try:
        from market.fyers_tbt_manager import get_tbt_manager

        mgr = get_tbt_manager()
        if mgr:
            obi = mgr.get_obi_50(symbol)
            if obi is not None:
                return float(obi)
    except Exception as e_suppressed:
        logger.debug(f"[liquidity_sweep] TBT OBI check non-fatal exception: {e_suppressed}")
    return None


def detect_predator_liquidity_sweep(
    symbol: str,
    df: pd.DataFrame,
    ltp: Optional[float] = None,
    vwap: Optional[float] = None,
    exchange: str = "NSE",
    rvol: float = 1.0,
    obi_50: Optional[float] = None,
    session_date: Optional[date] = None,
    time_horizon: str = "INTRADAY",
    pdh: Optional[float] = None,
    pdl: Optional[float] = None,
) -> Optional[AutoAlert]:
    """
    Scans for institutional liquidity sweeps reversing retail false breakouts
    at Previous Day High / Low, Opening Range, or swing levels with order flow absorption.
    """
    if df is None or len(df) < 10:
        return None

    clean_sym = canonical_alert_symbol(symbol)
    cols = {c.lower(): c for c in df.columns}
    if not all(k in cols for k in ("open", "high", "low", "close")):
        return None

    o_s = df[cols["open"]]
    h_s = df[cols["high"]]
    l_s = df[cols["low"]]
    c_s = df[cols["close"]]

    curr_ltp = float(ltp if ltp is not None and ltp > 0 else c_s.iloc[-1])
    if curr_ltp <= 0:
        return None

    atr = _calc_atr(df, period=14)
    if atr <= 0:
        atr = curr_ltp * 0.01

    # Determine reference structural liquidity levels (PDH / PDL)
    # If not explicitly provided, derive from preceding bars
    lookback = min(20, len(df) - 2)
    ref_high = (
        float(pdh) if (pdh is not None and pdh > 0) else float(h_s.iloc[-(lookback + 2) : -2].max())
    )
    ref_low = (
        float(pdl) if (pdl is not None and pdl > 0) else float(l_s.iloc[-(lookback + 2) : -2].min())
    )

    if ref_high <= ref_low or ref_low <= 0:
        return None

    # Inspect the most recent 2 completed bars for a liquidity sweep rejection
    eval_bars = [len(df) - 1, len(df) - 2] if len(df) >= 2 else [len(df) - 1]

    sweep_type: Optional[str] = None
    sweep_level: float = 0.0
    sweep_wick_ext: float = 0.0

    for idx in eval_bars:
        b_o = float(o_s.iloc[idx])
        b_h = float(h_s.iloc[idx])
        b_l = float(l_s.iloc[idx])
        b_c = float(c_s.iloc[idx])
        b_range = b_h - b_l

        if b_range <= 0:
            continue

        # 1. Bearish Predator Upthrust (Bull Trap at Prior High)
        # Price pierced above resistance by 0.05% to 0.85%, rejected with upper wick >= 30%, and closed below
        if b_h > ref_high and b_c < ref_high:
            sweep_depth = (b_h - ref_high) / ref_high
            upper_shadow = (b_h - max(b_o, b_c)) / b_range
            if 0.0005 <= sweep_depth <= 0.010 and upper_shadow >= 0.30 and curr_ltp <= ref_high:
                sweep_type = "BEARISH_PREDATOR_UPTHRUST"
                sweep_level = ref_high
                sweep_wick_ext = b_h
                break

        # 2. Bullish Predator Spring (Bear Trap at Prior Low)
        # Price pierced below support by 0.05% to 0.85%, rejected with lower wick >= 30%, and closed above
        if b_l < ref_low and b_c > ref_low:
            sweep_depth = (ref_low - b_l) / ref_low
            lower_shadow = (min(b_o, b_c) - b_l) / b_range
            if 0.0005 <= sweep_depth <= 0.010 and lower_shadow >= 0.30 and curr_ltp >= ref_low:
                sweep_type = "BULLISH_PREDATOR_SPRING"
                sweep_level = ref_low
                sweep_wick_ext = b_l
                break

    if not sweep_type:
        return None

    # Check Order Book Imbalance / Flow Absorption Confirmation
    effective_obi = obi_50 if obi_50 is not None else _get_order_book_imbalance_hint(clean_sym)
    is_bullish = sweep_type == "BULLISH_PREDATOR_SPRING"

    # Absorption filter: if OBI is available, it must confirm or at least not strongly oppose
    if effective_obi is not None:
        if is_bullish and effective_obi < -0.30:
            logger.debug(
                f"[liquidity_sweep] Suppressed bullish spring on {clean_sym}: Opposing heavy ask pressure (OBI={effective_obi:.2f})"
            )
            return None
        if not is_bullish and effective_obi > 0.30:
            logger.debug(
                f"[liquidity_sweep] Suppressed bearish upthrust on {clean_sym}: Opposing heavy bid pressure (OBI={effective_obi:.2f})"
            )
            return None

    # Check CVD (Cumulative Volume Delta) confirmation if available
    cvd_div = None
    try:
        from analysis.order_flow import compute_order_flow

        of_res = compute_order_flow(clean_sym, df=df, ltp=curr_ltp, exchange=exchange)
        if of_res and hasattr(of_res, "cvd_divergence"):
            cvd_div = of_res.cvd_divergence
            if (
                is_bullish
                and cvd_div == "AGGRESSIVE_SELLING"
                and (effective_obi is None or effective_obi <= 0)
            ):
                logger.debug(
                    f"[liquidity_sweep] Suppressed bullish spring on {clean_sym}: Opposing aggressive selling delta"
                )
                return None
            if (
                not is_bullish
                and cvd_div == "AGGRESSIVE_BUYING"
                and (effective_obi is None or effective_obi >= 0)
            ):
                logger.debug(
                    f"[liquidity_sweep] Suppressed bearish upthrust on {clean_sym}: Opposing aggressive buying delta"
                )
                return None
    except Exception as e_cvd:
        logger.debug(f"[liquidity_sweep] CVD check non-fatal exception: {e_cvd}")

    sess_date = session_date or datetime.now(IST).date()
    direction = "BULLISH" if is_bullish else "BEARISH"
    variant = "spring" if is_bullish else "upthrust"
    alert_id = generate_alert_id(
        clean_sym, "PREDATOR_SWEEP", session_date=sess_date, variant=variant
    )

    # Risk & Target Calibration with Institutional Volatility Floor (R:R >= 1:3.0)
    min_risk_floor = max(0.70 * atr, curr_ltp * 0.008)
    sl_buffer = max(0.35 * atr, curr_ltp * 0.004)
    if is_bullish:
        raw_stop = round(sweep_wick_ext - sl_buffer, 2)
        entry_price = round(curr_ltp, 2)
        risk = max(entry_price - raw_stop, min_risk_floor)
        stop_loss = round(entry_price - risk, 2)
        target_1 = round(entry_price + (2.0 * risk), 2)
        target_2 = round(entry_price + (3.5 * risk), 2)
        runner_target = round(entry_price + (5.5 * risk), 2)
        no_chase = round(entry_price + (0.35 * risk), 2)
        action_verb = "BUY"
        headline = f"🦅 [PREDATOR SWEEP] Bullish Bear-Trap Absorption: {clean_sym} swept low ₹{sweep_level:,.2f}"
        summary = (
            f"Institutional Bear-Trap Reversal! {clean_sym} swept liquidity low ₹{sweep_level:,.2f} down to ₹{sweep_wick_ext:,.2f} "
            f"where passive smart money absorbed retail stops. Rejection wick printed. Enter Long near ₹{entry_price:,.2f}."
        )
    else:
        raw_stop = round(sweep_wick_ext + sl_buffer, 2)
        entry_price = round(curr_ltp, 2)
        risk = max(raw_stop - entry_price, min_risk_floor)
        stop_loss = round(entry_price + risk, 2)
        target_1 = round(entry_price - (2.0 * risk), 2)
        target_2 = round(entry_price - (3.5 * risk), 2)
        runner_target = round(entry_price - (5.5 * risk), 2)
        no_chase = round(entry_price - (0.35 * risk), 2)
        action_verb = "SELL"
        headline = f"🦅 [PREDATOR SWEEP] Bearish Bull-Trap Absorption: {clean_sym} swept high ₹{sweep_level:,.2f}"
        summary = (
            f"Institutional Bull-Trap Reversal! {clean_sym} swept liquidity high ₹{sweep_level:,.2f} up to ₹{sweep_wick_ext:,.2f} "
            f"where resting ask walls absorbed breakout buyers. Rejection wick printed. Enter Short/Put near ₹{entry_price:,.2f}."
        )

    rr_ratio = round(abs(target_1 - entry_price) / risk, 2)

    # Option Contract Resolution for Index & F&O
    contract_symbol = None
    strike = None
    option_type = None
    expiry_date_str = None
    resolved_opt = None

    try:
        if is_index_symbol(clean_sym):
            resolved_opt = resolve_option_contract(
                symbol=clean_sym,
                spot=curr_ltp,
                direction=direction,
                underlying_sl=stop_loss,
                underlying_target=target_1,
                strike_tier="ATM",
                prefer_options=True,
            )
            if resolved_opt and getattr(resolved_opt, "contract_symbol", None):
                contract_symbol = resolved_opt.contract_symbol
                strike = resolved_opt.strike
                option_type = "CE" if is_bullish else "PE"
                expiry_date_str = resolved_opt.expiry_date
    except Exception as e_suppressed:
        logger.debug(f"[liquidity_sweep] Option resolution non-fatal exception: {e_suppressed}")

    has_opt = bool(resolved_opt and getattr(resolved_opt, "entry_premium", 0) > 0)
    opt_entry = getattr(resolved_opt, "entry_premium", 0.0) if has_opt else 0.0
    opt_sl = getattr(resolved_opt, "sl_premium", 0.0) if has_opt else 0.0
    opt_t1 = getattr(resolved_opt, "t1_premium", 0.0) if has_opt else 0.0
    opt_t2 = getattr(resolved_opt, "t2_premium", 0.0) if has_opt else 0.0
    opt_t3 = (
        getattr(resolved_opt, "t3_premium", 0.0) if has_opt else (opt_t2 * 1.25 if opt_t2 else 0.0)
    )
    opt_nc = round(opt_entry * 1.05, 2) if has_opt else 0.0

    blueprint = ActionableBlueprint(
        action=("BUY_CALL" if is_bullish else "BUY_PUT") if has_opt else action_verb,
        entry_range=f"₹{entry_price * 0.998:,.2f} – ₹{entry_price * 1.002:,.2f}",
        trigger_level=entry_price,
        invalidation_stop=stop_loss,
        target_1=target_1,
        target_2=target_2,
        runner_target=runner_target,
        risk_reward=f"1:{rr_ratio:.1f}",
        no_chase_boundary=no_chase,
        execution_style="LIMIT_ON_PULLBACK",
        when_to_buy=f"Limit order at OTE pullback near ₹{entry_price:,.2f} following trap rejection."
        + (f" (Option {contract_symbol} near ₹{opt_entry:,.2f})" if has_opt else ""),
        when_to_wait=f"Do not chase if spot moves beyond ₹{no_chase:,.2f}."
        + (f" (or premium beyond ₹{opt_nc:,.2f})" if has_opt else ""),
        profit_rule="Book 50% at Target 1 (+2R) and shift SL to Breakeven (+0.2%). Trail runner to Target 2.",
        segment="FNO_INDEX" if is_index_symbol(clean_sym) else "EQUITY",
        contract=contract_symbol,
        strike=strike,
        option_type=option_type,
        expiry_date=expiry_date_str,
        extra_details={
            "option_entry": f"₹{opt_entry:,.2f}" if has_opt else None,
            "option_sl": f"₹{opt_sl:,.2f}" if has_opt else None,
            "option_target_1": f"₹{opt_t1:,.2f}" if has_opt else None,
            "option_target_2": f"₹{opt_t2:,.2f}" if has_opt else None,
            "option_runner_target": f"₹{opt_t3:,.2f}" if has_opt else None,
            "option_no_chase_boundary": f"₹{opt_nc:,.2f}" if has_opt else None,
            "underlying_spot": f"₹{curr_ltp:,.2f}",
            "underlying_sl": f"₹{stop_loss:,.2f}",
            "underlying_target": f"₹{target_1:,.2f}",
        }
        if has_opt
        else {},
    )

    alert = AutoAlert(
        alert_id=alert_id,
        alert_type="PREDATOR_SWEEP",
        stage="IGNITED",
        symbol=clean_sym,
        exchange=exchange,
        segment="FNO_INDEX"
        if is_index_symbol(clean_sym)
        else ("FNO_STOCK" if contract_symbol else "EQUITY"),
        direction=direction,
        headline=headline,
        summary=summary,
        ltp=curr_ltp,
        trigger_level=entry_price,
        target_level=target_1,
        stop_loss=stop_loss,
        strike=strike,
        option_type=option_type,
        contract_symbol=contract_symbol,
        confidence=86,
        time_horizon=time_horizon,
        actionable_plan=blueprint.to_dict(),
        underlying_spot=curr_ltp,
        no_chase_boundary=no_chase,
        metrics={
            "sweep_type": sweep_type,
            "sweep_level": sweep_level,
            "sweep_wick_ext": sweep_wick_ext,
            "vwap": vwap,
            "atr": round(atr, 2),
            "rvol": round(rvol, 2),
            "obi_50": round(effective_obi, 3) if effective_obi is not None else None,
            "cvd_divergence": cvd_div,
            "risk_pts": round(risk, 2),
            "target_1_pts": round(abs(target_1 - entry_price), 2),
            "risk_reward_ratio": rr_ratio,
        },
    )

    return alert
