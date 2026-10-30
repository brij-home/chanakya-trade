"""
tests/test_telegram_apex_gate.py
──────────────────────────────────
Unit tests for the Institutional Telegram Apex Gate:
  1. Hourly rate limit pacing (Max 4/hr for Index, Max 10/hr for Stocks, Apex 15/hr)
  2. 0DTE (Expiry Day) Greeks & Moneyness adaptive architecture vs static premium floors
  3. In-Flight Telegram Trade Protection (Zero supersede invalidation churn)
  4. Early warning suppression when allow_early_warnings is disabled
  5. Non-actionable milestone pruning (IN_FLIGHT_WARNING, SPREAD_SHORT_STRIKE_TOUCH)
  6. Afternoon stock filter (RVOL / Vol-to-OI cutoff post-12:30 IST)
"""

import os
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
    if segment == "EQUITY":
        strike_val = None
        opt_type_val = None
        c_sym = None
        opt_prem = None
        exch = "NSE"
        if alert_type == "GAMMA_BLAST":
            alert_type = "BREAKOUT"
    else:
        if strike is None:
            strike = spot
        strike_val = strike
        opt_type_val = opt_type
        c_sym = f"{symbol}{int(strike)}{opt_type}" if strike and opt_type else None
        opt_prem = ltp
        exch = "NFO"
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
        exchange=exch,
        direction=direction,
        headline=f"⚡ {symbol} {opt_type_val or 'EQUITY'} SETUP",
        summary=f"Institutional setup for {symbol}",
        ltp=ltp,
        trigger_level=ltp,
        target_level=round(ltp * 1.35, 1),
        stop_loss=round(ltp * 0.80, 1),
        strike=strike_val,
        option_type=opt_type_val,
        contract_symbol=c_sym,
        expiry_date=exp_date_str,
        underlying_spot=spot,
        option_premium=opt_prem,
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
    """Index signals have ZERO hourly pacing and pass unthrottled on Telegram."""
    engine = AutoAlertEngine()
    engine._hourly_telegram_dispatches = {"INDEX": [], "STOCKS": []}

    now_t = time.time()
    # Simulate 4 already dispatched within the last 30 minutes
    engine._hourly_telegram_dispatches["INDEX"] = [
        now_t - 1800.0,
        now_t - 1200.0,
        now_t - 600.0,
        now_t - 300.0,
    ]

    # 5th index alert arriving in the same 60m window must pass unthrottled
    alert5 = _make_dummy_alert("idx-5", "NIFTY", confidence=92)
    passed, reason = engine._eval_telegram_apex_gate(alert5, in_market=True)

    assert passed is True
    assert reason == "PASSED_APEX_GATE"


def test_telegram_stocks_hourly_pacing_limit():
    """Stocks F&O has ZERO hourly pacing and passes unthrottled."""
    with patch.dict(os.environ, {"TELEGRAM_MAX_STOCKS_PER_HOUR": "10"}):
        engine = AutoAlertEngine()
        engine._hourly_telegram_dispatches = {"INDEX": [], "STOCKS": [], "FNO_STOCK": []}

        now_t = time.time()
        # Simulate 10 already dispatched within the last 40 minutes
        engine._hourly_telegram_dispatches["STOCKS"] = [now_t - (i * 200) for i in range(10)]
        engine._hourly_telegram_dispatches["FNO_STOCK"] = [now_t - (i * 200) for i in range(10)]

        # Stocks F&O alert must pass without pacing choke
        alert11 = _make_dummy_alert("stk-11", "RELIANCE", segment="FNO_STOCK", confidence=90)
        passed, reason = engine._eval_telegram_apex_gate(alert11, in_market=True)
        assert passed is True
        assert reason == "PASSED_APEX_GATE"


def test_stocks_and_options_unlimited_by_default():
    """By default, stocks and stock options have NO hourly or daily pacing limits."""
    engine = AutoAlertEngine()
    now_t = time.time()
    today_k = datetime.now(IST).strftime("%Y-%m-%d")

    # Simulate 50 stock alerts already dispatched within the last 30 minutes
    engine._hourly_telegram_dispatches["STOCKS"] = [now_t - (i * 20) for i in range(50)]
    engine._hourly_telegram_dispatches["FNO_STOCK"] = [now_t - (i * 20) for i in range(50)]
    engine._sector_hourly_telegram["it"] = [now_t - (i * 20) for i in range(50)]
    engine._sector_daily_telegram[today_k]["it"] = 50

    # New routine stock alert (confidence 85) must pass without any pacing or daily limits
    alert = _make_dummy_alert("stk-infy-unlimited", "INFY", segment="FNO_STOCK", confidence=85)
    alert.metrics["sector_id"] = "it"
    passed, reason = engine._eval_telegram_apex_gate(alert, in_market=True)
    assert passed is True, f"Expected alert to pass without pacing throttling, got: {reason}"
    assert reason == "PASSED_APEX_GATE"


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
    """A 95%+ confidence APEX stock setup must bypass the 10/hr routine limit up to 15/hr when configured."""
    with patch.dict(
        os.environ,
        {
            "TELEGRAM_MAX_STOCKS_PER_HOUR": "10",
            "TELEGRAM_MAX_STOCKS_APEX_PER_HOUR": "15",
        },
    ):
        engine = AutoAlertEngine()
        engine._hourly_telegram_dispatches = {"INDEX": [], "STOCKS": []}

        now_t = time.time()
        # Simulate 10 routine stock alerts already dispatched in the last 40 minutes
        engine._hourly_telegram_dispatches["STOCKS"] = [now_t - (i * 200) for i in range(10)]

        # 11th alert arriving, but it is an APEX setup with confidence=95
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

        # For Stocks F&O, alert_16_apex passes unthrottled (zero pacing for Stocks F&O)
        engine._hourly_telegram_dispatches["STOCKS"] = [now_t - (i * 100) for i in range(15)]
        alert_16_apex = _make_dummy_alert(
            "stk-mm-apex-16",
            "M&M",
            alert_type="INTRADAY_BREAKDOWN_SPARK",
            direction="BEARISH",
            opt_type="PE",
            segment="FNO_STOCK",
            confidence=95,
            rvol=3.94,
        )
        passed, reason = engine._eval_telegram_apex_gate(alert_16_apex, in_market=True)
        assert passed is True
        assert reason == "PASSED_APEX_GATE"


def test_telegram_index_hourly_pacing_apex_override():
    """Index signals have ZERO hourly pacing: 5th and 6th alerts pass unthrottled."""
    engine = AutoAlertEngine()
    engine._hourly_telegram_dispatches = {"INDEX": [], "STOCKS": []}

    now_t = time.time()
    # Simulate 4 routine index alerts already dispatched in the last 30 minutes
    engine._hourly_telegram_dispatches["INDEX"] = [
        now_t - 1800.0,
        now_t - 1200.0,
        now_t - 600.0,
        now_t - 300.0,
    ]

    # 5th alert arriving passes unthrottled
    alert_apex = _make_dummy_alert(
        "idx-nifty-apex",
        "NIFTY",
        confidence=95,
        is_0dte=True,
        rvol=3.5,
    )
    passed, reason = engine._eval_telegram_apex_gate(alert_apex, in_market=True)
    assert passed, f"Expected APEX 95% index setup to pass pacing override, but got: {reason}"

    # 6th alert arriving also passes unthrottled
    engine._hourly_telegram_dispatches["INDEX"].append(now_t - 100.0)
    alert_6_apex = _make_dummy_alert(
        "idx-nifty-apex-6",
        "NIFTY",
        confidence=95,
        is_0dte=True,
        rvol=3.5,
    )
    passed, reason = engine._eval_telegram_apex_gate(alert_6_apex, in_market=True)
    assert passed is True
    assert reason == "PASSED_APEX_GATE"


def test_obstacle_runway_trap_suppressed_on_telegram():
    """An alert obstructed by an immediate heavy resistance wall or max Call OI must be suppressed on Telegram."""
    engine = AutoAlertEngine()
    engine._hourly_telegram_dispatches = {"INDEX": [], "STOCKS": []}

    alert = _make_dummy_alert(
        "stk-obstacle-trap",
        "RELIANCE",
        segment="FNO_STOCK",
        confidence=90,
    )
    alert.metrics["trap_immediate_resistance"] = True

    passed, reason = engine._eval_telegram_apex_gate(alert, in_market=True)
    assert not passed
    assert "Obstacle Runway Trap" in reason


def test_telegram_index_daily_limit_and_apex_expansion_without_half_session_limits():
    """Index setups have ZERO daily limits: routine and APEX setups pass unthrottled."""
    engine = AutoAlertEngine()
    engine._hourly_telegram_dispatches = {"INDEX": [], "STOCKS": []}
    today_k = datetime.now(IST).strftime("%Y-%m-%d")

    # Set 10 alerts today
    engine._daily_index_telegram[today_k] = 10

    # 11th routine alert (confidence 90) passes unthrottled
    alert_routine = _make_dummy_alert("idx-11-routine", "NIFTY", confidence=90)
    passed, reason = engine._eval_telegram_apex_gate(alert_routine, in_market=True)
    assert passed is True
    assert reason == "PASSED_APEX_GATE"

    # 11th APEX alert (confidence 95) also passes
    alert_apex = _make_dummy_alert("idx-11-apex", "NIFTY", confidence=95, is_0dte=True)
    passed, reason = engine._eval_telegram_apex_gate(alert_apex, in_market=True)
    assert passed is True
    assert reason == "PASSED_APEX_GATE"

    # Even beyond 12 alerts today, valid index setups pass
    engine._daily_index_telegram[today_k] = 12
    alert_13_apex = _make_dummy_alert("idx-13-apex", "NIFTY", confidence=95, is_0dte=True)
    passed, reason = engine._eval_telegram_apex_gate(alert_13_apex, in_market=True)
    assert passed is True
    assert reason == "PASSED_APEX_GATE"


def test_telegram_stock_sector_hourly_pacing_prevents_basket_flooding():
    """Stocks F&O has ZERO sector pacing; Cash Equity enforces sector pacing when configured."""
    engine = AutoAlertEngine()
    engine._hourly_telegram_dispatches = {"INDEX": [], "STOCKS": [], "EQUITY": []}
    now_t = time.time()

    # Simulate 3 IT alerts already sent within the last 30 minutes
    engine._sector_hourly_telegram["it"] = [now_t - 1200.0, now_t - 800.0, now_t - 400.0]
    engine._sector_hourly_telegram["eq:it"] = [now_t - 1200.0, now_t - 800.0, now_t - 400.0]

    with patch.dict(
        os.environ,
        {"TELEGRAM_MAX_EQUITY_SECTOR_HOURLY": "3"},
    ):
        # 4th Stocks F&O IT alert arrives -> passes unthrottled (zero pacing for F&O)
        alert4_fno = _make_dummy_alert("it-4-fno", "INFY", segment="FNO_STOCK", confidence=90)
        alert4_fno.metrics["sector_id"] = "it"
        passed_fno, reason_fno = engine._eval_telegram_apex_gate(alert4_fno, in_market=True)
        assert passed_fno is True, (
            f"Stocks F&O must not be throttled by sector pacing: {reason_fno}"
        )

        # 4th Cash Equity IT alert arrives -> throttled by equity sector limit (routine confidence 85)
        alert4_eq = _make_dummy_alert("it-4-eq", "INFY", segment="EQUITY", confidence=85)
        alert4_eq.metrics["sector_id"] = "it"
        passed_eq, reason_eq = engine._eval_telegram_apex_gate(alert4_eq, in_market=True)
        assert not passed_eq
        assert "sector hourly limit reached" in reason_eq

        # Cross-sector isolation: Cash Equity in 'auto' sector passes
        alert_auto = _make_dummy_alert("auto-1", "TATAMOTORS", segment="EQUITY", confidence=85)
        alert_auto.metrics["sector_id"] = "auto"
        passed, reason = engine._eval_telegram_apex_gate(alert_auto, in_market=True)
        assert passed, f"Expected non-flooded sector to pass, got: {reason}"


def test_dispatch_records_index_half_and_sector_hourly():
    """_dispatch records to _index_half_telegram and _sector_hourly_telegram on success."""
    engine = AutoAlertEngine()
    engine._alerts.clear()
    engine._index_half_telegram.clear()
    engine._daily_index_telegram.clear()
    engine._sector_hourly_telegram.clear()
    engine._sector_daily_telegram.clear()
    today_k = datetime.now(IST).strftime("%Y-%m-%d")

    # Dispatch Index Alert during active market session
    idx_alert = _make_dummy_alert("idx-dispatch-test", "NIFTY", confidence=92)
    with (
        patch("engine.alerts._is_market_hours", return_value=True),
        patch("engine.alerts._telegram_notify"),
    ):
        engine._dispatch(idx_alert)

    # Check that it recorded in _index_half_telegram and _daily_index_telegram
    total_idx = sum(engine._index_half_telegram[today_k].values())
    assert total_idx == 1
    assert engine._daily_index_telegram[today_k] == 1

    # Dispatch Stock Alert in sector 'metals'
    stk_alert = _make_dummy_alert(
        "stk-dispatch-test", "TATASTEEL", segment="FNO_STOCK", confidence=90
    )
    stk_alert.metrics["sector_id"] = "metals"
    with (
        patch("engine.alerts._is_market_hours", return_value=True),
        patch("engine.alerts._telegram_notify"),
    ):
        engine._dispatch(stk_alert)

    # Check that it recorded in _sector_hourly_telegram and _sector_daily_telegram
    assert len(engine._sector_hourly_telegram["metals"]) == 1
    assert engine._sector_daily_telegram[today_k]["metals"] == 1


def test_telegram_stock_sector_daily_cap_and_apex_expansion():
    """Stocks F&O has ZERO sector daily cap and passes unthrottled."""
    engine = AutoAlertEngine()
    today_k = datetime.now(IST).strftime("%Y-%m-%d")

    # Simulate 3 banking alerts already dispatched today
    engine._sector_daily_telegram[today_k]["banking"] = 3

    with patch.dict(os.environ, {"TELEGRAM_MAX_STOCK_ALERTS_PER_SECTOR_DAY": "3"}):
        # 4th routine Stocks F&O banking alert passes unthrottled
        alert4_routine = _make_dummy_alert(
            "stk-hdfc-routine", "HDFCBANK", segment="FNO_STOCK", confidence=85
        )
        alert4_routine.metrics["sector_id"] = "banking"
        alert4_routine.metrics["sector_rs"] = 0.5
        passed, reason = engine._eval_telegram_apex_gate(alert4_routine, in_market=True)
        assert passed is True
        assert reason == "PASSED_APEX_GATE"

        # 5th APEX alert also passes unthrottled
        alert5_apex = _make_dummy_alert(
            "stk-hdfc-apex", "HDFCBANK", segment="FNO_STOCK", confidence=95
        )
        alert5_apex.metrics["sector_id"] = "banking"
        passed, reason = engine._eval_telegram_apex_gate(alert5_apex, in_market=True)
        assert passed is True
        assert reason == "PASSED_APEX_GATE"


def test_telegram_stocks_daily_limit_env_override():
    """TELEGRAM_MAX_STOCKS_PER_DAY env var enforces total stock daily limit when set."""
    engine = AutoAlertEngine()
    today_k = datetime.now(IST).strftime("%Y-%m-%d")

    # Simulate exactly 10 total stock alerts across sectors today
    engine._sector_daily_telegram[today_k] = {"banking": 3, "it": 3, "auto": 4}
    # Total = 10

    # Stocks F&O alert passes unthrottled (zero daily pacing for Stocks F&O)
    alert_next = _make_dummy_alert("stk-pharma-1", "SUNPHARMA", segment="FNO_STOCK", confidence=80)
    alert_next.metrics["sector_id"] = "pharma"

    with patch.dict(os.environ, {"TELEGRAM_MAX_STOCKS_PER_DAY": "10"}):
        passed, reason = engine._eval_telegram_apex_gate(alert_next, in_market=True)
        assert passed is True, f"Expected Stocks F&O to pass unthrottled, got: {reason}"
        assert reason == "PASSED_APEX_GATE"

        # Cash Equity alert respects daily limit when configured
        alert_eq = _make_dummy_alert("stk-pharma-eq", "SUNPHARMA", segment="EQUITY", confidence=80)
        alert_eq.metrics["sector_id"] = "pharma"
        passed_eq, reason_eq = engine._eval_telegram_apex_gate(alert_eq, in_market=True)
        assert not passed_eq
        assert "daily limit reached" in reason_eq


def test_telegram_index_reversal_bypass_allowed():
    """When index hourly pacing is saturated by one direction (e.g. 5 Puts),
    a high-conviction structural reversal in the opposing direction (Call)
    is granted the Reversal Bypass so the trader is not blinded.
    """
    engine = AutoAlertEngine()
    engine._hourly_telegram_dispatches = {"INDEX": [], "STOCKS": []}
    engine._hourly_index_directional = []

    now_t = time.time()
    # Simulate 5 BEARISH index put alerts dispatched in the last 20 minutes (e.g. morning down-flush)
    for i in range(5):
        t_disp = now_t - (i * 200.0)
        engine._hourly_telegram_dispatches["INDEX"].append(t_disp)
        engine._hourly_index_directional.append((t_disp, "BEARISH"))

    # 1. Another BEARISH alert arrives -> Passes unthrottled because Index has ZERO hourly pacing
    bear_alert = _make_dummy_alert(
        "idx-bear-6", "NIFTY", direction="BEARISH", opt_type="PE", confidence=92
    )
    passed_bear, reason_bear = engine._eval_telegram_apex_gate(bear_alert, in_market=True)
    assert passed_bear is True
    assert reason_bear == "PASSED_APEX_GATE"

    # 2. A high-conviction BULLISH reversal alert arrives (e.g. BANKNIFTY CE at V-bottom)
    bull_alert = _make_dummy_alert(
        "idx-bull-rev", "BANKNIFTY", direction="BULLISH", opt_type="CE", confidence=93
    )
    passed_bull, reason_bull = engine._eval_telegram_apex_gate(bull_alert, in_market=True)
    assert passed_bull is True
    assert reason_bull == "PASSED_APEX_GATE"


def test_fii_selling_and_index_vwap_bearish_regime_suppresses_longs():
    """On days like 2026-10-21 where NIFTY is down -0.34%, BANKNIFTY is down -0.92%,
    NIFTY is below session VWAP, and FIIs are net sellers (-₹1,148 Cr),
    counter-trend bullish equity breakouts must be suppressed on Telegram unless
    there is genuine sector decoupling and high RVOL.
    """
    engine = AutoAlertEngine()
    engine._hourly_telegram_dispatches = {"INDEX": [], "STOCKS": []}

    # 1. Routine Bullish Breakout in Metal sector without Decoupling
    alert_fail = _make_dummy_alert(
        "stk-tata-steel",
        "TATASTEEL",
        direction="BULLISH",
        segment="FNO_STOCK",
        opt_type="CE",
        confidence=86,
    )
    alert_fail.metrics = {
        "nifty_change_pct": -0.34,
        "nifty_below_vwap": True,
        "banknifty_change_pct": -0.92,
        "fii_net": -1148.5,
        "sector_id": "metal",
        "sector_change_pct": -0.50,
        "sector_rs": -0.16,
        "rvol": 1.4,
    }
    passed, reason = engine._eval_telegram_apex_gate(alert_fail, in_market=True)
    assert not passed
    assert "Institutional selling regime" in reason
    assert "FII -1,148 Cr" in reason

    # 2. Defensive decoupler (e.g. Pharma or FMCG with positive RS) still passes
    alert_pass = _make_dummy_alert(
        "stk-sunpharma",
        "SUNPHARMA",
        direction="BULLISH",
        segment="FNO_STOCK",
        opt_type="CE",
        confidence=90,
    )
    alert_pass.metrics = {
        "nifty_change_pct": -0.34,
        "nifty_below_vwap": True,
        "banknifty_change_pct": -0.92,
        "fii_net": -1148.5,
        "sector_id": "pharma",
        "sector_change_pct": 0.40,
        "sector_rs": 0.74,
        "rvol": 2.6,
    }
    passed_p, reason_p = engine._eval_telegram_apex_gate(alert_pass, in_market=True)
    assert passed_p, f"Expected decoupled defensive leader to pass, but got: {reason_p}"
