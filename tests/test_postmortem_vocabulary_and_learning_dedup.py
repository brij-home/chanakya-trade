"""
tests/test_postmortem_vocabulary_and_learning_dedup.py
──────────────────────────────────────────────────────
Institutional regression test suite verifying:
  1. Milestone vocabulary expansion in alert_postmortem_runner (RUNNER_EXIT, T0_5, T2, DE_RISK).
  2. Prevention of false clamping of winning runner/scale-out trades to 0.0R.
  3. Preservation of zero-milestone phantom R clamping (Rule 10 & 16 invariant).
  4. In-place outcome deduplication by alert_id in PatternLearningEngine.
  5. Canonical archetype recording in invalidation post-mortems (no INVALIDATED_ prefix).
  6. Automatic cleansing and deduplication of legacy pattern outcomes during load.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock
import pytest

from engine.alert_model import AutoAlert
from engine.alert_postmortem_runner import (
    generate_session_scorecard,
    is_target_or_profit_achieved,
)
from engine.learning_engine import PatternLearningEngine


def test_is_target_or_profit_achieved_comprehensive_vocabulary():
    """Verify that all institutional target milestones and winning stages are recognized."""
    # 1. Runner exit milestone
    a1 = MagicMock()
    a1.achieved_milestones = ["RUNNER_EXIT", "SESSION_CLOSE_EXIT"]
    a1.stage = "RUNNER_EXIT"
    a1.target_status = "RUNNER_EXIT"
    assert is_target_or_profit_achieved(a1) is True

    # 2. Scale 1 (T0.5) milestone
    a2 = MagicMock()
    a2.achieved_milestones = ["T0_5_ACHIEVED", "DE_RISK_0_5R"]
    a2.stage = "T0_5_ACHIEVED"
    a2.target_status = "T0_5_ACHIEVED"
    assert is_target_or_profit_achieved(a2) is True

    # 3. T2 target milestone
    a3 = MagicMock()
    a3.achieved_milestones = ["T2_ACHIEVED"]
    a3.stage = "COMPLETED"
    a3.target_status = "TARGET_ACHIEVED"
    assert is_target_or_profit_achieved(a3) is True

    # 4. Spread profit milestone
    a4 = MagicMock()
    a4.achieved_milestones = ["SPREAD_PROFIT_70"]
    a4.stage = "COMPLETED"
    a4.target_status = "SPREAD_PROFIT_70"
    assert is_target_or_profit_achieved(a4) is True

    # 5. Reconnaissance alert with 0 milestones (should be False)
    a5 = MagicMock()
    a5.achieved_milestones = []
    a5.stage = "EARLY_WARNING"
    a5.target_status = ""
    assert is_target_or_profit_achieved(a5, r_val=0.0) is False


def test_generate_session_scorecard_runner_and_t0_5_counted_as_wins():
    """
    Regression test: Verifies that runner exits and T0.5 scale-outs are counted as WINS
    in the EOD scorecard and their R-multiples are NOT falsely clamped to 0.0.
    """
    # Create 4 alerts:
    # Alert 1: Runner exit with +2.8R
    a1 = AutoAlert(
        alert_id="aa-orb-test1-20261028",
        alert_type="ORB_BREAKOUT",
        stage="RUNNER_EXIT",
        symbol="TATASTEEL",
        exchange="NSE",
        direction="BULLISH",
        headline="TATASTEEL Runner",
        summary="Runner exit",
        ltp=155.6,
        trigger_level=150.0,
        target_level=156.0,
        stop_loss=148.0,
    )
    a1.r_multiple = 2.8
    a1.achieved_milestones = ["T0_5_ACHIEVED", "RUNNER_EXIT"]

    # Alert 2: Target 0.5 scale-out with +1.2R
    a2 = AutoAlert(
        alert_id="aa-gamma-test2-20261028",
        alert_type="GAMMA_BLAST",
        stage="T0_5_ACHIEVED",
        symbol="NIFTY24800CE",
        exchange="NSE",
        direction="BULLISH",
        headline="NIFTY CE Target 0.5",
        summary="Scale 1 locked",
        ltp=124.0,
        trigger_level=100.0,
        target_level=140.0,
        stop_loss=80.0,
    )
    a2.r_multiple = 1.2
    a2.achieved_milestones = ["T0_5_ACHIEVED"]

    # Alert 3: Clean stop-out at -1.0R
    a3 = AutoAlert(
        alert_id="aa-spark-test3-20261028",
        alert_type="INTRADAY_BREAKOUT_SPARK",
        stage="INVALIDATED",
        symbol="RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="RELIANCE Invalidation",
        summary="Stopped out cleanly",
        ltp=1285.0,
        trigger_level=1300.0,
        target_level=1330.0,
        stop_loss=1285.0,
        is_invalidated=True,
    )
    a3.r_multiple = -1.0
    a3.achieved_milestones = []

    # Alert 4: Phantom R spike without any milestones (must be clamped to 0.0)
    a4 = AutoAlert(
        alert_id="aa-phantom-test4-20261028",
        alert_type="ORB_PRIMED",
        stage="PRIMED",
        symbol="INFY",
        exchange="NSE",
        direction="BULLISH",
        headline="INFY Primed",
        summary="Early primed setup",
        ltp=1850.0,
        trigger_level=1800.0,
        target_level=1860.0,
        stop_loss=1780.0,
    )
    a4.r_multiple = 2.5  # Unverified phantom R
    a4.achieved_milestones = []  # Zero milestones!

    scorecard = generate_session_scorecard([a1, a2, a3, a4], session_date="2026-10-28")

    # Verification:
    # Alert 1 & 2 must be wins (total 2 wins)
    assert scorecard["wins"] == 2
    # Alert 3 must be a loss (total 1 loss)
    assert scorecard["losses"] == 1
    # Alert 4 must be unfulfilled
    assert scorecard["unfulfilled"] == 1
    # Win rate across closed trades (2 wins / 3 closed) = 66.7%
    assert scorecard["win_rate_pct"] == 66.7
    # Net realized R should be 2.8 + 1.2 - 1.0 = +3.0R
    assert scorecard["net_realized_r"] == pytest.approx(3.0, abs=0.05)


def test_learning_engine_deduplication(tmp_path):
    """
    Verifies that calling record_trade_outcome() multiple times with the same alert_id
    updates in-place rather than appending duplicates.
    """
    engine = PatternLearningEngine()
    engine._outcomes = []
    # Point storage to tmp_path
    engine._save_outcomes = MagicMock()
    engine._recalculate_factor_weights = MagicMock()

    # Record first outcome
    engine.record_trade_outcome(
        alert_id="alert-101",
        symbol="SBIN",
        archetype="GAMMA_BLAST",
        entry_price=800.0,
        exit_price=820.0,
        outcome="WIN_T1",
        realized_rr=2.0,
    )
    assert len(engine._outcomes) == 1
    assert engine._outcomes[0].outcome == "WIN_T1"
    assert engine._outcomes[0].realized_rr == 2.0

    # Record second outcome for the SAME alert_id (e.g. exit update or runner completion)
    engine.record_trade_outcome(
        alert_id="alert-101",
        symbol="SBIN",
        archetype="GAMMA_BLAST",
        entry_price=800.0,
        exit_price=835.0,
        outcome="RUNNER_EXIT",
        realized_rr=3.5,
    )
    # Length MUST remain 1 (no duplicate!)
    assert len(engine._outcomes) == 1
    assert engine._outcomes[0].outcome == "RUNNER_EXIT"
    assert engine._outcomes[0].realized_rr == 3.5


def test_conduct_invalidation_canonical_archetype():
    """
    Verifies that conduct_invalidation_post_mortem records the canonical archetype
    without prepending 'INVALIDATED_'.
    """
    engine = PatternLearningEngine()
    engine._outcomes = []
    engine._post_mortems = []
    engine._save_outcomes = MagicMock()
    engine._save_post_mortems = MagicMock()
    engine._recalculate_factor_weights = MagicMock()
    engine.set_symbol_lockout = MagicMock()
    engine.record_session_trap_pivot = MagicMock()

    mock_alert = MagicMock()
    mock_alert.alert_id = "alert-inv-202"
    mock_alert.symbol = "TATASTEEL"
    mock_alert.alert_type = "THEMATIC_SYMPATHY_IGNITION"
    mock_alert.direction = "BULLISH"
    mock_alert.entry_price = 150.0
    mock_alert.stop_loss = 147.0
    mock_alert.trigger_level = 150.0
    mock_alert.ltp = 146.5
    mock_alert.option_type = None
    mock_alert.contract_symbol = None
    mock_alert.metrics = {}

    pm = engine.conduct_invalidation_post_mortem(
        alert=mock_alert,
        exit_price=147.0,
        exchange="NSE",
    )

    assert pm.alert_type == "THEMATIC_SYMPATHY_IGNITION"
    assert len(engine._outcomes) == 1
    # Archetype in outcomes must be canonical THEMATIC_SYMPATHY_IGNITION, NOT INVALIDATED_...
    assert engine._outcomes[0].archetype == "THEMATIC_SYMPATHY_IGNITION"
    assert engine._outcomes[0].outcome == "STOPPED_OUT"


def test_learning_engine_load_outcomes_cleanses_legacy_prefixes(tmp_path):
    """
    Verifies that _load_outcomes() purges duplicates and strips legacy 'INVALIDATED_' prefixes.
    """
    test_file = tmp_path / "pattern_outcomes.json"
    legacy_data = [
        {
            "alert_id": "dup-1",
            "symbol": "INFY",
            "archetype": "INVALIDATED_GAMMA_BLAST",
            "entry_price": 1800.0,
            "exit_price": 1780.0,
            "outcome": "STOPPED_OUT",
            "realized_rr": -1.0,
            "factors_present": [],
            "recorded_at": "2026-10-20 10:00:00 IST",
        },
        {
            "alert_id": "dup-1",  # Exact duplicate!
            "symbol": "INFY",
            "archetype": "GAMMA_BLAST",
            "entry_price": 1800.0,
            "exit_price": 1780.0,
            "outcome": "STOPPED_OUT",
            "realized_rr": -1.0,
            "factors_present": [],
            "recorded_at": "2026-10-20 10:05:00 IST",
        },
        {
            "alert_id": "unique-2",
            "symbol": "TCS",
            "archetype": "INVALIDATED_ORB_BREAKOUT",
            "entry_price": 4000.0,
            "exit_price": 3960.0,
            "outcome": "STOPPED_OUT",
            "realized_rr": -1.0,
            "factors_present": [],
            "recorded_at": "2026-10-20 11:00:00 IST",
        },
    ]
    test_file.write_text(json.dumps(legacy_data), encoding="utf-8")

    engine = PatternLearningEngine()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("engine.learning_engine.get_pattern_outcomes_file", lambda: test_file)
        engine._load_outcomes()

    # Must be deduplicated from 3 down to 2
    assert len(engine._outcomes) == 2
    # Prefixes must be stripped
    assert engine._outcomes[0].archetype == "GAMMA_BLAST"
    assert engine._outcomes[1].archetype == "ORB_BREAKOUT"
