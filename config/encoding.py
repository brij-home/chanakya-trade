"""
config/encoding.py
──────────────────
Windows UTF-8 console encoding fix — singleton module.

Import and call fix_windows_console() ONCE at the top of each application
entrypoint (app/main.py, web/api.py) instead of copy-pasting the 10-line
block across 13+ files.

Historical issue: The reconfiguration block was duplicated verbatim in:
  agent/core.py, agent/smart_funnel.py, agent/multi_agent.py,
  web/api.py, web/skills.py, engine/auto_alert_engine.py,
  and 7+ other modules.

This module is the single source of truth. If the fix needs updating,
update it here only.
"""

from __future__ import annotations

import sys


def fix_windows_console() -> None:
    """
    Reconfigure stdout/stderr to UTF-8 on Windows to prevent cp1252 / charmap
    codec errors when printing unicode characters (emojis, rupee symbol, etc.).

    Safe to call multiple times — idempotent.
    Call once at entrypoint startup (app/main.py, web/api.py).
    """
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass  # Stream may be None or not support reconfigure (e.g. pytest capture)
