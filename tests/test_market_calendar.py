"""
tests/test_market_calendar.py
─────────────────────────────
Comprehensive unit & integration test suite for Indian Exchange Trading Calendar,
holiday detection, MCX session handling, active trading minutes calculation,
and asymmetry veto enforcement.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo
import pytest

from market.calendar import (
    is_trading_holiday,
    get_holiday_reason,
    is_market_open,
    get_market_status,
    get_current_ist_session,
    get_trading_minutes_elapsed,
    get_adjusted_expiry_date,
)

IST = ZoneInfo("Asia/Kolkata")


def test_trading_holiday_detection_2026():
    """Verify official NSE/BSE holidays in 2026 are recognized."""
    # Ganesh Chaturthi (Current user date)
    assert is_trading_holiday(date(2026, 9, 14), "NSE") is True
    assert get_holiday_reason(date(2026, 9, 14), "NSE") == "Ganesh Chaturthi"

    # Republic Day, Gandhi Jayanti, Christmas
    assert is_trading_holiday(date(2026, 1, 26), "NSE") is True
    assert is_trading_holiday(date(2026, 10, 2), "NSE") is True
    assert is_trading_holiday(date(2026, 12, 25), "NSE") is True

    # Normal weekday should NOT be a holiday
    assert is_trading_holiday(date(2026, 9, 15), "NSE") is False
    assert get_holiday_reason(date(2026, 9, 15), "NSE") is None


def test_mcx_split_session_on_holidays():
    """
    On holidays like Ganesh Chaturthi, MCX is closed for the morning session (09:00–17:00)
    but open for the evening session (17:00–23:30).
    On Good Friday, MCX is closed for both sessions.
    """
    ganesh_dt_morning = datetime(2026, 9, 14, 11, 30, tzinfo=IST)
    ganesh_dt_evening = datetime(2026, 9, 14, 18, 30, tzinfo=IST)

    assert is_market_open("MCX", ref_dt=ganesh_dt_morning) is False
    assert is_market_open("MCX", ref_dt=ganesh_dt_evening) is True

    # Good Friday (full-day closed on MCX)
    good_fri_morning = datetime(2026, 4, 3, 11, 30, tzinfo=IST)
    good_fri_evening = datetime(2026, 4, 3, 18, 30, tzinfo=IST)
    assert is_market_open("MCX", ref_dt=good_fri_morning) is False
    assert is_market_open("MCX", ref_dt=good_fri_evening) is False


def test_is_market_open_regular_sessions():
    """Verify regular market sessions during non-holiday periods."""
    # Tuesday 10:30 IST -> Open for NSE
    tue_market_hours = datetime(2026, 9, 15, 10, 30, tzinfo=IST)
    assert is_market_open("NSE", ref_dt=tue_market_hours) is True
    assert is_market_open("NFO", ref_dt=tue_market_hours) is True

    # Pre-market 08:30 IST -> Closed
    pre_market = datetime(2026, 9, 15, 8, 30, tzinfo=IST)
    assert is_market_open("NSE", ref_dt=pre_market) is False

    # Post-market 16:00 IST -> Closed
    post_market = datetime(2026, 9, 15, 16, 0, tzinfo=IST)
    assert is_market_open("NSE", ref_dt=post_market) is False

    # Weekend (Saturday) -> Closed
    sat = datetime(2026, 9, 19, 11, 0, tzinfo=IST)
    assert is_market_open("NSE", ref_dt=sat) is False
    assert is_market_open("MCX", ref_dt=sat) is False


def test_get_market_status_reporting():
    """Verify human-readable labels and status structures."""
    # Holiday
    holiday_dt = datetime(2026, 9, 14, 11, 0, tzinfo=IST)
    st_holiday = get_market_status("NSE", ref_dt=holiday_dt)
    assert st_holiday["is_open"] is False
    assert st_holiday["status"] == "HOLIDAY"
    assert "Ganesh Chaturthi" in st_holiday["label"]

    # Weekend
    sat_dt = datetime(2026, 9, 19, 11, 0, tzinfo=IST)
    st_weekend = get_market_status("NSE", ref_dt=sat_dt)
    assert st_weekend["is_open"] is False
    assert st_weekend["status"] == "WEEKEND"

    # Live market
    live_dt = datetime(2026, 9, 15, 11, 0, tzinfo=IST)
    st_live = get_market_status("NSE", ref_dt=live_dt)
    assert st_live["is_open"] is True
    assert st_live["status"] == "LIVE"
    assert st_live["remaining_session_mins"] == 270  # 11:00 to 15:30 = 4.5h = 270m


def test_get_current_ist_session():
    """Verify session flags respect holidays and operating windows."""
    # Monday 14-Sep-2026 (Ganesh Chaturthi morning) -> all False
    holiday_dt = datetime(2026, 9, 14, 11, 0, tzinfo=IST)
    sess_holiday = get_current_ist_session(ref_dt=holiday_dt)
    assert sess_holiday == {"equity_nfo": False, "currency": False, "commodity": False}

    # Monday 14-Sep-2026 (Ganesh Chaturthi evening) -> commodity True, equity False
    holiday_eve = datetime(2026, 9, 14, 18, 0, tzinfo=IST)
    sess_eve = get_current_ist_session(ref_dt=holiday_eve)
    assert sess_eve == {"equity_nfo": False, "currency": False, "commodity": True}

    # Regular Tuesday 11:00 IST -> equity True, currency False, commodity False
    tue_day = datetime(2026, 9, 15, 11, 0, tzinfo=IST)
    sess_tue = get_current_ist_session(ref_dt=tue_day)
    assert sess_tue["equity_nfo"] is True


def test_get_trading_minutes_elapsed():
    """
    Computes active trading minutes only, skipping nights, weekends, and holidays.
    From Friday 15:00 to Monday 14:00 (when Monday is Ganesh Chaturthi):
      - Friday 15:00 to 15:30 = 30 minutes trading.
      - Friday 15:30 to Monday 14:00 = Closed (night + weekend + holiday).
      Total active trading minutes MUST be exactly 30.0!
    """
    fri_start = datetime(2026, 9, 11, 15, 0, tzinfo=IST)
    mon_end = datetime(2026, 9, 14, 14, 0, tzinfo=IST)

    elapsed = get_trading_minutes_elapsed(fri_start, mon_end, "NSE")
    assert elapsed == pytest.approx(30.0, abs=1.0)


def test_get_adjusted_expiry_date():
    """If target expiry falls on holiday or weekend, roll backward to preceding trading day."""
    # 2026-10-02 is Friday (Gandhi Jayanti)
    # Expiry scheduled for Friday should roll back to Thursday 2026-10-01
    adjusted = get_adjusted_expiry_date(date(2026, 10, 2), "NFO")
    assert adjusted == date(2026, 10, 1)

    # 2026-09-14 is Monday (Ganesh Chaturthi)
    # Expiry scheduled for Monday should roll back to Friday 2026-09-11 (skipping weekend Sat/Sun)
    adjusted_mon = get_adjusted_expiry_date(date(2026, 9, 14), "NFO")
    assert adjusted_mon == date(2026, 9, 11)


def test_in_flight_warning_skips_when_market_closed(monkeypatch):
    """Verify that evaluate_alert_in_flight_decay returns None when market is closed."""
    from engine.alert_evaluator import evaluate_alert_in_flight_decay
    from engine.alert_model import AutoAlert

    alert = AutoAlert(
        alert_id="test-live-alert",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Test Alert",
        summary="Test Summary",
        ltp=100.0,
        trigger_level=100.0,
        target_level=150.0,
        stop_loss=80.0,
        strike=23500.0,
        option_type="CE",
        contract_symbol="NIFTY23500CE",
        is_live=True,
        environment="LIVE",
    )

    # Ensure environment is not marked as test runner
    monkeypatch.delenv("CHANAKYA_TESTING", raising=False)
    monkeypatch.delenv("DEPLOY_MODE", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    # Mock market as closed
    monkeypatch.setattr("market.calendar.is_market_open", lambda exch: False)

    res = evaluate_alert_in_flight_decay(alert, current_ltp=100.0)
    assert res is None


def test_gamma_blast_strictly_rejects_unviable_asymmetry():
    """
    Verify detect_gamma_blast asymmetry gate behavior after SMC structural bypass (Fix 2).

    New behaviour:
    - Index PE with extreme OI unwind (vol_oi >= 2.0) bypasses is_asymmetry_viable=False
      because extreme institutional shedding IS the structural bearish signal (stronger
      than the EMA-calibrated trade plan viability model).
    - Equity stock PEs are still rejected: the bypass is index-only.
    - Index PE with LOW vol_oi (< 2.0 threshold) is still rejected normally.
    """
    from engine.detectors.gamma_blast import detect_gamma_blast
    from brokers.base import OptionsContract
    from unittest.mock import MagicMock

    mock_tp = MagicMock()
    mock_tp.is_asymmetry_viable = False
    mock_tp.asymmetry_verdict = "POOR_ASYMMETRY_REJECTED"

    # Case A: NIFTY PE with extreme vol/OI (10x >= 2.0) — SMC bypass fires, alert EXPECTED
    chain_extreme = [
        OptionsContract(
            symbol="NIFTY23500PE",
            underlying="NIFTY",
            expiry="2026-09-25",
            strike=23500.0,
            option_type="PE",
            last_price=100.0,
            oi=50000,
            oi_change=-25000,
            volume=500000,
            exchange="NFO",
        )
    ]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("engine.trade_plan.calculate_trade_plan", lambda **kwargs: mock_tp)
        alerts = detect_gamma_blast("NIFTY", spot=23480.0, chain=chain_extreme, vwap=23490.0)
        assert len(alerts) == 1, (
            "NIFTY PE with 10x vol_oi extreme unwind must bypass asymmetry gate — "
            "institutional OI shedding is the structural signal"
        )

    # Case B: Equity stock (RELIANCE) — bypass is index-only, must still be rejected
    chain_equity = [
        OptionsContract(
            symbol="RELIANCE2900PE",
            underlying="RELIANCE",
            expiry="2026-09-25",
            strike=2900.0,
            option_type="PE",
            last_price=50.0,
            oi=20000,
            oi_change=-10000,
            volume=200000,
            exchange="NFO",
        )
    ]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("engine.trade_plan.calculate_trade_plan", lambda **kwargs: mock_tp)
        alerts = detect_gamma_blast("RELIANCE", spot=2870.0, chain=chain_equity, vwap=2880.0)
        assert len(alerts) == 0, "Equity PE must still be rejected — SMC bypass is index-only"

    # Case C: NIFTY PE with LOW vol/OI (1.2x < bypass threshold) — still rejected
    chain_low = [
        OptionsContract(
            symbol="NIFTY23500PE",
            underlying="NIFTY",
            expiry="2026-09-25",
            strike=23500.0,
            option_type="PE",
            last_price=100.0,
            oi=50000,
            oi_change=-5000,
            volume=60000,
            exchange="NFO",
        )
    ]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("engine.trade_plan.calculate_trade_plan", lambda **kwargs: mock_tp)
        alerts = detect_gamma_blast("NIFTY", spot=23480.0, chain=chain_low, vwap=23490.0)
        assert len(alerts) == 0, (
            "NIFTY PE with 1.2x vol_oi (< 2.0 bypass threshold) must still be rejected "
            "when is_asymmetry_viable=False"
        )


def test_scrutiny_auditor_vetoes_unviable_trade_plan():
    """Verify that verify_tier1_sanity vetoes alerts when attached trade plan is unviable."""
    from engine.alert_scrutiny import alert_scrutiny_auditor
    from engine.alert_model import AutoAlert

    alert = AutoAlert(
        alert_id="test-veto",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BEARISH",
        headline="Test Veto Alert",
        summary="Test Summary",
        ltp=112.0,
        trigger_level=112.0,
        target_level=200.0,
        stop_loss=78.0,
        strike=23500.0,
        option_type="PE",
        actionable_plan={
            "action": "BUY",
            "trade_plan": {
                "is_asymmetry_viable": False,
                "asymmetry_verdict": "POOR_ASYMMETRY_REJECTED",
                "asymmetry_note": "Structural R:R below threshold.",
            },
        },
    )

    passed, reason, flags = alert_scrutiny_auditor.verify_tier1_sanity(alert)
    assert passed is False
    assert "Sanity Veto" in reason
    assert "poor asymmetry" in reason
    assert flags["rr_valid"] is False
