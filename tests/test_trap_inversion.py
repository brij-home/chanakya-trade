"""
tests/test_trap_inversion.py
────────────────────────────
Unit tests for Wyckoff Trap Inversion Protocol (Trading Failed Breakouts into Reversals).
"""

from unittest.mock import MagicMock
from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine


def test_wyckoff_trap_inversion_spawns_counter_trade_on_failed_breakout(monkeypatch):
    """
    Verifies that when an active Bullish Breakout alert fails and hits stop-loss,
    the AutoAlertEngine automatically inverts the trapped retail liquidity into
    an institutional Bearish Upthrust Turtle Soup counter-trade setup.
    """
    engine = AutoAlertEngine()
    engine._auditor = MagicMock()
    engine._auditor.verify_tier1_sanity.return_value = (True, "", {})
    engine._dispatch = MagicMock()
    engine._save = MagicMock()

    failed_bull_alert = AutoAlert(
        alert_id="aa-orb-infy-test-20261014",
        alert_type="ORB_BREAKOUT",
        stage="IGNITED",
        symbol="NSE:INFY",
        exchange="NSE",
        direction="BULLISH",
        headline="Infosys ORB Breakout",
        summary="Bullish expansion",
        ltp=1500.0,
        trigger_level=1500.0,
        stop_loss=1480.0,
        target_level=1550.0,
        time_horizon="INTRADAY",
        is_live=True,
        environment="LIVE",
        metrics={"rvol": 2.1},
    )

    with engine._lock:
        engine._alerts = [failed_bull_alert]

    # Handle exit: stop-loss hit
    is_inv = engine._handle_alert_exit(
        alert=failed_bull_alert,
        reason="Stop-loss breached: Price (₹1,478.00) breached invalidation stop ₹1,480.00",
        current_ltp=1478.0,
        now_iso="2026-10-14 10:15:00 IST",
        loop_context="Test",
    )

    assert is_inv is True
    assert failed_bull_alert.is_invalidated is True

    # Verify that an inverted Turtle Soup counter-trade setup was spawned and saved!
    with engine._lock:
        inversions = [
            a for a in engine._alerts if (a.metrics or {}).get("is_trap_inversion") is True
        ]

    assert len(inversions) == 1
    inv = inversions[0]
    assert inv.direction == "BEARISH"
    assert "WYCKOFF TRAP INVERSION" in inv.headline
    assert inv.alert_type == "TURTLE_SOUP_SWEEP"
    assert inv.target_level < inv.trigger_level  # Valid short target!
    assert inv.stop_loss > inv.trigger_level  # Valid short stop-loss!
    assert inv.actionable_plan is not None
    assert inv.actionable_plan.target_1 < inv.actionable_plan.trigger_level
    assert inv.actionable_plan.action == "SELL"
    assert "2.5" in inv.actionable_plan.risk_reward
