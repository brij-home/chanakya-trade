"""
app/commands/eod.py
───────────────────
Institutional Post-Market End-Of-Day (EOD) terminal command for ChanakyaTrade.

Renders an institutional Bloomberg-density terminal report summarizing:
  1. Market Overview & Flow Intelligence
  2. Quantitative Alert Performance & Win Rate
  3. Star Winning Setups & Multi-Baggers
  4. Root Cause Analysis (RCA) on Stopped-Out Positions
  5. Systemic Algorithmic Improvements
  6. Tomorrow's Strategy Blueprint & Reference Levels
"""

from __future__ import annotations

from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

console = Console()


def run(
    target_date: Optional[str] = None,
    dispatch_telegram: bool = False,
    chat_id: Optional[str] = None,
) -> None:
    """Run EOD report command."""
    from engine.eod_report_generator import EODReportGenerator

    console.print()
    console.print(
        Panel(
            f"[bold bright_cyan]🏛️  ChanakyaTrade Institutional EOD Terminal[/bold bright_cyan]  "
            f"[dim]Date: {target_date or 'Today'}[/dim]",
            box=box.ROUNDED,
            border_style="bright_blue",
        )
    )

    with console.status(
        "[bold bright_cyan]Compiling Institutional Post-Market Intelligence...[/bold bright_cyan]"
    ):
        gen = EODReportGenerator()
        rep = gen.generate(target_date=target_date)
        json_p, md_p = gen.save_to_disk(rep)
        tg_status = False
        if dispatch_telegram:
            tg_status = gen.dispatch_to_telegram(rep, chat_id=chat_id)

    # 1. Market Overview & Flows Table
    mkt_table = Table(
        box=box.SIMPLE_HEAVY,
        title="[bold yellow]Market Benchmarks & Institutional Flows[/bold yellow]",
    )
    mkt_table.add_column("Benchmark", style="cyan", justify="left")
    mkt_table.add_column("LTP", style="white", justify="right")
    mkt_table.add_column("Change", justify="right")
    mkt_table.add_column("Regime / Posture", style="bright_magenta", justify="center")

    n_color = "bright_green" if rep.nifty_change_pct >= 0 else "bright_red"
    bn_color = "bright_green" if rep.banknifty_change_pct >= 0 else "bright_red"
    sx_color = "bright_green" if rep.sensex_change_pct >= 0 else "bright_red"

    mkt_table.add_row(
        "NIFTY 50",
        f"₹{rep.nifty_ltp:,.2f}",
        f"[{n_color}]{rep.nifty_change_pct:+.2f}%[/{n_color}]",
        rep.market_posture,
    )
    mkt_table.add_row(
        "BANKNIFTY",
        f"₹{rep.banknifty_ltp:,.2f}",
        f"[{bn_color}]{rep.banknifty_change_pct:+.2f}%[/{bn_color}]",
        f"VIX: {rep.vix_ltp:.2f}",
    )
    mkt_table.add_row(
        "SENSEX",
        f"₹{rep.sensex_ltp:,.2f}",
        f"[{sx_color}]{rep.sensex_change_pct:+.2f}%[/{sx_color}]",
        f"FII: {rep.fii_net_cr:+,.0f} Cr",
    )
    console.print(mkt_table)

    # 2. Performance Scorecard
    score_table = Table(
        box=box.SIMPLE_HEAVY,
        title="[bold bright_green]Quantitative Signal Scorecard[/bold bright_green]",
    )
    score_table.add_column("Total Setups", justify="center")
    score_table.add_column("Ignited", justify="center")
    score_table.add_column("Win Rate", justify="center", style="bold bright_green")
    score_table.add_column("Wins / Losses", justify="center")
    score_table.add_column("Realized R", justify="center", style="bold bright_yellow")
    score_table.add_column("Profit Factor", justify="center")

    score_table.add_row(
        str(rep.total_alerts),
        str(rep.ignited_trades),
        f"{rep.win_rate_pct:.1f}%",
        f"{rep.win_count}W / {rep.loss_count}L",
        f"{rep.total_realized_r:+.2f}R",
        f"{rep.profit_factor:.2f}",
    )
    console.print(score_table)

    # 3. Star Setups
    if rep.star_setups:
        star_table = Table(
            box=box.SIMPLE_HEAVY,
            title="[bold bright_green]🌟 Star Winning Setups[/bold bright_green]",
        )
        star_table.add_column("Symbol", style="bold cyan")
        star_table.add_column("Segment", style="dim")
        star_table.add_column("Dir", justify="center")
        star_table.add_column("Entry", justify="right")
        star_table.add_column("Peak Gain", justify="right", style="bold bright_green")
        star_table.add_column("R:R", justify="right", style="bold bright_yellow")
        star_table.add_column("Milestones", justify="center")

        for s in rep.star_setups[:6]:
            ms = "/".join(s.milestones) if s.milestones else "T1"
            d_style = "bright_green" if s.direction == "BULLISH" else "bright_red"
            star_table.add_row(
                s.symbol,
                s.segment,
                f"[{d_style}]{s.direction}[/{d_style}]",
                f"₹{s.entry_level:,.2f}",
                f"+{s.peak_gain_pct:.1f}%",
                f"{s.realized_r:+.2f}R",
                f"[bright_cyan]{ms}[/bright_cyan]",
            )
        console.print(star_table)

    # 4. RCA Post-Mortem Table
    if rep.rca_breakdown:
        rca_table = Table(
            box=box.SIMPLE_HEAVY,
            title="[bold bright_red]🔬 Root Cause Decomposition & Forensic RCA[/bold bright_red]",
        )
        rca_table.add_column("Failure Vector", style="bold bright_red")
        rca_table.add_column("Count", justify="center")
        rca_table.add_column("Causal Attribution & Diagnosis", style="dim white")
        rca_table.add_column("Implemented Systemic Fix", style="bright_cyan")

        for rca in rep.rca_breakdown:
            rca_table.add_row(
                rca.category.replace("_", " ").title(),
                str(rca.count),
                rca.root_cause,
                rca.corrective_action,
            )
        console.print(rca_table)

    # 5. Strategic Recommendations & Blueprint
    rec_content = [f"[bold bright_yellow]Tomorrow ({rep.tomorrow_day_name}):[/bold bright_yellow]"]
    if rep.tomorrow_expiry_index:
        rec_content.append(
            f"• [bold bright_magenta]Expiry Focus:[/bold bright_magenta] {rep.tomorrow_expiry_index} Weekly Settlement."
        )
    for r in rep.tomorrow_recommendations[:3]:
        rec_content.append(f"• {r}")

    console.print(
        Panel(
            "\n".join(rec_content),
            title="[bold bright_cyan]Tomorrow's Execution Blueprint[/bold bright_cyan]",
            box=box.ROUNDED,
            border_style="bright_blue",
        )
    )

    console.print(f"[dim]Report saved: {md_p}[/dim]")
    if dispatch_telegram:
        console.print(
            f"[bold {'bright_green' if tg_status else 'bright_red'}]Telegram Dispatch: {'SUCCESS' if tg_status else 'FAILED'}[/bold {'bright_green' if tg_status else 'bright_red'}]"
        )
    console.print()
