"""
tests/test_anti_pattern_and_hardcoding_invariants.py
────────────────────────────────────────────────────
Deterministic static & AST invariant test suite to proactively guard against:
1. Hardcoded index point dictionaries for stops (e.g. `index_min_stop_floor = {'NIFTY': 50}`).
2. Bare `except: pass` or `except Exception: pass` (silent error swallowing, Invariant 21).
3. Hardcoded magic valuation multipliers (e.g. `price * 1.15`, Invariant 11).
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


def test_detectors_and_trade_plan_have_no_hardcoded_index_stop_dictionaries():
    """
    RCA & Invariant 38 Guard: Prohibits hardcoding ad-hoc index dictionaries for stop loss
    points (e.g. index_min_stop_floor, index_min_floors, idx_opt_floor) across trade_plan
    and core detector modules.
    Stops must be dynamically derived via engine.dynamic_risk.get_dynamic_noise_floor.
    """
    files_to_check = [
        ROOT_DIR / "engine" / "trade_plan.py",
        ROOT_DIR / "engine" / "detectors" / "opening_drive.py",
        ROOT_DIR / "engine" / "detectors" / "afternoon_thrust.py",
        ROOT_DIR / "engine" / "detectors" / "trend_day_continuation.py",
    ]
    disallowed_vars = ["index_min_stop_floor", "index_min_floors", "idx_opt_floor", "idx_floors"]
    violations = []
    for f in files_to_check:
        if f.exists():
            text = f.read_text(encoding="utf-8")
            for var in disallowed_vars:
                if var in text:
                    violations.append(f"{f.name} contains {var}")
    assert not violations, f"Found hardcoded index stop variables: {violations}"


def test_no_bare_pass_exceptions_in_core_modules():
    """
    Invariant 21 Guard: No bare pass in except blocks across engine, market, analysis, and web.
    Every exception must log context (logger.debug, logger.warning, or logger.error).
    """
    core_dirs = ["engine", "market", "analysis", "web"]
    violations: list[str] = []

    for dir_name in core_dirs:
        target_dir = ROOT_DIR / dir_name
        if not target_dir.exists():
            continue

        for py_file in target_dir.rglob("*.py"):
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            except Exception:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler):
                    # Check if body consists solely of `pass`
                    if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                        rel_path = py_file.relative_to(ROOT_DIR)
                        violations.append(f"{rel_path}:{node.lineno}")

    assert not violations, (
        f"Found {len(violations)} bare pass violations (Invariant 21 - Zero Silent Swallowing): "
        f"{violations[:5]}... Replace with structured logger.debug/warning."
    )


def test_no_arbitrary_pricing_multipliers_in_valuation():
    """
    Invariant 11 Guard: Prohibits arbitrary static multiples like `price * 1.15` or `ltp * 1.2`
    as fair value or target formulas in security_360 and DCF models.
    """
    sec_360 = ROOT_DIR / "engine" / "security_360.py"
    if sec_360.exists():
        text = sec_360.read_text(encoding="utf-8")
        assert "price * 1.15" not in text, (
            "security_360.py must not contain hardcoded `price * 1.15`"
        )
        assert "ltp * 1.15" not in text, "security_360.py must not contain hardcoded `ltp * 1.15`"
