"""
tests/test_alert_channel_parity.py
──────────────────────────────────
Institutional invariant & regression suite verifying:
1. Single Authority Ingestion: ExecutionGateReport routes through AutoAlertEngine.
2. Alert Identity Invariant: Ingested reports receive deterministic IDs (generate_alert_id).
3. Telegram & UI Parity: Alerts are stored in auto_alerts.json, broadcasted, and tracked.
4. Telegram Bot /alerts unification: cmd_alerts surfaces both AutoAlerts and Manual alerts.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from analysis.execution_gate import ExecutionGateReport
from engine.alert_identity import validate_alert_id
from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine


@pytest.fixture
def test_engine(tmp_path, monkeypatch):
    """Provides an isolated AutoAlertEngine backed by temporary storage."""
    alerts_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.AUTO_ALERTS_FILE", alerts_file)
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: alerts_file)
    engine = AutoAlertEngine()
    engine._alerts = []
    return engine


def test_ingest_execution_gate_report_dataclass(test_engine):
    """Verify that ingesting an ExecutionGateReport creates a valid, deterministic AutoAlert."""
    rep = ExecutionGateReport(
        symbol="TATAMOTORS",
        sector="Auto",
        sector_icon="🚗",
        ltp=985.50,
        strategic_score=88.0,
        tactical_score=86.0,
        execution_status="READY",
        setup_title="VCP Stage 2 Breakout",
        trade_bias="LONG",
        entry_price=985.0,
        stop_loss=960.0,
        target_1=1035.0,
        target_2=1085.0,
        risk_reward_ratio=2.0,
        rvol=2.4,
        options_oi_regime="CALL_UNWINDING",
        squeeze_fired=True,
        expected_timeline="2-5 Days",
        target_1_timeline="1-2 Days",
        target_2_timeline="3-5 Days",
        time_stop_days=5,
        profit_booking_plan="Scale 50% at T1",
        catalysts=["Earnings Surprise", "VCP Tightness"],
        action_summary="Strong institutional breakout setup",
    )

    alert = test_engine.ingest_execution_gate_report(rep)

    assert alert is not None
    assert alert.symbol == "TATAMOTORS"
    assert alert.alert_type == "EXECUTION_READY"
    assert alert.stage == "IGNITED"
    assert alert.direction == "BULLISH"
    assert alert.confidence == 88
    assert alert.trigger_level == 985.0
    assert alert.stop_loss == 960.0
    assert alert.target_level == 1035.0

    # Invariant: Alert ID must satisfy daily determinism
    valid, reason = validate_alert_id(alert.alert_id)
    assert valid, f"Alert ID validation failed: {reason}"
    assert "aa-execution-ready-tatamotors-ready-" in alert.alert_id

    # Storage: Must be present in engine alerts
    assert any(a.alert_id == alert.alert_id for a in test_engine.get_alerts(view_mode="ALL"))


def test_ingest_execution_gate_report_dict(test_engine):
    """Verify that ingesting a raw dict (e.g. from web skills/agent tool) works seamlessly."""
    raw_dict = {
        "symbol": "NSE:INFY",
        "execution_status": "STALK",
        "tactical_score": 82.0,
        "strategic_score": 84.0,
        "entry_price": 1920.0,
        "stop_loss": 1880.0,
        "target_1": 2000.0,
        "target_2": 2080.0,
        "trade_bias": "LONG",
        "setup_title": "SMC Order Block Sweep",
        "action_summary": "Order block sweep with LTF CHoCH",
        "expected_timeline": "1-3 Days",
        "risk_reward_ratio": 2.0,
        "sector": "IT",
    }

    alert = test_engine.ingest_execution_gate_report(raw_dict)

    assert alert is not None
    assert alert.symbol == "INFY"  # Normalized without exchange prefix
    assert alert.alert_type == "EXECUTION_READY"
    assert alert.stage == "EARLY_WARNING"  # STALK maps to EARLY_WARNING
    assert alert.confidence == 84
    assert alert.stop_loss == 1880.0
    assert "aa-execution-ready-infy-stalk-" in alert.alert_id


def test_cmd_alerts_unified_output(monkeypatch):
    """Verify that bot.telegram_bot.cmd_alerts displays both AutoAlerts and Manual alerts with channel delivery tags."""
    import asyncio
    from bot.telegram_bot import cmd_alerts

    # Mock AutoAlerts
    mock_auto = [
        AutoAlert(
            alert_id="aa-gamma-blast-nifty-20260928",
            symbol="NIFTY",
            exchange="NSE",
            alert_type="GAMMA_BLAST",
            stage="IGNITED",
            direction="BULLISH",
            headline="NIFTY Gamma Blast",
            summary="OI unwinding surge",
            ltp=25000.0,
            trigger_level=25000.0,
            target_level=25200.0,
            stop_loss=24900.0,
            confidence=92,
            telegram_dispatched=True,
        ),
        AutoAlert(
            alert_id="aa-squeeze-reliance-20260928",
            symbol="RELIANCE",
            exchange="NSE",
            alert_type="SQUEEZE_BREAKOUT",
            stage="EARLY_WARNING",
            direction="BULLISH",
            headline="RELIANCE Squeeze",
            summary="TTM Squeeze inside Keltner",
            ltp=3000.0,
            trigger_level=3000.0,
            target_level=3100.0,
            stop_loss=2950.0,
            confidence=76,
            telegram_dispatched=False,
            telegram_suppression_reason="Confidence 76% below Telegram bar (85%)",
        ),
    ]

    # Mock Manual Alert
    mock_manual = MagicMock()
    mock_manual.id = "alt-101"
    mock_manual.triggered = False
    mock_manual.is_invalidated = False
    mock_manual.describe.return_value = "TCS above ₹4300.0"

    monkeypatch.setattr(
        "engine.auto_alert_engine.auto_alert_engine.get_alerts",
        lambda view_mode="ACTIVE", limit=20: mock_auto,
    )
    monkeypatch.setattr(
        "engine.alerts.alert_manager._alerts",
        [mock_manual],
    )

    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    asyncio.run(cmd_alerts(update, context))

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]

    # Must contain sections for both Autonomous Radar and Manual Triggers
    assert "⚡ <b>Autonomous Radar (2)</b>" in reply_text
    assert "📌 <b>Manual Price Alerts (1)</b>" in reply_text
    # Must show TG SENT (📱) vs TG HELD (🔒)
    assert "📱 🟢 <b>NIFTY</b> [GAMMA BLAST]" in reply_text
    assert "🔒 🟢 <b>RELIANCE</b> [SQUEEZE BREAKOUT]" in reply_text
    assert "<code>[alt-101]</code> TCS above ₹4300.0" in reply_text
    assert "<i>Legend: 📱 Telegram Dispatched | 🔒 Terminal UI Only</i>" in reply_text


def test_execution_gate_dispatches_via_auto_alert_engine(ohlcv_df, monkeypatch):
    """Verify evaluate_execution_gate routes through AutoAlertEngine when notify_telegram=True."""
    from analysis.execution_gate import evaluate_execution_gate
    from analysis.big_move import OptionsFlowBias

    mock_ingest = MagicMock()
    monkeypatch.setattr(
        "engine.auto_alert_engine.auto_alert_engine.ingest_execution_gate_report",
        mock_ingest,
    )

    mock_flow = OptionsFlowBias(
        has_options=True,
        pcr=1.2,
        max_pain_strike=1300.0,
        dominant_regime="LONG_BUILDUP",
        call_oi_total=100000,
        put_oi_total=120000,
        highest_call_oi_strike=1400.0,
        highest_put_oi_strike=1200.0,
        institutional_sentiment="AGGRESSIVE_BULLISH",
    )
    with (
        patch(
            "analysis.sector_rotation.get_stock_sector_alignment",
            return_value={"sector": "METALS", "quadrant": "LEADING"},
        ),
        patch("analysis.execution_gate.analyze_options_flow", return_value=mock_flow),
        patch("bot.telegram_bot.push_execution_alert"),
    ):
        rep = evaluate_execution_gate("JSWSTEEL", df=ohlcv_df, notify_telegram=True)
        if rep.execution_status in ("READY", "STALK"):
            assert mock_ingest.called is True
