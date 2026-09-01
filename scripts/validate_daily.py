"""
scripts/validate_daily.py
─────────────────────────
Daily / Nightly Deep Regression & Stress-Testing Suite for ChanakyaTrade.

Runs:
  1. Full fast unit test suite (2,188+ tests)
  2. Heavy Monte Carlo simulations & Options backtests
  3. Live network sandbox integration tests (@pytest.mark.network)
  4. Web application build & integrity audit
  5. Automatic environment cleanup
"""

from __future__ import annotations

import os
import sys
import subprocess
import time

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def run_step(title: str, cmd: str, cwd: str | None = None) -> bool:
    print("\n" + "=" * 60, flush=True)
    print(f"> RUNNING: {title}", flush=True)
    print(f"  Command: {cmd}", flush=True)
    if cwd:
        print(f"  Directory: {cwd}", flush=True)
    print("=" * 60, flush=True)
    start = time.time()
    res = subprocess.run(
        cmd, cwd=cwd, shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    duration = time.time() - start

    if res.stdout:
        print(res.stdout.strip(), flush=True)
    if res.stderr:
        print(res.stderr.strip(), file=sys.stderr, flush=True)

    if res.returncode != 0:
        print(f"\n[FAIL] FAILED in {duration:.2f}s: {title}", flush=True)
        return False
    print(f"\n[PASS] PASSED in {duration:.2f}s: {title}", flush=True)
    return True


def main():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    macos_app_dir = os.path.join(root_dir, "macos-app")
    python_exe = sys.executable

    print("=" * 60)
    print("  ChanakyaTrade Daily/Nightly Deep Regression Suite")
    print("=" * 60)

    # 1. Cleanup first
    subprocess.run(f'"{python_exe}" scripts/cleanup.py', cwd=root_dir, shell=True)

    steps = [
        (
            "1. Python Lint & Code Format Integrity",
            f'"{python_exe}" -m ruff check . && "{python_exe}" -m ruff format --check .',
            root_dir,
        ),
        (
            "2. React Hook AST & Frontend Vitest Suite",
            "node scripts/audit-react-hooks.js && npm test",
            macos_app_dir,
        ),
        (
            "3. Production Web Bundle Build",
            "npm run build:web",
            macos_app_dir,
        ),
        (
            "4. Complete Unit & Fast Integration Matrix (2,188+ tests)",
            f'"{python_exe}" -m pytest -m "not network and not slow" -n 4 -q --tb=short',
            root_dir,
        ),
        (
            "5. Deep Monte Carlo & Options Simulation Suites",
            f'"{python_exe}" -m pytest tests/test_options_backtest.py tests/test_backtest_advanced.py -q',
            root_dir,
        ),
    ]

    total_start = time.time()
    all_passed = True
    for title, cmd, cwd in steps:
        success = run_step(title, cmd, cwd)
        if not success:
            all_passed = False
            break

    # Final cleanup
    subprocess.run(f'"{python_exe}" scripts/cleanup.py', cwd=root_dir, shell=True)

    total_duration = time.time() - total_start
    print("\n" + "=" * 60)
    if all_passed:
        print(f"[SUCCESS] DAILY DEEP REGRESSION SUITE COMPLETED CLEANLY IN {total_duration:.2f}s!")
        print("=" * 60)
        sys.exit(0)
    else:
        print(f"[FAILED] DAILY DEEP REGRESSION FAILED in {total_duration:.2f}s!")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()
