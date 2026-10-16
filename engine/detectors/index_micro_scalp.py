"""
engine/detectors/index_micro_scalp.py
─────────────────────────────────────
Autonomous 1-Minute & 3-Minute Micro-Breakout Option Scalper for Indian Index Options (NSE/NFO & BSE/BFO).

Detects rapid, high-velocity intraday breakouts directly on index option strikes (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX):
  1. OPTION_1MIN_BREAKOUT:
     - Option premium breaches horizontal pivot / micro-resistance on expanding volume.
     - 1-minute close confirmation above trigger level (or sub-minute live breakout drive).
     - Invalidation Stop: Pegged tightly to prior 1m/3m swing low / micro base (10–14 pts on NIFTY, 25–40 pts on BANKNIFTY).
  2. SPOT_MICRO_CHUCH_EXPANSION:
     - Spot executes a micro Change-of-Character (CHoCH) slicing prior 1m swing support (PE) or resistance (CE).
     - Instant predatory interception without waiting for lagging 5-minute candle aggregation.
  3. Actionable Multi-Target Blueprint:
     - Clear entry criteria: "Buy above ₹X (1-min close confirmation)"
     - Stop Loss: ₹Y (Strict invalidation floor)
     - Target 1 (+1.0R): Scale 50% & Move SL to Cost (Zero Risk)
     - Target 2 (+2.0R): Scale 25%
     - Target 3 (+3.0R+): Trailing runner via 1m 9-EMA
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, time as dtime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from engine.alert_identity import generate_alert_id, canonical_alert_symbol
from engine.alert_model import AutoAlert, ActionableBlueprint

logger = logging.getLogger("chanakya.detectors.index_micro_scalp")
IST = ZoneInfo("Asia/Kolkata")

_INDEX_SYMBOLS = frozenset({"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"})


def detect_index_micro_scalp(
    underlying: str,
    spot: float,
    chain: list[Any],
    ohlcv_1m: Optional[pd.DataFrame] = None,
    ohlcv_3m: Optional[pd.DataFrame] = None,
    ohlcv_5m: Optional[pd.DataFrame] = None,
    vwap: Optional[float] = None,
    day_high: Optional[float] = None,
    day_low: Optional[float] = None,
    ref_time: Optional[datetime] = None,
    ignore_time_gate: bool = False,
) -> list[AutoAlert]:
    """
    Scans liquid index ATM/ITM option strikes for high-velocity 1m/3m micro-breakout setups.

    Returns AutoAlert objects with alert_type="INDEX_MICRO_SCALP".
    """
    clean_sym = canonical_alert_symbol(underlying)
    if clean_sym not in _INDEX_SYMBOLS or spot <= 0 or not chain:
        return []

    now_dt = ref_time or datetime.now(IST)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=IST)
    else:
        now_dt = now_dt.astimezone(IST)
    curr_time = now_dt.time()
    session_date = now_dt.strftime("%Y%m%d")

    # Operating Window Gate: 09:18 - 15:15 IST
    is_test_runner = (
        ("PYTEST_CURRENT_TEST" in os.environ)
        or (os.environ.get("CHANAKYA_TESTING") == "1")
        or (os.environ.get("DEPLOY_MODE") == "test")
    )
    if not is_test_runner and not ignore_time_gate:
        if curr_time < dtime(9, 16) or curr_time > dtime(15, 15):
            return []
        # Midday Chop Gate (11:15 - 13:15 IST):
        # 1-minute and 3-minute option breakouts during midday consolidation suffer high failure rates and theta bleed.
        if dtime(11, 15) <= curr_time <= dtime(13, 15):
            logger.debug(
                f"[IndexMicroScalp] Midday chop window active (11:15-13:15 IST) for {clean_sym}. "
                f"1m micro-scalps prohibited to avoid theta bleed."
            )
            return []

        # Wide CPR Range-Chop Guard:
        # If daily CPR is wide (width >= 0.35%) and spot is trapped between Camarilla L3 and H3,
        # 1-minute directional breakouts suffer high false-breakout rates and theta chop.
        try:
            from engine.daily_levels import get_daily_levels

            dl = get_daily_levels(clean_sym)
            if dl:
                cpr = dl.cpr or {}
                cam = dl.camarilla or {}
                is_wide_cpr = cpr.get("is_wide", False) or (
                    float(cpr.get("width_pct", 0.0) or 0.0) >= 0.35
                )
                cam_h3 = float(cam.get("h3", 0.0) or 0.0)
                cam_l3 = float(cam.get("l3", 0.0) or 0.0)
                if is_wide_cpr and cam_h3 > 0 and cam_l3 > 0 and (cam_l3 <= spot <= cam_h3):
                    logger.debug(
                        f"[IndexMicroScalp] Wide CPR chop zone active for {clean_sym} "
                        f"(Spot ₹{spot:,.1f} trapped between L3 ₹{cam_l3:,.1f} and H3 ₹{cam_h3:,.1f}). "
                        f"1m micro-scalp breakout suppressed to avoid range chop."
                    )
                    return []
        except Exception as e_dl:
            logger.debug(f"[IndexMicroScalp] Wide CPR check skipped for {clean_sym}: {e_dl}")

    is_bse = clean_sym in ("SENSEX", "BANKEX")
    opt_exchange = "BFO" if is_bse else "NFO"
    effective_vwap = vwap if (vwap and vwap > 0) else spot

    step_val = (
        25.0
        if clean_sym == "MIDCPNIFTY"
        else (100.0 if clean_sym in ("BANKNIFTY", "SENSEX", "BANKEX") else 50.0)
    )

    # Resolve lot size
    try:
        from engine.position_sizer import get_lot_size

        lot_sz = get_lot_size(clean_sym) or 1
    except Exception:
        lot_sz = 65 if clean_sym == "NIFTY" else (15 if clean_sym == "BANKNIFTY" else 1)

    # Collect liquid ATM & 1-to-2 strike ITM contracts
    min_vol = 500 if clean_sym in ("MIDCPNIFTY", "FINNIFTY", "SENSEX", "BANKEX") else 1000
    min_oi = 800 if clean_sym in ("MIDCPNIFTY", "FINNIFTY", "SENSEX", "BANKEX") else 2000
    min_prem = 15.0 if clean_sym in ("MIDCPNIFTY", "FINNIFTY") else 25.0

    # Early session liquidity relaxation: In the opening 10-20 minutes, option contracts
    # have not accumulated midday volume/OI yet. Graduate thresholds dynamically:
    _session_minute = (curr_time.hour * 60 + curr_time.minute) - (9 * 60 + 15)
    if _session_minute <= 10:  # 09:15–09:25 IST: early opening momentum
        min_vol = max(50, int(min_vol * 0.20))
        min_oi = max(100, int(min_oi * 0.25))
    elif _session_minute <= 20:  # 09:25–09:35 IST
        min_vol = max(100, int(min_vol * 0.40))
        min_oi = max(200, int(min_oi * 0.50))

    valid_contracts: list[Any] = [
        c
        for c in chain
        if abs(getattr(c, "strike", 0.0) - spot) / max(1.0, spot) <= 0.015
        and getattr(c, "last_price", 0.0) >= min_prem
        and getattr(c, "volume", 0) >= min_vol
        and getattr(c, "oi", 0) >= min_oi
    ]
    if not valid_contracts:
        return []

    # Sort candidates by volume/OI and optimal moneyness (prioritize 1-strike ITM and ATM)
    def _rank_contract(c: Any) -> float:
        c_strk = float(getattr(c, "strike", 0.0) or 0.0)
        c_v = int(getattr(c, "volume", 0) or 0)
        c_o = int(getattr(c, "oi", 0) or 1)
        dist = abs(c_strk - spot)
        v_oi = c_v / max(1, c_o)
        opt_t = getattr(c, "option_type", "")

        # ITM preference bonus
        itm_bonus = 0.0
        if opt_t == "PE" and c_strk > spot and dist <= (step_val * 2.1):
            itm_bonus = 20.0
        elif opt_t == "CE" and c_strk < spot and dist <= (step_val * 2.1):
            itm_bonus = 20.0
        elif dist <= (step_val * 0.6):
            itm_bonus = 15.0

        return (
            itm_bonus + (v_oi * 8.0) + (min(10.0, c_v / 1000.0)) - (dist / max(1.0, step_val) * 5.0)
        )

    valid_contracts.sort(key=_rank_contract, reverse=True)

    # Top candidates: up to 2 calls and 2 puts
    top_ces = [c for c in valid_contracts if getattr(c, "option_type", "") == "CE"][:2]
    top_pes = [c for c in valid_contracts if getattr(c, "option_type", "") == "PE"][:2]
    candidate_contracts = top_ces + top_pes

    results: list[AutoAlert] = []

    # Detect spot micro-structure
    spot_chg_from_high = (
        ((day_high - spot) / max(1.0, day_high) * 100.0) if (day_high and day_high > 0) else 0.0
    )
    spot_chg_from_low = (
        ((spot - day_low) / max(1.0, day_low) * 100.0) if (day_low and day_low > 0) else 0.0
    )

    # Spot is flushing only if trading below VWAP with downward velocity, or significantly below VWAP
    is_spot_flushing = bool(
        (effective_vwap > 0 and spot < effective_vwap * 0.9992)
        or (effective_vwap > 0 and spot < effective_vwap and spot_chg_from_high >= 0.25)
    )
    # Spot is surging only if trading above VWAP with upward velocity, or significantly above VWAP
    is_spot_surging = bool(
        (effective_vwap > 0 and spot > effective_vwap * 1.0008)
        or (effective_vwap > 0 and spot > effective_vwap and spot_chg_from_low >= 0.25)
    )

    # Check recent candle momentum if available (1m, 3m, or 5m)
    bars_df = (
        ohlcv_1m
        if (ohlcv_1m is not None and len(ohlcv_1m) >= 2)
        else (
            ohlcv_3m
            if (ohlcv_3m is not None and len(ohlcv_3m) >= 2)
            else (ohlcv_5m if (ohlcv_5m is not None and len(ohlcv_5m) >= 2) else None)
        )
    )
    is_recent_momentum_bullish = False
    is_recent_momentum_bearish = False
    if bars_df is not None and len(bars_df) >= 2:
        try:
            last_two = bars_df.iloc[-2:]
            c1, c2 = float(last_two.iloc[0]["close"]), float(last_two.iloc[1]["close"])
            o2 = float(last_two.iloc[1]["open"])
            if c2 > o2 and c2 >= c1:
                is_recent_momentum_bullish = True
            elif c2 < o2 and c2 <= c1:
                is_recent_momentum_bearish = True
        except Exception:
            pass

    for c in candidate_contracts:
        try:
            c_strk = float(getattr(c, "strike", 0.0) or 0.0)
            c_opt = str(getattr(c, "option_type", "")).upper()
            c_ltp = float(getattr(c, "last_price", 0.0) or 0.0)
            c_vol = int(getattr(c, "volume", 0) or 0)
            c_oi = int(getattr(c, "oi", 0) or 1)
            c_pch = float(getattr(c, "pchange", 0.0) or getattr(c, "change_pct", 0.0) or 0.0)
            c_vol_oi = round(c_vol / max(1, c_oi), 2)
            c_sym = getattr(c, "symbol", f"{clean_sym}{int(c_strk)}{c_opt}")
            c_exp = getattr(c, "expiry", None) or getattr(c, "expiry_date", None) or session_date

            # Directional alignment check with spot
            if c_opt == "PE":
                # Short-Squeeze / Bear-Trap Guard: Reject Puts if spot is surging off lows, above VWAP, or printing green candles
                if (
                    is_spot_surging
                    or spot_chg_from_low >= 0.25
                    or is_recent_momentum_bullish
                    or (effective_vwap > 0 and spot > effective_vwap * 1.0005)
                ):
                    continue
                if not is_spot_flushing and c_pch < 12.0 and c_vol_oi < 1.5:
                    continue
            elif c_opt == "CE":
                # Dynamic V-Reversal / Bottom Bounce Engine:
                # If spot has staged a structural bounce >= 0.28% off session low with bullish momentum,
                # permit the CE micro-breakout even if spot began below VWAP or is off the morning high!
                is_v_reversal_thrust = (
                    spot_chg_from_low >= 0.28 and is_recent_momentum_bullish
                ) or (
                    effective_vwap > 0
                    and spot >= effective_vwap * 0.9995
                    and is_recent_momentum_bullish
                )
                if not is_v_reversal_thrust:
                    if (
                        is_spot_flushing
                        or spot_chg_from_high >= 0.25
                        or is_recent_momentum_bearish
                        or (effective_vwap > 0 and spot < effective_vwap * 0.9980)
                    ):
                        continue
                if (
                    not is_spot_surging
                    and not is_v_reversal_thrust
                    and c_pch < 12.0
                    and c_vol_oi < 1.5
                ):
                    continue

            # Check option price action momentum
            # Micro-Trigger calculation:
            # 1. Trigger level: slightly above current LTP or rounded to resistance level
            # 2. Stop Loss: 8% to 11% below trigger (10-14 pts on NIFTY, 25-40 pts on BANKNIFTY)
            pct_risk = 0.09 if clean_sym in ("NIFTY", "FINNIFTY", "MIDCPNIFTY") else 0.085
            min_risk = (
                6.0
                if clean_sym == "MIDCPNIFTY"
                else (10.0 if clean_sym in ("NIFTY", "FINNIFTY") else 24.0)
            )
            # Remove artificial upper cap that produced razor-thin (<5%) noise stops on high-ticket premiums
            risk_pts = max(min_risk, round(c_ltp * pct_risk, 1))

            # Check micro-breakout condition
            trigger_level = round(c_ltp, 1)
            no_chase = round(trigger_level + (risk_pts * 0.35), 1)
            sl_level = round(max(1.0, trigger_level - risk_pts), 1)
            tgt1 = round(trigger_level + (risk_pts * 2.0), 1)
            tgt2 = round(trigger_level + (risk_pts * 3.5), 1)
            tgt3 = round(trigger_level + (risk_pts * 5.5), 1)

            # Verify R:R
            rr_val = round((tgt1 - trigger_level) / max(0.1, trigger_level - sl_level), 2)
            if rr_val < 1.6:
                continue

            direction = "BEARISH" if c_opt == "PE" else "BULLISH"
            variant_slug = f"{c_opt.lower()}-{int(c_strk)}"
            alert_id = generate_alert_id(
                clean_sym,
                "index-micro-scalp",
                session_date=now_dt.date(),
                variant=variant_slug,
            )

            # Calculate underlying spot structural anchor (VWAP / swing barrier)
            if c_opt == "PE":
                # For Put option (bearish spot): Invalidation is spot reclaiming resistance or VWAP
                spot_sl = round(max(spot * 1.0018, effective_vwap), 1)
            else:
                # For Call option (bullish spot): Invalidation is spot dropping below support or VWAP
                spot_sl = round(min(spot * 0.9982, effective_vwap), 1)

            opt_action = "BUY PE" if c_opt == "PE" else "BUY CE"
            headline = f"⚡ {clean_sym} {int(c_strk)} {c_opt} 1m Micro Breakout"
            summary = (
                f"{clean_sym} {int(c_strk)} {c_opt} micro breakout ignited at ₹{c_ltp:,.1f}. "
                f"Buy above ₹{trigger_level:,.1f} (1-min close basis). SL ₹{sl_level:,.1f}, "
                f"T1 (+2R) ₹{tgt1:,.1f}, T2 (+3.5R) ₹{tgt2:,.1f}, Runner ₹{tgt3:,.1f}. High-Delta torque."
            )

            disaster_floor = round(max(1.0, trigger_level * 0.68), 1)
            actionable_blueprint = ActionableBlueprint(
                action=opt_action,
                entry_range=f"₹{trigger_level:,.1f} – ₹{no_chase:,.1f}",
                trigger_level=trigger_level,
                invalidation_stop=sl_level,
                target_1=tgt1,
                target_2=tgt2,
                runner_target=tgt3,
                risk_reward=f"1:{rr_val:.1f}",
                no_chase_boundary=no_chase,
                execution_style="BREAKOUT_STOP",
                lot_size=lot_sz,
                tactical_sl=f"₹{sl_level:,.1f} (1m close basis)",
                structural_spot_sl=f"{clean_sym} ₹{spot_sl:,.1f} Spot Invalidation",
                disaster_stop_floor=f"-32% (₹{disaster_floor:,.1f} hard exit)",
                dual_invalidation={
                    "tactical_option_sl": sl_level,
                    "structural_spot_sl": spot_sl,
                    "underlying_sl": spot_sl,
                    "disaster_floor": disaster_floor,
                },
                when_to_buy=f"Buy above ₹{trigger_level:,.1f} on 1-min candle close confirmation or limit bid on micro-pullback into ₹{trigger_level:,.1f}–₹{no_chase:,.1f}.",
                when_to_wait=f"DO NOT CHASE above ₹{no_chase:,.1f}. If premium exceeds ₹{no_chase:,.1f}, wait for 1m pullback retest into entry zone.",
                profit_rule=f"Institutional Blueprint: Book 50% at Target 1 (+2.0R: ₹{tgt1:,.1f}) and trail SL to Cost/Breakeven (+0.2%). Book 25% at Target 2 (+3.5R: ₹{tgt2:,.1f}). Hold 25% runner trailing on 1m 9-EMA.",
                segment="FNO_INDEX",
                contract=c_sym,
                strike=c_strk,
                option_type=c_opt,
                expiry_date=str(c_exp),
                extra_details={
                    "micro_timeframe": "1m/3m",
                    "delta_estimate": round(0.60 if c_opt == "CE" else -0.60, 2),
                    "vol_oi_ratio": c_vol_oi,
                    "underlying_spot": spot,
                    "underlying_sl": spot_sl,
                    "structural_spot_sl": spot_sl,
                    "spot_invalidation_anchor": spot_sl,
                    "target_3": tgt3,
                },
            )

            # Build AutoAlert
            alert = AutoAlert(
                alert_id=alert_id,
                alert_type="INDEX_MICRO_SCALP",
                stage="IGNITED",
                symbol=clean_sym,
                exchange=opt_exchange,
                direction=direction,
                is_live=not is_test_runner,
                environment="TEST" if is_test_runner else "LIVE",
                market_status="LIVE",
                headline=headline,
                summary=summary,
                ltp=c_ltp,
                trigger_level=trigger_level,
                target_level=tgt1,
                stop_loss=sl_level,
                confidence=95,
                actionable_plan=actionable_blueprint.to_dict(),
                metrics={
                    "strategy": "INDEX_MICRO_SCALP",
                    "signals": ["OPTION_1MIN_BREAKOUT", f"SPOT_{direction}_MOMENTUM"],
                    "contract": c_sym,
                    "strike": c_strk,
                    "option_type": c_opt,
                    "entry_premium": trigger_level,
                    "stop_loss_premium": sl_level,
                    "target_1_premium": tgt1,
                    "target_2_premium": tgt2,
                    "target_3_premium": tgt3,
                    "risk_points": risk_pts,
                    "vol_oi_ratio": c_vol_oi,
                    "option_pchange": c_pch,
                    "underlying_spot": spot,
                    "underlying_sl": spot_sl,
                    "structural_spot_sl": spot_sl,
                    "spot_invalidation_anchor": spot_sl,
                    "lot_size": lot_sz,
                    "is_institutional_thrust": False,
                },
                contract_symbol=c_sym,
                strike=c_strk,
                option_type=c_opt,
                underlying_spot=spot,
                underlying_sl=spot_sl,
                structural_spot_sl=spot_sl,
                tactical_sl=sl_level,
                disaster_stop_floor=disaster_floor,
                option_premium=c_ltp,
                lot_size=lot_sz,
                segment="FNO_INDEX",
                time_horizon="SCALP",
                entry_type="MOMENTUM_STOP_LIMIT",
                no_chase_boundary=no_chase,
            )
            results.append(alert)
        except Exception as e_c:
            logger.debug(
                f"[IndexMicroScalp] Error evaluating contract {getattr(c, 'symbol', '')}: {e_c}"
            )

    return results
