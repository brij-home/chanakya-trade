"""
tests/test_nightly_chain.py
Unit tests for the post-market nightly chain (mover autopsy -> SNR recalibration -> drift check).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from engine.nightly_chain import run_nightly_post_market_chain, schedule_nightly_chain


def test_run_nightly_post_market_chain_force():
    """Verify force=True executes all 3 stages without raising exceptions."""
    with patch("engine.mover_autopsy.mover_autopsy_engine.perform_daily_autopsy") as mock_autopsy:
        mock_rep = MagicMock()
        mock_rep.to_dict.return_value = {"date": "2026-09-22", "gainers": 5, "losers": 2}
        mock_rep.factor_snr = {"volume_dry_up": 3.2, "squeeze_coiling": 2.8}
        mock_autopsy.return_value = mock_rep

        res = run_nightly_post_market_chain(force=True, send_telegram=False)

        assert res is not None
        assert res["status"] == "COMPLETED"
        assert "stage1_autopsy" in res
        assert "stage2_snr" in res
        assert "stage2b_alert_postmortems" in res
        assert "stage3_drift" in res
        assert mock_autopsy.called


def test_alert_postmortem_runner_execution():
    """Verify alert post-mortem runner runs on simulated alerts."""
    from engine.alert_postmortem_runner import run_eod_alert_postmortems
    from unittest.mock import MagicMock

    mock_engine = MagicMock()
    mock_alert = MagicMock()
    mock_alert.alert_id = "test-alert-1"
    mock_alert.symbol = "RELIANCE"
    mock_alert.is_invalidated = True
    mock_alert.achieved_milestones = []
    mock_alert.created_at = "2026-09-23 10:00:00"
    mock_alert.entry_price = 2800.0
    mock_alert.ltp = 2750.0
    mock_alert.r_multiple = -1.0
    mock_alert.matched_factors = ["volume_dry_up"]
    mock_alert.exchange = "NSE"
    mock_alert.alert_type = "MOMENTUM"

    mock_engine.get_alerts.return_value = [mock_alert]

    res = run_eod_alert_postmortems(auto_engine=mock_engine, force=True)
    assert res["status"] == "COMPLETED"
    assert res["processed_count"] == 1
    assert res["post_mortems_conducted"] == 1
    assert res["outcomes_recorded"] == 1


def test_schedule_nightly_chain():
    """Verify schedule_nightly_chain starts daemon thread or returns True."""
    with patch("threading.Thread") as mock_thread:
        mock_inst = MagicMock()
        mock_thread.return_value = mock_inst

        schedule_nightly_chain()

        assert mock_thread.called
        assert mock_inst.start.called
