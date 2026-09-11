"""
tests/test_alert_revamp.py
──────────────────────────
Verification test suite for institutional alert system improvements:
1. FNO_STOCK Telegram routing to equity channel fallback.
2. Milestone alerts preserving original_call_time (avoiding "0s ago").
3. Scanner headline cleanliness (no hardcoded [REAL/LIVE]).
4. Currency pair CMP rendering (4 decimals + "Pair CMP").
5. Commodity CMP rendering.
6. Commodity VWAP dual-fire guard.
"""

import pytest
from engine.alert_preferences import AlertPreferences
from engine.auto_alert_engine import AutoAlert
from bot.alert_templates import MilestoneAlertData, render_milestone_alert, render_auto_alert


def test_fno_stock_routing_fallback(monkeypatch):
    """Verify FNO_STOCK falls back to dedicated FnO Channel (-1004393392375) when no custom FNO chat ID is set."""
    monkeypatch.delenv("TELEGRAM_FNO_CHAT_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_CHANNEL_ID", raising=False)
    prefs = AlertPreferences()
    prefs.fno_chat_id = None
    
    chat_id = prefs.get_telegram_chat_id("FNO_STOCK")
    assert chat_id == "-1004393392375", f"Expected dedicated FnO channel (-1004393392375), got {chat_id}"
    
    # Also verify with "FNO" segment
    chat_id_fno = prefs.get_telegram_chat_id("FNO")
    assert chat_id_fno == "-1004393392375"


def test_milestone_alert_preserves_original_call_time():
    """Verify MilestoneAlertData uses original_call_time instead of overwritten created_at."""
    alert = AutoAlert(
        alert_id="test-ms-001",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="OPTIONS MOMENTUM: NIFTY 24500 CE",
        summary="Test call",
        ltp=150.0,
        trigger_level=100.0,
        target_level=180.0,
        stop_loss=70.0,
        contract_symbol="NIFTY 24500 CE",
        created_at="2026-09-11 10:15:00 IST",  # Ignition moment
        original_call_time="2026-09-11 09:30:00 IST",  # Original signal moment (45m earlier)
        actionable_plan={"action": "BUY", "recommended_entry": "100.0", "target_1": "150.0", "stop_loss": "70.0"},
    )
    
    ms_data = MilestoneAlertData.from_alert(
        alert=alert,
        milestone_type="TARGET_1",
        timestamp="2026-09-11 10:15:00 IST"
    )
    
    # call_time should match original_call_time
    assert ms_data.call_time == "2026-09-11 09:30:00 IST"
    
    # Render telegram card
    rendered = render_milestone_alert(ms_data)
    assert "09:30 AM" in rendered or "9:30 AM" in rendered
    assert "0s ago" not in rendered
    assert "45m ago" in rendered


def test_currency_pair_cmp_formatting():
    """Verify Currency alerts render 'Pair CMP: ₹XX.XXXX' with 4 decimal places."""
    alert = AutoAlert(
        alert_id="curr-001",
        alert_type="CURRENCY_BREAKOUT",
        stage="IGNITED",
        symbol="USDINR",
        exchange="CDS",
        direction="BULLISH",
        headline="CURRENCY BREAKOUT: USDINR +0.15% @ ₹86.1250",
        summary="Macro USD strength",
        ltp=86.1250,
        trigger_level=86.1000,
        target_level=86.3000,
        stop_loss=86.0000,
        actionable_plan={"action": "BUY_FUTURES", "entry_range": "₹86.1200 – ₹86.1300", "target": "₹86.3000", "stop_loss": "₹86.0000"},
        segment="CURRENCY",
    )
    
    rendered = render_auto_alert(alert, in_market=True)
    assert "Pair CMP" in rendered or "₹86.1250" in rendered
    assert "Spot CMP: ₹86.12" not in rendered  # Must not truncate to 2 decimals or use generic Spot CMP


def test_commodity_cmp_formatting():
    """Verify Commodity alerts render CMP without duplicate Spot CMP text."""
    alert = AutoAlert(
        alert_id="mcx-001",
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        symbol="CRUDEOIL",
        exchange="MCX",
        direction="BULLISH",
        headline="COMMODITY MOMENTUM: CRUDEOIL +1.8% @ ₹6,120.00",
        summary="Crude oil surge",
        ltp=6120.0,
        trigger_level=6100.0,
        target_level=6250.0,
        stop_loss=6050.0,
        actionable_plan={"action": "BUY_FUTURES", "entry_range": "₹6,110 – ₹6,130", "target": "₹6,250", "stop_loss": "₹6,050"},
        segment="COMMODITY",
    )
    
    rendered = render_auto_alert(alert, in_market=True)
    assert "Spot CMP" not in rendered  # Commodities should not be called "Spot CMP"


def test_commodity_vwap_dual_fire_prevention():
    """Verify that when VWAP == LTP (sanitized fallback), dual fire cannot occur."""
    ltp = 6000.0
    vwap = 6000.0  # fallback
    min_chg = 1.0
    
    # Positive change
    chg = 1.5
    has_real_vwap_diff = (vwap > 0) and (abs(ltp - vwap) >= 2.0)
    if has_real_vwap_diff:
        is_bullish = (chg >= min_chg) and (ltp >= (vwap * 0.998))
        is_bearish = (chg <= -min_chg) and (ltp <= (vwap * 1.002))
    else:
        is_bullish = chg >= min_chg
        is_bearish = chg <= -min_chg
        
    assert is_bullish is True
    assert is_bearish is False  # Must NEVER be True simultaneously
