"""
scripts/cleanup.py
──────────────────
Universal Process & Resource Cleanup Utility for ChanakyaTrade.

Safely discovers and terminates:
  1. Orphaned pytest / pytest-xdist worker processes
  2. Dangling uvicorn sidecar server processes on port 8765
  3. Stale temporary test databases and socket locks
"""

from __future__ import annotations

import os
import sys
import subprocess
import socket
from pathlib import Path

# UTF-8 stdout configuration for Windows terminals
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def is_port_in_use(port: int = 8765) -> bool:
    """Check if a local TCP port is currently bound."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", port)) == 0


def cleanup_orphaned_processes() -> int:
    """Find and kill orphaned pytest/uvicorn workers belonging to chanakya-trade."""
    killed_count = 0
    current_pid = os.getpid()
    parent_pid = os.getppid() if hasattr(os, "getppid") else -1

    try:
        import psutil

        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                p_pid = proc.info["pid"]
                if p_pid in (current_pid, parent_pid, 0, 4):
                    continue

                cmdline = proc.info.get("cmdline") or []
                cmd_str = " ".join(cmdline).lower()
                p_name = (proc.info.get("name") or "").lower()

                # Identify orphaned pytest-xdist workers or uvicorn processes
                is_xdist_worker = "exec(eval(sys.stdin.readline()))" in cmd_str
                is_stale_uvicorn = "uvicorn" in cmd_str and "web.api:app" in cmd_str
                is_stale_pytest = (
                    "pytest" in cmd_str or "pytest.exe" in p_name
                ) and "validate_all" not in cmd_str

                if is_xdist_worker or is_stale_uvicorn or is_stale_pytest:
                    proc.kill()
                    killed_count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
    except ImportError:
        # Fallback using PowerShell CIM on Windows
        if sys.platform == "win32":
            cmd = (
                'powershell -NoProfile -Command "'
                "Get-CimInstance Win32_Process | "
                "Where-Object { ($_.Name -like '*python*' -or $_.Name -like '*uvicorn*') -and "
                "($_.CommandLine -like '*exec(eval*' -or ($_.CommandLine -like '*uvicorn*' -and $_.CommandLine -like '*web.api*')) -and "
                f"$_.ProcessId -ne {current_pid} }} | "
                'ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Output $_.ProcessId }"'
            )
            try:
                out = subprocess.check_output(cmd, shell=True, text=True)
                pids = [int(line.strip()) for line in out.splitlines() if line.strip().isdigit()]
                killed_count = len(pids)
            except Exception:
                pass
    return killed_count


def release_port(port: int = 8765) -> bool:
    """Release TCP port 8765 if bound."""
    if not is_port_in_use(port):
        return False

    released = False
    if sys.platform == "win32":
        cmd = (
            f'powershell -NoProfile -Command "'
            f"Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | "
            f"Select-Object -ExpandProperty OwningProcess -Unique | "
            f'ForEach-Object {{ Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue; Write-Output $_ }}"'
        )
        try:
            out = subprocess.check_output(cmd, shell=True, text=True)
            if out.strip():
                released = True
        except Exception:
            pass
    return released


def cleanup_stale_cache_files() -> int:
    """Remove temporary pytest lock files and databases."""
    cleaned = 0
    repo_root = Path(__file__).resolve().parent.parent

    stale_patterns = [
        ".pytest_trading_platform*",
        "test_*.db",
        "*.db-journal",
        "*.db-wal",
    ]

    for pat in stale_patterns:
        for p in repo_root.glob(pat):
            try:
                if p.is_file():
                    p.unlink(missing_ok=True)
                    cleaned += 1
                elif p.is_dir():
                    import shutil

                    shutil.rmtree(p, ignore_errors=True)
                    cleaned += 1
            except Exception:
                pass
    return cleaned


def main():
    print("=" * 60)
    print("  ChanakyaTrade Universal Environment Cleanup")
    print("=" * 60)

    n_procs = cleanup_orphaned_processes()
    if n_procs > 0:
        print(f" [+] Terminated {n_procs} orphaned background worker process(es).")
    else:
        print(" [v] No orphaned worker processes found.")

    if release_port(8765):
        print(" [+] Released stuck port 8765 listener.")
    else:
        print(" [v] Port 8765 is clear.")

    n_files = cleanup_stale_cache_files()
    if n_files > 0:
        print(f" [+] Removed {n_files} stale test database/lock file(s).")
    else:
        print(" [v] Temp lock files clean.")

    print("=" * 60)
    print(" Environment is clean and ready for execution.")
    print("=" * 60)
    sys.exit(0)


if __name__ == "__main__":
    main()
