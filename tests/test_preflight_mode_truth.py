"""
tests/test_preflight_mode_truth.py
──────────────────────────────────
Deterministic verification suite for Task P4-D (OPS-01, OPS-06):
1. PreflightReport mode reporting matches canonical TradingMode.
2. Parametrized coverage across all mode aliases (LIVE, EXECUTE, OBSERVE, DEMO, PAPER, SIMULATE).
3. Gate states (ALLOW_LIVE_TRADING, LIVE_EXECUTION_QUALIFIED) surfaced truthfully.
4. EXECUTE mode fails or requires explicit acknowledgment for healthy status.
"""

import pytest

from engine.preflight import run_preflight


@pytest.mark.parametrize(
    "raw_mode,expected_canonical_mode",
    [
        ("LIVE", "EXECUTE"),
        ("EXECUTE", "EXECUTE"),
        ("OBSERVE", "OBSERVE"),
        ("DEMO", "OBSERVE"),
        ("PAPER", "SIMULATE"),
        ("SIMULATE", "SIMULATE"),
    ],
)
def test_preflight_mode_truthful_resolution(monkeypatch, raw_mode, expected_canonical_mode):
    """A live desk can NEVER be told it is in paper mode; canonical mode must be truthful."""
    monkeypatch.setenv("TRADING_MODE", raw_mode)
    monkeypatch.delenv("ALLOW_LIVE_TRADING", raising=False)
    monkeypatch.delenv("LIVE_EXECUTION_QUALIFIED", raising=False)

    report = run_preflight(verbose=False)
    assert report.mode == expected_canonical_mode

    # Find the Trading Mode Safety check
    mode_check = next((c for c in report.checks if c.name == "Trading Mode Safety"), None)
    assert mode_check is not None
    assert mode_check.details["mode"] == expected_canonical_mode
    assert mode_check.details["raw"] == raw_mode


def test_preflight_execute_mode_fails_when_gates_locked(monkeypatch):
    """In EXECUTE mode without qualification gates, preflight fails closed."""
    monkeypatch.setenv("TRADING_MODE", "EXECUTE")
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "0")
    monkeypatch.setenv("LIVE_EXECUTION_QUALIFIED", "0")

    report = run_preflight(verbose=False)
    assert report.mode == "EXECUTE"
    assert report.healthy is False

    mode_check = next(c for c in report.checks if c.name == "Trading Mode Safety")
    assert mode_check.status == "FAIL"
    assert "requires both ALLOW_LIVE_TRADING=1 and LIVE_EXECUTION_QUALIFIED=1" in mode_check.message
    assert mode_check.details["allow_live_trading"] is False
    assert mode_check.details["live_execution_qualified"] is False


def test_preflight_execute_mode_unacknowledged_is_not_healthy(monkeypatch):
    """In EXECUTE mode with gates open but unacknowledged, healthy is False."""
    monkeypatch.setenv("TRADING_MODE", "EXECUTE")
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "1")
    monkeypatch.setenv("LIVE_EXECUTION_QUALIFIED", "1")
    monkeypatch.delenv("LIVE_EXECUTION_ACKNOWLEDGED", raising=False)

    report = run_preflight(verbose=False)
    assert report.mode == "EXECUTE"
    assert report.healthy is False

    mode_check = next(c for c in report.checks if c.name == "Trading Mode Safety")
    assert mode_check.status == "WARN"
    assert "Requires LIVE_EXECUTION_ACKNOWLEDGED=1" in mode_check.message


def test_preflight_simulate_mode_is_safe_default(monkeypatch):
    """In SIMULATE mode, Trading Mode Safety passes with zero real capital risk."""
    monkeypatch.setenv("TRADING_MODE", "SIMULATE")
    report = run_preflight(verbose=False)
    assert report.mode == "SIMULATE"

    mode_check = next(c for c in report.checks if c.name == "Trading Mode Safety")
    assert mode_check.status == "PASS"
    assert "Safe Default: SIMULATE" in mode_check.message
