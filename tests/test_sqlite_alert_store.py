"""
tests/test_sqlite_alert_store.py
─────────────────────────────────
Verification suite for SQLite WAL Alert Store and AutoAlertEngine persistence integration.
"""

from __future__ import annotations

import pytest

from engine.alert_model import AutoAlert
from engine.sqlite_store import SQLiteAlertStore


def _make_alert(
    alert_id: str,
    symbol: str,
    alert_type: str = "ORB",
    ltp: float = 100.0,
    confidence: int = 80,
) -> AutoAlert:
    return AutoAlert(
        alert_id=alert_id,
        alert_type=alert_type,
        stage="ACTIONABLE",
        symbol=symbol,
        exchange="NSE",
        direction="BULLISH",
        headline=f"🟢 {symbol} {alert_type} Test",
        summary=f"Summary for {symbol}",
        ltp=ltp,
        trigger_level=ltp,
        target_level=round(ltp * 1.03, 1),
        stop_loss=round(ltp * 0.98, 1),
        confidence=confidence,
    )


@pytest.fixture
def temp_store(tmp_path):
    db_file = tmp_path / "test_alerts.db"
    return SQLiteAlertStore(db_path=db_file)


def test_sqlite_store_save_and_retrieve_alert(temp_store):
    alert = _make_alert("aa-orb-RELIANCE-20261002", "RELIANCE", ltp=2950.0, confidence=85)
    temp_store.save_alert(alert)

    retrieved = temp_store.get_alert("aa-orb-RELIANCE-20261002")
    assert retrieved is not None
    assert retrieved["alert_id"] == "aa-orb-RELIANCE-20261002"
    assert retrieved["symbol"] == "RELIANCE"
    assert retrieved["ltp"] == 2950.0
    assert retrieved["confidence"] == 85


def test_sqlite_store_batch_save(temp_store):
    alerts = [
        _make_alert(f"aa-test-SYM{i}-20261002", f"SYM{i}", alert_type="GAMMA_BLAST", ltp=100.0 * i)
        for i in range(1, 11)
    ]

    saved = temp_store.save_alerts_batch(alerts)
    assert saved == 10

    results = temp_store.get_alerts(session_date="20261002", limit=20)
    assert len(results) == 10


def test_sqlite_store_update_status(temp_store):
    alert = _make_alert("aa-status-TCS-20261002", "TCS", ltp=3900.0, confidence=88)
    temp_store.save_alert(alert)

    ok = temp_store.update_alert_status("aa-status-TCS-20261002", "INVALIDATED", ltp=3850.0)
    assert ok is True

    updated = temp_store.get_alert("aa-status-TCS-20261002")
    assert updated["status"] == "INVALIDATED"
    assert updated["is_invalidated"] is True
    assert updated["ltp"] == 3850.0


def test_sqlite_store_filtering(temp_store):
    temp_store.save_alert(_make_alert("aa-filter-INFY-20261002", "INFY", ltp=1850.0))
    temp_store.save_alert(_make_alert("aa-filter-WIPRO-20261002", "WIPRO", ltp=520.0))

    infy_alerts = temp_store.get_alerts(symbol="INFY")
    assert len(infy_alerts) == 1
    assert infy_alerts[0]["symbol"] == "INFY"
