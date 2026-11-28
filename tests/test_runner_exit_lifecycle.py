"""
tests/test_runner_exit_lifecycle.py
───────────────────────────────────
Unit tests for the runner exit vs invalidation lifecycle, monotonic update counter,
and initial SL vs ratcheted trailing SL clarity.
"""

from __future__ import annotations

import json

from engine.alert_model import AutoAlert
from engine.alert_expiry import is_alert_option_premium_level
from engine.alert_evaluator import evaluate_alert_invalidation
from engine.auto_alert_engine import AutoAlertEngine
from bot.alert_templates import MilestoneAlertData, render_auto_alert


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
    assert (
        "Trailing runner stop triggered" in reason or "Trailing breakeven stop triggered" in reason
    )
    assert "breached stop ₹18.8" in reason or "breached ratcheted stop ₹18.8" in reason
    assert "original initial SL was ₹13.5" in reason
    assert "T1 profit banked earlier" in reason


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
    assert "UPDATE #4 · RUNNER CLOSED" in rendered
    assert "VIEW INVALIDATED" not in rendered
    assert "Target 1 was achieved. Initial SL was never breached." in rendered


def test_rehabilitation_of_falsely_invalidated_post_t1_alert(tmp_path, monkeypatch):
    """Verify explicit rehabilitation restores alerts that were falsely marked INVALIDATED after hitting T1."""
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
    engine.rehabilitate_falsely_invalidated_options()
    rehabbed = next((a for a in engine._alerts if a.alert_id == "REHAB-PIDI-01"), None)
    assert rehabbed is not None
    assert rehabbed.is_invalidated is False
    assert rehabbed.stage == "RUNNER_EXIT"
    assert rehabbed.target_status == "RUNNER_CLOSED"
    assert "RUNNER_EXIT" in rehabbed.achieved_milestones
    assert "RUNNER CLOSED (PROFIT SECURED)" in rehabbed.headline


def test_protection_exit_after_t0_5_never_claims_t1_achieved_or_profit_secured(monkeypatch):
    """De-risked T0.5/BE protection stop (-3.0%) must NOT fabricate T1 PROFIT BANKED or WIN."""
    engine = AutoAlertEngine()
    monkeypatch.setattr(engine, "_save", lambda *a, **kw: None)

    alert = AutoAlert(
        alert_id="TEST-SENSEX-BE-PROT",
        alert_type="TREND_DAY_PULLBACK",
        stage="BREAKEVEN_LOCKED",
        symbol="SENSEX",
        exchange="BFO",
        segment="FNO_INDEX",
        direction="BEARISH",
        headline="SENSEX 83700 PE",
        summary="SENSEX pullback",
        ltp=708.05,
        trigger_level=729.95,
        target_level=882.0,
        stop_loss=729.95,
        option_type="PE",
        contract_symbol="BSE:SENSEX26D0383700PE",
        strike=83700.0,
        lot_size=20,
        option_premium=729.95,
        initial_stop_loss=653.95,
        target_status="T0_5_ACHIEVED",
        achieved_milestones=["T0_5_ACHIEVED", "BREAKEVEN_LOCKED"],
        update_count=2,
        environment="LIVE",
        is_live=True,
    )

    reason = (
        "Breakeven Protection Triggered: De-risked trade fell below entry buffer "
        "(Option LTP ₹708.1 < Entry ₹730.0, Drawdown -3.0%). "
        "Protection floor enforced before initial SL breach."
    )
    engine._handle_alert_exit(alert, reason=reason, current_ltp=708.05)

    assert alert.is_invalidated is False
    assert alert.stage == "RUNNER_EXIT"
    assert alert.target_status == "BREAKEVEN_CLOSED"
    assert "RUNNER CLOSED (PROFIT SECURED)" not in alert.headline
    assert "BREAKEVEN PROTECTION EXIT" in alert.headline

    rendered = render_auto_alert(alert)
    assert "PROTECTION STOP HIT" in rendered
    assert "T1 PROFIT BANKED" not in rendered
    assert "Target 1 was achieved" not in rendered
    assert "Exit P&L:" in rendered
    assert "/pt" in rendered


def test_runner_exit_after_actual_t1_labels_runner_leg_pnl():
    """When T1 WAS achieved and residual runner closes negative, clarify Runner Leg P&L."""
    alert = AutoAlert(
        alert_id="TEST-SENSEX-T1-RUNNER",
        alert_type="TREND_DAY_PULLBACK",
        stage="RUNNER_EXIT",
        symbol="SENSEX",
        exchange="BFO",
        segment="FNO_INDEX",
        direction="BEARISH",
        headline="🏁 [LIVE] RUNNER CLOSED: SENSEX 83700 PE",
        summary="Trailing stop hit after T1",
        ltp=708.05,
        trigger_level=729.95,
        target_level=882.0,
        stop_loss=729.95,
        option_type="PE",
        contract_symbol="BSE:SENSEX26D0383700PE",
        strike=83700.0,
        lot_size=20,
        option_premium=729.95,
        initial_stop_loss=653.95,
        target_status="RUNNER_CLOSED",
        achieved_milestones=["T1_ACHIEVED", "RUNNER_EXIT"],
        update_count=2,
        environment="LIVE",
        is_live=True,
    )

    rendered = render_auto_alert(alert)
    assert "RUNNER CLOSED (T1 PROFIT BANKED · RUNNER STOP HIT)" in rendered
    assert "Target 1 was achieved. Initial SL was never breached." in rendered
    assert "Runner Leg P&L:" in rendered
    assert "/pt" in rendered


def test_de_risk_0_5r_breakeven_protection_exit_not_view_invalidated(monkeypatch):
    """Alert 9 RCA: INFY at stage DE_RISK_0_5R hitting Breakeven Protection Triggered must render PROTECTION STOP HIT, never VIEW INVALIDATED."""
    engine = AutoAlertEngine()
    monkeypatch.setattr(engine, "_save", lambda *a, **kw: None)

    alert = AutoAlert(
        alert_id="TEST-INFY-BE-DE-RISK",
        alert_type="OPTIONS_MOMENTUM",
        stage="DE_RISK_0_5R",
        symbol="INFY",
        exchange="NFO",
        segment="FNO_STOCK",
        direction="BEARISH",
        headline="INFY 1154 PE",
        summary="INFY Put surge",
        ltp=38.0,
        trigger_level=38.95,
        target_level=48.30,
        stop_loss=36.0,
        option_type="PE",
        contract_symbol="NSE:INFY26DEC1154PE",
        strike=1154.0,
        lot_size=400,
        option_premium=38.95,
        initial_stop_loss=34.28,
        achieved_milestones=[],
        update_count=1,
        environment="LIVE",
        is_live=True,
    )

    reason = (
        "Breakeven Protection Triggered: De-risked trade fell below entry buffer "
        "(Option LTP ₹38.0 < Entry ₹39.0, Drawdown -2.4%). "
        "Protection floor enforced before initial SL breach."
    )
    engine._handle_alert_exit(alert, reason=reason, current_ltp=38.0)

    assert alert.is_invalidated is False
    assert alert.stage == "RUNNER_EXIT"
    assert alert.target_status == "BREAKEVEN_CLOSED"
    assert "BREAKEVEN PROTECTION EXIT" in alert.headline

    rendered = render_auto_alert(alert)
    assert "VIEW INVALIDATED" not in rendered
    assert "NO LONGER VALID" not in rendered
    assert "PROTECTION STOP HIT" in rendered
    assert "T1 PROFIT BANKED" not in rendered
