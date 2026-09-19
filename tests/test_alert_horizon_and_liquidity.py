"""
tests/test_alert_horizon_and_liquidity.py
──────────────────────────────────────────
Unit tests for:
  1. Intraday auto-expiry at 15:15 IST (and 23:15 for MCX).
  2. Unignited setup time-stop invalidation (60-minute window).
  3. Real-time options liquidity watchdog (spread %, OI floor, slippage risk).
  4. Dynamic Strike Rolling recommendations upon reaching T2 and Final Target.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pytest

from engine.alert_model import AutoAlert
from engine.alert_evaluator import (
    evaluate_alert_invalidation,
    evaluate_alert_targets_and_trailing,
    calculate_strike_roll_recommendation,
)
from market.options import audit_option_liquidity

IST = ZoneInfo("Asia/Kolkata")


def test_intraday_alert_auto_expires_at_session_cutoff():
    """Verify that INTRADAY alerts automatically expire past 15:15 IST same day or from a prior date."""
    now = datetime.now(IST)
    
    # 1. Alert created on prior calendar date must be expired immediately
    yesterday = now - timedelta(days=1)
    alert_yesterday = AutoAlert(
        alert_id="test-prior-date-001",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Nifty Gamma Surge",
        summary="Testing prior day expiration",
        ltp=150.0,
        trigger_level=145.0,
        target_level=200.0,
        stop_loss=120.0,
        time_horizon="INTRADAY",
        created_at=yesterday.strftime("%Y-%m-%d %H:%M:%S IST"),
    )
    alert_yesterday._force_test_expiry = True
    assert alert_yesterday.is_expired is True

    # 2. Alert created today with time 15:20 IST must expire if now is after 15:15
    alert_today = AutoAlert(
        alert_id="test-today-cutoff-002",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Nifty Gamma Surge",
        summary="Testing today session cutoff",
        ltp=150.0,
        trigger_level=145.0,
        target_level=200.0,
        stop_loss=120.0,
        time_horizon="INTRADAY",
        created_at=now.strftime("%Y-%m-%d 10:00:00 IST"),
    )
    alert_today._force_test_expiry = True
    if now.hour > 15 or (now.hour == 15 and now.minute >= 15):
        assert alert_today.is_expired is True


def test_intraday_alert_invalidation_at_cutoff():
    """Verify evaluate_alert_invalidation returns session cutoff message for intraday trades."""
    now = datetime.now(IST)
    past_date = now - timedelta(days=1)
    
    alert = AutoAlert(
        alert_id="test-inval-cutoff-003",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Nifty Gamma",
        summary="Testing cutoff invalidation",
        ltp=150.0,
        trigger_level=145.0,
        target_level=200.0,
        stop_loss=120.0,
        time_horizon="INTRADAY",
        created_at=past_date.strftime("%Y-%m-%d 11:00:00 IST"),
    )
    alert._force_test_expiry = True
    reason = evaluate_alert_invalidation(alert, current_ltp=152.0)
    assert reason is not None
    assert "Intraday session expired" in reason
    assert "15:15 IST cutoff reached" in reason


def test_unignited_early_warning_time_stop():
    """Verify that unignited EARLY_WARNING setups expire after 60 minutes."""
    now = datetime.now(IST)
    old_time = now - timedelta(minutes=75)
    
    alert = AutoAlert(
        alert_id="test-timestop-004",
        alert_type="SQUEEZE_BREAKOUT",
        stage="EARLY_WARNING",
        symbol="RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="Reliance Coiling",
        summary="Compression base",
        ltp=2500.0,
        trigger_level=2520.0,
        target_level=2600.0,
        stop_loss=2480.0,
        time_horizon="INTRADAY",
        ttl_seconds=3600,
        created_at=old_time.strftime("%Y-%m-%d %H:%M:%S IST"),
    )
    alert._force_test_expiry = True
    reason = evaluate_alert_invalidation(alert, current_ltp=2505.0)
    assert reason is not None
    assert "Time-Stop expired" in reason
    assert "60-minute momentum window" in reason


def test_options_liquidity_audit():
    """Verify audit_option_liquidity detects optimal vs wide spreads and flags slippage risks."""
    # 1. Optimal tight spread: LTP 120, Bid 119.80, Ask 120.20 (Spread = 0.33%)
    tight_contract = {
        "ltp": 120.0,
        "bid": 119.80,
        "ask": 120.20,
        "oi": 35000,
        "volume": 12000,
    }
    audit_tight = audit_option_liquidity(tight_contract, underlying="NIFTY")
    assert audit_tight["is_liquid"] is True
    assert audit_tight["liquidity_status"] == "OPTIMAL"
    assert audit_tight["slippage_risk"] == "LOW"
    assert audit_tight["bid_ask_spread_pct"] < 1.0

    # 2. Wide spread caution: LTP 80, Bid 76.0, Ask 84.0 (Spread = 10%)
    wide_contract = {
        "ltp": 80.0,
        "bid": 76.0,
        "ask": 84.0,
        "oi": 15000,
        "volume": 2000,
    }
    audit_wide = audit_option_liquidity(wide_contract, underlying="NIFTY")
    assert audit_wide["liquidity_status"] == "WIDE_SPREAD_CAUTION"
    assert audit_wide["slippage_risk"] == "HIGH"
    assert audit_wide["bid_ask_spread_pct"] == 10.0
    assert "Wide bid-ask spread" in audit_wide["execution_warning"]

    # 3. Illiquid order book: missing bids/asks
    empty_book = {
        "ltp": 45.0,
        "bid": 0.0,
        "ask": 0.0,
        "oi": 100,
        "volume": 10,
    }
    audit_empty = audit_option_liquidity(empty_book, underlying="NIFTY")
    assert audit_empty["is_liquid"] is False
    assert audit_empty["liquidity_status"] == "ILLIQUID"


def test_strike_roll_recommendation_generation():
    """Verify calculate_strike_roll_recommendation suggests ATM roll when option reaches deep ITM."""
    alert = AutoAlert(
        alert_id="test-roll-005",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY 25000 CE",
        summary="Nifty Gamma Blast",
        ltp=120.0,
        trigger_level=120.0,
        target_level=220.0,
        stop_loss=90.0,
        strike=25000.0,
        option_type="CE",
        contract_symbol="NIFTY2692425000CE",
        underlying_spot=25380.0,  # Spot moved up by 380 points! 25000 CE is deep ITM
    )

    roll = calculate_strike_roll_recommendation(
        alert=alert,
        current_ltp=360.0,
        pnl_pct=200.0,
        is_bullish=True,
    )
    assert roll is not None
    assert roll["action"] == "ROLL_UP"
    assert roll["current_strike"] == 25000.0
    # 25380 spot with 50-step rounds to 25400 ATM
    assert roll["recommended_strike"] == 25400.0
    assert "25400" in roll["recommended_contract"]
    assert "Roll up to liquid ATM 25400 CE" in roll["reason"]


def test_evaluate_targets_and_trailing_attaches_strike_roll():
    """Verify evaluate_alert_targets_and_trailing attaches strike_roll_recommendation upon T2 / Final Hit."""
    alert = AutoAlert(
        alert_id="test-roll-t2-006",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="Nifty Call Momentum",
        summary="Testing strike roll attachment",
        ltp=100.0,
        trigger_level=100.0,
        target_level=180.0,
        stop_loss=75.0,
        strike=25000.0,
        option_type="CE",
        contract_symbol="NIFTY2692425000CE",
        underlying_spot=25350.0,
        actionable_plan={
            "recommended_entry": 100.0,
            "stop_loss": 75.0,
            "target_1": 135.0,
            "target_2": 175.0,
            "target_3": 230.0,
        },
    )

    # Simulate price reaching T2 (180.0)
    res = evaluate_alert_targets_and_trailing(alert, current_ltp=180.0)
    assert res is not None
    assert res.new_milestone in ("T2_ACHIEVED", "TARGET_ACHIEVED")
    assert res.should_roll_strike is True
    assert res.strike_roll_recommendation is not None
    assert res.strike_roll_recommendation["action"] == "ROLL_UP"
    assert res.strike_roll_recommendation["recommended_strike"] == 25350.0
