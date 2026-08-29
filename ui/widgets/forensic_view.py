"""
ui/widgets/forensic_view.py
────────────────────────────
Textual widget displaying corporate governance and forensic accounting audit.
"""

from __future__ import annotations

from rich.table import Table
from textual.app import ComposeResult
from textual.widgets import Label, Static


class ForensicWidget(Static):
    """
    Forensic audit widget showing Beneish M-Score, Altman Z''-Score, and Piotroski F-Score.
    """

    DEFAULT_CSS = """
    ForensicWidget {
        height: auto;
        border: round $primary;
        padding: 0 1;
    }
    ForensicWidget Label {
        color: $primary;
        text-style: bold;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("Forensic Quality")
        yield Static(id="forensic-body", markup=True)

    def on_mount(self) -> None:
        self.refresh_data("NIFTY")

    def refresh_data(self, symbol: str = "RELIANCE") -> None:
        try:
            from analysis.forensic import audit_forensics

            res = audit_forensics(symbol, use_cache=True)

            table = Table(
                show_header=False,
                box=None,
                padding=(0, 1),
                expand=True,
            )
            table.add_column("Metric", style="bold dim")
            table.add_column("Value", justify="right")

            rating_color = "green" if res.quality_rating in ("A+", "A") else "yellow" if res.quality_rating == "B" else "red"
            z_color = "green" if res.distress_zone == "SAFE" else "yellow" if res.distress_zone == "GREY" else "red"

            table.add_row("Symbol", f"[bold]{res.symbol}[/bold]")
            table.add_row("Quality Grade", f"[{rating_color}]{res.quality_rating}[/{rating_color}]")
            table.add_row("Beneish M-Score", f"{res.beneish_m_score:.2f} ({'FLAGGED' if res.is_beneish_flagged else 'CLEAN'})")
            table.add_row("Altman Z''-Score", f"[{z_color}]{res.altman_z_score:.2f} ({res.distress_zone})[/{z_color}]")
            table.add_row("Piotroski Score", f"{res.piotroski_f_score}/9")

            self.query_one("#forensic-body", Static).update(table)
        except Exception:
            self.query_one("#forensic-body", Static).update("[dim]Forensic audit ready.[/dim]")
