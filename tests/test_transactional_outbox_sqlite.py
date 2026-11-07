"""
tests/test_transactional_outbox_sqlite.py
─────────────────────────────────────────
Verifies institutional ACID transactional outbox behavior:
1. Single-transaction atomic commit: alert upsert + outbox staging.
2. Unique constraint on (alert_id, event_version, channel) with idempotent replay and conflict rejection.
3. Multi-worker claim/leasing: concurrent isolation and lease expiry reclamation.
4. Worker identity verification: non-claiming workers cannot mutate claimed entries.
5. Ambiguous delivery detection and explicit safe recovery without blind duplicate dispatch.
6. Archival of terminal outbox entries.
"""

from __future__ import annotations

import time
import pytest
from pathlib import Path

from engine.sqlite_store import SQLiteAlertStore


@pytest.fixture
def store(tmp_path: Path) -> SQLiteAlertStore:
    db_path = tmp_path / "test_outbox.db"
    return SQLiteAlertStore(db_path=db_path)


def test_atomic_save_alert_with_outbox(store: SQLiteAlertStore):
    alert_dict = {
        "alert_id": "aa-momentum-nifty-20261101",
        "symbol": "NIFTY",
        "exchange": "NSE",
        "segment": "OPTIONS",
        "alert_type": "MOMENTUM",
        "stage": "CONFIRMED",
        "direction": "BULLISH",
        "ltp": 24500.0,
        "trigger_level": 24500.0,
        "target_level": 24650.0,
        "stop_loss": 24420.0,
        "confidence": 0.85,
        "version": 1,
    }

    outbox_entries = [
        {"channel": "TELEGRAM", "payload": {"headline": "Nifty Bullish Momentum"}},
        {"channel": "SSE", "payload": {"headline": "Nifty Bullish Momentum"}},
    ]

    alert_id, staged_ids = store.save_alert_with_outbox(alert_dict, outbox_entries)
    assert alert_id == "aa-momentum-nifty-20261101"
    assert len(staged_ids) == 2

    # Verify alert exists in database
    saved_alert = store.get_alert(alert_id)
    assert saved_alert is not None
    assert saved_alert["symbol"] == "NIFTY"

    # Verify outbox entries exist and are PENDING
    pending = store.get_pending_outbox_entries()
    assert len(pending) == 2
    channels = {e["channel"] for e in pending}
    assert channels == {"TELEGRAM", "SSE"}


def test_unique_constraint_alert_version_channel(store: SQLiteAlertStore):
    alert_id = "aa-orb-banknifty-20261101"
    payload1 = {"msg": "Breakout above 52000"}

    # 1. Initial staging
    oid1 = store.stage_outbox_entry(alert_id, "TELEGRAM", payload1, event_version=1)
    assert oid1 is not None

    # 2. Identical staging is idempotent and returns same outbox_id
    oid2 = store.stage_outbox_entry(alert_id, "TELEGRAM", payload1, event_version=1)
    assert oid2 == oid1

    # 3. Conflicting payload for same (alert_id, version, channel) raises ValueError
    payload_conflict = {"msg": "Breakout below 51800"}
    with pytest.raises(ValueError, match="Conflicting outbox delivery intent"):
        store.stage_outbox_entry(alert_id, "TELEGRAM", payload_conflict, event_version=1)

    # 4. Same alert but higher event_version is allowed
    oid_v2 = store.stage_outbox_entry(alert_id, "TELEGRAM", payload_conflict, event_version=2)
    assert oid_v2 != oid1


def test_worker_claim_lease_concurrency(store: SQLiteAlertStore):
    alert_id = "aa-scalp-nifty-20261101"
    store.stage_outbox_entry(alert_id, "TELEGRAM", {"test": 1})

    # Worker 1 claims with a short 1.0s lease
    claimed_w1 = store.claim_pending_outbox_entries(worker_id="worker-1", lease_seconds=1.0)
    assert len(claimed_w1) == 1
    assert claimed_w1[0]["status"] == "CLAIMED"
    assert claimed_w1[0]["claimed_by"] == "worker-1"

    # Worker 2 attempts to claim immediately: gets 0 entries (isolation)
    claimed_w2 = store.claim_pending_outbox_entries(worker_id="worker-2", lease_seconds=1.0)
    assert len(claimed_w2) == 0

    # Wait for lease to expire
    time.sleep(1.1)

    # Worker 2 can now claim the expired lease
    claimed_w2_after = store.claim_pending_outbox_entries(worker_id="worker-2", lease_seconds=1.0)
    assert len(claimed_w2_after) == 1
    assert claimed_w2_after[0]["claimed_by"] == "worker-2"
    assert claimed_w2_after[0]["attempts"] == 2


def test_worker_identity_verification(store: SQLiteAlertStore):
    alert_id = "aa-auth-test-20261101"
    oid = store.stage_outbox_entry(alert_id, "TELEGRAM", {"data": True})

    store.claim_pending_outbox_entries(worker_id="legit-worker", lease_seconds=10.0)

    # Impostor worker cannot dispatch or acknowledge
    with pytest.raises(PermissionError, match="cannot dispatch entry claimed by legit-worker"):
        store.mark_outbox_dispatched(oid, worker_id="impostor-worker")

    with pytest.raises(PermissionError, match="cannot acknowledge entry claimed by legit-worker"):
        store.mark_outbox_acknowledged(oid, worker_id="impostor-worker")

    # Legit worker succeeds
    assert store.mark_outbox_dispatched(oid, worker_id="legit-worker") is True
    assert store.mark_outbox_acknowledged(oid, worker_id="legit-worker") is True

    entry = store.get_outbox_entry(oid)
    assert entry["status"] == "ACKNOWLEDGED"


def test_ambiguous_dispatch_recovery(store: SQLiteAlertStore):
    alert_id = "aa-ambiguous-test-20261101"
    oid = store.stage_outbox_entry(alert_id, "TELEGRAM", {"alert": 1}, max_attempts=3)

    # Worker claims and dispatches with 1.0 second lease
    store.claim_pending_outbox_entries(worker_id="worker-1", lease_seconds=10.0)
    store.mark_outbox_dispatched(oid, worker_id="worker-1", lease_seconds=1.0)

    # Immediately, entry is DISPATCHED and lease has not expired
    ambiguous0 = store.get_ambiguous_outbox_entries()
    assert len(ambiguous0) == 0

    # Wait for ambiguous lease timeout
    time.sleep(1.1)

    # Now entry is detected as ambiguous (dispatched without ack)
    ambiguous1 = store.get_ambiguous_outbox_entries()
    assert len(ambiguous1) == 1
    assert ambiguous1[0]["outbox_id"] == oid

    # Safely reclaim for retry
    assert store.reclaim_ambiguous_entry(oid, retry=True, error="Telegram API timeout 504") is True
    entry_reclaimed = store.get_outbox_entry(oid)
    assert entry_reclaimed["status"] == "FAILED_RETRY"
    assert "Telegram API timeout 504" in entry_reclaimed["last_error"]


def test_outbox_archival(store: SQLiteAlertStore):
    alert_id = "aa-archive-test-20261101"
    oid = store.stage_outbox_entry(alert_id, "SSE", {"msg": "done"})

    store.mark_outbox_dispatched(oid)
    store.mark_outbox_acknowledged(oid)

    # Set updated_at to 10 days in the past
    with store._lock, store._get_connection() as conn:
        conn.execute(
            "UPDATE alert_outbox SET updated_at = '2026-10-01T00:00:00' WHERE outbox_id = ?;",
            (oid,),
        )
        conn.commit()

    # Archiving entries older than 7 days should find and archive our entry
    count = store.archive_completed_outbox(older_than_days=7)
    assert count == 1
    entry = store.get_outbox_entry(oid)
    assert entry["archived"] == 1
