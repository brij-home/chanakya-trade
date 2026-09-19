"""
tests/test_signal_pipeline_fixes.py
───────────────────────────────────
Tests for:
1. Option entry range domain isolation against underlying spot/futures coordinates.
2. Closed-loop milestone trade outcome recording in learning engine.
3. Truthful, zero-hallucination EOD reporting on zero alerts.
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock
from engine.auto_alert_engine import AutoAlert, AutoAlertEngine
from engine.eod_report_generator import EODReportGenerator


def test_option_entry_range_not_mangled_by_underlying_price(tmp_path, monkeypatch):
    """Verify that when a spot/futures alert attaches an option plan, entry_range is preserved in option coordinates."""
    data_file = tmp_path / "auto_alerts_test.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)
    monkeypatch.setattr("engine.auto_alert_engine.AutoAlertEngine._dispatch", lambda self, a: None)
    monkeypatch.setattr("engine.learning_engine.pattern_learning_engine.is_symbol_locked_out", lambda *a, **kw: (False, ""))

    engine = AutoAlertEngine(max_buffer=20)
    engine.clear_alerts()

    # Commodity Momentum alert where underlying is CRUDEOIL at ~9196, SL is 9306.54
    # But the actionable plan is for an ATM Put Option trading at ₹347.02
    alert = AutoAlert(
        alert_id="comm-crudeoil-test",
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        symbol="CRUDEOIL",
        exchange="MCX",
        direction="BEARISH",
        headline="MCX OPTION: CRUDEOIL 9200 PE @ ₹347.0",
        summary="Commodity breakdown",
        ltp=9196.14,
        trigger_level=9196.14,
        target_level=8975.34,
        stop_loss=9306.54,
        option_premium=347.02,
        actionable_plan={
            "action": "BUY_PE",
            "segment": "COMMODITY",
            "instrument_type": "OPTION",
            "contract": "CRUDEOIL 9200 PE (16 Oct)",
            "raw_contract": "MCX:CRUDEOIL26OCT9200PE",
            "entry_range": "₹340.0 – ₹355.0",
            "stop_loss": "₹289.6",
            "target": "₹461.8",
            "target_2": "₹547.9",
            "trade_plan": {
                "entry_price": 347.02,
                "invalidation_stop": 289.6,
                "target_1": 461.8,
            },
        },
    )

    rec = engine.record_alert(alert)
    assert rec is True

    saved = engine._alerts[0]
    entry_range = saved.actionable_plan.get("entry_range", "")
    assert "9,307" not in entry_range, "Entry range was erroneously overwritten with underlying futures levels!"
    assert "340" in entry_range or "347" in entry_range, f"Entry range should remain in option premium space: {entry_range}"


def test_closed_loop_target_milestone_recorded_in_learning_engine(monkeypatch):
    """Verify that when an alert achieves Target 1, it is recorded in pattern_learning_engine."""
    from engine.learning_engine import pattern_learning_engine

    recorded_outcomes = []
    monkeypatch.setattr(
        pattern_learning_engine,
        "record_trade_outcome",
        lambda **kwargs: recorded_outcomes.append(kwargs),
    )

    engine = AutoAlertEngine(max_buffer=20)
    engine._alerts.clear()

    alert = AutoAlert(
        alert_id="test-win-milestone",
        alert_type="ASYMMETRIC_OPPORTUNITY",
        stage="IGNITED",
        symbol="TRENT",
        exchange="NSE",
        direction="BULLISH",
        headline="TRENT Pocket Pivot",
        summary="Expansion",
        ltp=7000.0,
        trigger_level=6850.0,
        stop_loss=6700.0,
        target_level=7150.0,
        achieved_milestones=[],
        is_live=True,
        environment="LIVE",
    )
    engine._alerts.append(alert)

    # Mock evaluate_alert_targets_and_trailing to return T1_ACHIEVED
    mock_eval = MagicMock()
    mock_eval.new_milestone = "T1_ACHIEVED"
    mock_eval.should_trail = True
    mock_eval.trailing_decision = "TRAIL_DYNAMIC_ATR"
    mock_eval.recommended_stop = 6850.0
    mock_eval.trailing_rationale = "Target 1 achieved"
    mock_eval.locked_profit_pts = 150.0
    mock_eval.locked_profit_pct = 2.2
    mock_eval.target_status = "T1_ACHIEVED"
    mock_eval.r_multiple = 2.0
    mock_eval.pnl_pct = 2.2

    monkeypatch.setattr("engine.auto_alert_engine.evaluate_alert_targets_and_trailing", lambda a, **kw: mock_eval)
    monkeypatch.setattr("engine.auto_alert_engine.AutoAlertEngine._dispatch", lambda self, a: None)
    monkeypatch.setattr("market.quotes.get_ltp", lambda sym: 7000.0)

    updated = engine.check_and_alert_targets_and_trailing(exchanges=["NSE"])
    assert len(updated) == 1
    assert "T1_ACHIEVED" in updated[0].achieved_milestones

    # Check that record_trade_outcome was invoked with WIN_T1
    assert len(recorded_outcomes) == 1
    rec = recorded_outcomes[0]
    assert rec["symbol"] == "TRENT"
    assert rec["outcome"] == "WIN_T1"
    assert rec["realized_rr"] == 2.0


def test_eod_report_truthful_on_zero_alerts(tmp_path, monkeypatch):
    """Verify EOD report generator truthfully reports 0 trades without synthetic demo fallbacks."""
    empty_file = tmp_path / "empty_alerts.json"
    empty_file.write_text("[]", encoding="utf-8")

    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))
    gen = EODReportGenerator(data_file=empty_file)

    report = gen.generate(target_date="2026-09-18")
    assert report.total_alerts == 0
    assert report.ignited_trades == 0
    assert report.win_count == 0
    assert report.loss_count == 0
    assert report.win_rate_pct == 0.0
    assert report.total_realized_r == 0.0
    assert report.star_setups == []
    assert any("Zero capital drawdown" in p for p in report.what_went_well_points)
