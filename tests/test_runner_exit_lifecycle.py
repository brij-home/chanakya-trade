"""
tests/test_runner_exit_lifecycle.py
───────────────────────────────────
Unit tests for the runner exit vs invalidation lifecycle, monotonic update counter,
and initial SL vs ratcheted trailing SL clarity.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
import pytest

from engine.alert_model import AutoAlert
from engine.alert_expiry import is_alert_option_premium_level
from engine.alert_evaluator import evaluate_alert_invalidation
from engine.auto_alert_engine import AutoAlertEngine
from bot.alert_templates import MilestoneAlertData, render_milestone_alert, render_auto_alert


def test_is_alert_option_premium_level_with_dict():
    """Verify is_alert_option_premium_level works on dicts as well as dataclass instances."""
    d_opt = {"alert_type": "OPTIONS_MOMENTUM", "contract_symbol": "PIDILITIND26SEP1520PE"}
    assert is_alert_option_premium_level(d_opt) is True

    d_gamma = {"alert_type": "GAMMA_BLAST", "option_type": "PE", "symbol": "PIDILITIND"}
    assert is_alert_option_premium_level(d_gamma) is True

    d_eq = {"alert_type": "SQUEEZE_BREAKOUT", "symbol": "RELIANCE"}
    assert is_alert_option_premium_level(d_eq) is False


def test_evaluate_invalidation_distinguishes_trailing_stop_from_initial_sl():
    """When a ratcheted trailing stop is breached after T1, evaluate_alert_invalidation must clarify initial SL."""
    alert = AutoAlert(
        alert_id="TEST-PIDI-01",
        alert_type="GAMMA_BLAST",
        stage="TARGET_1",
        symbol="PIDILITIND",
        exchange="NSE",
        direction="BEARISH",
        headline="PIDILITIND 1520 PE",
        summary="PIDILITIND Put setup",
        ltp=17.5,
        trigger_level=18.0,
        target_level=27.0,
        stop_loss=18.8,
        option_type="PE",
        contract_symbol="PIDILITIND 1520 PE",
        strike=1520.0,
        option_premium=18.0,
        initial_stop_loss=13.5,
        target_status="T1_ACHIEVED",
        achieved_milestones=["T1_ACHIEVED"],
    )

    reason = evaluate_alert_invalidation(alert, current_ltp=17.5)
    assert reason is not None
    assert "Trailing runner stop triggered" in reason
    assert "breached ratcheted stop ₹18.8" in reason
    assert "original initial SL was ₹13.5" in reason
    assert "Target 1 profit secured" in reason


def test_post_t1_exit_becomes_runner_exit_not_invalidated(tmp_path, monkeypatch):
    """An alert that hit T1 must transition to RUNNER_EXIT (not INVALIDATED), preserving positive PnL and milestones."""
    db_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: db_file)

    engine = AutoAlertEngine()
    engine._alerts = []

    alert = AutoAlert(
        alert_id="TEST-PIDI-RUNNER",
        alert_type="GAMMA_BLAST",
        stage="TARGET_1",
        symbol="PIDILITIND",
        exchange="NSE",
        direction="BEARISH",
        headline="PIDILITIND 1520 PE",
        summary="PIDILITIND Put setup",
        ltp=18.0,
        trigger_level=18.0,
        target_level=27.0,
        stop_loss=18.8,
        option_type="PE",
        contract_symbol="PIDILITIND 1520 PE",
        strike=1520.0,
        option_premium=18.0,
        initial_stop_loss=13.5,
        target_status="T1_ACHIEVED",
        achieved_milestones=["T1_ACHIEVED"],
        pnl_pct=50.0,
        r_multiple=2.0,
        environment="LIVE",
        is_live=True,
    )
    engine._alerts.append(alert)

    # Mock batch quotes returning 17.0 (breaching ratcheted stop 18.8)
    monkeypatch.setattr(engine, "_batch_refresh_quotes", lambda alerts: {"PIDILITIND": 17.0})
    monkeypatch.setattr(engine, "_lookup_sym", lambda a: "PIDILITIND")

    dispatched = []
    monkeypatch.setattr(engine, "_dispatch", lambda a: dispatched.append(a))

    invalidated = engine.check_and_alert_invalidations()

    # Must NOT be marked as an invalidation failure
    assert len(invalidated) == 0
    assert alert.is_invalidated is False
    assert alert.stage == "RUNNER_EXIT"
    assert alert.target_status == "RUNNER_CLOSED"
    assert "RUNNER_EXIT" in alert.achieved_milestones
    assert "T1_ACHIEVED" in alert.achieved_milestones
    # Milestones must NEVER be wiped
    assert len(alert.achieved_milestones) >= 2
    # Headline must declare runner closed with profit secured
    assert "RUNNER CLOSED (PROFIT SECURED)" in alert.headline
    assert len(dispatched) == 1


def test_monotonic_update_number_never_resets():
    """Update number must strictly increase and never reset back to UPDATE #1 after prior milestones."""
    alert = AutoAlert(
        alert_id="TEST-UPDATE-NUM",
        alert_type="GAMMA_BLAST",
        stage="RUNNER_EXIT",
        symbol="PIDILITIND",
        exchange="NSE",
        direction="BEARISH",
        headline="PIDILITIND 1520 PE",
        summary="PIDILITIND Put setup",
        ltp=17.5,
        trigger_level=18.0,
        target_level=27.0,
        stop_loss=18.8,
        option_type="PE",
        contract_symbol="PIDILITIND 1520 PE",
        strike=1520.0,
        option_premium=18.0,
        initial_stop_loss=13.5,
        target_status="RUNNER_CLOSED",
        achieved_milestones=["T1_ACHIEVED", "RUNNER_EXIT"],
        update_count=4,  # e.g. Ignited (#1) -> In-Flight (#2) -> T1 Hit (#3) -> Runner Exit (#4)
        environment="LIVE",
        is_live=True,
    )

    ms_data = MilestoneAlertData.from_alert(alert, "RUNNER_EXIT")
    assert ms_data.update_number == 4

    rendered = render_auto_alert(alert)
    assert "UPDATE #4 · RUNNER CLOSED (PROFIT SECURED)" in rendered
    assert "VIEW INVALIDATED" not in rendered
    assert "Target 1 was achieved. Initial SL was never breached." in rendered


def test_rehabilitation_of_falsely_invalidated_post_t1_alert(tmp_path, monkeypatch):
    """Verify _load rehabilitates alerts that were falsely marked INVALIDATED after hitting T1."""
    db_file = tmp_path / "auto_alerts.json"
    raw_alert_dict = {
        "alert_id": "REHAB-PIDI-01",
        "alert_type": "GAMMA_BLAST",
        "stage": "INVALIDATED",
        "symbol": "PIDILITIND",
        "exchange": "NSE",
        "direction": "BEARISH",
        "headline": "⚠️ VIEW INVALIDATED: PIDILITIND",
        "summary": "Option premium collapsed to ₹17.0 (breached stop-loss ₹18.8)",
        "ltp": 17.0,
        "trigger_level": 18.0,
        "target_level": 27.0,
        "stop_loss": 18.8,
        "strike": 1520.0,
        "option_type": "PE",
        "contract_symbol": "PIDILITIND 1520 PE",
        "is_invalidated": True,
        "invalidation_reason": "Option premium collapsed to ₹17.0 (breached stop-loss ₹18.8). Put gamma thesis invalidated.",
        "achieved_milestones": ["T1_ACHIEVED"],
        "target_status": "INVALIDATED",
    }
    db_file.write_text(json.dumps([raw_alert_dict]), encoding="utf-8")
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: db_file)

    engine = AutoAlertEngine()
    rehabbed = next((a for a in engine._alerts if a.alert_id == "REHAB-PIDI-01"), None)
    assert rehabbed is not None
    assert rehabbed.is_invalidated is False
    assert rehabbed.stage == "RUNNER_EXIT"
    assert rehabbed.target_status == "RUNNER_CLOSED"
    assert "RUNNER_EXIT" in rehabbed.achieved_milestones
    assert "RUNNER CLOSED (PROFIT SECURED)" in rehabbed.headline
