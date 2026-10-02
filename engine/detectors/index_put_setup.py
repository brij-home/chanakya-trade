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
import os
from datetime import datetime, time as dtime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from engine.alert_identity import generate_alert_id, canonical_alert_symbol
from engine.alert_model import AutoAlert
from engine.alert_expiry import classify_expiry_type

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

# Index universe for this detector
_INDEX_SYMBOLS = frozenset({"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"})

# Setup type → headline icon map
_SETUP_ICONS = {
    "PDH_SUPPLY_REJECTION": "🔴",
    "DAY_HIGH_SUPPLY_REJECTION": "🔴",
    "FAILED_DAY_HIGH_BREAKOUT": "⚡",
    "INTRADAY_CAPITULATION_TOP": "⚡",
    "DISTRIBUTION_TOP": "🔥",  # Mid-session VWAP overextension + session-high rejection
    "VWAP_REJECTION": "🔴",
    "VWAP_BREAKDOWN": "📉",
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
    ref_time: Optional[datetime] = None,
    ignore_time_gate: bool = False,
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
        ref_time:      Reference datetime for testing or historical audit.
        ignore_time_gate: If True, bypasses 09:25 IST stabilization gate for unit testing.
    """
    clean_sym = canonical_alert_symbol(underlying)
    if clean_sym not in _INDEX_SYMBOLS or spot <= 0:
        return []
    if not chain:
        return []

    # ── Market Breadth Gate ─────────────────────────────────────────
    # Index put setups into broad market rallies have negative statistical expectancy.
    # PRICE-ACTION ESCAPE: If spot is already -0.5% from session open, the index has
    # voted with price — A/D breadth lags by 10-15 minutes. Skip breadth gate in that case.
    is_test_runner = (
        ("PYTEST_CURRENT_TEST" in os.environ)
        or (os.environ.get("CHANAKYA_TESTING") == "1")
        or (os.environ.get("DEPLOY_MODE") == "test")
    )
    _day_open_price: Optional[float] = None
    if ohlcv_5m is not None:
        try:
            if hasattr(ohlcv_5m, "iloc") and len(ohlcv_5m) >= 1:
                col_o = "open" if "open" in ohlcv_5m.columns else "Open"
                _day_open_price = float(ohlcv_5m[col_o].iloc[0])
        except Exception:
            pass
    _spot_below_open_escape = bool(
        _day_open_price
        and _day_open_price > 0
        and spot < _day_open_price * 0.995  # spot already -0.5% from open: price action voted
    )
    _retreat_from_high_pct = (
        ((day_high - spot) / max(1.0, day_high)) * 100.0 if (day_high and day_high > 0) else 0.0
    )
    _min_top_retreat = (
        0.50 if clean_sym in ("BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "BANKEX") else 0.30
    )
    _eff_vwap = vwap if (vwap and vwap > 0) else spot
    _is_v_top_escape = bool(
        day_high
        and day_high > 0
        and _retreat_from_high_pct >= _min_top_retreat
        and (_eff_vwap > 0 and (day_high - _eff_vwap) / _eff_vwap * 100.0 >= 0.20)
    )
    _breadth_bypassed = _spot_below_open_escape or _is_v_top_escape

    if not is_test_runner or os.environ.get("ENFORCE_TEST_BREADTH") == "1":
        if not _breadth_bypassed:
            try:
                from market.sentiment import get_market_breadth

                mb = get_market_breadth()
                if mb and mb.verdict != "UNAVAILABLE" and getattr(mb, "ad_ratio", 0.0) > 0:
                    if (
                        mb.verdict == "BROAD_RALLY"
                        or mb.ad_ratio > 1.80
                        or (mb.advances >= 2.0 * max(1, mb.declines))
                    ):
                        logger.info(
                            f"[IndexPutSetup] Suppressed PE setup on {clean_sym}: Market Breadth Rally active "
                            f"(Adv: {mb.advances} / Dec: {mb.declines}, A/D {mb.ad_ratio:.2f}). Disallow put setups in bullish tide."
                        )
                        return []
            except Exception as e_mb:
                logger.debug(f"[IndexPutSetup] Breadth check bypassed: {e_mb}")
        else:
            if _spot_below_open_escape:
                escape_msg = f"spot ₹{spot:,.1f} already {((spot / _day_open_price - 1) * 100):.2f}% from open ₹{_day_open_price:,.1f}"
            else:
                escape_msg = f"V-Top / Climax exhaustion retreat (-{_retreat_from_high_pct:.2f}% from Day High ₹{day_high:,.1f}, VWAP overextension)"
            logger.debug(
                f"[IndexPutSetup] Breadth gate BYPASSED for {clean_sym}: {escape_msg} — price action overrides A/D lag."
            )

    now_dt = ref_time or datetime.now(IST)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=IST)
    else:
        now_dt = now_dt.astimezone(IST)
    now_iso = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")
    curr_time = now_dt.time()

    # ── 09:25 IST Market Stabilization Gate ─────────────────────────
    # First 10 minutes (09:15 - 09:25 IST) are noisy opening auction price discovery.
    # Multi-candle structural setups (trend pullbacks, double tops, day-low breakdowns)
    # require at least 2 completed 5m bars and cannot form before 09:25 IST.
    # EXCEPTION: Opening Range Displacement (ORD) — If spot has aggressively sliced
    # through Previous Day Low (PDL) by >= 0.20% and is down >= 0.50% from open,
    # institutional liquidation is already underway. Bypass opening buffer so early drops are caught.
    _is_opening_displacement = bool(
        prev_day_low
        and prev_day_low > 0
        and spot < prev_day_low * 0.998
        and _spot_below_open_escape
    )
    is_opening_buffer = (
        (curr_time < dtime(9, 25))
        and not ignore_time_gate
        and not _is_opening_displacement
        and (not is_test_runner or ref_time is not None)
    )
    if is_opening_buffer:
        logger.info(
            f"[IndexPutSetup] Suppressed PE setup on {clean_sym} at {curr_time.strftime('%H:%M:%S')}: "
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

    active_ohlcv = df_today_5m if df_today_5m is not None else ohlcv_5m
    try:
        from engine.index_velocity import calculate_roc_momentum, calculate_premium_velocity

        roc_metric = calculate_roc_momentum(active_ohlcv, symbol=clean_sym)
    except Exception:
        from engine.index_velocity import calculate_roc_momentum, calculate_premium_velocity

        roc_metric = calculate_roc_momentum(None, symbol=clean_sym)

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

    # Fix #6 (P1): Time-of-day OI relaxation — opening-range put setups
    # Before 09:45 IST, PE OI hasn't built. Valid early-session supply rejections
    # (PDH_SUPPLY_REJECTION, opening ORD) get dropped by the static OI gate.
    _session_minute = (curr_time.hour * 60 + curr_time.minute) - (9 * 60 + 15)
    if _session_minute <= 20:  # Before 09:35 IST: 40% threshold
        min_oi = max(50, int(min_oi * 0.40))
        min_vol = max(50, int(min_vol * 0.40))
    elif _session_minute <= 30:  # 09:35–09:45 IST: 60% threshold
        min_oi = max(100, int(min_oi * 0.60))
        min_vol = max(100, int(min_vol * 0.60))
    # After 09:45 IST: full standard thresholds apply

    min_contract_prem = 2.0 if clean_sym in ("MIDCPNIFTY", "FINNIFTY") else 3.5
    pe_contracts = [
        c
        for c in chain
        if getattr(c, "option_type", "") == "PE"
        and abs(getattr(c, "strike", 0.0) - spot) / max(1.0, spot) <= 0.012
        and getattr(c, "last_price", 0.0) >= min_contract_prem
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
        vol_oi = min(4.0, vol / max(1, oi))
        dist_pct = abs(float(getattr(c, "strike", 0.0) or 0.0) - spot) / max(1.0, spot)
        # BSE indices (SENSEX/BANKEX) trade at much higher absolute levels and have higher absolute premiums
        if clean_sym in ("SENSEX", "BANKEX"):
            ideal_prem = 250.0
        elif clean_sym in ("MIDCPNIFTY", "FINNIFTY"):
            ideal_prem = 40.0
        else:  # NIFTY, BANKNIFTY
            ideal_prem = 125.0
        prem_dist = abs(lp - ideal_prem) / ideal_prem if lp > 0 else 2.0
        return (vol_oi * 10.0) + (min(10.0, vol / 500.0)) - (dist_pct * 800.0) - (prem_dist * 5.0)

    pe_contracts.sort(key=_contract_score, reverse=True)

    best_cand_pe = pe_contracts[0]
    cand_pe_pchange = float(getattr(best_cand_pe, "pchange", 0.0) or 0.0)
    cand_pe_vol = getattr(best_cand_pe, "volume", 0)
    cand_pe_oi = getattr(best_cand_pe, "oi", 0)
    cand_pe_vol_oi = round(cand_pe_vol / max(1, cand_pe_oi), 2)
    cand_pe_oi_change = int(getattr(best_cand_pe, "oi_change", 0) or 0)
    cand_pe_oi_roc = (
        round((cand_pe_oi_change / max(1, cand_pe_oi - cand_pe_oi_change)) * 100.0, 1)
        if cand_pe_oi > cand_pe_oi_change and cand_pe_oi_change > 0
        else 0.0
    )
    is_breakdown_momentum = (
        cand_pe_pchange >= 15.0 and cand_pe_vol_oi >= 1.2
    ) or cand_pe_vol_oi >= 2.0
    is_explosive_momentum = cand_pe_vol_oi >= 3.0 or (
        cand_pe_pchange >= 25.0 and cand_pe_vol_oi >= 2.0
    )

    # ── Optimization 1: Intraday Put-Call Ratio (PCR) Confluence Gate ───
    # PCR > 1.45 ONLY indicates a floor when PUT WRITERS ARE ADDING (pe_oi_change > 0).
    # If PE OI is unwinding (pe_oi_change < 0) with high PCR, that is a breakdown signal
    # — the floor is collapsing as writers cover. Do NOT veto in that case.
    ce_oi_total = sum(
        int(getattr(c, "oi", 0) or 0) for c in chain if getattr(c, "option_type", "") == "CE"
    )
    pe_oi_total = sum(
        int(getattr(c, "oi", 0) or 0) for c in chain if getattr(c, "option_type", "") == "PE"
    )
    pe_oi_change_sum = sum(
        int(getattr(c, "oi_change", 0) or 0) for c in chain if getattr(c, "option_type", "") == "PE"
    )
    chain_pcr = (
        round(pe_oi_total / max(1, ce_oi_total), 2)
        if (ce_oi_total > 5000 and pe_oi_total > 5000)
        else None
    )

    # Veto only when: PCR > 1.45 AND writers are actively adding new puts (floor building)
    # NOT when writers are unwinding (breakdown acceleration)
    _pcr_writers_adding = pe_oi_change_sum > 0
    if chain_pcr is not None and chain_pcr > 1.45 and _pcr_writers_adding:
        logger.info(
            f"[IndexPutSetup] Suppressed PE setup on {clean_sym}: Active Put Writing Cushion "
            f"(PCR: {chain_pcr:.2f} > 1.45, OI adding {pe_oi_change_sum:+,}). Floor-building writers resist breakdown."
        )
        return []
    elif chain_pcr is not None and chain_pcr > 1.45 and not _pcr_writers_adding:
        logger.debug(
            f"[IndexPutSetup] PCR={chain_pcr:.2f} > 1.45 but pe_oi_change={pe_oi_change_sum:+,} (unwinding) "
            f"→ NOT a floor, this is a breakdown signal. Allowing PE setup to proceed."
        )

    # ── Strike Wall Radar: Max Put OI Cushion vs Long Unwinding Flush ──
    ce_contracts_oi = [
        c
        for c in chain
        if getattr(c, "option_type", "") == "CE" and int(getattr(c, "oi", 0) or 0) > 0
    ]
    pe_contracts_oi = [
        c
        for c in chain
        if getattr(c, "option_type", "") == "PE" and int(getattr(c, "oi", 0) or 0) > 0
    ]
    max_ce_contract = (
        max(ce_contracts_oi, key=lambda c: int(getattr(c, "oi", 0) or 0))
        if ce_contracts_oi
        else None
    )
    max_pe_contract = (
        max(pe_contracts_oi, key=lambda c: int(getattr(c, "oi", 0) or 0))
        if pe_contracts_oi
        else None
    )
    max_call_oi_strike = (
        float(getattr(max_ce_contract, "strike", 0.0) or 0.0) if max_ce_contract else None
    )
    max_put_oi_strike = (
        float(getattr(max_pe_contract, "strike", 0.0) or 0.0) if max_pe_contract else None
    )
    max_ce_oi_change = int(getattr(max_ce_contract, "oi_change", 0) or 0) if max_ce_contract else 0
    max_pe_oi_change = int(getattr(max_pe_contract, "oi_change", 0) or 0) if max_pe_contract else 0

    is_put_wall_collision = False
    is_long_unwinding_flush = False
    put_wall_dist_pct = None

    if max_put_oi_strike and max_put_oi_strike > 0 and spot > 0:
        put_wall_dist_pct = round(((spot - max_put_oi_strike) / spot) * 100.0, 3)
        # Collision: Spot is within 0.15% above the Max Put OI strike and writers are actively adding
        if 0.0 < put_wall_dist_pct <= 0.15 and max_pe_oi_change > 0:
            is_put_wall_collision = True
            logger.info(
                f"[IndexPutSetup] Max Put OI Wall Collision: Spot ₹{spot:,.1f} is {put_wall_dist_pct:.2f}% "
                f"above Put Wall ₹{max_put_oi_strike:,.0f} with writers adding ({max_pe_oi_change:+,}). Mandating Bear Put Spread."
            )
        # Long Unwinding Flush: Spot has broken at or below the Max Put OI strike AND put writers are unwinding (panic covering)
        elif spot <= max_put_oi_strike and max_pe_oi_change < 0:
            is_long_unwinding_flush = True
            logger.info(
                f"[IndexPutSetup] LONG UNWINDING FLUSH: Spot ₹{spot:,.1f} broke below Max Put Wall ₹{max_put_oi_strike:,.0f} "
                f"with put writers unwinding ({max_pe_oi_change:+,})."
            )

    # ── Optimization 2: Index Heavyweight Breadth Confluence Matrix (HBCM) ──
    hw_posture: dict[str, Any] = {}
    hbcm_dict: dict[str, Any] = {}
    try:
        from engine.hbcm import evaluate_hbcm
        from market.indices import get_heavyweights_posture

        hw_posture = get_heavyweights_posture(clean_sym)
        # Pass allow_weighted_fallback when momentum is active or V-top escape is triggered so that
        # 3/5 heavyweights with >= 55% combined weight can satisfy the confluence gate on fast dump days.
        _allow_weighted = is_explosive_momentum or is_breakdown_momentum or _breadth_bypassed
        hbcm_res = evaluate_hbcm(
            clean_sym,
            "BEARISH",
            allow_weighted_fallback=_allow_weighted,
        )
        hbcm_dict = hbcm_res.to_dict()

        has_hbcm_quotes = hbcm_res.total_heavyweights > 0 and not (
            hbcm_res.summary or ""
        ).startswith("HBCM_TEST_PASSTHROUGH")
        if has_hbcm_quotes:
            if not hbcm_res.confluence_pass:
                # If market breadth bypassed via strong V-top retreat (price action voted)
                # and at least 3 heavyweights are already bearish or net heavyweights bearish:
                _v_top_hbcm_pass = _breadth_bypassed and (
                    hbcm_res.bearish_count >= 3
                    or (
                        hbcm_res.bearish_count > hbcm_res.bullish_count
                        and hbcm_res.bearish_count >= 2
                    )
                )
                # Explosive Momentum HBCM Bypass (symmetric to CE)
                # When option order flow is explosive (vol/OI >= 3.0x or PE premium +25%+), lower the bar
                # to >= 1 bearish locomotive so we catch fast flushes before 80% of move is gone.
                _explosive_momentum_hbcm_pass = (
                    is_explosive_momentum
                    and hbcm_res.bearish_count >= 1
                    and not getattr(hbcm_res, "all_bullish", False)
                )
                # ROC Breakdown Acceleration HBCM Bypass
                # Accelerating negative ROC (d²P/dt² < 0) with meaningful magnitude confirms
                # institutional liquidation. Allow PE setup if at least 1 heavy is falling and not all heavies are bullish.
                _roc_hbcm_pass = (
                    roc_metric.is_accelerating_down
                    and roc_metric.is_meaningful_down
                    and hbcm_res.bearish_count >= 1
                    and not getattr(hbcm_res, "all_bullish", False)
                )
                if not (_v_top_hbcm_pass or _explosive_momentum_hbcm_pass or _roc_hbcm_pass):
                    logger.info(
                        f"[IndexPutSetup] Suppressed PE setup on {clean_sym}: {hbcm_res.rejection_reason}"
                    )
                    return []
                else:
                    _bypass_reason = (
                        "ROC_ACCELERATION"
                        if _roc_hbcm_pass
                        else ("EXPLOSIVE_MOMENTUM" if _explosive_momentum_hbcm_pass else "V_TOP_CONFLUENCE")
                    )
                    hbcm_res.confluence_pass = True
                    hbcm_res.rejection_reason = None
                    hbcm_dict = hbcm_res.to_dict()
                    hbcm_dict["confluence_pass"] = True
                    hbcm_dict["hbcm_bypassed"] = True
                    hbcm_dict["bypass_reason"] = _bypass_reason
                    hbcm_dict["rejection_reason"] = None

                if _roc_hbcm_pass:
                    logger.info(
                        f"[IndexPutSetup] ROC ACCELERATION HBCM Bypass: PE setup on {clean_sym} allowed "
                        f"with {hbcm_res.bearish_count}/5 bearish heavyweights — "
                        f"price breakdown accelerating (ROC_1={roc_metric.roc_1:.2f}%, 3-bar={roc_metric.roc_3bar:.2f}%)."
                    )
                elif _explosive_momentum_hbcm_pass:
                    logger.info(
                        f"[IndexPutSetup] EXPLOSIVE MOMENTUM HBCM Bypass: PE setup on {clean_sym} allowed "
                        f"with {hbcm_res.bearish_count}/5 bearish heavyweights — "
                        f"option vol/OI surge confirms institutional breakdown."
                    )
                else:
                    logger.info(
                        f"[IndexPutSetup] V-Top Price Action Confluence: Allowed PE setup on {clean_sym} "
                        f"with {hbcm_res.bearish_count}/5 bearish heavyweights (V-top retreat -{_retreat_from_high_pct:.2f}% overrides lagging constituent)."
                    )
        else:
            active_hw = hw_posture.get("heavyweights", [])
            hw_total = len(active_hw)
            hw_bears = hw_posture.get("bear_count", 0)
            if hw_posture.get("all_bullish"):
                hw_tags = [f"{h['symbol']} (+{h['change_pct']:+.2f}%)" for h in active_hw]
                logger.info(
                    f"[IndexPutSetup] Suppressed PE setup on {clean_sym}: Heavyweight locomotives in structural markup "
                    f"({', '.join(hw_tags)}). Disallow put setups fighting index drivers."
                )
                return []

            _roc_hw_pass = (
                roc_metric.is_accelerating_down
                and roc_metric.is_meaningful_down
                and hw_bears >= 1
                and not hw_posture.get("all_bullish")
            )
            hw_bulls = hw_posture.get("bull_count", 0)
            if (
                hw_total >= 3
                and hw_bulls > hw_bears
                and not (is_explosive_momentum or _roc_hw_pass)
            ):
                hw_tags = [f"{h['symbol']} ({h['change_pct']:+.2f}%)" for h in active_hw]
                logger.info(
                    f"[IndexPutSetup] Suppressed PE setup on {clean_sym}: Heavyweights are net bullish "
                    f"({hw_bulls} bulls vs {hw_bears} bears: {', '.join(hw_tags)}). Disallow put setups fighting net index driver bias."
                )
                return []

            # High Conviction Invariant: Index Put requires at least 1 active heavyweight falling (bear_count >= 1)
            if hw_total > 0 and hw_bears == 0 and not (is_explosive_momentum or _roc_hw_pass):
                hw_tags = [f"{h['symbol']} ({h['change_pct']:+.2f}%)" for h in active_hw]
                logger.info(
                    f"[IndexPutSetup] Suppressed PE setup on {clean_sym}: Zero heavyweight locomotives breaking down (0/{hw_total} bearish: {', '.join(hw_tags)}). "
                    f"Disallow put setups without locomotive drag."
                )
                return []
    except Exception as e_hw:
        logger.debug(f"[IndexPutSetup] Heavyweights check bypassed: {e_hw}")

    # ── Optimization 2b: Low-VIX (< 13.0) Range-Bound Regime Filter ──
    vix_val = None
    try:
        from market.indices import get_vix

        vix_val = get_vix()
    except Exception:
        pass
    is_low_vix_range = bool(
        vix_val
        and 0 < vix_val < 13.0
        and effective_vwap > 0
        and abs((spot - effective_vwap) / effective_vwap * 100.0) < 0.35
        and not is_explosive_momentum
    )
    is_high_iv_risk = bool(vix_val is not None and vix_val >= 18.0)

    # ── Opposing Demand Barrier Check (Headroom Sanity & Bear Trap Prevention) ───
    # If spot is right above Previous Day Low or Day Low, buying PE collides directly
    # into underneath demand support UNLESS breaking down with true momentum.
    # If spot has just pierced PDL by < 0.15% without momentum, it's a high-probability Bear Trap sweep.
    if prev_day_low and prev_day_low > 0:
        if spot > prev_day_low:
            pdl_headroom_pct = (spot - prev_day_low) / spot * 100.0
            if pdl_headroom_pct < 0.25 and not is_breakdown_momentum:
                logger.debug(
                    f"[IndexPutSetup] Suppressed PE: Spot ₹{spot:,.1f} is within {pdl_headroom_pct:.2f}% of PDL ₹{prev_day_low:,.1f} (Opposing Demand Collision)"
                )
                return []
        else:
            pdl_break_pct = (prev_day_low - spot) / prev_day_low * 100.0
            if pdl_break_pct < 0.15 and not is_breakdown_momentum:
                logger.debug(
                    f"[IndexPutSetup] Suppressed PE: Spot ₹{spot:,.1f} shallow pierce of PDL ₹{prev_day_low:,.1f} ({pdl_break_pct:.2f}%) without breakdown momentum (Bear Trap Risk)"
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
    # Default: Extended > 0.65% below VWAP = FOMO exhaustion trap, skip.
    # MOMENTUM ESCAPE: On genuine institutional flushes, spot can legitimately trade
    # 1-2% below VWAP as sellers step through bids. Raise the cap dynamically:
    #   vol_oi_ratio >= 2.0x or pe_pchange >= 15% → cap 1.2% below VWAP
    #   vol_oi_ratio >= 3.0x or pe_pchange >= 25% → cap 2.0% (full flush)
    if effective_vwap > 0 and spot < effective_vwap:
        spot_vwap_ext = (effective_vwap - spot) / effective_vwap * 100.0
        _is_full_flush_ps = cand_pe_vol_oi >= 3.0 or (
            cand_pe_pchange >= 25.0
            and cand_pe_vol >= (15000 if clean_sym in ("NIFTY", "BANKNIFTY") else 3000)
        )
        _is_momentum_exp_ps = cand_pe_vol_oi >= 2.0 or (
            cand_pe_pchange >= 15.0
            and cand_pe_vol >= (8000 if clean_sym in ("NIFTY", "BANKNIFTY") else 1500)
        )
        _vwap_cap = 2.0 if _is_full_flush_ps else (1.2 if _is_momentum_exp_ps else 0.65)
        if spot_vwap_ext > _vwap_cap:
            logger.debug(
                f"[IndexPutSetup] Suppressed PE: Spot extended -{spot_vwap_ext:.2f}% below VWAP "
                f"(cap={_vwap_cap:.2f}% | flush={_is_full_flush_ps} | momentum={_is_momentum_exp_ps})"
            )
            return []

    # ── Structural Signal Detection ───────────────────────────────
    signals: list[str] = []
    signal_tags: dict[str, Any] = {
        "roc_momentum": roc_metric.to_dict(),
        "oi_roc": cand_pe_oi_roc,
    }
    if is_long_unwinding_flush:
        signals.append("LONG_UNWINDING_FLUSH")
        signal_tags["long_unwinding_flush"] = {
            "max_put_oi_strike": max_put_oi_strike,
            "max_pe_oi_change": max_pe_oi_change,
            "spot": spot,
            "put_wall_dist_pct": put_wall_dist_pct,
        }

    # 5m Trend Structure Alignment: Detect sustained bullish momentum
    is_5m_bull_trend = False
    if active_ohlcv is not None and hasattr(active_ohlcv, "iloc") and len(active_ohlcv) >= 12:
        try:
            import pandas as pd  # noqa: F401

            col_c = "close" if "close" in active_ohlcv.columns else "Close"
            closes = active_ohlcv[col_c].values
            ema9 = pd.Series(closes).ewm(span=9, adjust=False).mean().values[-1]
            ema20 = (
                pd.Series(closes).ewm(span=20, adjust=False).mean().values[-1]
                if len(closes) >= 20
                else pd.Series(closes).mean()
            )
            is_5m_bull_trend = bool(
                ema9 > (ema20 * 1.0005) and (effective_vwap > 0 and spot > effective_vwap * 1.001)
            )
        except Exception:
            pass

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

    # 2b. Day High Supply Rejection (Intraday Bull Trap / Ceiling Rejection)
    # Spot tested Day High and has now retreated from the peak
    if day_high and day_high > 0 and "PDH_SUPPLY_REJECTION" not in signals:
        dh_retreat_pct = (day_high - spot) / max(1.0, day_high) * 100.0

        # When spot is trading ABOVE session VWAP in a bullish session:
        # A tiny pause is normal trend consolidation, NOT a supply ceiling!
        # Require:
        # 1. Not in a 5m golden bull trend (EMA9 > EMA20 > VWAP) unless extreme exhaustion
        # 2. Minimum retreat >= 0.18% (40+ pts on Nifty, 100+ pts on BankNifty)
        # 3. Candlestick rejection verification: upper wick >= 38% and red/bottom close
        # 4. Put option must not be bleeding heavily (pchange >= -8.0% or vol_oi >= 1.2)
        is_above_vwap = bool(effective_vwap > 0 and spot >= effective_vwap * 1.0005)

        has_candle_rejection = True
        if active_ohlcv is not None and hasattr(active_ohlcv, "iloc") and len(active_ohlcv) >= 1:
            try:
                col_h = "high" if "high" in active_ohlcv.columns else "High"
                col_l = "low" if "low" in active_ohlcv.columns else "Low"
                col_c = "close" if "close" in active_ohlcv.columns else "Close"
                col_o = "open" if "open" in active_ohlcv.columns else "Open"
                last_b = active_ohlcv.iloc[-1]
                b_h = float(last_b[col_h])
                b_l = float(last_b[col_l])
                b_c = float(last_b[col_c])
                b_o = float(last_b[col_o])
                b_rng = max(0.1, b_h - b_l)
                u_wick_pct = (b_h - max(b_c, b_o)) / b_rng * 100.0
                has_candle_rejection = (u_wick_pct >= 38.0) or (
                    b_c < b_o and (b_h - b_c) / b_rng >= 0.50
                )
            except Exception:
                has_candle_rejection = True

        pe_receptive = (cand_pe_pchange >= -8.0) or (cand_pe_vol_oi >= 1.2) or is_breakdown_momentum

        if is_above_vwap:
            is_valid_dh_rejection = (
                (0.18 <= dh_retreat_pct <= 0.60)
                and has_candle_rejection
                and pe_receptive
                and (not is_5m_bull_trend or cand_pe_vol_oi >= 2.0)
            )
        else:
            # Below VWAP: 0.10% to 0.50% retreat is valid ceiling resistance
            is_valid_dh_rejection = (0.10 <= dh_retreat_pct <= 0.50) and pe_receptive

        if is_valid_dh_rejection:
            signals.append("DAY_HIGH_SUPPLY_REJECTION")
            signal_tags["day_high_supply_rejection"] = {
                "day_high": day_high,
                "spot": spot,
                "dh_retreat_pct": round(dh_retreat_pct, 3),
            }

    # 3. VWAP Failure Retest
    # Spot tagged VWAP from below, failed to close above, now below VWAP
    if effective_vwap > 0 and spot < effective_vwap:
        vwap_fail_pct = (effective_vwap - spot) / effective_vwap * 100
        day_high_vs_vwap = (
            ((day_high or spot) - effective_vwap) / effective_vwap * 100 if day_high else 0.0
        )
        # Day high must have been at or above VWAP (touched it) but spot now below (failed retest)
        # PROXIMITY ENVELOPE: 0.03% <= rejection <= 0.18% (for Nifty: 7 to 40 pts below VWAP).
        # Above 0.18%, price has already dumped far away from VWAP resistance and faces short-squeeze risk.
        max_rejection_envelope = (
            0.25 if clean_sym in ("BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "BANKEX") else 0.18
        )

        # Ascending Bounce Guard: If spot is bouncing up strongly from Day Low towards VWAP,
        # it is a recovery bounce / short squeeze, NOT a VWAP rejection.
        _bounce_from_dl_pct = (
            ((spot - day_low) / max(1.0, day_low) * 100.0)
            if (day_low and day_low > 0 and spot > day_low)
            else 0.0
        )
        _is_ascending_bounce_from_low = (
            _bounce_from_dl_pct >= 0.15 and _bounce_from_dl_pct >= vwap_fail_pct
        )

        # Candle Rejection Guard: Last 5m candle must show bearish posture, not strong green expansion
        _is_candle_bearish = True
        if active_ohlcv is not None and hasattr(active_ohlcv, "iloc") and len(active_ohlcv) >= 1:
            try:
                col_c = "close" if "close" in active_ohlcv.columns else "Close"
                col_o = "open" if "open" in active_ohlcv.columns else "Open"
                col_h = "high" if "high" in active_ohlcv.columns else "High"
                col_l = "low" if "low" in active_ohlcv.columns else "Low"
                _lb = active_ohlcv.iloc[-1]
                _c = float(_lb[col_c])
                _o = float(_lb[col_o])
                _h = float(_lb[col_h])
                _l = float(_lb[col_l])
                _rng = max(0.1, _h - _l)
                if _c > _o and (_h - _c) / _rng < 0.25:
                    _is_candle_bearish = False
            except Exception:
                pass

        if (
            day_high_vs_vwap >= -0.1
            and (0.03 <= vwap_fail_pct <= max_rejection_envelope)
            and not _is_ascending_bounce_from_low
            and _is_candle_bearish
        ):
            signals.append("VWAP_REJECTION")
            signal_tags["vwap_rejection"] = {
                "vwap": effective_vwap,
                "spot": spot,
                "vwap_fail_pct": round(vwap_fail_pct, 3),
                "day_high": day_high,
                "day_high_vs_vwap_pct": round(day_high_vs_vwap, 3),
            }

    # 3b. VWAP Breakdown (Institutional Transition from Bull to Bear Regime)
    # Price was trading above VWAP in the session and decisively sliced below VWAP
    # with confirmed 5m close below VWAP and receptive Put momentum.
    if (
        effective_vwap > 0
        and spot < effective_vwap
        and "VWAP_BREAKDOWN" not in signals
        and not is_opening_buffer
    ):
        vwap_bd_pct = (effective_vwap - spot) / effective_vwap * 100.0
        day_high_vs_vwap = (
            ((day_high or spot) - effective_vwap) / effective_vwap * 100.0 if day_high else 0.0
        )
        # Price was previously trading above VWAP (day high >= 0.08% above VWAP)
        was_above_vwap = day_high_vs_vwap >= 0.08

        has_bar_breakdown = True
        if active_ohlcv is not None and hasattr(active_ohlcv, "iloc") and len(active_ohlcv) >= 1:
            try:
                col_c = "close" if "close" in active_ohlcv.columns else "Close"
                col_o = "open" if "open" in active_ohlcv.columns else "Open"
                col_h = "high" if "high" in active_ohlcv.columns else "High"
                col_l = "low" if "low" in active_ohlcv.columns else "Low"
                last_b = active_ohlcv.iloc[-1]
                b_c = float(last_b[col_c])
                b_o = float(last_b[col_o])
                b_h = float(last_b[col_h])
                b_l = float(last_b[col_l])
                b_rng = max(0.1, b_h - b_l)
                has_bar_breakdown = (b_c <= effective_vwap * 1.0005) and (
                    b_c <= b_o or (b_h - b_c) / b_rng >= 0.35
                )
            except Exception:
                has_bar_breakdown = True

        pe_momentum_receptive = (
            cand_pe_vol_oi >= 1.1 or cand_pe_pchange >= 8.0 or is_breakdown_momentum
        )

        # VWAP breakdown distance cap: how far below VWAP before we stop signalling a "fresh" breakdown
        # (too extended = mean reversion risk; don't chase past the zone)
        # BSE indices (SENSEX ~73K, BANKEX ~55K) need wider caps because 0.45% = 330-250 pts, within noise.
        _vwap_bd_cap = (
            0.75
            if clean_sym in ("SENSEX", "BANKEX")
            else 0.60
            if clean_sym in ("BANKNIFTY",)
            else 0.45
        )
        if (
            0.04 <= vwap_bd_pct <= _vwap_bd_cap
            and was_above_vwap
            and has_bar_breakdown
            and pe_momentum_receptive
        ):
            signals.append("VWAP_BREAKDOWN")
            signal_tags["vwap_breakdown"] = {
                "vwap": effective_vwap,
                "spot": spot,
                "vwap_bd_pct": round(vwap_bd_pct, 3),
                "day_high": day_high,
                "day_high_vs_vwap_pct": round(day_high_vs_vwap, 3),
                "vol_oi": cand_pe_vol_oi,
                "pe_pchange": cand_pe_pchange,
            }

    # 4. Intraday Supply Zone Sweep
    # Spot's intraday high exceeded the opening range high + 0.3% and has since pulled back
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
                or_high = float(active_ohlcv[col_h].iloc[:4].max())
                last_bar = active_ohlcv.iloc[-1]
                last_bar_high = float(last_bar[col_h])
                last_bar_close = float(last_bar[col_c])
                last_bar_vol = float(last_bar[col_v])
                avg_vol = float(active_ohlcv[col_v].iloc[:-1].mean())

                supply_sweep_pct = (last_bar_high - or_high) / max(1.0, or_high) * 100
                wick_pct = (
                    (last_bar_high - last_bar_close)
                    / max(0.1, last_bar_high - float(active_ohlcv[col_l].iloc[-1]))
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
                if len(active_ohlcv) >= 15 and not is_opening_buffer:
                    rolling_highs = active_ohlcv[col_h].values
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
                        vol_at_p2 = float(active_ohlcv[col_v].iloc[p2_idx])
                        vol_at_p1 = float(active_ohlcv[col_v].iloc[p1_idx])
                        if peak_diff_pct <= 0.25 and spot < p2_val * 0.998:
                            signals.append("DOUBLE_TOP_BREAKDOWN")
                            signal_tags["double_top"] = {
                                "peak_1": round(p1_val, 2),
                                "peak_2": round(p2_val, 2),
                                "peak_diff_pct": round(peak_diff_pct, 3),
                                "current_spot": spot,
                                "vol_ratio_p2_vs_p1": round(vol_at_p2 / max(1.0, vol_at_p1), 2),
                            }

                # 6. Trend Continuation Retrace / Rejection (EMA 9/20 & VWAP Resistance Rejection)
                # Catches sustained downtrends where price retraces up into EMA/VWAP resistance and resumes down
                if (
                    len(active_ohlcv) >= 6
                    and not is_opening_buffer
                    and "TREND_PULLBACK_REJECTION" not in signals
                ):
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

                        last_h = float(highs[-1])
                        last_c = float(closes[-1])
                        last_o = float(opens[-1])
                        candle_rng = max(0.1, last_h - float(lows[-1]))

                        # Bearish moving average alignment & holding below or near VWAP
                        if ema9 <= (ema20 * 1.002) and spot <= (
                            effective_vwap * 1.003 if effective_vwap else spot * 1.01
                        ):
                            tested_ema = last_h >= (ema9 * 0.998) and last_c <= (ema9 * 1.001)
                            tested_vwap = (
                                effective_vwap > 0
                                and last_h >= (effective_vwap * 0.998)
                                and last_c <= (effective_vwap * 1.001)
                            )
                            is_bearish_candle = (last_c <= last_o) and (
                                (last_h - last_c) / candle_rng >= 0.35
                            )

                            if (tested_ema or tested_vwap) and is_bearish_candle:
                                signals.append("TREND_PULLBACK_REJECTION")
                                signal_tags["trend_pullback"] = {
                                    "ema9": round(float(ema9), 2),
                                    "ema20": round(float(ema20), 2),
                                    "vwap": round(float(effective_vwap), 2),
                                    "spot": spot,
                                }
                    except Exception as e_tpb:
                        logger.debug(f"[IndexPutSetup] Trend pullback check error: {e_tpb}")

                # 6b. Intraday Capitulation Top (ICT) — Catches V-Top turning points & Bull Traps above VWAP
                # Mirrors INTRADAY_CAPITULATION_REVERSAL in index_call_setup:
                # Fires when:
                # a. Day high was heavily overbought above session VWAP (>= 0.25% for Nifty, >= 0.40% for BankNifty)
                # b. Spot has retreated >= 0.10% off the day high
                # c. 5m structure shift confirmed (lower close or break of previous bar low / CHoCH)
                if (
                    len(active_ohlcv) >= 6
                    and not is_opening_buffer
                    and "INTRADAY_CAPITULATION_TOP" not in signals
                ):
                    try:
                        # BSE indices move in larger absolute pts; use a slightly tighter overbought
                        # threshold so mid-session distribution tops aren't missed.
                        # SENSEX/BANKEX: 0.30% overbought = ~220/350+ pts above VWAP (sensitive)
                        # BANKNIFTY/FINNIFTY/MIDCPNIFTY: 0.40%
                        # NIFTY: 0.25%
                        min_overbought = (
                            0.40
                            if clean_sym in ("BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
                            else 0.30
                            if clean_sym in ("SENSEX", "BANKEX")
                            else 0.25
                        )
                        day_high_ext = (
                            (((day_high or spot) - effective_vwap) / effective_vwap * 100.0)
                            if effective_vwap > 0
                            else 0.0
                        )
                        spot_retreat = (
                            (((day_high or spot) - spot) / max(1.0, spot) * 100.0)
                            if day_high
                            else 0.0
                        )

                        if day_high_ext >= min_overbought and spot_retreat >= 0.10:
                            b_curr = active_ohlcv.iloc[-1]
                            b_prev = active_ohlcv.iloc[-2]
                            curr_c = float(b_curr[col_c])
                            prev_l = float(b_prev[col_l])
                            curr_h = float(b_curr[col_h])
                            prev_h = float(b_prev[col_h])
                            col_o_ict = "open" if "open" in active_ohlcv.columns else "Open"
                            curr_o = float(b_curr[col_o_ict])

                            is_choch = curr_c <= (prev_l * 1.0005)
                            is_lower_high = (curr_h < prev_h) and (curr_c < curr_o)

                            if is_choch or is_lower_high:
                                signals.append("INTRADAY_CAPITULATION_TOP")
                                signal_tags["capitulation_top"] = {
                                    "day_high": round(day_high or spot, 2),
                                    "vwap": round(effective_vwap, 2),
                                    "overbought_pct": round(day_high_ext, 2),
                                    "retreat_pct": round(spot_retreat, 2),
                                    "choch_break": is_choch,
                                    "lower_high": is_lower_high,
                                }
                    except Exception as e_ict:
                        logger.debug(f"[IndexPutSetup] ICT check error: {e_ict}")

                # 6c. Failed Day High Breakout (Bull Trap / Liquidity Sweep above Day High)
                # Catches institutional stop hunts where price momentarily pierces Day High and snaps back below
                if (
                    len(active_ohlcv) >= 6
                    and not is_opening_buffer
                    and "FAILED_DAY_HIGH_BREAKOUT" not in signals
                ):
                    try:
                        b_curr = active_ohlcv.iloc[-1]
                        curr_h = float(b_curr[col_h])
                        curr_c = float(b_curr[col_c])
                        curr_l = float(b_curr[col_l])
                        col_o_fdh = "open" if "open" in active_ohlcv.columns else "Open"
                        curr_o = float(b_curr[col_o_fdh])
                        c_rng = max(0.1, curr_h - curr_l)
                        u_wick_pct = (curr_h - curr_c) / c_rng * 100.0

                        prior_high = float(active_ohlcv[col_h].iloc[:-1].max())
                        ref_high = day_high if (day_high and day_high < curr_h) else prior_high

                        if ref_high and ref_high > 0 and curr_h > ref_high and curr_c <= ref_high:
                            pierce_pct = (curr_h - ref_high) / ref_high * 100.0
                            if 0.02 <= pierce_pct <= 0.60 and (
                                u_wick_pct >= 35.0 or curr_c < curr_o
                            ):
                                signals.append("FAILED_DAY_HIGH_BREAKOUT")
                                signal_tags["failed_day_high_breakout"] = {
                                    "day_high": round(ref_high, 2),
                                    "pierce_high": round(curr_h, 2),
                                    "pierce_pct": round(pierce_pct, 3),
                                    "upper_wick_pct": round(u_wick_pct, 1),
                                    "close": round(curr_c, 2),
                                }
                    except Exception as e_fdh:
                        logger.debug(f"[IndexPutSetup] FDH check error: {e_fdh}")

        except Exception as e_ohlcv:
            logger.debug(f"[IndexPutSetup] OHLCV analysis error for {underlying}: {e_ohlcv}")

    # 7. Day Low Breakdown (Bearish Continuation / Range Expansion)
    # When spot is testing or breaking down through session low with VWAP weakness and PE momentum
    if day_low and day_low > 0 and "DAY_LOW_BREAKDOWN" not in signals and not is_opening_buffer:
        dl_dist_pct = (day_low - spot) / day_low * 100.0
        # Within 0.15% above day low, or broke down below day low up to 0.50%
        if -0.15 <= dl_dist_pct <= 0.50 and (
            spot <= (effective_vwap * 1.002) if effective_vwap > 0 else True
        ):
            if is_breakdown_momentum or (active_ohlcv is not None and len(active_ohlcv) >= 3):
                signals.append("DAY_LOW_BREAKDOWN")
                signal_tags["day_low_breakdown"] = {
                    "day_low": day_low,
                    "spot": spot,
                    "dl_dist_pct": round(dl_dist_pct, 3),
                    "pe_pchange": cand_pe_pchange,
                    "vol_oi": cand_pe_vol_oi,
                }

    # 8. Institutional Expansion Breakdown (Parabolic Momentum Flush)
    # Detects vertical institutional flushes that breakdown through session consolidation or Day Low
    # with ATR range expansion, volume surge, and strong close near the lows.
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
                tr.append(
                    max(
                        highs[i] - lows[i],
                        abs(highs[i] - closes[i - 1]),
                        abs(lows[i] - closes[i - 1]),
                    )
                )
            atr_14 = float(pd.Series(tr).rolling(min(14, len(tr)), min_periods=1).mean().iloc[-1])

            last_bar_rng = max(0.1, float(highs[-1]) - float(lows[-1]))
            rng_atr_ratio = round(last_bar_rng / max(1.0, atr_14), 2)

            avg_vol_20 = float(
                pd.Series(vols).rolling(min(20, len(vols)), min_periods=1).mean().iloc[-1]
            )
            last_vol = float(vols[-1])
            vol_ratio = round(last_vol / max(1.0, avg_vol_20), 2)

            last_c = float(closes[-1])
            last_o = float(opens[-1])
            last_h = float(highs[-1])
            last_l = float(lows[-1])

            # Lower wick rejection check: lower wick <= 25% of candle range
            lower_wick = max(0.0, min(last_c, last_o) - last_l)
            lower_wick_pct = round((lower_wick / last_bar_rng) * 100.0, 1)

            # Bearish close check: close <= open and close in bottom 30% of bar
            close_pos_pct = round(((last_h - last_c) / last_bar_rng) * 100.0, 1)

            # Day low or session low breakdown
            dl_val = day_low or (
                min(lows[:-1]) if len(lows) >= 2 else (lows[0] if len(lows) >= 1 else spot)
            )
            is_at_or_below_dl = (last_c <= dl_val * 1.0005) or (spot <= dl_val)

            # Cumulative Volume Delta (CVD) Footprint Check:
            # Integrate tick-level or intra-candle seller/buyer aggressive volume delta into the 5m thrust detector.
            # Alert fires ONLY if seller volume exceeds buyer volume by >= 2.2x during the breakdown candle.
            if "buy_volume" in active_ohlcv and "sell_volume" in active_ohlcv:
                buyer_vol = float(active_ohlcv["buy_volume"].iloc[-1])
                seller_vol = float(active_ohlcv["sell_volume"].iloc[-1])
            else:
                # Intra-candle footprint proxy:
                # If candle is green (close > open) or doji with negligible range, sellers cannot dominate
                if last_c > last_o or last_bar_rng < (max(1.0, atr_14) * 0.3):
                    seller_vol = last_vol * 0.2
                    buyer_vol = last_vol * 0.8
                else:
                    buyer_vol = last_vol * max(0.01, (last_c - last_l)) / last_bar_rng
                    seller_vol = last_vol * max(0.01, (last_h - last_c)) / last_bar_rng
            cvd_ratio = round(seller_vol / max(1.0, buyer_vol), 2)
            is_cvd_seller_dominant = cvd_ratio >= 2.2

            is_vol_surge = (vol_ratio >= 1.6) or (
                last_vol >= max(vols[-min(10, len(vols)) : -1]) if len(vols) >= 3 else True
            )
            if (
                rng_atr_ratio >= 1.3
                and is_vol_surge
                and lower_wick_pct <= 25.0
                and close_pos_pct >= 70.0
                and is_cvd_seller_dominant
                and is_at_or_below_dl
                and (is_breakdown_momentum or cand_pe_pchange >= 12.0)
            ):
                is_institutional_thrust = True
                signals.append("INSTITUTIONAL_EXPANSION_BREAKDOWN")
                thrust_details = {
                    "range_atr_ratio": rng_atr_ratio,
                    "vol_ratio": vol_ratio,
                    "cvd_ratio": cvd_ratio,
                    "buyer_vol": round(buyer_vol, 0),
                    "seller_vol": round(seller_vol, 0),
                    "lower_wick_pct": lower_wick_pct,
                    "close_pos_pct": close_pos_pct,
                    "day_low": round(float(dl_val), 2),
                    "breakout_bar_high": round(last_h, 2),
                    "atr_14": round(atr_14, 2),
                }
                signal_tags["institutional_expansion_breakdown"] = thrust_details
        except Exception as e_thrust:
            logger.debug(f"[IndexPutSetup] Thrust check error: {e_thrust}")

    # ── 11. DISTRIBUTION_TOP (Mid-Session VWAP Overextension + Session-High Rejection) ────
    # This is the canonical mid-session top reversal setup:
    # Market rallied strongly (spot ≥ 1.0% above VWAP), hit session ceiling (within 0.20% of
    # day high), and the last 5m bar shows institutional supply absorption with a rejection wick.
    # This is the EXACT pattern for setups like Sensex 73200 PE at 13:05 IST — the jackpot
    # that was previously missed because is_strong_bull_trend permanently blocked the put scanner.
    if day_high and day_high > 0 and not is_opening_buffer and "DISTRIBUTION_TOP" not in signals:
        spot_at_dh_pct = (day_high - spot) / max(1.0, spot) * 100.0  # distance below day high
        vwap_overextended = bool(
            effective_vwap > 0 and spot > effective_vwap * 1.010
        )  # ≥ 1.0% above VWAP

        has_distribution_bar = False
        _dist_bar_tags: dict[str, Any] = {}
        if active_ohlcv is not None and hasattr(active_ohlcv, "iloc") and len(active_ohlcv) >= 3:
            try:
                col_c = "close" if "close" in active_ohlcv.columns else "Close"
                col_o = "open" if "open" in active_ohlcv.columns else "Open"
                col_h = "high" if "high" in active_ohlcv.columns else "High"
                col_l = "low" if "low" in active_ohlcv.columns else "Low"
                col_v = "volume" if "volume" in active_ohlcv.columns else "Volume"
                last_b = active_ohlcv.iloc[-1]
                b_c = float(last_b[col_c])
                b_o = float(last_b[col_o])
                b_h = float(last_b[col_h])
                b_l = float(last_b[col_l])
                b_v = float(last_b[col_v])
                b_rng = max(0.1, b_h - b_l)
                upper_wick_pct = (b_h - max(b_c, b_o)) / b_rng * 100.0
                close_pos_pct = (b_c - b_l) / b_rng * 100.0  # close in bottom = selling pressure
                avg_vol = (
                    float(active_ohlcv[col_v].iloc[:-1].mean()) if len(active_ohlcv) > 1 else b_v
                )
                rvol = round(b_v / max(1.0, avg_vol), 2)
                # Rejection candle: close < open (bearish bar) AND significant upper wick (≥ 35%)
                # OR: close in bottom 30% of bar with elevated volume (distribution absorption)
                is_rejection_bar = b_c < b_o and upper_wick_pct >= 35.0
                is_high_vol_distribution = rvol >= 1.4 and close_pos_pct <= 30.0
                has_distribution_bar = is_rejection_bar or is_high_vol_distribution
                _dist_bar_tags = {
                    "upper_wick_pct": round(upper_wick_pct, 1),
                    "close_pos_pct": round(close_pos_pct, 1),
                    "rvol": rvol,
                    "is_rejection_bar": is_rejection_bar,
                    "is_high_vol_distribution": is_high_vol_distribution,
                }
            except Exception as _e_dist:
                logger.debug(f"[IndexPutSetup] DISTRIBUTION_TOP bar check error: {_e_dist}")

        if (
            0.0 <= spot_at_dh_pct <= 0.20  # within 0.20% below day high
            and vwap_overextended
            and has_distribution_bar
        ):
            vwap_ext_pct = (
                round((spot / effective_vwap - 1) * 100, 2) if effective_vwap > 0 else 0.0
            )
            signals.append("DISTRIBUTION_TOP")
            signal_tags["distribution_top"] = {
                "day_high": round(day_high, 2),
                "spot": round(spot, 2),
                "dh_proximity_pct": round(spot_at_dh_pct, 3),
                "vwap": round(effective_vwap, 2) if effective_vwap > 0 else None,
                "vwap_ext_pct": vwap_ext_pct,
                "roc_deceleration": roc_metric.is_decelerating_up,
                "roc_1": roc_metric.roc_1,
                "roc_2": roc_metric.roc_2,
                **_dist_bar_tags,
            }
            logger.info(
                f"[IndexPutSetup] DISTRIBUTION_TOP detected on {clean_sym}: "
                f"Spot ₹{spot:,.1f} within {spot_at_dh_pct:.3f}% of Day High ₹{day_high:,.1f}, "
                f"VWAP overextended +{vwap_ext_pct:.2f}% (₹{effective_vwap:,.1f}), "
                f"rejection bar confirmed ({_dist_bar_tags}), ROC deceleration={roc_metric.is_decelerating_up}."
            )

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

    # ── Option Greeks & DTE Computation ───────────────────────────
    opt_delta = None
    opt_gamma = None
    opt_iv = None
    is_0dte = False
    dte_days = 1
    if exp_date:
        try:
            exp_d = datetime.strptime(str(exp_date)[:10], "%Y-%m-%d").date()
            today_d = datetime.now(IST).date()
            dte_days = max(0, (exp_d - today_d).days)
            is_0dte = dte_days == 0
        except Exception:
            pass
    if opt_ltp > 0 and exp_date:
        try:
            from analysis.options import compute_greeks

            g = compute_greeks(spot, strike, str(exp_date)[:10], "PE", opt_ltp)
            if g and getattr(g, "delta", None) is not None:
                opt_delta = round(float(g.delta), 4)
                opt_gamma = round(float(g.gamma), 6)
                opt_iv = round(float(g.iv_pct), 2)
        except Exception:
            pass

    # ── Confidence Score ─────────────────────────────────────────
    base_confidence = 68
    signal_bonuses = {
        "PDH_SUPPLY_REJECTION": 14,
        "DAY_HIGH_SUPPLY_REJECTION": 14,
        "FAILED_DAY_HIGH_BREAKOUT": 15,
        "INTRADAY_CAPITULATION_TOP": 15,
        "DISTRIBUTION_TOP": 16,  # High-conviction: VWAP exhaustion + session-high ceiling rejection
        "VWAP_REJECTION": 10,
        "VWAP_BREAKDOWN": 14,
        "SUPPLY_ZONE_SWEEP": 8,
        "BEARISH_OB_CONFLUENCE": 10,
        "DOUBLE_TOP_BREAKDOWN": 8,
        "DAY_LOW_BREAKDOWN": 12,
        "INSTITUTIONAL_EXPANSION_BREAKDOWN": 16,
        "LONG_UNWINDING_FLUSH": 16,
    }
    confidence = base_confidence
    for sig in signals:
        confidence += signal_bonuses.get(sig, 5)
    # Vol/OI bonus
    confidence += min(8, int(vol_oi_ratio * 3))
    # Premium expansion bonus
    if pchange >= 10.0:
        confidence += 6
    if roc_metric.is_accelerating_down and roc_metric.is_meaningful_down:
        confidence += 5
    if "DISTRIBUTION_TOP" in signals and roc_metric.is_decelerating_up:
        confidence += 4
    if cand_pe_oi_roc >= 15.0:
        confidence += 3
    prem_vel = calculate_premium_velocity(contract_sym, opt_ltp)
    signal_tags["premium_velocity"] = round(prem_vel, 2)
    if prem_vel >= 25.0:
        confidence += 5
    elif prem_vel >= 10.0:
        confidence += 3
    confidence = min(96, confidence)

    # Single-signal unconfirmed guard: if only 1 secondary signal, cap at 72%
    if (
        len(signals) == 1
        and signals[0] in ("DAY_HIGH_SUPPLY_REJECTION", "SUPPLY_ZONE_SWEEP")
        and not is_breakdown_momentum
    ):
        confidence = min(72, confidence)

    # Determine stage: IGNITED if premium is already expanding strongly, else EARLY_WARNING
    if is_institutional_thrust:
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

    if "INSTITUTIONAL_EXPANSION_BREAKDOWN" in signals:
        ieb = signal_tags.get("institutional_expansion_breakdown", {})
        headline = f"📉 INSTITUTIONAL EXPANSION BREAKDOWN: {clean_sym} {int(strike)} PE"
        summary = (
            f"Institutional flush breakdown: Spot (₹{spot:,.1f}) breaking Session Low (₹{ieb.get('day_low', 0):,.1f}) "
            f"with {ieb.get('range_atr_ratio', 1.3):.1f}x ATR expansion & {ieb.get('vol_ratio', 1.6):.1f}x volume surge. "
            f"Clean liquidation ({ieb.get('lower_wick_pct', 0):.0f}% lower wick) with PE momentum ({volume:,} contracts, {vol_oi_ratio:.1f}x Vol/OI, +{pchange:.1f}%). "
            f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{sl_premium:,.1f} ({sl_pct:.0f}%) | T1: ₹{t1_premium:,.1f} (+{t1_pct:.0f}%)."
        )
    elif "PDH_SUPPLY_REJECTION" in signals:
        level_type = signal_tags.get("pdh_supply_rejection", {}).get("level_type", "PDH")
        headline = (
            f"{vel_badge}{icon} SMC {level_type} SUPPLY REJECTION: {clean_sym} {int(strike)} PE"
        )
        struct_detail = signal_tags["pdh_supply_rejection"]
        ref_level = struct_detail.get("prev_day_high") or struct_detail.get("prev_week_high", 0.0)
        retreat_pct = struct_detail.get("retreat_pct", 0.0)
        summary = (
            f"Spot swept {level_type} (₹{ref_level:,.1f}) and rejected with a {retreat_pct:.2f}% wick — "
            f"institutional supply OB confirmed. Put volume surging ({volume:,} contracts, {vol_oi_ratio:.1f}x Vol/OI). "
            f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{sl_premium:,.1f} | T1: ₹{t1_premium:,.1f} (+{t1_pct:.0f}%)."
        )
    elif "INTRADAY_CAPITULATION_TOP" in signals:
        ict = signal_tags.get("capitulation_top", {})
        headline = f"{vel_badge}⚡ INTRADAY CAPITULATION TOP: {clean_sym} {int(strike)} PE"
        summary = (
            f"Climax exhaustion & V-top reversal: Spot overbought +{ict.get('overbought_pct', 0):.2f}% above session VWAP (₹{effective_vwap:,.1f}) "
            f"and rejected Day High (₹{ict.get('day_high', 0):,.1f}) with 5m CHoCH structure breakdown. "
            f"High-probability mean-reversion retest back towards VWAP. "
            f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{sl_premium:,.1f} ({sl_pct:.0f}%) | T1: ₹{t1_premium:,.1f} (+{t1_pct:.0f}%)."
        )
    elif "FAILED_DAY_HIGH_BREAKOUT" in signals:
        fdh = signal_tags.get("failed_day_high_breakout", {})
        headline = f"⚡ FAILED DAY HIGH BREAKOUT (BULL TRAP): {clean_sym} {int(strike)} PE"
        summary = (
            f"Bull Trap / Liquidity Sweep above Day High: Spot (₹{spot:,.1f}) pierced Session High (₹{fdh.get('day_high', 0):,.1f}) "
            f"by {fdh.get('pierce_pct', 0):.2f}% to ₹{fdh.get('pierce_high', 0):,.1f}, then failed and closed back below with a "
            f"{fdh.get('upper_wick_pct', 0):.0f}% supply rejection wick. Trapped buyers vulnerable to liquidation. "
            f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{sl_premium:,.1f} ({sl_pct:.0f}%) | T1: ₹{t1_premium:,.1f} (+{t1_pct:.0f}%)."
        )
    elif "DAY_HIGH_SUPPLY_REJECTION" in signals:
        dhsr = signal_tags.get("day_high_supply_rejection", {})
        headline = f"{vel_badge}{icon} DAY HIGH SUPPLY REJECTION: {clean_sym} {int(strike)} PE"
        summary = (
            f"Spot rejected Day High (₹{dhsr.get('day_high', 0):,.1f}) and formed an upper-wick supply rejection "
            f"(retreating -{dhsr.get('dh_retreat_pct', 0):.2f}% from peak) — institutional distribution/bull trap confirmed. "
            f"Put volume active ({volume:,} contracts, {vol_oi_ratio:.1f}x Vol/OI). "
            f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{sl_premium:,.1f} ({sl_pct:.0f}%) | T1: ₹{t1_premium:,.1f} (+{t1_pct:.0f}%)."
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
    elif "VWAP_BREAKDOWN" in signals:
        vbd = signal_tags.get("vwap_breakdown", {})
        headline = f"{vel_badge}📉 VWAP BREAKDOWN PUT SETUP: {clean_sym} {int(strike)} PE"
        summary = (
            f"Institutional Regime Shift: Spot sliced cleanly below session VWAP (₹{effective_vwap:,.1f}) "
            f"after earlier trading above VWAP. Spot now -{vbd.get('vwap_bd_pct', 0):.2f}% below VWAP with confirmed "
            f"5m bar breakdown and Put volume expansion ({volume:,} contracts, {vol_oi_ratio:.1f}x Vol/OI). "
            f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{sl_premium:,.1f} ({sl_pct:.0f}%) | T1: ₹{t1_premium:,.1f} (+{t1_pct:.0f}%)."
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
    elif "DISTRIBUTION_TOP" in signals:
        dt_tags = signal_tags.get("distribution_top", {})
        headline = f"🔥 DISTRIBUTION TOP REVERSAL: {clean_sym} {int(strike)} PE"
        summary = (
            f"Mid-session distribution ceiling rejection: Spot ₹{dt_tags.get('spot', spot):,.1f} "
            f"hit Day High ₹{dt_tags.get('day_high', 0):,.1f} ({dt_tags.get('dh_proximity_pct', 0):.3f}% below) "
            f"while VWAP overextended +{dt_tags.get('vwap_ext_pct', 0):.2f}% (VWAP ₹{dt_tags.get('vwap', effective_vwap):,.1f}). "
            f"Rejection bar confirmed: {dt_tags.get('upper_wick_pct', 0):.0f}% upper wick, close bottom-{dt_tags.get('close_pos_pct', 0):.0f}% of bar, "
            f"RVOL {dt_tags.get('rvol', 0):.1f}x. Institutional supply absorption detected. "
            f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{sl_premium:,.1f} ({sl_pct:.0f}%) | T1: ₹{t1_premium:,.1f} (+{t1_pct:.0f}%)."
        )
    elif "LONG_UNWINDING_FLUSH" in signals:
        luf = signal_tags.get("long_unwinding_flush", {})
        headline = f"⚡ LONG UNWINDING FLUSH: {clean_sym} {int(strike)} PE"
        summary = (
            f"Put Writers Capitulation Flush: Spot (₹{spot:,.1f}) broke below Max Put OI Wall ₹{luf.get('max_put_oi_strike', 0):,.0f} "
            f"with writers aggressively unwinding ({luf.get('max_pe_oi_change', 0):+,} contracts). Downside liquidation acceleration ignited. "
            f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{sl_premium:,.1f} ({sl_pct:.0f}%) | T1: ₹{t1_premium:,.1f} (+{t1_pct:.0f}%)."
        )
    elif "TREND_PULLBACK_REJECTION" in signals:
        tpb = signal_tags.get("trend_pullback", {})
        headline = f"📉 TREND RETRACE REJECTION: {clean_sym} {int(strike)} PE"
        summary = (
            f"Bearish trend continuation: Spot (₹{spot:,.1f}) tested EMA-9/20 resistance (₹{tpb.get('ema9', 0):,.1f}) and failed beneath VWAP (₹{effective_vwap:,.1f}) with sellers in control. "
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

    # ── Defined-Risk Hedged Spread Construction (Bear Put Spread) ─
    hedge_plan = None
    now_time = now_dt.time()
    is_low_vix_range = bool(vix_val is not None and vix_val < 13.0)
    is_midday_chop_window = bool(dtime(11, 30) <= now_time <= dtime(14, 0)) and (vel_score < 65)
    is_chop_regime = (
        is_midday_chop_window
        or is_low_vix_range
        or (vel_regime == "CHOP_PINNED")
        or (vel_score < 55)
    )
    is_explosive_momentum = bool(
        is_institutional_thrust
        if "is_institutional_thrust" in locals()
        else False
        or (vel_score >= 75)
        or ("DAY_LOW_BREAKDOWN" in signals)
        or (vel_regime == "LEADER_EXPANSION")
    )

    if clean_sym in ("BANKNIFTY", "BANKEX"):
        step = 100.0
        if is_chop_regime:
            min_spread_width = 300.0
            regime_note = "CHOP / RANGE DEFENSE (300 pt width)"
        elif is_explosive_momentum:
            min_spread_width = 500.0
            regime_note = "HIGH-VELOCITY MOMENTUM / THRUST (500 pt width)"
        else:
            min_spread_width = 400.0
            regime_note = "TREND CONTINUATION (400 pt width)"
    elif clean_sym == "SENSEX":
        step = 100.0
        if is_chop_regime:
            min_spread_width = 400.0
            regime_note = "CHOP / RANGE DEFENSE (400 pt width)"
        elif is_explosive_momentum:
            min_spread_width = 700.0
            regime_note = "HIGH-VELOCITY MOMENTUM / THRUST (700 pt width)"
        else:
            min_spread_width = 600.0
            regime_note = "TREND CONTINUATION (600 pt width)"
    elif clean_sym == "MIDCPNIFTY":
        step = 25.0
        if is_chop_regime:
            min_spread_width = 75.0
            regime_note = "CHOP / RANGE DEFENSE (75 pt width)"
        elif is_explosive_momentum:
            min_spread_width = 125.0
            regime_note = "HIGH-VELOCITY MOMENTUM / THRUST (125 pt width)"
        else:
            min_spread_width = 100.0
            regime_note = "TREND CONTINUATION (100 pt width)"
    elif clean_sym in ("NIFTY", "FINNIFTY"):
        step = 50.0
        if is_chop_regime:
            min_spread_width = 100.0
            regime_note = "CHOP / RANGE DEFENSE (100 pt width)"
        elif is_explosive_momentum:
            min_spread_width = 200.0
            regime_note = "HIGH-VELOCITY MOMENTUM / THRUST (200 pt width)"
        else:
            min_spread_width = 150.0
            regime_note = "TREND CONTINUATION (150 pt width)"
    else:
        step = 50.0
        min_spread_width = 100.0 if is_chop_regime else (200.0 if is_explosive_momentum else 150.0)
        regime_note = "ADAPTIVE SPREAD"

    # DTE and Volatility for Delta / Greeks evaluation
    dte = 7
    try:
        from engine.alert_expiry import get_expiry_metadata

        exp_meta = get_expiry_metadata(exp_date, exp_type, clean_sym, contract_sym)
        if exp_meta and "dte" in exp_meta:
            dte = max(0, int(exp_meta["dte"]))
    except Exception:
        pass

    iv_val = max(0.10, (vix_val / 100.0) if vix_val else 0.14)
    from engine.options_backtest import bs_delta

    long_delta = bs_delta(spot, strike, dte, iv_val, "PE")

    # Target 1 Confluence: Short leg must be strictly OTM (below current spot) and sit at or beyond Target 1 support
    # so the spread never caps downward profitability before Target 1 is attained.
    otm_target_strike = min(
        max(step, strike - min_spread_width), max(step, (round(spot / step) * step) - step)
    )

    # 1. Evaluate candidate OTM strikes from chain (aiming for short delta ~ -0.25 to -0.32 or ~45% long premium)
    target_short_delta = -0.28
    otm_cand = None
    if chain:
        preferred_candidates = [
            c
            for c in chain
            if getattr(c, "option_type", "") == "PE"
            and getattr(c, "strike", 0.0)
            <= min(strike - min_spread_width * 0.75, spot - (step * 0.25))
            and float(getattr(c, "last_price", 0.0) or 0.0) > 0.0
        ]
        if preferred_candidates:

            def _score_put_cand(c):
                c_strike = float(getattr(c, "strike", 0.0))
                c_ltp = float(getattr(c, "last_price", 0.0))
                c_delta = bs_delta(spot, c_strike, dte, iv_val, "PE")
                delta_diff = abs(c_delta - target_short_delta)
                prem_ratio_diff = abs((c_ltp / max(1.0, opt_ltp)) - 0.45) if opt_ltp > 0 else 0.0
                strike_dist = abs(c_strike - otm_target_strike) / max(1.0, step)
                return delta_diff * 2.0 + prem_ratio_diff + strike_dist * 0.1

            preferred_candidates.sort(key=_score_put_cand)
            otm_cand = preferred_candidates[0]
        else:
            # Fallback to any contract in chain strictly lower than strike and spot
            fallback_candidates = [
                c
                for c in chain
                if getattr(c, "option_type", "") == "PE"
                and getattr(c, "strike", 0.0) < min(strike, spot)
                and float(getattr(c, "last_price", 0.0) or 0.0) > 0.0
            ]
            if fallback_candidates:
                fallback_candidates.sort(
                    key=lambda c: abs(getattr(c, "strike", 0.0) - otm_target_strike)
                )
                otm_cand = fallback_candidates[0]

    if otm_cand:
        sell_strike = float(getattr(otm_cand, "strike", otm_target_strike))
        sell_prem = float(getattr(otm_cand, "last_price", 0.0) or 0.0)
    else:
        sell_strike = otm_target_strike
        try:
            from engine.options_backtest import bs_premium

            sell_prem = round(bs_premium(spot, sell_strike, max(1, dte), iv_val, "PE"), 2)
        except Exception:
            sell_prem = 0.0

    if sell_strike >= strike or sell_strike >= spot:
        atm_strike = round(spot / step) * step
        sell_strike = min(max(step, strike - min_spread_width), max(step, atm_strike - step))

    actual_width = strike - sell_strike
    if sell_prem <= 0.0 or sell_prem >= opt_ltp or (opt_ltp - sell_prem) >= actual_width:
        sell_prem = max(
            1.0, round(min(opt_ltp * 0.55, max(1.0, opt_ltp - (actual_width * 0.35))), 2)
        )

    short_delta = bs_delta(spot, sell_strike, dte, iv_val, "PE")
    net_spread_delta = round(long_delta - short_delta, 2)

    is_spread_mandated = False
    is_0dte_midday_trap = False
    is_midday_chop_window = False

    if opt_ltp > 0 and sell_prem > 0 and sell_strike < strike:
        net_debit = round(max(1.0, min(actual_width * 0.75, opt_ltp - sell_prem)), 2)
        strike_width = round(strike - sell_strike, 2)
        max_loss = round(net_debit * lot_sz, 2)
        max_profit = round(max(1.0, (strike_width - net_debit) * lot_sz), 2)
        be_spot = round(spot - net_debit, 1)
        rr_spread = round(max_profit / max(1.0, max_loss), 2)

        now_time = now_dt.time()
        is_midday_chop_window = (dtime(11, 30) <= now_time <= dtime(14, 0)) and (vel_score < 70)

        # 0DTE Expiry Check:
        is_0dte = False
        try:
            from engine.alert_expiry import get_expiry_metadata

            exp_meta = get_expiry_metadata(exp_date, exp_type, clean_sym, contract_sym)
            if exp_meta and exp_meta.get("dte") == 0:
                is_0dte = True
            elif exp_date and exp_date == now_dt.strftime("%Y-%m-%d"):
                is_0dte = True
        except Exception:
            pass

        # 0DTE Midday Theta Trap: On expiry day between 11:30 and 14:00, theta decay is at its weekly maximum.
        # Naked option buying during this window suffers severe theta drag and mean-reversion whipsaws.
        is_0dte_midday_trap = is_0dte and (dtime(11, 30) <= now_time <= dtime(14, 0))

        if is_low_vix_range:
            pref_veh = "SPREAD_ONLY"
            spread_guidance = (
                "🛡️ MANDATORY HEDGED SPREAD: India VIX < 13.0 indicates low volatility / mean-reverting regime. "
                "Naked options suffer heavy theta bleed. Execute Bear Put Spread only."
            )
        elif is_high_iv_risk:
            pref_veh = "SPREAD_ONLY"
            spread_guidance = (
                f"⚠️ HIGH-VIX REGIME (India VIX {vix_val:.1f} >= 18.0): High IV crush risk on naked options; "
                "execute defined-risk Bear Put Spread or Deep ITM only."
            )
        elif is_0dte_midday_trap:
            pref_veh = "SPREAD_ONLY"
            spread_guidance = (
                "⚠️ 0DTE MIDDAY THETA TRAP (11:30–14:00 IST): Naked option buying strictly prohibited on expiry day; "
                "execute defined-risk Bear Put Spread only to eliminate theta bleed."
            )
        elif is_midday_chop_window:
            pref_veh = "HEDGED_SPREAD"
            spread_guidance = "⚠️ MIDDAY CHOP WINDOW: Execute Bear Put Spread to avoid theta decay."
        else:
            pref_veh = "NAKED_OPTION_OR_SPREAD"
            spread_guidance = "High Momentum: Fast scalpers can trade Naked PE; for defined risk, trade Bear Put Spread."

        hedge_plan = {
            "strategy": "BEAR_PUT_SPREAD",
            "sentiment": "BEARISH",
            "preferred_vehicle": pref_veh,
            "description": f"Buy {int(strike)} PE & Sell {int(sell_strike)} PE (Defined Risk / Capped Loss)",
            "buy_leg": f"BUY {clean_sym} {int(strike)} PE @ ₹{opt_ltp:,.1f}",
            "sell_leg": f"SELL {clean_sym} {int(sell_strike)} PE @ ₹{sell_prem:,.1f}",
            "net_debit_per_share": net_debit,
            "net_debit_total": max_loss,
            "max_loss": max_loss,
            "max_profit": max_profit,
            "breakeven_spot": be_spot,
            "risk_reward": f"1:{rr_spread:.1f}",
            "lot_size": lot_sz,
            "strike_width": actual_width,
            "entry_spot": spot,
            "buy_strike": strike,
            "sell_strike": sell_strike,
            "short_strike": sell_strike,
            "long_delta": round(long_delta, 2),
            "short_delta": round(short_delta, 2),
            "net_spread_delta": net_spread_delta,
            "net_delta": net_spread_delta,
            "adaptive_regime": regime_note,
            "greeks": {
                "long_delta": round(long_delta, 2),
                "short_delta": round(short_delta, 2),
                "net_delta": net_spread_delta,
            },
            "booking_target_70": round(net_debit + 0.70 * (actual_width - net_debit), 2),
            "spread_stop_loss": round(net_debit * 0.50, 2),
            "booking_rule": (
                f"Book 70%–80% Max Profit (Net Spread value ₹{round(net_debit + 0.70 * (actual_width - net_debit), 2):,.1f}) "
                f"or if Spot touches {sell_strike:,.0f} (Short Strike Wall). Stop loss if spread decays below ₹{round(net_debit * 0.50, 2):,.1f}."
            ),
            "margin_benefit_note": "SEBI Hedged Margin: ~70% margin reduction when executing both legs simultaneously.",
            "peace_of_mind_benefit": "Zero Theta Bleed — short OTM leg finances time decay. Maximum downside risk strictly capped.",
            "execution_guidance": spread_guidance,
            "legs": [
                {
                    "side": "BUY",
                    "strike": strike,
                    "option_type": "PE",
                    "premium": opt_ltp,
                    "lots": 1,
                    "qty": lot_sz,
                },
                {
                    "side": "SELL",
                    "strike": sell_strike,
                    "option_type": "PE",
                    "premium": sell_prem,
                    "lots": 1,
                    "qty": lot_sz,
                },
            ],
        }
        is_long_dated_monthly = dte_days >= 8
        is_spread_mandated = bool(
            (
                is_low_vix_range
                or is_high_iv_risk
                or is_midday_chop_window
                or is_0dte_midday_trap
                or is_put_wall_collision
                or is_long_dated_monthly
            )
            and hedge_plan is not None
        )

    # ── Optimal Trade Entry (OTE) & No-Chase Guard ───────────────
    if (is_low_vix_range or is_0dte_midday_trap or is_put_wall_collision) and not hedge_plan:
        logger.info(
            f"[IndexPutSetup] Suppressed PE setup on {clean_sym}: "
            f"{'Imminent Put Wall Collision' if is_put_wall_collision else ('0DTE Midday Theta Trap' if is_0dte_midday_trap else 'Low-VIX range-bound regime')} without viable hedged spread."
        )
        return []

    act_verb = "BEAR PUT SPREAD" if is_spread_mandated else "BUY PE"
    target_inst = (
        f"{clean_sym} {int(strike)}/{int(hedge_plan['sell_strike'])} Bear Put Spread"
        if is_spread_mandated
        else contract_sym
    )

    entry_min = round(max(0.5, opt_ltp * 0.94), 1) if opt_ltp > 0 else spot
    entry_max = round(opt_ltp * 1.02, 1) if opt_ltp > 0 else spot
    entry_range_str = f"₹{entry_min:,.1f} – ₹{entry_max:,.1f}"
    no_chase_lvl = round(opt_ltp * 1.04, 1) if opt_ltp > 0 else round(spot * 0.996, 1)

    alert = AutoAlert(
        alert_id=generate_alert_id(clean_sym, "INDEX_PUT_SETUP", variant=f"pe-{int(strike)}"),
        alert_type="INDEX_PUT_SETUP",
        stage=stage,
        symbol=clean_sym,
        exchange=opt_exchange,
        direction="BEARISH",
        headline=f"🛡️ [HEDGED SPREAD MANDATE] {headline}" if is_spread_mandated else headline,
        summary=f"{summary} | OTE: {entry_range_str} | No Chase > ₹{no_chase_lvl:,.1f} | Rule: 50% @ T1 -> SL to BE",
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
            "delta": opt_delta,
            "gamma": opt_gamma,
            "iv": opt_iv,
            "dte": dte_days,
            "is_0dte": is_0dte,
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
            # CHoCH / MSS tags for whiplash guard unlock (PDH rejection IS a structural reversal)
            "choch": "PDH_SUPPLY_REJECTION" in signals,
            "mss": "PDH_SUPPLY_REJECTION" in signals,
            "pdh_sweep": "PDH_SUPPLY_REJECTION" in signals,
            "pdl_sweep": False,
            "day_high": day_high,
            "day_low": day_low,
            "prev_day_high": prev_day_high,
            "prev_day_low": prev_day_low,
            "pcr": chain_pcr,
            "heavyweights_posture": hw_posture.get("summary", "UNAVAILABLE"),
            "hbcm": hbcm_dict,
            "max_call_oi_strike": max_call_oi_strike,
            "max_put_oi_strike": max_put_oi_strike,
            "put_wall_dist_pct": put_wall_dist_pct,
            "is_put_wall_collision": is_put_wall_collision,
            "is_long_unwinding_flush": is_long_unwinding_flush,
            "roc_momentum": roc_metric.to_dict(),
            "premium_velocity": round(prem_vel, 2),
            "oi_roc": cand_pe_oi_roc,
            "cvd_ratio": thrust_details.get(
                "cvd_ratio", cvd_ratio if "cvd_ratio" in locals() else 0.0
            ),
            "detector": "INDEX_PUT_SETUP",
            "is_institutional_thrust": is_institutional_thrust,
            "thrust_details": thrust_details,
            "breakout_bar_high": thrust_details.get("breakout_bar_high"),
            "india_vix": vix_val,
            "is_high_iv_risk": is_high_iv_risk,
        },
        actionable_plan={
            "action": act_verb,
            "contract": target_inst,
            "instrument": target_inst,
            "instrument_type": "OPTION_SPREAD" if is_spread_mandated else "OPTION",
            "preferred_vehicle": hedge_plan.get(
                "preferred_vehicle", "SPREAD_ONLY" if is_spread_mandated else "NAKED_OPTION"
            )
            if hedge_plan
            else ("DEEP_ITM_OR_SPREAD" if is_high_iv_risk else "NAKED_OPTION"),
            "iv_crush_defense": (
                f"HIGH_VIX_IV_CRUSH_WARNING: India VIX {vix_val:.1f} >= 18.0. Elevated IV crush risk on OTM/ATM longs. Prefer Deep ITM (Delta >= 0.65), Bear Put Vertical Spreads, or Futures."
                if is_high_iv_risk
                else None
            ),
            "strike": strike,
            "option_type": "PE",
            "expiry_date": exp_date,
            "expiry_type": exp_type,
            "underlying_spot": f"₹{spot:,.1f}",
            "recommended_entry": f"₹{opt_ltp:,.2f} (OTE Pullback: {entry_range_str})"
            if opt_ltp
            else "Market",
            "entry_range": entry_range_str,
            "no_chase": f"DO NOT CHASE above ₹{no_chase_lvl:,.1f}",
            "impulse_trigger_level": round(opt_ltp * 1.01, 2) if opt_ltp > 0 else spot,
            "target_1": f"₹{t1_premium:,.2f}",
            "target": f"₹{t1_premium:,.2f} (+{t1_pct:.0f}%)",
            "target_2": f"₹{t2_premium:,.2f}",
            "target_moonshot": f"₹{t3_premium:,.2f}",
            "stop_loss": f"₹{sl_premium:,.2f}",
            "risk_reward": rr_str,
            "profit_rule": (
                f"Scale Blueprint: Book 50% at T1 (₹{t1_premium:,.1f}) & move SL to Cost/Breakeven (Zero Risk). "
                f"Book 25% at T2 (₹{t2_premium:,.1f}). Leave 25% runner trailing on 5m 9-EMA."
            ),
            "when_to_wait": (
                f"DO NOT CHASE above ₹{no_chase_lvl:,.1f}. If premium > ₹{no_chase_lvl:,.1f}, place LIMIT order in OTE zone "
                f"({entry_range_str}) on 1m-5m pullback retest. If not filled, cancel order."
            ),
            "execution_protocol": {
                "ote_limit_zone": entry_range_str,
                "no_chase_boundary": f"₹{no_chase_lvl:,.1f}",
                "rule": "Never chase market orders if price > No Chase. Wait for limit retest or cancel.",
                "t1_scale": "50% off + Move SL to Breakeven",
                "t2_scale": "25% off",
                "runner_trail": "25% position trailed via 5m 9-EMA close",
            },
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
            "hedge_plan": hedge_plan,
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
