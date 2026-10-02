"""
analysis/gex.py
───────────────
Institutional Options Gamma Exposure (GEX) & Dealer Zero-Gamma Levels Engine.

Quantitative Foundation:
  - Market Makers (Dealers) are assumed net short retail/client options orders.
  - Positive GEX (Dealer Long Gamma): Dealers hedge delta by selling into rallies and buying into dips,
    dampening market volatility and creating pinning magnets near High-GEX strikes / Max Pain.
  - Negative GEX (Dealer Short Gamma): Dealers hedge delta by buying into rallies and selling into dips,
    accelerating directional momentum and creating explosive volatility breakouts.
  - Zero-Gamma Level (Gamma Flip): The exact price level where Net Dealer Gamma transitions from
    volatility-dampening positive territory to volatility-accelerating negative territory.

Formulas (Crores of Rupee Gamma per 1% underlying move):
  d1 = (ln(Spot / Strike) + (r + 0.5 * sigma^2) * T) / (sigma * sqrt(T))
  Gamma = exp(-0.5 * d1^2) / (Spot * sigma * sqrt(2 * pi * T))
  Call GEX (Cr) = 0.5 * Gamma * (Spot^2) * Call_OI * Lot_Size / 1e7
  Put GEX (Cr)  = -0.5 * Gamma * (Spot^2) * Put_OI * Lot_Size / 1e7
  Net GEX (Cr)  = Call GEX + Put GEX
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from rich.console import Console
from rich.panel import Panel

console = Console()

RISK_FREE_RATE = 0.065  # 6.5% RBI repo rate benchmark


def _bs_gamma(spot: float, strike: float, dte_days: int, iv_pct: float, rate: float = RISK_FREE_RATE) -> float:
    """Analytical Black-Scholes gamma calculation (100% deterministic, zero C-dep failure)."""
    if spot <= 0 or strike <= 0:
        return 0.0
    t_years = max(1.0 / 365.0, dte_days / 365.0)
    sigma = max(0.05, min(3.0, (iv_pct / 100.0) if iv_pct > 0 else 0.15))
    sqrt_t = math.sqrt(t_years)

    denom = sigma * sqrt_t
    if denom <= 0:
        return 0.0

    d1 = (math.log(spot / strike) + (rate + 0.5 * sigma * sigma) * t_years) / denom
    pdf_d1 = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
    gamma = pdf_d1 / (spot * sigma * sqrt_t) if (spot * sigma * sqrt_t) > 0 else 0.0
    return gamma


def compute_gex_at_strike(
    oi: int,
    gamma: float,
    spot: float,
    lot_size: int,
    is_call: bool,
) -> float:
    """Compute Rupee GEX in Crores for a single strike option contract."""
    if oi <= 0 or gamma <= 0 or spot <= 0 or lot_size <= 0:
        return 0.0
    # Rupee GEX in Crores (1e7)
    gex_cr = 0.5 * gamma * (spot**2) * oi * lot_size / 1e7
    return round(gex_cr, 2) if is_call else round(-gex_cr, 2)


def find_gex_flip(gex_by_strike: List[Tuple[float, float]]) -> Optional[float]:
    """
    Find the exact interpolated Gamma Flip / Dealer Zero-Gamma level.
    Identifies where Net GEX crosses the zero line from positive to negative.
    """
    if len(gex_by_strike) < 2:
        return None

    for i in range(1, len(gex_by_strike)):
        prev_strike, prev_gex = gex_by_strike[i - 1]
        curr_strike, curr_gex = gex_by_strike[i]

        # Crossing from positive to negative or vice versa
        if (prev_gex > 0 and curr_gex <= 0) or (prev_gex < 0 and curr_gex >= 0):
            if prev_gex != curr_gex:
                ratio = abs(prev_gex) / (abs(prev_gex) + abs(curr_gex))
                return round(prev_strike + ratio * (curr_strike - prev_strike), 1)
            return round(curr_strike, 1)

    return None


def classify_gex_regime(total_gex: float, threshold: float = 25.0) -> str:
    """Classify institutional dealer gamma regime."""
    if total_gex > threshold:
        return "POSITIVE"  # Volatility dampener / mean-reverting / pinning
    elif total_gex < -threshold:
        return "NEGATIVE"  # Volatility accelerator / trending / breakout risk
    return "NEUTRAL"


def get_gex_analysis(underlying: str, expiry: Optional[str] = None) -> Dict[str, Any]:
    """
    Compute comprehensive institutional Gamma Exposure (GEX) analysis.
    Identifies Dealer Zero-Gamma Levels, Call Wall, Put Wall, and Volatility Breakout Zones.
    """
    try:
        from market.options import get_options_chain
        from market.quotes import get_ltp, get_quote
        from market.instruments import STANDARD_LOT_SIZES

        raw_sym = str(underlying).upper().strip()
        clean = (
            raw_sym.replace("NSE:", "")
            .replace("BSE:", "")
            .replace("NFO:", "")
            .replace("MCX:", "")
            .replace("CDS:", "")
            .strip()
        )

        # 1. Resolve canonical spot ticker
        if clean in ("NIFTY", "NIFTY 50", "NIFTY50"):
            clean = "NIFTY"
            spot_key = "NSE:NIFTY 50"
        elif clean in ("BANKNIFTY", "NIFTY BANK"):
            clean = "BANKNIFTY"
            spot_key = "NSE:NIFTY BANK"
        elif clean in ("FINNIFTY", "NIFTY FIN SERVICE"):
            clean = "FINNIFTY"
            spot_key = "NSE:NIFTY FIN SERVICE"
        elif clean in ("MIDCPNIFTY", "NIFTY MIDCAP SELECT"):
            clean = "MIDCPNIFTY"
            spot_key = "NSE:NIFTY MIDCAP SELECT"
        elif clean == "SENSEX":
            spot_key = "BSE:SENSEX"
        else:
            spot_key = f"NSE:{clean}"

        # 2. Retrieve live spot quote
        spot = float(get_ltp(spot_key) or get_ltp(clean) or 0.0)
        if spot <= 0:
            q_dict = get_quote(spot_key)
            if spot_key in q_dict and q_dict[spot_key].last_price:
                spot = float(q_dict[spot_key].last_price)

        # 3. Retrieve options chain
        chain = get_options_chain(clean, expiry)
        if not chain:
            return {
                "status": "UNAVAILABLE",
                "error": f"No options chain data available for {clean}",
                "underlying": clean,
            }

        if spot <= 0:
            # Fallback to ATM strike from options chain
            strikes = [c.strike for c in chain if getattr(c, "strike", 0) > 0]
            if strikes:
                spot = sum(strikes) / len(strikes)
            else:
                return {"status": "UNAVAILABLE", "error": "Could not determine spot price for GEX analysis"}

        # 4. Resolve official contract lot size
        lot_size = STANDARD_LOT_SIZES.get(clean, getattr(chain[0], "lot_size", 25) or 25)

        # 5. Determine Days to Expiry (DTE)
        first_exp = chain[0].expiry if chain and chain[0].expiry else expiry or ""
        dte_days = 4  # Default near-week
        if first_exp:
            try:
                exp_date = datetime.strptime(str(first_exp)[:10], "%Y-%m-%d").date()
                dte_days = max(1, (exp_date - date.today()).days)
            except Exception:
                pass

        # 6. Aggregate by strike
        strike_map: Dict[float, Dict[str, Any]] = {}
        for c in chain:
            k = float(c.strike)
            if k not in strike_map:
                strike_map[k] = {
                    "strike": k,
                    "ce_oi": 0,
                    "pe_oi": 0,
                    "ce_iv": 15.0,
                    "pe_iv": 15.0,
                    "ce_price": 0.0,
                    "pe_price": 0.0,
                }
            opt_type = str(c.option_type).upper()
            oi = int(getattr(c, "oi", 0) or 0)
            iv = float(getattr(c, "iv", 0.0) or 0.0)
            ltp = float(getattr(c, "last_price", 0.0) or 0.0)

            if opt_type == "CE":
                strike_map[k]["ce_oi"] = oi
                strike_map[k]["ce_price"] = ltp
                if iv > 0:
                    strike_map[k]["ce_iv"] = iv
            elif opt_type == "PE":
                strike_map[k]["pe_oi"] = oi
                strike_map[k]["pe_price"] = ltp
                if iv > 0:
                    strike_map[k]["pe_iv"] = iv

        # 7. Compute GEX per strike
        strikes_sorted = sorted(strike_map.keys())
        gex_strip: List[Dict[str, Any]] = []

        for k in strikes_sorted:
            row = strike_map[k]
            avg_iv = (row["ce_iv"] + row["pe_iv"]) / 2.0
            gamma = _bs_gamma(spot, k, dte_days, avg_iv)

            call_gex = compute_gex_at_strike(row["ce_oi"], gamma, spot, lot_size, is_call=True)
            put_gex = compute_gex_at_strike(row["pe_oi"], gamma, spot, lot_size, is_call=False)
            net_gex = round(call_gex + put_gex, 2)

            dist_pct = round(((k - spot) / spot) * 100.0, 2)

            gex_strip.append(
                {
                    "strike": k,
                    "distance_pct": dist_pct,
                    "gamma": float(f"{gamma:.6f}"),
                    "ce_oi": row["ce_oi"],
                    "pe_oi": row["pe_oi"],
                    "call_gex_cr": call_gex,
                    "put_gex_cr": put_gex,
                    "net_gex_cr": net_gex,
                    "avg_iv": round(avg_iv, 1),
                }
            )

        # 8. Key Institutional Levels
        total_call_gex = round(sum(s["call_gex_cr"] for s in gex_strip), 2)
        total_put_gex = round(sum(s["put_gex_cr"] for s in gex_strip), 2)
        total_net_gex = round(total_call_gex + total_put_gex, 2)

        # Call Wall (Maximum positive Call GEX — strong dealer selling resistance)
        call_wall_entry = max(gex_strip, key=lambda x: x["call_gex_cr"]) if gex_strip else None
        call_wall = call_wall_entry["strike"] if call_wall_entry else None

        # Put Wall (Maximum absolute Put GEX — strong dealer buying support)
        put_wall_entry = min(gex_strip, key=lambda x: x["put_gex_cr"]) if gex_strip else None
        put_wall = put_wall_entry["strike"] if put_wall_entry else None

        # Absolute Net Gamma Magnet
        max_gex_entry = max(gex_strip, key=lambda x: abs(x["net_gex_cr"])) if gex_strip else None
        max_gamma_strike = max_gex_entry["strike"] if max_gex_entry else None

        # Gamma Flip / Dealer Zero-Gamma Level
        gex_tuples = [(s["strike"], s["net_gex_cr"]) for s in gex_strip]
        zero_gamma = find_gex_flip(gex_tuples)

        # Regime classification
        regime = classify_gex_regime(total_net_gex)

        # Volatility acceleration zones
        volatility_zones = {
            "dampening_zone": f"Between {put_wall:,.0f} and {call_wall:,.0f}" if (put_wall and call_wall) else "Pending",
            "upside_acceleration": f"Above {call_wall:,.0f} (Dealers forced to cover shorts, explosive squeeze)" if call_wall else "Pending",
            "downside_acceleration": f"Below {zero_gamma:,.0f} (Negative Gamma cascade, volatility expansion)" if zero_gamma else "Pending",
        }

        # Actionable Dealer Positioning Interpretation
        interpretation = _interpret_institutional_gex(regime, zero_gamma, call_wall, put_wall, spot)

        return {
            "status": "ok",
            "underlying": clean,
            "spot": round(spot, 2),
            "lot_size": lot_size,
            "expiry": first_exp,
            "dte_days": dte_days,
            "regime": regime,
            "total_net_gex_cr": total_net_gex,
            "total_call_gex_cr": total_call_gex,
            "total_put_gex_cr": total_put_gex,
            "zero_gamma_level": zero_gamma,
            "gamma_flip": zero_gamma,
            "call_wall": call_wall,
            "put_wall": put_wall,
            "max_gamma_strike": max_gamma_strike,
            "volatility_acceleration_zones": volatility_zones,
            "interpretation": interpretation,
            "strikes": gex_strip,
        }

    except Exception as e:
        return {"status": "error", "error": str(e), "underlying": underlying}


def _interpret_institutional_gex(
    regime: str,
    zero_gamma: Optional[float],
    call_wall: Optional[float],
    put_wall: Optional[float],
    spot: float,
) -> str:
    """Generate crisp, actionable dealer positioning blueprint."""
    if regime == "POSITIVE":
        msg = f"POSITIVE DEALER GAMMA (Long Gamma Regime). Market makers dampen volatility by selling rallies and buying dips. Expect mean-reverting price action and pinning."
        if put_wall and call_wall:
            msg += f" Institutional corridor: {put_wall:,.0f} (Put Wall Support) to {call_wall:,.0f} (Call Wall Resistance)."
        if zero_gamma and spot < zero_gamma:
            msg += f" Caution: Spot ({spot:,.0f}) is below Zero-Gamma ({zero_gamma:,.0f}) — dealer hedging could abruptly flip to volatility acceleration."
        return msg
    elif regime == "NEGATIVE":
        msg = f"NEGATIVE DEALER GAMMA (Short Gamma Regime). Market makers accelerate volatility by chasing price directionally. High probability of trending expansion and violent breakout moves."
        if zero_gamma:
            msg += f" Gamma Flip pivot is {zero_gamma:,.0f}. Stability requires reclaiming this level."
        return msg

    return f"BALANCED DEALER GAMMA. Gamma profile is neutral across strikes. Directional follow-through will be dictated by cash delivery and macro flows rather than dealer rehedging."


def print_gex(underlying: str, expiry: Optional[str] = None) -> None:
    """Display Rich terminal GEX dashboard."""
    data = get_gex_analysis(underlying, expiry)
    if data.get("status") != "ok":
        console.print(f"[red]{data.get('error', 'Error generating GEX')}[/red]")
        return

    lines = [
        f"  Underlying: [bold white]{data['underlying']}[/bold white] | Spot: ₹{data['spot']:,.2f} | DTE: {data['dte_days']}d",
        f"  Total Net GEX: [bold {'green' if data['total_net_gex_cr'] > 0 else 'red'}]{data['total_net_gex_cr']:+,.2f} Cr[/bold]",
        f"  Dealer Regime: [bold cyan]{data['regime']}[/bold cyan]",
    ]
    if data.get("zero_gamma_level"):
        lines.append(f"  Zero-Gamma Level (Flip): [bold yellow]₹{data['zero_gamma_level']:,.1f}[/bold yellow]")
    if data.get("call_wall"):
        lines.append(f"  Call Wall (Resistance): [bold red]₹{data['call_wall']:,.0f}[/bold red]")
    if data.get("put_wall"):
        lines.append(f"  Put Wall (Support): [bold green]₹{data['put_wall']:,.0f}[/bold green]")
    lines.append(f"\n  [italic]{data['interpretation']}[/italic]")

    console.print(
        Panel(
            "\n".join(lines),
            title=f"[bold cyan]⚡ Institutional Options Gamma Exposure (GEX) — {data['underlying']}[/bold cyan]",
            border_style="cyan",
        )
    )
