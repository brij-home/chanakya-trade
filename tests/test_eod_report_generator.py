"""
tests/test_eod_report_generator.py
───────────────────────────────────
Unit and integration tests for the Institutional EOD Report Generator,
Telegram chunking, RCA categorization, scheduler hooks, REST API, and CLI.
"""

import json
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from engine.eod_report_generator import (
    EODReportGenerator,
    check_and_trigger_daily_eod,
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
        assert len(c) <= 4000, f"Chunk {idx + 1} exceeded 4000 characters ({len(c)})"
        assert "<b>" in c and "</b>" in c


def test_eod_report_persistence(synthetic_alerts_file, tmp_path, monkeypatch):
    """Verify JSON, Markdown, and Excel files are created in reports directory."""
    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))
    gen = EODReportGenerator(data_file=synthetic_alerts_file)
    report = gen.generate(target_date="2026-09-17")

    json_p, md_p = gen.save_to_disk(report)
    assert json_p.exists()
    assert md_p.exists()
    xlsx_p = tmp_path / "reports" / f"eod_{report.date_str}.xlsx"
    assert xlsx_p.exists()
    loaded = json.loads(json_p.read_text(encoding="utf-8"))
    assert loaded["date_str"] == "2026-09-17"


def test_eod_report_excel_generation(synthetic_alerts_file, tmp_path, monkeypatch):
    """Verify Excel workbook generation across all 5 institutional tabs."""
    import openpyxl

    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))
    gen = EODReportGenerator(data_file=synthetic_alerts_file)
    report = gen.generate(target_date="2026-09-17")

    xlsx_path = tmp_path / "reports" / "test_eod.xlsx"
    out_path = report.to_excel(xlsx_path)
    assert out_path.exists()
    assert out_path.stat().st_size > 0

    wb = openpyxl.load_workbook(str(out_path))
    expected_sheets = [
        "1_Executive_Summary",
        "2_Trading_Journal",
        "3_Strategy_Efficacy",
        "4_Forensic_RCA",
        "5_Tomorrow_Playbook",
    ]
    for s_name in expected_sheets:
        assert s_name in wb.sheetnames, f"Missing sheet: {s_name}"

    # Verify Journal Sheet
    ws_journal = wb["2_Trading_Journal"]
    assert ws_journal.max_row >= 2
    # Verify auto filter was applied
    assert ws_journal.auto_filter.ref is not None


def test_eod_report_dispatch_telegram_mock(synthetic_alerts_file, tmp_path, monkeypatch):
    """Verify Telegram dispatch sends 3 message chunks AND attaches the Excel workbook."""
    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))
    monkeypatch.delenv("CHANAKYA_TESTING", raising=False)
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "1225164824")
    monkeypatch.setattr("bot.telegram_bot._get_bot_token", lambda: "mock_token_123")
    monkeypatch.setattr("bot.telegram_bot._load_chat_id", lambda: "1225164824")

    posted_calls = []

    def mock_post(url, json=None, data=None, files=None, **kwargs):
        posted_calls.append({"url": url, "json": json, "data": data, "files": files})
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.status_code = 200
        return mock_resp

    with patch("httpx.post", side_effect=mock_post):
        gen = EODReportGenerator(data_file=synthetic_alerts_file)
        report = gen.generate(target_date="2026-09-17")
        success = gen.dispatch_to_telegram(report, chat_id="1225164824")
        assert success is True

        # Exactly 3 sendMessage chunks and 1 sendDocument call
        msg_calls = [c for c in posted_calls if c["url"].endswith("/sendMessage")]
        doc_calls = [c for c in posted_calls if c["url"].endswith("/sendDocument")]

        assert len(msg_calls) == 3
        assert len(doc_calls) == 1
        assert doc_calls[0]["data"]["chat_id"] == "1225164824"
        assert "document" in doc_calls[0]["files"]


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


def test_eod_report_persistent_disk_lock(tmp_path, monkeypatch):
    """Verify that file-backed lock prevents re-triggering across process restarts."""
    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    lock_file = reports_dir / ".eod_dispatch_lock.json"

    from datetime import datetime
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
    today_str = datetime.now(IST).strftime("%Y-%m-%d")

    # Simulate that an EOD report was already generated & dispatched earlier today
    lock_data = {
        today_str: {
            "generated_at": "16:00:00 IST",
            "dispatched_telegram": True,
            "total_alerts": 10,
            "win_rate_pct": 70.0,
            "total_realized_r": 5.4,
        }
    }
    lock_file.write_text(json.dumps(lock_data), encoding="utf-8")

    # Clear in-memory set (simulating clean service restart)
    _EOD_GENERATED_TODAY_LOCK.clear()

    # Attempt trigger without force — MUST return None immediately without re-dispatching
    result = check_and_trigger_daily_eod(force=False)
    assert result is None, "Should not trigger on restart if already dispatched on disk today"

    # Attempt trigger with force=True — MUST bypass lock
    with patch("engine.eod_report_generator.EODReportGenerator._load_alerts", return_value=[]):
        forced_report = check_and_trigger_daily_eod(force=True)
        assert forced_report is not None


def test_eod_report_tabular_journal_and_accurate_attribution(tmp_path, monkeypatch):
    """Verify accurate classification of untriggered setups, EOD cutoffs, and velocity scratches."""
    alerts = [
        # 1. Untriggered setup: Radar alert that expired without entry trigger
        {
            "alert_id": "al-untrig-1",
            "alert_type": "PRECURSOR_RADAR",
            "stage": "EXPIRED",
            "symbol": "INFY",
            "segment": "EQUITY",
            "direction": "BULLISH",
            "ltp": 1920.0,
            "trigger_level": 1935.0,
            "stop_loss": 1910.0,
            "target_level": 1980.0,
            "target_status": "PENDING",
            "achieved_milestones": [],
            "created_at": "2026-09-24 10:00:00 IST",
            "is_invalidated": True,
            "invalidation_reason": "Time-Stop expired: Setup did not trigger within 60-minute momentum window.",
        },
        # 2. Session cutoff: Closed at 15:15 IST cutoff
        {
            "alert_id": "al-eod-1",
            "alert_type": "SQUEEZE_BREAKDOWN",
            "stage": "INVALIDATED",
            "symbol": "TCS",
            "segment": "FNO_STOCK",
            "direction": "BEARISH",
            "ltp": 4200.0,
            "trigger_level": 4210.0,
            "stop_loss": 4240.0,
            "target_level": 4120.0,
            "target_status": "INVALIDATED",
            "achieved_milestones": [],
            "created_at": "2026-09-24 13:45:00 IST",
            "is_invalidated": True,
            "invalidation_reason": "Intraday session expired (15:15 IST cutoff reached). Trade closed.",
        },
        # 3. Velocity time-stop exit: Early capital defense
        {
            "alert_id": "al-vel-1",
            "alert_type": "INTRADAY_BREAKDOWN_SPARK",
            "stage": "TIME_STOP_EXIT",
            "symbol": "WIPRO",
            "segment": "EQUITY",
            "direction": "BEARISH",
            "ltp": 540.0,
            "trigger_level": 542.0,
            "stop_loss": 548.0,
            "target_level": 526.0,
            "target_status": "TIME_STOP_EXIT",
            "achieved_milestones": [],
            "created_at": "2026-09-24 11:15:00 IST",
            "is_invalidated": True,
            "invalidation_reason": "⏱️ VELOCITY TIME-STOP: Trade active for 31m without momentum expansion (P&L: +0.3%). Scratched early.",
        },
        # 4. Target winner
        {
            "alert_id": "al-win-star",
            "alert_type": "GAMMA_BLAST",
            "stage": "IGNITED",
            "symbol": "ETERNAL",
            "segment": "FNO_STOCK",
            "direction": "BEARISH",
            "ltp": 13.85,
            "trigger_level": 12.85,
            "stop_loss": 11.50,
            "target_level": 13.85,
            "target_status": "TARGET_ACHIEVED",
            "achieved_milestones": ["T1", "T2"],
            "created_at": "2026-09-24 09:35:00 IST",
            "is_invalidated": False,
        },
    ]

    alerts_path = tmp_path / "auto_alerts.json"
    alerts_path.write_text(json.dumps(alerts, indent=2), encoding="utf-8")
    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))

    gen = EODReportGenerator(data_file=alerts_path)
    report = gen.generate(target_date="2026-09-24")

    # Assertions on accurate attribution
    assert report.total_alerts == 4
    assert report.untriggered_count == 1  # INFY did not trigger
    assert report.ignited_trades == 3     # TCS, WIPRO, ETERNAL
    assert report.win_count == 1          # ETERNAL
    assert report.loss_count == 0         # No true SL breaches!
    assert report.scratch_count == 1      # WIPRO velocity time-stop
    assert report.eod_squareoff_count == 1 # TCS 15:15 session cutoff

    # Trading journal verification
    assert len(report.journal_entries) == 4
    journal_outcomes = {j.outcome for j in report.journal_entries}
    assert "UNTRIGGERED_EXPIRED" in journal_outcomes
    assert "SESSION_EOD_SQUAREOFF" in journal_outcomes
    assert "VELOCITY_TIME_STOP" in journal_outcomes
    assert "WIN_TARGET" in journal_outcomes

    # Markdown format verification
    md = report.to_markdown()
    assert "## 2. 📓 Institutional Trading Journal (Crux Recap)" in md
    assert "## 3. 🎯 Strategy & Detector Efficacy Journal" in md
    assert "ETERNAL" in md
    assert "TARGET_HIT" in md
    assert "UNTRIGGERED" in md
    assert "EOD_SQUAREOFF" in md


def test_eod_report_telegram_vs_ui_segregation(tmp_path, monkeypatch):
    """Verify clean segregation between Telegram dispatched trades and UI terminal universe."""
    import openpyxl

    alerts = [
        # 1. Telegram Winner (Target hit)
        {
            "alert_id": "tg-win-1",
            "alert_type": "GAMMA_BLAST",
            "stage": "IGNITED",
            "symbol": "NIFTY 25400 CE",
            "segment": "FNO",
            "direction": "BULLISH",
            "ltp": 160.0,
            "trigger_level": 100.0,
            "stop_loss": 70.0,
            "target_level": 140.0,
            "target_status": "T1_ACHIEVED",
            "achieved_milestones": ["T1"],
            "created_at": "2026-09-24 09:30:00 IST",
            "is_invalidated": False,
            "telegram_dispatched": True,
        },
        # 2. Telegram Stopped Loss
        {
            "alert_id": "tg-loss-1",
            "alert_type": "GAMMA_BLAST",
            "stage": "INVALIDATED",
            "symbol": "BANKNIFTY 54500 PE",
            "segment": "FNO",
            "direction": "BEARISH",
            "ltp": 50.0,
            "trigger_level": 80.0,
            "stop_loss": 60.0,
            "target_level": 120.0,
            "target_status": "PENDING",
            "achieved_milestones": [],
            "created_at": "2026-09-24 10:30:00 IST",
            "is_invalidated": True,
            "invalidation_reason": "Stop-loss hit on structural break.",
            "telegram_dispatched": True,
        },
        # 3. Telegram Scratch (Velocity)
        {
            "alert_id": "tg-scratch-1",
            "alert_type": "INTRADAY_MOMENTUM_SPARK",
            "stage": "TIME_STOP_EXIT",
            "symbol": "TATASTEEL",
            "segment": "EQUITY",
            "direction": "BULLISH",
            "ltp": 150.0,
            "trigger_level": 150.0,
            "stop_loss": 146.0,
            "target_level": 158.0,
            "target_status": "TIME_STOP_EXIT",
            "achieved_milestones": [],
            "created_at": "2026-09-24 11:00:00 IST",
            "is_invalidated": True,
            "invalidation_reason": "Velocity time-stop expired. Stagnated for 35m.",
            "telegram_dispatched": True,
        },
        # 4. UI-only Winner (Scale BE)
        {
            "alert_id": "ui-win-1",
            "alert_type": "SQUEEZE_BREAKOUT",
            "stage": "IGNITED",
            "symbol": "RELIANCE",
            "segment": "EQUITY",
            "direction": "BULLISH",
            "ltp": 3020.0,
            "trigger_level": 3000.0,
            "stop_loss": 2980.0,
            "target_level": 3050.0,
            "target_status": "PENDING",
            "achieved_milestones": ["T0.5"],
            "created_at": "2026-09-24 11:30:00 IST",
            "is_invalidated": False,
            "telegram_dispatched": False,
        },
        # 5. UI-only Untriggered
        {
            "alert_id": "ui-untrig-1",
            "alert_type": "PRECURSOR_RADAR",
            "stage": "EXPIRED",
            "symbol": "HDFCBANK",
            "segment": "EQUITY",
            "direction": "BULLISH",
            "ltp": 1650.0,
            "trigger_level": 1670.0,
            "stop_loss": 1640.0,
            "target_level": 1720.0,
            "target_status": "PENDING",
            "achieved_milestones": [],
            "created_at": "2026-09-24 12:00:00 IST",
            "is_invalidated": True,
            "invalidation_reason": "Time-Stop expired: Setup did not trigger.",
            "telegram_dispatched": False,
        },
    ]

    alerts_path = tmp_path / "auto_alerts.json"
    alerts_path.write_text(json.dumps(alerts, indent=2), encoding="utf-8")
    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))

    gen = EODReportGenerator(data_file=alerts_path)
    report = gen.generate(target_date="2026-09-24")

    # 1. Verification of Total Universe Metrics
    assert report.total_alerts == 5
    assert report.ignited_trades == 4
    assert report.untriggered_count == 1

    # 2. Verification of Telegram Segregated Metrics
    assert report.telegram_total_alerts == 3
    assert report.telegram_ignited_trades == 3
    assert report.telegram_win_count == 1
    assert report.telegram_loss_count == 1
    assert report.telegram_scratch_count == 1
    assert report.telegram_win_rate_pct == pytest.approx(50.0, 0.1)
    assert report.telegram_total_realized_r > 0
    assert len(report.telegram_star_setups) == 1
    assert len(report.telegram_stopped_setups) == 1

    # 3. Verification of UI-only Segregated Metrics
    assert report.ui_total_alerts == 2
    assert report.ui_ignited_trades == 1
    assert report.ui_untriggered_count == 1
    assert report.ui_win_count == 1
    assert report.ui_loss_count == 0

    # 4. Verification of Markdown Output
    md = report.to_markdown()
    assert "### 📱 Executive Summary: Telegram Trader Feed vs 🖥️ UI Scanner Universe" in md
    assert "📱 TELEGRAM" in md
    assert "🖥️ UI ONLY" in md

    # 5. Verification of Telegram Chunks
    chunks = report.to_telegram_chunks()
    assert "📱 <b>1. TELEGRAM TRADER FEED" in chunks[0]
    assert "🖥️ <b>2. UI SCANNER RADAR" in chunks[0]
    assert "📱TG" in chunks[0]

    # 6. Verification of Excel Workbook Tabs & Columns
    xlsx_path = tmp_path / "reports" / "test_segregation.xlsx"
    report.to_excel(xlsx_path)
    wb = openpyxl.load_workbook(str(xlsx_path))
    assert "2_Telegram_Trades" in wb.sheetnames
    assert "2_Trading_Journal" in wb.sheetnames
    ws_tg = wb["2_Telegram_Trades"]
    assert ws_tg.cell(row=1, column=2).value == "Channel"
    # Ensure only 3 Telegram setups are in ws_tg (header row + 3 entries = 4 rows)
    assert ws_tg.max_row == 4
    for r in range(2, 5):
        assert ws_tg.cell(row=r, column=2).value == "📱 TELEGRAM"

    ws_all = wb["2_Trading_Journal"]
    assert ws_all.max_row == 6  # header + 5 alerts

