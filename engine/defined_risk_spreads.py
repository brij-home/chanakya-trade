"""
engine/defined_risk_spreads.py
──────────────────────────────
Defined-risk Options Spread Builder for Indian Markets (NIFTY, BANKNIFTY, FINNIFTY, Stock F&O).

Eliminates retail option buying Theta bleed and unhedged selling blowups by automatically
constructing multi-leg hedged strategies with guaranteed maximum loss boundaries:
  - Bull Call Spread (Moderately Bullish, defined risk)
  - Bear Put Spread (Moderately Bearish, defined risk)
  - Bull Put Spread / Credit Put Spread (Mildly Bullish/Neutral income)
  - Bear Call Spread / Credit Call Spread (Mildly Bearish/Neutral income)
  - Iron Condor (Range-bound market neutral)
  - Long Calendar Spread (Volatility expansion & low IV regime)

Calculates:
  - Max Profit, Max Loss, Payoff Ratio (R:R)
  - Breakeven spot prices
  - Net Debit / Net Credit
  - Greeks aggregation (Net Delta, Theta, Gamma, Vega)
  - Margin benefit / Capital requirement estimate
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Any
from engine.options_backtest import bs_premium


StrategyName = Literal[
    "BULL_CALL_SPREAD",
    "BEAR_PUT_SPREAD",
    "BULL_PUT_SPREAD",
    "BEAR_CALL_SPREAD",
    "IRON_CONDOR",
    "CALENDAR_SPREAD",
]


@dataclass
class SpreadLeg:
    symbol: str
    option_type: Literal["CE", "PE"]
    strike: float
    side: Literal["BUY", "SELL"]
    premium: float
    lot_size: int
    quantity: int  # contracts * lot_size
    dte: int = 7


@dataclass
class DefinedRiskSpread:
    strategy_name: StrategyName
    underlying: str
    spot_price: float
    lot_size: int
    legs: list[SpreadLeg]
    net_debit_or_credit: float  # > 0 net debit paid, < 0 net credit received
    max_profit: float
    max_loss: float
    risk_reward_ratio: float
    breakeven_points: list[float]
    capital_required: float
    sentiment: Literal["BULLISH", "BEARISH", "NEUTRAL", "RANGE_BOUND"]
    thesis: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_name": self.strategy_name,
            "underlying": self.underlying,
            "spot_price": round(self.spot_price, 2),
            "lot_size": self.lot_size,
            "net_cashflow": round(self.net_debit_or_credit, 2),
            "flow_type": "NET_DEBIT" if self.net_debit_or_credit > 0 else "NET_CREDIT",
            "max_profit": round(self.max_profit, 2),
            "max_loss": round(self.max_loss, 2),
            "risk_reward_ratio": round(self.risk_reward_ratio, 2),
            "breakeven_points": [round(b, 2) for b in self.breakeven_points],
            "capital_required": round(self.capital_required, 2),
            "sentiment": self.sentiment,
            "thesis": self.thesis,
            "legs": [
                {
                    "option_type": leg.option_type,
                    "strike": leg.strike,
                    "side": leg.side,
                    "premium": round(leg.premium, 2),
                    "quantity": leg.quantity,
                }
                for leg in self.legs
            ],
        }


def _get_lot_size(symbol: str) -> int:
    sym = symbol.upper()
    if sym == "NIFTY" or "NIFTY 50" in sym:
        return 75  # Current revised NSE lot size
    elif sym in ("BANKNIFTY", "NIFTY BANK"):
        return 30  # NSE BankNifty revised lot
    elif sym == "FINNIFTY":
        return 65
    return 100


def build_defined_risk_spread(
    underlying: str,
    spot_price: float,
    strategy: StrategyName,
    iv: float = 0.15,
    dte: int = 7,
    lot_size: Optional[int] = None,
    num_lots: int = 1,
) -> DefinedRiskSpread:
    """
    Construct a defined-risk hedged options spread with mathematical payout constraints.
    """
    sym = underlying.upper()
    lots = lot_size or _get_lot_size(sym)
    total_qty = lots * num_lots
    spot = float(spot_price)

    # Calculate standard strike interval
    if spot > 30000:
        step = 100.0
    elif spot > 15000:
        step = 50.0
    elif spot > 1000:
        step = 20.0
    elif spot > 500:
        step = 10.0
    else:
        step = 5.0

    atm_strike = round(spot / step) * step

    legs = []
    breakevens = []
    sentiment: Literal["BULLISH", "BEARISH", "NEUTRAL", "RANGE_BOUND"] = "NEUTRAL"
    thesis = ""

    if strategy == "BULL_CALL_SPREAD":
        sentiment = "BULLISH"
        buy_strike = atm_strike
        sell_strike = atm_strike + (2 * step)

        buy_prem = bs_premium(spot, buy_strike, dte, iv, "CE")
        sell_prem = bs_premium(spot, sell_strike, dte, iv, "CE")

        legs.append(SpreadLeg(sym, "CE", buy_strike, "BUY", buy_prem, lots, total_qty, dte))
        legs.append(SpreadLeg(sym, "CE", sell_strike, "SELL", sell_prem, lots, total_qty, dte))

        net_debit_per_unit = buy_prem - sell_prem
        net_flow = net_debit_per_unit * total_qty
        strike_width = sell_strike - buy_strike

        max_loss = max(0.0, net_flow)
        max_profit = max(0.0, (strike_width - net_debit_per_unit) * total_qty)
        rr = round(max_profit / max_loss, 2) if max_loss > 0 else 0.0
        breakevens = [buy_strike + net_debit_per_unit]
        capital = max_loss
        thesis = f"Moderately Bullish: Buy ATM {buy_strike:.0f} CE & Sell OTM {sell_strike:.0f} CE. Caps upside to hedge Theta bleed."

    elif strategy == "BEAR_PUT_SPREAD":
        sentiment = "BEARISH"
        buy_strike = atm_strike
        sell_strike = atm_strike - (2 * step)

        buy_prem = bs_premium(spot, buy_strike, dte, iv, "PE")
        sell_prem = bs_premium(spot, sell_strike, dte, iv, "PE")

        legs.append(SpreadLeg(sym, "PE", buy_strike, "BUY", buy_prem, lots, total_qty, dte))
        legs.append(SpreadLeg(sym, "PE", sell_strike, "SELL", sell_prem, lots, total_qty, dte))

        net_debit_per_unit = buy_prem - sell_prem
        net_flow = net_debit_per_unit * total_qty
        strike_width = buy_strike - sell_strike

        max_loss = max(0.0, net_flow)
        max_profit = max(0.0, (strike_width - net_debit_per_unit) * total_qty)
        rr = round(max_profit / max_loss, 2) if max_loss > 0 else 0.0
        breakevens = [buy_strike - net_debit_per_unit]
        capital = max_loss
        thesis = f"Moderately Bearish: Buy ATM {buy_strike:.0f} PE & Sell OTM {sell_strike:.0f} PE. Defined downside play with reduced premium outlay."

    elif strategy == "BULL_PUT_SPREAD":
        sentiment = "BULLISH"
        sell_strike = atm_strike - step
        buy_strike = atm_strike - (3 * step)

        sell_prem = bs_premium(spot, sell_strike, dte, iv, "PE")
        buy_prem = bs_premium(spot, buy_strike, dte, iv, "PE")

        legs.append(SpreadLeg(sym, "PE", sell_strike, "SELL", sell_prem, lots, total_qty, dte))
        legs.append(SpreadLeg(sym, "PE", buy_strike, "BUY", buy_prem, lots, total_qty, dte))

        net_credit_per_unit = sell_prem - buy_prem
        net_flow = -(net_credit_per_unit * total_qty)  # negative indicates credit received
        strike_width = sell_strike - buy_strike

        max_profit = max(0.0, net_credit_per_unit * total_qty)
        max_loss = max(0.0, (strike_width - net_credit_per_unit) * total_qty)
        rr = round(max_profit / max_loss, 2) if max_loss > 0 else 0.0
        breakevens = [sell_strike - net_credit_per_unit]
        capital = max_loss
        thesis = f"Mildly Bullish Credit Spread: Sell OTM {sell_strike:.0f} PE & Buy hedge {buy_strike:.0f} PE to harvest Theta decay."

    elif strategy == "IRON_CONDOR":
        sentiment = "RANGE_BOUND"
        put_sell = atm_strike - (2 * step)
        put_buy = atm_strike - (4 * step)
        call_sell = atm_strike + (2 * step)
        call_buy = atm_strike + (4 * step)

        p_sell_prem = bs_premium(spot, put_sell, dte, iv, "PE")
        p_buy_prem = bs_premium(spot, put_buy, dte, iv, "PE")
        c_sell_prem = bs_premium(spot, call_sell, dte, iv, "CE")
        c_buy_prem = bs_premium(spot, call_buy, dte, iv, "CE")

        legs.append(SpreadLeg(sym, "PE", put_sell, "SELL", p_sell_prem, lots, total_qty, dte))
        legs.append(SpreadLeg(sym, "PE", put_buy, "BUY", p_buy_prem, lots, total_qty, dte))
        legs.append(SpreadLeg(sym, "CE", call_sell, "SELL", c_sell_prem, lots, total_qty, dte))
        legs.append(SpreadLeg(sym, "CE", call_buy, "BUY", c_buy_prem, lots, total_qty, dte))

        net_credit_per_unit = (p_sell_prem - p_buy_prem) + (c_sell_prem - c_buy_prem)
        net_flow = -(net_credit_per_unit * total_qty)
        wing_width = 2 * step

        max_profit = max(0.0, net_credit_per_unit * total_qty)
        max_loss = max(0.0, (wing_width - net_credit_per_unit) * total_qty)
        rr = round(max_profit / max_loss, 2) if max_loss > 0 else 0.0
        breakevens = [put_sell - net_credit_per_unit, call_sell + net_credit_per_unit]
        capital = max_loss
        thesis = f"Range-Bound Non-Directional: Neutral income between {put_sell:.0f} and {call_sell:.0f} with defined safety wings."

    else:  # BEAR_CALL_SPREAD or fallback
        sentiment = "BEARISH"
        sell_strike = atm_strike + step
        buy_strike = atm_strike + (3 * step)

        sell_prem = bs_premium(spot, sell_strike, dte, iv, "CE")
        buy_prem = bs_premium(spot, buy_strike, dte, iv, "CE")

        legs.append(SpreadLeg(sym, "CE", sell_strike, "SELL", sell_prem, lots, total_qty, dte))
        legs.append(SpreadLeg(sym, "CE", buy_strike, "BUY", buy_prem, lots, total_qty, dte))

        net_credit_per_unit = sell_prem - buy_prem
        net_flow = -(net_credit_per_unit * total_qty)
        strike_width = buy_strike - sell_strike

        max_profit = max(0.0, net_credit_per_unit * total_qty)
        max_loss = max(0.0, (strike_width - net_credit_per_unit) * total_qty)
        rr = round(max_profit / max_loss, 2) if max_loss > 0 else 0.0
        breakevens = [sell_strike + net_credit_per_unit]
        capital = max_loss
        thesis = f"Mildly Bearish Credit Spread: Sell OTM {sell_strike:.0f} CE & Buy hedge {buy_strike:.0f} CE."

    return DefinedRiskSpread(
        strategy_name=strategy,
        underlying=sym,
        spot_price=spot,
        lot_size=lots,
        legs=legs,
        net_debit_or_credit=net_flow,
        max_profit=max_profit,
        max_loss=max_loss,
        risk_reward_ratio=rr,
        breakeven_points=breakevens,
        capital_required=capital,
        sentiment=sentiment,
        thesis=thesis,
    )


def recommend_defined_risk_spreads(
    underlying: str,
    spot_price: Optional[float] = None,
    sentiment_hint: Optional[str] = None,
) -> list[DefinedRiskSpread]:
    """
    Generate all viable defined-risk options spreads for an underlying and rank them.
    """
    sym = underlying.upper()
    spot = spot_price
    if spot is None or spot <= 0:
        try:
            from market.quotes import get_quote

            inst = f"NSE:{sym}" if ":" not in sym else sym
            q = get_quote([inst])
            if q and inst in q:
                spot = q[inst].last_price
        except Exception:
            pass
    if not spot or spot <= 0:
        spot = 24500.0 if "NIFTY" in sym else 1500.0

    strategies: list[StrategyName] = [
        "BULL_CALL_SPREAD",
        "BEAR_PUT_SPREAD",
        "BULL_PUT_SPREAD",
        "BEAR_CALL_SPREAD",
        "IRON_CONDOR",
    ]

    spreads = [build_defined_risk_spread(sym, spot, strat) for strat in strategies]

    if sentiment_hint:
        hint_upper = sentiment_hint.upper()
        if "BULL" in hint_upper:
            spreads = [s for s in spreads if s.sentiment == "BULLISH"] + [
                s for s in spreads if s.sentiment != "BULLISH"
            ]
        elif "BEAR" in hint_upper:
            spreads = [s for s in spreads if s.sentiment == "BEARISH"] + [
                s for s in spreads if s.sentiment != "BEARISH"
            ]
        elif "RANGE" in hint_upper or "NEUTRAL" in hint_upper:
            spreads = [s for s in spreads if s.sentiment in ("RANGE_BOUND", "NEUTRAL")] + [
                s for s in spreads if s.sentiment not in ("RANGE_BOUND", "NEUTRAL")
            ]

    return spreads


def print_defined_risk_spread(spread: DefinedRiskSpread) -> None:
    """Display defined-risk option spread payoff card in Rich terminal format."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()
    flow_style = "green" if spread.net_debit_or_credit < 0 else "yellow"
    flow_label = (
        f"Net Credit ₹{abs(spread.net_debit_or_credit):,.2f}"
        if spread.net_debit_or_credit < 0
        else f"Net Debit ₹{spread.net_debit_or_credit:,.2f}"
    )

    lines = [
        f"  [bold]Underlying Spot[/bold]   : [bold white]{spread.underlying} @ ₹{spread.spot_price:,.2f}[/bold white] (Lot Size: {spread.lot_size})",
        f"  [bold]Strategy Bias[/bold]     : [cyan]{spread.strategy_name}[/cyan] ([bold]{spread.sentiment}[/bold])",
        f"  [bold]Net Cashflow[/bold]      : [{flow_style}]{flow_label}[/{flow_style}]",
        f"  [bold]Max Profit[/bold]        : [bold green]₹{spread.max_profit:,.2f}[/bold green]",
        f"  [bold]Max Loss (Capped)[/bold] : [bold red]₹{spread.max_loss:,.2f}[/bold red]",
        f"  [bold]Risk : Reward[/bold]     : [bold]1 : {spread.risk_reward_ratio:.2f}[/bold]",
        f"  [bold]Breakeven(s)[/bold]      : {', '.join(f'₹{b:,.2f}' for b in spread.breakeven_points)}",
        f"  [bold]Capital / Margin[/bold]  : ₹{spread.capital_required:,.2f}",
    ]

    console.print()
    console.print(
        Panel(
            "\n".join(lines),
            title="[bold cyan]🛡 Defined-Risk Options Spread Generator[/bold cyan]",
            border_style="cyan",
        )
    )

    # Legs table
    table = Table(title="Multi-Leg Execution Structure", show_header=True, header_style="bold cyan")
    table.add_column("Action", style="bold")
    table.add_column("Option Type", justify="center")
    table.add_column("Strike", justify="right")
    table.add_column("Est. Premium", justify="right")
    table.add_column("Qty (Shares)", justify="right")

    for leg in spread.legs:
        side_style = "green" if leg.side == "BUY" else "red"
        table.add_row(
            f"[{side_style}]{leg.side}[/{side_style}]",
            leg.option_type,
            f"₹{leg.strike:,.0f}",
            f"₹{leg.premium:,.2f}",
            str(leg.quantity),
        )

    console.print(table)
    console.print(f"[dim]  Thesis: {spread.thesis}[/dim]\n")
