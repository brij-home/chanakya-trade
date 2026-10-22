"""
tests/test_reasonable_rr_calibration.py
───────────────────────────────────────
Verifies that the institutional quantitative terminal captures reasonable R:R
setups (1.5R to 2.0R+) without dropping valid high-probability trades,
while still filtering out sub-par risk (< 1.4R/1.5R).
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine
from engine.alert_scrutiny import AlertScrutinyAuditor
from engine.pipeline.coherence_gate import CoherenceGate

IST = ZoneInfo("Asia/Kolkata")


def _make_alert(
    alert_id: str,
    symbol: str,
    alert_type: str,
    direction: str,
    ltp: float,
    stop_loss: float,
    target_1: float,
    target_2: float = 0.0,
    confidence: int = 88,
    segment: str = "FNO_INDEX",
    metrics: dict = None,
    actionable_plan: dict = None,
) -> AutoAlert:
    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    plan = actionable_plan or {
        "risk_reward": f"1:{abs(target_1 - ltp) / max(0.01, abs(ltp - stop_loss)):.1f}",
        "target_1": f"₹{target_1:,.1f}",
        "target_2": f"₹{target_2:,.1f}" if target_2 > 0 else None,
    }
    return AutoAlert(
        alert_id=alert_id,
        alert_type=alert_type,
        symbol=symbol,
        exchange="NSE" if "MCX" not in segment else "MCX",
        direction=direction,
        headline=f"{symbol} Setup Test",
        summary=f"{symbol} setup test summary",
        stage="IGNITED",
        ltp=ltp,
        trigger_level=ltp,
        stop_loss=stop_loss,
        target_level=target_1,
        confidence=confidence,
        segment=segment,
        is_live=True,
        environment="LIVE",
        created_at=now_str,
        metrics=metrics or ({"target_2": target_2} if target_2 > 0 else {}),
        actionable_plan=plan,
    )


def test_telegram_apex_gate_allows_1_5r_and_2_0r_index_setups():
    """Verify that index setups offering 1.5R and 2.0R pass the Telegram Apex Gate."""
    engine = AutoAlertEngine()

    # 1. 1.5R Index Option Setup (Risk = 20 pts, Reward = 30 pts -> R:R = 1.5)
    alert_1_5r = _make_alert(
        alert_id="aa-nifty-1-5r-test",
        symbol="NIFTY",
        alert_type="INDEX_CALL_SETUP",
        direction="BULLISH",
        ltp=100.0,
        stop_loss=80.0,  # Risk = 20
        target_1=130.0,  # Reward = 30 (1.5R)
        confidence=90,
        segment="FNO_INDEX",
    )
    passed, reason = engine._eval_telegram_apex_gate(alert_1_5r, in_market=True)
    assert passed is True, f"1.5R setup should pass Apex Gate, but got: {reason}"

    # 2. 2.0R Index Option Setup (Risk = 20 pts, Reward = 40 pts -> R:R = 2.0)
    alert_2_0r = _make_alert(
        alert_id="aa-banknifty-2-0r-test",
        symbol="BANKNIFTY",
        alert_type="INDEX_CALL_SETUP",
        direction="BULLISH",
        ltp=200.0,
        stop_loss=160.0,  # Risk = 40
        target_1=280.0,  # Reward = 80 (2.0R)
        confidence=90,
        segment="FNO_INDEX",
    )
    passed, reason = engine._eval_telegram_apex_gate(alert_2_0r, in_market=True)
    assert passed is True, f"2.0R setup should pass Apex Gate, but got: {reason}"


def test_telegram_apex_gate_allows_staged_targets_with_t1_derisking():
    """
    Verify that setups with staged targets (T1 = 1.2R quick scale/de-risk, T2 = 2.0R swing expansion)
    pass through the gate cleanly instead of being rejected by T1 alone.
    """
    engine = AutoAlertEngine()

    alert_staged = _make_alert(
        alert_id="aa-staged-target-test",
        symbol="CRUDEOIL",
        alert_type="COMMODITY_MOMENTUM",
        direction="BULLISH",
        ltp=6000.0,
        stop_loss=5950.0,  # Risk = 50 pts
        target_1=6060.0,  # T1 = 60 pts (1.2R de-risk)
        target_2=6100.0,  # T2 = 100 pts (2.0R expansion)
        confidence=85,
        segment="COMMODITY",
        actionable_plan={
            "risk_reward": "1:1.2",
            "target_1": "6060.0",
            "target_2": "6100.0",
        },
    )
    passed, reason = engine._eval_telegram_apex_gate(alert_staged, in_market=True)
    assert passed is True, (
        f"Staged target trade (T1=1.2R, T2=2.0R) should pass Apex Gate, got: {reason}"
    )


def test_telegram_apex_gate_still_rejects_sub_par_risk():
    """Verify that poor risk (< 1.4R/1.5R without higher T2) remains strictly filtered."""
    engine = AutoAlertEngine()

    alert_low_rr = _make_alert(
        alert_id="aa-low-rr-test",
        symbol="NIFTY",
        alert_type="INDEX_CALL_SETUP",
        direction="BULLISH",
        ltp=100.0,
        stop_loss=90.0,  # Risk = 10
        target_1=111.0,  # Reward = 11 (1.1R)
        confidence=90,
        segment="FNO_INDEX",
    )
    passed, reason = engine._eval_telegram_apex_gate(alert_low_rr, in_market=True)
    assert passed is False
    assert "below minimum 1:1.5 threshold" in reason


def test_obstacle_headroom_adapts_to_reasonable_1_5r_target():
    """
    Verify that a setup targeting 1.5R is NOT vetoed when nearest resistance provides 1.70R headroom.
    """
    auditor = AlertScrutinyAuditor()

    # Trade targeting 1.5R (LTP 1000, SL 980 -> risk 20; T1 1030 -> reward 30, target_rr = 1.5)
    # Nearest resistance at 1034 (headroom = 34 / 20 = 1.70R >= 1.5R target)
    alert_1_5r = AutoAlert(
        alert_id="aa-headroom-1-5r-test",
        alert_type="STAGE_1_TO_2_EXPANSION",
        stage="ACTIONABLE",
        symbol="NSE:TCS",
        exchange="NSE",
        direction="BULLISH",
        headline="TCS Stage 2 Expansion",
        summary="Clear runway to 1.5R target",
        ltp=1000.0,
        trigger_level=1000.0,
        stop_loss=980.0,  # Risk = 20
        target_level=1030.0,  # Reward = 30 (1.5R)
        time_horizon="SWING",
        is_live=True,
        environment="LIVE",
        metrics={
            "atr": 15.0,
            "nearest_resistance": 1034.0,  # 1.70R headroom (> 1.5R required)
        },
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert_1_5r)
    assert passed is True, (
        f"1.5R setup with 1.70R obstacle headroom should PASS, got veto: {reason}"
    )


def test_coherence_gate_permits_1_5r_concurrent_index():
    """Verify that CoherenceGate permits concurrent index setups with R:R >= 1.5 and confidence >= 80%."""
    cg = CoherenceGate()

    from datetime import timezone, timedelta

    active_ts = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()

    # Active index trade already in flight (older than 5 mins)
    active_alert = AutoAlert(
        alert_id="aa-active-nifty-old",
        alert_type="INDEX_CALL_SETUP",
        symbol="NIFTY",
        exchange="NSE",
        headline="Active Nifty",
        summary="Active Nifty",
        direction="BULLISH",
        stage="ACTIONABLE",
        ltp=25000.0,
        trigger_level=25000.0,
        stop_loss=24900.0,
        target_level=25200.0,
        confidence=85,
        created_at=active_ts,
    )

    # New forming BankNifty trade with 1.6R and 85% confidence
    new_bn_alert = AutoAlert(
        alert_id="aa-new-bn-1-6r",
        alert_type="INDEX_CALL_SETUP",
        symbol="BANKNIFTY",
        exchange="NSE",
        headline="New BankNifty",
        summary="New BankNifty",
        direction="BULLISH",
        stage="IGNITED",
        ltp=52000.0,
        trigger_level=52000.0,
        stop_loss=51800.0,  # Risk = 200 pts
        target_level=52320.0,  # Reward = 320 pts (1.6R)
        confidence=85,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    is_allowed, reason = cg.validate_multi_index_coherence(new_bn_alert, [active_alert])
    assert is_allowed is True, f"Concurrent index trade with 1.6R should be approved, got: {reason}"
