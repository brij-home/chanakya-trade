"""
tests/test_invalidation_learning.py
───────────────────────────────────
Unit & integration tests for:
1. Forensic Invalidation Post-Mortem extraction (missed signals, failure reasons).
2. Negative Feedback Symbol Lockout (knife-catching prevention).
3. AutoAlertEngine live vs test alert separation on invalidation sweeps.
4. Coiling detector lockout gating & noise floor stop-loss buffer.
5. Post-mortem API endpoints.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from engine.auto_alert_engine import AutoAlert, AutoAlertEngine
from engine.learning_engine import (
    InvalidationPostMortem,
    PatternLearningEngine,
)


@pytest.fixture
def temp_learning_engine(tmp_path, monkeypatch):
    mem_file = tmp_path / "pattern_memory.json"
    outcomes_file = tmp_path / "pattern_outcomes.json"
    pm_file = tmp_path / "invalidation_post_mortems.json"

    monkeypatch.setattr("engine.learning_engine.get_pattern_memory_file", lambda: mem_file)
    monkeypatch.setattr("engine.learning_engine.get_pattern_outcomes_file", lambda: outcomes_file)
    monkeypatch.setattr("engine.learning_engine.get_pattern_post_mortems_file", lambda: pm_file)

    eng = PatternLearningEngine()
    return eng


def test_symbol_invalidation_lockout(temp_learning_engine):
    eng = temp_learning_engine

    # Initially not locked out
    is_locked, reason = eng.is_symbol_locked_out("MANKIND", direction="BULLISH")
    assert is_locked is False

    # Activate lockout for 10 seconds
    eng.set_symbol_lockout(
        "MANKIND", direction="BULLISH", duration_seconds=10.0, reason="Sub-ATR noise stop breach"
    )

    is_locked, reason = eng.is_symbol_locked_out("MANKIND", direction="BULLISH")
    assert is_locked is True
    assert "Sub-ATR noise stop breach" in reason

    # Opposite direction (BEARISH) is not locked
    is_locked_bear, _ = eng.is_symbol_locked_out("MANKIND", direction="BEARISH")
    assert is_locked_bear is False

    # Check active lockouts listing
    active = eng.get_locked_out_symbols()
    assert len(active) == 1
    assert active[0]["symbol"] == "MANKIND"

    # Clear lockout
    eng.clear_symbol_lockout("MANKIND")
    is_locked_after, _ = eng.is_symbol_locked_out("MANKIND", direction="BULLISH")
    assert is_locked_after is False


def test_conduct_invalidation_post_mortem(temp_learning_engine):
    eng = temp_learning_engine

    dummy_alert = AutoAlert(
        alert_id="test-inv-mankind-1",
        alert_type="PATTERN_COILING",
        stage="EARLY_WARNING",
        symbol="MANKIND",
        exchange="NSE",
        direction="BULLISH",
        headline="PRE-BLAST COILING: MANKIND",
        summary="Coiling setup",
        ltp=2274.0,
        trigger_level=2274.0,
        target_level=2400.0,
        stop_loss=2271.0,  # Only 3 pts away -> sub-ATR stop
    )

    pm = eng.conduct_invalidation_post_mortem(dummy_alert, exit_price=2270.0)

    assert isinstance(pm, InvalidationPostMortem)
    assert pm.symbol == "MANKIND"
    assert pm.alert_id == "test-inv-mankind-1"
    assert pm.realized_r < 0
    assert len(pm.missed_signals) > 0
    assert len(pm.corrective_actions) > 0
    assert "MANKIND" in pm.corrective_actions[0]

    # Verify symbol was automatically locked out
    is_locked, _ = eng.is_symbol_locked_out("MANKIND", "BULLISH")
    assert is_locked is True

    # Verify post-mortem was persisted
    recent = eng.get_recent_post_mortems()
    assert len(recent) >= 1
    assert recent[0]["symbol"] == "MANKIND"


def test_evaluate_candidate_respects_lockout(temp_learning_engine):
    eng = temp_learning_engine

    # Lock out MANKIND
    eng.set_symbol_lockout(
        "MANKIND", direction="BULLISH", duration_seconds=600.0, reason="Recent invalidation"
    )

    res = eng.evaluate_candidate("MANKIND")
    assert res.is_explosive_candidate is False
    assert res.recommended_entry_action == "LOCKED_OUT_POST_MORTEM"
    assert any("locked out" in f.lower() for f in res.matched_factors)


def test_auto_alert_engine_skips_test_alerts_during_invalidation_sweep(tmp_path, monkeypatch):
    data_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)

    engine = AutoAlertEngine()
    engine.clear_alerts()

    # Create a synthetic test alert on RELIANCE with SL 2820
    test_alert = AutoAlert(
        alert_id="test-target-fake-1",
        alert_type="SQUEEZE_BREAKOUT",
        stage="T1_ACHIEVED",
        symbol="RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="[TEST] TARGET 1: RELIANCE",
        summary="Test target",
        ltp=2920.0,
        trigger_level=2860.0,
        target_level=3050.0,
        stop_loss=2820.0,
        is_live=False,
        environment="TEST",
        is_invalidated=False,
    )
    engine._alerts.append(test_alert)

    # Mock get_ltp to return 1309.0 (Reliance real current price)
    with patch("market.quotes.get_ltp", return_value=1309.0):
        # check_and_alert_invalidations must SKIP test alerts!
        invalidated = engine.check_and_alert_invalidations()
        assert len(invalidated) == 0

    # Ensure test alert remains not invalidated
    assert test_alert.is_invalidated is False
    assert test_alert.stage == "T1_ACHIEVED"


def test_auto_alert_engine_records_post_mortem_on_live_invalidation(tmp_path, monkeypatch):
    data_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)

    engine = AutoAlertEngine()
    engine.clear_alerts()

    live_alert = AutoAlert(
        alert_id="live-mankind-1",
        alert_type="PATTERN_COILING",
        stage="EARLY_WARNING",
        symbol="MANKIND",
        exchange="NSE",
        direction="BULLISH",
        headline="PRE-BLAST COILING: MANKIND",
        summary="Live coiling",
        ltp=2280.0,
        trigger_level=2280.0,
        target_level=2400.0,
        stop_loss=2270.0,
        is_live=True,
        environment="LIVE",
        is_invalidated=False,
    )
    engine._alerts.append(live_alert)

    # Mock price dropping to 2265.0 (below stop-loss 2270.0)
    with patch("market.quotes.get_ltp", return_value=2265.0):
        invalidated = engine.check_and_alert_invalidations()
        assert len(invalidated) == 1
        assert invalidated[0].alert_id == "live-mankind-1"
        assert invalidated[0].is_invalidated is True
        assert "post_mortem" in invalidated[0].metrics
        pm = invalidated[0].metrics["post_mortem"]
        assert pm["symbol"] == "MANKIND"
        assert len(pm["missed_signals"]) > 0


def test_adaptive_structural_reclaim_unlocks_symbol(temp_learning_engine):
    eng = temp_learning_engine

    # 1. Activate lockout on MANKIND with reclaim level 2274.0 (the breakdown level)
    eng.set_symbol_lockout(
        "MANKIND",
        direction="BULLISH",
        duration_seconds=5400.0,
        reason="Stop loss breach",
        reclaim_level=2274.0,
    )

    # Price at 2270.0 (below 2274.0) -> Remains locked out
    is_locked, reason = eng.is_symbol_locked_out(
        "MANKIND", direction="BULLISH", ltp=2270.0, vwap=2272.0
    )
    assert is_locked is True

    # Price at 2276.0 (surged above 2274.0 reclaim level and above VWAP 2272.0) -> Wyckoff Spring Reclaim!
    is_locked_reclaim, _ = eng.is_symbol_locked_out(
        "MANKIND", direction="BULLISH", ltp=2276.0, vwap=2272.0
    )
    assert is_locked_reclaim is False

    # Lockout should now be automatically cleared from engine state
    assert len(eng.get_locked_out_symbols()) == 0
