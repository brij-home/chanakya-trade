"""
tests/test_tool_permissions.py
───────────────────────────────
Deterministic verification suite for Task P4-B (OPS-03):
1. Enforcement of permission="ask" gate on ToolRegistry.execute.
2. Injected approval callbacks (interactive prompt / programmatic gate).
3. Fail-closed behavior in non-interactive/auto contexts (ask -> deny).
4. Protection against demoting destructive tools.
5. Parallel execution safety with permission enforcement.
"""

from unittest.mock import MagicMock

from agent.tools import ToolRegistry


def test_permission_auto_runs_freely():
    """permission='auto' tools run freely without requiring approval."""
    reg = ToolRegistry()
    called = []
    reg.register(
        name="read_quote",
        description="Reads quote",
        parameters={"type": "object", "properties": {}},
        fn=lambda sym: called.append(sym) or {"price": 100.0},
        permission="auto",
    )
    res = reg.execute("read_quote", {"sym": "INFY"})
    assert res == {"price": 100.0}
    assert called == ["INFY"]


def test_permission_deny_blocked():
    """permission='deny' tools are blocked with an explicit permission error."""
    reg = ToolRegistry()
    called = []
    reg.register(
        name="delete_account",
        description="Deletes account",
        parameters={"type": "object", "properties": {}},
        fn=lambda: called.append(True),
        permission="deny",
    )
    res = reg.execute("delete_account", {})
    assert "error" in res
    assert "blocked by permission rules" in res["error"]
    assert len(called) == 0


def test_permission_ask_fails_closed_without_callback():
    """permission='ask' fails closed when no approval callback is configured."""
    reg = ToolRegistry(approval_callback=None)
    called = []
    reg.register(
        name="execute_order",
        description="Executes order",
        parameters={"type": "object", "properties": {}},
        fn=lambda qty: called.append(qty) or {"order_id": "ORD-1"},
        is_destructive=True,
        permission="ask",
    )
    res = reg.execute("execute_order", {"qty": 50})
    assert res.get("permission_denied") is True
    assert "requires interactive operator approval" in res.get("error", "")
    assert len(called) == 0


def test_permission_ask_denied_by_callback():
    """permission='ask' is blocked when approval callback returns False."""
    callback = MagicMock(return_value=False)
    reg = ToolRegistry(approval_callback=callback)
    called = []
    reg.register(
        name="execute_order",
        description="Executes order",
        parameters={"type": "object", "properties": {}},
        fn=lambda qty: called.append(qty) or {"order_id": "ORD-1"},
        is_destructive=True,
        permission="ask",
    )
    res = reg.execute("execute_order", {"qty": 50})
    callback.assert_called_once_with("execute_order", {"qty": 50})
    assert res.get("permission_denied") is True
    assert "denied by operator" in res.get("error", "")
    assert len(called) == 0


def test_permission_ask_approved_by_callback():
    """permission='ask' executes when approval callback returns True."""
    callback = MagicMock(return_value=True)
    reg = ToolRegistry(approval_callback=callback)
    called = []
    reg.register(
        name="execute_order",
        description="Executes order",
        parameters={"type": "object", "properties": {}},
        fn=lambda qty: called.append(qty) or {"order_id": "ORD-1"},
        is_destructive=True,
        permission="ask",
    )
    res = reg.execute("execute_order", {"qty": 50})
    callback.assert_called_once_with("execute_order", {"qty": 50})
    assert res == {"order_id": "ORD-1"}
    assert called == [50]


def test_permission_ask_dynamic_override_callback():
    """execute() accepts per-call approval_callback override."""
    default_cb = MagicMock(return_value=False)
    reg = ToolRegistry(approval_callback=default_cb)
    called = []
    reg.register(
        name="execute_order",
        description="Executes order",
        parameters={"type": "object", "properties": {}},
        fn=lambda: called.append(True) or {"status": "FILLED"},
        is_destructive=True,
        permission="ask",
    )

    # Per-call approval grants execution
    res = reg.execute("execute_order", {}, approval_callback=lambda n, a: True)
    assert res == {"status": "FILLED"}
    assert len(called) == 1
    default_cb.assert_not_called()


def test_destructive_tool_cannot_be_demoted_to_auto():
    """Destructive tools cannot be registered or re-registered with permission='auto'."""
    reg = ToolRegistry()
    reg.register(
        name="live_flatten",
        description="Flatten live",
        parameters={"type": "object", "properties": {}},
        fn=lambda: {"flattened": True},
        is_destructive=True,
        permission="auto",  # Attempt to bypass
    )
    # Automatically elevated to "ask"
    assert reg.permission("live_flatten") == "ask"

    # Attempt re-registration to demote
    reg.register(
        name="live_flatten",
        description="Innocent looking tool",
        parameters={"type": "object", "properties": {}},
        fn=lambda: {"flattened": True},
        is_destructive=False,
        permission="auto",
    )
    # Still protected as destructive and "ask"
    assert reg.is_destructive("live_flatten") is True
    assert reg.permission("live_flatten") == "ask"


def test_parallel_execution_respects_approval():
    """execute_parallel enforces approval for destructive/unsafe tools."""
    approval = MagicMock(side_effect=lambda name, args: name == "safe_write")
    reg = ToolRegistry(approval_callback=approval)

    reg.register(
        name="safe_write",
        description="Safe write",
        parameters={"type": "object", "properties": {}},
        fn=lambda: {"written": True},
        is_destructive=True,
        is_concurrency_safe=False,
        permission="ask",
    )
    reg.register(
        name="unsafe_destructive",
        description="Unsafe write",
        parameters={"type": "object", "properties": {}},
        fn=lambda: {"deleted": True},
        is_destructive=True,
        is_concurrency_safe=False,
        permission="ask",
    )

    tool_calls = [
        {"id": "call_1", "name": "safe_write", "input": {}},
        {"id": "call_2", "name": "unsafe_destructive", "input": {}},
    ]

    import json

    results = reg.execute_parallel(tool_calls)
    assert len(results) == 2

    res1 = json.loads(results[0]["content"])
    res2 = json.loads(results[1]["content"])

    assert res1 == {"written": True}
    assert res2.get("permission_denied") is True
