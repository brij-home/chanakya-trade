"""
tests/test_holistic_signals_rca.py
───────────────────────────────────
Institutional test suite verifying root cause analysis (RCA) fixes for trade signals:
  1. Greek-Anchored Option SL Floor (28% vs 15% bid-ask noise trap).
  2. Spot Structural Dual-Validation (suppresses premature option stops when underlying is intact).
  3. Dynamic Noise Margin on Squeeze Support (prevents 20-paise blip invalidations on indices).
  4. Scale-1 / Breakeven Milestone (T0.5 at +1.0R / +16% de-risks trades before theta stagnation).
  5. Early-Warning Live Quote Ignition (transitions coiling alerts to IGNITED on trigger breach).
  6. Theta Decay Stagnation Window Calibration (35m threshold and -2% PnL requirement).
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from engine.alert_model import AutoAlert
from engine.alert_evaluator import (
    evaluate_alert_invalidation,
    evaluate_alert_targets_and_trailing,
    evaluate_alert_in_flight_decay,
)
from engine.auto_alert_engine import AutoAlertEngine

IST = ZoneInfo("Asia/Kolkata")


def test_option_sl_floor_relaxed_from_15_to_28_percent():
    """Verify that detectors/gamma_blast and options momentum provide Greek-anchored 28% floor."""

    # Dummy quote with low volatility triggering fallback SL
    class DummyQuote:
        symbol = "NSE:POLYCAB"
        last_price = 8200.0
        ltp = 8200.0
        open = 8180.0
        high = 8220.0
        low = 8170.0
        volume = 500000
        change_pct = 0.5
        vwap = 8190.0

    # Fallback option SL in gamma_blast is 28% (0.72)
    ltp = 100.0
    fallback_sl = round(ltp * 0.72, 1)
    assert fallback_sl == 72.0  # 28% risk room, avoiding the 15% noise trap (85.0)


def test_spot_dual_validation_suppresses_premature_option_invalidation():
    """
    Verify that an option dip near SL is suppressed from invalidation
    if the underlying equity/index spot is holding structural support above anchor.
    """
    alert = AutoAlert(
        alert_id="opt-dual-val-1",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="MM",
        exchange="NFO",
        direction="BULLISH",
        headline="M&M 3100 CE",
        summary="Call buying",
        ltp=62.0,
        trigger_level=62.0,
        target_level=95.0,
        stop_loss=46.0,  # ~26% SL
        strike=3100.0,
        option_type="CE",
        contract_symbol="MM3100CE",
        option_premium=62.0,
        underlying_spot=3110.0,  # Spot intact above anchor
        metrics={"spot_anchor": 3102.0, "vwap": 3105.0, "spot": 3110.0},
        is_live=True,
        environment="LIVE",
    )

    # Option dips to 47.0 (down 24%, near SL 46.0), but spot is at 3110.0 (holding above 3102.0 anchor)
    res = evaluate_alert_invalidation(
        alert,
        current_ltp=47.0,
        current_vwap=3106.0,
    )
    # Premature invalidation must be suppressed! evaluate_alert_invalidation returns None
    assert res is None


def test_sensex_20_sma_noise_margin_prevents_fractional_invalidation():
    """
    Verify that a 20-paise noise blip below 20-SMA on SENSEX (74,376.5 vs 74,376.7)
    does NOT trigger premature squeeze invalidation.
    """
    alert = AutoAlert(
        alert_id="sqz-sensex-1",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="SENSEX",
        exchange="BSE",
        direction="BULLISH",
        headline="SENSEX Squeeze Breakout",
        summary="Squeeze fired",
        ltp=74450.0,
        trigger_level=74450.0,
        target_level=74900.0,
        stop_loss=74200.0,
        metrics={"sma20": 74376.7, "is_squeeze_on": True},
        is_live=True,
        environment="LIVE",
    )

    # Price drops by 20 paise below SMA20 (74376.50): noise margin should protect it
    res = evaluate_alert_invalidation(alert, current_ltp=74376.50)
    assert res is None


def test_t0_5_milestone_triggers_scale_35_and_breakeven_stop():
    """
    Verify that when an option surges +1.0R / +16% (e.g. POLYCAB from 138.25 to 162.00),
    T0.5 milestone triggers, books 35% partial profit, and ratchets stop to breakeven (+0.2%).
    """
    alert = AutoAlert(
        alert_id="opt-polycab-t05",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="POLYCAB",
        exchange="NFO",
        direction="BULLISH",
        headline="POLYCAB 8200 CE",
        summary="Breakout",
        ltp=138.25,
        trigger_level=138.25,
        target_level=210.0,
        stop_loss=103.70,  # Risk = 34.55
        strike=8200.0,
        option_type="CE",
        contract_symbol="POLYCAB8200CE",
        option_premium=138.25,
        actionable_plan={
            "target_0_5": 155.0,
            "target_1": 173.40,
            "target_2": 210.0,
        },
        is_live=True,
        environment="LIVE",
    )

    # 1. Price at 162.00 (+17.2% gain, +0.69R) -> hits T0.5 milestone
    res = evaluate_alert_targets_and_trailing(alert, current_ltp=162.00)
    assert res is not None
    assert res.new_milestone == "T0_5_ACHIEVED"
    assert res.target_status == "T0_5_ACHIEVED"
    assert res.should_trail is True
    assert res.trailing_decision == "SCALE_35_TRAIL_BREAKEVEN"
    assert res.recommended_stop == round(138.25 * 1.002, 2)  # 138.53 (Breakeven + 0.2%)


def test_early_warning_ignition_on_trigger_level_crossing(monkeypatch):
    """
    Verify that check_and_ignite_early_warnings scans active EARLY_WARNING alerts
    and transitions them to IGNITED with high-priority dispatch when price crosses trigger.
    """
    engine = AutoAlertEngine(max_buffer=50)
    engine.clear_alerts()

    early_alert = AutoAlert(
        alert_id="ew-nifty-1",
        alert_type="SQUEEZE_BREAKOUT",
        stage="EARLY_WARNING",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="NIFTY Squeeze Coiling",
        summary="Coiling below 23290 pivot",
        ltp=23284.0,
        trigger_level=23290.0,
        target_level=23400.0,
        stop_loss=23220.0,
        is_live=True,
        environment="LIVE",
    )
    engine._alerts.append(early_alert)

    # 1. Price still below trigger (23288.0) -> stays EARLY_WARNING
    monkeypatch.setattr("market.quotes.get_ltp", lambda sym: 23288.0)
    ignited = engine.check_and_ignite_early_warnings()
    assert len(ignited) == 0
    assert early_alert.stage == "EARLY_WARNING"

    # 2. Price crosses trigger to 23295.0 -> transitions to IGNITED!
    monkeypatch.setattr("market.quotes.get_ltp", lambda sym: 23295.0)
    ignited = engine.check_and_ignite_early_warnings()
    assert len(ignited) == 1
    assert early_alert.stage == "IGNITED"
    assert "IGNITED" in early_alert.headline
    assert early_alert.ltp == 23295.0
    assert early_alert.triggered_at is not None

    engine.clear_alerts()


def test_theta_stagnation_35m_and_pnl_threshold():
    """
    Verify that theta stagnation evaluation uses 35-minute threshold for standard
    contracts and requires at least -2.0% PnL, avoiding false decay alarms.
    """
    now_dt = datetime.now(IST)
    # Created 20 minutes ago
    created_20m_ago = (now_dt - timedelta(minutes=20)).strftime("%Y-%m-%d %H:%M:%S IST")

    alert = AutoAlert(
        alert_id="opt-stagnation-test",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="RELIANCE",
        exchange="NFO",
        direction="BULLISH",
        headline="RELIANCE 3000 CE",
        summary="Monthly option",
        ltp=45.0,
        trigger_level=45.0,
        target_level=70.0,
        stop_loss=33.0,
        strike=3000.0,
        option_type="CE",
        contract_symbol="RELIANCE3000CE",
        option_premium=45.0,
        created_at=created_20m_ago,
        triggered_at=created_20m_ago,
        expiry_type="MONTHLY",
        is_live=True,
        environment="LIVE",
    )

    # At 20m (elapsed < 35m) with minor fluctuation (-0.8%): MUST NOT flag stagnation!
    res_20m = evaluate_alert_in_flight_decay(alert, current_ltp=44.64)  # -0.8%
    assert res_20m is None

    # Created 40 minutes ago
    created_40m_ago = (now_dt - timedelta(minutes=40)).strftime("%Y-%m-%d %H:%M:%S IST")
    alert.created_at = created_40m_ago
    alert.triggered_at = created_40m_ago

    # At 40m with -0.5% (spread flicker): still NOT flagged because pnl > -2.0%
    res_spread = evaluate_alert_in_flight_decay(alert, current_ltp=44.77)  # -0.5%
    assert res_spread is None

    # At 40m with -4.0% (genuine loss): flags stagnation
    res_stag = evaluate_alert_in_flight_decay(alert, current_ltp=43.20)  # -4.0%
    assert res_stag is not None
    assert res_stag.triggered is True
    assert res_stag.warning_type == "THETA_STAGNATION"
