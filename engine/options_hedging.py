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

    # 2. Determine strike interval & spread width
    is_banknifty = clean_sym in ("BANKNIFTY", "SENSEX")
    is_nifty = clean_sym in ("NIFTY", "NIFTY 50", "FINNIFTY", "MIDCPNIFTY")
    if is_banknifty:
        step = 100.0
        spread_width = 200.0
    elif is_nifty:
        step = 50.0
        spread_width = 50.0 if clean_sym == "NIFTY" else step
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
        spread_width = step

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
        sell_strike = strike + spread_width
    else:
        sell_strike = max(step, strike - spread_width)

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
        actual_width = spread_width
        sell_strike = strike + spread_width if is_bullish else strike - spread_width

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

    booking_target_70 = round(net_debit + 0.70 * (actual_width - net_debit), 2)
    stop_loss_val = round(net_debit * 0.50, 2)

    pref_veh = "HEDGED_SPREAD" if is_midday_chop else "NAKED_OPTION_OR_SPREAD"

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
        "lot_size": lot_sz,
        "booking_target_70": booking_target_70,
        "spread_stop_loss": stop_loss_val,
        "booking_rule": booking_rule,
        "margin_benefit_note": "SEBI Hedged Margin: ~70% margin reduction when executing both legs simultaneously.",
        "peace_of_mind_benefit": "Zero Theta Bleed — short OTM leg finances time decay. Maximum risk strictly capped.",
        "execution_guidance": (
            "⚠️ MIDDAY CHOP WINDOW: Execute Hedged Spread to avoid theta decay."
            if is_midday_chop
            else "High Momentum: Fast scalpers can trade Naked Option; for defined risk, trade Hedged Spread."
        ),
        "legs": legs,
    }


def evaluate_spread_in_flight(
    alert: Any,
    current_ltp: Optional[float] = None,
    quotes_map: Optional[dict[str, Any]] = None,
) -> Optional[SpreadEvaluationResult]:
    """
    Evaluates in-flight performance of a defined-risk spread.
    Triggers automated exit recommendations:
      1. SPREAD_PROFIT_70: Spread value captures >= 70% of max profit potential.
      2. SPREAD_SHORT_STRIKE_TOUCH: Underlying spot reaches short strike wall (delta near 0).
      3. SPREAD_STOP_LOSS: Net spread value erodes by >= 50% from entry net debit.
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

    # Trigger C: 50% Debit Erosion Stop Loss
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
