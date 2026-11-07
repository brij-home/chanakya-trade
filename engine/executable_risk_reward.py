"""
engine/executable_risk_reward.py
────────────────────────────────
Institutional Multi-Horizon Risk:Reward & Opportunity Concentration Engine.

Institutional Mandates (S05):
1. Multi-Horizon R:R Dimensional Sanctity:
   Explicitly isolates and stores the 5 distinct R:R dimensions:
     - Underlying Structural R: (Target - Entry) / (Entry - Stop) in spot underlying space.
     - Option Premium Scenario R: Modeled premium target/stop scenario.
     - Spread Expiry Payoff R: Defined-risk vertical spread max reward / max debit.
     - Executable Indicative R: Net R:R after bid-ask spread, slippage, and dated statutory charges.
     - Observed Outcome R: Post-trade realized R:R.
2. Realistic Friction Modeling:
   - Long entry priced conservatively from Ask (or entry + slippage).
   - Modeled future exit target/stop scenarios with explicit spread/slippage assumptions (never current quote).
   - Full statutory charges calculated via engine.charges (STT, GST, Exchange, SEBI, Stamp Duty, Brokerage).
   - Gap Stress Scenario: Models 1.5x stop gap risk.
3. Opportunity Concentration & Ranking:
   - Prioritizes NSE/BSE Index Options first, then liquid stock F&O.
   - Deduplicates correlated index/constituent signals into unified risk episodes.
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Optional

from engine.alert_identity import canonical_alert_symbol
from engine.charges import SegmentType, calculate_transaction_charges
from engine.position_sizer import resolve_payoff_orientation

logger = logging.getLogger("engine.executable_rr")


@dataclass
class MultiHorizonRRMetrics:
    """Distinctly stores the 5 R:R dimensions without mathematical mixing."""

    underlying_structural_rr: Optional[float] = None
    option_premium_scenario_rr: Optional[float] = None
    spread_expiry_payoff_rr: Optional[float] = None
    executable_indicative_rr: Optional[float] = None
    observed_outcome_rr: Optional[float] = None

    # Granular Friction & Stress Accounting
    entry_ask: float = 0.0
    exit_bid: float = 0.0
    spread_friction_pts: float = 0.0
    statutory_charges_total: Optional[float] = None
    statutory_charges_rupees: Optional[float] = None
    slippage_buffer_pts: float = 0.0
    gap_stress_risk_pts: float = 0.0
    sensitivity_bands: dict[str, Optional[float]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if (
            d.get("statutory_charges_rupees") is None
            and d.get("statutory_charges_total") is not None
        ):
            d["statutory_charges_rupees"] = d["statutory_charges_total"]
        if (
            d.get("statutory_charges_total") is None
            and d.get("statutory_charges_rupees") is not None
        ):
            d["statutory_charges_total"] = d["statutory_charges_rupees"]
        return d


def calculate_net_executable_rr(
    symbol: Optional[str] = None,
    direction: Optional[str] = None,
    entry_price: Optional[float] = None,
    stop_loss: Optional[float] = None,
    target_price: Optional[float] = None,
    quantity: int = 1,
    segment: Optional[str] = None,
    payoff_type: Optional[str] = None,
    bid: Optional[float] = None,
    ask: Optional[float] = None,
    slippage_bps: float = 25.0,
    trade_date: Optional[str] = None,
    underlying_entry: Optional[float] = None,
    underlying_sl: Optional[float] = None,
    underlying_target: Optional[float] = None,
    spread_max_profit: Optional[float] = None,
    spread_max_loss: Optional[float] = None,
    alert: Optional[Any] = None,
    quote_snapshot: Optional[dict[str, Any]] = None,
    current_entry_book: Optional[dict[str, Any]] = None,
    modeled_target_exit_book: Optional[dict[str, Any]] = None,
    modeled_target_bid: Optional[float] = None,
    modeled_target_ask: Optional[float] = None,
) -> MultiHorizonRRMetrics:
    """Computes all 5 R:R dimensions factoring in bid-ask friction, dated statutory taxes,

    and gap stress scenarios. Supports direct invocation with alert instance or parameters.
    """
    if alert is not None:
        symbol = symbol or getattr(alert, "contract_symbol", None) or getattr(alert, "symbol", "")
        direction = direction or getattr(alert, "direction", "BULLISH")
        is_opt = bool(
            getattr(alert, "contract_symbol", None)
            or getattr(alert, "option_premium", None) is not None
            or getattr(alert, "alert_type", None) in ("OPTIONS_MOMENTUM", "OPTION_WRITE")
        )
        if is_opt and getattr(alert, "option_premium", None) is not None:
            entry_price = entry_price if entry_price is not None else float(alert.option_premium)
            if stop_loss is None and getattr(alert, "option_stop_loss", None) is not None:
                stop_loss = float(alert.option_stop_loss)
            if target_price is None and getattr(alert, "option_target", None) is not None:
                target_price = float(alert.option_target)
        else:
            entry_price = (
                entry_price
                if entry_price is not None
                else (
                    float(alert.trigger_level)
                    if getattr(alert, "trigger_level", None) is not None
                    else (
                        float(alert.entry_price)
                        if getattr(alert, "entry_price", None) is not None
                        else (float(alert.ltp) if getattr(alert, "ltp", None) is not None else None)
                    )
                )
            )
            if stop_loss is None and getattr(alert, "stop_loss", None) is not None:
                stop_loss = float(alert.stop_loss)
            if target_price is None and getattr(alert, "target_level", None) is not None:
                target_price = float(alert.target_level)

        canonical_seg = getattr(alert, "segment", None) or ("OPTIONS" if is_opt else "EQUITY")
        segment = segment or canonical_seg
        if payoff_type is None:
            if getattr(alert, "alert_type", None) == "OPTION_WRITE":
                payoff_type = "SHORT_OPTION"
            elif is_opt:
                payoff_type = "LONG_OPTION"

        if quote_snapshot and isinstance(quote_snapshot, dict):
            bid = bid if bid is not None else quote_snapshot.get("bid")
            ask = ask if ask is not None else quote_snapshot.get("ask")
        elif hasattr(alert, "_live_quote_snapshot") and isinstance(
            alert._live_quote_snapshot, dict
        ):
            bid = bid if bid is not None else alert._live_quote_snapshot.get("bid")
            ask = ask if ask is not None else alert._live_quote_snapshot.get("ask")

    if current_entry_book and isinstance(current_entry_book, dict):
        bid = current_entry_book.get("bid", bid)
        ask = current_entry_book.get("ask", ask)

    if modeled_target_exit_book and isinstance(modeled_target_exit_book, dict):
        modeled_target_bid = modeled_target_exit_book.get("bid", modeled_target_bid)
        modeled_target_ask = modeled_target_exit_book.get("ask", modeled_target_ask)

    symbol = str(symbol or "")
    direction = str(direction or "BULLISH")

    # 0. Validate Numeric Sanity
    for name, val in [
        ("entry_price", entry_price),
        ("stop_loss", stop_loss),
        ("target_price", target_price),
    ]:
        if not isinstance(val, (int, float)) or not math.isfinite(val) or val <= 0:
            return MultiHorizonRRMetrics()

    p_entry = float(entry_price)
    p_sl = float(stop_loss)
    p_tgt = float(target_price)

    # Resolve shared payoff coordinate orientation (LONG premium vs SHORT premium)
    default_payoff = "LONG_OPTION" if segment in ("OPTIONS", "NFO", "BFO") else "LONG_ASSET"
    coord_orientation = resolve_payoff_orientation(
        payoff_type=payoff_type or default_payoff,
        direction=direction,
        symbol=symbol,
    )
    is_long_coord = coord_orientation == "LONG"

    # Validate instrument anchors strictly
    if is_long_coord:
        valid_anchors = p_sl < p_entry < p_tgt
        gross_reward = p_tgt - p_entry if valid_anchors else 0.0
        gross_risk = p_entry - p_sl if valid_anchors else 0.0
    else:  # SHORT coord (credit / sold option / short cash)
        valid_anchors = p_tgt < p_entry < p_sl
        gross_reward = p_entry - p_tgt if valid_anchors else 0.0
        gross_risk = p_sl - p_entry if valid_anchors else 0.0

    # 1. Underlying Structural R:R (only when underlying levels are explicitly supplied)
    u_rr = None
    if underlying_entry is not None and underlying_sl is not None and underlying_target is not None:
        try:
            u_e = float(underlying_entry)
            u_s = float(underlying_sl)
            u_t = float(underlying_target)
            if (
                math.isfinite(u_e)
                and math.isfinite(u_s)
                and math.isfinite(u_t)
                and u_e > 0
                and u_s > 0
                and u_t > 0
            ):
                d_up = str(direction).upper().strip()
                is_u_bull = d_up in ("BULLISH", "BUY", "LONG")
                if is_u_bull and u_s < u_e < u_t:
                    u_risk = u_e - u_s
                    u_reward = u_t - u_e
                    u_rr = round(u_reward / u_risk, 2) if u_risk > 0 else None
                elif (not is_u_bull) and u_t < u_e < u_s:
                    u_risk = u_s - u_e
                    u_reward = u_e - u_t
                    u_rr = round(u_reward / u_risk, 2) if u_risk > 0 else None
        except Exception:
            u_rr = None

    # 2. Option Premium Scenario R:R
    opt_scenario_rr = None
    if segment in ("OPTIONS", "NFO", "BFO"):
        if valid_anchors and gross_risk > 0 and gross_reward > 0:
            opt_scenario_rr = round(gross_reward / gross_risk, 2)

    # 3. Spread Expiry Payoff R:R
    spread_payoff_rr = None
    if spread_max_profit is not None and spread_max_loss is not None:
        try:
            s_prof = float(spread_max_profit)
            s_loss = float(spread_max_loss)
            if math.isfinite(s_prof) and math.isfinite(s_loss) and s_loss > 0 and s_prof > 0:
                spread_payoff_rr = round(s_prof / s_loss, 2)
        except Exception:
            spread_payoff_rr = None

    # 4. Executable Indicative R:R after Friction
    # If quantity <= 0 or anchors invalid, executable R is not applicable
    if quantity <= 0 or not math.isfinite(quantity) or not valid_anchors:
        return MultiHorizonRRMetrics(
            underlying_structural_rr=u_rr,
            option_premium_scenario_rr=opt_scenario_rr,
            spread_expiry_payoff_rr=spread_payoff_rr,
            executable_indicative_rr=None,
            statutory_charges_total=None,
            statutory_charges_rupees=None,
        )

    qty = int(quantity)
    slip_mult = slippage_bps / 10000.0
    slip_pts = round(p_entry * slip_mult, 2)

    # Current entry quote from current book and future exit scenario modeling
    if is_long_coord:
        eff_entry = (
            float(ask)
            if (ask is not None and math.isfinite(ask) and ask >= p_entry)
            else (p_entry + slip_pts)
        )
        # Future target exit: if modeled_target_bid explicitly provided or if bid was provided closer to target than entry
        if modeled_target_bid is not None and math.isfinite(modeled_target_bid):
            eff_target_exit = float(modeled_target_bid)
        elif (
            bid is not None
            and math.isfinite(bid)
            and abs(float(bid) - p_tgt) < abs(float(bid) - p_entry)
        ):
            eff_target_exit = float(bid)
        else:
            eff_target_exit = p_tgt - (p_tgt * slip_mult)
        eff_stop_exit = p_sl - (p_sl * slip_mult)
        side_entry = "BUY"
        side_exit = "SELL"
    else:
        eff_entry = (
            float(bid)
            if (bid is not None and math.isfinite(bid) and bid <= p_entry)
            else (p_entry - slip_pts)
        )
        # Future target exit: if modeled_target_ask explicitly provided or if ask was provided closer to target than entry
        if modeled_target_ask is not None and math.isfinite(modeled_target_ask):
            eff_target_exit = float(modeled_target_ask)
        elif (
            ask is not None
            and math.isfinite(ask)
            and abs(float(ask) - p_tgt) < abs(float(ask) - p_entry)
        ):
            eff_target_exit = float(ask)
        else:
            eff_target_exit = p_tgt + (p_tgt * slip_mult)
        eff_stop_exit = p_sl + (p_sl * slip_mult)
        side_entry = "SELL"
        side_exit = "BUY"

    spread_fric = abs(eff_entry - p_entry)

    # Calculate statutory charges for entry, target-exit, and stop-exit separately
    charge_seg: SegmentType = (
        "OPTIONS" if segment in ("OPTIONS", "NFO", "BFO") else "EQUITY_INTRADAY"
    )
    tot_charges = None
    exec_rr = None

    t_date = None
    if trade_date:
        if isinstance(trade_date, str):
            try:
                t_date = date.fromisoformat(trade_date[:10])
            except Exception:
                t_date = None
        elif isinstance(trade_date, date):
            t_date = trade_date

    try:
        c_entry = calculate_transaction_charges(
            price=eff_entry, quantity=qty, segment=charge_seg, side=side_entry, trade_date=t_date
        )
        c_target_exit = calculate_transaction_charges(
            price=eff_target_exit,
            quantity=qty,
            segment=charge_seg,
            side=side_exit,
            trade_date=t_date,
        )
        c_stop_exit = calculate_transaction_charges(
            price=eff_stop_exit, quantity=qty, segment=charge_seg, side=side_exit, trade_date=t_date
        )
        target_charges = float(c_entry.total_charges + c_target_exit.total_charges)
        stop_charges = float(c_entry.total_charges + c_stop_exit.total_charges)
        tot_charges = target_charges

        # Calculate exact net cash flows in rupees
        if is_long_coord:
            net_target_gain = (eff_target_exit - eff_entry) * qty - target_charges
            net_stop_loss = (eff_entry - eff_stop_exit) * qty + stop_charges
        else:
            net_target_gain = (eff_entry - eff_target_exit) * qty - target_charges
            net_stop_loss = (eff_stop_exit - eff_entry) * qty + stop_charges

        if net_stop_loss > 0:
            exec_rr = round(max(0.0, net_target_gain) / net_stop_loss, 2)
        else:
            exec_rr = 0.0
    except Exception as e_charge:
        logger.warning(f"[executable_rr] Charges calculation unavailable: {e_charge}")
        tot_charges = None
        exec_rr = None

    # Gap Stress Scenario: 1.5x stop loss distance under market shock
    gap_stress_risk = round(gross_risk * 1.5, 2)

    # Sensitivity Bands for Execution Slippage (10 bps, 25 bps, 50 bps)
    sensitivity: dict[str, Optional[float]] = {}
    if tot_charges is not None:
        charges_per_unit = tot_charges / qty
        for bps in (10.0, 25.0, 50.0):
            s_pts = p_entry * (bps / 10000.0)
            s_rew = max(0.0, gross_reward - (s_pts * 2.0) - charges_per_unit)
            s_rsk = max(0.05, gross_risk + (s_pts * 2.0) + charges_per_unit)
            sensitivity[f"{int(bps)}bps_slippage_rr"] = round(s_rew / s_rsk, 2)
    else:
        for bps in (10.0, 25.0, 50.0):
            sensitivity[f"{int(bps)}bps_slippage_rr"] = None

    tot_charges_val = round(tot_charges, 2) if tot_charges is not None else None
    return MultiHorizonRRMetrics(
        underlying_structural_rr=u_rr,
        option_premium_scenario_rr=opt_scenario_rr,
        spread_expiry_payoff_rr=spread_payoff_rr,
        executable_indicative_rr=exec_rr,
        observed_outcome_rr=None,
        entry_ask=eff_entry,
        exit_bid=eff_target_exit,
        spread_friction_pts=round(spread_fric, 2),
        statutory_charges_total=tot_charges_val,
        statutory_charges_rupees=tot_charges_val,
        slippage_buffer_pts=slip_pts,
        gap_stress_risk_pts=gap_stress_risk,
        sensitivity_bands=sensitivity,
    )


def rank_desk_opportunities(
    candidates: list[dict[str, Any]],
    active_portfolio_exposures: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """Ranks desk candidates prioritizing:

    1. Index Options priority (NIFTY, BANKNIFTY, SENSEX, FINNIFTY)
    2. Non-correlated unique exposure (avoiding competing tickets on same underlying)
    3. Net executable indicative R:R
    4. Conviction tier (APEX > HIGH > DEFINED_RISK)
    """
    from engine.option_resolver import is_index_symbol

    active_exposures = {
        canonical_alert_symbol(s).upper() for s in (active_portfolio_exposures or [])
    }

    def sort_key(c: dict[str, Any]) -> tuple[int, int, float, float]:
        sym = canonical_alert_symbol(c.get("symbol", "")).upper()
        is_idx = 1 if is_index_symbol(sym) else 0

        # Exposure penalty: if portfolio already holds open exposure in this symbol, penalize new entries
        has_exp = 0 if sym in active_exposures else 1

        tier_str = str(c.get("conviction_tier", "") or "").upper()
        tier_score = 3 if "APEX" in tier_str else (2 if "HIGH" in tier_str else 1)

        net_rr = float(c.get("executable_indicative_rr") or c.get("rr") or 0.0)

        # Sort descending by (is_index, not_over_exposed, tier_score, net_rr)
        return (is_idx, has_exp, tier_score, net_rr)

    return sorted(candidates, key=sort_key, reverse=True)
