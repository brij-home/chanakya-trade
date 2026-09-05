"""
engine/preflight.py
───────────────────
Institutional System Preflight Checker & Diagnostic Engine for ChanakyaTrade.

Validates environment configuration, port availability, disk permissions,
storage databases, trading mode safety guardrails, and AI provider bindings.
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

    # 5. Host Memory & Headroom Check (8 GB Profile Sizing)
    try:
        from engine.memory_guard import get_memory_status

        mem = get_memory_status()
        if mem.pressure_level == "CRITICAL":
            checks.append(
                PreflightCheckResult(
                    name="RAM & Memory Headroom",
                    status="WARN",
                    message=f"Low available RAM ({mem.available_ram_mb:.0f} MB free). Recommendation: {mem.recommendation}",
                    details=mem.to_dict(),
                )
            )
        else:
            checks.append(
                PreflightCheckResult(
                    name="RAM & Memory Headroom",
                    status="PASS",
                    message=f"RAM OK: {mem.available_ram_mb:.0f} MB available | RSS: {mem.process_rss_mb:.0f} MB",
                    details=mem.to_dict(),
                )
            )
    except Exception as e:
        checks.append(
            PreflightCheckResult(
                name="RAM & Memory Headroom",
                status="WARN",
                message=f"Unable to read memory headroom: {e}",
            )
        )

    # 6. SSD Dedicated Storage & Free Space Check (100 GB SSD Profile)
    try:
        from engine.maintenance import get_storage_breakdown

        sb = get_storage_breakdown()
        if sb.free_ssd_gb < 5.0:
            checks.append(
                PreflightCheckResult(
                    name="SSD Storage Space",
                    status="WARN",
                    message=f"Low SSD free space ({sb.free_ssd_gb:.1f} GB free). Purge recommended.",
                    details=sb.to_dict(),
                )
            )
        else:
            checks.append(
                PreflightCheckResult(
                    name="SSD Storage Space",
                    status="PASS",
                    message=f"SSD Storage Healthy: {sb.free_ssd_gb:.1f} GB free | App Data: {sb.total_app_data_mb:.1f} MB",
                    details=sb.to_dict(),
                )
            )
    except Exception as e:
        checks.append(
            PreflightCheckResult(
                name="SSD Storage Space",
                status="WARN",
                message=f"Unable to evaluate SSD free space: {e}",
            )
        )

    # 7. Database Integrity Checks (PRAGMA quick_check)
    try:
        import sqlite3
        from config.paths import app_data_path

        dbs_to_check = [
            "users.db",
            "orders.db",
            "audit.db",
            "market_data.db",
            "analysis_cache.db",
            "analysis_search.db",
        ]
        corrupt_dbs = []
        for db_name in dbs_to_check:
            db_p = app_data_path(db_name)
            if db_p.exists():
                conn = None
                try:
                    conn = sqlite3.connect(str(db_p), timeout=5.0)
                    row = conn.execute("PRAGMA quick_check").fetchone()
                    if not row or row[0] != "ok":
                        corrupt_dbs.append(f"{db_name}: {row[0] if row else 'empty'}")
                except Exception as err:
                    corrupt_dbs.append(f"{db_name}: {err}")
                finally:
                    if conn is not None:
                        try:
                            conn.close()
                        except Exception:
                            pass

        if corrupt_dbs:
            checks.append(
                PreflightCheckResult(
                    name="Database Integrity",
                    status="WARN",
                    message=f"Integrity warnings in: {', '.join(corrupt_dbs)}",
                    details={"issues": corrupt_dbs},
                )
            )
        else:
            checks.append(
                PreflightCheckResult(
                    name="Database Integrity",
                    status="PASS",
                    message="All SQLite database files passed PRAGMA quick_check.",
                    details={"verified_dbs": dbs_to_check},
                )
            )
    except Exception as e:
        checks.append(
            PreflightCheckResult(
                name="Database Integrity",
                status="WARN",
                message=f"Database integrity check skipped: {e}",
            )
        )

    # 8. Active Configured Broker Discovery (Ignore unconfigured brokers)
    try:
        from config.paths import app_data_path

        active_configured = []

        # Helper to check if a token file contains real (non-dummy) credentials
        def _has_valid_token(filename: str) -> bool:
            p = app_data_path(filename)
            if not p.exists():
                return False
            try:
                import json
                data = json.loads(p.read_text(encoding="utf-8"))
                tok = str(data.get("token", "")).strip()
                return bool(tok and tok != "dummy_token" and not tok.startswith("dummy"))
            except Exception:
                return False

        # m.Stock (Current active primary)
        if _has_valid_token("mstock.json") or (os.environ.get("MSTOCK_API_KEY") and os.environ.get("MSTOCK_CLIENT_CODE")):
            active_configured.append("mstock (Mirae Asset)")
        # Fyers (Planned primary data feed)
        if _has_valid_token("fyers.json") or os.environ.get("FYERS_APP_ID"):
            active_configured.append("fyers (Data API)")
        # Stoxkart (Planned standby/failover)
        if _has_valid_token("stoxkart.json") or os.environ.get("STOXKART_API_KEY"):
            active_configured.append("stoxkart (SMC Global)")
        # Flattrade (Planned ₹0 brokerage failover)
        if _has_valid_token("flattrade.json") or os.environ.get("FLATTRADE_API_KEY"):
            active_configured.append("flattrade (WallConnect)")

        # Any other broker only if explicitly configured
        for b_name, env_key in [
            ("zerodha", "KITE_API_KEY"),
            ("groww", "GROWW_API_KEY"),
            ("angelone", "ANGEL_API_KEY"),
            ("upstox", "UPSTOX_API_KEY"),
            ("shoonya", "SHOONYA_USER_ID"),
        ]:
            if _has_valid_token(f"{b_name}.json") or os.environ.get(env_key):
                active_configured.append(b_name)

        if active_configured:
            msg = f"Active configured: {', '.join(active_configured)} | Fallback: Mock Broker (Paper Mode)"
        else:
            msg = "No live brokers configured. Safe default: Mock Broker (Paper/Demo Mode Active)."

        checks.append(
            PreflightCheckResult(
                name="Configured Broker Integrations",
                status="PASS",
                message=msg,
                details={"active_brokers": active_configured, "paper_fallback": "mock"},
            )
        )
    except Exception as e:
        checks.append(
            PreflightCheckResult(
                name="Configured Broker Integrations",
                status="WARN",
                message=f"Broker discovery warning: {e}",
            )
        )

    # 9. Trading Mode & Safety Guardrails
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

    # 10. AI Providers & Model Configuration
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
        "GROWW_API_KEY",
        "UPSTOX_API_KEY",
        "ALLOW_LIVE_TRADING",
    ]

    masked_env = {k: mask_secret(os.environ.get(k)) for k in keys_to_inspect}

    report = PreflightReport(
        healthy=healthy,
        mode=trading_mode,
        checks=checks,
        masked_env=masked_env,
    )

    return report
