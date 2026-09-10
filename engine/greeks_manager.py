"""
engine/greeks_manager.py
────────────────────────
Greeks-based position management — delta hedging, roll suggestions,
theta/gamma monitoring with actionable warnings.

Commands:
  greeks          Enhanced dashboard with warnings + actions
  delta-hedge     Suggest trades to neutralize portfolio delta
  roll-options    Find positions expiring soon, suggest rolls

Uses existing portfolio Greeks from engine/portfolio.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


# ── Lightweight Greeks container (for testing without broker) ─


@dataclass
class _PortfolioGreeksLike:
    """Minimal Greeks container matching PortfolioGreeks interface."""

    net_delta: float = 0.0
    net_theta: float = 0.0
    net_vega: float = 0.0
    net_gamma: float = 0.0
    positions_with_greeks: list = field(default_factory=list)
    by_underlying: dict = field(default_factory=dict)


LOT_SIZES: dict[str, int] = {
    "NIFTY": 65,
    "BANKNIFTY": 30,
    "FINNIFTY": 60,
    "MIDCPNIFTY": 120,
    "NIFTYNXT50": 25,
    "SENSEX": 20,
    "BANKEX": 30,
}


# ── Delta Hedge ──────────────────────────────────────────────


@dataclass
class DeltaHedgeSuggestion:
    current_delta: float
    target_delta: float
    gap: float  # how much delta to add (positive) or remove (negative)
    suggestions: list[
        dict
    ]  # [{"action", "instrument", "lots", "delta_change", "why", "when", "how"}]
    cost_estimate: float = 0.0
    lot_size: int = 65
    rupee_sensitivity: float = 0.0
    why: str = ""
    when: str = ""
    how: str = ""


def compute_delta_hedge(
    net_delta: float,
    target_delta: float = 0.0,
    lot_size: int | None = None,
    underlying: str = "NIFTY",
    tolerance: float = 10.0,
    spot_price: float = 24250.0,
) -> DeltaHedgeSuggestion:
    """
    Compute realistic trades needed to move portfolio delta toward target.

    Args:
        net_delta: current net portfolio delta (shares/units equivalent)
        target_delta: desired delta (0 = delta-neutral)
        lot_size: lot size for the hedging instrument (auto-resolved if None)
        underlying: index/stock for hedging
        tolerance: don't hedge if gap is within this range
        spot_price: current underlying spot price for cash sensitivity calculation

    Returns:
        DeltaHedgeSuggestion with concrete trade suggestions and why/when/how rationale.
    """
    sym = underlying.upper().replace("NSE:", "").replace("NFO:", "")
    actual_lot_size = lot_size if lot_size is not None else LOT_SIZES.get(sym, 75)

    gap = target_delta - net_delta  # positive = need to buy, negative = need to sell
    suggestions = []

    # Calculate monetary cash sensitivity per 1% move in underlying
    point_move_1pct = spot_price * 0.01
    rupee_sensitivity = round(net_delta * point_move_1pct, 2)

    # Why, When, How narrative explanations
    abs_gap = abs(gap)
    pts_1pct = round(point_move_1pct, 1)

    if net_delta > tolerance:
        direction = "Long Delta (Bullish Exposure)"
        risk_desc = f"If {sym} drops 1% (~₹{pts_1pct} pts), the options book suffers an immediate ~₹{abs(rupee_sensitivity):,.0f} loss from directional delta drift before volatility/gamma compensations."
    elif net_delta < -tolerance:
        direction = "Short Delta (Bearish Exposure)"
        risk_desc = f"If {sym} rallies 1% (~₹{pts_1pct} pts), the options book suffers an immediate ~₹{abs(rupee_sensitivity):,.0f} loss from upside delta drift."
    else:
        direction = "Delta Neutral"
        risk_desc = f"Portfolio directional exposure is balanced within tolerance (±{tolerance} delta). No mandatory delta hedge required."

    why_text = (
        f"Directional Risk Stance: {direction}. {risk_desc} "
        f"Delta hedging neutralizes directional drift, isolating pure Theta time decay and Vega volatility capture."
    )

    when_text = (
        f"1. Spot Drift: Rebalance when {sym} moves > ±0.75% (~₹{round(spot_price * 0.0075)} pts) from current spot (₹{spot_price:,.0f}).\n"
        f"2. Greek Threshold: Rebalance whenever Net Delta deviates beyond ±{tolerance:.1f} from target {target_delta:.1f}.\n"
        f"3. Time of Day: Execute rebalance around 03:15 PM IST to mitigate overnight gap risk, or ahead of major macro announcements."
    )

    if abs_gap <= tolerance:
        return DeltaHedgeSuggestion(
            current_delta=net_delta,
            target_delta=target_delta,
            gap=gap,
            suggestions=[],
            lot_size=actual_lot_size,
            rupee_sensitivity=rupee_sensitivity,
            why=why_text,
            when=when_text,
            how="Portfolio is within safe delta neutral bounds. Maintain current positions and monitor 03:15 PM IST closing drift.",
        )

    # Futures hedge (1 future lot = actual_lot_size delta)
    delta_per_lot = actual_lot_size
    lots_needed = abs_gap / delta_per_lot
    lots_rounded = max(1, math.ceil(lots_needed))
    est_margin = round(lots_rounded * actual_lot_size * spot_price * 0.11)

    how_text = (
        f"Route a LIMIT order to {'BUY' if gap > 0 else 'SELL'} {lots_rounded} Lot{'s' if lots_rounded > 1 else ''} "
        f"({lots_rounded * actual_lot_size} Qty) of {sym} nearest-expiry Futures at ₹{spot_price:,.2f} "
        f"(Est. Margin: ₹{est_margin:,.0f}) with an invalidation stop-loss placed ±{round(spot_price * 0.005)} pts away."
    )

    if gap > 0:
        # Need positive delta: BUY futures
        suggestions.append(
            {
                "action": "BUY",
                "instrument": f"{sym} FUT (nearest expiry)",
                "lots": lots_rounded,
                "quantity": lots_rounded * actual_lot_size,
                "delta_change": f"+{lots_rounded * delta_per_lot:.0f}",
                "margin_required": est_margin,
                "note": f"Adds +{lots_rounded * delta_per_lot:.0f} delta with zero theta decay",
                "strategy_type": "FUTURES",
            }
        )
    else:
        # Need negative delta: SELL futures
        suggestions.append(
            {
                "action": "SELL",
                "instrument": f"{sym} FUT (nearest expiry)",
                "lots": lots_rounded,
                "quantity": lots_rounded * actual_lot_size,
                "delta_change": f"-{lots_rounded * delta_per_lot:.0f}",
                "margin_required": est_margin,
                "note": f"Reduces delta by {lots_rounded * delta_per_lot:.0f} with zero theta decay",
                "strategy_type": "FUTURES",
            }
        )

    # Options hedge alternative (ATM option has ~0.50 delta per share)
    opt_lots = max(1, math.ceil((abs_gap / (actual_lot_size * 0.5))))
    opt_strike = round(spot_price / 50) * 50
    opt_type = "CE" if gap > 0 else "PE"
    opt_cost = round(opt_lots * actual_lot_size * (spot_price * 0.008))

    suggestions.append(
        {
            "action": "BUY",
            "instrument": f"{sym} {opt_strike} {opt_type} (nearest expiry)",
            "lots": opt_lots,
            "quantity": opt_lots * actual_lot_size,
            "delta_change": f"{'+' if gap > 0 else '-'}{opt_lots * actual_lot_size * 0.5:.0f}",
            "margin_required": opt_cost,
            "note": f"Defined-risk option hedge: adds {'+' if gap > 0 else '-'}{opt_lots * actual_lot_size * 0.5:.0f} delta with capped max risk",
            "strategy_type": "OPTIONS",
        }
    )

    return DeltaHedgeSuggestion(
        current_delta=net_delta,
        target_delta=target_delta,
        gap=gap,
        suggestions=suggestions,
        cost_estimate=float(est_margin),
        lot_size=actual_lot_size,
        rupee_sensitivity=rupee_sensitivity,
        why=why_text,
        when=when_text,
        how=how_text,
    )


# ── Roll Suggestions ─────────────────────────────────────────


@dataclass
class RollSuggestion:
    current_symbol: str
    current_expiry: str
    current_dte: int
    current_premium: float
    next_expiry: str
    next_premium: float
    roll_cost: float  # positive = credit, negative = debit
    recommendation: str  # "ROLL" | "LET EXPIRE" | "CLOSE"
    reason: str


def compute_roll_suggestions(
    positions: list[dict],
    dte_threshold: int = 3,
) -> list[RollSuggestion]:
    """
    Find F&O positions expiring soon and suggest rolls.

    Args:
        positions: list of position dicts with keys:
            symbol, underlying, expiry, strike, option_type, qty, ltp
        dte_threshold: suggest rolls for positions with DTE <= this

    Returns:
        List of RollSuggestion for positions needing attention.
    """
    today = date.today()
    suggestions = []

    for pos in positions:
        expiry_str = pos.get("expiry", "")
        if not expiry_str:
            continue

        try:
            expiry_date = date.fromisoformat(expiry_str[:10])
        except (ValueError, TypeError):
            continue

        dte = (expiry_date - today).days
        if dte > dte_threshold:
            continue

        ltp = pos.get("ltp", 0)

        # Next weekly expiry: current + 7 days (approximate)
        next_expiry = expiry_date + timedelta(days=7)
        # Rough estimate: next expiry premium ≈ current + time value bump
        next_premium_estimate = ltp * 1.5 if ltp > 0 else 0

        # Recommendation logic
        if dte <= 0:
            rec = "CLOSE"
            reason = "Already expired or expiring today"
        elif ltp < 5:
            rec = "LET EXPIRE"
            reason = f"Premium too low (₹{ltp:.1f}) — not worth rolling"
        else:
            rec = "ROLL"
            reason = f"Expiring in {dte}d with ₹{ltp:.1f} premium — roll to preserve position"

        roll_cost = next_premium_estimate - ltp if rec == "ROLL" else 0

        suggestions.append(
            RollSuggestion(
                current_symbol=pos.get("symbol", ""),
                current_expiry=expiry_str,
                current_dte=dte,
                current_premium=ltp,
                next_expiry=next_expiry.isoformat(),
                next_premium=round(next_premium_estimate, 2),
                roll_cost=round(roll_cost, 2),
                recommendation=rec,
                reason=reason,
            )
        )

    return suggestions


# ── Greeks Dashboard ─────────────────────────────────────────


@dataclass
class GreeksDashboard:
    net_delta: float
    net_theta: float
    net_vega: float
    net_gamma: float
    warnings: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    risk_level: str = "LOW"


# Thresholds for warnings
DELTA_WARN = 200  # net delta above this = directionally exposed
THETA_WARN = -500  # daily theta below this = heavy time decay
GAMMA_WARN = 1.0  # gamma above this = high gamma risk
VEGA_WARN = 500  # vega above this = significant IV exposure


def build_dashboard(
    net_delta: float = 0,
    net_theta: float = 0,
    net_vega: float = 0,
    net_gamma: float = 0,
) -> GreeksDashboard:
    """
    Build a Greeks dashboard with warnings and action items.

    Args:
        net_delta/theta/vega/gamma: portfolio-level Greeks

    Returns:
        GreeksDashboard with risk classification, warnings, and actions.
    """
    warnings = []
    actions = []
    risk_score = 0

    # Delta check
    if abs(net_delta) > DELTA_WARN:
        direction = "LONG" if net_delta > 0 else "SHORT"
        warnings.append(
            f"High delta exposure: {net_delta:+.0f} ({direction}) — "
            f"portfolio is directionally exposed"
        )
        actions.append(
            f"Delta-hedge: {'sell' if net_delta > 0 else 'buy'} "
            f"~{abs(net_delta) / 25:.0f} NIFTY lots to neutralize"
        )
        risk_score += 2

    # Theta check
    if net_theta < THETA_WARN:
        warnings.append(
            f"Heavy theta decay: ₹{abs(net_theta):,.0f}/day — "
            f"losing ₹{abs(net_theta) * 5:,.0f}/week in time value"
        )
        actions.append("Close or roll short-dated positions to reduce theta bleed")
        risk_score += 2

    # Gamma check
    if abs(net_gamma) > GAMMA_WARN:
        warnings.append(
            f"High gamma: {net_gamma:+.2f} — delta will change rapidly with price moves"
        )
        actions.append("Reduce gamma exposure before expiry — close or roll near-expiry options")
        risk_score += 3

    # Vega check
    if abs(net_vega) > VEGA_WARN:
        warnings.append(
            f"Significant vega exposure: ₹{net_vega:,.0f} per 1% IV move — "
            f"{'long' if net_vega > 0 else 'short'} volatility"
        )
        actions.append(
            f"{'IV crush will hurt' if net_vega > 0 else 'IV spike will hurt'} — "
            "consider hedging with opposite vega position"
        )
        risk_score += 1

    # Risk level
    if risk_score >= 5:
        risk_level = "CRITICAL"
    elif risk_score >= 3:
        risk_level = "HIGH"
    elif risk_score >= 1:
        risk_level = "MODERATE"
    else:
        risk_level = "LOW"

    return GreeksDashboard(
        net_delta=net_delta,
        net_theta=net_theta,
        net_vega=net_vega,
        net_gamma=net_gamma,
        warnings=warnings,
        actions=actions,
        risk_level=risk_level,
    )


# ── Display Functions ────────────────────────────────────────


def print_delta_hedge(suggestion: DeltaHedgeSuggestion) -> None:
    """Display delta hedge suggestions as Rich panel."""
    lines = [
        f"  Current Delta  : [bold]{suggestion.current_delta:+.1f}[/bold]",
        f"  Target Delta   : {suggestion.target_delta:+.1f}",
        f"  Gap            : {suggestion.gap:+.1f}",
    ]

    if not suggestion.suggestions:
        lines.append("\n  [green]Portfolio is within tolerance — no hedge needed.[/green]")
    else:
        lines.append("\n  [bold]Suggested Trades:[/bold]")
        for s in suggestion.suggestions:
            action_color = "red" if s["action"] == "SELL" else "green"
            lines.append(
                f"    [{action_color}]{s['action']:4s}[/{action_color}] "
                f"{s['instrument']}  ×{s['lots']}  ({s['delta_change']} delta)"
            )
            if s.get("note"):
                lines.append(f"    [dim]{s['note']}[/dim]")

    console.print(
        Panel(
            "\n".join(lines),
            title="[bold cyan]Delta Hedge Suggestion[/bold cyan]",
            border_style="cyan",
        )
    )


def print_roll_suggestions(suggestions: list[RollSuggestion]) -> None:
    """Display roll suggestions as Rich table."""
    if not suggestions:
        console.print("[dim]No positions need rolling at this time.[/dim]")
        return

    table = Table(title="Roll Suggestions", show_lines=True)
    table.add_column("Symbol", style="cyan")
    table.add_column("Expiry", width=12)
    table.add_column("DTE", justify="right", width=5)
    table.add_column("Premium", justify="right")
    table.add_column("Action", width=12)
    table.add_column("Reason")

    for s in suggestions:
        rec_color = {"ROLL": "yellow", "LET EXPIRE": "dim", "CLOSE": "red"}.get(
            s.recommendation, "white"
        )
        table.add_row(
            s.current_symbol[:20],
            s.current_expiry[:10],
            str(s.current_dte),
            f"₹{s.current_premium:,.1f}",
            f"[{rec_color}]{s.recommendation}[/{rec_color}]",
            s.reason[:50],
        )

    console.print(table)


def print_dashboard(dash: GreeksDashboard) -> None:
    """Display enhanced Greeks dashboard with warnings."""
    risk_colors = {"LOW": "green", "MODERATE": "yellow", "HIGH": "red", "CRITICAL": "bold red"}
    risk_color = risk_colors.get(dash.risk_level, "white")

    lines = [
        f"  Δ Delta  : [cyan]{dash.net_delta:+.1f}[/cyan]",
        f"  Θ Theta  : [red]₹{dash.net_theta:,.0f}/day[/red]",
        f"  ν Vega   : [yellow]₹{dash.net_vega:,.0f} per 1% IV[/yellow]",
        f"  Γ Gamma  : {dash.net_gamma:+.3f}",
        f"\n  Risk Level: [{risk_color}]{dash.risk_level}[/{risk_color}]",
    ]

    if dash.warnings:
        lines.append("\n  [bold]⚠  Warnings:[/bold]")
        for w in dash.warnings:
            lines.append(f"    [yellow]• {w}[/yellow]")

    if dash.actions:
        lines.append("\n  [bold]Actions:[/bold]")
        for a in dash.actions:
            lines.append(f"    → {a}")

    console.print(
        Panel(
            "\n".join(lines),
            title="[bold cyan]Greeks Dashboard[/bold cyan]",
            border_style="cyan",
        )
    )


# ── Black-76 Model for Commodity Futures Options ─────────────────────────────


def black_76_price_and_greeks(
    futures_price: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float = 0.065,
    volatility: float = 0.30,
    option_type: str = "CE",
) -> dict[str, float]:
    """
    Computes theoretical option price and Greeks using the Black-76 model for options on futures.
    Standard pricing model for MCX Commodity options and futures options worldwide.

    Formulas:
      d1 = [ln(F/K) + 0.5 * sigma^2 * T] / (sigma * sqrt(T))
      d2 = d1 - sigma * sqrt(T)
      Call = e^(-rT) * [F * N(d1) - K * N(d2)]
      Put  = e^(-rT) * [K * N(-d2) - F * N(-d1)]
    """
    F = max(0.001, float(futures_price))
    K = max(0.001, float(strike))
    T = max(1e-5, float(time_to_expiry_years))
    r = float(risk_free_rate)
    sigma = max(0.01, float(volatility))
    is_call = str(option_type).upper() in ("CE", "CALL")

    sqrt_T = math.sqrt(T)
    sigma_sqrt_T = sigma * sqrt_T

    d1 = (math.log(F / K) + 0.5 * (sigma**2) * T) / sigma_sqrt_T
    d2 = d1 - sigma_sqrt_T

    def norm_cdf(x: float) -> float:
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    def norm_pdf(x: float) -> float:
        return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * (x**2))

    discount = math.exp(-r * T)
    pdf_d1 = norm_pdf(d1)

    if is_call:
        price = discount * (F * norm_cdf(d1) - K * norm_cdf(d2))
        delta = discount * norm_cdf(d1)
        theta_annual = -(discount * F * sigma * pdf_d1) / (2.0 * sqrt_T) - r * discount * (
            F * norm_cdf(d1) - K * norm_cdf(d2)
        )
    else:
        price = discount * (K * norm_cdf(-d2) - F * norm_cdf(-d1))
        delta = -discount * norm_cdf(-d1)
        theta_annual = -(discount * F * sigma * pdf_d1) / (2.0 * sqrt_T) - r * discount * (
            K * norm_cdf(-d2) - F * norm_cdf(-d1)
        )

    gamma = (discount * pdf_d1) / (F * sigma_sqrt_T)
    vega = (discount * F * sqrt_T * pdf_d1) / 100.0  # per 1% change in IV
    theta_daily = theta_annual / 365.0

    return {
        "price": max(0.05, round(price, 2)),
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta": round(theta_daily, 2),
        "vega": round(vega, 2),
        "d1": round(d1, 4),
        "d2": round(d2, 4),
    }


def get_mcx_prompt_expiry_and_dte(sym: str, as_of: Optional[Any] = None) -> tuple[str, int]:
    """
    Resolves the exact prompt calendar expiry date and DTE for MCX commodities:
      - CRUDEOIL / CRUDEOILM: Mid-month cycle (~15th-17th of month, 2 business days prior to futures expiry)
      - NATURALGAS / NATGASMINI: ~24th-26th of month
      - GOLD / GOLDM / SILVER / SILVERM: ~27th of month (matching Zerodha 27SEP)
      - COPPER / BASE METALS: ~27th-28th of month
    """
    from datetime import datetime, timezone, timedelta, date

    IST = timezone(timedelta(hours=5, minutes=30))
    now_dt = as_of or datetime.now(IST)
    today = now_dt.date() if isinstance(now_dt, datetime) else now_dt

    clean = sym.upper().replace("MCX:", "").strip()
    if clean in ("CRUDEOIL", "CRUDEOILM"):
        exp_day = 16  # mid-month option expiry for Crude Oil
    elif clean in ("NATURALGAS", "NATGASMINI"):
        exp_day = 25
    elif clean in ("GOLD", "GOLDM", "SILVER", "SILVERM"):
        exp_day = 27
    else:
        exp_day = 27

    try:
        cand = date(today.year, today.month, exp_day)
    except ValueError:
        cand = date(today.year, today.month, 28)

    # If prompt date has already expired, roll to next month
    if cand <= today:
        next_m = 1 if today.month == 12 else today.month + 1
        next_y = today.year + 1 if today.month == 12 else today.year
        cand = date(next_y, next_m, exp_day)

    dte = max(1, (cand - today).days)
    return cand.strftime("%Y-%m-%d"), dte


def build_commodity_option_chain_synthetic(
    underlying: str,
    futures_price: float,
    iv: Optional[float] = None,
    days_to_expiry: int = 14,
    expiry_date: Optional[str] = None,
) -> list:
    """
    Generates a deterministic, institutionally grounded MCX commodity options chain
    using the Black-76 model when live broker credentials are unavailable or off-market.
    Provides 21 strikes (10 OTM, 1 ATM, 10 ITM) for CE and PE with exact lot sizes.
    """
    from brokers.base import OptionsContract
    from market.instruments import STANDARD_LOT_SIZES

    sym = underlying.upper().replace("MCX:", "").strip()
    F = float(futures_price)
    if F <= 0:
        return []

    # Strike step mapping for Indian MCX contracts
    strike_step_map = {
        "CRUDEOIL": 50.0,
        "CRUDEOILM": 50.0,
        "NATURALGAS": 5.0,
        "NATGASMINI": 5.0,
        "GOLD": 500.0,
        "GOLDM": 100.0,
        "SILVER": 1000.0,
        "SILVERM": 500.0,
        "COPPER": 10.0,
        "ZINC": 5.0,
    }
    step = strike_step_map.get(sym, 50.0)

    # Base typical IVs for commodities
    base_iv_map = {
        "CRUDEOIL": 0.34,
        "NATURALGAS": 0.48,
        "GOLD": 0.16,
        "SILVER": 0.24,
        "COPPER": 0.22,
        "ZINC": 0.20,
    }
    vol = iv if iv is not None else base_iv_map.get(sym, 0.30)
    lot_size = STANDARD_LOT_SIZES.get(sym, 1)

    if not expiry_date:
        target_exp, calc_dte = get_mcx_prompt_expiry_and_dte(sym)
        # Use calculated prompt calendar DTE unless caller explicitly specified a non-default custom DTE
        dte = days_to_expiry if (days_to_expiry is not None and days_to_expiry != 14) else calc_dte
    else:
        target_exp = expiry_date
        try:
            from datetime import datetime, timezone, timedelta

            IST = timezone(timedelta(hours=5, minutes=30))
            exp_d = datetime.strptime(expiry_date, "%Y-%m-%d").date()
            dte = max(1, (exp_d - datetime.now(IST).date()).days)
        except Exception:
            dte = max(1, days_to_expiry or 14)

    T = dte / 365.0

    # Find nearest ATM strike
    atm_strike = round(F / step) * step

    contracts: list[OptionsContract] = []
    # 10 strikes below and 10 strikes above ATM
    strikes = [atm_strike + i * step for i in range(-10, 11)]

    for strike in strikes:
        strike_val = round(strike, 2 if step < 1.0 else 0)
        strike_int = int(strike_val)

        for opt_type in ("CE", "PE"):
            greeks = black_76_price_and_greeks(
                futures_price=F,
                strike=strike_val,
                time_to_expiry_years=T,
                volatility=vol,
                option_type=opt_type,
            )
            price = greeks["price"]
            # Spread: 1-2 ticks
            spread = max(0.10, round(price * 0.004, 2))
            bid = max(0.05, round(price - spread / 2.0, 2))
            ask = round(price + spread / 2.0, 2)

            # Realistic mock OI: higher near ATM, tapering out
            dist = abs(strike_val - F) / step
            mock_oi = max(50, int(5000 * math.exp(-0.15 * dist)))

            try:
                from datetime import datetime

                d_obj = datetime.strptime(target_exp, "%Y-%m-%d")
                exp_tag = d_obj.strftime("%y%b").upper()
                contract_symbol = f"MCX:{sym}{exp_tag}{strike_int}{opt_type}"
            except Exception:
                contract_symbol = (
                    f"MCX:{sym}{target_exp.replace('-', '')[2:]}{strike_int}{opt_type}"
                )

            contracts.append(
                OptionsContract(
                    symbol=contract_symbol,
                    underlying=sym,
                    expiry=target_exp,
                    strike=strike_val,
                    option_type=opt_type,
                    last_price=price,
                    oi=mock_oi,
                    oi_change=int(mock_oi * 0.05),
                    volume=int(mock_oi * 1.5),
                    iv=round(vol * 100.0, 1),
                    bid=bid,
                    ask=ask,
                    lot_size=lot_size,
                    exchange="MCX",
                )
            )

    return sorted(contracts, key=lambda c: (c.expiry, c.strike, c.option_type))
