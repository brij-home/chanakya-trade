"""
engine/charges.py
─────────────────
Effective-dated Indian Market Transaction Cost Engine.

Calculates statutory taxes, exchange fees, SEBI turnover fees, stamp duty,
and brokerage charges across NSE/BSE Cash and NFO F&O segments.

Used identically across:
  - Pre-order tickets & margin calculations
  - Paper trading simulation
  - Backtesting engines (vectorized & event-driven)
  - Post-trade reconciliation & P&L accounting

Statutory Rates (Effective 2024-2026 Union Budget / SEBI schedules):
  - STT:
      • Equity Delivery : 0.1% on Buy and Sell turnover
      • Equity Intraday : 0.025% on Sell turnover
      • Futures         : 0.02% on Sell turnover
      • Options         : 0.1% (or 0.125% for exercised contracts) on Sell premium turnover
  - Exchange Turnover Charges:
      • NSE Cash        : 0.00297% (₹297 / crore)
      • NSE Futures     : 0.00173% (₹173 / crore)
      • NSE Options     : 0.03503% (on premium turnover)
  - GST: 18% on (Brokerage + Exchange Turnover Charges)
  - SEBI Turnover Fee : ₹10 / crore (0.0001%) on turnover
  - Stamp Duty (Buy side only):
      • Equity Delivery : 0.015% (₹1,500 / crore)
      • Equity Intraday : 0.003% (₹300 / crore)
      • Futures         : 0.002% (₹200 / crore)
      • Options         : 0.003% (₹300 / crore on premium)
  - Brokerage: Default discount model (₹20 flat or 0.03%, ₹0 for delivery).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal, Dict, Any

SegmentType = Literal["EQUITY_DELIVERY", "EQUITY_INTRADAY", "FUTURES", "OPTIONS"]
OrderSide = Literal["BUY", "SELL"]


@dataclass
class TransactionCostBreakdown:
    """Detailed statutory and broker cost breakdown for an Indian market order."""

    segment: SegmentType
    side: OrderSide
    notional_turnover: Decimal
    brokerage: Decimal
    stt: Decimal
    exchange_charges: Decimal
    gst: Decimal
    stamp_duty: Decimal
    sebi_charges: Decimal
    total_charges: Decimal
    effective_pct: Decimal  # total charges as % of turnover

    def to_dict(self) -> Dict[str, Any]:
        return {
            "segment": self.segment,
            "side": self.side,
            "notional_turnover": float(self.notional_turnover),
            "brokerage": float(self.brokerage),
            "stt": float(self.stt),
            "exchange_charges": float(self.exchange_charges),
            "gst": float(self.gst),
            "stamp_duty": float(self.stamp_duty),
            "sebi_charges": float(self.sebi_charges),
            "total_charges": float(self.total_charges),
            "effective_pct": float(self.effective_pct),
        }


def _round_currency(val: Decimal | float) -> Decimal:
    """Round to 2 decimal places (paisa)."""
    return Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_transaction_charges(
    price: float | Decimal,
    quantity: int,
    segment: SegmentType = "EQUITY_DELIVERY",
    side: OrderSide = "BUY",
    brokerage_rate: float | None = None,  # None = use standard discount defaults
    broker_flat_fee: float = 20.0,
) -> TransactionCostBreakdown:
    """
    Calculate full statutory Indian transaction costs for an order leg.

    Args:
        price: Price per share/contract (or option premium).
        quantity: Total quantity (shares or contracts).
        segment: EQUITY_DELIVERY, EQUITY_INTRADAY, FUTURES, or OPTIONS.
        side: BUY or SELL.
        brokerage_rate: Custom brokerage % (if variable).
        broker_flat_fee: Flat max brokerage fee (default ₹20).

    Returns:
        TransactionCostBreakdown dataclass with all individual line items.
    """
    p = Decimal(str(price))
    q = Decimal(str(abs(quantity)))
    turnover = p * q

    if turnover <= Decimal("0"):
        return TransactionCostBreakdown(
            segment=segment,
            side=side,
            notional_turnover=Decimal("0.00"),
            brokerage=Decimal("0.00"),
            stt=Decimal("0.00"),
            exchange_charges=Decimal("0.00"),
            gst=Decimal("0.00"),
            stamp_duty=Decimal("0.00"),
            sebi_charges=Decimal("0.00"),
            total_charges=Decimal("0.00"),
            effective_pct=Decimal("0.00"),
        )

    # 1. Brokerage calculation
    if segment == "EQUITY_DELIVERY":
        # Zero brokerage for delivery or max ₹20 depending on broker plan
        if brokerage_rate is not None:
            brokerage = min(turnover * Decimal(str(brokerage_rate)), Decimal(str(broker_flat_fee)))
        else:
            brokerage = Decimal("0.00")
    else:
        # Intraday & F&O: 0.03% or flat ₹20 whichever is lower
        rate = Decimal("0.0003") if brokerage_rate is None else Decimal(str(brokerage_rate))
        brokerage = min(turnover * rate, Decimal(str(broker_flat_fee)))

    # 2. Securities Transaction Tax (STT)
    stt = Decimal("0.00")
    if segment == "EQUITY_DELIVERY":
        # 0.1% on both Buy and Sell
        stt = turnover * Decimal("0.001")
    elif segment == "EQUITY_INTRADAY":
        # 0.025% on Sell only
        if side == "SELL":
            stt = turnover * Decimal("0.00025")
    elif segment == "FUTURES":
        # 0.02% on Sell only
        if side == "SELL":
            stt = turnover * Decimal("0.0002")
    elif segment == "OPTIONS":
        # 0.1% on Sell premium turnover
        if side == "SELL":
            stt = turnover * Decimal("0.001")

    # 3. Exchange Turnover Charges (NSE rates)
    if segment in ("EQUITY_DELIVERY", "EQUITY_INTRADAY"):
        exchange_charges = turnover * Decimal("0.0000297")  # 0.00297%
    elif segment == "FUTURES":
        exchange_charges = turnover * Decimal("0.0000173")  # 0.00173%
    elif segment == "OPTIONS":
        exchange_charges = turnover * Decimal("0.0003503")  # 0.03503% on premium

    # 4. GST (18% on Brokerage + Exchange Charges)
    gst = (brokerage + exchange_charges) * Decimal("0.18")

    # 5. Stamp Duty (Buy side only)
    stamp_duty = Decimal("0.00")
    if side == "BUY":
        if segment == "EQUITY_DELIVERY":
            stamp_duty = turnover * Decimal("0.00015")  # 0.015%
        elif segment == "EQUITY_INTRADAY":
            stamp_duty = turnover * Decimal("0.00003")  # 0.003%
        elif segment == "FUTURES":
            stamp_duty = turnover * Decimal("0.00002")  # 0.002%
        elif segment == "OPTIONS":
            stamp_duty = turnover * Decimal("0.00003")  # 0.003% on premium

    # 6. SEBI Turnover Charges (₹10 / crore = 0.0001%)
    sebi_charges = turnover * Decimal("0.000001")

    # Quantize line items to ₹0.01
    b_rounded = _round_currency(brokerage)
    stt_rounded = _round_currency(stt)
    ex_rounded = _round_currency(exchange_charges)
    gst_rounded = _round_currency(gst)
    sd_rounded = _round_currency(stamp_duty)
    sebi_rounded = _round_currency(sebi_charges)

    total = b_rounded + stt_rounded + ex_rounded + gst_rounded + sd_rounded + sebi_rounded
    effective_pct = (
        _round_currency((total / turnover) * Decimal("100"))
        if turnover > Decimal("0")
        else Decimal("0.00")
    )

    return TransactionCostBreakdown(
        segment=segment,
        side=side,
        notional_turnover=_round_currency(turnover),
        brokerage=b_rounded,
        stt=stt_rounded,
        exchange_charges=ex_rounded,
        gst=gst_rounded,
        stamp_duty=sd_rounded,
        sebi_charges=sebi_rounded,
        total_charges=_round_currency(total),
        effective_pct=effective_pct,
    )


# ── Capital Gains & Tax Engine (Post-Budget 2024/2026 Rules) ──


@dataclass
class CapitalGainsEstimate:
    """Breakdown of realized/unrealized capital gains tax under Indian Income Tax Act."""

    gross_pnl: float
    holding_period_days: int
    tax_type: Literal["STCG", "LTCG", "SPECULATIVE_INTRADAY", "BUSINESS_FO"]
    tax_rate_pct: float
    tax_exemption_applied: float
    estimated_tax: float
    net_post_tax_pnl: float
    effective_tax_pct: float
    rules_applied: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "gross_pnl": round(self.gross_pnl, 2),
            "holding_period_days": self.holding_period_days,
            "tax_type": self.tax_type,
            "tax_rate_pct": round(self.tax_rate_pct, 2),
            "tax_exemption_applied": round(self.tax_exemption_applied, 2),
            "estimated_tax": round(self.estimated_tax, 2),
            "net_post_tax_pnl": round(self.net_post_tax_pnl, 2),
            "effective_tax_pct": round(self.effective_tax_pct, 2),
            "rules_applied": self.rules_applied,
        }


def calculate_capital_gains_tax(
    gross_pnl: float,
    holding_period_days: int,
    segment: SegmentType = "EQUITY_DELIVERY",
    prior_accumulated_ltcg: float = 0.0,
    ltcg_exemption_limit: float = 125000.0,  # ₹1.25 Lakhs post-budget 2024
) -> CapitalGainsEstimate:
    """
    Compute Indian capital gains tax under post-budget rules.
    - Equity Delivery:
        • STCG (< 365 days): Flat 20% (Section 111A).
        • LTCG (>= 365 days): 12.5% on gains above ₹1.25L exemption (Section 112A).
    - Equity Intraday:
        • Speculative Business Income taxed at investor slab (assumed standard 30% conservative).
    - F&O:
        • Non-Speculative Business Income taxed at slab (Section 43(5)).
    """
    pnl = float(gross_pnl)
    if pnl <= 0:
        return CapitalGainsEstimate(
            gross_pnl=pnl,
            holding_period_days=holding_period_days,
            tax_type="LTCG"
            if holding_period_days >= 365 and segment == "EQUITY_DELIVERY"
            else ("STCG" if segment == "EQUITY_DELIVERY" else "BUSINESS_FO"),
            tax_rate_pct=0.0,
            tax_exemption_applied=0.0,
            estimated_tax=0.0,
            net_post_tax_pnl=pnl,
            effective_tax_pct=0.0,
            rules_applied="Loss incurred: No tax liability. Can be carried forward for set-off up to 8 assessment years.",
        )

    if segment == "EQUITY_DELIVERY":
        if holding_period_days < 365:
            # Short-Term Capital Gains (Section 111A)
            tax_rate = 20.0
            tax = pnl * 0.20
            net = pnl - tax
            return CapitalGainsEstimate(
                gross_pnl=pnl,
                holding_period_days=holding_period_days,
                tax_type="STCG",
                tax_rate_pct=tax_rate,
                tax_exemption_applied=0.0,
                estimated_tax=tax,
                net_post_tax_pnl=net,
                effective_tax_pct=tax_rate,
                rules_applied="Section 111A: Short-term equity capital gain flat 20.0% (Post-Budget 2024).",
            )
        else:
            # Long-Term Capital Gains (Section 112A)
            remaining_exemption = max(0.0, ltcg_exemption_limit - prior_accumulated_ltcg)
            taxable_gain = max(0.0, pnl - remaining_exemption)
            exemption_used = min(pnl, remaining_exemption)
            tax = taxable_gain * 0.125
            net = pnl - tax
            eff_pct = (tax / pnl * 100.0) if pnl > 0 else 0.0
            return CapitalGainsEstimate(
                gross_pnl=pnl,
                holding_period_days=holding_period_days,
                tax_type="LTCG",
                tax_rate_pct=12.5,
                tax_exemption_applied=exemption_used,
                estimated_tax=tax,
                net_post_tax_pnl=net,
                effective_tax_pct=eff_pct,
                rules_applied=f"Section 112A: Long-term capital gain 12.5% above ₹1.25L exemption (Used ₹{exemption_used:,.0f}).",
            )
    elif segment == "EQUITY_INTRADAY":
        # Speculative Business Income (assumed 30% standard bracket)
        tax = pnl * 0.30
        return CapitalGainsEstimate(
            gross_pnl=pnl,
            holding_period_days=holding_period_days,
            tax_type="SPECULATIVE_INTRADAY",
            tax_rate_pct=30.0,
            tax_exemption_applied=0.0,
            estimated_tax=tax,
            net_post_tax_pnl=pnl - tax,
            effective_tax_pct=30.0,
            rules_applied="Section 43(5): Speculative Business Income taxed at applicable personal income slab rate (~30%).",
        )
    else:
        # F&O: Non-speculative business income
        tax = pnl * 0.30
        return CapitalGainsEstimate(
            gross_pnl=pnl,
            holding_period_days=holding_period_days,
            tax_type="BUSINESS_FO",
            tax_rate_pct=30.0,
            tax_exemption_applied=0.0,
            estimated_tax=tax,
            net_post_tax_pnl=pnl - tax,
            effective_tax_pct=30.0,
            rules_applied="Section 43(5): Non-Speculative Business Income taxed at applicable slab rate (~30%). Eligible for business expense deductions.",
        )


def calculate_fo_turnover(trades: list[dict]) -> dict[str, Any]:
    """
    Calculate Section 43(5) & Section 44AB Tax Audit Turnover for F&O.
    Under ICAI Guidance Note:
    - F&O Turnover = Absolute sum of positive and negative P&L on all squared-off contracts
                     + Premium received on sale of options contracts.
    """
    total_abs_pnl = 0.0
    options_premium_turnover = 0.0
    trade_count = len(trades)

    for t in trades:
        pnl = float(t.get("pnl", 0.0))
        total_abs_pnl += abs(pnl)
        if t.get("segment") == "OPTIONS" and t.get("side", "").upper() == "SELL":
            price = float(t.get("price", 0.0))
            qty = abs(int(t.get("quantity", 0)))
            options_premium_turnover += price * qty

    total_turnover = total_abs_pnl + options_premium_turnover
    audit_threshold_standard = 100000000.0  # ₹10 Crore for digital transactions (Section 44AB)

    return {
        "trades_analyzed": trade_count,
        "total_abs_pnl": round(total_abs_pnl, 2),
        "options_premium_turnover": round(options_premium_turnover, 2),
        "icai_tax_turnover": round(total_turnover, 2),
        "audit_threshold": audit_threshold_standard,
        "tax_audit_required": total_turnover > audit_threshold_standard,
        "turnover_utilization_pct": round((total_turnover / audit_threshold_standard) * 100.0, 2),
    }


def suggest_tax_loss_harvesting(
    holdings: list[dict], realized_stcg_gain: float = 0.0
) -> list[dict[str, Any]]:
    """
    Identify positions with unrealized short-term losses that can be harvested
    to offset realized STCG gains before March 31.
    """
    harvestable = []
    for h in holdings:
        pnl = float(h.get("pnl", 0.0))
        qty = int(h.get("qty", 0))
        ltp = float(h.get("ltp", 0.0))
        symbol = h.get("symbol", "")
        days_held = int(h.get("days_held", 30))

        if pnl < 0 and qty > 0 and days_held < 365:
            loss_amount = abs(pnl)
            potential_tax_saved = loss_amount * 0.20  # 20% STCG
            harvestable.append(
                {
                    "symbol": symbol,
                    "qty": qty,
                    "current_price": ltp,
                    "unrealized_loss": round(loss_amount, 2),
                    "potential_stcg_tax_saved": round(potential_tax_saved, 2),
                    "holding_days": days_held,
                    "recommendation": f"Sell {qty} shares of {symbol} to harvest ₹{loss_amount:,.2f} loss, saving ~₹{potential_tax_saved:,.2f} in STCG tax.",
                }
            )

    harvestable.sort(key=lambda x: x["unrealized_loss"], reverse=True)
    return harvestable


# ── Rich Display Helpers ─────────────────────────────────────────


def print_transaction_charges(breakdown: TransactionCostBreakdown) -> None:
    """Display statutory charges breakdown as a clean Rich table."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()
    side_style = "green" if breakdown.side == "BUY" else "red"

    header_lines = [
        f"  [bold]Segment / Side[/bold]   : [cyan]{breakdown.segment}[/cyan] | [{side_style}]{breakdown.side}[/{side_style}]",
        f"  [bold]Turnover Value[/bold]   : [bold white]₹{breakdown.notional_turnover:,.2f}[/bold white]",
        f"  [bold]Total Charges[/bold]    : [bold yellow]₹{breakdown.total_charges:,.2f}[/bold yellow] ([dim]{breakdown.effective_pct:.3f}% of turnover[/dim])",
    ]
    console.print()
    console.print(
        Panel(
            "\n".join(header_lines),
            title="[bold cyan]🇮🇳 Statutory Transaction Charges[/bold cyan]",
            border_style="cyan",
        )
    )

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Charge Component", style="bold white")
    table.add_column("Amount (₹)", justify="right")
    table.add_column("Statutory Basis", style="dim")

    table.add_row(
        "Brokerage", f"₹{breakdown.brokerage:,.2f}", "Discount broker max ₹20 / free delivery"
    )
    table.add_row(
        "Securities Transaction Tax (STT)", f"₹{breakdown.stt:,.2f}", "Govt of India STT Schedule"
    )
    table.add_row(
        "Exchange Turnover Charges",
        f"₹{breakdown.exchange_charges:,.2f}",
        "NSE / BSE Transaction Fee",
    )
    table.add_row("GST (18%)", f"₹{breakdown.gst:,.2f}", "18% on (Brokerage + Exchange Fees)")
    table.add_row("Stamp Duty", f"₹{breakdown.stamp_duty:,.2f}", "State Stamp Act (Buy Side)")
    table.add_row("SEBI Turnover Fee", f"₹{breakdown.sebi_charges:,.2f}", "₹10 / Crore")
    table.add_row(
        "[bold]Total Statutory Cost[/bold]",
        f"[bold yellow]₹{breakdown.total_charges:,.2f}[/bold yellow]",
        "[bold]All Inclusive[/bold]",
    )

    console.print(table)
    console.print()


def print_tax_estimate(estimate: CapitalGainsEstimate) -> None:
    """Display capital gains tax estimate as a Rich dashboard."""
    from rich.console import Console
    from rich.panel import Panel

    console = Console()
    pnl_style = "green" if estimate.gross_pnl >= 0 else "red"

    lines = [
        f"  [bold]Gross Trade P&L[/bold]       : [{pnl_style}]₹{estimate.gross_pnl:,.2f}[/{pnl_style}]",
        f"  [bold]Holding Period[/bold]        : {estimate.holding_period_days} days",
        f"  [bold]Tax Classification[/bold]    : [bold cyan]{estimate.tax_type}[/bold cyan] ({estimate.tax_rate_pct:.1f}% rate)",
        f"  [bold]Exemption Applied[/bold]     : ₹{estimate.tax_exemption_applied:,.2f}",
        f"  [bold]Estimated Tax Payable[/bold] : [bold red]₹{estimate.estimated_tax:,.2f}[/bold red] ([dim]Effective {estimate.effective_tax_pct:.1f}%[/dim])",
        f"  [bold]Net Post-Tax Profit[/bold]   : [bold green]₹{estimate.net_post_tax_pnl:,.2f}[/bold green]",
    ]

    console.print()
    console.print(
        Panel(
            "\n".join(lines),
            title="[bold cyan]📊 Indian Income Tax & Capital Gains Estimator[/bold cyan]",
            border_style="cyan",
        )
    )
    console.print(f"[dim]  Rules Applied: {estimate.rules_applied}[/dim]\n")


def print_fo_turnover(turnover_dict: dict[str, Any]) -> None:
    """Display F&O Section 44AB tax audit turnover summary."""
    from rich.console import Console
    from rich.panel import Panel

    console = Console()
    audit_req = turnover_dict.get("tax_audit_required", False)
    status_style = "bold red" if audit_req else "bold green"
    status_text = (
        "MANDATORY (Threshold Exceeded)" if audit_req else "NOT REQUIRED (Safe within limits)"
    )

    lines = [
        f"  [bold]Trades Analyzed[/bold]         : {turnover_dict.get('trades_analyzed', 0)}",
        f"  [bold]Absolute P&L Turnover[/bold]   : ₹{turnover_dict.get('total_abs_pnl', 0.0):,.2f}",
        f"  [bold]Options Premium Turnover[/bold]: ₹{turnover_dict.get('options_premium_turnover', 0.0):,.2f}",
        f"  [bold]Total ICAI Tax Turnover[/bold] : [bold white]₹{turnover_dict.get('icai_tax_turnover', 0.0):,.2f}[/bold white]",
        f"  [bold]Section 44AB Threshold[/bold]  : ₹{turnover_dict.get('audit_threshold', 100000000.0):,.2f} (₹10 Cr for digital)",
        f"  [bold]Turnover Utilization[/bold]   : {turnover_dict.get('turnover_utilization_pct', 0.0):.2f}%",
        f"  [bold]Tax Audit Status[/bold]       : [{status_style}]{status_text}[/{status_style}]",
    ]

    console.print()
    console.print(
        Panel(
            "\n".join(lines),
            title="[bold cyan]💼 F&O Section 43(5) / 44AB Tax Audit Turnover[/bold cyan]",
            border_style="cyan",
        )
    )
    console.print()


def print_tax_harvesting(opportunities: list[dict[str, Any]]) -> None:
    """Display tax-loss harvesting candidates table."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()
    if not opportunities:
        console.print(
            "\n[bold green]✓ No tax-loss harvesting needed.[/bold green] [dim]All holdings are profitable or long-term.[/dim]\n"
        )
        return

    total_saved = sum(o.get("potential_stcg_tax_saved", 0.0) for o in opportunities)
    console.print()
    console.print(
        Panel(
            f"  [bold]Identified Opportunities[/bold]: {len(opportunities)} positions\n"
            f"  [bold]Potential Tax Savings[/bold]   : [bold green]₹{total_saved:,.2f}[/bold green] (STCG 20% offset)",
            title="[bold cyan]🌾 Tax-Loss Harvesting Recommendations[/bold cyan]",
            border_style="cyan",
        )
    )

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Symbol", style="bold white")
    table.add_column("Qty", justify="right")
    table.add_column("LTP", justify="right")
    table.add_column("Unrealized Loss", justify="right", style="red")
    table.add_column("Tax Saved (20%)", justify="right", style="green")
    table.add_column("Days Held", justify="right", style="dim")

    for o in opportunities:
        table.add_row(
            o["symbol"],
            str(o["qty"]),
            f"₹{o['current_price']:,.2f}",
            f"-₹{o['unrealized_loss']:,.2f}",
            f"₹{o['potential_stcg_tax_saved']:,.2f}",
            str(o["holding_days"]),
        )

    console.print(table)
    console.print(
        "\n[dim]Note: Re-buy after T+1 settlement to maintain long-term fundamental positioning while booking tax offset.[/dim]\n"
    )
