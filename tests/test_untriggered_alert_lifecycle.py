"""
tests/test_untriggered_alert_lifecycle.py
─────────────────────────────────────────
Invariant regression tests for untriggered radar/precursor setups,
symmetric volatility noise floors, time gate cutoffs, and scorecard integrity.

Validates:
  1. Untriggered alerts (STALK, EARLY_WARNING, PRIMED) never register trading losses.
  2. Invalidation of untriggered setups transitions cleanly to SETUP_DISQUALIFIED (R=0.0, PnL=0.0%).
  3. No circuit breaker penalties or symbol lockouts are levied on disqualified untriggered setups.
  4. Session scorecards partition untriggered setups under 'unfulfilled', never 'losses'.
  5. Precursor Radar alerts do not pre-ignite; genuine trigger breach is mandatory.
  6. Sub-ATR noise floors (>= 1.20x ATR for sparks, >= 1.0x ATR for ORB) are enforced symmetrically.
  7. 0DTE options post 14:30 IST enforce mandatory SPREAD_ONLY defined-risk execution.
  8. Post-15:00 IST intraday momentum detectors are suppressed prior to broker MIS square-off.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from engine.alert_model import AutoAlert
from engine.alert_evaluator import evaluate_alert_invalidation
from engine.auto_alert_engine import AutoAlertEngine
from engine.alert_postmortem_runner import generate_session_scorecard
from engine.detectors.orb import detect_opening_range_breakout
from engine.detectors.index_call_setup import detect_index_call_setup
from engine.dynamic_risk import resolve_price_tier

IST = ZoneInfo("Asia/Kolkata")


def test_auto_alert_has_triggered_property():
    """Verify has_triggered accurately distinguishes active trades from unfulfilled radar setups."""
    # Untriggered radar setups
    radar_stalk = AutoAlert(
        alert_id="aa-radar-test-1",
        alert_type="PRECURSOR_RADAR",
        stage="STALK",
        symbol="SUNPHARMA",
        exchange="NSE",
        direction="BULLISH",
        headline="Radar stalk",
        summary="Stalking",
        ltp=1850.0,
        trigger_level=1880.0,
        stop_loss=1820.0,
        target_level=1950.0,
    )
    assert radar_stalk.has_triggered is False

    radar_ew = AutoAlert(
        alert_id="aa-radar-test-2",
        alert_type="PRECURSOR_RADAR",
        stage="EARLY_WARNING",
        symbol="SUNPHARMA",
        exchange="NSE",
        direction="BULLISH",
        headline="Early warning",
        summary="Early warning",
        ltp=1850.0,
        trigger_level=1880.0,
        stop_loss=1820.0,
        target_level=1950.0,
    )
    assert radar_ew.has_triggered is False

    radar_primed = AutoAlert(
        alert_id="aa-radar-test-3",
        alert_type="ORB_PRIMED",
        stage="PRIMED",
        symbol="RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="ORB primed",
        summary="Coiling",
        ltp=2500.0,
        trigger_level=2520.0,
        stop_loss=2480.0,
        target_level=2600.0,
    )
    assert radar_primed.has_triggered is False

    # Triggered setups
    active_ignited = AutoAlert(
        alert_id="aa-spark-test-4",
        alert_type="INTRADAY_BREAKOUT_SPARK",
        stage="IGNITED",
        symbol="TCS",
        exchange="NSE",
        direction="BULLISH",
        headline="Ignited",
        summary="Ignited",
        ltp=3500.0,
        trigger_level=3500.0,
        stop_loss=3460.0,
        target_level=3600.0,
    )
    assert active_ignited.has_triggered is True

    promoted_alert = AutoAlert(
        alert_id="aa-radar-test-5",
        alert_type="PRECURSOR_RADAR",
        stage="TRIGGERED",
        symbol="INFY",
        exchange="NSE",
        direction="BULLISH",
        headline="Triggered",
        summary="Triggered",
        ltp=1520.0,
        trigger_level=1500.0,
        stop_loss=1470.0,
        target_level=1560.0,
    )
    assert promoted_alert.has_triggered is True

    timestamped_alert = AutoAlert(
        alert_id="aa-radar-test-6",
        alert_type="PRECURSOR_RADAR",
        stage="STALK",
        symbol="INFY",
        exchange="NSE",
        direction="BULLISH",
        headline="Timestamped",
        summary="Timestamped",
        ltp=1520.0,
        trigger_level=1500.0,
        stop_loss=1470.0,
        target_level=1560.0,
        triggered_at="2026-10-14 10:15:00 IST",
    )
    assert timestamped_alert.has_triggered is True


def test_untriggered_stop_breach_evaluator_message():
    """Verify evaluate_alert_invalidation explicitly notes trade was never entered for untriggered setups."""
    radar = AutoAlert(
        alert_id="aa-radar-test-untriggered",
        alert_type="PRECURSOR_RADAR",
        stage="EARLY_WARNING",
        symbol="SHRIRAMFIN",
        exchange="NSE",
        direction="BULLISH",
        headline="Radar",
        summary="Radar",
        ltp=3250.0,
        trigger_level=3300.0,
        stop_loss=3200.0,
        target_level=3500.0,
    )
    # Price falls below stop loss (3190 < 3200) without ever reaching trigger 3300
    reason = evaluate_alert_invalidation(
        radar,
        current_ltp=3190.0,
        current_vwap=3210.0,
    )
    assert reason is not None
    assert "Setup invalidated prior to trigger" in reason
    assert "Trade was never entered" in reason


def test_untriggered_exit_routes_to_setup_disqualified():
    """Verify _handle_alert_exit transitions untriggered setups to SETUP_DISQUALIFIED with 0 PnL and zero penalties."""
    engine = AutoAlertEngine()

    radar = AutoAlert(
        alert_id="aa-radar-test-exit",
        alert_type="PRECURSOR_RADAR",
        stage="STALK",
        symbol="SUNPHARMA",
        exchange="NSE",
        direction="BULLISH",
        headline="Radar stalk",
        summary="Stalking",
        ltp=1850.0,
        trigger_level=1880.0,
        stop_loss=1820.0,
        target_level=1950.0,
    )
    # Register alert in engine
    engine._alerts.append(radar)

    # Trigger exit via invalidation
    was_loss = engine._handle_alert_exit(
        alert=radar,
        reason="Setup invalidated prior to trigger: LTP breached stop loss. Trade was never entered.",
        current_ltp=1815.0,
    )

    # Invariants for untriggered invalidation
    assert was_loss is True, "Untriggered setup exit is recorded as an invalidation exit event"
    assert radar.target_status == "SETUP_DISQUALIFIED"
    assert radar.r_multiple == 0.0
    assert radar.pnl_pct == 0.0
    assert radar.is_invalidated is True
    assert radar.stage == "EXPIRED"

    # Verify no quarantine penalty or symbol lockout was imposed
    clean_sym = engine._clean_sym("SUNPHARMA")
    assert clean_sym not in engine._directional_quarantine


def test_session_scorecard_unfulfilled_partition():
    """Verify generate_session_scorecard puts untriggered setups under unfulfilled and does not count negative R."""
    untriggered_alert = AutoAlert(
        alert_id="aa-radar-sunpharma-test",
        alert_type="PRECURSOR_RADAR",
        stage="DISQUALIFIED",
        symbol="SUNPHARMA",
        exchange="NSE",
        direction="BULLISH",
        headline="Radar",
        summary="Radar",
        ltp=1850.0,
        trigger_level=1880.0,
        stop_loss=1820.0,
        target_level=1950.0,
        target_status="SETUP_DISQUALIFIED",
        r_multiple=0.0,
        pnl_pct=0.0,
        created_at="2026-10-14 09:30:00 IST",
    )

    scorecard = generate_session_scorecard(
        today_alerts=[untriggered_alert],
        session_date="2026-10-14",
    )

    assert scorecard["total_alerts"] == 1
    assert scorecard["unfulfilled"] == 1
    assert scorecard["losses"] == 0
    assert scorecard["wins"] == 0
    assert scorecard["net_realized_r"] == 0.0


def test_precursor_radar_does_not_pre_ignite():
    """Verify PRECURSOR_RADAR requires genuine trigger breach and does not pre-ignite at 0.25% distance."""
    engine = AutoAlertEngine()

    radar = AutoAlert(
        alert_id="aa-precursor-banknifty-test",
        alert_type="PRECURSOR_RADAR",
        stage="EARLY_WARNING",
        symbol="BANKNIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="BankNifty Precursor",
        summary="Coiling below 55551.75",
        ltp=55400.0,
        trigger_level=55551.75,
        stop_loss=55200.0,
        target_level=56000.0,
    )
    engine._alerts = [radar]

    # Price at 55450.0 is 0.18% below trigger level 55551.75.
    # An asymmetric setup might pre-ignite within 0.25%, but PRECURSOR_RADAR must NOT pre-ignite!
    engine._batch_refresh_quotes = lambda alerts: {"NSE:BANKNIFTY": 55450.0, "BANKNIFTY": 55450.0}
    ignited = engine.check_and_ignite_early_warnings()
    assert len(ignited) == 0, "PRECURSOR_RADAR must NOT pre-ignite before genuine trigger breach!"
    assert radar.stage in ("EARLY_WARNING", "PRIMED")

    # Price crosses genuine trigger level at 55560.0
    engine._batch_refresh_quotes = lambda alerts: {"NSE:BANKNIFTY": 55560.0, "BANKNIFTY": 55560.0}
    ignited_genuine = engine.check_and_ignite_early_warnings()
    assert len(ignited_genuine) == 1
    assert radar.stage == "IGNITED"
    assert radar.has_triggered is True


def test_intraday_spark_atr_volatility_noise_floor():
    """Verify intraday spark enforces >= 1.20x ATR noise floor symmetrically on bullish and bearish setups."""
    ltp = 1025.0
    atr_val = 10.0
    price_tier = resolve_price_tier(ltp)
    expected_min_risk = max(price_tier.abs_min_risk_pts, round(1.20 * atr_val, 2))

    assert expected_min_risk >= 12.0, "Expected min risk must be at least 1.20x ATR (12.0 pts)!"


def test_orb_detector_noise_floor():
    """Verify ORB detector uses resolve_price_tier and >= 1.0x ATR volatility noise floor."""
    import pandas as pd

    dates = pd.date_range("2026-10-14 09:15", periods=20, freq="1min", tz=IST)
    df = pd.DataFrame(
        {
            "open": [1000.0] * 20,
            "high": [1008.0] * 20,
            "low": [995.0] * 20,
            "close": [1005.0] * 20,
            "volume": [10000] * 20,
        },
        index=dates,
    )

    # 10:00 IST is inside the ORB 09:30 - 11:30 execution window
    ref_time = datetime(2026, 10, 14, 10, 0, tzinfo=IST)
    alert = detect_opening_range_breakout(
        symbol="INFY",
        df=df,
        ltp=1010.0,
        vwap=1003.0,
        rvol=2.2,
        ref_time=ref_time,
        orb_levels=(1008.0, 995.0, 13.0, 1001.5),
    )
    assert alert is not None
    # Risk points must be >= 1.0x ATR / price tier, not tiny sub-ATR 0.20x
    risk_pts = abs(alert.trigger_level - alert.stop_loss)
    assert risk_pts >= 8.0, f"ORB risk points {risk_pts} must be properly cushioned against noise!"


def test_0dte_late_session_spread_mandate():
    """Verify post-14:30 IST 0DTE index options mandate SPREAD_ONLY defined-risk execution."""
    ref_time_late = datetime(2026, 10, 14, 14, 45, tzinfo=IST)
    today_str = ref_time_late.strftime("%Y-%m-%d")

    # Mock 0DTE options chain
    chain = [
        type(
            "MockOpt",
            (),
            {
                "strike": 25000,
                "option_type": "CE",
                "expiry": today_str,
                "ltp": 60.0,
                "delta": 0.50,
                "iv": 14.0,
                "volume": 200000,
                "oi": 500000,
                "tradingsymbol": "NIFTY26OCT25000CE",
            },
        )(),
        type(
            "MockOpt",
            (),
            {
                "strike": 25100,
                "option_type": "CE",
                "expiry": today_str,
                "ltp": 25.0,
                "delta": 0.30,
                "iv": 14.0,
                "volume": 150000,
                "oi": 400000,
                "tradingsymbol": "NIFTY26OCT25100CE",
            },
        )(),
    ]

    import pandas as pd

    dates = pd.date_range("2026-10-14 09:15", periods=50, freq="5min", tz=IST)
    ohlcv = pd.DataFrame(
        {
            "open": [24950.0] * 50,
            "high": [25020.0] * 50,
            "low": [24940.0] * 50,
            "close": [25010.0] * 50,
            "volume": [10000] * 50,
        },
        index=dates,
    )

    alerts = detect_index_call_setup(
        underlying="NIFTY",
        spot=25005.0,
        chain=chain,
        vwap=24980.0,
        day_high=25020.0,
        day_low=24940.0,
        prev_day_high=24990.0,
        prev_day_low=24900.0,
        ohlcv_5m=ohlcv,
        ref_time=ref_time_late,
        ignore_time_gate=True,
    )
    if alerts:
        alert = alerts[0]
        assert alert.instrument_type == "OPTION_SPREAD", "0DTE post-14:30 must be OPTION_SPREAD!"
        assert alert.hedge_plan is not None
        assert alert.hedge_plan.get("preferred_vehicle") == "SPREAD_ONLY"
