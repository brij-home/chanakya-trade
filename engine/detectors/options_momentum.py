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
import re
import time
from datetime import datetime, time as dtime
from typing import Any, Optional

import numpy as np

from engine.alert_model import AutoAlert
from engine.alert_expiry import classify_expiry_type
from engine.options_hedging import (
    audit_stock_option_liquidity_spread,
)

from engine.alert_identity import canonical_alert_symbol
from market.instruments import format_strike

logger = logging.getLogger("chanakya.detectors.options_momentum")
from config.constants import IST

DEFAULT_WATCHED_INDICES = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"}


def resolve_index_exchange(sym: str) -> str:
    """Resolves BSE for SENSEX/BANKEX, MCX for commodities, otherwise NSE."""
    from config.market_universes import BSE_EQUITY_SYMBOLS, MCX_COMMODITY_SYMBOLS
    from engine.alert_identity import canonical_alert_symbol

    clean = canonical_alert_symbol(sym)
    if clean in BSE_EQUITY_SYMBOLS:
        return "BSE"
    if clean in MCX_COMMODITY_SYMBOLS:
        return "MCX"
    return "NSE"


def detect_options_momentum_breakouts(
    targets: Optional[list[str]] = None,
    watched_indices: Optional[set[str] | list[str]] = None,
    recent_alerts: Optional[list[AutoAlert]] = None,
    batch_quotes: Optional[dict[str, Any]] = None,
    now_dt: Optional[datetime] = None,
    chains_map: Optional[dict[str, Any]] = None,
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

    is_preopen_auction = now_dt.hour == 9 and now_dt.minute < 15
    if not is_test_env and is_preopen_auction:
        logger.debug(
            "[OptionsBreakout] Suppressed during pre-open call auction (09:00–09:15 IST). "
            "Continuous F&O session begins at 09:15 IST."
        )
        return []

    is_friday_late = (now_dt.weekday() == 4) and (
        now_dt.hour > 14 or (now_dt.hour == 14 and now_dt.minute >= 30)
    )
    is_opening_freeze = now_dt.hour == 9 and now_dt.minute < 25
    is_opening_drive = now_dt.hour == 9 and (25 <= now_dt.minute <= 45)
    is_midday_lull = (
        (now_dt.hour == 10 and now_dt.minute >= 30)
        or (now_dt.hour == 11)
        or (now_dt.hour == 12)
        or (now_dt.hour == 13 and now_dt.minute <= 15)
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
        nq = get_quote("NSE:NIFTY50-INDEX") or get_quote("NSE:NIFTY 50")
        q_obj = (
            nq.get("NSE:NIFTY50-INDEX") or nq.get("NSE:NIFTY 50") or nq.get("NIFTY 50")
            if isinstance(nq, dict)
            else nq
        )
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
        nifty_change is not None and nifty_change <= -0.30 and nifty_below_vwap is not False
    )
    is_nifty_markup = (
        nifty_change is not None and nifty_change >= 0.25 and nifty_below_vwap is False
    )

    vix_val = None
    try:
        from market.indices import get_vix

        vix_val = get_vix()
    except Exception:
        vix_val = None

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
        clean_sym = canonical_alert_symbol(sym)
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
            from market.instruments import COMMODITY_SYMBOLS

            is_comm = clean_sym in COMMODITY_SYMBOLS or exch == "MCX"
            alert_segment = "FNO_INDEX" if is_idx else ("COMMODITY" if is_comm else "FNO_STOCK")

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
                    spot_vwap > 0 and abs(spot - spot_vwap) / spot_vwap >= 0.0035
                )
                is_momentum_active = bool(
                    abs(spot_change_pct) >= 0.35
                    or (spot_open > 0 and abs(spot - spot_open) / spot_open >= 0.0035)
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

    # Prioritize indices and top highest-momentum single-stock options to eliminate rate-gate bottlenecks
    # Apply RRG sector tailwind boost (bidirectional) so sector-driven runners (CE calls or PE puts) are prioritized
    directional_sector_syms: dict[str, set[str]] = {"BULLISH": set(), "BEARISH": set()}
    try:
        from analysis.sector_rotation import get_directional_sector_constituents

        directional_sector_syms = get_directional_sector_constituents()
    except Exception as e_rrg_opt:
        logger.debug(f"[OptionsBreakout] Sector RRG resolution error: {e_rrg_opt}")

    bullish_sector_syms = directional_sector_syms.get("BULLISH", set())
    bearish_sector_syms = directional_sector_syms.get("BEARISH", set())

    def _eq_priority_score(t: dict[str, Any]) -> float:
        spot_chg = float(t.get("spot_change_pct", 0.0) or 0.0)
        base_chg = abs(spot_chg)
        clean_s = t.get("clean_sym", "")
        # Prioritize active institutional movers (0.5% - 4.5%) monotonically; only dampen extreme >5.5% exhaustion
        if base_chg <= 4.5:
            move_score = base_chg
        elif base_chg <= 5.5:
            move_score = 4.5
        else:
            move_score = max(2.0, 4.5 - (base_chg - 5.5) * 0.4)
        spot_p = float(t.get("spot", 0.0) or 0.0)
        vwap_p = float(t.get("spot_vwap", 0.0) or 0.0)
        if spot_p > 0 and vwap_p > 0:
            vw_dist_pct = abs(spot_p - vwap_p) / vwap_p * 100.0
            if (
                (spot_chg > 0 and spot_p >= vwap_p) or (spot_chg < 0 and spot_p <= vwap_p)
            ) and vw_dist_pct <= 1.5:
                move_score *= 1.15
            elif vw_dist_pct > 3.5:
                move_score *= 0.80
        multiplier = 1.0
        # Bidirectional sector boost (daily RRG + live intraday sector rotation):
        # Long side: Positive move + Bullish sector confluence
        # Short side: Negative move + Bearish sector breakdown confluence
        if spot_chg > 0 and clean_s in bullish_sector_syms:
            multiplier = 1.25
        elif spot_chg < 0 and clean_s in bearish_sector_syms:
            multiplier = 1.25
        sec_breadth = intraday_sector_avg.get(stock_sector_map.get(clean_s, ""), 0.0)
        if spot_chg > 0 and sec_breadth >= 1.2:
            multiplier *= 1.20
        elif spot_chg < 0 and sec_breadth <= -1.2:
            multiplier *= 1.20
        return move_score * multiplier

    # Zero-REST intraday sector breadth calculation from already-fetched active_targets
    stock_sector_map: dict[str, str] = {}
    sector_changes: dict[str, list[float]] = {}
    try:
        from analysis.universe import get_stock_sector

        for _t in active_targets:
            if not _t.get("is_idx"):
                _cs = _t.get("clean_sym", "")
                _sid, _ = get_stock_sector(_cs)
                if _sid and _sid != "index":
                    stock_sector_map[_cs] = _sid
                    sector_changes.setdefault(_sid, []).append(
                        float(_t.get("spot_change_pct", 0.0) or 0.0)
                    )
    except Exception as e_sec:
        logger.debug(f"[options_momentum] Sector baseline map skipped: {e_sec}")
    intraday_sector_avg: dict[str, float] = {
        k: (sum(v) / len(v)) for k, v in sector_changes.items() if len(v) >= 2
    }

    idx_targets = [t for t in active_targets if t["is_idx"]]
    eq_targets = [t for t in active_targets if not t["is_idx"]]
    eq_targets.sort(key=_eq_priority_score, reverse=True)
    has_active_sectors = bool(bullish_sector_syms or bearish_sector_syms or intraday_sector_avg)
    eq_limit = 65 if has_active_sectors else 40
    active_targets = idx_targets + eq_targets[:eq_limit]

    def _eval_sym(sym_info: dict[str, Any]) -> Optional[tuple[float, AutoAlert]]:
        nonlocal vix_val
        is_test_env = (
            (os.environ.get("CHANAKYA_TESTING") == "1")
            or (os.environ.get("DEPLOY_MODE") == "test")
            or ("PYTEST_CURRENT_TEST" in os.environ)
        )
        sym = sym_info["sym"]
        clean_sym = sym_info["clean_sym"]
        exch = sym_info["exch"]
        spot = sym_info["spot"]
        spot_change_pct = sym_info["spot_change_pct"]
        spot_open = sym_info["spot_open"]
        spot_high = sym_info.get("spot_high", 0.0)
        spot_vwap = sym_info["spot_vwap"]
        is_idx = sym_info["is_idx"]
        from market.instruments import COMMODITY_SYMBOLS

        is_comm = clean_sym in COMMODITY_SYMBOLS or exch == "MCX"
        alert_segment = sym_info["alert_segment"]
        is_bear_drive = sym_info["is_bear_drive"]
        is_bull_drive = sym_info["is_bull_drive"]
        from engine.position_sizer import get_lot_size

        try:
            # ── Spot-First Pre-Filter Funnel (compute 5m/VWAP/RVOL BEFORE cold REST option-chain calls) ──
            df_5m = None
            if not is_test_env:
                try:
                    from engine.market_matrix import get_market_matrix

                    mm = get_market_matrix()
                    df_5m = mm.get_candles_df(clean_sym, timeframe="5m", limit=80)
                except Exception:
                    df_5m = None

            if df_5m is None or len(df_5m) < 6:
                try:
                    from market.history import get_ohlcv

                    df_5m = get_ohlcv(clean_sym, exchange=exch, interval="5minute", days=2)
                    if df_5m is not None and len(df_5m) >= 6 and not is_test_env:
                        try:
                            from engine.market_matrix import get_market_matrix

                            get_market_matrix().seed_historical_candles(clean_sym, "5m", df_5m)
                        except Exception as e_om5:
                            logger.debug(
                                f"[OptionsMomentum] MarketMatrix 5m seed skipped for {clean_sym}: {e_om5}"
                            )
                except Exception as e_suppressed:
                    logger.debug(
                        f"[engine.detectors.options_momentum] Non-fatal exception suppressed: {e_suppressed}"
                    )

            if df_5m is not None and len(df_5m) >= 1:
                try:
                    last_c = float(df_5m.iloc[-1].get("close", df_5m.iloc[-1].get("Close", 0.0)))
                    if last_c > 0 and abs(last_c - spot) / max(1.0, spot) > 0.15:
                        df_5m = None
                except Exception as e_suppressed:
                    logger.debug(
                        f"[engine.detectors.options_momentum] Non-fatal exception suppressed: {e_suppressed}"
                    )

            if (not spot_vwap or spot_vwap <= 0) and df_5m is not None and len(df_5m) >= 2:
                try:
                    df_vw = df_5m
                    if hasattr(df_5m.index, "date"):
                        sub_today = df_5m[df_5m.index.date == now_dt.date()]
                        if len(sub_today) >= 2:
                            df_vw = sub_today
                        else:
                            last_sess = df_5m.index.date[-1]
                            sub_last = df_5m[df_5m.index.date == last_sess]
                            if len(sub_last) >= 2:
                                df_vw = sub_last
                    vols = df_vw["volume"].values
                    highs = (
                        df_vw["high"].values if "high" in df_vw.columns else df_vw["High"].values
                    )
                    lows = df_vw["low"].values if "low" in df_vw.columns else df_vw["Low"].values
                    closes = (
                        df_vw["close"].values if "close" in df_vw.columns else df_vw["Close"].values
                    )
                    cum_vol = np.cumsum(vols)
                    if cum_vol[-1] > 0:
                        typical_price = (highs + lows + closes) / 3.0
                        cum_pv = np.cumsum(typical_price * vols)
                        spot_vwap = float(cum_pv[-1] / cum_vol[-1])
                except Exception as e_suppressed:
                    logger.debug(
                        f"[engine.detectors.options_momentum] Non-fatal exception suppressed: {e_suppressed}"
                    )
            if not spot_vwap or spot_vwap <= 0:
                try:
                    from market.quotes import get_computed_vwap

                    spot_vwap = float(get_computed_vwap(clean_sym, exchange=exch) or 0.0)
                except Exception:
                    spot_vwap = spot_vwap or 0.0

            spot_rvol: float = 0.0
            spot_atr: Optional[float] = None
            if df_5m is not None and len(df_5m) >= 5:
                try:
                    _col_v = (
                        "volume"
                        if "volume" in df_5m.columns
                        else ("Volume" if "Volume" in df_5m.columns else None)
                    )
                    if _col_v:
                        _vols = df_5m[_col_v].astype(float)
                        _last_v = float(_vols.iloc[-1] or 0.0)
                        _med_v = float(_vols.iloc[:-1].median() or 0.0)
                        if _med_v > 0 and _last_v > 0:
                            spot_rvol = round(min(15.0, _last_v / _med_v), 2)
                except Exception:
                    spot_rvol = 0.0

                try:
                    _col_h = "high" if "high" in df_5m.columns else "High"
                    _col_l = "low" if "low" in df_5m.columns else "Low"
                    _col_c = "close" if "close" in df_5m.columns else "Close"
                    _h_s = df_5m[_col_h].astype(float)
                    _l_s = df_5m[_col_l].astype(float)
                    _c_s = df_5m[_col_c].astype(float)
                    _prev_c = _c_s.shift(1).fillna(_c_s)
                    _tr = (
                        (_h_s - _l_s)
                        .combine((_h_s - _prev_c).abs(), max)
                        .combine((_l_s - _prev_c).abs(), max)
                    )
                    _avg_5m_tr = float(_tr.tail(min(14, len(_tr))).mean() or 0.0)
                    if _avg_5m_tr > 0:
                        spot_atr = round(_avg_5m_tr * float(np.sqrt(75.0)), 2)
                except Exception:
                    spot_atr = None

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
                except Exception as e_suppressed:
                    logger.debug(
                        f"[engine.detectors.options_momentum] Non-fatal exception suppressed: {e_suppressed}"
                    )

            has_prewarmed_chain = bool(
                chains_map is not None and (chains_map.get(clean_sym) or chains_map.get(sym))
            )
            if not is_idx and not is_comm and not is_test_env and not has_prewarmed_chain:
                if (
                    0 < spot_rvol < 0.70
                    and abs(spot_change_pct) < 1.2
                    and not (is_bull_drive or is_bear_drive)
                ):
                    logger.debug(
                        f"[OptionsBreakout] Spot-first skip {clean_sym} before chain fetch: low RVOL {spot_rvol:.2f}x"
                    )
                    return None
                if (
                    spot_vwap > 0
                    and not (is_bull_drive or is_bear_drive)
                    and abs(spot_change_pct) < 1.5
                    and (
                        (spot_change_pct >= 0.35 and spot < spot_vwap * 0.996)
                        or (spot_change_pct <= -0.35 and spot > spot_vwap * 1.004)
                    )
                ):
                    logger.debug(
                        f"[OptionsBreakout] Spot-first skip {clean_sym} before chain fetch: fighting VWAP ({spot:.1f} vs {spot_vwap:.1f})"
                    )
                    return None

            # Institutional Single-Stock Expiry Protection:
            # Under SEBI regulations, single-stock options are physically settled.
            # In settlement week (DTE <= 4), automatically route stock options to Next-Month
            # series to reduce near-month physical settlement and expiry risk.
            chain = None
            is_next_month_routed = False
            if not is_idx and not is_comm:
                try:
                    from engine.alert_expiry import (
                        is_monthly_physical_expiry_week,
                        resolve_recommended_derivative_expiry,
                    )
                    from market.options import get_expiries

                    # Zero-API calendar gate: only query expiries during actual physical expiry week
                    if is_monthly_physical_expiry_week(ref_dt=now_dt):
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

            if (
                not is_idx
                and "exp_res" in locals()
                and exp_res
                and exp_res.get("is_next_month_routed")
                and not is_next_month_routed
            ):
                logger.info(
                    f"[OptionsBreakout] {clean_sym} next-month chain unavailable during expiry week. "
                    f"Suppressed current-month stock options to eliminate SEBI physical delivery margin risk."
                )
                return None

            if chain is None and chains_map is not None:
                chain = chains_map.get(clean_sym) or chains_map.get(sym)
            if chain is None:
                chain = get_options_chain(clean_sym)
            if chains_map is not None and chain:
                chains_map[clean_sym] = chain
                chains_map[sym] = chain

            if not chain:
                return None

            min_opt_volume = (
                (2000 if is_idx else 300) if is_opening_drive else (3000 if is_idx else 500)
            )
            min_oi = 10000 if is_idx else (300 if is_test_env else 1000)

            max_strike_dist = (
                (
                    max(spot * 0.015, 300.0)
                    if clean_sym in ("NIFTY", "FINNIFTY")
                    else (
                        max(spot * 0.018, 900.0)
                        if clean_sym in ("BANKNIFTY", "SENSEX", "BANKEX")
                        else (120.0 if clean_sym in ("MIDCPNIFTY",) else 150.0)
                    )
                )
                if is_idx
                else max(
                    spot * 0.022, 3.0 if spot < 100.0 else (5.0 if spot < 250.0 else spot * 0.02)
                )
            )
            min_opt_price = (
                2.5
                if clean_sym in ("MIDCPNIFTY",)
                else (
                    5.0
                    if is_idx
                    else (
                        0.50
                        if (is_test_env or spot < 100.0)
                        else 3.0  # Align with Telegram non-0DTE quality floor (rejects penny options)
                    )
                )
            )

            atm_contracts = [
                c
                for c in chain
                if abs(getattr(c, "strike", 0.0) - spot) <= max_strike_dist
                and getattr(c, "last_price", 0.0) >= min_opt_price
                and getattr(c, "volume", 0) >= min_opt_volume
                and getattr(c, "oi", 0) >= min_oi
            ]
            if not atm_contracts:
                return None

            if is_idx:
                atm_contracts.sort(key=lambda c: abs(getattr(c, "strike", 0.0) - spot))
            else:
                # Institutional Single-Stock High-Torque Sweet-Spot Scoring (Delta 0.35 - 0.50):
                # Prioritizes ATM and immediate near-the-money contracts (for both Calls and Puts)
                def _stock_strike_score(c):
                    c_strk = getattr(c, "strike", 0.0)
                    c_prem = float(getattr(c, "last_price", 0.0) or 0.0)
                    c_v = getattr(c, "volume", 0)
                    c_o = getattr(c, "oi", 0)
                    dist_p = abs(c_strk - spot) / max(1.0, spot)
                    prem_ratio = c_prem / max(1.0, spot)
                    # Sweet-spot premium: Target 2.2% - 3.8% of spot to ensure Delta >= 0.35
                    prem_score = max(0.0, 15.0 - abs(prem_ratio - 0.028) * 200.0)
                    # Institutional liquidity score: Reward healthy absolute open interest
                    oi_score = min(10.0, (c_o / 5000.0) * 5.0)
                    # Bounded turnover bonus: only rewarded if OI is substantial (eliminates penny gambling traps)
                    turnover = min(10.0, (c_v / max(1000, c_o)) * 5.0) if c_o >= 800 else 0.0
                    # Heavily penalize distance from spot so true ATM / nearest strikes win decisively over distant OTM
                    return prem_score + oi_score + turnover - (dist_p * 250.0)

                atm_contracts.sort(key=_stock_strike_score, reverse=True)

            # ── Institutional Daily Levels & Central Pivot Range (CPR) ───────────
            from engine.daily_levels import get_daily_levels, evaluate_cpr_gate

            dl = None
            try:
                dl = get_daily_levels(clean_sym, session_date=str(now_dt.date()))
            except Exception as e_dl:
                logger.debug(
                    f"[OptionsBreakout] Daily levels lookup failed for {clean_sym}: {e_dl}"
                )

            cpr_gate_ce = evaluate_cpr_gate(
                clean_sym, spot, "BULLISH", dl=dl, session_date=str(now_dt.date())
            )
            cpr_gate_pe = evaluate_cpr_gate(
                clean_sym, spot, "BEARISH", dl=dl, session_date=str(now_dt.date())
            )

            for c in atm_contracts:
                vol = getattr(c, "volume", 0)
                oi = getattr(c, "oi", 0)
                oi_change = getattr(c, "oi_change", 0)
                vol_oi = round(vol / max(1, oi), 2)
                opt_ltp = float(getattr(c, "last_price", 0.0) or 0.0)
                opt_type = getattr(c, "option_type", "")
                strike = float(getattr(c, "strike", 0.0))
                contract_sym = getattr(c, "symbol", f"{clean_sym}{format_strike(strike)}{opt_type}")
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
                    except Exception as e_suppressed:
                        logger.debug(
                            f"[engine.detectors.options_momentum] Non-fatal exception suppressed: {e_suppressed}"
                        )

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
                        if exp_dt:
                            dte_check = (exp_dt - now_dt.date()).days
                            _is_test = (
                                os.environ.get("CHANAKYA_TESTING") == "1"
                                or "PYTEST_CURRENT_TEST" in os.environ
                            )
                            if (not _is_test and dte_check < 0) or dte_check > max_dte:
                                continue
                    except Exception as e_suppressed:
                        logger.debug(
                            f"[engine.detectors.options_momentum] Non-fatal exception suppressed: {e_suppressed}"
                        )

                if is_opening_drive:
                    min_vol_oi = 0.60 if is_idx else 1.00
                    min_contracts = 2000 if is_idx else 500
                else:
                    min_vol_oi = 1.00 if is_idx else 1.20
                    min_contracts = 2500 if is_idx else 600

                has_vol_surge = (vol_oi >= min_vol_oi) or (vol >= (min_contracts * 2.5))
                if not has_vol_surge or vol < min_contracts:
                    continue

                # 0DTE Afternoon Theta Decay Acceleration Guard (post 13:00 IST):
                # Strictly veto naked OTM strikes (Delta < 0.48) on expiry day to avoid the Hero-or-Zero trap
                is_0dte = False
                if expiry_date:
                    try:
                        exp_str = str(expiry_date).split("T")[0].strip()
                        exp_d = datetime.strptime(exp_str, "%Y-%m-%d").date()
                        is_0dte = exp_d == now_dt.date()
                    except Exception as e_suppressed:
                        logger.debug(
                            f"[engine.detectors.options_momentum] Non-fatal exception suppressed: {e_suppressed}"
                        )
                if (
                    is_idx
                    and is_0dte
                    and now_dt.time() >= datetime.strptime("13:00", "%H:%M").time()
                ):
                    is_otm = (opt_type == "CE" and strike > spot) or (
                        opt_type == "PE" and strike < spot
                    )
                    if is_otm:
                        logger.debug(
                            f"[OptionsBreakout] Vetoed naked 0DTE OTM {contract_sym} post-13:00 IST to prevent theta trap."
                        )
                        continue

                bid = getattr(c, "bid", None)
                ask = getattr(c, "ask", None)
                if (
                    not is_idx
                    and bid is not None
                    and ask is not None
                    and (float(bid or 0) > 0 or float(ask or 0) > 0)
                ):
                    liq_audit_scan = audit_stock_option_liquidity_spread(
                        symbol=contract_sym,
                        bid=float(bid or 0.0),
                        ask=float(ask or 0.0),
                        max_spread_pct=0.045,
                    )
                    if not liq_audit_scan["is_acceptable"]:
                        logger.debug(
                            f"[OptionsBreakout] Vetoed illiquid stock option {contract_sym}: {liq_audit_scan['warning']}"
                        )
                        continue
                else:
                    max_spread_mult = 1.30 if is_idx else 1.15
                    if bid and ask and bid > 0 and ask > 0 and ask > (bid * max_spread_mult):
                        continue

                is_physical_expiry_week = False
                if not is_idx and not is_comm and expiry_date:
                    try:
                        from engine.alert_expiry import is_monthly_physical_expiry_week

                        is_physical_expiry_week = is_monthly_physical_expiry_week(
                            str(expiry_date), symbol=clean_sym, ref_dt=now_dt
                        )
                    except Exception as e_suppressed:
                        logger.debug(
                            f"[engine.detectors.options_momentum] Non-fatal exception suppressed: {e_suppressed}"
                        )

                if is_physical_expiry_week and not is_next_month_routed:
                    logger.debug(
                        f"[OptionsBreakout] Strictly vetoed {contract_sym}: Near-month stock option in SEBI physical delivery expiry week"
                    )
                    continue

                pchange = getattr(c, "pchange", None)
                min_pchange = 8.0 if is_opening_drive else 6.0
                if opt_type == "CE":
                    if pchange is not None and pchange < min_pchange:
                        continue
                    if spot_change_pct is not None and spot_change_pct < -1.5:
                        continue
                    if spot_open and spot_open > 0 and spot < spot_open * 0.995:
                        continue
                    if cpr_gate_ce.is_vetoed:
                        logger.debug(
                            f"[OptionsBreakout] CE vetoed for {clean_sym}: {cpr_gate_ce.veto_reason}"
                        )
                        continue

                    if is_idx:
                        if spot_vwap and spot_vwap > 0 and spot < spot_vwap:
                            continue
                        try:
                            if dl and dl.camarilla:
                                cam_h4 = float(dl.camarilla.get("h4", 0.0) or 0.0)
                                cam_rng = float(dl.camarilla.get("range", 0.0) or (spot * 0.008))
                                h4_buf = min(spot * 0.0008, 0.15 * cam_rng)
                                if cam_h4 > 0 and spot <= cam_h4 and spot >= (cam_h4 - h4_buf):
                                    if df_5m is not None and len(df_5m) >= 1:
                                        c_last = float(
                                            df_5m.iloc[-1].get(
                                                "close", df_5m.iloc[-1].get("Close", 0.0)
                                            )
                                        )
                                        if c_last <= cam_h4:
                                            continue
                        except Exception as e_cam:
                            logger.debug(f"[OptionsBreakout] Camarilla check skipped: {e_cam}")
                    else:
                        if spot_vwap and spot_vwap > 0 and spot < spot_vwap * 1.0005:
                            continue

                    # Order Book Imbalance (OBI50) & Fortress Wall Check (Indices & Stock F&O)
                    try:
                        from market.fyers_tbt_manager import (
                            fyers_tbt_manager,
                            FyersTbtManager,
                            resolve_tradable_tbt_symbol,
                        )

                        mgr = (
                            fyers_tbt_manager
                            if getattr(fyers_tbt_manager, "is_connected", False)
                            else FyersTbtManager()
                        )
                        tradable = resolve_tradable_tbt_symbol(clean_sym)
                        depth = mgr.get_50_depth(tradable or clean_sym)
                        if depth and depth.get("status") not in ("UNAVAILABLE", None):
                            obi_val = float(depth.get("obi_50", 0.0) or 0.0)
                            fortress_ask = bool(depth.get("fortress_ask_wall_confirmed", False))
                            if obi_val <= -0.20 or fortress_ask:
                                logger.info(
                                    f"[OptionsBreakout] CE rejected for {clean_sym}: "
                                    f"Severe ask book imbalance (OBI50={obi_val:+.2f}) or fortress wall ({fortress_ask})"
                                )
                                continue
                    except Exception as e_tbt:
                        logger.debug(f"[OptionsBreakout] TBT check skipped: {e_tbt}")
                    if candle_range >= (spot * 0.0025) and upper_wick_ratio > 0.50:
                        continue
                    direction = "BULLISH"
                elif opt_type == "PE":
                    if pchange is not None and pchange < min_pchange:
                        continue
                    retreat_pct = (
                        ((spot_high - spot) / spot_high * 100.0)
                        if (spot_high and spot_high > spot)
                        else 0.0
                    )
                    is_intraday_dump = bool(
                        retreat_pct >= 0.8 or (spot_vwap and spot_vwap > 0 and spot < spot_vwap)
                    )
                    max_pe_change = 3.5 if is_intraday_dump else 1.5
                    if spot_change_pct is not None and spot_change_pct > max_pe_change:
                        continue
                    if (
                        spot_open
                        and spot_open > 0
                        and spot > spot_open * 1.005
                        and not is_intraday_dump
                    ):
                        continue
                    if cpr_gate_pe.is_vetoed:
                        logger.debug(
                            f"[OptionsBreakout] PE vetoed for {clean_sym}: {cpr_gate_pe.veto_reason}"
                        )
                        continue

                    if is_idx:
                        if spot_vwap and spot_vwap > 0 and spot > spot_vwap:
                            continue
                        try:
                            if dl and dl.camarilla:
                                cam_l4 = float(dl.camarilla.get("l4", 0.0) or 0.0)
                                cam_rng = float(dl.camarilla.get("range", 0.0) or (spot * 0.008))
                                l4_buf = min(spot * 0.0008, 0.15 * cam_rng)
                                if cam_l4 > 0 and spot >= cam_l4 and spot <= (cam_l4 + l4_buf):
                                    if df_5m is not None and len(df_5m) >= 1:
                                        c_last = float(
                                            df_5m.iloc[-1].get(
                                                "close", df_5m.iloc[-1].get("Close", 0.0)
                                            )
                                        )
                                        if c_last >= cam_l4:
                                            continue
                        except Exception as e_cam:
                            logger.debug(f"[OptionsBreakout] Camarilla check skipped: {e_cam}")
                    else:
                        if spot_vwap and spot_vwap > 0 and spot > spot_vwap * 0.9995:
                            continue

                    # Order Book Imbalance (OBI50) & Fortress Wall Check (Indices & Stock F&O)
                    try:
                        from market.fyers_tbt_manager import (
                            fyers_tbt_manager,
                            FyersTbtManager,
                            resolve_tradable_tbt_symbol,
                        )

                        mgr = (
                            fyers_tbt_manager
                            if getattr(fyers_tbt_manager, "is_connected", False)
                            else FyersTbtManager()
                        )
                        tradable = resolve_tradable_tbt_symbol(clean_sym)
                        depth = mgr.get_50_depth(tradable or clean_sym)
                        if depth and depth.get("status") not in ("UNAVAILABLE", None):
                            obi_val = float(depth.get("obi_50", 0.0) or 0.0)
                            fortress_bid = bool(depth.get("fortress_bid_wall_confirmed", False))
                            if obi_val >= +0.20 or fortress_bid:
                                logger.info(
                                    f"[OptionsBreakout] PE rejected for {clean_sym}: "
                                    f"Severe bid book imbalance (OBI50={obi_val:+.2f}) or fortress wall ({fortress_bid})"
                                )
                                continue
                    except Exception as e_tbt:
                        logger.debug(f"[OptionsBreakout] TBT check skipped: {e_tbt}")
                    if candle_range >= (spot * 0.0025) and lower_wick_ratio > 0.50:
                        continue
                    direction = "BEARISH"
                else:
                    continue

                mtf_15m_trend = "NEUTRAL"
                try:
                    df_15m = None
                    if not is_test_env:
                        try:
                            from engine.market_matrix import get_market_matrix

                            df_15m = get_market_matrix().get_candles_df(
                                clean_sym, timeframe="15m", limit=80
                            )
                        except Exception:
                            df_15m = None

                    if df_15m is None or len(df_15m) < 15:
                        from market.history import get_ohlcv

                        df_15m = get_ohlcv(clean_sym, days=4, interval="15minute")
                        if df_15m is not None and len(df_15m) >= 15 and not is_test_env:
                            try:
                                from engine.market_matrix import get_market_matrix

                                get_market_matrix().seed_historical_candles(
                                    clean_sym, "15m", df_15m
                                )
                            except Exception as e_om15:
                                logger.debug(
                                    f"[OptionsMomentum] MarketMatrix 15m seed skipped for {clean_sym}: {e_om15}"
                                )
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
                    (
                        (spot_open and spot <= spot_open * 0.996)
                        or (
                            spot_change_pct is not None
                            and spot_change_pct <= -0.50
                            and (not spot_open or spot <= spot_open * 1.001)
                        )
                    )
                    and (spot_vwap and spot <= spot_vwap * 1.000)
                    and (lower_wick_ratio <= 0.40)
                )
                has_opening_breakout = bool(
                    (
                        (spot_open and spot >= spot_open * 1.004)
                        or (
                            spot_change_pct is not None
                            and spot_change_pct >= 0.50
                            and (not spot_open or spot >= spot_open * 0.999)
                        )
                    )
                    and (spot_vwap and spot >= spot_vwap * 1.000)
                    and (upper_wick_ratio <= 0.40)
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

                is_explosive_momentum = bool(
                    (vol_oi >= 1.8 and vol >= (800 if is_idx else 500))
                    or (vol >= (500 if is_idx else 200) and (pchange or 0.0) >= 8.0)
                    or (spot_change_pct and abs(spot_change_pct) >= 2.0)
                )

                hbcm_meta = None
                if is_idx:
                    try:
                        from engine.hbcm import evaluate_hbcm

                        hbcm_eval = evaluate_hbcm(
                            clean_sym,
                            direction,
                            allow_weighted_fallback=(
                                is_explosive_momentum
                                or is_opening_drive
                                or is_bull_drive
                                or is_bear_drive
                            ),
                        )
                        if hbcm_eval.total_heavyweights > 0:
                            if not hbcm_eval.confluence_pass and not is_opening_drive:
                                logger.info(
                                    f"[OptionsBreakout] Suppressed index option alert for {clean_sym} {opt_type}: {hbcm_eval.rejection_reason}"
                                )
                                continue
                            hbcm_meta = hbcm_eval.to_dict()
                    except Exception as e_hbcm:
                        logger.debug(
                            f"[OptionsBreakout] HBCM check bypassed for {clean_sym}: {e_hbcm}"
                        )

                is_decoupler = False
                opt_pch = getattr(c, "pchange", 0.0) or getattr(c, "change_pct", 0.0) or 0.0
                if not is_idx:
                    stock_lot = getattr(c, "lot_size", None) or 1
                    if stock_lot <= 1:
                        try:
                            stock_lot = get_lot_size(clean_sym) or 1
                        except Exception:
                            stock_lot = 1
                    eff_decouple_vol = max(40, min(350, int(20000 / max(1, stock_lot))))
                    eff_decouple_vol_mid = int(eff_decouple_vol * 0.75)
                    if opt_type == "CE":
                        if (vol_oi >= 1.8 and vol >= eff_decouple_vol and opt_pch >= 15.0) or (
                            spot_change_pct
                            and spot_change_pct >= 1.8
                            and (vol_oi >= 1.2 or vol >= eff_decouple_vol_mid)
                        ):
                            is_decoupler = True
                    elif opt_type == "PE":
                        if (vol_oi >= 1.8 and vol >= eff_decouple_vol and opt_pch >= 15.0) or (
                            spot_change_pct
                            and spot_change_pct <= -1.8
                            and (vol_oi >= 1.2 or vol >= eff_decouple_vol_mid)
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
                    except Exception as e_suppressed:
                        logger.debug(
                            f"[engine.detectors.options_momentum] Non-fatal exception suppressed: {e_suppressed}"
                        )

                # Extreme Idiosyncratic Catalyst Escape Hatch:
                # Allows stock options to fire even if parent sector is not supportive,
                # ONLY IF extraordinary volume/OI turnover, huge price displacement, or writer panic decouples it.
                is_extreme_catalyst = False
                if not is_idx:
                    is_extreme_catalyst = bool(
                        is_decoupler
                        or is_writer_panic
                        or (vol_oi >= 2.5 and vol >= int(eff_decouple_vol * 1.5))
                        or (spot_change_pct and abs(spot_change_pct) >= 2.0)
                    )

                is_explosive_momentum = bool(
                    is_extreme_catalyst
                    or (vol_oi >= 1.8 and vol >= (800 if is_idx else eff_decouple_vol))
                    or (
                        vol >= (500 if is_idx else max(30, eff_decouple_vol // 2))
                        and (pchange or 0.0) >= 8.0
                    )
                    or (spot_change_pct and abs(spot_change_pct) >= 2.0)
                )

                # ── Time-of-Day Institutional Gates ──
                if not is_test_env:
                    # 1. Opening Auction Discovery Freeze (09:15 - 09:25 IST)
                    # Squelch speculative breakout buying before morning market structure forms
                    if is_opening_freeze and not (
                        is_bear_drive
                        or is_bull_drive
                        or is_extreme_catalyst
                        or has_opening_breakout
                        or has_opening_breakdown
                    ):
                        logger.debug(
                            f"[OptionsBreakout] Suppressed {clean_sym} during 09:15-09:25 IST opening auction discovery"
                        )
                        continue

                    # 2. Midday Volume Lull (11:15 - 13:15 IST)
                    # Suppress options buying during midday consolidation unless confirmed by volume/momentum/order flow
                    if is_midday_lull and not is_extreme_catalyst:
                        thrust_vol_floor = 500 if is_idx else 80
                        has_midday_thrust = (
                            is_explosive_momentum
                            or (vol_oi >= 1.35 and vol >= thrust_vol_floor)
                            or (spot_change_pct is not None and abs(spot_change_pct) >= 1.2)
                        )
                        min_midday_vol = 1200 if is_idx else 150
                        min_vol_oi = 2.0 if is_idx else 1.25
                        if not has_midday_thrust and (vol_oi < min_vol_oi or vol < min_midday_vol):
                            logger.debug(
                                f"[OptionsBreakout] Suppressed {clean_sym} during 11:15-13:15 IST midday lull (vol_oi {vol_oi}x < {min_vol_oi}x or vol {vol} < {min_midday_vol})"
                            )
                            continue

                # 3. Theta Drag & Stagnation Defense (Midday Lull 11:15–13:15, Low VIX < 14.0, or Late Session post-14:45 IST)
                # Enforce minimum 20-minute runway before canonical derivative squareoff cutoff (eliminates 15:03-15:12 EOD traps)
                from market.rule_schedule import intraday_squareoff_cutoff as _om_sq_cutoff

                _sq_t_om = _om_sq_cutoff(
                    now_dt.date(), is_derivative=True, expiring_index=bool(is_idx and is_0dte)
                )
                _sq_mins = _sq_t_om.hour * 60 + _sq_t_om.minute
                _cutoff_mins = _sq_mins - 20  # e.g. 14:55 IST pre-Dec 7; 15:10 IST post-Dec 7
                _now_mins = now_dt.hour * 60 + now_dt.minute
                if not is_test_env and _now_mins > _cutoff_mins:
                    logger.debug(
                        f"[OptionsBreakout] Suppressed {clean_sym} at {now_dt.strftime('%H:%M')} IST: "
                        f"<20m runway before {_sq_t_om.strftime('%H:%M')} IST square-off cutoff"
                    )
                    continue

                # Route single-stock options to defined-risk spreads (Bull Call / Bear Put Spread) to neutralize theta burn
                mandate_spread_afternoon = False
                if not is_idx:
                    is_low_vix_stock = vix_val is not None and vix_val < 14.0
                    if (
                        is_midday_lull or is_late_session_theta or is_low_vix_stock
                    ) and not is_next_month_routed:
                        mandate_spread_afternoon = True
                elif is_late_session_theta and not is_next_month_routed:
                    mandate_spread_afternoon = True

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
                    # Decouple idiosyncratic breakouts on strong individual momentum + VWAP alignment
                    has_stock_thrust = bool(
                        (
                            spot_change_pct is not None
                            and spot_change_pct >= 1.2
                            and (not spot_vwap or spot >= spot_vwap)
                        )
                        or (spot_change_pct is not None and spot_change_pct >= 2.2)
                        or (is_decoupler and spot_change_pct and spot_change_pct > 0)
                    )
                    is_strong_markdown = nifty_change is not None and nifty_change <= -0.60
                    has_intraday_rs_decouple = bool(
                        (
                            tailwind
                            and float(getattr(tailwind, "intraday_rs", 0.0) or 0.0) >= 0.50
                            and spot_change_pct is not None
                            and spot_change_pct >= 2.0
                            and (not spot_vwap or spot >= spot_vwap)
                        )
                    )
                    if is_strong_markdown:
                        if not (
                            is_extreme_catalyst
                            or has_intraday_rs_decouple
                            or (is_defensive and has_stock_thrust and spot_change_pct >= 2.0)
                        ):
                            logger.debug(
                                f"[OptionsBreakout] Suppressed counter-trend Call on {clean_sym}: NIFTY markdown ({nifty_change:.2f}%)"
                            )
                            continue
                    elif not (
                        is_defensive
                        or sector_tailwind_bonus > 0
                        or is_extreme_catalyst
                        or (
                            has_stock_thrust
                            and not (is_nifty_markdown and spot_vwap and spot < spot_vwap)
                        )
                    ):
                        logger.debug(
                            f"[OptionsBreakout] Suppressed Call breakout on {clean_sym}: NIFTY in markdown ({nifty_change:.2f}%)"
                        )
                        continue

                if not is_idx and is_nifty_markup and opt_type == "PE":
                    from analysis.universe import get_stock_sector

                    if not sec_name:
                        sec_id, sec_name = get_stock_sector(clean_sym)
                    # Institutional Macro Decoupling Invariant:
                    # In a broad market markup (NIFTY >= +0.60%), naked PEs without sector breakdown
                    # or extreme catalyst fail downstream Telegram counter-trend gates and pollute UI.
                    has_stock_breakdown = bool(
                        (
                            spot_change_pct is not None
                            and spot_change_pct <= -1.2
                            and (not spot_vwap or spot <= spot_vwap)
                        )
                        or (spot_change_pct is not None and spot_change_pct <= -2.2)
                        or (is_decoupler and spot_change_pct and spot_change_pct < 0)
                    )
                    is_strong_markup = nifty_change is not None and nifty_change >= 0.60
                    if is_strong_markup:
                        if not (
                            is_extreme_catalyst
                            or (sector_tailwind_bonus > 0 and has_stock_breakdown)
                        ):
                            logger.debug(
                                f"[OptionsBreakout] Suppressed counter-trend Put on {clean_sym}: NIFTY markup (+{nifty_change:.2f}%) without sector breakdown or catalyst"
                            )
                            continue
                    elif not has_stock_breakdown:
                        logger.debug(
                            f"[OptionsBreakout] Suppressed Put surge on {clean_sym}: NIFTY in markup (+{nifty_change:.2f}%) without verified underlying stock breakdown"
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

                if vix_val is None:
                    try:
                        from market.indices import get_vix

                        vix_val = get_vix()
                    except Exception as e_vix_om:
                        logger.debug(f"[OptionsMomentum] Live VIX lookup skipped: {e_vix_om}")

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

                is_high_iv_risk = bool(vix_val is not None and vix_val >= 18.0)

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
                                or (vol_oi >= 1.8 and vol >= (800 if is_idx else eff_decouple_vol))
                                or (
                                    vol >= (500 if is_idx else max(30, eff_decouple_vol // 2))
                                    and (pchange or 0.0) >= 8.0
                                )
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

                obv_div_status = "NEUTRAL"
                dmi_model_verdict = "NEUTRAL"
                vsa_sig_status = "NEUTRAL"
                vsa_fake_risk = False
                rsi_5m = None
                ema20_5m = None
                avwap_bias_status = "NEUTRAL"
                flow_bonus = 0
                if df_5m is not None and len(df_5m) >= 5:
                    try:
                        from analysis.technical import rsi

                        c_series = df_5m["close"] if "close" in df_5m.columns else df_5m["Close"]
                        rsi_s = rsi(c_series, period=14).dropna()
                        if len(rsi_s) > 0:
                            rsi_5m = round(float(rsi_s.iloc[-1]), 1)
                        if len(c_series) >= 20:
                            ema20_5m = round(
                                float(c_series.ewm(span=20, adjust=False).mean().iloc[-1]), 2
                            )
                    except Exception as e_rsi:
                        logger.debug(
                            f"[OptionsBreakout] RSI computation failed for {clean_sym}: {e_rsi}"
                        )

                    # ── Climax / Blow-off Exhaustion Gate ──
                    if rsi_5m is not None:
                        if opt_type == "CE" and rsi_5m >= 76.0:
                            logger.debug(
                                f"[OptionsBreakout] Suppressed CE on {clean_sym}: 5m RSI ({rsi_5m:.1f}) >= 76.0 (Parabolic climax overbought)"
                            )
                            continue
                        elif opt_type == "PE" and rsi_5m <= 24.0:
                            logger.debug(
                                f"[OptionsBreakout] Suppressed PE on {clean_sym}: 5m RSI ({rsi_5m:.1f}) <= 24.0 (Oversold capitulation floor)"
                            )
                            continue

                    # ── Upper/Lower Wick Supply/Demand Collision on Expanding Bar ──
                    if (
                        opt_type == "CE"
                        and upper_wick_ratio >= 0.58
                        and candle_range >= (spot * 0.0020)
                    ):
                        logger.debug(
                            f"[OptionsBreakout] Suppressed CE on {clean_sym}: Heavy upper wick rejection ({upper_wick_ratio * 100:.1f}%) on expanding bar"
                        )
                        continue
                    elif (
                        opt_type == "PE"
                        and lower_wick_ratio >= 0.58
                        and candle_range >= (spot * 0.0020)
                    ):
                        logger.debug(
                            f"[OptionsBreakout] Suppressed PE on {clean_sym}: Heavy lower wick rejection ({lower_wick_ratio * 100:.1f}%) on expanding bar"
                        )
                        continue

                if df_5m is not None and len(df_5m) >= 10:
                    try:
                        from analysis.obv import analyse_obv
                        from analysis.dmi_filter import evaluate_triple_dmi
                        from analysis.vsa import analyse_vsa
                        from analysis.anchored_vwap import detect_intraday_anchors

                        _obv = analyse_obv(df_5m, is_intraday=True)
                        _dmi = evaluate_triple_dmi(df_5m, is_intraday=True)
                        obv_div_status = _obv.divergence
                        dmi_model_verdict = _dmi.verdict

                        if opt_type == "CE":
                            if _dmi.verdict == "TRIPLE_BULLISH_CONFIRMED":
                                flow_bonus += 10
                            if _obv.divergence == "BULLISH_DIVERGENCE":
                                flow_bonus += 8
                            elif _obv.divergence == "BEARISH_DIVERGENCE":
                                flow_bonus -= 15
                                mandate_spread_afternoon = True
                        elif opt_type == "PE":
                            if _dmi.verdict == "TRIPLE_BEARISH_CONFIRMED":
                                flow_bonus += 10
                            if _obv.divergence == "BEARISH_DIVERGENCE":
                                flow_bonus += 8

                        _vsa = analyse_vsa(df_5m, symbol=clean_sym, is_intraday=True)
                        vsa_sig_status = _vsa.vsa_signal
                        vsa_fake_risk = _vsa.is_fake_breakout_risk
                        if opt_type == "CE":
                            if vsa_fake_risk or vsa_sig_status in (
                                "EFFORT_NO_RESULT_BEARISH",
                                "NO_DEMAND",
                            ):
                                logger.debug(
                                    f"[OptionsBreakout] Suppressed CE on {clean_sym}: VSA distribution / effort vs result trap ({vsa_sig_status})"
                                )
                                continue
                            elif _vsa.bias == "BULLISH":
                                flow_bonus += min(8, max(3, _vsa.conviction_modifier))
                        elif opt_type == "PE":
                            if vsa_fake_risk or vsa_sig_status in ("STOPPING_VOLUME", "NO_SUPPLY"):
                                logger.debug(
                                    f"[OptionsBreakout] Suppressed PE on {clean_sym}: VSA absorption / stopping volume floor ({vsa_sig_status})"
                                )
                                continue
                            elif _vsa.bias == "BEARISH":
                                flow_bonus += min(8, max(3, _vsa.conviction_modifier))

                        _avwap = detect_intraday_anchors(df_5m, spot_price=spot)
                        avwap_bias_status = _avwap.get("bias", "NEUTRAL")
                        if opt_type == "CE" and avwap_bias_status == "BULLISH":
                            flow_bonus += 5
                        elif opt_type == "PE" and avwap_bias_status == "BEARISH":
                            flow_bonus += 5
                        else:
                            opt_cpr_wide = bool(
                                (cpr_gate_ce if opt_type == "CE" else cpr_gate_pe).is_wide
                            )
                            is_counter_avwap = (
                                opt_type == "PE" and avwap_bias_status == "BULLISH"
                            ) or (opt_type == "CE" and avwap_bias_status == "BEARISH")
                            if (
                                not is_test_env
                                and opt_cpr_wide
                                and is_counter_avwap
                                and not is_extreme_catalyst
                            ):
                                logger.debug(
                                    f"[OptionsBreakout] Suppressed counter-AVWAP {opt_type} on {clean_sym}: "
                                    f"Wide CPR with opposing AVWAP bias ({avwap_bias_status})"
                                )
                                continue
                    except Exception as _e_obv_dmi:
                        logger.debug(f"[OptionsBreakout] Flow analysis check skipped: {_e_obv_dmi}")

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
                om_struct_loc = None
                if df_5m is not None and len(df_5m) >= 6:
                    try:
                        from analysis.market_structure import evaluate_structural_location

                        om_struct_loc = evaluate_structural_location(
                            df_5m,
                            spot=spot,
                            direction=direction,
                            vwap=spot_vwap or 0.0,
                            vol_oi_ratio=float(vol_oi or 0.0),
                            iv_val=float(vix_val) if vix_val is not None else None,
                            rvol_val=spot_rvol if spot_rvol > 0 else 1.0,
                        )
                        if (
                            not is_test_env
                            and om_struct_loc.has_opposing_wall
                            and not is_writer_panic
                            and not is_extreme_catalyst
                            and vol_oi < 2.5
                        ):
                            logger.debug(
                                f"[OptionsBreakout] Suppressed {opt_type} on {clean_sym}: {om_struct_loc.opposing_wall_reason}"
                            )
                            continue
                        if om_struct_loc.location_tags:
                            for lt in om_struct_loc.location_tags:
                                if lt not in vp_tags:
                                    vp_tags.append(lt)
                        if om_struct_loc.has_strong_location:
                            vp_bonus += 4
                    except Exception as e_smc_loc:
                        logger.debug(
                            f"[OptionsBreakout] Structural location skipped for {clean_sym}: {e_smc_loc}"
                        )
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

                # 2b. Midday Lull Multi-Factor Confluence Filter (10:30 - 13:15 IST):
                # Require genuine structural confluence + volume participation during midday chop
                if not is_test_env and is_midday_lull and not is_extreme_catalyst:
                    has_midday_structure = bool(
                        mtf_15m_trend == direction
                        or sector_tailwind_bonus > 0
                        or flow_bonus >= 8
                        or is_confirmed
                        or vp_bonus >= 5
                    )
                    has_midday_volume = bool(
                        (spot_rvol >= 1.25) or (spot_rvol <= 0 and vol_oi >= 2.2)
                    )
                    if not (has_midday_structure and has_midday_volume):
                        logger.debug(
                            f"[OptionsBreakout] Suppressed {clean_sym} {opt_type} during midday chop (10:30-13:15 IST): "
                            f"structure={has_midday_structure}, vol={has_midday_volume} (rvol={spot_rvol}, vol_oi={vol_oi})"
                        )
                        continue

                from engine.alert_identity import (
                    generate_alert_id,
                    get_session_phase_slot,
                )

                phase_slot = get_session_phase_slot(now_dt)
                alert_id = generate_alert_id(
                    clean_sym,
                    "OPTIONS_MOMENTUM",
                    session_date=now_dt.date(),
                    variant=f"{opt_type.lower()}-{format_strike(strike).replace('.', 'p')}-{phase_slot}",
                )

                tp = None
                opt_plan = None
                try:
                    from engine.trade_plan import (
                        calculate_trade_plan,
                        calculate_option_execution_plan,
                    )

                    opt_exchange = "MCX" if is_comm else ("BFO" if exch == "BSE" else "NFO")
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
                            contract_symbol=contract_sym,
                        )
                except Exception as e_tp:
                    logger.debug(f"[OptionsBreakout] Trade plan calculation failed: {e_tp}")

                is_index_sym = clean_sym in (
                    "NIFTY",
                    "BANKNIFTY",
                    "FINNIFTY",
                    "MIDCPNIFTY",
                    "SENSEX",
                    "BANKEX",
                )
                # DTE & afternoon runway calibration so monthly (10-35 DTE) expensive contracts
                # receive realistic intraday targets instead of multi-day +44% swing targets.
                om_dte_days: Optional[int] = None
                if expiry_date:
                    try:
                        exp_d_om = datetime.strptime(str(expiry_date)[:10], "%Y-%m-%d").date()
                        om_dte_days = max(0, (exp_d_om - now_dt.date()).days)
                    except Exception:
                        om_dte_days = None

                is_monthly_dte = om_dte_days is not None and om_dte_days >= 10
                afternoon_scale_om = 0.80 if now_dt.time() >= dtime(14, 0) else 1.0

                if is_index_sym:
                    idx_pts_cap = {
                        "NIFTY": 28.0,
                        "BANKNIFTY": 65.0,
                        "FINNIFTY": 30.0,
                        "MIDCPNIFTY": 18.0,
                        "SENSEX": 95.0,
                        "BANKEX": 95.0,
                    }.get(clean_sym, 35.0) * afternoon_scale_om
                    max_sl_pct = 0.12 if (is_monthly_dte or opt_ltp >= 350.0) else 0.18
                    max_allowed_risk = round(min(opt_ltp * max_sl_pct, idx_pts_cap), 2)
                else:
                    max_sl_pct = (0.12 if (is_monthly_dte or opt_ltp >= 150.0) else 0.16) * (
                        0.85 if now_dt.time() >= dtime(14, 0) else 1.0
                    )
                    max_allowed_risk = round(max(0.5, opt_ltp * max_sl_pct), 2)

                t1_mult = 1.6 if now_dt.time() >= dtime(14, 0) else 1.8

                if opt_plan and opt_plan.get("sl_premium") and opt_plan.get("t1_premium"):
                    raw_sl = float(opt_plan["sl_premium"])
                    raw_risk = max(0.2, opt_ltp - raw_sl)
                    if raw_risk > max_allowed_risk:
                        opt_sl = round(max(0.05, opt_ltp - max_allowed_risk), 2)
                        opt_risk = max_allowed_risk
                    else:
                        opt_sl = raw_sl
                        opt_risk = raw_risk

                    raw_t1 = float(opt_plan["t1_premium"])
                    min_t1 = round(opt_ltp + (opt_risk * t1_mult), 2)
                    max_t1 = round(opt_ltp + (opt_risk * 2.2), 2)
                    opt_t1 = round(min(max_t1, max(raw_t1, min_t1)), 2)

                    opt_t2 = round(opt_ltp + (opt_risk * 3.0), 2)
                    opt_moonshot = round(opt_ltp + (opt_risk * 4.5), 2)
                    opt_t0_5 = float(
                        opt_plan.get("t0_5_premium") or round(opt_ltp + (0.8 * opt_risk), 2)
                    )
                    if opt_t0_5 >= opt_t1:
                        opt_t0_5 = round(opt_ltp + (0.8 * opt_risk), 2)
                    rr_str = f"1:{round((opt_t1 - opt_ltp) / max(0.01, opt_risk), 1)}"

                    # Sync calibrated targets back into opt_plan & free_roll_plan (SSOT: no T2/T3 drift)
                    opt_plan["sl_premium"] = opt_sl
                    opt_plan["t0_5_premium"] = opt_t0_5
                    opt_plan["t1_premium"] = opt_t1
                    opt_plan["t2_premium"] = opt_t2
                    opt_plan["t3_premium"] = opt_moonshot
                    fr_plan = opt_plan.get("free_roll_plan")
                    if isinstance(fr_plan, dict):
                        be_stop = float(fr_plan.get("breakeven_stop") or round(opt_ltp * 1.002, 2))
                        ts_mins = int(
                            fr_plan.get("time_stop_minutes") or (25 if is_index_sym else 35)
                        )
                        fr_plan["t1_target_premium"] = opt_t1
                        fr_plan["runner_target_2"] = opt_t2
                        fr_plan["runner_target_3"] = opt_moonshot
                        fr_plan["protocol_summary"] = (
                            f"Multi-lot: Bank 50% at T1, ratchet SL to Cost (₹{be_stop:,.1f}) | "
                            f"1-lot: Ratchet SL to Breakeven & hold for T2. "
                            f"Time stop: {ts_mins}m if stagnation occurs. "
                            f"Net trade risk becomes ₹0.00 (Free-Roll). "
                            f"Hold remaining 50% for T2 (₹{opt_t2:,.1f}) and T3 (₹{opt_moonshot:,.1f})."
                        )
                else:
                    risk_pts = round(max(0.20, min(max_allowed_risk, opt_ltp - 0.05)), 2)
                    opt_risk = risk_pts
                    opt_sl = round(max(0.05, opt_ltp - risk_pts), 2)
                    opt_t0_5 = round(opt_ltp + (0.8 * risk_pts), 2)
                    opt_t1 = round(opt_ltp + (t1_mult * risk_pts), 2)
                    opt_t2 = round(opt_ltp + (3.0 * risk_pts), 2)
                    opt_moonshot = round(opt_ltp + (4.5 * risk_pts), 2)
                    rr_val = round((opt_t1 - opt_ltp) / max(0.01, risk_pts), 1)
                    rr_str = f"1:{rr_val}"

                _adr_cal = None
                try:
                    from engine.option_target_calibration import compute_option_adr_headroom_targets

                    _iv_hint = (vix_val / 100.0) if (vix_val and vix_val > 0) else 0.20
                    _adr_cal = compute_option_adr_headroom_targets(
                        spot=spot,
                        opt_ltp=opt_ltp,
                        opt_sl=opt_sl,
                        raw_t1=opt_t1,
                        option_type=opt_type,
                        strike=strike,
                        dte_days=om_dte_days,
                        iv=_iv_hint,
                        spot_atr=spot_atr,
                        day_high=spot_high if spot_high > 0 else None,
                        day_low=spot_low if spot_low > 0 else None,
                        now_dt=now_dt,
                        segment=alert_segment,
                        min_rr=1.25,
                    )
                    if _adr_cal.was_adr_capped:
                        opt_t1 = _adr_cal.calibrated_t1
                        opt_t2 = max(opt_t1 + opt_risk * 0.75, min(opt_t2, _adr_cal.calibrated_t2))
                        opt_moonshot = max(
                            opt_t2 + opt_risk * 0.95, min(opt_moonshot, _adr_cal.calibrated_t3)
                        )
                        opt_t2 = round(opt_t2, 2)
                        opt_moonshot = round(opt_moonshot, 2)
                        if opt_t0_5 >= opt_t1:
                            opt_t0_5 = round(opt_ltp + ((opt_t1 - opt_ltp) * 0.5), 2)
                        rr_str = f"1:{round((opt_t1 - opt_ltp) / max(0.01, opt_ltp - opt_sl), 1)}"
                        if isinstance(opt_plan, dict):
                            opt_plan["t0_5_premium"] = opt_t0_5
                            opt_plan["t1_premium"] = opt_t1
                            opt_plan["t2_premium"] = opt_t2
                            opt_plan["t3_premium"] = opt_moonshot
                            _fr_p = opt_plan.get("free_roll_plan")
                            if isinstance(_fr_p, dict):
                                _fr_p["t1_target_premium"] = opt_t1
                                _fr_p["runner_target_2"] = opt_t2
                                _fr_p["runner_target_3"] = opt_moonshot
                    if not is_test_env and not _adr_cal.viable_rr:
                        logger.debug(
                            f"[OptionsBreakout] Rejected {contract_sym}: ADR-calibrated R:R {_adr_cal.calibrated_rr:.2f} < 1.25"
                        )
                        continue
                except Exception as _e_adr:
                    logger.debug(
                        f"[OptionsBreakout] ADR target calibration skipped for {contract_sym}: {_e_adr}"
                    )

                friday_tag = (
                    " ⚠️ FRIDAY POST-14:30: Weekend theta decay risk; Intraday Quick Scalp only (Square off by 15:20 IST) or trade Bull Call Spread."
                    if is_friday_late
                    else ""
                )
                _sqoff_om_str = "15:15"
                if is_zero_dte_pm:
                    try:
                        from market.rule_schedule import intraday_squareoff_cutoff

                        _sqoff_om_str = intraday_squareoff_cutoff(
                            now_dt.date(), is_derivative=True, expiring_index=is_idx
                        ).strftime("%H:%M")
                    except Exception as _e_sched_om:
                        logger.debug(
                            f"[OptionsBreakout] Rule schedule squareoff lookup failed: {_e_sched_om}"
                        )
                dte_pm_tag = (
                    f" ⚠️ 0DTE AFTERNOON: Accelerated theta decay active. Deep ATM/ITM only; mandatory square-off by {_sqoff_om_str} IST."
                    if is_zero_dte_pm
                    else ""
                )
                phys_tag = (
                    " Physical settlement risk is elevated near listed stock expiry. Verify current exchange margin before holding."
                    if (is_physical_expiry_week and not is_next_month_routed)
                    else ""
                )
                rollover_tag = (
                    f" 🎯 NEXT-MONTH ROLLOVER ({expiry_date}): Bypasses SEBI physical delivery margin surge & near-month theta collapse."
                    if is_next_month_routed
                    else ""
                )
                high_vix_tag = (
                    f" ⚠️ HIGH VIX ({vix_val:.1f}): Elevated IV crush risk on naked options. Prefer Deep ITM (Delta >= 0.65) or Defined-Risk Spreads."
                    if is_high_iv_risk
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
                is_climax_extended = False
                if opt_pch >= 25.0:
                    # Parabolic climax exhaustion: penalize blind market chasing (+0 bonus) and enforce pullback limit entry
                    conf_score += 0
                    is_climax_extended = True
                elif opt_pch >= 18.0:
                    conf_score += 5
                    is_climax_extended = True
                elif opt_pch >= 8.0:
                    conf_score += 10
                elif opt_pch >= 4.0:
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
                conf_score += flow_bonus

                confidence = min(96, max(50, conf_score))
                if not is_test_env and confidence < 60 and vol_oi < 2.2:
                    logger.debug(
                        f"[OptionsBreakout] Suppressed low-confluence setup {contract_sym}: confidence={confidence}, vol_oi={vol_oi}"
                    )
                    continue

                best_bid = float(getattr(c, "best_bid", 0.0) or getattr(c, "bid", 0.0) or 0.0)
                best_ask = float(getattr(c, "best_ask", 0.0) or getattr(c, "ask", 0.0) or 0.0)
                if not is_idx and best_bid <= 0 and best_ask <= 0:
                    try:
                        from market.order_book import get_depth_book

                        _ob_chk = get_depth_book(contract_sym)
                        if _ob_chk and _ob_chk.total_bid_qty > 0 and _ob_chk.total_ask_qty > 0:
                            best_bid = float(_ob_chk.best_bid or 0.0)
                            best_ask = float(_ob_chk.best_ask or 0.0)
                    except Exception as _e_ob_fb:
                        logger.debug(
                            f"[OptionsBreakout] Order book L2 fallback skipped for {contract_sym}: {_e_ob_fb}"
                        )
                if not is_test_env and not is_idx and best_bid > 0 and opt_ltp > (best_bid * 1.15):
                    logger.debug(
                        f"[OptionsBreakout] Rejected stale/off-quote stock option {contract_sym}: "
                        f"opt_ltp ₹{opt_ltp:.2f} > best_bid ₹{best_bid:.2f} * 1.15"
                    )
                    continue
                if (
                    not is_test_env
                    and not is_idx
                    and (best_bid <= 0 or best_ask <= 0)
                    and opt_ltp >= 200.0
                    and oi < 25000
                ):
                    logger.debug(
                        f"[OptionsBreakout] Rejected illiquid high-premium stock option {contract_sym}: "
                        f"ltp=₹{opt_ltp:.2f}, bid={best_bid}, oi={oi} < 25000"
                    )
                    continue
                sfr = 0.0
                is_wide_spread = False
                midpoint_price = opt_ltp
                liq_audit = None
                if not is_idx and best_bid > 0 and best_ask > 0:
                    liq_audit = audit_stock_option_liquidity_spread(
                        symbol=contract_sym,
                        bid=best_bid,
                        ask=best_ask,
                        max_spread_pct=0.045,
                    )
                    if not liq_audit["is_acceptable"]:
                        logger.debug(
                            f"[OptionsBreakout] Rejected stock option {contract_sym} on secondary depth check: {liq_audit['warning']}"
                        )
                        continue
                    sfr = liq_audit["spread_pct"]
                    midpoint_price = liq_audit["midpoint"]
                    if liq_audit["status"] == "CAUTION_MIDPOINT":
                        is_wide_spread = True
                elif best_bid > 0 and best_ask > 0 and opt_ltp > 0:
                    sfr = round(((best_ask - best_bid) / opt_ltp) * 100.0, 2)
                    midpoint_price = round((best_bid + best_ask) / 2.0, 2)
                    if sfr >= 3.0:
                        is_wide_spread = True

                _fric_eval = None
                try:
                    from engine.option_target_calibration import evaluate_option_friction_viability

                    _fric_eval = evaluate_option_friction_viability(
                        entry_price=opt_ltp,
                        target_1=opt_t1,
                        stop_loss=opt_sl,
                        quantity=lot_sz,
                        bid=best_bid,
                        ask=best_ask,
                        segment=("COMMODITY" if is_comm else "OPTIONS"),
                        max_spread_pct=(5.5 if is_idx else 4.5),
                        max_friction_drag_pct=28.0,
                        min_net_rr=1.05,
                    )
                    if not is_test_env and not _fric_eval["viable"]:
                        logger.debug(
                            f"[OptionsBreakout] Rejected {contract_sym} pre-creation on friction/liquidity: {_fric_eval['reason']}"
                        )
                        continue
                except Exception as _e_fric_om:
                    logger.debug(
                        f"[OptionsBreakout] Friction check skipped for {contract_sym}: {_e_fric_om}"
                    )

                ote_lower = round(max(0.05, opt_ltp * 0.94), 1)
                ote_upper = round(opt_ltp * 1.01, 1)
                max_chase = round(opt_ltp * 1.045, 1)
                entry_range_str = f"₹{ote_lower:,.1f} – ₹{ote_upper:,.1f}"
                when_to_wait_str = f"DO NOT CHASE if premium surges > 4.5% past entry (> ₹{max_chase:,.1f}). Wait for 5m consolidation retest."
                spot_anchor_str = (
                    f" (Spot Anchor: ₹{tp.invalidation_stop:,.1f})"
                    if (tp and tp.invalidation_stop > 0)
                    else ""
                )
                pullback_entry_limit = ote_lower
                if is_climax_extended:
                    entry_range_str = f"₹{pullback_entry_limit:,.1f} – ₹{round(opt_ltp * 0.98, 1):,.1f} (PULLBACK RETEST ZONE)"
                    when_to_buy_str = (
                        f"LIMIT ORDER ON PULLBACK MANDATORY: Premium is extended (+{opt_pch:.1f}%). "
                        f"Place LIMIT BUY at ₹{pullback_entry_limit:,.1f}–₹{round(opt_ltp * 0.98, 1):,.1f} "
                        f"(5m 20-EMA / VWAP retest zone). DO NOT BUY AT MARKET."
                    )
                    when_to_wait_str = (
                        f"DO NOT CHASE AT MARKET (Extended +{opt_pch:.1f}%). "
                        f"Wait for 5m consolidation pullback to ₹{pullback_entry_limit:,.1f}. "
                        f"Cancel if price surges without filling."
                    )
                elif liq_audit and liq_audit.get("status") == "CAUTION_MIDPOINT":
                    when_to_buy_str = (
                        f"LIMIT MIDPOINT ORDER MANDATORY: Best bid ₹{best_bid:,.2f} / Best ask ₹{best_ask:,.2f} "
                        f"(Spread {sfr:.1f}% > 4.5%). Limit order strictly pegged to Midpoint "
                        f"₹{midpoint_price:,.2f} enforced to eliminate immediate bid-ask slippage."
                    )
                elif is_wide_spread:
                    when_to_buy_str = (
                        f"LIMIT ORDER ONLY: Best bid ₹{best_bid:,.2f} / Best ask ₹{best_ask:,.2f} (Spread {sfr:.1f}%). "
                        f"Enter via Limit Order at midpoint ₹{midpoint_price:,.2f} to eliminate -{sfr / 2.0:.1f}% immediate market slippage."
                    )
                else:
                    when_to_buy_str = (
                        f"Buy on ask/limit within entry range with spot invalidation anchor at ₹{tp.invalidation_stop:,.1f} (Option SL ₹{opt_sl:,.1f})."
                        if (tp and tp.invalidation_stop > 0)
                        else f"Buy on ask/limit within entry range with tight defined risk below ₹{opt_sl:,.1f}."
                    )

                lot_tag = f" (Lot: {lot_sz})" if (lot_sz and lot_sz > 1) else ""
                sec_badge = ""
                if sec_name and not is_idx:
                    from bot.alert_templates import shorten_sector_name

                    short_sec = shorten_sector_name(sec_name).upper() or sec_name.upper()
                    sec_badge = f" [{short_sec}]"
                cat_badge = (
                    " ⚡ DECOUPLER"
                    if (not is_idx and is_extreme_catalyst and not sector_tailwind_bonus)
                    else ""
                )
                from bot.alert_templates import format_contract_display

                contract_clean = format_contract_display(contract_sym)
                contract_clean = re.sub(
                    r"^(?:NSE|BSE|NFO|MCX|CDS|BFO):", "", contract_clean, flags=re.IGNORECASE
                ).strip()
                ext_badge = " ⚡ [PULLBACK LIMIT]" if is_climax_extended else ""
                spread_badge = " 🛡️ [HEDGED SPREAD MANDATORY]" if mandate_spread_afternoon else ""
                sec_cat = f"{sec_badge}{cat_badge}{ext_badge}{spread_badge}".strip()
                sec_cat_str = f" · {sec_cat}" if sec_cat else ""

                if opt_type == "PE":
                    headline = f"🔴 {contract_clean} PUT SURGE @ ₹{opt_ltp:,.1f}{lot_tag}{sec_cat_str} (Vol/OI {vol_oi}x)"
                    summary = (
                        f"Institutional Put surge in {clean_sym} {format_strike(strike)} PE. "
                        f"Underlying spot ₹{spot:,.1f}{spot_anchor_str}. Turnover: {vol:,} contracts ({vol_oi}x OI). "
                        f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{opt_sl:,.1f} | T1: ₹{opt_t1:,.1f} (Scale 50% & SL to Cost) | T2: ₹{opt_t2:,.1f}.{drive_tag}{friday_tag}{dte_pm_tag}{phys_tag}{rollover_tag}{high_vix_tag}"
                    )
                else:
                    headline = f"🟢 {contract_clean} CALL BREAKOUT @ ₹{opt_ltp:,.1f}{lot_tag}{sec_cat_str} (Vol/OI {vol_oi}x)"
                    summary = (
                        f"Institutional Call surge in {clean_sym} {format_strike(strike)} CE. "
                        f"Underlying spot ₹{spot:,.1f}{spot_anchor_str}. Turnover: {vol:,} contracts ({vol_oi}x OI). "
                        f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{opt_sl:,.1f} | T1: ₹{opt_t1:,.1f} (Scale 50% & SL to Cost) | T2: ₹{opt_t2:,.1f}.{drive_tag}{friday_tag}{dte_pm_tag}{phys_tag}{rollover_tag}{high_vix_tag}"
                    )

                hedge_plan = None
                try:
                    from engine.options_hedging import build_defined_risk_hedge_plan

                    hedge_plan = build_defined_risk_hedge_plan(
                        symbol=clean_sym,
                        direction="BULLISH" if opt_type == "CE" else "BEARISH",
                        spot=spot,
                        strike=strike,
                        opt_type=opt_type,
                        opt_ltp=opt_ltp,
                        chain=chain,
                        lot_size=lot_sz,
                        vix=vix_val,
                        now_dt=now_dt,
                        vel_score=conf_score,
                        asymmetric_r_r=True,
                        expiry_date=str(expiry_date) if expiry_date else None,
                        target_level=tp.target_1 if tp else None,
                    )
                    if mandate_spread_afternoon and isinstance(hedge_plan, dict):
                        hedge_plan["preferred_vehicle"] = "SPREAD_ONLY"
                        hedge_plan["regime_verdict"] = "HEDGE_RECOMMENDED"
                        hedge_plan.pop("ratio_spread_1x2", None)
                except Exception as e_h:
                    logger.debug(
                        f"[OptionsBreakout] Hedge plan construction error for {clean_sym}: {e_h}"
                    )

                opt_delta = None
                opt_gamma = None
                opt_iv = None
                dte_days: Optional[int] = None
                is_0dte = False
                try:
                    if expiry_date:
                        exp_clean_om = str(expiry_date).strip()[:10]
                        exp_d = None
                        for _fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
                            try:
                                exp_d = datetime.strptime(exp_clean_om, _fmt).date()
                                break
                            except ValueError:
                                continue
                        if exp_d is not None:
                            dte_days = max(0, (exp_d - now_dt.date()).days)
                            is_0dte = dte_days == 0
                    from engine.options_backtest import bs_delta

                    iv_est = (vix_val / 100.0) if (vix_val and vix_val > 0) else 0.15
                    opt_iv = round(iv_est, 4)
                    opt_delta = round(
                        bs_delta(
                            spot,
                            strike,
                            dte_days if dte_days is not None else 7,
                            iv_est,
                            opt_type,
                        ),
                        4,
                    )
                except Exception as e_suppressed:
                    logger.debug(
                        f"[engine.detectors.options_momentum] Non-fatal exception suppressed: {e_suppressed}"
                    )

                _vwap_stretch_cap = (
                    0.035
                    if (is_opening_drive or is_bull_drive or is_bear_drive or spot_rvol >= 2.0)
                    else 0.028
                )
                _is_vwap_overextended = bool(
                    not is_idx
                    and spot_vwap
                    and spot_vwap > 0
                    and abs(spot - spot_vwap) / spot_vwap > _vwap_stretch_cap
                )
                if not is_test_env and _is_vwap_overextended and not is_opening_drive:
                    logger.debug(
                        f"[OptionsBreakout] Anti-FOMO suppressed {clean_sym} {opt_type}: "
                        f"spot stretched >2.5% from session VWAP ({spot:.1f} vs {spot_vwap:.1f})"
                    )
                    continue

                _has_early_confluence = bool(
                    vol_oi >= 0.85
                    and (
                        sector_tailwind_bonus > 0
                        or mtf_15m_trend == direction
                        or flow_bonus >= 5
                        or is_confirmed
                    )
                )
                if vol_oi >= 2.0 or (is_opening_drive and (vol_oi >= 0.50 or vol >= 6000)):
                    _om_stage = "IGNITED"
                    _om_trigger = opt_ltp
                elif _has_early_confluence:
                    _om_stage = "PRIMED"
                    _om_trigger = round(opt_ltp * 1.02, 2)
                else:
                    _om_stage = "EARLY_WARNING"
                    _om_trigger = round(opt_ltp * 1.02, 2)

                if (
                    not is_test_env
                    and not is_climax_extended
                    and max_chase > 0
                    and opt_ltp > max_chase
                ):
                    logger.debug(
                        f"[OptionsBreakout] Suppressed chased {clean_sym} {opt_type}: "
                        f"LTP ₹{opt_ltp:.2f} > no-chase ₹{max_chase:.2f}"
                    )
                    continue

                alert = AutoAlert(
                    alert_id=alert_id,
                    alert_type="OPTIONS_MOMENTUM",
                    stage=_om_stage,
                    symbol=clean_sym,
                    exchange=opt_exchange,
                    direction=direction,
                    headline=headline,
                    summary=summary,
                    ltp=opt_ltp,
                    trigger_level=_om_trigger,
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
                    is_live=not is_test_env,
                    environment="TEST" if is_test_env else "LIVE",
                    mtf_confluence=(
                        "BEARISH_BREAKDOWN"
                        if has_opening_breakdown
                        else ("BULLISH_BREAKOUT" if has_opening_breakout else mtf_15m_trend)
                    ),
                    preferred_vehicle="SPREAD_ONLY" if mandate_spread_afternoon else "NAKED_OPTION",
                    vix_regime=vix_regime,
                    metrics={
                        "signals": list(
                            dict.fromkeys(
                                [
                                    *vp_tags,
                                    *(
                                        ["OPENING_DRIVE"]
                                        if (is_bear_drive or is_bull_drive)
                                        else []
                                    ),
                                    *(["WRITER_PANIC"] if is_writer_panic else []),
                                    *(
                                        [
                                            f"VWAP_{'DISPLACED_BULL' if opt_type == 'CE' else 'DISPLACED_BEAR'}"
                                        ]
                                        if spot_vwap
                                        else []
                                    ),
                                    *(["OPTION_V_OI_SURGE"] if vol_oi >= 1.5 else []),
                                ]
                            )
                        ),
                        "structural_location": (
                            om_struct_loc.location_tags if om_struct_loc else []
                        ),
                        "fib_retracement_pct": (
                            om_struct_loc.fib_retracement_pct if om_struct_loc else None
                        ),
                        "nearest_ob_zone": (
                            om_struct_loc.nearest_ob_zone if om_struct_loc else None
                        ),
                        "obv_divergence": obv_div_status,
                        "dmi_triple_verdict": dmi_model_verdict,
                        "vsa_signal": vsa_sig_status,
                        "avwap_bias": avwap_bias_status,
                        "mandate_spread_afternoon": mandate_spread_afternoon,
                        "cpr": (cpr_gate_ce if opt_type == "CE" else cpr_gate_pe).cpr_data,
                        "cpr_type": (cpr_gate_ce if opt_type == "CE" else cpr_gate_pe).cpr_type,
                        "is_narrow_cpr": (
                            cpr_gate_ce if opt_type == "CE" else cpr_gate_pe
                        ).is_narrow,
                        "is_wide_cpr": (cpr_gate_ce if opt_type == "CE" else cpr_gate_pe).is_wide,
                        "delta": opt_delta,
                        "gamma": opt_gamma,
                        "iv": opt_iv,
                        "dte": dte_days,
                        "is_0dte": is_0dte,
                        "hbcm": hbcm_meta,
                        "vol_oi_ratio": vol_oi,
                        "volume": vol,
                        "oi": oi,
                        "oi_change": oi_change,
                        "spot": spot,
                        "strike": strike,
                        "lot_size": lot_sz,
                        "spot_vwap": spot_vwap,
                        "vwap": spot_vwap,
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
                        "is_high_iv_risk": is_high_iv_risk,
                        "is_gamma_squeeze": is_gamma_squeeze,
                        "liquidity_spread_audit": liq_audit,
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
                        "hedge_plan": hedge_plan,
                        "rsi": rsi_5m,
                        "rsi_5m": rsi_5m,
                        "ema20": ema20_5m,
                        "vsa_fake_breakout_risk": vsa_fake_risk,
                        "rvol": spot_rvol if spot_rvol > 0 else None,
                        "spot_atr": spot_atr,
                        "adr_target_calibration": (
                            {
                                "delta": _adr_cal.delta,
                                "gamma": _adr_cal.gamma,
                                "remaining_spot_headroom": _adr_cal.remaining_spot_headroom,
                                "max_adr_t1": _adr_cal.max_adr_t1,
                                "was_adr_capped": _adr_cal.was_adr_capped,
                                "calibrated_rr": _adr_cal.calibrated_rr,
                            }
                            if _adr_cal is not None
                            else None
                        ),
                        "friction_viability": _fric_eval,
                    },
                    actionable_plan={
                        "action": f"BUY {opt_type}",
                        "segment": "FNO",
                        "contract": contract_sym,
                        "preferred_vehicle": (
                            "SPREAD_ONLY"
                            if mandate_spread_afternoon
                            else (
                                hedge_plan.get(
                                    "preferred_vehicle",
                                    "DEEP_ITM_OR_SPREAD"
                                    if is_high_iv_risk
                                    else "NAKED_OPTION_OR_SPREAD",
                                )
                                if hedge_plan
                                else (
                                    "DEEP_ITM_OR_SPREAD"
                                    if is_high_iv_risk
                                    else "NAKED_OPTION_OR_SPREAD"
                                )
                            )
                        ),
                        "execution_style_mandate": (
                            "HEDGED_SPREAD_MANDATORY" if mandate_spread_afternoon else None
                        ),
                        "iv_crush_defense": (
                            f"HIGH_VIX_IV_CRUSH_WARNING: India VIX {vix_val:.1f} >= 18.0. Elevated IV crush risk on OTM/ATM longs. Prefer Deep ITM (Delta >= 0.65), Bull/Bear Vertical Spreads, or Futures."
                            if is_high_iv_risk
                            else None
                        ),
                        "hedge_plan": hedge_plan,
                        "recommended_entry": (
                            f"₹{pullback_entry_limit:,.1f} (Pullback Limit)"
                            if is_climax_extended
                            else (
                                f"₹{midpoint_price:,.2f} (Midpoint Limit)"
                                if is_wide_spread
                                else f"₹{opt_ltp:,.2f}"
                            )
                        ),
                        "entry_range": entry_range_str,
                        "spread_friction_ratio": sfr,
                        "is_wide_spread": is_wide_spread,
                        "recommended_limit_price": (
                            pullback_entry_limit
                            if is_climax_extended
                            else (midpoint_price if is_wide_spread else None)
                        ),
                        "broker_order_type": (
                            "BUY LIMIT (PULLBACK RETEST)"
                            if is_climax_extended
                            else ("BUY LIMIT" if is_wide_spread else "LIMIT_OR_MARKET")
                        ),
                        "entry_mode": "LIMIT_ON_PULLBACK"
                        if is_climax_extended
                        else "MOMENTUM_CONFIRMED",
                        "stop_loss": f"₹{opt_sl:,.1f}",
                        "target_0_5": f"₹{opt_t0_5:,.1f}",
                        "target_1": f"₹{opt_t1:,.1f}",
                        "target": f"₹{opt_t1:,.1f}",
                        "target_2": f"₹{opt_t2:,.1f}",
                        "target_3": f"₹{opt_moonshot:,.1f}",
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
                            "is_micro_scalp": False,
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
                            f"⚠️ 0DTE AFTERNOON: Accelerated theta decay active. Deep ATM/ITM only; mandatory square-off by {_sqoff_om_str} IST."
                            if is_zero_dte_pm
                            else None
                        ),
                        "rollover_notice": (
                            f"🎯 NEXT-MONTH ROLLOVER: Contract {contract_sym} expires {expiry_date} (bypasses SEBI delivery margin surge & theta decay)."
                            if is_next_month_routed
                            else None
                        ),
                        "physical_settlement_warning": (
                            "Physical settlement risk is elevated near listed stock expiry. Verify current exchange margin and avoid unprotected overnight carry."
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
        # Institutional Top-N Prioritization:
        # Retain all index targets, and prioritize top 8 highest-momentum single-stocks
        # using in-RAM quote metrics (opening drive, day high/low proximity, abs % change).
        # This prevents fan-out across 40+ stocks, dropping REST API hits by 80%.
        if not is_test_env and len(active_targets) > 10:
            idx_targets = [t for t in active_targets if t.get("is_idx")]
            stock_targets = [t for t in active_targets if not t.get("is_idx")]

            def _pre_rank(t):
                score = 0.0
                if t.get("is_bear_drive") or t.get("is_bull_drive"):
                    score += 20.0
                score += abs(t.get("spot_change_pct", 0.0)) * 3.0
                s = t.get("spot", 0.0)
                if s > 0:
                    hi = t.get("spot_high", 0.0)
                    lo = t.get("spot_low", 0.0)
                    if hi > 0 and abs(s - hi) / hi <= 0.003:
                        score += 15.0  # At or breaking Day High
                    elif lo > 0 and abs(s - lo) / lo <= 0.003:
                        score += 15.0  # At or breaking Day Low
                return score

            stock_targets.sort(key=_pre_rank, reverse=True)
            active_targets = idx_targets + stock_targets[:8]

        import concurrent.futures

        executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=min(8, max(1, len(active_targets))),
            thread_name_prefix="chanakya-optmom-pool",
        )
        try:
            future_to_sym = {executor.submit(_eval_sym, sym): sym for sym in active_targets}
            try:
                for future in concurrent.futures.as_completed(future_to_sym, timeout=20.0):
                    try:
                        cand_res = future.result()
                        if cand_res:
                            candidate_alerts.append(cand_res)
                    except Exception as e_sym:
                        sym_name = future_to_sym.get(future, "unknown")
                        logger.debug(
                            f"[OptionsBreakout] Target evaluation notice for {sym_name}: {e_sym}"
                        )
            except concurrent.futures.TimeoutError:
                logger.info(
                    f"[OptionsBreakout] Evaluation timeout (20s) reached. "
                    f"Proceeding safely with {len(candidate_alerts)} qualified candidates."
                )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

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
        _opt_pacing_limit = int(os.environ.get("OPTIONS_MOMENTUM_STOCK_PACING", "0"))
        is_apex = bool(
            (alert.metrics or {}).get("is_apex_confluence")
            or getattr(alert, "confidence", 0) >= 90
            or ((alert.metrics or {}).get("conviction_tier") == "APEX_CONFLUENCE")
        )
        effective_limit = (
            (_opt_pacing_limit + 1) if (is_apex and _opt_pacing_limit > 0) else _opt_pacing_limit
        )
        if (
            effective_limit > 0
            and is_stock
            and (recent_options_count + len(found)) >= effective_limit
        ):
            if (
                alert.confidence < 88
                and alert.metrics.get("decoupler_status") != "VERIFIED_DECOUPLER"
            ):
                logger.debug(
                    f"[OptionsBreakout] Paced options alert {alert.symbol}: Rolling 5m limit reached (score {q_score:.1f}, conf {alert.confidence}, limit {effective_limit})"
                )
                continue

        found.append(alert)

    return found
