"""
engine/detectors/index_put_setup.py
─────────────────────────────────────
SMC-Driven Bearish Index Options Detector (Fix 8).

Catches PUT entry opportunities that the OI-centric Gamma Blast detector misses because:
  - Spot may be slightly above VWAP at entry (supply zone rejection before breakdown)
  - OI hasn't unwound yet (fresh accumulation, not shedding)
  - Trade-plan asymmetry check rejects the setup (calibrated for equity longs, not index reversal)

Institutional Setups Detected:
  1. PDH_SUPPLY_REJECTION  — Spot sweeps previous day high + immediate wick rejection (supply OB)
  2. VWAP_REJECTION         — Spot fails VWAP retest from below (VWAP-as-resistance flip)
  3. SUPPLY_ZONE_SWEEP      — Intraday high sweep beyond key resistance with reversal candle
  4. BEARISH_OB_CONFLUENCE  — Put volume surge at a known bearish order block zone
  5. DOUBLE_TOP_BREAKDOWN   — Two equal intraday highs + volume expansion on second rejection

All signals produce a GAMMA_BLAST-compatible AutoAlert (BEARISH direction) so they flow
naturally through the existing alert engine pipeline, deduplication, and Telegram templates.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from engine.alert_model import AutoAlert
from engine.alert_expiry import classify_expiry_type

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

# Index universe for this detector
_INDEX_SYMBOLS = frozenset({"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"})

# Setup type → headline icon map
_SETUP_ICONS = {
    "PDH_SUPPLY_REJECTION": "🔴",
    "VWAP_REJECTION": "🔴",
    "SUPPLY_ZONE_SWEEP": "⚡",
    "BEARISH_OB_CONFLUENCE": "🎯",
    "DOUBLE_TOP_BREAKDOWN": "🔴",
    "DAY_LOW_BREAKDOWN": "📉",
}


def detect_index_put_setup(
    underlying: str,
    spot: float,
    chain: list[Any],
    vwap: Optional[float] = None,
    day_high: Optional[float] = None,
    day_low: Optional[float] = None,
    prev_day_high: Optional[float] = None,
    prev_day_low: Optional[float] = None,
    prev_week_high: Optional[float] = None,
    ohlcv_5m: Optional[Any] = None,  # pandas DataFrame, 5-minute bars
) -> list[AutoAlert]:
    """
    Scans for institutional PUT entry setups on index options using SMC price action signals.

    Returns AutoAlert objects with alert_type="GAMMA_BLAST", direction="BEARISH" so they
    integrate transparently with the existing alert pipeline, templates, and deduplication.

    Args:
        underlying:    Index symbol (e.g. "NIFTY", "BANKNIFTY").
        spot:          Current spot price.
        chain:         Options chain contracts (list of contract objects).
        vwap:          Session VWAP for the underlying.
        day_high:      Intraday high so far.
        day_low:       Intraday low so far.
        prev_day_high: Previous session's high (PDH — key supply level).
        prev_day_low:  Previous session's low (PDL — key demand level).
        prev_week_high: Previous week's high (PWH — weekly supply level).
        ohlcv_5m:      5-minute OHLCV DataFrame for structural analysis.
    """
    clean_sym = (
        underlying.upper().replace(".NS", "").replace("NSE:", "").replace("NFO:", "").strip()
    )
    if clean_sym not in _INDEX_SYMBOLS or spot <= 0:
        return []
    if not chain:
        return []

    now_dt = datetime.now(IST)
    now_iso = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")
    is_bse = clean_sym in ("SENSEX", "BANKEX")
    opt_exchange = "BFO" if is_bse else "NFO"
    effective_vwap = vwap if (vwap and vwap > 0) else spot

    # ── Resolve lot size ─────────────────────────────────────────
    try:
        from engine.position_sizer import get_lot_size

        lot_sz = get_lot_size(underlying) or 1
    except Exception:
        lot_sz = 1

    # ── Collect PE contracts within ATM band (within 1.2% of spot) ─
    if clean_sym in ("SENSEX", "BANKEX"):
        min_oi, min_vol = 300, 300
    elif clean_sym == "MIDCPNIFTY":
        min_oi, min_vol = 800, 400
    elif clean_sym == "FINNIFTY":
        min_oi, min_vol = 2000, 800
    else:
        min_oi, min_vol = 5000, 1000

    pe_contracts = [
        c
        for c in chain
        if getattr(c, "option_type", "") == "PE"
        and abs(getattr(c, "strike", 0.0) - spot) / max(1.0, spot) <= 0.012
        and getattr(c, "last_price", 0.0) >= 5.0
        and getattr(c, "volume", 0) >= min_vol
        and getattr(c, "oi", 0) >= min_oi
    ]
    if not pe_contracts:
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

    pe_contracts.sort(key=_contract_score, reverse=True)

    best_cand_pe = pe_contracts[0]
    cand_pe_pchange = float(getattr(best_cand_pe, "pchange", 0.0) or 0.0)
    cand_pe_vol = getattr(best_cand_pe, "volume", 0)
    cand_pe_oi = getattr(best_cand_pe, "oi", 0)
    cand_pe_vol_oi = round(cand_pe_vol / max(1, cand_pe_oi), 2)
    is_breakdown_momentum = cand_pe_pchange >= 8.0 or cand_pe_vol_oi >= 1.5

    # ── Opposing Demand Barrier Check (Headroom Sanity) ─────────
    # If spot is right above Previous Day Low or Day Low,
    # buying PE collides directly into underneath demand support UNLESS breaking down with momentum.
    if prev_day_low and spot > prev_day_low:
        pdl_headroom_pct = (spot - prev_day_low) / spot * 100.0
        if pdl_headroom_pct < 0.20 and not is_breakdown_momentum:
            logger.debug(
                f"[IndexPutSetup] Suppressed PE: Spot ₹{spot:,.1f} is within {pdl_headroom_pct:.2f}% of PDL ₹{prev_day_low:,.1f} (Opposing Demand Collision)"
            )
            return []

    if day_low and spot > day_low and day_high and ((day_high - day_low) / max(1.0, spot)) >= 0.003:
        dl_headroom_pct = (spot - day_low) / spot * 100.0
        if dl_headroom_pct < 0.15 and not is_breakdown_momentum:
            logger.debug(
                f"[IndexPutSetup] Suppressed PE: Spot ₹{spot:,.1f} is within {dl_headroom_pct:.2f}% of Day Low ₹{day_low:,.1f} (Headroom Truncated)"
            )
            return []

    # ── VWAP Overextension & Capitulation Filter ─────────────────
    # If spot has already dumped > 0.65% below VWAP, entering at market is a FOMO exhaustion trap
    if effective_vwap > 0 and spot < effective_vwap:
        spot_vwap_ext = (effective_vwap - spot) / effective_vwap * 100.0
        if spot_vwap_ext > 0.65:
            logger.debug(
                f"[IndexPutSetup] Suppressed PE: Spot extended -{spot_vwap_ext:.2f}% below VWAP (>0.65% capitulation threshold)"
            )
            return []

    # ── Structural Signal Detection ───────────────────────────────
    signals: list[str] = []
    signal_tags: dict[str, Any] = {}

    # 1. PDH Supply Rejection
    # Spot came within 0.25% of prev_day_high and is now pulling back
    if prev_day_high and prev_day_high > 0:
        pdh_proximity_pct = ((day_high or spot) - prev_day_high) / prev_day_high * 100
        spot_retreat_from_high = (
            ((day_high or spot) - spot) / max(1.0, spot) * 100 if day_high else 0.0
        )
        if -0.1 <= pdh_proximity_pct <= 0.5 and spot_retreat_from_high >= 0.1:
            signals.append("PDH_SUPPLY_REJECTION")
            signal_tags["pdh_supply_rejection"] = {
                "prev_day_high": prev_day_high,
                "day_high": day_high,
                "pdh_proximity_pct": round(pdh_proximity_pct, 3),
                "retreat_pct": round(spot_retreat_from_high, 3),
            }

    # 2. PWH Supply Rejection (Previous Week High)
    if prev_week_high and prev_week_high > 0 and "PDH_SUPPLY_REJECTION" not in signals:
        pwh_proximity_pct = ((day_high or spot) - prev_week_high) / prev_week_high * 100
        spot_retreat_from_high = (
            ((day_high or spot) - spot) / max(1.0, spot) * 100 if day_high else 0.0
        )
        if -0.15 <= pwh_proximity_pct <= 0.4 and spot_retreat_from_high >= 0.12:
            signals.append("PDH_SUPPLY_REJECTION")  # reuse the same type; tagged differently
            signal_tags["pdh_supply_rejection"] = {
                "level_type": "PWH",
                "prev_week_high": prev_week_high,
                "day_high": day_high,
                "pwh_proximity_pct": round(pwh_proximity_pct, 3),
                "retreat_pct": round(spot_retreat_from_high, 3),
            }

    # 3. VWAP Failure Retest
    # Spot tagged VWAP from below, failed to close above, now below VWAP
    if effective_vwap > 0 and spot < effective_vwap:
        vwap_fail_pct = (effective_vwap - spot) / effective_vwap * 100
        day_high_vs_vwap = (
            ((day_high or spot) - effective_vwap) / effective_vwap * 100 if day_high else 0.0
        )
        # Day high must have been at or above VWAP (touched it) but spot now below (failed retest)
        if day_high_vs_vwap >= -0.1 and vwap_fail_pct >= 0.05:
            signals.append("VWAP_REJECTION")
            signal_tags["vwap_rejection"] = {
                "vwap": effective_vwap,
                "spot": spot,
                "vwap_fail_pct": round(vwap_fail_pct, 3),
                "day_high": day_high,
                "day_high_vs_vwap_pct": round(day_high_vs_vwap, 3),
            }

    # 4. Intraday Supply Zone Sweep
    # Spot's intraday high exceeded the opening range high + 0.3% and has since pulled back
    if ohlcv_5m is not None:
        try:
            import pandas as pd  # noqa: F401 — runtime only

            if hasattr(ohlcv_5m, "iloc") and len(ohlcv_5m) >= 8:
                col_h = "high" if "high" in ohlcv_5m.columns else "High"
                col_l = "low" if "low" in ohlcv_5m.columns else "Low"
                col_c = "close" if "close" in ohlcv_5m.columns else "Close"
                col_v = "volume" if "volume" in ohlcv_5m.columns else "Volume"

                # Opening range = first 4 bars (09:15 – 09:35 IST)
                or_high = float(ohlcv_5m[col_h].iloc[:4].max())
                last_bar = ohlcv_5m.iloc[-1]
                last_bar_high = float(last_bar[col_h])
                last_bar_close = float(last_bar[col_c])
                last_bar_vol = float(last_bar[col_v])
                avg_vol = float(ohlcv_5m[col_v].iloc[:-1].mean())

                supply_sweep_pct = (last_bar_high - or_high) / max(1.0, or_high) * 100
                wick_pct = (
                    (last_bar_high - last_bar_close)
                    / max(0.1, last_bar_high - float(ohlcv_5m[col_l].iloc[-1]))
                    * 100
                )
                rvol = last_bar_vol / max(1.0, avg_vol)

                # Sweep: high exceeded OR high by 0.3%+, closed back below (wick >= 40%), RVOL >= 1.3x
                if supply_sweep_pct >= 0.30 and wick_pct >= 40.0 and rvol >= 1.3:
                    signals.append("SUPPLY_ZONE_SWEEP")
                    signal_tags["supply_zone_sweep"] = {
                        "opening_range_high": round(or_high, 2),
                        "last_bar_high": round(last_bar_high, 2),
                        "supply_sweep_pct": round(supply_sweep_pct, 3),
                        "wick_pct": round(wick_pct, 1),
                        "rvol": round(rvol, 2),
                    }

                # 5. Double Top Detection
                # Check if the last 3 peaks show two approximately equal highs with a dip in between
                if len(ohlcv_5m) >= 15:
                    rolling_highs = ohlcv_5m[col_h].values
                    peaks = []
                    for i in range(2, len(rolling_highs) - 1):
                        if (
                            rolling_highs[i] > rolling_highs[i - 1]
                            and rolling_highs[i] > rolling_highs[i + 1]
                        ):
                            peaks.append((i, rolling_highs[i]))
                    if len(peaks) >= 2:
                        # Compare last two peaks
                        p1_idx, p1_val = peaks[-2]
                        p2_idx, p2_val = peaks[-1]
                        peak_diff_pct = abs(p1_val - p2_val) / max(1.0, p1_val) * 100
                        # Volume on second peak should be lower (distribution) or current bar high-volume rejection
                        vol_at_p2 = float(ohlcv_5m[col_v].iloc[p2_idx])
                        vol_at_p1 = float(ohlcv_5m[col_v].iloc[p1_idx])
                        if peak_diff_pct <= 0.25 and spot < p2_val * 0.998:
                            signals.append("DOUBLE_TOP_BREAKDOWN")
                            signal_tags["double_top"] = {
                                "peak_1": round(p1_val, 2),
                                "peak_2": round(p2_val, 2),
                                "peak_diff_pct": round(peak_diff_pct, 3),
                                "current_spot": spot,
                                "vol_ratio_p2_vs_p1": round(vol_at_p2 / max(1.0, vol_at_p1), 2),
                            }
        except Exception as e_ohlcv:
            logger.debug(f"[IndexPutSetup] OHLCV analysis error for {underlying}: {e_ohlcv}")

    # 6. Day Low Breakdown (Bearish Continuation / Range Expansion)
    # When spot is testing or breaking down through session low with VWAP weakness and PE momentum
    if day_low and day_low > 0 and "DAY_LOW_BREAKDOWN" not in signals:
        dl_dist_pct = (day_low - spot) / day_low * 100.0
        # Within 0.15% above day low, or broke down below day low up to 0.50%
        if -0.15 <= dl_dist_pct <= 0.50 and (
            spot <= (effective_vwap * 1.002) if effective_vwap > 0 else True
        ):
            if is_breakdown_momentum or (ohlcv_5m is not None and len(ohlcv_5m) >= 3):
                signals.append("DAY_LOW_BREAKDOWN")
                signal_tags["day_low_breakdown"] = {
                    "day_low": day_low,
                    "spot": spot,
                    "dl_dist_pct": round(dl_dist_pct, 3),
                    "pe_pchange": cand_pe_pchange,
                    "vol_oi": cand_pe_vol_oi,
                }

    if not signals:
        return []

    # ── Select Best PE Contract ───────────────────────────────────
    best_pe = pe_contracts[0]
    strike = float(getattr(best_pe, "strike", spot))
    opt_ltp = float(getattr(best_pe, "last_price", 0.0) or 0.0)
    contract_sym = getattr(best_pe, "symbol", f"{clean_sym}{int(strike)}PE")
    exp_date = getattr(best_pe, "expiry", None)
    oi = getattr(best_pe, "oi", 0)
    oi_change = getattr(best_pe, "oi_change", 0)
    volume = getattr(best_pe, "volume", 0)
    vol_oi_ratio = round(volume / max(1, oi), 2)
    pchange = float(getattr(best_pe, "pchange", 0.0) or 0.0)
    exp_type = classify_expiry_type(exp_date, underlying) if exp_date else "WEEKLY"

    # ── Confidence Score ─────────────────────────────────────────
    base_confidence = 68
    signal_bonuses = {
        "PDH_SUPPLY_REJECTION": 14,
        "VWAP_REJECTION": 10,
        "SUPPLY_ZONE_SWEEP": 8,
        "BEARISH_OB_CONFLUENCE": 10,
        "DOUBLE_TOP_BREAKDOWN": 8,
        "DAY_LOW_BREAKDOWN": 12,
    }
    confidence = base_confidence
    for sig in signals:
        confidence += signal_bonuses.get(sig, 5)
    # Vol/OI bonus
    confidence += min(8, int(vol_oi_ratio * 3))
    # Premium expansion bonus
    if pchange >= 10.0:
        confidence += 6
    confidence = min(94, confidence)

    # Determine stage: IGNITED if premium is already expanding strongly, else EARLY_WARNING
    stage = "IGNITED" if (pchange >= 8.0 or vol_oi_ratio >= 1.5) else "EARLY_WARNING"

    # ── Trade Plan ───────────────────────────────────────────────
    try:
        from engine.trade_plan import calculate_option_execution_plan, get_market_status
        from engine.position_sizer import get_lot_size as _gls

        lot_sz = _gls(underlying) or lot_sz
        opt_plan = (
            calculate_option_execution_plan(
                trade_plan=None,
                option_type="PE",
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
    sl_pct = opt_plan.get("sl_pct", -20.0) if opt_plan else -20.0

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
    icon = _SETUP_ICONS.get(primary_signal, "🔴")
    signal_label = primary_signal.replace("_", " ")

    if "PDH_SUPPLY_REJECTION" in signals:
        level_type = signal_tags.get("pdh_supply_rejection", {}).get("level_type", "PDH")
        headline = (
            f"{vel_badge}{icon} SMC {level_type} SUPPLY REJECTION: {clean_sym} {int(strike)} PE"
        )
        struct_detail = signal_tags["pdh_supply_rejection"]
        ref_level = struct_detail.get("prev_day_high") or struct_detail.get("prev_week_high", 0.0)
        retreat_pct = struct_detail.get("retreat_pct", 0.0)
        summary = (
            f"Spot swept {level_type} (₹{ref_level:,.1f}) and rejected with a {retreat_pct:.2f}% wick \u2014 "
            f"institutional supply OB confirmed. Put volume surging ({volume:,} contracts, {vol_oi_ratio:.1f}x Vol/OI). "
            f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{sl_premium:,.1f} | T1: ₹{t1_premium:,.1f} (+{t1_pct:.0f}%)."
        )
    elif "VWAP_REJECTION" in signals:
        vwap_fail = signal_tags.get("vwap_rejection", {})
        headline = f"{icon} VWAP REJECTION PUT SETUP: {clean_sym} {int(strike)} PE"
        summary = (
            f"Spot failed VWAP (₹{effective_vwap:,.1f}) retest — VWAP now acting as resistance. "
            f"Spot {vwap_fail.get('vwap_fail_pct', 0):.2f}% below VWAP after reversal. "
            f"Put volume active ({volume:,} contracts, {vol_oi_ratio:.1f}x). "
            f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{sl_premium:,.1f} | T1: ₹{t1_premium:,.1f} (+{t1_pct:.0f}%)."
        )
    elif "SUPPLY_ZONE_SWEEP" in signals:
        sweep = signal_tags.get("supply_zone_sweep", {})
        headline = f"{icon} INTRADAY SUPPLY SWEEP: {clean_sym} {int(strike)} PE"
        summary = (
            f"Spot swept opening range high (₹{sweep.get('opening_range_high', 0):,.1f}) by "
            f"{sweep.get('supply_sweep_pct', 0):.2f}% — {sweep.get('wick_pct', 0):.0f}% wick rejection "
            f"(RVOL {sweep.get('rvol', 0):.1f}x). Institutional supply zone confirmed. "
            f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{sl_premium:,.1f} | T1: ₹{t1_premium:,.1f} (+{t1_pct:.0f}%)."
        )
    elif "DOUBLE_TOP_BREAKDOWN" in signals:
        dt = signal_tags.get("double_top", {})
        headline = f"{icon} DOUBLE TOP BREAKDOWN: {clean_sym} {int(strike)} PE"
        summary = (
            f"Two equal highs (₹{dt.get('peak_1', 0):,.1f} / ₹{dt.get('peak_2', 0):,.1f}, "
            f"{dt.get('peak_diff_pct', 0):.2f}% apart) — spot now breaking below neckline. "
            f"Put momentum building ({volume:,} contracts, {vol_oi_ratio:.1f}x Vol/OI). "
            f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{sl_premium:,.1f} ({sl_pct:.0f}%) | T1: ₹{t1_premium:,.1f} (+{t1_pct:.0f}%)."
        )
    elif "DAY_LOW_BREAKDOWN" in signals:
        dlb = signal_tags.get("day_low_breakdown", {})
        headline = f"📉 DAY LOW BREAKDOWN: {clean_sym} {int(strike)} PE"
        summary = (
            f"Spot (₹{spot:,.1f}) breaking down through Session Low (₹{dlb.get('day_low', 0):,.1f}) with bearish liquidation. "
            f"Spot holding below VWAP (₹{effective_vwap:,.1f}) with PE volume expansion ({volume:,} contracts, {vol_oi_ratio:.1f}x Vol/OI, +{pchange:.1f}%). "
            f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{sl_premium:,.1f} ({sl_pct:.0f}%) | T1: ₹{t1_premium:,.1f} (+{t1_pct:.0f}%)."
        )
    else:
        headline = f"{icon} SMC BEARISH SETUP: {clean_sym} {int(strike)} PE ({signal_label})"
        summary = (
            f"Structural bearish signal detected ({', '.join(signals)}). "
            f"Put volume: {volume:,} contracts ({vol_oi_ratio:.1f}x Vol/OI). "
            f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{sl_premium:,.1f} ({sl_pct:.0f}%) | T1: ₹{t1_premium:,.1f} (+{t1_pct:.0f}%)."
        )

    # ── Liquidity Audit ─────────────────────────────────────────
    try:
        from market.options import audit_option_liquidity

        liq_audit = audit_option_liquidity(best_pe, underlying=underlying, lot_size=lot_sz)
    except Exception:
        liq_audit = {"liquidity_status": "UNKNOWN", "bid_ask_spread_pct": 0.0}

    is_authentic = bool(opt_ltp and opt_ltp > 0.0)
    alert_env = "LIVE" if is_authentic else "TEST"

    # ── Optimal Trade Entry (OTE) & No-Chase Guard ───────────────
    entry_min = round(max(0.5, opt_ltp * 0.94), 1) if opt_ltp > 0 else spot
    entry_max = round(opt_ltp * 1.02, 1) if opt_ltp > 0 else spot
    entry_range_str = f"₹{entry_min:,.1f} – ₹{entry_max:,.1f}"
    no_chase_lvl = round(opt_ltp * 1.04, 1) if opt_ltp > 0 else round(spot * 0.996, 1)

    alert = AutoAlert(
        alert_id=f"aa-ips-pe-{clean_sym}-{int(strike)}-{uuid.uuid4().hex[:6]}",
        alert_type="GAMMA_BLAST",
        stage=stage,
        symbol=clean_sym,
        exchange=opt_exchange,
        direction="BEARISH",
        headline=headline,
        summary=f"{summary} | OTE Entry: {entry_range_str} | No Chase > ₹{no_chase_lvl}",
        ltp=opt_ltp or spot,
        trigger_level=opt_ltp if (opt_ltp and opt_ltp > 0) else strike,
        target_level=t1_premium,
        stop_loss=sl_premium,
        no_chase_boundary=no_chase_lvl,
        strike=strike,
        option_type="PE",
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
            # CHoCH / MSS tags for whiplash guard unlock (PDH rejection IS a structural reversal)
            "choch": "PDH_SUPPLY_REJECTION" in signals,
            "mss": "PDH_SUPPLY_REJECTION" in signals,
            "pdh_sweep": "PDH_SUPPLY_REJECTION" in signals,
            "pdl_sweep": False,
            "day_high": day_high,
            "day_low": day_low,
            "prev_day_high": prev_day_high,
            "prev_day_low": prev_day_low,
            "prev_week_high": prev_week_high,
            "detector": "INDEX_PUT_SETUP",
        },
        actionable_plan={
            "action": "BUY PE",
            "contract": contract_sym,
            "instrument": contract_sym,
            "instrument_type": "OPTION",
            "strike": strike,
            "option_type": "PE",
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
                    "scalp_profit_rule": f"Book 70% at ₹{round(opt_ltp * 1.18, 2):,.2f} (+18%), move SL to Cost, or exit on first 5m green candle.",
                    "time_stop_mins": 20,
                    "time_stop_rule": "If trade active 20m with < +5% gain, exit at CMP/Scratch to avoid theta decay.",
                }
            ),
            "velocity_regime": vel_regime,
            "velocity_score": vel_score,
            "structural_signals": signals,
            "market_status": mkt_status,
            "lot_size": lot_sz,
            "option_plan": {
                "contract_symbol": contract_sym,
                "strike": strike,
                "option_type": "PE",
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
