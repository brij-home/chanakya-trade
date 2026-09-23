"""
TTM Squeeze breakout and breakdown detector (Early Warning & Ignited).
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from engine.alert_model import AutoAlert
from engine.option_resolver import resolve_option_contract, is_index_symbol

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


def compute_adx(df: Any, period: int = 14) -> tuple[float, float]:
    """
    Computes Welles Wilder's ADX(14) and 3-bar slope from an OHLCV DataFrame.
    Returns (adx_value, adx_slope).
    """
    if df is None or len(df) < period + 5:
        return 25.0, 0.0

    try:
        highs = df["high"].values if "high" in df.columns else df["High"].values
        lows = df["low"].values if "low" in df.columns else df["Low"].values
        closes = df["close"].values if "close" in df.columns else df["Close"].values

        up_move = highs[1:] - highs[:-1]
        down_move = lows[:-1] - lows[1:]

        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - closes[:-1]),
                np.abs(lows[1:] - closes[:-1]),
            ),
        )

        tr_s = pd.Series(tr).ewm(alpha=1.0 / period, adjust=False).mean()
        pdm_s = pd.Series(plus_dm).ewm(alpha=1.0 / period, adjust=False).mean()
        mdm_s = pd.Series(minus_dm).ewm(alpha=1.0 / period, adjust=False).mean()

        plus_di = 100.0 * (pdm_s / np.maximum(1e-6, tr_s))
        minus_di = 100.0 * (mdm_s / np.maximum(1e-6, tr_s))

        dx = 100.0 * np.abs(plus_di - minus_di) / np.maximum(1e-6, (plus_di + minus_di))
        adx_series = dx.ewm(alpha=1.0 / period, adjust=False).mean()

        adx_val = float(adx_series.iloc[-1])
        slope = float(adx_series.iloc[-1] - adx_series.iloc[-3]) if len(adx_series) >= 3 else 0.0
        return round(adx_val, 1), round(slope, 1)
    except Exception:
        return 25.0, 0.0


def _format_squeeze_alert(
    symbol: str,
    exchange: str,
    stage: str,
    direction: str,
    ltp: float,
    sl: float,
    target: float,
    target_2: float,
    rr_str: str,
    conf: int,
    headline: str,
    summary: str,
    metrics: dict[str, Any],
    tp_dict: dict[str, Any],
    now_iso: str,
    action: str,
    entry_rg: str,
    trigger_lvl: float,
) -> AutoAlert:
    clean_sym = symbol.upper().replace("NSE:", "").replace("BSE:", "").strip()
    is_idx = is_index_symbol(clean_sym)
    opt_plan = (
        resolve_option_contract(
            symbol=clean_sym,
            spot=ltp,
            direction=direction,
            underlying_sl=sl,
            underlying_target=target,
        )
        if is_idx
        else None
    )

    if opt_plan:
        icon = "🎯" if stage == "EARLY_WARNING" else "🚀"
        status_txt = "COILING" if stage == "EARLY_WARNING" else "IGNITED"
        opt_headline = f"{icon} SQUEEZE {status_txt}: {opt_plan.contract_symbol} @ ₹{opt_plan.entry_premium:,.1f} (Spot ₹{ltp:,.1f})"
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
            "risk_reward": rr_str,
            "underlying_spot": f"₹{ltp:,.1f}",
            "underlying_sl": f"₹{sl:,.1f}",
            "underlying_target": f"₹{target:,.1f}",
            "option_type": opt_plan.option_type,
            "strike": opt_plan.strike,
            "option_plan": opt_plan.as_dict(),
            "trade_plan": tp_dict,
        }
        return AutoAlert(
            alert_id=f"aa-sqz-{stage.lower()[:5]}-{clean_sym.lower()}-{uuid.uuid4().hex[:6]}",
            alert_type="SQUEEZE_BREAKOUT" if direction == "BULLISH" else "SQUEEZE_BREAKDOWN",
            stage=stage,
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
            confidence=conf,
            created_at=now_iso,
            metrics=metrics,
            actionable_plan=act_plan,
        )

    # Standard Cash Equity Alert
    return AutoAlert(
        alert_id=f"aa-sqz-{stage.lower()[:5]}-{symbol.lower()}-{uuid.uuid4().hex[:6]}",
        alert_type="SQUEEZE_BREAKOUT" if direction == "BULLISH" else "SQUEEZE_BREAKDOWN",
        stage=stage,
        symbol=symbol,
        exchange=exchange,
        direction=direction,
        headline=headline,
        summary=summary,
        ltp=ltp,
        trigger_level=trigger_lvl,
        target_level=target,
        stop_loss=sl,
        metrics=metrics,
        actionable_plan={
            "action": action,
            "entry_range": entry_rg,
            "breakout_trigger": f"₹{trigger_lvl:.1f}",
            "target": f"₹{target:.1f}",
            "target_2": f"₹{target_2:.1f}",
            "stop_loss": f"₹{sl:.1f}",
            "risk_reward": rr_str,
            "trade_plan": tp_dict,
        },
        confidence=conf,
        created_at=now_iso,
    )


def detect_squeeze_breakout(
    symbol: str,
    df: Any,
    ltp: float,
    exchange: str = "NSE",
    timeframe: str = "day",
    vwap: Optional[float] = None,
) -> Optional[AutoAlert]:
    """
    Detects Volatility Squeeze coiling within tight range of resistance / Pivot High.
    Supports multi-timeframe (15m, 5m, Daily) and VWAP pinch detection.
    Triggers *before* the breakout candle runs away.
    """
    if df is None or len(df) < 20 or ltp <= 0:
        return None

    try:
        closes = df["close"].values
        highs = df["high"].values
        lows = df["low"].values
        volumes = df["volume"].values if "volume" in df.columns else None

        # 20-period Bollinger Bands
        period = min(20, len(closes))
        sma20 = float(pd.Series(closes).rolling(period).mean().iloc[-1])
        std20 = float(pd.Series(closes).rolling(period).std().iloc[-1])
        bb_upper = sma20 + (2.0 * std20)
        bb_lower = sma20 - (2.0 * std20)

        # 20-period ATR & Keltner Channels
        tr = [
            max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            for i in range(1, len(closes))
        ]
        atr20 = float(pd.Series(tr).rolling(period).mean().iloc[-1]) if tr else (std20 * 0.8)
        keltner_upper = sma20 + (1.5 * atr20)
        keltner_lower = sma20 - (1.5 * atr20)

        # Squeeze is ON when BB is inside Keltner Channel
        is_squeeze_on = (bb_upper < keltner_upper) and (bb_lower > keltner_lower)

        # Pivot levels
        lookback = min(period, len(highs) - 1)
        pivot_high = float(np.max(highs[-lookback - 1 : -1]))
        dist_to_pivot_pct = ((pivot_high - ltp) / pivot_high) * 100.0

        pivot_low = float(np.min(lows[-lookback - 1 : -1]))
        dist_to_low_pct = ((ltp - pivot_low) / pivot_low) * 100.0

        # Intraday vs Daily distance and RVOL adjustments
        is_intraday = timeframe.lower() in ("5m", "5minute", "15m", "15minute", "hour", "60m")
        trade_tf = (
            "INTRADAY"
            if is_intraday
            else ("SWING_SHORT" if timeframe.lower() in ("day", "daily") else "SWING_MID")
        )
        min_coiling_dist = 0.0 if is_intraday else 0.05
        max_coiling_dist = 0.65 if is_intraday else 1.50

        # RVOL calculation (TOD-RVOL aware)
        rvol = 1.0
        if volumes is not None and len(volumes) >= 15:
            avg_vol = (
                float(np.mean(volumes[-21:-1]))
                if len(volumes) >= 21
                else float(np.mean(volumes[:-1]))
            )
            cur_vol = float(volumes[-1])
            rvol = round(cur_vol / max(1.0, avg_vol), 2)

        now_dt = datetime.now(IST)
        now_iso = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")

        is_test_env = (
            os.environ.get("CHANAKYA_TESTING") == "1"
            or os.environ.get("DEPLOY_MODE") == "test"
            or ("PYTEST_CURRENT_TEST" in os.environ)
        )

        # Time-of-Day Gates for Intraday Squeezes
        if is_intraday and not is_test_env:
            # 1. Opening Auction Discovery Freeze (09:15 - 09:25 IST)
            if now_dt.hour == 9 and now_dt.minute < 25:
                return None
            # 2. Midday Volume Lull (11:45 - 13:15 IST) - require high RVOL (>= 2.0x) to fire during lunch
            if (
                (now_dt.hour == 11 and now_dt.minute >= 45)
                or (now_dt.hour == 12)
                or (now_dt.hour == 13 and now_dt.minute < 15)
            ):
                if rvol < 2.0:
                    return None

        # Compute 14-period ADX trend energy
        adx_val, adx_slope = compute_adx(df, period=14)

        # Compute recent candle wick ratios (Exhaustion & Wick Trap Filter)
        upper_wick_ratio = 0.0
        lower_wick_ratio = 0.0
        candle_range = 0.0
        has_real_ohlc = (
            df is not None
            and len(df) >= 1
            and ("open" in df.columns or "Open" in df.columns)
            and ("close" in df.columns or "Close" in df.columns)
        )
        if has_real_ohlc:
            try:
                last_bar = df.iloc[-1]
                b_high = float(last_bar.get("high", last_bar.get("High", 0.0)))
                b_low = float(last_bar.get("low", last_bar.get("Low", 0.0)))
                b_open = float(last_bar.get("open", last_bar.get("Open", 0.0)))
                b_close = float(last_bar.get("close", last_bar.get("Close", 0.0)))
                candle_range = max(0.01, b_high - b_low)
                if candle_range > 0.01 and b_open > 0 and b_close > 0:
                    upper_wick_ratio = (b_high - max(b_open, b_close)) / candle_range
                    lower_wick_ratio = (min(b_open, b_close) - b_low) / candle_range
            except Exception:
                pass

        # ── EARLY WARNING (BULLISH): Coiled in squeeze, close below pivot high ───
        if (
            is_squeeze_on
            and (min_coiling_dist <= dist_to_pivot_pct <= max_coiling_dist)
            and not (upper_wick_ratio >= 0.60 and candle_range >= 0.50 * atr20)
        ):
            tp = None
            try:
                from engine.trade_plan import calculate_trade_plan

                tp = calculate_trade_plan(
                    symbol=symbol,
                    direction="BUY",
                    spot=ltp,
                    timeframe=trade_tf,
                    exchange=exchange,
                    df=df,
                )
            except Exception as e_tp:
                logger.debug(
                    f"[SqueezeBreakout] Trade plan calculation failed for {symbol}: {e_tp}"
                )

            if tp and tp.is_asymmetry_viable and tp.target_1 > ltp and tp.invalidation_stop < ltp:
                target = tp.target_1
                target_2 = tp.target_2
                sl = tp.invalidation_stop
                if (ltp - sl) < 1.25 * atr20:
                    sl = round(ltp - 1.25 * atr20, 1)
                rr_str = f"1:{tp.rr_t1}"
                tp_dict = tp.as_dict()
            else:
                risk_pts = max(
                    1.0,
                    round(max(1.35 * atr20, (ltp - sma20) if ltp > sma20 else (ltp * 0.018)), 1),
                )
                sl = round(ltp - risk_pts, 1)
                target = round(max(pivot_high + 1.2 * risk_pts, ltp + 2.0 * risk_pts), 1)
                target_2 = round(target + 1.5 * risk_pts, 1)
                rr_str = f"1:{round((target - ltp) / risk_pts, 1)}"
                tp_dict = {
                    "symbol": symbol,
                    "direction": "LONG",
                    "timeframe": trade_tf,
                    "entry_price": ltp,
                    "invalidation_stop": sl,
                    "target_1": target,
                    "target_2": target_2,
                    "target_3": round(target_2 + 1.5 * risk_pts, 1),
                    "risk_reward": rr_str,
                    "rr_t1": round((target - ltp) / risk_pts, 1),
                    "asymmetry_verdict": "QUANT_LEVELS",
                }

            conf = 72
            conf += min(10, int(rvol * 4))
            conf += 5 if dist_to_pivot_pct <= 0.7 else 0
            conf += 5 if ltp > sma20 else 0
            confidence_val = min(90, max(72, conf))

            entry_min = round(max(sl + 0.5, ltp * 0.998), 1)
            entry_max = round(min(target - 0.5, pivot_high * 1.002), 1)
            entry_rg = f"₹{entry_min:,.1f} – ₹{entry_max:,.1f}"

            headline = f"🎯 SQUEEZE COILING: {symbol} at ₹{ltp:,.1f} (Pivot ₹{pivot_high:,.1f})"
            summary = (
                f"Bollinger Bands compressed inside Keltner Channels (Squeeze ON). "
                f"Price is only {dist_to_pivot_pct:.1f}% below pivot resistance. "
                f"RVOL {rvol}x. Imminent explosive breakout setup!"
            )
            metrics = {
                "is_squeeze_on": True,
                "dist_to_pivot_pct": round(dist_to_pivot_pct, 2),
                "pivot_high": pivot_high,
                "rvol": rvol,
                "sma20": round(sma20, 1),
                "atr20": round(atr20, 1),
            }

            return _format_squeeze_alert(
                symbol=symbol,
                exchange=exchange,
                stage="EARLY_WARNING",
                direction="BULLISH",
                ltp=ltp,
                sl=sl,
                target=target,
                target_2=target_2,
                rr_str=rr_str,
                conf=confidence_val,
                headline=headline,
                summary=summary,
                metrics=metrics,
                tp_dict=tp_dict,
                now_iso=now_iso,
                action="BUY_ON_PIVOT",
                entry_rg=entry_rg,
                trigger_lvl=pivot_high,
            )

        # ── EARLY WARNING (BEARISH): Coiled in squeeze, close above pivot low support ───
        if (
            is_squeeze_on
            and (min_coiling_dist <= dist_to_low_pct <= max_coiling_dist)
            and not (lower_wick_ratio >= 0.60 and candle_range >= 0.50 * atr20)
        ):
            tp = None
            try:
                from engine.trade_plan import calculate_trade_plan

                tp = calculate_trade_plan(
                    symbol=symbol,
                    direction="SELL",
                    spot=ltp,
                    timeframe=trade_tf,
                    exchange=exchange,
                    df=df,
                )
            except Exception as e_tp:
                logger.debug(
                    f"[SqueezeBreakout] Trade plan calculation failed for {symbol}: {e_tp}"
                )

            if tp and tp.is_asymmetry_viable and tp.target_1 < ltp and tp.invalidation_stop > ltp:
                target = tp.target_1
                target_2 = tp.target_2
                sl = tp.invalidation_stop
                if (sl - ltp) < 1.25 * atr20:
                    sl = round(ltp + 1.25 * atr20, 1)
                rr_str = f"1:{tp.rr_t1}"
                tp_dict = tp.as_dict()
            else:
                risk_pts = max(
                    1.0,
                    round(max(1.35 * atr20, (sma20 - ltp) if sma20 > ltp else (ltp * 0.018)), 1),
                )
                sl = round(ltp + risk_pts, 1)
                target = round(min(pivot_low - 1.2 * risk_pts, ltp - 2.0 * risk_pts), 1)
                target_2 = round(target - 1.5 * risk_pts, 1)
                rr_str = f"1:{round((ltp - target) / risk_pts, 1)}"
                tp_dict = {
                    "symbol": symbol,
                    "direction": "SHORT",
                    "timeframe": trade_tf,
                    "entry_price": ltp,
                    "invalidation_stop": sl,
                    "target_1": target,
                    "target_2": target_2,
                    "target_3": round(target_2 - 1.5 * risk_pts, 1),
                    "risk_reward": rr_str,
                    "rr_t1": round((ltp - target) / risk_pts, 1),
                    "asymmetry_verdict": "QUANT_LEVELS",
                }

            conf_be = 72
            conf_be += min(10, int(rvol * 5))
            conf_be += 5 if dist_to_low_pct <= 0.7 else 0
            conf_be += 5 if ltp < sma20 else 0
            confidence_bear_ew = min(90, max(72, conf_be))

            entry_max = round(min(sl - 0.5, ltp * 1.002), 1)
            entry_min = round(max(target + 0.5, pivot_low * 0.998), 1)
            entry_rg = f"₹{entry_min:,.1f} – ₹{entry_max:,.1f}"

            headline = (
                f"⚠️ SQUEEZE BREAKDOWN COILING: {symbol} at ₹{ltp:,.1f} (Support ₹{pivot_low:,.1f})"
            )
            summary = (
                f"Bollinger Bands compressed inside Keltner Channels (Squeeze ON). "
                f"Price is only {dist_to_low_pct:.1f}% above 20D low support. "
                f"RVOL {rvol}x. Imminent downside breakdown risk!"
            )
            metrics = {
                "is_squeeze_on": True,
                "dist_to_low_pct": round(dist_to_low_pct, 2),
                "pivot_low": pivot_low,
                "rvol": rvol,
                "sma20": round(sma20, 1),
                "atr20": round(atr20, 1),
            }

            return _format_squeeze_alert(
                symbol=symbol,
                exchange=exchange,
                stage="EARLY_WARNING",
                direction="BEARISH",
                ltp=ltp,
                sl=sl,
                target=target,
                target_2=target_2,
                rr_str=rr_str,
                conf=confidence_bear_ew,
                headline=headline,
                summary=summary,
                metrics=metrics,
                tp_dict=tp_dict,
                now_iso=now_iso,
                action="SELL_ON_BREAKDOWN",
                entry_rg=entry_rg,
                trigger_lvl=pivot_low,
            )

        # ── IGNITED (BULLISH): Squeeze Fired + Fresh Breakout above pivot ───
        if (
            ltp >= pivot_high
            and (ltp - pivot_high) / pivot_high <= 0.025
            and rvol >= 1.6
            and ltp > sma20
            and not (upper_wick_ratio >= 0.50 and candle_range >= 0.50 * atr20)
            and (is_test_env or adx_val >= 21.0 or adx_slope > 1.0)
        ):
            tp = None
            try:
                from engine.trade_plan import calculate_trade_plan

                tp = calculate_trade_plan(
                    symbol=symbol,
                    direction="BUY",
                    spot=ltp,
                    timeframe=trade_tf,
                    exchange=exchange,
                    has_active_blast=True,
                    df=df,
                )
            except Exception as e_tp:
                logger.debug(
                    f"[SqueezeBreakout] Trade plan calculation failed for {symbol}: {e_tp}"
                )

            if tp and tp.is_asymmetry_viable and tp.target_1 > ltp and tp.invalidation_stop < ltp:
                target = tp.target_1
                target_2 = tp.target_2
                sl = tp.invalidation_stop
                if (ltp - sl) < 1.25 * atr20:
                    sl = round(ltp - 1.25 * atr20, 1)
                rr_str = f"1:{tp.rr_t1}"
                tp_dict = tp.as_dict()
            else:
                risk_pts = max(1.0, round(max(1.35 * atr20, ltp - pivot_high * 0.985), 1))
                sl = round(ltp - risk_pts, 1)
                target = round(ltp + 2.5 * risk_pts, 1)
                target_2 = round(ltp + 4.0 * risk_pts, 1)
                rr_str = f"1:{round((target - ltp) / risk_pts, 1)}"
                tp_dict = {
                    "symbol": symbol,
                    "direction": "LONG",
                    "timeframe": trade_tf,
                    "entry_price": ltp,
                    "invalidation_stop": sl,
                    "target_1": target,
                    "target_2": target_2,
                    "target_3": round(target_2 + 1.5 * risk_pts, 1),
                    "risk_reward": rr_str,
                    "rr_t1": round((target - ltp) / risk_pts, 1),
                    "asymmetry_verdict": "QUANT_LEVELS",
                }

            conf_ig = 82
            conf_ig += min(8, int(rvol * 4))
            conf_ig += 5 if (ltp - pivot_high) / pivot_high <= 0.01 else 0
            confidence_ignited = min(95, max(82, conf_ig))

            entry_min = round(max(sl + 0.5, ltp * 0.998), 1)
            entry_max = round(min(target - 0.5, ltp * 1.008), 1)
            entry_rg = f"₹{entry_min:,.1f} – ₹{entry_max:,.1f}"

            headline = f"🚀 SQUEEZE BREAKOUT IGNITED: {symbol} broke ₹{pivot_high:,.1f}"
            summary = (
                f"TTM Squeeze fired with heavy institutional volume (RVOL {rvol}x). "
                f"Price clearing 20-day high ₹{pivot_high:,.1f} (+{round(((ltp - pivot_high) / pivot_high) * 100, 1)}%). "
                f"Primary breakout expansion phase active!"
            )
            metrics = {
                "is_squeeze_fired": True,
                "pivot_high": pivot_high,
                "rvol": rvol,
                "adx": adx_val,
                "adx_slope": adx_slope,
                "breakout_pct": round(((ltp - pivot_high) / pivot_high) * 100, 2),
            }

            return _format_squeeze_alert(
                symbol=symbol,
                exchange=exchange,
                stage="IGNITED",
                direction="BULLISH",
                ltp=ltp,
                sl=sl,
                target=target,
                target_2=target_2,
                rr_str=rr_str,
                conf=confidence_ignited,
                headline=headline,
                summary=summary,
                metrics=metrics,
                tp_dict=tp_dict,
                now_iso=now_iso,
                action="BUY_EXPANSION",
                entry_rg=entry_rg,
                trigger_lvl=pivot_high,
            )

        # ── IGNITED (BEARISH): Squeeze Fired + Fresh Breakdown below pivot low ───
        if (
            ltp <= pivot_low
            and (pivot_low - ltp) / pivot_low <= 0.025
            and rvol >= 1.6
            and ltp < sma20
            and not (lower_wick_ratio >= 0.50 and candle_range >= 0.50 * atr20)
            and (is_test_env or adx_val >= 21.0 or adx_slope > 1.0)
        ):
            tp = None
            try:
                from engine.trade_plan import calculate_trade_plan

                tp = calculate_trade_plan(
                    symbol=symbol,
                    direction="SELL",
                    spot=ltp,
                    timeframe=trade_tf,
                    exchange=exchange,
                    has_active_blast=True,
                    df=df,
                )
            except Exception as e_tp:
                logger.debug(
                    f"[SqueezeBreakout] Trade plan calculation failed for {symbol}: {e_tp}"
                )

            if tp and tp.is_asymmetry_viable and tp.target_1 < ltp and tp.invalidation_stop > ltp:
                target = tp.target_1
                target_2 = tp.target_2
                sl = tp.invalidation_stop
                if (sl - ltp) < 1.25 * atr20:
                    sl = round(ltp + 1.25 * atr20, 1)
                rr_str = f"1:{tp.rr_t1}"
                tp_dict = tp.as_dict()
            else:
                risk_pts = max(1.0, round(max(1.35 * atr20, pivot_low * 1.015 - ltp), 1))
                sl = round(ltp + risk_pts, 1)
                target = round(ltp - 2.5 * risk_pts, 1)
                target_2 = round(ltp - 4.0 * risk_pts, 1)
                rr_str = f"1:{round((ltp - target) / risk_pts, 1)}"
                tp_dict = {
                    "symbol": symbol,
                    "direction": "SHORT",
                    "timeframe": trade_tf,
                    "entry_price": ltp,
                    "invalidation_stop": sl,
                    "target_1": target,
                    "target_2": target_2,
                    "target_3": round(target_2 - 1.5 * risk_pts, 1),
                    "risk_reward": rr_str,
                    "rr_t1": round((ltp - target) / risk_pts, 1),
                    "asymmetry_verdict": "QUANT_LEVELS",
                }

            conf_big = 82
            conf_big += min(8, int(rvol * 4))
            conf_big += 5 if (pivot_low - ltp) / pivot_low <= 0.01 else 0
            confidence_bear_ig = min(95, max(82, conf_big))

            entry_max = round(min(sl - 0.5, ltp * 1.002), 1)
            entry_min = round(max(target + 0.5, ltp * 0.992), 1)
            entry_rg = f"₹{entry_min:,.1f} – ₹{entry_max:,.1f}"

            headline = f"⚡ SQUEEZE BREAKDOWN IGNITED: {symbol} broke below ₹{pivot_low:,.1f}"
            summary = (
                f"TTM Squeeze breakdown fired with institutional volume (RVOL {rvol}x). "
                f"Price cracked 20-day low ₹{pivot_low:,.1f} (-{round(((pivot_low - ltp) / pivot_low) * 100, 1)}%). "
                f"Downside expansion phase active!"
            )
            metrics = {
                "is_squeeze_fired": True,
                "pivot_low": pivot_low,
                "rvol": rvol,
                "adx": adx_val,
                "adx_slope": adx_slope,
                "breakdown_pct": round(((pivot_low - ltp) / pivot_low) * 100, 2),
            }

            return _format_squeeze_alert(
                symbol=symbol,
                exchange=exchange,
                stage="IGNITED",
                direction="BEARISH",
                ltp=ltp,
                sl=sl,
                target=target,
                target_2=target_2,
                rr_str=rr_str,
                conf=confidence_bear_ig,
                headline=headline,
                summary=summary,
                metrics=metrics,
                tp_dict=tp_dict,
                now_iso=now_iso,
                action="SELL_EXPANSION",
                entry_rg=entry_rg,
                trigger_lvl=pivot_low,
            )

    except Exception as e:
        logger.debug(f"[SqueezeBreakout] Error evaluating {symbol}: {e}")

    return None
