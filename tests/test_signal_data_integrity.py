"""
tests/test_signal_data_integrity.py
───────────────────────────────────
Institutional Unit Tests for the Centralized Signal Data Integrity Framework:
  1. Complete & Positive Price Levels (LTP, SL, Target > 0)
  2. Geometric Level Sanity (SL < LTP < T1 for long/option, T1 < LTP < SL for short)
  3. Option Coordinate Boundary Sanctity (Premium < Spot, Premium < Strike for PE, No Spot SL leakage)
  4. Contract vs Expiry Date Coherence (Contract Symbol YYYYMMDD == Alert Expiry Date)
  5. Non-Negative DTE (Reject historical/expired dates in live alerts)
  6. Zero Bid Liquidity Veto (Order book exit liquidity audit)
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from engine.alert_model import AutoAlert
from engine.alert_scrutiny import alert_scrutiny_auditor

IST = ZoneInfo("Asia/Kolkata")


def make_alert(**overrides) -> AutoAlert:
    defaults = {
        "alert_id": "aa-test-integrity-001",
        "alert_type": "BREAKOUT",
        "stage": "IGNITED",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "direction": "BULLISH",
        "headline": "RELIANCE Breakout Ignition",
        "summary": "Institutional volume surge above resistance",
        "ltp": 2950.0,
        "trigger_level": 2950.0,
        "target_level": 3030.0,
        "stop_loss": 2910.0,
        "confidence": 88,
        "is_live": True,
        "environment": "LIVE",
    }
    defaults.update(overrides)
    return AutoAlert(**defaults)


def test_valid_equity_alert_data_integrity():
    """A valid, clean equity breakout alert passes all data integrity checks."""
    alert = make_alert()
    is_valid, reason = alert.validate_data_integrity()
    assert is_valid is True
    assert reason == ""

    passed, rej, flags = alert_scrutiny_auditor.verify_tier1_sanity(alert)
    assert passed is True


def test_incomplete_or_zero_price_levels():
    """Zero or negative LTP/SL/Target fails data integrity."""
    alert = make_alert(ltp=0.0)
    is_valid, reason = alert.validate_data_integrity()
    assert is_valid is False
    assert "Incomplete price levels" in reason


def test_inverted_stop_loss_or_target():
    """Stop-loss higher than LTP on a long setup fails data integrity."""
    alert = make_alert(stop_loss=3000.0)  # Inverted: SL (3000) > LTP (2950)
    is_valid, reason = alert.validate_data_integrity()
    assert is_valid is False
    assert "Inverted Stop-Loss" in reason


def test_option_coordinate_spot_leakage_veto():
    """Passing underlying spot price as option premium fails coordinate sanity."""
    alert = make_alert(
        alert_type="OPTIONS_MOMENTUM",
        symbol="UNITDSPR",
        contract_symbol="UNITDSPR202610271380PE",
        option_type="PE",
        strike=1380.0,
        ltp=1376.3,  # Spot leaked as option premium!
        stop_loss=1409.7,
        target_level=1300.0,
        underlying_spot=1376.3,
    )
    is_valid, reason = alert.validate_data_integrity()
    assert is_valid is False
    assert "Option Coordinate Veto" in reason


def test_option_spot_stop_loss_leakage_veto():
    """Option stop-loss > 2.5x option premium indicates underlying spot SL leakage."""
    alert = make_alert(
        alert_type="OPTIONS_MOMENTUM",
        symbol="UNITDSPR",
        contract_symbol="UNITDSPR202610271380PE",
        option_type="PE",
        strike=1380.0,
        ltp=27.5,  # Correct option premium
        stop_loss=1409.7,  # Leaked spot SL instead of option SL!
        target_level=55.0,
        underlying_spot=1376.3,
    )
    is_valid, reason = alert.validate_data_integrity()
    assert is_valid is False
    assert "Option SL" in reason and "spot SL leakage" in reason


def test_contract_and_expiry_date_coherence_mismatch():
    """Contract symbol date (e.g. 20260929) conflicting with alert.expiry_date (2026-10-27) is vetoed."""
    alert = make_alert(
        alert_type="OPTIONS_MOMENTUM",
        symbol="UNITDSPR",
        contract_symbol="UNITDSPR202609291380PE",  # Encodes 2026-09-29
        expiry_date="2026-10-27",  # Contradiction!
        option_type="PE",
        strike=1380.0,
        ltp=27.5,
        stop_loss=21.4,
        target_level=37.1,
        underlying_spot=1376.3,
    )
    is_valid, reason = alert.validate_data_integrity()
    assert is_valid is False
    assert "Contract/Expiry Mismatch" in reason


def test_historical_expired_date_veto(monkeypatch):
    """Signals referencing expired historical contracts fail closed in production/live mode."""
    monkeypatch.delenv("CHANAKYA_TESTING", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    yesterday = (datetime.now(IST).date() - timedelta(days=2)).isoformat()
    alert = make_alert(
        alert_id="aa-live-prod-signal-99",  # Does not start with test-
        alert_type="OPTIONS_MOMENTUM",
        symbol="NIFTY",
        contract_symbol=f"NIFTY{yesterday.replace('-', '')}25000CE",
        expiry_date=yesterday,  # Expired!
        option_type="CE",
        strike=25000.0,
        ltp=120.0,
        stop_loss=90.0,
        target_level=180.0,
        underlying_spot=25100.0,
        is_live=True,
        environment="LIVE",
    )
    is_valid, reason = alert.validate_data_integrity()
    assert is_valid is False
    assert "Historical Expiry Veto" in reason


def test_zero_bid_liquidity_veto():
    """Contract with active ask but 0.00 bid is vetoed for zero exit liquidity."""
    alert = make_alert(
        alert_type="OPTIONS_MOMENTUM",
        symbol="UNITDSPR",
        contract_symbol="UNITDSPR202610271380PE",
        expiry_date="2026-10-27",
        option_type="PE",
        strike=1380.0,
        ltp=27.5,
        stop_loss=21.4,
        target_level=37.1,
        underlying_spot=1376.3,
        metrics={"bid": 0.0, "ask": 29.5},
    )
    passed, rej_reason, flags = alert_scrutiny_auditor.verify_tier1_sanity(alert)
    assert passed is False
    assert "Zero Bid Liquidity Veto" in rej_reason


def test_option_execution_plan_never_generates_inverted_sl():
    """Option execution plan must clamp SL strictly below entry premium for all options."""
    from engine.trade_plan import calculate_trade_plan, calculate_option_execution_plan

    tp = calculate_trade_plan("BANKNIFTY", direction="SELL", spot=54120.0, timeframe="INTRADAY")
    opt_plan = calculate_option_execution_plan(
        trade_plan=tp,
        option_type="PE",
        strike=54400.0,
        expiry="2026-10-27",
        option_ltp=142.5,
        lot_size=15,
    )
    sl = opt_plan["sl_premium"]
    assert sl < 142.5
    assert sl <= round(142.5 * 0.88, 2)
    assert sl >= round(142.5 * 0.72, 2)


def test_alert_evaluator_suppresses_invalidation_on_inverted_sl():
    """Alert evaluator must not trigger false 'Option premium collapsed' when alert has an inverted SL defect."""
    from engine.alert_evaluator import evaluate_alert_invalidation

    # Inverted SL: SL (149.0) > Entry (142.5)
    bad_alert = make_alert(
        alert_type="GAMMA_BLAST",
        symbol="BANKNIFTY",
        contract_symbol="BANKNIFTY2026102754400PE",
        option_type="PE",
        strike=54400.0,
        ltp=142.5,
        trigger_level=142.5,
        stop_loss=149.0,
        target_level=200.0,
        direction="BEARISH",
        is_live=True,
    )
    # Evaluating current_ltp=142.5 (which is below bad SL of 149.0) must NOT fire an invalidation!
    reason = evaluate_alert_invalidation(bad_alert, current_ltp=142.5)
    assert reason is None
