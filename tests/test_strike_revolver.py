"""
tests/test_strike_revolver.py
─────────────────────────────
Comprehensive institutional test suite for Dynamic Strike Revolving, Rolling,
Order-Book Bid-Ask Spread Gating, and Convexity Optimization.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from config.constants import IST
from engine.alert_model import AutoAlert
from engine.strike_revolver import (
    derive_new_contract_symbol,
    evaluate_strike_revolving,
    get_strike_step_for_symbol,
)
from engine.alert_evaluator import (
    evaluate_alert_targets_and_trailing,
)
from engine.lifecycle.trade_lifecycle_manager import TradeLifecycleManager
from engine.option_resolver import resolve_option_contract
from market.options import OptionsContract


def test_strike_step_resolution():
    """Verify canonical strike step resolution across Indian indices and equity tiers."""
    assert get_strike_step_for_symbol("NIFTY") == 50.0
    assert get_strike_step_for_symbol("BANKNIFTY") == 100.0
    assert get_strike_step_for_symbol("FINNIFTY") == 50.0
    assert get_strike_step_for_symbol("MIDCPNIFTY") == 25.0
    assert get_strike_step_for_symbol("SENSEX") == 100.0

    # Stock options tiering by spot
    assert get_strike_step_for_symbol("MRF", spot=130000.0) == 100.0
    assert get_strike_step_for_symbol("TCS", spot=3500.0) == 50.0
    assert get_strike_step_for_symbol("INFY", spot=1850.0) == 20.0
    assert get_strike_step_for_symbol("SBIN", spot=820.0) == 10.0
    assert get_strike_step_for_symbol("ITC", spot=480.0) == 5.0
    assert get_strike_step_for_symbol("IDEA", spot=12.0) == 2.5


def test_derive_new_contract_symbol():
    """Verify deterministic contract symbol derivation for spaced and exchange formats."""
    # Spaced format
    s1 = derive_new_contract_symbol("NIFTY 24800 CE", "NIFTY", "CE", 24800.0, 25100.0)
    assert s1 == "NIFTY 25100 CE"

    # Compact format
    s2 = derive_new_contract_symbol("NIFTY26OCT24800CE", "NIFTY", "CE", 24800.0, 25100.0)
    assert s2 == "NIFTY26OCT25100CE"

    # Empty format fallback
    s3 = derive_new_contract_symbol("", "BANKNIFTY", "PE", 52000.0, 51500.0)
    assert s3 == "BANKNIFTY 51500 PE"


def test_call_deep_itm_roll_up_convexity_reset():
    """Verify Deep-ITM Call generates ROLL_UP advisory with locked profits and risk-free compounding."""
    alert = AutoAlert(
        alert_id="test-nifty-call-revolve",
        alert_type="OPTIONS_MOMENTUM",
        stage="TRIGGERED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="🟢 NIFTY 24800 CE",
        summary="Deep ITM call breakout",
        ltp=340.0,
        trigger_level=160.0,
        target_level=240.0,
        stop_loss=120.0,
        strike=24800.0,
        option_type="CE",
        contract_symbol="NIFTY 24800 CE",
        underlying_spot=25200.0,  # 400 pts ITM = 8 strike steps!
        lot_size=75,
    )

    advisory = evaluate_strike_revolving(
        alert=alert,
        current_ltp=340.0,
        pnl_pct=112.5,
        is_bullish=True,
    )

    assert advisory is not None
    assert advisory.action == "ROLL_UP"
    assert advisory.current_strike == 24800.0
    assert advisory.recommended_strike == 25200.0  # ATM strike
    assert advisory.recommended_contract == "NIFTY 25200 CE"
    assert advisory.locked_profit_pts == 180.0  # 340.0 - 160.0
    assert advisory.risk_free_guarantee is True
    assert "Roll up to liquid ATM 25200 CE" in advisory.reason


def test_put_deep_itm_roll_down_convexity_reset():
    """Verify Deep-ITM Put generates ROLL_DOWN advisory with gamma reset."""
    alert = AutoAlert(
        alert_id="test-bn-put-revolve",
        alert_type="INDEX_PUT_SETUP",
        stage="TRIGGERED",
        symbol="BANKNIFTY",
        exchange="NFO",
        direction="BEARISH",
        headline="🔴 BANKNIFTY 53000 PE",
        summary="Deep ITM put breakdown",
        ltp=950.0,
        trigger_level=420.0,
        target_level=800.0,
        stop_loss=300.0,
        strike=53000.0,
        option_type="PE",
        contract_symbol="BANKNIFTY 53000 PE",
        underlying_spot=52200.0,  # 800 pts ITM = 8 strike steps!
        lot_size=30,
    )

    advisory = evaluate_strike_revolving(
        alert=alert,
        current_ltp=950.0,
        pnl_pct=126.2,
        is_bullish=False,
    )

    assert advisory is not None
    assert advisory.action == "ROLL_DOWN"
    assert advisory.current_strike == 53000.0
    assert advisory.recommended_strike == 52200.0  # ATM strike
    assert advisory.recommended_contract == "BANKNIFTY 52200 PE"
    assert advisory.locked_profit_pts == 530.0  # 950.0 - 420.0
    assert advisory.risk_free_guarantee is True
    assert "Roll down to liquid ATM 52200 PE" in advisory.reason


def test_revolve_suppressed_when_profit_below_threshold():
    """Verify strike revolving is suppressed if pnl_pct < 25% to prevent friction churn."""
    alert = AutoAlert(
        alert_id="test-shallow-pnl",
        alert_type="OPTIONS_MOMENTUM",
        stage="TRIGGERED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="🟢 NIFTY 24800 CE",
        summary="Test",
        ltp=180.0,
        trigger_level=160.0,
        target_level=240.0,
        stop_loss=120.0,
        strike=24800.0,
        option_type="CE",
        contract_symbol="NIFTY 24800 CE",
        underlying_spot=25000.0,
    )

    # 12.5% gain (< 25%)
    adv = evaluate_strike_revolving(alert=alert, current_ltp=180.0, pnl_pct=12.5, is_bullish=True)
    assert adv is None


def test_revolve_suppressed_when_wide_bid_ask_spread(monkeypatch):
    """Verify that candidate strikes with bid-ask spread > 3.0% are rejected to avoid slippage traps."""
    alert = AutoAlert(
        alert_id="test-wide-spread-revolve",
        alert_type="OPTIONS_MOMENTUM",
        stage="TRIGGERED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="🟢 NIFTY 24800 CE",
        summary="Test",
        ltp=300.0,
        trigger_level=160.0,
        target_level=240.0,
        stop_loss=120.0,
        strike=24800.0,
        option_type="CE",
        contract_symbol="NIFTY 24800 CE",
        underlying_spot=25100.0,
    )

    # Mock options chain returning target ATM contract with wide spread (Bid 180, Ask 210, LTP 200 -> 15% spread)
    mock_contract = MagicMock()
    mock_contract.option_type = "CE"
    mock_contract.strike = 25100.0
    mock_contract.last_price = 200.0
    mock_contract.bid = 180.0
    mock_contract.ask = 210.0  # spread = (210 - 180)/200 = 15.0% (> 3.0%)
    mock_contract.symbol = "NIFTY 25100 CE"

    mock_chain = MagicMock()
    mock_chain.contracts = [mock_contract]

    monkeypatch.setattr("market.options.get_options_chain", lambda sym: mock_chain)

    adv = evaluate_strike_revolving(alert=alert, current_ltp=300.0, pnl_pct=87.5, is_bullish=True)
    assert adv is None  # Suppressed due to excessive spread!


def test_0dte_afternoon_expiry_rollover(monkeypatch):
    """Verify that 0DTE options past 13:30 IST on expiry day trigger ROLL_EXPIRY advisory."""
    mock_now = datetime(2026, 10, 15, 14, 15, tzinfo=IST)
    alert = AutoAlert(
        alert_id="test-0dte-revolve",
        alert_type="OPTIONS_MOMENTUM",
        stage="TRIGGERED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="🟢 NIFTY 25000 CE (0DTE)",
        summary="Expiring 0DTE contract",
        ltp=150.0,
        trigger_level=100.0,
        target_level=180.0,
        stop_loss=70.0,
        strike=25000.0,
        option_type="CE",
        contract_symbol="NIFTY 25000 CE",
        underlying_spot=25000.0,
        expiry_date="2026-10-15",
    )

    # Mock current time to 14:15 IST (past 13:30 IST on expiry day)
    monkeypatch.setattr("engine.strike_revolver.datetime", MagicMock(now=lambda tz: mock_now))

    adv = evaluate_strike_revolving(alert=alert, current_ltp=150.0, pnl_pct=50.0, is_bullish=True)
    assert adv is not None
    assert adv.action == "ROLL_EXPIRY"
    assert "0DTE Expiry Session Warning" in adv.reason
    assert "Next-Weekly" in adv.reason


def test_banknifty_afternoon_expiry_rollover_recommends_monthly(monkeypatch):
    """Verify that BANKNIFTY expiring contracts roll to Next-Monthly (never weekly)."""
    mock_now = datetime(2026, 10, 29, 14, 15, tzinfo=IST)  # Last Thursday of month
    alert = AutoAlert(
        alert_id="test-bn-monthly-revolve",
        alert_type="OPTIONS_MOMENTUM",
        stage="TRIGGERED",
        symbol="BANKNIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="🟢 BANKNIFTY 52000 CE (Monthly Expiry)",
        summary="Expiring BankNifty Monthly contract",
        ltp=250.0,
        trigger_level=160.0,
        target_level=320.0,
        stop_loss=100.0,
        strike=52000.0,
        option_type="CE",
        contract_symbol="BANKNIFTY 52000 CE",
        underlying_spot=52100.0,
        expiry_date="2026-10-29",
    )

    monkeypatch.setattr("engine.strike_revolver.datetime", MagicMock(now=lambda tz: mock_now))

    adv = evaluate_strike_revolving(alert=alert, current_ltp=250.0, pnl_pct=56.2, is_bullish=True)
    assert adv is not None
    assert adv.action == "ROLL_EXPIRY"
    assert "Next-Monthly" in adv.reason
    assert "Next-Weekly" not in adv.reason


def test_trade_lifecycle_manager_records_revolve_audit():
    """Verify that TradeLifecycleManager persists revolve_advisory and appends an immutable audit record."""
    alert = AutoAlert(
        alert_id="test-audit-revolve-001",
        alert_type="OPTIONS_MOMENTUM",
        stage="TRIGGERED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="🟢 NIFTY 24800 CE",
        summary="Test",
        ltp=250.0,
        trigger_level=160.0,
        target_level=240.0,
        stop_loss=120.0,
        initial_stop_loss=120.0,
        strike=24800.0,
        option_type="CE",
        contract_symbol="NIFTY 24800 CE",
        underlying_spot=25100.0,
        actionable_plan={
            "target_1": 240.0,
            "target_2": 320.0,
            "stop_loss": 120.0,
        },
    )

    eval_res = evaluate_alert_targets_and_trailing(alert, current_ltp=250.0)
    assert eval_res is not None
    assert eval_res.strike_roll_recommendation is not None

    mgr = TradeLifecycleManager()
    mgr.apply_milestone_state(
        alert=alert,
        eval_res=eval_res,
        cur_quote_ltp=250.0,
        now_ts=1700000000.0,
        now_str="2026-10-19 14:00:00 IST",
    )

    # Verify both properties are set
    assert alert.revolve_advisory is not None
    assert alert.strike_roll_recommendation is not None
    assert alert.revolve_advisory["action"] == "ROLL_UP"

    # Verify audit trail record
    audit_events = [e for e in alert.audit_trail if e.get("action") == "STRIKE_REVOLVE_ADVISORY"]
    assert len(audit_events) == 1
    event = audit_events[0]
    assert event["actor"] == "StrikeRevolver"
    assert event["details"]["recommended_strike"] == 25100.0
    assert event["details"]["action"] == "ROLL_UP"


def test_option_resolver_bid_ask_spread_filtering(monkeypatch):
    """Verify that resolve_option_contract filters out contracts with wide bid-ask spread (> 3.5%)."""
    # Create two candidate contracts near spot (25000):
    # Contract 1: Strike 25000, wide spread (Bid 100, Ask 110, LTP 105 -> 9.5% spread)
    # Contract 2: Strike 25050, tight spread (Bid 80, Ask 81, LTP 80.5 -> 1.2% spread)
    c1 = OptionsContract(
        symbol="NIFTY25000CE",
        underlying="NIFTY",
        expiry="2026-10-22",
        strike=25000.0,
        option_type="CE",
        last_price=105.0,
        oi=10000,
        oi_change=100,
        volume=50000,
        bid=100.0,
        ask=110.0,
    )
    c2 = OptionsContract(
        symbol="NIFTY25050CE",
        underlying="NIFTY",
        expiry="2026-10-22",
        strike=25050.0,
        option_type="CE",
        last_price=80.5,
        oi=10000,
        oi_change=100,
        volume=50000,
        bid=80.0,
        ask=81.0,
    )

    mock_chain = MagicMock()
    mock_chain.contracts = [c1, c2]

    monkeypatch.setattr("market.options.get_options_chain", lambda sym: mock_chain)

    plan = resolve_option_contract(
        symbol="NIFTY",
        direction="BULLISH",
        spot=25000.0,
        strike_tier="ATM",
    )

    assert plan is not None
    # c1 had 9.5% spread, so option resolver should select c2 (1.2% spread)
    assert plan.strike == 25050.0
    assert plan.contract_symbol == "NIFTY25050CE"
    assert plan.bid_ask_spread_pct is not None
    assert plan.bid_ask_spread_pct <= 0.035
