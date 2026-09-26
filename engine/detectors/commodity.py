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


def detect_commodity_breakouts(
    universe: Optional[list[str]] = None,
    quotes_map: Optional[dict[str, Any]] = None,
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

        # Minimum move threshold for commodity trigger (0.6% for Gold/Silver/Copper, 1.0% for Crude/NatGas)
        min_chg = 1.0 if clean_sym in ("CRUDEOIL", "CRUDEOILM", "NATURALGAS", "NATGASMINI") else 0.6

        # 20-Bar Donchian Channel Breakout & Wick Rejection Verification on 5m OHLCV
        df_5m = None
        try:
            from market.history import get_ohlcv

            df_5m = get_ohlcv(clean_sym, exchange="MCX", interval="5minute", days=2)
        except Exception as e:
            logger.debug(f"[CommodityDetector] Error fetching 5m OHLCV for MCX:{clean_sym}: {e}")

        # US Open Transition Gate (18:15 to 19:15 IST):
        is_us_open_transition = (now_ist.hour == 18 and now_ist.minute >= 15) or (
            now_ist.hour == 19 and now_ist.minute < 15
        )

        is_bullish = False
        is_bearish = False
        is_donchian_breakout = False
        rvol = 1.0

        roc_15m = 0.0
        if df_5m is not None and len(df_5m) >= 4:
            try:
                c_ago = float(df_5m.iloc[-4]["close"])
                if c_ago > 0:
                    roc_15m = round(((ltp - c_ago) / c_ago * 100), 2)
            except Exception:
                pass

        has_bull_chg = (
            (chg_prev >= min_chg)
            or (chg_open >= min_chg)
            or (chg_from_low >= min_chg * 1.2 and roc_15m >= 0.5)
        )
        has_bear_chg = (
            (chg_prev <= -min_chg)
            or (chg_open <= -min_chg)
            or (chg_from_high >= min_chg * 1.2 and roc_15m <= -0.5)
        )

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

            # Compute Relative Volume (RVOL) against 20-bar rolling average
            try:
                vols_s = df_5m["volume"] if "volume" in df_5m.columns else df_5m.get("Volume")
                if vols_s is not None and len(vols_s) >= 20:
                    avg_v = float(vols_s.iloc[-21:-1].mean())
                    cur_v = float(last_bar.get("volume", 0.0) or 0.0)
                    rvol = round(cur_v / max(1.0, avg_v), 2) if avg_v > 0 else 1.0
            except Exception:
                rvol = 1.0

            upper_wick_ratio = (cur_high - max(cur_open, cur_close)) / bar_range
            lower_wick_ratio = (min(cur_open, cur_close) - cur_low) / bar_range
            bull_close_ratio = (cur_close - cur_low) / bar_range
            bear_close_ratio = (cur_high - cur_close) / bar_range

            max_wick = 0.45 if (is_us_open_transition and rvol >= 1.2) else 0.40
            req_bull_close = 0.55 if is_us_open_transition else 0.50
            req_bear_close = 0.55 if is_us_open_transition else 0.50

            # Trend continuation condition (trading firmly above VWAP with momentum and healthy candle close)
            is_vwap_trend_bull = (
                not is_locked_bull
                and has_bull_chg
                and ltp >= vwap * 1.002
                and cur_close > cur_open
                and upper_wick_ratio <= max_wick
                and bull_close_ratio >= req_bull_close
                and rvol >= 1.25
            )
            is_vwap_trend_bear = (
                not is_locked_bear
                and has_bear_chg
                and ltp <= vwap * 0.998
                and cur_close < cur_open
                and lower_wick_ratio <= max_wick
                and bear_close_ratio >= req_bear_close
                and rvol >= 1.25
            )

            if (
                not is_locked_bull
                and has_bull_chg
                and (
                    (ltp >= prior_high * 0.999 or cur_close >= prior_high)
                    or is_vwap_trend_bull
                )
                and upper_wick_ratio <= max_wick
                and bull_close_ratio >= req_bull_close
                and ltp >= vwap * 0.998
            ):
                if not is_us_open_transition or rvol >= 1.2:
                    is_bullish = True
                    is_donchian_breakout = True

            elif (
                not is_locked_bear
                and has_bear_chg
                and (
                    (ltp <= prior_low * 1.001 or cur_close <= prior_low)
                    or is_vwap_trend_bear
                )
                and lower_wick_ratio <= max_wick
                and bear_close_ratio >= req_bear_close
                and ltp <= vwap * 1.002
            ):
                if not is_us_open_transition or rvol >= 1.2:
                    is_bearish = True
                    is_donchian_breakout = True
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

        if not (is_bullish or is_bearish):
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
        smc_tags: list[str] = []
        smc_report = None
        if df_5m is not None and len(df_5m) >= 14:
            try:
                from analysis.market_structure import analyze_market_structure

                smc_report = analyze_market_structure(
                    clean_sym, df=df_5m, exchange="MCX", timeframe="5m"
                )
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
                    if is_bullish and smc_report.in_discount_zone:
                        smc_tags.append("Discount Zone (≤50% Eq)")
            except Exception as e:
                logger.debug(f"[CommodityDetector] SMC analysis error: {e}")

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

        if rvol >= 1.5:
            smc_tags.append(f"Institutional Surge (RVOL {rvol:.1f}x)")
        elif rvol >= 1.2:
            smc_tags.append(f"Volume Expansion (RVOL {rvol:.1f}x)")

        noise_safe_pts = max(base_atr * 1.5, min_structural_pts, min_noise_floor_pts)
        if smc_report and smc_report.invalidation_level and smc_report.invalidation_level > 0:
            smc_inval_pts = abs(ltp - smc_report.invalidation_level)
            if smc_inval_pts >= min_structural_pts:
                noise_safe_pts = max(noise_safe_pts, round(smc_inval_pts, 1))

        risk_pts = round(max(1.0, noise_safe_pts), 1)
        atr = round(base_atr, 1)
        direction = "BULLISH" if is_bullish else "BEARISH"
        from engine.alert_identity import generate_alert_id

        alert_id = generate_alert_id(clean_sym, alert_type)

        from engine.position_sizer import get_lot_size

        lot_sz = get_lot_size(clean_sym) or 1
        has_real_vwap = abs(ltp - vwap) >= 2.0 and vwap != ltp

        if is_bullish:
            sl_price = round(ltp - risk_pts, 2)
            t1_price = round(ltp + 2.0 * risk_pts, 2)
            t2_price = round(ltp + 3.5 * risk_pts, 2)
            if is_donchian_breakout:
                headline = (
                    f"🛢️ MCX BREAKOUT: {clean_sym} +{chg:.1f}% Breaking 20-bar High (₹{ltp:,.1f})"
                )
                summary = f"Institutional breakout in {clean_sym}: Trading at ₹{ltp:,.1f} (+{chg:.1f}%). 20-bar 5m Donchian high broken with VWAP support at ₹{vwap:,.1f}."
            elif has_real_vwap:
                headline = f"MCX MOMENTUM: {clean_sym} +{chg:.1f}% Reclaiming VWAP (₹{vwap:,.1f})"
                summary = f"Institutional breakout in {clean_sym}: Trading at ₹{ltp:,.1f} (+{chg:.1f}%). VWAP support at ₹{vwap:,.1f}."
            else:
                headline = f"MCX MOMENTUM: {clean_sym} +{chg:.1f}% Breakout @ ₹{ltp:,.1f}"
                summary = f"Institutional breakout in {clean_sym}: Trading at ₹{ltp:,.1f} (+{chg:.1f}%). Session momentum active."
            action = "BUY_FUTURES"
        else:
            sl_price = round(ltp + risk_pts, 2)
            t1_price = round(ltp - 2.0 * risk_pts, 2)
            t2_price = round(ltp - 3.5 * risk_pts, 2)
            if is_donchian_breakout:
                headline = (
                    f"🛢️ MCX BREAKDOWN: {clean_sym} {chg:.1f}% Breaking 20-bar Low (₹{ltp:,.1f})"
                )
                summary = f"Institutional breakdown in {clean_sym}: Trading at ₹{ltp:,.1f} ({chg:.1f}%). 20-bar 5m Donchian low broken below VWAP ₹{vwap:,.1f}."
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
                    candidates.sort(key=lambda c: abs(float(getattr(c, "strike", 0.0)) - ltp))
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
                    opt_t1 = round(opt_prem + 2.0 * opt_risk, 1)
                    opt_t2 = round(opt_prem + 3.5 * opt_risk, 1)

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
                        "risk_reward": opt_rr_str,
                        "max_loss_capped": round(opt_prem * lot_sz, 0),
                        "delta_tier": delta_tier,
                        "dte_warning": dte_warning,
                        "is_synthetic": is_synthetic_options,
                    }
            except Exception as e:
                logger.debug(f"[CommodityDetector] Options chain resolution error: {e}")
                opt_recommendation = None

        if is_bullish:
            e_low = round(max(sl_price + 0.5, ltp - 0.25 * risk_pts), 1)
            e_high = round(min(t1_price - 0.25 * risk_pts, ltp + 0.25 * risk_pts), 1)
        else:
            e_high = round(min(sl_price - 0.5, ltp + 0.25 * risk_pts), 1)
            e_low = round(max(t1_price + 0.25 * risk_pts, ltp - 0.25 * risk_pts), 1)

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
            opt_entry_low = round(max(0.5, opt_recommendation["ltp"] - 0.15 * opt_risk), 1)
            opt_entry_high = round(opt_recommendation["ltp"] + 0.15 * opt_risk, 1)

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
                "target_2": f"₹{opt_t2:,.1f}",
                "risk_reward": opt_recommendation["risk_reward"],
                "lot_size": lot_sz,
                "preferred_vehicle": "DEFINED_RISK_OPTION",
                "delta_tier": _delta_tier,
                "max_loss_capped": opt_max_outlay,
                "setup_confluence": confluence_str,
                "when_to_buy": (
                    f"Enter {_delta_tier} {opt_contract_name} on 5m candle closing in breakout direction above/below VWAP ₹{vwap:,.1f}."
                    + (f" {_dte_warn}" if _dte_warn else "")
                ),
                "when_to_wait": f"Do not chase if option premium moves >15% beyond ₹{opt_recommendation['ltp']:,.1f} (Spot above ₹{e_high:,.1f}).",
                "profit_rule": (
                    f"Book 50% at T1 (₹{opt_t1:,.1f}), trail stop to cost, hold runner for T2 (₹{opt_t2:,.1f}). "
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
                    "risk_reward": opt_recommendation["risk_reward"],
                },
                "futures_reference": {
                    "contract": f"MCX:{clean_sym}",
                    "entry": ltp,
                    "stop_loss": sl_price,
                    "target_1": t1_price,
                    "target_2": t2_price,
                    "risk_reward": rr_str,
                },
                "option_alternative": opt_recommendation,
            }
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
                "target_2": f"₹{t2_price:,.1f}",
                "risk_reward": rr_str,
                "lot_size": lot_sz,
                "preferred_vehicle": "FUTURES",
                "setup_confluence": confluence_str,
                "when_to_buy": f"Enter on 5m candle closing in direction above/below VWAP ₹{vwap:,.1f}.",
                "when_to_wait": f"Do not chase if move exceeds {round(abs(chg) + 1.0, 1)}% or price moves beyond ₹{e_high:,.1f}.",
                "profit_rule": f"Book 50% at T1 (+2.0R), trail stop to breakeven, hold runner for T2 (+3.5R). Capped risk ₹{fut_risk:,.0f} per lot.",
                "trade_plan": {
                    "symbol": clean_sym,
                    "direction": "LONG" if is_bullish else "SHORT",
                    "timeframe": "INTRADAY",
                    "entry_price": ltp,
                    "invalidation_stop": sl_price,
                    "target_1": t1_price,
                    "target_2": t2_price,
                    "risk_reward": rr_str,
                },
            }
            if opt_recommendation:
                plan_dict["option_alternative"] = opt_recommendation

        from engine.trade_plan import get_market_status

        mcx_status_dict = get_market_status("MCX")
        mcx_status = mcx_status_dict.get("status", "LIVE")

        n_smc_tags = len(smc_tags)
        base_conf = min(88, int(68 + abs(chg) * 5))
        conf_boost = min(15, n_smc_tags * 3)
        if smc_report and smc_report.divergence_bias:
            if (is_bullish and smc_report.divergence_bias == "BULLISH") or (
                is_bearish and smc_report.divergence_bias == "BEARISH"
            ):
                conf_boost = min(15, conf_boost + 5)
        final_conf = min(92, base_conf + conf_boost)

        alert = AutoAlert(
            alert_id=alert_id,
            alert_type=alert_type,
            stage="IGNITED" if abs(chg) >= (min_chg * 1.5) else "EARLY_WARNING",
            symbol=clean_sym,
            exchange="MCX",
            direction=direction,
            headline=headline,
            summary=summary,
            ltp=ltp,
            trigger_level=ltp,
            target_level=t1_price,
            stop_loss=sl_price,
            confidence=final_conf,
            created_at=now_iso,
            is_live=is_authentic_live,
            environment="LIVE" if is_authentic_live else "TEST",
            market_status=mcx_status,
            option_premium=opt_recommendation["ltp"]
            if (should_use_option_primary and opt_recommendation)
            else None,
            contract_symbol=opt_recommendation["contract"]
            if (should_use_option_primary and opt_recommendation)
            else f"MCX:{clean_sym}",
            metrics={
                "change_pct": chg,
                "volume": vol,
                "vwap": vwap,
                "atr": atr,
                "atr_14d": atr,
                "rvol": rvol,
                "lot_size": lot_sz,
                "segment": "COMMODITY",
                "has_options_chain": bool(opt_recommendation),
                "confluence": confluence_str,
                "spot": ltp,
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
        else:
            alert.derivative_type = "FUT"
            alert.contract_symbol = f"MCX:{clean_sym}"
            alert.option_premium = None

        found.append(alert)

    return found
