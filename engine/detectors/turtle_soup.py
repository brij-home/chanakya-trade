"""
engine/detectors/turtle_soup.py
───────────────────────────────
Autonomous Turtle Soup & Institutional Liquidity Sweep Reversal Detector.

Identifies failed breakouts / false breakdowns at key structural boundaries
(Previous Day High / Low, 20-bar Swing High / Low) where smart money engineers
stop-hunts to trap retail momentum traders. Inverts the retail trap into an
institutional asymmetric reversal setup (R:R >= 1:3.0).

Signal Mechanics:
  1. Bullish Spring (Bear Trap Inversion):
     - Spot pierces below key support (PDL or Swing Low) by <= 0.75%.
     - Immediate rejection wick (lower shadow >= 35% of bar range).
     - Candle closes back ABOVE the swept level and holds.
     - Invalidation SL = just below sweep wick floor with 0.15x ATR buffer.
     - Targets: Equilibrium / VWAP (T1, +2R) -> Prior High (T2, +3.5R).
  2. Bearish Upthrust (Bull Trap Inversion):
     - Spot pierces above key resistance (PDH or Swing High) by <= 0.75%.
     - Immediate rejection wick (upper shadow >= 35% of bar range).
     - Candle closes back BELOW the swept level and holds.
     - Invalidation SL = just above sweep wick ceiling with 0.15x ATR buffer.
     - Targets: Equilibrium / VWAP (T1, +2R) -> Prior Low (T2, +3.5R).
"""

from __future__ import annotations

import logging
from datetime import datetime, date
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from engine.alert_identity import canonical_alert_symbol, generate_alert_id
from engine.alert_model import ActionableBlueprint, AutoAlert
from engine.option_resolver import resolve_option_contract, is_index_symbol

logger = logging.getLogger("chanakya.detectors.turtle_soup")
IST = ZoneInfo("Asia/Kolkata")


def _calc_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Computes Average True Range (ATR) with fallback."""
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
    except Exception:
        pass
    return 0.0


def detect_turtle_soup_sweep(
    symbol: str,
    df: pd.DataFrame,
    ltp: Optional[float] = None,
    vwap: Optional[float] = None,
    exchange: str = "NSE",
    rvol: float = 1.0,
    session_date: Optional[date] = None,
    time_horizon: str = "INTRADAY",
) -> Optional[AutoAlert]:
    """
    Scans for institutional liquidity sweep rejections (Turtle Soup)
    reversing false breakouts at Previous Day High / Low or swing pivots.
    """
    if df is None or len(df) < 15:
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
        atr = curr_ltp * 0.012

    # Lookback boundary: swing high/low of preceding 20 bars (excluding the most recent 2 bars)
    lookback = min(20, len(df) - 2)
    prior_high = float(h_s.iloc[-(lookback + 2) : -2].max())
    prior_low = float(l_s.iloc[-(lookback + 2) : -2].min())

    if prior_high <= prior_low or prior_low <= 0:
        return None

    # Inspect the last 2 completed bars for a liquidity sweep rejection
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

        # 1. Bearish Upthrust (Bull Trap at Prior High)
        # High swept prior high, but closed back below, with top wick >= 35%
        if b_h > prior_high and b_c < prior_high:
            sweep_depth = (b_h - prior_high) / prior_high
            upper_shadow = (b_h - max(b_o, b_c)) / b_range
            if sweep_depth <= 0.0075 and upper_shadow >= 0.35 and curr_ltp <= prior_high:
                sweep_type = "BEARISH_UPTHRUST"
                sweep_level = prior_high
                sweep_wick_ext = b_h
                break

        # 2. Bullish Spring (Bear Trap at Prior Low)
        # Low swept prior low, but closed back above, with bottom wick >= 35%
        if b_l < prior_low and b_c > prior_low:
            sweep_depth = (prior_low - b_l) / prior_low
            lower_shadow = (min(b_o, b_c) - b_l) / b_range
            if sweep_depth <= 0.0075 and lower_shadow >= 0.35 and curr_ltp >= prior_low:
                sweep_type = "BULLISH_SPRING"
                sweep_level = prior_low
                sweep_wick_ext = b_l
                break

    if not sweep_type:
        return None

    sess_date = session_date or datetime.now(IST).date()
    is_bullish = sweep_type == "BULLISH_SPRING"
    direction = "BULLISH" if is_bullish else "BEARISH"
    variant = "spring" if is_bullish else "upthrust"
    alert_id = generate_alert_id(
        clean_sym, "TURTLE_SOUP_SWEEP", session_date=sess_date, variant=variant
    )

    # Ballistic Level Calibration
    # Add 0.15*ATR buffer beyond sweep wick
    sl_buffer = max(0.15 * atr, curr_ltp * 0.002)
    if is_bullish:
        stop_loss = round(sweep_wick_ext - sl_buffer, 2)
        entry_price = round(curr_ltp, 2)
        risk = max(entry_price - stop_loss, curr_ltp * 0.003)
        target_1 = round(entry_price + (2.0 * risk), 2)
        target_2 = round(entry_price + (3.5 * risk), 2)
        runner_target = round(entry_price + (5.5 * risk), 2)
        no_chase = round(entry_price + (0.35 * risk), 2)
        action_verb = "BUY"
        headline = (
            f"🐢 [TURTLE SOUP] Bullish Spring Reversal: {clean_sym} swept low ₹{sweep_level:,.2f}"
        )
        summary = (
            f"Bear Trap Neutralized! {clean_sym} swept swing low ₹{sweep_level:,.2f} down to ₹{sweep_wick_ext:,.2f} "
            f"before printing an aggressive rejection spring. Smart money absorbed selling. Enter Long near ₹{entry_price:,.2f}."
        )
    else:
        stop_loss = round(sweep_wick_ext + sl_buffer, 2)
        entry_price = round(curr_ltp, 2)
        risk = max(stop_loss - entry_price, curr_ltp * 0.003)
        target_1 = round(entry_price - (2.0 * risk), 2)
        target_2 = round(entry_price - (3.5 * risk), 2)
        runner_target = round(entry_price - (5.5 * risk), 2)
        no_chase = round(entry_price - (0.35 * risk), 2)
        action_verb = "SELL"
        headline = f"🐢 [TURTLE SOUP] Bearish Upthrust Reversal: {clean_sym} swept high ₹{sweep_level:,.2f}"
        summary = (
            f"Bull Trap Neutralized! {clean_sym} swept swing high ₹{sweep_level:,.2f} up to ₹{sweep_wick_ext:,.2f} "
            f"before printing an aggressive rejection upthrust. Breakout traders trapped. Enter Short/Put near ₹{entry_price:,.2f}."
        )

    rr_ratio = round(abs(target_1 - entry_price) / risk, 2)

    # Option Contract Resolution for Index & F&O
    contract_symbol = None
    strike = None
    option_type = None
    expiry_date_str = None

    try:
        from engine.position_sizer import is_fno_symbol

        if is_index_symbol(clean_sym) or is_fno_symbol(clean_sym):
            opt_type_req = "CE" if is_bullish else "PE"
            resolved = resolve_option_contract(
                symbol=clean_sym,
                spot_price=curr_ltp,
                option_type=opt_type_req,
                moneyness="ATM",
            )
            if resolved:
                contract_symbol = getattr(resolved, "contract_symbol", None)
                strike = getattr(resolved, "strike", None)
                option_type = opt_type_req
                expiry_date_str = getattr(resolved, "expiry_date", None)
    except Exception:
        pass

    blueprint = ActionableBlueprint(
        action=action_verb if not option_type else ("BUY_CALL" if is_bullish else "BUY_PUT"),
        entry_range=f"₹{entry_price * 0.998:,.2f} – ₹{entry_price * 1.002:,.2f}",
        trigger_level=entry_price,
        invalidation_stop=stop_loss,
        target_1=target_1,
        target_2=target_2,
        runner_target=runner_target,
        risk_reward=f"1:{rr_ratio:.1f}",
        no_chase_boundary=no_chase,
        execution_style="LIMIT_ON_PULLBACK",
        when_to_buy=f"Limit order at OTE pullback near ₹{entry_price:,.2f} after structural trap rejection.",
        when_to_wait=f"Do not chase if spot moves beyond ₹{no_chase:,.2f}.",
        profit_rule="Book 50% at Target 1 (+2R) and shift SL to Breakeven (+0.2%). Trail runner to Target 2.",
        segment="INDEX" if is_index_symbol(clean_sym) else "EQUITY",
        contract=contract_symbol,
        strike=strike,
        option_type=option_type,
        expiry_date=expiry_date_str,
    )

    # Horizon & ETA Calibration
    th_upper = (time_horizon or "INTRADAY").upper()
    if th_upper in ("SCALP", "FAST_SCALP", "INTRADAY_SCALP_ONLY"):
        horizon_val = "SCALP"
        eta_desc = "15–45m Scalp"
        style_val = "SCALP_REVERSAL"
    elif th_upper in ("SWING_SHORT", "SWING"):
        horizon_val = "SWING_SHORT"
        eta_desc = "2–5 Trading Days"
        style_val = "SWING_REVERSAL"
    elif th_upper == "SWING_MID":
        horizon_val = "SWING_MID"
        eta_desc = "1–4 Weeks"
        style_val = "SWING_REVERSAL"
    else:
        horizon_val = "INTRADAY"
        eta_desc = "Today 15:15 IST" if exchange != "MCX" else "Today 23:15 IST"
        style_val = "INTRADAY_REVERSAL"

    alert = AutoAlert(
        alert_id=alert_id,
        alert_type="TURTLE_SOUP_SWEEP",
        stage="IGNITED",
        symbol=f"{exchange}:{clean_sym}",
        exchange=exchange,
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
        confidence=82,
        time_horizon=horizon_val,
        eta_label=eta_desc,
        setup_style=style_val,
        entry_type="LIMIT_ON_PULLBACK",
        no_chase_boundary=no_chase,
        actionable_plan=blueprint.to_dict(),
        metrics={
            "sweep_type": sweep_type,
            "swept_level": sweep_level,
            "sweep_wick_ext": sweep_wick_ext,
            "atr": atr,
            "rvol": rvol,
            "rr_ratio": rr_ratio,
            "vwap": vwap,
        },
    )

    return alert
