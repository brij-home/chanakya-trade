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


CORE_REMEDIATED_MODULES = [
    "engine/auto_alert_engine.py",
    "engine/alert_scrutiny.py",
    "engine/alert_evaluator.py",
    "engine/alert_model.py",
    "web/api.py",
    "agent/core.py",
    "web/skills.py",
    "brokers/mstock.py",
    "agent/multi_agent.py",
    "agent/smart_funnel.py",
    "brokers/session.py",
    "analysis/fundamental.py",
    "agent/persona_agent.py",
    "brokers/fyers.py",
    "engine/learning_engine.py",
    "engine/precursor_radar.py",
    "market/history.py",
    "market/options.py",
    "analysis/inflection_scanner.py",
    "engine/detectors/index_call_setup.py",
    "engine/detectors/index_put_setup.py",
    "engine/detectors/options_momentum.py",
    "market/fyers_tbt_manager.py",
    "market/macro.py",
    "brokers/stoxkart.py",
    "market/websocket.py",
    "engine/alerts.py",
    "engine/asymmetric_radar.py",
    "engine/telemetry.py",
    "market/fyers_order_stream.py",
    "market/mstock_websocket.py",
    "analysis/forensic.py",
    "analysis/inflection_ai.py",
    "engine/memory.py",
    "engine/order_lifecycle.py",
    "market/quotes.py",
    "analysis/dcf.py",
    "engine/conviction_score.py",
    "engine/mover_autopsy.py",
    "engine/observability.py",
    "engine/position_sizer.py",
    "engine/synthetic_sl.py",
    "engine/detectors/intraday_spark.py",
    "market/tick_store.py",
    "analysis/market_structure.py",
]


def test_no_bare_pass_in_remediated_modules():
    """Ensure zero regression of bare except: pass blocks across core institutional modules."""
    root = Path(__file__).resolve().parent.parent
    violations = []

    for rel_path in CORE_REMEDIATED_MODULES:
        file_path = root / rel_path
        assert file_path.exists(), f"Remediated module does not exist: {file_path}"

        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(file_path))

        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                    violations.append(
                        f"{rel_path}:{node.lineno} -> Bare 'except: pass' without logging or handling."
                    )

    assert not violations, (
        f"Found {len(violations)} bare pass violations in remediated core modules:\n"
        + "\n".join(violations)
    )


def test_zero_bare_pass_across_entire_codebase():
    """Invariant 21: Enforces absolute 0 bare `except: pass` blocks across all core codebase directories."""
    root = Path(__file__).resolve().parent.parent
    check_dirs = [
        "engine",
        "market",
        "analysis",
        "agent",
        "brokers",
        "web",
        "app",
        "bot",
        "ui",
        "tools",
    ]
    violations = []

    for d in check_dirs:
        dir_path = root / d
        if not dir_path.exists():
            continue
        for py_path in dir_path.rglob("*.py"):
            with open(py_path, "r", encoding="utf-8", errors="ignore") as f:
                try:
                    tree = ast.parse(f.read(), filename=str(py_path))
                except Exception:
                    continue

            rel_path = str(py_path.relative_to(root))
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler):
                    if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                        violations.append(
                            f"{rel_path}:{node.lineno} -> Bare 'except: pass' without logging or handling."
                        )

    assert not violations, (
        f"Found {len(violations)} bare pass violations across codebase (Invariant 21):\n"
        + "\n".join(violations[:20])
    )
