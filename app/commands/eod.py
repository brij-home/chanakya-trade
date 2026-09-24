"""
app/commands/eod.py
───────────────────
Institutional Post-Market End-Of-Day (EOD) terminal command for ChanakyaTrade.

Renders an institutional Bloomberg-density terminal report summarizing:
  1. Market Overview & Flow Intelligence
  2. Quantitative Alert Performance & Win Rate
  3. Institutional Trading Journal (Crux Recap)
  4. Strategy & Detector Efficacy Table
  5. Star Winning Setups & Multi-Baggers
  6. Root Cause Analysis (RCA) on Stopped-Out Positions
  7. Systemic Algorithmic Improvements & Tomorrow's Blueprint
"""

from __future__ import annotations

from typing import Optional
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from config.encoding import fix_windows_console

fix_windows_console()
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
            f"[bold bright_cyan]🏛️  ChanakyaTrade Institutional EOD Terminal & Trading Journal[/bold bright_cyan]  "
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
        f"₹{rep.nifty_ltp:,.2f}" if rep.nifty_ltp > 0 else "UNAVAILABLE",
        f"[{n_color}]{rep.nifty_change_pct:+.2f}%[/{n_color}]" if rep.nifty_ltp > 0 else "—",
        rep.market_posture,
    )
    mkt_table.add_row(
        "BANKNIFTY",
        f"₹{rep.banknifty_ltp:,.2f}" if rep.banknifty_ltp > 0 else "UNAVAILABLE",
        f"[{bn_color}]{rep.banknifty_change_pct:+.2f}%[/{bn_color}]" if rep.banknifty_ltp > 0 else "—",
        f"VIX: {rep.vix_ltp:.2f}" if rep.vix_ltp > 0 else "VIX: —",
    )
    mkt_table.add_row(
        "SENSEX",
        f"₹{rep.sensex_ltp:,.2f}" if rep.sensex_ltp > 0 else "UNAVAILABLE",
        f"[{sx_color}]{rep.sensex_change_pct:+.2f}%[/{sx_color}]" if rep.sensex_ltp > 0 else "—",
        f"FII: {rep.fii_net_cr:+,.0f} Cr | DII: {rep.dii_net_cr:+,.0f} Cr",
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
    score_table.add_column("Scratches / Cutoffs", justify="center")
    score_table.add_column("Realized Payoff", justify="center", style="bold bright_yellow")
    score_table.add_column("Profit Factor", justify="center")

    score_table.add_row(
        str(rep.total_alerts),
        f"{rep.ignited_trades} (Untriggered: {rep.untriggered_count})",
        f"{rep.win_rate_pct:.1f}%",
        f"{rep.win_count}W / {rep.loss_count}L",
        str(rep.scratch_count + rep.eod_squareoff_count),
        f"{rep.total_realized_r:+.2f}R",
        f"{rep.profit_factor:.2f}",
    )
    console.print(score_table)

    # 3. Institutional Trading Journal Table
    if rep.journal_entries:
        journal_table = Table(
            box=box.SIMPLE_HEAVY,
            title="[bold bright_cyan]📓 Institutional Trading Journal (Crux Recap)[/bold bright_cyan]",
        )
        journal_table.add_column("Time", style="dim", justify="center")
        journal_table.add_column("Symbol", style="bold white")
        journal_table.add_column("Segment", style="dim")
        journal_table.add_column("Strategy", style="cyan")
        journal_table.add_column("Dir", justify="center")
        journal_table.add_column("Entry", justify="right")
        journal_table.add_column("Exit / LTP", justify="right")
        journal_table.add_column("P&L %", justify="right")
        journal_table.add_column("Realized R", justify="right")
        journal_table.add_column("Outcome Status", justify="center")
        journal_table.add_column("Diagnosis & Note", style="dim white")

        for j in rep.journal_entries[:15]:
            d_style = "bright_green" if j.direction.upper() == "BULLISH" else "bright_red"
            r_style = (
                "bold bright_green"
                if j.realized_r > 0
                else ("bold bright_red" if j.realized_r < 0 else "dim")
            )
            pnl_style = (
                "bright_green"
                if j.pnl_pct > 0
                else ("bright_red" if j.pnl_pct < 0 else "dim")
            )

            status_color = {
                "WIN_TARGET": "bold bright_green",
                "WIN_SCALE": "bright_green",
                "LOSS_STOPPED": "bold bright_red",
                "SESSION_EOD_SQUAREOFF": "yellow",
                "VELOCITY_TIME_STOP": "bright_yellow",
                "UNTRIGGERED_EXPIRED": "dim",
                "IN_FLIGHT": "bright_blue",
            }.get(j.outcome, "white")

            status_text = {
                "WIN_TARGET": "TARGET HIT",
                "WIN_SCALE": "SCALED / BE",
                "LOSS_STOPPED": "STOP LOSS",
                "SESSION_EOD_SQUAREOFF": "EOD CUTOFF",
                "VELOCITY_TIME_STOP": "TIME STOP",
                "UNTRIGGERED_EXPIRED": "UNTRIGGERED",
                "IN_FLIGHT": "IN FLIGHT",
            }.get(j.outcome, j.outcome)

            journal_table.add_row(
                j.time_str or "—",
                j.symbol,
                j.segment,
                j.strategy or "SCANNER",
                f"[{d_style}]{j.direction[:4]}[/{d_style}]",
                f"₹{j.entry_level:,.2f}",
                f"₹{j.exit_level:,.2f}",
                f"[{pnl_style}]{j.pnl_pct:+.1f}%[/{pnl_style}]",
                f"[{r_style}]{j.realized_r:+.2f}R[/{r_style}]",
                f"[{status_color}]{status_text}[/{status_color}]",
                j.verdict_note[:50] + ("..." if len(j.verdict_note) > 50 else ""),
            )
        console.print(journal_table)

    # 4. Strategy & Detector Efficacy Table
    if rep.detector_efficacy:
        eff_table = Table(
            box=box.SIMPLE_HEAVY,
            title="[bold bright_magenta]🎯 Strategy & Detector Performance Efficacy[/bold bright_magenta]",
        )
        eff_table.add_column("Detector / Strategy", style="bold cyan")
        eff_table.add_column("Signals", justify="center")
        eff_table.add_column("Ignited", justify="center")
        eff_table.add_column("Wins", justify="center", style="bright_green")
        eff_table.add_column("Losses", justify="center", style="bright_red")
        eff_table.add_column("Scratches", justify="center", style="yellow")
        eff_table.add_column("Win Rate", justify="right", style="bold white")
        eff_table.add_column("Net R", justify="right")
        eff_table.add_column("Action Verdict", style="dim")

        for d in rep.detector_efficacy:
            net_r_style = (
                "bold bright_green"
                if d.get("net_r", 0) > 0
                else ("bold bright_red" if d.get("net_r", 0) < 0 else "dim")
            )
            clean_verdict = d.get("verdict", "").replace("**", "")
            eff_table.add_row(
                d["detector"],
                str(d["count"]),
                str(d["ignited"]),
                str(d["wins"]),
                str(d["losses"]),
                str(d.get("scratches", 0)),
                f"{d['win_rate']:.1f}%",
                f"[{net_r_style}]{d.get('net_r', 0.0):+.2f}R[/{net_r_style}]",
                clean_verdict,
            )
        console.print(eff_table)

    # 5. Star Setups
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
        star_table.add_column("Realized R", justify="right", style="bold bright_yellow")
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

    # 6. RCA Post-Mortem Table
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

    # 7. Strategic Recommendations & Blueprint
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
