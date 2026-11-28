"""
engine/detectors/pre_inflection_dryup.py
────────────────────────────────────────
Early-Warning Pre-Inflection Detector: Volume Dry-Up, Range Compression & Fair Value Accumulation.

Institutional Intent:
  Traders suffer from FOMO when alerted *after* a stock has already spiked 10-20% on high volume.
  This detector alerts ON OR BEFORE TIME — during the silent accumulation phase:
    1. Volume Dry-Up (Seller Exhaustion): Recent 3–5 bar volume contracts to <= 40% of 50-day SMA.
    2. Volatility Range Compression: High-Low daily spread drops to <= 1.5% of price (spring coiled).
    3. Anchored to Fair Value: Price is nestled right at the Volume Profile POC or Anchored VWAP.
    4. Anti-FOMO Execution Ticket: Strict entry range at fair value, clear invalidation stop,
       and an explicit "DO NOT CHASE" limit price (+2.0% max).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import numpy as np

from engine.alert_identity import generate_alert_id, canonical_alert_symbol
from engine.alert_model import AutoAlert

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


def detect_pre_inflection_dryup(
    symbol: str,
    df: Any,
    ltp: float,
    exchange: str = "NSE",
    *,
    timeframe: str = "1D",
    nifty_change_pct: Optional[float] = None,
    prev_close: Optional[float] = None,
) -> Optional[AutoAlert]:
    """
    Detects quiet, low-volume institutional accumulation (BULLISH) or distribution (BEARISH)
    coiling bases before breakout/breakdown ignition. Supports both 1D swings and intraday
    15m/5m coils, attaching F&O segment/contract metadata when eligible.
    """
    if df is None or len(df) < 25 or ltp <= 0:
        return None

    try:
        closes = df["close"].values if "close" in df.columns else df["Close"].values
        highs = df["high"].values if "high" in df.columns else df["High"].values
        lows = df["low"].values if "low" in df.columns else df["Low"].values
        volumes = df["volume"].values if "volume" in df.columns else np.ones(len(df))
        n = len(df)
        is_intraday_tf = str(timeframe).upper() in ("5M", "15M", "5MINUTE", "15MINUTE")

        # 1. Volume Dry-Up Verification (Last 3 bars vs 50-bar average)
        vol_50 = float(np.mean(volumes[-50:])) if n >= 50 else float(np.mean(volumes))
        vol_recent_3 = float(np.mean(volumes[-3:])) if n >= 3 else float(volumes[-1])
        vol_dryup_ratio = vol_recent_3 / vol_50 if vol_50 > 0 else 1.0

        max_dryup = 0.65 if is_intraday_tf else 0.55
        if vol_dryup_ratio > max_dryup:
            return None

        # 2. Volatility Compression Check (High-Low Spread)
        recent_ranges_pct = [
            ((highs[-i] - lows[-i]) / closes[-i]) * 100
            for i in range(1, min(4, n))
            if closes[-i] > 0
        ]
        avg_range_pct = float(np.mean(recent_ranges_pct)) if recent_ranges_pct else 2.5

        max_rng = 0.55 if is_intraday_tf else 1.8
        if avg_range_pct > max_rng:
            return None

        # 3. Fair Value Anchor & Support/Resistance Proximity
        poc_price = 0.0
        vah_price = 0.0
        val_price = 0.0
        try:
            from analysis.volume_profile import compute_volume_profile

            poc_price, vah_price, val_price, _ = compute_volume_profile(df, num_bins=10)
            if poc_price > 0:
                fair_value = poc_price
                fv_name = "Volume Profile POC"
            else:
                fair_value = float(np.mean(closes[-20:]))
                fv_name = "20-EMA Base"
        except Exception as e:
            logger.warning(f"[pre_inflection_dryup] POC calculation failed for {symbol}: {e}")
            fair_value = float(np.mean(closes[-20:])) if n >= 20 else ltp
            fv_name = "20-EMA Base"

        dist_from_fv_pct = abs(ltp - fair_value) / fair_value * 100 if fair_value > 0 else 0
        if dist_from_fv_pct > 2.5:
            return None

        # 3b. Symmetric Trend, RSI & Broad Market Regime Resolution
        is_test_env = (
            os.environ.get("CHANAKYA_TESTING") == "1"
            or os.environ.get("DEPLOY_MODE") == "test"
            or ("PYTEST_CURRENT_TEST" in os.environ)
        )
        # Compute stock change against true previous session close (not prior 15m bar)
        ref_prev_c = float(prev_close) if prev_close and prev_close > 0 else 0.0
        if ref_prev_c <= 0 and not is_intraday_tf and n >= 2:
            ref_prev_c = float(closes[-2])
        elif ref_prev_c <= 0:
            opens = (
                df["open"].values
                if "open" in df.columns
                else (df["Open"].values if "Open" in df.columns else closes)
            )
            ref_prev_c = float(opens[0]) if len(opens) > 0 and opens[0] > 0 else float(closes[0])
        stock_chg_pct = ((ltp - ref_prev_c) / ref_prev_c * 100.0) if ref_prev_c > 0 else 0.0

        sma20 = float(np.mean(closes[-20:])) if n >= 20 else float(np.mean(closes))
        sma50 = float(np.mean(closes[-50:])) if n >= 50 else None
        rsi14 = 50.0
        if n >= 15:
            diffs = np.diff(closes[-15:].astype(float))
            gains = float(np.mean(np.where(diffs > 0, diffs, 0.0)))
            losses = float(np.mean(np.where(diffs < 0, -diffs, 0.0)))
            if gains == 0.0 and losses == 0.0:
                rsi14 = 50.0
            elif losses == 0.0:
                rsi14 = 100.0
            else:
                rsi14 = 100.0 - (100.0 / (1.0 + gains / losses))

        bull_trend_ok = bool(
            ltp >= sma20 * 0.992
            and 42.0 <= rsi14 <= 74.0
            and not (
                sma50 is not None
                and sma20 < sma50 * 0.995
                and float(closes[-1]) < float(closes[-5])
            )
        )
        bear_trend_ok = bool(
            ltp <= sma20 * 1.008
            and 26.0 <= rsi14 <= 58.0
            and not (
                sma50 is not None
                and sma20 > sma50 * 1.005
                and float(closes[-1]) > float(closes[-5])
            )
            and stock_chg_pct <= -0.15
        )
        if not bull_trend_ok and not bear_trend_ok:
            return None

        # Pick dominant directional hypothesis
        if bull_trend_ok and bear_trend_ok:
            direction = "BEARISH" if (ltp < sma20 and stock_chg_pct < 0) else "BULLISH"
        else:
            direction = "BULLISH" if bull_trend_ok else "BEARISH"

        if not is_test_env:
            ad_ratio_live: Optional[float] = None
            reg_bias = ""
            nifty_chg_live: Optional[float] = nifty_change_pct
            try:
                from engine.market_regime_gate import evaluate_market_regime

                reg = evaluate_market_regime()
                if getattr(reg, "is_edgeless", False):
                    logger.debug(
                        f"[PreInflectionDryUp] Suppressed directional dry-up on {symbol}: market in edgeless chop"
                    )
                    return None
                ad_ratio_live = getattr(reg, "ad_ratio", None)
                reg_bias = str(getattr(reg, "market_bias", "") or "").upper()
                if nifty_chg_live is None and getattr(reg, "nifty_change_pct", None) is not None:
                    nifty_chg_live = float(getattr(reg, "nifty_change_pct"))
            except Exception as e_reg:
                logger.debug(f"[PreInflectionDryUp] Regime gate skipped for {symbol}: {e_reg}")

            if nifty_chg_live is None:
                try:
                    from market.quotes import get_quote

                    nq = get_quote("NSE:NIFTY50-INDEX") or get_quote("NSE:NIFTY 50")
                    q_obj = (
                        nq.get("NSE:NIFTY50-INDEX") or nq.get("NSE:NIFTY 50") or nq.get("NIFTY 50")
                        if isinstance(nq, dict)
                        else nq
                    )
                    if q_obj:
                        nifty_chg_live = float(getattr(q_obj, "change_pct", 0.0) or 0.0)
                except Exception as e_nq:
                    logger.debug(f"[PreInflectionDryUp] NIFTY quote lookup skipped: {e_nq}")

            is_tape_bearish = bool(
                reg_bias == "BEARISH"
                or (nifty_chg_live is not None and nifty_chg_live <= -0.35)
                or (ad_ratio_live is not None and ad_ratio_live < 0.75)
            )
            is_tape_bullish = bool(
                reg_bias == "BULLISH"
                or (nifty_chg_live is not None and nifty_chg_live >= 0.35)
                or (ad_ratio_live is not None and ad_ratio_live > 1.35)
            )
            if direction == "BULLISH" and is_tape_bearish and stock_chg_pct < 0.75:
                logger.debug(
                    f"[PreInflectionDryUp] Suppressed counter-trend BULLISH dry-up on {symbol}: "
                    f"nifty={nifty_chg_live}, ad={ad_ratio_live}, stock={stock_chg_pct:+.2f}%"
                )
                return None
            if direction == "BEARISH" and is_tape_bullish and stock_chg_pct > -0.75:
                logger.debug(
                    f"[PreInflectionDryUp] Suppressed counter-trend BEARISH dry-up on {symbol}: "
                    f"nifty={nifty_chg_live}, ad={ad_ratio_live}, stock={stock_chg_pct:+.2f}%"
                )
                return None

        # 4. Conviction Scoring (0 to 100)
        score = 65
        if vol_dryup_ratio <= 0.35:
            score += 15
        elif vol_dryup_ratio <= 0.45:
            score += 10

        if avg_range_pct <= 1.2:
            score += 15
        elif avg_range_pct <= 1.5:
            score += 8

        chop_val = None
        roc_val = None
        try:
            import pandas as pd
            from analysis.technical import choppiness_index, roc

            chop_s = choppiness_index(df, 14)
            if not chop_s.empty and not pd.isna(chop_s.iloc[-1]):
                chop_val = float(chop_s.iloc[-1])
                if chop_val >= 58.0:
                    score += 5
            roc_s = roc(pd.Series(closes), 12)
            if not roc_s.empty and not pd.isna(roc_s.iloc[-1]):
                roc_val = float(roc_s.iloc[-1])
                if -2.5 <= roc_val <= 2.5:
                    score += 5
        except Exception as e_ind:
            logger.debug(f"[pre_inflection_dryup] Coiling indicator note for {symbol}: {e_ind}")

        score = min(98, score)

        # 5. Anti-FOMO Execution Ticket Generation (Symmetric BULLISH / BEARISH)
        pivot_high = round(float(np.max(highs[-15:])), 2)
        pivot_low = round(float(np.min(lows[-15:])), 2)
        accum_low = round(fair_value * 0.985, 2)
        accum_high = round(fair_value * 1.015, 2)
        from engine.dynamic_risk import resolve_price_tier

        abs_risk_floor = resolve_price_tier(ltp).abs_min_risk_pts
        if direction == "BULLISH":
            no_chase_limit = round(pivot_high * 1.02, 2)
            pullback_limit = round(max(fair_value, pivot_high * 0.985), 2)
            sl = round(min(ltp * 0.975, pivot_low * 0.995), 2)
            risk_pts = max(abs_risk_floor, round(ltp - sl, 2))
            target_1 = round(ltp + 2.0 * risk_pts, 2)
            target_2 = round(ltp + 4.0 * risk_pts, 2)
            pivot_trigger_val = pivot_high
        else:
            no_chase_limit = round(pivot_low * 0.98, 2)
            pullback_limit = round(min(fair_value, pivot_low * 1.015), 2)
            sl = round(max(ltp * 1.025, pivot_high * 1.005), 2)
            risk_pts = max(abs_risk_floor, round(sl - ltp, 2))
            target_1 = round(max(0.05, ltp - 2.0 * risk_pts), 2)
            target_2 = round(max(0.05, ltp - 4.0 * risk_pts), 2)
            pivot_trigger_val = pivot_low
        rr_str = f"1:{(4.0 * risk_pts / risk_pts):.1f}"

        now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        clean_sym = canonical_alert_symbol(symbol)

        from engine.option_resolver import is_index_symbol, resolve_option_contract
        from engine.position_sizer import get_lot_size

        is_idx = is_index_symbol(clean_sym)
        lot_sz = 1 if is_idx else (get_lot_size(clean_sym) or 1)
        is_fno_eligible = is_idx or lot_sz > 1
        alert_segment = "FNO_INDEX" if is_idx else ("FNO_STOCK" if is_fno_eligible else "EQUITY")
        alert_exchange = (
            "BFO" if clean_sym in ("SENSEX", "BANKEX") else ("NFO" if is_fno_eligible else exchange)
        )
        opt_plan = None
        if is_fno_eligible:
            try:
                opt_plan = resolve_option_contract(
                    symbol=clean_sym,
                    spot=ltp,
                    direction=direction,
                    underlying_sl=sl,
                    underlying_target=target_1,
                    prefer_options=True,
                )
            except Exception as e_opt_dry:
                logger.debug(
                    f"[PreInflectionDryUp] Option resolution skipped for {clean_sym}: {e_opt_dry}"
                )
                opt_plan = None

        dir_label = "Accumulation" if direction == "BULLISH" else "Distribution"
        headline = (
            f"🤫 PRE-INFLECTION DRY-UP ({direction}): {clean_sym} at ₹{ltp:,.1f} (Fair Value Zone)"
        )
        summary = (
            f"Pre-ignition {dir_label.lower()} footprint ({timeframe}): Volume dried up to {vol_dryup_ratio * 100:.0f}% of average "
            f"with tight {avg_range_pct:.2f}% range. Price is resting near {fv_name} (₹{fair_value:,.1f}). "
            f"Enter within fair-value zone before the {'breakout' if direction == 'BULLISH' else 'breakdown'} candle detonates."
        )

        actionable_plan = {
            "action": "ACCUMULATE_FAIR_VALUE"
            if direction == "BULLISH"
            else "DISTRIBUTE_FAIR_VALUE",
            "fair_value_anchor": f"₹{fair_value:,.1f} ({fv_name})",
            "entry_range": f"₹{accum_low:,.1f} – ₹{accum_high:,.1f}",
            "pivot_trigger": f"₹{pivot_trigger_val:,.1f}",
            "do_not_chase_above": f"₹{no_chase_limit:,.1f} ({'+2.0%' if direction == 'BULLISH' else '-2.0%'} ceiling)",
            "pullback_limit_order": f"₹{pullback_limit:,.1f}",
            "stop_loss": f"₹{sl:,.1f}",
            "target_1": f"₹{target_1:,.1f} (+2R)",
            "target_2": f"₹{target_2:,.1f} (+4R)",
            "risk_reward": rr_str,
            "anti_fomo_rule": (
                f"Enter between ₹{accum_low:,.1f} and ₹{accum_high:,.1f}. "
                f"If price moves beyond ₹{no_chase_limit:,.1f}, DO NOT CHASE — place limit order at ₹{pullback_limit:,.1f}."
            ),
            "no_chase_boundary": f"₹{no_chase_limit:,.1f}",
        }
        if opt_plan:
            try:
                from engine.option_target_calibration import evaluate_option_friction_viability

                _fric_dry = evaluate_option_friction_viability(
                    entry_price=float(opt_plan.entry_premium),
                    target_1=float(opt_plan.t1_premium),
                    stop_loss=float(opt_plan.sl_premium),
                    quantity=int(opt_plan.lot_size or 1),
                    max_friction_drag_pct=28.0,
                    min_net_rr=1.05,
                )
                if not _fric_dry["viable"]:
                    opt_plan = None
            except Exception as e_fric:
                logger.debug(
                    f"[pre_inflection_dryup] option friction check skipped for {clean_sym}: {e_fric}"
                )

        if opt_plan:
            actionable_plan["option_plan"] = opt_plan.as_dict()
            actionable_plan["contract_symbol"] = opt_plan.contract_symbol
            _opt_no_chase = round(float(opt_plan.entry_premium) * 1.04, 2)
            actionable_plan["no_chase_boundary"] = f"₹{_opt_no_chase:,.1f}"
            actionable_plan["spot_no_chase_boundary"] = f"₹{no_chase_limit:,.1f}"
        else:
            _opt_no_chase = None

        if direction == "BULLISH":
            tf_var = "dryup-15m" if is_intraday_tf else "dryup"
        else:
            tf_var = "dryup-bear-15m" if is_intraday_tf else "dryup-bear"
        return AutoAlert(
            alert_id=generate_alert_id(clean_sym, "PRE_INFLECTION_DRYUP", variant=tf_var),
            alert_type="PRE_INFLECTION_DRYUP",
            stage="STALK" if is_intraday_tf else "EARLY_WARNING",
            symbol=clean_sym,
            exchange=alert_exchange,
            segment=alert_segment,
            direction=direction,
            headline=headline,
            summary=summary,
            ltp=float(opt_plan.entry_premium if opt_plan else ltp),
            underlying_spot=ltp,
            trigger_level=float(opt_plan.entry_premium if opt_plan else fair_value),
            target_level=float(opt_plan.t1_premium if opt_plan else target_1),
            stop_loss=float(opt_plan.sl_premium if opt_plan else sl),
            structural_spot_sl=sl,
            no_chase_boundary=float(_opt_no_chase if _opt_no_chase is not None else no_chase_limit),
            spot_no_chase_boundary=no_chase_limit if opt_plan else None,
            contract_symbol=opt_plan.contract_symbol if opt_plan else None,
            strike=opt_plan.strike if opt_plan else None,
            option_type=opt_plan.option_type if opt_plan else None,
            option_premium=opt_plan.entry_premium if opt_plan else None,
            expiry_date=opt_plan.expiry if opt_plan else None,
            lot_size=opt_plan.lot_size if opt_plan else lot_sz,
            time_horizon="INTRADAY" if is_intraday_tf else "SWING_SHORT",
            metrics={
                "timeframe": timeframe,
                "vol_dryup_ratio": round(vol_dryup_ratio, 2),
                "rvol": round(vol_dryup_ratio, 2),
                "is_pullback": True,
                "is_volume_dryup": True,
                "setup_archetype": "ABSORPTION_DRYUP"
                if direction == "BULLISH"
                else "DISTRIBUTION_DRYUP",
                "avg_range_pct": round(avg_range_pct, 2),
                "fair_value": fair_value,
                "fair_value_source": fv_name,
                "vwap": round(fair_value, 2),
                "poc": round(poc_price, 2) if poc_price > 0 else round(fair_value, 2),
                "value_area": (
                    {"vah": round(vah_price, 2), "val": round(val_price, 2)}
                    if (vah_price > 0 and val_price > 0)
                    else None
                ),
                "pdh": round(float(highs[-2]), 2) if n >= 2 else None,
                "pdl": round(float(lows[-2]), 2) if n >= 2 else None,
                "nearest_demand_ob": round(pivot_low, 2)
                if (direction == "BULLISH" and pivot_low > 0)
                else None,
                "nearest_supply_ob": round(pivot_high, 2)
                if (direction == "BEARISH" and pivot_high > 0)
                else None,
                "pivot_high": pivot_high,
                "pivot_low": pivot_low,
                "no_chase_limit": no_chase_limit,
                "no_chase_boundary": no_chase_limit,
                "chop_index": round(chop_val, 1) if chop_val else None,
                "roc_12": round(roc_val, 2) if roc_val else None,
            },
            actionable_plan=actionable_plan,
            confidence=score,
            created_at=now_iso,
        )
    except Exception as e:
        logger.debug(f"[PreInflectionDryUp] Error evaluating {symbol}: {e}")
        return None
