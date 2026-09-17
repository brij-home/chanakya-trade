"""
tests/test_eod_report_generator.py
───────────────────────────────────
Unit and integration tests for the Institutional EOD Report Generator,
Telegram chunking, RCA categorization, scheduler hooks, REST API, and CLI.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from engine.eod_report_generator import (
    EODReportGenerator,
    EODReport,
    check_and_trigger_daily_eod,
    get_reports_dir,
    _EOD_GENERATED_TODAY_LOCK,
)


@pytest.fixture
def synthetic_alerts_file(tmp_path):
    """Creates a temporary auto_alerts.json file with diverse test alerts."""
    alerts = [
        # 1. Winner reaching T1 & T2
        {
            "alert_id": "al-win-1",
            "alert_type": "GAMMA_BLAST",
            "stage": "IGNITED",
            "symbol": "NIFTY 25350 CE",
            "segment": "FNO",
            "direction": "BULLISH",
            "ltp": 150.0,
            "trigger_level": 100.0,
            "stop_loss": 72.0,
            "target_level": 138.0,
            "target_status": "T2_ACHIEVED",
            "achieved_milestones": ["T0.5", "T1", "T2"],
            "created_at": "2026-09-17 09:35:00 IST",
            "is_invalidated": False,
        },
        # 2. Winner reaching T0.5
        {
            "alert_id": "al-win-2",
            "alert_type": "SQUEEZE_BREAKOUT",
            "stage": "IGNITED",
            "symbol": "BANKNIFTY 54800 CE",
            "segment": "FNO",
            "direction": "BULLISH",
            "ltp": 375.0,
            "trigger_level": 320.0,
            "stop_loss": 230.0,
            "target_level": 420.0,
            "target_status": "PENDING",
            "achieved_milestones": ["T0.5"],
            "created_at": "2026-09-17 10:15:00 IST",
            "is_invalidated": False,
        },
        # 3. Stopped out — Premature SL / Wick
        {
            "alert_id": "al-loss-1",
            "alert_type": "GAMMA_BLAST",
            "stage": "INVALIDATED",
            "symbol": "SENSEX 82500 PE",
            "segment": "FNO",
            "direction": "BEARISH",
            "ltp": 60.0,
            "trigger_level": 100.0,
            "stop_loss": 80.0,
            "target_level": 140.0,
            "target_status": "PENDING",
            "achieved_milestones": [],
            "created_at": "2026-09-17 11:00:00 IST",
            "is_invalidated": True,
            "invalidation_reason": "Option premium stop hit on 20-SMA micro-wick noise.",
        },
        # 4. Stopped out — Missed Target 1 Reversal
        {
            "alert_id": "al-loss-2",
            "alert_type": "MINERVINI_SEPA",
            "stage": "INVALIDATED",
            "symbol": "RELIANCE 2980 CE",
            "segment": "FNO",
            "direction": "BULLISH",
            "ltp": 18.0,
            "trigger_level": 30.0,
            "stop_loss": 21.0,
            "target_level": 45.0,
            "target_status": "PENDING",
            "achieved_milestones": [],
            "created_at": "2026-09-17 11:30:00 IST",
            "is_invalidated": True,
            "invalidation_reason": "Gained +22% but missed Target 1 and reversed into SL.",
        },
        # 5. Stopped out — Theta Stagnation
        {
            "alert_id": "al-loss-3",
            "alert_type": "GAMMA_BLAST",
            "stage": "INVALIDATED",
            "symbol": "MIDCPNIFTY 13150 CE",
            "segment": "FNO",
            "direction": "BULLISH",
            "ltp": 25.0,
            "trigger_level": 40.0,
            "stop_loss": 28.0,
            "target_level": 60.0,
            "target_status": "PENDING",
            "achieved_milestones": [],
            "created_at": "2026-09-17 12:45:00 IST",
            "is_invalidated": True,
            "invalidation_reason": "Theta decay bleed during 20m stagnation.",
        },
        # 6. Stopped out — Structural Invalidation
        {
            "alert_id": "al-loss-4",
            "alert_type": "SMC_SWEEP",
            "stage": "INVALIDATED",
            "symbol": "INFY",
            "segment": "EQUITY",
            "direction": "BULLISH",
            "ltp": 1880.0,
            "trigger_level": 1920.0,
            "stop_loss": 1895.0,
            "target_level": 1980.0,
            "target_status": "PENDING",
            "achieved_milestones": [],
            "created_at": "2026-09-17 13:10:00 IST",
            "is_invalidated": True,
            "invalidation_reason": "Structural Order Block floor breached on heavy selling volume.",
        },
        # 7. In-flight alert
        {
            "alert_id": "al-inflight-1",
            "alert_type": "PRECURSOR_RADAR",
            "stage": "IGNITED",
            "symbol": "TITAN",
            "segment": "EQUITY",
            "direction": "BULLISH",
            "ltp": 3450.0,
            "trigger_level": 3440.0,
            "stop_loss": 3400.0,
            "target_level": 3520.0,
            "target_status": "PENDING",
            "achieved_milestones": [],
            "created_at": "2026-09-17 14:00:00 IST",
            "is_invalidated": False,
        },
    ]
    alerts_path = tmp_path / "auto_alerts.json"
    alerts_path.write_text(json.dumps(alerts, indent=2), encoding="utf-8")
    return alerts_path


def test_eod_report_generation_and_metrics(synthetic_alerts_file, tmp_path, monkeypatch):
    """Verify quantitative metrics calculated from synthetic alerts."""
    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))
    gen = EODReportGenerator(data_file=synthetic_alerts_file)

    report = gen.generate(target_date="2026-09-17")
    assert report.date_str == "2026-09-17"
    assert report.total_alerts == 7
    assert report.ignited_trades == 7
    assert report.win_count == 2  # al-win-1 and al-win-2
    assert report.loss_count == 4  # 4 stopped setups
    assert report.in_flight_count == 1
    assert report.win_rate_pct == pytest.approx(33.3, 0.5)
    assert len(report.star_setups) == 2
    assert len(report.stopped_setups) == 4


def test_eod_report_rca_categorization(synthetic_alerts_file, tmp_path, monkeypatch):
    """Verify RCA decomposition maps failures to distinct categories."""
    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))
    gen = EODReportGenerator(data_file=synthetic_alerts_file)
    report = gen.generate(target_date="2026-09-17")

    categories = {rca.category for rca in report.rca_breakdown}
    assert "PREMATURE_STOP_LOSS" in categories
    assert "MISSED_TARGET_1_REVERSAL" in categories
    assert "THETA_STAGNATION_BLEED" in categories
    assert "STRUCTURAL_INVALIDATION" in categories


def test_eod_report_markdown_and_telegram_chunks(synthetic_alerts_file, tmp_path, monkeypatch):
    """Verify markdown output and Telegram message boundary constraints (<4000 chars)."""
    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))
    gen = EODReportGenerator(data_file=synthetic_alerts_file)
    report = gen.generate(target_date="2026-09-17")

    # Markdown format checks
    md = report.to_markdown()
    assert "# 🏛️ CHANAKYATRADE INSTITUTIONAL EOD REPORT" in md
    assert "Executive Scorecard" in md
    assert "What Went Well" in md
    assert "Root Cause Analysis (RCA)" in md
    assert "What Could Have Been Done Better" in md
    assert "How to Make the System Better" in md
    assert "Strategic Recommendations for Tomorrow" in md

    # Telegram chunks checks
    chunks = report.to_telegram_chunks()
    assert len(chunks) == 3
    for idx, c in enumerate(chunks):
        assert len(c) <= 4000, f"Chunk {idx+1} exceeded 4000 characters ({len(c)})"
        assert "<b>" in c and "</b>" in c


def test_eod_report_persistence(synthetic_alerts_file, tmp_path, monkeypatch):
    """Verify JSON and Markdown files are created in reports directory."""
    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))
    gen = EODReportGenerator(data_file=synthetic_alerts_file)
    report = gen.generate(target_date="2026-09-17")

    json_p, md_p = gen.save_to_disk(report)
    assert json_p.exists()
    assert md_p.exists()
    loaded = json.loads(json_p.read_text(encoding="utf-8"))
    assert loaded["date_str"] == "2026-09-17"


def test_eod_report_dispatch_telegram_mock(synthetic_alerts_file, tmp_path, monkeypatch):
    """Verify Telegram dispatch with mocked API response and plain text retry."""
    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))
    monkeypatch.delenv("CHANAKYA_TESTING", raising=False)
    monkeypatch.setattr("bot.telegram_bot._get_bot_token", lambda: "mock_token_123")
    monkeypatch.setattr("bot.telegram_bot._load_chat_id", lambda: "1225164824")

    posted_payloads = []

    def mock_post(url, json=None, **kwargs):
        posted_payloads.append(json)
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.status_code = 200
        return mock_resp

    with patch("httpx.post", side_effect=mock_post):
        gen = EODReportGenerator(data_file=synthetic_alerts_file)
        report = gen.generate(target_date="2026-09-17")
        success = gen.dispatch_to_telegram(report, chat_id="1225164824")
        assert success is True
        assert len(posted_payloads) == 3


def test_daily_eod_scheduler_hook(synthetic_alerts_file, tmp_path, monkeypatch):
    """Verify automatic scheduler hook triggers and respects lock."""
    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))
    _EOD_GENERATED_TODAY_LOCK.clear()

    with patch("engine.eod_report_generator.EODReportGenerator._load_alerts", return_value=[]):
        # Force trigger
        rep = check_and_trigger_daily_eod(force=True)
        assert rep is not None
        # Second call without force should be blocked by lock
        rep2 = check_and_trigger_daily_eod(force=False)
        assert rep2 is None


def test_eod_api_endpoints():
    """Verify FastAPI GET /api/reports/eod and POST /skills/eod_report endpoints."""
    from web.api import app

    client = TestClient(app)

    # 1. GET /api/reports/eod
    res1 = client.get("/api/reports/eod?date=2026-09-17")
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["status"] == "ok"
    assert "data" in data1
    assert data1["data"]["date_str"] == "2026-09-17"

    # 2. POST /skills/eod_report
    res2 = client.post("/skills/eod_report", json={"date": "2026-09-17"})
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["status"] == "ok"
    assert "data" in data2


def test_telegram_bot_cmd_eod():
    """Verify /eod command handler in bot/telegram_bot.py."""
    import asyncio
    from bot.telegram_bot import cmd_eod

    mock_update = MagicMock()
    mock_update.message.reply_text = MagicMock()

    # Create an async mock for reply_text
    async def async_reply(text, **kwargs):
        return MagicMock()

    mock_update.message.reply_text.side_effect = async_reply

    mock_context = MagicMock()
    mock_context.args = ["2026-09-17"]

    asyncio.run(cmd_eod(mock_update, mock_context))
    assert mock_update.message.reply_text.call_count >= 2
