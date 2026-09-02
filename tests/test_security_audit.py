"""
tests/test_security_audit.py
────────────────────────────
Unit tests for Immutable Security Audit Trail.
"""

import sqlite3
import pytest
from engine.security_audit import (
    record_audit_event,
    get_audit_logs,
    verify_audit_integrity,
)


@pytest.fixture(autouse=True)
def isolated_audit_db(tmp_path, monkeypatch):
    """Keep append-only/tamper tests isolated when xdist reorders test cases."""
    db_path = tmp_path / "audit.db"
    monkeypatch.setattr("engine.security_audit._get_db_path", lambda: db_path)
    return db_path


def test_record_audit_event():
    rec = record_audit_event(
        event_type="ORDER_SUBMITTED",
        mode="SIMULATE",
        actor="TEST_USER",
        details={"symbol": "NIFTY", "action": "BUY", "qty": 50},
    )
    assert rec.event_id
    assert rec.record_hash
    assert rec.event_type == "ORDER_SUBMITTED"
    assert rec.mode == "SIMULATE"
    assert rec.actor == "TEST_USER"
    assert "NIFTY" in rec.payload_json


def test_get_audit_logs():
    # Ensure at least one record exists in this worker's database
    rec = record_audit_event(
        event_type="TEST_RETRIEVAL_EVENT",
        mode="OBSERVE",
        actor="SYSTEM_AGENT",
        details={"note": "Testing retrieval"},
    )
    logs = get_audit_logs(limit=10)
    assert isinstance(logs, list)
    assert len(logs) > 0
    assert any(log["event_id"] == rec.event_id for log in logs)

    # Test event_type filter
    filtered = get_audit_logs(limit=10, event_type="TEST_RETRIEVAL_EVENT")
    assert len(filtered) > 0
    assert all(log["event_type"] == "TEST_RETRIEVAL_EVENT" for log in filtered)


def test_verify_audit_integrity():
    # Add a chain of records
    record_audit_event(event_type="EVENT_CHAIN_1", mode="SIMULATE", actor="USER_A")
    record_audit_event(event_type="EVENT_CHAIN_2", mode="SIMULATE", actor="USER_B")

    res = verify_audit_integrity()
    assert res["valid"] is True
    assert "total_records" in res
    assert res["total_records"] >= 2
    assert "latest_hash" in res


def test_verify_audit_integrity_tamper_detection(isolated_audit_db):
    # Record an event
    rec = record_audit_event(
        event_type="TAMPER_TEST_EVENT",
        mode="SIMULATE",
        actor="USER_C",
        details={"value": 100},
    )
    res_before = verify_audit_integrity()
    assert res_before["valid"] is True

    # Intentionally tamper with a record in the database
    with sqlite3.connect(isolated_audit_db) as conn:
        conn.execute(
            "UPDATE security_audit_log SET payload_json = ? WHERE event_id = ?",
            ('{"value": 999999}', rec.event_id),
        )
        conn.commit()

    # Integrity verification must detect the payload signature mismatch
    res_after = verify_audit_integrity()
    assert res_after["valid"] is False
    assert "Tamper detected" in res_after["message"]
    assert res_after["broken_event_id"] == rec.event_id
