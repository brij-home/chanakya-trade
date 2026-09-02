"""
Unit tests for agent/persona_tracker.py
Deterministic, synthetic testing of PersonaTrackerEngine.
"""

from pathlib import Path
from agent.persona_tracker import PersonaTrackerEngine


def test_persona_tracker_lifecycle(tmp_path: Path):
    db_file = tmp_path / "test_tracker.db"
    tracker = PersonaTrackerEngine(db_path=db_file)

    # 1. Record recommendation
    call_id = tracker.record_recommendation(
        persona_id="minervini",
        symbol="TRENT",
        conviction_score=85.0,
        verdict="BUY",
        entry_price=4500.0,
        target_1=4950.0,
        stop_loss=4350.0,
        sector="Retail",
        regime="TRENDING",
    )
    assert call_id > 0

    # 2. Record trade outcome
    tracker.record_trade_outcome(
        call_id=call_id,
        status="TARGET_HIT",
        exit_price=4950.0,
        realized_r=3.0,
        notes="VCP breakout completed",
    )

    # 3. Retrieve track record
    rec = tracker.get_track_record("minervini", sector="Retail", regime="TRENDING")
    assert rec.persona_id == "minervini"
    assert rec.win_rate == 100.0
    assert rec.total_calls == 1
    assert rec.data_status == "INSUFFICIENT_SAMPLE"
    assert rec.dynamic_weight_multiplier == 1.0
    assert rec.brier_score is not None

    # 4. Get all 13 track records
    all_recs = tracker.get_all_track_records()
    assert len(all_recs) == 13
    ids = [r["persona_id"] for r in all_recs]
    assert "buffett" in ids
    assert "kedia" in ids
    assert "smc" in ids
    assert "forensic" in ids


def test_persona_post_mortem(tmp_path: Path):
    db_file = tmp_path / "test_tracker2.db"
    tracker = PersonaTrackerEngine(db_path=db_file)

    pm_win = tracker.generate_post_mortem(
        persona_id="smc",
        symbol="RELIANCE",
        outcome_status="TARGET_HIT",
        realized_r=2.8,
        entry_price=2800.0,
        exit_price=2920.0,
        sector="Energy",
    )
    assert pm_win["outcome_status"] == "TARGET_HIT"
    assert "retrospective_thesis" in pm_win
    assert "key_learning" in pm_win

    pm_loss = tracker.generate_post_mortem(
        persona_id="wyckoff",
        symbol="INFY",
        outcome_status="SL_HIT",
        realized_r=-1.0,
        entry_price=1500.0,
        exit_price=1470.0,
        sector="IT",
    )
    assert pm_loss["outcome_status"] == "SL_HIT"
    assert "retrospective_thesis" in pm_loss
