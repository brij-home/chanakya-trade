"""Scheduling must not defeat the candidate governor's reversal exceptions."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from config.constants import IST
from engine.alert_model import AutoAlert
from engine.alert_scrutiny import AlertScrutinyAuditor
from engine.auto_alert_engine import AutoAlertEngine


@pytest.mark.parametrize("direction", ["BULLISH", "BEARISH", "NEUTRAL"])
def test_scrutiny_passes_actual_direction_to_regime_gate(monkeypatch, direction):
    short = direction == "BEARISH"
    alert = AutoAlert(
        alert_id="regime-direction-test",
        alert_type="PRECURSOR_RADAR",
        stage="EARLY_WARNING",
        symbol="TRENT",
        exchange="NSE",
        direction=direction,
        headline="Test",
        summary="Test",
        ltp=100.0,
        trigger_level=100.0,
        stop_loss=102.0 if short else 98.0,
        target_level=94.0 if short else 106.0,
        is_live=True,
        environment="LIVE",
    )
    gate = Mock(return_value=(False, "gate reached"))
    monkeypatch.setattr("analysis.regime_governor.is_detector_eligible_for_regime", gate)
    monkeypatch.setattr(
        "analysis.regime_governor.classify_market_regime",
        lambda: SimpleNamespace(regime="BALANCED_CHOP"),
    )
    passed, reason, _ = AlertScrutinyAuditor().verify_tier1_sanity(alert)
    assert not passed and reason == "gate reached"
    assert gate.call_args.kwargs["direction"] == direction


@pytest.mark.parametrize(
    "regime", ["INSTITUTIONAL_DISTRIBUTION", "BALANCED_CHOP", "TREND_EXPANSION"]
)
def test_production_scheduler_keeps_both_directions_and_neutral_candidates_reachable(
    monkeypatch, regime
):
    from engine import auto_alert_engine as module

    engine = AutoAlertEngine.__new__(AutoAlertEngine)
    for name in dir(AutoAlertEngine):
        if name.startswith("scan_") and name != "scan_equity_nfo_now":
            setattr(engine, name, Mock(return_value=[]))
    engine._get_cycle_quotes = Mock(return_value={})
    engine._should_run_detector = Mock(return_value=True)
    monkeypatch.setenv("CHANAKYA_TESTING", "0")
    monkeypatch.setenv("DEPLOY_MODE", "live")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(module, "get_current_ist_session", lambda: {"equity_nfo": True})
    monkeypatch.setattr(
        module,
        "datetime",
        SimpleNamespace(now=lambda *args: datetime(2026, 11, 2, 10, 30, tzinfo=IST)),
    )
    monkeypatch.setattr(
        "analysis.regime_governor.classify_market_regime", lambda: SimpleNamespace(regime=regime)
    )
    assert engine.scan_equity_nfo_now() == []
    engine.scan_index_call_setups.assert_called_once()
    engine.scan_index_put_setups.assert_called_once()
    engine.scan_defined_risk_neutral.assert_called_once()
    engine.scan_squeeze_breakouts.assert_called_once()
    engine.scan_opening_range_breakouts.assert_called_once()
