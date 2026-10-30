"""
tests/test_alert_session_rca_invariants.py

Deterministic regression and invariant verification for Alert Session RCA fixes:
1. Zero Ghost +6.0R Win Inflation (trend_day_continuation r_multiple is None at ignition).
2. Tier-2 Scrutiny Veto uses disqualify_alert_by_id (0 capital risked, zero phantom trading losses).
3. Post-mortem scorecard respects disqualified/cancelled/superseded setups (0.0R, unfulfilled).
4. Sector Leader supersede updates stage=CANCELLED and target_status=SUPERSEDED.
5. EOD report separates pure option premium scale from equity spot setups (no BHARATFORG contamination).
6. EOD Sweep cleanly squares off intraday alerts post-market (no zombie in-flight positions).
7. Intraday spark enforces 14:00 IST cutoff.
"""

import os
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from config.constants import IST
from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine
from engine.alert_postmortem_runner import generate_session_scorecard
from engine.eod_report_generator import EODReportGenerator


def make_alert(**kwargs) -> AutoAlert:
    defaults = {
        "alert_id": "aa-test-default-id",
        "alert_type": "TREND_DAY_PULLBACK",
        "stage": "IGNITED",
        "symbol": "TEST",
        "exchange": "NSE",
        "direction": "BULLISH",
        "headline": "Test Headline",
        "summary": "Test Summary",
        "ltp": 100.0,
        "trigger_level": 100.0,
        "target_level": 110.0,
        "stop_loss": 95.0,
    }
    defaults.update(kwargs)
    return AutoAlert(**defaults)


def test_trend_day_continuation_zero_ghost_r_multiple():
    """Verify trend_day_pullback creates alerts with r_multiple=None, not pre-filled 6.0R."""
    from engine.detectors.trend_day_continuation import detect_trend_day_pullback
    from tests.test_trend_day_pullback import _generate_synthetic_trend_df

    df_5m = _generate_synthetic_trend_df(direction="BULLISH")
    last_ltp = float(df_5m["close"].iloc[-1])
    test_dt = datetime(2026, 10, 22, 11, 30, tzinfo=IST)

    with patch("os.environ.get", return_value="1"):
        alert = detect_trend_day_pullback(
            symbol="INFY",
            df_5m=df_5m,
            ltp=last_ltp,
            now_dt=test_dt,
            exchange="NSE",
            segment="EQUITY",
        )

    assert alert is not None
    assert alert.r_multiple is None, f"Expected r_multiple=None at ignition, got {alert.r_multiple}"


def test_tier2_scrutiny_veto_calls_disqualify_not_invalidate():
    """Verify that when Tier-2 scrutiny vetoes an alert, it marks SETUP_DISQUALIFIED and 0 capital risked."""
    engine = AutoAlertEngine()
    alert = make_alert(alert_id="aa-test-scrutiny-veto-20261028")
    engine._alerts = [alert]

    vetoed_alert = engine.disqualify_alert_by_id(
        alert.alert_id, reason="Tier-2 Scrutiny Veto: Morning Reversal Trap"
    )

    assert vetoed_alert is not None
    assert vetoed_alert.stage == "CANCELLED"
    assert vetoed_alert.target_status == "SETUP_DISQUALIFIED"
    assert vetoed_alert.is_invalidated is False
    assert vetoed_alert.r_multiple == 0.0
    assert "PRE-TRADE VETO" in vetoed_alert.headline


def test_postmortem_scorecard_excludes_disqualified_from_losses():
    """Verify generate_session_scorecard does NOT count disqualified/cancelled setups as losses."""
    alert_loss = make_alert(
        alert_id="aa-real-stop-loss-20261028",
        stage="INVALIDATED",
        is_invalidated=True,
        r_multiple=-1.0,
    )

    alert_veto = make_alert(
        alert_id="aa-pretrade-veto-20261028",
        stage="CANCELLED",
        target_status="SETUP_DISQUALIFIED",
        is_invalidated=False,
        r_multiple=0.0,
    )

    scorecard = generate_session_scorecard([alert_loss, alert_veto], session_date="20261028")

    assert scorecard["losses"] == 1, f"Expected exactly 1 loss, got {scorecard['losses']}"
    assert scorecard["unfulfilled"] == 1, (
        f"Expected 1 unfulfilled/vetoed setup, got {scorecard['unfulfilled']}"
    )
    assert scorecard["net_realized_r"] == -1.0, (
        f"Expected net_realized_r=-1.0, got {scorecard['net_realized_r']}"
    )


def test_sector_leader_supersede_marks_cancelled():
    """Verify that when a sector leader supersedes an existing alert, the superseded alert is CANCELLED."""
    engine = AutoAlertEngine()
    existing = make_alert(
        alert_id="aa-existing-leader-20261028",
        symbol="OLDLEAD",
        confidence=75,
        metrics={"rvol": 1.5, "sector_id": "IT"},
    )
    engine._alerts = [existing]

    incoming = make_alert(
        alert_id="aa-incoming-leader-20261028",
        symbol="NEWLEAD",
        confidence=85,
        metrics={"rvol": 2.5, "sector_id": "IT"},
    )

    with (
        patch("analysis.universe.get_stock_sector", return_value=("IT", "IT Sector")),
        patch.object(engine, "_load", return_value=None),
        patch.object(engine, "_save", return_value=None),
        patch.object(engine, "_dispatch", return_value=None),
    ):
        # Calling sector leader evaluation
        engine.record_alert(incoming)

        # Existing alert should be superseded
        assert existing.is_archived is True
        assert existing.stage == "CANCELLED"
        assert existing.target_status == "SUPERSEDED"
        assert "Superseded by stronger Sector Leader" in existing.archive_reason


def test_eod_report_equity_spot_scale_isolation():
    """Verify equity setups with attached option recommendation keep equity symbol and spot scale."""
    generator = EODReportGenerator()

    # Cash alert with attached option contract vehicle
    alert_equity_with_option = {
        "alert_id": "aa-intraday-breakout-spark-bharatforg-bull-20261028",
        "alert_type": "INTRADAY_BREAKOUT_SPARK",
        "symbol": "BHARATFORG",
        "contract_symbol": "NSE:BHARATFORG26NOV1780CE",
        "direction": "BULLISH",
        "stage": "IGNITED",
        "target_status": "PENDING",
        "ltp": 1776.4,
        "entry_price": 1777.4,
        "trigger_level": 1777.4,
        "stop_loss": 1716.58,
        "target_level": 1899.04,
        "option_premium": 63.8,
        "underlying_spot": 1776.4,
        "created_at": "2026-10-28 13:15:00 IST",
    }

    mock_mkt = {
        "nifty_ltp": 24000.0,
        "nifty_change_pct": 0.5,
        "banknifty_ltp": 51000.0,
        "banknifty_change_pct": 0.4,
        "sensex_ltp": 79000.0,
        "sensex_change_pct": 0.3,
        "vix_ltp": 14.5,
        "market_posture": "BULLISH",
        "fii_net_cr": 500.0,
        "dii_net_cr": 800.0,
        "provenance": "REAL/LIVE",
    }

    with (
        patch.object(generator, "_load_alerts", return_value=[alert_equity_with_option]),
        patch.object(generator, "_get_market_context", return_value=mock_mkt),
    ):
        report = generator.generate(target_date="2026-10-28")
        entry = report.journal_entries[0]

        # Must display equity symbol BHARATFORG, not option contract NSE:BHARATFORG26NOV1780CE
        assert entry.symbol == "BHARATFORG", f"Expected 'BHARATFORG', got '{entry.symbol}'"
        assert entry.entry_level == 1777.4, f"Expected spot entry 1777.4, got {entry.entry_level}"
        assert entry.stop_loss == 1716.58, f"Expected spot SL 1716.58, got {entry.stop_loss}"


def test_eod_sweep_squares_off_intraday_positions():
    """Verify sweep_intraday_eod_squareoffs converts in-flight intraday setups to SESSION_CLOSE_EXIT."""
    engine = AutoAlertEngine()
    alert_intraday = make_alert(
        alert_id="aa-inflight-intraday-20261028",
        alert_type="INTRADAY_BREAKOUT_SPARK",
        symbol="INFLIGHT",
        time_horizon="INTRADAY",
        ltp=105.0,
        trigger_level=100.0,
        stop_loss=95.0,
        target_level=110.0,
    )
    engine._alerts = [alert_intraday]

    with (
        patch.object(engine, "_save", return_value=None),
        patch.object(engine, "_dispatch", return_value=None),
        patch("engine.auto_alert_engine.datetime") as mock_dt,
    ):
        # Simulate 15:35 IST
        mock_now = datetime(2026, 10, 28, 15, 35, tzinfo=IST)
        mock_dt.now.return_value = mock_now

        closed = engine.sweep_intraday_eod_squareoffs()
        assert len(closed) == 1
        assert alert_intraday.stage == "COMPLETED"
        assert alert_intraday.target_status == "SESSION_CLOSE_EXIT"
        assert "15:15 IST cutoff reached" in alert_intraday.archive_reason


def test_intraday_spark_1400_cutoff():
    """Verify intraday spark detector does not scan after 14:00 IST."""
    from engine.detectors.intraday_spark import detect_intraday_mover_sparks

    with (
        patch("engine.detectors.intraday_spark.os.environ.get", return_value="0"),
        patch("engine.auto_alert_engine.datetime") as mock_aae_dt,
    ):
        # Simulate 14:05 IST
        mock_aae_dt.now.return_value = datetime(2026, 10, 28, 14, 5, tzinfo=IST)
        sparks = detect_intraday_mover_sparks(universe=["RELIANCE"])
        assert sparks == [], "Expected zero sparks after 14:00 IST"


def test_scorecard_calibration_integrity_clamping():
    """Verify scorecard clamps phantom R > 0.5 to 0.0 when 0 milestones achieved and not invalidated."""
    from engine.alert_postmortem_runner import generate_session_scorecard

    # Alert with unearned +6.0R
    corrupted_alert = make_alert(
        alert_id="aa-trend_day-tcs-20261028",
        symbol="TCS",
        alert_type="TREND_DAY_PULLBACK",
        r_multiple=6.0,
        achieved_milestones=[],
        is_invalidated=False,
        stage="ACTIONABLE",
    )

    scorecard = generate_session_scorecard([corrupted_alert], session_date="2026-10-28")
    assert scorecard["wins"] == 0, f"Expected 0 wins, got {scorecard['wins']}"
    assert scorecard["unfulfilled"] == 1
    assert scorecard["net_realized_r"] == 0.0, (
        f"Expected 0.0 net R, got {scorecard['net_realized_r']}"
    )


def test_midday_compression_lull_rvol_threshold():
    """Verify 1.75x RVOL requirement for non-apex in midday lull, and exemption for apex."""
    from engine.session_runway import evaluate_session_runway

    midday_time = datetime(2026, 10, 28, 12, 0, tzinfo=IST)

    with patch.dict(os.environ, {"FORCE_RUNWAY_CHECK": "1"}, clear=False):
        # 1. Non-apex with low RVOL (1.4x < 1.75x) -> VETO
        res_low = evaluate_session_runway(
            symbol="INFY",
            alert_type="INTRADAY_BREAKOUT_SPARK",
            time_horizon="INTRADAY",
            segment="EQUITY",
            rvol=1.4,
            now_dt=midday_time,
            is_apex=False,
        )
        assert not res_low.is_allowed
        assert "Midday Compression Lull" in res_low.veto_reason

        # 2. Non-apex with high RVOL (1.8x >= 1.75x) -> ALLOWED
        res_high = evaluate_session_runway(
            symbol="INFY",
            alert_type="INTRADAY_BREAKOUT_SPARK",
            time_horizon="INTRADAY",
            segment="EQUITY",
            rvol=1.8,
            now_dt=midday_time,
            is_apex=False,
        )
        assert res_high.is_allowed

        # 3. Apex opportunity with low RVOL (1.2x) -> ALLOWED
        res_apex = evaluate_session_runway(
            symbol="INFY",
            alert_type="INTRADAY_BREAKOUT_SPARK",
            time_horizon="INTRADAY",
            segment="EQUITY",
            rvol=1.2,
            now_dt=midday_time,
            is_apex=True,
        )
        assert res_apex.is_allowed


def test_telegram_apex_gate_and_delivery_status():
    """Verify Telegram gate records HELD delivery status when non-apex signal is held in UI."""
    engine = AutoAlertEngine()
    engine._alerts.clear()

    non_apex = make_alert(
        alert_id="aa-spark-wipro-20261028",
        symbol="WIPRO",
        alert_type="INTRADAY_MOVER_SPARK",
        confidence=82,
        stage="ACTIONABLE",
    )

    with (
        patch.dict(os.environ, {"TELEGRAM_APEX_ONLY": "1", "CHANAKYA_TESTING": "0"}, clear=False),
        patch("market.calendar.is_market_open", return_value=True),
    ):
        engine._dispatch(non_apex)
        assert non_apex.telegram_delivery_status == "HELD"
        assert "Telegram channel restricted to Apex signals only" in (
            non_apex.telegram_suppression_reason or ""
        )


def test_index_and_stocks_fno_zero_hourly_daily_pacing_invariants():
    """Verify that Index and Stocks F&O have ZERO hourly and daily pacing limits.

    1. 20 index alerts in 30 minutes all pass unthrottled through Telegram Apex gate.
    2. 20 stocks F&O alerts in 30 minutes all pass unthrottled through Telegram Apex gate.
    3. 5 stock option alerts in the exact same sector within 30 minutes all pass unthrottled.
    4. Index and Stocks F&O are never throttled by daily limits, directional limits, or burst cooldown.
    """

    def _create_fno_alert(
        alert_id, symbol, segment="FNO_INDEX", strike=22500.0, ltp=120.0, sector="it", confidence=90
    ):
        c_sym = f"{symbol}{int(strike)}CE"
        return AutoAlert(
            alert_id=alert_id,
            alert_type="GAMMA_BLAST" if segment == "FNO_INDEX" else "BREAKOUT",
            stage="IGNITED",
            symbol=symbol,
            exchange="NFO",
            direction="BULLISH",
            headline=f"⚡ {symbol} {segment} SETUP",
            summary=f"Setup for {symbol}",
            ltp=ltp,
            trigger_level=ltp,
            target_level=round(ltp * 1.35, 1),
            stop_loss=round(ltp * 0.80, 1),
            strike=strike,
            option_type="CE",
            contract_symbol=c_sym,
            expiry_date=(datetime.now(IST) + timedelta(days=7)).strftime("%Y-%m-%d"),
            underlying_spot=strike,
            option_premium=ltp,
            is_live=True,
            environment="LIVE",
            segment=segment,
            confidence=confidence,
            created_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
            metrics={
                "spot": strike,
                "strike": strike,
                "vwap": strike - 10.0,
                "delta": 0.50,
                "gamma": 0.005,
                "iv": 18.5,
                "is_0dte": False,
                "vol_oi_ratio": 2.5,
                "rvol": 3.0,
                "sector_id": sector,
                "signals": ["VWAP_BREAKOUT", "DAY_HIGH_BREAKOUT"],
                "is_institutional_thrust": True,
            },
        )

    engine = AutoAlertEngine()
    now_t = time.time()
    today_k = datetime.now(IST).strftime("%Y-%m-%d")

    # 1. Seed 20 index alerts dispatched in last 30 minutes
    engine._hourly_telegram_dispatches["INDEX"] = [now_t - (i * 60) for i in range(20)]
    engine._hourly_index_directional = [(now_t - (i * 60), "BULLISH") for i in range(20)]
    engine._daily_index_telegram[today_k] = 20

    # 2. Seed 20 stock F&O alerts dispatched in last 30 minutes and 5 in sector 'it'
    engine._hourly_telegram_dispatches["STOCKS"] = [now_t - (i * 60) for i in range(20)]
    engine._hourly_telegram_dispatches["FNO_STOCK"] = [now_t - (i * 60) for i in range(20)]
    engine._hourly_fno_stock_directional = [(now_t - (i * 60), "BULLISH") for i in range(20)]
    engine._sector_hourly_telegram["it"] = [now_t - (i * 60) for i in range(5)]
    engine._sector_daily_telegram[today_k]["it"] = 15

    # Test 21st Index alert passes unthrottled
    idx_alert = _create_fno_alert("aa-idx-21", "NIFTY", segment="FNO_INDEX", strike=22600.0)
    passed, reason = engine._eval_telegram_apex_gate(idx_alert, in_market=True)
    assert passed is True, f"Index alert unexpectedly throttled: {reason}"
    assert reason == "PASSED_APEX_GATE"

    # Test 21st Stock F&O alert passes unthrottled
    stk_alert = _create_fno_alert(
        "aa-stk-21", "RELIANCE", segment="FNO_STOCK", strike=3000.0, sector="energy"
    )
    passed, reason = engine._eval_telegram_apex_gate(stk_alert, in_market=True)
    assert passed is True, f"Stock F&O alert unexpectedly throttled: {reason}"
    assert reason == "PASSED_APEX_GATE"

    # Test 6th Stock F&O alert in the same sector ('it') passes unthrottled
    tcs_alert = _create_fno_alert(
        "aa-tcs-6", "TCS", segment="FNO_STOCK", strike=3600.0, sector="it"
    )
    passed, reason = engine._eval_telegram_apex_gate(tcs_alert, in_market=True)
    assert passed is True, f"Stock F&O sector unexpectedly throttled: {reason}"
    assert reason == "PASSED_APEX_GATE"

    # Test zero burst cooldown for Index and Stocks F&O
    engine._last_telegram_dispatch_time = now_t
    quick_idx = _create_fno_alert("aa-idx-burst", "BANKNIFTY", segment="FNO_INDEX", strike=48500.0)
    passed, reason = engine._eval_telegram_apex_gate(quick_idx, in_market=True)
    assert passed is True, f"Index burst unexpectedly throttled: {reason}"

    quick_stk = _create_fno_alert(
        "aa-stk-burst", "INFY", segment="FNO_STOCK", strike=1800.0, sector="it"
    )
    passed, reason = engine._eval_telegram_apex_gate(quick_stk, in_market=True)
    assert passed is True, f"Stocks F&O burst unexpectedly throttled: {reason}"


def test_cpr_hydration_and_regime_veto_invariants():
    """Verify record_alert hydrates CPR and vetoes breakout chasing in CHOP_MEAN_REVERSION."""
    from engine.session_regime_sentinel import SessionRegimeClassification, CPRMetrics
    from engine.daily_levels import DailyLevels

    engine = AutoAlertEngine()
    engine._alerts = []

    # 1. Hydration invariant: CPR metrics are populated from DailyLevels if missing
    alert_narrow = make_alert(
        alert_id="aa-cpr-narrow-test-20261028",
        symbol="NARROWCO",
        alert_type="TREND_DAY_PULLBACK",
        metrics={},
    )
    mock_dl = DailyLevels(
        symbol="NARROWCO",
        canonical_symbol="NARROWCO",
        exchange="NSE",
        session_date="2026-10-28",
        pdh=105.0,
        pdl=95.0,
        pdc=100.0,
        cpr={
            "pivot": 100.0,
            "tc": 100.1,
            "bc": 99.9,
            "top": 100.1,
            "bottom": 99.9,
            "width_pct": 0.20,
            "is_narrow": True,
            "is_wide": False,
            "cpr_type": "NARROW",
        },
    )

    with (
        patch("engine.daily_levels.get_daily_levels", return_value=mock_dl),
        patch.object(engine, "_load", return_value=None),
        patch.object(engine, "_save", return_value=None),
        patch.object(engine, "_dispatch", return_value=None),
    ):
        ok = engine.record_alert(alert_narrow)
        assert ok is True
        assert "cpr" in alert_narrow.metrics
        assert alert_narrow.metrics["cpr"]["cpr_type"] == "NARROW"
        assert alert_narrow.metrics["is_trend_expansion_regime"] is True

    # 2. Veto invariant: Breakout chase in CHOP_MEAN_REVERSION is vetoed
    alert_chop_spark = make_alert(
        alert_id="aa-chop-spark-test-20261028",
        symbol="CHOPCO",
        alert_type="INTRADAY_BREAKOUT_SPARK",
        metrics={},
    )
    chop_regime_res = SessionRegimeClassification(
        symbol="CHOPCO",
        regime="CHOP_MEAN_REVERSION",
        cpr=CPRMetrics(100.0, 99.0, 101.0, 2.0, 2.0, "WIDE"),
        session_range_pts=5.0,
        adr_5d_pts=5.5,
        adr_exhaustion_pct=90.0,
        veto_breakout_chase=True,
        favor_mean_reversion=True,
        rationale="Exhaustion Veto on Wide CPR",
    )

    with (
        patch(
            "engine.session_regime_sentinel.check_alert_session_regime",
            return_value=chop_regime_res,
        ),
        patch.dict(os.environ, {"FORCE_REGIME_CHECK": "1"}),
    ):
        vetoed = engine.record_alert(alert_chop_spark)
        assert vetoed is False, "Expected breakout spark to be vetoed in CHOP_MEAN_REVERSION regime"


def test_target_calibration_and_t0_5_derisk_invariants():
    """Verify alert_evaluator compresses T1 on chop and triggers Target 0.5 early de-risking."""
    from engine.alert_evaluator import evaluate_alert_progress

    # 1. Wide CPR / Chop: T1 must be compressed to +1.2R even if static plan had +2.0R
    alert_chop = make_alert(
        alert_id="aa-chop-eval-test-20261028",
        symbol="CHOPCO",
        alert_type="INTRADAY_BREAKOUT_SPARK",
        direction="BULLISH",
        ltp=100.0,
        trigger_level=100.0,
        stop_loss=90.0,  # 10 pts risk
        target_level=120.0,  # Static 2.0R
        metrics={"is_chop_regime": True, "cpr_type": "WIDE"},
        actionable_plan={"target_1": 120.0},
    )

    # Price moves to +1.2R (112.0)
    res_t1 = evaluate_alert_progress(alert_chop, current_ltp=112.0)
    assert res_t1.is_t1_hit is True
    assert res_t1.new_milestone in ("T1_ACHIEVED", "TARGET_ACHIEVED")
    assert res_t1.target_level == 112.0, f"Expected compressed T1 112.0, got {res_t1.target_level}"

    # 2. Target 0.5 early de-risk ratchet at +0.8R
    alert_trend = make_alert(
        alert_id="aa-trend-eval-test-20261028",
        symbol="TRENDCO",
        alert_type="TREND_DAY_PULLBACK",
        direction="BULLISH",
        ltp=100.0,
        trigger_level=100.0,
        stop_loss=90.0,  # 10 pts risk
        target_level=120.0,  # 2.0R
        metrics={"is_trend_expansion_regime": True, "cpr_type": "NARROW"},
        actionable_plan={"target_1": 120.0},
    )

    # Price moves to +0.8R (108.0)
    res_t0_5 = evaluate_alert_progress(alert_trend, current_ltp=108.0)
    assert res_t0_5.is_t0_5_hit is True
    assert res_t0_5.new_milestone == "T0_5_ACHIEVED"
    # Stop-Loss must be moved to Breakeven (+0.2% fee buffer -> 100.20)
    assert res_t0_5.new_stop_loss >= 100.1, (
        f"Expected SL ratcheted to BE buffer, got {res_t0_5.new_stop_loss}"
    )


def test_cpr_telegram_rendering_invariants():
    """Verify render_auto_alert formats institutional CPR lines in Telegram output."""
    from bot.alert_templates import render_auto_alert

    # Case A: Narrow CPR Alert
    alert_narrow = make_alert(
        alert_id="aa-tg-narrow-20261028",
        symbol="NIFTY",
        alert_type="TREND_DAY_PULLBACK",
        direction="BULLISH",
        ltp=24150.0,
        trigger_level=24150.0,
        stop_loss=24050.0,
        target_level=24350.0,
        metrics={
            "cpr": {
                "pivot": 24100.0,
                "tc": 24115.0,
                "bc": 24085.0,
                "top": 24115.0,
                "bottom": 24085.0,
                "width_pct": 0.12,
                "cpr_type": "NARROW",
                "is_narrow": True,
            },
            "cpr_type": "NARROW",
        },
    )
    msg_narrow = render_auto_alert(alert_narrow, in_market=True)
    assert "CPR:" in msg_narrow
    assert "NARROW" in msg_narrow
    assert "Trend Expansion" in msg_narrow
    assert "24,100" in msg_narrow

    # Case B: Wide CPR Alert
    alert_wide = make_alert(
        alert_id="aa-tg-wide-20261028",
        symbol="BANKNIFTY",
        alert_type="INTRADAY_BREAKOUT_SPARK",
        direction="BULLISH",
        ltp=51200.0,
        trigger_level=51200.0,
        stop_loss=51000.0,
        target_level=51600.0,
        metrics={
            "cpr": {
                "pivot": 51100.0,
                "tc": 51300.0,
                "bc": 50900.0,
                "top": 51300.0,
                "bottom": 50900.0,
                "width_pct": 0.78,
                "cpr_type": "WIDE",
                "is_wide": True,
            },
            "cpr_type": "WIDE",
            "adr_exhaustion_pct": 74.0,
        },
    )
    msg_wide = render_auto_alert(alert_wide, in_market=True)
    assert "CPR:" in msg_wide
    assert "WIDE" in msg_wide
    assert "Chop Containment" in msg_wide
    assert "ADR: 74%" in msg_wide


def test_detector_cpr_overhead_gates_invariants():
    """Verify ORB and Intraday Spark detectors respect CPR resistance and chop containment."""
    from engine.detectors.orb import detect_opening_range_breakout
    from engine.daily_levels import DailyLevels
    import pandas as pd

    # Synthetic 5m df
    times = pd.date_range("2026-10-28 09:15", periods=5, freq="5min", tz=IST)
    df_5m = pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0, 103.0, 104.0],
            "high": [102.0, 103.0, 104.0, 105.0, 106.0],
            "low": [99.0, 100.0, 101.0, 102.0, 103.0],
            "close": [101.0, 102.0, 103.0, 104.0, 105.5],
            "volume": [10000, 12000, 15000, 20000, 25000],
        },
        index=times,
    )

    # Case A: ORB breaking out into resting Wide CPR Top resistance -> VETOED
    wide_dl = DailyLevels(
        symbol="ORBCO",
        canonical_symbol="ORBCO",
        exchange="NSE",
        session_date="2026-10-28",
        pdh=108.0,
        pdl=95.0,
        pdc=100.0,
        cpr={
            "pivot": 100.0,
            "tc": 105.7,
            "bc": 94.3,
            "top": 105.7,
            "bottom": 94.3,
            "width_pct": 1.14,
            "is_wide": True,
            "is_narrow": False,
            "cpr_type": "WIDE",
        },
    )

    with patch("engine.daily_levels.get_daily_levels", return_value=wide_dl):
        # LTP = 105.5, CPR Top = 105.7 (within 0.4% resistance)
        alert_orb = detect_opening_range_breakout(
            symbol="ORBCO",
            df=df_5m,
            ltp=105.5,
            vwap=102.0,
            rvol=2.0,
            orb_levels=(105.0, 103.0, 2.0, 104.0),
            ignore_time_gate=True,
        )
        assert alert_orb is None, (
            "Expected ORB breakout directly into Wide CPR Top to be suppressed"
        )

    # Case B: ORB with Narrow CPR -> PASSES with CPR in metrics
    narrow_dl = DailyLevels(
        symbol="ORBCO",
        canonical_symbol="ORBCO",
        exchange="NSE",
        session_date="2026-10-28",
        pdh=102.0,
        pdl=98.0,
        pdc=100.0,
        cpr={
            "pivot": 100.0,
            "tc": 100.1,
            "bc": 99.9,
            "top": 100.1,
            "bottom": 99.9,
            "width_pct": 0.20,
            "is_wide": False,
            "is_narrow": True,
            "cpr_type": "NARROW",
        },
    )

    with patch("engine.daily_levels.get_daily_levels", return_value=narrow_dl):
        alert_orb_pass = detect_opening_range_breakout(
            symbol="ORBCO",
            df=df_5m,
            ltp=105.5,
            vwap=102.0,
            rvol=2.0,
            orb_levels=(105.0, 103.0, 2.0, 104.0),
            ignore_time_gate=True,
        )
        assert alert_orb_pass is not None
        assert alert_orb_pass.metrics["cpr_type"] == "NARROW"
        assert alert_orb_pass.metrics["is_narrow_cpr"] is True


def test_agent_daily_levels_tool():
    """Verify agent/tools.py registers get_daily_reference_levels and returns CPR data."""
    from agent.tools import build_registry
    from engine.daily_levels import DailyLevels

    reg = build_registry()
    assert "get_daily_reference_levels" in reg._tools
    tool_info = reg._tools["get_daily_reference_levels"]
    assert tool_info["is_read_only"] is True

    mock_dl = DailyLevels(
        symbol="NIFTY",
        canonical_symbol="NIFTY",
        exchange="NSE",
        session_date="2026-10-28",
        pdh=24200.0,
        pdl=24000.0,
        pdc=24100.0,
        spot=24150.0,
        cpr={
            "pivot": 24100.0,
            "tc": 24120.0,
            "bc": 24080.0,
            "width_pct": 0.16,
            "cpr_type": "NARROW",
        },
    )

    with patch("engine.daily_levels.get_daily_levels", return_value=mock_dl):
        res = tool_info["fn"]("NIFTY")
        assert res["symbol"] == "NIFTY"
        assert res["cpr"]["pivot"] == 24100.0
        assert res["cpr"]["cpr_type"] == "NARROW"


def test_options_momentum_cpr_invariants():
    """Verify options_momentum strictly vetoes setups trapped inside Wide CPR core."""
    from engine.detectors.options_momentum import detect_options_momentum_breakouts
    from engine.daily_levels import DailyLevels

    mock_quote = MagicMock()
    mock_quote.last_price = 24100.0
    mock_quote.open = 24100.0
    mock_quote.high = 24150.0
    mock_quote.low = 24050.0
    mock_quote.close = 24100.0
    mock_quote.change_pct = 0.5
    mock_quote.vwap = 24090.0

    mock_contract = MagicMock()
    mock_contract.strike = 24100.0
    mock_contract.option_type = "CE"
    mock_contract.last_price = 120.0
    mock_contract.volume = 50000
    mock_contract.oi = 30000
    mock_contract.oi_change = 5000
    mock_contract.pchange = 15.0
    mock_contract.bid = 119.5
    mock_contract.ask = 120.5
    mock_contract.symbol = "NIFTY24OCT24100CE"
    mock_contract.expiry = "2026-10-29"

    wide_dl = DailyLevels(
        symbol="NIFTY",
        canonical_symbol="NIFTY",
        exchange="NSE",
        session_date="2026-10-28",
        pdh=24250.0,
        pdl=23950.0,
        pdc=24100.0,
        cpr={
            "pivot": 24100.0,
            "tc": 24200.0,
            "bc": 24000.0,
            "top": 24200.0,
            "bottom": 24000.0,
            "width_pct": 0.83,
            "is_wide": True,
            "is_narrow": False,
            "cpr_type": "WIDE",
        },
    )

    # When spot (24100.0) is trapped inside Wide CPR core [24000 - 24200]
    with patch("market.options.get_options_chain", return_value=[mock_contract]):
        with patch(
            "market.quotes.get_quote", return_value={"NSE:NIFTY": mock_quote, "NIFTY": mock_quote}
        ):
            with patch("market.history.get_ohlcv", return_value=None):
                with patch("engine.daily_levels.get_daily_levels", return_value=wide_dl):
                    alerts = detect_options_momentum_breakouts(
                        targets=["NIFTY"],
                        now_dt=datetime(2026, 10, 28, 10, 0, tzinfo=IST),
                    )
                    assert len(alerts) == 0, (
                        "Expected Options Momentum CE to be strictly vetoed inside Wide CPR core"
                    )


def test_afternoon_thrust_and_opening_drive_cpr_invariants():
    """Verify afternoon_thrust and opening_drive veto breakout chasing inside Wide CPR."""
    from engine.detectors.afternoon_thrust import detect_afternoon_thrust
    from engine.detectors.opening_drive import detect_opening_drive
    from engine.daily_levels import DailyLevels
    import pandas as pd

    wide_dl = DailyLevels(
        symbol="NIFTY",
        canonical_symbol="NIFTY",
        exchange="NSE",
        session_date="2026-10-28",
        pdh=24250.0,
        pdl=23950.0,
        pdc=24100.0,
        cpr={
            "pivot": 24100.0,
            "tc": 24200.0,
            "bc": 24000.0,
            "top": 24200.0,
            "bottom": 24000.0,
            "width_pct": 0.83,
            "is_wide": True,
            "is_narrow": False,
            "cpr_type": "WIDE",
        },
    )

    # 1. Afternoon Thrust: Trapped inside Wide CPR core
    df_pm = pd.DataFrame(
        {
            "open": [24080.0, 24090.0, 24095.0, 24100.0],
            "high": [24095.0, 24105.0, 24105.0, 24110.0],
            "low": [24075.0, 24085.0, 24090.0, 24095.0],
            "close": [24090.0, 24100.0, 24100.0, 24105.0],
            "volume": [1000, 1200, 1500, 2000],
        },
        index=pd.date_range("2026-10-28 13:30", periods=4, freq="5min", tz=IST),
    )

    with patch("engine.daily_levels.get_daily_levels", return_value=wide_dl):
        at_alert = detect_afternoon_thrust(
            symbol="NIFTY",
            df_5m=df_pm,
            ltp=24105.0,
            vwap=24090.0,
            rvol=1.5,
            day_high=24110.0,
            day_low=24000.0,
            ignore_time_gate=True,
        )
        assert at_alert is None, "Expected Afternoon Thrust to be vetoed inside Wide CPR core"

    # 2. Opening Drive: Trapped inside Wide CPR core
    df_am = pd.DataFrame(
        {
            "open": [24050.0, 24060.0, 24070.0],
            "high": [24080.0, 24090.0, 24100.0],
            "low": [24050.0, 24060.0, 24070.0],
            "close": [24075.0, 24085.0, 24095.0],
            "volume": [5000, 6000, 8000],
        },
        index=pd.date_range("2026-10-28 09:15", periods=3, freq="5min", tz=IST),
    )

    with patch("engine.daily_levels.get_daily_levels", return_value=wide_dl):
        od_alert = detect_opening_drive(
            symbol="NIFTY",
            df_5m=df_am,
            ltp=24095.0,
            vwap=24080.0,
            rvol=2.0,
            ignore_time_gate=True,
        )
        assert od_alert is None, "Expected Opening Drive to be vetoed inside Wide CPR core"


def test_smt_sweep_cpr_invariants():
    """Verify smt_sweep detects CPR_TOP_CONFLUENCE and vetoes false sweeps inside Wide CPR."""
    from engine.detectors.smt_sweep import detect_smt_sweep
    from engine.smt_divergence import SMTDivergenceResult
    from engine.daily_levels import DailyLevels

    mock_pe = MagicMock()
    mock_pe.strike = 24200.0
    mock_pe.option_type = "PE"
    mock_pe.last_price = 150.0
    mock_pe.symbol = "NIFTY24OCT24200PE"

    wide_dl = DailyLevels(
        symbol="NIFTY",
        canonical_symbol="NIFTY",
        exchange="NSE",
        session_date="2026-10-28",
        pdh=24250.0,
        pdl=23950.0,
        pdc=24100.0,
        cpr={
            "pivot": 24000.0,
            "tc": 24200.0,
            "bc": 23800.0,
            "top": 24200.0,
            "bottom": 23800.0,
            "width_pct": 1.66,
            "is_wide": True,
            "is_narrow": False,
            "cpr_type": "WIDE",
        },
    )

    mock_smt_res = SMTDivergenceResult(
        has_divergence=True,
        is_trap=True,
        divergence_type="BEARISH_DIVERGENCE_BULL_TRAP",
        primary_symbol="NIFTY",
        sibling_symbol="BANKNIFTY",
        rationale="NIFTY swept high while BANKNIFTY lagged below VWAP",
        sibling_spot=52000.0,
        sibling_vwap=52100.0,
    )

    # Spot swept Day High at 24200.0 coinciding with CPR Top
    with patch("engine.daily_levels.get_daily_levels", return_value=wide_dl):
        with patch("engine.detectors.smt_sweep.evaluate_smt_divergence", return_value=mock_smt_res):
            alerts = detect_smt_sweep(
                underlying="NIFTY",
                spot=24200.0,
                chain=[mock_pe],
                vwap=24150.0,
                day_high=24200.0,
                day_low=23900.0,
                ignore_time_gate=True,
            )
            assert len(alerts) >= 1
            a = alerts[0]
            assert "CPR_TOP_CONFLUENCE" in a.metrics["signals"]
            assert a.metrics["cpr_type"] == "WIDE"
            assert a.metrics["smart_money_score"] >= 95
