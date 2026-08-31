"""
scripts/preflight.py
────────────────────
System preflight checker for ChanakyaTrade.

Validates environment configuration, port availability, disk permissions,
and API bindings before starting the application or running live workflows.

Usage:
    python -m scripts.preflight
    # or from app.main:
    trade --preflight
"""

from __future__ import annotations

import sys
from engine.preflight import (  # noqa: F401
    PreflightCheckResult,
    PreflightReport,
    is_port_available,
    mask_secret,
    run_preflight as _engine_run_preflight,
)


def print_preflight_report(report: PreflightReport) -> None:
    """Pretty print preflight report to stdout with color/symbols."""
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table

        console = Console()

        table = Table(title="ChanakyaTrade — System Preflight Readiness", expand=True)
        table.add_column("Check", style="bold white", width=28)
        table.add_column("Status", width=10, justify="center")
        table.add_column("Details", style="dim")

        for c in report.checks:
            if c.status == "PASS":
                status_str = "[bold green]PASS[/bold green]"
            elif c.status == "WARN":
                status_str = "[bold yellow]WARN[/bold yellow]"
            else:
                status_str = "[bold red]FAIL[/bold red]"
            table.add_row(c.name, status_str, c.message)

        console.print(table)

        summary_color = "green" if report.healthy else "red"
        status_text = "READY" if report.healthy else "ACTION REQUIRED"
        console.print(
            Panel(
                f"Mode: [bold cyan]{report.mode}[/bold cyan] | Status: [bold {summary_color}]{status_text}[/bold {summary_color}]",
                title="System Health Summary",
                border_style=summary_color,
            )
        )
    except ImportError:
        print("=== ChanakyaTrade Preflight Readiness ===")
        for c in report.checks:
            print(f"[{c.status}] {c.name}: {c.message}")
        print(
            f"Overall Health: {'HEALTHY' if report.healthy else 'ACTION REQUIRED'} (Mode: {report.mode})"
        )


def run_preflight(verbose: bool = True) -> PreflightReport:
    """Run all preflight checks and optionally format/print output."""
    report = _engine_run_preflight(verbose=verbose)
    if verbose:
        print_preflight_report(report)
    return report


if __name__ == "__main__":
    rep = run_preflight(verbose=True)
    sys.exit(0 if rep.healthy else 1)
