"""
engine/detectors/index_call_setup.py
──────────────────────────────────────
SMC-Driven Bullish Index Options Detector (CE symmetric counterpart to index_put_setup.py).

Catches CALL entry opportunities that the OI-centric Gamma Blast detector misses because:
  - Spot may be slightly below VWAP at entry (demand zone retest before bounce)
  - OI hasn't built yet (fresh positioning, not yet visible in chain turnover)
  - Trade-plan asymmetry check rejects the setup (calibrated for equity context)

Institutional Setups Detected:
  1. PDL_DEMAND_REJECTION   — Spot sweeps previous day low + immediate wick bounce (demand OB)
  2. VWAP_RECLAIM           — Spot breaks above VWAP from below (VWAP-as-support flip)
  3. DEMAND_ZONE_SWEEP      — Intraday low sweep beyond key support with reversal candle
  4. BEARISH_EXHAUSTION_CE  — Extreme selling wick on high volume = demand absorption (Call setup)
  5. DOUBLE_BOTTOM_BREAKOUT — Two equal intraday lows + volume expansion on second bounce

All signals produce a GAMMA_BLAST-compatible AutoAlert (BULLISH direction) so they flow
naturally through the existing alert engine pipeline, deduplication, and Telegram templates.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, time as dtime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from engine.alert_identity import generate_alert_id
from engine.alert_model import AutoAlert
from engine.alert_expiry import classify_expiry_type

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

# Index universe for this detector
_INDEX_SYMBOLS = frozenset({"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"})

# Setup type → headline icon map
_SETUP_ICONS = {
    "PDL_DEMAND_REJECTION": "🟢",
    "VWAP_RECLAIM": "🟢",
    "DEMAND_ZONE_SWEEP": "⚡",
    "BEARISH_EXHAUSTION_CE": "🎯",
    "DOUBLE_BOTTOM_BREAKOUT": "🟢",
    "VCP_COILING": "🔴",  # Red dot = early warning, coiling before explosive move
    "DAY_HIGH_BREAKOUT": "🚀",
}


def detect_index_call_setup(
    underlying: str,
    spot: float,
    chain: list[Any],
    vwap: Optional[float] = None,
    day_high: Optional[float] = None,
    day_low: Optional[float] = None,
    prev_day_high: Optional[float] = None,
    prev_day_low: Optional[float] = None,
    prev_week_low: Optional[float] = None,
    ohlcv_5m: Optional[Any] = None,  # pandas DataFrame, 5-minute bars
    ref_time: Optional[datetime] = None,
    ignore_time_gate: bool = False,
) -> list[AutoAlert]:
    """
    Scans for institutional CALL entry setups on index options using SMC price action signals.

    Returns AutoAlert objects with alert_type="GAMMA_BLAST", direction="BULLISH" so they
    integrate transparently with the existing alert pipeline, templates, and deduplication.

    Args:
        underlying:    Index symbol (e.g. "NIFTY", "BANKNIFTY").
        spot:          Current spot price.
        chain:         Options chain contracts (list of contract objects).
        vwap:          Session VWAP for the underlying.
        day_high:      Intraday high so far.
        day_low:       Intraday low so far.
        prev_day_high: Previous session's high (PDH — key resistance level).
        prev_day_low:  Previous session's low (PDL — key demand level).
        prev_week_low: Previous week's low (PWL — weekly demand level).
        ohlcv_5m:      5-minute OHLCV DataFrame for structural analysis.
        ref_time:      Reference datetime for testing or historical audit.
        ignore_time_gate: If True, bypasses 09:25 IST stabilization gate for unit testing.
    """
    clean_sym = (
        underlying.upper().replace(".NS", "").replace("NSE:", "").replace("NFO:", "").strip()
    )
    if clean_sym not in _INDEX_SYMBOLS or spot <= 0:
        return []
    if not chain:
        return []

    # ── Market Breadth Gate ─────────────────────────────────────────
    # Index call setups into severe broad market liquidation have negative statistical expectancy.
    is_test_runner = (
        ("PYTEST_CURRENT_TEST" in os.environ)
        or (os.environ.get("CHANAKYA_TESTING") == "1")
        or (os.environ.get("DEPLOY_MODE") == "test")
    )
    if not is_test_runner or os.environ.get("ENFORCE_TEST_BREADTH") == "1":
        try:
            from market.sentiment import get_market_breadth

            mb = get_market_breadth()
            if mb and mb.verdict != "UNAVAILABLE" and getattr(mb, "ad_ratio", 0.0) > 0:
                if (
                    mb.verdict == "BROAD_DECLINE"
                    or mb.ad_ratio < 0.60
                    or (mb.declines >= 2.0 * max(1, mb.advances))
                ):
                    logger.info(
                        f"[IndexCallSetup] Suppressed CE setup on {clean_sym}: Market Breadth Liquidation active "
                        f"(Adv: {mb.advances} / Dec: {mb.declines}, A/D {mb.ad_ratio:.2f}). Disallow call setups in negative tide."
                    )
                    return []
        except Exception as e_mb:
            logger.debug(f"[IndexCallSetup] Breadth check bypassed: {e_mb}")

    now_dt = ref_time or datetime.now(IST)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=IST)
    else:
        now_dt = now_dt.astimezone(IST)
    now_iso = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")
    curr_time = now_dt.time()

    # ── 09:25 IST Market Stabilization Gate ─────────────────────────
    # First 10 minutes (09:15 - 09:25 IST) are noisy opening auction price discovery.
    # Multi-candle structural setups (trend pullbacks, double bottoms, day-high breakouts)
    # require at least 2 completed 5m bars and cannot form before 09:25 IST.
    is_opening_buffer = (curr_time < dtime(9, 25)) and not ignore_time_gate and (not is_test_runner or ref_time is not None)
    if is_opening_buffer:
        logger.info(
            f"[IndexCallSetup] Suppressed CE setup on {clean_sym} at {curr_time.strftime('%H:%M:%S')}: "
            f"Opening auction stabilization window (09:15–09:25 IST) active."
        )
        return []

    # Strict today session bar isolation: prevent yesterday's historical bars from forging fake today patterns
    today_str = now_dt.strftime("%Y-%m-%d")
    df_today_5m = None
    if ohlcv_5m is not None:
        try:
            if hasattr(ohlcv_5m, "index") and hasattr(ohlcv_5m.index, "strftime"):
                filtered = ohlcv_5m[ohlcv_5m.index.strftime("%Y-%m-%d") == today_str]
                if len(filtered) >= 1:
                    df_today_5m = filtered
                elif is_test_runner or ignore_time_gate:
                    df_today_5m = ohlcv_5m
            elif hasattr(ohlcv_5m, "iloc"):
                df_today_5m = ohlcv_5m
        except Exception:
            df_today_5m = ohlcv_5m

    is_bse = clean_sym in ("SENSEX", "BANKEX")
    opt_exchange = "BFO" if is_bse else "NFO"
    effective_vwap = vwap if (vwap and vwap > 0) else spot

    # ── Resolve lot size ─────────────────────────────────────────
    try:
        from engine.position_sizer import get_lot_size

        lot_sz = get_lot_size(underlying) or 1
    except Exception:
        lot_sz = 1

    # ── Collect CE contracts within ATM band (within 1.2% of spot) ─
    if clean_sym in ("SENSEX", "BANKEX"):
        min_oi, min_vol = 300, 300
    elif clean_sym == "MIDCPNIFTY":
        min_oi, min_vol = 800, 400
    elif clean_sym == "FINNIFTY":
        min_oi, min_vol = 2000, 800
    else:
        min_oi, min_vol = 5000, 1000

    ce_contracts = [
        c
        for c in chain
        if getattr(c, "option_type", "") == "CE"
        and abs(getattr(c, "strike", 0.0) - spot) / max(1.0, spot) <= 0.012
        and getattr(c, "last_price", 0.0) >= 5.0
        and getattr(c, "volume", 0) >= min_vol
        and getattr(c, "oi", 0) >= min_oi
    ]
    if not ce_contracts:
        return []

    # Sort by optimal Gamma-Torque (high liquidity, proximity to ATM, and sweet-spot premium)
    def _contract_score(c: Any) -> float:
        lp = float(getattr(c, "last_price", 0.0) or 0.0)
        vol = int(getattr(c, "volume", 0) or 0)
        oi = int(getattr(c, "oi", 0) or 1)
        vol_oi = vol / max(1, oi)
        dist_pct = abs(float(getattr(c, "strike", 0.0) or 0.0) - spot) / max(1.0, spot)
        ideal_prem = 40.0 if clean_sym in ("MIDCPNIFTY", "FINNIFTY", "SENSEX") else 125.0
        prem_dist = abs(lp - ideal_prem) / ideal_prem if lp > 0 else 2.0
        return (vol_oi * 15.0) + (min(10.0, vol / 500.0)) - (dist_pct * 300.0) - (prem_dist * 5.0)

    ce_contracts.sort(key=_contract_score, reverse=True)

    best_cand_ce = ce_contracts[0]
    cand_ce_pchange = float(getattr(best_cand_ce, "pchange", 0.0) or 0.0)
    cand_ce_vol = getattr(best_cand_ce, "volume", 0)
    cand_ce_oi = getattr(best_cand_ce, "oi", 0)
    cand_ce_vol_oi = round(cand_ce_vol / max(1, cand_ce_oi), 2)
    is_breakout_momentum = (cand_ce_pchange >= 15.0 and cand_ce_vol_oi >= 1.2) or cand_ce_vol_oi >= 2.0
    is_explosive_momentum = cand_ce_vol_oi >= 3.0 or (cand_ce_pchange >= 25.0 and cand_ce_vol_oi >= 2.0)

    # ── Optimization 1: Intraday Put-Call Ratio (PCR) Confluence Gate ───
    # PCR < 0.65 indicates overwhelming Call Writing overhead capping the ceiling.
    ce_oi_total = sum(int(getattr(c, "oi", 0) or 0) for c in chain if getattr(c, "option_type", "") == "CE")
    pe_oi_total = sum(int(getattr(c, "oi", 0) or 0) for c in chain if getattr(c, "option_type", "") == "PE")
    chain_pcr = round(pe_oi_total / max(1, ce_oi_total), 2) if (ce_oi_total > 5000 and pe_oi_total > 5000) else None

    if chain_pcr is not None and chain_pcr < 0.65 and not is_explosive_momentum:
        logger.info(
            f"[IndexCallSetup] Suppressed CE setup on {clean_sym}: Heavy Call Writing Wall active "
            f"(PCR: {chain_pcr:.2f} < 0.65, Call OI {ce_oi_total:,} vs Put OI {pe_oi_total:,})."
        )
        return []

    # ── Optimization 2: Index Heavyweight Breadth Confluence Matrix (HBCM) ──
    hw_posture: dict[str, Any] = {}
    hbcm_dict: dict[str, Any] = {}
    try:
        from engine.hbcm import evaluate_hbcm
        from market.indices import get_heavyweights_posture

        hw_posture = get_heavyweights_posture(clean_sym)
        hbcm_res = evaluate_hbcm(clean_sym, "BULLISH")
        hbcm_dict = hbcm_res.to_dict()

        if hbcm_res.total_heavyweights > 0:
            if not hbcm_res.confluence_pass and not is_explosive_momentum:
                logger.info(
                    f"[IndexCallSetup] Suppressed CE setup on {clean_sym}: {hbcm_res.rejection_reason}"
                )
                return []
        else:
            active_hw = hw_posture.get("heavyweights", [])
            hw_total = len(active_hw)
            hw_bulls = hw_posture.get("bull_count", 0)
            if hw_posture.get("all_bearish") and not is_explosive_momentum:
                hw_tags = [f"{h['symbol']} ({h['change_pct']:+.2f}%)" for h in active_hw]
                logger.info(
                    f"[IndexCallSetup] Suppressed CE setup on {clean_sym}: Heavyweight locomotives in structural markdown "
                    f"({', '.join(hw_tags)}). Disallow call setups fighting index drivers."
                )
                return []

            # High Conviction Invariant: Index Call requires at least 1 active heavyweight expanding (bull_count >= 1)
            if hw_total > 0 and hw_bulls == 0 and not is_explosive_momentum:
                hw_tags = [f"{h['symbol']} ({h['change_pct']:+.2f}%)" for h in active_hw]
                logger.info(
                    f"[IndexCallSetup] Suppressed CE setup on {clean_sym}: Zero heavyweight locomotives expanding (0/{hw_total} bullish: {', '.join(hw_tags)}). "
                    f"Disallow call setups without locomotive thrust."
                )
                return []
    except Exception as e_hw:
        logger.debug(f"[IndexCallSetup] Heavyweights check bypassed: {e_hw}")

    # ── Optimization 2b: Low-VIX (< 13.0) Range-Bound Regime Filter ──
    vix_val = None
    try:
        from market.indices import get_vix
        vix_val = get_vix()
    except Exception:
        pass
    is_low_vix_range = bool(
        vix_val and 0 < vix_val < 13.0
        and effective_vwap > 0
        and abs((spot - effective_vwap) / effective_vwap * 100.0) < 0.35
        and not is_explosive_momentum
    )

    # ── Opposing Supply Barrier Check (Headroom Sanity & Bull Trap Prevention) ───
    # If spot is right underneath Previous Day High or Day High, buying CE collides directly
    # into overhead supply UNLESS breaking out with true momentum.
    # If spot has just pierced PDH by < 0.15% without momentum, it's a high-probability Bull Trap sweep.
    if prev_day_high and prev_day_high > 0:
        if spot < prev_day_high:
            pdh_headroom_pct = (prev_day_high - spot) / spot * 100.0
            if pdh_headroom_pct < 0.25 and not is_breakout_momentum:
                logger.debug(
                    f"[IndexCallSetup] Suppressed CE: Spot ₹{spot:,.1f} is within {pdh_headroom_pct:.2f}% of PDH ₹{prev_day_high:,.1f} (Opposing Supply Collision)"
                )
                return []
        else:
            pdh_break_pct = (spot - prev_day_high) / prev_day_high * 100.0
            if pdh_break_pct < 0.15 and not is_breakout_momentum:
                logger.debug(
                    f"[IndexCallSetup] Suppressed CE: Spot ₹{spot:,.1f} shallow pierce of PDH ₹{prev_day_high:,.1f} ({pdh_break_pct:.2f}%) without breakout momentum (Bull Trap Risk)"
                )
                return []

    if (
        day_high
        and spot < day_high
        and day_low
        and ((day_high - day_low) / max(1.0, spot)) >= 0.003
    ):
        dh_headroom_pct = (day_high - spot) / spot * 100.0
        if dh_headroom_pct < 0.30 and not is_breakout_momentum:
            logger.debug(
                f"[IndexCallSetup] Suppressed CE: Spot ₹{spot:,.1f} is within {dh_headroom_pct:.2f}% of Day High ₹{day_high:,.1f} (Headroom Truncated)"
            )
            return []

    # ── VWAP Overextension & Climax Filter ───────────────────────
    # If spot has surged > 1.20% above VWAP it's a climax extension — no fresh CE entry.
    # Note: index legs routinely extend 0.8–1.0% above VWAP during genuine momentum moves;
    # the old 0.65% threshold was killing valid continuation setups.
    if effective_vwap > 0 and spot > effective_vwap:
        spot_vwap_ext = (spot - effective_vwap) / effective_vwap * 100.0
        if spot_vwap_ext > 1.20:
            logger.debug(
                f"[IndexCallSetup] Suppressed CE: Spot extended +{spot_vwap_ext:.2f}% above VWAP (>0.65% climax threshold)"
            )
            return []

    # ── Structural Signal Detection ───────────────────────────────
    signals: list[str] = []
    signal_tags: dict[str, Any] = {}

    # 1. PDL Demand Rejection (symmetric to PDH Supply Rejection in put detector)
    # Spot came within 0.25% of prev_day_low and is now bouncing
    if prev_day_low and prev_day_low > 0:
        pdl_proximity_pct = (prev_day_low - (day_low or spot)) / prev_day_low * 100
        spot_bounce_from_low = (spot - (day_low or spot)) / max(1.0, spot) * 100 if day_low else 0.0
        if -0.1 <= pdl_proximity_pct <= 0.5 and spot_bounce_from_low >= 0.1:
            signals.append("PDL_DEMAND_REJECTION")
            signal_tags["pdl_demand_rejection"] = {
                "prev_day_low": prev_day_low,
                "day_low": day_low,
                "pdl_proximity_pct": round(pdl_proximity_pct, 3),
                "bounce_pct": round(spot_bounce_from_low, 3),
            }

    # 2. PWL Demand Rejection (Previous Week Low)
    if prev_week_low and prev_week_low > 0 and "PDL_DEMAND_REJECTION" not in signals:
        pwl_proximity_pct = (prev_week_low - (day_low or spot)) / prev_week_low * 100
        spot_bounce_from_low = (spot - (day_low or spot)) / max(1.0, spot) * 100 if day_low else 0.0
        if -0.15 <= pwl_proximity_pct <= 0.4 and spot_bounce_from_low >= 0.12:
            signals.append("PDL_DEMAND_REJECTION")  # reuse type; tagged differently
            signal_tags["pdl_demand_rejection"] = {
                "level_type": "PWL",
                "prev_week_low": prev_week_low,
                "day_low": day_low,
                "pwl_proximity_pct": round(pwl_proximity_pct, 3),
                "bounce_pct": round(spot_bounce_from_low, 3),
            }

    # 3. VWAP Reclaim (symmetric to VWAP Rejection in put detector)
    # Spot was below VWAP, tagged it from below, and is now holding above
    if effective_vwap > 0 and spot > effective_vwap:
        vwap_reclaim_pct = (spot - effective_vwap) / effective_vwap * 100
        day_low_vs_vwap = (
            (effective_vwap - (day_low or spot)) / effective_vwap * 100 if day_low else 0.0
        )
        # Day low must have been at or below VWAP (was below it) but spot now above (reclaimed)
        if day_low_vs_vwap >= -0.1 and vwap_reclaim_pct >= 0.05:
            signals.append("VWAP_RECLAIM")
            signal_tags["vwap_reclaim"] = {
                "vwap": effective_vwap,
                "spot": spot,
                "vwap_reclaim_pct": round(vwap_reclaim_pct, 3),
                "day_low": day_low,
                "day_low_vs_vwap_pct": round(day_low_vs_vwap, 3),
            }

    # 4. Intraday Demand Zone Sweep (symmetric to Supply Zone Sweep in put detector)
    # Spot's intraday low exceeded the opening range low - 0.3% and has since bounced
    active_ohlcv = df_today_5m if df_today_5m is not None else ohlcv_5m
    if active_ohlcv is not None:
        try:
            import pandas as pd  # noqa: F401 — runtime only

            if hasattr(active_ohlcv, "iloc") and len(active_ohlcv) >= 8 and not is_opening_buffer:
                col_h = "high" if "high" in active_ohlcv.columns else "High"
                col_l = "low" if "low" in active_ohlcv.columns else "Low"
                col_c = "close" if "close" in active_ohlcv.columns else "Close"
                col_v = "volume" if "volume" in active_ohlcv.columns else "Volume"

                # Opening range = first 4 bars (09:15 – 09:35 IST)
                or_low = float(active_ohlcv[col_l].iloc[:4].min())
                last_bar = active_ohlcv.iloc[-1]
                last_bar_low = float(last_bar[col_l])
                last_bar_close = float(last_bar[col_c])
                last_bar_vol = float(last_bar[col_v])
                avg_vol = float(active_ohlcv[col_v].iloc[:-1].mean())

                demand_sweep_pct = (or_low - last_bar_low) / max(1.0, or_low) * 100
                candle_range = max(0.01, float(last_bar[col_h]) - last_bar_low)
                wick_pct = (last_bar_close - last_bar_low) / candle_range * 100  # lower wick body
                rvol = last_bar_vol / max(1.0, avg_vol)

                # Sweep: low exceeded OR low by 0.3%+, closed back above (wick >= 40%), RVOL >= 1.3x
                if demand_sweep_pct >= 0.30 and wick_pct >= 40.0 and rvol >= 1.3:
                    signals.append("DEMAND_ZONE_SWEEP")
                    signal_tags["demand_zone_sweep"] = {
                        "opening_range_low": round(or_low, 2),
                        "last_bar_low": round(last_bar_low, 2),
                        "demand_sweep_pct": round(demand_sweep_pct, 3),
                        "lower_wick_pct": round(wick_pct, 1),
                        "rvol": round(rvol, 2),
                    }

                # 5. Bearish Exhaustion → CE setup
                # Extreme selling wick on current bar = demand absorption (smart money buying)
                if rvol >= 1.5 and wick_pct >= 55.0 and last_bar_close > (or_low * 1.001):
                    if "DEMAND_ZONE_SWEEP" not in signals:
                        signals.append("BEARISH_EXHAUSTION_CE")
                        signal_tags["bearish_exhaustion"] = {
                            "lower_wick_pct": round(wick_pct, 1),
                            "rvol": round(rvol, 2),
                            "last_bar_close": round(last_bar_close, 2),
                        }

                # 6. Double Bottom Detection (symmetric to Double Top in put detector)
                if len(active_ohlcv) >= 12 and not is_opening_buffer:
                    rolling_lows = active_ohlcv[col_l].values
                    troughs = []
                    for i in range(2, len(rolling_lows) - 1):
                        if (
                            rolling_lows[i] < rolling_lows[i - 1]
                            and rolling_lows[i] < rolling_lows[i + 1]
                        ):
                            troughs.append((i, rolling_lows[i]))
                    if len(troughs) >= 2:
                        t1_idx, t1_val = troughs[-2]
                        t2_idx, t2_val = troughs[-1]
                        trough_diff_pct = abs(t1_val - t2_val) / max(1.0, t1_val) * 100
                        if trough_diff_pct <= 0.25 and spot > t2_val * 1.002:
                            signals.append("DOUBLE_BOTTOM_BREAKOUT")
                            signal_tags["double_bottom"] = {
                                "trough_1": round(t1_val, 2),
                                "trough_2": round(t2_val, 2),
                                "trough_diff_pct": round(trough_diff_pct, 3),
                                "current_spot": spot,
                            }

                # 7. VCP Coiling — Pre-Breakout Early Warning (EARLY_WARNING stage)
                # ATR compression: last 4 bars each narrower than the previous.
                # Spot within 0.30% of session high with CE OI building.
                # Fires 5–15 mins BEFORE the breakout candle, capturing the full option move.
                if len(active_ohlcv) >= 6 and not is_opening_buffer and "VCP_COILING" not in signals:
                    try:
                        recent = active_ohlcv.iloc[-5:]
                        ranges = (recent[col_h] - recent[col_l]).values.tolist()
                        is_compressing = (
                            all(
                                ranges[i] < ranges[i - 1] * 1.05  # < 5% wider than prior bar
                                for i in range(1, len(ranges))
                            )
                            and ranges[-1] < ranges[0] * 0.70
                        )  # final bar < 70% of 5-bar open
                        total_range_pct = (
                            (max(recent[col_h]) - min(recent[col_l])) / max(1.0, spot) * 100
                        )
                        # Spot within 0.30% of the recent high (coiling near top)
                        near_session_high = (
                            day_high and (day_high - spot) / max(1.0, spot) * 100 <= 0.30
                        )
                        last_bar_vol_ratio = (
                            last_bar_vol / max(1.0, avg_vol) if avg_vol > 0 else 1.0
                        )

                        if (
                            is_compressing
                            and total_range_pct <= 0.35
                            and near_session_high
                            and last_bar_vol_ratio >= 0.8  # volume not dried up
                        ):
                            signals.append("VCP_COILING")
                            signal_tags["vcp_coiling"] = {
                                "bar_ranges_pct": [
                                    round(r / max(1.0, spot) * 100, 3) for r in ranges
                                ],
                                "total_range_pct": round(total_range_pct, 3),
                                "near_session_high": bool(near_session_high),
                                "vol_ratio": round(last_bar_vol_ratio, 2),
                            }
                    except Exception as e_vcp:
                        logger.debug(f"[IndexCallSetup] VCP coiling check error: {e_vcp}")

                # 8. Trend Continuation Pullback (EMA 9/20 & VWAP Support Reclaim)
                # Catches sustained morning trends where price pulls back into EMA/VWAP support and resumes up
                if len(active_ohlcv) >= 6 and not is_opening_buffer and "TREND_PULLBACK_RECLAIM" not in signals:
                    try:
                        closes = active_ohlcv[col_c].values
                        lows = active_ohlcv[col_l].values
                        highs = active_ohlcv[col_h].values
                        col_o = "open" if "open" in active_ohlcv.columns else "Open"
                        opens = active_ohlcv[col_o].values

                        ema9 = pd.Series(closes).ewm(span=9, adjust=False).mean().values[-1]
                        ema20 = (
                            pd.Series(closes).ewm(span=20, adjust=False).mean().values[-1]
                            if len(closes) >= 20
                            else pd.Series(closes).mean()
                        )

                        last_l = float(lows[-1])
                        last_c = float(closes[-1])
                        last_o = float(opens[-1])
                        candle_rng = max(0.1, float(highs[-1]) - last_l)

                        # Bullish moving average alignment & holding above or near VWAP
                        if ema9 >= (ema20 * 0.998) and spot >= (effective_vwap * 0.997):
                            tested_ema = last_l <= (ema9 * 1.002) and last_c >= (ema9 * 0.999)
                            tested_vwap = (
                                effective_vwap > 0
                                and last_l <= (effective_vwap * 1.002)
                                and last_c >= (effective_vwap * 0.999)
                            )
                            is_bullish_candle = (last_c >= last_o) and (
                                (last_c - last_l) / candle_rng >= 0.35
                            )

                            if (tested_ema or tested_vwap) and is_bullish_candle:
                                signals.append("TREND_PULLBACK_RECLAIM")
                                signal_tags["trend_pullback"] = {
                                    "ema9": round(float(ema9), 2),
                                    "ema20": round(float(ema20), 2),
                                    "vwap": round(float(effective_vwap), 2),
                                    "spot": spot,
                                }
                    except Exception as e_tpb:
                        logger.debug(f"[IndexCallSetup] Trend pullback check error: {e_tpb}")

        except Exception as e_ohlcv:
            logger.debug(f"[IndexCallSetup] OHLCV analysis error for {underlying}: {e_ohlcv}")

    # 9. Day High Breakout (Bullish Continuation / Range Expansion)
    # When spot is testing or breaking out through session high with VWAP support and CE momentum
    if day_high and day_high > 0 and "DAY_HIGH_BREAKOUT" not in signals and not is_opening_buffer:
        dh_dist_pct = (spot - day_high) / day_high * 100.0
        # Within 0.15% below day high, or broke out above day high up to 0.50%
        if -0.15 <= dh_dist_pct <= 0.50 and (
            spot >= (effective_vwap * 0.998) if effective_vwap > 0 else True
        ):
            if is_breakout_momentum or (active_ohlcv is not None and len(active_ohlcv) >= 3):
                signals.append("DAY_HIGH_BREAKOUT")
                signal_tags["day_high_breakout"] = {
                    "day_high": day_high,
                    "spot": spot,
                    "dh_dist_pct": round(dh_dist_pct, 3),
                    "ce_pchange": cand_ce_pchange,
                    "vol_oi": cand_ce_vol_oi,
                }

    # 10. Institutional Expansion Thrust (Parabolic Momentum Squeeze)
    # Detects vertical institutional thrusts that breakout through session consolidation or Day High
    # with ATR range expansion, volume surge, and strong close near the highs.
    is_institutional_thrust = False
    thrust_details: dict[str, Any] = {}
    if active_ohlcv is not None and len(active_ohlcv) >= 6 and not is_opening_buffer:
        try:
            import pandas as pd  # noqa: F401
            col_h = "high" if "high" in active_ohlcv.columns else "High"
            col_l = "low" if "low" in active_ohlcv.columns else "Low"
            col_c = "close" if "close" in active_ohlcv.columns else "Close"
            col_o = "open" if "open" in active_ohlcv.columns else "Open"
            col_v = "volume" if "volume" in active_ohlcv.columns else "Volume"

            highs = active_ohlcv[col_h].values
            lows = active_ohlcv[col_l].values
            closes = active_ohlcv[col_c].values
            opens = active_ohlcv[col_o].values
            vols = active_ohlcv[col_v].values

            # 5m ATR(14)
            tr = [highs[0] - lows[0]]
            for i in range(1, len(active_ohlcv)):
                tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
            atr_14 = float(pd.Series(tr).rolling(min(14, len(tr)), min_periods=1).mean().iloc[-1])

            last_bar_rng = max(0.1, float(highs[-1]) - float(lows[-1]))
            rng_atr_ratio = round(last_bar_rng / max(1.0, atr_14), 2)

            avg_vol_20 = float(pd.Series(vols).rolling(min(20, len(vols)), min_periods=1).mean().iloc[-1])
            last_vol = float(vols[-1])
            vol_ratio = round(last_vol / max(1.0, avg_vol_20), 2)

            last_c = float(closes[-1])
            last_o = float(opens[-1])
            last_h = float(highs[-1])
            last_l = float(lows[-1])

            # Upper wick rejection check: upper wick <= 25% of candle range
            upper_wick = max(0.0, last_h - max(last_c, last_o))
            upper_wick_pct = round((upper_wick / last_bar_rng) * 100.0, 1)

            # Bullish close check: close >= open and close in top 30% of bar
            close_pos_pct = round(((last_c - last_l) / last_bar_rng) * 100.0, 1)

            # Day high or session high breakout
            dh_val = day_high or (max(highs[:-1]) if len(highs) >= 2 else (highs[0] if len(highs) >= 1 else spot))
            is_at_or_above_dh = (last_c >= dh_val * 0.9995) or (spot >= dh_val)

            # Cumulative Volume Delta (CVD) Footprint Check:
            # Integrate tick-level or intra-candle buyer/seller aggressive volume delta into the 5m thrust detector.
            # Alert fires ONLY if buyer volume exceeds seller volume by >= 2.2x during the breakout candle.
            if "buy_volume" in active_ohlcv and "sell_volume" in active_ohlcv:
                buyer_vol = float(active_ohlcv["buy_volume"].iloc[-1])
                seller_vol = float(active_ohlcv["sell_volume"].iloc[-1])
            else:
                # Intra-candle footprint proxy:
                # If candle is red (close < open) or doji with negligible range, buyers cannot dominate
                if last_c < last_o or last_bar_rng < (max(1.0, atr_14) * 0.3):
                    buyer_vol = last_vol * 0.2
                    seller_vol = last_vol * 0.8
                else:
                    buyer_vol = last_vol * max(0.01, (last_c - last_l)) / last_bar_rng
                    seller_vol = last_vol * max(0.01, (last_h - last_c)) / last_bar_rng
            cvd_ratio = round(buyer_vol / max(1.0, seller_vol), 2)
            is_cvd_buyer_dominant = cvd_ratio >= 2.2

            # Institutional thrust criteria:
            # 1. Range expansion: >= 1.3x ATR
            # 2. Volume expansion: >= 1.6x 20-EMA volume (or highest volume of last 10 bars)
            # 3. Clean absorption: upper wick <= 25%, close in top 30%
            # 4. CVD footprint: buyer volume >= 2.2x seller volume
            # 5. Breaking Day/Session High
            # 6. Call momentum confirmed (pchange >= 12% or vol_oi >= 1.2 or is_breakout_momentum)
            is_vol_surge = (vol_ratio >= 1.6) or (last_vol >= max(vols[-min(10, len(vols)):-1]) if len(vols) >= 3 else True)
            if (
                rng_atr_ratio >= 1.3
                and is_vol_surge
                and upper_wick_pct <= 25.0
                and close_pos_pct >= 70.0
                and is_cvd_buyer_dominant
                and is_at_or_above_dh
                and (is_breakout_momentum or cand_ce_pchange >= 12.0)
            ):
                is_institutional_thrust = True
                signals.append("INSTITUTIONAL_EXPANSION_THRUST")
                thrust_details = {
                    "range_atr_ratio": rng_atr_ratio,
                    "vol_ratio": vol_ratio,
                    "cvd_ratio": cvd_ratio,
                    "buyer_vol": round(buyer_vol, 0),
                    "seller_vol": round(seller_vol, 0),
                    "upper_wick_pct": upper_wick_pct,
                    "close_pos_pct": close_pos_pct,
                    "day_high": round(float(dh_val), 2),
                    "breakout_bar_low": round(last_l, 2),
                    "atr_14": round(atr_14, 2),
                }
                signal_tags["institutional_expansion_thrust"] = thrust_details
        except Exception as e_thrust:
            logger.debug(f"[IndexCallSetup] Thrust check error: {e_thrust}")

    if not signals:
        return []

    # ── Select Best CE Contract ───────────────────────────────────
    best_ce = ce_contracts[0]
    strike = float(getattr(best_ce, "strike", spot))
    opt_ltp = float(getattr(best_ce, "last_price", 0.0) or 0.0)
    contract_sym = getattr(best_ce, "symbol", f"{clean_sym}{int(strike)}CE")
    exp_date = getattr(best_ce, "expiry", None)
    oi = getattr(best_ce, "oi", 0)
    oi_change = getattr(best_ce, "oi_change", 0)
    volume = getattr(best_ce, "volume", 0)
    vol_oi_ratio = round(volume / max(1, oi), 2)
    pchange = float(getattr(best_ce, "pchange", 0.0) or 0.0)
    exp_type = classify_expiry_type(exp_date, underlying) if exp_date else "WEEKLY"

    # ── Confidence Score ─────────────────────────────────────────
    base_confidence = 68
    signal_bonuses = {
        "PDL_DEMAND_REJECTION": 14,
        "VWAP_RECLAIM": 10,
        "DEMAND_ZONE_SWEEP": 8,
        "BEARISH_EXHAUSTION_CE": 10,
        "DOUBLE_BOTTOM_BREAKOUT": 8,
        "VCP_COILING": 7,  # Pre-breakout, lower confidence since not yet confirmed
        "DAY_HIGH_BREAKOUT": 12,
        "INSTITUTIONAL_EXPANSION_THRUST": 16,
    }
    confidence = base_confidence
    for sig in signals:
        confidence += signal_bonuses.get(sig, 5)
    confidence += min(8, int(vol_oi_ratio * 3))
    if pchange >= 10.0:
        confidence += 6
    confidence = min(96, confidence)

    # VCP_COILING is always EARLY_WARNING (fires before the breakout candle)
    if signals == ["VCP_COILING"]:
        stage = "EARLY_WARNING"
    elif is_institutional_thrust:
        stage = "IGNITED"
    else:
        stage = "IGNITED" if (pchange >= 8.0 or vol_oi_ratio >= 1.5) else "EARLY_WARNING"

    # ── Trade Plan ───────────────────────────────────────────────
    try:
        from engine.trade_plan import calculate_option_execution_plan, get_market_status
        from engine.position_sizer import get_lot_size as _gls

        lot_sz = _gls(underlying) or lot_sz
        opt_plan = (
            calculate_option_execution_plan(
                trade_plan=None,
                option_type="CE",
                strike=strike,
                expiry=exp_date or "",
                option_ltp=opt_ltp,
                lot_size=lot_sz,
            )
            if (opt_ltp > 0 and exp_date)
            else None
        )
        mkt_status = get_market_status(opt_exchange)
    except Exception:
        opt_plan = None
        mkt_status = {"status": "SESSION_OPEN", "label": "⚡ SESSION OPEN"}

    t1_premium = opt_plan["t1_premium"] if opt_plan else round(opt_ltp * 1.30, 1)
    t2_premium = opt_plan.get("t2_premium") if opt_plan else round(opt_ltp * 1.55, 1)
    t3_premium = opt_plan.get("t3_premium") if opt_plan else round(opt_ltp * 1.90, 1)
    sl_premium = opt_plan["sl_premium"] if opt_plan else round(max(0.5, opt_ltp * 0.80), 1)
    rr_str = opt_plan.get("option_rr", "1:1.9") if opt_plan else "1:1.9"
    t1_pct = opt_plan.get("t1_pct", 30.0) if opt_plan else 30.0

    # ── Velocity Regime Check ────────────────────────────────────
    vel_regime = "NORMAL_TREND"
    vel_score = 50.0
    try:
        from engine.index_velocity import calculate_index_velocity

        v_metric = calculate_index_velocity(
            clean_sym, spot=spot, ohlcv_5m=ohlcv_5m, day_high=day_high, day_low=day_low
        )
        vel_regime = v_metric.regime
        vel_score = v_metric.velocity_score
    except Exception:
        pass

    vel_badge = ""
    if vel_regime == "LEADER_EXPANSION":
        vel_badge = "🚀 LEADER "
    elif vel_regime == "CHOP_PINNED":
        vel_badge = "⚠️ LOW VELOCITY "

    # ── Build Headline & Summary ─────────────────────────────────
    primary_signal = signals[0]
    icon = _SETUP_ICONS.get(primary_signal, "🟢")

    if "INSTITUTIONAL_EXPANSION_THRUST" in signals:
        iet = signal_tags.get("institutional_expansion_thrust", {})
        headline = f"🚀 INSTITUTIONAL EXPANSION THRUST: {clean_sym} {int(strike)} CE"
        summary = (
            f"Institutional breakout thrust: Spot (₹{spot:,.1f}) breaking Session High (₹{iet.get('day_high', 0):,.1f}) "
            f"with {iet.get('range_atr_ratio', 1.3):.1f}x ATR expansion & {iet.get('vol_ratio', 1.6):.1f}x volume surge. "
            f"Clean absorption ({iet.get('upper_wick_pct', 0):.0f}% upper wick) with CE momentum ({volume:,} contracts, {vol_oi_ratio:.1f}x Vol/OI, +{pchange:.1f}%). "
            f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{sl_premium:,.1f} | T1: ₹{t1_premium:,.1f} (+{t1_pct:.0f}%)."
        )
    elif "PDL_DEMAND_REJECTION" in signals:
        level_type = signal_tags.get("pdl_demand_rejection", {}).get("level_type", "PDL")
        headline = (
            f"{vel_badge}{icon} SMC {level_type} DEMAND REJECTION: {clean_sym} {int(strike)} CE"
        )
        struct_detail = signal_tags["pdl_demand_rejection"]
        ref_level = struct_detail.get("prev_day_low") or struct_detail.get("prev_week_low", 0.0)
        bounce_pct = struct_detail.get("bounce_pct", 0.0)
        summary = (
            f"Spot swept {level_type} (₹{ref_level:,.1f}) and bounced with a {bounce_pct:.2f}% demand wick — "
            f"institutional demand OB confirmed. Call volume surging ({volume:,} contracts, {vol_oi_ratio:.1f}x Vol/OI). "
            f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{sl_premium:,.1f} | T1: ₹{t1_premium:,.1f} (+{t1_pct:.0f}%)."
        )
    elif "VWAP_RECLAIM" in signals:
        vr = signal_tags.get("vwap_reclaim", {})
        headline = f"{icon} VWAP RECLAIM CALL SETUP: {clean_sym} {int(strike)} CE"
        summary = (
            f"Spot reclaimed VWAP (₹{effective_vwap:,.1f}) — now acting as support (bullish flip). "
            f"Spot {vr.get('vwap_reclaim_pct', 0):.2f}% above VWAP post-reclaim. "
            f"Call volume active ({volume:,} contracts, {vol_oi_ratio:.1f}x). "
            f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{sl_premium:,.1f} | T1: ₹{t1_premium:,.1f} (+{t1_pct:.0f}%)."
        )
    elif "DEMAND_ZONE_SWEEP" in signals:
        sweep = signal_tags.get("demand_zone_sweep", {})
        headline = f"{icon} INTRADAY DEMAND SWEEP: {clean_sym} {int(strike)} CE"
        summary = (
            f"Spot swept opening range low (₹{sweep.get('opening_range_low', 0):,.1f}) by "
            f"{sweep.get('demand_sweep_pct', 0):.2f}% — {sweep.get('lower_wick_pct', 0):.0f}% demand wick "
            f"(RVOL {sweep.get('rvol', 0):.1f}x). Institutional demand OB confirmed. "
            f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{sl_premium:,.1f} | T1: ₹{t1_premium:,.1f} (+{t1_pct:.0f}%)."
        )
    elif "BEARISH_EXHAUSTION_CE" in signals:
        exh = signal_tags.get("bearish_exhaustion", {})
        headline = f"{icon} BEARISH EXHAUSTION CALL SETUP: {clean_sym} {int(strike)} CE"
        summary = (
            f"Extreme selling wick ({exh.get('lower_wick_pct', 0):.0f}%) on {exh.get('rvol', 0):.1f}x RVOL — "
            f"demand absorption confirmed, smart money stepping in. "
            f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{sl_premium:,.1f} | T1: ₹{t1_premium:,.1f} (+{t1_pct:.0f}%)."
        )
    elif "DOUBLE_BOTTOM_BREAKOUT" in signals:
        db = signal_tags.get("double_bottom", {})
        headline = f"{icon} DOUBLE BOTTOM BREAKOUT: {clean_sym} {int(strike)} CE"
        summary = (
            f"Two equal intraday lows (₹{db.get('trough_1', 0):,.1f} / ₹{db.get('trough_2', 0):,.1f}, "
            f"{db.get('trough_diff_pct', 0):.2f}% apart) — spot breaking above neckline. "
            f"Call momentum building ({volume:,} contracts, {vol_oi_ratio:.1f}x Vol/OI). "
            f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{sl_premium:,.1f} | T1: ₹{t1_premium:,.1f} (+{t1_pct:.0f}%)."
        )
    elif "VCP_COILING" in signals:
        vcp = signal_tags.get("vcp_coiling", {})
        headline = f"🔴 VCP COILING — PRE-BREAKOUT EARLY WARNING: {clean_sym} {int(strike)} CE"
        summary = (
            f"⚡ Range compression detected ({vcp.get('total_range_pct', 0):.2f}% over 5 bars) near session high. "
            f"Classic Volatility Contraction Pattern — breakout imminent within 1–3 bars. "
            f"CE OI building ({vol_oi_ratio:.1f}x Vol/OI). "
            f"Optimal Entry Zone: ₹{opt_ltp:,.1f}–₹{round(opt_ltp * 1.03, 1):,.1f} | SL: ₹{sl_premium:,.1f} | T1: ₹{t1_premium:,.1f} (+{t1_pct:.0f}%). "
            f"DO NOT CHASE above ₹{round(opt_ltp * 1.08, 1):,.1f} — wait for volume confirmation candle."
        )
    elif "TREND_PULLBACK_RECLAIM" in signals:
        tpb = signal_tags.get("trend_pullback", {})
        headline = f"📈 TREND PULLBACK RECLAIM: {clean_sym} {int(strike)} CE"
        summary = (
            f"Bullish trend continuation: Spot (₹{spot:,.1f}) tested EMA-9/20 support (₹{tpb.get('ema9', 0):,.1f}) and held above VWAP (₹{effective_vwap:,.1f}) with buyers stepping in. "
            f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{sl_premium:,.1f} | T1: ₹{t1_premium:,.1f} (+{t1_pct:.0f}%)."
        )
    elif "DAY_HIGH_BREAKOUT" in signals:
        dhb = signal_tags.get("day_high_breakout", {})
        headline = f"🚀 DAY HIGH BREAKOUT: {clean_sym} {int(strike)} CE"
        summary = (
            f"Spot (₹{spot:,.1f}) breaking out through Session High (₹{dhb.get('day_high', 0):,.1f}) with bullish momentum. "
            f"Spot holding above VWAP (₹{effective_vwap:,.1f}) with CE volume expansion ({volume:,} contracts, {vol_oi_ratio:.1f}x Vol/OI, +{pchange:.1f}%). "
            f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{sl_premium:,.1f} | T1: ₹{t1_premium:,.1f} (+{t1_pct:.0f}%)."
        )
    else:
        headline = f"{icon} SMC BULLISH SETUP: {clean_sym} {int(strike)} CE ({primary_signal.replace('_', ' ')})"
        summary = (
            f"Structural bullish signal detected ({', '.join(signals)}). "
            f"Call volume: {volume:,} contracts ({vol_oi_ratio:.1f}x Vol/OI). "
            f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{sl_premium:,.1f} | T1: ₹{t1_premium:,.1f} (+{t1_pct:.0f}%)."
        )

    # ── Liquidity Audit ─────────────────────────────────────────
    try:
        from market.options import audit_option_liquidity

        liq_audit = audit_option_liquidity(best_ce, underlying=underlying, lot_size=lot_sz)
    except Exception:
        liq_audit = {"liquidity_status": "UNKNOWN", "bid_ask_spread_pct": 0.0}

    is_authentic = bool(opt_ltp and opt_ltp > 0.0)
    alert_env = "LIVE" if is_authentic else "TEST"

    # ── Defined-Risk Hedged Spread Construction (Bull Call Spread) ─
    hedge_plan = None
    step = 100.0 if clean_sym in ("BANKNIFTY", "SENSEX") else 50.0
    spread_width = 2.0 * step if clean_sym in ("BANKNIFTY", "SENSEX") else step
    otm_target_strike = strike + spread_width

    # 1. Try exact target OTM strike in provided chain
    otm_cand = None
    exact_matches = [
        c
        for c in chain
        if getattr(c, "option_type", "") == "CE"
        and abs(getattr(c, "strike", 0.0) - otm_target_strike) <= (step * 0.25)
        and float(getattr(c, "last_price", 0.0) or 0.0) > 0.0
    ]
    if exact_matches:
        otm_cand = exact_matches[0]
    else:
        # Fallback to any contract in chain with strike > strike
        higher_strikes = [
            c
            for c in chain
            if getattr(c, "option_type", "") == "CE"
            and getattr(c, "strike", 0.0) >= (strike + spread_width * 0.75)
            and float(getattr(c, "last_price", 0.0) or 0.0) > 0.0
        ]
        if higher_strikes:
            higher_strikes.sort(key=lambda c: abs(getattr(c, "strike", 0.0) - otm_target_strike))
            otm_cand = higher_strikes[0]

    if otm_cand:
        sell_strike = float(getattr(otm_cand, "strike", otm_target_strike))
        sell_prem = float(getattr(otm_cand, "last_price", 0.0) or 0.0)
    else:
        sell_strike = strike + spread_width
        try:
            from engine.options_backtest import bs_premium

            sell_prem = round(bs_premium(spot, sell_strike, 7, 0.15, "CE"), 2)
        except Exception:
            sell_prem = 0.0

    if sell_strike <= strike:
        sell_strike = strike + spread_width

    actual_width = sell_strike - strike
    if sell_prem <= 0.0 or sell_prem >= opt_ltp or (opt_ltp - sell_prem) >= actual_width:
        sell_prem = max(
            1.0, round(min(opt_ltp * 0.55, max(1.0, opt_ltp - (actual_width * 0.35))), 2)
        )

    if opt_ltp > 0 and sell_prem > 0 and sell_strike > strike:
        net_debit = round(max(1.0, min(actual_width * 0.75, opt_ltp - sell_prem)), 2)
        strike_width = round(sell_strike - strike, 2)
        max_loss = round(net_debit * lot_sz, 2)
        max_profit = round(max(1.0, (strike_width - net_debit) * lot_sz), 2)
        be_spot = round(spot + net_debit, 1)
        rr_spread = round(max_profit / max(1.0, max_loss), 2)

        now_time = now_dt.time()
        is_midday_chop_window = (dtime(11, 30) <= now_time <= dtime(14, 0)) and (vel_score < 70)
        if is_low_vix_range:
            pref_veh = "SPREAD_ONLY"
            spread_guidance = (
                "⚠️ LOW-VIX RANGE-BOUND REGIME (India VIX < 13.0): Naked CE prohibited due to accelerated theta decay; "
                "execute defined-risk Bull Call Spread only."
            )
        elif is_midday_chop_window:
            pref_veh = "HEDGED_SPREAD"
            spread_guidance = "⚠️ MIDDAY CHOP WINDOW: Execute Bull Call Spread to avoid theta decay."
        else:
            pref_veh = "NAKED_OPTION_OR_SPREAD"
            spread_guidance = "High Momentum: Fast scalpers can trade Naked CE; for defined risk, trade Bull Call Spread."

        hedge_plan = {
            "strategy": "BULL_CALL_SPREAD",
            "sentiment": "BULLISH",
            "preferred_vehicle": pref_veh,
            "description": f"Buy {int(strike)} CE & Sell {int(sell_strike)} CE (Defined Risk / Capped Loss)",
            "buy_leg": f"BUY {clean_sym} {int(strike)} CE @ ₹{opt_ltp:,.1f}",
            "sell_leg": f"SELL {clean_sym} {int(sell_strike)} CE @ ₹{sell_prem:,.1f}",
            "net_debit_per_share": net_debit,
            "net_debit_total": max_loss,
            "max_loss": max_loss,
            "max_profit": max_profit,
            "breakeven_spot": be_spot,
            "risk_reward": f"1:{rr_spread:.1f}",
            "lot_size": lot_sz,
            "strike_width": actual_width,
            "buy_strike": strike,
            "sell_strike": sell_strike,
            "short_strike": sell_strike,
            "booking_target_70": round(net_debit + 0.70 * (actual_width - net_debit), 2),
            "spread_stop_loss": round(net_debit * 0.50, 2),
            "booking_rule": (
                f"Book 70%–80% Max Profit (Net Spread value ₹{round(net_debit + 0.70 * (actual_width - net_debit), 2):,.1f}) "
                f"or if Spot touches {sell_strike:,.0f} (Short Strike Wall). Stop loss if spread decays below ₹{round(net_debit * 0.50, 2):,.1f}."
            ),
            "margin_benefit_note": "SEBI Hedged Margin: ~70% margin reduction when executing both legs simultaneously.",
            "peace_of_mind_benefit": "Zero Theta Bleed — short OTM leg finances time decay. Maximum risk strictly capped.",
            "execution_guidance": spread_guidance,
            "legs": [
                {
                    "side": "BUY",
                    "strike": strike,
                    "option_type": "CE",
                    "premium": opt_ltp,
                    "lots": 1,
                    "qty": lot_sz,
                },
                {
                    "side": "SELL",
                    "strike": sell_strike,
                    "option_type": "CE",
                    "premium": sell_prem,
                    "lots": 1,
                    "qty": lot_sz,
                },
            ],
        }

    # ── Optimal Trade Entry (OTE) & No-Chase Guard ───────────────
    if is_low_vix_range and not hedge_plan:
        logger.info(
            f"[IndexCallSetup] Suppressed CE setup on {clean_sym}: Low-VIX range-bound regime without viable hedged spread."
        )
        return []

    act_verb = "BULL CALL SPREAD" if (is_low_vix_range and hedge_plan) else "BUY CE"
    target_inst = (
        f"{clean_sym} {int(strike)}/{int(hedge_plan['sell_strike'])} Bull Call Spread"
        if (is_low_vix_range and hedge_plan)
        else contract_sym
    )

    entry_min = round(max(0.5, opt_ltp * 0.94), 1) if opt_ltp > 0 else spot
    entry_max = round(opt_ltp * 1.02, 1) if opt_ltp > 0 else spot
    entry_range_str = f"₹{entry_min:,.1f} – ₹{entry_max:,.1f}"
    no_chase_lvl = round(opt_ltp * 1.04, 1) if opt_ltp > 0 else round(spot * 1.004, 1)

    alert = AutoAlert(
        alert_id=generate_alert_id(clean_sym, "INDEX_CALL_SETUP", variant=f"ce-{int(strike)}"),
        alert_type="GAMMA_BLAST",
        stage=stage,
        symbol=clean_sym,
        exchange=opt_exchange,
        direction="BULLISH",
        headline=f"🛡️ [HEDGED SPREAD MANDATE] {headline}" if (is_low_vix_range and hedge_plan) else headline,
        summary=f"{summary} | OTE Entry: {entry_range_str} | No Chase > ₹{no_chase_lvl}",
        ltp=opt_ltp or spot,
        trigger_level=opt_ltp if (opt_ltp and opt_ltp > 0) else strike,
        target_level=t1_premium,
        stop_loss=sl_premium,
        no_chase_boundary=no_chase_lvl,
        strike=strike,
        option_type="CE",
        contract_symbol=contract_sym,
        expiry_date=exp_date,
        expiry_type=exp_type,
        underlying_spot=spot,
        option_premium=opt_ltp or None,
        market_status=mkt_status.get("status", "SESSION_OPEN"),
        is_live=is_authentic,
        environment=alert_env,
        liquidity_status=liq_audit.get("liquidity_status", "UNKNOWN"),
        bid_ask_spread_pct=liq_audit.get("bid_ask_spread_pct", 0.0),
        segment="FNO_INDEX",
        lot_size=lot_sz,
        confidence=confidence,
        created_at=now_iso,
        metrics={
            "strike": strike,
            "oi": oi,
            "oi_change": oi_change,
            "volume": volume,
            "vol_oi_ratio": vol_oi_ratio,
            "spot": spot,
            "vwap": effective_vwap,
            "spot_to_vwap_pct": round(
                ((spot - effective_vwap) / max(1.0, effective_vwap)) * 100, 2
            ),
            "lot_size": lot_sz,
            "liquidity": liq_audit,
            # SMC structural signal context
            "signals": signals,
            "signal_tags": signal_tags,
            "hedge_plan": hedge_plan,
            # CHoCH / MSS tags for whiplash guard unlock (PDL bounce IS a structural reversal)
            "choch": "PDL_DEMAND_REJECTION" in signals,
            "mss": "PDL_DEMAND_REJECTION" in signals,
            "pdl_sweep": "PDL_DEMAND_REJECTION" in signals,
            "pdh_sweep": False,
            "day_high": day_high,
            "day_low": day_low,
            "prev_day_high": prev_day_high,
            "prev_day_low": prev_day_low,
            "pcr": chain_pcr,
            "heavyweights_posture": hw_posture.get("summary", "UNAVAILABLE"),
            "hbcm": hbcm_dict,
            "cvd_ratio": thrust_details.get("cvd_ratio", cvd_ratio if "cvd_ratio" in locals() else 0.0),
            "detector": "INDEX_CALL_SETUP",
            "is_institutional_thrust": is_institutional_thrust,
            "thrust_details": thrust_details,
            "breakout_bar_low": thrust_details.get("breakout_bar_low"),
        },
        actionable_plan={
            "action": act_verb,
            "contract": contract_sym,
            "instrument": target_inst,
            "instrument_type": "OPTION_SPREAD" if (is_low_vix_range and hedge_plan) else "OPTION",
            "preferred_vehicle": hedge_plan.get("preferred_vehicle") if hedge_plan else "NAKED_OPTION",
            "strike": strike,
            "option_type": "CE",
            "expiry_date": exp_date,
            "expiry_type": exp_type,
            "underlying_spot": f"₹{spot:,.1f}",
            "recommended_entry": f"₹{opt_ltp:,.2f} (OTE Pullback: {entry_range_str})"
            if opt_ltp
            else "Market",
            "entry_range": entry_range_str,
            "no_chase": f"DO NOT CHASE above ₹{no_chase_lvl}",
            "impulse_trigger_level": round(opt_ltp * 1.01, 2) if opt_ltp > 0 else spot,
            "target_1": f"₹{t1_premium:,.2f}",
            "target": f"₹{t1_premium:,.2f} (+{t1_pct:.0f}%)",
            "target_2": f"₹{t2_premium:,.2f}",
            "target_moonshot": f"₹{t3_premium:,.2f}",
            "stop_loss": f"₹{sl_premium:,.2f}",
            "risk_reward": rr_str,
            "profit_rule": (
                f"Book 50% at T1 (₹{t1_premium:,.2f}), move SL to cost, trail on T2 (₹{t2_premium:,.2f})."
            ),
            "fast_scalp": (
                opt_plan.get("fast_scalp")
                if (opt_plan and opt_plan.get("fast_scalp"))
                else {
                    "scalp_target_premium": round(opt_ltp * 1.18, 2),
                    "scalp_target_pct": 18.0,
                    "scalp_target_eta": "10m–15m",
                    "scalp_profit_rule": f"Book 70% at ₹{round(opt_ltp * 1.18, 2):,.2f} (+18%), move SL to Cost, or exit on first 5m red candle.",
                    "time_stop_mins": 20,
                    "time_stop_rule": "If trade active 20m with < +5% gain, exit at CMP/Scratch to avoid theta decay.",
                }
            ),
            "preferred_vehicle": hedge_plan.get("preferred_vehicle")
            if hedge_plan
            else "NAKED_OPTION_OR_SPREAD",
            "hedge_plan": hedge_plan,
            "velocity_regime": vel_regime,
            "velocity_score": vel_score,
            "structural_signals": signals,
            "market_status": mkt_status,
            "lot_size": lot_sz,
            "option_plan": {
                "contract_symbol": contract_sym,
                "strike": strike,
                "option_type": "CE",
                "expiry_date": exp_date,
                "entry_premium": opt_ltp,
                "sl_premium": sl_premium,
                "t1_premium": t1_premium,
                "t2_premium": t2_premium,
                "lot_size": lot_sz,
            },
        },
    )

    return [alert]
