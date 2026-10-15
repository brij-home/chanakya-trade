"""
scripts/shift_left_check.py
───────────────────────────
Institutional Shift-Left Quality & Safety Invariant Gateway for ChanakyaTrade.

Enforces zero-defect upfront validation before committing or pushing code:
  Tier 1: Static Code Hygiene (ruff lint + ruff format check)
  Tier 2: Core Safety Invariants (Rule 6 fail-closed OMS, Rule 10/23 pure data provenance,
          Rule 17 alert identity determinism, Rule 21 zero silent exception swallowing)
  Tier 3: Institutional Signal & Execution Pipeline Sanctity
  Tier 4: Full Fast Regression Suite (optional with --full)

Usage:
  python scripts/shift_left_check.py           # Standard Shift-Left gate (< 20s)
  python scripts/shift_left_check.py --fix     # Auto-fix lint & formatting issues upfront
  python scripts/shift_left_check.py --full    # Full pre-push gate including entire test suite
  python scripts/shift_left_check.py --install # Configure git core.hooksPath to .githooks
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

# Ensure UTF-8 console output
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


ROOT_DIR = Path(__file__).resolve().parent.parent


def get_optimal_workers(file_count: int | None = None, max_cap: int = 8) -> int:
    """
    Computes optimal parallel test worker count based on machine topology and workload size.
    Leaves headroom for OS and disk I/O, defaults to 2 in CI environments.
    """
    if os.environ.get("GITHUB_ACTIONS"):
        return 2
    cpu = os.cpu_count() or 2
    machine_cap = max(2, min(cpu - 2, max_cap))
    if file_count is not None and file_count > 0:
        return max(2, min(file_count, machine_cap))
    return machine_cap


def get_python_exe() -> str:
    """Resolve python executable, preferring virtualenv if active."""
    venv_win = ROOT_DIR / ".venv" / "Scripts" / "python.exe"
    venv_nix = ROOT_DIR / ".venv" / "bin" / "python"
    if venv_win.exists():
        return str(venv_win)
    if venv_nix.exists():
        return str(venv_nix)
    return sys.executable


def run_command(
    title: str,
    cmd_args: list[str],
    cwd: Path = ROOT_DIR,
    allow_failure: bool = False,
    timeout: float | None = 600.0,
    stream: bool = False,
) -> tuple[bool, float, str]:
    """Runs a command with optional real-time streaming, safety timeout, and returns (success, duration_seconds, output)."""
    print(f"\n[RUNNING] {title} ...", flush=True)
    start = time.perf_counter()
    lines: list[str] = []

    try:
        proc = subprocess.Popen(
            cmd_args,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        if proc.stdout:
            for line in iter(proc.stdout.readline, ""):
                lines.append(line)
                stripped = line.rstrip()
                if stream and stripped:
                    print(f"   {stripped}", flush=True)
            proc.stdout.close()

        try:
            returncode = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
            duration = time.perf_counter() - start
            print(f"  ❌ TIMEOUT ({duration:.2f}s exceeded {timeout}s limit): {title}", flush=True)
            return (
                False,
                duration,
                "".join(lines) + f"\n[ERROR] Command timed out after {timeout} seconds.",
            )

    except Exception as exc:
        duration = time.perf_counter() - start
        print(f"  ❌ ERROR ({duration:.2f}s): {title} ({exc})", flush=True)
        return False, duration, str(exc)

    duration = time.perf_counter() - start
    output = "".join(lines).strip()

    if returncode == 0:
        print(f"  ✅ PASS ({duration:.2f}s): {title}", flush=True)
        return True, duration, output
    else:
        if allow_failure:
            print(f"  ⚠️ WARN ({duration:.2f}s): {title}", flush=True)
            return True, duration, output
        print(f"  ❌ FAIL ({duration:.2f}s): {title}", flush=True)
        if not stream and output:
            for line in output.splitlines()[-25:]:
                print(f"     | {line}", flush=True)
        return False, duration, output


def install_hooks() -> bool:
    """Installs local git pre-commit and pre-push hooks targeting shift_left_check.py."""
    githooks_dir = ROOT_DIR / ".githooks"
    githooks_dir.mkdir(exist_ok=True)
    pre_commit_hook = githooks_dir / "pre-commit"
    pre_push_hook = githooks_dir / "pre-push"

    hook_script = """#!/bin/sh
# ChanakyaTrade Shift-Left Institutional Pre-Commit Gate
echo "🛡️  Running ChanakyaTrade Shift-Left Pre-Commit Gate..."

if [ -f ".venv/Scripts/python.exe" ]; then
    PYTHON_BIN=".venv/Scripts/python.exe"
elif [ -f ".venv/bin/python" ]; then
    PYTHON_BIN=".venv/bin/python"
else
    PYTHON_BIN="python"
fi

"$PYTHON_BIN" scripts/shift_left_check.py
if [ $? -ne 0 ]; then
    echo "❌ Pre-commit check failed! Fix issues before committing or run: $PYTHON_BIN scripts/shift_left_check.py --fix"
    exit 1
fi
echo "✅ Shift-Left validation passed!"
exit 0
"""
    pre_commit_hook.write_text(hook_script, encoding="utf-8")

    pre_push_script = """#!/bin/sh
# ChanakyaTrade Shift-Left Institutional Pre-Push Parity Gate
echo "🛡️  Running ChanakyaTrade Shift-Left Pre-Push Parity Gate..."

if [ -f ".venv/Scripts/python.exe" ]; then
    PYTHON_BIN=".venv/Scripts/python.exe"
elif [ -f ".venv/bin/python" ]; then
    PYTHON_BIN=".venv/bin/python"
else
    PYTHON_BIN="python"
fi

"$PYTHON_BIN" scripts/shift_left_check.py --full
if [ $? -ne 0 ]; then
    echo "❌ Pre-push gate failed! Regression detected before push. Fix before pushing (or git push --no-verify if emergency)."
    exit 1
fi
echo "✅ Pre-push verification passed! Remote CI parity guaranteed."
exit 0
"""
    pre_push_hook.write_text(pre_push_script, encoding="utf-8")

    try:
        import stat

        pre_commit_hook.chmod(pre_commit_hook.stat().st_mode | stat.S_IEXEC)
        pre_push_hook.chmod(pre_push_hook.stat().st_mode | stat.S_IEXEC)
    except Exception:
        pass

    # Configure git
    res = subprocess.run(
        ["git", "config", "core.hooksPath", ".githooks"],
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
    )
    if res.returncode == 0:
        print("✅ Configured git core.hooksPath -> .githooks (pre-commit & pre-push)")
        return True
    else:
        print(f"❌ Failed to configure git hooks: {res.stderr}")
        return False


def get_affected_test_suites(already_covered: set[str]) -> list[tuple[str, str]]:
    """
    Dynamically identifies test suites impacted by currently staged or modified files.
    Ensures that domain changes (alert models, detectors, brokers, configs)
    automatically trigger their corresponding unit tests in shift-left pre-commit.
    """
    cmd = ["git", "diff", "--cached", "--name-only"]
    res = subprocess.run(cmd, cwd=str(ROOT_DIR), capture_output=True, text=True)
    changed_files = [f.strip().replace("\\", "/") for f in res.stdout.splitlines() if f.strip()]
    if not changed_files:
        # Check unstaged working tree diff against HEAD
        res_work = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
        )
        changed_files = [
            f.strip().replace("\\", "/") for f in res_work.stdout.splitlines() if f.strip()
        ]
    if not changed_files:
        # Check last commit diff
        res_last = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
        )
        changed_files = [
            f.strip().replace("\\", "/") for f in res_last.stdout.splitlines() if f.strip()
        ]

    impacted: list[str] = []

    for path_str in changed_files:
        p = Path(path_str)
        # 1. Direct test file modification
        if (
            p.parts
            and p.parts[0] == "tests"
            and p.name.startswith("test_")
            and p.name.endswith(".py")
        ):
            rel_test = str(p).replace("\\", "/")
            if (ROOT_DIR / rel_test).exists():
                impacted.append(rel_test)

        # 2. Direct stem match in tests/
        stem = p.stem
        candidate = f"tests/test_{stem}.py"
        if (ROOT_DIR / candidate).exists():
            impacted.append(candidate)

        # 3. Known domain mappings
        if "alert_model" in stem or "auto_alert_engine" in stem or "interception_engine" in stem:
            for extra in [
                "tests/test_interception_engine.py",
                "tests/test_trap_and_conflict_controls.py",
                "tests/test_holistic_signals_rca.py",
                "tests/test_alert_calibration_and_enhancements.py",
            ]:
                if (ROOT_DIR / extra).exists():
                    impacted.append(extra)

        if "ws_subscription_manager" in stem:
            candidate = "tests/test_ws_subscription_manager.py"
            if (ROOT_DIR / candidate).exists():
                impacted.append(candidate)

        if "eod_report_generator" in stem or stem == "paths":
            candidate = "tests/test_eod_report_generator.py"
            if (ROOT_DIR / candidate).exists():
                impacted.append(candidate)

        if "nightly_chain" in stem or "mover_autopsy" in stem:
            candidate = "tests/test_nightly_chain.py"
            if (ROOT_DIR / candidate).exists():
                impacted.append(candidate)

        if "index_micro_scalp" in stem:
            candidate = "tests/test_index_micro_scalp_and_reversals.py"
            if (ROOT_DIR / candidate).exists():
                impacted.append(candidate)

    # Deduplicate and remove already covered suites
    unique_impacted: list[tuple[str, str]] = []
    seen = set()
    norm_covered = {c.replace("\\", "/") for c in already_covered}
    for t in impacted:
        norm = t.replace("\\", "/")
        if norm not in norm_covered and norm not in seen and (ROOT_DIR / norm).exists():
            seen.add(norm)
            unique_impacted.append((f"Tier 3.5: Impacted Suite ({Path(norm).name})", norm))

    return unique_impacted


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ChanakyaTrade Shift-Left Institutional Quality & Safety Gateway"
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Auto-fix formatting and lint issues upfront with ruff",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Run full regression test suite in addition to invariant suites",
    )
    parser.add_argument(
        "--invariants-only",
        action="store_true",
        help="Run only Tier 2 institutional invariants suites",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Install git pre-commit hook in repository",
    )
    parser.add_argument(
        "--workers",
        "-n",
        type=int,
        default=None,
        help="Number of parallel pytest workers (default: auto-detected optimal)",
    )
    args = parser.parse_args()

    if args.install:
        return 0 if install_hooks() else 1

    py_exe = get_python_exe()
    workers = args.workers if args.workers and args.workers > 0 else get_optimal_workers()
    total_start = time.perf_counter()

    print("=" * 65)
    print("🛡️  CHANAKYATRADE SHIFT-LEFT INSTITUTIONAL QUALITY GATE")
    print(f"   Python:  {py_exe}")
    print(f"   Root:    {ROOT_DIR}")
    print(f"   Workers: {workers} parallel execution workers")
    print("=" * 65)

    if args.fix:
        print("\n[*] Auto-fixing code with ruff format & check --fix ...", flush=True)
        subprocess.run([py_exe, "-m", "ruff", "format", "."], cwd=str(ROOT_DIR))
        subprocess.run([py_exe, "-m", "ruff", "check", "--fix", "."], cwd=str(ROOT_DIR))
        print("[v] Auto-fix completed.", flush=True)

    results: list[tuple[str, bool, float]] = []

    # ── Tier 1: Static Hygiene & Linters ──────────────────────────────────────
    ok, dur, _ = run_command(
        "Tier 1: Ruff Lint Check",
        [py_exe, "-m", "ruff", "check", "."],
    )
    results.append(("Ruff Lint Check", ok, dur))
    if not ok:
        print(
            "\n💡 Hint: Run `python scripts/shift_left_check.py --fix` to auto-heal fixable lint errors."
        )
        return 1

    ok, dur, _ = run_command(
        "Tier 1: Ruff Format Check",
        [py_exe, "-m", "ruff", "format", "--check", "."],
    )
    results.append(("Ruff Format Check", ok, dur))
    if not ok:
        print("\n💡 Hint: Run `python scripts/shift_left_check.py --fix` to auto-format files.")
        return 1

    # ── Tier 2 & 3 Test Suites Definition ────────────────────────────────────
    invariant_suites = [
        (
            "Alert Identity & Deduplication Invariants (Rule 17)",
            "tests/test_alert_identity_invariants.py",
        ),
        (
            "Zero Silent Swallowing & Observability Invariants (Rule 21)",
            "tests/test_observability_invariants.py",
        ),
        (
            "Pure Data Provenance & Zero Dummy Fallbacks (Rules 10, 23)",
            "tests/test_data_integrity_audit.py",
        ),
        (
            "Fail-Closed Order Execution & OMS Safety Boundary (Rule 6)",
            "tests/test_order_lifecycle.py",
        ),
        ("Live OMS Paper/Live Double-Submit Protection", "tests/test_live_oms_p3b.py"),
    ]
    invariant_files = [f for _, f in invariant_suites]

    pipeline_suites = [
        (
            "Alert Quality & Realtime Feed Verification",
            "tests/test_alert_quality_and_realtime_feed.py",
        ),
        (
            "Early Warning Interception & Proximity Promotion",
            "tests/test_interception_engine.py",
        ),
        (
            "Opposing Mutual Exclusion & Conflicting Ignition Gates",
            "tests/test_trap_and_conflict_controls.py",
        ),
        (
            "Holistic Signals RCA & Multi-Milestone Trailing",
            "tests/test_holistic_signals_rca.py",
        ),
        (
            "Hedged Spread & Sector Concurrency Limits",
            "tests/test_hedged_spread_and_concurrency.py",
        ),
        (
            "Index Adaptive Regime & Tiger Stalking Filter",
            "tests/test_index_adaptive_regime.py",
        ),
        (
            "Signal Data Integrity & Diffusion Calibration",
            "tests/test_signal_data_integrity.py",
        ),
        (
            "Signal Quality & Institutional Recommendations",
            "tests/test_signal_quality_recommendations.py",
        ),
    ]

    covered_files = set(invariant_files) | {f for _, f in pipeline_suites}
    affected_suites = get_affected_test_suites(covered_files)
    affected_files = [f for _, f in affected_suites]

    if args.invariants_only:
        worker_count = (
            args.workers
            if args.workers and args.workers > 0
            else get_optimal_workers(len(invariant_files))
        )
        print(f"\n[INFO] Running Tier 2 Invariants with {worker_count} parallel workers:")
        for title, f in invariant_suites:
            print(f"   • {title} ({f})")

        ok, dur, _ = run_command(
            f"Tier 2: Core Safety Invariants ({len(invariant_suites)} suites, {worker_count}w)",
            [
                py_exe,
                "-m",
                "pytest",
                *invariant_files,
                "-n",
                str(worker_count),
                "--dist",
                "loadfile",
                "-q",
                "--tb=line",
            ],
            timeout=180.0,
            stream=True,
        )
        results.append(("Tier 2: Core Safety Invariants", ok, dur))
        if not ok:
            return 1

    elif not args.full:
        # ── Unified Shift-Left Pre-Commit Gate (Tier 2 + Tier 3 + Tier 3.5) ───────
        all_test_files = invariant_files + [f for _, f in pipeline_suites] + affected_files
        worker_count = (
            args.workers
            if args.workers and args.workers > 0
            else get_optimal_workers(len(all_test_files))
        )

        print(
            f"\n[INFO] Running Unified Shift-Left Test Gate with {worker_count} parallel workers ({len(all_test_files)} suites):"
        )
        print(f"   • Tier 2 Invariants ({len(invariant_suites)} suites):")
        for title, f in invariant_suites:
            print(f"     - {title} ({f})")
        print(f"   • Tier 3 Core Pipelines ({len(pipeline_suites)} suites):")
        for title, f in pipeline_suites:
            print(f"     - {title} ({f})")
        if affected_suites:
            print(f"   • Tier 3.5 Git-Impacted ({len(affected_suites)} suites):")
            for title, f in affected_suites:
                print(f"     - {title} ({f})")

        extra_msg = f" + {len(affected_files)} impacted" if affected_files else ""
        ok, dur, _ = run_command(
            f"Unified Shift-Left Gate ({len(invariant_suites) + len(pipeline_suites)} suites{extra_msg}, {worker_count}w)",
            [
                py_exe,
                "-m",
                "pytest",
                *all_test_files,
                "-n",
                str(worker_count),
                "--dist",
                "loadfile",
                "-q",
                "--tb=line",
            ],
            timeout=180.0,
            stream=True,
        )
        results.append(("Unified Shift-Left Test Gate", ok, dur))
        if not ok:
            return 1
    else:
        # ── Tier 4: Full Fast Regression Suite (Pre-Push / CI) ───────────────
        worker_count = args.workers if args.workers and args.workers > 0 else get_optimal_workers()
        ok, dur, _ = run_command(
            f"Tier 4: Full Fast Regression Suite ({worker_count} workers)",
            [
                py_exe,
                "-m",
                "pytest",
                "-m",
                "not network and not slow",
                "-n",
                str(worker_count),
                "--dist",
                "loadfile",
                "-q",
                "--tb=short",
            ],
            timeout=1200.0,
            stream=True,
        )
        results.append(("Tier 4: Full Fast Regression Suite", ok, dur))
        if not ok:
            return 1

    total_duration = time.perf_counter() - total_start
    print("\n" + "=" * 65)
    print(f"🏆 SHIFT-LEFT GATE PASSED ALL {len(results)} CHECKS IN {total_duration:.2f}s!")
    print("=" * 65)
    for name, success, dur in results:
        status_icon = "✅" if success else "❌"
        print(f"  {status_icon} {name:<55} {dur:>6.2f}s")
    print("=" * 65)

    return 0


if __name__ == "__main__":
    sys.exit(main())
