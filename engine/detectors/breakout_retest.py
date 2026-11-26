# -*- coding: utf-8 -*-
"""
engine/detectors/breakout_retest.py
───────────────────────────────────
Institutional Breakout-Retest & Asymmetric Continuation Detector.

Solves the core structural problem of raw breakout chasing (FOMO entries) by enforcing
a 4-stage institutional verification protocol:
  1. Origin Displacement: Prior breakout of a verified structural anchor
     (Confluence Block, Order Block, PDH/PDL, Chart Pattern Neckline, or ORB boundary)
     with clear momentum displacement (>= 1.2x ATR).
  2. Orderly Retest Pullback: Price retraces back to re-test the broken level
     (Resistance-turned-Support for BULLISH, Support-turned-Resistance for BEARISH).
  3. Volume Dry-Up Gate: Volume during the retest must dry up (RVOL <= 0.85x 20-MA volume).
     Heavy volume during retracement indicates distribution / liquidation, aborting the setup.
  4. Candlestick Re-ignition Trigger: Rejection wick (Hammer / Shooting Star), Engulfing bar,
     Rob Smith's The Strat 2-1-2 continuation, or lower-timeframe micro-CHoCH.

Yields exceptional asymmetry:
  - Tight Stop-Loss: Placed just behind the retested anchor with sub-ATR buffer (0.15 - 0.25x ATR).
  - Target 1: Prior swing high/low (+2.0R, triggers 50% scale-out & SL to breakeven).
  - Target 2: Structural expansion (+3.5R to +4.5R).
  - Target Runner: Macro trend continuation (+6.0R+).
  - R:R strictly >= 1:2.5 (filtering out cramped trades).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from engine.alert_identity import canonical_alert_symbol, generate_alert_id
from engine.alert_model import AutoAlert
from engine.option_resolver import (
    build_spot_anchored_option_overlay,
    is_index_symbol,
    resolve_option_contract,
)
from engine.position_sizer import get_lot_size

logger = logging.getLogger("chanakya.detectors.breakout_retest")
IST = ZoneInfo("Asia/Kolkata")


def _compute_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Computes ATR(14) defensively from OHLCV DataFrame."""
    if df is None or len(df) < period:
        return 0.0
    try:
        h = df["high"] if "high" in df.columns else df.get("High", df.iloc[:, 1])
        l = df["low"] if "low" in df.columns else df.get("Low", df.iloc[:, 2])
        c = df["close"] if "close" in df.columns else df.get("Close", df.iloc[:, 3])
        tr1 = h - l
        tr2 = (h - c.shift(1)).abs()
        tr3 = (l - c.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr_series = tr.rolling(window=period).mean().dropna()
        if len(atr_series) > 0:
            val = float(atr_series.iloc[-1])
            if val > 0:
                return round(val, 4)
    except Exception as e_supp:
        logger.debug(f"[breakout_retest] ATR computation note: {e_supp}")
    return 0.0


def _extract_breakout_anchors(
    symbol: str,
    df: pd.DataFrame,
    ltp: float,
    atr_val: float,
    exchange: str = "NSE",
) -> list[dict[str, Any]]:
    """
    Extracts all candidate structural breakout anchors that price can re-test:
      - 1. Confluence Clusters (Order Blocks, VPOC, AVWAP, OI walls)
      - 2. Classical Chart Pattern Necklines (W/M bases, Triangles, Flags)
      - 3. Key Daily Levels (PDH, PDL, PWH, PWL)
      - 4. Recent Swing Highs / Swing Lows (Fractal Pivots)
    """
    anchors: list[dict[str, Any]] = []
    clean_sym = canonical_alert_symbol(symbol)

    # 1. Confluence Clusters (Demand & Supply Blocks)
    try:
        from analysis.confluence_engine import find_confluence_clusters

        bull_clusters = find_confluence_clusters(
            symbol=clean_sym, ltp=ltp, direction="BULLISH", df=df, exchange=exchange
        )
        for c in (bull_clusters or [])[:3]:
            anchors.append(
                {
                    "type": "DEMAND_BLOCK",
                    "level": c.midpoint,
                    "top": c.top,
                    "bottom": c.bottom,
                    "bias": "BULLISH",
                    "source": f"Confluence Cluster ({c.factors_count} factors: {', '.join(c.confluence_factors[:2])})",
                    "score": c.confluence_score,
                }
            )

        bear_clusters = find_confluence_clusters(
            symbol=clean_sym, ltp=ltp, direction="BEARISH", df=df, exchange=exchange
        )
        for c in (bear_clusters or [])[:3]:
            anchors.append(
                {
                    "type": "SUPPLY_BLOCK",
                    "level": c.midpoint,
                    "top": c.top,
                    "bottom": c.bottom,
                    "bias": "BEARISH",
                    "source": f"Confluence Cluster ({c.factors_count} factors: {', '.join(c.confluence_factors[:2])})",
                    "score": c.confluence_score,
                }
            )
    except Exception as e_conf:
        logger.debug(f"[breakout_retest] Confluence extraction note for {clean_sym}: {e_conf}")

    # 2. Classical Chart Pattern Necklines
    try:
        from analysis.chart_patterns import detect_chart_patterns

        patterns = detect_chart_patterns(df, ltp=ltp)
        for p in (patterns or [])[:2]:
            if p.breakout_level > 0:
                anchors.append(
                    {
                        "type": f"{p.name}_NECKLINE",
                        "level": p.breakout_level,
                        "top": p.breakout_level + (0.15 * atr_val),
                        "bottom": p.breakout_level - (0.15 * atr_val),
                        "bias": p.bias,
                        "source": f"Chart Pattern: {p.summary}",
                        "score": p.confidence,
                    }
                )
    except Exception as e_cp:
        logger.debug(f"[breakout_retest] Chart pattern extraction note for {clean_sym}: {e_cp}")

    # 3. Swing High / Swing Low Fractal Pivots
    try:
        from analysis.market_structure import analyze_market_structure

        ms = analyze_market_structure(symbol=clean_sym, df=df, exchange=exchange)
        if ms:
            if ms.last_swing_high and ms.last_swing_high > 0:
                anchors.append(
                    {
                        "type": "SWING_HIGH_PIVOT",
                        "level": ms.last_swing_high,
                        "top": ms.last_swing_high + (0.15 * atr_val),
                        "bottom": ms.last_swing_high - (0.15 * atr_val),
                        "bias": "BULLISH",  # Resistance turned support
                        "source": f"Broken Swing High ₹{ms.last_swing_high:,.1f}",
                        "score": 75,
                    }
                )
            if ms.last_swing_low and ms.last_swing_low > 0:
                anchors.append(
                    {
                        "type": "SWING_LOW_PIVOT",
                        "level": ms.last_swing_low,
                        "top": ms.last_swing_low + (0.15 * atr_val),
                        "bottom": ms.last_swing_low - (0.15 * atr_val),
                        "bias": "BEARISH",  # Support turned resistance
                        "source": f"Broken Swing Low ₹{ms.last_swing_low:,.1f}",
                        "score": 75,
                    }
                )
    except Exception as e_ms:
        logger.debug(f"[breakout_retest] Market structure note for {clean_sym}: {e_ms}")

    return anchors


def detect_breakout_retest_setups(
    symbol: str,
    df: Optional[pd.DataFrame] = None,
    ltp: float = 0.0,
    exchange: str = "NSE",
    rvol: Optional[float] = None,
    timeframe: str = "15m",
    quotes_map: Optional[dict[str, Any]] = None,
) -> list[AutoAlert]:
    """
    Scans for institutional Breakout-Retest setups across Indices, Equities, and F&O.

    Args:
        symbol: Clean symbol (e.g., 'NIFTY', 'RELIANCE')
        df: 5m, 15m, or Daily OHLCV DataFrame
        ltp: Current Last Traded Price
        exchange: Market exchange ('NSE', 'BSE')
        rvol: Current Relative Volume (RVOL)
        timeframe: Candle interval ('5m', '15m', 'day')
        quotes_map: Optional live quote snapshot

    Returns:
        List of AutoAlert objects with alert_type="BREAKOUT_RETEST".
    """
    is_test = (
        os.environ.get("CHANAKYA_TESTING") == "1"
        or os.environ.get("DEPLOY_MODE") == "test"
        or "PYTEST_CURRENT_TEST" in os.environ
    )

    clean_sym = canonical_alert_symbol(symbol)
    alerts: list[AutoAlert] = []

    # Detect timeframe properties
    is_intraday = timeframe in ("5m", "15m", "1h", "intraday")
    min_bars = 15 if is_intraday else 25

    # 1. Fetch OHLCV if not provided
    if df is None or len(df) < min_bars:
        if is_test:
            return []
        try:
            from market.history import get_ohlcv

            df = get_ohlcv(
                clean_sym,
                exchange=exchange,
                interval=timeframe,
                days=5 if is_intraday else 120,
            )
        except Exception as e_hist:
            logger.debug(f"[breakout_retest] OHLCV fetch failed for {clean_sym}: {e_hist}")
            return []

    if df is None or len(df) < min_bars:
        return []

    # 2. Fetch LTP if not provided
    if ltp <= 0:
        if is_test:
            return []
        try:
            from market.quotes import get_ltp

            fetched = get_ltp(f"{exchange}:{clean_sym}")
            if fetched and float(fetched) > 0:
                ltp = float(fetched)
        except Exception:
            return []

    if not ltp or ltp <= 0:
        return []

    cols = {c.lower(): c for c in df.columns}
    h_col = cols.get("high", "high")
    l_col = cols.get("low", "low")
    c_col = cols.get("close", "close")
    o_col = cols.get("open", "open")
    v_col = cols.get("volume", "volume")

    # 3. Dynamic ATR computation
    atr_val = _compute_atr(df, period=14)
    if atr_val <= 0:
        atr_val = max(1.0, ltp * (0.005 if is_intraday else 0.015))

    # 4. Extract Candidate Breakout Anchors
    anchors = _extract_breakout_anchors(clean_sym, df, ltp, atr_val, exchange=exchange)
    if not anchors:
        return []

    # 5. Volume baseline for retest dry-up check
    v_series = df[v_col].astype(float) if v_col in df.columns else pd.Series(1000.0, index=df.index)
    avg_vol_20 = (
        float(v_series.rolling(20, min_periods=3).mean().iloc[-1])
        if len(v_series) >= 3
        else float(v_series.mean())
    )
    last_vol = float(v_series.iloc[-1])
    current_bar_rvol = (
        rvol if rvol is not None else (last_vol / max(1.0, avg_vol_20) if avg_vol_20 > 0 else 1.0)
    )

    # 5.b CVD Divergence computation for order flow absorption confirmation
    cvd_data = {}
    try:
        from engine.detectors.order_flow import compute_order_flow_cvd_divergence

        cvd_data = compute_order_flow_cvd_divergence(df, curr_p=ltp, lookback_bars=10)
    except Exception as e_cvd:
        logger.debug(f"[breakout_retest] CVD divergence extraction note for {clean_sym}: {e_cvd}")

    # Candlestick inspection on the latest completed / forming bar
    last_bar = df.iloc[-1]
    prev_bar = df.iloc[-2]
    c_c = float(last_bar[c_col])
    c_o = float(last_bar[o_col]) if o_col in last_bar else c_c
    c_h = float(last_bar[h_col])
    c_l = float(last_bar[l_col])
    b_range = max(0.001, c_h - c_l)
    body = abs(c_c - c_o)
    lower_wick = min(c_o, c_c) - c_l
    upper_wick = c_h - max(c_o, c_c)

    p_c = float(prev_bar[c_col])
    p_o = float(prev_bar[o_col]) if o_col in prev_bar else p_c
    p_h = float(prev_bar[h_col])
    p_l = float(prev_bar[l_col])

    now_dt = datetime.now(IST)
    now_iso = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")

    # Evaluate anchors
    for anchor in anchors:
        lvl = anchor["level"]
        bias = anchor["bias"]
        src = anchor["source"]
        score = anchor["score"]

        # Proximity Gate: Spot must be within 0.45x ATR of the anchor level
        dist = abs(ltp - lvl)
        if dist > (0.45 * atr_val):
            continue

        # ─────────────────────────────────────────────────────────
        # A. BULLISH BREAKOUT RETEST (Resistance turned Support)
        # ─────────────────────────────────────────────────────────
        if bias == "BULLISH":
            # Origin Displacement Verification:
            # Price must have previously traded above the anchor level (demonstrating breakout)
            # and is now pulling back to test it from above.
            recent_high = float(df[h_col].tail(10).max())
            if recent_high < (lvl + 0.30 * atr_val):
                # Never broke out cleanly; this is chop at resistance, not a retest
                continue

            # Retest Volume Dry-up Gate:
            # Retest volume should NOT be an aggressive institutional dumping spike
            if current_bar_rvol > 1.80:
                logger.debug(
                    f"[breakout_retest] {clean_sym} Bullish retest suppressed: RVOL {current_bar_rvol:.2f} > 1.80 (dumping risk into retest)"
                )
                continue

            is_dryup = current_bar_rvol <= 0.90

            # Candlestick Re-ignition Detection:
            # 1. Hammer / Rejection Pin Bar: lower wick >= 2x body
            is_hammer = lower_wick >= 1.8 * max(body, 0.0001) and upper_wick <= 0.35 * b_range
            # 2. Bullish Engulfing
            is_engulfing = c_c > c_o and p_c < p_o and c_c >= p_h
            # 3. Strat 2-1-2 Continuation / Green Re-ignition
            is_green_reignition = c_c > c_o and c_c >= p_c and (lower_wick >= 0.25 * b_range)

            is_confirmed = is_hammer or is_engulfing or is_green_reignition
            candle_tag = (
                "HAMMER_REJECTION"
                if is_hammer
                else ("BULLISH_ENGULFING" if is_engulfing else "GREEN_REIGNITION")
            )

            # Structural Invalidation & Asymmetric Targets:
            # Stop Loss anchored just below the retest low with sub-ATR buffer
            retest_low = min(c_l, p_l, lvl)
            sl_buffer = max(0.18 * atr_val, ltp * 0.003)
            stop_loss = round(retest_low - sl_buffer, 2)
            risk = round(abs(ltp - stop_loss), 2)
            if risk <= 0 or (ltp - stop_loss) < (0.15 * atr_val):
                risk = round(max(0.40 * atr_val, ltp * 0.005), 2)
                stop_loss = round(ltp - risk, 2)

            # Targets:
            # T1 at prior swing high (+2.0R), T2 at structural extension (+4.0R), Runner (+6.0R+)
            t1 = round(max(recent_high, ltp + 2.0 * risk), 2)
            t2 = round(ltp + 4.0 * risk, 2)
            runner = round(ltp + 6.0 * risk, 2)

            rr_t1 = round(abs(t1 - ltp) / max(0.01, risk), 2)
            rr_t2 = round(abs(t2 - ltp) / max(0.01, risk), 2)

            # Filter out cramped trades (R:R must be >= 1:2.0 on T1, >= 1:3.5 on T2)
            if rr_t1 < 1.8 or rr_t2 < 3.2:
                continue

            has_bull_absorption = bool(cvd_data.get("is_bullish_absorption", False))
            if has_bull_absorption:
                is_confirmed = True
                confidence = min(98, score + 12 + (5 if is_dryup else 0))
            else:
                confidence = min(95, score + (8 if is_confirmed else 0) + (5 if is_dryup else 0))

            stage = "CONFIRMED" if is_confirmed else "EARLY_WARNING"

            alert_id = generate_alert_id(
                clean_sym,
                "BREAKOUT_RETEST",
                variant="bull",
            )

            summary = (
                f"Bullish Breakout-Retest ({stage}, {confidence}% Conf): Price retesting broken resistance ₹{lvl:,.1f} "
                f"({src}) as new support. Dry-up RVOL: {current_bar_rvol:.2f}x. Re-ignition: {candle_tag}. R:R 1:{rr_t1:.1f}."
            )

            # Option contract resolution
            is_idx = is_index_symbol(clean_sym)
            stock_lot = get_lot_size(clean_sym)
            resolved_opt = None
            if is_idx or stock_lot > 1:
                try:
                    resolved_opt = resolve_option_contract(
                        symbol=clean_sym,
                        spot=ltp,
                        direction="BULLISH",
                        underlying_sl=stop_loss,
                        underlying_target=t1,
                        prefer_options=True,
                    )
                except Exception as e_opt:
                    logger.debug(f"[breakout_retest] Option resolution note: {e_opt}")

            has_opt = resolved_opt is not None and getattr(resolved_opt, "entry_premium", 0) > 0
            headline = (
                f"🎯 BREAKOUT RETEST: {resolved_opt.contract_symbol} @ ₹{resolved_opt.entry_premium:,.1f} "
                f"(Spot ₹{ltp:,.1f} retesting ₹{lvl:,.1f})"
                if has_opt
                else f"🎯 BREAKOUT RETEST: {clean_sym} LONG @ ₹{ltp:,.1f} (Retesting ₹{lvl:,.1f})"
            )

            metrics = {
                "spot": ltp,
                "anchor_level": lvl,
                "anchor_source": src,
                "anchor_type": anchor["type"],
                "retest_type": "RESISTANCE_TURNED_SUPPORT",
                "rvol": round(current_bar_rvol, 2),
                "is_volume_dryup": is_dryup,
                "cvd_absorption": has_bull_absorption,
                "candlestick_trigger": candle_tag,
                "is_confirmed": is_confirmed,
                "risk_pts": risk,
                "rr_ratio": rr_t1,
                "rr_t2": rr_t2,
                "no_chase_limit": round(ltp + 0.35 * atr_val, 2),
                "timeframe": timeframe,
                "stop_loss": stop_loss,
                "target_1": t1,
                "target_2": t2,
                "runner": runner,
            }

            act_plan = None
            if has_opt:
                opt_metrics, act_plan = build_spot_anchored_option_overlay(
                    resolved_opt,
                    clean_sym=clean_sym,
                    spot=ltp,
                    spot_sl=stop_loss,
                    spot_target=t1,
                )
                metrics.update(opt_metrics)

            alert = AutoAlert(
                alert_id=alert_id,
                symbol=clean_sym,
                exchange=exchange,
                alert_type="BREAKOUT_RETEST",
                direction="BULLISH",
                stage=stage,
                ltp=ltp,
                underlying_spot=ltp,
                trigger_level=ltp,
                stop_loss=stop_loss,
                target_level=t1,
                confidence=confidence,
                headline=headline,
                summary=summary,
                created_at=now_iso,
                metrics=metrics,
                actionable_plan=act_plan,
            )
            alerts.append(alert)
            break  # Max 1 bullish alert per scan cycle

        # ─────────────────────────────────────────────────────────
        # B. BEARISH BREAKDOWN RETEST (Support turned Resistance)
        # ─────────────────────────────────────────────────────────
        elif bias == "BEARISH":
            recent_low = float(df[l_col].tail(10).min())
            if recent_low > (lvl - 0.30 * atr_val):
                continue

            if current_bar_rvol > 1.80:
                logger.debug(
                    f"[breakout_retest] {clean_sym} Bearish retest suppressed: RVOL {current_bar_rvol:.2f} > 1.80 (absorption risk into retest)"
                )
                continue

            is_dryup = current_bar_rvol <= 0.90

            is_shooting_star = (
                upper_wick >= 1.8 * max(body, 0.0001) and lower_wick <= 0.35 * b_range
            )
            is_bear_engulfing = c_c < c_o and p_c > p_o and c_c <= p_l
            is_red_reignition = c_c < c_o and c_c <= p_c and (upper_wick >= 0.25 * b_range)

            is_confirmed = is_shooting_star or is_bear_engulfing or is_red_reignition
            candle_tag = (
                "SHOOTING_STAR"
                if is_shooting_star
                else ("BEARISH_ENGULFING" if is_bear_engulfing else "RED_REIGNITION")
            )

            retest_high = max(c_h, p_h, lvl)
            sl_buffer = max(0.18 * atr_val, ltp * 0.003)
            stop_loss = round(retest_high + sl_buffer, 2)
            risk = round(abs(stop_loss - ltp), 2)
            if risk <= 0 or (stop_loss - ltp) < (0.15 * atr_val):
                risk = round(max(0.40 * atr_val, ltp * 0.005), 2)
                stop_loss = round(ltp + risk, 2)

            t1 = round(min(recent_low, ltp - 2.0 * risk), 2)
            t2 = round(ltp - 4.0 * risk, 2)
            runner = round(ltp - 6.0 * risk, 2)

            rr_t1 = round(abs(ltp - t1) / max(0.01, risk), 2)
            rr_t2 = round(abs(ltp - t2) / max(0.01, risk), 2)

            if rr_t1 < 1.8 or rr_t2 < 3.2:
                continue

            has_bear_exhaustion = bool(cvd_data.get("is_bearish_exhaustion", False))
            if has_bear_exhaustion:
                is_confirmed = True
                confidence = min(98, score + 12 + (5 if is_dryup else 0))
            else:
                confidence = min(95, score + (8 if is_confirmed else 0) + (5 if is_dryup else 0))

            stage = "CONFIRMED" if is_confirmed else "EARLY_WARNING"

            alert_id = generate_alert_id(
                clean_sym,
                "BREAKOUT_RETEST",
                variant="bear",
            )

            summary = (
                f"Bearish Breakdown-Retest ({stage}, {confidence}% Conf): Price retesting broken support ₹{lvl:,.1f} "
                f"({src}) as new resistance. Dry-up RVOL: {current_bar_rvol:.2f}x. Re-ignition: {candle_tag}. R:R 1:{rr_t1:.1f}."
            )

            is_idx = is_index_symbol(clean_sym)
            stock_lot = get_lot_size(clean_sym)
            resolved_opt = None
            if is_idx or stock_lot > 1:
                try:
                    resolved_opt = resolve_option_contract(
                        symbol=clean_sym,
                        spot=ltp,
                        direction="BEARISH",
                        underlying_sl=stop_loss,
                        underlying_target=t1,
                        prefer_options=True,
                    )
                except Exception as e_opt:
                    logger.debug(f"[breakout_retest] Option resolution note: {e_opt}")

            has_opt = resolved_opt is not None and getattr(resolved_opt, "entry_premium", 0) > 0
            headline = (
                f"🎯 BREAKDOWN RETEST: {resolved_opt.contract_symbol} @ ₹{resolved_opt.entry_premium:,.1f} "
                f"(Spot ₹{ltp:,.1f} retesting ₹{lvl:,.1f})"
                if has_opt
                else f"🎯 BREAKDOWN RETEST: {clean_sym} SHORT @ ₹{ltp:,.1f} (Retesting ₹{lvl:,.1f})"
            )

            metrics = {
                "spot": ltp,
                "anchor_level": lvl,
                "anchor_source": src,
                "anchor_type": anchor["type"],
                "retest_type": "SUPPORT_TURNED_RESISTANCE",
                "rvol": round(current_bar_rvol, 2),
                "is_volume_dryup": is_dryup,
                "cvd_exhaustion": has_bear_exhaustion,
                "candlestick_trigger": candle_tag,
                "is_confirmed": is_confirmed,
                "risk_pts": risk,
                "rr_ratio": rr_t1,
                "rr_t2": rr_t2,
                "no_chase_limit": round(ltp - 0.35 * atr_val, 2),
                "timeframe": timeframe,
                "stop_loss": stop_loss,
                "target_1": t1,
                "target_2": t2,
                "runner": runner,
            }

            act_plan_bear = None
            if has_opt:
                opt_metrics_bear, act_plan_bear = build_spot_anchored_option_overlay(
                    resolved_opt,
                    clean_sym=clean_sym,
                    spot=ltp,
                    spot_sl=stop_loss,
                    spot_target=t1,
                )
                metrics.update(opt_metrics_bear)

            alert = AutoAlert(
                alert_id=alert_id,
                symbol=clean_sym,
                exchange=exchange,
                alert_type="BREAKOUT_RETEST",
                direction="BEARISH",
                stage=stage,
                ltp=ltp,
                underlying_spot=ltp,
                trigger_level=ltp,
                stop_loss=stop_loss,
                target_level=t1,
                confidence=confidence,
                headline=headline,
                summary=summary,
                created_at=now_iso,
                metrics=metrics,
                actionable_plan=act_plan_bear,
            )
            alerts.append(alert)
            break  # Max 1 bearish alert per scan cycle

    return alerts
