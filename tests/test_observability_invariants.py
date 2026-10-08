"""
test_observability_invariants.py — Static Invariant Verification for Zero Silent Swallowing.

Enforces Invariant 21 (Zero Silent Swallowing & Traceable Observability Contract):
Bare `except:` or `except Exception: pass` without logging is strictly prohibited across
critical analysis, detector, engine, and web modules.
"""

import ast
from pathlib import Path

# Explicitly guarded critical modules where silent swallowing has caused bugs
GUARDED_MODULES = [
    "analysis/century_compounder.py",
    "analysis/universe.py",
    "engine/detectors/pre_inflection_dryup.py",
    "engine/eod_store.py",
]


def test_no_silent_exception_swallowing_in_guarded_modules():
    root = Path(__file__).resolve().parent.parent
    violations = []

    for rel_path in GUARDED_MODULES:
        file_path = root / rel_path
        assert file_path.exists(), f"Guarded module does not exist: {file_path}"

        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(file_path))

        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                # Check 1: Body is ONLY `pass`
                if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                    violations.append(
                        f"{rel_path}:{node.lineno} -> Bare 'except: pass' without logging or handling."
                    )
                    continue

                # Check 2: Verify at least one logging / diagnostic call exists in handler
                has_logging = any(
                    isinstance(n, ast.Call)
                    and (
                        (
                            isinstance(n.func, ast.Attribute)
                            and n.func.attr in ("warning", "error", "exception", "info", "debug")
                        )
                        or (isinstance(n.func, ast.Name) and n.func.id in ("print", "log"))
                    )
                    for stmt in node.body
                    for n in ast.walk(stmt)
                )

                if not has_logging:
                    violations.append(
                        f"{rel_path}:{node.lineno} -> Exception caught without logging or diagnostic trace."
                    )

    assert not violations, (
        f"Found {len(violations)} observability violations (Invariant 21: Zero Silent Swallowing):\n"
        + "\n".join(violations)
    )
