"""
tests/test_no_hardcoded_engine_quotes.py
────────────────────────────────────────
Static AST Invariant Test: Enforces Zero Hardcoded Quotes / Placeholder Prices (Invariants 10, 11 & 23).

Parses the Abstract Syntax Tree (AST) of all production modules in engine/ to verify that:
1. No detector or scanner instantiates DetectionContext, build_detection_context, or AutoAlert
   with hardcoded numeric literals for `ltp`, `trigger_level`, or `entry_price`.
2. All quotes and prices must be passed as variables derived from live feeds or mathematical models.
"""

from __future__ import annotations

import ast
import pathlib
import pytest


def test_zero_hardcoded_prices_in_engine_ast():
    """
    Scans the engine/ codebase via Python AST to statically forbid hardcoded
    numeric literals in DetectionContext, build_detection_context, and AutoAlert calls.
    """
    engine_dir = pathlib.Path(__file__).resolve().parent.parent / "engine"
    assert engine_dir.exists(), f"Engine directory not found at {engine_dir}"

    target_constructors = {"DetectionContext", "build_detection_context", "AutoAlert"}
    price_keywords = {"ltp", "trigger_level", "entry_price"}

    violations: list[str] = []

    for py_file in engine_dir.rglob("*.py"):
        if py_file.name.startswith("test_") or "tests" in py_file.parts:
            continue

        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
        except Exception as exc:
            pytest.fail(f"Failed to parse AST for {py_file}: {exc}")

        # Walk AST tracking enclosing function definitions
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue

            func_name = node.name
            if func_name.startswith("create_test_") or func_name.startswith("test_"):
                continue

            for subnode in ast.walk(node):
                if not isinstance(subnode, ast.Call):
                    continue

                call_id = getattr(subnode.func, "id", getattr(subnode.func, "attr", ""))
                if call_id not in target_constructors:
                    continue

                for kw in subnode.keywords:
                    if kw.arg in price_keywords:
                        is_constant = isinstance(kw.value, ast.Constant) and isinstance(
                            kw.value.value, (int, float)
                        )
                        is_unary_constant = (
                            isinstance(kw.value, ast.UnaryOp)
                            and isinstance(kw.value.operand, ast.Constant)
                            and isinstance(kw.value.operand.value, (int, float))
                        )
                        if is_constant or is_unary_constant:
                            val_str = ast.unparse(kw.value)
                            rel_path = py_file.relative_to(engine_dir.parent)
                            violations.append(
                                f"{rel_path}:{subnode.lineno} in {func_name}() "
                                f"passed hardcoded literal {kw.arg}={val_str} to {call_id}()"
                            )

    assert not violations, (
        f"Zero Hardcoding Invariant (Rule 11 & 23) violated! "
        f"Found {len(violations)} hardcoded numeric quote/price literals in production engine code:\n"
        + "\n".join(f"  ❌ {v}" for v in violations)
        + "\nAll prices must be resolved dynamically via live market feeds or verified historical models."
    )
