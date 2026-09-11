"""
tests/test_signal_quality_and_learning_enhancements.py
───────────────────────────────────────────────────────
Comprehensive test suite verifying institutional signal conviction,
trap prevention, Donchian channel breakouts, Climax exhaustion filters,
Two-Strike session lockouts, and dual invalidation anchors.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np
import pytest

from engine.alert_model import AutoAlert
from engine.alert_scrutiny import AlertScrutinyAuditor
from engine.learning_engine import PatternLearningEngine
from engine.alert_evaluator import evaluate_alert_targets_and_trailing, evaluate_alert_invalidation
from bot.alert_templates import render_auto_alert

IST = timezone(timedelta(hours=5, minutes=30))


def test_climax_overbought_exhaustion_filter():
    """Verify AlertScrutinyAuditor rejects parabolic blow-off setups with RSI > 78 and capitulation shorts with RSI < 22."""
    auditor = AlertScrutinyAuditor()

    # 1. Parabolic Bullish Setup with RSI 82 (Blow-off top risk)
    overbought_alert = AutoAlert(
        alert_id="test-overbought-1",
        alert_type="PRECURSOR_RADAR",
        stage="IGNITED",
        symbol="NSE:TESTBULL",
        exchange="NSE",
        direction="BULLISH",
        headline="Bullish Breakout",
        summary="Parabolic move",
        ltp=1000.0,
        trigger_level=1000.0,
        stop_loss=970.0,
        target_level=1080.0,
        metrics={"rsi": 82.5},
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(overbought_alert)
    assert passed is False
    assert "Climax Exhaustion: RSI (82.5) > 78" in reason

    # 2. Healthy Bullish Setup with RSI 62
    healthy_bull = AutoAlert(
        alert_id="test-healthy-bull",
        alert_type="PRECURSOR_RADAR",
        stage="IGNITED",
        symbol="NSE:TESTBULL",
        exchange="NSE",
        direction="BULLISH",
        headline="Bullish Breakout",
        summary="Coiled move",
        ltp=1000.0,
        trigger_level=1000.0,
        stop_loss=970.0,
        target_level=1080.0,
        metrics={"rsi": 62.0},
        is_live=True,
        environment="LIVE",
    )
    passed_h, _, _ = auditor.verify_tier1_sanity(healthy_bull)
    assert passed_h is True

    # 3. Capitulation Bearish Setup with RSI 18 (Bottom shorting trap)
    oversold_short = AutoAlert(
        alert_id="test-oversold-short",
        alert_type="PRECURSOR_RADAR",
        stage="IGNITED",
        symbol="NSE:TESTBEAR",
        exchange="NSE",
        direction="BEARISH",
        headline="Bearish Breakdown",
        summary="Capitulation drop",
        ltp=500.0,
        trigger_level=500.0,
        stop_loss=520.0,
        target_level=450.0,
        metrics={"rsi": 18.0},
        is_live=True,
        environment="LIVE",
    )
    passed_os, reason_os, _ = auditor.verify_tier1_sanity(oversold_short)
    assert passed_os is False
    assert "Oversold Exhaustion: RSI (18.0) < 22" in reason_os


def test_two_strike_hard_session_lockout(tmp_path, monkeypatch):
    """Verify that a second invalidation within a session triggers an 8-hour hard lockout with disabled structural reclaim."""
    db_file = tmp_path / "test_pm.json"
    monkeypatch.setattr("engine.learning_engine.get_pattern_post_mortems_file", lambda: db_file)
    monkeypatch.setattr("engine.learning_engine.get_pattern_memory_file", lambda: tmp_path / "mem.json")
    monkeypatch.setattr("engine.learning_engine.get_pattern_outcomes_file", lambda: tmp_path / "out.json")

    engine = PatternLearningEngine()

    # Strike 1: First failure triggers adaptive lockout with reclaim level
    lock1 = engine.set_symbol_lockout(
        symbol="MCX:SILVER",
        direction="BULLISH",
        duration_seconds=5400.0,
        reclaim_level=248000.0,
    )
    assert lock1["invalidation_count"] == 1
    assert lock1["is_hard_session_lockout"] is False

    # Check that price above reclaim level clears lockout for Strike 1
    is_locked, _ = engine.is_symbol_locked_out("SILVER", direction="BULLISH", ltp=249000.0, vwap=248500.0)
    assert is_locked is False

    # Strike 2: Second failure triggers HARD SESSION LOCKOUT (8 hours, disabled reclaim)
    lock2 = engine.set_symbol_lockout(
        symbol="SILVER",
        direction="BULLISH",
        reclaim_level=248500.0,
    )
    assert lock2["invalidation_count"] == 2
    assert lock2["is_hard_session_lockout"] is True
    assert lock2["duration_minutes"] >= 480.0  # 8 hours

    # Now, even if price is above reclaim level, HARD LOCKOUT remains active
    is_locked_hard, reason = engine.is_symbol_locked_out("SILVER", direction="BULLISH", ltp=250000.0, vwap=248500.0)
    assert is_locked_hard is True
    assert "Two-Strike Rule" in reason
    assert "Hard session lockout" in reason


def test_dual_invalidation_rendering_in_options_template():
    """Verify Telegram alert template displays both Option SL and Spot Structural Anchor."""
    alert = AutoAlert(
        alert_id="opt-test-dual-1",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BEARISH",
        headline="NIFTY 23100 PE Ignited",
        summary="Institutional put surge",
        ltp=30.55,
        trigger_level=30.55,
        target_level=45.80,
        stop_loss=22.90,
        strike=23100.0,
        option_type="PE",
        contract_symbol="NIFTY23100PE",
        metrics={"spot_invalidation_anchor": 23180.0},
        actionable_plan={
            "action": "BUY PE",
            "recommended_entry": "₹30.55",
            "entry_range": "₹29.5 – ₹31.0",
            "stop_loss": "₹22.90",
            "target": "₹45.80",
            "risk_reward": "1:2.0",
            "profit_rule": "Book 50% at T1 (₹45.80), move SL to Cost.",
            "spot_invalidation_anchor": "₹23,180.0",
        },
        is_live=True,
        environment="LIVE",
    )

    rendered = render_auto_alert(alert, in_market=True)
    assert "Invalidation SL:</b> <code>₹22.90</code>" in rendered
    assert "Spot Anchor: <code>₹23,180.0</code>" in rendered
    assert "Playbook:</b> <i>Book 50% at T1 (₹45.80), move SL to Cost.</i>" in rendered


def test_absolute_profitability_invariant_in_evaluator():
    """Verify target milestones can NEVER trigger when trade is in loss or breakeven."""
    # Bullish Call buyer at 30.0, current price drops to 28.0 (loss of -2.0)
    alert = AutoAlert(
        alert_id="opt-test-loss-1",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY 23500 CE",
        summary="Call surge",
        ltp=30.0,
        trigger_level=30.0,
        target_level=45.0,
        stop_loss=20.0,
        strike=23500.0,
        option_type="CE",
        contract_symbol="NIFTY23500CE",
        is_live=True,
        environment="LIVE",
    )

    # Price at 28.0 (Loss of -₹2.0, -6.7%)
    eval_loss = evaluate_alert_targets_and_trailing(alert, current_ltp=28.0)
    assert eval_loss is not None
    # Must NOT award T1 or T2
    assert eval_loss.new_milestone is None
    assert eval_loss.should_trail is False
    assert eval_loss.pnl_pct < 0.0

    # Price at 45.5 (Target achieved: +₹15.5, +51.7%)
    eval_win = evaluate_alert_targets_and_trailing(alert, current_ltp=45.5)
    assert eval_win is not None
    assert eval_win.new_milestone == "TARGET_ACHIEVED"
    assert eval_win.trailing_decision == "BOOK_FULL_PROFIT_NO_TRAIL"
    assert eval_win.pnl_pct > 0.0
