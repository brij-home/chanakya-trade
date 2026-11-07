from __future__ import annotations

import pytest

from engine.alert_model import AutoAlert
from engine.alert_outcomes import calculate_terminal_forward_outcome


def _alert(**overrides) -> AutoAlert:
    values = {
        "alert_id": "aa-test-nifty-20261031",
        "alert_type": "ORB_BREAKOUT",
        "stage": "IGNITED",
        "symbol": "NIFTY",
        "exchange": "NSE",
        "direction": "BULLISH",
        "headline": "Test alert",
        "summary": "Test only",
        "ltp": 100.0,
        "trigger_level": 100.0,
        "target_level": 110.0,
        "stop_loss": 95.0,
        "initial_stop_loss": 95.0,
        "is_live": True,
        "environment": "LIVE",
    }
    values.update(overrides)
    return AutoAlert(**values)


def test_terminal_forward_outcome_uses_immutable_entry_and_initial_stop():
    alert = _alert()

    outcome = calculate_terminal_forward_outcome(alert, 105.0)

    assert outcome is not None
    assert outcome.entry_price == 100.0
    assert outcome.initial_stop_loss == 95.0
    assert outcome.exit_price == 105.0
    assert outcome.realized_r == 1.0
    assert outcome.pnl_pct == 5.0


def test_untriggered_alert_has_no_trade_outcome():
    alert = _alert(stage="PRIMED")

    assert alert.has_triggered is False
    assert calculate_terminal_forward_outcome(alert, 97.0) is None


def test_alert_with_partial_scale_milestone_is_not_calibrated_as_full_exit():
    alert = _alert(achieved_milestones=["T1_ACHIEVED"])

    assert calculate_terminal_forward_outcome(alert, 110.0) is None


def test_wrong_side_initial_stop_is_rejected():
    alert = _alert(initial_stop_loss=105.0)

    assert calculate_terminal_forward_outcome(alert, 110.0) is None


def test_bearish_terminal_outcome_mirrors_bullish_path():
    outcome = calculate_terminal_forward_outcome(
        _alert(direction="BEARISH", initial_stop_loss=105.0, stop_loss=105.0, target_level=90.0),
        95.0,
    )
    assert outcome is not None
    assert outcome.realized_r == 1.0
    assert outcome.pnl_pct == 5.0


@pytest.mark.parametrize("direction", ["NEUTRAL", "UNKNOWN", ""])
def test_non_directional_payoff_requires_leg_evidence(direction):
    assert calculate_terminal_forward_outcome(_alert(direction=direction), 110.0) is None


def test_option_seller_r_uses_premium_decay_and_initial_premium():
    alert = _alert(
        alert_type="OPTION_WRITE",
        exchange="NFO",
        symbol="NIFTY",
        strike=25000.0,
        option_type="CE",
        contract_symbol="NIFTY-20261031-25000-CE",
        derivative_type="OPT",
        trigger_level=102.0,
        initial_entry_premium=100.0,
        initial_stop_loss=120.0,
        option_premium=82.0,
        ltp=82.0,
    )

    outcome = calculate_terminal_forward_outcome(alert, 80.0)

    assert outcome is not None
    assert outcome.entry_price == 100.0
    assert outcome.realized_r == 1.0
    assert outcome.pnl_pct == 20.0
