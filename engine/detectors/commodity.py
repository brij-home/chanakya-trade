"""
engine/detectors/commodity.py
──────────────────────────────
Autonomous MCX Commodity Breakout & Options-First Detector.

Monitors liquid MCX commodities (Crude Oil, Gold, Silver, Natural Gas, Copper, Zinc)
for high-asymmetry session breakouts, 20-bar Donchian channel expansions, VWAP reclaims,
and US session volatility surges with defined-risk options alternatives.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import pandas as pd

from engine.alert_model import AutoAlert

logger = logging.getLogger("chanakya.detectors.commodity")
IST = timezone(timedelta(hours=5, minutes=30))

DEFAULT_COMMODITIES = [
    "CRUDEOIL",
    "NATURALGAS",
    "GOLD",
    "SILVER",
    "COPPER",
    "ZINC",
]

# On Indian MCX, only energy (Crude, NatGas) and gold have active option liquidity.
# Base metals (Copper, Zinc, Aluminium) and silver mini/lead have virtually non-existent option liquidity
# and ITM options devolve into physically settled 2,500 kg futures requiring high margin.
# Trading them as primary options is an institutional violation; they MUST be traded as MCX Futures.
LIQUID_COMMODITY_OPTIONS = {"CRUDEOIL", "CRUDEOILM", "NATURALGAS", "NATGASMINI", "GOLD", "GOLDM"}


def compute_commodity_rsi(df_5m: Optional[pd.DataFrame], period: int = 14) -> Optional[float]:
    """Calculates 14-period Wilder RSI from 5m OHLCV bars for momentum corridor gating."""
    if df_5m is None or len(df_5m) < period + 1:
        return None
    try:
        close_s = df_5m["close"] if "close" in df_5m.columns else df_5m.get("Close")
        if close_s is None or len(close_s) < period + 1:
            return None
        delta = close_s.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(window=period, min_periods=period).mean()
        avg_loss = loss.rolling(window=period, min_periods=period).mean()
        last_gain = float(avg_gain.iloc[-1])
        last_loss = float(avg_loss.iloc[-1])
        if last_loss == 0:
            return 100.0 if last_gain > 0 else 50.0
        rs = last_gain / last_loss
        return round(100.0 - (100.0 / (1.0 + rs)), 2)
    except Exception:
        return None


def get_commodity_max_chase(clean_sym: str, risk_pts: float) -> float:
    """
    Returns asset-tailored maximum chase points for MCX commodities.
    Ensures chase never exceeds 30% of structural risk or volatility budget (1 solution doesn't fit all).
    """
    sym = clean_sym.upper()
    if sym in ("CRUDEOIL", "CRUDEOILM"):
        return round(max(5.0, min(risk_pts * 0.30, 20.0)), 1)
    elif sym in ("NATURALGAS", "NATGASMINI"):
        return round(max(0.40, min(risk_pts * 0.28, 1.20)), 2)
    elif sym in ("GOLD", "GOLDM", "GOLDGUINEA", "GOLDPETAL"):
        return round(max(30.0, min(risk_pts * 0.30, 100.0)), 1)
    elif sym in ("SILVER", "SILVERM", "SILMIC"):
        return round(max(60.0, min(risk_pts * 0.30, 250.0)), 1)
    elif sym in ("COPPER", "ZINC", "ALUMINIUM", "LEAD"):
        return round(max(0.40, min(risk_pts * 0.28, 1.50)), 2)
    return round(max(1.0, risk_pts * 0.30), 2)


def detect_commodity_volatility_squeeze(df: Optional[pd.DataFrame]) -> dict[str, Any]:
    """
    Computes 20-period TTM Squeeze metric (Bollinger Bands vs Keltner Channels) on 5m bars.
    Detects volatility coiling prior to explosive expansion.
    Returns:
        is_squeeze_on: True if BB is currently inside KC (volatility coiling)
        is_squeeze_fired: True if BB was inside KC within the last 1-6 bars and is now expanding
        squeeze_direction: "BULLISH" if close >= EMA20 else "BEARISH"
        squeeze_bars: number of consecutive coiled bars
    """
    empty_result = {
        "is_squeeze_on": False,
        "is_squeeze_fired": False,
        "squeeze_direction": "NEUTRAL",
        "squeeze_bars": 0,
    }
    if df is None or len(df) < 21:
        return empty_result
    try:
        closes = df["close"] if "close" in df.columns else df.get("Close")
        highs = df["high"] if "high" in df.columns else df.get("High")
        lows = df["low"] if "low" in df.columns else df.get("Low")
        if closes is None or len(closes) < 21:
            return empty_result

        # Bollinger Bands (20, 2.0)
        sma20 = closes.rolling(20).mean()
        std20 = closes.rolling(20).std()
        bb_upper = sma20 + 2.0 * std20
        bb_lower = sma20 - 2.0 * std20

        # Keltner Channels (20, 1.5 ATR)
        ema20 = closes.ewm(span=20, adjust=False).mean()
        tr1 = highs - lows
        tr2 = (highs - closes.shift(1)).abs()
        tr3 = (lows - closes.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr14 = tr.rolling(14).mean()
        kc_upper = ema20 + 1.5 * atr14
        kc_lower = ema20 - 1.5 * atr14

        # Squeeze condition: BB inside KC
        squeeze_mask = (bb_upper < kc_upper) & (bb_lower > kc_lower)
        is_squeeze_on = bool(squeeze_mask.iloc[-1])

        # How many bars coiled in the last 10 bars
        recent_squeezes = squeeze_mask.iloc[-10:].tolist()
        squeeze_bars = sum(1 for s in recent_squeezes if s)

        # Squeeze fired: was in squeeze within the last 1-6 bars, but current bar broke out
        was_in_squeeze_recently = any(squeeze_mask.iloc[-7:-1]) if len(squeeze_mask) >= 7 else False
        is_squeeze_fired = was_in_squeeze_recently and not is_squeeze_on

        last_close = float(closes.iloc[-1])
        last_ema = float(ema20.iloc[-1])
        squeeze_dir = "BULLISH" if last_close >= last_ema else "BEARISH"

        return {
            "is_squeeze_on": is_squeeze_on,
            "is_squeeze_fired": is_squeeze_fired,
            "squeeze_direction": squeeze_dir,
            "squeeze_bars": squeeze_bars,
        }
    except Exception as e:
        logger.debug(f"[CommodityDetector] Volatility squeeze calculation error: {e}")
        return empty_result


def detect_commodity_breakouts(
    universe: Optional[list[str]] = None,
    quotes_map: Optional[dict[str, Any]] = None,
    ohlcv_1m_map: Optional[dict[str, Any]] = None,
) -> list[AutoAlert]:
    """
    Scans liquid MCX commodities for high-asymmetry breakouts and options-first setups.
    Active during post-equity and US market sessions (15:30 - 23:30 IST).
    """
    from market.quotes import get_quote

    found: list[AutoAlert] = []
    targets = universe or DEFAULT_COMMODITIES
    formatted = [f"MCX:{s}" if ":" not in s else s for s in targets]
    now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    if quotes_map is None:
        try:
            quotes_map = get_quote(formatted)
        except Exception as e:
            logger.debug(f"[CommodityDetector] Commodity quotes fetch error: {e}")
            return found

    # Pre-fetch 5m OHLCV concurrently across watched commodities to eliminate serial network latency
    ohlcv_map: dict[str, Any] = {}
    try:
        from concurrent.futures import ThreadPoolExecutor
        from market.history import get_ohlcv

        def _fetch_target_ohlcv(t_sym: str) -> tuple[str, Any]:
            c_sym = t_sym.upper().replace("MCX:", "").strip()
            try:
                return c_sym, get_ohlcv(c_sym, exchange="MCX", interval="5minute", days=2)
            except Exception as e_hist:
                logger.debug(f"[CommodityDetector] Error pre-fetching 5m OHLCV for MCX:{c_sym}: {e_hist}")
                return c_sym, None

        with ThreadPoolExecutor(max_workers=min(6, len(targets))) as pool:
            for c_sym, df_res in pool.map(_fetch_target_ohlcv, targets):
                ohlcv_map[c_sym] = df_res
    except Exception as e_pool:
        logger.debug(f"[CommodityDetector] Concurrent OHLCV pre-fetch error: {e_pool}")

    for sym in targets:
        clean_sym = sym.upper().replace("MCX:", "").strip()
        q = quotes_map.get(f"MCX:{clean_sym}") or quotes_map.get(clean_sym)
        if not q:
            continue

        ltp = float(getattr(q, "last_price", 0.0) or getattr(q, "ltp", 0.0) or 0.0)
        if ltp <= 0:
            continue

        # Strict Data Provenance Gate: Verify if quote is authentic live broker data vs synthetic/mock
        is_mock_quote = (
            type(q).__name__ == "MagicMock"
            or getattr(q, "_is_mock", False)
            or getattr(q, "provider", "") in ("mock", "TEST")
            or getattr(q, "data_state", "") == "UNAVAILABLE"
        )
        is_test_env = (
            os.environ.get("CHANAKYA_TESTING") == "1" or os.environ.get("DEPLOY_MODE") == "test"
        )
        is_authentic_live = not (is_mock_quote or is_test_env)

        chg_prev = float(getattr(q, "change_pct", 0.0) or 0.0)
        open_p = float(getattr(q, "open", 0.0) or 0.0)
        high_p = float(getattr(q, "high", 0.0) or 0.0)
        low_p = float(getattr(q, "low", 0.0) or 0.0)
        vol = int(getattr(q, "volume", 0) or 0)

        chg_open = round(((ltp - open_p) / open_p * 100), 2) if open_p > 0 else chg_prev
        chg_from_low = round(((ltp - low_p) / low_p * 100), 2) if low_p > 0 else 0.0
        chg_from_high = round(((high_p - ltp) / high_p * 100), 2) if high_p > 0 else 0.0
        chg = chg_open if abs(chg_open) > abs(chg_prev) else chg_prev

        # 1. Sanitize VWAP: discard corrupted/mock zero or sub-50% values
        raw_vwap = getattr(q, "vwap", None)
        try:
            vwap = (
                float(raw_vwap) if (raw_vwap is not None and float(raw_vwap) > (ltp * 0.5)) else ltp
            )
        except Exception:
            vwap = ltp
        has_real_vwap = (vwap > 0) and (abs(ltp - vwap) >= 2.0) and (vwap != ltp)

        # Check Learning Engine Lockout first (Kill repetitive invalidation loops)
        from engine.learning_engine import pattern_learning_engine

        is_locked_bull, _ = pattern_learning_engine.is_symbol_locked_out(
            clean_sym, direction="BULLISH", ltp=ltp, vwap=vwap
        )
        is_locked_bear, _ = pattern_learning_engine.is_symbol_locked_out(
            clean_sym, direction="BEARISH", ltp=ltp, vwap=vwap
        )

        # High-Impact Scheduled US Inventory Event Blackout Window (Live market only)
        now_ist = datetime.now(IST)
        if is_authentic_live:
            hh, mm = now_ist.hour, now_ist.minute
            weekday = now_ist.weekday()  # Monday=0, Tuesday=1, Wednesday=2, Thursday=3

            # 1. Wednesday EIA Weekly Petroleum Status Report (Crude): 19:55 - 20:15 IST (release at 20:00 IST)
            if clean_sym in ("CRUDEOIL", "CRUDEOILM") and weekday == 2:
                if (hh == 19 and mm >= 55) or (hh == 20 and mm <= 15):
                    logger.info(
                        f"[CommodityDetector] Suppressing {clean_sym} during Wednesday EIA Crude inventory blackout window ({hh:02d}:{mm:02d} IST)"
                    )
                    continue

            # 2. Thursday EIA Natural Gas Storage Report: 19:55 - 20:15 IST (release at 20:00 IST)
            if clean_sym in ("NATURALGAS", "NATGASMINI") and weekday == 3:
                if (hh == 19 and mm >= 55) or (hh == 20 and mm <= 15):
                    logger.info(
                        f"[CommodityDetector] Suppressing {clean_sym} during Thursday EIA NatGas storage blackout window ({hh:02d}:{mm:02d} IST)"
                    )
                    continue

            # 3. Tuesday API Weekly Crude Inventory (American Petroleum Institute): 20:00 - 20:20 IST
            if clean_sym in ("CRUDEOIL", "CRUDEOILM") and weekday == 1:
                if hh == 20 and mm <= 20:
                    logger.info(
                        f"[CommodityDetector] Suppressing {clean_sym} during Tuesday API crude inventory blackout window ({hh:02d}:{mm:02d} IST)"
                    )
                    continue

        # Golden Hours Window Check (17:30 to 22:30 IST)
        from engine.quality_gate import is_mcx_golden_hours_window

        is_golden_hours = is_mcx_golden_hours_window(now_ist)

        # Minimum move threshold for commodity trigger (0.6% for Gold/Silver/Copper, 1.0% for Crude/NatGas)
        min_chg = 1.0 if clean_sym in ("CRUDEOIL", "CRUDEOILM", "NATURALGAS", "NATGASMINI") else 0.6

        # 20-Bar Donchian Channel Breakout & Wick Rejection Verification on 5m OHLCV
        df_5m = ohlcv_map.get(clean_sym)
        if df_5m is None:
            try:
                from market.history import get_ohlcv

                df_5m = get_ohlcv(clean_sym, exchange="MCX", interval="5minute", days=2)
            except Exception as e:
                logger.debug(f"[CommodityDetector] Error fetching 5m OHLCV for MCX:{clean_sym}: {e}")

        rsi_5m = compute_commodity_rsi(df_5m)

        # US Open Transition Gate (18:15 to 19:15 IST):
        is_us_open_transition = (now_ist.hour == 18 and now_ist.minute >= 15) or (
            now_ist.hour == 19 and now_ist.minute < 15
        )

        is_bullish = False
        is_bearish = False
        is_donchian_breakout = False
        is_utad_bear = False
        is_spring_bull = False
        is_1m_micro_bear = False
        is_1m_micro_bull = False
        poc_price = 0.0
        vah_price = 0.0
        val_price = 0.0
        peak_recent = 0.0
        trough_recent = 0.0
        nearest_round_high = 0.0
        nearest_round_low = 0.0
        rvol = 1.0

        roc_15m = 0.0
        if df_5m is not None and len(df_5m) >= 4:
            try:
                c_ago = float(df_5m.iloc[-4]["close"])
                if c_ago > 0:
                    roc_15m = round(((ltp - c_ago) / c_ago * 100), 2)
            except Exception:
                pass

        # Compute Relative Volume (RVOL) early against 20-bar rolling average
        if df_5m is not None and len(df_5m) >= 20:
            try:
                vols_s = df_5m["volume"] if "volume" in df_5m.columns else df_5m.get("Volume")
                if vols_s is not None and len(vols_s) >= 20:
                    avg_v = float(vols_s.iloc[-21:-1].mean())
                    cur_v = float(df_5m.iloc[-1].get("volume", 0.0) or 0.0)
                    prev_v = (
                        float(df_5m.iloc[-2].get("volume", 0.0) or 0.0)
                        if len(df_5m) >= 2
                        else cur_v
                    )
                    rvol_cur = cur_v / max(1.0, avg_v) if avg_v > 0 else 1.0
                    rvol_prev = prev_v / max(1.0, avg_v) if avg_v > 0 else 1.0
                    rvol = round(max(rvol_prev, rvol_cur), 2)
            except Exception:
                rvol = 1.0

        # Golden Hours Session Momentum: catches US Open breakout / VWAP reclaim (17:30 - 22:30 IST)
        # without requiring full-day 1.0% move from 09:00 AM close
        is_golden_thrust_bull = (
            is_golden_hours
            and (vwap > 0 and ltp >= vwap * 1.001)
            and roc_15m >= 0.25
            and rvol >= 1.10
        )
        is_golden_thrust_bear = (
            is_golden_hours
            and (vwap > 0 and ltp <= vwap * 0.999)
            and roc_15m <= -0.25
            and rvol >= 1.10
        )

        has_bull_chg = (
            (chg_prev >= min_chg)
            or (chg_open >= min_chg)
            or (chg_from_low >= min_chg * 1.2 and roc_15m >= 0.5)
            or is_golden_thrust_bull
        )
        has_bear_chg = (
            (chg_prev <= -min_chg)
            or (chg_open <= -min_chg)
            or (chg_from_high >= min_chg * 1.2 and roc_15m <= -0.5)
            or is_golden_thrust_bear
        )

        # Smart Money Concepts (SMC) & Market Structure Analysis
        smc_report = None
        if df_5m is not None and len(df_5m) >= 14:
            try:
                from analysis.market_structure import analyze_market_structure

                smc_report = analyze_market_structure(
                    clean_sym, df=df_5m, exchange="MCX", timeframe="5m"
                )
            except Exception as e:
                logger.debug(f"[CommodityDetector] SMC analysis error: {e}")

        if df_5m is not None and len(df_5m) >= 20:
            recent_20 = df_5m.iloc[-21:-1]
            prior_high = float(recent_20["high"].max())
            prior_low = float(recent_20["low"].min())
            last_bar = df_5m.iloc[-1]
            cur_open = float(last_bar.get("open", ltp))
            cur_high = max(float(last_bar.get("high", ltp)), ltp)
            cur_low = min(float(last_bar.get("low", ltp)), ltp)
            cur_close = float(last_bar.get("close", ltp))
            bar_range = max(1.0, cur_high - cur_low)

            upper_wick_ratio = (cur_high - max(cur_open, cur_close)) / bar_range
            lower_wick_ratio = (min(cur_open, cur_close) - cur_low) / bar_range
            bull_close_ratio = (cur_close - cur_low) / bar_range
            bear_close_ratio = (cur_high - cur_close) / bar_range

            max_wick = 0.45 if (is_us_open_transition and rvol >= 1.2) else 0.40
            req_bull_close = 0.55 if is_us_open_transition else 0.50
            req_bear_close = 0.55 if is_us_open_transition else 0.50

            # 1. Donchian Breakout
            is_donchian_bull = (
                not is_locked_bull
                and has_bull_chg
                and (ltp >= prior_high * 0.999 or cur_close >= prior_high)
                and upper_wick_ratio <= max_wick
                and bull_close_ratio >= req_bull_close
                and ltp >= vwap * 0.998
            )
            is_donchian_bear = (
                not is_locked_bear
                and has_bear_chg
                and (ltp <= prior_low * 1.001 or cur_close <= prior_low)
                and lower_wick_ratio <= max_wick
                and bear_close_ratio >= req_bear_close
                and ltp <= vwap * 1.002
            )

            # 2. VWAP Trend Continuation
            is_vwap_trend_bull = (
                not is_locked_bull
                and has_bull_chg
                and ltp >= vwap * 1.001
                and cur_close >= cur_open
                and upper_wick_ratio <= max_wick
                and bull_close_ratio >= 0.45
                and rvol >= 1.05
            )
            is_vwap_trend_bear = (
                not is_locked_bear
                and has_bear_chg
                and ltp <= vwap * 0.999
                and cur_close <= cur_open
                and lower_wick_ratio <= max_wick
                and bear_close_ratio >= 0.45
                and rvol >= 1.05
            )

            # 3. SMC Structural Confluence
            is_smc_bull = False
            is_smc_bear = False
            if smc_report is not None:
                has_smc_bull_trigger = (
                    (smc_report.bos_detected and smc_report.bos_type == "BULLISH_BOS")
                    or (smc_report.choch_detected and smc_report.choch_type == "BULLISH_CHOCH")
                    or (
                        smc_report.liquidity_sweeps
                        and any(s.type == "BULLISH_SWEEP" for s in smc_report.liquidity_sweeps)
                    )
                    or (
                        smc_report.active_demand_zones
                        and smc_report.regime in ("BULLISH", "STRONG_BULLISH")
                    )
                    or (smc_report.structure_score >= 60 and ltp >= vwap)
                )
                if (
                    not is_locked_bull
                    and has_smc_bull_trigger
                    and (has_bull_chg or roc_15m >= 0.25)
                    and ltp >= vwap * 0.995
                    and upper_wick_ratio <= 0.50
                ):
                    is_smc_bull = True

                has_smc_bear_trigger = (
                    (smc_report.bos_detected and smc_report.bos_type == "BEARISH_BOS")
                    or (smc_report.choch_detected and smc_report.choch_type == "BEARISH_CHOCH")
                    or (
                        smc_report.liquidity_sweeps
                        and any(s.type == "BEARISH_SWEEP" for s in smc_report.liquidity_sweeps)
                    )
                    or (
                        smc_report.active_supply_zones
                        and smc_report.regime in ("BEARISH", "STRONG_BEARISH")
                    )
                    or (smc_report.structure_score <= -60 and ltp <= vwap)
                )
                if (
                    not is_locked_bear
                    and has_smc_bear_trigger
                    and (has_bear_chg or roc_15m <= -0.25)
                    and ltp <= vwap * 1.005
                    and lower_wick_ratio <= 0.50
                ):
                    is_smc_bear = True

            # 4. Momentum Thrust
            is_thrust_bull = (
                not is_locked_bull
                and has_bull_chg
                and roc_15m >= 0.4
                and ltp >= vwap * 1.001
                and rvol >= 1.10
                and upper_wick_ratio <= max_wick
            )
            is_thrust_bear = (
                not is_locked_bear
                and has_bear_chg
                and roc_15m <= -0.4
                and ltp <= vwap * 0.999
                and rvol >= 1.10
                and lower_wick_ratio <= max_wick
            )

            # 5. Wyckoff UTAD (Upthrust After Distribution) & Spring Structural Reversals
            # Catches false breakouts piercing resistance / round strikes that violently fail back inside.
            lookback_bars = df_5m.iloc[-6:] if len(df_5m) >= 6 else df_5m
            peak_recent = float(lookback_bars["high"].max())
            trough_recent = float(lookback_bars["low"].min())

            # Round number strike inflection levels (e.g. 8800 on Crude, 250 on Natgas)
            strike_step = 50.0 if clean_sym in ("CRUDEOIL", "CRUDEOILM") else (
                100.0 if "GOLD" in clean_sym else (500.0 if "SILVER" in clean_sym else 1.0)
            )
            nearest_round_high = round(peak_recent / strike_step) * strike_step if peak_recent > 0 else 0.0
            nearest_round_low = round(trough_recent / strike_step) * strike_step if trough_recent > 0 else 0.0

            # Sub-Candle 1m Micro-Rejection Trigger:
            # Eliminates the 2-5 min 5m-candle close lag during fast institutional liquidity sweeps.
            df_1m = ohlcv_1m_map.get(clean_sym) if ohlcv_1m_map else None
            if (
                df_1m is None
                and is_authentic_live
                and is_golden_hours
                and clean_sym in ("CRUDEOIL", "CRUDEOILM", "NATURALGAS", "NATGASMINI", "GOLD", "GOLDM")
            ):
                near_high_probe = (
                    (nearest_round_high > 0 and abs(ltp - nearest_round_high) <= (ltp * 0.004))
                    or (peak_recent > 0 and abs(ltp - peak_recent) <= (ltp * 0.004))
                )
                near_low_probe = (
                    (nearest_round_low > 0 and abs(ltp - nearest_round_low) <= (ltp * 0.004))
                    or (trough_recent > 0 and abs(ltp - trough_recent) <= (ltp * 0.004))
                )
                if near_high_probe or near_low_probe:
                    try:
                        from market.history import get_ohlcv

                        df_1m = get_ohlcv(clean_sym, exchange="MCX", interval="1m", days=1)
                    except Exception as e_1m:
                        logger.debug(f"[CommodityDetector] Error fetching 1m OHLCV for {clean_sym}: {e_1m}")

            if df_1m is not None and len(df_1m) >= 2:
                try:
                    recent_1m = df_1m.iloc[-5:] if len(df_1m) >= 5 else df_1m
                    high_1m_max = float(recent_1m["high"].max())
                    low_1m_min = float(recent_1m["low"].min())
                    last_1m = df_1m.iloc[-1]
                    m_open = float(last_1m.get("open", ltp))
                    m_high = max(float(last_1m.get("high", ltp)), ltp)
                    m_low = min(float(last_1m.get("low", ltp)), ltp)
                    m_close = float(last_1m.get("close", ltp))
                    m_range = max(0.5, m_high - m_low)
                    m_uwick = (m_high - max(m_open, m_close)) / m_range
                    m_lwick = (min(m_open, m_close) - m_low) / m_range

                    # Micro Bearish Rejection (UTAD):
                    poked_high_1m = (
                        high_1m_max >= prior_high * 0.9995
                        or (nearest_round_high > 0 and high_1m_max >= nearest_round_high)
                        or (peak_recent > 0 and high_1m_max >= peak_recent * 0.9995)
                    )
                    if (
                        poked_high_1m
                        and (ltp <= nearest_round_high or (prior_high > 0 and ltp <= prior_high * 0.999) or ltp < high_1m_max)
                        and (m_close <= m_open or ltp <= m_open or m_uwick >= 0.30)
                        and ltp < high_1m_max
                    ):
                        is_1m_micro_bear = True

                    # Micro Bullish Reclaim (Spring):
                    poked_low_1m = (
                        low_1m_min <= prior_low * 1.0005
                        or (nearest_round_low > 0 and low_1m_min <= nearest_round_low)
                        or (trough_recent > 0 and low_1m_min <= trough_recent * 1.0005)
                    )
                    if (
                        poked_low_1m
                        and (ltp >= nearest_round_low or (prior_low > 0 and ltp >= prior_low * 1.001) or ltp > low_1m_min)
                        and (m_close >= m_open or ltp >= m_open or m_lwick >= 0.30)
                        and ltp > low_1m_min
                    ):
                        is_1m_micro_bull = True
                except Exception as e_1m_calc:
                    logger.debug(f"[CommodityDetector] 1m micro-rejection calc error: {e_1m_calc}")

            # UTAD: Poked above prior_high or round strike (e.g. 8824 >= 8800), then failed back below on volume
            has_utad_poke = (
                (peak_recent >= prior_high * 0.9995 or peak_recent >= nearest_round_high or is_1m_micro_bear)
                and (peak_recent > ltp or is_1m_micro_bear)
            )
            if (
                not is_locked_bear
                and has_utad_poke
                and (ltp <= nearest_round_high or ltp <= prior_high * 0.998 or is_1m_micro_bear)
                and (cur_close <= cur_open or ltp <= cur_open or is_1m_micro_bear)
                and (bear_close_ratio >= 0.45 or upper_wick_ratio >= 0.35 or is_1m_micro_bear)
                and (roc_15m <= -0.15 or is_1m_micro_bear)
                and (rvol >= 1.10 or is_1m_micro_bear)
            ):
                is_utad_bear = True

            # Spring: Poked below prior_low or round strike, then reclaimed above on volume
            has_spring_poke = (
                (trough_recent <= prior_low * 1.0005 or trough_recent <= nearest_round_low or is_1m_micro_bull)
                and (trough_recent < ltp or is_1m_micro_bull)
            )
            if (
                not is_locked_bull
                and has_spring_poke
                and (ltp >= nearest_round_low or ltp >= prior_low * 1.002 or is_1m_micro_bull)
                and (cur_close >= cur_open or ltp >= cur_open or is_1m_micro_bull)
                and (bull_close_ratio >= 0.45 or lower_wick_ratio >= 0.35 or is_1m_micro_bull)
                and (roc_15m >= 0.15 or is_1m_micro_bull)
                and (rvol >= 1.10 or is_1m_micro_bull)
            ):
                is_spring_bull = True

            # US Open Transition Gate (18:15 to 19:15 IST):
            transition_gate_passed = (
                (not is_us_open_transition)
                or (rvol >= 1.10)
                or is_donchian_bull
                or is_donchian_bear
                or is_smc_bull
                or is_smc_bear
                or is_utad_bear
                or is_spring_bull
            )

            if transition_gate_passed:
                if is_donchian_bull or is_vwap_trend_bull or is_smc_bull or is_thrust_bull or is_spring_bull:
                    is_bullish = True
                    is_donchian_breakout = is_donchian_bull
                elif is_donchian_bear or is_vwap_trend_bear or is_smc_bear or is_thrust_bear or is_utad_bear:
                    is_bearish = True
                    is_donchian_breakout = is_donchian_bear

            # Golden Hours (17:30 - 22:30 IST) Trend-Following Invariant:
            # During the US active pit session, strictly veto counter-trend bets against VWAP,
            # UNLESS a confirmed Wyckoff UTAD or Spring structural reversal is triggered.
            if is_golden_hours and has_real_vwap:
                if ltp >= vwap * 1.001 and not is_utad_bear:
                    is_bearish = False  # Strictly ban counter-trend shorts / PE buys above VWAP
                elif ltp <= vwap * 0.999 and not is_spring_bull:
                    is_bullish = False  # Strictly ban counter-trend longs / CE buys below VWAP
        else:
            strict_min_chg = max(min_chg * 1.2, 0.9)
            has_real_vwap_diff = (vwap > 0) and (abs(ltp - vwap) >= 2.0)
            is_bull_thrust = (
                (chg_prev >= strict_min_chg)
                or (chg_open >= strict_min_chg)
                or (chg_from_low >= strict_min_chg * 1.2)
            )
            is_bear_thrust = (
                (chg_prev <= -strict_min_chg)
                or (chg_open <= -strict_min_chg)
                or (chg_from_high >= strict_min_chg * 1.2)
            )
            if has_real_vwap_diff:
                is_bullish = not is_locked_bull and is_bull_thrust and (ltp >= (vwap * 0.998))
                is_bearish = not is_locked_bear and is_bear_thrust and (ltp <= (vwap * 1.002))
            else:
                is_bullish = not is_locked_bull and is_bull_thrust
                is_bearish = not is_locked_bear and is_bear_thrust

            # Golden Hours Trend Invariant for fallback branch as well
            if is_golden_hours and has_real_vwap_diff:
                if ltp >= vwap * 1.001 and not is_utad_bear:
                    is_bearish = False
                elif ltp <= vwap * 0.999 and not is_spring_bull:
                    is_bullish = False

        if not (is_bullish or is_bearish):
            continue

        # Eagle RSI Momentum Corridor Gate (Live market only: reject true exhaustion tops & oversold washouts)
        if is_authentic_live and rsi_5m is not None:
            has_bearish_div = bool(smc_report and smc_report.divergence_bias == "BEARISH")
            has_bullish_div = bool(smc_report and smc_report.divergence_bias == "BULLISH")
            is_breakout_thrust = is_donchian_breakout or is_thrust_bull or is_smc_bull

            # Natural Gas mean-reverts violently near round numbers; enforce tighter RSI bounds (68.0 max)
            # Crude Oil / Bullion breakout ceiling capped at 74.0 to prevent top-tick exhaustion FOMO entries
            max_bull_rsi = 68.0 if clean_sym in ("NATURALGAS", "NATGASMINI") else (74.0 if is_breakout_thrust else 70.0)
            min_bear_rsi = 32.0 if clean_sym in ("NATURALGAS", "NATGASMINI") else (18.0 if (is_donchian_bear or is_thrust_bear or is_smc_bear) else 26.0)

            if is_bullish and (rsi_5m > max_bull_rsi or (rsi_5m > 66.0 and has_bearish_div)):
                logger.debug(
                    f"[CommodityDetector] Suppressed bullish {clean_sym}: Overbought RSI ({rsi_5m:.1f} > {max_bull_rsi}) exhaustion/divergence risk"
                )
                continue
            elif is_bearish and (rsi_5m < min_bear_rsi or (rsi_5m < 32.0 and has_bullish_div)):
                logger.debug(
                    f"[CommodityDetector] Suppressed bearish {clean_sym}: Oversold RSI ({rsi_5m:.1f} < {min_bear_rsi}) washout/divergence risk"
                )
                continue

        # Global Macro Pre-Filter (Live market only: DXY for Bullion, Brent for Crude Oil)
        if is_authentic_live:
            try:
                from market.macro import get_macro_snapshot

                macro_snap = get_macro_snapshot()
                if macro_snap:
                    if clean_sym in ("GOLD", "GOLDM", "SILVER", "SILVERM"):
                        dxy_chg = macro_snap.dxy_change
                        if dxy_chg is not None:
                            if is_bullish and dxy_chg >= 0.25:
                                logger.debug(
                                    f"[CommodityDetector] Bullish {clean_sym} vetoed by surging DXY (+{dxy_chg:.2f}%)"
                                )
                                continue
                            elif is_bearish and dxy_chg <= -0.25:
                                logger.debug(
                                    f"[CommodityDetector] Bearish {clean_sym} vetoed by collapsing DXY ({dxy_chg:.2f}%)"
                                )
                                continue
                    elif clean_sym in ("CRUDEOIL", "CRUDEOILM"):
                        brent_chg = macro_snap.crude_change
                        if brent_chg is not None:
                            if is_bullish and brent_chg <= -1.2:
                                logger.debug(
                                    f"[CommodityDetector] Bullish {clean_sym} vetoed by collapsing Brent ({brent_chg:.2f}%)"
                                )
                                continue
                            elif is_bearish and brent_chg >= 1.2:
                                logger.debug(
                                    f"[CommodityDetector] Bearish {clean_sym} vetoed by surging Brent (+{brent_chg:.2f}%)"
                                )
                                continue
                    elif clean_sym in ("NATURALGAS", "NATGASMINI"):
                        ng_chg = getattr(macro_snap, "natural_gas_change", None)
                        if ng_chg is not None:
                            if is_bullish and ng_chg <= -2.0:
                                logger.debug(
                                    f"[CommodityDetector] Bullish {clean_sym} vetoed by collapsing Henry Hub NatGas ({ng_chg:.2f}%)"
                                )
                                continue
                            elif is_bearish and ng_chg >= 2.0:
                                logger.debug(
                                    f"[CommodityDetector] Bearish {clean_sym} vetoed by surging Henry Hub NatGas (+{ng_chg:.2f}%)"
                                )
                                continue
            except Exception as e:
                logger.debug(f"[CommodityDetector] Macro snapshot check exception: {e}")

        # Noise-Safe Quantitative Volatility Risk
        atr_calc = None
        if df_5m is not None and len(df_5m) >= 14:
            try:
                highs_s = df_5m["high"] if "high" in df_5m.columns else df_5m["High"]
                lows_s = df_5m["low"] if "low" in df_5m.columns else df_5m["Low"]
                closes_s = df_5m["close"] if "close" in df_5m.columns else df_5m["Close"]
                tr1 = highs_s - lows_s
                tr2 = (highs_s - closes_s.shift(1)).abs()
                tr3 = (lows_s - closes_s.shift(1)).abs()
                tr_s = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
                atr_calc = float(tr_s.rolling(14).mean().iloc[-1])
            except Exception:
                atr_calc = None

        is_energy = clean_sym in ("CRUDEOIL", "CRUDEOILM", "NATURALGAS", "NATGASMINI")
        min_vol_pct = 0.008 if is_energy else 0.005
        min_noise_floor_pts = round(ltp * min_vol_pct, 1)
        base_atr = atr_calc if (atr_calc and atr_calc > 0) else min_noise_floor_pts

        from engine.alert_scrutiny import COMMODITY_MIN_SL_FLOORS

        min_structural_pts = COMMODITY_MIN_SL_FLOORS.get(clean_sym, round(ltp * min_vol_pct, 1))

        # Institutional Smart Money Concepts (SMC) & Price Action Confluence
        # Institutional Smart Money Concepts (SMC) & Price Action Confluence
        smc_tags: list[str] = []
        if smc_report:
            if smc_report.bos_detected:
                if is_bullish and smc_report.bos_type == "BULLISH_BOS":
                    smc_tags.append("SMC Bullish BOS")
                elif is_bearish and smc_report.bos_type == "BEARISH_BOS":
                    smc_tags.append("SMC Bearish BOS")
            if smc_report.choch_detected:
                if is_bullish and smc_report.choch_type == "BULLISH_CHOCH":
                    smc_tags.append("SMC Bullish CHoCH Reversal")
                elif is_bearish and smc_report.choch_type == "BEARISH_CHOCH":
                    smc_tags.append("SMC Bearish CHoCH Reversal")
            if smc_report.liquidity_sweeps:
                sweep_types = [s.type for s in smc_report.liquidity_sweeps]
                if is_bullish and "BULLISH_SWEEP" in sweep_types:
                    smc_tags.append("SMC Liquidity Sweep (Spring Reclaim)")
                elif is_bearish and "BEARISH_SWEEP" in sweep_types:
                    smc_tags.append("SMC Liquidity Sweep (Upthrust Reclaim)")
            if is_bullish and smc_report.active_demand_zones:
                smc_tags.append("Demand Order Block Support")
            elif is_bearish and smc_report.active_supply_zones:
                smc_tags.append("Supply Order Block Resistance")
            if is_bullish and getattr(smc_report, "in_discount_zone", False):
                smc_tags.append("Discount Zone (≤50% Eq)")

        # Candlestick Patterns
        if df_5m is not None and len(df_5m) >= 2:
            try:
                last_b = df_5m.iloc[-1]
                prev_b = df_5m.iloc[-2]
                c_o = float(last_b.get("open", ltp))
                c_c = float(last_b.get("close", ltp))
                c_h = float(last_b.get("high", ltp))
                c_l = float(last_b.get("low", ltp))
                p_o = float(prev_b.get("open", ltp))
                p_c = float(prev_b.get("close", ltp))
                b_range = max(0.5, c_h - c_l)

                u_wick = (c_h - max(c_o, c_c)) / b_range
                l_wick = (min(c_o, c_c) - c_l) / b_range
                if is_bullish and l_wick >= 0.45 and (c_c >= c_o):
                    smc_tags.append("Hammer / Absorption Wick")
                elif is_bearish and u_wick >= 0.45 and (c_c <= c_o):
                    smc_tags.append("Shooting Star / Rejection Wick")

                if is_bullish and (c_c > c_o) and (p_c < p_o) and (c_c >= p_o) and (c_o <= p_c):
                    smc_tags.append("Bullish Engulfing Expansion")
                elif is_bearish and (c_c < c_o) and (p_c > p_o) and (c_c <= p_o) and (c_o >= p_c):
                    smc_tags.append("Bearish Engulfing Expansion")
            except Exception:
                pass

        if smc_report is not None:
            if smc_report.confirmation_confirmed and smc_report.confirmation_candle:
                smc_tags.append(f"Confirmed: {smc_report.confirmation_candle}")

            if smc_report.divergence_type and smc_report.divergence_bias:
                div_bias = smc_report.divergence_bias
                div_type = smc_report.divergence_type
                if (is_bullish and div_bias == "BULLISH") or (is_bearish and div_bias == "BEARISH"):
                    smc_tags.append(f"RSI Divergence ({div_type.replace('_', ' ').title()})")
                elif (is_bullish and div_bias == "BEARISH") or (
                    is_bearish and div_bias == "BULLISH"
                ):
                    if rvol < 1.5:
                        logger.info(
                            f"[CommodityDetector] ⚠️ Contra divergence ({div_type}) on {clean_sym} — RVOL {rvol:.1f}x below 1.5x threshold; suppressing."
                        )
                        is_bullish = False
                        is_bearish = False

        if smc_report and smc_report.setup_type in (
            "PULLBACK_RETEST",
            "BOTTOM_FISHING_SPRING",
            "TOP_FISHING_UTAD",
        ):
            if smc_report.confirmation_confirmed is False and rvol < 1.5:
                if is_bullish or is_bearish:
                    smc_tags.append("⚠️ Awaiting Candle Confirmation")

        # Volume Profile
        if df_5m is not None and len(df_5m) >= 10:
            try:
                from analysis.volume_profile import compute_volume_profile

                poc_price, vah_price, val_price, _ = compute_volume_profile(df_5m, num_bins=10)
                if poc_price > 0 and ltp > 0:
                    poc_dist_pct = abs(ltp - poc_price) / ltp * 100
                    if poc_dist_pct <= 0.30:
                        smc_tags.append(f"POC Magnet (₹{poc_price:,.1f})")
                    if is_bullish:
                        if vah_price > 0 and ltp >= vah_price * 0.999:
                            smc_tags.append(f"Breaking VAH ₹{vah_price:,.1f} (Volume Breakout)")
                        elif val_price > 0 and abs(ltp - val_price) / ltp <= 0.003:
                            smc_tags.append(f"VAL Support ₹{val_price:,.1f}")
                    elif is_bearish:
                        if val_price > 0 and ltp <= val_price * 1.001:
                            smc_tags.append(f"Breaking VAL ₹{val_price:,.1f} (Volume Breakdown)")
                        elif vah_price > 0 and abs(ltp - vah_price) / ltp <= 0.003:
                            smc_tags.append(f"VAH Resistance ₹{vah_price:,.1f}")
            except Exception as e:
                logger.debug(f"[CommodityDetector] Volume profile error for {clean_sym}: {e}")

        # Cumulative Volume Delta (CVD) Footprint Check
        cvd_ratio = 1.0
        if df_5m is not None and len(df_5m) >= 2:
            try:
                from engine.detectors.order_flow import compute_bar_volume_delta

                last_bar = df_5m.iloc[-1]
                b_vol, s_vol, net_delta = compute_bar_volume_delta(
                    float(last_bar.get("open", ltp)),
                    float(last_bar.get("high", ltp)),
                    float(last_bar.get("low", ltp)),
                    float(last_bar.get("close", ltp)),
                    float(last_bar.get("volume", vol)),
                )
                if is_bullish:
                    cvd_ratio = round(b_vol / max(1.0, s_vol), 2)
                    if cvd_ratio >= 2.0:
                        smc_tags.append(f"Buyer CVD Aggression ({cvd_ratio:.1f}x)")
                    elif s_vol > (b_vol * 2.0):
                        if is_spring_bull:
                            smc_tags.append("Institutional Absorption of Sellers (Bear Trap Confirmed)")
                        elif is_authentic_live and rvol < 2.0:
                            logger.info(
                                f"[CommodityDetector] 🛑 Trap candle detected on {clean_sym}: Seller Delta {s_vol:.0f} > 2x Buyer {b_vol:.0f} (Exhaustion Trap); suppressing."
                            )
                            is_bullish = False
                elif is_bearish:
                    cvd_ratio = round(s_vol / max(1.0, b_vol), 2)
                    if cvd_ratio >= 2.0:
                        smc_tags.append(f"Seller CVD Aggression ({cvd_ratio:.1f}x)")
                    elif b_vol > (s_vol * 2.0):
                        if is_utad_bear:
                            smc_tags.append("Institutional Absorption of Buyers (Bull Trap Confirmed)")
                        elif is_authentic_live and rvol < 2.0:
                            logger.info(
                                f"[CommodityDetector] 🛑 Trap candle detected on {clean_sym}: Buyer Delta {b_vol:.0f} > 2x Seller {s_vol:.0f} (Absorption Trap); suppressing."
                            )
                            is_bearish = False
            except Exception as e_cvd:
                logger.debug(f"[CommodityDetector] CVD evaluation error for {clean_sym}: {e_cvd}")

        # Signal Ensemble Gate
        if df_5m is not None and len(df_5m) >= 50:
            try:
                from engine.signal_ensemble import ensemble_signal

                ens = ensemble_signal(df_5m)
                if ens.confidence > 0:
                    if (is_bullish and ens.verdict == "BEARISH" and ens.confidence >= 0.55) or (
                        is_bearish and ens.verdict == "BULLISH" and ens.confidence >= 0.55
                    ):
                        logger.info(
                            f"[CommodityDetector] 🛑 Ensemble VETO on {clean_sym}: Suppressing."
                        )
                        is_bullish = False
                        is_bearish = False
                    elif (is_bullish and ens.verdict == "BULLISH" and ens.confidence >= 0.55) or (
                        is_bearish and ens.verdict == "BEARISH" and ens.confidence >= 0.55
                    ):
                        smc_tags.append(f"Ensemble ✓ ({ens.verdict} {ens.confidence:.0%})")
            except Exception as e:
                logger.debug(f"[CommodityDetector] Ensemble signal error for {clean_sym}: {e}")

        if not (is_bullish or is_bearish):
            continue

        if rsi_5m is not None:
            smc_tags.append(f"RSI {rsi_5m:.1f}")

        from engine.commodity_adaptive_regime import (
            evaluate_commodity_adaptive_regime,
            compute_commodity_choppiness_index,
            compute_commodity_adx,
        )

        chop_idx = compute_commodity_choppiness_index(df_5m, period=14)
        adx_14 = compute_commodity_adx(df_5m, period=14)

        if chop_idx is not None:
            if chop_idx <= 38.2:
                smc_tags.append(f"Trending Expansion (CHOP {chop_idx:.1f})")
            elif chop_idx >= 61.8:
                smc_tags.append(f"Consolidation / Chop ({chop_idx:.1f})")

        if adx_14 is not None and adx_14 >= 25.0:
            smc_tags.append(f"Strong Trend (ADX {adx_14:.1f})")

        if rvol >= 1.5:
            smc_tags.append(f"Institutional Surge (RVOL {rvol:.1f}x)")
        elif rvol >= 1.2:
            smc_tags.append(f"Volume Expansion (RVOL {rvol:.1f}x)")

        # Volatility Squeeze Compression & Expansion Fire
        sq_info = detect_commodity_volatility_squeeze(df_5m)
        is_sq_fired = bool(
            sq_info.get("is_squeeze_fired")
            and sq_info.get("squeeze_direction") == ("BULLISH" if is_bullish else "BEARISH")
        )
        if is_sq_fired:
            smc_tags.append(f"TTM Squeeze Expansion Fire ({sq_info.get('squeeze_bars', 0)} bars coiling)")

        if is_utad_bear:
            smc_tags.append(f"Wyckoff UTAD Sweep (₹{peak_recent:,.1f} ➔ Rejection)")
            if is_1m_micro_bear:
                smc_tags.append("1m Micro-Rejection Sweep Confirmed")
        elif is_spring_bull:
            smc_tags.append(f"Wyckoff Spring Reclaim (₹{trough_recent:,.1f} ➔ Absorption)")
            if is_1m_micro_bull:
                smc_tags.append("1m Micro-Reclaim Sweep Confirmed")

        # Multi-Timeframe (MTF) Alignment & HTF Resistance Wall Check
        mtf_data = None
        if df_5m is not None and len(df_5m) >= 20:
            try:
                from analysis.market_structure import check_mtf_structural_alignment

                mtf_data = check_mtf_structural_alignment(
                    clean_sym,
                    exchange="MCX",
                    ltp=ltp,
                    direction="BULLISH" if is_bullish else "BEARISH",
                    df_5m=df_5m,
                )
            except Exception as e_mtf:
                logger.debug(f"[CommodityDetector] MTF check exception: {e_mtf}")

        if mtf_data:
            if mtf_data.get("wall_collision") and rvol < 1.8 and is_authentic_live:
                logger.info(
                    f"[CommodityDetector] 🛑 Suppressed {clean_sym}: 1H structural wall collision within {mtf_data.get('distance_pct', 0.0)}% and RVOL {rvol}x < 1.8x."
                )
                continue
            mtf_align_count = mtf_data.get("alignment_count", 0)
            if mtf_align_count >= 2:
                smc_tags.append(f"MTF Trend Aligned ({mtf_align_count}/3)")

        noise_safe_pts = max(base_atr * 1.5, min_structural_pts, min_noise_floor_pts)
        if smc_report and smc_report.invalidation_level and smc_report.invalidation_level > 0:
            smc_inval_pts = abs(ltp - smc_report.invalidation_level)
            if smc_inval_pts >= min_structural_pts:
                noise_safe_pts = max(noise_safe_pts, round(smc_inval_pts, 1))

        risk_pts = round(max(1.0, noise_safe_pts), 1)
        atr = round(base_atr, 1)
        direction = "BULLISH" if is_bullish else "BEARISH"
        alert_type = "COMMODITY_MOMENTUM"
        from engine.alert_identity import generate_alert_id

        alert_id = generate_alert_id(clean_sym, alert_type, variant=direction.lower())

        from engine.position_sizer import get_lot_size

        lot_sz = get_lot_size(clean_sym) or 1
        has_real_vwap = abs(ltp - vwap) >= 2.0 and vwap != ltp
        chase_pts = get_commodity_max_chase(clean_sym, risk_pts)

        if is_bullish:
            sl_price = round(ltp - risk_pts, 2)
            default_t1 = round(ltp + 2.8 * risk_pts, 2)
            default_t2 = round(ltp + 5.0 * risk_pts, 2)
            default_t3 = round(ltp + 8.0 * risk_pts, 2)

            # Volume Profile rotation: Target 1 = Session POC, Target 2 = VAH
            if (is_spring_bull or is_donchian_breakout) and poc_price > 0 and (poc_price - ltp) >= (1.0 * risk_pts):
                t1_price = round(poc_price, 2)
                t2_price = round(vah_price, 2) if (vah_price > 0 and vah_price > poc_price and (vah_price - ltp) >= (2.0 * risk_pts)) else default_t2
                t3_price = round(max(default_t3, t2_price + 2.0 * risk_pts), 2)
            else:
                t1_price = default_t1
                t2_price = default_t2
                t3_price = default_t3
            no_chase = round(ltp + chase_pts, 2)

            retest_anchor = prior_high if (is_donchian_breakout and "prior_high" in locals()) else vwap
            is_extended = bool(retest_anchor > 0 and (ltp > retest_anchor + 0.30 * risk_pts))

            if is_extended:
                e_low = round(max(sl_price + 0.5, retest_anchor), 1)
                e_high = round(min(no_chase - 0.1, retest_anchor + 0.20 * risk_pts), 1)
                if e_high <= e_low:
                    e_high = round(retest_anchor + 0.15 * risk_pts, 1)
                    e_low = round(max(sl_price + 0.5, retest_anchor - 0.05 * risk_pts), 1)
                when_buy_action = f"Await 5m pullback/retest into ₹{e_low:,.1f} – ₹{e_high:,.1f} (prior resistance turned support). Avoid chasing at extended highs to lock in 1:3.5+ R:R."
            else:
                e_low = round(max(sl_price + 0.5, ltp - 0.20 * risk_pts), 1)
                e_high = round(min(no_chase - 0.1, ltp + 0.15 * risk_pts), 1)
                if e_high <= e_low:
                    e_high = round(no_chase - 0.05, 1)
                    e_low = round(max(sl_price + 0.5, ltp - 0.10 * risk_pts), 1)
                when_buy_action = f"Enter on 5m candle closing in direction above/below VWAP ₹{vwap:,.1f}."

            if is_sq_fired:
                headline = f"⚡ MCX SQUEEZE EXPANSION: {clean_sym} +{chg:.1f}% Fire (₹{ltp:,.1f})"
                summary = f"Institutional volatility expansion in {clean_sym}: Coiling squeeze fired bullishly. Trading at ₹{ltp:,.1f} (+{chg:.1f}%) with VWAP support at ₹{vwap:,.1f}."
            elif is_donchian_breakout:
                headline = (
                    f"🛢️ MCX BREAKOUT: {clean_sym} +{chg:.1f}% Breaking 20-bar High (₹{ltp:,.1f})"
                )
                summary = f"Institutional breakout in {clean_sym}: Trading at ₹{ltp:,.1f} (+{chg:.1f}%). 20-bar 5m Donchian high broken with VWAP support at ₹{vwap:,.1f}."
            elif smc_report and (smc_report.bos_detected or smc_report.choch_detected or smc_report.liquidity_sweeps):
                smc_name = "BOS" if smc_report.bos_detected else ("CHoCH" if smc_report.choch_detected else "Liquidity Sweep")
                headline = f"🏛️ MCX SMC {smc_name}: {clean_sym} +{chg:.1f}% @ ₹{ltp:,.1f}"
                summary = f"Institutional Smart Money structure in {clean_sym}: {smc_name} confirmed at ₹{ltp:,.1f} (+{chg:.1f}%). VWAP support at ₹{vwap:,.1f}."
            elif has_real_vwap:
                headline = f"MCX MOMENTUM: {clean_sym} +{chg:.1f}% Reclaiming VWAP (₹{vwap:,.1f})"
                summary = f"Institutional breakout in {clean_sym}: Trading at ₹{ltp:,.1f} (+{chg:.1f}%). VWAP support at ₹{vwap:,.1f}."
            else:
                headline = f"MCX MOMENTUM: {clean_sym} +{chg:.1f}% Breakout @ ₹{ltp:,.1f}"
                summary = f"Institutional breakout in {clean_sym}: Trading at ₹{ltp:,.1f} (+{chg:.1f}%). Session momentum active."
            action = "BUY_FUTURES"
        else:
            sl_price = round(ltp + risk_pts, 2)
            default_t1 = round(ltp - 2.8 * risk_pts, 2)
            default_t2 = round(ltp - 5.0 * risk_pts, 2)
            default_t3 = round(ltp - 8.0 * risk_pts, 2)

            # Volume Profile rotation: Target 1 = Session POC, Target 2 = VAL
            if (is_utad_bear or is_donchian_breakout) and poc_price > 0 and (ltp - poc_price) >= (1.0 * risk_pts):
                t1_price = round(poc_price, 2)
                t2_price = round(val_price, 2) if (val_price > 0 and poc_price > val_price and (ltp - val_price) >= (2.0 * risk_pts)) else default_t2
                t3_price = round(min(default_t3, t2_price - 2.0 * risk_pts), 2)
            else:
                t1_price = default_t1
                t2_price = default_t2
                t3_price = default_t3
            no_chase = round(ltp - chase_pts, 2)

            retest_anchor = prior_low if (is_donchian_breakout and "prior_low" in locals()) else vwap
            is_extended = bool(retest_anchor > 0 and (ltp < retest_anchor - 0.30 * risk_pts))

            if is_extended:
                e_high = round(min(sl_price - 0.5, retest_anchor), 1)
                e_low = round(max(no_chase + 0.1, retest_anchor - 0.20 * risk_pts), 1)
                if e_low >= e_high:
                    e_low = round(retest_anchor - 0.15 * risk_pts, 1)
                    e_high = round(min(sl_price - 0.5, retest_anchor + 0.05 * risk_pts), 1)
                when_sell_action = f"Await 5m bounce/retest into ₹{e_low:,.1f} – ₹{e_high:,.1f} (prior support turned resistance). Avoid chasing at extended breakdown lows to lock in 1:3.5+ R:R."
            else:
                e_high = round(min(sl_price - 0.5, ltp + 0.20 * risk_pts), 1)
                e_low = round(max(no_chase + 0.1, ltp - 0.15 * risk_pts), 1)
                if e_low >= e_high:
                    e_low = round(no_chase + 0.05, 1)
                    e_high = round(min(sl_price - 0.5, ltp + 0.10 * risk_pts), 1)
                when_sell_action = f"Enter on 5m candle closing in breakdown direction below VWAP ₹{vwap:,.1f}."

            if is_sq_fired:
                headline = f"⚡ MCX SQUEEZE EXPANSION: {clean_sym} {chg:.1f}% Fire (₹{ltp:,.1f})"
                summary = f"Institutional volatility breakdown in {clean_sym}: Coiling squeeze fired bearishly. Trading at ₹{ltp:,.1f} ({chg:.1f}%) below VWAP ₹{vwap:,.1f}."
            elif is_donchian_breakout:
                headline = (
                    f"🛢️ MCX BREAKDOWN: {clean_sym} {chg:.1f}% Breaking 20-bar Low (₹{ltp:,.1f})"
                )
                summary = f"Institutional breakdown in {clean_sym}: Trading at ₹{ltp:,.1f} ({chg:.1f}%). 20-bar 5m Donchian low broken below VWAP ₹{vwap:,.1f}."
            elif smc_report and (smc_report.bos_detected or smc_report.choch_detected or smc_report.liquidity_sweeps):
                smc_name = "BOS" if smc_report.bos_detected else ("CHoCH" if smc_report.choch_detected else "Liquidity Sweep")
                headline = f"🏛️ MCX SMC {smc_name}: {clean_sym} {chg:.1f}% @ ₹{ltp:,.1f}"
                summary = f"Institutional Smart Money breakdown in {clean_sym}: {smc_name} confirmed at ₹{ltp:,.1f} ({chg:.1f}%). Below VWAP ₹{vwap:,.1f}."
            elif has_real_vwap:
                headline = f"MCX BREAKDOWN: {clean_sym} {chg:.1f}% Lost VWAP (₹{vwap:,.1f})"
                summary = f"Severe session weakness in {clean_sym}: Trading at ₹{ltp:,.1f} ({chg:.1f}%). Broken below VWAP ₹{vwap:,.1f}."
            else:
                headline = f"MCX BREAKDOWN: {clean_sym} {chg:.1f}% Drop @ ₹{ltp:,.1f}"
                summary = f"Severe session weakness in {clean_sym}: Trading at ₹{ltp:,.1f} ({chg:.1f}%). Session selling active."
            action = "SELL_SHORT_FUTURES"

        # Empirical mathematical R:R calculation
        rr_ratio_t1 = round(abs(t1_price - ltp) / max(0.01, abs(ltp - sl_price)), 1)
        rr_str = f"1:{rr_ratio_t1}"

        # Resolve defined-risk options contract only for liquid MCX commodities
        opt_recommendation = None
        readable_contract = None
        is_synthetic_options = False

        if clean_sym in LIQUID_COMMODITY_OPTIONS:
            try:
                from market.options import get_options_chain, format_readable_option_symbol
                from brokers.session import get_data_broker_key

                broker_key = (get_data_broker_key() or "").lower()

                chain = get_options_chain(clean_sym)
                is_mock_chain = (
                    any(type(c).__name__ == "MagicMock" for c in chain) if chain else False
                )
                is_test_env = (
                    os.environ.get("CHANAKYA_TESTING") == "1"
                    or os.environ.get("DEPLOY_MODE") == "test"
                )

                # If broker doesn't feed MCX, chain is synthetic Black-76 theoretical pricing
                is_synthetic_options = (
                    not is_mock_chain
                    and not is_test_env
                    and (
                        broker_key in ("mstock", "")
                        or getattr(q, "source", "") == "FALLBACK"
                        or getattr(q, "provider", "") == "yfinance"
                    )
                )

                opt_type = "CE" if is_bullish else "PE"
                filtered = [
                    c
                    for c in chain
                    if getattr(c, "option_type", "") == opt_type
                    and float(getattr(c, "last_price", 0.0) or 0.0) > 0
                ]
                if filtered:
                    atm_band = ltp * 0.03
                    atm_candidates = [
                        c
                        for c in filtered
                        if abs(float(getattr(c, "strike", 0.0)) - ltp) <= atm_band
                        and float(getattr(c, "last_price", 0.0)) >= 1.0
                    ]
                    candidates = atm_candidates if atm_candidates else filtered
                    target_strike = (
                        nearest_round_high
                        if (is_utad_bear and nearest_round_high > 0)
                        else (
                            nearest_round_low
                            if (is_spring_bull and nearest_round_low > 0)
                            else ltp
                        )
                    )
                    candidates.sort(key=lambda c: abs(float(getattr(c, "strike", 0.0)) - target_strike))
                    closest_opt = candidates[0]

                    strike_val = float(getattr(closest_opt, "strike", 0.0))
                    moneyness_pct = (
                        (ltp - strike_val) / ltp * 100
                        if is_bullish
                        else (strike_val - ltp) / ltp * 100
                    )
                    if -1.0 <= moneyness_pct <= 1.0:
                        delta_tier = "ATM (Δ≈0.50)"
                    elif moneyness_pct > 1.0:
                        delta_tier = "ITM (Δ>0.50)"
                    else:
                        delta_tier = "OTM (Δ<0.40)"

                    dte_warning = None
                    try:
                        expiry = getattr(closest_opt, "expiry", None)
                        if expiry:
                            from datetime import date as _date

                            exp_date = (
                                expiry
                                if isinstance(expiry, _date)
                                else _date.fromisoformat(str(expiry)[:10])
                            )
                            dte = (exp_date - _date.today()).days
                            if dte <= 5:
                                dte_warning = f"⚠️ THETA RISK: Only {dte} DTE — rapid premium decay."
                    except Exception:
                        pass

                    opt_prem = float(getattr(closest_opt, "last_price", 0.0))
                    opt_risk = round(max(1.0, min(opt_prem * 0.35, risk_pts * 0.52)), 1)
                    opt_sl = round(max(0.05, opt_prem - opt_risk), 1)
                    opt_t1 = round(opt_prem + 3.0 * opt_risk, 1)
                    opt_t2 = round(opt_prem + 5.0 * opt_risk, 1)
                    opt_runner = round(opt_prem + 7.5 * opt_risk, 1)
                    opt_no_chase = round(opt_prem + 0.15 * opt_risk, 1)

                    opt_rr_calc = round(
                        abs(opt_t1 - opt_prem) / max(0.01, abs(opt_prem - opt_sl)), 1
                    )
                    opt_rr_str = f"1:{opt_rr_calc}"

                    readable_contract = format_readable_option_symbol(
                        closest_opt.symbol,
                        strike=strike_val,
                        option_type=opt_type,
                        expiry=getattr(closest_opt, "expiry", None),
                    )
                    opt_recommendation = {
                        "contract": closest_opt.symbol,
                        "readable_contract": readable_contract,
                        "strike": strike_val,
                        "option_type": opt_type,
                        "ltp": opt_prem,
                        "stop_loss": opt_sl,
                        "target_1": opt_t1,
                        "target_2": opt_t2,
                        "target_3": opt_runner,
                        "runner_target": opt_runner,
                        "no_chase_boundary": opt_no_chase,
                        "risk_reward": opt_rr_str,
                        "max_loss_capped": round(opt_prem * lot_sz, 0),
                        "delta_tier": delta_tier,
                        "dte_warning": dte_warning,
                        "is_synthetic": is_synthetic_options,
                    }
            except Exception as e:
                logger.debug(f"[CommodityDetector] Options chain resolution error: {e}")
                opt_recommendation = None

        is_institutional_thrust = bool(
            (rvol >= 1.75 and (roc_15m >= 0.35 if is_bullish else roc_15m <= -0.35))
            or (cvd_ratio >= 2.0 and rvol >= 1.4)
            or is_sq_fired
        )

        adaptive_decision = evaluate_commodity_adaptive_regime(
            symbol=clean_sym,
            spot=ltp,
            df_5m=df_5m,
            ref_time=now_ist,
            trigger_level=ltp,
            invalidation_level=sl_price,
            direction=direction,
            is_institutional_thrust=is_institutional_thrust,
            rvol=rvol,
            has_smc_confluence=bool(smc_tags),
            cvd_ratio=cvd_ratio,
            trap_detected=False,
            trap_reason=None,
            opt_recommendation=opt_recommendation,
            lot_size=lot_sz,
            retest_anchor=retest_anchor if "retest_anchor" in locals() else None,
        )

        # 🐅 Pillar 2: Tiger Stalking Gate — Suppress routine breakouts during midday lull or severe chop
        if is_authentic_live and not adaptive_decision.tiger.allow_routine_breakouts:
            logger.info(
                f"[CommodityDetector] 🐅 Tiger Stalking VETO on {clean_sym}: {adaptive_decision.tiger.reason}. Routine breakout suppressed."
            )
            continue

        # 🎯 Pillar 3: Anti-FOMO No-Chase Sniper Gate — Suppress entries if spot is already past No-Chase ceiling
        if is_authentic_live and adaptive_decision.sniper and adaptive_decision.sniper.is_chasing and rvol < 2.5:
            logger.info(
                f"[CommodityDetector] 🛑 FOMO Chase Suppressed on {clean_sym}: Spot ₹{ltp:,.1f} is beyond No-Chase boundary ₹{no_chase:,.1f} with RVOL {rvol:.1f}x < 2.5x."
            )
            continue

        if adaptive_decision.eagle.overall_environment == "OPTIMAL_TREND_EXPANSION":
            smc_tags.append("Eagle: Trend Expansion")
        if adaptive_decision.tiger.mandate == "MOMENTUM_EXPANSION":
            smc_tags.append("Tiger: Institutional Thrust")
        if adaptive_decision.sniper:
            smc_tags.append(
                f"Sniper OTE ₹{adaptive_decision.sniper.entry_zone_min:,.1f}–₹{adaptive_decision.sniper.entry_zone_max:,.1f}"
            )

        confluence_str = (
            " + ".join(smc_tags) if smc_tags else "Donchian Breakout + VWAP Confirmation"
        )

        # Only prioritize option as primary vehicle if liquid AND verified from authentic live feed
        should_use_option_primary = bool(opt_recommendation and not is_synthetic_options)

        if should_use_option_primary:
            opt_contract_name = (
                opt_recommendation.get("readable_contract")
                or readable_contract
                or opt_recommendation["contract"]
            )
            opt_sl = opt_recommendation["stop_loss"]
            opt_t1 = opt_recommendation["target_1"]
            opt_t2 = opt_recommendation["target_2"]
            opt_runner = opt_recommendation.get("target_3", round(opt_recommendation["ltp"] + 7.5 * opt_risk, 1))
            opt_no_chase = opt_recommendation.get("no_chase_boundary", round(opt_recommendation["ltp"] + 0.15 * opt_risk, 1))
            opt_entry_low = round(max(0.5, opt_recommendation["ltp"] - 0.15 * opt_risk), 1)
            opt_entry_high = round(min(opt_no_chase - 0.1, opt_recommendation["ltp"] + 0.10 * opt_risk), 1)
            if opt_entry_high <= opt_entry_low:
                opt_entry_high = round(opt_no_chase - 0.05, 1)

            _delta_tier = opt_recommendation.get("delta_tier", "ATM (Δ≈0.50)")
            _dte_warn = opt_recommendation.get("dte_warning") or ""
            opt_sl_risk = round(abs(opt_recommendation["ltp"] - opt_sl) * lot_sz, 0)
            opt_max_outlay = round(opt_recommendation["ltp"] * lot_sz, 0)
            plan_dict = {
                "action": f"BUY_{opt_type}",
                "segment": "COMMODITY",
                "instrument_type": "OPTION",
                "contract": opt_contract_name,
                "raw_contract": opt_recommendation["contract"],
                "entry_range": f"₹{opt_entry_low:,.1f} – ₹{opt_entry_high:,.1f}",
                "stop_loss": f"₹{opt_sl:,.1f}",
                "target": f"₹{opt_t1:,.1f}",
                "target_1": f"₹{opt_t1:,.1f}",
                "target_2": f"₹{opt_t2:,.1f}",
                "target_3": f"₹{opt_runner:,.1f}",
                "runner_target": f"₹{opt_runner:,.1f}",
                "no_chase_boundary": f"₹{opt_no_chase:,.1f}",
                "risk_reward": opt_recommendation["risk_reward"],
                "lot_size": lot_sz,
                "preferred_vehicle": "DEFINED_RISK_OPTION",
                "delta_tier": _delta_tier,
                "max_loss_capped": opt_max_outlay,
                "setup_confluence": confluence_str,
                "when_to_buy": (
                    (
                        f"Active 1m micro-rejection confirmed after liquidity sweep at ₹{peak_recent:,.1f}. "
                        f"Immediate limit entry in ₹{opt_entry_low:,.1f} – ₹{opt_entry_high:,.1f}."
                        if (is_utad_bear and is_1m_micro_bear)
                        else (
                            f"Active 1m micro-reclaim confirmed after liquidity sweep at ₹{trough_recent:,.1f}. "
                            f"Immediate limit entry in ₹{opt_entry_low:,.1f} – ₹{opt_entry_high:,.1f}."
                            if (is_spring_bull and is_1m_micro_bull)
                            else f"Enter {_delta_tier} {opt_contract_name} on 5m candle closing in breakout direction above/below VWAP ₹{vwap:,.1f}."
                        )
                    )
                    + (f" {_dte_warn}" if _dte_warn else "")
                ),
                "when_to_wait": f"Do not chase if option premium moves beyond ₹{opt_no_chase:,.1f} (Spot above/below ₹{no_chase:,.1f}).",
                "profit_rule": (
                    f"Book 50% at T1 (₹{opt_t1:,.1f}), trail stop to cost, hold 25% for T2 (₹{opt_t2:,.1f}), runner for T3 (₹{opt_runner:,.1f}). "
                    f"SL Risk: ₹{opt_sl_risk:,.0f} per lot (Max capital at risk: ₹{opt_max_outlay:,.0f})."
                ),
                "vehicle_rationale": (
                    f"Defined-risk option vehicle: {_delta_tier} {opt_recommendation['option_type']} "
                    f"caps maximum loss to ₹{opt_max_outlay:,.0f} per lot against sub-ATR noise whipsaws and gap risk."
                ),
                "trade_plan": {
                    "symbol": clean_sym,
                    "direction": "LONG" if is_bullish else "SHORT",
                    "timeframe": "INTRADAY",
                    "entry_price": opt_recommendation["ltp"],
                    "invalidation_stop": opt_sl,
                    "target_1": opt_t1,
                    "target_2": opt_t2,
                    "target_3": opt_runner,
                    "runner_target": opt_runner,
                    "no_chase_boundary": opt_no_chase,
                    "risk_reward": opt_recommendation["risk_reward"],
                },
                "futures_reference": {
                    "contract": f"MCX:{clean_sym}",
                    "entry": ltp,
                    "stop_loss": sl_price,
                    "target_1": t1_price,
                    "target_2": t2_price,
                    "target_3": t3_price,
                    "runner_target": t3_price,
                    "no_chase_boundary": no_chase,
                    "risk_reward": rr_str,
                },
                "option_alternative": opt_recommendation,
            }
            if is_utad_bear:
                headline_prefix = "🎯 MCX SNIPER REVERSAL" if is_1m_micro_bear else "🎯 MCX REVERSAL"
                headline = f"{headline_prefix}: {opt_contract_name} @ ₹{opt_recommendation['ltp']:,.1f} (UTAD Rejection from ₹{peak_recent:,.1f})"
                summary = (
                    f"Wyckoff Liquidity Sweep & UTAD Rejection in {clean_sym} after testing high ₹{peak_recent:,.1f}. "
                    f"Price failed back under ₹{nearest_round_high:,.1f} on heavy institutional selling volume (RVOL {rvol:.1f}x). "
                    f"Preferred Vehicle: {opt_contract_name} @ ₹{opt_recommendation['ltp']:,.1f} with capped risk ₹{opt_max_outlay:,.0f}. "
                    f"Confluence: {confluence_str}."
                )
            elif is_spring_bull:
                headline_prefix = "🎯 MCX SNIPER REVERSAL" if is_1m_micro_bull else "🎯 MCX REVERSAL"
                headline = f"{headline_prefix}: {opt_contract_name} @ ₹{opt_recommendation['ltp']:,.1f} (Spring Reclaim from ₹{trough_recent:,.1f})"
                summary = (
                    f"Wyckoff Spring & Bear Trap Reclaim in {clean_sym} after undercutting low ₹{trough_recent:,.1f}. "
                    f"Price reclaimed ₹{nearest_round_low:,.1f} on high buying volume (RVOL {rvol:.1f}x). "
                    f"Preferred Vehicle: {opt_contract_name} @ ₹{opt_recommendation['ltp']:,.1f} with capped risk ₹{opt_max_outlay:,.0f}. "
                    f"Confluence: {confluence_str}."
                )
            else:
                headline = f"🛢️ MCX OPTION: {opt_contract_name} @ ₹{opt_recommendation['ltp']:,.1f} ({'Breakout' if is_bullish else 'Breakdown'} @ ₹{ltp:,.1f})"
                summary = (
                    f"Institutional {'breakout' if is_bullish else 'breakdown'} in {clean_sym} ({chg:+.1f}%). "
                    f"Preferred Vehicle: {opt_contract_name} @ ₹{opt_recommendation['ltp']:,.1f} with capped risk ₹{opt_max_outlay:,.0f}. "
                    f"Confluence: {confluence_str}."
                )
        else:
            fut_risk = round(risk_pts * lot_sz, 0)
            plan_dict = {
                "action": action,
                "segment": "COMMODITY",
                "instrument_type": "FUTURES",
                "contract": f"MCX:{clean_sym}",
                "entry_range": f"₹{e_low:,.1f} – ₹{e_high:,.1f}",
                "stop_loss": f"₹{sl_price:,.1f}",
                "target": f"₹{t1_price:,.1f}",
                "target_1": f"₹{t1_price:,.1f}",
                "target_2": f"₹{t2_price:,.1f}",
                "target_3": f"₹{t3_price:,.1f}",
                "runner_target": f"₹{t3_price:,.1f}",
                "no_chase_boundary": f"₹{no_chase:,.1f}",
                "risk_reward": rr_str,
                "lot_size": lot_sz,
                "preferred_vehicle": "FUTURES",
                "setup_confluence": confluence_str,
                "when_to_buy": when_buy_action if is_bullish else when_sell_action,
                "when_to_wait": f"Do not chase if move exceeds {round(abs(chg) + 1.0, 1)}% or price moves beyond ₹{e_high if is_bullish else e_low:,.1f}.",
                "profit_rule": f"Book 50% at T1 (+2.8R), move stop to breakeven, hold 25% for T2 (+5.0R), runner for T3 (+8.0R). Capped risk ₹{fut_risk:,.0f} per lot.",
                "trade_plan": {
                    "symbol": clean_sym,
                    "direction": "LONG" if is_bullish else "SHORT",
                    "timeframe": "INTRADAY",
                    "entry_price": ltp,
                    "invalidation_stop": sl_price,
                    "target_1": t1_price,
                    "target_2": t2_price,
                    "target_3": t3_price,
                    "runner_target": t3_price,
                    "no_chase_boundary": no_chase,
                    "risk_reward": rr_str,
                },
            }
            if opt_recommendation:
                plan_dict["option_alternative"] = opt_recommendation

        sniper = adaptive_decision.sniper
        sniper_dict = None
        if sniper:
            sniper_dict = {
                "optimal_entry_zone": f"₹{sniper.entry_zone_min:,.1f} – ₹{sniper.entry_zone_max:,.1f}",
                "time_stop_minutes": 25,
                "stop_loss_rule": f"Trail to breakeven at T1; invalidation at ₹{sniper.structural_invalidation:,.1f}",
                "risk_reward_ratio": f"{sniper.risk_reward_t1:.1f}",
                "setup_name": sniper.setup_name,
                "session_phase": adaptive_decision.eagle.session_phase,
                "is_chasing": sniper.is_chasing,
                "entry_instruction": sniper.entry_instruction,
                "no_chase_boundary": sniper.no_chase_boundary,
            }
            plan_dict["sniper_plan"] = sniper_dict
            plan_dict["time_stop_minutes"] = 25

        from engine.trade_plan import get_market_status

        mcx_status_dict = get_market_status("MCX")
        mcx_status = mcx_status_dict.get("status", "LIVE")

        n_smc_tags = len(smc_tags)
        base_conf = min(88, int(70 + abs(chg) * 5))
        conf_boost = min(15, n_smc_tags * 3)
        if rvol >= 1.25:
            conf_boost = min(18, conf_boost + 3)
        if is_donchian_breakout:
            conf_boost = min(18, conf_boost + 4)
        if is_utad_bear or is_spring_bull:
            conf_boost = min(22, conf_boost + 5)
        if is_sq_fired:
            conf_boost = min(22, conf_boost + 5)
        if mtf_data and mtf_data.get("alignment_count", 0) >= 2:
            conf_boost = min(22, conf_boost + 4)
        if smc_report and smc_report.divergence_bias:
            if (is_bullish and smc_report.divergence_bias == "BULLISH") or (
                is_bearish and smc_report.divergence_bias == "BEARISH"
            ):
                conf_boost = min(22, conf_boost + 5)

        if is_1m_micro_bear or is_1m_micro_bull:
            conf_boost = min(22, conf_boost + 5)
        if cvd_ratio >= 2.0:
            conf_boost = min(22, conf_boost + 3)

        # Live Microstructure & Order Book Imbalance (OBI) Gate
        ob_snap = None
        obi_val = None
        iceberg_detected = False
        if is_authentic_live:
            try:
                from market.order_book import analyze_symbol_order_book

                ob_snap = analyze_symbol_order_book(f"MCX:{clean_sym}")
                if ob_snap and ob_snap.live_broker_connected:
                    obi_val = ob_snap.obi_5
                    iceberg_detected = ob_snap.iceberg_detected
                    if is_bullish:
                        if obi_val >= 0.20 or ob_snap.bias in ("HEAVY_ACCUMULATION", "BUY_LEAN"):
                            conf_boost = min(22, conf_boost + 4)
                            smc_tags.append(f"Institutional Bid Absorption (OBI {obi_val:+.2f})")
                        elif obi_val <= -0.40:
                            # Massive resting supply wall blocking breakout
                            conf_boost = max(0, conf_boost - 8)

                        if iceberg_detected and ob_snap.iceberg_side == "BUY":
                            conf_boost = min(22, conf_boost + 4)
                            ice_price_str = f" @ ₹{ob_snap.iceberg_price:,.1f}" if ob_snap.iceberg_price else ""
                            smc_tags.append(f"Institutional Iceberg Bid{ice_price_str}")
                    elif is_bearish:
                        if obi_val <= -0.20 or ob_snap.bias in ("HEAVY_DISTRIBUTION", "SELL_LEAN"):
                            conf_boost = min(22, conf_boost + 4)
                            smc_tags.append(f"Institutional Supply Pressure (OBI {obi_val:+.2f})")
                        elif obi_val >= 0.40:
                            # Massive resting demand wall blocking breakdown
                            conf_boost = max(0, conf_boost - 8)

                        if iceberg_detected and ob_snap.iceberg_side == "SELL":
                            conf_boost = min(22, conf_boost + 4)
                            ice_price_str = f" @ ₹{ob_snap.iceberg_price:,.1f}" if ob_snap.iceberg_price else ""
                            smc_tags.append(f"Institutional Iceberg Ask{ice_price_str}")

                    if ob_snap.liquidity_status == "SPREAD_SHOCK":
                        conf_boost = max(0, conf_boost - 5)
                        smc_tags.append("⚠️ Wide Spread Caution")
            except Exception as e_ob:
                logger.debug(f"[CommodityDetector] Order book evaluation error for {clean_sym}: {e_ob}")

            # Cumulative Volume Delta (CVD) & Multi-Bar Divergence Analysis
            try:
                from analysis.order_flow import analyze_order_flow

                of_snap = analyze_order_flow(f"MCX:{clean_sym}", timeframe="5m")
                if of_snap and of_snap.market_state == "LIVE":
                    if is_bullish:
                        if of_snap.cvd_divergence in ("BULLISH_ABSORPTION", "AGGRESSIVE_BUYING"):
                            conf_boost = min(22, conf_boost + 5)
                            div_label = of_snap.cvd_divergence.replace("_", " ").title()
                            smc_tags.append(f"CVD {div_label}")
                        elif of_snap.cvd_divergence in ("BEARISH_EXHAUSTION", "AGGRESSIVE_SELLING"):
                            # Institutional selling/exhaustion into bullish breakout = trap warning!
                            conf_boost = max(0, conf_boost - 8)
                            smc_tags.append(f"⚠️ CVD Divergence Warning ({of_snap.cvd_divergence})")
                    elif is_bearish:
                        if of_snap.cvd_divergence in ("BEARISH_EXHAUSTION", "AGGRESSIVE_SELLING"):
                            conf_boost = min(22, conf_boost + 5)
                            div_label = of_snap.cvd_divergence.replace("_", " ").title()
                            smc_tags.append(f"CVD {div_label}")
                        elif of_snap.cvd_divergence in ("BULLISH_ABSORPTION", "AGGRESSIVE_BUYING"):
                            # Institutional absorption/buying into bearish breakdown:
                            # Confirms UTAD bull trap reversal!
                            if is_utad_bear:
                                conf_boost = min(22, conf_boost + 5)
                                smc_tags.append("Institutional CVD Absorption (Bull Trap Confirmed)")
                            else:
                                conf_boost = max(0, conf_boost - 8)
                                smc_tags.append(f"⚠️ CVD Divergence Warning ({of_snap.cvd_divergence})")
            except Exception as e_of:
                logger.debug(f"[CommodityDetector] Order flow divergence evaluation error for {clean_sym}: {e_of}")

        final_conf = min(94, base_conf + conf_boost)

        if should_use_option_primary and opt_recommendation:
            primary_ltp = opt_recommendation["ltp"]
            primary_trigger = opt_recommendation["ltp"]
            primary_target = opt_t1
            primary_sl = opt_sl
            primary_no_chase = round(opt_no_chase, 2)
            primary_contract = opt_recommendation["contract"]
            primary_deriv = "OPT"
            opt_t = opt_recommendation["option_type"]
            opt_s = opt_recommendation["strike"]
            opt_p = opt_recommendation["ltp"]
            opt_stop = opt_sl
            opt_tgt = opt_t1
            opt_s_int = int(opt_s) if isinstance(opt_s, (int, float)) and opt_s == int(opt_s) else opt_s
            variant_slug = f"{direction.lower()}-{opt_s_int}{str(opt_t).lower()}"
        else:
            primary_ltp = ltp
            primary_trigger = ltp
            primary_target = t1_price
            primary_sl = sl_price
            primary_no_chase = round(no_chase, 2)
            primary_contract = f"MCX:{clean_sym}"
            primary_deriv = "FUT"
            opt_t = None
            opt_s = None
            opt_p = None
            opt_stop = None
            opt_tgt = None
            variant_slug = f"{direction.lower()}-fut"

        alert_id = generate_alert_id(clean_sym, alert_type, variant=variant_slug)

        alert = AutoAlert(
            alert_id=alert_id,
            alert_type=alert_type,
            stage="IGNITED" if abs(chg) >= (min_chg * 1.5) else "EARLY_WARNING",
            symbol=clean_sym,
            exchange="MCX",
            direction=direction,
            headline=headline,
            summary=summary,
            ltp=primary_ltp,
            trigger_level=primary_trigger,
            target_level=primary_target,
            stop_loss=primary_sl,
            no_chase_boundary=primary_no_chase,
            confidence=final_conf,
            created_at=now_iso,
            is_live=is_authentic_live,
            environment="LIVE" if is_authentic_live else "TEST",
            market_status=mcx_status,
            derivative_type=primary_deriv,
            option_type=opt_t,
            strike=opt_s,
            option_premium=opt_p,
            option_stop_loss=opt_stop,
            option_target_level=opt_tgt,
            contract_symbol=primary_contract,
            underlying_spot=ltp,
            metrics={
                "change_pct": chg,
                "volume": vol,
                "vwap": vwap,
                "spot_vwap": vwap,
                "spot_ltp": ltp,
                "spot_stop_loss": sl_price,
                "is_utad_reversal": is_utad_bear,
                "is_spring_reversal": is_spring_bull,
                "peak_recent": peak_recent,
                "trough_recent": trough_recent,
                "spot_target": t1_price,
                "spot_no_chase": round(no_chase, 2),
                "is_1m_micro_trigger": bool(is_1m_micro_bear or is_1m_micro_bull),
                "poc_price": poc_price,
                "vah_price": vah_price,
                "val_price": val_price,
                "atr": atr,
                "atr_14d": atr,
                "rvol": rvol,
                "rsi_5m": rsi_5m,
                "lot_size": lot_sz,
                "segment": "COMMODITY",
                "has_options_chain": bool(opt_recommendation),
                "confluence": confluence_str,
                "spot": ltp,
                "no_chase_boundary": primary_no_chase,
                "target_1": primary_target,
                "target_2": opt_t2 if (should_use_option_primary and opt_recommendation) else t2_price,
                "target_3": opt_runner if (should_use_option_primary and opt_recommendation) else t3_price,
                "runner_target": opt_runner if (should_use_option_primary and opt_recommendation) else t3_price,
                "is_squeeze_fired": is_sq_fired,
                "is_squeeze_on": sq_info.get("is_squeeze_on", False),
                "mtf_alignment_count": mtf_data.get("alignment_count", 1) if mtf_data else 1,
                "wall_collision": mtf_data.get("wall_collision", False) if mtf_data else False,
                "cvd_ratio": cvd_ratio if "cvd_ratio" in locals() else 1.0,
                "obi_5": obi_val if "obi_val" in locals() else None,
                "iceberg_detected": iceberg_detected if "iceberg_detected" in locals() else False,
                "divergence_type": smc_report.divergence_type if smc_report else None,
                "divergence_bias": smc_report.divergence_bias if smc_report else None,
                "eagle_regime": adaptive_decision.eagle.to_dict(),
                "tiger_mandate": adaptive_decision.tiger.to_dict(),
                "sniper_plan": sniper_dict if sniper else None,
                "chop_index": chop_idx if "chop_idx" in locals() else None,
                "adx_14": adx_14 if "adx_14" in locals() else None,
                "session_phase": adaptive_decision.eagle.session_phase,
                "confluence_factors": smc_tags,
            },
            actionable_plan=plan_dict,
        )
        if should_use_option_primary and opt_recommendation:
            alert.derivative_type = "OPT"
            alert.strike = opt_recommendation["strike"]
            alert.option_type = opt_recommendation["option_type"]
            alert.option_premium = opt_recommendation["ltp"]
            alert.option_stop_loss = opt_recommendation["stop_loss"]
            alert.option_target_1 = opt_recommendation["target_1"]
            alert.option_target_2 = opt_recommendation["target_2"]
            alert.underlying_spot = ltp
            alert.raw_contract = opt_recommendation["contract"]
            alert.contract_symbol = opt_recommendation["contract"]
            alert.ltp = opt_recommendation["ltp"]
            alert.trigger_level = opt_recommendation["ltp"]
            alert.stop_loss = opt_recommendation["stop_loss"]
            alert.target_level = opt_recommendation["target_1"]
            alert.no_chase_boundary = round(opt_recommendation["no_chase_boundary"], 2)
        else:
            alert.derivative_type = "FUT"
            alert.contract_symbol = f"MCX:{clean_sym}"
            alert.option_premium = None
            alert.underlying_spot = ltp

        found.append(alert)

    return found
