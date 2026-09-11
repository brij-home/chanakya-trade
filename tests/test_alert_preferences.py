"""
tests/test_alert_preferences.py
───────────────────────────────
Unit and integration tests for Alert Preferences, Segment Classification,
and Multi-Channel Alert Routing (UI, Telegram, Desktop).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from engine.alert_preferences import (
    CANONICAL_SEGMENTS,
    AlertPreferences,
    AlertPreferencesManager,
    classify_alert_segment,
)
from engine.auto_alert_engine import AutoAlert, AutoAlertEngine, auto_alert_engine


def test_classify_alert_segment():
    """Verify deterministic classification of market alerts across asset classes."""
    # 1. Commodity (MCX)
    assert classify_alert_segment({"symbol": "CRUDEOIL", "exchange": "MCX"}) == "COMMODITY"
    assert classify_alert_segment({"symbol": "MCX:GOLD", "exchange": "MCX"}) == "COMMODITY"
    assert classify_alert_segment({"symbol": "SILVER", "exchange": "MCX"}) == "COMMODITY"
    assert classify_alert_segment({"symbol": "NATURALGAS"}) == "COMMODITY"
    assert classify_alert_segment({"alert_type": "COMMODITY_MOMENTUM", "symbol": "COPPER"}) == "COMMODITY"

    # 2. Currency (CDS)
    assert classify_alert_segment({"symbol": "USDINR", "exchange": "CDS"}) == "CURRENCY"
    assert classify_alert_segment({"symbol": "CDS:EURINR", "exchange": "CDS"}) == "CURRENCY"
    assert classify_alert_segment({"symbol": "GBPINR"}) == "CURRENCY"
    assert classify_alert_segment({"alert_type": "CURRENCY_BREAKOUT", "symbol": "USDINR"}) == "CURRENCY"

    # 3. F&O / Derivatives — Index vs Stock
    assert classify_alert_segment({"symbol": "NIFTY", "exchange": "NSE"}) == "FNO_INDEX"
    assert classify_alert_segment({"symbol": "BANKNIFTY", "exchange": "NSE"}) == "FNO_INDEX"
    assert classify_alert_segment({"symbol": "FINNIFTY", "exchange": "NSE"}) == "FNO_INDEX"
    assert classify_alert_segment({"symbol": "MIDCPNIFTY", "segment": "INDEX"}) == "FNO_INDEX"
    assert classify_alert_segment({"symbol": "SENSEX", "exchange": "BSE"}) == "FNO_INDEX"

    assert classify_alert_segment({"symbol": "RELIANCE", "contract_symbol": "RELIANCE26SEPFUT"}) == "FNO_STOCK"
    assert classify_alert_segment({"symbol": "INFY", "option_type": "CE", "strike": 1900.0}) == "FNO_STOCK"
    assert classify_alert_segment({"alert_type": "GAMMA_BLAST", "symbol": "TCS"}) == "FNO_STOCK"
    assert classify_alert_segment({"alert_type": "OPTIONS_MOMENTUM", "symbol": "HDFCBANK"}) == "FNO_STOCK"

    # 4. Cash Equity
    assert classify_alert_segment({"symbol": "TATASTEEL", "exchange": "NSE"}) == "EQUITY"
    assert classify_alert_segment({"symbol": "ZOMATO", "exchange": "NSE"}) == "EQUITY"
    assert classify_alert_segment({"alert_type": "POCKET_PIVOT", "symbol": "KAYNES"}) == "EQUITY"
    assert classify_alert_segment({"alert_type": "SQUEEZE_BREAKOUT", "symbol": "DIXON"}) == "EQUITY"

    # Dataclass instances
    alt_opt = AutoAlert(
        alert_id="a1",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY CE Gamma Surge",
        summary="Test",
        ltp=150.0,
        trigger_level=140.0,
        target_level=200.0,
        stop_loss=110.0,
        option_type="CE",
        strike=25000.0,
    )
    assert classify_alert_segment(alt_opt) == "FNO_INDEX"
    assert alt_opt.segment == "FNO_INDEX"

    alt_stk = AutoAlert(
        alert_id="a_stk",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="RELIANCE",
        contract_symbol="RELIANCE26SEP3000CE",
        exchange="NFO",
        direction="BULLISH",
        headline="RELIANCE CE Gamma Surge",
        summary="Test",
        ltp=45.0,
        trigger_level=42.0,
        target_level=60.0,
        stop_loss=32.0,
        option_type="CE",
        strike=3000.0,
    )
    assert classify_alert_segment(alt_stk) == "FNO_STOCK"
    assert alt_stk.segment == "FNO_STOCK"

    alt_comm = AutoAlert(
        alert_id="a2",
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        symbol="CRUDEOIL",
        exchange="MCX",
        direction="BULLISH",
        headline="Crude Breakout",
        summary="Inventory drop",
        ltp=6100.0,
        trigger_level=6050.0,
        target_level=6300.0,
        stop_loss=5950.0,
    )
    assert classify_alert_segment(alt_comm) == "COMMODITY"
    assert alt_comm.segment == "COMMODITY"


def test_alert_preferences_manager(tmp_path):
    """Verify preference persistence, multi-select, and channel gating."""
    test_pref_file = tmp_path / "test_alert_prefs.json"

    mgr = AlertPreferencesManager()
    mgr._pref_file = test_pref_file
    mgr._preferences = AlertPreferences()
    mgr._save()

    # Initial state: all allowed
    prefs = mgr.get_preferences()
    assert set(prefs["allowed_segments"]) == set(CANONICAL_SEGMENTS)
    assert mgr.is_segment_allowed("FNO_INDEX", "ui") is True
    assert mgr.is_segment_allowed("FNO_STOCK", "ui") is True
    assert mgr.is_segment_allowed("FNO", "ui") is True  # Alias check
    assert mgr.is_segment_allowed("COMMODITY", "telegram") is True

    # Configure Telegram to ONLY allow FNO_INDEX (Silencing Stock F&O, Equity, Commodity)
    mgr.update_preferences({
        "telegram": {
            "enabled": True,
            "allowed_segments": ["FNO_INDEX"],
            "min_confidence": 80,
        }
    })

    assert mgr.is_segment_allowed("FNO_INDEX", "telegram") is True
    assert mgr.is_segment_allowed("FNO_STOCK", "telegram") is False
    assert mgr.is_segment_allowed("EQUITY", "telegram") is False
    assert mgr.is_segment_allowed("COMMODITY", "telegram") is False
    assert mgr.is_segment_allowed("CURRENCY", "telegram") is False

    # Check alert gating
    index_alert = {"symbol": "NIFTY", "option_type": "CE", "confidence": 85, "stage": "IGNITED"}
    stock_alert = {"symbol": "RELIANCE", "contract_symbol": "RELIANCE26SEPFUT", "confidence": 90, "stage": "IGNITED"}
    comm_alert = {"symbol": "CRUDEOIL", "exchange": "MCX", "confidence": 95, "stage": "IGNITED"}

    # Index FNO is allowed on both UI and Telegram
    assert mgr.is_alert_allowed(index_alert, "ui") is True
    assert mgr.is_alert_allowed(index_alert, "telegram") is True

    # Stock FNO is allowed on UI, but BLOCKED on Telegram!
    assert mgr.is_alert_allowed(stock_alert, "ui") is True
    assert mgr.is_alert_allowed(stock_alert, "telegram") is False

    # Commodity is allowed on UI, but BLOCKED on Telegram!
    assert mgr.is_alert_allowed(comm_alert, "ui") is True
    assert mgr.is_alert_allowed(comm_alert, "telegram") is False

    # Check legacy FNO alias update
    mgr.update_preferences({
        "allowed_segments": ["FNO", "EQUITY"],
        "ui": {"allowed_segments": ["FNO", "EQUITY"]},
        "desktop": {"allowed_segments": ["FNO", "EQUITY"]},
        "telegram": {"allowed_segments": ["FNO", "EQUITY"]},
    })
    # Legacy "FNO" expands to both FNO_INDEX and FNO_STOCK
    assert mgr.is_segment_allowed("FNO_INDEX", "telegram") is True
    assert mgr.is_segment_allowed("FNO_STOCK", "telegram") is True
    assert mgr.is_segment_globally_disabled("COMMODITY") is True
    assert mgr.is_segment_globally_disabled("FNO_INDEX") is False


def test_auto_alert_engine_dispatch_routing(monkeypatch, tmp_path):
    """Verify that AutoAlertEngine._dispatch obeys Telegram and UI preference routing."""
    from engine.alert_preferences import alert_preferences

    # Direct preferences to tmp file
    monkeypatch.setattr(alert_preferences, "_pref_file", tmp_path / "prefs.json")
    alert_preferences.update_preferences({
        "telegram": {
            "enabled": True,
            "allowed_segments": ["FNO_INDEX"],  # Only Index FNO permitted on Telegram
            "min_confidence": 80,
        },
        "ui": {
            "enabled": True,
            "allowed_segments": ["FNO_INDEX", "FNO_STOCK", "COMMODITY"],
        }
    })

    tg_sent = []

    monkeypatch.setattr("engine.alerts._telegram_notify", lambda msg: tg_sent.append(msg))
    monkeypatch.setattr("engine.alerts._is_market_hours", lambda exch: True)

    engine = AutoAlertEngine()

    # 1. Commodity alert -> Should be blocked from Telegram!
    comm_alert = AutoAlert(
        alert_id="live-comm-001",
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        symbol="CRUDEOIL",
        exchange="MCX",
        direction="BULLISH",
        headline="CRUDE OIL IGNITED",
        summary="Crude inventory surge",
        ltp=6100.0,
        trigger_level=6050.0,
        target_level=6300.0,
        stop_loss=5950.0,
        confidence=90,
        is_live=True,
        environment="LIVE",
    )

    engine._dispatch(comm_alert)
    assert len(tg_sent) == 0  # Silenced on Telegram!

    # 2. Stock F&O alert -> Should also be blocked from Telegram since only FNO_INDEX is subscribed!
    stock_fno_alert = AutoAlert(
        alert_id="live-stk-001",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="RELIANCE",
        contract_symbol="RELIANCE26SEP3000CE",
        exchange="NFO",
        direction="BULLISH",
        headline="RELIANCE 3000 CE GAMMA SURGE",
        summary="Stock Call OI surge",
        ltp=45.0,
        trigger_level=42.0,
        target_level=60.0,
        stop_loss=32.0,
        option_type="CE",
        strike=3000.0,
        confidence=88,
        is_live=True,
        environment="LIVE",
    )
    engine._dispatch(stock_fno_alert)
    assert len(tg_sent) == 0  # Silenced on Telegram!

    # 3. Index FNO alert -> Should be sent to Telegram!
    fno_alert = AutoAlert(
        alert_id="live-fno-001",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY 25000 CE GAMMA SURGE",
        summary="Call OI unwinding",
        ltp=150.0,
        trigger_level=140.0,
        target_level=220.0,
        stop_loss=110.0,
        option_type="CE",
        strike=25000.0,
        confidence=92,
        is_live=True,
        environment="LIVE",
    )

    engine._dispatch(fno_alert)
    assert len(tg_sent) == 1  # Successfully dispatched!


def test_api_alert_preferences_endpoints():
    """Verify GET and POST /api/alerts/preferences and /skills/alerts/preferences."""
    from web.api import app

    client = TestClient(app)

    # 1. GET preferences
    res = client.get("/api/alerts/preferences")
    assert res.status_code == 200
    data = res.json()["data"]
    assert "allowed_segments" in data
    assert "telegram" in data

    # 2. POST update preferences
    update_payload = {
        "allowed_segments": ["FNO_INDEX", "EQUITY"],
        "telegram": {
            "enabled": True,
            "allowed_segments": ["FNO_INDEX"],
            "min_confidence": 85,
        }
    }
    res_post = client.post("/api/alerts/preferences", json=update_payload)
    assert res_post.status_code == 200
    updated_data = res_post.json()["data"]
    assert updated_data["allowed_segments"] == ["FNO_INDEX", "EQUITY"]
    assert updated_data["telegram"]["allowed_segments"] == ["FNO_INDEX"]
    assert updated_data["telegram"]["min_confidence"] == 85

    # 3. GET via skills router
    res_skills = client.get("/skills/alerts/preferences")
    assert res_skills.status_code == 200
    assert res_skills.json()["data"]["allowed_segments"] == ["FNO_INDEX", "EQUITY"]


@pytest.mark.anyio
async def test_telegram_cmd_filter(monkeypatch):
    """Verify Telegram /filter command shows status and updates allowed segments."""
    from bot.telegram_bot import cmd_filter
    from engine.alert_preferences import alert_preferences

    # Mock Update and Context
    mock_update = MagicMock()
    mock_message = AsyncMock()
    mock_update.message = mock_message
    mock_context = MagicMock()

    # 1. No args -> view active status
    mock_context.args = []
    await cmd_filter(mock_update, mock_context)
    assert mock_message.reply_text.called
    call_args = mock_message.reply_text.call_args[0][0]
    assert "TELEGRAM ALERT ROUTING" in call_args
    assert "Subscribed Segments:" in call_args

    # 2. With args -> update to fno_indices,equity
    mock_context.args = ["fno_indices,", "equity"]
    await cmd_filter(mock_update, mock_context)
    call_args2 = mock_message.reply_text.call_args[0][0]
    assert "Telegram Alert Segments Updated:" in call_args2
    assert "FNO_INDEX, EQUITY" in call_args2

    prefs = alert_preferences.get_preferences()
    assert prefs["telegram"]["allowed_segments"] == ["FNO_INDEX", "EQUITY"]

    # 3. Reset to all
    mock_context.args = ["all"]
    await cmd_filter(mock_update, mock_context)
    call_args3 = mock_message.reply_text.call_args[0][0]
    assert "FNO_INDEX, FNO_STOCK, EQUITY, COMMODITY, CURRENCY" in call_args3


def test_fno_telegram_destination_routing(monkeypatch):
    """Verify that F&O Index alerts route to TELEGRAM_FNO_INDEX_CHAT_ID and F&O Stock alerts route to TELEGRAM_FNO_CHAT_ID."""
    from bot.telegram_bot import get_telegram_destinations
    from engine.alert_preferences import alert_preferences
    from engine.auto_alert_engine import AutoAlert, AutoAlertEngine

    monkeypatch.setenv("TELEGRAM_FNO_INDEX_CHAT_ID", "-1004380788314")
    monkeypatch.setenv("TELEGRAM_FNO_CHAT_ID", "-1004393392375")
    monkeypatch.setattr("engine.alerts._is_market_hours", lambda exch: True)

    dests = get_telegram_destinations()
    assert dests["fno_index_chat_id"] == "-1004380788314"
    assert dests["fno_index_chat_name"] == "Premium_Alpha_Vortex_FnO_Index"
    assert dests["fno_chat_id"] == "-1004393392375"

    sent_calls = []

    def mock_tg_notify(msg, chat_id=None):
        sent_calls.append((msg, chat_id))

    monkeypatch.setattr("engine.alerts._telegram_notify", mock_tg_notify)

    engine = AutoAlertEngine()

    # 1. F&O Index Alert (NIFTY) -> routes to Premium_Alpha_Vortex_FnO_Index
    fno_index_alert = AutoAlert(
        alert_id="live-fno-index-routing-001",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY 25000 CE GAMMA SURGE",
        summary="Call OI unwinding",
        ltp=150.0,
        trigger_level=140.0,
        target_level=220.0,
        stop_loss=110.0,
        option_type="CE",
        strike=25000.0,
        confidence=92,
        is_live=True,
        environment="LIVE",
    )

    engine._dispatch(fno_index_alert)
    assert len(sent_calls) == 1
    assert sent_calls[0][1] == "-1004380788314"

    # 2. F&O Stock Alert (RELIANCE) -> routes to Premium_Alpha_Vortex_FnO_Channel
    fno_stock_alert = AutoAlert(
        alert_id="live-fno-stock-routing-001",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="RELIANCE",
        contract_symbol="RELIANCE26SEP3000CE",
        exchange="NFO",
        direction="BULLISH",
        headline="RELIANCE 3000 CE BREAKOUT",
        summary="Heavy call buying",
        ltp=45.0,
        trigger_level=42.0,
        target_level=60.0,
        stop_loss=32.0,
        option_type="CE",
        strike=3000.0,
        confidence=90,
        is_live=True,
        environment="LIVE",
    )

    engine._dispatch(fno_stock_alert)
    assert len(sent_calls) == 2
    assert sent_calls[1][1] == "-1004393392375"


def test_mcx_commodity_currency_telegram_destination_routing(monkeypatch):
    """Verify that MCX, Commodity, and Currency alerts route to Premium_Alpha_Vortex_MCX_Channel (-1004320002599)."""
    from bot.telegram_bot import get_telegram_destinations
    from engine.alert_preferences import alert_preferences
    from engine.auto_alert_engine import AutoAlert, AutoAlertEngine

    monkeypatch.setattr("engine.alerts._is_market_hours", lambda exch: True)

    # 1. Verify destination info reporting
    dests = get_telegram_destinations()
    assert dests["mcx_chat_id"] == "-1004320002599"
    assert dests["mcx_chat_name"] == "Premium_Alpha_Vortex_MCX_Channel"

    sent_calls = []

    def mock_tg_notify(msg, chat_id=None):
        sent_calls.append((msg, chat_id))

    monkeypatch.setattr("engine.alerts._telegram_notify", mock_tg_notify)

    engine = AutoAlertEngine()

    # 2. Commodity alert (MCX: CRUDEOIL)
    crude_alert = AutoAlert(
        alert_id="live-mcx-crude-001",
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        symbol="CRUDEOIL",
        exchange="MCX",
        direction="BULLISH",
        headline="CRUDEOIL MCX SQUEEZE IGNITED",
        summary="Crude inventory drawdown surge",
        ltp=6150.0,
        trigger_level=6100.0,
        target_level=6350.0,
        stop_loss=6020.0,
        confidence=91,
        is_live=True,
        environment="LIVE",
    )

    engine._dispatch(crude_alert)
    assert len(sent_calls) == 1
    assert sent_calls[0][1] == "-1004320002599"

    # 3. Currency alert (CDS: USDINR)
    usdinr_alert = AutoAlert(
        alert_id="live-cds-usdinr-001",
        alert_type="CURRENCY_BREAKOUT",
        stage="IGNITED",
        symbol="USDINR",
        exchange="CDS",
        direction="BEARISH",
        headline="USDINR BREAKDOWN BELOW SUPPORT",
        summary="RBI interventions pushing INR higher",
        ltp=83.45,
        trigger_level=83.50,
        target_level=83.10,
        stop_loss=83.65,
        confidence=88,
        is_live=True,
        environment="LIVE",
    )

    engine._dispatch(usdinr_alert)
    assert len(sent_calls) == 2
    assert sent_calls[1][1] == "-1004320002599"

    # 4. Symbol prefix MCX: GOLD
    gold_alert = AutoAlert(
        alert_id="live-mcx-gold-001",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="MCX:GOLD",
        exchange="MCX",
        direction="BULLISH",
        headline="GOLD 1H RANGE EXPANSION",
        summary="Safe haven demand spike",
        ltp=72500.0,
        trigger_level=72000.0,
        target_level=73500.0,
        stop_loss=71800.0,
        confidence=94,
        is_live=True,
        environment="LIVE",
    )

    engine._dispatch(gold_alert)
    assert len(sent_calls) == 3
    assert sent_calls[2][1] == "-1004320002599"

    # 5. Test override via TELEGRAM_MCX_CHAT_ID env var
    monkeypatch.setenv("TELEGRAM_MCX_CHAT_ID", "-1008888888888")
    silver_alert = AutoAlert(
        alert_id="live-mcx-silver-001",
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        symbol="SILVER",
        exchange="MCX",
        direction="BULLISH",
        headline="SILVER MOMENTUM",
        summary="Industrial demand",
        ltp=85000.0,
        trigger_level=84500.0,
        target_level=87000.0,
        stop_loss=83500.0,
        confidence=90,
        is_live=True,
        environment="LIVE",
    )
    engine._dispatch(silver_alert)
    assert sent_calls[3][1] == "-1008888888888"


def test_equity_telegram_destination_routing(monkeypatch):
    """Verify that Cash Equity alerts route to Premium_Alpha_Vortex_Equity_Channel (-1003524867091)."""
    from bot.telegram_bot import get_telegram_destinations
    from engine.alert_preferences import alert_preferences
    from engine.auto_alert_engine import AutoAlert, AutoAlertEngine

    monkeypatch.setattr("engine.alerts._is_market_hours", lambda exch: True)

    # 1. Verify destination info reporting
    dests = get_telegram_destinations()
    assert dests["equity_chat_id"] == "-1003524867091"
    assert dests["equity_chat_name"] == "Premium_Alpha_Vortex_Equity_Channel"

    sent_calls = []

    def mock_tg_notify(msg, chat_id=None):
        sent_calls.append((msg, chat_id))

    monkeypatch.setattr("engine.alerts._telegram_notify", mock_tg_notify)

    engine = AutoAlertEngine()

    # 2. Equity alert (NSE: TATASTEEL)
    eq_alert = AutoAlert(
        alert_id="live-eq-tatasteel-001",
        alert_type="POCKET_PIVOT",
        stage="IGNITED",
        symbol="TATASTEEL",
        exchange="NSE",
        direction="BULLISH",
        headline="TATASTEEL POCKET PIVOT IGNITED",
        summary="High volume institutional accumulation off 50 EMA",
        ltp=155.0,
        trigger_level=153.0,
        target_level=168.0,
        stop_loss=148.0,
        confidence=89,
        is_live=True,
        environment="LIVE",
    )

    engine._dispatch(eq_alert)
    assert len(sent_calls) == 1
    assert sent_calls[0][1] == "-1003524867091"

    # 3. Test custom override via env var
    monkeypatch.setenv("TELEGRAM_EQUITY_CHAT_ID", "-1007777777777")
    eq_alert_2 = AutoAlert(
        alert_id="live-eq-zomato-001",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="ZOMATO",
        exchange="NSE",
        direction="BULLISH",
        headline="ZOMATO SQUEEZE BREAKOUT",
        summary="Consolidation breakout",
        ltp=280.0,
        trigger_level=278.0,
        target_level=310.0,
        stop_loss=268.0,
        confidence=92,
        is_live=True,
        environment="LIVE",
    )
    engine._dispatch(eq_alert_2)
    assert len(sent_calls) == 2
    assert sent_calls[1][1] == "-1007777777777"

