import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock

from analysis.execution_gate import (
    evaluate_execution_gate,
    scan_and_alert_execution_candidates,
    ExecutionGateReport,
)
from bot.telegram_bot import format_execution_alert_message


@pytest.fixture
def bullish_breakout_df():
    dates = pd.date_range("2024-01-01", periods=220, freq="D")
    base_closes = [500.0 + i * 2.5 for i in range(215)]
    surge_closes = [1040.0, 1060.0, 1085.0, 1110.0, 1140.0]
    all_closes = base_closes + surge_closes
    return pd.DataFrame({
        "open": all_closes,
        "high": [c + 15.0 for c in all_closes],
        "low": [c - 5.0 for c in all_closes],
        "close": all_closes,
        "volume": [100000] * 215 + [700000] * 5,
    }, index=dates)


def test_evaluate_execution_gate_ready(bullish_breakout_df):
    with (
        patch("analysis.sector_rotation.get_stock_sector_alignment", return_value={"sector": "METALS", "quadrant": "LEADING"}),
        patch("bot.telegram_bot.push_execution_alert") as mock_push,
    ):
        rep = evaluate_execution_gate("JSWSTEEL", df=bullish_breakout_df, notify_telegram=True)
        assert isinstance(rep, ExecutionGateReport)
        assert rep.strategic_score >= 60
        assert rep.tactical_score >= 60
        assert rep.execution_status in ("READY", "STALK")
        assert rep.target_1 > rep.ltp
        assert rep.stop_loss < rep.ltp
        assert mock_push.called is True



def test_format_execution_alert_message():
    d = {
        "symbol": "JSWSTEEL",
        "sector": "Metals",
        "sector_icon": "⛏️",
        "ltp": 1337.50,
        "execution_status": "READY",
        "strategic_score": 86,
        "tactical_score": 88,
        "entry_price": 1337.50,
        "stop_loss": 1285.80,
        "target_1": 1440.80,
        "target_2": 1518.40,
        "risk_reward_ratio": 2.0,
        "setup_title": "Stage 2 Superperformer",
        "rvol": 1.6,
        "options_oi_regime": "LONG_BUILDUP",
        "catalysts": ["Squeeze Fired", "Institutional RVOL 1.6x"],
    }
    msg = format_execution_alert_message(d)
    assert "READY TO EXECUTE" in msg
    assert "JSWSTEEL" in msg
    assert "₹1,337.50" in msg
    assert "Strategic: <b>86/100</b>" in msg
    assert "/size JSWSTEEL" in msg


def test_scan_and_alert_execution_candidates():
    with (
        patch("analysis.universe.resolve_dynamic_universe", return_value=["JSWSTEEL"]),
        patch("analysis.execution_gate.evaluate_execution_gate") as mock_eval,
    ):
        mock_eval.return_value = ExecutionGateReport(
            symbol="JSWSTEEL",
            sector="Metals",
            sector_icon="⛏️",
            ltp=1337.50,
            strategic_score=86,
            tactical_score=88,
            execution_status="READY",
            setup_title="Stage 2 Superperformer",
            trade_bias="LONG",
            entry_price=1337.50,
            stop_loss=1285.80,
            target_1=1440.80,
            target_2=1518.40,
            risk_reward_ratio=2.0,
            rvol=1.6,
            options_oi_regime="LONG_BUILDUP",
            squeeze_fired=True,
            catalysts=["Squeeze Fired"],
            action_summary="Execute now",
            telegram_sent=True,
        )
        candidates = scan_and_alert_execution_candidates(universe="auto_market_aware", top_n=1, notify_telegram=False)
        assert len(candidates) == 1
        assert candidates[0].symbol == "JSWSTEEL"
        assert candidates[0].execution_status == "READY"
