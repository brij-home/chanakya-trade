"""
tests/test_pre_inflection_dryup_telegram.py
─────────────────────────────────────────────
Unit tests for Pre-Inflection Dry-Up Radar Telegram integration,
apex gate qualification, alert preferences routing, and template formatting.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from engine.alert_identity import generate_alert_id
from engine.alert_model import AutoAlert
from engine.alert_preferences import alert_preferences
from engine.auto_alert_engine import AutoAlertEngine
from bot.alert_templates import render_auto_alert
from bot.telegram_bot import cmd_dryup


def _make_dryup_alert(
    symbol: str = "TRENT",
    ltp: float = 6200.0,
    confidence: int = 92,
    vol_dryup_ratio: float = 0.32,
    avg_range_pct: float = 1.1,
    fair_value: float = 6180.0,
    sl: float = 6110.0,
    t1: float = 6320.0,
    t2: float = 6460.0,
) -> AutoAlert:
    return AutoAlert(
        alert_id=generate_alert_id(symbol, "PRE_INFLECTION_DRYUP", variant="dryup"),
        alert_type="PRE_INFLECTION_DRYUP",
        stage="EARLY_WARNING",
        symbol=symbol,
        exchange="NSE",
        direction="BULLISH",
        headline=f"🤫 PRE-INFLECTION DRY-UP: {symbol} at ₹{ltp:,.1f} (Fair Value Zone)",
        summary=f"Pre-ignition footprint detected: Volume dried up to {int(vol_dryup_ratio * 100)}% with {avg_range_pct}% range.",
        ltp=ltp,
        trigger_level=fair_value,
        target_level=t1,
        stop_loss=sl,
        confidence=confidence,
        metrics={
            "vol_dryup_ratio": vol_dryup_ratio,
            "avg_range_pct": avg_range_pct,
            "fair_value": fair_value,
            "fair_value_source": "Volume Profile POC",
            "no_chase_limit": ltp * 1.02,
        },
        actionable_plan={
            "action": "ACCUMULATE_FAIR_VALUE",
            "entry_range": f"₹{fair_value * 0.992:,.1f} – ₹{fair_value * 1.008:,.1f}",
            "stop_loss": f"₹{sl:,.1f}",
            "target_1": f"₹{t1:,.1f} (+2R)",
            "target_2": f"₹{t2:,.1f} (+4R)",
            "do_not_chase_above": f"₹{ltp * 1.02:,.1f} (+2.0% ceiling)",
            "risk_reward": "1:4.2",
        },
    )


def test_alert_preferences_allows_pre_inflection_dryup():
    """Verify alert_preferences permits PRE_INFLECTION_DRYUP on telegram and UI channels."""
    alert = _make_dryup_alert(confidence=92)
    allowed, reason = alert_preferences.explain_alert_allowed(alert, channel="telegram")
    assert allowed, f"PRE_INFLECTION_DRYUP should be permitted on Telegram, got: {reason}"

    ui_allowed, _ = alert_preferences.explain_alert_allowed(alert, channel="ui")
    assert ui_allowed, "PRE_INFLECTION_DRYUP should be permitted on UI"


def test_telegram_apex_gate_allows_high_conviction_dryup():
    """Verify AutoAlertEngine apex gate passes PRE_INFLECTION_DRYUP with >= 88% confidence."""
    engine = AutoAlertEngine()
    alert_high = _make_dryup_alert(confidence=90)
    passes, reason = engine._eval_telegram_apex_gate(alert_high, in_market=True)
    assert passes, f"High conviction dry-up alert should pass apex gate, got: {reason}"

    alert_low = _make_dryup_alert(confidence=80)
    passes_low, reason_low = engine._eval_telegram_apex_gate(alert_low, in_market=True)
    assert not passes_low, "Sub-88% early warning dry-up should be held in UI"
    assert "below 88%" in reason_low or "below" in reason_low


def test_format_telegram_alert_pre_inflection_dryup_header():
    """Verify render_auto_alert renders institutional header for PRE_INFLECTION_DRYUP."""
    alert = _make_dryup_alert()
    text = render_auto_alert(alert)
    assert "PRE-INFLECTION DRY-UP (ANTI-FOMO)" in text
    assert "TRENT" in text


@pytest.mark.anyio
async def test_cmd_dryup_handler_returns_formatted_setups():
    """Verify /dryup bot command returns structured setups to user."""
    mock_update = MagicMock()
    mock_update.message.reply_text = AsyncMock()
    mock_context = MagicMock()
    mock_context.args = []

    mock_alert = _make_dryup_alert(symbol="KAYNES", ltp=4500.0, confidence=94)

    with patch(
        "engine.detectors.pre_inflection_dryup.detect_pre_inflection_dryup",
        return_value=mock_alert,
    ):
        with patch(
            "market.history.get_ohlcv",
            return_value=MagicMock(iloc=[MagicMock()], __len__=lambda s: 30),
        ):
            await cmd_dryup(mock_update, mock_context)
            assert mock_update.message.reply_text.call_count >= 2
            final_call = mock_update.message.reply_text.call_args_list[-1]
            msg_text = final_call[0][0]
            assert "PRE-INFLECTION DRY-UP RADAR" in msg_text
            assert "KAYNES" in msg_text
            assert "Volume Dry-Up" in msg_text
            assert "Anti-FOMO Boundary" in msg_text
