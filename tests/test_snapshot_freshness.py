"""
tests/test_snapshot_freshness.py
─────────────────────────────────
Unit tests for strict options snapshot observation freshness, skew, and receipt validation (E02).
Verifies:
  1. Old exchange observation (>15s or 1 hour) is rejected with STALE_OBSERVATION_TIME.
  2. Future observation timestamp (> 0.5s skew tolerance) is rejected with FUTURE_OBSERVATION_TIME.
  3. Naive observation timestamp is rejected with NAIVE_OBSERVATION_TIME_REJECTED.
  4. Malformed observation timestamp is rejected with MALFORMED_OBSERVATION_TIME.
  5. Out-of-order receipt preceding observation (>0.5s) is rejected with OUT_OF_ORDER_RECEIPT_PRECEDES_OBSERVATION.
  6. Fresh receipt without exchange observation is accepted as is_receipt_only=True.
  7. Fresh receipt with fresh exchange observation is accepted as is_valid=True and is_receipt_only=False.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import pytest

from market.contract_selection import validate_options_snapshot_provenance


@pytest.fixture
def base_snapshot():
    now = datetime.now(timezone.utc)
    return {
        "as_of": now.isoformat(),
        "received_at": now.isoformat(),
        "receipt_time": now.isoformat(),
        "source": "BROKER_REST",
        "provider": "FYERS",
        "data_state": "LIVE",
        "is_realtime": True,
        "is_market_open": True,
    }


def test_one_hour_old_observation_is_rejected(base_snapshot):
    now = datetime.now(timezone.utc)
    base_snapshot["observation_time"] = (now - timedelta(hours=1)).isoformat()
    res = validate_options_snapshot_provenance(base_snapshot)
    assert res.is_valid is False
    assert "STALE_OBSERVATION_TIME" in res.rejection_reason


def test_twenty_second_old_observation_is_rejected_on_15s_sla(base_snapshot):
    now = datetime.now(timezone.utc)
    base_snapshot["observation_time"] = (now - timedelta(seconds=20.0)).isoformat()
    res = validate_options_snapshot_provenance(base_snapshot, max_age_seconds=15.0)
    assert res.is_valid is False
    assert "STALE_OBSERVATION_TIME" in res.rejection_reason


def test_naive_observation_timestamp_is_rejected(base_snapshot):
    base_snapshot["observation_time"] = "2026-11-01T10:00:00"  # Naive (no timezone)
    res = validate_options_snapshot_provenance(base_snapshot)
    assert res.is_valid is False
    assert "NAIVE_OBSERVATION_TIME_REJECTED" in res.rejection_reason


def test_malformed_observation_timestamp_is_rejected(base_snapshot):
    base_snapshot["observation_time"] = "INVALID_TIMESTAMP_STRING"
    res = validate_options_snapshot_provenance(base_snapshot)
    assert res.is_valid is False
    assert "MALFORMED_OBSERVATION_TIME" in res.rejection_reason


def test_future_observation_timestamp_is_rejected(base_snapshot):
    now = datetime.now(timezone.utc)
    base_snapshot["observation_time"] = (now + timedelta(seconds=5.0)).isoformat()
    res = validate_options_snapshot_provenance(base_snapshot)
    assert res.is_valid is False
    assert "FUTURE_OBSERVATION_TIME" in res.rejection_reason


def test_out_of_order_receipt_precedes_observation(base_snapshot):
    now = datetime.now(timezone.utc)
    base_snapshot["receipt_time"] = (now - timedelta(seconds=10.0)).isoformat()
    base_snapshot["observation_time"] = now.isoformat()  # Observation claimed 10s after receipt!
    res = validate_options_snapshot_provenance(base_snapshot)
    assert res.is_valid is False
    assert "OUT_OF_ORDER_RECEIPT_PRECEDES_OBSERVATION" in res.rejection_reason


def test_fresh_observation_and_receipt_is_valid(base_snapshot):
    now = datetime.now(timezone.utc)
    base_snapshot["observation_time"] = (now - timedelta(seconds=1.0)).isoformat()
    base_snapshot["receipt_time"] = (now - timedelta(seconds=0.5)).isoformat()
    res = validate_options_snapshot_provenance(base_snapshot)
    assert res.is_valid is True
    assert res.is_receipt_only is False
    assert res.observation_time is not None
    assert res.observation_age_seconds is not None
    assert res.observation_age_seconds <= 15.0


def test_fresh_receipt_without_observation_is_receipt_only(base_snapshot):
    base_snapshot.pop("observation_time", None)
    res = validate_options_snapshot_provenance(base_snapshot)
    assert res.is_valid is True
    assert res.is_receipt_only is True
    assert res.observation_time is None
