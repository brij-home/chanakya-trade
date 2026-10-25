"""
engine/market_impact.py
───────────────────────
Almgren-Chriss (2000) Non-Linear Market Impact & Execution Cost Simulator.

Models the true institutional friction of executing large block sizes into
finite order books, capturing:
  1. Instantaneous Bid-Ask Spread Cross Cost (Half-Spread Concession)
  2. Temporary Market Impact (Transient Liquidity Depression via Square-Root Law)
  3. Permanent Market Impact (Information Leakage & Post-Trade Price Displacement)

Mathematical Formulation:
  - Permanent Price Shift:
      ΔP_perm = γ * σ * (Q / V) * P
  - Temporary Price Concession:
      ΔP_temp = (half_spread) + η * σ * (Q / (τ * V))^α * P
  - Realized Effective Fill Price:
      P_effective = P_0 + side_sign * (0.5 * ΔP_perm + ΔP_temp)

Where:
  - Q = Order quantity
  - V = Average Daily Volume (ADV)
  - σ = Daily asset return volatility
  - τ = Fraction of trading day utilized (e.g. 0.05 for 18.75 minutes of 375-min day)
  - α = Power-law exponent (typically 0.5 to 0.6)
  - γ, η = Canonical institutional calibration constants
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, Any

logger = logging.getLogger("engine.market_impact")


@dataclass
class MarketImpactEstimate:
    symbol: str
    side: Literal["BUY", "SELL"]
    order_quantity: int
    base_price: float
    effective_fill_price: float
    half_spread_cost: float
    temporary_impact: float
    permanent_impact: float
    total_slippage_per_unit: float
    total_slippage_cost_inr: float
    participation_of_adv_pct: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "order_quantity": self.order_quantity,
            "base_price": round(self.base_price, 2),
            "effective_fill_price": round(self.effective_fill_price, 2),
            "half_spread_cost": round(self.half_spread_cost, 4),
            "temporary_impact": round(self.temporary_impact, 4),
            "permanent_impact": round(self.permanent_impact, 4),
            "total_slippage_per_unit": round(self.total_slippage_per_unit, 4),
            "total_slippage_cost_inr": round(self.total_slippage_cost_inr, 2),
            "participation_of_adv_pct": round(self.participation_of_adv_pct, 4),
        }


def calculate_almgren_chriss_impact(
    symbol: str,
    side: Literal["BUY", "SELL"],
    quantity: int,
    price: float,
    adv: int,  # Average Daily Volume in shares
    daily_volatility: float = 0.018,  # ~1.8% typical daily equity vol
    half_spread_bps: float = 2.0,  # 2 basis points (0.0002) half-spread
    execution_horizon_fraction: float = 0.05,  # ~19 minutes of 375-minute Indian trading day
    gamma_perm: float = 0.314,  # Standard Kyle/Almgren permanent constant
    eta_temp: float = 0.142,  # Standard temporary impact constant
    alpha_power: float = 0.60,  # Square-root / sub-linear law
) -> MarketImpactEstimate:
    """
    Computes rigorous non-linear institutional market impact for an order.

    Args:
        symbol: Ticker symbol.
        side: 'BUY' or 'SELL'.
        quantity: Shares/contracts to execute.
        price: Unaffected mid-price before trade arrival.
        adv: 20-day Average Daily Volume.
        daily_volatility: Daily standard deviation of returns.
        half_spread_bps: Half the bid-ask spread in basis points.
        execution_horizon_fraction: Fraction of trading day (e.g. 0.05).
        gamma_perm: Empirical permanent impact calibration coefficient.
        eta_temp: Empirical temporary impact calibration coefficient.
        alpha_power: Sub-linear power coefficient (0.5 - 0.6).
    """
    if quantity <= 0 or price <= 0:
        return MarketImpactEstimate(
            symbol=symbol,
            side=side,
            order_quantity=quantity,
            base_price=price,
            effective_fill_price=price,
            half_spread_cost=0.0,
            temporary_impact=0.0,
            permanent_impact=0.0,
            total_slippage_per_unit=0.0,
            total_slippage_cost_inr=0.0,
            participation_of_adv_pct=0.0,
        )

    adv_safe = max(quantity, adv)
    participation_adv = (quantity / adv_safe) * 100.0

    # 1. Half-spread cross cost
    half_spread = price * (half_spread_bps / 10000.0)

    # 2. Permanent Market Impact (linear in Q / V)
    # ΔP_perm = γ * σ * (Q / V) * P
    perm_impact = gamma_perm * daily_volatility * (quantity / adv_safe) * price

    # 3. Temporary Market Impact (sub-linear power law in execution rate)
    # ΔP_temp = η * σ * (Q / (τ * V))^α * P
    tau = max(0.001, min(1.0, execution_horizon_fraction))
    normalized_rate = quantity / (tau * adv_safe)
    temp_impact = eta_temp * daily_volatility * (normalized_rate**alpha_power) * price

    # Total slippage per share: half-spread + average permanent impact experienced + temporary impact
    total_slip = half_spread + (0.5 * perm_impact) + temp_impact

    sign = 1.0 if side.upper() == "BUY" else -1.0
    effective_price = price + (sign * total_slip)

    return MarketImpactEstimate(
        symbol=symbol,
        side=side,
        order_quantity=quantity,
        base_price=price,
        effective_fill_price=effective_price,
        half_spread_cost=half_spread,
        temporary_impact=temp_impact,
        permanent_impact=perm_impact,
        total_slippage_per_unit=total_slip,
        total_slippage_cost_inr=total_slip * quantity,
        participation_of_adv_pct=participation_adv,
    )
