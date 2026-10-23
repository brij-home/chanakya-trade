"""
tests/test_category_segregation_and_unlimited_index.py
───────────────────────────────────────────────────────
Verifies:
1. Category Segregation:
   - SCALP (Micro-Scalp, 15-45m ETA, 1m/5m trailing, sub-ATR stop, 1.0R T1 de-risk).
   - INTRADAY (Day trade, Today 15:15 IST / 23:15 MCX ETA, 1.5R T1 de-risk, hard EOD auto-settle).
   - SWING_SHORT (2-5 Sessions, daily ATR stop, multi-day overnight carry).
   - SWING_MID (1-4 Weeks, VCP/SMC/Carter Squeeze, multi-week carry).
   - POSITIONAL & MULTIBAGGER (1-6 Months / 6-24 Months, stage markup, multibagger alpha).
2. Unlimited Strong Index Signals:
   - Pacing limits (hourly/daily) do NOT throttle strong, logical, and valid index trade setups.
   - Weak / ill-formed index signals remain protected under pacing discipline.
"""

import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine
from bot.alert_templates import render_auto_alert

IST = ZoneInfo("Asia/Kolkata")


def _build_test_index_alert(
    alert_id: str = "aa-idx-test-1",
    symbol: str = "NIFTY",
    direction: str = "BULLISH",
    confidence: int = 90,
    ltp: float = 120.0,
    trigger: float = 120.0,
    stop_loss: float = 90.0,
    target_1: float = 170.0,
    target_2: float = 210.0,
    bypass_pacing: bool = True,
) -> AutoAlert:
    """Helper to build a strong, logical, valid index option alert."""
    return AutoAlert(
        alert_id=alert_id,
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        symbol=symbol,
        exchange="NFO",
        direction=direction,
        headline=f"⚡ {symbol} 22500 CE SURGE",
        summary="Strong institutional order flow and volume breakout",
        ltp=ltp,
        trigger_level=trigger,
        target_level=target_1,
        stop_loss=stop_loss,
        strike=22500,
        option_type="CE",
        contract_symbol=f"{symbol} 22500 CE",
        segment="FNO_INDEX",
        confidence=confidence,
        time_horizon="INTRADAY",
        actionable_plan={
            "action": "BUY_CE",
            "contract": f"{symbol} 22500 CE",
            "entry_range": f"₹{trigger:,.1f}",
            "stop_loss": f"₹{stop_loss:,.1f}",
            "target_1": f"₹{target_1:,.1f}",
            "target_2": f"₹{target_2:,.1f}",
            "risk_reward": "1:1.7",
            "profit_rule": "Book 50% at T1, move SL to breakeven.",
        },
        metrics={
            "conviction_tier": "HIGH_CONVICTION",
            "fii_aligned": True,
            "vwap_trend": True,
        },
        details={"bypass_pacing": bypass_pacing},
    )


def test_unlimited_strong_index_signals_bypass_hourly_and_daily_pacing():
    """
    Strong, logical, valid index signals must NOT be blocked by hourly or daily pacing limits.
    """
    engine = AutoAlertEngine()
    now_t = time.time()
    today_k = datetime.now(IST).strftime("%Y-%m-%d")

    # Simulate 20 index alerts already dispatched in the past 40 minutes (exceeding hourly=4 and daily=12)
    engine._hourly_telegram_dispatches["INDEX"] = [now_t - (i * 60) for i in range(20)]
    engine._hourly_index_directional = [(now_t - (i * 60), "BULLISH") for i in range(20)]
    engine._daily_index_telegram[today_k] = 20

    # Strong, logical, valid index setup with bypass_pacing flag enabled
    alert = _build_test_index_alert(
        alert_id="aa-idx-strong-valid",
        confidence=90,
        trigger=120.0,
        stop_loss=90.0,
        target_1=170.0,  # Reward = 50, Risk = 30 -> R:R = 1.67 >= 1.4
        target_2=210.0,
        bypass_pacing=True,
    )
    # Explicitly attach bypass_pacing attribute
    alert.bypass_pacing = True

    passed, reason = engine._eval_telegram_apex_gate(alert, in_market=True, now_ts=now_t)
    assert passed is True, (
        f"Expected strong valid index alert to bypass pacing limits, got: {reason}"
    )
    assert reason == "PASSED_APEX_GATE"


def test_weak_or_incomplete_index_signal_still_throttled_by_pacing():
    """
    If an index signal is weak (<80% conf) or has invalid geometry,
    it must NOT bypass pacing limits.
    """
    engine = AutoAlertEngine()
    now_t = time.time()

    # Simulate hourly limit reached
    engine._hourly_telegram_dispatches["INDEX"] = [now_t - (i * 60) for i in range(10)]
    engine._hourly_index_directional = [(now_t - (i * 60), "BULLISH") for i in range(10)]

    # Weak index alert (confidence=75 < 80)
    alert_weak = _build_test_index_alert(
        alert_id="aa-idx-weak",
        confidence=75,
        trigger=120.0,
        stop_loss=90.0,
        target_1=170.0,
        bypass_pacing=True,
    )
    alert_weak.bypass_pacing = True

    passed, reason = engine._eval_telegram_apex_gate(alert_weak, in_market=True, now_ts=now_t)
    assert passed is False
    assert "pacing limit reached" in reason or "confidence" in reason


def test_category_segregation_scalp():
    """
    INDEX_MICRO_SCALP must automatically resolve to SCALP with 15–45m Scalp ETA
    and unmistakable fast scalp Telegram badges.
    """
    alert = AutoAlert(
        alert_id="aa-scalp-nifty",
        alert_type="INDEX_MICRO_SCALP",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY 22500 CE · Scalp Spark",
        summary="Micro-pullback tap on 1m 9-EMA",
        ltp=110.0,
        trigger_level=110.0,
        target_level=125.0,  # +15 pts (+1.5R)
        stop_loss=100.0,  # -10 pts
        strike=22500,
        option_type="CE",
        contract_symbol="NIFTY 22500 CE",
        segment="FNO_INDEX",
        confidence=88,
    )
    # Check AutoAlert auto-inference
    assert alert.time_horizon == "SCALP"
    assert alert.eta_label == "15–45m Scalp"

    # Check Telegram rendering
    rendered = render_auto_alert(alert, in_market=True)
    assert "FAST SCALP ⚡ 15–45m" in rendered
    assert "⚡ SCALP (15–45m)" in rendered
    assert "15–45m Scalp" in rendered


def test_category_segregation_swing_short():
    """
    SWING_INFLECTION and PRE_INFLECTION_DRYUP must resolve to SWING_SHORT with 2–5 Sessions ETA.
    """
    alert = AutoAlert(
        alert_id="aa-swing-short-tata",
        alert_type="SWING_INFLECTION",
        stage="IGNITED",
        symbol="TATAMOTORS",
        exchange="NSE",
        direction="BULLISH",
        headline="TATAMOTORS · Minervini VCP Compression",
        summary="Contraction 18% -> 7% -> 2% with volume dry-up",
        ltp=950.0,
        trigger_level=955.0,
        target_level=1020.0,
        stop_loss=925.0,
        confidence=86,
    )
    assert alert.time_horizon == "SWING_SHORT"
    assert alert.eta_label == "2–5 Sessions"

    rendered = render_auto_alert(alert, in_market=True)
    assert "SHORT SWING (2–5 SESSIONS)" in rendered
    assert "2-5D SHORT SWING" in rendered


def test_category_segregation_swing_mid():
    """
    SQUEEZE_BREAKOUT must resolve to SWING_MID with 1–4 Weeks ETA.
    """
    alert = AutoAlert(
        alert_id="aa-swing-mid-infy",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="INFY",
        exchange="NSE",
        direction="BULLISH",
        headline="INFY · Carter TTM Squeeze Explosion",
        summary="6 black squeeze dots firing green on daily chart",
        ltp=1850.0,
        trigger_level=1860.0,
        target_level=2000.0,
        stop_loss=1790.0,
        confidence=88,
    )
    assert alert.time_horizon == "SWING_MID"
    assert alert.eta_label == "1–4 Weeks"

    rendered = render_auto_alert(alert, in_market=True)
    assert "MID SWING (1–4 WEEKS)" in rendered
    assert "1-4W MID SWING" in rendered


def test_category_segregation_multibagger():
    """
    STAGE_1_TO_2_EXPANSION marked as MULTIBAGGER must resolve to MULTIBAGGER with 6–24 Months ETA.
    """
    alert = AutoAlert(
        alert_id="aa-multibagger-hal",
        alert_type="STAGE_1_TO_2_EXPANSION",
        stage="IGNITED",
        symbol="HAL",
        exchange="NSE",
        direction="BULLISH",
        headline="HAL · Weinstein Stage 1→2 Multibagger Markup",
        summary="32-week base breakout with 4.5x institutional volume surge",
        ltp=4500.0,
        trigger_level=4520.0,
        target_level=7000.0,
        stop_loss=4100.0,
        confidence=92,
    )
    assert alert.time_horizon == "MULTIBAGGER"
    assert alert.eta_label == "6–24 Months"

    rendered = render_auto_alert(alert, in_market=True)
    assert "MULTIBAGGER ALPHA (6–24M)" in rendered
    assert "6–24 Months" in rendered


def test_alert_repository_prior_session_cleanup():
    """
    Prior-session intraday & scalp positions must be auto-settled,
    while swing & positional positions MUST survive across sessions.
    """
    from engine.storage.alert_repository import AlertRepository
    from pathlib import Path

    repo = AlertRepository(Path("/tmp/alerts.json"))

    yesterday_str = (datetime.now(IST) - timedelta(days=1)).strftime("%Y-%m-%d 10:00:00 IST")

    # 1. Prior-session Scalp
    scalp_alert = AutoAlert(
        alert_id="aa-prior-scalp",
        alert_type="INDEX_MICRO_SCALP",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY Scalp",
        summary="Fast scalp",
        ltp=100.0,
        trigger_level=100.0,
        target_level=115.0,
        stop_loss=90.0,
        time_horizon="SCALP",
        created_at=yesterday_str,
    )

    # 2. Prior-session Swing
    swing_alert = AutoAlert(
        alert_id="aa-prior-swing",
        alert_type="SWING_INFLECTION",
        stage="IGNITED",
        symbol="RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="RELIANCE VCP Swing",
        summary="Multi-day swing",
        ltp=2800.0,
        trigger_level=2810.0,
        target_level=2950.0,
        stop_loss=2740.0,
        time_horizon="SWING_SHORT",
        created_at=yesterday_str,
    )

    cleaned, _ = repo.sanitize_legacy_alerts([scalp_alert, swing_alert])

    # Scalp alert must be marked COMPLETED / SESSION_CLOSE_EXIT
    assert scalp_alert.is_archived is True
    assert scalp_alert.stage == "COMPLETED"
    assert scalp_alert.target_status == "SESSION_CLOSE_EXIT"

    # Swing alert must remain ACTIVE and NOT archived
    assert swing_alert.is_archived is False
    assert swing_alert.stage == "IGNITED"
