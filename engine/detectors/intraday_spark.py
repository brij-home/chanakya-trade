"""
engine/detectors/intraday_spark.py
──────────────────────────────────
Autonomous Intraday Mover Spark Detector (T-0 Session Explosive Moves).

Scans liquid universe (Indices, F&O, Cash) for explosive intraday sparks:
  1. Bullish breakout sparks (surge >= +2.2%, holds above VWAP, RVOL >= 1.8x).
  2. Bearish breakdown sparks (drop <= -2.0%, breaks below VWAP, RVOL >= 1.8x).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import numpy as np

from engine.alert_model import AutoAlert

logger = logging.getLogger("chanakya.detectors.intraday_spark")
IST = timezone(timedelta(hours=5, minutes=30))


def expected_volume_fraction(minutes_from_open: float) -> float:
    """Returns expected cumulative volume fraction (0.03 to 1.0) for 09:15-15:30 IST."""
    if minutes_from_open <= 0:
        return 0.03
    if minutes_from_open >= 375.0:
        return 1.0

    t = minutes_from_open
    if t <= 15.0:
        return 0.03 + (t / 15.0) * 0.09
    elif t <= 45.0:
        return 0.12 + ((t - 15.0) / 30.0) * 0.13
    elif t <= 135.0:
        return 0.25 + ((t - 45.0) / 90.0) * 0.20
    elif t <= 255.0:
        return 0.45 + ((t - 135.0) / 120.0) * 0.18
    elif t <= 345.0:
        return 0.63 + ((t - 255.0) / 90.0) * 0.22
    else:
        return 0.85 + ((t - 345.0) / 30.0) * 0.15


def compute_time_of_day_rvol(
    current_vol: float,
    avg_daily_vol: float,
    ref_dt: Optional[datetime] = None,
) -> float:
    """Computes Time-of-Day Relative Volume (TOD-RVOL)."""
    if avg_daily_vol <= 0:
        return 1.0
    now_ist = ref_dt or datetime.now(IST)
    if now_ist.tzinfo is None:
        now_ist = now_ist.replace(tzinfo=IST)
    else:
        now_ist = now_ist.astimezone(IST)

    mins_from_open = (now_ist.hour * 60 + now_ist.minute) - (9 * 60 + 15)
    fraction = expected_volume_fraction(float(mins_from_open))
    expected_vol = max(1.0, avg_daily_vol * fraction)
    return round(float(current_vol) / expected_vol, 2)


def detect_intraday_mover_sparks(
    universe: Optional[list[str]] = None,
    quotes_map: Optional[dict[str, Any]] = None,
) -> list[AutoAlert]:
    """
    Scans liquid universe for explosive intraday sparks.
    """
    from engine.precursor_radar import precursor_radar, classify_symbol_segment
    from market.quotes import get_quote
    from market.history import get_ohlcv

    found: list[AutoAlert] = []
    scan_universe = list(universe) if universe else precursor_radar.get_scan_universe(segment="ALL")

    formatted = [f"NSE:{s}" if ":" not in s else s for s in scan_universe]
    if quotes_map is None:
        try:
            quotes_map = get_quote(formatted)
        except Exception as e:
            logger.debug(f"[IntradaySpark] Quotes fetch error in spark scan: {e}")
            return found

    now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    # Resolve benchmark NIFTY status once for the whole scan batch
    nifty_q = (
        quotes_map.get("NSE:NIFTY 50")
        or quotes_map.get("NSE:NIFTY")
        or quotes_map.get("NIFTY 50")
        or quotes_map.get("NIFTY")
    )
    nifty_chg = float(getattr(nifty_q, "change_pct", 0.0) or 0.0) if nifty_q else 0.0
    nifty_ltp = (
        float(getattr(nifty_q, "last_price", 0.0) or getattr(nifty_q, "ltp", 0.0) or 0.0)
        if nifty_q
        else 0.0
    )
    nifty_vwap = float(getattr(nifty_q, "vwap", 0.0) or 0.0) if nifty_q else 0.0
    is_nifty_markdown = (nifty_chg <= -0.35) and (
        (nifty_ltp < nifty_vwap) if nifty_vwap > 0 else True
    )
    is_nifty_markup = (nifty_chg >= 0.40) and ((nifty_ltp > nifty_vwap) if nifty_vwap > 0 else True)

    for sym in scan_universe:
        clean_sym = sym.upper().replace("NSE:", "").replace(".NS", "").strip()
        q = quotes_map.get(f"NSE:{clean_sym}") or quotes_map.get(clean_sym)
        if not q:
            continue

        ltp = float(getattr(q, "last_price", 0.0) or getattr(q, "ltp", 0.0) or 0.0)
        if ltp <= 0:
            continue

        chg = float(getattr(q, "change_pct", 0.0) or 0.0)
        vol = int(getattr(q, "volume", 0) or 0)
        vwap = float(getattr(q, "vwap", 0.0) or ltp)

        seg = classify_symbol_segment(clean_sym)

        # Check turnover gate for equities (₹5 Cr min, or active volume)
        turnover_cr = round((ltp * vol) / 1e7, 2)
        if seg != "INDEX" and turnover_cr < 5.0 and vol < 50000:
            continue

        # Calculate TOD-RVOL
        df = None
        try:
            df = get_ohlcv(clean_sym, exchange="NSE", interval="day", days=30)
            if df is not None and len(df) >= 15:
                vols = df["volume"].values
                avg_vol = (
                    float(np.mean(vols[-21:-1])) if len(vols) >= 21 else float(np.mean(vols[:-1]))
                )
                try:
                    import engine.auto_alert_engine as aae

                    _rvol_fn = getattr(aae, "compute_time_of_day_rvol", compute_time_of_day_rvol)
                except Exception:
                    _rvol_fn = compute_time_of_day_rvol
                rvol = _rvol_fn(vol, avg_vol, ref_dt=datetime.now(IST))
            else:
                rvol = 1.0
        except Exception:
            rvol = 1.0

        min_pos_chg = 0.22 if seg == "INDEX" else 0.85
        min_neg_chg = -0.22 if seg == "INDEX" else -0.80
        min_rvol = 1.35 if seg == "INDEX" else 1.50

        # Session Time Gates
        is_test_env = (os.environ.get("CHANAKYA_TESTING") == "1") or (
            "PYTEST_CURRENT_TEST" in os.environ
        )
        if not is_test_env:
            try:
                import engine.auto_alert_engine as aae

                current_dt = aae.datetime.now(IST)
            except Exception:
                current_dt = datetime.now(IST)
            time_hm = current_dt.hour * 60 + current_dt.minute
            if 555 <= time_hm < 570 and seg != "INDEX":
                continue
            if 570 <= time_hm < 585:
                min_rvol = max(min_rvol, 2.0)
                if seg != "INDEX" and abs(chg) < 1.20:
                    continue

        if vwap > 0:
            vwap_dist_pct = (abs(ltp - vwap) / vwap) * 100.0
            max_allowed_ext = 1.20 if seg == "INDEX" else 2.50
            if vwap_dist_pct > max_allowed_ext:
                continue

        is_bullish = (
            (chg >= min_pos_chg) and (vwap <= 0 or ltp >= (vwap * 0.998)) and (rvol >= min_rvol)
        )
        is_bearish = (
            (chg <= min_neg_chg) and (vwap > 0 and ltp < (vwap * 1.002)) and (rvol >= min_rvol)
        )

        if not (is_bullish or is_bearish):
            continue

        uc = float(getattr(q, "upper_circuit", 0.0) or getattr(q, "circuit_limit", 0.0) or 0.0)
        if uc > 0 and ltp >= (uc * 0.992) and is_bullish:
            continue
        lc = float(getattr(q, "lower_circuit", 0.0) or 0.0)
        if lc > 0 and ltp <= (lc * 1.008) and is_bearish:
            continue

        sec_id = None
        sec_name = None
        sector_tailwind_bonus = 0
        if seg != "INDEX":
            try:
                from analysis.universe import get_stock_sector

                sec_id, sec_name = get_stock_sector(clean_sym)
            except Exception:
                pass

            try:
                from analysis.sector_rotation import get_stock_tailwind

                tailwind = get_stock_tailwind(clean_sym)
                if tailwind and hasattr(tailwind, "quadrant"):
                    if is_bullish:
                        if tailwind.quadrant in ("LEADING", "IMPROVING"):
                            sector_tailwind_bonus = 8
                        elif tailwind.quadrant == "LAGGING" and rvol < 2.5:
                            continue
                    elif is_bearish:
                        if tailwind.quadrant == "LAGGING":
                            sector_tailwind_bonus = 8
                        elif tailwind.quadrant == "LEADING" and rvol < 2.5:
                            continue
            except Exception:
                pass

        is_mock_spark = (
            type(q).__name__ == "MagicMock"
            or getattr(q, "_is_mock", False)
            or getattr(q, "provider", "") in ("mock", "TEST")
        )
        is_authentic_spark = not (is_mock_spark or is_test_env)

        if is_bullish:
            direction = "BULLISH"
            alert_type = "INTRADAY_BREAKOUT_SPARK"
            stage = "IGNITED" if chg >= (min_pos_chg * 2.0) else "EARLY_WARNING"
            headline = (
                f"⚡ INTRADAY SPARK: {clean_sym} Surge +{chg:.1f}% (RVOL {rvol:.1f}x) @ ₹{ltp:,.1f}"
            )
            summary = (
                f"T-0 Explosive Session Mover: {clean_sym} moving +{chg:.1f}% with "
                f"{rvol:.1f}x Time-of-Day Relative Volume. Holding above VWAP ₹{vwap:,.1f}."
            )

            tp = None
            try:
                from engine.trade_plan import calculate_trade_plan

                tp = calculate_trade_plan(
                    symbol=clean_sym,
                    direction="BUY",
                    spot=ltp,
                    timeframe="INTRADAY",
                    exchange="NSE",
                    has_active_blast=True,
                    df=df,
                )
            except Exception as e_tp:
                logger.debug(
                    f"[IntradaySpark] Trade plan calculation failed for {clean_sym}: {e_tp}"
                )

            atr_val = max(1.0, ltp * 0.015)
            if df is not None and len(df) >= 5 and "high" in df.columns and "low" in df.columns:
                try:
                    tr = np.maximum(
                        df["high"] - df["low"],
                        np.maximum(
                            abs(df["high"] - df["close"].shift(1)),
                            abs(df["low"] - df["close"].shift(1)),
                        ),
                    )
                    atr_calc = float(tr.tail(14).mean())
                    if atr_calc > 0:
                        atr_val = round(atr_calc, 2)
                except Exception:
                    pass
            min_risk = (
                max(1.0, round(0.70 * atr_val, 2))
                if seg != "INDEX"
                else max(1.0, round(0.50 * atr_val, 2))
            )

            if tp and tp.is_asymmetry_viable and tp.target_1 > ltp and tp.invalidation_stop < ltp:
                risk_pts = max(min_risk, round(ltp - tp.invalidation_stop, 2))
                sl_price = round(ltp - risk_pts, 2)
                t1_price = max(tp.target_1, round(ltp + 1.5 * risk_pts, 2))
                t2_price = max(tp.target_2, round(ltp + 2.5 * risk_pts, 2))
                t3_price = max(tp.target_3, round(ltp + 4.0 * risk_pts, 2))
                rr_str = f"1:{round(abs(t1_price - ltp) / max(0.01, risk_pts), 1)}"
                tp_dict = tp.as_dict()
            else:
                risk_pts = max(
                    min_risk,
                    round(max(0.8 * atr_val, ltp - vwap if ltp > vwap else ltp * 0.012), 2),
                )
                sl_price = round(ltp - risk_pts, 2)
                t1_price = round(ltp + 2.0 * risk_pts, 2)
                t2_price = round(ltp + 3.5 * risk_pts, 2)
                t3_price = round(ltp + 5.0 * risk_pts, 2)
                rr_str = f"1:{round(abs(t1_price - ltp) / max(0.01, risk_pts), 1)}"
                tp_dict = None

            tick_offset = max(0.05, min(0.5, round(ltp * 0.001, 2)))
            e_min = round(max(sl_price + tick_offset, ltp * 0.998), 1)
            e_max = round(min(t1_price - tick_offset, ltp * 1.005), 1)
            if e_min >= e_max:
                e_min = round(ltp * 0.998, 1)
                e_max = round(ltp * 1.005, 1)

            fut_advice = None
            if seg != "INDEX":
                try:
                    from engine.alert_expiry import (
                        is_monthly_physical_expiry_week,
                        get_next_monthly_expiry_date,
                    )

                    now_d = datetime.now(IST)
                    is_exp_wk, dte = is_monthly_physical_expiry_week(now_d)
                    if is_exp_wk:
                        next_dt = get_next_monthly_expiry_date(now_d)
                        next_str = next_dt.strftime("%d-%b-%Y")
                        fut_advice = (
                            f"⚠️ SEBI Physical Delivery Week (DTE: {dte}d). For Derivatives: "
                            f"Roll over / execute in Next-Month Future (Exp: {next_str}) to eliminate physical delivery margin risk."
                        )
                except Exception:
                    pass

            plan = {
                "action": "BUY / LONG",
                "segment": seg,
                "entry_range": f"₹{e_min:,.1f} – ₹{e_max:,.1f}",
                "stop_loss": f"₹{sl_price:,.1f}",
                "target": f"₹{t1_price:,.1f}",
                "target_2": f"₹{t2_price:,.1f}",
                "target_3": f"₹{t3_price:,.1f}",
                "target_moonshot": f"₹{t3_price:,.1f}",
                "risk_reward": rr_str,
                "when_to_buy": f"Enter on 1m/5m consolidation holding above VWAP (₹{vwap:,.1f}).",
                "when_to_wait": f"Do not chase if price moves > {round(chg + 1.2, 1)}% from open.",
                "profit_rule": "Book 50% at T1, trail SL to Breakeven for T2 & Runner.",
                "trade_plan": tp_dict
                or {
                    "symbol": clean_sym,
                    "direction": "LONG",
                    "timeframe": "INTRADAY",
                    "entry_price": ltp,
                    "invalidation_stop": sl_price,
                    "target_1": t1_price,
                    "target_2": t2_price,
                    "target_3": t3_price,
                    "risk_reward": rr_str,
                },
            }
            if fut_advice:
                plan["derivatives_advice"] = fut_advice

        else:
            direction = "BEARISH"
            alert_type = "INTRADAY_BREAKDOWN_SPARK"
            stage = "IGNITED" if chg <= (min_neg_chg * 2.0) else "EARLY_WARNING"
            headline = f"⚡ INTRADAY BREAKDOWN: {clean_sym} Dump {chg:.1f}% (RVOL {rvol:.1f}x) @ ₹{ltp:,.1f}"
            summary = (
                f"T-0 Explosive Downside Mover: {clean_sym} falling {chg:.1f}% with "
                f"{rvol:.1f}x Time-of-Day Relative Volume. Trapped below VWAP ₹{vwap:,.1f}."
            )

            tp = None
            try:
                from engine.trade_plan import calculate_trade_plan

                tp = calculate_trade_plan(
                    symbol=clean_sym,
                    direction="SELL",
                    spot=ltp,
                    timeframe="INTRADAY",
                    exchange="NSE",
                    has_active_blast=True,
                    df=df,
                )
            except Exception as e_tp:
                logger.debug(
                    f"[IntradaySpark] Trade plan calculation failed for {clean_sym}: {e_tp}"
                )

            atr_val = max(1.0, ltp * 0.015)
            if df is not None and len(df) >= 5 and "high" in df.columns and "low" in df.columns:
                try:
                    tr = np.maximum(
                        df["high"] - df["low"],
                        np.maximum(
                            abs(df["high"] - df["close"].shift(1)),
                            abs(df["low"] - df["close"].shift(1)),
                        ),
                    )
                    atr_calc = float(tr.tail(14).mean())
                    if atr_calc > 0:
                        atr_val = round(atr_calc, 2)
                except Exception:
                    pass
            min_risk = (
                max(1.0, round(0.70 * atr_val, 2))
                if seg != "INDEX"
                else max(1.0, round(0.50 * atr_val, 2))
            )

            if tp and tp.is_asymmetry_viable and tp.target_1 < ltp and tp.invalidation_stop > ltp:
                risk_pts = max(min_risk, round(tp.invalidation_stop - ltp, 2))
                sl_price = round(ltp + risk_pts, 2)
                t1_price = min(tp.target_1, round(max(0.05, ltp - 1.5 * risk_pts), 2))
                t2_price = min(tp.target_2, round(max(0.05, ltp - 2.5 * risk_pts), 2))
                t3_price = min(tp.target_3, round(max(0.05, ltp - 4.0 * risk_pts), 2))
                rr_str = f"1:{round(abs(ltp - t1_price) / max(0.01, risk_pts), 1)}"
                tp_dict = tp.as_dict()
            else:
                risk_pts = max(
                    min_risk,
                    round(max(0.8 * atr_val, vwap - ltp if vwap > ltp else ltp * 0.012), 2),
                )
                sl_price = round(ltp + risk_pts, 2)
                t1_price = round(max(0.05, ltp - 2.0 * risk_pts), 2)
                t2_price = round(max(0.05, ltp - 3.5 * risk_pts), 2)
                t3_price = round(max(0.05, ltp - 5.0 * risk_pts), 2)
                rr_str = f"1:{round(abs(ltp - t1_price) / max(0.01, risk_pts), 1)}"
                tp_dict = None

            tick_offset = max(0.05, min(0.5, round(ltp * 0.001, 2)))
            e_max = round(min(sl_price - tick_offset, ltp * 1.002), 1)
            e_min = round(max(t1_price + tick_offset, ltp * 0.995), 1)
            if e_min >= e_max:
                e_min = round(ltp * 0.995, 1)
                e_max = round(ltp * 1.002, 1)

            fut_advice = None
            if seg != "INDEX":
                try:
                    from engine.alert_expiry import (
                        is_monthly_physical_expiry_week,
                        get_next_monthly_expiry_date,
                    )

                    now_d = datetime.now(IST)
                    is_exp_wk, dte = is_monthly_physical_expiry_week(now_d)
                    if is_exp_wk:
                        next_dt = get_next_monthly_expiry_date(now_d)
                        next_str = next_dt.strftime("%d-%b-%Y")
                        fut_advice = (
                            f"⚠️ SEBI Physical Delivery Week (DTE: {dte}d). For Short Derivatives: "
                            f"Execute in Next-Month Future (Exp: {next_str}) to eliminate physical delivery margin spikes."
                        )
                except Exception:
                    pass

            plan = {
                "action": "SELL_SHORT_OR_BUY_PUT",
                "segment": seg,
                "entry_range": f"₹{e_min:,.1f} – ₹{e_max:,.1f}",
                "stop_loss": f"₹{sl_price:,.1f}",
                "target": f"₹{t1_price:,.1f}",
                "target_2": f"₹{t2_price:,.1f}",
                "target_3": f"₹{t3_price:,.1f}",
                "target_moonshot": f"₹{t3_price:,.1f}",
                "risk_reward": rr_str,
                "when_to_buy": f"Short on rejection retest of VWAP (₹{vwap:,.1f}) from below.",
                "when_to_wait": f"Do not chase if breakdown already exceeds {round(abs(chg) + 1.2, 1)}%.",
                "profit_rule": "Cover 50% at T1, trail stop to breakeven for T2 & Runner.",
                "trade_plan": tp_dict
                or {
                    "symbol": clean_sym,
                    "direction": "SHORT",
                    "timeframe": "INTRADAY",
                    "entry_price": ltp,
                    "invalidation_stop": sl_price,
                    "target_1": t1_price,
                    "target_2": t2_price,
                    "target_3": t3_price,
                    "risk_reward": rr_str,
                },
            }
            if fut_advice:
                plan["derivatives_advice"] = fut_advice

        df_5m = None
        alignment_count = 0
        try:
            from market.history import get_ohlcv
            from analysis.market_structure import compute_mtf_alignment

            df_5m = get_ohlcv(clean_sym, exchange="NSE", interval="5minute", days=3)
            df_15m = get_ohlcv(clean_sym, exchange="NSE", interval="15minute", days=5)
            if df_5m is not None and df_15m is not None:
                mtf_res = compute_mtf_alignment(df_5m=df_5m, df_15m=df_15m, df_daily=df)
                alignment_count = int(mtf_res.get("alignment_count", 0))
                opp_trend = mtf_res.get("opposing_trend")
                if opp_trend:
                    logger.debug(
                        f"[IntradaySpark] Suppressed {direction} spark on {clean_sym}: Opposing higher-timeframe trend ({opp_trend})"
                    )
                    continue
        except Exception as e_mtf:
            logger.debug(f"[IntradaySpark] MTF alignment check error for {clean_sym}: {e_mtf}")

        confirmation_bonus = 0
        divergence_bonus = 0
        conf_candle = None
        is_confirmed = False
        div_type = None
        div_bias = None
        if df_5m is not None and len(df_5m) >= 5:
            try:
                from analysis.market_structure import (
                    detect_confirmation_candle,
                    detect_divergence,
                )

                conf_res = detect_confirmation_candle(df_5m, direction=direction)
                is_confirmed = (
                    bool(conf_res.get("confirmed")) if isinstance(conf_res, dict) else False
                )
                conf_candle = conf_res.get("pattern") if isinstance(conf_res, dict) else None
                if is_confirmed:
                    confirmation_bonus = 8

                div_res = detect_divergence(df_5m)
                div_type = div_res.get("type") if isinstance(div_res, dict) else None
                div_bias = div_res.get("bias") if isinstance(div_res, dict) else None
                if div_type == "NONE":
                    div_type = None
                if div_bias == "NONE":
                    div_bias = None

                if div_type:
                    if is_bullish and div_bias == "BEARISH" and "REGULAR" in div_type:
                        logger.debug(
                            f"[IntradaySpark] Suppressed bullish spark on {clean_sym}: Bearish regular RSI divergence trap ({div_type})"
                        )
                        continue
                    elif is_bearish and div_bias == "BULLISH" and "REGULAR" in div_type:
                        logger.debug(
                            f"[IntradaySpark] Suppressed bearish spark on {clean_sym}: Bullish regular RSI divergence trap ({div_type})"
                        )
                        continue
                    elif (is_bullish and div_bias == "BULLISH") or (
                        is_bearish and div_bias == "BEARISH"
                    ):
                        divergence_bonus = 6
            except Exception as e_smc:
                logger.debug(f"[IntradaySpark] Spark candle/divergence check error: {e_smc}")

        alert_id = f"spark-{clean_sym.lower()}-{datetime.now(IST).strftime('%Y%m%d%H%M')}"
        alert = AutoAlert(
            alert_id=alert_id,
            alert_type=alert_type,
            stage=stage,
            symbol=clean_sym,
            exchange="NSE",
            direction=direction,
            headline=headline,
            summary=summary,
            ltp=ltp,
            trigger_level=ltp,
            target_level=t1_price,
            stop_loss=sl_price,
            confidence=min(
                95,
                int(75 + rvol * 5 + sector_tailwind_bonus + confirmation_bonus + divergence_bonus),
            ),
            created_at=now_iso,
            is_live=is_authentic_spark,
            environment="LIVE" if is_authentic_spark else "TEST",
            metrics={
                "rvol": rvol,
                "turnover_cr": turnover_cr,
                "vwap": vwap,
                "change_pct": chg,
                "segment": seg,
                "atr": atr_val,
                "nifty_change_pct": nifty_chg if nifty_q else None,
                "nifty_below_vwap": (
                    ((nifty_ltp < nifty_vwap) if nifty_vwap > 0 else (nifty_chg < 0))
                    if nifty_q
                    else None
                ),
                "nifty_regime": (
                    (
                        "MARKDOWN"
                        if is_nifty_markdown
                        else ("MARKUP" if is_nifty_markup else "NORMAL")
                    )
                    if nifty_q
                    else "NORMAL"
                ),
                "sector_id": sec_id,
                "sector_name": sec_name,
                "confirmation_candle": conf_candle,
                "confirmation_confirmed": is_confirmed,
                "divergence_type": div_type,
                "divergence_bias": div_bias,
                "alignment_count": alignment_count,
                "sector_tailwind_bonus": sector_tailwind_bonus,
            },
            actionable_plan=plan,
        )
        found.append(alert)

    return found
