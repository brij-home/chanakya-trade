"""
tests/test_microstructure_postmortem.py
────────────────────────────────────────
Deterministic verification of post-mortem microstructure attribution:
1. Order book wall trap detection (ORDER_BOOK_ABSORPTION_WALL_TRAP).
2. Heavy adverse OBI imbalance attribution (HEAVY_OBI_LIQUIDITY_RUN_IMBALANCE).
3. Excessive bid-ask spread friction attribution (EXCESSIVE_SPREAD_FRICTION_DRAG).
4. AutoAlertEngine invalidation capturing depth snapshot into exit_microstructure and audit trail.
5. Session scorecard and Telegram EOD formatting of microstructure root causes.
"""

from __future__ import annotations

import pytest

from engine.alert_model import AutoAlert
from engine.alert_postmortem_runner import (
    format_eod_scorecard_telegram,
    generate_session_scorecard,
)
from engine.learning_engine import PatternLearningEngine
from market.order_book import get_depth_book, clear_depth_books


@pytest.fixture
def temp_learning_engine(tmp_path, monkeypatch):
    mem_file = tmp_path / "pattern_memory.json"
    outcomes_file = tmp_path / "pattern_outcomes.json"
    pm_file = tmp_path / "invalidation_post_mortems.json"

    monkeypatch.setattr("engine.learning_engine.get_pattern_memory_file", lambda: mem_file)
    monkeypatch.setattr("engine.learning_engine.get_pattern_outcomes_file", lambda: outcomes_file)
    monkeypatch.setattr("engine.learning_engine.get_pattern_post_mortems_file", lambda: pm_file)

    return PatternLearningEngine()


def test_post_mortem_diagnoses_order_book_wall_trap(temp_learning_engine):
    eng = temp_learning_engine

    alert = AutoAlert(
        alert_id="aa-wall-trap-test-1",
        alert_type="GAMMA_BLAST",
        stage="TRIGGERED",
        symbol="TCS",
        exchange="NSE",
        direction="BULLISH",
        headline="GAMMA BLAST: TCS",
        summary="Bullish expansion",
        ltp=3500.0,
        trigger_level=3500.0,
        target_level=3600.0,
        stop_loss=3480.0,
        created_at="2026-10-18 11:30:00 IST",
        exit_microstructure={
            "symbol": "TCS",
            "best_bid": 3479.5,
            "best_ask": 3480.0,
            "mid_price": 3479.75,
            "spread_bps": 1.4,
            "obi_5": -0.20,
            "obi_50": -0.25,
            "has_resting_wall": True,
            "wall_side": "ASK",
            "wall_qty": 25000,
            "wall_price": 3515.0,
            "wall_ratio": 4.5,
        },
    )

    pm = eng.conduct_invalidation_post_mortem(alert, exit_price=3478.0)

    assert pm.primary_failure_reason == "ORDER_BOOK_ABSORPTION_WALL_TRAP"
    assert any("Resting fortress ASK wall" in sig for sig in pm.missed_signals)
    assert any("Resting wall avoidance" in act for act in pm.corrective_actions)
    assert pm.metrics_snapshot.get("exit_microstructure") is not None


def test_post_mortem_diagnoses_heavy_obi_imbalance(temp_learning_engine):
    eng = temp_learning_engine

    alert = AutoAlert(
        alert_id="aa-obi-imbalance-test-1",
        alert_type="SMC_SWEEP",
        stage="TRIGGERED",
        symbol="INFY",
        exchange="NSE",
        direction="BULLISH",
        headline="SMC SWEEP: INFY",
        summary="Bullish sweep",
        ltp=1850.0,
        trigger_level=1850.0,
        target_level=1900.0,
        stop_loss=1835.0,
        created_at="2026-10-18 11:30:00 IST",
        exit_microstructure={
            "symbol": "INFY",
            "best_bid": 1834.5,
            "best_ask": 1835.0,
            "mid_price": 1834.75,
            "spread_bps": 2.7,
            "obi_5": -0.42,
            "obi_50": -0.52,  # Severe ask book skew opposing long trade
            "has_resting_wall": False,
        },
    )

    pm = eng.conduct_invalidation_post_mortem(alert, exit_price=1834.0)

    assert pm.primary_failure_reason == "HEAVY_OBI_LIQUIDITY_RUN_IMBALANCE"
    assert any("Severe ask book imbalance" in sig for sig in pm.missed_signals)
    assert any("Regime-aware OBI filter" in act for act in pm.corrective_actions)


def test_post_mortem_diagnoses_excessive_spread_friction(temp_learning_engine):
    eng = temp_learning_engine

    alert = AutoAlert(
        alert_id="aa-spread-friction-test-1",
        alert_type="MOMENTUM",
        stage="TRIGGERED",
        symbol="MIDCAP_ILLIQUID",
        exchange="NSE",
        direction="BULLISH",
        headline="BREAKOUT: MIDCAP",
        summary="Midcap momentum",
        ltp=450.0,
        trigger_level=450.0,
        target_level=490.0,
        stop_loss=440.0,
        created_at="2026-10-18 11:30:00 IST",
        exit_microstructure={
            "symbol": "MIDCAP_ILLIQUID",
            "best_bid": 437.0,
            "best_ask": 440.0,
            "mid_price": 438.5,
            "spread_bps": 68.4,  # High spread friction (> 45 bps)
            "obi_5": -0.10,
            "obi_50": -0.12,
            "has_resting_wall": False,
        },
    )

    pm = eng.conduct_invalidation_post_mortem(alert, exit_price=438.0)

    assert pm.primary_failure_reason == "EXCESSIVE_SPREAD_FRICTION_DRAG"
    assert any("spread friction" in sig.lower() for sig in pm.missed_signals)
    assert any("Spread friction gate" in act for act in pm.corrective_actions)


def test_auto_alert_engine_exit_captures_depth_and_audit():
    from engine.auto_alert_engine import AutoAlertEngine

    clear_depth_books()
    book = get_depth_book("RELIANCE")
    # Feed an ask fortress wall: 5 asks with 1 massive level
    book.update_level("SELL", 2801.0, 500)
    book.update_level("SELL", 2802.0, 600)
    book.update_level("SELL", 2803.0, 8500)  # > 4x avg depth
    book.update_level("SELL", 2804.0, 400)
    book.update_level("SELL", 2805.0, 500)
    # Bids
    book.update_level("BUY", 2800.0, 1000)
    book.update_level("BUY", 2799.0, 800)

    alert = AutoAlert(
        alert_id="aa-audit-micro-test-1",
        alert_type="MOMENTUM",
        stage="TRIGGERED",
        symbol="RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="MOMENTUM: RELIANCE",
        summary="Test momentum",
        ltp=2800.0,
        trigger_level=2800.0,
        target_level=2880.0,
        stop_loss=2785.0,
        created_at="2026-10-18 11:30:00 IST",
        is_live=True,
    )

    engine = AutoAlertEngine()
    engine._alerts = [alert]

    # Invalidate alert via _handle_alert_exit
    engine._handle_alert_exit(
        alert=alert,
        reason="Stop-Loss Hit: LTP 2780.0 fell below SL 2785.0",
        current_ltp=2780.0,
        now_iso="2026-10-18 11:45:00 IST",
    )

    assert alert.is_invalidated is True
    assert alert.exit_microstructure is not None
    assert alert.exit_microstructure["has_resting_wall"] is True
    assert alert.exit_microstructure["wall_side"] == "ASK"
    assert alert.exit_microstructure["wall_qty"] == 8500

    # Verify audit trail contains EXIT_MICROSTRUCTURE event
    audit_events = [evt["event_type"] for evt in alert.audit_trail]
    assert "INVALIDATED" in audit_events
    assert "EXIT_MICROSTRUCTURE" in audit_events

    micro_audit = next(
        evt for evt in alert.audit_trail if evt["event_type"] == "EXIT_MICROSTRUCTURE"
    )
    assert micro_audit["details"]["has_resting_wall"] is True


def test_session_scorecard_aggregates_microstructure():
    alert_wall = AutoAlert(
        alert_id="aa-wall-1",
        alert_type="GAMMA_BLAST",
        stage="INVALIDATED",
        symbol="SBIN",
        exchange="NSE",
        direction="BULLISH",
        headline="GAMMA: SBIN",
        summary="Test",
        ltp=800.0,
        trigger_level=800.0,
        target_level=840.0,
        stop_loss=790.0,
        created_at="2026-10-18 11:30:00 IST",
        is_invalidated=True,
        r_multiple=-1.0,
        metrics={"post_mortem": {"primary_failure_reason": "ORDER_BOOK_ABSORPTION_WALL_TRAP"}},
    )

    alert_obi = AutoAlert(
        alert_id="aa-obi-1",
        alert_type="SMC_SWEEP",
        stage="INVALIDATED",
        symbol="HDFCBANK",
        exchange="NSE",
        direction="BULLISH",
        headline="SMC: HDFCBANK",
        summary="Test",
        ltp=1650.0,
        trigger_level=1650.0,
        target_level=1720.0,
        stop_loss=1630.0,
        created_at="2026-10-18 11:30:00 IST",
        is_invalidated=True,
        r_multiple=-1.0,
        metrics={"post_mortem": {"primary_failure_reason": "HEAVY_OBI_LIQUIDITY_RUN_IMBALANCE"}},
    )

    scorecard = generate_session_scorecard([alert_wall, alert_obi], session_date="2026-10-18")
    assert "microstructure_attribution" in scorecard
    assert scorecard["microstructure_attribution"]["wall_traps"] == 1
    assert scorecard["microstructure_attribution"]["obi_imbalances"] == 1
    assert scorecard["microstructure_attribution"]["spread_friction"] == 0

    tg_text = format_eod_scorecard_telegram(scorecard)
    assert "Microstructure Root Causes" in tg_text
    assert "1 Wall Absorption" in tg_text
    assert "1 OBI Skew" in tg_text


def test_session_scorecard_calibration_recommendations_and_persistence(tmp_path, monkeypatch):
    """
    Verifies Phase 5: Autonomous Post-Mortem & Scrutiny Calibration Loop.
    1. Detects repeated wall traps and low win rate to produce actionable scrutiny recommendations.
    2. Correctly formats autonomous scrutiny calibrations into Telegram EOD scorecard.
    3. Persists daily scorecard JSON to disk and recalibrates factor weights without error.
    """
    from engine.alert_postmortem_runner import run_eod_alert_postmortems
    from pathlib import Path

    # Redirect app_data_path to tmp_path
    monkeypatch.setattr(
        "engine.alert_postmortem_runner.app_data_path", lambda *parts: tmp_path.joinpath(*parts)
    )

    alerts = []
    # 4 stopped-out alerts with wall traps and spread drag (0% win rate -> triggers recommendations)
    for i in range(4):
        alerts.append(
            AutoAlert(
                alert_id=f"aa-test-loss-{i}",
                alert_type="INTRADAY_BREAKOUT_SPARK",
                stage="INVALIDATED",
                symbol=f"SYM{i}",
                exchange="NSE",
                direction="BULLISH",
                headline=f"SPARK: SYM{i}",
                summary="Test loss",
                ltp=500.0,
                trigger_level=500.0,
                target_level=530.0,
                stop_loss=490.0,
                created_at="2026-10-24 11:30:00 IST",
                is_invalidated=True,
                r_multiple=-1.0,
                metrics={
                    "post_mortem": {
                        "primary_failure_reason": "ORDER_BOOK_ABSORPTION_WALL_TRAP"
                        if i < 2
                        else "EXCESSIVE_SPREAD_FRICTION_DRAG"
                    }
                },
            )
        )

    scorecard = generate_session_scorecard(alerts, session_date="2026-10-24")
    assert scorecard["win_rate_pct"] == 0.0
    assert scorecard["microstructure_attribution"]["wall_traps"] == 2
    assert scorecard["microstructure_attribution"]["spread_friction"] == 2

    # Check calibration recommendations
    recs = scorecard.get("calibration_recommendations", [])
    assert len(recs) >= 2
    rec_targets = [r["target"] for r in recs]
    assert "scrutiny_conviction_threshold" in rec_targets
    assert "depth_wall_scrutiny" in rec_targets
    assert "spread_bps_cap" in rec_targets

    # Check telegram formatting
    tg = format_eod_scorecard_telegram(scorecard)
    assert "Autonomous Scrutiny Calibrations" in tg
    assert "depth_wall_scrutiny" in tg
    assert "spread_bps_cap" in tg

    # Test runner execution and persistence
    class MockEngine:
        def get_alerts(self):
            return alerts

    report = run_eod_alert_postmortems(
        auto_engine=MockEngine(), force=True, broadcast=False, session_date="2026-10-24"
    )
    assert report["status"] == "COMPLETED"
    assert report.get("scorecard_path") is not None
    assert Path(report["scorecard_path"]).exists()
    assert report["processed_count"] == 4
    assert isinstance(report.get("factor_weights"), dict)
