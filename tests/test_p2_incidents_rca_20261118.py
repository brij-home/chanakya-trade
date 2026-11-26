"""
tests/test_p2_incidents_rca_20261118.py
────────────────────────────────────────
Regression & Invariant verification for 18-Nov-2026 P2 incidents:
1. FyersDataSocket 'sf|bse_fo|1165066' KeyError on in-flight ticks after unsubscription.
2. websocket [WinError 10054] remote host closure - goodbye classified as routine P3.
3. brokers.fyers Rate gate denied permit for DEPTH_CHAIN optionchain handled as P3 rate pacing.
4. AutoAlertEngine derivative scanners enforce market hours (09:16 - 15:25 IST) off-market guard.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest
import pytz

from engine.telemetry import TelemetryLogHandler, derive_priority
from market.fyers_socket_patch import _SafeSymbolTokenDict

IST = pytz.timezone("Asia/Kolkata")


# ── 1. FyersDataSocket In-Flight KeyError Guard ──────────────────────────────


def test_safe_symbol_token_dict_prevents_keyerror_on_popped_tokens():
    """Verify _SafeSymbolTokenDict safely returns tombstoned symbol on popped tokens instead of KeyError."""
    d = _SafeSymbolTokenDict()
    d["sf|bse_fo|1165066"] = "BSE:SENSEX26NOV78000CE"

    # Pre-unsubscription lookup
    assert d["sf|bse_fo|1165066"] == "BSE:SENSEX26NOV78000CE"
    assert len(d) == 1

    # Unsubscription pops token from active capacity
    popped = d.pop("sf|bse_fo|1165066")
    assert popped == "BSE:SENSEX26NOV78000CE"
    assert len(d) == 0
    assert "sf|bse_fo|1165066" not in d

    # In-flight packet arrives after unsubscription: MUST NOT raise KeyError!
    in_flight_sym = d["sf|bse_fo|1165066"]
    assert in_flight_sym == "BSE:SENSEX26NOV78000CE"

    # Completely unknown token returns key itself, never raises KeyError
    assert d["unknown_token_999"] == "unknown_token_999"


def test_fyers_data_socket_property_descriptor():
    """Verify FyersDataSocket.symbol_token property wraps dicts and preserves tombstones across re-assignments."""
    pytest.importorskip("fyers_apiv3")
    from fyers_apiv3.FyersWebsocket import data_ws

    dummy = MagicMock(spec=data_ws.FyersDataSocket)
    # Clear any instance-level mock overrides to test class descriptor
    type(dummy).symbol_token = data_ws.FyersDataSocket.symbol_token

    # Direct assignment inside SDK
    dummy.symbol_token = {"sf|bse_fo|1165066": "BSE:SENSEX26NOV78000CE"}
    assert isinstance(dummy.symbol_token, _SafeSymbolTokenDict)
    assert dummy.symbol_token["sf|bse_fo|1165066"] == "BSE:SENSEX26NOV78000CE"

    # Pop on unsubscription
    dummy.symbol_token.pop("sf|bse_fo|1165066")

    # SDK resets symbol_token = {} on reconnect
    dummy.symbol_token = {}
    assert isinstance(dummy.symbol_token, _SafeSymbolTokenDict)
    # Tombstone is preserved across resets!
    assert dummy.symbol_token["sf|bse_fo|1165066"] == "BSE:SENSEX26NOV78000CE"


# ── 2. WebSocket WinError 10054 Remote Closure Classification ────────────────


def test_websocket_winerror_10054_classified_as_p3():
    """Verify WinError 10054 connection reset by remote host is classified as P3 informational audit."""
    msg = "[WinError 10054] An existing connection was forcibly closed by the remote host - goodbye"
    prio = derive_priority("SYSTEM_LOG", "websocket", "ERROR", msg)
    assert prio == "P3"


def test_telemetry_handler_keeps_websocket_goodbye_at_p3():
    """Verify TelemetryLogHandler does not elevate websocket ERROR goodbye to P2."""
    handler = TelemetryLogHandler()
    record = logging.LogRecord(
        name="websocket",
        level=logging.ERROR,
        pathname="websocket/_app.py",
        lineno=591,
        msg="[WinError 10054] An existing connection was forcibly closed by the remote host - goodbye",
        args=(),
        exc_info=None,
    )

    with patch("engine.telemetry.record_event") as mock_record:
        handler.emit(record)
        assert mock_record.called
        kwargs = mock_record.call_args.kwargs
        assert kwargs["priority"] == "P3"
        assert kwargs["severity"] == "INFO"


# ── 3. Fyers Rate Gate Permit Denial Classification ──────────────────────────


def test_rate_gate_denied_permit_classified_as_p3():
    """Verify Rate gate denied permit is classified as P3 informational pacing."""
    msg = "[FyersAPI] Rate gate denied permit for DEPTH_CHAIN optionchain (M&M)."
    prio = derive_priority("SYSTEM_LOG", "brokers.fyers", "WARNING", msg)
    assert prio == "P3"

    msg_chunk = "[FyersAPI] Rate gate denied permit for SCANNER_QUOTE chunk (50 symbols)."
    assert derive_priority("SYSTEM_LOG", "brokers.fyers", "INFO", msg_chunk) == "P3"


def test_telemetry_handler_keeps_rate_gate_denied_at_p3():
    """Verify TelemetryLogHandler treats rate gate permit denial as P3 informational audit if logged at WARNING."""
    handler = TelemetryLogHandler()
    record = logging.LogRecord(
        name="brokers.fyers",
        level=logging.WARNING,
        pathname="brokers/fyers.py",
        lineno=2123,
        msg="[FyersAPI] Rate gate denied permit for DEPTH_CHAIN optionchain (M&M).",
        args=(),
        exc_info=None,
    )

    with patch("engine.telemetry.record_event") as mock_record:
        handler.emit(record)
        assert mock_record.called
        kwargs = mock_record.call_args.kwargs
        assert kwargs["priority"] == "P3"
        assert kwargs["severity"] == "INFO"


# ── 4. Off-Market Derivative Scanner Guard ───────────────────────────────────


def test_scan_gamma_blasts_respects_market_hours():
    """Verify scan_gamma_blasts returns empty list immediately when FNO market is closed."""
    from engine.auto_alert_engine import AutoAlertEngine

    engine = AutoAlertEngine()

    with (
        patch("market.calendar.is_market_open", return_value=False),
        patch.dict("os.environ", {"CHANAKYA_TESTING": "0", "PYTEST_CURRENT_TEST": ""}),
    ):
        alerts = engine.scan_gamma_blasts()
        assert alerts == []


def test_scan_options_momentum_breakouts_respects_market_hours():
    """Verify scan_options_momentum_breakouts returns empty list immediately when FNO market is closed."""
    from engine.auto_alert_engine import AutoAlertEngine

    engine = AutoAlertEngine()

    with (
        patch("market.calendar.is_market_open", return_value=False),
        patch.dict("os.environ", {"CHANAKYA_TESTING": "0", "PYTEST_CURRENT_TEST": ""}),
    ):
        alerts = engine.scan_options_momentum_breakouts()
        assert alerts == []
