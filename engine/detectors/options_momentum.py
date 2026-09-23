"""
engine/detectors/options_momentum.py
────────────────────────────────────
Autonomous Options Momentum Breakout Detector for Indian Markets (NSE/NFO & BSE/BFO).

Scans liquid indices and Tier-1 F&O leaders for directional Options Momentum Breakouts.
Surfaces high-volume, high-turnover ATM contracts with verified underlying SMC alignment,
tight spot-anchored stop-losses, optimal trade entry (OTE) pullback zones, and favorable R:R.
Enforces institutional safeguards: 0DTE afternoon theta guard, SEBI physical delivery
rollover protection, Wick rejection filter, and anti-storm pacing.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import numpy as np

from engine.alert_model import AutoAlert
from engine.alert_expiry import classify_expiry_type

logger = logging.getLogger("chanakya.detectors.options_momentum")
IST = timezone(timedelta(hours=5, minutes=30))

DEFAULT_WATCHED_INDICES = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"}


def resolve_index_exchange(sym: str) -> str:
    """Resolves BSE for SENSEX/BANKEX, MCX for commodities, otherwise NSE."""
    clean = sym.replace("NSE:", "").replace("BSE:", "").replace("MCX:", "").strip().upper()
    if clean in ("SENSEX", "BANKEX"):
        return "BSE"
    if clean in ("CRUDEOIL", "NATURALGAS", "GOLD", "SILVER", "COPPER", "ZINC"):
        return "MCX"
    return "NSE"


def detect_options_momentum_breakouts(
    targets: Optional[list[str]] = None,
    watched_indices: Optional[set[str] | list[str]] = None,
    recent_alerts: Optional[list[AutoAlert]] = None,
    batch_quotes: Optional[dict[str, Any]] = None,
    now_dt: Optional[datetime] = None,
) -> list[AutoAlert]:
    """
    Scans liquid indices and Tier-1 F&O leaders for directional Options Momentum Breakouts.
    Returns ranked and paced AutoAlert instances meeting institutional conviction standards.
    """
    from market.options import get_options_chain
    from market.quotes import get_ltp, get_quote
    from engine.position_sizer import get_lot_size
    from engine.alert_preferences import alert_preferences

    found: list[AutoAlert] = []
    candidate_alerts: list[tuple[float, AutoAlert]] = []
    active_targets: list[dict[str, Any]] = []

    if now_dt is None:
        now_dt = datetime.now(IST)
    now_iso = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")

    is_test_env = (
        os.environ.get("CHANAKYA_TESTING") == "1"
        or os.environ.get("DEPLOY_MODE") == "test"
        or ("PYTEST_CURRENT_TEST" in os.environ)
    )

    is_friday_late = (now_dt.weekday() == 4) and (
        now_dt.hour > 14 or (now_dt.hour == 14 and now_dt.minute >= 30)
    )
    is_opening_freeze = now_dt.hour == 9 and now_dt.minute < 25
    is_opening_drive = now_dt.hour == 9 and (25 <= now_dt.minute <= 45)
    is_midday_lull = (
        (now_dt.hour == 11 and now_dt.minute >= 45)
        or (now_dt.hour == 12)
        or (now_dt.hour == 13 and now_dt.minute < 15)
    )
    is_late_session_theta = now_dt.hour > 14 or (now_dt.hour == 14 and now_dt.minute >= 45)

    index_allowed = alert_preferences.is_segment_allowed("FNO_INDEX")
    resolved_indices = (
        set(watched_indices) if watched_indices is not None else DEFAULT_WATCHED_INDICES
    )

    if targets is None:
        target_list: list[str] = list(resolved_indices) if index_allowed else []
    else:
        target_list = list(targets)

    # Resolve benchmark NIFTY regime once for the scan cycle
    nifty_change = None
    nifty_below_vwap = None
    try:
        nq = get_quote("NSE:NIFTY 50")
        q_obj = nq.get("NSE:NIFTY 50") or nq.get("NIFTY 50") if isinstance(nq, dict) else nq
        if q_obj:
            n_ltp = float(getattr(q_obj, "last_price", 0.0) or getattr(q_obj, "ltp", 0.0) or 0.0)
            n_vwap = float(getattr(q_obj, "vwap", 0.0) or 0.0)
            n_chg = float(getattr(q_obj, "change_pct", 0.0) or 0.0)
            if n_ltp > 0:
                nifty_change = n_chg
                nifty_below_vwap = (n_ltp < n_vwap) if n_vwap > 0 else (n_chg < 0)
    except Exception as e_nifty:
        logger.debug(f"[OptionsBreakout] NIFTY benchmark fetch error: {e_nifty}")

    is_nifty_markdown = (
        nifty_change is not None and nifty_change <= -0.35 and nifty_below_vwap is not False
    )
    is_nifty_markup = (
        nifty_change is not None and nifty_change >= 0.40 and nifty_below_vwap is False
    )

    is_test_env = (
        os.environ.get("CHANAKYA_TESTING") == "1"
        or os.environ.get("DEPLOY_MODE") == "test"
        or ("PYTEST_CURRENT_TEST" in os.environ)
    )

    # Stage 1: Fast Batch-fetch underlying spot quotes for all targets in one call (<150ms)
    formatted_targets = [f"{resolve_index_exchange(s)}:{s}" for s in target_list]
    if batch_quotes is None:
        try:
            batch_quotes = get_quote(formatted_targets)
        except Exception as e_batch:
            logger.debug(f"[OptionsBreakout] Batch quote pre-fetch error: {e_batch}")
            batch_quotes = {}

    for sym in target_list:
        clean_sym = sym.replace("NSE:", "").replace("NFO:", "").replace("BSE:", "").strip().upper()
        try:
            exch = resolve_index_exchange(clean_sym)
            lookup_sym = f"{exch}:{clean_sym}"
            quote_obj = (
                (batch_quotes.get(lookup_sym) or batch_quotes.get(clean_sym))
                if batch_quotes
                else None
            )
            spot = (
                float(
                    getattr(quote_obj, "last_price", 0.0) or getattr(quote_obj, "ltp", 0.0) or 0.0
                )
                if quote_obj
                else 0.0
            )
            if spot <= 0:
                spot = get_ltp(lookup_sym) or 0.0
            if spot <= 0:
                continue

            spot_change_pct = (
                float(getattr(quote_obj, "change_pct", 0.0) or 0.0) if quote_obj else 0.0
            )
            spot_open = float(getattr(quote_obj, "open", 0.0) or 0.0) if quote_obj else 0.0
            spot_high = float(getattr(quote_obj, "high", 0.0) or 0.0) if quote_obj else 0.0
            spot_low = float(getattr(quote_obj, "low", 0.0) or 0.0) if quote_obj else 0.0
            spot_vwap = float(getattr(quote_obj, "vwap", 0.0) or 0.0) if quote_obj else 0.0

            is_idx = clean_sym in (
                "NIFTY",
                "BANKNIFTY",
                "FINNIFTY",
                "MIDCPNIFTY",
                "SENSEX",
                "BANKEX",
            )
            alert_segment = "FNO_INDEX" if is_idx else "FNO_STOCK"

            # ── STAGE 1: SPOT MOVEMENT & OPENING DRIVE PRE-FILTER ──
            # For single-stock F&O, skip cash equities and skip inactive stocks with 0 momentum.
            is_bear_drive = False
            is_bull_drive = False
            if not is_idx:
                from engine.position_sizer import get_lot_size

                if get_lot_size(clean_sym) <= 1:
                    continue
                if spot_open > 0:
                    if (
                        spot_high > 0
                        and (abs(spot_high - spot_open) / spot_open <= 0.0015)
                        and spot_change_pct <= -0.4
                    ):
                        is_bear_drive = True  # Open = High Bearish Liquidation Drive
                    elif (
                        spot_low > 0
                        and (abs(spot_low - spot_open) / spot_open <= 0.0015)
                        and spot_change_pct >= 0.4
                    ):
                        is_bull_drive = True  # Open = Low Bullish Institutional Sweep

                is_vwap_displaced = bool(
                    spot_vwap > 0 and abs(spot - spot_vwap) / spot_vwap >= 0.005
                )
                is_momentum_active = bool(
                    abs(spot_change_pct) >= 0.50
                    or (spot_open > 0 and abs(spot - spot_open) / spot_open >= 0.005)
                )

                if not is_test_env and not (
                    is_momentum_active or is_bear_drive or is_bull_drive or is_vwap_displaced
                ):
                    continue

            active_targets.append(
                {
                    "sym": sym,
                    "clean_sym": clean_sym,
                    "exch": exch,
                    "lookup_sym": lookup_sym,
                    "spot": spot,
                    "spot_change_pct": spot_change_pct,
                    "spot_open": spot_open,
                    "spot_high": spot_high,
                    "spot_low": spot_low,
                    "spot_vwap": spot_vwap,
                    "is_idx": is_idx,
                    "alert_segment": alert_segment,
                    "is_bear_drive": is_bear_drive,
                    "is_bull_drive": is_bull_drive,
                }
            )
        except Exception as e_sym:
            logger.debug(f"[OptionsBreakout] Pre-filter error for {sym}: {e_sym}")

    def _eval_sym(sym_info: dict[str, Any]) -> Optional[tuple[float, AutoAlert]]:
        sym = sym_info["sym"]
        clean_sym = sym_info["clean_sym"]
        exch = sym_info["exch"]
        spot = sym_info["spot"]
        spot_change_pct = sym_info["spot_change_pct"]
        spot_open = sym_info["spot_open"]
        spot_vwap = sym_info["spot_vwap"]
        is_idx = sym_info["is_idx"]
        alert_segment = sym_info["alert_segment"]
        is_bear_drive = sym_info["is_bear_drive"]
        is_bull_drive = sym_info["is_bull_drive"]
        try:
            # Institutional Single-Stock Expiry Protection:
            # Under SEBI regulations, single-stock options are physically settled.
            # In settlement week (DTE <= 4), automatically route stock options to Next-Month
            # series to eliminate staggered physical delivery margins (25%->100%) and near-month theta collapse.
            chain = None
            is_next_month_routed = False
            if not is_idx:
                try:
                    from engine.alert_expiry import (
                        is_monthly_physical_expiry_week,
                        resolve_recommended_derivative_expiry,
                    )
                    from market.options import get_expiries

                    available_exps = get_expiries(clean_sym)
                    exp_res = resolve_recommended_derivative_expiry(
                        symbol=clean_sym,
                        instrument_type="OPTION",
                        available_expiries=available_exps,
                        ref_dt=now_dt,
                    )
                    if exp_res.get("is_next_month_routed"):
                        next_exp_str = exp_res.get("recommended_expiry")
                        next_chain = get_options_chain(clean_sym, expiry=next_exp_str)
                        if next_chain and any(
                            float(getattr(c, "last_price", 0.0) or 0.0) > 0 for c in next_chain
                        ):
                            chain = next_chain
                            is_next_month_routed = True
                except Exception as e_exp:
                    logger.debug(
                        f"[OptionsBreakout] Next-month rollover check failed for {clean_sym}: {e_exp}"
                    )

            if chain is None:
                chain = get_options_chain(clean_sym)

            if not chain:
                return None

            min_opt_volume = (
                (2000 if is_idx else 300) if is_opening_drive else (3000 if is_idx else 500)
            )
            min_oi = 10000 if is_idx else 300

            max_strike_dist = (
                (
                    120.0
                    if clean_sym in ("NIFTY", "FINNIFTY")
                    else (
                        250.0
                        if clean_sym in ("BANKNIFTY", "SENSEX", "BANKEX")
                        else (75.0 if clean_sym in ("MIDCPNIFTY",) else 100.0)
                    )
                )
                if is_idx
                else spot * 0.02
            )
            min_opt_price = 10.0 if is_idx else 2.0

            atm_contracts = [
                c
                for c in chain
                if abs(getattr(c, "strike", 0.0) - spot) <= max_strike_dist
                and getattr(c, "last_price", 0.0) >= min_opt_price
                and getattr(c, "volume", 0) >= min_opt_volume
            ]
            if not atm_contracts:
                return None

            if is_idx:
                atm_contracts.sort(key=lambda c: abs(getattr(c, "strike", 0.0) - spot))
            else:
                # Institutional Single-Stock High-Torque Sweet-Spot Scoring (Delta 0.38 - 0.48):
                # Balances moneyness, turnover, and premium sweet-spot (1.2% - 3.5% of spot)
                def _stock_strike_score(c):
                    c_strk = getattr(c, "strike", 0.0)
                    c_prem = float(getattr(c, "last_price", 0.0) or 0.0)
                    c_v = getattr(c, "volume", 0)
                    c_o = getattr(c, "oi", 0)
                    dist_p = abs(c_strk - spot) / max(1.0, spot)
                    prem_ratio = c_prem / max(1.0, spot)
                    prem_score = max(0.0, 10.0 - abs(prem_ratio - 0.022) * 250.0)
                    turnover = min(15.0, (c_v / max(1, c_o)) * 5.0)
                    return prem_score + turnover - (dist_p * 80.0)

                atm_contracts.sort(key=_stock_strike_score, reverse=True)

            # ── Underlying Price Action & SMC Due Diligence ──
            from market.history import get_ohlcv

            df_5m = None
            try:
                df_5m = get_ohlcv(clean_sym, exchange=exch, interval="5minute", days=2)
            except Exception:
                pass

            if df_5m is not None and len(df_5m) >= 1:
                try:
                    last_c = float(df_5m.iloc[-1].get("close", df_5m.iloc[-1].get("Close", 0.0)))
                    if last_c > 0 and abs(last_c - spot) / max(1.0, spot) > 0.02:
                        df_5m = None
                except Exception:
                    pass

            if (not spot_vwap or spot_vwap <= 0) and df_5m is not None and len(df_5m) >= 2:
                try:
                    vols = df_5m["volume"].values
                    highs = (
                        df_5m["high"].values if "high" in df_5m.columns else df_5m["High"].values
                    )
                    lows = df_5m["low"].values if "low" in df_5m.columns else df_5m["Low"].values
                    closes = (
                        df_5m["close"].values if "close" in df_5m.columns else df_5m["Close"].values
                    )
                    typical_price = (highs + lows + closes) / 3.0
                    cum_vol = np.cumsum(vols)
                    cum_pv = np.cumsum(typical_price * vols)
                    if cum_vol[-1] > 0:
                        spot_vwap = float(cum_pv[-1] / cum_vol[-1])
                except Exception:
                    pass

            upper_wick_ratio = 0.0
            lower_wick_ratio = 0.0
            candle_range = 0.0
            if df_5m is not None and len(df_5m) >= 1:
                try:
                    last_bar = df_5m.iloc[-1]
                    b_high = float(last_bar.get("high", last_bar.get("High", 0.0)))
                    b_low = float(last_bar.get("low", last_bar.get("Low", 0.0)))
                    b_open = float(last_bar.get("open", last_bar.get("Open", 0.0)))
                    b_close = float(last_bar.get("close", last_bar.get("Close", 0.0)))
                    candle_range = max(0.01, b_high - b_low)
                    upper_wick_ratio = (b_high - max(b_open, b_close)) / candle_range
                    lower_wick_ratio = (min(b_open, b_close) - b_low) / candle_range
                except Exception:
                    pass

            for c in atm_contracts:
                vol = getattr(c, "volume", 0)
                oi = getattr(c, "oi", 0)
                oi_change = getattr(c, "oi_change", 0)
                vol_oi = round(vol / max(1, oi), 2)
                opt_ltp = float(getattr(c, "last_price", 0.0) or 0.0)
                opt_type = getattr(c, "option_type", "")
                strike = float(getattr(c, "strike", 0.0))
                contract_sym = getattr(c, "symbol", f"{clean_sym}{int(strike)}{opt_type}")
                expiry_date = getattr(c, "expiry", None)
                lot_sz = get_lot_size(clean_sym)

                if oi < min_oi:
                    continue

                # 0DTE Expiry Day Afternoon Theta Guard
                is_zero_dte_pm = False
                if expiry_date:
                    try:
                        from engine.alert_expiry import is_0dte_afternoon

                        is_zero_dte_pm = is_0dte_afternoon(str(expiry_date), ref_dt=now_dt)
                        if is_zero_dte_pm:
                            if opt_type == "CE" and strike > (spot * 1.002):
                                continue
                            if opt_type == "PE" and strike < (spot * 0.998):
                                continue
                    except Exception:
                        pass

                max_dte = 8 if clean_sym in ("NIFTY",) else 45
                if expiry_date:
                    try:
                        exp_str = str(expiry_date).split("T")[0].strip()
                        exp_dt = None
                        for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
                            try:
                                exp_dt = datetime.strptime(exp_str, fmt).date()
                                break
                            except ValueError:
                                continue
                        if exp_dt and (exp_dt - now_dt.date()).days > max_dte:
                            continue
                    except Exception:
                        pass

                if is_opening_drive:
                    min_vol_oi = 0.60 if is_idx else 1.00
                    min_contracts = 2000 if is_idx else 500
                else:
                    min_vol_oi = 1.00 if is_idx else 1.20
                    min_contracts = 2500 if is_idx else 600

                if vol_oi < min_vol_oi or vol < min_contracts:
                    continue

                bid = getattr(c, "bid", None)
                ask = getattr(c, "ask", None)
                max_spread_mult = 1.30 if is_idx else 1.15
                if bid and ask and bid > 0 and ask > 0 and ask > (bid * max_spread_mult):
                    continue

                is_physical_expiry_week = False
                if not is_idx and expiry_date:
                    try:
                        from engine.alert_expiry import is_monthly_physical_expiry_week

                        is_physical_expiry_week = is_monthly_physical_expiry_week(
                            str(expiry_date), symbol=clean_sym, ref_dt=now_dt
                        )
                    except Exception:
                        pass

                pchange = getattr(c, "pchange", None)
                min_pchange = 8.0 if is_opening_drive else 6.0
                if opt_type == "CE":
                    if pchange is not None and pchange < min_pchange:
                        continue
                    if spot_change_pct is not None and spot_change_pct < -1.5:
                        continue
                    if spot_open and spot_open > 0 and spot < spot_open * 0.995:
                        continue
                    if is_idx:
                        if spot_vwap and spot_vwap > 0 and spot < spot_vwap:
                            continue
                    else:
                        if spot_vwap and spot_vwap > 0 and spot < spot_vwap * 1.0005:
                            continue
                    if candle_range >= (spot * 0.0025) and upper_wick_ratio > 0.50:
                        continue
                    direction = "BULLISH"
                elif opt_type == "PE":
                    if pchange is not None and pchange < min_pchange:
                        continue
                    if spot_change_pct is not None and spot_change_pct > 1.5:
                        continue
                    if spot_open and spot_open > 0 and spot > spot_open * 1.005:
                        continue
                    if spot_vwap and spot_vwap > 0 and spot > spot_vwap * 1.007:
                        continue
                    else:
                        if spot_vwap and spot_vwap > 0 and spot > spot_vwap * 0.9995:
                            continue
                    if candle_range >= (spot * 0.0025) and lower_wick_ratio > 0.50:
                        continue
                    direction = "BEARISH"
                else:
                    continue

                mtf_15m_trend = "NEUTRAL"
                try:
                    df_15m = get_ohlcv(clean_sym, days=4, interval="15minute")
                    if df_15m is not None and len(df_15m) >= 15:
                        c_15 = df_15m["close"] if "close" in df_15m.columns else df_15m["Close"]
                        ema20_15 = float(c_15.ewm(span=20, adjust=False).mean().iloc[-1])
                        ema50_15 = (
                            float(c_15.ewm(span=50, adjust=False).mean().iloc[-1])
                            if len(c_15) >= 40
                            else ema20_15
                        )
                        if spot >= (ema20_15 * 0.998) and ema20_15 >= (ema50_15 * 0.998):
                            mtf_15m_trend = "BULLISH"
                        elif spot <= (ema20_15 * 1.002) and ema20_15 <= (ema50_15 * 1.002):
                            mtf_15m_trend = "BEARISH"
                except Exception as e_mtf:
                    logger.debug(f"[OptionsBreakout] MTF 15m fetch failed for {clean_sym}: {e_mtf}")

                has_opening_breakdown = bool(
                    (spot_open and spot <= spot_open * 0.996)
                    and (spot_vwap and spot <= spot_vwap * 0.999)
                    and (lower_wick_ratio <= 0.35)
                )
                has_opening_breakout = bool(
                    (spot_open and spot >= spot_open * 1.004)
                    and (spot_vwap and spot >= spot_vwap * 1.001)
                    and (upper_wick_ratio <= 0.35)
                )

                if opt_type == "CE" and mtf_15m_trend == "BEARISH" and not has_opening_breakout:
                    logger.debug(
                        f"[OptionsBreakout] Suppressed Call breakout on {clean_sym}: 15m trend BEARISH"
                    )
                    continue
                if opt_type == "PE" and mtf_15m_trend == "BULLISH" and not has_opening_breakdown:
                    logger.debug(
                        f"[OptionsBreakout] Suppressed Put surge on {clean_sym}: 15m trend BULLISH"
                    )
                    continue

                is_decoupler = False
                opt_pch = getattr(c, "pchange", 0.0) or getattr(c, "change_pct", 0.0) or 0.0
                if not is_idx:
                    if opt_type == "CE":
                        if (vol_oi >= 1.8 and vol >= 2500 and opt_pch >= 15.0) or (
                            spot_change_pct
                            and spot_change_pct >= 1.8
                            and (vol_oi >= 1.2 or vol >= 2000)
                        ):
                            is_decoupler = True
                    elif opt_type == "PE":
                        if (vol_oi >= 1.8 and vol >= 2500 and opt_pch >= 15.0) or (
                            spot_change_pct
                            and spot_change_pct <= -1.8
                            and (vol_oi >= 1.2 or vol >= 2000)
                        ):
                            is_decoupler = True

                is_writer_panic = False
                writer_panic_note = ""
                if oi_change is not None and oi > 0:
                    try:
                        oi_chg_f = float(oi_change)
                        base_oi = max(1.0, oi - oi_chg_f)
                        oi_chg_pct = (oi_chg_f / base_oi) * 100.0
                        if opt_type == "CE" and (oi_chg_pct <= -4.0 or oi_chg_f <= -25000):
                            is_writer_panic = True
                            writer_panic_note = (
                                f"Call Writer Capitulation: OI shedding {oi_chg_pct:.1f}% "
                                f"({oi_chg_f:,.0f} contracts unwound) — short squeeze cascade active"
                            )
                        elif opt_type == "PE" and (oi_chg_pct <= -4.0 or oi_chg_f <= -25000):
                            is_writer_panic = True
                            writer_panic_note = (
                                f"Put Writer Capitulation: OI shedding {oi_chg_pct:.1f}% "
                                f"({oi_chg_f:,.0f} contracts unwound) — long liquidation cascade active"
                            )
                    except Exception:
                        pass

                # Extreme Idiosyncratic Catalyst Escape Hatch:
                # Allows stock options to fire even if parent sector is not supportive,
                # ONLY IF extraordinary volume/OI turnover, huge price displacement, or writer panic decouples it.
                is_extreme_catalyst = False
                if not is_idx:
                    is_extreme_catalyst = bool(
                        is_decoupler
                        or is_writer_panic
                        or (vol_oi >= 2.5 and vol >= 1500)
                        or (spot_change_pct and abs(spot_change_pct) >= 2.5)
                    )

                # ── Time-of-Day Institutional Gates ──
                if not is_test_env:
                    # 1. Opening Auction Discovery Freeze (09:15 - 09:25 IST)
                    # Squelch speculative breakout buying before morning market structure forms
                    if is_opening_freeze and not (
                        is_bear_drive or is_bull_drive or is_extreme_catalyst
                    ):
                        logger.debug(
                            f"[OptionsBreakout] Suppressed {clean_sym} during 09:15-09:25 IST opening auction discovery"
                        )
                        continue

                    # 2. Midday Volume Lull (11:45 - 13:15 IST)
                    # Suppress single-stock options during midday consolidation unless extreme catalyst
                    if is_midday_lull and not is_idx and not is_extreme_catalyst:
                        if vol_oi < 2.0 or vol < 1500:
                            logger.debug(
                                f"[OptionsBreakout] Suppressed {clean_sym} during 11:45-13:15 IST midday lull (vol_oi {vol_oi}x < 2.0x)"
                            )
                            continue

                    # 3. Late Session Intraday Theta Drag (post-14:45 IST)
                    # Ban new intraday option buying setups into market close
                    if is_late_session_theta and not is_next_month_routed:
                        logger.debug(
                            f"[OptionsBreakout] Suppressed {clean_sym} post-14:45 IST: terminal intraday theta collapse"
                        )
                        continue

                # Institutional Sector Support Gate ("A rising tide lifts all boats")
                sector_tailwind_bonus = 0
                sec_id = None
                sec_name = None
                tailwind = None
                if not is_idx:
                    try:
                        from analysis.universe import get_stock_sector
                        from analysis.sector_rotation import get_stock_tailwind

                        sec_id, sec_name = get_stock_sector(clean_sym)
                        tailwind = get_stock_tailwind(clean_sym)
                    except Exception as e_sec:
                        logger.debug(
                            f"[OptionsBreakout] Sector lookup failed for {clean_sym}: {e_sec}"
                        )

                    if tailwind and hasattr(tailwind, "quadrant"):
                        quad = tailwind.quadrant
                        rs_intra = float(getattr(tailwind, "intraday_rs", 0.0) or 0.0)
                        align = getattr(tailwind, "alignment", "")
                        intra_align = getattr(tailwind, "intraday_alignment", "")

                        if opt_type == "CE":
                            is_sector_support = bool(
                                quad in ("LEADING", "IMPROVING")
                                or rs_intra >= 0.20
                                or align in ("STRONG_TAILWIND", "MODERATE_TAILWIND")
                                or intra_align in ("STRONG_INTRADAY_TAILWIND", "INTRADAY_TAILWIND")
                            )
                            if is_sector_support:
                                sector_tailwind_bonus = 10
                            elif not is_extreme_catalyst:
                                logger.debug(
                                    f"[OptionsBreakout] Suppressed Call on {clean_sym}: Lacks sector support ({sec_name} in {quad}, RS {rs_intra:+.2f}%) and no extreme catalyst"
                                )
                                continue
                        elif opt_type == "PE":
                            is_sector_support = bool(
                                quad in ("LAGGING", "WEAKENING")
                                or rs_intra <= -0.20
                                or align in ("HEADWIND", "NEUTRAL")
                                or intra_align
                                in ("HEADWIND", "INTRADAY_HEADWIND", "SEVERE_INTRADAY_HEADWIND")
                            )
                            if is_sector_support:
                                sector_tailwind_bonus = 10
                            elif not is_extreme_catalyst:
                                logger.debug(
                                    f"[OptionsBreakout] Suppressed Put on {clean_sym}: Lacks sector support ({sec_name} in {quad}, RS {rs_intra:+.2f}%) and no extreme catalyst"
                                )
                                continue

                if not is_idx and is_nifty_markdown and opt_type == "CE":
                    from analysis.universe import get_stock_sector

                    if not sec_name:
                        sec_id, sec_name = get_stock_sector(clean_sym)
                    is_defensive = any(
                        d in (sec_name or "").upper() for d in ("PHARMA", "FMCG", "HEALTH")
                    )
                    is_thematic = any(
                        d in (sec_name or "").upper()
                        for d in (
                            "DEFENCE",
                            "RAIL",
                            "ENERGY",
                            "CAPITAL",
                            "INFRA",
                            "EMS",
                            "TECH",
                            "SOLAR",
                            "CONSUMER",
                        )
                    )
                    if not (
                        is_defensive
                        or is_thematic
                        or sector_tailwind_bonus > 0
                        or is_extreme_catalyst
                    ):
                        logger.debug(
                            f"[OptionsBreakout] Suppressed Call breakout on {clean_sym}: NIFTY in markdown ({nifty_change:.2f}%)"
                        )
                        continue

                if not is_idx and is_nifty_markup and opt_type == "PE":
                    from analysis.universe import get_stock_sector

                    if not sec_name:
                        sec_id, sec_name = get_stock_sector(clean_sym)
                    is_lagging = any(d in (sec_name or "").upper() for d in ("MEDIA", "REALTY"))
                    if not (is_lagging or sector_tailwind_bonus > 0 or is_extreme_catalyst):
                        logger.debug(
                            f"[OptionsBreakout] Suppressed Put surge on {clean_sym}: NIFTY in markup (+{nifty_change:.2f}%)"
                        )
                        continue

                is_gamma_squeeze = False
                if opt_type == "CE":
                    if oi_change and oi_change < 0:
                        is_gamma_squeeze = True
                    elif oi_change and oi_change > 0 and spot_vwap and spot < spot_vwap:
                        logger.debug(
                            f"[OptionsBreakout] Suppressed CE on {clean_sym}: Call writing wall below VWAP"
                        )
                        continue
                elif opt_type == "PE":
                    if oi_change and oi_change < 0:
                        is_gamma_squeeze = True

                vix_val = None
                try:
                    from market.indices import get_vix

                    vix_val = get_vix()
                except Exception:
                    vix_val = None

                if vix_val and vix_val > 0:
                    if vix_val < 12.0:
                        vix_regime = "LOW_VOLATILITY"
                    elif vix_val <= 18.0:
                        vix_regime = "NORMAL_VOLATILITY"
                    elif vix_val <= 24.0:
                        vix_regime = "ELEVATED_VOLATILITY"
                    else:
                        vix_regime = "EXTREME_VOLATILITY"
                else:
                    vix_regime = "NORMAL_VOLATILITY"

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
                        conf_candle = (
                            conf_res.get("pattern") if isinstance(conf_res, dict) else None
                        )
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
                            # Bypass RSI divergence veto if explosive momentum / high turnover is active
                            # Explosive trends routinely exhibit minor 5m RSI divergence while continuation surges
                            is_explosive_momentum = bool(
                                is_extreme_catalyst
                                or (vol_oi >= 1.8 and vol >= 800)
                                or (vol >= 500 and (pchange or 0.0) >= 8.0)
                                or (spot_change_pct and abs(spot_change_pct) >= 2.0)
                            )
                            if opt_type == "CE" and div_bias == "BEARISH" and "REGULAR" in div_type:
                                if is_explosive_momentum:
                                    logger.debug(
                                        f"[OptionsBreakout] Bypassed bearish RSI divergence on {clean_sym} due to explosive momentum (vol_oi={vol_oi:.2f}, pchange={pchange}%)"
                                    )
                                else:
                                    logger.debug(
                                        f"[OptionsBreakout] Suppressed CE on {clean_sym}: Bearish RSI divergence trap ({div_type})"
                                    )
                                    continue
                            elif (
                                opt_type == "PE" and div_bias == "BULLISH" and "REGULAR" in div_type
                            ):
                                if is_explosive_momentum:
                                    logger.debug(
                                        f"[OptionsBreakout] Bypassed bullish RSI divergence on {clean_sym} due to explosive momentum (vol_oi={vol_oi:.2f}, pchange={pchange}%)"
                                    )
                                else:
                                    logger.debug(
                                        f"[OptionsBreakout] Suppressed PE on {clean_sym}: Bullish RSI divergence trap ({div_type})"
                                    )
                                    continue
                            elif (opt_type == "CE" and div_bias == "BULLISH") or (
                                opt_type == "PE" and div_bias == "BEARISH"
                            ):
                                divergence_bonus = 6
                    except Exception as e_smc:
                        logger.debug(
                            f"[OptionsBreakout] SMC candle/divergence error for {clean_sym}: {e_smc}"
                        )

                if df_5m is not None and len(df_5m) >= 10:
                    try:
                        from engine.signal_ensemble import ensemble_signal

                        ens = ensemble_signal(df_5m)
                        conf = getattr(ens, "confidence", 0.0) or 0.0
                        conf_pct = conf * 100.0 if conf <= 1.0 else conf
                        if ens and conf_pct >= 55.0:
                            verd = str(getattr(ens, "verdict", "")).upper()
                            sig_val = getattr(ens, "signal", 0)
                            is_bear = verd == "BEARISH" or sig_val == -1
                            is_bull = verd == "BULLISH" or sig_val == 1
                            if (opt_type == "CE" and is_bear) or (opt_type == "PE" and is_bull):
                                logger.debug(
                                    f"[OptionsBreakout] Suppressed {opt_type} on {clean_sym}: Ensemble veto ({verd} {conf_pct:.0f}%)"
                                )
                                continue
                    except Exception as e_ens:
                        logger.debug(
                            f"[OptionsBreakout] Ensemble veto error for {clean_sym}: {e_ens}"
                        )

                vp_bonus = 0
                vp_tags = []
                if df_5m is not None and len(df_5m) >= 10:
                    try:
                        from analysis.volume_profile import compute_volume_profile

                        vp = compute_volume_profile(df_5m)
                        if vp and getattr(vp, "poc", 0) > 0:
                            poc_dist = abs(spot - vp.poc) / max(1.0, spot)
                            if opt_type == "CE" and spot >= vp.vah * 0.998:
                                vp_bonus += 5
                                vp_tags.append("VAH_BREAKOUT")
                                if spot > vp.vah * 1.002:
                                    vp_bonus += 3
                                    vp_tags.append("LVN_VACUUM_AIRSPACE")
                            elif opt_type == "CE" and poc_dist <= 0.003:
                                vp_bonus += 4
                                vp_tags.append("POC_SUPPORT_BOUNCE")
                            elif opt_type == "PE" and spot <= vp.val * 1.002:
                                vp_bonus += 5
                                vp_tags.append("VAL_BREAKDOWN")
                                if spot < vp.val * 0.998:
                                    vp_bonus += 3
                                    vp_tags.append("LVN_VACUUM_AIRSPACE")
                            elif opt_type == "PE" and poc_dist <= 0.003:
                                vp_bonus += 4
                                vp_tags.append("POC_RESISTANCE_REJECT")
                    except Exception as e_vp:
                        logger.debug(
                            f"[OptionsBreakout] Volume profile error for {clean_sym}: {e_vp}"
                        )

                alert_id = (
                    f"aa-optmom-{opt_type.lower()}-{clean_sym}-{int(strike)}-{uuid.uuid4().hex[:6]}"
                )

                tp = None
                opt_plan = None
                try:
                    from engine.trade_plan import (
                        calculate_trade_plan,
                        calculate_option_execution_plan,
                    )

                    opt_exchange = "BFO" if exch == "BSE" else "NFO"
                    tp = calculate_trade_plan(
                        symbol=clean_sym,
                        direction="BUY" if opt_type == "CE" else "SELL",
                        spot=spot,
                        timeframe="INTRADAY",
                        exchange=opt_exchange,
                        has_active_blast=(vol_oi >= 2.0),
                    )
                    if tp and tp.invalidation_stop > 0:
                        opt_plan = calculate_option_execution_plan(
                            trade_plan=tp,
                            option_type=opt_type,
                            strike=strike,
                            expiry=str(expiry_date) if expiry_date else "",
                            option_ltp=opt_ltp,
                            lot_size=lot_sz,
                        )
                except Exception as e_tp:
                    logger.debug(f"[OptionsBreakout] Trade plan calculation failed: {e_tp}")

                if opt_plan and opt_plan.get("sl_premium") and opt_plan.get("t1_premium"):
                    opt_sl = float(opt_plan["sl_premium"])
                    opt_t1 = float(opt_plan["t1_premium"])
                    max_opt_sl_risk = round(opt_ltp * 0.28, 2)
                    opt_sl = max(opt_sl, round(opt_ltp - max_opt_sl_risk, 2))
                    opt_risk = max(0.2, opt_ltp - opt_sl)
                    opt_t0_5 = round(opt_ltp + 1.0 * opt_risk, 2)
                    opt_t1 = max(
                        float(opt_plan.get("t1_premium") or 0.0), round(opt_ltp + 1.8 * opt_risk, 2)
                    )
                    opt_t2 = max(
                        float(opt_plan.get("t2_premium") or 0.0), round(opt_ltp + 3.0 * opt_risk, 2)
                    )
                    opt_moonshot = max(
                        float(opt_plan.get("t3_premium") or 0.0), round(opt_ltp + 5.0 * opt_risk, 2)
                    )
                    rr_val = round((opt_t1 - opt_ltp) / max(0.01, opt_risk), 1)
                    rr_str = f"1:{rr_val}"
                else:
                    risk_pts = round(max(0.20, min(opt_ltp * 0.28, opt_ltp - 0.05)), 2)
                    opt_sl = round(max(0.05, opt_ltp - risk_pts), 2)
                    opt_t0_5 = round(opt_ltp + 1.0 * risk_pts, 2)
                    opt_t1 = round(opt_ltp + 1.8 * risk_pts, 2)
                    opt_t2 = round(opt_ltp + 3.0 * risk_pts, 2)
                    opt_moonshot = round(opt_ltp + 5.0 * risk_pts, 2)
                    rr_val = round((opt_t1 - opt_ltp) / max(0.01, risk_pts), 1)
                    rr_str = f"1:{rr_val}"

                friday_tag = (
                    " ⚠️ FRIDAY POST-14:30: Weekend theta decay risk; Intraday Quick Scalp only (Square off by 15:20 IST) or trade Bull Call Spread."
                    if is_friday_late
                    else ""
                )
                dte_pm_tag = (
                    " ⚠️ 0DTE AFTERNOON: Accelerated theta decay active. Deep ATM/ITM only; mandatory square-off by 15:15 IST."
                    if is_zero_dte_pm
                    else ""
                )
                phys_tag = (
                    " ⚠️ SEBI Physical Delivery Expiry Week: STAGGERED MARGIN SURGE (25%->100% full lot cash value). INTRADAY SCALP ONLY — MANDATORY EXIT BY 15:00 IST."
                    if (is_physical_expiry_week and not is_next_month_routed)
                    else ""
                )
                rollover_tag = (
                    f" 🎯 NEXT-MONTH ROLLOVER ({expiry_date}): Bypasses SEBI physical delivery margin surge & near-month theta collapse."
                    if is_next_month_routed
                    else ""
                )

                conf_score = 50
                if vol_oi >= 3.0:
                    conf_score += 20
                elif vol_oi >= 2.0:
                    conf_score += 15
                elif vol_oi >= 1.5:
                    conf_score += 10
                elif vol_oi >= 1.2:
                    conf_score += 5

                opt_pch = getattr(c, "pchange", 0.0) or 0.0
                if opt_pch >= 20.0:
                    conf_score += 15
                elif opt_pch >= 12.0:
                    conf_score += 10
                elif opt_pch >= 6.0:
                    conf_score += 5

                if spot_vwap and spot_vwap > 0:
                    vwap_dist_pct = abs(spot - spot_vwap) / spot_vwap * 100.0
                    if opt_type == "CE" and spot >= spot_vwap * 1.005:
                        conf_score += 12 if vwap_dist_pct >= 0.8 else 8
                    elif opt_type == "PE" and spot <= spot_vwap * 0.995:
                        conf_score += 12 if vwap_dist_pct >= 0.8 else 8
                    elif (opt_type == "CE" and spot >= spot_vwap) or (
                        opt_type == "PE" and spot <= spot_vwap
                    ):
                        conf_score += 4

                if tp and tp.is_asymmetry_viable:
                    conf_score += 8

                if upper_wick_ratio <= 0.20 and lower_wick_ratio <= 0.20:
                    conf_score += 5

                if is_writer_panic:
                    conf_score += 10
                elif is_gamma_squeeze:
                    conf_score += 7
                elif oi_change and oi_change < 0:
                    conf_score += 4

                if mtf_15m_trend == ("BULLISH" if opt_type == "CE" else "BEARISH"):
                    conf_score += 7

                if is_nifty_markdown and opt_type == "PE":
                    conf_score += 6
                elif is_nifty_markup and opt_type == "CE":
                    conf_score += 6

                opening_drive_bonus = 0
                drive_tag = ""
                if is_bear_drive and opt_type == "PE":
                    opening_drive_bonus = 10
                    drive_tag = " ⚡ OPENING DRIVE (Open=High)"
                elif is_bull_drive and opt_type == "CE":
                    opening_drive_bonus = 10
                    drive_tag = " ⚡ OPENING DRIVE (Open=Low)"

                decoupler_bonus = 10 if is_decoupler else 0
                conf_score += confirmation_bonus
                conf_score += divergence_bonus
                conf_score += vp_bonus
                conf_score += sector_tailwind_bonus
                conf_score += opening_drive_bonus
                conf_score += decoupler_bonus

                confidence = min(96, max(50, conf_score))

                ote_lower = round(max(0.05, opt_ltp * 0.96), 1)
                ote_upper = round(opt_ltp * 1.01, 1)
                max_chase = round(opt_ltp * 1.08, 1)
                entry_range_str = f"₹{ote_lower:,.1f} – ₹{ote_upper:,.1f}"
                when_to_wait_str = f"DO NOT CHASE if premium surges > 8% past entry (> ₹{max_chase:,.1f}). Wait for 5m consolidation retest."
                spot_anchor_str = (
                    f" (Spot Anchor: ₹{tp.invalidation_stop:,.1f})"
                    if (tp and tp.invalidation_stop > 0)
                    else ""
                )
                when_to_buy_str = (
                    f"Buy on ask/limit within entry range with spot invalidation anchor at ₹{tp.invalidation_stop:,.1f} (Option SL ₹{opt_sl:,.1f})."
                    if (tp and tp.invalidation_stop > 0)
                    else f"Buy on ask/limit within entry range with tight defined risk below ₹{opt_sl:,.1f}."
                )

                lot_tag = f" (Lot: {lot_sz})" if (lot_sz and lot_sz > 1) else ""
                sec_badge = f" [{sec_name.upper()}]" if (sec_name and not is_idx) else ""
                cat_badge = (
                    " ⚡ DECOUPLER"
                    if (not is_idx and is_extreme_catalyst and not sector_tailwind_bonus)
                    else ""
                )
                if opt_type == "PE":
                    headline = f"🔴 OPTIONS MOMENTUM{sec_badge}{cat_badge} (PUT SURGE): {contract_sym} @ ₹{opt_ltp:,.1f}{lot_tag} (Vol/OI {vol_oi}x)"
                    summary = (
                        f"Institutional Put surge in {clean_sym} {int(strike)} PE. "
                        f"Underlying spot ₹{spot:,.1f}{spot_anchor_str}. Turnover: {vol:,} contracts ({vol_oi}x OI). "
                        f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{opt_sl:,.1f} | T1: ₹{opt_t1:,.1f} (Scale 50% & SL to Cost) | T2: ₹{opt_t2:,.1f}.{drive_tag}{friday_tag}{dte_pm_tag}{phys_tag}{rollover_tag}"
                    )
                else:
                    headline = f"🟢 OPTIONS MOMENTUM{sec_badge}{cat_badge}: {contract_sym} @ ₹{opt_ltp:,.1f}{lot_tag} (Vol/OI {vol_oi}x)"
                    summary = (
                        f"Institutional Call surge in {clean_sym} {int(strike)} CE. "
                        f"Underlying spot ₹{spot:,.1f}{spot_anchor_str}. Turnover: {vol:,} contracts ({vol_oi}x OI). "
                        f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{opt_sl:,.1f} | T1: ₹{opt_t1:,.1f} (Scale 50% & SL to Cost) | T2: ₹{opt_t2:,.1f}.{drive_tag}{friday_tag}{dte_pm_tag}{phys_tag}{rollover_tag}"
                    )

                alert = AutoAlert(
                    alert_id=alert_id,
                    alert_type="OPTIONS_MOMENTUM",
                    stage=(
                        "IGNITED"
                        if (vol_oi >= 2.0 or (is_opening_drive and (vol_oi >= 0.50 or vol >= 6000)))
                        else "EARLY_WARNING"
                    ),
                    symbol=clean_sym,
                    exchange=opt_exchange,
                    direction=direction,
                    headline=headline,
                    summary=summary,
                    ltp=opt_ltp,
                    trigger_level=opt_ltp,
                    target_level=opt_t1,
                    stop_loss=opt_sl,
                    no_chase_boundary=max_chase,
                    strike=strike,
                    option_type=opt_type,
                    contract_symbol=contract_sym,
                    expiry_date=expiry_date,
                    expiry_type=classify_expiry_type(expiry_date, clean_sym),
                    segment=alert_segment,
                    lot_size=lot_sz,
                    option_premium=opt_ltp,
                    underlying_spot=spot,
                    confidence=confidence,
                    created_at=now_iso,
                    is_live=True,
                    environment="LIVE",
                    mtf_confluence=(
                        "BEARISH_BREAKDOWN"
                        if has_opening_breakdown
                        else ("BULLISH_BREAKOUT" if has_opening_breakout else mtf_15m_trend)
                    ),
                    vix_regime=vix_regime,
                    metrics={
                        "vol_oi_ratio": vol_oi,
                        "volume": vol,
                        "oi": oi,
                        "oi_change": oi_change,
                        "spot": spot,
                        "strike": strike,
                        "lot_size": lot_sz,
                        "spot_vwap": spot_vwap,
                        "spot_invalidation_anchor": tp.invalidation_stop if tp else None,
                        "spot_target_1": tp.target_1 if tp else None,
                        "spot_target_2": tp.target_2 if tp else None,
                        "upper_wick_ratio": round(upper_wick_ratio, 2),
                        "lower_wick_ratio": round(lower_wick_ratio, 2),
                        "high": getattr(c, "high", None),
                        "low": getattr(c, "low", None),
                        "open": getattr(c, "open", None),
                        "close": getattr(c, "close", None),
                        "is_friday_late": is_friday_late,
                        "is_opening_drive": bool(is_bear_drive or is_bull_drive),
                        "opening_drive_type": "BEARISH_OPEN_EQUALS_HIGH"
                        if is_bear_drive
                        else ("BULLISH_OPEN_EQUALS_LOW" if is_bull_drive else None),
                        "mtf_15m_trend": (
                            "BEARISH_BREAKDOWN"
                            if has_opening_breakdown
                            else ("BULLISH_BREAKOUT" if has_opening_breakout else mtf_15m_trend)
                        ),
                        "has_opening_breakdown": has_opening_breakdown,
                        "has_opening_breakout": has_opening_breakout,
                        "vix_regime": vix_regime,
                        "india_vix": vix_val,
                        "is_gamma_squeeze": is_gamma_squeeze,
                        "nifty_change_pct": nifty_change,
                        "nifty_below_vwap": nifty_below_vwap,
                        "nifty_regime": (
                            "MARKDOWN"
                            if is_nifty_markdown
                            else ("MARKUP" if is_nifty_markup else "NORMAL")
                        ),
                        "confirmation_candle": conf_candle,
                        "confirmation_confirmed": is_confirmed,
                        "divergence_type": div_type,
                        "divergence_bias": div_bias,
                        "volume_profile_tags": vp_tags,
                        "is_writer_panic": is_writer_panic,
                        "writer_panic_note": writer_panic_note if is_writer_panic else None,
                        "is_lvn_vacuum": "LVN_VACUUM_AIRSPACE" in vp_tags,
                        "is_0dte_afternoon": is_zero_dte_pm,
                        "physical_settlement_week": is_physical_expiry_week or is_next_month_routed,
                        "rollover_series": "NEXT_MONTH"
                        if is_next_month_routed
                        else "CURRENT_MONTH",
                        "is_rollover_recommended": is_next_month_routed,
                        "rollover_protected": is_next_month_routed,
                        "sector_tailwind_bonus": sector_tailwind_bonus,
                        "decoupler_status": "VERIFIED_DECOUPLER" if is_decoupler else "NORMAL",
                        "is_decoupler": is_decoupler,
                        "is_extreme_catalyst": is_extreme_catalyst if not is_idx else False,
                        "sector_id": sec_id or ("index" if is_idx else "broad_market"),
                        "sector_name": sec_name or ("Index F&O" if is_idx else "Broad Market"),
                        "sector_quadrant": getattr(tailwind, "quadrant", "UNAVAILABLE")
                        if tailwind
                        else "UNAVAILABLE",
                        "sector_alignment": getattr(tailwind, "alignment", "UNAVAILABLE")
                        if tailwind
                        else "UNAVAILABLE",
                        "sector_rs": float(getattr(tailwind, "intraday_rs", 0.0) or 0.0)
                        if tailwind
                        else 0.0,
                        "time_stop_mins": 20,
                    },
                    actionable_plan={
                        "action": f"BUY {opt_type}",
                        "segment": "FNO",
                        "contract": contract_sym,
                        "recommended_entry": f"₹{opt_ltp:,.2f}",
                        "entry_range": entry_range_str,
                        "stop_loss": f"₹{opt_sl:,.1f}",
                        "target_0_5": f"₹{opt_t0_5:,.1f}",
                        "target_1": f"₹{opt_t1:,.1f}",
                        "target": f"₹{opt_t1:,.1f}",
                        "target_2": f"₹{opt_t2:,.1f}",
                        "target_moonshot": f"₹{opt_moonshot:,.1f}",
                        "risk_reward": rr_str,
                        "when_to_buy": when_to_buy_str,
                        "when_to_wait": when_to_wait_str,
                        "impulse_trigger_level": f"₹{round(spot * (1.002 if opt_type == 'CE' else 0.998), 1):,.1f} (Spot Breakout Tick)",
                        "fast_scalp": {
                            "scalp_target_premium": f"₹{round(opt_ltp * 1.20, 1):,.1f}",
                            "scalp_target_pct": "+20.0%",
                            "scalp_target_eta": "10m–15m",
                            "scalp_profit_rule": "Book 70% at scalp target (+20%), move SL to Breakeven (+0.2%), let 30% runner ride",
                            "time_stop_mins": 20,
                            "time_stop_rule": "If position has < +0.40R or < +5% gain after 20 minutes, scratch at CMP to halt theta decay",
                        },
                        "profit_rule": (
                            f"🏆 3-TIER PROFIT-TAKING: "
                            f"1) Scale 50% at T1 (₹{opt_t1:,.1f}) & move SL to Breakeven (0 Risk). "
                            f"2) Scale 25% at T2 (₹{opt_t2:,.1f}). "
                            f"3) Trail final 25% on 15m VWAP / 20-EMA to Moonshot (₹{opt_moonshot:,.1f})."
                        ),
                        "option_plan": opt_plan,
                        "lot_size": lot_sz,
                        "spot_invalidation_anchor": f"₹{tp.invalidation_stop:,.1f}"
                        if (tp and tp.invalidation_stop > 0)
                        else None,
                        "sector_name": sec_name or ("Index F&O" if is_idx else "Broad Market"),
                        "sector_id": sec_id or ("index" if is_idx else "broad_market"),
                        "sector_support": "ALIGNED"
                        if sector_tailwind_bonus > 0
                        else ("DECOUPLER" if is_extreme_catalyst else "NEUTRAL"),
                        "friday_weekend_warning": friday_tag.strip() if friday_tag else None,
                        "zero_dte_afternoon_guard": (
                            "⚠️ 0DTE AFTERNOON: Accelerated theta decay active. Deep ATM/ITM only; mandatory square-off by 15:15 IST."
                            if is_zero_dte_pm
                            else None
                        ),
                        "rollover_notice": (
                            f"🎯 NEXT-MONTH ROLLOVER: Contract {contract_sym} expires {expiry_date} (bypasses SEBI delivery margin surge & theta decay)."
                            if is_next_month_routed
                            else None
                        ),
                        "physical_settlement_warning": (
                            "⚠️ SEBI Physical Delivery Expiry Week: STAGGERED MARGIN SURGE (25%->100% full lot cash value). Mandatory exit by 15:00 IST — DO NOT CARRY OVERNIGHT."
                            if (is_physical_expiry_week and not is_next_month_routed)
                            else None
                        ),
                    },
                )

                decoupler_pts = (
                    12.0
                    if alert.metrics.get("is_extreme_catalyst")
                    else (
                        10.0
                        if alert.metrics.get("decoupler_status") == "VERIFIED_DECOUPLER"
                        else 0.0
                    )
                )
                sector_pts = 10.0 if sector_tailwind_bonus > 0 else 0.0
                drive_pts = 5.0 if (is_bull_drive or is_bear_drive) else 0.0
                gamma_pts = 5.0 if is_gamma_squeeze else 0.0

                quality_score = (
                    (confidence * 0.40)
                    + min(25.0, vol_oi * 7.0)
                    + min(15.0, (vol / 5000.0) * 15.0)
                    + (10.0 if (tp and tp.is_asymmetry_viable) else 0.0)
                    + decoupler_pts
                    + sector_pts
                    + drive_pts
                    + gamma_pts
                )
                return (quality_score, alert)
            return None
        except Exception as e:
            logger.debug(f"[OptionsBreakout] Options momentum scan error for {sym}: {e}")
            return None

    if active_targets:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(6, len(active_targets))
        ) as executor:
            for cand_res in executor.map(_eval_sym, active_targets):
                if cand_res:
                    candidate_alerts.append(cand_res)

    # ── ANTI-STORM PACING & TOP-N QUALITY SELECTION ──
    candidate_alerts.sort(key=lambda x: x[0], reverse=True)
    max_cycle_alerts = 3 if is_opening_drive else 5

    recent_options_count = 0
    now_ts = time.time()
    for rec_a in recent_alerts or []:
        if rec_a.alert_type == "OPTIONS_MOMENTUM" and not rec_a.symbol.startswith(
            ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX")
        ):
            rec_epoch = rec_a.metrics.get("_recorded_epoch", 0) if rec_a.metrics else 0
            if rec_epoch and (now_ts - rec_epoch) <= 300:
                recent_options_count += 1

    for q_score, alert in candidate_alerts:
        if len(found) >= max_cycle_alerts:
            break

        is_stock = not alert.symbol.startswith(
            ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX")
        )
        if is_stock and (recent_options_count + len(found)) >= 3:
            if (
                alert.confidence < 88
                and alert.metrics.get("decoupler_status") != "VERIFIED_DECOUPLER"
            ):
                logger.debug(
                    f"[OptionsBreakout] Paced options alert {alert.symbol}: Rolling 5m limit reached (score {q_score:.1f}, conf {alert.confidence})"
                )
                continue

        found.append(alert)

    return found
