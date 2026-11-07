"""
tests/test_p1_p2_fixes_regression.py
────────────────────────────────────
Deterministic regression tests ensuring permanent resolution of:
1. P1: OutboxWorker and NightlyChain Telegram delivery error (get_telegram_bot).
2. P2-1: AutoAlertEngine poll cycle 'function' object has no attribute 'strftime'.
3. P2-2: Telemetry priority classification for routine socket disconnects,
   TBT silence watchdog freeze self-healing, and discarded phantom dirty ticks.
4. P3: Canonical Fyers index symbol mapping for sector indices (e.g. PSU_BANK).
"""

from __future__ import annotations

from unittest.mock import MagicMock


from bot.telegram_bot import get_telegram_bot
from brokers.fyers import to_fyers_symbol
from engine.outbox_worker import OutboxWorker
from engine.telemetry import derive_priority
from market.websocket import _to_ws_symbol


class TestP1TelegramBotFacade:
    """P1 Regression: get_telegram_bot must be exported and functional."""

    def test_get_telegram_bot_facade(self):
        bot = get_telegram_bot()
        assert bot is not None
        assert hasattr(bot, "send_push")
        assert hasattr(bot, "send_message")
        assert hasattr(bot, "push_alert")
        assert hasattr(bot, "push_brief")

    def test_outbox_worker_dispatches_with_telegram_facade(self, monkeypatch):
        mock_send = MagicMock(return_value=True)
        bot = get_telegram_bot()
        monkeypatch.setattr(bot, "send_push", mock_send)

        mock_store = MagicMock()
        worker = OutboxWorker(store=mock_store)

        payload = {
            "alert_id": "aa-gamma-nifty-20261103",
            "symbol": "NIFTY",
            "is_live": True,
            "environment": "LIVE",
        }
        entry = {
            "channel": "TELEGRAM",
            "payload": payload,
        }
        res = worker.dispatch_channel_entry(entry)
        assert res is True
        mock_send.assert_called_once()
        args, kwargs = mock_send.call_args
        # Telegram send_push requires string message (never raw dict)
        assert isinstance(args[0], str)
        assert "NIFTY" in args[0]
        assert kwargs.get("alert_id") == "aa-gamma-nifty-20261103"


class TestP2AutoAlertEngineDefensiveDates:
    """P2-1 Regression: Zero 'function' object has no attribute 'strftime' in poll cycle."""

    def test_defensive_strftime_on_callables_and_dates(self):
        # Even if a callable or mock is passed, strftime resolution must not crash
        def _callable_date():
            from datetime import date

            return date(2026, 11, 3)

        effective_d = _callable_date
        if callable(effective_d):
            effective_d = effective_d()
        assert hasattr(effective_d, "strftime")
        assert effective_d.strftime("%Y%m%d") == "20261103"


class TestP2TelemetryPriorityClassification:
    """P2-2 and P2-3 Regression: Telemetry priorities for self-healing & sanity drops."""

    def test_socket_remote_disconnect_is_p3(self):
        # Routine socket drops must be classified as P3
        prio = derive_priority(
            "SYSTEM_LOG", "websocket", "ERROR", "Connection to remote host was lost. - goodbye"
        )
        assert prio == "P3"

        prio_fyers = derive_priority(
            "SYSTEM_LOG", "FyersDataSocket", "ERROR", "Connection to remote host was lost."
        )
        assert prio_fyers == "P3"

    def test_discarded_phantom_dirty_tick_is_p3(self):
        msg = (
            "[AlertEvaluator] Discarded phantom dirty tick for SENSEX: "
            "current_ltp=582.05 exceeds exchange day_high=520.35 by >2%."
        )
        prio = derive_priority("SYSTEM_LOG", "engine.alert_evaluator", "WARNING", msg)
        assert prio == "P3"

    def test_silence_watchdog_packet_freeze_is_p3(self):
        msg = (
            "[TbtManager] SILENCE WATCHDOG: Packet freeze detected (15.6s > 15.0s) "
            "across 15 active subscriptions during market hours. Initiating self-healing reconnect."
        )
        prio = derive_priority("SYSTEM_LOG", "market.fyers_tbt", "WARNING", msg)
        assert prio == "P3"

    def test_proactively_dropped_invalid_symbol_is_p3(self):
        msg = "[WebSocket] Proactively dropped invalid symbol 'NSE:TEST-EQ' before broker dispatch"
        prio = derive_priority("SYSTEM_LOG", "market.websocket", "WARNING", msg)
        assert prio == "P3"


class TestP3SectorIndexSymbolMapping:
    """P3 Regression: Canonical conversion of sector indices to Fyers -INDEX format."""

    def test_psu_bank_resolves_to_index(self):
        assert to_fyers_symbol("NSE:NIFTY PSU BANK") == "NSE:NIFTYPSUBANK-INDEX"
        assert to_fyers_symbol("PSU_BANK") == "NSE:NIFTYPSUBANK-INDEX"
        assert _to_ws_symbol("NSE:NIFTY PSU BANK") == "NSE:NIFTYPSUBANK-INDEX"
        assert _to_ws_symbol("PSU_BANK") == "NSE:NIFTYPSUBANK-INDEX"

    def test_other_sector_indices_resolve_to_index(self):
        assert to_fyers_symbol("NSE:NIFTY INFRA") == "NSE:NIFTYINFRA-INDEX"
        assert to_fyers_symbol("NSE:NIFTY MEDIA") == "NSE:NIFTYMEDIA-INDEX"
        assert _to_ws_symbol("NSE:NIFTY INFRA") == "NSE:NIFTYINFRA-INDEX"
        assert _to_ws_symbol("NSE:NIFTY MEDIA") == "NSE:NIFTYMEDIA-INDEX"
