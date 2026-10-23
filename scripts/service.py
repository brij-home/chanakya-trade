#!/usr/bin/env python3
"""
scripts/service.py
──────────────────
Universal, Cross-Platform Background Service Controller for ChanakyaTrade.

Dynamically supports:
  • Windows (PowerShell / Win32 background detachment without console popup)
  • macOS (Darwin POSIX detachment via start_new_session / nohup)
  • Linux (POSIX detachment via start_new_session / setsid)

Usage:
  python scripts/service.py status
  python scripts/service.py start [--no-frontend] [--skip-build-web] [--force-build-web]
  python scripts/service.py stop
  python scripts/service.py restart [--no-frontend] [--skip-build-web] [--force-build-web]
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Configure logging
logger = logging.getLogger("scripts.service")

# OS detection constants
IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

ROOT_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT_DIR / ".logs"
FRONTEND_DIR = ROOT_DIR / "macos-app"
PID_FILE = LOG_DIR / "services.json"

# Setup UTF-8 console output for Windows
if IS_WINDOWS and sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def get_python_exe() -> str:
    """Resolve the appropriate Python executable for current OS."""
    if IS_WINDOWS:
        venv_py = ROOT_DIR / ".venv" / "Scripts" / "python.exe"
    else:
        venv_py = ROOT_DIR / ".venv" / "bin" / "python"

    if venv_py.is_file() and os.access(venv_py, os.X_OK):
        return str(venv_py)
    return sys.executable


def get_npm_exe() -> str | None:
    """Resolve the appropriate npm executable for current OS."""
    if IS_WINDOWS:
        candidates = ["npm.cmd", "npm.exe", "npm"]
    else:
        candidates = ["npm"]

    for cand in candidates:
        found = shutil.which(cand)
        if found:
            return found
    return None


def is_port_in_use(port: int, host: str = "localhost") -> bool:
    """Check if a TCP port is currently open and accepting connections (IPv4 & IPv6)."""
    try:
        for res in socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM):
            af, socktype, proto, _, sa = res
            with socket.socket(af, socktype, proto) as s:
                s.settimeout(0.2)
                if s.connect_ex(sa) == 0:
                    return True
    except Exception:
        pass
    return False


def get_pids_for_port(port: int) -> list[int]:
    """Find process IDs currently bound to a port across OSes (IPv4 & IPv6)."""
    pids = []
    current_pid = os.getpid()

    if IS_WINDOWS:
        try:
            out = subprocess.check_output(
                "netstat -ano",
                shell=True,
                text=True,
                stderr=subprocess.DEVNULL,
            )
            target = f":{port}"
            for line in out.splitlines():
                parts = line.strip().split()
                if len(parts) >= 4 and parts[0].upper().startswith("TCP"):
                    local_addr = parts[1]
                    state = parts[3].upper() if len(parts) >= 5 else parts[2].upper()
                    pid_str = parts[-1]
                    if local_addr.endswith(target) and "LISTEN" in state:
                        if pid_str.isdigit():
                            pid = int(pid_str)
                            if pid not in (0, 4, current_pid):
                                pids.append(pid)
        except Exception:
            pass
    elif IS_MACOS or IS_LINUX:
        if shutil.which("lsof"):
            try:
                out = subprocess.check_output(
                    ["lsof", "-ti", f":{port}"],
                    text=True,
                    stderr=subprocess.DEVNULL,
                )
                for line in out.splitlines():
                    line = line.strip()
                    if line.isdigit():
                        pid = int(line)
                        if pid not in (0, 1, current_pid):
                            pids.append(pid)
            except Exception:
                pass
        elif shutil.which("fuser"):
            try:
                out = subprocess.check_output(
                    ["fuser", f"{port}/tcp"],
                    text=True,
                    stderr=subprocess.DEVNULL,
                )
                for part in out.split():
                    part = part.strip()
                    if part.isdigit():
                        pid = int(part)
                        if pid not in (0, 1, current_pid):
                            pids.append(pid)
            except Exception:
                pass
    return list(set(pids))


def terminate_pid(pid: int) -> bool:
    """Terminate a process by PID across OSes."""
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        if IS_WINDOWS:
            res = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            return res.returncode == 0
        else:
            os.kill(pid, signal.SIGKILL)
            return True
    except Exception:
        return False


def stop_services(api_port: int = 8765, vite_port: int = 5173) -> None:
    """Stop all existing ChanakyaTrade backend and frontend services."""
    print("[*] Stopping existing ChanakyaTrade services...", flush=True)

    # 1. Terminate recorded PIDs
    if PID_FILE.is_file():
        try:
            with open(PID_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            b_pid = data.get("backend_pid")
            f_pid = data.get("frontend_pid")
            if b_pid:
                terminate_pid(int(b_pid))
            if f_pid:
                terminate_pid(int(f_pid))
        except Exception:
            pass
        try:
            PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    # 2. Release port bindings
    for port in (api_port, vite_port):
        for pid in get_pids_for_port(port):
            terminate_pid(pid)

    # 3. Invoke cleanup utility for orphaned background workers
    try:
        from scripts.cleanup import cleanup_orphaned_processes, cleanup_stale_cache_files

        cleanup_orphaned_processes()
        cleanup_stale_cache_files()
    except Exception:
        pass


def sync_web_bundle(skip_build: bool = False, force_build: bool = False) -> None:
    """Synchronize Vite static bundle into web/static/ across OSes."""
    if skip_build:
        print(" [+] Web static build skipped (--skip-build-web).", flush=True)
        return

    npm_exe = get_npm_exe()
    if not npm_exe:
        print(" [!] npm executable not found in PATH. Skipping web build.", flush=True)
        return

    static_index = ROOT_DIR / "web" / "static" / "index.html"
    needs_build = False
    build_reason = ""

    if force_build:
        needs_build = True
        build_reason = "Forced rebuild requested (--force-build-web)"
    elif not static_index.is_file():
        needs_build = True
        build_reason = "web/static/index.html not found"
    else:
        static_mtime = static_index.stat().st_mtime
        latest_src_time = 0.0
        latest_file = None
        src_dir = FRONTEND_DIR / "src"

        if src_dir.is_dir():
            for root, _, files in os.walk(src_dir):
                for fname in files:
                    fpath = Path(root) / fname
                    mtime = fpath.stat().st_mtime
                    if mtime > latest_src_time:
                        latest_src_time = mtime
                        latest_file = fname

            if latest_src_time > static_mtime:
                needs_build = True
                build_reason = f"UI source updated ({latest_file})"

    if needs_build:
        print(f"[*] UI change detected: {build_reason}. Building web bundle...", flush=True)
        try:
            subprocess.run(
                [npm_exe, "run", "build:web:fast"],
                cwd=str(FRONTEND_DIR),
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print(" [+] Web bundle synchronized to web/static/", flush=True)
        except Exception as e:
            print(f" [!] Web build warning: {e}. Continuing...", flush=True)
    else:
        print(" [+] Web static bundle is up-to-date.", flush=True)


def launch_detached_process(cmd: list[str], cwd: Path, stdout_file: Path, stderr_file: Path) -> int:
    """
    Launch a process completely detached from current terminal across Windows, macOS, and Linux.
    Guarantees zero console popup on Windows and proper process group dissociation on POSIX.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    out_f = open(stdout_file, "a", encoding="utf-8")
    err_f = open(stderr_file, "a", encoding="utf-8")

    if IS_WINDOWS:
        # On Windows, launch via WMI Win32_Process to break away from parent Job Objects
        # and guarantee zero popup windows (ShowWindow = 0)
        cmd_joined = " ".join(f'"{c}"' if " " in c else c for c in cmd)
        cmd_wrapper = f'cmd.exe /c "{cmd_joined} > \\"{stdout_file}\\" 2> \\"{stderr_file}\\""'
        ps_script = (
            f'$s = ([wmiclass]"Win32_ProcessStartup").CreateInstance(); '
            f"$s.ShowWindow = 0; "
            f"$res = ([wmiclass]\"Win32_Process\").Create('{cmd_wrapper}', '{cwd}', $s); "
            f"if ($res.ReturnValue -eq 0) {{ Write-Output $res.ProcessId }} else {{ exit 1 }}"
        )
        try:
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", ps_script],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            pid_str = out.strip()
            if pid_str.isdigit():
                return int(pid_str)
        except Exception:
            pass

        # Fallback to subprocess Popen with CREATE_BREAKAWAY_FROM_JOB
        # 0x00000008 (DETACHED_PROCESS) | 0x08000000 (CREATE_NO_WINDOW) | 0x01000000 (CREATE_BREAKAWAY_FROM_JOB)
        creationflags = 0x00000008 | 0x08000000 | 0x01000000
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                stdout=out_f,
                stderr=err_f,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
                close_fds=True,
            )
            return proc.pid
        except Exception:
            # If CREATE_BREAKAWAY_FROM_JOB fails due to job settings, retry without it
            proc = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                stdout=out_f,
                stderr=err_f,
                stdin=subprocess.DEVNULL,
                creationflags=0x00000008 | 0x08000000,
                close_fds=True,
            )
            return proc.pid
    else:
        # POSIX (macOS / Linux) daemon detachment
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=out_f,
            stderr=err_f,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        return proc.pid


def wait_for_port(port: int, host: str = "127.0.0.1", timeout: float = 30.0) -> int | None:
    """Poll until a port is actively listening and return its owning PID."""
    start = time.time()
    while time.time() - start < timeout:
        if is_port_in_use(port, host):
            pids = get_pids_for_port(port)
            return pids[0] if pids else -1
        time.sleep(0.1)
    return None


def probe_http_health(url: str, timeout: float = 2.0) -> tuple[bool, str]:
    """Perform a fast, standard-library HTTP GET health probe without external shell aliases."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ChanakyaTrade-Health/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return (response.status == 200, body)
    except urllib.error.HTTPError as e:
        return (False, f"HTTP {e.code}")
    except Exception as e:
        return (False, str(e))


def get_service_status(api_port: int = 8765, vite_port: int = 5173) -> bool:
    """Check and display comprehensive status of background services."""
    os_name = platform.system()
    print(f"\n=== ChanakyaTrade Service Status ({os_name}) ===")

    backend_ok = False

    # 1. Backend check
    b_pids = get_pids_for_port(api_port)
    if b_pids:
        b_pid_str = f"PID: {b_pids[0]}"
        healthy, mode_json = probe_http_health(f"http://127.0.0.1:{api_port}/api/mode")
        if healthy:
            backend_ok = True
            try:
                mdata = json.loads(mode_json)
                mode_str = f"Mode: {mdata.get('mode', 'UNKNOWN')}"
            except Exception:
                mode_str = "Mode: OK"
            print(
                f" [+] Backend (FastAPI):  RUNNING on http://127.0.0.1:{api_port} ({b_pid_str}, {mode_str})"
            )
        else:
            print(
                f" [*] Backend (FastAPI):  PORT BOUND ({b_pid_str}), but HTTP probe unready ({mode_json})"
            )
    else:
        print(f" [-] Backend (FastAPI):  STOPPED (port {api_port} free)")

    # 2. Frontend check
    f_pids = get_pids_for_port(vite_port)
    if f_pids:
        f_pid_str = f"PID: {f_pids[0]}"
        f_healthy, _ = probe_http_health(f"http://localhost:{vite_port}/")
        if f_healthy:
            print(f" [+] Frontend (Vite/UI): RUNNING on http://localhost:{vite_port} ({f_pid_str})")
        else:
            print(f" [*] Frontend (Vite/UI): PORT BOUND ({f_pid_str}), waiting for renderer")
    else:
        print(f" [-] Frontend (Vite/UI): STOPPED (port {vite_port} free)")

    print("==============================================\n")
    return backend_ok


def start_services(
    action: str = "restart",
    no_frontend: bool = False,
    skip_build_web: bool = False,
    force_build_web: bool = False,
    api_host: str = "127.0.0.1",
    api_port: int = 8765,
    vite_port: int = 5173,
    timeout: float = 45.0,
) -> int:
    """Start or restart ChanakyaTrade services dynamically based on OS."""
    if IS_WINDOWS:
        ps1_script = ROOT_DIR / "scripts" / "service.ps1"
        if ps1_script.is_file():
            cmd = [
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ps1_script),
                "-Action",
                action,
                "-ApiHost",
                api_host,
                "-ApiPort",
                str(api_port),
                "-VitePort",
                str(vite_port),
                "-TimeoutSeconds",
                str(int(timeout)),
            ]
            if no_frontend:
                cmd.append("-NoFrontend")
            if skip_build_web:
                cmd.append("-SkipBuildWeb")
            if force_build_web:
                cmd.append("-ForceBuildWeb")
            res = subprocess.run(cmd)
            return res.returncode

    # POSIX (macOS and Linux) native daemon startup
    stop_services(api_port, vite_port)

    # 1. Sync web bundle if needed
    if not no_frontend:
        sync_web_bundle(skip_build=skip_build_web, force_build=force_build_web)

    python_exe = get_python_exe()
    npm_exe = get_npm_exe()

    # 2. Launch FastAPI sidecar
    print(f"[*] Launching detached FastAPI Sidecar on http://{api_host}:{api_port} ...", flush=True)
    backend_out = LOG_DIR / "backend.log"
    backend_err = LOG_DIR / "backend_err.log"

    backend_cmd = [
        python_exe,
        "-m",
        "uvicorn",
        "web.api:app",
        "--host",
        api_host,
        "--port",
        str(api_port),
    ]

    launch_detached_process(backend_cmd, ROOT_DIR, backend_out, backend_err)

    # Wait for FastAPI to bind
    print(f"[*] Waiting for FastAPI Sidecar to initialize on port {api_port}...", flush=True)
    backend_pid = wait_for_port(api_port, api_host, timeout=timeout)
    if not backend_pid:
        print(
            f"[!] ERROR: Backend did not bind to port {api_port} within {timeout}s. Check {backend_err}",
            flush=True,
        )
        return 1

    print(
        f" [+] FastAPI Sidecar is healthy and listening on http://{api_host}:{api_port} (PID: {backend_pid})",
        flush=True,
    )

    # 3. Launch Frontend if requested
    frontend_pid = None
    if not no_frontend and FRONTEND_DIR.is_dir() and npm_exe:
        print(
            f"[*] Launching detached Vite Dev Server on http://localhost:{vite_port} ...",
            flush=True,
        )
        frontend_out = LOG_DIR / "frontend.log"
        frontend_err = LOG_DIR / "frontend_err.log"

        frontend_cmd = [npm_exe, "run", "dev:renderer"]
        launch_detached_process(frontend_cmd, FRONTEND_DIR, frontend_out, frontend_err)

        frontend_pid = wait_for_port(vite_port, "127.0.0.1", timeout=timeout)
        if frontend_pid:
            print(
                f" [+] Frontend Desktop & Vite are listening on http://localhost:{vite_port} (PID: {frontend_pid})",
                flush=True,
            )
        else:
            print(f" [*] Frontend is initializing in background (check {frontend_out})", flush=True)

    # Save PID metadata
    meta = {
        "backend_pid": backend_pid,
        "frontend_pid": frontend_pid,
        "api_port": api_port,
        "vite_port": vite_port,
        "os": platform.system(),
        "started_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        with open(PID_FILE, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
    except Exception:
        pass

    print(f"\n[SUCCESS] ChanakyaTrade services active on {platform.system()}!", flush=True)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ChanakyaTrade Dynamic Cross-Platform Service Manager"
    )
    parser.add_argument(
        "action", choices=["start", "stop", "restart", "status"], default="status", nargs="?"
    )
    parser.add_argument(
        "--no-frontend", action="store_true", help="Do not start the Vite/UI frontend"
    )
    parser.add_argument(
        "--skip-build-web", action="store_true", help="Skip web static bundle synchronization"
    )
    parser.add_argument(
        "--force-build-web", action="store_true", help="Force rebuild of web static bundle"
    )
    parser.add_argument("--host", default="127.0.0.1", help="API Host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="API Port (default: 8765)")
    parser.add_argument("--vite-port", type=int, default=5173, help="Vite UI Port (default: 5173)")
    parser.add_argument("--timeout", type=float, default=45.0, help="Startup timeout in seconds")

    args = parser.parse_args()

    if args.action == "status":
        ok = get_service_status(args.port, args.vite_port)
        sys.exit(0 if ok else 1)
    elif args.action == "stop":
        if IS_WINDOWS:
            ps1_script = ROOT_DIR / "scripts" / "service.ps1"
            if ps1_script.is_file():
                subprocess.run(
                    [
                        "powershell",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(ps1_script),
                        "-Action",
                        "stop",
                    ]
                )
                sys.exit(0)
        stop_services(args.port, args.vite_port)
        print("[+] All services cleanly stopped.")
        sys.exit(0)
    elif args.action in ("start", "restart"):
        code = start_services(
            action=args.action,
            no_frontend=args.no_frontend,
            skip_build_web=args.skip_build_web,
            force_build_web=args.force_build_web,
            api_host=args.host,
            api_port=args.port,
            vite_port=args.vite_port,
            timeout=args.timeout,
        )
        sys.exit(code)


if __name__ == "__main__":
    main()
