"""
tests/test_calibration_runner.py
────────────────────────────────
Unit tests for background walk-forward model calibration manager,
concurrency mutex safety, staleness detection, and sidecar endpoints.
"""

from __future__ import annotations

import json
from unittest.mock import patch
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi.testclient import TestClient

from engine.calibration_runner import CalibrationRunner
from web.api import app

IST = ZoneInfo("Asia/Kolkata")


def test_calibration_runner_initial_status():
    """Verify initial status and disk metadata loading."""
    runner = CalibrationRunner()
    st = runner.get_status()
    assert st.state in ("IDLE", "COMPLETED", "RUNNING")
    assert isinstance(st.to_dict(), dict)


def test_calibration_runner_staleness_detection(tmp_path):
    """Verify staleness detection for missing, old, or prior-date calibration files."""
    runner = CalibrationRunner()

    # 1. Missing file -> stale
    with patch("pathlib.Path.home", return_value=tmp_path):
        assert runner.is_calibration_stale() is True

    # 2. File with today's date -> fresh
    cal_dir = tmp_path / ".trading_platform" / "calibration"
    cal_dir.mkdir(parents=True, exist_ok=True)
    cal_file = cal_dir / "index_calibration.json"

    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    with open(cal_file, "w", encoding="utf-8") as f:
        json.dump({"version": "1.1.0", "generated_at": now_str}, f)

    with patch("pathlib.Path.home", return_value=tmp_path):
        assert runner.is_calibration_stale() is False

    # 3. File from yesterday's date -> stale
    yesterday_str = "2026-10-29 18:00:00 IST"
    with open(cal_file, "w", encoding="utf-8") as f:
        json.dump({"version": "1.1.0", "generated_at": yesterday_str}, f)

    with patch("pathlib.Path.home", return_value=tmp_path):
        assert runner.is_calibration_stale() is True


def test_calibration_runner_concurrency_mutex():
    """Verify runner rejects concurrent runs when already RUNNING."""
    runner = CalibrationRunner()
    runner._status.state = "RUNNING"

    started, msg = runner.trigger_calibration_async()
    assert started is False
    assert "already" in msg.lower()


def test_calibration_runner_auto_trigger_premarket():
    """Verify auto-trigger initiates calibration when stale."""
    runner = CalibrationRunner()
    with patch.object(runner, "is_calibration_stale", return_value=True):
        with patch.object(runner, "trigger_calibration_async", return_value=(True, "started")):
            res = runner.auto_trigger_premarket_calibration()
            assert res is True

    with patch.object(runner, "is_calibration_stale", return_value=False):
        res = runner.auto_trigger_premarket_calibration()
        assert res is False


def test_calibration_sidecar_endpoints():
    """Verify /api/calibration/status and /api/calibration/run endpoints."""
    client = TestClient(app)

    # Status endpoint
    r_stat = client.get("/api/calibration/status")
    assert r_stat.status_code == 200
    stat_data = r_stat.json()
    assert stat_data["status"] == "success"
    assert "data" in stat_data
    assert "is_stale" in stat_data

    # Trigger endpoint
    with patch(
        "engine.calibration_runner.calibration_runner.trigger_calibration_async",
        return_value=(True, "started"),
    ):
        r_run = client.post("/api/calibration/run")
        assert r_run.status_code == 200
        run_data = r_run.json()
        assert run_data["status"] == "RUNNING"
