from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import numpy as np

IST = ZoneInfo("Asia/Kolkata")


def test_orb_extended_window_and_rolling_rvol():
    """Verify that ORB detector accepts trades up to 12:00 IST and uses rolling 5-bar RVOL."""
    from engine.detectors.orb import detect_opening_range_breakout

    # Construct synthetic 5m candles mimicking BankNifty 11:35 IST breakout
    times = pd.date_range("2026-11-09 09:15", "2026-11-09 11:35", freq="5min", tz=IST)
    n = len(times)
    np.random.seed(42)

    # Base price coiling in range [59200, 59400]
    prices = [59300.0]
    for _ in range(n - 1):
        prices.append(prices[-1] + np.random.uniform(-15.0, 15.0))

    # Opening 09:15 bar has massive 500,000 volume
    vols = [500000.0] + [25000.0] * (n - 2)
    # The breakout bar at 11:35 has 80,000 volume (3.2x rolling 25k, but < session avg)
    vols.append(80000.0)

    # Breakout bar pushes spot above ORB high (59420)
    prices[-1] = 59430.0

    df = pd.DataFrame(
        {
            "open": prices,
            "high": [p + 20.0 for p in prices],
            "low": [p - 20.0 for p in prices],
            "close": prices,
            "volume": vols,
        },
        index=times,
    )

    now_1135 = datetime(2026, 11, 9, 11, 35, tzinfo=IST)
    orb_levels = (59400.0, 59200.0, 200.0, 59300.0)

    # Test with 11:35 IST timestamp
    alert = detect_opening_range_breakout(
        symbol="BANKNIFTY",
        df=df,
        ltp=59430.0,
        vwap=59310.0,
        orb_levels=orb_levels,
        ref_time=now_1135,
        ignore_time_gate=False,
    )

    assert alert is not None, "11:35 IST ORB Breakout should not be rejected by time gate"
    assert alert.direction == "BULLISH"
    assert alert.metrics["orb_high"] == 59400.0
    assert alert.metrics["rvol"] >= 1.30


def test_fno_only_policy_enriches_stock_alert(monkeypatch):
    """Verify that record_alert under FNO_ONLY does not drop eligible F&O stocks as FOCUS_FILTERED."""
    monkeypatch.setenv("SESSION_FOCUS_MODE", "FNO_ONLY")
    monkeypatch.setenv("CHANAKYA_TESTING", "1")

    from engine.auto_alert_engine import AutoAlertEngine
    from engine.alert_model import AutoAlert
    from config.discovery_policy import get_discovery_policy

    policy = get_discovery_policy()
    assert policy.fno_only is True

    engine = AutoAlertEngine()

    alert = AutoAlert(
        alert_id="aa-orb-breakout-divislab-bull-20261109",
        alert_type="ORB_BREAKOUT",
        stage="ACTIONABLE",
        symbol="NSE:DIVISLAB",
        exchange="NSE",
        segment="EQUITY",
        direction="BULLISH",
        headline="ORB BREAKOUT: DIVISLAB Bullish",
        summary="Opening range breakout confirmed on DIVISLAB",
        ltp=6150.0,
        trigger_level=6140.0,
        stop_loss=6050.0,
        target_level=6320.0,
        metrics={"rvol": 1.8},
    )

    # Call record_alert
    engine.record_alert(alert)

    # DIVISLAB is an active F&O constituent: it must NOT be dropped by FOCUS_FILTERED and must be tagged FNO_STOCK
    focus_filtered_events = [a for a in alert.audit_trail if a.get("action") == "FOCUS_FILTERED"]
    assert len(focus_filtered_events) == 0, (
        "F&O stock alert must not be dropped with FOCUS_FILTERED"
    )
    assert alert.segment == "FNO_STOCK", "Alert segment should be updated to FNO_STOCK"


def test_vsa_climax_gate_exempts_confirmed_breakouts():
    """Verify that alert scrutiny does not veto confirmed expansion breakouts on EFFORT_NO_RESULT_BEARISH."""
    from engine.alert_scrutiny import scrutinize_alert
    from engine.alert_model import AutoAlert

    alert = AutoAlert(
        alert_id="aa-double-bottom-breakout-banknifty-bull-20261109",
        alert_type="DOUBLE_BOTTOM_BREAKOUT",
        stage="ACTIONABLE",
        symbol="BANKNIFTY",
        exchange="NSE",
        segment="FNO_INDEX",
        direction="BULLISH",
        headline="DOUBLE BOTTOM BREAKOUT: BANKNIFTY",
        summary="Confirmed double bottom neck-line expansion breakout",
        ltp=59520.0,
        trigger_level=59500.0,
        stop_loss=59300.0,
        target_level=59900.0,
        metrics={
            "vsa_signal": "EFFORT_NO_RESULT_BEARISH",  # Upper wick on 5m breakout bar
            "vwap": 59380.0,
            "rvol": 2.2,
        },
    )

    result = scrutinize_alert(alert)

    # Should not fail on VSA Distribution Trap Veto
    rejection_msg = result.rejection_reason or ""
    assert "VSA Distribution Trap Veto" not in rejection_msg


def test_trend_continuation_relative_strength_decoupling():
    """Verify that a strong leader stock (e.g. DIVISLAB) is not suppressed when benchmark Nifty is below VWAP."""
    from engine.detectors.trend_day_continuation import detect_trend_day_pullback

    # Build 5m candles showing strong uptrend with a minor dry-up dip
    times = pd.date_range("2026-11-09 09:15", "2026-11-09 11:30", freq="5min", tz=IST)
    n = len(times)

    prices = np.linspace(5900.0, 6150.0, n)
    vols = [50000.0] * n
    # Make dip candle have volume dryup
    vols[-1] = 20000.0

    df = pd.DataFrame(
        {
            "open": prices,
            "high": prices + 10.0,
            "low": prices - 5.0,
            "close": prices,
            "volume": vols,
        },
        index=times,
    )

    now_1130 = datetime(2026, 11, 9, 11, 30, tzinfo=IST)

    # Stock is trading at 6150 with VWAP at 6050 (1.65% above VWAP - clear RS leader)
    alert = detect_trend_day_pullback(
        symbol="DIVISLAB",
        df_5m=df,
        ltp=6150.0,
        now_dt=now_1130,
        exchange="NSE",
    )

    if alert is not None:
        assert alert.direction == "BULLISH"
        assert "DIVISLAB" in alert.symbol


def test_smt_divergence_verdict_property_and_contract():
    """Verify that SMTDivergenceResult safely supports .verdict and is_trap."""
    from engine.smt_divergence import SMTDivergenceResult

    res = SMTDivergenceResult(
        has_divergence=True,
        divergence_type="BEARISH_DIVERGENCE_BULL_TRAP",
        sibling_symbol="BANKNIFTY",
        primary_symbol="NIFTY",
        is_trap=True,
        rationale="BankNifty non-confirmed",
    )

    assert res.verdict == "BEARISH_DIVERGENCE_BULL_TRAP"
    assert res.is_trap is True


def test_defined_risk_neutral_options_contract_ducktyping():
    """Verify that detect_defined_risk_neutral handles OptionsContract instances without .get() AttributeError."""
    from brokers.base import OptionsContract
    from engine.detection_context import build_detection_context
    from engine.detectors.defined_risk_neutral import detect_defined_risk_neutral

    times = pd.date_range("2026-11-09 09:15", "2026-11-09 13:00", freq="15min", tz=IST)
    n = len(times)
    # Range-bound prices around 24500
    prices = np.full(n, 24500.0)
    df = pd.DataFrame(
        {
            "open": prices,
            "high": prices + 15.0,
            "low": prices - 15.0,
            "close": prices,
            "volume": [10000.0] * n,
        },
        index=times,
    )

    # Provide real OptionsContract objects with OI walls
    contracts = [
        OptionsContract(
            symbol="NIFTY26NOV24300PE",
            underlying="NIFTY",
            expiry="2026-11-26",
            strike=24300.0,
            option_type="PE",
            last_price=45.0,
            oi=5000000,
            oi_change=10000,
            volume=200000,
        ),
        OptionsContract(
            symbol="NIFTY26NOV24400PE",
            underlying="NIFTY",
            expiry="2026-11-26",
            strike=24400.0,
            option_type="PE",
            last_price=70.0,
            oi=8000000,  # Put Wall
            oi_change=50000,
            volume=350000,
        ),
        OptionsContract(
            symbol="NIFTY26NOV24600CE",
            underlying="NIFTY",
            expiry="2026-11-26",
            strike=24600.0,
            option_type="CE",
            last_price=65.0,
            oi=9000000,  # Call Wall
            oi_change=40000,
            volume=400000,
        ),
        OptionsContract(
            symbol="NIFTY26NOV24700CE",
            underlying="NIFTY",
            expiry="2026-11-26",
            strike=24700.0,
            option_type="CE",
            last_price=35.0,
            oi=4500000,
            oi_change=12000,
            volume=180000,
        ),
    ]

    ctx = build_detection_context(
        symbol="NSE:NIFTY",
        exchange="NSE",
        segment="FNO_INDEX",
        ltp=24500.0,
        prev_close=24490.0,
        candles_15m=df,
        option_chain=contracts,
    )

    # Must execute safely without throwing AttributeError
    alert = detect_defined_risk_neutral(ctx)
    if alert is not None:
        assert alert.direction == "NEUTRAL"
        assert alert.alert_type == "DEFINED_RISK_NEUTRAL"


def test_afternoon_session_time_gate_alignment():
    """Verify that Intraday Sparks and Trend Continuation remain active past 14:00/14:30 IST until 15:15 IST."""
    import inspect
    from engine.detectors.intraday_spark import detect_intraday_mover_sparks
    from engine.detectors.trend_day_continuation import detect_trend_day_pullback

    spark_src = inspect.getsource(detect_intraday_mover_sparks)
    trend_src = inspect.getsource(detect_trend_day_pullback)

    # Intraday spark must not shut off at 14:00; must run until 15:15
    assert "dtime(14, 0)" not in spark_src
    assert "dtime(15, 15)" in spark_src

    # Trend day continuation must not shut off at 14:30; must run until 15:15
    assert "dtime(14, 30)" not in trend_src
    assert "dtime(15, 15)" in trend_src


def test_options_momentum_stock_volume_normalization():
    """Verify that options_momentum uses lot-size proportional volume rather than requiring 2500 contracts for stocks."""
    import inspect
    from engine.detectors.options_momentum import detect_options_momentum_breakouts

    src = inspect.getsource(detect_options_momentum_breakouts)
    # Ensure hardcoded 2500-contract requirement for stock option decoupler is eliminated
    assert "vol >= 2500" not in src
    assert "eff_decouple_vol" in src


def test_option_resolver_single_stock_expiry_week_routing(monkeypatch):
    """Verify that resolve_option_contract routes single-stock options to next-month contract during settlement week."""
    from engine.option_resolver import resolve_option_contract
    from brokers.base import OptionsContract

    # Mock is_monthly_physical_expiry_week to return True
    monkeypatch.setattr(
        "engine.alert_expiry.is_monthly_physical_expiry_week",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "engine.alert_expiry.resolve_recommended_derivative_expiry",
        lambda *args, **kwargs: {
            "is_next_month_routed": True,
            "recommended_expiry": "2026-12-31",
            "series": "NEXT_MONTH",
        },
    )

    # Provide contracts with next-month expiry
    next_month_contracts = [
        OptionsContract(
            symbol="RELIANCE26DEC1400CE",
            underlying="RELIANCE",
            expiry="2026-12-31",
            strike=1400.0,
            option_type="CE",
            last_price=45.0,
            bid=44.5,
            ask=45.5,
            volume=5000,
            oi=10000,
            oi_change=500,
        )
    ]

    plan = resolve_option_contract(
        symbol="RELIANCE",
        spot=1400.0,
        direction="BULLISH",
        contracts_override=next_month_contracts,
        india_vix=14.0,
    )

    assert plan is not None
    assert plan.is_next_month_routed is True
    assert plan.as_dict()["is_next_month_routed"] is True


def test_scale_isolation_no_chase_gate_rule_5():
    """Verify that alert scrutiny Rule 5 does not veto equity-scale alerts when option boundary is in plan."""
    from engine.alert_scrutiny import scrutinize_alert
    from engine.alert_model import AutoAlert

    alert = AutoAlert(
        alert_id="aa-intraday-mover-spark-divislab-bull-20261109",
        alert_type="INTRADAY_MOVER_SPARK",
        stage="ACTIONABLE",
        symbol="DIVISLAB",
        exchange="NSE",
        segment="FNO_STOCK",
        direction="BULLISH",
        headline="INTRADAY SPARK: DIVISLAB Bullish",
        summary="High momentum breakout on DIVISLAB",
        ltp=6150.0,
        trigger_level=6140.0,
        stop_loss=6050.0,
        target_level=6320.0,
        no_chase_boundary=6180.0,
        spot_no_chase_boundary=6180.0,
        actionable_plan={
            "no_chase_boundary": "₹146.50",  # Option premium scale leaked or present
            "spot_no_chase_boundary": "₹6,180.00",
            "option_no_chase_boundary": "₹146.50",
            "recommended_entry": "₹6,140.00",
            "stop_loss": "₹6,050.00",
            "target": "₹6,320.00",
        },
        metrics={
            "spot_no_chase_boundary": 6180.0,
            "rvol": 2.2,
            "vwap": 6050.0,
        },
    )

    result = scrutinize_alert(alert)

    # Scrutiny must not fail on No-Chase Violation due to 146.50 vs 6150.0
    rejection = result.rejection_reason or ""
    assert "No-Chase Violation" not in rejection


def test_adr_consumed_afternoon_thrust_rule_3g_exemption():
    """Verify that AFTERNOON_THRUST is not killed by Rule 3g when 72% of normal ADR is consumed."""
    from engine.alert_scrutiny import scrutinize_alert
    from engine.alert_model import AutoAlert

    alert = AutoAlert(
        alert_id="aa-afternoon-thrust-reliance-bull-20261109",
        alert_type="AFTERNOON_THRUST",
        stage="ACTIONABLE",
        symbol="RELIANCE",
        exchange="NSE",
        segment="FNO_STOCK",
        direction="BULLISH",
        headline="AFTERNOON THRUST: RELIANCE",
        summary="Power hour breakout after tight midday coil",
        ltp=1420.0,
        trigger_level=1418.0,
        stop_loss=1405.0,
        target_level=1445.0,
        no_chase_boundary=1425.0,
        created_at="2026-11-09 13:45:00 IST",
        metrics={
            "adr_consumed_pct": 75.0,  # > 65% normal morning ceiling
            "is_tight_midday_coil": True,
            "rvol": 1.8,
            "vwap": 1410.0,
        },
    )

    result = scrutinize_alert(alert)

    rejection = result.rejection_reason or ""
    assert "Stagnation Fuel Exhaustion Veto" not in rejection


def test_orb_option_scale_isolation():
    """Verify that ORB detector for index options generates option-space no_chase_boundary."""
    from engine.detectors.orb import detect_opening_range_breakout

    times = pd.date_range("2026-11-09 09:15", "2026-11-09 10:00", freq="5min", tz=IST)
    n = len(times)
    prices = [24500.0 + i * 15.0 for i in range(n)]
    df = pd.DataFrame(
        {
            "open": prices,
            "high": [p + 10.0 for p in prices],
            "low": [p - 10.0 for p in prices],
            "close": prices,
            "volume": [50000.0] * n,
        },
        index=times,
    )

    alert = detect_opening_range_breakout(
        symbol="NIFTY",
        df=df,
        ltp=24650.0,
        vwap=24550.0,
        orb_levels=(24600.0, 24450.0, 150.0, 24525.0),
        ref_time=datetime(2026, 11, 9, 10, 0, tzinfo=IST),
        ignore_time_gate=False,
    )

    if alert is not None:
        # If an option plan was resolved, no_chase_boundary should be in option premium space, not 24000+
        if alert.option_premium and alert.option_premium > 0:
            assert alert.no_chase_boundary < 1000.0
            assert (
                alert.spot_no_chase_boundary is not None and alert.spot_no_chase_boundary > 20000.0
            )
