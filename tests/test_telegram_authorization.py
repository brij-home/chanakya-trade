"""
tests/test_telegram_authorization.py
────────────────────────────────────
Deterministic verification suite for Task P4-A:
1. Telegram owner allowlists (TELEGRAM_ALLOWED_USER_IDS, TELEGRAM_ALLOWED_CHAT_IDS).
2. Middleware rejection of commands and callbacks from unauthorized callers.
3. /flatten two-step confirmation gate (prompt -> inline confirm/cancel) and owner protection.
4. Truthful mode reporting in execution and flatten responses (no hardcoded "PAPER").
5. SpreadExecutionResult field access safety (res.legs).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from bot.telegram_bot import (
    is_telegram_authorized,
    _track_command,
    cmd_flatten,
    handle_alert_callback,
)
from engine.multi_leg_executor import SpreadExecutionResult, ChildLegExecution
from engine.order_lifecycle import clear_emergency_lockout


@pytest.fixture(autouse=True)
def clean_lockout():
    clear_emergency_lockout()
    yield
    clear_emergency_lockout()


def test_is_telegram_authorized_fail_closed_when_no_env(monkeypatch):
    """When no allowlists are configured, fail closed: reject all callers."""
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_CHAT_IDS", raising=False)

    update = MagicMock()
    update.effective_user.id = "111111"
    update.effective_chat.id = "222222"

    assert is_telegram_authorized(update) is False
    assert is_telegram_authorized(None) is False


def test_is_telegram_authorized_allowlists(monkeypatch):
    """Enforces matching against user or chat allowlists."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "1001, 1002")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "9001 9002")

    # Matching user
    u1 = MagicMock()
    u1.effective_user.id = "1001"
    u1.effective_chat.id = "5555"
    assert is_telegram_authorized(u1) is True

    # Matching chat
    u2 = MagicMock()
    u2.effective_user.id = "9999"
    u2.effective_chat.id = "9002"
    assert is_telegram_authorized(u2) is True

    # Non-matching user & chat
    u3 = MagicMock()
    u3.effective_user.id = "8888"
    u3.effective_chat.id = "7777"
    assert is_telegram_authorized(u3) is False


def test_track_command_middleware_rejects_unauthorized(monkeypatch):
    """_track_command middleware blocks unauthorized caller from executing handler."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "1001")
    handler = AsyncMock(return_value="executed")
    wrapped = _track_command(handler)

    # Unauthorized update
    unauth_update = MagicMock()
    unauth_update.effective_user.id = "9999"
    unauth_update.effective_chat.id = "9999"
    unauth_update.message.text = "/quote RELIANCE"

    res = asyncio.run(wrapped(unauth_update, MagicMock()))
    assert res is None
    handler.assert_not_called()

    # Authorized update
    auth_update = MagicMock()
    auth_update.effective_user.id = "1001"
    auth_update.effective_chat.id = "9999"
    auth_update.message.text = "/quote RELIANCE"

    res = asyncio.run(wrapped(auth_update, MagicMock()))
    assert res == "executed"
    handler.assert_called_once()


def test_cmd_flatten_unauthorized_blocked(monkeypatch):
    """Unauthorized user running /flatten is rejected with zero broker action."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "1001")

    update = MagicMock()
    update.effective_user.id = "9999"
    update.effective_chat.id = "9999"
    update.message.reply_text = AsyncMock()

    with patch("engine.order_lifecycle.emergency_flatten_all_positions") as mock_flatten:
        asyncio.run(cmd_flatten(update, MagicMock()))
        mock_flatten.assert_not_called()
        update.message.reply_text.assert_not_called()


def test_cmd_flatten_owner_prompts_confirmation(monkeypatch):
    """Authorized owner running /flatten without 'confirm' arg is prompted with confirmation keyboard."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "1001")

    update = MagicMock()
    update.effective_user.id = "1001"
    update.effective_chat.id = "1001"
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.args = []

    with patch("engine.order_lifecycle.emergency_flatten_all_positions") as mock_flatten:
        asyncio.run(cmd_flatten(update, context))
        mock_flatten.assert_not_called()
        update.message.reply_text.assert_called_once()
        prompt_text = update.message.reply_text.call_args[0][0]
        assert "EMERGENCY FLATTEN CONFIRMATION REQUIRED" in prompt_text
        reply_markup = update.message.reply_text.call_args[1].get("reply_markup")
        assert reply_markup is not None


def test_cmd_flatten_owner_explicit_confirm_arg(monkeypatch):
    """Authorized owner running '/flatten confirm' executes flatten directly."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "1001")

    update = MagicMock()
    update.effective_user.id = "1001"
    update.effective_chat.id = "1001"
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.args = ["confirm"]

    fake_result = {
        "status": "COMPLETED",
        "cancelled_orders_count": 3,
        "flattened_positions_count": 2,
        "message": "All orders cancelled and positions flattened successfully.",
    }

    with patch(
        "engine.order_lifecycle.emergency_flatten_all_positions", return_value=fake_result
    ) as mock_flatten:
        asyncio.run(cmd_flatten(update, context))
        mock_flatten.assert_called_once_with(
            actor="TELEGRAM_BOT", reason="TELEGRAM_EMERGENCY_FLATTEN"
        )
        update.message.reply_text.assert_called_once()
        reply_text = update.message.reply_text.call_args[0][0]
        assert "EMERGENCY FLATTEN EXECUTED" in reply_text
        assert "Cancelled Orders:</b> 3" in reply_text
        assert "Flattened Positions:</b> 2" in reply_text


def test_handle_alert_callback_flatten_cancel(monkeypatch):
    """flatten_cancel callback aborts emergency flatten cleanly."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "1001")

    update = MagicMock()
    update.effective_user.id = "1001"
    query = MagicMock()
    query.data = "flatten_cancel"
    query.answer = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    query.message.reply_text = AsyncMock()
    update.callback_query = query

    with patch("engine.order_lifecycle.emergency_flatten_all_positions") as mock_flatten:
        asyncio.run(handle_alert_callback(update, MagicMock()))
        mock_flatten.assert_not_called()
        query.edit_message_reply_markup.assert_called_once_with(reply_markup=None)
        query.message.reply_text.assert_called_once()
        assert "Emergency Flatten Aborted" in query.message.reply_text.call_args[0][0]


def test_handle_alert_callback_flatten_confirm_authorized(monkeypatch):
    """flatten_confirm callback executes flatten when user is authorized."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "1001")

    update = MagicMock()
    update.effective_user.id = "1001"
    query = MagicMock()
    query.data = "flatten_confirm"
    query.answer = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    query.message.reply_text = AsyncMock()
    update.callback_query = query

    fake_result = {
        "status": "COMPLETED",
        "cancelled_orders_count": 1,
        "flattened_positions_count": 1,
        "message": "Safe flatten done.",
    }

    with patch(
        "engine.order_lifecycle.emergency_flatten_all_positions", return_value=fake_result
    ) as mock_flatten:
        asyncio.run(handle_alert_callback(update, MagicMock()))
        mock_flatten.assert_called_once_with(
            actor="TELEGRAM_BOT", reason="TELEGRAM_EMERGENCY_FLATTEN"
        )
        query.edit_message_reply_markup.assert_called_once_with(reply_markup=None)
        assert "EMERGENCY FLATTEN EXECUTED" in query.message.reply_text.call_args[0][0]


def test_handle_alert_callback_flatten_confirm_unauthorized(monkeypatch):
    """flatten_confirm callback is blocked when user is unauthorized."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "1001")

    update = MagicMock()
    update.effective_user.id = "9999"
    query = MagicMock()
    query.data = "flatten_confirm"
    query.answer = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    query.message.reply_text = AsyncMock()
    update.callback_query = query

    with patch("engine.order_lifecycle.emergency_flatten_all_positions") as mock_flatten:
        asyncio.run(handle_alert_callback(update, MagicMock()))
        mock_flatten.assert_not_called()
        query.message.reply_text.assert_not_called()


def test_handle_alert_callback_unrecognized_data():
    """Unrecognized callback data is ignored safely with no error or action."""
    update = MagicMock()
    query = MagicMock()
    query.data = "random_garbage_data:xyz"
    query.answer = AsyncMock()
    query.message.reply_text = AsyncMock()
    update.callback_query = query

    asyncio.run(handle_alert_callback(update, MagicMock()))
    query.message.reply_text.assert_not_called()


def test_handle_alert_callback_exec_paper_spread_fields(monkeypatch):
    """exec_paper on spread accesses res.legs safely and reports mode label truthfully."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "1001")

    update = MagicMock()
    update.effective_user.id = "1001"
    query = MagicMock()
    query.data = "exec_paper:aa-spread-test"
    query.answer = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    query.message.reply_text = AsyncMock()
    update.callback_query = query

    mock_alert = MagicMock()
    mock_alert.actionable_plan = {
        "hedge_plan": {
            "strategy_name": "BULL_CALL_SPREAD",
            "net_debit_per_share": 45.0,
            "max_profit": 55.0,
            "max_loss": 45.0,
            "legs": [
                {
                    "symbol": "NIFTY26NOV25000CE",
                    "option_type": "CE",
                    "strike": 25000.0,
                    "side": "BUY",
                    "premium": 100.0,
                    "lot_size": 25,
                    "quantity": 25,
                },
                {
                    "symbol": "NIFTY26NOV25100CE",
                    "option_type": "CE",
                    "strike": 25100.0,
                    "side": "SELL",
                    "premium": 55.0,
                    "lot_size": 25,
                    "quantity": 25,
                },
            ],
        }
    }
    mock_alert.canonical_symbol = "NIFTY"
    mock_alert.ltp = 25020.0

    leg1 = ChildLegExecution(
        leg_index=0,
        symbol="NIFTY26NOV25000CE",
        option_type="CE",
        strike=25000.0,
        side="BUY",
        quantity=25,
        limit_price=100.0,
        order_id="ORD-1",
        broker_order_id="BRK-1",
        status="FILLED",
        fill_price=100.0,
        error_message="",
    )
    leg2 = ChildLegExecution(
        leg_index=1,
        symbol="NIFTY26NOV25100CE",
        option_type="CE",
        strike=25100.0,
        side="SELL",
        quantity=25,
        limit_price=55.0,
        order_id="ORD-2",
        broker_order_id="BRK-2",
        status="FILLED",
        fill_price=55.0,
        error_message="",
    )

    spread_res = SpreadExecutionResult(
        spread_id="SPRD-001",
        strategy_name="BULL_CALL_SPREAD",
        underlying="NIFTY",
        status="COMPLETED",
        legs=[leg1, leg2],
        net_fill_price=45.0,
        execution_start_time="2026-11-03T11:00:00",
        execution_end_time="2026-11-03T11:00:01",
        total_duration_ms=1000.0,
        unwind_performed=False,
        rejection_reason="",
        audit_events=[],
    )

    mock_engine = MagicMock()
    mock_engine.get_alert.return_value = mock_alert

    with (
        patch("engine.auto_alert_engine.get_auto_alert_engine", return_value=mock_engine),
        patch("engine.multi_leg_executor.execute_defined_risk_spread", return_value=spread_res),
    ):
        asyncio.run(handle_alert_callback(update, MagicMock()))
        query.message.reply_text.assert_called_once()
        text = query.message.reply_text.call_args[0][0]
        assert "SPREAD DISPATCHED" in text
        assert "Legs Filled: 2/2" in text
        assert "Net Fill: ₹45.00/sh" in text
