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
from datetime import datetime, time as dtime
from typing import Any, Optional

import pandas as pd
import numpy as np

from engine.alert_identity import (
    generate_alert_id,
    canonical_alert_symbol,
)
from engine.alert_model import AutoAlert
from market.instruments import format_strike

logger = logging.getLogger("chanakya.detectors.trend_day_continuation")

from config.constants import IST


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
    if df_5m is None or len(df_5m) < 4 or ltp <= 0:
        return None

    if now_dt is None:
        now_dt = datetime.now(IST)

    is_test_env = bool(os.getenv("CHANAKYA_TESTING") == "1" or os.getenv("PYTEST_CURRENT_TEST"))
    now_time = now_dt.time()

    # Time Window: Active from 09:35 to canonical derivative entry cutoff
    from market.rule_schedule import intraday_entry_cutoff

    _tdc_cutoff = intraday_entry_cutoff(now_dt.date(), is_derivative=True)
    if not is_test_env and not (dtime(9, 35) <= now_time <= _tdc_cutoff):
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

    # ── Multi-Timeframe 15m EMAs and Daily Structural Levels ───────────
    ema_50_15m = 0.0
    ema_20_15m = 0.0
    if len(closes) >= 15:
        try:
            span_50 = min(150, max(20, len(closes)))
            span_20 = min(60, max(10, len(closes) // 2))
            ema_50_15m = float(closes.ewm(span=span_50, adjust=False).mean().iloc[-1])
            ema_20_15m = float(closes.ewm(span=span_20, adjust=False).mean().iloc[-1])
        except Exception as e_ema:
            logger.debug(
                f"[TrendContinuation] MTF EMA computation skipped for {clean_sym}: {e_ema}"
            )
    daily_s1 = 0.0
    daily_r1 = 0.0
    cpr_pivot = 0.0
    pdl_val = 0.0
    pdh_val = 0.0
    try:
        from engine.daily_levels import get_daily_levels

        dl_obj = get_daily_levels(clean_sym)
        if dl_obj:
            pdl_val = float(dl_obj.pdl or 0.0)
            pdh_val = float(dl_obj.pdh or 0.0)
            if dl_obj.classic_pivots:
                daily_s1 = float(dl_obj.classic_pivots.get("s1", 0.0) or 0.0)
                daily_r1 = float(dl_obj.classic_pivots.get("r1", 0.0) or 0.0)
            if dl_obj.cpr:
                cpr_pivot = float(dl_obj.cpr.get("pivot", 0.0) or 0.0)
    except Exception as e_dl:
        logger.debug(f"[TrendContinuation] Daily levels lookup skipped for {clean_sym}: {e_dl}")

    # Fallback to prev_close for classic pivots if not already populated
    if daily_s1 == 0.0 and prev_close and prev_close > 0 and len(df_5m) >= 1:
        try:
            d_high = float(highs.max())
            d_low = float(lows.min())
            d_close = float(prev_close)
            pp = (d_high + d_low + d_close) / 3.0
            daily_s1 = round(2.0 * pp - d_high, 2)
            daily_r1 = round(2.0 * pp - d_low, 2)
            cpr_pivot = round(pp, 2)
        except Exception as e_piv:
            logger.debug(f"[TrendContinuation] Pivot fallback failed for {clean_sym}: {e_piv}")
    is_bull_trend = (
        (
            val_ema9 > val_ema20
            and val_ema20 >= prev_ema20
            and closes.iloc[-4:].mean() >= val_ema20 * 0.998
        )
        or (
            ema_20_15m > 0
            and ema_50_15m > 0
            and ema_20_15m > ema_50_15m
            and cur_c >= ema_50_15m * 0.998
        )
    ) and (val_vwap == 0 or cur_c >= val_vwap * 0.998)

    is_bear_trend = (
        (
            val_ema9 < val_ema20
            and val_ema20 <= prev_ema20
            and closes.iloc[-4:].mean() <= val_ema20 * 1.002
        )
        or (
            ema_20_15m > 0
            and ema_50_15m > 0
            and ema_20_15m < ema_50_15m
            and cur_c <= ema_50_15m * 1.002
        )
    ) and (val_vwap == 0 or cur_c <= val_vwap * 1.002)

    if not (is_bull_trend or is_bear_trend):
        return None

    # ── Pullback & Rejection Geometry ──────────────────────────────────
    is_bull_pullback = False
    is_bear_pullback = False
    support_reason = "20-EMA"
    resistance_reason = "20-EMA"

    if is_bull_trend:
        # Bullish: Low of recent 2 candles dipped into 9 EMA, 20 EMA, VWAP, 15m 50-EMA, Daily R1, or PDH
        tested_support = False
        if min(cur_l, prev_l) <= val_ema9 * 1.0025:
            tested_support = True
            support_reason = "9-EMA"
        elif min(cur_l, prev_l) <= val_ema20 * 1.0035:
            tested_support = True
            support_reason = "20-EMA"
        elif min(cur_l, prev_l) <= val_vwap * 1.0035:
            tested_support = True
            support_reason = "VWAP"
        elif ema_50_15m > 0 and min(cur_l, prev_l) <= ema_50_15m * 1.0035:
            tested_support = True
            support_reason = "15m 50-EMA"
        elif daily_r1 > 0 and min(cur_l, prev_l) <= daily_r1 * 1.0040:
            tested_support = True
            support_reason = "Daily R1 Pivot"
        elif pdh_val > 0 and min(cur_l, prev_l) <= pdh_val * 1.0040:
            tested_support = True
            support_reason = "Prior Day High"
        elif cpr_pivot > 0 and min(cur_l, prev_l) <= cpr_pivot * 1.0035:
            tested_support = True
            support_reason = "CPR Pivot"

        held_support = (
            (cur_c >= val_ema20 * 0.998 and ltp >= val_ema20 * 0.998)
            or (ema_50_15m > 0 and cur_c >= ema_50_15m * 0.998 and ltp >= ema_50_15m * 0.998)
            or (daily_r1 > 0 and cur_c >= daily_r1 * 0.998 and ltp >= daily_r1 * 0.998)
            or (pdh_val > 0 and cur_c >= pdh_val * 0.998 and ltp >= pdh_val * 0.998)
            or (cpr_pivot > 0 and cur_c >= cpr_pivot * 0.998 and ltp >= cpr_pivot * 0.998)
        )

        # Bullish Rejection: Lower wick >= 35% of bar or green reversal close > prev_h
        bar_rng = max(0.01, cur_h - cur_l)
        lower_wick = min(cur_o, cur_c) - cur_l
        lower_wick_ratio = lower_wick / bar_rng
        has_rejection = (
            (lower_wick_ratio >= 0.35)
            or (cur_c > prev_h)
            or (cur_c > cur_o and cur_c >= min(val_ema9, val_ema20))
            or (lower_wick_ratio >= 0.18 and cur_c > cur_o and cur_c > cur_l)
        )

        # Pullback volume dry-up: volume on the dip bar was below or near normal (< 1.25x SMA)
        is_dryup = cur_v <= (1.25 * vol_sma20)

        if tested_support and held_support and has_rejection and is_dryup:
            is_bull_pullback = True

    elif is_bear_trend:
        # Bearish: High of recent 2 candles retraced into 9 EMA, 20 EMA, VWAP, 15m 50-EMA, Daily S1, or PDL
        tested_resistance = False
        if max(cur_h, prev_h) >= val_ema9 * 0.9975:
            tested_resistance = True
            resistance_reason = "9-EMA"
        elif max(cur_h, prev_h) >= val_ema20 * 0.9965:
            tested_resistance = True
            resistance_reason = "20-EMA"
        elif max(cur_h, prev_h) >= val_vwap * 0.9965:
            tested_resistance = True
            resistance_reason = "VWAP"
        elif ema_50_15m > 0 and max(cur_h, prev_h) >= ema_50_15m * 0.9965:
            tested_resistance = True
            resistance_reason = "15m 50-EMA"
        elif daily_s1 > 0 and max(cur_h, prev_h) >= daily_s1 * 0.9960:
            tested_resistance = True
            resistance_reason = "Daily S1 Pivot"
        elif pdl_val > 0 and max(cur_h, prev_h) >= pdl_val * 0.9960:
            tested_resistance = True
            resistance_reason = "Prior Day Low"
        elif cpr_pivot > 0 and max(cur_h, prev_h) >= cpr_pivot * 0.9965:
            tested_resistance = True
            resistance_reason = "CPR Pivot"

        held_resistance = (
            (cur_c <= val_ema20 * 1.002 and ltp <= val_ema20 * 1.002)
            or (ema_50_15m > 0 and cur_c <= ema_50_15m * 1.002 and ltp <= ema_50_15m * 1.002)
            or (daily_s1 > 0 and cur_c <= daily_s1 * 1.002 and ltp <= daily_s1 * 1.002)
            or (pdl_val > 0 and cur_c <= pdl_val * 1.002 and ltp <= pdl_val * 1.002)
            or (cpr_pivot > 0 and cur_c <= cpr_pivot * 1.002 and ltp <= cpr_pivot * 1.002)
        )

        # Bearish Rejection: Upper wick >= 35% of bar or red breakdown close < prev_l
        bar_rng = max(0.01, cur_h - cur_l)
        upper_wick = cur_h - max(cur_o, cur_c)
        upper_wick_ratio = upper_wick / bar_rng
        has_rejection = (
            (upper_wick_ratio >= 0.35)
            or (cur_c < prev_l)
            or (cur_c < cur_o and cur_c <= max(val_ema9, val_ema20))
            or (upper_wick_ratio >= 0.18 and cur_c < cur_o and cur_c < cur_h)
        )

        # Retracement volume dry-up
        is_dryup = cur_v <= (1.25 * vol_sma20)

        if tested_resistance and held_resistance and has_rejection and is_dryup:
            is_bear_pullback = True

    if not (is_bull_pullback or is_bear_pullback):
        return None

    direction = "BULLISH" if is_bull_pullback else "BEARISH"

    # ── Benchmark Index Regime Gate (Institutional Market Alignment) ─────────
    # Prevents counter-trend traps: do not buy pullbacks when the benchmark index
    # is trading below its session VWAP (bearish market), and vice-versa.
    if not is_index and not is_test_env:
        try:
            from market.quotes import get_quote

            is_bank = "BANK" in clean_sym or clean_sym in (
                "SBIN",
                "KOTAKBANK",
                "ICICIBANK",
                "HDFCBANK",
                "AXISBANK",
                "INDUSINDBK",
                "BANDHANBNK",
                "FEDERALBNK",
            )
            idx_probe_sym = "NSE:NIFTY BANK" if is_bank else "NSE:NIFTY 50"
            idx_probe = get_quote(idx_probe_sym)
            iq = idx_probe.get(idx_probe_sym) or idx_probe.get(idx_probe_sym.replace("NSE:", ""))
            if not iq and is_bank:
                idx_probe = get_quote("NSE:NIFTY 50")
                iq = idx_probe.get("NSE:NIFTY 50") or idx_probe.get("NIFTY 50")
            if iq:
                i_ltp = float(getattr(iq, "last_price", 0.0) or 0.0)
                i_vwap = float(getattr(iq, "vwap", 0.0) or 0.0)
                if i_vwap > 0 and i_ltp > 0:
                    # Relative strength decoupling: If the individual stock exhibits strong momentum
                    # (trading >= 0.8% above its own VWAP for longs, or <= 0.8% below for shorts),
                    # it leads its sector independently of broader benchmark chop.
                    is_stock_rs_leader = val_vwap > 0 and ltp >= (val_vwap * 1.008)
                    is_stock_rs_laggard = val_vwap > 0 and ltp <= (val_vwap * 0.992)

                    if is_bull_pullback and i_ltp < i_vwap:
                        if not is_stock_rs_leader:
                            logger.debug(
                                f"[TrendContinuation] Suppressed Bullish Continuation on {symbol}: "
                                f"{idx_probe_sym} ({i_ltp:.1f}) below VWAP ({i_vwap:.1f}) - counter-trend trap"
                            )
                            return None
                        else:
                            logger.info(
                                f"[TrendContinuation] Bullish Continuation ALLOWED on {symbol} despite benchmark {idx_probe_sym} below VWAP: "
                                f"stock exhibits strong Relative Strength (+{((ltp - val_vwap) / val_vwap * 100):.2f}% above own VWAP)."
                            )
                    elif is_bear_pullback and i_ltp > i_vwap:
                        if not is_stock_rs_laggard:
                            logger.debug(
                                f"[TrendContinuation] Suppressed Bearish Continuation on {symbol}: "
                                f"{idx_probe_sym} ({i_ltp:.1f}) above VWAP ({i_vwap:.1f}) - counter-trend trap"
                            )
                            return None
                        else:
                            logger.info(
                                f"[TrendContinuation] Bearish Continuation ALLOWED on {symbol} despite benchmark {idx_probe_sym} above VWAP: "
                                f"stock exhibits strong Relative Weakness ({((ltp - val_vwap) / val_vwap * 100):.2f}% below own VWAP)."
                            )
        except Exception as e_idx_regime:
            logger.debug(
                f"[TrendContinuation] Index regime gate non-fatal check bypassed: {e_idx_regime}"
            )

    # ── Index Heavyweight Locomotive Polarization Gate ────────────
    if is_index and not is_test_env:
        try:
            from market.indices import get_index_polarization

            idx_pol = get_index_polarization(clean_sym)
            if idx_pol.is_polarized:
                logger.info(
                    f"[TrendContinuation] Suppressed on {clean_sym}: Heavyweight Locomotive Tug-of-War Polarization "
                    f"({idx_pol.summary}). Disallowing index trend continuation in conflict gridlock."
                )
                return None
        except Exception as e_pol:
            logger.debug(f"[TrendContinuation] Index polarization check notice: {e_pol}")

    # ── Multi-Pillar Structural Location & Confluence (OB / Fib OTE / FVG / Sweep) ──
    struct_loc = None
    try:
        from analysis.market_structure import evaluate_structural_location

        struct_loc = evaluate_structural_location(
            df_5m,
            spot=ltp,
            direction=direction,
            vwap=val_vwap,
            pdh=pdh_val,
            pdl=pdl_val,
            rvol_val=float(rvol_val or 1.0),
        )
        # Cross-asset Constituent Lead-Lag alignment for major indices (NIFTY / BANKNIFTY)
        if is_index and clean_sym in ("NIFTY", "BANKNIFTY"):
            try:
                from engine.feature_bus import compute_constituent_lead_lag

                ll = compute_constituent_lead_lag(clean_sym)
                if ll.get("status") == "AVAILABLE":
                    lb = ll.get("lead_bias", "NEUTRAL")
                    w_imp = float(ll.get("weighted_impulse_pct", 0.0) or 0.0)
                    if is_bull_pullback and lb == "BEARISH_LEAD" and w_imp <= -0.35:
                        logger.info(
                            f"[TrendContinuation] Suppressed {clean_sym} BULLISH pullback: opposing constituent basket {lb} ({w_imp:+.2f}%)."
                        )
                        return None
                    if is_bear_pullback and lb == "BULLISH_LEAD" and w_imp >= 0.35:
                        logger.info(
                            f"[TrendContinuation] Suppressed {clean_sym} BEARISH pullback: opposing constituent basket {lb} ({w_imp:+.2f}%)."
                        )
                        return None
            except Exception as e_ll:
                logger.debug(f"[TrendContinuation] Constituent lead-lag check skipped: {e_ll}")
    except Exception as e_loc:
        logger.debug(f"[TrendContinuation] Structural location evaluation skipped: {e_loc}")

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
                    obi_50_val >= 0.20
                    or tbt_depth.get("fortress_bid_wall_confirmed")
                    or tbt_depth.get("fleeing_ask_wall_detected")
                    or "ASK_SPOOF" in str(tbt_depth.get("spoof_trap_warning") or "")
                ):
                    logger.info(
                        f"[TrendContinuation] Suppressed Bearish Continuation on {clean_sym}: TBT OBI-50 {obi_50_val:+.2f} / Bid Wall / Ask Spoof on {fut_sym}."
                    )
                    return None
                elif is_bull_pullback and (
                    obi_50_val <= -0.20
                    or tbt_depth.get("fortress_ask_wall_confirmed")
                    or tbt_depth.get("fleeing_bid_wall_detected")
                    or "BID_SPOOF" in str(tbt_depth.get("spoof_trap_warning") or "")
                ):
                    logger.info(
                        f"[TrendContinuation] Suppressed Bullish Continuation on {clean_sym}: TBT OBI-50 {obi_50_val:+.2f} / Ask Wall / Bid Spoof on {fut_sym}."
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

    # Smart Money Flow Analysis: Granville OBV, Swingscape Triple-DMI, and Tom Williams VSA
    has_flow = False
    vsa_sig = None
    dmi_verdict = None
    obv_div = None

    if df_5m is not None and len(df_5m) >= 5:
        try:
            from analysis.vsa import analyse_vsa
            from analysis.dmi_filter import evaluate_triple_dmi
            from analysis.obv import analyse_obv

            vsa_res = analyse_vsa(df_5m, is_intraday=True)
            if vsa_res:
                vsa_sig = vsa_res.signal
                if is_bull_pullback and vsa_res.signal in (
                    "NO_SUPPLY",
                    "STOPPING_VOLUME",
                    "EFFORT_VS_RESULT_BULLISH_ABSORPTION",
                    "ABSORPTION_BREAKOUT",
                ):
                    confidence_score += 6
                    has_flow = True
                elif is_bear_pullback and vsa_res.signal in (
                    "NO_DEMAND",
                    "SELLING_CLIMAX",
                    "EFFORT_VS_RESULT_BEARISH_CLIMAX",
                ):
                    confidence_score += 6
                    has_flow = True

            dmi_res = evaluate_triple_dmi(df_5m, is_intraday=True)
            if dmi_res:
                dmi_verdict = dmi_res.verdict
                if is_bull_pullback and dmi_verdict in (
                    "TRIPLE_BEARISH_CONFIRMED",
                    "BEARISH_ESTABLISHED",
                ):
                    logger.info(
                        f"[TrendContinuation] Vetoed Bullish Pullback on {clean_sym}: Triple-DMI={dmi_verdict} opposes direction."
                    )
                    return None
                if is_bear_pullback and dmi_verdict in (
                    "TRIPLE_BULLISH_CONFIRMED",
                    "BULLISH_ESTABLISHED",
                ):
                    logger.info(
                        f"[TrendContinuation] Vetoed Bearish Pullback on {clean_sym}: Triple-DMI={dmi_verdict} opposes direction."
                    )
                    return None
                if is_bull_pullback and (
                    dmi_verdict in ("TRIPLE_BULLISH_CONFIRMED", "BULLISH_ESTABLISHED")
                    or dmi_res.plus_di >= 22.0
                ):
                    confidence_score += 5
                    has_flow = True
                elif is_bear_pullback and (
                    dmi_verdict in ("TRIPLE_BEARISH_CONFIRMED", "BEARISH_ESTABLISHED")
                    or dmi_res.minus_di >= 22.0
                ):
                    confidence_score += 5
                    has_flow = True

            obv_res = analyse_obv(df_5m, is_intraday=True)
            if obv_res:
                obv_div = obv_res.divergence
                if is_bull_pullback and obv_res.divergence == "BEARISH_DIVERGENCE":
                    logger.info(
                        f"[TrendContinuation] Vetoed Bullish Pullback on {clean_sym}: opposing OBV BEARISH_DIVERGENCE."
                    )
                    return None
                if is_bear_pullback and obv_res.divergence == "BULLISH_DIVERGENCE":
                    logger.info(
                        f"[TrendContinuation] Vetoed Bearish Pullback on {clean_sym}: opposing OBV BULLISH_DIVERGENCE."
                    )
                    return None
                if is_bull_pullback and (
                    obv_res.divergence in ("BULLISH_CONVERGENCE", "BULLISH_DIVERGENCE")
                    or obv_res.obv_slope_5bar > 0
                ):
                    confidence_score += 4
                    has_flow = True
                elif is_bear_pullback and (
                    obv_res.divergence in ("BEARISH_CONVERGENCE", "BEARISH_DIVERGENCE")
                    or obv_res.obv_slope_5bar < 0
                ):
                    confidence_score += 4
                    has_flow = True

            # Opposing SMC Wall & Wide-CPR Single-EMA Guard (eliminates low-edge EMA-only bounces)
            if not is_test_env and struct_loc is not None:
                if struct_loc.has_opposing_wall and not (has_flow and rvol_val >= 1.6):
                    logger.info(
                        f"[TrendContinuation] Suppressed {clean_sym} {direction}: {struct_loc.opposing_wall_reason}"
                    )
                    return None
                is_pure_ema_only = (support_reason if is_bull_pullback else resistance_reason) in (
                    "9-EMA",
                    "20-EMA",
                )
                if (
                    is_wide_cpr
                    and is_pure_ema_only
                    and not struct_loc.has_strong_location
                    and rvol_val < 1.35
                ):
                    logger.info(
                        f"[TrendContinuation] Suppressed {clean_sym} {direction}: Wide CPR EMA-only pullback without OB/Fib/Sweep confluence (rvol={rvol_val:.2f})."
                    )
                    return None

            # Reject weak/choppy low-edge pullbacks lacking flow confirmation (cuts -6% churn)
            if (
                not has_flow
                and dmi_verdict in (None, "NEUTRAL", "WEAK_OR_CHOPPY")
                and alpha_quality_score < 82.0
            ):
                logger.info(
                    f"[TrendContinuation] Suppressed low-edge pullback on {clean_sym}: "
                    f"dmi={dmi_verdict}, has_flow={has_flow}, aqs={alpha_quality_score:.1f} < 82.0"
                )
                return None

            # Midday Chop Window (11:30 - 13:15 IST): Require stronger RVOL + trend/flow confluence
            if (
                not is_test_env
                and dtime(11, 30) <= now_time <= dtime(13, 15)
                and not is_narrow_cpr
                and (rvol_val < 1.35 or (not has_flow and alpha_quality_score < 85.0))
            ):
                logger.info(
                    f"[TrendContinuation] Suppressed midday-chop pullback on {clean_sym}: "
                    f"rvol={rvol_val:.2f}, has_flow={has_flow}, aqs={alpha_quality_score:.1f}"
                )
                return None
        except Exception as e_flow:
            logger.debug(f"[TrendContinuation] Flow analysis skipped: {e_flow}")

    confidence_score = min(98, max(75, confidence_score))
    is_afternoon = now_time >= dtime(13, 30)
    pref_vehicle = "SPREAD_ONLY" if is_afternoon else "NAKED_OPTION"

    # ── Option Resolution via Unified VIX-Aware Resolver ──────────────
    from engine.position_sizer import get_lot_size
    from engine.option_resolver import resolve_option_contract

    stock_lot_size = get_lot_size(clean_sym)
    should_prefer_opt = is_index or (stock_lot_size > 1)

    resolved_opt = resolve_option_contract(
        symbol=clean_sym,
        spot=ltp,
        direction=direction,
        underlying_sl=sl_price,
        underlying_target=t1_price,
        prefer_options=should_prefer_opt,
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

    try:
        from engine.pullback_level_resolver import resolve_pullback_entry

        pullback_res = resolve_pullback_entry(
            symbol=clean_sym,
            direction=direction,
            spot=ltp,
            vwap=val_vwap or ltp,
            day_high=cur_h,
            day_low=cur_l,
            atr_5m=atr_5m,
            prefer_options=is_index,
        )
        if pullback_res:
            act_plan["limit_entry_zone"] = (
                f"₹{pullback_res.entry_zone_min:,.1f} - ₹{pullback_res.entry_zone_max:,.1f}"
            )
            act_plan["limit_entry_mid"] = pullback_res.entry_zone_mid
    except Exception as e_pb:
        logger.debug(f"[TrendContinuation] Pullback level resolver error for {clean_sym}: {e_pb}")

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

    retest_label = support_reason if is_bull_pullback else resistance_reason
    loc_tags = list(struct_loc.location_tags) if struct_loc and struct_loc.location_tags else []
    anchor_tag = f"{retest_label.upper().replace(' ', '_')}_{'SUPPORT' if is_bull_pullback else 'RESISTANCE'}"
    pb_signals: list[str] = [anchor_tag]
    for lt in loc_tags:
        if lt not in pb_signals:
            pb_signals.append(lt)
    pb_signals.append(f"VOL_DRYUP_{pullback_vol_ratio:.2f}X")
    if is_bull_pullback:
        pb_signals.append("BULL_WICK_REJECTION")
    else:
        pb_signals.append("BEAR_WICK_REJECTION")
    confluence_pillars = [
        p
        for p, ok in (
            (
                "LOCATION",
                bool(struct_loc and struct_loc.is_valid_location) or retest_label not in ("9-EMA",),
            ),
            ("TRIGGER", True),
            ("FLOW", bool(has_flow or rvol_val >= 1.25)),
        )
        if ok
    ]
    if is_wide_cpr and not (struct_loc and struct_loc.has_strong_location):
        confidence_score = min(confidence_score, 84)
    elif struct_loc and struct_loc.has_strong_location:
        confidence_score = min(98, confidence_score + 3)
    if has_opt and opt_strike:
        opt_action = f"{format_strike(opt_strike)} {opt_type} Buy"
        headline = (
            f"🎯 [TREND PULLBACK] {clean_sym} {opt_action}: {retest_label} Support Retest (Spot ₹{ltp:,.1f})"
            if is_bull_pullback
            else f"🎯 [TREND PULLBACK] {clean_sym} {opt_action}: {retest_label} Resistance Reject (Spot ₹{ltp:,.1f})"
        )
        summary = (
            f"Institutional shallow pullback into {retest_label} on {clean_sym}. Low-volume retest holds support."
            if is_bull_pullback
            else f"Institutional shallow bounce into {retest_label} on {clean_sym}. Low-volume retest rejected at resistance."
        )
    else:
        eq_action = "Long" if is_bull_pullback else "Short"
        headline = (
            f"🎯 [TREND PULLBACK] {clean_sym} {eq_action}: {retest_label} Support Retest @ ₹{ltp:,.1f} (T1: ₹{t1_price:,.1f})"
            if is_bull_pullback
            else f"🎯 [TREND PULLBACK] {clean_sym} {eq_action}: {retest_label} Resistance Reject @ ₹{ltp:,.1f} (T1: ₹{t1_price:,.1f})"
        )
        summary = (
            f"Institutional shallow pullback into {retest_label} on {clean_sym}. Low-volume retest holds support."
            if is_bull_pullback
            else f"Institutional shallow bounce into {retest_label} on {clean_sym}. Low-volume retest rejected at resistance."
        )

    alert_seg = "FNO_INDEX" if is_index else ("FNO_STOCK" if has_opt else segment)
    alert_exch = (
        "BFO"
        if clean_sym in ("SENSEX", "BANKEX")
        else ("NFO" if (is_index or has_opt) else exchange)
    )
    act_plan["segment"] = alert_seg
    spread_info = getattr(resolved_opt, "spread_details", None) if has_opt else None

    # Coordinate lower-timeframe fractal entry and 3-tier scale-out plan
    fractal_dict = {}
    try:
        from engine.fractal_entry_coordinator import coordinate_fractal_entry

        zone_buffer = 0.25 * atr_5m
        htf_zone = (ltp + zone_buffer, ltp - zone_buffer)
        fractal_bp = coordinate_fractal_entry(
            symbol=clean_sym,
            direction=direction,
            htf_zone=htf_zone,
            htf_target=t1_price,
            df_ltf=df_5m,
            ltp=ltp,
        )
        fractal_dict = fractal_bp.to_dict()
        if isinstance(act_plan, dict):
            act_plan["scale_out_plan"] = fractal_bp.scale_out_plan
            act_plan["fractal_entry_type"] = fractal_bp.entry_type
    except Exception as _e_frac:
        logger.debug(f"[trend_day_continuation] Fractal coordination non-fatal: {_e_frac}")

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
            "day_high": round(float(df_5m[col_h].max()), 2)
            if df_5m is not None and col_h in df_5m.columns
            else None,
            "day_low": round(float(df_5m[col_l].min()), 2)
            if df_5m is not None and col_l in df_5m.columns
            else None,
            "prev_close": round(float(prev_close), 2) if prev_close else None,
            "underlying_spot": round(float(ltp), 2),
            "underlying_vwap": round(val_vwap, 2),
            "rvol": round(rvol_val, 2),
            "trend_impulse_rvol": trend_rvol,
            "pullback_vol_ratio": pullback_vol_ratio,
            "is_volume_dryup": is_dryup,
            "is_pullback": True,
            "setup_archetype": "PULLBACK_RETEST",
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
            "has_flow": has_flow,
            "vsa_signal": vsa_sig,
            "dmi_triple_verdict": dmi_verdict,
            "obv_regime": obv_div,
            "signals": pb_signals,
            "structural_location": loc_tags,
            "fib_retracement_pct": struct_loc.fib_retracement_pct if struct_loc else None,
            "nearest_ob_zone": struct_loc.nearest_ob_zone if struct_loc else None,
            "confluence_pillars": confluence_pillars,
            "fractal_blueprint": fractal_dict,
        },
        preferred_vehicle=pref_vehicle,
        no_chase_boundary=opt_no_chase if has_opt else resolved_no_chase,
        spot_no_chase_boundary=resolved_no_chase if has_opt else None,
        created_at=now_iso,
        environment="LIVE",
        is_live=True,
    )
