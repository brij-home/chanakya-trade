"""
analysis/event_volatility.py
────────────────────────────
Event-volatility research context for earnings catalysts.

This module can construct an illustrative leg shape only when an IV-rank input
is explicitly supplied. It has no integrated historical option-IV source or
source-qualified leg-premium payoff model, so its output is always
RESEARCH_ONLY and cannot be used as a trade recommendation or conviction bonus.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Literal, Optional

from market.instruments import format_strike

logger = logging.getLogger("analysis.event_volatility")
from config.constants import IST_ZONE as IST
from market.earnings import _NIFTY50_EARNINGS_MONTHS, get_pre_earnings_iv


@dataclass
class OptionLeg:
    action: Literal["BUY", "SELL"]
    option_type: Literal["CE", "PE"]
    strike: float
    description: str


@dataclass
class EventHedgePlan:
    symbol: str
    event_type: str  # "EARNINGS" | "RBI_POLICY" | "UNION_BUDGET"
    hours_to_event: float
    iv_rank: Optional[float]
    historical_avg_move_pct: Optional[float]
    volatility_regime: str  # "OVERPRICED_IV" | "UNDERPRICED_IV" | "NEUTRAL"
    recommended_strategy: str  # "BULL_CALL_SPREAD" | "BEAR_PUT_SPREAD" | "IRON_CONDOR" | "LONG_STRADDLE" | "PEAD_ORB_DRIFT"
    preferred_vehicle: str
    legs: list[OptionLeg] = field(default_factory=list)
    status: str = "RESEARCH_ONLY"
    actionable: bool = False
    iv_crush_neutralized: bool = False
    max_risk_pts: Optional[float] = None
    max_reward_pts: Optional[float] = None
    reward_risk_ratio: Optional[float] = None
    rationale: str = ""
    evaluated_at: str = field(
        default_factory=lambda: datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["legs"] = [asdict(leg) for leg in self.legs]
        return d


def detect_upcoming_earnings_window(
    symbol: str,
    ref_date: Optional[date] = None,
) -> tuple[bool, float, str]:
    """
    Checks whether the symbol is in an active quarterly earnings window (<= 48 hours).
    Returns: (is_earnings_window, hours_to_event, event_date_str)
    """
    clean_sym = symbol.upper().replace("NSE:", "").replace("BSE:", "").strip()
    cur_d = ref_date or datetime.now(IST).date()

    # 1. Check known historical reporting month schedule
    typical_months = _NIFTY50_EARNINGS_MONTHS.get(clean_sym, [])
    is_typical_month = cur_d.month in typical_months

    # If stock typically reports this month and day is between 10th and 28th
    if is_typical_month and 10 <= cur_d.day <= 28:
        # Approximate 24 hours window for current session
        return True, 24.0, cur_d.isoformat()

    return False, 999.0, ""


def evaluate_event_volatility_strategy(
    symbol: str,
    spot: float,
    direction: str = "BULLISH",
    hours_to_event: Optional[float] = None,
    iv_rank_override: Optional[float] = None,
) -> Optional[EventHedgePlan]:
    """
    Creates a non-actionable structure illustration when IV rank is supplied.
    """
    if spot <= 0:
        return None

    clean_sym = symbol.upper().replace("NSE:", "").replace("BSE:", "").strip()
    is_bullish = direction.upper() in ("BULLISH", "BUY", "LONG")

    # 1. Resolve event timing
    is_event, h_to_event, event_date = detect_upcoming_earnings_window(clean_sym)
    effective_hours = (
        hours_to_event if hours_to_event is not None else (h_to_event if is_event else 999.0)
    )

    if effective_hours > 48.0 and hours_to_event is None:
        return None  # No upcoming binary event within 48h

    # 2. Extract IV metrics. An explicit override is only a research/test input;
    # it cannot make this plan actionable without source-qualified option quotes.
    iv_data = (
        {"iv_rank": iv_rank_override, "avg_earnings_move": None}
        if iv_rank_override is not None
        else get_pre_earnings_iv(clean_sym)
    )
    raw_iv_rank = iv_data.get("iv_rank")
    try:
        iv_rank = float(raw_iv_rank) if raw_iv_rank is not None else None
    except (TypeError, ValueError):
        iv_rank = None
    if iv_rank is None or not 0 <= iv_rank <= 100:
        logger.info(
            "Event volatility research unavailable for %s: valid IV rank is missing", clean_sym
        )
        return None
    raw_avg_move = iv_data.get("avg_earnings_move")
    avg_move = float(raw_avg_move) if raw_avg_move is not None else None

    # Authoritative strike step from SSOT
    from market.symbol_master import get_strike_step

    strike_step = get_strike_step(clean_sym, spot=spot)
    atm_strike = round(spot / strike_step) * strike_step

    legs: list[OptionLeg] = []

    # ── Strategy Selection Matrix ─────────────────────────────────────────────
    # Case 1: Overpriced IV (IV Rank >= 50) -> Harvest IV Crush with Vertical Spreads
    if iv_rank >= 50.0:
        vol_regime = "OVERPRICED_IV"
        if is_bullish:
            strategy = "BULL_CALL_SPREAD"
            preferred_veh = f"{clean_sym} {format_strike(atm_strike)} CE / {format_strike(atm_strike + strike_step)} CE Bull Call Spread"
            legs = [
                OptionLeg(
                    action="BUY",
                    option_type="CE",
                    strike=atm_strike,
                    description=f"Long ATM {format_strike(atm_strike)} CE",
                ),
                OptionLeg(
                    action="SELL",
                    option_type="CE",
                    strike=atm_strike + strike_step,
                    description=f"Short OTM {format_strike(atm_strike + strike_step)} CE (Harvester)",
                ),
            ]
            max_risk = None
            max_reward = None
            rr = None
            rationale = (
                f"Research-only bullish spread illustration for {clean_sym}; IV rank {iv_rank:.1f}%. "
                "No premium-based payoff or post-event edge has been verified."
            )
        else:
            strategy = "BEAR_PUT_SPREAD"
            preferred_veh = f"{clean_sym} {format_strike(atm_strike)} PE / {format_strike(atm_strike - strike_step)} PE Bear Put Spread"
            legs = [
                OptionLeg(
                    action="BUY",
                    option_type="PE",
                    strike=atm_strike,
                    description=f"Long ATM {format_strike(atm_strike)} PE",
                ),
                OptionLeg(
                    action="SELL",
                    option_type="PE",
                    strike=atm_strike - strike_step,
                    description=f"Short OTM {format_strike(atm_strike - strike_step)} PE (Harvester)",
                ),
            ]
            max_risk = None
            max_reward = None
            rr = None
            rationale = (
                f"Research-only bearish spread illustration for {clean_sym}; IV rank {iv_rank:.1f}%. "
                "No premium-based payoff or post-event edge has been verified."
            )

    # Case 2: Underpriced IV (IV Rank < 40) -> Exploits Asymmetric Move with Long Straddle
    elif iv_rank < 40.0:
        vol_regime = "UNDERPRICED_IV"
        strategy = "LONG_STRADDLE"
        preferred_veh = f"{clean_sym} {format_strike(atm_strike)} ATM Long Straddle (CE + PE)"
        legs = [
            OptionLeg(
                action="BUY",
                option_type="CE",
                strike=atm_strike,
                description=f"Long ATM {format_strike(atm_strike)} CE",
            ),
            OptionLeg(
                action="BUY",
                option_type="PE",
                strike=atm_strike,
                description=f"Long ATM {format_strike(atm_strike)} PE",
            ),
        ]
        max_risk = None
        max_reward = None
        rr = None
        rationale = (
            f"Research-only long-volatility illustration for {clean_sym}; IV rank {iv_rank:.1f}%. "
            "No event-move comparison or executable edge has been verified."
        )

    # Case 3: Neutral IV (40 <= IV Rank < 50) -> Defined-Risk Vertical Spread
    else:
        vol_regime = "NEUTRAL"
        strategy = "BULL_CALL_SPREAD" if is_bullish else "BEAR_PUT_SPREAD"
        otm_strike = atm_strike + strike_step if is_bullish else atm_strike - strike_step
        opt_t = "CE" if is_bullish else "PE"
        preferred_veh = f"{clean_sym} {format_strike(atm_strike)}/{format_strike(otm_strike)} {opt_t} Vertical Spread"
        legs = [
            OptionLeg(
                action="BUY",
                option_type=opt_t,
                strike=atm_strike,
                description=f"Long {format_strike(atm_strike)} {opt_t}",
            ),
            OptionLeg(
                action="SELL",
                option_type=opt_t,
                strike=otm_strike,
                description=f"Short {format_strike(otm_strike)} {opt_t}",
            ),
        ]
        max_risk = None
        max_reward = None
        rr = None
        rationale = (
            f"⚡ DEFINED-RISK EVENT SPREAD: Pre-earnings positioning on {clean_sym}. "
            "Illustrative vertical spread only; premium-based payoff is unavailable."
        )

    return EventHedgePlan(
        symbol=clean_sym,
        event_type="EARNINGS",
        hours_to_event=effective_hours,
        iv_rank=iv_rank,
        historical_avg_move_pct=avg_move,
        volatility_regime=vol_regime,
        recommended_strategy=strategy,
        preferred_vehicle=preferred_veh,
        legs=legs,
        status="RESEARCH_ONLY",
        actionable=False,
        iv_crush_neutralized=False,
        max_risk_pts=max_risk,
        max_reward_pts=max_reward,
        reward_risk_ratio=rr,
        rationale=rationale,
    )
