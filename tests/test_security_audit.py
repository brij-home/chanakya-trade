"""
tests/test_security_audit.py
────────────────────────────
Unit tests for Immutable Security Audit Trail.
"""

from engine.security_audit import record_audit_event, get_audit_logs, verify_audit_integrity


def test_record_audit_event():
    rec = record_audit_event(
        event_type="TEST_EVENT",
        mode="SIMULATE",
        actor="TEST_USER",
        details={"symbol": "NIFTY", "action": "BUY"},
    )
    assert rec.event_id
    assert rec.record_hash
    assert rec.event_type == "TEST_EVENT"


def test_get_audit_logs():
    logs = get_audit_logs(limit=10)
    assert isinstance(logs, list)
    assert len(logs) > 0


def test_verify_audit_integrity():
    res = verify_audit_integrity()
    assert res["valid"] is True
    assert "total_records" in res
