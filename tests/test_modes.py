"""
tests/test_modes.py
───────────────────
Unit tests for strict 3-tier operating mode enforcement (engine/modes.py).
"""

from __future__ import annotations

import pytest
from engine.modes import (
    TradingMode,
    is_observe_mode,
    is_simulate_mode,
    is_execute_mode,
    assert_can_mutate,
    assert_live_execution_allowed,
)


def test_mode_parsing():
    assert TradingMode.from_str("OBSERVE") == TradingMode.OBSERVE
    assert TradingMode.from_str("read_only") == TradingMode.OBSERVE
    assert TradingMode.from_str("SIMULATE") == TradingMode.SIMULATE
    assert TradingMode.from_str("paper") == TradingMode.SIMULATE
    assert TradingMode.from_str("EXECUTE") == TradingMode.EXECUTE
    assert TradingMode.from_str("LIVE") == TradingMode.EXECUTE
    assert TradingMode.from_str(None) == TradingMode.SIMULATE
    assert TradingMode.from_str("unknown_xyz") == TradingMode.SIMULATE


def test_mode_helper_predicates(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    assert is_simulate_mode() is True
    assert is_observe_mode() is False
    assert is_execute_mode() is False

    monkeypatch.setenv("TRADING_MODE", "OBSERVE")
    assert is_observe_mode() is True
    assert is_simulate_mode() is False

    monkeypatch.setenv("TRADING_MODE", "LIVE")
    assert is_execute_mode() is True
    assert is_simulate_mode() is False


def test_assert_can_mutate(monkeypatch):
    # In SIMULATE or EXECUTE mode, mutation is allowed
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    assert_can_mutate("place order")

    # In OBSERVE mode, mutation is blocked
    monkeypatch.setenv("TRADING_MODE", "OBSERVE")
    with pytest.raises(PermissionError) as exc:
        assert_can_mutate("cancel order")
    assert "OBSERVE mode" in str(exc.value)


def test_assert_live_execution_allowed(monkeypatch):
    # Blocked in paper mode
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    with pytest.raises(PermissionError):
        assert_live_execution_allowed()

    # Blocked in live mode without ALLOW_LIVE_TRADING=1 server flag
    monkeypatch.setenv("TRADING_MODE", "LIVE")
    monkeypatch.delenv("ALLOW_LIVE_TRADING", raising=False)
    with pytest.raises(PermissionError) as exc:
        assert_live_execution_allowed()
    assert "ALLOW_LIVE_TRADING" in str(exc.value)

    # Allowed when both live mode and server safety flag are set
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "1")
    assert_live_execution_allowed()
