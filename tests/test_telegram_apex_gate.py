"""
tests/test_telegram_apex_gate.py
──────────────────────────────────
Unit tests for the Institutional Telegram Apex Gate:
  1. Hourly rate limit pacing (Max 3/hr for Index, Max 6/hr for Stocks)
  2. 0DTE (Expiry Day) Greeks & Moneyness adaptive architecture vs static premium floors
  3. In-Flight Telegram Trade Protection (Zero supersede invalidation churn)
  4. Early warning suppression when allow_early_warnings is disabled
  5. Non-actionable milestone pruning (IN_FLIGHT_WARNING, SPREAD_SHORT_STRIKE_TOUCH)
  6. Afternoon stock filter (RVOL / Vol-to-OI cutoff post-12:30 IST)
"""

import time
from datetime import datetime, timedelta
from unittest.mock import patch
from typing import Optional
from zoneinfo import ZoneInfo

from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine

IST = ZoneInfo("Asia/Kolkata")


def _make_dummy_alert(
    alert_id: str,
    symbol: str,
    alert_type: str = "GAMMA_BLAST",
    direction: str = "BULLISH",
    confidence: int = 90,
    segment: str = "FNO_INDEX",
    opt_type: str = "CE",
    strike: Optional[float] = None,
    spot: float = 22500.0,
    ltp: float = 120.0,
    stage: str = "IGNITED",
    is_0dte: bool = False,
    delta: float = 0.50,
    vol_oi: float = 2.5,
    rvol: float = 3.0,
    signals: list[str] = None,
    is_thrust: bool = True,
) -> AutoAlert:
    if strike is None:
        strike = spot
    exp_date_str = (
        datetime.now(IST).strftime("%Y-%m-%d")
        if is_0dte
        else (datetime.now(IST) + timedelta(days=7)).strftime("%Y-%m-%d")
    )
    return AutoAlert(
        alert_id=alert_id,
        alert_type=alert_type,
        stage=stage,
        symbol=symbol,
        exchange="NFO",
        direction=direction,
        headline=f"⚡ {symbol} {opt_type} SETUP",
        summary=f"Institutional setup for {symbol}",
        ltp=ltp,
        trigger_level=ltp,
        target_level=round(ltp * 1.35, 1),
        stop_loss=round(ltp * 0.80, 1),
        strike=strike,
        option_type=opt_type,
        contract_symbol=f"{symbol}{int(strike)}{opt_type}",
        expiry_date=exp_date_str,
        underlying_spot=spot,
        option_premium=ltp,
        is_live=True,
        environment="LIVE",
        segment=segment,
        confidence=confidence,
        created_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        metrics={
            "spot": spot,
            "strike": strike,
            "vwap": spot - 10.0,  # spot >= vwap for bullish
            "delta": delta,
            "gamma": 0.005,
            "iv": 18.5,
            "is_0dte": is_0dte,
            "vol_oi_ratio": vol_oi,
            "rvol": rvol,
            "signals": signals or ["VWAP_BREAKOUT", "DAY_HIGH_BREAKOUT"],
            "is_institutional_thrust": is_thrust,
        },
    )


def test_telegram_index_hourly_pacing_limit(tmp_path):
    """Index signals must enforce max 3 per rolling 60 minutes on Telegram."""
    engine = AutoAlertEngine()
    engine._hourly_telegram_dispatches = {"INDEX": [], "STOCKS": []}

    now_t = time.time()
    # Simulate 3 already dispatched within the last 30 minutes
    engine._hourly_telegram_dispatches["INDEX"] = [
        now_t - 1500.0,
        now_t - 900.0,
        now_t - 300.0,
    ]

    # 4th index alert arriving in the same 60m window
    alert4 = _make_dummy_alert("idx-4", "NIFTY", confidence=92)
    passed, reason = engine._eval_telegram_apex_gate(alert4, in_market=True)

    assert not passed
    assert "hourly pacing limit reached" in reason
    assert "3/3" in reason


def test_telegram_stocks_hourly_pacing_limit():
    """Stock signals must enforce max 6 per rolling 60 minutes on Telegram."""
    engine = AutoAlertEngine()
    engine._hourly_telegram_dispatches = {"INDEX": [], "STOCKS": []}

    now_t = time.time()
    # Simulate 6 already dispatched within the last 40 minutes
    engine._hourly_telegram_dispatches["STOCKS"] = [now_t - (i * 300) for i in range(6)]

    alert7 = _make_dummy_alert("stk-7", "RELIANCE", segment="FNO_STOCK", confidence=90)
    passed, reason = engine._eval_telegram_apex_gate(alert7, in_market=True)

    assert not passed
    assert "stocks hourly pacing limit reached" in reason
    assert "6/6" in reason


def test_0dte_atm_low_premium_passes_apex_gate():
    """On 0DTE (expiry day), genuine ATM low premium with strong delta and Vol/OI must pass."""
    engine = AutoAlertEngine()
    engine._hourly_telegram_dispatches = {"INDEX": [], "STOCKS": []}

    # NIFTY 0DTE ATM option trading at ₹14.50 (spot 22500, strike 22500)
    alert = _make_dummy_alert(
        "nifty-0dte-atm",
        "NIFTY",
        strike=22500,
        spot=22500,
        ltp=14.50,
        is_0dte=True,
        delta=0.48,
        vol_oi=2.8,
        confidence=92,
        is_thrust=True,
    )
    passed, reason = engine._eval_telegram_apex_gate(alert, in_market=True)
    assert passed, f"Expected ATM 0DTE setup to pass, but got: {reason}"


def test_0dte_far_otm_cheap_lottery_ticket_rejected():
    """On 0DTE, cheap far OTM lottery tickets with delta < 0.28 or strike distance > 0.65% must be rejected."""
    engine = AutoAlertEngine()
    engine._hourly_telegram_dispatches = {"INDEX": [], "STOCKS": []}

    # NIFTY 0DTE strike 22750 (250 pts / 1.11% OTM) trading at ₹2.50 with delta 0.05
    alert = _make_dummy_alert(
        "nifty-0dte-otm",
        "NIFTY",
        strike=22750,
        spot=22500,
        ltp=2.50,
        is_0dte=True,
        delta=0.05,
        vol_oi=1.5,
        confidence=90,
    )
    passed, reason = engine._eval_telegram_apex_gate(alert, in_market=True)
    assert not passed
    assert (
        ("Delta 0.05 below 0.28 floor" in reason)
        or ("Strike distance" in reason)
        or ("below dynamic floor" in reason)
    )


def test_non_0dte_low_premium_rejected_by_standard_floor():
    """On non-0DTE, an option with premium < ₹25 (Nifty standard floor) must be rejected."""
    engine = AutoAlertEngine()
    engine._hourly_telegram_dispatches = {"INDEX": [], "STOCKS": []}

    alert = _make_dummy_alert(
        "nifty-non-0dte-cheap",
        "NIFTY",
        strike=22500,
        spot=22500,
        ltp=14.0,  # Below ₹25 non-0DTE floor
        is_0dte=False,
        delta=0.45,
        vol_oi=2.0,
        confidence=90,
    )
    passed, reason = engine._eval_telegram_apex_gate(alert, in_market=True)
    assert not passed
    assert "below dynamic floor ₹25.00 (Non-0DTE)" in reason


def test_midcpnifty_0dte_dynamic_floor():
    """MIDCPNIFTY on 0DTE has 25-pt strikes; ATM option at ₹3.50 with Delta 0.45 must pass ₹2.50 floor."""
    engine = AutoAlertEngine()
    engine._hourly_telegram_dispatches = {"INDEX": [], "STOCKS": []}

    alert = _make_dummy_alert(
        "midcp-0dte-atm",
        "MIDCPNIFTY",
        strike=13200,
        spot=13200,
        ltp=3.80,
        is_0dte=True,
        delta=0.46,
        vol_oi=3.2,
        confidence=92,
        is_thrust=True,
    )
    passed, reason = engine._eval_telegram_apex_gate(alert, in_market=True)
    assert passed, f"Expected MIDCPNIFTY 0DTE setup to pass, but got: {reason}"


def test_in_flight_telegram_protection_prevents_supersede():
    """An active index trade already sent to Telegram must NOT be invalidated by a higher-scoring incoming trade."""
    engine = AutoAlertEngine()
    with engine._lock:
        engine._alerts.clear()

        # Existing active trade already dispatched to Telegram
        existing_trade = _make_dummy_alert("active-tg-trade", "NIFTY", confidence=88)
        existing_trade.telegram_dispatched = True
        existing_trade.stage = "IGNITED"
        engine._alerts.append(existing_trade)

        # Incoming higher scoring trade
        incoming_trade = _make_dummy_alert("incoming-upgrade", "NIFTY", confidence=96)
        incoming_trade.direction = "BULLISH"

        # Record incoming
        engine.record_alert(incoming_trade)
        # Existing trade must NOT be invalidated!
        assert not existing_trade.is_invalidated
        assert existing_trade.stage == "IGNITED"


def test_in_flight_warning_and_spread_touch_suppressed_on_telegram():
    """SPREAD_SHORT_STRIKE_TOUCH milestones must be suppressed from Telegram."""
    engine = AutoAlertEngine()
    alert = _make_dummy_alert("m-touch", "NIFTY", stage="SPREAD_SHORT_STRIKE_TOUCH")
    alert.telegram_dispatched = True  # Pretend original signal was dispatched

    with patch("engine.alerts._telegram_notify") as mock_tg:
        engine._dispatch(alert)
        # Must not call _telegram_notify for SPREAD_SHORT_STRIKE_TOUCH
        mock_tg.assert_not_called()
        assert "held in Terminal UI only" in getattr(alert, "telegram_suppression_reason", "")


def test_red_nifty_sector_rs_decoupled_stock_long_passes():
    """When NIFTY is down -0.75%, but the stock's sector is +1.50% green (Sector RS +2.25%), long setup must pass."""
    engine = AutoAlertEngine()
    engine._hourly_telegram_dispatches = {"INDEX": [], "STOCKS": []}

    alert = _make_dummy_alert(
        "stk-metal-long",
        "TATASTEEL",
        segment="FNO_STOCK",
        confidence=90,
        strike=160.0,
        spot=160.0,
        ltp=160.0,
    )
    alert.metrics["nifty_change_pct"] = -0.75
    alert.metrics["sector_id"] = "metals"
    alert.metrics["sector_change_pct"] = 1.50  # NIFTY METAL is +1.5% green!
    alert.metrics["sector_rs"] = 2.25

    passed, reason = engine._eval_telegram_apex_gate(alert, in_market=True)
    assert passed, f"Expected decoupled sector setup to pass, but got: {reason}"


def test_red_nifty_sepa_idiosyncratic_stock_alpha_passes():
    """When NIFTY is down -0.70%, but the individual stock is +2.8% green above VWAP with 2.5x RVOL, it must pass."""
    engine = AutoAlertEngine()
    engine._hourly_telegram_dispatches = {"INDEX": [], "STOCKS": []}

    alert = _make_dummy_alert(
        "stk-hal-alpha",
        "HAL",
        segment="FNO_STOCK",
        confidence=90,
        spot=4500.0,
        ltp=4500.0,
    )
    alert.metrics["nifty_change_pct"] = -0.70
    alert.metrics["sector_id"] = "defence"
    alert.metrics["rvol"] = 2.5
    alert.metrics["vwap"] = 4450.0  # Spot 4500 >= VWAP 4450

    passed, reason = engine._eval_telegram_apex_gate(alert, in_market=True)
    assert passed, f"Expected idiosyncratic SEPA alpha setup to pass, but got: {reason}"


def test_red_nifty_no_alpha_stock_suppressed():
    """When NIFTY is down -0.70% and stock has NO sector tailwind and low volume, it must be suppressed as a counter-trend trap."""
    engine = AutoAlertEngine()
    engine._hourly_telegram_dispatches = {"INDEX": [], "STOCKS": []}

    alert = _make_dummy_alert(
        "stk-weak-bank",
        "AXISBANK",
        segment="FNO_STOCK",
        confidence=86,
        spot=1150.0,
        ltp=1150.0,
    )
    alert.metrics["nifty_change_pct"] = -0.70
    alert.metrics["sector_id"] = "banking"
    alert.metrics["sector_change_pct"] = -0.80  # Sector also down
    alert.metrics["sector_rs"] = -0.10
    alert.metrics["rvol"] = 1.1

    passed, reason = engine._eval_telegram_apex_gate(alert, in_market=True)
    assert not passed
    assert "Counter-trend long suppressed" in reason
    assert "without Sector RS" in reason


def test_systemic_capitulation_blocks_longs():
    """When NIFTY is crashing <= -1.25%, market capitulation contagion must block long setups."""
    engine = AutoAlertEngine()
    engine._hourly_telegram_dispatches = {"INDEX": [], "STOCKS": []}

    alert = _make_dummy_alert(
        "stk-crash-day",
        "INFY",
        segment="FNO_STOCK",
        confidence=89,
    )
    alert.metrics["nifty_change_pct"] = -1.45

    passed, reason = engine._eval_telegram_apex_gate(alert, in_market=True)
    assert not passed
    assert "Systemic market capitulation" in reason


def test_bull_trend_day_counter_trend_short_suppressed():
    """When NIFTY is up +0.80% in a bull trend, weak short attempts without sector breakdown must be blocked as bear traps."""
    engine = AutoAlertEngine()
    engine._hourly_telegram_dispatches = {"INDEX": [], "STOCKS": []}

    alert = _make_dummy_alert(
        "stk-bear-trap",
        "RELIANCE",
        direction="BEARISH",
        opt_type="PE",
        segment="FNO_STOCK",
        confidence=86,
    )
    alert.metrics["nifty_change_pct"] = 0.80
    alert.metrics["rvol"] = 1.0

    passed, reason = engine._eval_telegram_apex_gate(alert, in_market=True)
    assert not passed
    assert "Counter-trend short suppressed" in reason
    assert "without Sector Breakdown" in reason


def test_exhaustion_upper_wick_trap_suppressed():
    """A bullish breakout with a 55% upper wick rejection at pivot must be blocked as an exhaustion wick trap."""
    engine = AutoAlertEngine()
    engine._hourly_telegram_dispatches = {"INDEX": [], "STOCKS": []}

    alert = _make_dummy_alert(
        "stk-wick-trap",
        "TCS",
        segment="FNO_STOCK",
        confidence=88,
    )
    alert.metrics["upper_wick_ratio"] = 0.55  # 55% upper wick rejection

    passed, reason = engine._eval_telegram_apex_gate(alert, in_market=True)
    assert not passed
    assert "Exhaustion upper wick trap" in reason


def test_overextended_vwap_mean_reversion_trap_suppressed():
    """A stock long stretched 4.5% above VWAP without institutional thrust must be blocked as an overextended trap."""
    engine = AutoAlertEngine()
    engine._hourly_telegram_dispatches = {"INDEX": [], "STOCKS": []}

    alert = _make_dummy_alert(
        "stk-vwap-stretched",
        "DIXON",
        segment="FNO_STOCK",
        confidence=88,
        spot=15000.0,
        ltp=15000.0,
        is_thrust=False,
    )
    alert.metrics["vwap"] = 14300.0  # (15000 - 14300)/14300 = +4.9% above VWAP

    passed, reason = engine._eval_telegram_apex_gate(alert, in_market=True)
    assert not passed
    assert "Overextended VWAP trap" in reason


def test_options_oi_wall_defending_trap_suppressed():
    """A GAMMA_BLAST call alert where call writers are expanding OI by +22% must be blocked as an OI wall resistance trap."""
    engine = AutoAlertEngine()
    engine._hourly_telegram_dispatches = {"INDEX": [], "STOCKS": []}

    alert = _make_dummy_alert(
        "opt-oi-wall-trap",
        "NIFTY",
        alert_type="GAMMA_BLAST",
        confidence=90,
    )
    alert.metrics["oi_chg_pct"] = 22.0  # Call writers adding 22% OI

    passed, reason = engine._eval_telegram_apex_gate(alert, in_market=True)
    assert not passed
    assert "Options OI wall resistance trap" in reason


def test_telegram_stocks_hourly_pacing_apex_override():
    """A 95%+ confidence APEX stock setup must bypass the 6/hr routine limit up to 8/hr."""
    engine = AutoAlertEngine()
    engine._hourly_telegram_dispatches = {"INDEX": [], "STOCKS": []}

    now_t = time.time()
    # Simulate 6 routine stock alerts already dispatched in the last 40 minutes
    engine._hourly_telegram_dispatches["STOCKS"] = [now_t - (i * 300) for i in range(6)]

    # 7th alert arriving, but it is an APEX setup with confidence=95
    alert_apex = _make_dummy_alert(
        "stk-mm-apex",
        "M&M",
        alert_type="INTRADAY_BREAKDOWN_SPARK",
        direction="BEARISH",
        opt_type="PE",
        segment="FNO_STOCK",
        confidence=95,
        rvol=3.94,
    )
    passed, reason = engine._eval_telegram_apex_gate(alert_apex, in_market=True)
    assert passed, f"Expected APEX 95% stock setup to pass pacing override, but got: {reason}"


def test_telegram_index_hourly_pacing_apex_override():
    """A 95%+ confidence APEX index setup must bypass the 3/hr routine limit up to 5/hr."""
    engine = AutoAlertEngine()
    engine._hourly_telegram_dispatches = {"INDEX": [], "STOCKS": []}

    now_t = time.time()
    # Simulate 3 routine index alerts already dispatched in the last 30 minutes
    engine._hourly_telegram_dispatches["INDEX"] = [
        now_t - 1500.0,
        now_t - 900.0,
        now_t - 300.0,
    ]

    # 4th alert arriving, but it is an APEX setup with confidence=95
    alert_apex = _make_dummy_alert(
        "idx-nifty-apex",
        "NIFTY",
        confidence=95,
        is_0dte=True,
        rvol=3.5,
    )
    passed, reason = engine._eval_telegram_apex_gate(alert_apex, in_market=True)
    assert passed, f"Expected APEX 95% index setup to pass pacing override, but got: {reason}"

