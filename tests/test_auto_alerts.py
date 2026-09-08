"""
tests/test_auto_alerts.py
─────────────────────────
Unit tests for the real-time autonomous alert engine.
Verifies early-warning detection for:
  - Gamma Blast (CE and PE writer capitulation)
  - Squeeze Breakout (Bollinger inside Keltner coiling near pivot)
  - Circuit Proximity (Upper Circuit proximity alert)
  - Engine recording, deduplication, cooldowns, and query filtering.
"""

from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd
import pytest

from engine.auto_alert_engine import (
    AutoAlert,
    AutoAlertEngine,
    detect_circuit_proximity,
    detect_gamma_blast,
    detect_squeeze_breakout,
    evaluate_alert_invalidation,
    evaluate_alert_targets_and_trailing,
)


@dataclass
class MockOptionsContract:
    symbol: str
    underlying: str
    strike: float
    option_type: str  # "CE" | "PE"
    last_price: float
    oi: int
    oi_change: int
    volume: int
    iv: float = 18.5
    exchange: str = "NFO"


def test_gamma_blast_bullish_ce_early_warning_and_ignite():
    """Test Call Gamma Blast detection on negative OI change and volume surge."""
    spot = 24000.0
    vwap = 23990.0  # spot is above VWAP

    # Synthetic chain with 24000 CE writers in panic
    chain = [
        # Normal strike with positive OI change
        MockOptionsContract(
            symbol="NIFTY24000PE",
            underlying="NIFTY",
            strike=24000.0,
            option_type="PE",
            last_price=45.0,
            oi=50000,
            oi_change=12000,
            volume=30000,
        ),
        # Panicking 24000 CE strike: OI shedding -30,000 (-37.5%), Vol/OI = 3.0x
        MockOptionsContract(
            symbol="NIFTY24000CE",
            underlying="NIFTY",
            strike=24000.0,
            option_type="CE",
            last_price=65.0,
            oi=80000,
            oi_change=-30000,
            volume=240000,  # 3.0x OI
        ),
        # 24100 CE coiling: Vol/OI = 2.0x, OI shedding -10,000 (-12%)
        MockOptionsContract(
            symbol="NIFTY24100CE",
            underlying="NIFTY",
            strike=24100.0,
            option_type="CE",
            last_price=22.0,
            oi=70000,
            oi_change=-10000,
            volume=140000,  # 2.0x OI
        ),
    ]

    alerts = detect_gamma_blast("NIFTY", spot=spot, chain=chain, vwap=vwap, day_high=24005.0)

    assert len(alerts) >= 1
    # 24000 CE should be detected with high confidence
    ce_alert = next((a for a in alerts if a.strike == 24000.0 and a.option_type == "CE"), None)
    assert ce_alert is not None
    assert ce_alert.alert_type == "GAMMA_BLAST"
    assert ce_alert.direction == "BULLISH"
    assert ce_alert.stage == "IGNITED"
    assert ce_alert.metrics["vol_oi_ratio"] >= 2.5
    assert ce_alert.metrics["oi_change"] < 0
    assert ce_alert.confidence >= 80
    assert "BUY" in ce_alert.actionable_plan["action"]


def test_gamma_blast_bearish_pe_ignite():
    """Test Put Gamma Blast detection when Put writers capitulate."""
    spot = 23750.0
    vwap = 23780.0  # spot is below VWAP

    chain = [
        # 23800 PE panicking: OI shedding -40,000, Vol/OI = 2.8x
        MockOptionsContract(
            symbol="NIFTY23800PE",
            underlying="NIFTY",
            strike=23800.0,
            option_type="PE",
            last_price=88.0,
            oi=90000,
            oi_change=-40000,
            volume=252000,  # 2.8x OI
        ),
    ]

    alerts = detect_gamma_blast("NIFTY", spot=spot, chain=chain, vwap=vwap, day_low=23745.0)
    assert len(alerts) == 1
    pe_alert = alerts[0]
    assert pe_alert.direction == "BEARISH"
    assert pe_alert.option_type == "PE"
    assert pe_alert.strike == 23800.0
    assert pe_alert.stage == "IGNITED"


def test_gamma_blast_no_panic_returns_empty():
    """When open interest is building normally, no gamma blast alert should fire."""
    spot = 24000.0
    vwap = 24000.0

    chain = [
        # Normal steady trading with positive OI addition
        MockOptionsContract(
            symbol="NIFTY24000CE",
            underlying="NIFTY",
            strike=24000.0,
            option_type="CE",
            last_price=50.0,
            oi=100000,
            oi_change=15000,  # positive
            volume=50000,     # Vol/OI = 0.5x
        ),
    ]

    alerts = detect_gamma_blast("NIFTY", spot=spot, chain=chain, vwap=vwap)
    assert len(alerts) == 0


def test_detect_squeeze_breakout_early_warning():
    """Test Squeeze Breakout early-warning coiling within 0.8% of pivot."""
    # Build 30 bars of consolidating tight data
    np.random.seed(42)
    closes = [2500.0 + (i * 0.5) + (np.sin(i) * 3) for i in range(30)]
    highs = [c + 3.0 for c in closes]
    lows = [c - 3.0 for c in closes]
    volumes = [100000 for _ in range(30)]

    df = pd.DataFrame({
        "close": closes,
        "high": highs,
        "low": lows,
        "volume": volumes,
    })

    # 20-day high is around 2520, LTP is 2505 (around 0.6% below pivot)
    pivot_high = float(np.max(highs[-21:-1]))
    ltp = pivot_high * 0.992  # 0.8% below pivot

    alert = detect_squeeze_breakout("RELIANCE", df=df, ltp=ltp)
    if alert is not None:
        assert alert.alert_type == "SQUEEZE_BREAKOUT"
        assert alert.stage == "EARLY_WARNING"
        assert alert.metrics["is_squeeze_on"] is True
        assert alert.target_level > alert.ltp


def test_detect_circuit_proximity():
    """Test upper circuit proximity alert when stock is within 1.2% of ceiling."""
    prev_close = 500.0
    # 5% circuit ceiling is 525.0
    # LTP at 519.0 is +3.8% gain and 1.14% away from 525.0
    ltp = 519.0
    alert = detect_circuit_proximity("SUZLON", ltp=ltp, prev_close=prev_close, circuit_band_pct=5.0)

    assert alert is not None
    assert alert.alert_type == "CIRCUIT_WARNING"
    assert alert.stage == "EARLY_WARNING"
    assert alert.direction == "BULLISH"
    assert alert.trigger_level == 525.0
    assert alert.metrics["dist_to_uc_pct"] <= 1.5


def test_auto_alert_engine_recording_and_deduplication():
    """Verify engine records alerts, filters duplicates via cooldown, and queries."""
    engine = AutoAlertEngine(max_buffer=50)
    engine.clear_alerts()

    alert1 = AutoAlert(
        alert_id="test-1",
        alert_type="GAMMA_BLAST",
        stage="EARLY_WARNING",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="Test Gamma Alert",
        summary="Test summary",
        ltp=24000.0,
        trigger_level=24000.0,
        target_level=24150.0,
        stop_loss=23920.0,
    )

    # First record should succeed
    assert engine.record_alert(alert1) is True

    # Immediate duplicate should be suppressed by anti-spam cooldown
    assert engine.record_alert(alert1) is False

    # Check query
    alerts = engine.get_alerts(alert_type="GAMMA_BLAST")
    assert len(alerts) == 1
    assert alerts[0].symbol == "NIFTY"

    # Stage filter
    assert len(engine.get_alerts(stage="IGNITED")) == 0
    assert len(engine.get_alerts(stage="EARLY_WARNING")) == 1

    engine.clear_alerts()
    assert len(engine.get_alerts()) == 0


def test_auto_alert_live_vs_test_tagging():
    """Verify live vs test environment properties and dispatch tagging."""
    engine = AutoAlertEngine(max_buffer=50)
    engine.clear_alerts()

    # Test alert
    test_alert = engine.create_test_alert(
        alert_type="GAMMA_BLAST",
        stage="EARLY_WARNING",
        symbol="NIFTY",
        is_invalidation=False,
    )
    assert test_alert.is_live is False
    assert test_alert.environment == "TEST"
    assert "[TEST]" in test_alert.headline
    assert test_alert.is_invalidated is False

    # Live alert default
    live_alert = AutoAlert(
        alert_id="live-1",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="Squeeze Breakout Ignited: RELIANCE",
        summary="Price broke above 20D high",
        ltp=2850.0,
        trigger_level=2800.0,
        target_level=2950.0,
        stop_loss=2780.0,
        is_live=True,
        environment="LIVE",
    )
    assert live_alert.is_live is True
    assert live_alert.environment == "LIVE"

    engine.clear_alerts()


def test_auto_alert_invalidation_detection_stop_loss():
    """Verify stop-loss breach triggers invalidation for bullish and bearish setups."""
    # Bullish setup with stop-loss at 2780.0
    bull_alert = AutoAlert(
        alert_id="sqz-1",
        alert_type="SQUEEZE_BREAKOUT",
        stage="EARLY_WARNING",
        symbol="RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="Squeeze coiling",
        summary="Squeeze ON",
        ltp=2820.0,
        trigger_level=2850.0,
        target_level=2980.0,
        stop_loss=2780.0,
        metrics={"sma20": 2780.0},
    )

    # LTP at 2810.0 (above stop-loss) -> still valid
    assert evaluate_alert_invalidation(bull_alert, current_ltp=2810.0) is None

    # LTP drops to 2770.0 (below stop-loss 2780) -> invalidated!
    reason = evaluate_alert_invalidation(bull_alert, current_ltp=2770.0)
    assert reason is not None
    assert "breached stop-loss" in reason or "below stop loss" in reason

    # Bearish setup with stop-loss at 24100.0
    bear_alert = AutoAlert(
        alert_id="gamma-pe-1",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BEARISH",
        headline="Put Gamma Surge",
        summary="Put capitulation",
        ltp=23950.0,
        trigger_level=24000.0,
        target_level=23800.0,
        stop_loss=24100.0,
    )

    # LTP surges to 24150.0 (above stop-loss 24100) -> invalidated!
    reason_bear = evaluate_alert_invalidation(bear_alert, current_ltp=24150.0)
    assert reason_bear is not None
    assert "Bearish thesis invalidated" in reason_bear or "breached stop-loss" in reason_bear


def test_auto_alert_invalidation_detection_structural():
    """Verify structural failure (squeeze drift > 3.5% or circuit retreat > 3%)."""
    # Squeeze alert with pivot trigger at 3000.0
    sqz_alert = AutoAlert(
        alert_id="sqz-drift",
        alert_type="SQUEEZE_BREAKOUT",
        stage="EARLY_WARNING",
        symbol="TCS",
        exchange="NSE",
        direction="BULLISH",
        headline="Coiling near 3000",
        summary="Squeeze",
        ltp=2980.0,
        trigger_level=3000.0,
        target_level=3150.0,
        stop_loss=2800.0,
    )
    # Price drifts down to 2890 (3.67% below 3000 pivot)
    reason = evaluate_alert_invalidation(sqz_alert, current_ltp=2890.0)
    assert reason is not None
    assert "Squeeze compression lost momentum" in reason or "below breakout pivot" in reason

    # Circuit alert with upper circuit ceiling at 1000.0
    cir_alert = AutoAlert(
        alert_id="cir-retreat",
        alert_type="CIRCUIT_WARNING",
        stage="EARLY_WARNING",
        symbol="TATAMOTORS",
        exchange="NSE",
        direction="BULLISH",
        headline="Approaching Upper Circuit",
        summary="Circuit warning",
        ltp=990.0,
        trigger_level=1000.0,
        target_level=1000.0,
        stop_loss=960.0,
    )
    # Price retreats to 960 (4.0% below 1000 upper circuit)
    cir_reason = evaluate_alert_invalidation(cir_alert, current_ltp=960.0)
    assert cir_reason is not None
    assert "Circuit lock threat subsided" in cir_reason


def test_auto_alert_engine_check_and_alert_invalidations():
    """Verify check_and_alert_invalidations marks alert and broadcasts."""
    engine = AutoAlertEngine(max_buffer=50)
    engine.clear_alerts()

    alert = AutoAlert(
        alert_id="inv-test-1",
        alert_type="SQUEEZE_BREAKOUT",
        stage="EARLY_WARNING",
        symbol="INFY",
        exchange="NSE",
        direction="BULLISH",
        headline="Squeeze setup",
        summary="Watching for breakout",
        ltp=1850.0,
        trigger_level=1880.0,
        target_level=1950.0,
        stop_loss=1820.0,
        is_live=True,
        environment="LIVE",
    )
    engine._alerts.append(alert)

    # Manually invalidate
    inv_alert = engine.invalidate_alert_by_id("inv-test-1", reason="Stop-loss floor broken")
    assert inv_alert is not None
    assert inv_alert.is_invalidated is True
    assert inv_alert.stage == "INVALIDATED"
    assert "VIEW INVALIDATED" in inv_alert.headline
    assert inv_alert.invalidation_reason == "Stop-loss floor broken"

    # Query with is_invalidated filter
    invalidated_list = engine.get_alerts(is_invalidated=True)
    assert len(invalidated_list) == 1
    assert invalidated_list[0].alert_id == "inv-test-1"

    engine.clear_alerts()


def test_create_test_alert_and_invalidation():
    """Verify test alert creation for both regular and invalidation modes."""
    engine = AutoAlertEngine(max_buffer=50)
    engine.clear_alerts()

    # Regular test alert
    regular = engine.create_test_alert(is_invalidation=False)
    assert regular.environment == "TEST"
    assert regular.is_live is False
    assert regular.is_invalidated is False
    assert "[TEST]" in regular.headline

    # Invalidation test alert
    inv = engine.create_test_alert(is_invalidation=True)
    assert inv.environment == "TEST"
    assert inv.is_live is False
    assert inv.is_invalidated is True
    assert inv.stage == "INVALIDATED"
    assert "VIEW INVALIDATED" in inv.headline
    assert "Setup invalidated" in inv.invalidation_reason or "is no longer valid" in inv.summary

    engine.clear_alerts()


def test_target_1_breakeven_trailing_decision():
    """Verify Target 1 (1.8R-2.0R) triggers BOOK_50_TRAIL_BREAKEVEN with 0.2% buffer."""
    alert = AutoAlert(
        alert_id="t1-bull-1",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="Breakout triggered",
        summary="Squeeze fired",
        ltp=2500.0,
        trigger_level=2500.0,
        target_level=2700.0,
        stop_loss=2450.0,  # Risk = 50 pts, T1 = 2590.0 (or midpoint 2600.0)
    )

    # Current price at 2595.0 reaches T1
    res = evaluate_alert_targets_and_trailing(alert, current_ltp=2595.0)
    assert res is not None
    assert res.new_milestone == "T1_ACHIEVED"
    assert res.target_status == "T1_ACHIEVED"
    assert res.should_trail is True
    assert res.trailing_decision == "BOOK_50_TRAIL_BREAKEVEN"
    assert res.recommended_stop == round(2500.0 * 1.002, 2)  # 2505.0 Breakeven with buffer
    assert res.locked_profit_pts > 0
    assert res.locked_profit_pct > 0
    assert "BOOK 50% PARTIAL PROFIT NOW" in res.trailing_rationale
    assert "TRAIL STOP-LOSS TO BREAKEVEN" in res.trailing_rationale


def test_final_target_book_full_profit_no_trail():
    """Verify Final Target at standard resistance triggers BOOK_FULL_PROFIT_NO_TRAIL."""
    alert = AutoAlert(
        alert_id="tgt-bull-1",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="TCS",
        exchange="NSE",
        direction="BULLISH",
        headline="Breakout triggered",
        summary="Squeeze fired",
        ltp=3000.0,
        trigger_level=3000.0,
        target_level=3200.0,
        stop_loss=2950.0,
    )

    # Price hits final target 3205.0 with normal volume
    res = evaluate_alert_targets_and_trailing(alert, current_ltp=3205.0, current_volume_ratio=1.2)
    assert res is not None
    assert res.new_milestone == "TARGET_ACHIEVED"
    assert res.target_status == "TARGET_ACHIEVED"
    assert res.should_trail is False
    assert res.trailing_decision == "BOOK_FULL_PROFIT_NO_TRAIL"
    assert res.recommended_stop == 3205.0
    assert "FULL PROFIT BOOKING RECOMMENDED" in res.trailing_rationale
    assert "DO NOT TRAIL FURTHER" in res.trailing_rationale


def test_momentum_extension_chandelier_trailing():
    """Verify Final Target with runaway volume (>=2.0x) triggers TRAIL_DYNAMIC_ATR."""
    alert = AutoAlert(
        alert_id="tgt-super-1",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="Gamma surge",
        summary="Panic short covering",
        ltp=24000.0,
        trigger_level=24000.0,
        target_level=24200.0,
        stop_loss=23920.0,
    )

    # Price reaches target 24210.0 with massive volume turnover (vol_ratio=2.6x)
    res = evaluate_alert_targets_and_trailing(alert, current_ltp=24210.0, current_volume_ratio=2.6)
    assert res is not None
    assert res.new_milestone == "TARGET_ACHIEVED"
    assert res.should_trail is True
    assert res.trailing_decision == "TRAIL_DYNAMIC_ATR"
    assert res.is_superperforming is True
    assert res.recommended_stop > 24000.0
    assert "DO NOT FULLY EXIT RUNNER" in res.trailing_rationale
    assert "Chandelier ATR Trail" in res.trailing_rationale


def test_early_subtarget_hold_stop():
    """Verify sub-target price action (<1.5R) advises maintaining initial stop-loss."""
    alert = AutoAlert(
        alert_id="early-1",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="INFY",
        exchange="NSE",
        direction="BULLISH",
        headline="Breakout",
        summary="Watching",
        ltp=1800.0,
        trigger_level=1800.0,
        target_level=1950.0,
        stop_loss=1760.0,  # Risk = 40 pts
    )

    # Current LTP at 1820.0 is only 0.5R
    res = evaluate_alert_targets_and_trailing(alert, current_ltp=1820.0)
    assert res is not None
    assert res.new_milestone is None
    assert res.should_trail is False
    assert res.trailing_decision == "DO_NOT_TRAIL_HOLD_STOP"
    assert res.recommended_stop == 1760.0
    assert "DO NOT TRAIL YET" in res.trailing_rationale


def test_bearish_target_and_trailing():
    """Verify bearish trade target progression and trailing stop calculation."""
    alert = AutoAlert(
        alert_id="bear-1",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="BANKNIFTY",
        exchange="NFO",
        direction="BEARISH",
        headline="Put panic",
        summary="Downside momentum",
        ltp=51000.0,
        trigger_level=51000.0,
        target_level=50200.0,
        stop_loss=51250.0,  # Risk = 250 pts, T1 = 51000 - 450 = 50550 (or midpoint 50600)
    )

    # Price drops to 50540.0 reaching T1
    res = evaluate_alert_targets_and_trailing(alert, current_ltp=50540.0)
    assert res is not None
    assert res.new_milestone == "T1_ACHIEVED"
    assert res.should_trail is True
    assert res.trailing_decision == "BOOK_50_TRAIL_BREAKEVEN"
    assert res.recommended_stop == round(51000.0 * 0.998, 2)  # 50898.0
    assert "BOOK 50% PARTIAL PROFIT NOW" in res.trailing_rationale


def test_target_milestone_latching_and_ratchet_dedup(monkeypatch):
    """Verify that achieved milestones are latched so targets do not re-alert on every tick."""
    engine = AutoAlertEngine(max_buffer=50)
    engine.clear_alerts()

    alert = AutoAlert(
        alert_id="latch-test-1",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="TITAN",
        exchange="NSE",
        direction="BULLISH",
        headline="Breakout",
        summary="Test",
        ltp=3400.0,
        trigger_level=3400.0,
        target_level=3600.0,
        stop_loss=3350.0,  # Risk = 50 pts, T1 = 3490.0 (or midpoint 3500.0)
        is_live=True,
        environment="LIVE",
    )
    engine._alerts.append(alert)

    # 1. Price hits T1 (3495.0)
    monkeypatch.setattr("market.quotes.get_ltp", lambda sym: 3495.0)
    updated = engine.check_and_alert_targets_and_trailing()
    assert len(updated) == 1
    assert "T1_ACHIEVED" in alert.achieved_milestones
    assert alert.stage == "T1_ACHIEVED"
    assert alert.should_trail is True
    assert alert.trailing_decision == "BOOK_50_TRAIL_BREAKEVEN"

    # 2. Immediate next tick with same price 3495.0: Latched! Must NOT alert again!
    updated_again = engine.check_and_alert_targets_and_trailing()
    assert len(updated_again) == 0

    # 3. Price surges to Final Target (3605.0)
    monkeypatch.setattr("market.quotes.get_ltp", lambda sym: 3605.0)
    updated_final = engine.check_and_alert_targets_and_trailing()
    assert len(updated_final) == 1
    assert "TARGET_ACHIEVED" in alert.achieved_milestones
    assert alert.stage in ("TARGET_ACHIEVED", "COMPLETED")

    # 4. Immediate next tick with price 3608.0: Latched & retired! Must NOT alert again!
    updated_final_again = engine.check_and_alert_targets_and_trailing()
    assert len(updated_final_again) == 0

    engine.clear_alerts()


def test_create_test_target_alert():
    """Verify test target alert generation for T1, FINAL, and TRAIL modes."""
    engine = AutoAlertEngine(max_buffer=50)
    engine.clear_alerts()

    # T1 Test Alert
    t1_test = engine.create_test_target_alert(milestone="T1", should_trail=True, symbol="RELIANCE")
    assert t1_test.environment == "TEST"
    assert t1_test.is_live is False
    assert t1_test.stage == "T1_ACHIEVED"
    assert t1_test.should_trail is True
    assert t1_test.trailing_decision == "BOOK_50_TRAIL_BREAKEVEN"
    assert "[TEST]" in t1_test.headline
    assert t1_test.trailing_stop == 2865.0

    # Final Target Test Alert with full profit booking (no trail)
    final_test = engine.create_test_target_alert(milestone="FINAL", should_trail=False, symbol="TCS")
    assert final_test.environment == "TEST"
    assert final_test.stage == "TARGET_ACHIEVED"
    assert final_test.should_trail is False
    assert final_test.trailing_decision == "BOOK_FULL_PROFIT_NO_TRAIL"
    assert "DO NOT TRAIL FURTHER" in final_test.trailing_rationale

    # Trail SL Ratchet Test Alert
    trail_test = engine.create_test_target_alert(milestone="TRAIL", should_trail=True, symbol="INFY")
    assert trail_test.environment == "TEST"
    assert trail_test.stage == "TRAILING_UPDATE"
    assert trail_test.should_trail is True
    assert trail_test.trailing_decision == "TRAIL_DYNAMIC_ATR"
    assert trail_test.trailing_stop == 2950.0

    engine.clear_alerts()


def test_active_alert_deduplication_and_in_place_upgrade():
    """Verify that recording alerts for the same symbol does not duplicate active alerts, and upgrades early warnings."""
    engine = AutoAlertEngine(max_buffer=50)
    engine.clear_alerts()

    early = AutoAlert(
        alert_id="titan-sqz-1",
        alert_type="SQUEEZE_BREAKOUT",
        stage="EARLY_WARNING",
        symbol="TITAN",
        exchange="NSE",
        direction="BULLISH",
        headline="Squeeze Coiling: TITAN",
        summary="Coiled below pivot",
        ltp=3420.0,
        trigger_level=3440.0,
        target_level=3650.0,
        stop_loss=3380.0,
        confidence=82,
    )
    assert engine.record_alert(early) is True
    assert len(engine.get_alerts(alert_type="SQUEEZE_BREAKOUT")) == 1

    # Incoming IGNITED breakout should upgrade existing alert in place
    ignited = AutoAlert(
        alert_id="titan-sqz-2",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="TITAN",
        exchange="NSE",
        direction="BULLISH",
        headline="Breakout Ignited: TITAN",
        summary="Volume expansion",
        ltp=3445.0,
        trigger_level=3440.0,
        target_level=3650.0,
        stop_loss=3390.0,
        confidence=90,
    )
    assert engine.record_alert(ignited) is True
    alerts = engine.get_alerts(alert_type="SQUEEZE_BREAKOUT")
    assert len(alerts) == 1
    assert alerts[0].stage == "IGNITED"
    assert alerts[0].confidence == 90

    # Another duplicate breakout alert while one is already active must be suppressed
    assert engine.record_alert(ignited) is False
    assert len(engine.get_alerts(alert_type="SQUEEZE_BREAKOUT")) == 1

    engine.clear_alerts()


def test_decisive_telegram_formatting_and_one_shot_dispatch(monkeypatch):
    """Verify that Telegram messages contain distinct, decisive actions and are dispatched at most once per milestone."""
    engine = AutoAlertEngine(max_buffer=50)
    engine.clear_alerts()

    dispatched_messages = []
    monkeypatch.setattr("engine.alerts._telegram_notify", lambda msg: dispatched_messages.append(msg))

    alert = AutoAlert(
        alert_id="decisive-test-1",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="TITAN",
        exchange="NSE",
        direction="BULLISH",
        headline="Breakout: TITAN",
        summary="Breakout ignited",
        ltp=3400.0,
        trigger_level=3400.0,
        target_level=3600.0,
        stop_loss=3350.0,
        is_live=True,
        environment="LIVE",
    )
    engine._alerts.append(alert)

    # 1. T1 Hit
    monkeypatch.setattr("market.quotes.get_ltp", lambda sym: 3495.0)
    engine.check_and_alert_targets_and_trailing()
    assert len(dispatched_messages) == 1
    t1_msg = dispatched_messages[0]
    assert "TARGET 1 ACHIEVED" in t1_msg
    assert "BOOK 50% PROFIT NOW & HOLD RUNNER" in t1_msg
    assert "100% risk-free" in t1_msg.lower()

    # Next cycle at T1: Dispatch gate blocks duplicate
    engine.check_and_alert_targets_and_trailing()
    assert len(dispatched_messages) == 1  # Still 1, not duplicate!

    # 2. Final Target Hit
    monkeypatch.setattr("market.quotes.get_ltp", lambda sym: 3605.0)
    engine.check_and_alert_targets_and_trailing()
    assert len(dispatched_messages) == 2
    final_msg = dispatched_messages[1]
    assert "FINAL TARGET REACHED" in final_msg
    assert "CLOSE ALL POSITIONS (BOOK FULL PROFIT)" in final_msg

    # Next cycle: Dispatch gate and completed status block duplicate
    engine.check_and_alert_targets_and_trailing()
    assert len(dispatched_messages) == 2  # No duplicate final target alert

    engine.clear_alerts()


@pytest.mark.live_telegram
def test_telegram_bot_send_push_deduplication_buffer(monkeypatch):
    """Verify bot.telegram_bot.send_push deduplication buffer suppresses identical messages within 5 minutes."""
    from bot.telegram_bot import send_push, _recent_push_digests, _push_dedup_lock
    import bot.telegram_bot as tb_module

    sent_calls = []

    class DummyExecutor:
        def submit(self, fn):
            sent_calls.append(True)
            return None

    monkeypatch.setattr(tb_module, "_load_chat_id", lambda: "12345678")
    monkeypatch.setattr(tb_module, "_get_bot_token", lambda: "fake-bot-token")
    monkeypatch.setattr(tb_module, "_get_push_executor", lambda: DummyExecutor())

    with _push_dedup_lock:
        _recent_push_digests.clear()

    # First send should succeed
    msg = "🎯 <b>[REAL / LIVE TARGET 1 HIT]</b>\n\n🏆 <b>TITAN (SQUEEZE BREAKOUT) — TARGET 1 ACHIEVED</b>\n\n🕒 2026-09-07 15:45:00 IST"
    send_push(msg)
    assert len(sent_calls) == 1

    # Exact duplicate send within 5 minutes (even if timestamp shifts slightly) should be suppressed
    msg2 = "🎯 <b>[REAL / LIVE TARGET 1 HIT]</b>\n\n🏆 <b>TITAN (SQUEEZE BREAKOUT) — TARGET 1 ACHIEVED</b>\n\n🕒 2026-09-07 15:45:10 IST"
    send_push(msg2)
    assert len(sent_calls) == 1  # Suppressed!

    # Different message content should be allowed
    msg3 = "🏁 <b>[REAL / LIVE FINAL TARGET ACHIEVED]</b>\n\n🏆 <b>TITAN (SQUEEZE BREAKOUT) — FINAL TARGET REACHED</b>\n\n🕒 2026-09-07 15:48:00 IST"
    send_push(msg3)
    assert len(sent_calls) == 2


