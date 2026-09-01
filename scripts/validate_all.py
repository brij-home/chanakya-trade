"""
validate_all.py — Institutional Tiered Validation Gate for ChanakyaTrade.

Usage:
  python scripts/validate_all.py --fast          # Quick local pre-commit gate (< 8s)
  python scripts/validate_all.py --full          # Full pre-push CI/CD gate (< 30s, all 2,188+ tests)
  python scripts/validate_all.py --backend-only  # Python linters + pytest
  python scripts/validate_all.py --frontend-only # React hook AST audit + vitest + web build
  python scripts/validate_all.py --fix           # Auto-format and auto-fix Python code
"""

import argparse
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


def run_step(title: str, cmd: str, cwd: str | None = None) -> bool:
    print("\n=======================================================", flush=True)
    print(f"> RUNNING: {title}", flush=True)
    print(f"  Command: {cmd}", flush=True)
    if cwd:
        print(f"  Directory: {cwd}", flush=True)
    print("=======================================================", flush=True)
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
    parser = argparse.ArgumentParser(description="ChanakyaTrade Tiered Validation Gate")
    parser.add_argument("--fast", action="store_true", help="Run fast pre-commit check (< 8s)")
    parser.add_argument(
        "--full", action="store_true", help="Run full pre-push gate (all 2,188+ tests, < 30s)"
    )
    parser.add_argument("--backend-only", action="store_true", help="Validate Python backend only")
    parser.add_argument("--frontend-only", action="store_true", help="Validate frontend only")
    parser.add_argument(
        "--fix", action="store_true", help="Auto-fix Python lint & formatting issues"
    )
    args = parser.parse_args()

    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    macos_app_dir = os.path.join(root_dir, "macos-app")
    ruff_exe = (
        os.path.join(root_dir, ".venv", "Scripts", "ruff.exe")
        if os.name == "nt"
        else os.path.join(root_dir, ".venv", "bin", "ruff")
    )

    if args.fix:
        print("\n[*] Auto-fixing Python code formatting & lints...")
        subprocess.run(f'"{ruff_exe}" check --fix .', cwd=root_dir, shell=True)
        subprocess.run(f'"{ruff_exe}" format .', cwd=root_dir, shell=True)
        print("[v] Auto-fix completed.")

    steps = []

    # Backend steps
    if not args.frontend_only:
        steps.append(
            (
                "1. Python Lint Check (ruff check)",
                f'"{ruff_exe}" check .',
                root_dir,
            )
        )
        steps.append(
            (
                "2. Python Format Check (ruff format --check)",
                f'"{ruff_exe}" format --check .',
                root_dir,
            )
        )

    # Frontend steps
    if not args.backend_only:
        steps.append(
            (
                "3. React Hook Invariant AST Linter",
                "node scripts/audit-react-hooks.js",
                macos_app_dir,
            )
        )
        steps.append(
            (
                "4. TypeScript Typecheck (tsc --noEmit)",
                "cmd /c npm run typecheck" if os.name == "nt" else "npm run typecheck",
                macos_app_dir,
            )
        )
        steps.append(
            (
                "5. Frontend Vitest Component & Store Tests",
                "cmd /c npm test" if os.name == "nt" else "npm test",
                macos_app_dir,
            )
        )

    # Pytest execution
    if not args.frontend_only:
        if args.fast or (not args.full and not args.backend_only):
            # Fast mode: Run core smoke test matrix in parallel
            core_test_files = (
                "tests/test_execution_gate.py "
                "tests/test_risk_debate.py "
                "tests/test_smart_funnel.py "
                "tests/test_multibagger.py "
                "tests/test_dcf.py "
                "tests/test_ai_brain.py "
                "tests/test_super_investor_pipeline.py "
                "tests/test_export_explain_endpoints.py"
            )
            steps.append(
                (
                    "5. Fast Pytest Smoke Matrix",
                    f'"{sys.executable}" -m pytest {core_test_files} -n 4 -q',
                    root_dir,
                )
            )
        else:
            # Full mode: Web build + full test suite with 4 workers
            if not args.backend_only:
                steps.append(
                    (
                        "5. Production Web Bundle Build",
                        "cmd /c npm run build:web" if os.name == "nt" else "npm run build:web",
                        macos_app_dir,
                    )
                )
            steps.append(
                (
                    "6. Complete Fast Pytest Test Matrix (2,188+ tests)",
                    f'"{sys.executable}" -m pytest -m "not network and not slow" -n 4 -q --tb=short',
                    root_dir,
                )
            )

    total_start = time.time()
    all_passed = True
    for title, cmd, cwd in steps:
        success = run_step(title, cmd, cwd)
        if not success:
            all_passed = False
            break

    total_duration = time.time() - total_start
    print("\n" + "=" * 60)
    if all_passed:
        mode_label = "FAST" if (args.fast or not args.full) else "FULL"
        print(f"[SUCCESS] {mode_label} VALIDATION GATE PASSED CLEANLY IN {total_duration:.2f}s!")
        print("=" * 60)
        sys.exit(0)
    else:
        print(f"[FAILED] VALIDATION GATE FAILED in {total_duration:.2f}s! Review failures above.")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()
