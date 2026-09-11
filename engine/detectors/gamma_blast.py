"""
Options Gamma Blast detector (Early Warning & Ignited triggers on call/put writer capitulation).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from engine.alert_expiry import classify_expiry_type
from engine.alert_model import AutoAlert

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


def detect_gamma_blast(
    underlying: str,
    spot: float,
    chain: list[Any],
    vwap: Optional[float] = None,
    day_high: Optional[float] = None,
    day_low: Optional[float] = None,
) -> list[AutoAlert]:
    """
    Evaluates options chain for explosive Gamma Blast early-warning and ignite triggers.

    Leading Indicators:
      - Negative Change in OI (Call/Put writers closing positions in panic).
      - Volume / OI Ratio >= 1.8x (massive intraday turnover vs accumulated open interest).
      - Spot price reclaiming or breaking away from intraday VWAP.
      - ATM & near-OTM strike proximity (within ±1.5% of spot).
    """
    if not chain or spot <= 0:
        return []

    alerts: list[AutoAlert] = []
    now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    # Institutional Liquidity & Significance Filters (SEBI / F&O standard):
    is_index = underlying.upper() in (
        "NIFTY",
        "BANKNIFTY",
        "FINNIFTY",
        "MIDCPNIFTY",
        "SENSEX",
        "BANKEX",
    )
    min_strike_oi = 15000 if is_index else 500
    min_abs_oi_change = 3000 if is_index else 150
    min_volume = 10000 if is_index else 500

    ce_contracts = [c for c in chain if getattr(c, "option_type", "") == "CE"]
    pe_contracts = [c for c in chain if getattr(c, "option_type", "") == "PE"]

    effective_vwap = vwap if (vwap and vwap > 0) else spot

    # ── Analyze CALL Gamma Blast (Bullish Upside Explosion) ───
    for c in ce_contracts:
        strike = getattr(c, "strike", 0.0)
        strike_diff_pct = ((strike - spot) / spot) * 100.0
        if not (-0.5 <= strike_diff_pct <= 0.8):
            continue

        oi = getattr(c, "oi", 0)
        oi_change = getattr(c, "oi_change", 0)
        volume = getattr(c, "volume", 0)
        opt_ltp = getattr(c, "last_price", 0.0)
        contract_sym = getattr(c, "symbol", f"{underlying}{int(strike)}CE")

        if oi < min_strike_oi or volume < min_volume or abs(oi_change) < min_abs_oi_change:
            continue

        exp_date = getattr(c, "expiry", "") or None
        if exp_date:
            try:
                exp_str = str(exp_date).split("T")[0].strip()
                exp_dt = None
                for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
                    try:
                        exp_dt = datetime.strptime(exp_str, fmt).date()
                        break
                    except ValueError:
                        continue
                if exp_dt:
                    today_ist = datetime.now(IST).date()
                    dte_days = (exp_dt - today_ist).days
                    max_gamma_dte = 5 if is_index else 35
                    if dte_days > max_gamma_dte:
                        continue
            except Exception:
                pass

        vol_oi_ratio = round(volume / max(1, oi), 2)
        oi_chg_pct = (
            round((oi_change / max(1, oi - oi_change)) * 100.0, 1) if (oi - oi_change) > 0 else 0.0
        )

        is_oi_shedding = oi_change < 0 and (oi_chg_pct <= -8.0 or abs(oi_change) >= 20000)
        is_high_turnover = vol_oi_ratio >= 1.8
        spot_above_vwap = spot >= (effective_vwap * 0.998)

        if is_oi_shedding and is_high_turnover and spot_above_vwap:
            is_ignited = (vol_oi_ratio >= 2.5 and oi_chg_pct <= -15.0) or (
                day_high and spot >= day_high * 0.999
            )
            stage = "IGNITED" if is_ignited else "EARLY_WARNING"
            confidence = min(96, int(65 + (vol_oi_ratio * 7) + min(20, abs(oi_chg_pct) * 0.5)))

            exp_type = classify_expiry_type(exp_date, underlying)

            try:
                from engine.trade_plan import (
                    calculate_trade_plan,
                    calculate_option_execution_plan,
                    get_market_status,
                )
                from engine.position_sizer import get_lot_size

                tp = calculate_trade_plan(
                    symbol=underlying,
                    direction="BUY",
                    spot=spot,
                    timeframe="INTRADAY",
                    exchange="NFO",
                    has_active_blast=is_ignited,
                )

                if tp and not tp.is_asymmetry_viable and not is_ignited:
                    continue

                mkt_status = get_market_status("NFO")
                lot_sz = get_lot_size(underlying)
                opt_plan = (
                    calculate_option_execution_plan(
                        trade_plan=tp,
                        option_type="CE",
                        strike=strike,
                        expiry=exp_date or "",
                        option_ltp=opt_ltp,
                        lot_size=lot_sz,
                    )
                    if opt_ltp > 0 and exp_date
                    else None
                )
                target_premium = opt_plan["t1_premium"] if opt_plan else round(opt_ltp * 1.8, 1)
                sl_premium = (
                    opt_plan["sl_premium"] if opt_plan else round(max(1.0, opt_ltp * 0.7), 1)
                )
                if opt_plan and opt_plan.get("option_rr"):
                    rr_str = opt_plan["option_rr"]
                elif opt_plan and opt_plan.get("t1_premium") and opt_plan.get("sl_premium"):
                    risk_prem = max(0.5, opt_ltp - opt_plan["sl_premium"])
                    reward_prem = max(0.5, opt_plan["t1_premium"] - opt_ltp)
                    rr_str = f"1:{round(reward_prem / risk_prem, 2)}"
                elif tp:
                    rr_str = f"1:{tp.rr_t1}"
                else:
                    rr_str = "1:2"
                t1_pct_str = (
                    f"+{opt_plan['t1_pct']:.1f}%"
                    if (opt_plan and opt_plan.get("t1_pct"))
                    else "+90%"
                )
                sl_pct_str = (
                    f"{opt_plan['sl_pct']:.1f}%"
                    if (opt_plan and opt_plan.get("sl_pct"))
                    else "-30%"
                )
                tp_dict = tp.as_dict()
            except Exception as e_tp:
                logger.debug(
                    "[GammaBlast CE] Dynamic trade plan failed, using conservative fallback: %s",
                    e_tp,
                )
                tp_dict = None
                opt_plan = None
                mkt_status = {"status": "SESSION_CLOSED", "label": "🌙 SESSION CLOSED"}
                target_premium = (
                    round(opt_ltp * 1.8, 1) if opt_ltp > 0 else round(strike * 0.015, 1)
                )
                sl_premium = round(max(1.0, opt_ltp * 0.70), 1) if opt_ltp > 0 else 1.0
                rr_str = "1:2"
                t1_pct_str = "+80%"
                sl_pct_str = "-30%"

            headline = (
                f"⚡ CALL GAMMA BLAST {stage.replace('_', ' ')}: {underlying} {int(strike)} CE"
            )
            summary = (
                f"Call writers shedding {abs(oi_chg_pct):.1f}% OI (ΔOI: {oi_change:,}). "
                f"Vol/OI turnover {vol_oi_ratio}x. Spot ₹{spot:,.1f} holding VWAP. "
                f"{'Explosive short-covering underway!' if is_ignited else 'Early-warning coiling before gamma surge!'}"
            )

            if not opt_ltp or opt_ltp <= 0.0:
                try:
                    from market.quotes import get_ltp
                    fetched = get_ltp(contract_sym)
                    if fetched and fetched > 0:
                        opt_ltp = float(fetched)
                except Exception:
                    pass

            is_authentic_opt = bool(opt_ltp and opt_ltp > 0.0)
            alert_env = "LIVE" if is_authentic_opt else "TEST"

            alerts.append(
                AutoAlert(
                    alert_id=f"aa-gamma-ce-{underlying}-{int(strike)}-{uuid.uuid4().hex[:6]}",
                    alert_type="GAMMA_BLAST",
                    stage=stage,
                    symbol=underlying,
                    exchange="NFO",
                    direction="BULLISH",
                    headline=headline,
                    summary=summary,
                    ltp=opt_ltp or spot,
                    trigger_level=strike,
                    target_level=target_premium,
                    stop_loss=sl_premium,
                    strike=strike,
                    option_type="CE",
                    contract_symbol=contract_sym,
                    expiry_date=exp_date,
                    expiry_type=exp_type,
                    underlying_spot=spot,
                    option_premium=opt_ltp or None,
                    market_status=mkt_status["status"],
                    is_live=is_authentic_opt,
                    environment=alert_env,
                    metrics={
                        "strike": strike,
                        "oi": oi,
                        "oi_change": oi_change,
                        "oi_change_pct": oi_chg_pct,
                        "volume": volume,
                        "vol_oi_ratio": vol_oi_ratio,
                        "spot": spot,
                        "vwap": effective_vwap,
                        "spot_to_vwap_pct": round(
                            ((spot - effective_vwap) / effective_vwap) * 100, 2
                        ),
                    },
                    actionable_plan={
                        "action": "BUY",
                        "instrument": contract_sym,
                        "strike": strike,
                        "option_type": "CE",
                        "expiry_date": exp_date,
                        "expiry_type": exp_type,
                        "underlying_spot": f"₹{spot:,.1f}",
                        "recommended_entry": f"₹{opt_ltp:.1f} (Option Premium)"
                        if opt_ltp
                        else "Market",
                        "target": f"₹{target_premium:.1f} ({t1_pct_str})",
                        "stop_loss": f"₹{sl_premium:.1f} ({sl_pct_str})",
                        "risk_reward": rr_str,
                        "trade_plan": tp_dict,
                        "option_plan": opt_plan,
                        "market_status": mkt_status,
                    },
                    confidence=confidence,
                    created_at=now_iso,
                )
            )

    # ── Analyze PUT Gamma Blast (Bearish Downside Panic) ───────
    for c in pe_contracts:
        strike = getattr(c, "strike", 0.0)
        strike_diff_pct = ((strike - spot) / spot) * 100.0
        if not (-0.8 <= strike_diff_pct <= 0.5):
            continue

        oi = getattr(c, "oi", 0)
        oi_change = getattr(c, "oi_change", 0)
        volume = getattr(c, "volume", 0)
        opt_ltp = getattr(c, "last_price", 0.0)
        contract_sym = getattr(c, "symbol", f"{underlying}{int(strike)}PE")

        if oi < min_strike_oi or volume < min_volume or abs(oi_change) < min_abs_oi_change:
            continue

        exp_date = getattr(c, "expiry", "") or None
        if exp_date:
            try:
                exp_str = str(exp_date).split("T")[0].strip()
                exp_dt = None
                for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
                    try:
                        exp_dt = datetime.strptime(exp_str, fmt).date()
                        break
                    except ValueError:
                        continue
                if exp_dt:
                    today_ist = datetime.now(IST).date()
                    dte_days = (exp_dt - today_ist).days
                    max_gamma_dte = 5 if is_index else 35
                    if dte_days > max_gamma_dte:
                        continue
            except Exception:
                pass

        vol_oi_ratio = round(volume / max(1, oi), 2)
        oi_chg_pct = (
            round((oi_change / max(1, oi - oi_change)) * 100.0, 1) if (oi - oi_change) > 0 else 0.0
        )

        is_oi_shedding = oi_change < 0 and (oi_chg_pct <= -8.0 or abs(oi_change) >= 20000)
        is_high_turnover = vol_oi_ratio >= 1.8
        spot_below_vwap = spot <= (effective_vwap * 1.002)

        if is_oi_shedding and is_high_turnover and spot_below_vwap:
            is_ignited = (vol_oi_ratio >= 2.5 and oi_chg_pct <= -15.0) or (
                day_low and spot <= day_low * 1.001
            )
            stage = "IGNITED" if is_ignited else "EARLY_WARNING"
            confidence = min(96, int(65 + (vol_oi_ratio * 7) + min(20, abs(oi_chg_pct) * 0.5)))

            exp_type = classify_expiry_type(exp_date, underlying)

            try:
                from engine.trade_plan import (
                    calculate_trade_plan,
                    calculate_option_execution_plan,
                    get_market_status,
                )
                from engine.position_sizer import get_lot_size

                tp = calculate_trade_plan(
                    symbol=underlying,
                    direction="SELL",
                    spot=spot,
                    timeframe="INTRADAY",
                    exchange="NFO",
                    has_active_blast=is_ignited,
                )

                if tp and not tp.is_asymmetry_viable and not is_ignited:
                    continue

                mkt_status = get_market_status("NFO")
                lot_sz = get_lot_size(underlying)
                opt_plan = (
                    calculate_option_execution_plan(
                        trade_plan=tp,
                        option_type="PE",
                        strike=strike,
                        expiry=exp_date or "",
                        option_ltp=opt_ltp,
                        lot_size=lot_sz,
                    )
                    if opt_ltp > 0 and exp_date
                    else None
                )
                target_premium = opt_plan["t1_premium"] if opt_plan else round(opt_ltp * 1.8, 1)
                sl_premium = (
                    opt_plan["sl_premium"] if opt_plan else round(max(1.0, opt_ltp * 0.7), 1)
                )
                if opt_plan and opt_plan.get("option_rr"):
                    rr_str = opt_plan["option_rr"]
                elif opt_plan and opt_plan.get("t1_premium") and opt_plan.get("sl_premium"):
                    risk_prem = max(0.5, opt_ltp - opt_plan["sl_premium"])
                    reward_prem = max(0.5, opt_plan["t1_premium"] - opt_ltp)
                    rr_str = f"1:{round(reward_prem / risk_prem, 2)}"
                elif tp:
                    rr_str = f"1:{tp.rr_t1}"
                else:
                    rr_str = "1:2"
                t1_pct_str = (
                    f"+{opt_plan['t1_pct']:.1f}%"
                    if (opt_plan and opt_plan.get("t1_pct"))
                    else "+90%"
                )
                sl_pct_str = (
                    f"{opt_plan['sl_pct']:.1f}%"
                    if (opt_plan and opt_plan.get("sl_pct"))
                    else "-30%"
                )
                tp_dict = tp.as_dict()
            except Exception as e_tp:
                logger.debug(
                    "[GammaBlast PE] Dynamic trade plan failed, using conservative fallback: %s",
                    e_tp,
                )
                tp_dict = None
                opt_plan = None
                mkt_status = {"status": "SESSION_CLOSED", "label": "🌙 SESSION CLOSED"}
                target_premium = (
                    round(opt_ltp * 1.8, 1) if opt_ltp > 0 else round(strike * 0.015, 1)
                )
                sl_premium = round(max(1.0, opt_ltp * 0.70), 1) if opt_ltp > 0 else 1.0
                rr_str = "1:2"
                t1_pct_str = "+80%"
                sl_pct_str = "-30%"

            headline = (
                f"⚡ PUT GAMMA BLAST {stage.replace('_', ' ')}: {underlying} {int(strike)} PE"
            )
            summary = (
                f"Put writers capitulating {abs(oi_chg_pct):.1f}% OI (ΔOI: {oi_change:,}). "
                f"Vol/OI turnover {vol_oi_ratio}x. Spot ₹{spot:,.1f} below VWAP. "
                f"{'Aggressive long put / short spot momentum!' if is_ignited else 'Early-warning coiling before put gamma surge!'}"
            )

            if not opt_ltp or opt_ltp <= 0.0:
                try:
                    from market.quotes import get_ltp
                    fetched = get_ltp(contract_sym)
                    if fetched and fetched > 0:
                        opt_ltp = float(fetched)
                except Exception:
                    pass

            is_authentic_opt = bool(opt_ltp and opt_ltp > 0.0)
            alert_env = "LIVE" if is_authentic_opt else "TEST"

            alerts.append(
                AutoAlert(
                    alert_id=f"aa-gamma-pe-{underlying}-{int(strike)}-{uuid.uuid4().hex[:6]}",
                    alert_type="GAMMA_BLAST",
                    stage=stage,
                    symbol=underlying,
                    exchange="NFO",
                    direction="BEARISH",
                    headline=headline,
                    summary=summary,
                    ltp=opt_ltp or spot,
                    trigger_level=strike,
                    target_level=target_premium,
                    stop_loss=sl_premium,
                    strike=strike,
                    option_type="PE",
                    contract_symbol=contract_sym,
                    expiry_date=exp_date,
                    expiry_type=exp_type,
                    underlying_spot=spot,
                    option_premium=opt_ltp or None,
                    market_status=mkt_status["status"],
                    is_live=is_authentic_opt,
                    environment=alert_env,
                    metrics={
                        "strike": strike,
                        "oi": oi,
                        "oi_change": oi_change,
                        "oi_change_pct": oi_chg_pct,
                        "volume": volume,
                        "vol_oi_ratio": vol_oi_ratio,
                        "spot": spot,
                        "vwap": effective_vwap,
                        "spot_to_vwap_pct": round(
                            ((spot - effective_vwap) / effective_vwap) * 100, 2
                        ),
                    },
                    actionable_plan={
                        "action": "BUY",
                        "instrument": contract_sym,
                        "strike": strike,
                        "option_type": "PE",
                        "expiry_date": exp_date,
                        "expiry_type": exp_type,
                        "underlying_spot": f"₹{spot:,.1f}",
                        "recommended_entry": f"₹{opt_ltp:.1f}" if opt_ltp else "Market",
                        "target": f"₹{target_premium:.1f} ({t1_pct_str})",
                        "stop_loss": f"₹{sl_premium:.1f} ({sl_pct_str})",
                        "risk_reward": rr_str,
                        "trade_plan": tp_dict,
                        "option_plan": opt_plan,
                        "market_status": mkt_status,
                    },
                    confidence=confidence,
                    created_at=now_iso,
                )
            )

    return alerts
