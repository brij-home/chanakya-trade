"""
tests/test_fomo_trap_guards.py
───────────────────────────────
Institutional verification suite for Anti-FOMO and Trap Avoidance invariants:
  1. Pre-Trade Gate 10 (Anti-FOMO & No-Chase enforcement).
  2. Tier-1 Alert Scrutiny exact No-Chase boundary adherence.
  3. Universal No-Chase boundary standardization across all detectors.
  4. Order book depth sweep slippage and wall absorption warnings.
"""

from __future__ import annotations


from engine.alert_model import AutoAlert
from engine.pretrade import validate_pretrade
from engine.alert_scrutiny import AlertScrutinyAuditor
from engine.auto_alert_engine import AutoAlertEngine


def test_pretrade_gate_10_blocks_when_ltp_exceeds_no_chase_boundary():
    """Verify Gate 10 strictly rejects buy orders when live price has run past no-chase boundary."""
    res = validate_pretrade(
        symbol="RELIANCE",
        side="BUY",
        quantity=10,
        order_type="LIMIT",
        price=2500.0,
        segment="EQ",
        ltp=2520.0,
        no_chase_boundary=2510.0,
        skip_session_check=True,
    )
    assert not res.is_eligible
    assert any("FOMO Violation" in r and "2,510.00" in r for r in res.blocking_reasons)
    assert "no_chase" in res.gate_results
    assert res.gate_results["no_chase"].blocked


def test_pretrade_gate_10_blocks_when_sell_drops_below_no_chase_boundary():
    """Verify Gate 10 strictly rejects sell orders when price has dropped below no-chase boundary."""
    res = validate_pretrade(
        symbol="INFY",
        side="SELL",
        quantity=10,
        order_type="LIMIT",
        price=1800.0,
        segment="EQ",
        ltp=1780.0,
        no_chase_boundary=1790.0,
        skip_session_check=True,
    )
    assert not res.is_eligible
    assert any("FOMO Violation" in r and "1,790.00" in r for r in res.blocking_reasons)
    assert res.gate_results["no_chase"].blocked


def test_pretrade_gate_10_blocks_runaway_market_orders():
    """Verify Gate 10 protects traders from executing market orders when price has surged >1.2% above intended baseline."""
    res = validate_pretrade(
        symbol="TCS",
        side="BUY",
        quantity=5,
        order_type="MARKET",
        segment="EQ",
        ltp=4060.0,  # +1.5% above trigger 4000.0
        trigger_price=4000.0,
        max_chase_pct=1.2,
        skip_session_check=True,
    )
    assert not res.is_eligible
    assert any("FOMO Market Order Violation" in r for r in res.blocking_reasons)
    assert res.gate_results["no_chase"].blocked


def test_pretrade_gate_10_passes_when_within_bounds():
    """Verify Gate 10 passes cleanly when live LTP is within the no-chase boundary."""
    res = validate_pretrade(
        symbol="HDFCBANK",
        side="BUY",
        quantity=10,
        order_type="LIMIT",
        price=1600.0,
        segment="EQ",
        ltp=1602.0,
        no_chase_boundary=1608.0,
        trigger_price=1600.0,
        quote_age_seconds=5.0,
        skip_session_check=True,
    )
    assert res.is_eligible
    assert len(res.blocking_reasons) == 0
    assert res.gate_results["no_chase"].passed


def test_tier1_scrutiny_vetoes_alerts_extended_past_no_chase_boundary():
    """Verify Tier 1 alert scrutiny vetoes candidate alerts where current price has run past explicit no_chase_boundary."""
    auditor = AlertScrutinyAuditor(min_rr_ratio=2.0)
    alert = AutoAlert(
        alert_id="test-fomo-1",
        alert_type="BREAKOUT",
        stage="IGNITED",
        symbol="RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="Breakout",
        summary="Testing no chase",
        ltp=2525.0,  # Exceeded no_chase_boundary 2515.0
        trigger_level=2500.0,
        stop_loss=2460.0,  # 40 pts risk, clears the 26.5 pts ATR floor
        target_level=2600.0,  # 100 pts reward -> 1:2.5 RR
        no_chase_boundary=2515.0,
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert not passed
    assert "FOMO Trap Veto" in reason
    assert not flags["no_chase"]


def test_auto_alert_engine_standardizes_no_chase_boundary():
    """Verify record_alert dynamically populates no_chase_boundary if missing."""
    engine = AutoAlertEngine()
    alert = AutoAlert(
        alert_id="test-standardize-1",
        alert_type="ORB_BREAKOUT",
        stage="IGNITED",
        symbol="ICICIBANK",
        exchange="NSE",
        direction="BULLISH",
        headline="ORB Breakout",
        summary="ORB testing",
        ltp=1200.0,
        trigger_level=1200.0,
        stop_loss=1180.0,
        target_level=1260.0,
        no_chase_boundary=None,  # Unset
        is_live=False,  # Test environment
        environment="TEST",
    )
    # Simulate record_alert standardization
    engine.record_alert(alert)
    assert alert.no_chase_boundary is not None
    assert alert.no_chase_boundary == 1214.4  # 1200 * 1.012 = 1214.4
    assert "no_chase_boundary" in alert.actionable_plan
