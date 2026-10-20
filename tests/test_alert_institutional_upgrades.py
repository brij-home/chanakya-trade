"""
tests/test_alert_institutional_upgrades.py
──────────────────────────────────────────
Institutional unit and regression test suite for:
  1. Async Scrutiny Trap Rejection Invalidation in AutoAlertEngine.
  2. Telegram Monospace Template Presentation of APEX Confluence, Execution Friction, and 0DTE Scratch.
  3. Execution Ticket Strict Limit Mandate on Wide Bid-Ask Spreads.
"""

import time
from datetime import datetime
from unittest.mock import MagicMock, patch
from config.constants import IST
from engine.alert_model import AutoAlert, ActionableBlueprint
from engine.auto_alert_engine import AutoAlertEngine
from bot.alert_templates import render_auto_alert
from engine.position_sizer import generate_execution_ticket


def test_async_scrutiny_trap_rejection_invalidates_alert():
    """Verify that when Tier-2 AI Scrutiny rejects an urgent fast-tracked alert, it is promptly invalidated."""
    engine = AutoAlertEngine()
    now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    alert_id = "aa-gamma-blast-nifty24000ce-20261018"
    alert = AutoAlert(
        alert_id=alert_id,
        symbol="NIFTY",
        alert_type="GAMMA_BLAST",
        direction="BULLISH",
        confidence=85,
        stage="NEW",
        exchange="NSE",
        headline="NIFTY 24000 CE Gamma Blast",
        summary="Urgent gamma acceleration",
        ltp=120.0,
        trigger_level=120.0,
        target_level=170.0,
        stop_loss=95.0,
        created_at=now_iso,
    )

    with engine._lock:
        engine._alerts = [alert]

    # Mock Tier-2 scrutiny returning REJECTED status with trap warning
    mock_scrutiny = MagicMock()
    mock_scrutiny.status = "REJECTED"
    mock_scrutiny.trap_risk_warning = "Institutional absorption trap into heavy put writing wall"
    mock_scrutiny.rejection_reason = "Overhead gamma supply barrier"
    mock_scrutiny.score = 35

    with patch(
        "engine.alert_scrutiny.alert_scrutiny_auditor.scrutinize_alert", return_value=mock_scrutiny
    ):
        engine._async_enrich_scrutiny(alert)
        time.sleep(0.3)  # Allow worker thread to execute

    with engine._lock:
        target = next((a for a in engine._alerts if a.alert_id == alert_id), None)
        assert target is not None
        assert target.is_invalidated is True
        assert target.stage == "INVALIDATED"
        assert "Tier-2 Scrutiny Veto" in target.invalidation_reason
        assert "Institutional absorption trap" in target.invalidation_reason


def test_telegram_template_renders_apex_confluence_and_friction_badge():
    """Verify Telegram rendering surfaces 💎 APEX CONFLUENCE header and execution friction badges."""
    now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    bp = ActionableBlueprint(
        action="BUY",
        entry_range="₹135.0",
        trigger_level=135.0,
        invalidation_stop=115.0,
        target_1=175.0,
        target_2=215.0,
        execution_friction_badge="⚠️ WIDE SPREAD — USE STRICT LIMIT",
        estimated_slippage_bps=75.0,
    )
    alert = AutoAlert(
        alert_id="aa-gamma-blast-nifty-20261018",
        symbol="NIFTY",
        contract_symbol="NIFTY 24500 CE",
        alert_type="GAMMA_BLAST",
        direction="BULLISH",
        stage="IGNITED",
        exchange="NSE",
        headline="NIFTY 24500 CE Gamma Blast",
        summary="Urgent gamma acceleration",
        ltp=135.0,
        trigger_level=135.0,
        target_level=175.0,
        stop_loss=115.0,
        option_type="CE",
        confidence=95,
        created_at=now_iso,
        actionable_plan=bp.to_dict(),
    )
    alert.is_apex_confluence = True
    alert.metrics = {"conviction_tier": "APEX_CONFLUENCE"}
    alert.execution_friction_badge = "⚠️ WIDE SPREAD — USE STRICT LIMIT"
    alert.estimated_slippage_bps = 75.0

    rendered = render_auto_alert(alert, in_market=True)
    assert "💎 APEX CONFLUENCE" in rendered
    assert "⚠️ <b>Execution Friction:</b>" in rendered
    assert "WIDE SPREAD — USE STRICT LIMIT" in rendered
    assert "75 bps" in rendered


def test_telegram_template_renders_0dte_theta_stagnation_scratch():
    """Verify 0DTE theta stagnation bailout renders an emergency scratch alert."""
    now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    bp = ActionableBlueprint(
        action="BUY",
        entry_range="₹208.0",
        trigger_level=208.0,
        invalidation_stop=170.0,
        target_1=284.0,
        target_2=360.0,
    )
    alert = AutoAlert(
        alert_id="aa-index-call-banknifty-20261018",
        symbol="BANKNIFTY",
        contract_symbol="BANKNIFTY 52000 CE",
        alert_type="INDEX_CALL_SETUP",
        direction="BULLISH",
        stage="THETA_STAGNATION_SCRATCH",
        exchange="NSE",
        headline="BANKNIFTY 52000 CE Setup",
        summary="Index call momentum",
        ltp=210.0,
        trigger_level=208.0,
        target_level=284.0,
        stop_loss=170.0,
        option_type="CE",
        confidence=80,
        created_at=now_iso,
        actionable_plan=bp.to_dict(),
    )
    alert.theta_scratch_recommended = True
    alert.stagnation_bailout_reason = (
        "0DTE Option stagnant 16m post-13:30 IST. Cut immediately to prevent theta cliff ruin."
    )

    rendered = render_auto_alert(alert, in_market=True)
    assert "0DTE THETA STAGNATION SCRATCH" in rendered
    assert "BAILOUT / SCRATCH OPTION AT MARKET" in rendered
    assert "0DTE Option stagnant 16m" in rendered


def test_position_sizer_mandates_strict_limit_on_friction_badge():
    """Verify that generate_execution_ticket forces LIMIT order when friction badge is present."""
    # When market order is requested with wide spread friction badge
    ticket = generate_execution_ticket(
        symbol="NIFTY 24500 CE",
        entry_price=135.0,
        stop_loss=115.0,
        target_price=175.0,
        capital=200000.0,
        order_type="MARKET",
        execution_friction_badge="⚠️ WIDE SPREAD — USE STRICT LIMIT",
    )

    assert ticket["order_type"] == "LIMIT"
    assert "Strict LIMIT order enforced" in ticket["notes"]
    assert ticket["execution_friction_badge"] == "⚠️ WIDE SPREAD — USE STRICT LIMIT"
