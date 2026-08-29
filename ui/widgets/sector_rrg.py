"""
ui/widgets/sector_rrg.py
─────────────────────────
Textual widget displaying live Relative Rotation Graphs (RRG) sector momentum.
"""

from __future__ import annotations

from rich.table import Table
from textual.app import ComposeResult
from textual.widgets import Label, Static

QUADRANT_COLORS = {
    "LEADING": "bold green",
    "WEAKENING": "bold yellow",
    "LAGGING": "bold red",
    "IMPROVING": "bold cyan",
}


class SectorRRGWidget(Static):
    """
    RRG Sector Rotation panel showing relative strength and velocity of major NSE sectors.
    """

    DEFAULT_CSS = """
    SectorRRGWidget {
        height: auto;
        border: round $primary;
        padding: 0 1;
    }
    SectorRRGWidget Label {
        color: $primary;
        text-style: bold;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("Sector RRG Matrix")
        yield Static(id="rrg-table", markup=True)

    def on_mount(self) -> None:
        self.refresh_data()
        self.set_interval(60, self.refresh_data)

    def refresh_data(self) -> None:
        try:
            from analysis.sector_rotation import get_sector_rrg_matrix

            points = get_sector_rrg_matrix(use_cache=True)

            table = Table(
                show_header=True,
                header_style="bold dim",
                box=None,
                padding=(0, 1),
                expand=True,
            )
            table.add_column("Sector", style="bold", ratio=2)
            table.add_column("Ratio", justify="right")
            table.add_column("Mom", justify="right")
            table.add_column("Quadrant", justify="right")

            for p in points[:8]:
                q_style = QUADRANT_COLORS.get(p.quadrant, "white")
                table.add_row(
                    p.sector,
                    f"{p.rs_ratio:.1f}",
                    f"{p.rs_momentum:.1f}",
                    f"[{q_style}]{p.quadrant[:4]}[/{q_style}]",
                )

            self.query_one("#rrg-table", Static).update(table)
        except Exception:
            self.query_one("#rrg-table", Static).update("[dim]Loading sector RRG...[/dim]")
