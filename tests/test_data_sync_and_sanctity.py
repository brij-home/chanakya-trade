"""
tests/test_data_sync_and_sanctity.py
────────────────────────────────────
Integration tests for Production Data Firewall, DataSyncScheduler,
and maintenance sync API endpoints.
"""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from engine.data_sanctity import (
    is_test_or_mock_payload,
)
from engine.data_sync_scheduler import data_sync_scheduler
from web.api import app


def test_firewall_payload_classification():
    """Verify test/mock payloads are accurately flagged."""
    # Test environment tag
    assert is_test_or_mock_payload({"environment": "TEST"})[0] is True
    assert is_test_or_mock_payload({"environment": "LIVE"})[0] is False

    # Mock flag
    assert is_test_or_mock_payload({"is_mock": True})[0] is True
    assert is_test_or_mock_payload({"is_mock": False})[0] is False

    # Test symbol prefixes
    assert is_test_or_mock_payload({"symbol": "TEST_TCS"})[0] is True
    assert is_test_or_mock_payload({"symbol": "NSE:MOCK_INFY"})[0] is True
    assert is_test_or_mock_payload({"symbol": "RELIANCE"})[0] is False

    # Test alert ID prefixes
    assert is_test_or_mock_payload({"alert_id": "test-12345"})[0] is True
    assert is_test_or_mock_payload({"alert_id": "aa-degenerate-sanitization-001"})[0] is True
    assert is_test_or_mock_payload({"alert_id": "aa-breakout-reliance-20261004"})[0] is False


def test_sync_status_endpoint():
    """Verify GET /api/maintenance/sync-status returns scheduler operational metrics."""
    client = TestClient(app)
    res = client.get("/api/maintenance/sync-status")
    assert res.status_code == 200
    data = res.json()
    assert "running" in data
    assert "is_syncing" in data
    assert "last_eod_sync_date" in data
    assert "last_fundamentals_sync_date" in data
    assert "last_master_sync_date" in data


def test_sync_eod_endpoint_mocked(monkeypatch):
    """Verify POST /api/maintenance/sync-eod executes and responds properly."""
    client = TestClient(app)

    # Mock internal sync_daily_eod to avoid actual network requests during unit testing
    monkeypatch.setattr(
        data_sync_scheduler,
        "sync_daily_eod",
        lambda force=False, universe="NIFTY500": {
            "status": "SUCCESS",
            "universe": universe,
            "symbols_count": 5,
            "mocked": True,
        },
    )

    res = client.post("/api/maintenance/sync-eod?universe=NIFTY500&force=true")
    assert res.status_code == 200
    data = res.json()
    assert data.get("status") == "SUCCESS"
    assert data.get("mocked") is True


def test_sync_fundamentals_endpoint_mocked(monkeypatch):
    """Verify POST /api/maintenance/sync-fundamentals executes and responds properly."""
    client = TestClient(app)

    monkeypatch.setattr(
        data_sync_scheduler,
        "sync_weekly_fundamentals",
        lambda limit=500, force=False: {
            "status": "SUCCESS",
            "fundamentals_saved": 10,
            "forensics_saved": 10,
            "mocked": True,
        },
    )

    res = client.post("/api/maintenance/sync-fundamentals?limit=10&force=true")
    assert res.status_code == 200
    data = res.json()
    assert data.get("status") == "SUCCESS"
    assert data.get("mocked") is True


def test_maintenance_purge_cleans_aged_temp_files(tmp_path, monkeypatch):
    """Verify run_maintenance_purge deletes temporary and backup files older than 24 hours."""
    from engine.maintenance import run_maintenance_purge

    monkeypatch.setattr("engine.maintenance.app_data_dir", lambda: tmp_path)
    monkeypatch.setattr("engine.maintenance.app_data_path", lambda *p: tmp_path.joinpath(*p))

    # Create dummy old temp file (>24h old)
    old_file = tmp_path / "auto_alerts.json.tmp.1234"
    old_file.write_text("old temp data", encoding="utf-8")
    old_mtime = (datetime.now(timezone.utc) - timedelta(hours=36)).timestamp()
    import os

    os.utime(old_file, (old_mtime, old_mtime))

    # Create dummy new temp file (<24h old)
    new_file = tmp_path / "auto_alerts.json.tmp.5678"
    new_file.write_text("new temp data", encoding="utf-8")

    # Run maintenance purge
    rep = run_maintenance_purge()
    assert rep.items_deleted >= 1

    # Old file must be unlinked; new file must be preserved
    assert not old_file.exists()
    assert new_file.exists()
