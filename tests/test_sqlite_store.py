"""
tests/test_sqlite_store.py
──────────────────────────
Unit tests for SQLiteAlertStore with WAL mode.
Verifies WAL pragma settings, atomic UPSERTs, query filtering, and legacy JSON sync.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import pytest

from engine.alert_model import AutoAlert
from engine.sqlite_store import SQLiteAlertStore


@pytest.fixture
def temp_store(tmp_path):
    """Provides isolated SQLiteAlertStore with temporary database file."""
    db_file = tmp_path / "test_ledger.db"
    return SQLiteAlertStore(db_path=db_file)


def test_sqlite_store_wal_pragmas(temp_store):
    """Verify WAL mode and performance pragmas are set."""
    conn = temp_store._get_connection()
    try:
        row = conn.execute("PRAGMA journal_mode;").fetchone()
        assert row[0].upper() == "WAL"
    finally:
        conn.close()


def test_save_and_retrieve_alert(temp_store):
    """Verify saving AutoAlert and retrieving it by alert_id."""
    alert = AutoAlert(
        alert_id="aa-gamma-blast-nifty-20260926",
        symbol="NIFTY",
        exchange="NSE",
        segment="NFO",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        direction="BULLISH",
        headline="NIFTY Gamma Blast Ignited",
        summary="Call unwinding observed at 24200.",
        ltp=24220.0,
        trigger_level=24200.0,
        target_level=24350.0,
        stop_loss=24150.0,
        confidence=85.0,
    )

    temp_store.save_alert(alert)

    retrieved = temp_store.get_alert("aa-gamma-blast-nifty-20260926")
    assert retrieved is not None
    assert retrieved["symbol"] == "NIFTY"
    assert retrieved["alert_type"] == "GAMMA_BLAST"
    assert retrieved["ltp"] == 24220.0
    assert retrieved["stage"] == "IGNITED"


def test_atomic_upsert_update(temp_store):
    """Verify upsert updates existing record without duplicating rows."""
    alert = AutoAlert(
        alert_id="aa-orb-tcs-20260926",
        symbol="TCS",
        exchange="NSE",
        segment="EQUITY",
        alert_type="ORB",
        stage="EARLY_WARNING",
        direction="BULLISH",
        headline="TCS ORB Breakout Coiling",
        summary="Testing 4200 pivot.",
        ltp=4198.0,
        trigger_level=4200.0,
        target_level=4250.0,
        stop_loss=4170.0,
    )

    temp_store.save_alert(alert)

    # Update LTP and stage
    alert.stage = "IGNITED"
    alert.ltp = 4205.0
    temp_store.save_alert(alert)

    alerts = temp_store.get_alerts(symbol="TCS")
    assert len(alerts) == 1
    assert alerts[0]["stage"] == "IGNITED"
    assert alerts[0]["ltp"] == 4205.0


def test_update_alert_status(temp_store):
    """Verify status update to INVALIDATED."""
    alert = AutoAlert(
        alert_id="aa-circuit-tatamotors-20260926",
        symbol="TATAMOTORS",
        exchange="NSE",
        segment="EQUITY",
        alert_type="CIRCUIT_WARNING",
        stage="EARLY_WARNING",
        direction="BULLISH",
        headline="TATAMOTORS Approaching Circuit",
        summary="0.5% below UC ceiling.",
        ltp=995.0,
        trigger_level=1000.0,
        target_level=1000.0,
        stop_loss=980.0,
    )

    temp_store.save_alert(alert)
    ok = temp_store.update_alert_status("aa-circuit-tatamotors-20260926", "INVALIDATED", ltp=975.0)
    assert ok is True

    record = temp_store.get_alert("aa-circuit-tatamotors-20260926")
    assert record["status"] == "INVALIDATED"
    assert record["is_invalidated"] is True
    assert record["ltp"] == 975.0


def test_sync_and_export_legacy_json(temp_store, tmp_path):
    """Verify bidirectional sync with legacy JSON files."""
    json_path = tmp_path / "legacy_alerts.json"
    legacy_data = [
        {
            "alert_id": "aa-gamma-blast-banknifty-20260926",
            "symbol": "BANKNIFTY",
            "exchange": "NSE",
            "segment": "NFO",
            "alert_type": "GAMMA_BLAST",
            "stage": "IGNITED",
            "direction": "BULLISH",
            "headline": "BANKNIFTY Blast",
            "summary": "Short squeeze.",
            "ltp": 52100.0,
            "trigger_level": 52000.0,
            "target_level": 52400.0,
            "stop_loss": 51850.0,
            "confidence": 90.0,
        }
    ]
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(legacy_data, f)

    count = temp_store.sync_from_legacy_json(json_path)
    assert count == 1

    retrieved = temp_store.get_alert("aa-gamma-blast-banknifty-20260926")
    assert retrieved is not None
    assert retrieved["symbol"] == "BANKNIFTY"

    # Export to new json
    export_path = tmp_path / "exported.json"
    exported_count = temp_store.export_to_legacy_json(export_path)
    assert exported_count == 1
    assert export_path.exists()
