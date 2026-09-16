"""
tests/test_nse_nfo_conviction_and_safeguards.py
────────────────────────────────────────────────
Unit test suite verifying institutional conviction safeguards and false-signal trap
suppression across Indian Equities (NSE/BSE) and Derivatives (NFO/BFO).
"""

from __future__ import annotations

from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from typing import Any
import pandas as pd
import numpy as np
import pytest

from engine.alert_model import AutoAlert
from engine.alert_scrutiny import AlertScrutinyAuditor, INDEX_MIN_SL_FLOORS
from engine.alert_expiry import (
    is_0dte_expiry,
    is_0dte_afternoon,
    is_monthly_physical_expiry_week,
    get_last_thursday_of_month,
    get_next_monthly_expiry_date,
    resolve_recommended_derivative_expiry,
)

IST = ZoneInfo("Asia/Kolkata")


# ── 1. Index Minimum Stop-Loss Volatility Floor Tests ─────────────


def test_index_min_sl_floor_nifty_rejection():
    """NIFTY spot/futures setups with sub-noise stops (< 25 pts) must be rejected."""
    auditor = AlertScrutinyAuditor(min_rr_ratio=1.3)
    # Stop distance of only 15 points on Nifty (e.g. 24500 to 24485)
    alert = AutoAlert(
        alert_id="test-nifty-subnoise",
        alert_type="INDEX_BREAKOUT",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Nifty breakout",
        summary="Nifty testing high",
        ltp=24500.0,
        trigger_level=24500.0,
        target_level=24560.0,  # 60 pt target (4:1 R:R mathematically)
        stop_loss=24485.0,     # 15 pt stop -> SUB_NOISE
        confidence=85,
        created_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert not passed, "Sub-noise 15pt Nifty stop-loss must be rejected"
    assert "Sub-Noise Trap" in reason
    assert "25.0 pts" in reason


def test_index_min_sl_floor_nifty_acceptance():
    """NIFTY setup with valid structural stop (>= 25 pts) must pass sanity."""
    auditor = AlertScrutinyAuditor(min_rr_ratio=1.3)
    # 30 points stop distance (24500 to 24470), target 24560 (60 pts, 2:1 R:R)
    alert = AutoAlert(
        alert_id="test-nifty-valid",
        alert_type="INDEX_BREAKOUT",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Nifty breakout",
        summary="Nifty testing high",
        ltp=24500.0,
        trigger_level=24500.0,
        target_level=24560.0,
        stop_loss=24470.0,     # 30 pt stop >= 25 floor
        confidence=85,
        created_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed, f"Valid 30pt Nifty stop must be accepted; failed with: {reason}"
    assert flags.get("risk_within_bounds") is True


def test_index_min_sl_floor_banknifty_rejection():
    """BANKNIFTY setup with stop < 65 pts must be rejected as noise trap."""
    auditor = AlertScrutinyAuditor(min_rr_ratio=1.3)
    alert = AutoAlert(
        alert_id="test-bn-subnoise",
        alert_type="INDEX_BREAKOUT",
        stage="IGNITED",
        symbol="BANKNIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="BankNifty breakout",
        summary="BankNifty surge",
        ltp=52000.0,
        trigger_level=52000.0,
        target_level=52200.0,
        stop_loss=51960.0,     # 40 pt stop < 65 floor
        confidence=85,
        created_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert not passed, "Sub-noise 40pt BankNifty stop must be rejected"
    assert "65.0 pts" in reason


def test_equity_sub_atr_stop_rejection():
    """Cash equity setup with stop tighter than 0.70x ATR must be rejected."""
    auditor = AlertScrutinyAuditor(min_rr_ratio=1.3)
    # Stock at 1000.0, daily ATR is 25.0 (2.5%). Stop is at 990.0 (10 pt risk < 0.70 * 25 = 17.5 pt floor)
    alert = AutoAlert(
        alert_id="test-eq-sub-atr",
        alert_type="INTRADAY_SPARK",
        stage="IGNITED",
        symbol="TATASTEEL",
        exchange="NSE",
        direction="BULLISH",
        headline="Tata Steel Spark",
        summary="Momentum breakout",
        ltp=1000.0,
        trigger_level=1000.0,
        target_level=1040.0,
        stop_loss=990.0,     # 10 pt risk
        confidence=85,
        created_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        is_live=True,
        environment="LIVE",
        metrics={"atr": 25.0},
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert not passed, "Sub-0.70x ATR stop must be rejected"
    assert "Sub-ATR Equity Noise Trap" in reason


# ── 2. 0DTE Expiry & Physical Delivery Settlement Tests ───────────


def test_0dte_expiry_and_afternoon_detection():
    """Verifies accurate identification of 0DTE and afternoon theta decay phase."""
    today = datetime.now(IST)
    today_str = today.strftime("%Y-%m-%d")

    assert is_0dte_expiry(today_str, ref_dt=today) is True
    assert is_0dte_expiry("2030-01-01", ref_dt=today) is False

    # Simulate morning (10:15 IST) vs afternoon (13:30 IST)
    morning_dt = datetime(today.year, today.month, today.day, 10, 15, tzinfo=IST)
    afternoon_dt = datetime(today.year, today.month, today.day, 13, 30, tzinfo=IST)

    assert is_0dte_afternoon(today_str, ref_dt=morning_dt) is False
    assert is_0dte_afternoon(today_str, ref_dt=afternoon_dt) is True


def test_monthly_physical_expiry_week_detection():
    """Detects when single-stock options enter final 4 days of physical settlement week."""
    ref_dt = datetime(2026, 9, 21, 10, 0, tzinfo=IST)  # Monday
    expiry_thu = "2026-09-24"  # Thursday of same week (3 DTE)

    # For single stock (e.g. RELIANCE), physical settlement applies
    assert is_monthly_physical_expiry_week(expiry_thu, symbol="RELIANCE", ref_dt=ref_dt) is True

    # For indices (NIFTY), cash settlement applies (never physical delivery)
    assert is_monthly_physical_expiry_week(expiry_thu, symbol="NIFTY", ref_dt=ref_dt) is False


# ── 3. Options Momentum Breakouts Confluence & Filter Tests ───────


def test_options_momentum_0dte_afternoon_otm_rejection(monkeypatch):
    """In scan_options_momentum_breakouts, OTM contracts on 0DTE afternoon must be rejected."""
    from engine.auto_alert_engine import AutoAlertEngine
    from brokers.base import OptionsContract, Quote

    eng = AutoAlertEngine()

    now_afternoon = datetime(2026, 9, 24, 13, 45, tzinfo=IST)
    today_str = "2026-09-24"

    # NIFTY spot at 24000.0
    spot = 24000.0
    q_nifty = Quote(symbol="NIFTY", last_price=spot, vwap=23980.0, open=23950.0, change=50.0, change_pct=0.25)
    monkeypatch.setattr("market.quotes.get_ltp", lambda sym: spot)
    monkeypatch.setattr("market.quotes.get_quote", lambda sym: {"NSE:NIFTY": q_nifty, "NIFTY": q_nifty, "NSE:NIFTY 50": q_nifty})

    # Chain contains:
    # 1. 24100 CE (OTM by 100 pts on 0DTE afternoon -> must be rejected)
    # 2. 23950 CE (ITM by 50 pts -> eligible)
    otm_ce = OptionsContract(
        symbol="NIFTY2692424100CE",
        underlying="NIFTY",
        expiry=today_str,
        strike=24100.0,
        option_type="CE",
        last_price=25.0,
        oi=10000,
        oi_change=500,
        volume=15000,
        pchange=15.0,
        bid=24.5,
        ask=25.5,
    )
    itm_ce = OptionsContract(
        symbol="NIFTY2692423950CE",
        underlying="NIFTY",
        expiry=today_str,
        strike=23950.0,
        option_type="CE",
        last_price=95.0,
        oi=12000,
        oi_change=800,
        volume=20000,
        pchange=18.0,
        bid=94.5,
        ask=95.5,
    )

    monkeypatch.setattr("market.options.get_options_chain", lambda sym: [otm_ce, itm_ce])
    # Mock datetime.now(IST) to 13:45 IST
    monkeypatch.setattr("engine.auto_alert_engine.datetime", type("MockDT", (), {
        "now": classmethod(lambda cls, tz=None: now_afternoon),
        "strptime": datetime.strptime,
    }))

    # Set watched indices to NIFTY only
    eng._watched_indices = ["NIFTY"]
    eng.watched_equities = []

    alerts = eng.scan_options_momentum_breakouts()
    # If any alert generated, it must be the ITM contract (23950), NOT the OTM contract (24100)
    for a in alerts:
        assert a.strike != 24100.0, "OTM Call (24100 CE) must be rejected on 0DTE afternoon"
        if a.strike == 23950.0:
            assert "0DTE AFTERNOON" in a.summary or "0DTE" in str(a.actionable_plan)


def test_single_stock_option_wide_spread_rejection(monkeypatch):
    """Single stock option with bid-ask spread > 15% must be rejected."""
    from engine.auto_alert_engine import AutoAlertEngine
    from brokers.base import OptionsContract, Quote

    eng = AutoAlertEngine()
    spot = 1500.0
    q_infy = Quote(symbol="INFY", last_price=spot, vwap=1495.0, open=1490.0, change=10.0, change_pct=0.67)
    monkeypatch.setattr("market.quotes.get_ltp", lambda sym: spot)
    monkeypatch.setattr("market.quotes.get_quote", lambda sym: {"NSE:INFY": q_infy, "INFY": q_infy})

    # Illiquid strike with wide spread: Bid 20.0, Ask 25.0 (25% gap > 15% limit)
    illiquid_c = OptionsContract(
        symbol="INFY26SEP1500CE",
        underlying="INFY",
        expiry="2026-09-24",
        strike=1500.0,
        option_type="CE",
        last_price=22.0,
        oi=1500,
        oi_change=100,
        volume=3000,
        pchange=8.0,
        bid=20.0,
        ask=25.0,  # 25.0 > 20.0 * 1.15
    )

    monkeypatch.setattr("market.options.get_options_chain", lambda sym: [illiquid_c])
    eng._watched_indices = []
    eng.watched_equities = ["INFY"]

    alerts = eng.scan_options_momentum_breakouts()
    assert len(alerts) == 0, "Single-stock option with 25% spread must be rejected"


# ── 4. Sector RRG Tailwind & Circuit Limit Tests ──────────────────


def test_intraday_spark_sector_rrg_tailwind_integration(monkeypatch):
    """Intraday spark in a LEADING sector gets conviction bonus, while LAGGING sector is suppressed."""
    from engine.auto_alert_engine import AutoAlertEngine
    from brokers.base import Quote
    from dataclasses import dataclass

    eng = AutoAlertEngine()
    eng._alerts = []
    eng._cooldowns = {}
    monkeypatch.setattr(eng, "_save", lambda: None)

    q_stock = Quote(symbol="BEL", last_price=300.0, vwap=296.0, open=294.0, change=6.0, change_pct=2.04, volume=200000)
    q_nifty = Quote(symbol="NIFTY", last_price=24000.0, vwap=24000.0, open=24000.0, change=0.0, change_pct=0.0)

    # 30-day synthetic daily dataframe for get_ohlcv
    dates = pd.date_range(end=pd.Timestamp.now(), periods=30, freq="D")
    df_daily = pd.DataFrame({
        "open": [290.0] * 30,
        "high": [305.0] * 30,
        "low": [288.0] * 30,
        "close": [295.0] * 30,
        "volume": [100000] * 30,
    }, index=dates)

    monkeypatch.setattr("market.history.get_ohlcv", lambda *a, **kw: df_daily)
    monkeypatch.setattr("market.quotes.get_quote", lambda syms: {
        "NSE:BEL": q_stock,
        "BEL": q_stock,
        "NSE:NIFTY 50": q_nifty,
    })
    monkeypatch.setattr("engine.precursor_radar.precursor_radar.get_scan_universe", lambda segment="ALL": ["BEL"])
    monkeypatch.setattr("analysis.market_structure.check_mtf_structural_alignment", lambda *a, **kw: {"alignment_count": 2, "wall_collision": False})
    monkeypatch.setattr("analysis.market_structure.detect_confirmation_candle", lambda *a, **kw: ("HAMMER", True))
    monkeypatch.setattr("analysis.market_structure.detect_divergence", lambda *a, **kw: (None, None))
    eng.watched_equities = ["BEL"]

    @dataclass
    class DummyTailwind:
        quadrant: str
        sector: str

    # Case 1: Stock is in a LAGGING sector with moderate RVOL (1.8x < 2.5x) -> must be suppressed
    monkeypatch.setattr("engine.auto_alert_engine.compute_time_of_day_rvol", lambda *a, **kw: 1.8)
    monkeypatch.setattr("analysis.sector_rotation.get_stock_tailwind", lambda sym: DummyTailwind(quadrant="LAGGING", sector="NIFTY DEFENCE"))

    alerts_lagging = eng.scan_intraday_mover_sparks()
    assert len(alerts_lagging) == 0, "Bullish spark in LAGGING sector without RVOL >= 2.5x must be suppressed"

    # Case 2: Stock is in a LEADING sector -> must pass and receive conviction bonus
    monkeypatch.setattr("engine.auto_alert_engine.compute_time_of_day_rvol", lambda *a, **kw: 2.0)
    monkeypatch.setattr("analysis.sector_rotation.get_stock_tailwind", lambda sym: DummyTailwind(quadrant="LEADING", sector="NIFTY DEFENCE"))

    alerts_leading = eng.scan_intraday_mover_sparks()
    assert len(alerts_leading) == 1, "Bullish spark in LEADING sector must be accepted"
    bel_alert = alerts_leading[0]
    assert bel_alert.metrics.get("sector_tailwind_bonus") == 8
    assert bel_alert.confidence >= 80


def test_intraday_spark_upper_circuit_proximity_rejection(monkeypatch):
    """Stock within 0.8% of Upper Circuit must be suppressed to avoid circuit freeze traps."""
    from engine.auto_alert_engine import AutoAlertEngine
    from brokers.base import Quote

    eng = AutoAlertEngine()

    dates = pd.date_range(end=pd.Timestamp.now(), periods=30, freq="D")
    df_daily = pd.DataFrame({
        "open": [100.0] * 30,
        "high": [105.0] * 30,
        "low": [98.0] * 30,
        "close": [102.0] * 30,
        "volume": [100000] * 30,
    }, index=dates)

    monkeypatch.setattr("market.history.get_ohlcv", lambda *a, **kw: df_daily)
    monkeypatch.setattr("engine.auto_alert_engine.compute_time_of_day_rvol", lambda *a, **kw: 2.5)

    # Stock at 104.5, Upper Circuit is 105.0 (0.47% away, < 0.8% threshold)
    q_stock = Quote(
        symbol="IDEA",
        last_price=104.5,
        vwap=102.0,
        open=100.0,
        change=4.5,
        change_pct=4.5,
        volume=5000000,
        upper_circuit=105.0,
    )
    q_nifty = Quote(symbol="NIFTY", last_price=24000.0, vwap=24000.0, open=24000.0, change=0.0, change_pct=0.0)

    monkeypatch.setattr("market.quotes.get_quote", lambda syms: {
        "NSE:IDEA": q_stock,
        "IDEA": q_stock,
        "NSE:NIFTY 50": q_nifty,
    })
    monkeypatch.setattr("engine.precursor_radar.precursor_radar.get_scan_universe", lambda segment="ALL": ["IDEA"])
    eng.watched_equities = ["IDEA"]

    alerts = eng.scan_intraday_mover_sparks()
    assert len(alerts) == 0, "Stock within 0.8% of Upper Circuit must be suppressed"


# ── 5. Next-Month Rollover & Settlement Week Derivatives Tests ────


def test_last_thursday_and_next_monthly_expiry_calculation():
    """Validates calculation of last Thursday of month and next monthly rollover date."""
    from datetime import date

    # September 2026: 30 days. Sep 24 is Thursday, Sep 30 is Wednesday -> Last Thu is Sep 24
    assert get_last_thursday_of_month(2026, 9) == date(2026, 9, 24)
    # October 2026: 31 days. Oct 29 is Thursday -> Last Thu is Oct 29
    assert get_last_thursday_of_month(2026, 10) == date(2026, 10, 29)
    # December 2026 / January 2027 year crossover
    assert get_last_thursday_of_month(2026, 12) == date(2026, 12, 31)
    assert get_last_thursday_of_month(2027, 1) == date(2027, 1, 28)

    # Next monthly expiry from Sep 21, 2026 (expiry week) should be Oct 29, 2026
    ref_sep = datetime(2026, 9, 21, 10, 0, tzinfo=IST)
    assert get_next_monthly_expiry_date(ref_sep) == date(2026, 10, 29)


def test_resolve_recommended_derivative_expiry_stock_options():
    """Verifies single-stock options route to next month during settlement week, while indices stay on weekly."""
    # Case 1: RELIANCE during expiry week (3 DTE) -> Auto-route to Next-Month
    ref_expiry_week = datetime(2026, 9, 21, 10, 0, tzinfo=IST)
    res_stock = resolve_recommended_derivative_expiry(
        "RELIANCE",
        instrument_type="OPTION",
        current_expiry="2026-09-24",
        available_expiries=["2026-09-24", "2026-10-29", "2026-11-26"],
        ref_dt=ref_expiry_week,
    )
    assert res_stock["is_next_month_routed"] is True
    assert res_stock["recommended_expiry"] == "2026-10-29"
    assert res_stock["series"] == "NEXT_MONTH"
    assert res_stock["margin_risk"] == "PROTECTED"
    assert "NEXT-MONTH ROLLOVER" in res_stock["badge"]

    # Case 2: RELIANCE early in the month (20 DTE) -> Normal current month
    ref_early = datetime(2026, 9, 4, 10, 0, tzinfo=IST)
    res_stock_early = resolve_recommended_derivative_expiry(
        "RELIANCE",
        instrument_type="OPTION",
        current_expiry="2026-09-24",
        ref_dt=ref_early,
    )
    assert res_stock_early["is_next_month_routed"] is False
    assert res_stock_early["recommended_expiry"] == "2026-09-24"
    assert res_stock_early["series"] == "CURRENT_MONTH"

    # Case 3: NIFTY Index during expiry week -> Cash settled, stays on current weekly/monthly
    res_index = resolve_recommended_derivative_expiry(
        "NIFTY",
        instrument_type="OPTION",
        current_expiry="2026-09-24",
        ref_dt=ref_expiry_week,
    )
    assert res_index["is_next_month_routed"] is False
    assert res_index["recommended_expiry"] == "2026-09-24"
    assert res_index["series"] == "CURRENT_SERIES"


def test_resolve_recommended_derivative_expiry_stock_futures():
    """Verifies single-stock futures route to next-month contract during settlement week."""
    ref_expiry_week = datetime(2026, 9, 22, 11, 30, tzinfo=IST)  # Tuesday of expiry week (2 DTE)
    res_fut = resolve_recommended_derivative_expiry(
        "TATASTEEL",
        instrument_type="FUTURE",
        current_expiry="2026-09-24",
        available_expiries=["2026-09-24", "2026-10-29"],
        ref_dt=ref_expiry_week,
    )
    assert res_fut["is_next_month_routed"] is True
    assert res_fut["recommended_expiry"] == "2026-10-29"
    assert res_fut["series"] == "NEXT_MONTH"
    assert "staggered delivery margin risk" in res_fut["reason"]


def test_options_scanner_auto_routes_stock_options_to_next_month_in_expiry_week(monkeypatch):
    """Verifies that scan_options_momentum_breakouts loads next-month option chain for single stocks in expiry week."""
    from engine.auto_alert_engine import AutoAlertEngine
    from brokers.base import OptionsContract, Quote

    eng = AutoAlertEngine()
    eng._alerts = []
    eng._cooldowns = {}
    monkeypatch.setattr(eng, "_save", lambda: None)

    spot = 3000.0
    q_rel = Quote(symbol="RELIANCE", last_price=spot, vwap=2990.0, open=2980.0, change=20.0, change_pct=0.67)
    q_nifty = Quote(symbol="NIFTY", last_price=24000.0, vwap=24000.0, open=24000.0, change=0.0, change_pct=0.0)

    # Monday of expiry week: 2026-09-21
    now_exp_week = datetime(2026, 9, 21, 10, 15, tzinfo=IST)
    monkeypatch.setattr("engine.auto_alert_engine.datetime", type("MockDT", (), {
        "now": classmethod(lambda cls, tz=None: now_exp_week),
        "strptime": datetime.strptime,
    }))

    monkeypatch.setattr("market.quotes.get_ltp", lambda sym: spot)
    monkeypatch.setattr("market.quotes.get_quote", lambda sym: {
        "NSE:RELIANCE": q_rel,
        "RELIANCE": q_rel,
        "NSE:NIFTY 50": q_nifty,
    })

    dates = pd.date_range(end=pd.Timestamp.now(), periods=30, freq="D")
    df_synthetic = pd.DataFrame({
        "open": [2990.0] * 30,
        "high": [3020.0] * 30,
        "low": [2980.0] * 30,
        "close": [3000.0] * 30,
        "volume": [500000] * 30,
    }, index=dates)
    monkeypatch.setattr("market.history.get_ohlcv", lambda *a, **kw: df_synthetic)

    # Near-month contract (Sep 24): dying series in settlement week
    c_near = OptionsContract(
        symbol="RELIANCE26SEP3000CE",
        underlying="RELIANCE",
        expiry="2026-09-24",
        strike=3000.0,
        option_type="CE",
        last_price=25.0,
        oi=50000,
        oi_change=2000,
        volume=80000,
        pchange=12.0,
        bid=24.5,
        ask=25.5,
    )
    # Next-month contract (Oct 29): institutional rollover series
    c_next = OptionsContract(
        symbol="RELIANCE26OCT3000CE",
        underlying="RELIANCE",
        expiry="2026-10-29",
        strike=3000.0,
        option_type="CE",
        last_price=65.0,
        oi=50000,
        oi_change=3000,
        volume=80000,
        pchange=15.0,
        bid=64.5,
        ask=65.5,
    )

    def mock_get_options_chain(sym, expiry=None):
        if expiry == "2026-10-29":
            return [c_next]
        return [c_near]

    monkeypatch.setattr("market.options.get_options_chain", mock_get_options_chain)
    monkeypatch.setattr("market.options.get_expiries", lambda sym: ["2026-09-24", "2026-10-29"])

    from dataclasses import dataclass

    @dataclass
    class DummyTailwind:
        quadrant: str = "LEADING"
        sector: str = "ENERGY"

    monkeypatch.setattr("analysis.sector_rotation.get_stock_tailwind", lambda sym: DummyTailwind())

    eng._watched_indices = []
    eng.watched_equities = ["RELIANCE"]

    alerts = eng.scan_options_momentum_breakouts()
    assert len(alerts) == 1, "Should generate exactly 1 options momentum alert"
    a = alerts[0]
    # Verify it automatically selected next-month expiry
    assert a.expiry_date == "2026-10-29", "Must route to next-month expiry date"
    assert a.contract_symbol == "RELIANCE26OCT3000CE", "Must select next-month contract symbol"
    assert a.metrics.get("rollover_series") == "NEXT_MONTH"
    assert a.metrics.get("is_rollover_recommended") is True
    assert a.metrics.get("rollover_protected") is True
    assert "NEXT-MONTH ROLLOVER" in a.summary


def test_trade_plan_advises_next_month_derivatives_in_expiry_week():
    """Verifies that TradePlan structure advice explicitly recommends next-month derivatives during settlement week."""
    from engine.trade_plan import calculate_trade_plan

    # Mock datetime during September 2026 expiry week (e.g. 2026-09-22)
    ref_dt = datetime(2026, 9, 22, 11, 0, tzinfo=IST)

    tp = calculate_trade_plan(
        symbol="INFY",
        direction="BUY",
        spot=1500.0,
        timeframe="INTRADAY",
        ref_dt=ref_dt,
    )
    assert "SEBI PHYSICAL SETTLEMENT EXPIRY WEEK" in tp.structure_advice
    assert "NEXT-MONTH" in tp.structure_advice
    assert "staggered margin" in tp.structure_advice.lower()

