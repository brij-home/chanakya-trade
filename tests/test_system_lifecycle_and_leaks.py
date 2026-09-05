"""
tests/test_system_lifecycle_and_leaks.py
────────────────────────────────────────
Institutional-grade test suite to verify:
- Complete SQLite connection closure without lingering handles or locked WAL files
- TickArchive lifecycle, background worker health, and clean shutdown
- Broker HTTP client session termination on logout/close
- In-memory cache bounds and LRU eviction in chat sessions
- ThreadPoolExecutor exception handling and process reaping
"""

import os
import sqlite3
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_analysis_cache_connection_closed(tmp_path):
    """Verify AnalysisCache closes connections immediately after operations."""
    from engine.analysis_cache import AnalysisCache

    db_path = tmp_path / "test_cache.db"
    cache = AnalysisCache(db_path=db_path)

    # Perform read and write
    cache.save_macro("test_key", {"data": 123}, ttl_minutes=5)
    val = cache.get_macro("test_key")
    assert val == {"data": 123}

    # Verify that we can write to the database independently with timeout without being blocked
    with sqlite3.connect(str(db_path), timeout=1.0) as test_conn:
        test_conn.execute("VACUUM")
        test_conn.commit()


def test_risk_limits_connection_closed(tmp_path, monkeypatch):
    """Verify RiskLimits closes SQLite connections after checks and trade recordings."""
    from engine.risk_limits import RiskLimits

    db_path = tmp_path / "test_risk.db"
    monkeypatch.setenv("RISK_DB_PATH", str(db_path))

    rl = RiskLimits()
    # Check shouldn't raise
    rl.check("INFY", "BUY", 10, 1500.0)
    rl.record_trade("INFY", "BUY", 10, 1500.0, pnl=50.0)

    # Verify database can be opened with exclusive lock immediately
    with sqlite3.connect(str(db_path), timeout=1.0) as test_conn:
        test_conn.execute("VACUUM")
        test_conn.commit()


def test_persona_tracker_connection_closed(tmp_path):
    """Verify PersonaTracker closes SQLite connections after recording."""
    from agent.persona_tracker import PersonaTrackerEngine

    db_path = tmp_path / "test_persona.db"
    tracker = PersonaTrackerEngine(db_path=db_path)

    call_id = tracker.record_recommendation(
        persona_id="minervini",
        symbol="TCS",
        conviction_score=85.0,
        verdict="BUY",
        entry_price=4000.0,
        target_1=4300.0,
        stop_loss=3900.0,
    )
    assert call_id > 0

    # Verify independent vacuum succeeds without locks
    with sqlite3.connect(str(db_path), timeout=1.0) as test_conn:
        test_conn.execute("VACUUM")
        test_conn.commit()


def test_security_audit_connection_closed(tmp_path, monkeypatch):
    """Verify SecurityAudit closes SQLite connection after record_audit_event."""
    from engine import security_audit

    db_path = tmp_path / "test_audit.db"
    monkeypatch.setattr(security_audit, "_get_db_path", lambda: db_path)

    rec = security_audit.record_audit_event("TEST_EVENT", mode="OBSERVE", actor="TEST_AGENT")
    assert rec.event_id is not None

    with sqlite3.connect(str(db_path), timeout=1.0) as test_conn:
        test_conn.execute("VACUUM")
        test_conn.commit()


def test_instrument_master_connection_closed(tmp_path, monkeypatch):
    """Verify InstrumentMaster closes connections on upsert and lookup."""
    from market import instrument_master

    db_path = tmp_path / "test_instruments.db"
    monkeypatch.setattr(instrument_master, "_db_path", lambda: db_path)

    instrument_master.upsert_verified_contract(
        lookup_symbol="NIFTY26MAR24000CE",
        provider="fyers",
        provider_symbol="NSE:NIFTY26MAR24000CE",
        provider_token="12345",
        exchange="NFO",
        segment="OPTIONS",
        lot_size=65,
        tick_size=0.05,
    )
    contract = instrument_master.get_verified_contract("NIFTY26MAR24000CE")
    assert contract is not None
    assert contract["lot_size"] == 65

    with sqlite3.connect(str(db_path), timeout=1.0) as test_conn:
        test_conn.execute("VACUUM")
        test_conn.commit()


def test_eod_store_connection_closed(tmp_path, monkeypatch):
    """Verify EODStore closes connections on snapshot save and load."""
    from market import eod_store

    db_path = tmp_path / "test_eod.db"
    monkeypatch.setattr(eod_store, "_db_path", lambda: db_path)

    snap_id = eod_store.save_eod_snapshot(
        canonical_instrument_id="NSE:INFY",
        provider="yfinance",
        provider_symbol="INFY.NS",
        as_of_date="2026-09-05",
        rows=[{"date": "2026-09-05", "close": 1500.0}],
    )
    assert snap_id is not None

    loaded = eod_store.load_eod_snapshot("NSE:INFY", as_of_date="2026-09-05")
    assert loaded is not None

    with sqlite3.connect(str(db_path), timeout=1.0) as test_conn:
        test_conn.execute("VACUUM")
        test_conn.commit()


def test_tick_archive_lifecycle(tmp_path, monkeypatch):
    """Verify TickArchive background worker starts, handles time cleanly, and stops."""
    from market import tick_store
    from market.data_events import MarketDataEvent

    db_path = tmp_path / "test_ticks.db"
    monkeypatch.setattr(tick_store, "_db_path", lambda: db_path)

    archive = tick_store.TickArchive(max_queue_size=100)
    event = MarketDataEvent(
        canonical_instrument_id="NSE:TCS",
        provider="mock",
        provider_symbol="TCS",
        source="TEST",
        data_state="LIVE",
        last_price=4100.0,
    )

    archive.record(event)
    assert archive._started is True
    # Allow background thread a moment to process the queue
    time.sleep(0.3)

    # Clean shutdown
    archive.stop(timeout=1.5)
    assert archive._started is False
    assert archive._worker_thread is None

    # Verify rows were written and database is clean
    with sqlite3.connect(str(db_path), timeout=1.0) as conn:
        count = conn.execute("SELECT COUNT(*) FROM raw_market_ticks").fetchone()[0]
        assert count == 1
        conn.execute("VACUUM")


def test_broker_session_close_all():
    """Verify close_all_brokers properly stops websockets and closes clients."""
    from brokers import session

    mock_broker_1 = MagicMock()
    mock_broker_2 = MagicMock()

    session._brokers["mock1"] = mock_broker_1
    session._brokers["mock2"] = mock_broker_2

    session.close_all_brokers()

    mock_broker_1.close.assert_called_once()
    mock_broker_2.close.assert_called_once()
    assert len(session._brokers) == 0


def test_chat_followup_lru_and_history_bounded():
    """Verify _chat_sessions is bounded at 200 sessions and message history is rolling."""
    from web.skills import _chat_sessions

    # Prime with dummy entries
    _chat_sessions.clear()
    for i in range(200):
        _chat_sessions[f"session_{i}"] = {"system": "sys", "history": []}

    assert len(_chat_sessions) == 200

    # Adding a 201st session should evict the oldest
    from web.skills import analyze_followup, AnalyzeFollowupRequest

    req = AnalyzeFollowupRequest(
        symbol="TCS",
        exchange="NSE",
        question="How is revenue growth?",
        context={"analysts": [], "synthesis_text": "Good", "report": "Test report"},
    )

    with patch("agent.core.get_provider") as mock_get_provider:
        mock_provider = MagicMock()
        mock_provider.chat.return_value = "Revenue grew 8%."
        mock_get_provider.return_value = mock_provider

        import asyncio

        loop = asyncio.new_event_loop()
        try:
            res = loop.run_until_complete(analyze_followup(req))
            assert res["status"] == "ok"
        finally:
            loop.close()

    # Total sessions must still not exceed 200
    assert len(_chat_sessions) <= 200
    # Oldest session should have been popped
    assert "session_0" not in _chat_sessions


def test_sqlite_connection_pool_concurrency_and_reuse(tmp_path):
    """Verify SQLiteConnectionPool handles concurrent acquisition, reuse, and teardown."""
    import concurrent.futures
    from engine.db_pool import SQLiteConnectionPool

    db_file = tmp_path / "pooled_test.db"
    pool = SQLiteConnectionPool(str(db_file), max_conns=3, timeout=5.0)

    # Initialize schema
    with pool.acquire() as conn:
        conn.execute("CREATE TABLE test (id INT PRIMARY KEY, val TEXT)")

    # Test concurrent acquisition across 10 tasks on 3 pooled connections
    def insert_worker(worker_id):
        with pool.acquire() as conn:
            conn.execute("INSERT INTO test (id, val) VALUES (?, ?)", (worker_id, f"val_{worker_id}"))
        return worker_id

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(insert_worker, range(10)))

    assert len(results) == 10

    with pool.acquire() as conn:
        cursor = conn.execute("SELECT count(*) FROM test")
        assert cursor.fetchone()[0] == 10

    # Ensure close cleans up all connections
    pool.close()
    assert pool._closed is True
    # Subsequent acquire should raise RuntimeError
    try:
        with pool.acquire() as conn:
            pass
        assert False, "Should have raised RuntimeError"
    except RuntimeError:
        pass


def test_shared_http_pool_lifecycle():
    """Verify market.http_pool singleton creation, configuration, and teardown."""
    from market.http_pool import get_shared_client, get_nse_client, close_http_pools

    # Reset any existing pool
    close_http_pools()

    client = get_shared_client()
    assert client is not None
    assert not client.is_closed
    assert client._transport._pool._max_keepalive_connections == 20
    assert client._transport._pool._max_connections == 50

    # Calling again returns same instance
    assert get_shared_client() is client

    # Close pools
    close_http_pools()
    assert client.is_closed


def test_analysis_cache_and_instrument_master_pool_close(tmp_path):
    """Verify analysis_cache.close() and instrument_master.close_db() tear down cleanly."""
    from engine.analysis_cache import AnalysisCache
    from market import instrument_master

    cache_db = tmp_path / "test_cache_close.db"
    cache = AnalysisCache(db_path=cache_db)
    cache.save_macro("test_key", {"val": 123}, ttl_minutes=5)
    cached = cache.get_macro("test_key")
    assert cached == {"val": 123}

    # Close cache pool
    cache.close()
    assert cache._pool._closed is True

    # Test instrument master close_db
    instrument_master.close_db()
    assert instrument_master._POOL is None
