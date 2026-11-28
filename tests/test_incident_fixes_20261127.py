"""Regression tests for 2026-11-27 incident RCAs.

Covers:
1. Windows Proactor _call_connection_lost ConnectionResetError(10054) in exc_info
   never elevates to P1 ERROR in TelemetryLogHandler.
2. AutoAlertEngine bounded pool soft-cutoff logs classify as P3 INFO.
3. GUJGASLTD corporate rename resolves canonically to GUJENERGY (NSE:GUJENERGY-EQ).
4. WebSocketManager short-circuits already-subscribed symbols in filter_unsubscribed / subscribe.
5. get_memory_status(stale_ok=True) returns cached status without blocking when refresh lock is held.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from unittest.mock import MagicMock, patch

from analysis.universe import SECTOR_TAXONOMY
from engine.memory_guard import MemoryStatus, get_memory_status
from engine.telemetry import TelemetryLogHandler, derive_priority
from market.instruments import resolve_corporate_alias
from market.symbol_master import resolve_fyers_equity_symbol
from market.websocket import WebSocketManager


def test_proactor_connection_lost_winerror_10054_in_exc_info_suppressed():
    """Windows Proactor client-disconnect socket reset in exc_info must never trigger P1 ERROR."""
    handler = TelemetryLogHandler()
    exc = ConnectionResetError(
        10054, "[WinError 10054] An existing connection was forcibly closed by the remote host"
    )
    record = logging.LogRecord(
        name="asyncio",
        level=logging.ERROR,
        pathname="asyncio/base_events.py",
        lineno=1890,
        msg="Exception in callback _ProactorBasePipeTransport._call_connection_lost()\nhandle: <Handle _ProactorBasePipeTransport._call_connection_lost()>",
        args=(),
        exc_info=(type(exc), exc, None),
    )

    with patch("engine.telemetry.record_event") as mock_record:
        handler.emit(record)
        assert not mock_record.called


def test_winerror_10054_in_exc_info_classified_as_p3():
    """Any logger error carrying WinError 10054 in exc_info must classify as P3 INFO, not P1."""
    handler = TelemetryLogHandler()
    exc = ConnectionResetError(
        10054, "[WinError 10054] An existing connection was forcibly closed by the remote host"
    )
    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.ERROR,
        pathname="uvicorn/server.py",
        lineno=100,
        msg="Socket transport closed unexpectedly",
        args=(),
        exc_info=(type(exc), exc, None),
    )

    with patch("engine.telemetry.record_event") as mock_record:
        handler.emit(record)
        assert mock_record.called
        kwargs = mock_record.call_args.kwargs
        assert kwargs["priority"] == "P3"
        assert kwargs["severity"] == "INFO"


def test_auto_alert_engine_bounded_pool_cutoff_is_p3():
    """Bounded SLA soft cutoffs from AutoAlertEngine symbol pools must classify as P3."""
    msg = "[AutoAlertEngine] Defined risk neutral timeout (10s) reached. Proceeding with 4 candidate alerts."
    assert derive_priority("SYSTEM_LOG", "engine.auto_alert_engine", "WARNING", msg) == "P3"


def test_gujgasltd_canonical_rename_to_gujenergy():
    """GUJGASLTD corporate rename resolves to GUJENERGY and legacy ticker is absent from taxonomy."""
    assert resolve_corporate_alias("GUJGASLTD") == "GUJENERGY"
    assert resolve_corporate_alias("NSE:GUJGASLTD-EQ") == "NSE:GUJENERGY-EQ"
    assert resolve_fyers_equity_symbol("GUJGASLTD") == "NSE:GUJENERGY-EQ"
    assert "GUJGASLTD" not in SECTOR_TAXONOMY["energy"]["symbols"]
    assert "GUJENERGY" in SECTOR_TAXONOMY["energy"]["symbols"]


def test_websocket_manager_short_circuits_already_subscribed():
    """WebSocketManager.filter_unsubscribed and subscribe skip symbols already in _subscribed."""
    mgr = WebSocketManager()
    mgr._ws = MagicMock()
    mgr._connected = True
    mgr._subscribed = {"NSE:RELIANCE-EQ", "NSE:TCS-EQ"}

    assert mgr.filter_unsubscribed(["RELIANCE", "NSE:TCS-EQ"]) == []
    assert mgr.filter_unsubscribed(["RELIANCE", "INFY"]) == ["NSE:INFY-EQ"]

    with patch("market.symbol_master.load_master") as mock_load:
        mgr.subscribe(["RELIANCE", "NSE:TCS-EQ"])
        mock_load.assert_not_called()
        mgr._ws.subscribe.assert_not_called()


def test_get_memory_status_stale_ok_nonblocking_when_refresh_locked():
    """get_memory_status(stale_ok=True) returns cached MemoryStatus immediately if lock is contended."""
    import engine.memory_guard as mg

    cached = MemoryStatus(
        total_ram_mb=16384.0,
        available_ram_mb=8192.0,
        used_ram_pct=50.0,
        process_rss_mb=500.0,
        pressure_level="NORMAL",
        recommendation="Cached",
    )
    old_cache = mg._mem_status_cache
    mg._mem_status_cache = (0.0, cached)  # Expired cache, but valid stale snapshot

    acquired = threading.Event()
    release = threading.Event()

    def _holder():
        with mg._mem_status_refresh_lock:
            acquired.set()
            release.wait(timeout=2.0)

    t = threading.Thread(target=_holder, daemon=True)
    t.start()
    assert acquired.wait(timeout=1.0)
    try:
        t0 = time.perf_counter()
        res = get_memory_status(stale_ok=True)
        elapsed = time.perf_counter() - t0
        assert res is cached
        assert elapsed < 0.2
    finally:
        release.set()
        t.join(timeout=1.0)
        mg._mem_status_cache = old_cache


def test_win_proactor_handler_presence_in_web_api_source():
    """Verify web/api.py installs Windows Proactor exception handler for _call_connection_lost."""
    import pathlib

    src = pathlib.Path("web/api.py").read_text(encoding="utf-8")
    assert "_win_proactor_exception_handler" in src
    assert "_ProactorBasePipeTransport._call_connection_lost" in src
    assert sys.platform  # keeps sys import used
