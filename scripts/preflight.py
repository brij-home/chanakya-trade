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

import os
import socket
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal


@dataclass
class PreflightCheckResult:
    name: str
    status: Literal["PASS", "WARN", "FAIL"]
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PreflightReport:
    healthy: bool
    mode: str
    checks: List[PreflightCheckResult]
    masked_env: Dict[str, str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "healthy": self.healthy,
            "mode": self.mode,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status,
                    "message": c.message,
                    "details": c.details,
                }
                for c in self.checks
            ],
            "masked_env": self.masked_env,
        }


def mask_secret(value: str | None) -> str:
    """Mask a secret value preserving only the last 4 characters if length > 6."""
    if not value:
        return "<unset>"
    val = str(value).strip()
    if len(val) <= 6:
        return "***"
    return f"{'*' * (len(val) - 4)}{val[-4:]}"


def is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a TCP port is free on the host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def run_preflight(verbose: bool = True) -> PreflightReport:
    """Run all system preflight checks and return a structured report."""
    checks: List[PreflightCheckResult] = []
    healthy = True

    # 1. Python Version Check
    py_version = sys.version_info
    py_ver_str = f"{py_version.major}.{py_version.minor}.{py_version.micro}"
    if py_version >= (3, 11):
        checks.append(
            PreflightCheckResult(
                name="Python Runtime",
                status="PASS",
                message=f"Python {py_ver_str} (>= 3.11 required)",
                details={"version": py_ver_str},
            )
        )
    else:
        healthy = False
        checks.append(
            PreflightCheckResult(
                name="Python Runtime",
                status="FAIL",
                message=f"Python {py_ver_str} is unsupported. Python >= 3.11 is required.",
                details={"version": py_ver_str},
            )
        )

    # 2. Ports Check (API: 8765, Vite: 5173)
    api_port_free = is_port_available(8765)
    vite_port_free = is_port_available(5173)

    if api_port_free:
        checks.append(
            PreflightCheckResult(
                name="API Sidecar Port (8765)",
                status="PASS",
                message="Port 8765 is available on 127.0.0.1",
            )
        )
    else:
        # Port might be in use by an already running instance of our server
        checks.append(
            PreflightCheckResult(
                name="API Sidecar Port (8765)",
                status="WARN",
                message="Port 8765 is currently occupied (existing instance or another service).",
                details={"port": 8765},
            )
        )

    if vite_port_free:
        checks.append(
            PreflightCheckResult(
                name="Vite Frontend Port (5173)",
                status="PASS",
                message="Port 5173 is available on 127.0.0.1",
            )
        )
    else:
        checks.append(
            PreflightCheckResult(
                name="Vite Frontend Port (5173)",
                status="WARN",
                message="Port 5173 is in use. Vite may choose 5174 or connect to existing frontend.",
                details={"port": 5173},
            )
        )

    # 3. Disk Write & App Data Directory Permissions
    try:
        from config.paths import app_data_dir, app_data_path

        app_dir = app_data_dir()
        app_dir.mkdir(parents=True, exist_ok=True)
        test_file = app_data_path(".preflight_write_test")
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)

        checks.append(
            PreflightCheckResult(
                name="App Data Storage",
                status="PASS",
                message=f"App data directory writable: {app_dir}",
                details={"path": str(app_dir)},
            )
        )
    except Exception as e:
        healthy = False
        checks.append(
            PreflightCheckResult(
                name="App Data Storage",
                status="FAIL",
                message=f"Cannot write to app data directory: {e}",
            )
        )

    # 4. Auth & Cache Database Initialization
    try:
        from web.auth import init_db as init_auth_db, _db_path

        init_auth_db()
        db_path = _db_path()
        checks.append(
            PreflightCheckResult(
                name="SQLite Storage",
                status="PASS",
                message=f"Auth & persistence SQLite database initialized at {db_path}",
                details={"db_path": str(db_path)},
            )
        )
    except Exception as e:
        healthy = False
        checks.append(
            PreflightCheckResult(
                name="SQLite Storage",
                status="FAIL",
                message=f"SQLite database initialization error: {e}",
            )
        )

    # 5. Trading Mode & Safety Guardrails
    raw_mode = os.environ.get("TRADING_MODE", "PAPER").upper()
    trading_mode = "EXECUTE" if raw_mode == "LIVE" else "SIMULATE"

    if trading_mode == "SIMULATE":
        checks.append(
            PreflightCheckResult(
                name="Trading Mode Safety",
                status="PASS",
                message="Safe Default: SIMULATE (Paper Mode). No real broker orders will be placed.",
                details={"mode": "SIMULATE", "raw": raw_mode},
            )
        )
    else:
        checks.append(
            PreflightCheckResult(
                name="Trading Mode Safety",
                status="WARN",
                message="EXECUTE (Live Mode) is enabled in configuration. Extreme caution required.",
                details={"mode": "EXECUTE", "raw": raw_mode},
            )
        )

    # 6. AI Providers & Model Configuration
    ai_provider = os.environ.get("AI_PROVIDER", "gemini")
    fast_provider = os.environ.get("AI_FAST_PROVIDER", ai_provider)
    deep_provider = os.environ.get("AI_DEEP_PROVIDER", ai_provider)

    checks.append(
        PreflightCheckResult(
            name="AI Routing Configuration",
            status="PASS",
            message=f"Primary: {ai_provider} | Fast: {fast_provider} | Deep: {deep_provider}",
            details={
                "primary": ai_provider,
                "fast": fast_provider,
                "deep": deep_provider,
            },
        )
    )

    # Masked Environment Summary
    keys_to_inspect = [
        "TRADING_MODE",
        "AI_PROVIDER",
        "AI_MODEL",
        "AI_FAST_PROVIDER",
        "AI_DEEP_PROVIDER",
        "GEMINI_API_KEY",
        "NVIDIA_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GROQ_API_KEY",
        "FYERS_APP_ID",
        "FYERS_SECRET_KEY",
        "KITE_API_KEY",
        "KITE_API_SECRET",
        "ANGEL_API_KEY",
        "UPSTOX_API_KEY",
    ]

    masked_env = {}
    for k in keys_to_inspect:
        val = os.environ.get(k)
        if "KEY" in k or "SECRET" in k or "PASSWORD" in k or "TOKEN" in k:
            masked_env[k] = mask_secret(val)
        else:
            masked_env[k] = val or "<unset>"

    report = PreflightReport(
        healthy=healthy,
        mode=trading_mode,
        checks=checks,
        masked_env=masked_env,
    )

    if verbose:
        print_preflight_report(report)

    return report


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


if __name__ == "__main__":
    rep = run_preflight(verbose=True)
    sys.exit(0 if rep.healthy else 1)
