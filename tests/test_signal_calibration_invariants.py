"""
tests/test_signal_calibration_invariants.py
───────────────────────────────────────────
Deterministic test suite verifying the empirical signal calibration invariants:
  1. AutoAlert symbol normalization (Rule 17).
  2. Verified RVOL Sector Leader promotion (no default 1.0x ties).
  3. Index Directional Hysteresis (20m anti-flip lockout).
  4. Dynamic Volatility SL Floor (1.20x 5m ATR).
  5. Midday Compression synchronization in trend continuation.
"""

import os
import time
from datetime import datetime, time as dtime, timedelta

from engine.alert_model import AutoAlert
from engine.alert_factory import AlertFactory
from engine.auto_alert_engine import AutoAlertEngine
from engine.alert_scrutiny import AlertScrutinyAuditor


def test_auto_alert_symbol_canonicalization_rule_17():
    """Rule 17: AutoAlert.__post_init__ must unconditionally strip exchange prefixes."""
    for prefix, sym in [
        ("NSE:", "LT"),
        ("BSE:", "TCS"),
        ("NFO:", "BANKNIFTY"),
        ("MCX:", "CRUDEOIL"),
    ]:
        alert = AutoAlert(
            alert_id=f"aa-test-{sym.lower()}-01",
            alert_type="PREDATOR_SWEEP",
            stage="IGNITED",
            symbol=f"{prefix}{sym}",
            exchange="NSE",
            direction="BULLISH",
            headline=f"{sym} Test",
            summary="Prefix stripping test",
            ltp=1000.0,
            trigger_level=1000.0,
            target_level=1050.0,
            stop_loss=980.0,
        )
        assert alert.symbol == sym, f"Failed for {prefix}{sym}: got {alert.symbol}"


def test_unverified_rvol_does_not_supersede_sector_leader():
    """Flaw 4: Two unverified default 1.0x RVOL alerts must NEVER supersede an active sector leader."""
    from unittest.mock import patch

    with patch("engine.alerts._is_market_hours", return_value=True):
        engine = AutoAlertEngine()
        engine._alerts.clear()

        # Active Leader 1 (e.g. TCS) with default metrics
        leader_1 = AutoAlert(
            alert_id="aa-test-tcs-01",
            alert_type="TREND_DAY_PULLBACK",
            stage="IGNITED",
            symbol="TCS",
            exchange="NSE",
            direction="BEARISH",
            headline="TCS Trend Pullback",
            summary="Testing leader 1",
            ltp=4000.0,
            trigger_level=4000.0,
            target_level=3900.0,
            stop_loss=4050.0,
            confidence=82,
            metrics={"sector_id": "IT", "is_sector_leader": True},
            is_live=True,
        )
        res1 = engine.record_alert(leader_1)
        assert res1 is True
        assert leader_1.is_archived is False

        # Incoming Candidate 2 (e.g. TECHM) with confidence 85 but NO verified RVOL (both default 1.0x)
        candidate_2 = AutoAlert(
            alert_id="aa-test-techm-02",
            alert_type="TREND_DAY_PULLBACK",
            stage="IGNITED",
            symbol="TECHM",
            exchange="NSE",
            direction="BEARISH",
            headline="TECHM Trend Pullback",
            summary="Testing leader 2 without RVOL",
            ltp=1500.0,
            trigger_level=1500.0,
            target_level=1450.0,
            stop_loss=1520.0,
            confidence=85,
            metrics={"sector_id": "IT"},
            is_live=True,
        )
        # Because candidate_2 lacks verified RVOL (default 1.0x), it must NOT archive leader_1
        _ = engine.record_alert(candidate_2)
        assert leader_1.is_archived is False
        assert "Superseded" not in str(leader_1.archive_reason or "")


def test_index_directional_hysteresis_suppresses_rapid_flip():
    """Flaw 1: Index directional hysteresis blocks opposing flip within 20m without confirmed CHoCH."""
    from unittest.mock import patch

    with patch("engine.alerts._is_market_hours", return_value=True):
        engine = AutoAlertEngine()
        engine._alerts.clear()

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")

        # 1. First alert: BANKNIFTY BULLISH CE
        alert_ce = AutoAlert(
            alert_id="aa-bn-ce-01",
            alert_type="GAMMA_BLAST",
            stage="EARLY_WARNING",
            symbol="BANKNIFTY",
            exchange="NSE",
            direction="BULLISH",
            headline="BANKNIFTY 54800 CE",
            summary="Bullish setup",
            ltp=54800.0,
            trigger_level=54800.0,
            target_level=55200.0,
            stop_loss=54600.0,
            confidence=85,
            created_at=now_str,
            is_live=True,
        )
        res_ce = engine.record_alert(alert_ce)
        assert res_ce is True

        # 2. Opposing alert: BANKNIFTY BEARISH PE arrives 5 minutes later without CHoCH
        five_mins_later = (datetime.now() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S IST")
        alert_pe = AutoAlert(
            alert_id="aa-bn-pe-02",
            alert_type="GAMMA_BLAST",
            stage="IGNITED",
            symbol="BANKNIFTY",
            exchange="NSE",
            direction="BEARISH",
            headline="BANKNIFTY 54800 PE",
            summary="Bearish flip without CHoCH",
            ltp=54790.0,
            trigger_level=54790.0,
            target_level=54400.0,
            stop_loss=55000.0,
            confidence=88,  # Higher score alone must not cause a flip
            created_at=five_mins_later,
            metrics={"rvol": 1.2},
            is_live=True,
        )

        res_pe = engine.record_alert(alert_pe)
        # Opposing alert must be suppressed due to 20m hysteresis lock!
        assert res_pe is False
        assert alert_ce.is_invalidated is False


def test_scrutiny_rejects_sub_atr_noise_whipsaw():
    """Flaw 2: Tier-1 Scrutiny must reject equity and option SL narrower than 1.20x 5m ATR."""
    auditor = AlertScrutinyAuditor()

    # Alert with tight SL (10 pts) vs 5m ATR (15 pts) -> SL distance 10 pts < 1.20x ATR (18 pts)
    tight_sl_alert = AutoAlert(
        alert_id="aa-sub-atr-test-01",
        alert_type="ORB_BREAKOUT",
        stage="IGNITED",
        symbol="RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="RELIANCE Breakout",
        summary="Tight SL test",
        ltp=2800.0,
        trigger_level=2800.0,
        target_level=2850.0,
        stop_loss=2790.0,  # 10 pts risk
        metrics={"rvol": 1.8, "atr_5m": 15.0},
        environment="LIVE",
        is_live=True,
    )

    passed, reason, _ = auditor.verify_tier1_sanity(tight_sl_alert)
    assert passed is False
    assert "Sub-ATR Equity Noise Trap" in reason
    assert "1.20x 5m ATR" in reason


def test_midday_trend_pullback_runway_exemption():
    """Verify that TREND_DAY_PULLBACK is exempted from the 1.8x breakout volume floor during midday compression (11:00-13:15)."""
    import os
    from engine.session_runway import evaluate_session_runway

    midday_dt = datetime(2026, 10, 22, 12, 29)
    # Ensure live runway rules are tested
    orig_force = os.environ.get("FORCE_RUNWAY_CHECK")
    os.environ["FORCE_RUNWAY_CHECK"] = "1"
    try:
        # Standard breakout chase should be vetoed with 1.1x RVOL
        res_breakout = evaluate_session_runway(
            symbol="TECHM",
            alert_type="MOMENTUM_BREAKOUT",
            time_horizon="INTRADAY",
            segment="FNO_STOCK",
            rvol=1.10,
            now_dt=midday_dt,
        )
        assert res_breakout.is_allowed is False
        assert "Midday Compression Lull" in res_breakout.veto_reason

        # TREND_DAY_PULLBACK is an equilibrium retest and must pass with 1.1x RVOL
        res_pullback = evaluate_session_runway(
            symbol="TECHM",
            alert_type="TREND_DAY_PULLBACK",
            time_horizon="INTRADAY",
            segment="FNO_STOCK",
            rvol=1.10,
            now_dt=midday_dt,
        )
        assert res_pullback.is_allowed is True, (
            f"TREND_DAY_PULLBACK was unexpectedly vetoed: {res_pullback.veto_reason}"
        )

        # Defined-risk hedged spread must pass with 1.1x RVOL
        res_spread = evaluate_session_runway(
            symbol="TECHM",
            alert_type="MOMENTUM_BREAKOUT",
            time_horizon="INTRADAY",
            segment="FNO_STOCK",
            rvol=1.10,
            now_dt=midday_dt,
            is_hedged_spread=True,
        )
        assert res_spread.is_allowed is True, "Defined-risk hedged spread was unexpectedly vetoed"
    finally:
        if orig_force is not None:
            os.environ["FORCE_RUNWAY_CHECK"] = orig_force
        else:
            del os.environ["FORCE_RUNWAY_CHECK"]


def test_zero_ghost_cancelled_alert_telegram_suppression():
    """Zero-Ghost Invariant: Disqualified / Cancelled alerts must NEVER be dispatched to Telegram if initial call was not dispatched."""
    from unittest.mock import MagicMock, patch
    from engine.auto_alert_engine import AutoAlertEngine
    from engine.alert_model import AutoAlert

    engine = AutoAlertEngine()
    engine._alerts = []

    mock_send = MagicMock()
    with (
        patch("engine.alerts._telegram_notify", mock_send),
        patch("engine.alerts._is_market_hours", return_value=True),
        patch("engine.alert_preferences.alert_preferences.is_alert_allowed", return_value=True),
    ):
        # Case A: Alert was NEVER sent to Telegram (telegram_dispatched == False)
        alert_unsent = AutoAlert(
            alert_id="aa-ghost-suppress-1-20261022",
            alert_type="TREND_DAY_PULLBACK",
            stage="CANCELLED",
            target_status="SETUP_DISQUALIFIED",
            symbol="TECHM",
            exchange="NSE",
            direction="BEARISH",
            headline="🛡️ PRE-TRADE VETO: TECHM",
            summary="Midday compression veto",
            ltp=28.15,
            trigger_level=28.15,
            stop_loss=23.45,
            target_level=34.90,
            confidence=90,
            telegram_dispatched=False,
            is_live=True,
            environment="LIVE",
        )
        engine._dispatch(alert_unsent)
        assert mock_send.call_count == 0, (
            "Ghost cancellation alert was dispatched to Telegram even though initial call was never sent!"
        )

        # Case B: Alert WAS sent to Telegram earlier (telegram_dispatched == True, telegram_root_message_id set)
        alert_sent = AutoAlert(
            alert_id="aa-ghost-threaded-2-20261022",
            alert_type="TREND_DAY_PULLBACK",
            stage="CANCELLED",
            target_status="SETUP_DISQUALIFIED",
            symbol="TECHM",
            exchange="NSE",
            direction="BEARISH",
            headline="🛡️ PRE-TRADE VETO: TECHM",
            summary="Pre-trade veto",
            ltp=28.15,
            trigger_level=28.15,
            stop_loss=23.45,
            target_level=34.90,
            confidence=90,
            telegram_dispatched=True,
            telegram_root_message_id=999888,
            is_live=True,
            environment="LIVE",
        )
        engine._dispatch(alert_sent)
        assert mock_send.call_count == 1, (
            "Threaded cancellation update was not dispatched to Telegram for active subscriber trade!"
        )
        # Verify reply_to_message_id is threaded under root message ID
        _, kwargs = mock_send.call_args
        assert kwargs.get("reply_to_message_id") == 999888, (
            "Cancellation update was not threaded as a reply to the root message!"
        )


def test_index_back_to_back_strike_stacking_mutex():
    """
    Empirical Invariant: Prevent back-to-back index option strike churn.
    1. If BankNifty 54800 CE is active/ignited, incoming 54900 CE must be suppressed.
    2. After 54800 CE exits, incoming 54900 CE or 55100 CE within 15 minutes must be suppressed.
    """
    from unittest.mock import patch
    import os
    from config.constants import IST

    now = datetime.now(IST)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S IST")

    with patch("engine.alerts._is_market_hours", return_value=True):
        engine = AutoAlertEngine()
        engine._alerts.clear()

        # 1. Primary active trade: BANKNIFTY 54800 CE (IGNITED)
        bn_54800 = AutoAlert(
            alert_id="aa-index-call-setup-banknifty-ce-54800-0915-20261022",
            alert_type="INDEX_CALL_SETUP",
            stage="IGNITED",
            symbol="BANKNIFTY",
            exchange="NFO",
            direction="BULLISH",
            headline="BANKNIFTY 54800 CE Ignited",
            summary="BankNifty momentum surge",
            ltp=530.0,
            trigger_level=530.0,
            stop_loss=450.0,
            target_level=690.0,
            strike=54800.0,
            option_type="CE",
            contract_symbol="BANKNIFTY26OCT54800CE",
            created_at=now_str,
            confidence=88,
            is_live=True,
            environment="LIVE",
        )
        res_primary = engine.record_alert(bn_54800)
        assert res_primary is True
        assert bn_54800 in engine._alerts

        # 2. While 54800 CE is active, incoming 54900 CE arrives (e.g. 5 minutes later as spot moves up)
        bn_54900_active = AutoAlert(
            alert_id="aa-index-call-setup-banknifty-ce-54900-0915-20261022",
            alert_type="INDEX_CALL_SETUP",
            stage="IGNITED",
            symbol="BANKNIFTY",
            exchange="NFO",
            direction="BULLISH",
            headline="BANKNIFTY 54900 CE Ignited",
            summary="BankNifty momentum continuation",
            ltp=490.0,
            trigger_level=490.0,
            stop_loss=410.0,
            target_level=650.0,
            strike=54900.0,
            option_type="CE",
            contract_symbol="BANKNIFTY26OCT54900CE",
            created_at=now_str,
            confidence=86,
            is_live=True,
            environment="LIVE",
        )
        # Must be suppressed by 1b consolidation and registered under related_strikes
        res_competing = engine.record_alert(bn_54900_active)
        assert res_competing is False
        assert "BANKNIFTY26OCT54900CE" in (bn_54800.metrics or {}).get("related_strikes", [])

        # 3. Simulate 54800 CE exiting (RUNNER_EXIT with breakeven stop locked)
        bn_54800.stage = "RUNNER_EXIT"
        bn_54800.target_status = "RUNNER_CLOSED"
        bn_54800.archived_at = now_str

        # 4. Immediate alternate strike 9 seconds after exit: must be suppressed by the 15-minute reset buffer
        bn_55100_premature = AutoAlert(
            alert_id="aa-index-call-setup-banknifty-ce-55100-0915-20261022",
            alert_type="INDEX_CALL_SETUP",
            stage="IGNITED",
            symbol="BANKNIFTY",
            exchange="NFO",
            direction="BULLISH",
            headline="BANKNIFTY 55100 CE Ignited",
            summary="BankNifty new strike trigger",
            ltp=450.0,
            trigger_level=450.0,
            stop_loss=380.0,
            target_level=590.0,
            strike=55100.0,
            option_type="CE",
            contract_symbol="BANKNIFTY26OCT55100CE",
            created_at=now_str,
            confidence=85,
            is_live=True,
            environment="LIVE",
        )
        with patch.dict(os.environ, {"CHANAKYA_TESTING": "0"}):
            res_premature = engine.record_alert(bn_55100_premature)
            assert res_premature is False, (
                "Cross-strike premature index re-entry was not suppressed!"
            )


def test_sub_atr_auto_calibration_and_factory_repair():
    """Verify that AlertFactory auto-calibrates sub-ATR stops to the volatility floor rather than dying."""
    # 1. Equity setup with sub-ATR stop (5 pts vs 15 pts 5m ATR)
    eq_alert = AlertFactory.create_equity_alert(
        alert_type="ORB_BREAKOUT",
        stage="IGNITED",
        symbol="RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="RELIANCE Breakout",
        summary="Auto-calibration test",
        ltp=2800.0,
        trigger_level=2800.0,
        target_level=2830.0,
        stop_loss=2795.0,  # 5 pts risk < 1.20x 5m ATR (18 pts)
        rvol=1.8,
        metrics={"atr_5m": 15.0},
    )
    # Stop-loss must be auto-expanded to 18 pts (2782.0) and target rebalanced to >= 1:2.0 R:R (>= 2836.0)
    assert eq_alert.stop_loss <= 2782.0
    assert eq_alert.target_level >= 2836.0
    assert (eq_alert.target_level - eq_alert.trigger_level) / (
        eq_alert.trigger_level - eq_alert.stop_loss
    ) >= 2.0

    # 2. Index option setup with tight stop (20 pts on SENSEX 250 CE)
    opt_alert = AlertFactory.create_option_alert(
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        underlying_symbol="SENSEX",
        contract_symbol="SENSEX26OCT80000CE",
        exchange="BFO",
        direction="BULLISH",
        strike=80000.0,
        option_type="CE",
        option_premium=250.0,
        option_trigger=250.0,
        option_target=320.0,
        option_sl=230.0,  # 20 pts risk < SENSEX 45.0 pt floor
        underlying_spot=80100.0,
        underlying_sl=79800.0,
        rvol=1.5,
        lot_size=10,
        headline="SENSEX 80000 CE Ignited",
        summary="SENSEX test",
    )
    # Tactical SL must be auto-calibrated to at least 45 pts away (<= 205.0)
    assert opt_alert.stop_loss <= 205.0
    assert opt_alert.target_level >= 340.0


def test_learning_engine_timeframe_aware_noise_attribution(tmp_path, monkeypatch):
    """Verify that LearningEngine does not misdiagnose valid 5m ATR stops as sub-ATR due to Daily ATR."""
    from engine.learning_engine import PatternLearningEngine

    mem_file = tmp_path / "pattern_memory.json"
    outcomes_file = tmp_path / "pattern_outcomes.json"
    pm_file = tmp_path / "invalidation_post_mortems.json"
    monkeypatch.setattr("engine.learning_engine.get_pattern_memory_file", lambda: mem_file)
    monkeypatch.setattr("engine.learning_engine.get_pattern_outcomes_file", lambda: outcomes_file)
    monkeypatch.setattr("engine.learning_engine.get_pattern_post_mortems_file", lambda: pm_file)

    eng = PatternLearningEngine()

    # Intraday alert with 20 pt stop and 15 pt 5m ATR on LTTS (Daily ATR is 165 pts!)
    alert = AutoAlert(
        alert_id="test-ltts-intraday",
        alert_type="INTRADAY_BREAKDOWN_SPARK",
        stage="IGNITED",
        symbol="LTTS",
        exchange="NSE",
        direction="BEARISH",
        headline="LTTS Breakdown",
        summary="Intraday breakdown",
        ltp=3848.0,
        trigger_level=3848.0,
        target_level=3780.0,
        stop_loss=3868.0,  # 20 pts risk >= 1.20x 5m ATR (18 pts)
        time_horizon="INTRADAY",
        metrics={"atr_5m": 15.0},
    )

    pm = eng.conduct_invalidation_post_mortem(alert, exit_price=3870.0)
    # Must NOT be classified as SUB_ATR_NOISE_WHIPSAW because 20 pts >= 1.20x 5m ATR (18 pts)
    assert pm.primary_failure_reason != "SUB_ATR_NOISE_WHIPSAW"
    assert "Stop-loss buffer" not in str(pm.missed_signals)


def test_afternoon_runner_bypasses_daily_stock_cap():
    """Verify that high-conviction afternoon runners (>=90%) bypass the exhausted morning stock daily cap."""
    from engine.auto_alert_engine import AutoAlertEngine
    from zoneinfo import ZoneInfo
    from unittest.mock import patch

    IST = ZoneInfo("Asia/Kolkata")
    engine = AutoAlertEngine()
    today_k = datetime.now(IST).strftime("%Y-%m-%d")

    # Simulate 46 total stock alerts fired in the morning, exceeding the 32 cap
    engine._sector_daily_telegram[today_k]["it"] = 20
    engine._sector_daily_telegram[today_k]["banking"] = 26

    # Trent triggered at 13:55 IST with confidence 92
    afternoon_ts = datetime.combine(
        datetime.now(IST).date(),
        dtime(13, 55, 0),
        tzinfo=IST,
    ).timestamp()

    alert_trent = AutoAlert(
        alert_id="aa-afternoon-thrust-trent-bear-1315-20261022",
        alert_type="AFTERNOON_THRUST",
        stage="IGNITED",
        symbol="TRENT",
        exchange="NSE",
        direction="BEARISH",
        headline="⚡ TRENT PE SETUP",
        summary="Afternoon thrust runner",
        ltp=18.70,
        trigger_level=18.70,
        target_level=23.19,
        stop_loss=14.59,
        confidence=92,
        is_live=True,
        environment="LIVE",
        segment="FNO_STOCK",
        option_type="PE",
        strike=2750.0,
        metrics={"sector_id": "retail", "spot": 2750.0},
    )

    with patch.dict(os.environ, {"TELEGRAM_MAX_STOCKS_PER_DAY": "32"}):
        passed, reason = engine._eval_telegram_apex_gate(
            alert_trent, now_ts=afternoon_ts, in_market=True
        )
        assert passed is True, f"Trent was unexpectedly throttled: {reason}"


def test_index_derivative_exempt_from_broad_market_cash_equity_sector_hourly():
    """Verify that Index options (BANKNIFTY) are exempt from Cash Equity sector hourly pacing."""
    from engine.auto_alert_engine import AutoAlertEngine

    engine = AutoAlertEngine()
    now_ts = time.time()

    # Fill cash equity broad market sector hourly to the max (6/6)
    engine._sector_hourly_telegram["eq:broad_market"] = [
        now_ts - 500,
        now_ts - 400,
        now_ts - 300,
        now_ts - 200,
        now_ts - 100,
        now_ts - 50,
    ]

    # BankNifty 55000 PE
    alert_bn = AutoAlert(
        alert_id="aa-gamma-blast-banknifty-pe-55000-1315-20261022",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="BANKNIFTY",
        exchange="NFO",
        direction="BEARISH",
        headline="⚡ BANKNIFTY 55000 PE",
        summary="Institutional breakdown",
        ltp=210.0,
        trigger_level=210.0,
        target_level=310.0,
        stop_loss=175.0,
        confidence=98,
        is_live=True,
        environment="LIVE",
        segment="FNO_INDEX",
        option_type="PE",
        strike=55000.0,
        metrics={"spot": 54800.0, "vwap": 54900.0, "rvol": 2.5},
    )

    passed, reason = engine._eval_telegram_apex_gate(alert_bn, now_ts=now_ts, in_market=True)
    assert passed is True, f"BankNifty was unexpectedly throttled by Cash Equity sector: {reason}"


def test_fno_stock_options_permitted_until_1445():
    """Verify that F&O stock options remain active past 14:00 (until 14:45), while cash equity is stopped at 14:00."""
    from engine.session_runway import evaluate_session_runway
    from zoneinfo import ZoneInfo

    IST = ZoneInfo("Asia/Kolkata")
    pm_time = datetime.combine(datetime.now(IST).date(), dtime(14, 15, 0), tzinfo=IST)

    from unittest.mock import patch

    with patch.dict(os.environ, {"FORCE_RUNWAY_CHECK": "1"}):
        # 1. Cash Equity at 14:15 -> Must be vetoed (14:00 hard cutoff)
        res_cash = evaluate_session_runway(
            symbol="RELIANCE",
            alert_type="MOMENTUM_BREAKOUT",
            time_horizon="INTRADAY",
            segment="EQUITY",
            rvol=2.0,
            now_dt=pm_time,
        )
        assert res_cash.is_allowed is False
        assert "cash equity entries silenced after 14:00 IST" in res_cash.veto_reason

        # 2. F&O Stock Option at 14:15 -> Must be allowed (valid until 14:45)
        res_fno = evaluate_session_runway(
            symbol="TRENT",
            alert_type="AFTERNOON_THRUST",
            time_horizon="INTRADAY",
            segment="FNO_STOCK",
            rvol=2.0,
            now_dt=pm_time,
        )
        assert res_fno.is_allowed is True, (
            f"F&O stock option was unexpectedly vetoed at 14:15: {res_fno.veto_reason}"
        )

        # 3. F&O Stock Option at 14:46 -> Must be vetoed
        late_time = datetime.combine(datetime.now(IST).date(), dtime(14, 46, 0), tzinfo=IST)
        res_fno_late = evaluate_session_runway(
            symbol="TRENT",
            alert_type="AFTERNOON_THRUST",
            time_horizon="INTRADAY",
            segment="FNO_STOCK",
            rvol=2.0,
            now_dt=late_time,
        )
        assert res_fno_late.is_allowed is False
        assert "silenced after 14:45 IST" in res_fno_late.veto_reason


def test_midday_compression_rvol_floor_allows_130_breakout():
    """Verify that Time-of-Day adjusted 1.30x RVOL passes during midday compression (11:00-13:15)."""
    from engine.session_runway import evaluate_session_runway
    from zoneinfo import ZoneInfo
    from unittest.mock import patch

    IST = ZoneInfo("Asia/Kolkata")
    midday_dt = datetime.combine(datetime.now(IST).date(), dtime(12, 15, 0), tzinfo=IST)

    with patch.dict(os.environ, {"FORCE_RUNWAY_CHECK": "1"}):
        # 1.35x RVOL breakout (e.g. Squeeze Breakout or Predator Sweep) should pass with 1.30x floor
        res = evaluate_session_runway(
            symbol="ASIANPAINT",
            alert_type="SQUEEZE_BREAKOUT",
            time_horizon="INTRADAY",
            segment="FNO_STOCK",
            rvol=1.35,
            now_dt=midday_dt,
        )
        assert res.is_allowed is True, f"Midday breakout was unexpectedly vetoed: {res.veto_reason}"

        # Very thin volume (<1.30x) still correctly vetoes
        res_thin = evaluate_session_runway(
            symbol="ASIANPAINT",
            alert_type="SQUEEZE_BREAKOUT",
            time_horizon="INTRADAY",
            segment="FNO_STOCK",
            rvol=1.10,
            now_dt=midday_dt,
        )
        assert res_thin.is_allowed is False
        assert "Midday Compression Lull" in res_thin.veto_reason


def test_eod_postmortem_triggers_market_mover_learning():
    """Verify that run_eod_alert_postmortems invokes scan_and_learn_from_market_movers."""
    from unittest.mock import patch, MagicMock
    from engine.alert_postmortem_runner import run_eod_alert_postmortems

    mock_engine = MagicMock()
    mock_engine._alerts = []

    with patch(
        "engine.alert_postmortem_runner.pattern_learning_engine.scan_and_learn_from_market_movers"
    ) as mock_learn:
        mock_learn.return_value = ["fingerprint1", "fingerprint2"]
        report = run_eod_alert_postmortems(auto_engine=mock_engine, force=True)
        assert mock_learn.called
        assert report.get("learned_movers_count") == 2
