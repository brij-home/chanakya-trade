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
)
from engine.alert_preferences import get_alert_preferences_manager
from engine.alert_model import AutoAlert


def test_format_telegram_push_payload_attaches_inline_buttons():
    """Actionable fresh alert payloads must include 1-tap mobile execution buttons."""
    message = "🟢 <b>[REAL/LIVE] NEW CALL · GAMMA BLAST</b>\nNIFTY 25000 CE @ ₹120.0"
    payload = format_telegram_push_payload(
        message=message,
        chat_id="12345678",
        alert_id="aa-gamma-nifty-20261025",
        is_update=False,
    )
    assert "reply_markup" in payload
    inline_kb = payload["reply_markup"].get("inline_keyboard", [])
    assert len(inline_kb) == 1
    buttons = inline_kb[0]
    assert len(buttons) == 3
    assert buttons[0]["text"] == "⚡ Execute Live"
    assert buttons[0]["callback_data"] == "exec_live:aa-gamma-nifty-20261025"
    assert buttons[1]["text"] == "🛡️ Paper Trade"
    assert buttons[1]["callback_data"] == "exec_paper:aa-gamma-nifty-20261025"
    assert buttons[2]["text"] == "❌ Dismiss"
    assert buttons[2]["callback_data"] == "dismiss:aa-gamma-nifty-20261025"


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
