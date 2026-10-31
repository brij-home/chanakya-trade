"""
tests/test_fno_session_focus_and_dual_blueprint.py
───────────────────────────────────────────────────
Institutional test suite for F&O Live Session Focus & Dual-Blueprint Options Execution.

Verifies:
  1. Market-Hours Session Focus Gate (SESSION_FOCUS_MODE="FNO_PRIORITY"):
     - Dedicates 100% of compute & API quota to domestic Equity/NFO F&O during 09:15-15:30 IST.
     - Bypasses distracting cash-only scanners (circuits, incubations, pairs arbitrage).
  2. Dual-Blueprint Options Execution:
     - Route A: Naked High Convexity (momentum scalpers & trend riders).
     - Route B: Dynamic Adaptive Hedged Spread (defined-risk & theta defense).
     - Regime Verdict: Contextually flags MARKET_FAVORS_NAKED vs HEDGE_RECOMMENDED.
  3. Dynamic Level-Anchored Runway:
     - Strike difference dynamically expands to accommodate target resistance levels.
"""

import os
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from engine.options_hedging import build_defined_risk_hedge_plan
from config.constants import SESSION_FOCUS_MODE

IST = timezone(timedelta(hours=5, minutes=30))


# ── 1. Dynamic Level-Anchored Runway & Regime Verdict ─────────────────────────


def test_level_anchored_runway_strike_expansion():
    """Verify short leg expands to sit at or beyond target_level to give long leg full runway."""
    spot = 24500.0
    strike = 24500.0
    # Normal Nifty trend width is 150 pts (sell strike 24650).
    # If major target resistance is at 24800 (300 pts away), width must expand to >= 300 pts!
    target_res = 24800.0

    plan = build_defined_risk_hedge_plan(
        symbol="NIFTY",
        direction="BULLISH",
        spot=spot,
        strike=strike,
        opt_type="CE",
        opt_ltp=130.0,
        vel_score=60.0,
        target_level=target_res,
    )
    assert plan is not None
    assert plan["strike_width"] >= 300.0
    assert plan["sell_strike"] >= 24800.0
    assert "LEVEL-ANCHORED RUNWAY" in plan["adaptive_regime"]
    assert plan["target_level"] == target_res


def test_stock_fno_level_anchored_runway():
    """Verify stock F&O strike width dynamically expands based on resistance target."""
    # Reliance spot ~1350, strike step is 20
    # Normal trend width is 60 pts.
    # Target resistance is 1450 (100 pts away).
    plan = build_defined_risk_hedge_plan(
        symbol="RELIANCE",
        direction="BULLISH",
        spot=1350.0,
        strike=1360.0,
        opt_type="CE",
        opt_ltp=35.0,
        vel_score=65.0,
        target_level=1450.0,
    )
    assert plan is not None
    assert plan["strike_width"] >= 80.0
    assert plan["sell_strike"] >= 1440.0


def test_regime_verdict_logic():
    """Verify regime verdict tags MARKET_FAVORS_NAKED during high velocity and HEDGE_RECOMMENDED in chop."""
    # Explosive thrust, stable VIX -> MARKET_FAVORS_NAKED
    morning_dt = datetime(2026, 10, 30, 10, 15, tzinfo=IST)
    plan_thrust = build_defined_risk_hedge_plan(
        symbol="BANKNIFTY",
        direction="BULLISH",
        spot=52000.0,
        strike=52000.0,
        opt_type="CE",
        opt_ltp=350.0,
        vix=14.0,
        vel_score=82.0,
        now_dt=morning_dt,
    )
    assert plan_thrust is not None
    assert plan_thrust["regime_verdict"] == "MARKET_FAVORS_NAKED"
    assert "High convexity" in plan_thrust["route_a_guidance"]

    # Midday lull, elevated VIX -> HEDGE_RECOMMENDED
    midday_dt = datetime(2026, 10, 30, 12, 15, tzinfo=IST)
    plan_chop = build_defined_risk_hedge_plan(
        symbol="BANKNIFTY",
        direction="BULLISH",
        spot=52000.0,
        strike=52000.0,
        opt_type="CE",
        opt_ltp=350.0,
        vix=18.5,
        vel_score=50.0,
        now_dt=midday_dt,
    )
    assert plan_chop is not None
    assert plan_chop["regime_verdict"] == "HEDGE_RECOMMENDED"


# ── 2. Market-Hours Focus Gate in AutoAlertEngine ─────────────────────────────


def test_session_focus_mode_constant_default():
    """Verify SESSION_FOCUS_MODE defaults to FNO_PRIORITY."""
    assert SESSION_FOCUS_MODE == "FNO_PRIORITY"


@patch.dict(os.environ, {"SESSION_FOCUS_MODE": "FNO_PRIORITY"}, clear=False)
def test_scan_fresh_signals_fno_priority_gate():
    """Under FNO_PRIORITY during active equity/NFO hours, only scan_equity_nfo_now is executed."""
    from engine.auto_alert_engine import AutoAlertEngine

    engine = AutoAlertEngine()

    # Mock session where domestic equity_nfo is open
    mock_session = {
        "equity_nfo": True,
        "currency": True,
        "commodity": False,
    }

    with (
        patch("engine.auto_alert_engine.get_current_ist_session", return_value=mock_session),
        patch.object(engine, "scan_equity_nfo_now", return_value=[]) as mock_equity,
        patch.object(engine, "scan_currency_now", return_value=[]) as mock_currency,
        patch.object(engine, "scan_crypto_now", return_value=[]) as mock_crypto,
        patch.dict(os.environ, {"CHANAKYA_TESTING": "0", "DEPLOY_MODE": "live"}, clear=False),
    ):
        # Remove pytest current test temporarily to test live gate
        current_test = os.environ.pop("PYTEST_CURRENT_TEST", None)
        try:
            _ = engine.scan_fresh_signals_now(segment="AUTO")
            # Must run equity_nfo
            assert mock_equity.called
            # Must NOT run currency or crypto in peak equity FNO session
            assert not mock_currency.called
            assert not mock_crypto.called
        finally:
            if current_test:
                os.environ["PYTEST_CURRENT_TEST"] = current_test


# ── 3. Dual-Blueprint Alert Rendering in Telegram & UI ───────────────────────


def test_dual_blueprint_rendering_in_alert_template():
    """Verify alert template renders the EXECUTION REGIME banner and both routes."""
    from bot.alert_templates import render_auto_alert
    from engine.alert_model import AutoAlert

    alert = AutoAlert(
        alert_id="aa-call-nifty-test-20261030",
        alert_type="INDEX_CALL_SETUP",
        stage="TRIGGERED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY 24500 CE VWAP RECLAIM",
        summary="SMC VWAP Reclaim Breakout",
        ltp=120.0,
        trigger_level=120.0,
        target_level=155.0,
        stop_loss=95.0,
        strike=24500.0,
        option_type="CE",
        contract_symbol="NIFTY26OCT24500CE",
        lot_size=65,
        confidence=85.0,
        metrics={
            "regime_verdict": "MARKET_FAVORS_NAKED",
        },
        actionable_plan={
            "action": "BUY CE",
            "recommended_entry": "₹120.0",
            "target": "₹155.0",
            "stop_loss": "₹95.0",
            "regime_verdict": "MARKET_FAVORS_NAKED",
            "hedge_plan": {
                "strategy": "BULL_CALL_SPREAD",
                "buy_leg": "BUY NIFTY 24500 CE @ ₹120.0",
                "sell_leg": "SELL NIFTY 24700 CE @ ₹40.0",
                "net_debit_per_share": 80.0,
                "max_loss": 5200.0,
                "max_profit": 7800.0,
                "risk_reward": "1:1.5",
                "strike_width": 200.0,
            },
        },
    )

    rendered = render_auto_alert(alert)
    assert "EXECUTION REGIME:" in rendered
    assert "MARKET FAVORS NAKED" in rendered
    assert "DEFINED-RISK HEDGE SPREAD" in rendered
    assert "BUY NIFTY 24500 CE" in rendered
    assert "SELL NIFTY 24700 CE" in rendered
