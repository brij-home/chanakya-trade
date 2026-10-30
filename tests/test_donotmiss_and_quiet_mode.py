"""
tests/test_donotmiss_and_quiet_mode.py
──────────────────────────────────────
Institutional unit tests for:
1. '🌟 DoNotMiss' Apex Asymmetry tier classification and Telegram header badging.
2. Quiet/Mute by default audio channel preferences & runtime toggle.
3. Autonomous Breakeven Locking engine (auto-ratchet Stop-Loss to Breakeven at Target 1).
"""

from engine.alert_model import AutoAlert
from engine.alert_preferences import AlertPreferencesManager
from engine.trade_lifecycle import apply_autonomous_breakeven_lock
from bot.alert_templates import (
    render_fno_alert,
    render_equity_alert,
    render_asymmetric_alert,
    render_auto_alert,
    FNOAlertData,
    EquityAlertData,
)


def test_alert_model_is_do_not_miss_apex_confluence():
    """Alerts with APEX_CONFLUENCE conviction tier or high confidence + high R:R are flagged as DoNotMiss."""
    # 1. Apex Confluence tier
    a1 = AutoAlert(
        alert_id="aa-gamma-nifty-20261025",
        alert_type="GAMMA_BLAST",
        symbol="NIFTY",
        stage="IGNITED",
        exchange="NSE",
        direction="BULLISH",
        summary="High conviction option surge",
        ltp=25000.0,
        trigger_level=25000.0,
        target_level=25150.0,
        stop_loss=24900.0,
        confidence=90,
        headline="APEX CONFLUENCE: NIFTY 25000 CE",
        actionable_plan={"risk_reward": "1:2.6"},
    )
    assert a1.is_do_not_miss is True
    d1 = a1.to_dict()
    assert d1["is_do_not_miss"] is True
    assert "DO NOT MISS" in d1.get("do_not_miss_label", "")

    # 2. Confidence >= 85 and R:R >= 2.5
    a2 = AutoAlert(
        alert_id="aa-breakout-tcs-20261025",
        alert_type="EXECUTION_READY",
        symbol="TCS",
        stage="READY",
        exchange="NSE",
        direction="BULLISH",
        summary="Stage 2 breakout confirmed",
        ltp=4000.0,
        trigger_level=4000.0,
        target_level=4300.0,
        stop_loss=3900.0,
        headline="TCS Stage 2 Breakout",
        confidence=86,
        actionable_plan={"risk_reward": "1:3.0"},
    )
    assert a2.is_do_not_miss is True

    # 3. Standard setup with moderate confidence does not qualify
    a3 = AutoAlert(
        alert_id="aa-breakout-infy-20261025",
        alert_type="EXECUTION_READY",
        symbol="INFY",
        stage="READY",
        exchange="NSE",
        direction="BULLISH",
        summary="Standard consolidation breakout",
        ltp=1800.0,
        trigger_level=1800.0,
        target_level=1840.0,
        stop_loss=1780.0,
        headline="INFY Consolidation Breakout",
        confidence=72,
        actionable_plan={"risk_reward": "1:2.0"},
    )
    assert a3.is_do_not_miss is False


def test_render_fno_alert_surfaces_do_not_miss():
    """render_fno_alert prepends DO NOT MISS SETUP banner when flagged."""
    data = FNOAlertData(
        contract="NIFTY 25000 CE",
        underlying="NIFTY",
        premium=120.0,
        stop_loss=90.0,
        target_1=160.0,
        target_2=210.0,
        risk_reward="1:2.8",
        score=90,
        is_do_not_miss=True,
    )
    msg = render_fno_alert(data)
    assert "🌟 <b>DO NOT MISS SETUP · APEX ASYMMETRY</b>" in msg
    assert "NIFTY 25000 CE" in msg


def test_render_equity_alert_surfaces_do_not_miss():
    """render_equity_alert prepends DO NOT MISS SETUP banner when flagged."""
    data = EquityAlertData(
        symbol="RELIANCE",
        ltp=2850.0,
        action="BUY",
        entry_range="₹2,845 – ₹2,855",
        stop_loss=2800.0,
        target_1=2950.0,
        target_2=3050.0,
        risk_reward=3.0,
        strategic_score=88,
        is_do_not_miss=True,
    )
    msg = render_equity_alert(data)
    assert "🌟 <b>DO NOT MISS SETUP · APEX ASYMMETRY</b>" in msg
    assert "RELIANCE" in msg


def test_render_asymmetric_alert_surfaces_do_not_miss():
    """render_asymmetric_alert prepends DO NOT MISS SETUP banner when flagged."""
    opp = {
        "symbol": "BAJFINANCE",
        "underlying_spot": 7200.0,
        "stop_loss": 7000.0,
        "target_1": 7600.0,
        "target_2": 8000.0,
        "target_moonshot": 8800.0,
        "risk_reward_ratio": 3.5,
        "conviction_score": 92,
        "is_do_not_miss": True,
    }
    msg = render_asymmetric_alert(opp)
    assert "🌟 <b>DO NOT MISS SETUP · APEX ASYMMETRY</b>" in msg
    assert "BAJFINANCE" in msg


def test_render_auto_alert_surfaces_do_not_miss():
    """render_auto_alert surfaces DO NOT MISS banner at the top of the message."""
    alert = AutoAlert(
        alert_id="aa-asym-trent-20261025",
        alert_type="ASYMMETRIC_OPPORTUNITY",
        symbol="TRENT",
        stage="READY",
        exchange="NSE",
        direction="BULLISH",
        summary="High conviction confluence setup",
        ltp=6400.0,
        trigger_level=6400.0,
        target_level=6800.0,
        stop_loss=6200.0,
        confidence=92,
        actionable_plan={"risk_reward": "1:3.2"},
        headline="TRENT Stage 2 Breakout",
    )
    msg = render_auto_alert(alert)
    assert "🌟 <b>DO NOT MISS SETUP · APEX ASYMMETRY</b>" in msg


def test_quiet_mode_default_sound_disabled(tmp_path, monkeypatch):
    """Audio alert chimes must be disabled by default (Quiet Mode) with runtime toggle."""
    mgr = AlertPreferencesManager()
    # Sound channel must default to False
    assert mgr.sound.enabled is False

    # Update preference to enable sound
    mgr.update_preferences({"sound": {"enabled": True}})
    assert mgr.sound.enabled is True

    # Re-toggle back to quiet mode
    mgr.update_preferences({"sound": {"enabled": False}})
    assert mgr.sound.enabled is False


def test_autonomous_breakeven_locking():
    """apply_autonomous_breakeven_lock ratchets stop loss to breakeven + fee buffer at Target 1."""
    # 1. Price has NOT reached Target 1
    res_not_reached = apply_autonomous_breakeven_lock(
        symbol="SBIN",
        current_price=805.0,
        entry_price=800.0,
        initial_stop_loss=790.0,
        target_1=820.0,
        position_type="LONG",
    )
    assert res_not_reached["locked"] is False
    assert res_not_reached["ratcheted_orders_count"] == 0

    # 2. Price reaches Target 1 (820.0)
    res_reached = apply_autonomous_breakeven_lock(
        symbol="SBIN",
        current_price=820.5,
        entry_price=800.0,
        initial_stop_loss=790.0,
        target_1=820.0,
        position_type="LONG",
        cost_buffer_pct=0.002,  # +0.2% = 801.60
    )
    assert res_reached["locked"] is True
    assert res_reached["milestone"] == "T1_ACHIEVED"
    # Entry price 800 * 1.002 = 801.60
    assert res_reached["breakeven_stop"] == 801.60

    # 3. Short position reaching downward Target 1
    res_short = apply_autonomous_breakeven_lock(
        symbol="TATAMOTORS",
        current_price=948.0,
        entry_price=980.0,
        initial_stop_loss=1000.0,
        target_1=950.0,
        position_type="SHORT",
        cost_buffer_pct=0.002,  # -0.2% = 978.04
    )
    assert res_short["locked"] is True
    assert res_short["breakeven_stop"] == 978.04
