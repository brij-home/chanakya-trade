"""
tests/test_telegram_interactive_actions.py
──────────────────────────────────────────
Institutional unit tests for:
1. 1-Tap Mobile Execution inline keyboard generation (⚡ Execute Live, 🛡️ Paper Trade, ❌ Dismiss).
2. Callback query handling with safety fail-closed guardrails (ALLOW_LIVE_TRADING=1 gate).
3. /mute and /unmute telegram command handlers.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

from bot.telegram_bot import (
    format_telegram_push_payload,
    cmd_mute,
    cmd_unmute,
    handle_alert_callback,
    build_alert_callback_data,
    resolve_alert_callback_data,
    build_alert_execution_keyboard,
    sanitize_reply_markup,
    send_push,
)
from engine.alert_preferences import get_alert_preferences_manager
from engine.alert_model import AutoAlert


def test_format_telegram_push_payload_no_automatic_buttons():
    """Fresh alert payloads must remain clean and crisp without automatic inline buttons."""
    message = "🟢 <b>[REAL/LIVE] NEW CALL · GAMMA BLAST</b>\nNIFTY 25000 CE @ ₹120.0"
    payload = format_telegram_push_payload(
        message=message,
        chat_id="12345678",
        alert_id="aa-gamma-nifty-20261025",
        is_update=False,
    )
    assert "reply_markup" not in payload


def test_format_telegram_push_payload_no_buttons_on_update():
    """Milestone updates must not attach execution buttons to prevent duplicate entries."""
    message = "🎯 <b>UPDATE #1 · TARGET 1 ACHIEVED</b>\nScale 50% & SL to Cost."
    payload = format_telegram_push_payload(
        message=message,
        chat_id="12345678",
        alert_id="aa-gamma-nifty-20261025",
        is_update=True,
    )
    assert "reply_markup" not in payload


def test_format_telegram_push_payload_custom_reply_markup():
    """Explicit reply_markup override is preserved."""
    custom_markup = {"inline_keyboard": [[{"text": "Custom", "callback_data": "custom:1"}]]}
    payload = format_telegram_push_payload(
        message="Test message",
        chat_id="12345678",
        reply_markup=custom_markup,
    )
    assert payload["reply_markup"] == custom_markup


def test_cmd_mute_and_unmute():
    """Tests /mute and /unmute Telegram commands cleanly updating AlertPreferencesManager."""

    async def _test():
        mgr = get_alert_preferences_manager()
        mock_update = MagicMock()
        mock_update.message.reply_text = AsyncMock()
        mock_context = MagicMock()

        # Call /unmute first
        await cmd_unmute(mock_update, mock_context)
        assert mgr.sound.enabled is True
        mock_update.message.reply_text.assert_called()
        assert "Audio Unmuted" in mock_update.message.reply_text.call_args[0][0]

        # Call /mute
        await cmd_mute(mock_update, mock_context)
        assert mgr.sound.enabled is False
        assert "Quiet Mode Active" in mock_update.message.reply_text.call_args[0][0]

    import asyncio

    asyncio.run(_test())


def test_handle_alert_callback_dismiss():
    """Tapping Dismiss answers query, clears buttons, and confirms dismissal."""

    async def _test():
        mock_update = MagicMock()
        mock_query = MagicMock()
        mock_query.data = "dismiss:aa-test-123"
        mock_query.answer = AsyncMock()
        mock_query.edit_message_reply_markup = AsyncMock()
        mock_query.message.reply_text = AsyncMock()
        mock_update.callback_query = mock_query

        await handle_alert_callback(mock_update, MagicMock())

        mock_query.answer.assert_called_once()
        mock_query.edit_message_reply_markup.assert_called_once_with(reply_markup=None)
        mock_query.message.reply_text.assert_called_once()
        assert "Alert Dismissed" in mock_query.message.reply_text.call_args[0][0]

    import asyncio

    asyncio.run(_test())


def test_handle_alert_callback_exec_live_fail_closed_without_env():
    """Executing Live without ALLOW_LIVE_TRADING=1 must fail-closed with safety advisory."""

    async def _test():
        with patch.dict(os.environ, {"ALLOW_LIVE_TRADING": "0"}, clear=False):
            mock_update = MagicMock()
            mock_query = MagicMock()
            mock_query.data = "exec_live:aa-test-123"
            mock_query.answer = AsyncMock()
            mock_query.message.reply_text = AsyncMock()
            mock_update.callback_query = mock_query

            await handle_alert_callback(mock_update, MagicMock())

            mock_query.answer.assert_called_once()
            mock_query.message.reply_text.assert_called_once()
            reply_msg = mock_query.message.reply_text.call_args[0][0]
            assert "LIVE EXECUTION LOCKED" in reply_msg
            assert "ALLOW_LIVE_TRADING=1" in reply_msg

    import asyncio

    asyncio.run(_test())


def test_handle_alert_callback_exec_paper_success():
    """Tapping Paper Trade executes paper order lifecycle intent cleanly."""

    async def _test():
        alert_obj = AutoAlert(
            alert_id="aa-test-paper-exec",
            alert_type="EXECUTION_READY",
            symbol="SBIN",
            stage="READY",
            exchange="NSE",
            direction="BULLISH",
            summary="Test paper execution",
            ltp=800.0,
            trigger_level=800.0,
            target_level=820.0,
            stop_loss=790.0,
            headline="SBIN Breakout",
            actionable_plan={"action": "BUY"},
        )

        mock_engine = MagicMock()
        mock_engine.get_alert.return_value = alert_obj

        with patch("engine.auto_alert_engine.get_auto_alert_engine", return_value=mock_engine):
            mock_update = MagicMock()
            mock_query = MagicMock()
            mock_query.data = "exec_paper:aa-test-paper-exec"
            mock_query.answer = AsyncMock()
            mock_query.edit_message_reply_markup = AsyncMock()
            mock_query.message.reply_text = AsyncMock()
            mock_update.callback_query = mock_query

            await handle_alert_callback(mock_update, MagicMock())

            mock_query.answer.assert_called_once()
            mock_query.edit_message_reply_markup.assert_called_once_with(reply_markup=None)
            mock_query.message.reply_text.assert_called_once()
            reply_msg = mock_query.message.reply_text.call_args[0][0]
            assert "PAPER ORDER EXECUTED" in reply_msg
            assert "SBIN" in reply_msg

    import asyncio

    asyncio.run(_test())


def test_build_and_resolve_alert_callback_data_long_id():
    """Verify that alerts with long IDs (> 53 chars) are compacted under 64 bytes and resolve cleanly."""
    long_aid = "aa-commodity-momentum-naturalgas-bullish-290ce-20261026"  # 56 chars
    # Raw exec_live + long_aid would be 10 + 56 = 66 chars > 64 chars
    cb_live = build_alert_callback_data("exec_live", long_aid)
    assert len(cb_live.encode("utf-8")) <= 64
    assert cb_live.startswith("exec_live:h_")

    action, resolved_aid = resolve_alert_callback_data(cb_live)
    assert action == "exec_live"
    assert resolved_aid == long_aid

    # Short alert ID should remain unhashed
    short_aid = "aa-test-123"
    cb_short = build_alert_callback_data("dismiss", short_aid)
    assert cb_short == "dismiss:aa-test-123"
    assert len(cb_short.encode("utf-8")) <= 64
    action_s, resolved_s = resolve_alert_callback_data(cb_short)
    assert action_s == "dismiss"
    assert resolved_s == short_aid


def test_build_alert_execution_keyboard_strictly_bounded():
    """Verify build_alert_execution_keyboard generates buttons all strictly under 64 bytes."""
    long_aid = "aa-commodity-momentum-naturalgas-bullish-290ce-20261026"
    kb = build_alert_execution_keyboard(long_aid)
    assert "inline_keyboard" in kb
    buttons = kb["inline_keyboard"][0]
    assert len(buttons) == 3
    for btn in buttons:
        assert len(btn["callback_data"].encode("utf-8")) <= 64


def test_sanitize_reply_markup_compacts_oversized_callback_data():
    """Verify custom reply_markup with oversized callback_data is sanitized to <= 64 bytes."""
    long_aid = "aa-commodity-momentum-naturalgas-bullish-290ce-20261026"
    oversized_markup = {
        "inline_keyboard": [
            [
                {"text": "⚡ Live", "callback_data": f"exec_live:{long_aid}"},
                {"text": "🛡️ Paper", "callback_data": f"exec_paper:{long_aid}"},
                {"text": "❌ Dismiss", "callback_data": f"dismiss:{long_aid}"},
            ]
        ]
    }
    sanitized = sanitize_reply_markup(oversized_markup)
    for row in sanitized["inline_keyboard"]:
        for btn in row:
            assert len(btn["callback_data"].encode("utf-8")) <= 64


def test_handle_alert_callback_with_compacted_hash():
    """Tapping button with compacted hash token correctly resolves alert ID and executes action."""

    async def _test():
        long_aid = "aa-commodity-momentum-naturalgas-bullish-290ce-20261026"
        compact_cb = build_alert_callback_data("dismiss", long_aid)

        mock_update = MagicMock()
        mock_query = MagicMock()
        mock_query.data = compact_cb
        mock_query.answer = AsyncMock()
        mock_query.edit_message_reply_markup = AsyncMock()
        mock_query.message.reply_text = AsyncMock()
        mock_update.callback_query = mock_query

        await handle_alert_callback(mock_update, MagicMock())

        mock_query.answer.assert_called_once()
        mock_query.edit_message_reply_markup.assert_called_once_with(reply_markup=None)
        mock_query.message.reply_text.assert_called_once()
        assert long_aid in mock_query.message.reply_text.call_args[0][0]

    import asyncio

    asyncio.run(_test())


def test_send_push_adaptive_recovery_on_button_data_invalid(monkeypatch):
    """When Telegram rejects with BUTTON_DATA_INVALID, send_push adaptively strips reply_markup and succeeds."""
    import bot.telegram_bot as tb_module

    attempts = []

    class DummyResponse:
        def __init__(self, status_code, data):
            self.status_code = status_code
            self._data = data
            self.is_success = status_code == 200
            self.text = str(data)

        def json(self):
            return self._data

    def mock_post(url, json=None, timeout=10):
        attempts.append(dict(json))
        if len(attempts) == 1:
            # First attempt: reject with BUTTON_DATA_INVALID
            return DummyResponse(
                400,
                {"ok": False, "error_code": 400, "description": "Bad Request: BUTTON_DATA_INVALID"},
            )
        # Second attempt: succeed
        return DummyResponse(200, {"ok": True, "result": {"message_id": 9999}})

    class ImmediateExecutor:
        def submit(self, fn):
            fn()
            return None

    monkeypatch.setattr("httpx.post", mock_post)
    monkeypatch.setattr(tb_module, "_load_chat_id", lambda: "-1004320002599")
    monkeypatch.setattr(tb_module, "_get_bot_token", lambda: "fake-bot-token")
    monkeypatch.setattr(tb_module, "_get_push_executor", lambda: ImmediateExecutor())
    monkeypatch.setattr(tb_module, "_ALLOW_TEST_DISPATCH", True)

    oversized_markup = {"inline_keyboard": [[{"text": "Bad", "callback_data": "bad"}]]}
    success_called = []
    send_push(
        message="Test alert message",
        chat_id="-1004320002599",
        reply_markup=oversized_markup,
        bypass_dedup=True,
        on_success=lambda mid: success_called.append(mid),
    )

    assert len(attempts) == 2
    assert "reply_markup" in attempts[0]
    assert "reply_markup" not in attempts[1]  # Stripped on adaptive retry!
    assert success_called == [9999]


def test_send_push_adaptive_recovery_on_replied_message_not_found(monkeypatch):
    """When Telegram rejects with replied message not found, send_push adaptively strips reply params and succeeds."""
    import bot.telegram_bot as tb_module

    attempts = []

    class DummyResponse:
        def __init__(self, status_code, data):
            self.status_code = status_code
            self._data = data
            self.is_success = status_code == 200
            self.text = str(data)

        def json(self):
            return self._data

    def mock_post(url, json=None, timeout=10):
        attempts.append(dict(json))
        if len(attempts) == 1:
            return DummyResponse(
                400,
                {
                    "ok": False,
                    "error_code": 400,
                    "description": "Bad Request: message to be replied not found",
                },
            )
        return DummyResponse(200, {"ok": True, "result": {"message_id": 8888}})

    class ImmediateExecutor:
        def submit(self, fn):
            fn()
            return None

    monkeypatch.setattr("httpx.post", mock_post)
    monkeypatch.setattr(tb_module, "_load_chat_id", lambda: "-1004320002599")
    monkeypatch.setattr(tb_module, "_get_bot_token", lambda: "fake-bot-token")
    monkeypatch.setattr(tb_module, "_get_push_executor", lambda: ImmediateExecutor())
    monkeypatch.setattr(tb_module, "_ALLOW_TEST_DISPATCH", True)

    success_called = []
    send_push(
        message="Update on missing thread",
        chat_id="-1004320002599",
        reply_to_message_id=12345,
        bypass_dedup=True,
        on_success=lambda mid: success_called.append(mid),
    )

    assert len(attempts) == 2
    assert "reply_to_message_id" in attempts[0]
    assert "reply_to_message_id" not in attempts[1]  # Stripped on adaptive retry!
    assert success_called == [8888]


def test_send_push_ultimate_barebones_fail_safe(monkeypatch):
    """When both formatted attempts fail (e.g. button error then entity error), barebones delivers plain text."""
    import bot.telegram_bot as tb_module

    attempts = []

    class DummyResponse:
        def __init__(self, status_code, data):
            self.status_code = status_code
            self._data = data
            self.is_success = status_code == 200
            self.text = str(data)

        def json(self):
            return self._data

    def mock_post(url, json=None, timeout=10):
        attempts.append(dict(json))
        if len(attempts) == 1:
            # First attempt: rejected due to buttons
            return DummyResponse(
                400,
                {"ok": False, "error_code": 400, "description": "Bad Request: BUTTON_DATA_INVALID"},
            )
        elif len(attempts) == 2:
            # Second attempt (adaptive without buttons): rejected due to entity parsing
            return DummyResponse(
                400,
                {
                    "ok": False,
                    "error_code": 400,
                    "description": "Bad Request: can't parse entities in message text",
                },
            )
        # Third attempt (barebones): succeeds
        return DummyResponse(200, {"ok": True, "result": {"message_id": 7777}})

    class ImmediateExecutor:
        def submit(self, fn):
            fn()
            return None

    monkeypatch.setattr("httpx.post", mock_post)
    monkeypatch.setattr(tb_module, "_load_chat_id", lambda: "-1004320002599")
    monkeypatch.setattr(tb_module, "_get_bot_token", lambda: "fake-bot-token")
    monkeypatch.setattr(tb_module, "_get_push_executor", lambda: ImmediateExecutor())
    monkeypatch.setattr(tb_module, "_ALLOW_TEST_DISPATCH", True)

    oversized_markup = {"inline_keyboard": [[{"text": "Bad", "callback_data": "bad"}]]}
    success_called = []
    send_push(
        message="<b>CRITICAL</b> Alert message <unclosed tag",
        chat_id="-1004320002599",
        parse_mode="HTML",
        reply_markup=oversized_markup,
        bypass_dedup=True,
        on_success=lambda mid: success_called.append(mid),
    )

    assert len(attempts) == 3
    # Attempt 1 had markup
    assert "reply_markup" in attempts[0]
    # Attempt 2 stripped markup
    assert "reply_markup" not in attempts[1]
    # Attempt 3 was barebones plain text without parse_mode
    assert attempts[2]["text"] == "CRITICAL Alert message unclosed tag"
    assert "parse_mode" not in attempts[2]
    assert success_called == [7777]
