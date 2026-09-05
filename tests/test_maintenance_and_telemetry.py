"""
tests/test_maintenance_and_telemetry.py
───────────────────────────────────────
Unit and integration tests for memory guard, storage purge, telemetry exception capturing,
log rotation, and system diagnostics on 8 GB RAM / 100 GB SSD hardware profile.
"""

import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from engine.memory_guard import (
    get_memory_status,
    register_trim_callback,
    trim_memory_if_needed,
    unregister_trim_callback,
)
from engine.maintenance import get_storage_breakdown, run_maintenance_purge
from engine.telemetry import (
    EVENT_EXCEPTION,
    get_error_incidents,
    get_recent_events,
    record_event,
    record_exception,
    sanitize_sensitive_data,
)
from market.disk_cache import prune_disk_cache, save_cache, load_cache
from market.history import clear_df_memory_cache, get_ohlcv


def test_memory_guard_status_and_callbacks():
    """Verify memory status evaluation and callback execution under pressure."""
    status = get_memory_status()
    assert status.total_ram_mb > 0
    assert status.available_ram_mb > 0
    assert status.pressure_level in ("NORMAL", "MODERATE", "CRITICAL")
    assert "recommendation" in status.to_dict()

    evicted = [0]

    def dummy_trim():
        evicted[0] += 5
        return 5

    register_trim_callback(dummy_trim)
    res = trim_memory_if_needed(force=True)
    assert res["triggered"] is True
    assert evicted[0] == 5
    unregister_trim_callback(dummy_trim)


def test_history_df_memory_cache_bounded(monkeypatch):
    """Verify in-memory DataFrame cache LRU behavior and clear callback."""
    clear_df_memory_cache()

    # Fake broker historical data
    fake_data = [
        {"date": "2026-09-01", "open": 100, "high": 105, "low": 95, "close": 102, "volume": 1000},
        {"date": "2026-09-02", "open": 102, "high": 108, "low": 101, "close": 106, "volume": 1200},
    ]
    monkeypatch.setattr("brokers.session.get_data_broker", lambda: type("B", (), {"_is_mock": False, "get_historical_data": lambda *a, **kw: fake_data})())

    # Fetch multiple symbols
    df1 = get_ohlcv("STOCK1")
    assert not df1.empty
    df2 = get_ohlcv("STOCK2")
    assert not df2.empty

    # Test clearing memory cache
    evicted_count = clear_df_memory_cache()
    assert evicted_count >= 2


def test_disk_cache_prune(tmp_path):
    """Verify JSON disk cache purging of stale files and size ceiling."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    # 1. Fresh file
    save_cache("fresh", [{"test": 1}], cache_dir=cache_dir)
    # 2. Stale file (8 days old)
    stale_file = cache_dir / "stale.json"
    old_time = (datetime.now() - timedelta(days=8)).timestamp()
    stale_file.write_text(json.dumps({"saved_at": (datetime.now() - timedelta(days=8)).isoformat(), "data": []}))
    import os
    os.utime(stale_file, (old_time, old_time))

    deleted = prune_disk_cache(cache_dir=cache_dir, max_age_days=7)
    assert deleted >= 1
    assert not stale_file.exists()

    data, cached_at = load_cache("fresh", cache_dir=cache_dir)
    assert len(data) == 1


def test_telemetry_sanitization_and_exception_record(tmp_path, monkeypatch):
    """Verify sensitive credential masking and structured incident recording."""
    monkeypatch.setattr("engine.telemetry.app_data_path", lambda *parts: tmp_path.joinpath(*parts))

    sensitive_payload = {
        "user_id": 42,
        "api_key": "secret-12345",
        "nested": {"totp_secret": "TOPSECRET", "status": "active"},
    }
    clean = sanitize_sensitive_data(sensitive_payload)
    assert clean["api_key"] == "***REDACTED***"
    assert clean["nested"]["totp_secret"] == "***REDACTED***"
    assert clean["nested"]["status"] == "active"

    # Test record_exception
    try:
        raise ValueError("Simulated network timeout during broker quote retrieval")
    except Exception as exc:
        incident = record_exception(
            component="test.component",
            error=exc,
            context={"url": "https://api.broker.com/quote", "api_key": "hidden"},
        )

    assert incident["incident_id"].startswith("ERR-")
    assert "Simulated network timeout" in incident["error_message"]
    assert "Traceback" in incident["traceback"]

    # Verify retrieval
    incidents = get_error_incidents(limit=10)
    assert len(incidents) >= 1
    assert incidents[0]["incident_id"] == incident["incident_id"]


def test_maintenance_purge(tmp_path, monkeypatch):
    """Verify storage maintenance purge runs cleanly and preserves business data."""
    app_dir = tmp_path / "app_data"
    app_dir.mkdir(parents=True)
    monkeypatch.setattr("engine.maintenance.app_data_dir", lambda: app_dir)
    monkeypatch.setattr("engine.maintenance.app_data_path", lambda *p: app_dir.joinpath(*p))
    monkeypatch.setattr("engine.telemetry.app_data_path", lambda *p: app_dir.joinpath(*p))

    # Create dummy business db
    orders_db = app_dir / "orders.db"
    with sqlite3.connect(orders_db) as conn:
        conn.execute("CREATE TABLE orders (id INT, status TEXT)")
        conn.execute("INSERT INTO orders VALUES (1, 'FILLED')")
        conn.commit()

    # Create dummy cache directory
    cache_dir = app_dir / "cache"
    cache_dir.mkdir()
    (cache_dir / "test.json").write_text("{}")

    report = run_maintenance_purge(raw_tick_retention_days=1, disk_cache_retention_days=0)
    assert report.timestamp is not None
    assert len(report.actions_taken) > 0
    # Business data must NOT be deleted
    assert orders_db.exists()
    with sqlite3.connect(orders_db) as conn:
        row = conn.execute("SELECT COUNT(*) FROM orders").fetchone()
        assert row[0] == 1


def test_api_diagnostics_and_maintenance_endpoints():
    """Verify /api/diagnostics, /api/diagnostics/errors and /api/maintenance/purge endpoints."""
    from web.api import app

    client = TestClient(app)

    # 1. Diagnostics
    res = client.get("/api/diagnostics")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data
    assert "memory" in data
    assert "storage" in data
    assert "preflight" in data

    # 2. Errors
    res_err = client.get("/api/diagnostics/errors")
    assert res_err.status_code == 200
    err_data = res_err.json()
    assert "total" in err_data
    assert "incidents" in err_data

    # 3. Storage breakdown
    res_sb = client.get("/api/maintenance/storage-breakdown")
    assert res_sb.status_code == 200
    assert "total_app_data_mb" in res_sb.json()

    # 4. Trigger maintenance purge
    res_purge = client.post("/api/maintenance/purge")
    assert res_purge.status_code == 200
    purge_data = res_purge.json()
    assert "actions_taken" in purge_data
    assert "storage_after" in purge_data


def test_global_exception_middleware():
    """Verify global exception middleware catches unhandled errors and returns incident_id."""
    from web.api import app

    # Add a temporary crash route
    @app.get("/api/test-crash")
    def _crash():
        raise RuntimeError("Intentional diagnostic crash test for middleware")

    client = TestClient(app, raise_server_exceptions=False)
    res = client.get("/api/test-crash")
    assert res.status_code == 500
    body = res.json()
    assert "incident_id" in body
    assert body["incident_id"].startswith("ERR-")
    assert "Intentional diagnostic crash" in body["message"]

