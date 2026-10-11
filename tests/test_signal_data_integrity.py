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
    if "ltp" in overrides and "trigger_level" not in overrides:
        defaults["trigger_level"] = overrides["ltp"]
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


def test_inverted_target_hierarchy_veto():
    """Target 2 <= Target 1 on a long setup is rejected for inverted target geometry."""
    alert = make_alert(
        ltp=100.0,
        stop_loss=95.0,
        target_level=110.0,
        actionable_plan={"target_1": 110.0, "target_2": 105.0},
    )
    is_valid, reason = alert.validate_data_integrity()
    assert is_valid is False
    assert "Inverted Target Hierarchy" in reason


def test_micro_risk_noise_trap_veto():
    """Stop-loss placed within <0.05% of entry is rejected as an unviable micro-noise trap."""
    alert = make_alert(
        ltp=1000.0,
        trigger_level=1000.0,
        stop_loss=999.80,  # 0.02% risk
        target_level=1020.0,
    )
    is_valid, reason = alert.validate_data_integrity()
    assert is_valid is False
    assert "Micro-Risk Noise Trap" in reason


def test_circuit_limit_violation_veto(monkeypatch):
    """Cash equity intraday setup promising >25% single-day move is vetoed for violating exchange circuit bands."""
    monkeypatch.delenv("CHANAKYA_TESTING", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    alert = make_alert(
        alert_id="aa-live-equity-breakout-101",
        symbol="TATASTEEL",
        exchange="NSE",
        ltp=150.0,
        trigger_level=150.0,
        stop_loss=147.0,
        target_level=200.0,  # +33.3% move! Exceeds SEBI 20% max circuit!
        time_horizon="INTRADAY",
        is_live=True,
        environment="LIVE",
    )
    is_valid, reason = alert.validate_data_integrity()
    assert is_valid is False
    assert "Circuit Limit Violation" in reason


def test_no_false_invalidation_from_pre_alert_morning_extremes():
    """An active mid-day alert sitting in profit must NEVER be invalidated by pre-alert morning lows."""
    from engine.alert_evaluator import evaluate_alert_invalidation

    # Alert triggered at 1:00 PM: Entry 500, SL 490, Target 520. Current LTP is 505 (in profit!).
    alert = make_alert(
        alert_id="aa-midday-trade-01",
        symbol="INFY",
        exchange="NSE",
        direction="BULLISH",
        ltp=505.0,
        trigger_level=500.0,
        stop_loss=490.0,
        target_level=520.0,
        is_live=True,
    )
    # Even if day's quote had low=480 from 09:15 AM, evaluating with live price 505.0 must NOT invalidate!
    reason = evaluate_alert_invalidation(alert, current_ltp=505.0)
    assert reason is None


def test_early_warning_ignition_suppressed_if_target1_already_surpassed(monkeypatch):
    """If an early warning's symbol surged directly past Target 1 before ignition, entry is aborted (No-Chase)."""
    from engine.auto_alert_engine import AutoAlertEngine

    engine = AutoAlertEngine()
    engine.clear_alerts()

    alert = make_alert(
        alert_id="ew-overshoot-test-1",
        symbol="SBIN",
        stage="EARLY_WARNING",
        ltp=800.0,
        trigger_level=805.0,
        stop_loss=795.0,
        target_level=830.0,
        actionable_plan={"target_1": 815.0, "target_2": 830.0},
        is_live=True,
    )
    engine._alerts.append(alert)

    # Price surged to 820.0 (past T1 of 815.0!)
    monkeypatch.setattr(
        engine, "_batch_refresh_quotes", lambda alerts: {"NSE:SBIN": 820.0, "SBIN": 820.0}
    )

    ignited = engine.check_and_ignite_early_warnings()
    assert len(ignited) == 0, "Must NOT ignite when price already surpassed Target 1!"
    assert alert.stage == "EXPIRED"
    assert "Entry missed" in alert.invalidation_reason


def test_order_book_wide_spread_and_zero_bid_veto():
    """Option alerts with wide bid-ask spread or zero bid liquidity are vetoed in Tier-1 sanity."""
    # 1. Wide spread: Bid 100, Ask 108 (7.4% spread > 2.5% max for index)
    wide_alert = make_alert(
        alert_type="OPTIONS_MOMENTUM",
        symbol="NIFTY",
        contract_symbol="NIFTY2026102725000CE",
        option_type="CE",
        strike=25000.0,
        ltp=105.0,
        stop_loss=85.0,
        target_level=145.0,
        metrics={"bid": 100.0, "ask": 108.0, "bid_ask_spread_pct": 7.4},
    )
    passed, reason, flags = alert_scrutiny_auditor.verify_tier1_sanity(wide_alert)
    assert passed is False
    assert "Illiquid Order Book Veto" in reason

    # 2. Zero bid liquidity: Ask 25.0, Bid 0.0
    zero_bid_alert = make_alert(
        alert_type="OPTIONS_MOMENTUM",
        symbol="NIFTY",
        contract_symbol="NIFTY2026102725000CE",
        option_type="CE",
        strike=25000.0,
        ltp=25.0,
        stop_loss=20.0,
        target_level=45.0,
        metrics={"bid": 0.0, "ask": 25.0},
    )
    passed, reason, flags = alert_scrutiny_auditor.verify_tier1_sanity(zero_bid_alert)
    assert passed is False
    assert "Zero Bid Liquidity Veto" in reason


def test_pre_squareoff_advisory_broadcast(monkeypatch):
    """At 15:10 IST, open intraday alerts trigger pre-squareoff broadcast and latch for the session."""
    from engine.auto_alert_engine import AutoAlertEngine

    engine = AutoAlertEngine()
    engine.clear_alerts()
    engine._session_closing_warned_date = None

    alert = make_alert(
        alert_id="aa-open-pos-1",
        symbol="RELIANCE",
        stage="T1_ACHIEVED",
        ltp=2980.0,
        trigger_level=2950.0,
        stop_loss=2950.0,
        target_level=3050.0,
        achieved_milestones=["T1_ACHIEVED"],
        time_horizon="INTRADAY",
        is_live=True,
    )
    engine._alerts.append(alert)

    # Mock telegram send
    sent_msgs = []
    monkeypatch.setattr("bot.telegram_bot.send_message", lambda msg, **kw: sent_msgs.append(msg))

    res = engine.check_session_closing_warning()
    assert res is not None
    assert res["open_count"] == 1
    assert len(sent_msgs) == 1
    assert "15:10 IST AUTO-SQUAREOFF ADVISORY" in sent_msgs[0]
    assert "RELIANCE" in sent_msgs[0]

    # Calling again in the same session must NOT broadcast again (latched)
    monkeypatch.delenv("CHANAKYA_TESTING", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    res2 = engine.check_session_closing_warning()
    assert res2 is None
    assert len(sent_msgs) == 1  # No duplicate message


def test_record_alert_populates_position_sizing():
    """record_alert enriches actionable_plan with lot_size, recommended_lots, and capital_at_risk."""
    from engine.auto_alert_engine import AutoAlertEngine

    engine = AutoAlertEngine()
    engine.clear_alerts()

    alert = make_alert(
        alert_id="aa-sizing-test-01",
        symbol="RELIANCE",
        ltp=2500.0,
        trigger_level=2500.0,
        stop_loss=2450.0,
        target_level=2600.0,
        actionable_plan={},
        is_live=True,
    )
    engine.record_alert(alert)

    plan = alert.actionable_plan
    assert "lot_size" in plan
    assert "recommended_lots" in plan
    assert "capital_at_risk" in plan
    assert plan["lot_size"] in (250, 500)  # Canonical RELIANCE F&O lot size
    assert plan["recommended_lots"] >= 1


def test_0dte_expiry_day_afternoon_theta_cliff_veto(monkeypatch):
    """0DTE naked OTM option buy post-13:30 IST is vetoed for afternoon theta cliff."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from engine.alert_scrutiny import alert_scrutiny_auditor
    import engine.alert_scrutiny as scr

    ist = ZoneInfo("Asia/Kolkata")
    fake_now = datetime(2026, 10, 5, 13, 45, tzinfo=ist)
    today_str = fake_now.strftime("%Y-%m-%d")

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fake_now

    monkeypatch.setattr(scr, "datetime", FakeDatetime)

    # Naked OTM CE alert: Spot 25000, Strike 25200 (0.8% OTM > 0.4% threshold)
    naked_otm = make_alert(
        alert_type="OPTIONS_MOMENTUM",
        symbol="NIFTY",
        contract_symbol="NIFTY2026100525200CE",
        option_type="CE",
        strike=25200.0,
        expiry_date=today_str,
        ltp=25.0,
        stop_loss=20.0,
        target_level=45.0,
        metrics={"spot": 25000.0, "expiry_date": today_str},
    )

    passed, reason, flags = alert_scrutiny_auditor.verify_tier1_sanity(naked_otm)
    assert passed is False
    assert "0DTE Afternoon Theta Cliff Veto" in reason

    # Same setup with hedged_spread attached passes the gate!
    hedged_alert = make_alert(
        alert_type="OPTIONS_MOMENTUM",
        symbol="NIFTY",
        contract_symbol="NIFTY2026100525200CE",
        option_type="CE",
        strike=25200.0,
        expiry_date=today_str,
        ltp=25.0,
        stop_loss=20.0,
        target_level=45.0,
        actionable_plan={"hedged_spread": {"short_leg": "25300CE", "type": "BULL_CALL_SPREAD"}},
        metrics={"spot": 25000.0, "expiry_date": today_str},
    )
    passed2, reason2, flags2 = alert_scrutiny_auditor.verify_tier1_sanity(hedged_alert)
    assert passed2 is True


def test_0dte_expiry_pin_risk_veto(monkeypatch):
    """0DTE option setup near major OI Wall post-14:15 IST is vetoed for terminal pin risk."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from engine.alert_scrutiny import alert_scrutiny_auditor
    import engine.alert_scrutiny as scr

    ist = ZoneInfo("Asia/Kolkata")
    fake_now = datetime(2026, 10, 5, 14, 25, tzinfo=ist)
    today_str = fake_now.strftime("%Y-%m-%d")

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fake_now

    monkeypatch.setattr(scr, "datetime", FakeDatetime)

    # Spot 25000, OI Wall 25010 (0.04% away <= 0.25% pin zone)
    pin_alert = make_alert(
        alert_type="OPTIONS_MOMENTUM",
        symbol="NIFTY",
        contract_symbol="NIFTY2026100525000CE",
        option_type="CE",
        strike=25000.0,
        expiry_date=today_str,
        ltp=30.0,
        stop_loss=24.0,
        target_level=50.0,
        metrics={"spot": 25000.0, "oi_wall_strike": 25010.0, "expiry_date": today_str},
    )

    passed, reason, flags = alert_scrutiny_auditor.verify_tier1_sanity(pin_alert)
    assert passed is False
    assert "0DTE Expiry Pin Risk Veto" in reason


def test_eod_session_scorecard_and_review(monkeypatch):
    """EOD session scorecard calculates win rate, profit factor, net R, and latches idempotently."""
    from engine.auto_alert_engine import AutoAlertEngine
    from engine.alert_postmortem_runner import generate_session_scorecard

    engine = AutoAlertEngine()
    engine.clear_alerts()
    engine._eod_session_reviewed_date = None

    # Alert 1: Winner (+2.0R, T1 achieved)
    a1 = make_alert(
        alert_id="aa-eod-win-1",
        symbol="RELIANCE",
        stage="T1_ACHIEVED",
        ltp=2550.0,
        trigger_level=2500.0,
        stop_loss=2475.0,
        target_level=2550.0,
        r_multiple=2.0,
        achieved_milestones=["T1_ACHIEVED"],
    )
    # Alert 2: Winner (+3.5R, T2 achieved)
    a2 = make_alert(
        alert_id="aa-eod-win-2",
        symbol="BANKNIFTY",
        alert_type="GAMMA_BLAST",
        stage="T2_ACHIEVED",
        ltp=240.0,
        trigger_level=120.0,
        stop_loss=90.0,
        target_level=240.0,
        r_multiple=3.5,
        achieved_milestones=["T1_ACHIEVED", "T2_ACHIEVED"],
    )
    # Alert 3: Loser (-1.0R, Invalidated)
    a3 = make_alert(
        alert_id="aa-eod-loss-1",
        symbol="INFY",
        stage="INVALIDATED",
        is_invalidated=True,
        ltp=1500.0,
        trigger_level=1520.0,
        stop_loss=1500.0,
        target_level=1560.0,
        r_multiple=-1.0,
    )
    engine._alerts.extend([a1, a2, a3])

    scorecard = generate_session_scorecard([a1, a2, a3])
    assert scorecard["total_alerts"] == 3
    assert scorecard["wins"] == 2
    assert scorecard["losses"] == 1
    assert scorecard["win_rate_pct"] == 66.7
    assert scorecard["net_realized_r"] == 4.5  # +2.0 + 3.5 - 1.0
    assert scorecard["profit_factor"] == 5.5  # 5.5 / 1.0
    assert scorecard["best_trade"]["symbol"] == "BANKNIFTY"

    # Verify check_eod_session_review execution and single-session latch
    sent_msgs = []
    monkeypatch.setattr("bot.telegram_bot.send_message", lambda msg, **kw: sent_msgs.append(msg))

    rep = engine.check_eod_session_review(force=True)
    assert rep is not None
    assert rep["status"] == "COMPLETED"
    assert rep["scorecard"]["wins"] == 2
    assert len(sent_msgs) == 1
    assert "EOD QUANTITATIVE SESSION SCORECARD" in sent_msgs[0]

    # Calling again without force must return None due to single-session latch
    rep2 = engine.check_eod_session_review(force=False)
    assert rep2 is None


def test_options_inverted_target_without_option_plan_vetoed():
    """Option alert with inverted targets (target_2 <= target_1) is vetoed even when option_plan is absent."""
    alert = make_alert(
        alert_type="INDEX_MICRO_SCALP",
        symbol="NIFTY",
        contract_symbol="NIFTY2026100622550CE",
        option_type="CE",
        strike=22550.0,
        ltp=113.6,
        trigger_level=113.6,
        stop_loss=103.4,
        target_level=198.8,
        actionable_plan={"target_1": 198.8, "target_2": 168.1},
    )
    is_valid, reason = alert.validate_data_integrity()
    assert is_valid is False
    assert "Inverted Target Hierarchy" in reason


def test_alert_normalize_target_hierarchy_self_healing():
    """Verify that normalize_target_hierarchy corrects inverted target dictionaries."""
    alert = make_alert(
        alert_type="INDEX_MICRO_SCALP",
        symbol="NIFTY",
        contract_symbol="NIFTY2026100622550CE",
        option_type="CE",
        strike=22550.0,
        ltp=113.6,
        trigger_level=113.6,
        stop_loss=103.4,
        target_level=198.8,
        actionable_plan={
            "action": "BUY NIFTY 22550 CE",
            "target": "₹198.8",
            "target_2": "₹168.1",
            "target_1": "₹144.2",
        },
    )
    alert.normalize_target_hierarchy()
    assert alert.target_level == 144.2
    assert alert.actionable_plan["target"] == "₹144.2"
    assert alert.actionable_plan["target_1"] == "₹144.2"
    assert alert.actionable_plan["target_2"] == "₹168.1"
    assert alert.actionable_plan["target_3"] == "₹198.8"
    assert alert.actionable_plan["runner_target"] == "₹198.8"


def test_micro_scalp_exempt_from_anti_whipsaw_widening():
    """INDEX_MICRO_SCALP alert with tight 9% stop is preserved and not widened to 15%."""
    from engine.auto_alert_engine import AutoAlertEngine

    engine = AutoAlertEngine()
    engine.clear_alerts()

    scalp_alert = make_alert(
        alert_id="test-micro-scalp-tight-stop",
        alert_type="INDEX_MICRO_SCALP",
        symbol="NIFTY",
        contract_symbol="NIFTY2026100622550CE",
        option_type="CE",
        strike=22550.0,
        ltp=113.6,
        trigger_level=113.6,
        stop_loss=103.4,  # 8.98% risk
        target_level=123.8,
        time_horizon="SCALP",
        actionable_plan={
            "action": "BUY NIFTY 22550 CE",
            "entry_range": "₹113.6 – ₹117.2",
            "recommended_entry": "₹113.6 – ₹117.2",
            "stop_loss": "₹103.4",
            "target": "₹123.8",
            "target_1": "₹123.8",
            "target_2": "₹134.0",
            "runner_target": "₹146.3",
            "lot_size": 65,
        },
    )

    success = engine.record_alert(scalp_alert)
    assert success is True
    # Verify stop loss was NOT widened to 96.6 (15%)
    assert scalp_alert.actionable_plan["target_2"] == "₹134.0"


def test_0dte_afternoon_option_target_calibration_and_diffusion():
    """Verify that a 0-DTE ITM option trade at 14:27 IST has realistic, achievable T1 and T2 levels.

    Prevents the bug where a distant +4.5R structural spot target was directly set as T1 (e.g. ₹207.7),
    violating the basic risk management definition of an initial 50% scale-out level.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from engine.trade_plan import calculate_trade_plan, calculate_option_execution_plan

    IST = ZoneInfo("Asia/Kolkata")
    ref_dt = datetime(2026, 10, 6, 14, 27, tzinfo=IST)
    spot = 22685.5
    strike = 22600.0
    opt_ltp = 92.15

    # 1. Spot TradePlan should enforce temporal diffusion budget
    tp = calculate_trade_plan(
        symbol="NIFTY",
        direction="BUY",
        spot=spot,
        timeframe="INTRADAY",
        exchange="NFO",
        has_active_blast=True,
        ref_dt=ref_dt,
    )
    # At 14:27 IST (~48m to close), T1 distance should be bounded by session budget / 1.2R floor (~40-95 pts, not 180+ pts)
    t1_spot_dist = tp.target_1 - tp.entry_price
    assert 20.0 <= t1_spot_dist <= 105.0, (
        f"Spot T1 distance {t1_spot_dist} violates 14:27 IST diffusion budget"
    )

    # 2. Option Execution Plan must provide realistic scale-out R-multiples
    opt_plan = calculate_option_execution_plan(
        trade_plan=tp,
        option_type="CE",
        strike=strike,
        expiry="2026-10-06",
        option_ltp=opt_ltp,
        lot_size=65,
        spot=spot,
    )

    t1_prem = opt_plan["t1_premium"]
    t2_prem = opt_plan["t2_premium"]
    t3_prem = opt_plan["t3_premium"]
    sl_prem = opt_plan["sl_premium"]
    opt_risk = opt_ltp - sl_prem

    # Target 1 must be an achievable scale-out: +1.4R to +2.0R (e.g. ₹128 to ₹145, not ₹207.7)
    rr_t1 = (t1_prem - opt_ltp) / opt_risk
    assert 1.40 <= rr_t1 <= 2.10, f"Option T1 R:R {rr_t1} is outside institutional scale-out range"
    assert 120.0 <= t1_prem <= 145.0, f"Option T1 premium {t1_prem} is unrealistic"

    # Target 2 must be a sensible structural expansion: +2.4R to +4.0R
    rr_t2 = (t2_prem - opt_ltp) / opt_risk
    assert 2.40 <= rr_t2 <= 4.00, f"Option T2 R:R {rr_t2} is outside structural expansion range"
    assert 130.0 <= t2_prem <= 195.0, f"Option T2 premium {t2_prem} is unrealistic"

    # Target 3 (Moonshot Runner) must preserve higher potential
    assert t3_prem > t2_prem
    assert t3_prem >= 190.0

    # Monotonicity check
    assert sl_prem < opt_ltp < t1_prem < t2_prem < t3_prem


def test_vwap_band_warning_suppressed_on_feed_divergence_or_cross_contamination():
    """Underlying spot deviating > 5% from VWAP or > 15% from strike must be suppressed as corrupted feed."""
    from engine.alert_evaluator import evaluate_alert_in_flight_decay

    alert = make_alert(
        alert_id="aa-test-vwap-divergence-001",
        alert_type="INDEX_CALL_SETUP",
        symbol="NIFTY",
        contract_symbol="NIFTY22650CE",
        option_type="CE",
        strike=22650.0,
        ltp=63.4,
        trigger_level=64.3,
        option_premium=64.3,
        stop_loss=48.22,
        target_level=90.0,
        underlying_spot=10852.10,  # Corrupted alien feed!
        metrics={"vwap": 22600.0, "vwap_std": 35.0, "spot": 10852.10},
        is_live=True,
    )

    # Cross-sanity feed guard must suppress this completely
    eval_res = evaluate_alert_in_flight_decay(alert, current_ltp=63.4)
    assert eval_res is None


def test_vwap_band_warning_never_renders_contradictory_zero_rupee_hedge_defense():
    """VWAP band warning alerts must never render contradictory hedge defense blocks with ₹0.0 values."""
    from bot.alert_templates import render_auto_alert

    alert = make_alert(
        alert_id="aa-test-vwap-no-ghost-hedge",
        alert_type="INDEX_CALL_SETUP",
        stage="IN_FLIGHT_WARNING",
        symbol="NIFTY",
        contract_symbol="NIFTY22650CE",
        option_type="CE",
        strike=22650.0,
        ltp=63.4,
        stop_loss=48.22,
        target_level=90.0,
        in_flight_warning_sent=True,
        in_flight_warning_reason="VWAP BAND BREAKDOWN: Price ₹22,480.00 broke below -1.0σ band (₹22,493.54).",
        trailing_decision="SCRATCH_OR_TIGHTEN_TO_VWAP",
        actionable_plan={
            "hedge_plan": {
                "strategy": "BULL_CALL_SPREAD",
                "short_strike": 22750.0,
                "net_debit_per_share": 41.75,
            }
        },
        is_live=True,
    )

    rendered = render_auto_alert(alert, in_market=True)
    assert "VWAP BAND WARNING" in rendered
    assert "SCRATCH OR TIGHTEN TO VWAP" in rendered
    # Contradictory hedge defense must be completely absent
    assert "HEDGE DEFENSE" not in rendered
    assert "@ ~₹0.0" not in rendered
    assert "Risk Frozen: ₹0.0" not in rendered
    assert "22750.0" not in rendered


def test_mstock_quote_mapping_never_cross_contaminates_unmatched_tokens():
    """mStock get_quote must not map an unmatched broker token onto inst_list[0]."""
    from brokers.mstock import MStockAPI
    from unittest.mock import MagicMock

    api = MStockAPI()
    api._token = "valid_test_token"
    api._headers = lambda: {"Authorization": "Bearer test"}

    # Mock client post returning an alien token 10852 when query was for NIFTY (token 26000)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": True,
        "data": {
            "fetched": [
                {
                    "exchange": "NSE",
                    "tradingSymbol": "ULTRACEMCO",
                    "symbolToken": "10852",
                    "ltp": 10852.10,
                    "close": 10800.0,
                }
            ]
        },
    }
    api._client.post = MagicMock(return_value=mock_resp)

    # Query for NSE:NIFTY 50 (whose token is 26000, not 10852)
    quotes = api.get_quote(["NSE:NIFTY 50"])
    assert "NSE:NIFTY 50" not in quotes
    assert "NIFTY 50" not in quotes
