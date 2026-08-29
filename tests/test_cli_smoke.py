"""
tests/test_cli_smoke.py
───────────────────────
Smoke test to ensure app.repl and CLI commands can be imported and parsed without SyntaxError.
"""

import ast
from pathlib import Path


def test_repl_ast_syntax():
    """Verify app/repl.py has valid Python AST syntax."""
    repl_path = Path(__file__).parent.parent / "app" / "repl.py"
    assert repl_path.exists()
    content = repl_path.read_text(encoding="utf-8")
    parsed = ast.parse(content)
    assert parsed is not None


def test_repl_import_smoke():
    """Verify app.repl imports cleanly without error."""
    import app.repl
    assert hasattr(app.repl, "COMMANDS")
    assert "funnel" in app.repl.COMMANDS
    assert "cache" in app.repl.COMMANDS
