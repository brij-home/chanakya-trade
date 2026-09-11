"""
tests/test_mover_alerts_telegram.py
───────────────────────────────────
Unit tests for Telegram alert formatting, push dispatching, and bot commands (/movers, /precursors).
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from bot.telegram_bot import (
    format_precursor_alert,
    send_precursor_push,
    cmd_movers,
    cmd_precursors,
)
from engine.mover_autopsy import DailyMoverAutopsy, MoverCausalProfile
from engine.precursor_radar import PrecursorCandidate


def test_format_precursor_alert():
    """Verify high-conviction precursor alert formatting contains all profit targets and no-chase rules."""
    candidate_dict = {
        "symbol": "TRENT",
        "conviction_score": 92,
        "verdict": "MAX_CONVICTION",
        "ltp": 6850.0,
        "entry_range": "₹6,820.0 – ₹6,870.0",
        "stop_loss": 6720.0,
        "target_1": 7045.0,
        "target_2": 7250.0,
        "risk_reward": "1:2.5",
        "when_to_buy": "Enter on ask within coiling zone.",
        "when_to_wait": "DO NOT CHASE if gaps up > 1.8%. Wait for 15-min VWAP pullback.",
        "profit_rule": "Book 50% at T1, move SL to breakeven, trail runner to T2.",
        "matched_factors": [
            "Volume dry-up (15% of 20D SMA)",
            "4-bar TTM Squeeze compression",
            "Parent sector in LEADING RRG quadrant",
        ],
    }

    msg = format_precursor_alert(candidate_dict)

    assert "PRECURSOR RADAR" in msg
    assert "Chanakya" not in msg
    assert "TRENT" in msg
    assert "92/100" in msg
    assert "MAX_CONVICTION" in msg
    assert "₹6,820.0 – ₹6,870.0" in msg
    assert "₹6,720.00" in msg
    assert "₹7,045.00" in msg
    assert "DO NOT CHASE" in msg
    assert "Volume dry-up" in msg


def test_send_precursor_push():
    """Verify send_precursor_push dispatches HTML-formatted message via send_push."""
    cand = {
        "symbol": "DIXON",
        "conviction_score": 88,
        "ltp": 11500.0,
        "entry_range": "₹11,450 – ₹11,550",
        "stop_loss": 11320.0,
        "target_1": 11770.0,
        "target_2": 12050.0,
    }

    with patch("bot.telegram_bot.send_push") as mock_push:
        ok = send_precursor_push(cand)
        assert ok is True
        mock_push.assert_called_once()
        args, kwargs = mock_push.call_args
        assert "DIXON" in args[0]
        assert kwargs.get("parse_mode") == "HTML"


@pytest.mark.anyio
async def test_cmd_movers():
    """Verify /movers command replies with autopsy summary."""
    mock_update = MagicMock()
    mock_update.message.reply_text = AsyncMock()
    mock_context = MagicMock()

    mock_autopsy = DailyMoverAutopsy(
        date="2026-09-09",
        market_regime="NORMAL_TRENDING",
        gainers=[
            MoverCausalProfile(
                symbol="TRENT",
                direction="GAINER",
                change_pct=6.5,
                ltp=6850.0,
                volume=2000000,
                turnover_cr=1370.0,
                rvol=2.5,
                deciding_factors=["VCP Supply Dry-Up", "Sector Contagion"],
                archetype="ARCHETYPE_VOLATILITY_CONTRACTION_SPRING",
            )
        ],
        losers=[],
        top_predictive_precursors=["Volume Dry-Up (SNR: +0.65)"],
        traps_filtered=1,
    )

    with patch(
        "engine.mover_autopsy.mover_autopsy_engine.get_latest_autopsy", return_value=mock_autopsy
    ):
        await cmd_movers(mock_update, mock_context)
        assert mock_update.message.reply_text.call_count >= 2
        final_call_args = mock_update.message.reply_text.call_args_list[-1]
        msg_text = final_call_args[0][0]
        assert "DAILY MOVER FORENSIC AUTOPSY" in msg_text
        assert "TRENT" in msg_text
        assert "+6.5%" in msg_text


@pytest.mark.anyio
async def test_cmd_precursors():
    """Verify /precursors command replies with high-conviction candidate list."""
    mock_update = MagicMock()
    mock_update.message.reply_text = AsyncMock()
    mock_context = MagicMock()

    mock_candidates = [
        PrecursorCandidate(
            symbol="INFY",
            exchange="NSE",
            direction="BULLISH",
            conviction_score=86,
            verdict="MAX_CONVICTION",
            sector_name="IT",
            rrg_quadrant="LEADING",
            ltp=1950.0,
            turnover_cr=600.0,
            entry_range="₹1,940 – ₹1,955",
            stop_loss=1915.0,
            target_1=2000.0,
            target_2=2050.0,
            matched_factors=["Volume Dry-up (20% of 20D SMA)", "4-session Squeeze"],
            when_to_wait="DO NOT CHASE if price gaps > 1.8%.",
        )
    ]

    with patch(
        "engine.precursor_radar.precursor_radar.scan_precursors", return_value=mock_candidates
    ):
        await cmd_precursors(mock_update, mock_context)
        assert mock_update.message.reply_text.call_count >= 2
        final_call_args = mock_update.message.reply_text.call_args_list[-1]
        msg_text = final_call_args[0][0]
        assert "PRECURSOR RADAR" in msg_text
        assert "Chanakya" not in msg_text
        assert "INFY" in msg_text
        assert "86/100" in msg_text


@pytest.mark.anyio
async def test_cmd_precursors_with_segment_arg():
    """Verify /precursors cash passes segment filter to scanner."""
    mock_update = MagicMock()
    mock_update.message.reply_text = AsyncMock()
    mock_context = MagicMock()
    mock_context.args = ["cash"]

    with patch(
        "engine.precursor_radar.precursor_radar.scan_precursors", return_value=[]
    ) as mock_scan:
        await cmd_precursors(mock_update, mock_context)
        mock_scan.assert_called_once_with(segment="NON_FNO", top_n=5)
        final_call_args = mock_update.message.reply_text.call_args_list[-1]
        msg_text = final_call_args[0][0]
        assert "CASH" in msg_text


@pytest.mark.anyio
async def test_cmd_movers_with_segment_arg():
    """Verify /movers fno passes segment filter to autopsy engine."""
    mock_update = MagicMock()
    mock_update.message.reply_text = AsyncMock()
    mock_context = MagicMock()
    mock_context.args = ["fno"]

    mock_autopsy = DailyMoverAutopsy(
        date="2026-09-09",
        market_regime="NORMAL",
        gainers=[
            MoverCausalProfile(
                symbol="RELIANCE",
                segment="FNO",
                direction="GAINER",
                change_pct=3.2,
                ltp=3000.0,
                volume=1000000,
                turnover_cr=300.0,
                rvol=2.1,
            )
        ],
        losers=[],
        top_predictive_precursors=[],
    )

    with patch(
        "engine.mover_autopsy.mover_autopsy_engine.get_latest_autopsy", return_value=mock_autopsy
    ):
        await cmd_movers(mock_update, mock_context)
        assert mock_update.message.reply_text.call_count >= 2
        final_call_args = mock_update.message.reply_text.call_args_list[-1]
        msg_text = final_call_args[0][0]
        assert "FNO" in msg_text
        assert "RELIANCE" in msg_text
