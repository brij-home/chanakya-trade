"""
engine/portfolio_greeks.py
──────────────────────────
Unified Institutional Greek Portfolio Risk Surface & Stress Testing Engine.

Aggregates individual position Greeks (Delta, Gamma, Theta, Vega) across Equity and F&O derivatives
into a cohesive portfolio-level risk surface.

Capabilities:
1. Net Greek Aggregation:
   - Net Delta: Expressed in canonical benchmark contract equivalents (e.g. NIFTY units).
   - Net Gamma: Acceleration risk to market gapping.
   - Net Theta: Daily portfolio theta bleed / collection in INR.
   - Net Vega: INR sensitivity per 1.0 point India VIX shock.
2. Multi-Scenario Stress Testing:
   - Index gap shocks: -2.5%, -1.5%, +1.5%, +2.5%.
   - Volatility shock: +25% VIX spike (Black Swan), -15% IV crush.
3. Autonomous Delta-Neutral Hedging Advisory:
   - Generates exact counter-trend defined-risk spread parameters to neutralize excessive delta exposure.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import logging
import math
from typing import Any, Literal, Optional

logger = logging.getLogger("engine.portfolio_greeks")

DeltaPosture = Literal["BULLISH", "BEARISH", "NEUTRAL", "EXTREME_LONG", "EXTREME_SHORT"]
ThetaStatus = Literal["HEALTHY_INCOME", "ACCEPTABLE_DECAY", "HAZARDOUS_THETA_CLIFF"]


@dataclass
class PositionGreek:
    """Individual position Greek profile."""

    symbol: str
    underlying: str
    instrument_type: str  # "EQUITY" | "CE" | "PE" | "FUT"
    quantity: int
    lots: int
    delta: float
    gamma: float
    theta_daily_inr: float
    vega_inr: float
    ltp: float


@dataclass
class PortfolioGreekSnapshot:
    """Consolidated institutional Greek surface and stress test report."""

    net_delta_nifty_eq: float
    net_gamma: float
    net_theta_daily_inr: float
    net_vega_inr: float
    total_capital_deployed_inr: float
    positions_count: int
    delta_posture: DeltaPosture
    theta_status: ThetaStatus
    stress_tests: dict[str, float] = field(default_factory=dict)
    hedging_recommendation: Optional[dict[str, Any]] = None
    positions: list[PositionGreek] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["positions"] = [asdict(p) for p in self.positions]
        return d


def estimate_contract_delta(
    instrument_type: str,
    spot_price: float,
    strike: Optional[float] = None,
    dte: int = 7,
    iv: float = 0.15,
) -> tuple[float, float, float, float]:
    """
    Computes analytical Black-Scholes Greeks approximation for an option / equity contract.
    Returns: (delta, gamma, theta_per_share, vega_per_share)
    """
    norm_type = instrument_type.upper().strip()
    if norm_type in ("EQUITY", "EQ", "FUT", "FUTURES"):
        # Linear instruments have Delta = 1.0, Gamma = 0, Theta = 0, Vega = 0
        return 1.0, 0.0, 0.0, 0.0

    if not strike or strike <= 0 or spot_price <= 0:
        return 0.5 if norm_type == "CE" else -0.5, 0.001, -2.5, 12.0

    # Black-Scholes d1 calculation
    t = max(0.5, float(dte)) / 365.0
    vol = max(0.05, float(iv))
    r = 0.065  # RBI risk-free rate ~6.5%

    try:
        d1 = (math.log(spot_price / strike) + (r + 0.5 * vol**2) * t) / (vol * math.sqrt(t))
        # Standard normal CDF approximation
        nd1 = 0.5 * (1.0 + math.erf(d1 / math.sqrt(2.0)))
        # Standard normal PDF
        npd1 = (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * d1**2)

        gamma = npd1 / (spot_price * vol * math.sqrt(t))
        vega_unit = (spot_price * math.sqrt(t) * npd1) / 100.0  # per 1% IV change

        if norm_type == "CE":
            delta = nd1
            theta_annual = -(spot_price * npd1 * vol) / (2.0 * math.sqrt(t)) - r * strike * math.exp(-r * t) * (0.5 * (1.0 + math.erf((d1 - vol * math.sqrt(t)) / math.sqrt(2.0))))
        else:  # PE
            delta = nd1 - 1.0
            theta_annual = -(spot_price * npd1 * vol) / (2.0 * math.sqrt(t)) + r * strike * math.exp(-r * t) * (1.0 - (0.5 * (1.0 + math.erf((d1 - vol * math.sqrt(t)) / math.sqrt(2.0)))))

        theta_daily = theta_annual / 365.0
        return round(delta, 3), round(gamma, 5), round(theta_daily, 2), round(vega_unit, 2)
    except Exception:
        return 0.5 if norm_type == "CE" else -0.5, 0.001, -2.0, 10.0


def calculate_portfolio_greeks(
    positions: list[dict[str, Any]],
    spot_map: Optional[dict[str, float]] = None,
    vix: float = 13.5,
    nifty_spot: float = 24500.0,
) -> PortfolioGreekSnapshot:
    """
    Aggregates open positions into a unified Greek risk surface.
    """
    spots = spot_map or {}
    parsed_positions: list[PositionGreek] = []

    total_capital = 0.0
    agg_delta_value = 0.0
    agg_gamma = 0.0
    agg_theta_daily_inr = 0.0
    agg_vega_inr = 0.0

    for pos in positions:
        sym = str(pos.get("symbol") or "").upper()
        underlying = str(pos.get("underlying") or sym).upper()
        inst_type = str(pos.get("instrument_type") or pos.get("option_type") or "EQUITY").upper()
        qty = int(pos.get("quantity") or pos.get("shares") or 0)
        lots = int(pos.get("lots") or 1)
        ltp = float(pos.get("ltp") or pos.get("price") or 0.0)
        strike = float(pos.get("strike") or 0.0) if pos.get("strike") else None
        dte = int(pos.get("dte") or 7)
        iv = float(pos.get("iv") or (vix / 100.0))

        # Resolve underlying spot price accurately
        spot_p = spots.get(underlying) or spots.get(sym)
        if not spot_p or spot_p <= 0:
            if "BANK" in underlying or "BANKNIFTY" in sym:
                spot_p = 52000.0
            elif "NIFTY" in underlying or "NIFTY" in sym:
                spot_p = nifty_spot
            elif strike and strike > 0:
                spot_p = strike  # ATM proxy
            else:
                spot_p = ltp or nifty_spot

        d, g, th, vg = estimate_contract_delta(
            instrument_type=inst_type,
            spot_price=spot_p,
            strike=strike,
            dte=dte,
            iv=iv,
        )

        pos_capital = abs(qty) * ltp
        total_capital += pos_capital

        pos_theta_inr = th * qty
        pos_vega_inr = vg * qty

        # Delta exposure in INR
        delta_inr = d * qty * spot_p
        agg_delta_value += delta_inr
        agg_gamma += g * qty
        agg_theta_daily_inr += pos_theta_inr
        agg_vega_inr += pos_vega_inr

        parsed_positions.append(
            PositionGreek(
                symbol=sym,
                underlying=underlying,
                instrument_type=inst_type,
                quantity=qty,
                lots=lots,
                delta=d,
                gamma=g,
                theta_daily_inr=round(pos_theta_inr, 2),
                vega_inr=round(pos_vega_inr, 2),
                ltp=ltp,
            )
        )

    # Convert Net Delta Value into NIFTY contract equivalents (1 NIFTY lot = 25 shares * spot)
    nifty_lot_val = 25.0 * nifty_spot
    net_delta_nifty_eq = round(agg_delta_value / max(1.0, nifty_lot_val), 2)

    # Classify Posture
    if net_delta_nifty_eq > 5.0:
        delta_posture: DeltaPosture = "EXTREME_LONG"
    elif net_delta_nifty_eq > 1.2:
        delta_posture = "BULLISH"
    elif net_delta_nifty_eq < -5.0:
        delta_posture = "EXTREME_SHORT"
    elif net_delta_nifty_eq < -1.2:
        delta_posture = "BEARISH"
    else:
        delta_posture = "NEUTRAL"

    # Classify Theta burn
    if agg_theta_daily_inr > 0:
        theta_status: ThetaStatus = "HEALTHY_INCOME"
    elif agg_theta_daily_inr < -3000.0:
        theta_status = "HAZARDOUS_THETA_CLIFF"
    else:
        theta_status = "ACCEPTABLE_DECAY"

    # 4-Scenario Shock Stress Test (P&L impact)
    stress_tests = {
        "gap_down_2_5_pct": round(agg_delta_value * -0.025 + (0.5 * agg_gamma * (nifty_spot * -0.025)**2), 2),
        "gap_down_1_5_pct": round(agg_delta_value * -0.015, 2),
        "gap_up_1_5_pct": round(agg_delta_value * 0.015, 2),
        "gap_up_2_5_pct": round(agg_delta_value * 0.025 + (0.5 * agg_gamma * (nifty_spot * 0.025)**2), 2),
        "vix_spike_25_pct": round(agg_vega_inr * (vix * 0.25), 2),
        "iv_crush_15_pct": round(agg_vega_inr * (vix * -0.15), 2),
    }

    # Hedging Recommendation if exposure is extreme
    hedge_rec: Optional[dict[str, Any]] = None
    if delta_posture in ("EXTREME_LONG", "EXTREME_SHORT"):
        is_long = delta_posture == "EXTREME_LONG"
        hedge_lots = max(1, int(abs(net_delta_nifty_eq)))
        hedge_rec = {
            "underlying": "NIFTY",
            "action": "BUY_BEAR_PUT_SPREAD" if is_long else "BUY_BULL_CALL_SPREAD",
            "lots": hedge_lots,
            "shares": hedge_lots * 25,
            "target_delta_neutralization": -net_delta_nifty_eq,
            "urgency": "HIGH",
            "rationale": (
                f"Net Delta exposure is {net_delta_nifty_eq:+.1f} NIFTY contract equivalents. "
                f"A 2.5% adverse gap causes ~₹{abs(stress_tests['gap_down_2_5_pct'] if is_long else stress_tests['gap_up_2_5_pct']):,.0f} loss. "
                f"Deploy {hedge_lots} lots of defined-risk spread to immunize delta."
            ),
        }

    return PortfolioGreekSnapshot(
        net_delta_nifty_eq=net_delta_nifty_eq,
        net_gamma=round(agg_gamma, 5),
        net_theta_daily_inr=round(agg_theta_daily_inr, 2),
        net_vega_inr=round(agg_vega_inr, 2),
        total_capital_deployed_inr=round(total_capital, 2),
        positions_count=len(parsed_positions),
        delta_posture=delta_posture,
        theta_status=theta_status,
        stress_tests=stress_tests,
        hedging_recommendation=hedge_rec,
        positions=parsed_positions,
    )
