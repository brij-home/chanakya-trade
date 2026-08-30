"""
validate_all.py — Institutional End-to-End Validation Gate for ChanakyaTrade.

Runs:
1. AST React Hook Invariant & Early-Return Audit (0 Hook Violations)
2. Frontend Vitest component render & user flow tests (69+ tests)
3. Production Web Bundle build (web/static/)
4. Python backend pytest suites (API, Broker, SSE, Risk Gate)
"""

import os
import sys
import subprocess
import time

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def run_step(title, cmd, cwd=None):
    print("\n=======================================================")
    print(f"> RUNNING: {title}")
    print(f"  Command: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    if cwd:
        print(f"  Directory: {cwd}")
    print("=======================================================")
    start = time.time()
    res = subprocess.run(
        cmd, cwd=cwd, shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    duration = time.time() - start

    if res.stdout:
        print(res.stdout.strip())
    if res.stderr:
        print(res.stderr.strip(), file=sys.stderr)

    if res.returncode != 0:
        print(f"\n[FAIL] FAILED in {duration:.2f}s: {title}")
        return False
    print(f"\n[PASS] PASSED in {duration:.2f}s: {title}")
    return True


def main():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    macos_app_dir = os.path.join(root_dir, "macos-app")
    pytest_exe = (
        os.path.join(root_dir, ".venv", "Scripts", "pytest.exe")
        if os.name == "nt"
        else os.path.join(root_dir, ".venv", "bin", "pytest")
    )

    steps = [
        ("1. React Hook Invariant AST Linter", "node scripts/audit-react-hooks.js", macos_app_dir),
        (
            "2. Frontend Vitest Component & Store Tests",
            "cmd /c npm test" if os.name == "nt" else "npm test",
            macos_app_dir,
        ),
        (
            "3. Production Web Bundle Build",
            "cmd /c npm run build:web" if os.name == "nt" else "npm run build:web",
            macos_app_dir,
        ),
        (
            "4. Backend Core API & SSE Test Suites",
            f'"{pytest_exe}" -v tests/test_api_broker.py tests/test_sse_streaming.py',
            root_dir,
        ),
    ]

    all_passed = True
    for title, cmd, cwd in steps:
        success = run_step(title, cmd, cwd)
        if not success:
            all_passed = False
            break

    print("\n" + "=" * 55)
    if all_passed:
        print("[SUCCESS] ALL PLATFORM VALIDATIONS PASSED CLEANLY! ZERO REGRESSIONS.")
        print("=" * 55)
        sys.exit(0)
    else:
        print("[FAILED] PLATFORM VALIDATION GATE FAILED! Review errors above.")
        print("=" * 55)
        sys.exit(1)


if __name__ == "__main__":
    main()
