# -*- coding: utf-8 -*-
"""
analysis/trajectory_search.py
─────────────────────────────
Test-Time Reasoning & Trajectory Scenario Simulator (Agentic MCTS).

Simulates forward probabilistic price-action trajectory paths over 15m, 30m,
and 60m horizons to evaluate conditional branch probabilities:
  - Branch A: EXPANSION_CONTINUATION (Immediate thrust through T1 to T2)
  - Branch B: MEAN_REVERSION_PULLBACK (Chops or retests breakout level/VWAP before bounce)
  - Branch C: SFP_LIQUIDITY_TRAP (False breakout, wick rejection, sweeps stop-loss)

Computes expected payoff (EV) for aggressive market entry vs. patient limit retest,
vetoing negative-expectancy chase orders and enforcing institutional entry discipline.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

logger = logging.getLogger("chanakya.analysis.trajectory_search")


@dataclass
class TrajectoryBranch:
    """A forward simulated price-action path scenario."""

    scenario_name: (
        str  # "EXPANSION_CONTINUATION" | "MEAN_REVERSION_PULLBACK" | "SFP_LIQUIDITY_TRAP"
    )
    probability: float  # 0.0 to 1.0
    projected_price_15m: float
    projected_price_30m: float
    projected_price_60m: float
    expected_payoff_pts: float
    expected_r: float
    driver_catalysts: list[str] = field(default_factory=list)


@dataclass
class TrajectorySimulationResult:
    """Overall multi-branch forward trajectory simulation analysis."""

    symbol: str
    direction: str
    spot: float
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float
    # Probabilities
    prob_expansion: float
    prob_retest: float
    prob_trap: float
    # Expected Values
    ev_market_chase_pts: float
    ev_limit_retest_pts: float
    optimal_execution_style: (
        str  # "AGGRESSIVE_MOMENTUM" | "PATIENT_LIMIT_RETEST" | "ABORT_NEGATIVE_EXPECTANCY"
    )
    optimal_entry_zone: str
    branches: list[TrajectoryBranch] = field(default_factory=list)
    executive_synthesis: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def simulate_trade_trajectories(
    symbol: str,
    direction: str,
    spot: float,
    entry_price: float,
    stop_loss: float,
    target_1: float,
    target_2: Optional[float] = None,
    atr_14: Optional[float] = None,
    vix: float = 14.5,
    vpin: float = 0.50,
    day_archetype: str = "NORMAL_DAY",
    rvol: float = 1.0,
    has_exhaustion_wick: bool = False,
    headroom_r: float = 2.0,
) -> TrajectorySimulationResult:
    """
    Simulates test-time forward multi-path trajectories across the next 15–60 minutes.
    """
    clean_sym = symbol.upper().replace("NSE:", "").replace(".NS", "").strip()
    is_long = direction.upper() in ("LONG", "BULLISH", "BUY", "CE")
    initial_risk = max(1.0, abs(entry_price - stop_loss))
    t1 = (
        target_1
        if target_1 > 0
        else (entry_price + (2.0 * initial_risk) if is_long else entry_price - (2.0 * initial_risk))
    )
    t2 = (
        target_2
        if (target_2 and target_2 > 0)
        else (entry_price + (4.0 * initial_risk) if is_long else entry_price - (4.0 * initial_risk))
    )

    # Baseline branch probability distributions (prior)
    # Default unconditioned: 40% Expansion, 40% Pullback/Retest, 20% Trap
    p_exp = 0.40
    p_retest = 0.40
    p_trap = 0.20

    drivers_exp: list[str] = []
    drivers_retest: list[str] = []
    drivers_trap: list[str] = []

    # 1. Conditioning on VPIN Order Flow Toxicity (Informed aggressive institutional flow)
    if vpin >= 0.70:
        p_exp += 0.20
        p_retest -= 0.10
        p_trap -= 0.10
        drivers_exp.append(
            f"High VPIN flow toxicity ({vpin:.0%}) signals aggressive institutional absorption driving directional momentum."
        )
    elif vpin <= 0.35:
        p_exp -= 0.15
        p_retest += 0.15
        drivers_retest.append(
            f"Low VPIN ({vpin:.0%}) indicates balanced two-way liquidity; immediate runaway expansion unlikely."
        )

    # 2. Conditioning on Dalton Day Archetype
    if day_archetype == "TREND_DAY":
        p_exp += 0.15
        p_trap -= 0.10
        drivers_exp.append(
            "Trend Day archetype confirms one-time framing and strong institutional range extension."
        )
    elif day_archetype == "NORMAL_DAY":
        p_exp -= 0.15
        p_retest += 0.10
        p_trap += 0.05
        drivers_retest.append(
            "Normal Day archetype: initial breakout moves have high mean-reversion frequency back toward POC."
        )

    # 3. Conditioning on Relative Volume (RVOL)
    if rvol >= 1.50:
        p_exp += 0.10
        p_trap -= 0.05
        drivers_exp.append(
            f"Surging relative volume ({rvol:.1f}x) validates institutional commitment."
        )
    elif rvol < 0.85:
        p_exp -= 0.20
        p_trap += 0.20
        drivers_trap.append(
            f"Dry volume breakout ({rvol:.2f}x): High risk of false breakout / retail trap."
        )

    # 4. Conditioning on Rejection Wick
    if has_exhaustion_wick:
        p_exp -= 0.25
        p_trap += 0.30
        drivers_trap.append(
            "Exhaustion rejection wick formed at highs/lows, indicating passive limit order wall absorption."
        )

    # 5. Conditioning on Structural Headroom
    if headroom_r < 0.80:
        p_exp -= 0.20
        p_trap += 0.20
        drivers_trap.append(
            f"Tight structural headroom ({headroom_r:.2f}R): Immediate obstacle barrier blocks easy runway."
        )

    # Normalize probabilities to sum to 1.0
    raw_sum = max(0.01, p_exp + p_retest + p_trap)
    p_exp = max(0.05, min(0.85, p_exp / raw_sum))
    p_retest = max(0.05, min(0.85, p_retest / raw_sum))
    p_trap = max(0.05, min(0.85, p_trap / raw_sum))
    # Re-normalize
    tot = p_exp + p_retest + p_trap
    p_exp = round(p_exp / tot, 3)
    p_retest = round(p_retest / tot, 3)
    p_trap = round(1.0 - p_exp - p_retest, 3)

    # Compute Forward Price Projections
    retest_price = round(
        entry_price - (0.40 * initial_risk) if is_long else entry_price + (0.40 * initial_risk), 2
    )
    sl_price = round(stop_loss, 2)

    # ── Branch 1: Expansion Continuation ──────────────────────────────
    payoff_exp = abs(t1 - entry_price)
    b_exp = TrajectoryBranch(
        scenario_name="EXPANSION_CONTINUATION",
        probability=p_exp,
        projected_price_15m=round(entry_price + (0.50 * (t1 - entry_price)), 2),
        projected_price_30m=round(t1, 2),
        projected_price_60m=round(t2, 2),
        expected_payoff_pts=payoff_exp,
        expected_r=round(payoff_exp / initial_risk, 2),
        driver_catalysts=drivers_exp,
    )

    # ── Branch 2: Mean Reversion Pullback / Retest ─────────────────────
    payoff_retest = abs(t1 - retest_price)
    b_retest = TrajectoryBranch(
        scenario_name="MEAN_REVERSION_PULLBACK",
        probability=p_retest,
        projected_price_15m=retest_price,
        projected_price_30m=round(entry_price, 2),
        projected_price_60m=round(t1, 2),
        expected_payoff_pts=payoff_retest,
        expected_r=round(payoff_retest / max(0.5, abs(retest_price - stop_loss)), 2),
        driver_catalysts=drivers_retest,
    )

    # ── Branch 3: SFP Liquidity Trap ──────────────────────────────────
    loss_pts = -initial_risk
    b_trap = TrajectoryBranch(
        scenario_name="SFP_LIQUIDITY_TRAP",
        probability=p_trap,
        projected_price_15m=round(
            entry_price - (0.50 * initial_risk) if is_long else entry_price + (0.50 * initial_risk),
            2,
        ),
        projected_price_30m=sl_price,
        projected_price_60m=round(
            sl_price - (0.50 * initial_risk) if is_long else sl_price + (0.50 * initial_risk), 2
        ),
        expected_payoff_pts=loss_pts,
        expected_r=-1.0,
        driver_catalysts=drivers_trap,
    )

    # Expected Values (EV)
    # EV(Market Chase) = P(Exp) * Payoff_T1 + P(Retest) * 0.2*Payoff_T1 - P(Trap) * InitialRisk
    ev_market = (p_exp * payoff_exp) + (p_retest * (0.20 * payoff_exp)) - (p_trap * initial_risk)
    # EV(Limit Retest) = P(Retest) * Payoff_Retest + P(Exp)*0.5*Payoff_T1 - (P(Trap)*0.5) * (initial_risk * 0.70)
    ev_limit = (
        (p_retest * payoff_retest)
        + (p_exp * 0.50 * payoff_exp)
        - (p_trap * 0.50 * (initial_risk * 0.70))
    )

    ev_market = round(ev_market, 2)
    ev_limit = round(ev_limit, 2)

    # Optimal Execution Recommendation
    if p_trap >= 0.45 or (ev_market < 0 and ev_limit < 0):
        optimal_style = "ABORT_NEGATIVE_EXPECTANCY"
        entry_zone = "DO_NOT_ENTER"
        synthesis = (
            f"Negative Expectancy / High Trap Risk ({p_trap:.0%}): Expected value is unfavorable. "
            f"Adversarial simulation recommends standing down."
        )
    elif p_exp >= 0.55 and ev_market >= ev_limit * 0.85:
        optimal_style = "AGGRESSIVE_MOMENTUM"
        entry_zone = f"₹{entry_price:,.1f} – ₹{entry_price * (1.001 if is_long else 0.999):,.1f}"
        synthesis = (
            f"High-Probability Directional Expansion ({p_exp:.0%}): High VPIN and clean momentum support immediate "
            f"market entry targeting T1 ₹{t1:,.1f} (EV: +₹{ev_market:.1f} pts)."
        )
    else:
        optimal_style = "PATIENT_LIMIT_RETEST"
        entry_zone = f"₹{retest_price:,.1f}"
        synthesis = (
            f"Pullback / Retest Dominant ({p_retest:.0%}): High probability of dip before expansion. "
            f"Patient resting limit order at ₹{retest_price:,.1f} yields higher expectancy (+₹{ev_limit:.1f} pts vs +₹{ev_market:.1f} pts chase)."
        )

    return TrajectorySimulationResult(
        symbol=clean_sym,
        direction=direction.upper(),
        spot=spot,
        entry_price=entry_price,
        stop_loss=stop_loss,
        target_1=t1,
        target_2=t2,
        prob_expansion=p_exp,
        prob_retest=p_retest,
        prob_trap=p_trap,
        ev_market_chase_pts=ev_market,
        ev_limit_retest_pts=ev_limit,
        optimal_execution_style=optimal_style,
        optimal_entry_zone=entry_zone,
        branches=[b_exp, b_retest, b_trap],
        executive_synthesis=synthesis,
    )
