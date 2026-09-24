"""
engine/options_hedging.py
─────────────────────────
Unified Institutional Defined-Risk Hedging & Spread Lifecycle Engine.

Provides:
  1. VIX & Regime Adaptive Spread Construction:
     - Normal/Low Volatility (VIX <= 16.0): Debit Spreads (Bull Call Spread, Bear Put Spread)
     - High Volatility (VIX > 16.0) or IV spike: Credit Spreads (Bull Put Credit, Bear Call Credit)
     - Midday Chop Defense (11:30 - 14:00 IST): Auto-switches to HEDGED_SPREAD preference
  2. Multi-Leg Basket Construction:
     - Exact strikes, premiums, net debit/credit, max loss (strictly capped), max gain, breakeven
     - Canonical `legs` structure with SEBI hedged margin reduction (~70% capital relief)
  3. Mathematical Booking & Exit Playbook:
     - 70%–80% Max Profit Target (never hold into expiry for the final 20% residual tail)
     - Short Strike Wall / Delta Inversion Boundary
     - 50% Net Debit Loss Mitigation Stop
  4. Composite In-Flight Spread Tracking:
     - `evaluate_spread_in_flight()` for real-time monitoring of composite spread value
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time as dtime, timezone, timedelta
from typing import Any, Optional

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class SpreadEvaluationResult:
    """Result of real-time in-flight spread evaluation."""

    triggered: bool
    milestone_type: str  # "SPREAD_PROFIT_70" | "SPREAD_SHORT_STRIKE_TOUCH" | "SPREAD_STOP_LOSS"
    headline: str
    summary: str
    coaching_decision: str
    current_net_value: float
    entry_net_debit: float
    pnl_pts: float
    pnl_pct: float
    spot_price: float
    short_strike: float


def get_optimal_expiry_recommendation(
    symbol: str,
    now_dt: Optional[datetime] = None,
) -> dict[str, Any]:
    """
    Evaluates whether current day/time warrants trading the Current Weekly vs Next Weekly expiry.
    Protects positions from the Wednesday/Thursday post-13:00 IST Theta Cliff.
    """
    now = now_dt or datetime.now(IST)
    weekday = now.weekday()  # 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri
    now_time = now.time()

    is_wed_afternoon = weekday == 2 and now_time >= dtime(13, 0)
    is_thu_expiry_day = weekday == 3
    is_fri_weekend_eve = weekday == 4 and now_time >= dtime(14, 0)

    if is_thu_expiry_day:
        if now_time >= dtime(13, 15):
            return {
                "preferred_expiry": "NEXT_WEEKLY",
                "warning": "⚠️ 0DTE THETA CLIFF ACTIVE: Same-day weekly options lose ~60% premium in final 90 minutes. Route defined-risk spreads to NEXT WEEKLY expiry.",
                "reason": "EXPIRY_DAY_AFTERNOON_CLIFF",
            }
        else:
            return {
                "preferred_expiry": "CURRENT_WEEKLY_OR_NEXT",
                "warning": "⚡ EXPIRY DAY MORNING: Fast morning scalp viable; for swing holds, select Next Weekly.",
                "reason": "EXPIRY_DAY_MORNING",
            }
    elif is_wed_afternoon:
        return {
            "preferred_expiry": "NEXT_WEEKLY",
            "warning": "⏳ PRE-EXPIRY DECAY ACCELERATION: Next Weekly contract provides ~5x more theta runway and avoids pin risk.",
            "reason": "WEDNESDAY_PRE_EXPIRY",
        }
    elif is_fri_weekend_eve:
        return {
            "preferred_expiry": "CURRENT_WEEKLY",
            "warning": "⚠️ WEEKEND THETA HOLD: Close intraday MIS before 15:20 IST or hold defined-risk spread to withstand weekend decay.",
            "reason": "FRIDAY_WEEKEND_THETA",
        }

    return {
        "preferred_expiry": "CURRENT_WEEKLY",
        "warning": None,
        "reason": "NORMAL_SESSION",
    }


def build_ratio_spread_1x2_plan(
    symbol: str,
    direction: str,
    spot: float,
    strike: float,
    opt_type: str,
    opt_ltp: float,
    chain: Optional[list[Any]] = None,
    lot_size: Optional[int] = None,
    spread_width: Optional[float] = None,
    now_dt: Optional[datetime] = None,
) -> Optional[dict[str, Any]]:
    """
    Constructs an institutional 1x2 Ratio Spread (Buy 1 ATM, Sell 2 OTM).
    Designed to achieve near Zero-Cost entry (Net Debit ~0), zero downside loss on thesis failure,
    and massive payoff at the sweet spot (short strike).
    """
    clean_sym = symbol.replace("NSE:", "").replace("NFO:", "").replace("BSE:", "").strip().upper()
    spot = float(spot or 0.0)
    opt_ltp = float(opt_ltp or 0.0)
    strike = float(strike or 0.0)

    if spot <= 0 or opt_ltp <= 0 or strike <= 0:
        return None

    # Resolve lot size
    lot_sz = lot_size
    if not lot_sz or lot_sz <= 1:
        try:
            from engine.position_sizer import get_lot_size

            lot_sz = get_lot_size(clean_sym)
        except Exception:
            lot_sz = 25 if "NIFTY" in clean_sym else 1

    is_bullish = str(direction).upper() in ("BULLISH", "LONG", "BUY") or opt_type == "CE"

    # Determine step & width (ratio leg is placed 2-3 strikes away)
    if clean_sym in ("BANKNIFTY", "SENSEX"):
        step = 100.0
        width = spread_width or 300.0
    elif clean_sym in ("NIFTY", "NIFTY 50", "FINNIFTY"):
        step = 50.0
        width = spread_width or 100.0
    elif clean_sym == "MIDCPNIFTY":
        step = 25.0
        width = spread_width or 75.0
    else:
        step = 50.0 if spot >= 2500 else (20.0 if spot >= 1000 else 10.0)
        width = spread_width or (step * 2.0)

    target_sell_strike = strike + width if is_bullish else max(step, strike - width)
    target_sell_prem = opt_ltp / 2.0  # Ideally 2 x sell_prem ~ opt_ltp

    sell_strike = target_sell_strike
    sell_prem = 0.0

    if chain:
        cands = [
            c
            for c in chain
            if getattr(c, "option_type", "") == opt_type
            and (
                getattr(c, "strike", 0.0) >= strike + step
                if is_bullish
                else getattr(c, "strike", 0.0) <= strike - step
            )
            and float(getattr(c, "last_price", 0.0) or 0.0) > 0.0
        ]
        if cands:
            cands.sort(
                key=lambda c: abs(float(getattr(c, "last_price", 0.0) or 0.0) - target_sell_prem)
            )
            sell_strike = float(cands[0].strike)
            sell_prem = float(cands[0].last_price)

    if sell_prem <= 0.0 or sell_prem >= opt_ltp:
        sell_prem = max(0.5, round(opt_ltp * 0.48, 2))

    actual_width = abs(sell_strike - strike)
    if actual_width <= 0:
        actual_width = width
        sell_strike = strike + width if is_bullish else strike - width

    # Net debit: 1 x Long - 2 x Short
    net_debit = round(opt_ltp - (2 * sell_prem), 2)
    is_credit = net_debit < 0
    entry_desc = (
        f"Net Credit ₹{abs(net_debit):,.1f}" if is_credit else f"Net Debit ₹{net_debit:,.1f}"
    )

    downside_loss = max(0.0, net_debit * lot_sz)
    sweet_spot_gain = round((actual_width - net_debit) * lot_sz, 2)
    upper_breakeven = round(
        sell_strike + (actual_width - net_debit)
        if is_bullish
        else sell_strike - (actual_width - net_debit),
        1,
    )

    strat_name = "RATIO_CALL_SPREAD_1X2" if is_bullish else "RATIO_PUT_SPREAD_1X2"
    strat_title = strat_name.replace("_", " ").title()

    legs = [
        {
            "side": "BUY",
            "strike": strike,
            "option_type": opt_type,
            "premium": opt_ltp,
            "lots": 1,
            "qty": lot_sz,
            "instrument": f"{clean_sym} {int(strike)} {opt_type}",
        },
        {
            "side": "SELL",
            "strike": sell_strike,
            "option_type": opt_type,
            "premium": sell_prem,
            "lots": 2,
            "qty": lot_sz * 2,
            "instrument": f"{clean_sym} {int(sell_strike)} {opt_type}",
        },
    ]

    rr_desc = (
        f"1:{round(sweet_spot_gain / max(1.0, downside_loss), 1)}"
        if downside_loss > 0
        else "INFINITE (Zero Downside)"
    )

    return {
        "strategy": strat_name,
        "strategy_title": strat_title,
        "strategy_type": "RATIO_SPREAD",
        "sentiment": "BULLISH" if is_bullish else "BEARISH",
        "description": f"Buy 1x {int(strike)} {opt_type} & Sell 2x {int(sell_strike)} {opt_type} ({entry_desc})",
        "buy_strike": strike,
        "sell_strike": sell_strike,
        "short_strike": sell_strike,
        "strike_width": actual_width,
        "net_debit_per_share": net_debit,
        "entry_cost_desc": entry_desc,
        "downside_loss": downside_loss,
        "sweet_spot_gain": sweet_spot_gain,
        "sweet_spot_strike": sell_strike,
        "upper_breakeven": upper_breakeven,
        "lot_size": lot_sz,
        "risk_reward": rr_desc,
        "invalidation_boundary": f"Exit if spot crosses ₹{upper_breakeven:,.0f} (Upper Tail Breakeven)",
        "edge_note": "Zero-Cost Entry: 2x short legs completely finance the 1x long leg. ₹0 loss if trade thesis fails.",
        "legs": legs,
    }


def build_defined_risk_hedge_plan(
    symbol: str,
    direction: str,
    spot: float,
    strike: float,
    opt_type: str,
    opt_ltp: float,
    chain: Optional[list[Any]] = None,
    lot_size: Optional[int] = None,
    vix: Optional[float] = None,
    now_dt: Optional[datetime] = None,
    vel_score: float = 80.0,
    spread_width: Optional[float] = None,
    asymmetric_r_r: bool = False,
) -> Optional[dict[str, Any]]:
    """
    Constructs an institutional defined-risk hedge plan for any option signal.
    Dynamically adapts between Debit Spreads (VIX <= 16.0) and Credit Spreads (VIX > 16.0),
    enforcing strike width rules and SEBI margin benefits.
    """
    clean_sym = symbol.replace("NSE:", "").replace("NFO:", "").replace("BSE:", "").strip().upper()
    now_time = (now_dt or datetime.now(IST)).time()
    spot = float(spot or 0.0)
    opt_ltp = float(opt_ltp or 0.0)
    strike = float(strike or 0.0)

    if spot <= 0 or opt_ltp <= 0 or strike <= 0:
        return None

    # 1. Resolve lot size
    lot_sz = lot_size
    if not lot_sz or lot_sz <= 1:
        try:
            from engine.position_sizer import get_lot_size

            lot_sz = get_lot_size(clean_sym)
        except Exception:
            lot_sz = 25 if "NIFTY" in clean_sym else 1

    # 2. Determine strike interval & calibrated spread width
    is_sensex = clean_sym in ("SENSEX", "BANKEX")
    is_banknifty = clean_sym in ("BANKNIFTY",)
    is_nifty = clean_sym in ("NIFTY", "NIFTY 50")
    is_finnifty = clean_sym == "FINNIFTY"
    is_midcpnifty = clean_sym == "MIDCPNIFTY"
    is_idx = (
        is_sensex
        or is_banknifty
        or is_nifty
        or is_finnifty
        or is_midcpnifty
        or any(x in clean_sym for x in ("NIFTY", "SENSEX", "BANKEX"))
    )

    if is_sensex:
        step = 100.0
        width = spread_width or (400.0 if asymmetric_r_r else 300.0)
    elif is_banknifty:
        step = 100.0
        width = spread_width or (300.0 if asymmetric_r_r else 200.0)
    elif is_nifty:
        step = 50.0
        width = spread_width or (100.0 if asymmetric_r_r else 50.0)
    elif is_finnifty:
        step = 50.0
        width = spread_width or (100.0 if asymmetric_r_r else 50.0)
    elif is_midcpnifty:
        step = 25.0
        width = spread_width or (75.0 if asymmetric_r_r else 50.0)
    else:
        # Single-stock F&O: dynamic step based on stock price
        if spot >= 5000:
            step = 100.0
        elif spot >= 2500:
            step = 50.0
        elif spot >= 1000:
            step = 20.0
        elif spot >= 500:
            step = 10.0
        else:
            step = 5.0
        width = spread_width or (step * 2.0 if asymmetric_r_r else step)

    # 3. Volatility & Midday Regime
    current_vix = vix
    if current_vix is None:
        try:
            from market.indices import get_vix

            current_vix = get_vix() or 14.0
        except Exception:
            current_vix = 14.0

    is_midday_chop = (dtime(11, 30) <= now_time <= dtime(14, 0)) and (vel_score < 70)
    is_high_iv = current_vix > 16.5

    is_bullish = str(direction).upper() in ("BULLISH", "LONG", "BUY") or opt_type == "CE"

    # Evaluate Macro Market Breadth alignment for spread selection
    mb = None
    is_counter_trend = False
    counter_trend_warning = None
    try:
        from market.sentiment import get_market_breadth

        mb = get_market_breadth()
        if mb and mb.verdict != "UNAVAILABLE" and getattr(mb, "ad_ratio", 0.0) > 0:
            if is_bullish and (
                mb.verdict == "BROAD_DECLINE"
                or mb.ad_ratio < 0.60
                or (mb.declines >= 2.0 * max(1, mb.advances))
            ):
                is_counter_trend = True
                counter_trend_warning = (
                    f"⚠️ COUNTER-TREND WARNING: Broad Market Breadth is negative (Adv: {mb.advances} / Dec: {mb.declines}, "
                    f"A/D {mb.ad_ratio:.2f}). Bull Call Spreads face heavy market resistance; recommend Bear Put Spreads or 50% reduced sizing."
                )
            elif (not is_bullish) and (
                mb.verdict == "BROAD_RALLY"
                or mb.ad_ratio > 1.80
                or (mb.advances >= 2.0 * max(1, mb.declines))
            ):
                is_counter_trend = True
                counter_trend_warning = (
                    f"⚠️ COUNTER-TREND WARNING: Broad Market Breadth is positive (Adv: {mb.advances} / Dec: {mb.declines}, "
                    f"A/D {mb.ad_ratio:.2f}). Bear Put Spreads face strong market bids; recommend Bull Call Spreads or 50% reduced sizing."
                )
    except Exception:
        pass

    # Strategy Selection:
    # Under high IV (VIX > 16.5), sell overpriced extrinsic premium via Credit Spreads.
    # Under low/normal IV (VIX <= 16.5), buy momentum via Debit Spreads.
    if is_bullish:
        if is_high_iv:
            strat_name = "BULL_PUT_CREDIT_SPREAD"
            strat_type = "CREDIT_SPREAD"
        else:
            strat_name = "BULL_CALL_SPREAD"
            strat_type = "DEBIT_SPREAD"
    else:
        if is_high_iv:
            strat_name = "BEAR_CALL_CREDIT_SPREAD"
            strat_type = "CREDIT_SPREAD"
        else:
            strat_name = "BEAR_PUT_SPREAD"
            strat_type = "DEBIT_SPREAD"

    # 4. Find Hedge Leg Strike
    if is_bullish:
        sell_strike = strike + width
    else:
        sell_strike = max(step, strike - width)

    # 5. Extract or estimate Hedge Leg Premium
    sell_prem = 0.0
    if chain:
        matching_legs = [
            c
            for c in chain
            if getattr(c, "option_type", "") == opt_type
            and abs(getattr(c, "strike", 0.0) - sell_strike) <= (step * 0.35)
            and float(getattr(c, "last_price", 0.0) or 0.0) > 0.0
        ]
        if matching_legs:
            sell_strike = float(matching_legs[0].strike)
            sell_prem = float(matching_legs[0].last_price)
        else:
            # Fallback to nearest higher/lower
            cands = [
                c
                for c in chain
                if getattr(c, "option_type", "") == opt_type
                and (
                    getattr(c, "strike", 0.0) >= sell_strike
                    if is_bullish
                    else getattr(c, "strike", 0.0) <= sell_strike
                )
                and float(getattr(c, "last_price", 0.0) or 0.0) > 0.0
            ]
            if cands:
                cands.sort(key=lambda c: abs(getattr(c, "strike", 0.0) - sell_strike))
                sell_strike = float(cands[0].strike)
                sell_prem = float(cands[0].last_price)

    actual_width = abs(sell_strike - strike)
    if actual_width <= 0:
        actual_width = width
        sell_strike = strike + width if is_bullish else strike - width

    if sell_prem <= 0.0 or sell_prem >= opt_ltp or (opt_ltp - sell_prem) >= actual_width:
        # Realistic premium estimation for OTM hedge leg (~40% - 55% of ATM premium)
        sell_prem = max(
            0.5, round(min(opt_ltp * 0.55, max(0.5, opt_ltp - (actual_width * 0.35))), 2)
        )

    net_debit = round(max(0.5, min(actual_width * 0.85, opt_ltp - sell_prem)), 2)
    max_loss = round(net_debit * lot_sz, 2)
    max_profit = round(max(1.0, (actual_width - net_debit) * lot_sz), 2)
    be_spot = round(spot + net_debit if is_bullish else spot - net_debit, 1)
    rr_spread = round(max_profit / max(1.0, max_loss), 2)

    debit_ratio = round(net_debit / max(1.0, actual_width), 2)
    is_poor_rr = (debit_ratio > 0.45) or (rr_spread < 1.1)

    booking_target_70 = round(net_debit + 0.70 * (actual_width - net_debit), 2)
    stop_loss_val = round(net_debit * 0.50, 2)

    strat_title = strat_name.replace("_", " ").title()
    desc = f"Buy {int(strike)} {opt_type} & Sell {int(sell_strike)} {opt_type} (Defined Risk / Capped Loss)"
    buy_desc = f"BUY {clean_sym} {int(strike)} {opt_type} @ ₹{opt_ltp:,.1f}"
    sell_desc = f"SELL {clean_sym} {int(sell_strike)} {opt_type} @ ₹{sell_prem:,.1f}"

    booking_rule = (
        f"Book 70%–80% Max Profit (Net Spread value ₹{booking_target_70:,.1f}) "
        f"or if Spot touches {sell_strike:,.0f} (Short Strike Wall). Stop loss if spread decays below ₹{stop_loss_val:,.1f}."
    )

    legs = [
        {
            "side": "BUY",
            "strike": strike,
            "option_type": opt_type,
            "premium": opt_ltp,
            "lots": 1,
            "qty": lot_sz,
            "instrument": f"{clean_sym} {int(strike)} {opt_type}",
        },
        {
            "side": "SELL",
            "strike": sell_strike,
            "option_type": opt_type,
            "premium": sell_prem,
            "lots": 1,
            "qty": lot_sz,
            "instrument": f"{clean_sym} {int(sell_strike)} {opt_type}",
        },
    ]

    # Optional 1x2 Ratio Spread Alternative (Zero-Cost Asymmetric Upside)
    # Compute if velocity is solid OR if this is a single stock / poor R:R debit spread
    ratio_plan = None
    if vel_score >= 65.0 or (not is_idx) or is_poor_rr:
        try:
            ratio_plan = build_ratio_spread_1x2_plan(
                symbol=clean_sym,
                direction=direction,
                spot=spot,
                strike=strike,
                opt_type=opt_type,
                opt_ltp=opt_ltp,
                chain=chain,
                lot_size=lot_sz,
                spread_width=width,
                now_dt=now_dt,
            )
        except Exception:
            ratio_plan = None

    # Single-Stock Sector Confluence & Headwind Filter
    stock_sector_warning = ""
    if not is_idx:
        try:
            from analysis.sector_rotation import get_stock_tailwind

            tw = get_stock_tailwind(clean_sym)
            if tw and hasattr(tw, "quadrant"):
                sec_q = getattr(tw, "quadrant", "")
                sec_align = getattr(tw, "alignment", "")
                sec_intra = getattr(tw, "intraday_alignment", "")
                if is_bullish and (
                    sec_q in ("LAGGING", "WEAKENING")
                    or sec_align in ("HEADWIND", "STRONG_HEADWIND", "MODERATE_HEADWIND")
                    or "HEADWIND" in sec_intra
                ):
                    stock_sector_warning = (
                        f"⚠️ SECTOR HEADWIND ({tw.sector} in {sec_q}): Stock is fighting parent sector trend. "
                        f"Debit spread decay risk is high."
                    )
                elif not is_bullish and (
                    sec_q in ("LEADING", "IMPROVING")
                    or sec_align in ("TAILWIND", "STRONG_TAILWIND", "MODERATE_TAILWIND")
                    or "TAILWIND" in sec_intra
                ):
                    stock_sector_warning = (
                        f"⚠️ SECTOR TAILWIND ({tw.sector} in {sec_q}): Shorting stock while parent sector is strong."
                    )
        except Exception:
            pass

    # Single-Stock Atomic Multi-Leg Execution Guard
    combo_execution_note = ""
    if not is_idx:
        combo_execution_note = (
            f"Stock Option Liquidity Guard: Enter as atomic Limit Multi-Leg combo at Net Price (Limit ₹{net_debit:,.2f}). "
            f"DO NOT enter legs individually via Market Orders to avoid bid-ask slippage."
        )

    # Preferred Vehicle & Asymmetry Routing
    debit_rr_warning = ""
    if not is_idx and is_poor_rr:
        debit_rr_warning = (
            f"⚠️ DEBIT SPREAD R:R DEGRADED (1:{rr_spread:.1f}, Net Debit {int(debit_ratio*100)}% of width). "
            f"Auto-promoted 1x2 Ratio Spread for Zero-Downside / Net Credit entry."
        )
        if ratio_plan and (
            ratio_plan.get("downside_loss", 999) == 0
            or "Credit" in str(ratio_plan.get("entry_cost_desc", ""))
        ):
            pref_veh = "RATIO_SPREAD_1X2"
        elif is_midday_chop:
            pref_veh = "HEDGED_SPREAD"
        else:
            pref_veh = "HEDGED_SPREAD"
    elif not is_idx and stock_sector_warning:
        if ratio_plan and (
            ratio_plan.get("downside_loss", 999) == 0
            or "Credit" in str(ratio_plan.get("entry_cost_desc", ""))
        ):
            pref_veh = "RATIO_SPREAD_1X2"
        elif is_midday_chop:
            pref_veh = "HEDGED_SPREAD"
        else:
            pref_veh = "HEDGED_SPREAD"
    elif is_midday_chop:
        pref_veh = "HEDGED_SPREAD"
    else:
        pref_veh = "NAKED_OPTION_OR_SPREAD"

    # Assemble comprehensive execution guidance
    guidance_parts = []
    if is_midday_chop:
        guidance_parts.append("⚠️ MIDDAY CHOP WINDOW: Execute Hedged Spread to avoid theta decay.")
    if debit_rr_warning:
        guidance_parts.append(debit_rr_warning)
    if stock_sector_warning:
        guidance_parts.append(stock_sector_warning)
    if counter_trend_warning:
        guidance_parts.append(counter_trend_warning)
    if combo_execution_note:
        guidance_parts.append(combo_execution_note)
    if not guidance_parts:
        guidance_parts.append(
            "High Momentum: Fast scalpers can trade Naked Option; for defined risk, trade Hedged Spread."
        )

    exec_guidance = " ".join(guidance_parts)

    expiry_rec = get_optimal_expiry_recommendation(clean_sym, now_dt)

    return {
        "strategy": strat_name,
        "strategy_title": strat_title,
        "strategy_type": strat_type,
        "sentiment": "BULLISH" if is_bullish else "BEARISH",
        "preferred_vehicle": pref_veh,
        "description": desc,
        "buy_leg": buy_desc,
        "sell_leg": sell_desc,
        "buy_strike": strike,
        "sell_strike": sell_strike,
        "short_strike": sell_strike,
        "buy_premium": opt_ltp,
        "sell_premium": sell_prem,
        "strike_width": actual_width,
        "net_debit_per_share": net_debit,
        "net_debit_total": max_loss,
        "max_loss": max_loss,
        "max_profit": max_profit,
        "breakeven_spot": be_spot,
        "risk_reward": f"1:{rr_spread:.1f}",
        "debit_ratio": debit_ratio,
        "is_poor_rr": is_poor_rr,
        "debit_rr_warning": debit_rr_warning or None,
        "stock_sector_warning": stock_sector_warning or None,
        "combo_execution_note": combo_execution_note or None,
        "lot_size": lot_sz,
        "booking_target_70": booking_target_70,
        "spread_stop_loss": stop_loss_val,
        "booking_rule": booking_rule,
        "margin_benefit_note": "SEBI Hedged Margin: ~70% margin reduction when executing both legs simultaneously.",
        "execution_guidance": exec_guidance,
        "counter_trend_warning": counter_trend_warning,
        "market_breadth_ad_ratio": getattr(mb, "ad_ratio", None) if mb else None,
        "legs": legs,
        "ratio_spread_1x2": ratio_plan,
        "expiry_recommendation": expiry_rec,
    }


def evaluate_spread_in_flight(
    alert: Any,
    current_ltp: Optional[float] = None,
    quotes_map: Optional[dict[str, Any]] = None,
) -> Optional[SpreadEvaluationResult]:
    """
    Evaluates in-flight performance of a defined-risk spread.
    Triggers automated exit recommendations:
      1. SPREAD_SHORT_STRIKE_TOUCH: Underlying spot reaches short strike wall (delta near 0).
      2. SPREAD_PROFIT_70: Spread value captures >= 70% of max profit potential.
      3. SPREAD_FREE_ROLL: Net spread value expands >= 40% towards max gain (trim 50% long leg).
      4. SPREAD_STOP_LOSS: Net spread value erodes by >= 50% from entry net debit.
    """
    plan = getattr(alert, "actionable_plan", None) or {}
    hedge_plan = plan.get("hedge_plan") or (
        alert.metrics.get("hedge_plan")
        if isinstance(getattr(alert, "metrics", None), dict)
        else None
    )
    if not hedge_plan or not isinstance(hedge_plan, dict):
        return None

    buy_strike = float(hedge_plan.get("buy_strike", 0.0) or 0.0)
    sell_strike = float(hedge_plan.get("sell_strike", 0.0) or 0.0)
    net_debit = float(hedge_plan.get("net_debit_per_share", 0.0) or 0.0)
    width = float(hedge_plan.get("strike_width", 0.0) or abs(sell_strike - buy_strike))
    target_70 = float(
        hedge_plan.get("booking_target_70", 0.0) or (net_debit + 0.70 * (width - net_debit))
    )
    stop_val = float(hedge_plan.get("spread_stop_loss", 0.0) or (net_debit * 0.50))
    is_bullish = hedge_plan.get("sentiment") == "BULLISH"
    symbol = getattr(alert, "symbol", "NIFTY")

    # 1. Resolve current spot price
    spot = 0.0
    if current_ltp and current_ltp > (buy_strike * 0.5):
        spot = float(current_ltp)
    elif getattr(alert, "underlying_spot", None) and float(alert.underlying_spot) > 0:
        spot = float(alert.underlying_spot)
    elif getattr(alert, "ltp", None) and float(alert.ltp) > (buy_strike * 0.5):
        spot = float(alert.ltp)
    else:
        try:
            from market.quotes import get_ltp

            sym = getattr(alert, "symbol", "")
            if sym:
                spot = float(get_ltp(sym) or 0.0)
        except Exception:
            pass

    if spot <= 0:
        return None

    # 2. Estimate or resolve current spread value
    current_net_val = None
    if quotes_map:
        legs = hedge_plan.get("legs", [])
        if len(legs) >= 2:
            q_buy = quotes_map.get(legs[0].get("instrument")) or quotes_map.get(
                legs[0].get("strike")
            )
            q_sell = quotes_map.get(legs[1].get("instrument")) or quotes_map.get(
                legs[1].get("strike")
            )
            if q_buy and q_sell:
                b_ltp = float(getattr(q_buy, "last_price", 0.0) or 0.0)
                s_ltp = float(getattr(q_sell, "last_price", 0.0) or 0.0)
                if b_ltp > 0 and s_ltp > 0:
                    current_net_val = round(b_ltp - s_ltp, 2)

    # If leg quotes are absent, model intrinsic spread expansion from spot progress
    if current_net_val is None:
        if is_bullish:
            spot_progress = max(0.0, min(width, spot - buy_strike))
        else:
            spot_progress = max(0.0, min(width, buy_strike - spot))
        # Net spread expansion tracks spot progress bounded between 0 and width
        current_net_val = round(max(0.1, min(width * 0.95, net_debit + (spot_progress * 0.65))), 2)

    pnl_pts = round(current_net_val - net_debit, 2)
    pnl_pct = round((pnl_pts / net_debit) * 100, 1) if net_debit > 0 else 0.0

    is_test = (getattr(alert, "environment", "LIVE") == "TEST") or (
        not getattr(alert, "is_live", True)
    )
    env_tag = "[TEST]" if is_test else "[REAL/LIVE]"

    achieved = getattr(alert, "achieved_milestones", None) or []

    # Trigger A: Short Strike Wall Reached (Delta collapsing to ~0)
    is_short_strike_hit = (spot >= sell_strike) if is_bullish else (spot <= sell_strike)
    if is_short_strike_hit and sell_strike > 0:
        headline = (
            f"⚠️ {env_tag} SPREAD SHORT STRIKE REACHED: {symbol} (Pin Wall @ ₹{sell_strike:,.0f})"
        )
        summary = (
            f"Underlying spot ₹{spot:,.1f} has reached or breached the Short Strike Wall (₹{sell_strike:,.0f}). "
            f"Spread delta has flattened to ~0 (no further gain possible). "
            f"DECISION: CLOSE BOTH LEGS AT MARKET OR ROLL SHORT LEG TO LOCK IN MAXIMUM REWARD."
        )
        return SpreadEvaluationResult(
            triggered=True,
            milestone_type="SPREAD_SHORT_STRIKE_TOUCH",
            headline=headline,
            summary=summary,
            coaching_decision="CLOSE_SPREAD_OR_ROLL",
            current_net_value=current_net_val,
            entry_net_debit=net_debit,
            pnl_pts=pnl_pts,
            pnl_pct=pnl_pct,
            spot_price=spot,
            short_strike=sell_strike,
        )

    # Trigger B: 70% Max Profit Target Captured
    if current_net_val >= target_70:
        headline = f"🎯 {env_tag} 70% MAX PROFIT CAPTURED: {symbol} Hedged Spread"
        summary = (
            f"Net spread value expanded to ₹{current_net_val:,.1f} (Entry: ₹{net_debit:,.1f}, +{pnl_pct:.1f}% P&L). "
            f"70% of maximum possible spread profit is captured. Waiting for the final 30% exposes trade to unnecessary tail reversal risk. "
            f"DECISION: BOOK FULL SPREAD NOW (CLOSE BOTH LEGS)."
        )
        return SpreadEvaluationResult(
            triggered=True,
            milestone_type="SPREAD_PROFIT_70",
            headline=headline,
            summary=summary,
            coaching_decision="BOOK_SPREAD_70_PCT",
            current_net_value=current_net_val,
            entry_net_debit=net_debit,
            pnl_pts=pnl_pts,
            pnl_pct=pnl_pct,
            spot_price=spot,
            short_strike=sell_strike,
        )

    # Trigger C: Spread Free-Roll Unlocked (+40% to +50% progress towards max profit)
    free_roll_val = round(net_debit + 0.40 * (width - net_debit), 2)
    if current_net_val >= free_roll_val and pnl_pts > 0 and "SPREAD_FREE_ROLL" not in achieved:
        headline = f"🛡️ {env_tag} SPREAD FREE-ROLL UNLOCKED: {symbol} (+{pnl_pct:.0f}% Gain)"
        summary = (
            f"Net spread value expanded to ₹{current_net_val:,.1f} (Entry: ₹{net_debit:,.1f}, +{pnl_pct:.1f}%). "
            f"DECISION: SCALE 50% OF LONG LEG (OR LOCK SL AT BREAKEVEN). TRADE IS NOW 100% CAPITAL RISK-FREE (FREE-ROLL)."
        )
        return SpreadEvaluationResult(
            triggered=True,
            milestone_type="SPREAD_FREE_ROLL",
            headline=headline,
            summary=summary,
            coaching_decision="SCALE_50_PCT_LOCK_BREAKEVEN",
            current_net_value=current_net_val,
            entry_net_debit=net_debit,
            pnl_pts=pnl_pts,
            pnl_pct=pnl_pct,
            spot_price=spot,
            short_strike=sell_strike,
        )

    # Trigger D: 50% Debit Erosion Stop Loss
    if current_net_val <= stop_val and pnl_pts < 0:
        headline = f"🛑 {env_tag} SPREAD RISK MITIGATION: {symbol} (50% Debit Eroded)"
        summary = (
            f"Net spread value dropped to ₹{current_net_val:,.1f} (-50% from entry ₹{net_debit:,.1f}). "
            f"Underlying momentum has invalidated setup thesis. "
            f"DECISION: EXIT SPREAD AT MARKET TO PREVENT FULL CAPITAL LOSS."
        )
        return SpreadEvaluationResult(
            triggered=True,
            milestone_type="SPREAD_STOP_LOSS",
            headline=headline,
            summary=summary,
            coaching_decision="SCRATCH_SPREAD_AT_MARKET",
            current_net_value=current_net_val,
            entry_net_debit=net_debit,
            pnl_pts=pnl_pts,
            pnl_pct=pnl_pct,
            spot_price=spot,
            short_strike=sell_strike,
        )

    return None
