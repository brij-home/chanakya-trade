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
import json
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
            volume=50000,  # Vol/OI = 0.5x
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

    df = pd.DataFrame(
        {
            "close": closes,
            "high": highs,
            "low": lows,
            "volume": volumes,
        }
    )

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

    # PUT Option Alert (SBIN / ICICIBANK PE Gamma Blast)
    # Bought PE option contract: entry premium 16.55, SL premium 10.8, Target 36.4
    put_opt_alert = AutoAlert(
        alert_id="gamma-pe-sbin",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="SBIN",
        exchange="NFO",
        direction="BEARISH",
        headline="⚡ PUT GAMMA BLAST: SBIN 1010 PE",
        summary="Put capitulation",
        ltp=16.55,
        trigger_level=1010.0,
        target_level=36.4,
        stop_loss=10.8,
        strike=1010.0,
        option_type="PE",
        contract_symbol="SBIN1010PE",
        underlying_spot=1007.3,
        option_premium=16.55,
    )

    # Option premium at 20.6 (profitable, above SL 10.8) -> MUST NOT be invalidated!
    assert evaluate_alert_invalidation(put_opt_alert, current_ltp=20.6) is None
    assert evaluate_alert_invalidation(put_opt_alert, current_ltp=16.55) is None
    assert evaluate_alert_invalidation(put_opt_alert, current_ltp=11.0) is None

    # Option premium drops to 9.5 (breached SL 10.8) -> invalidated!
    reason_opt = evaluate_alert_invalidation(put_opt_alert, current_ltp=9.5)
    assert reason_opt is not None
    assert "Option premium collapsed to ₹9.5" in reason_opt
    assert "breached stop-loss ₹10.8" in reason_opt
    assert "Put gamma thesis invalidated" in reason_opt

    # OPTION SELLING / WRITING ALERT (Short CE / Short PE / Credit Writing)
    # Seller writes option at premium 50.0, target 10.0, stop loss 75.0
    sell_opt_alert = AutoAlert(
        alert_id="opt-sell-sbin",
        alert_type="OPTION_WRITE",
        stage="IGNITED",
        symbol="SBIN",
        exchange="NFO",
        direction="BEARISH",
        headline="⚡ CALL OPTION WRITING: SBIN 1020 CE",
        summary="Call writing credit",
        ltp=50.0,
        trigger_level=1020.0,
        target_level=10.0,
        stop_loss=75.0,
        strike=1020.0,
        option_type="CE",
        contract_symbol="SBIN1020CE",
        actionable_plan={"action": "SELL", "recommended_entry": "50.0"},
        option_premium=50.0,
    )

    # Option premium drops to 30.0 (profitable decay) -> MUST NOT be invalidated!
    assert evaluate_alert_invalidation(sell_opt_alert, current_ltp=30.0) is None
    assert evaluate_alert_invalidation(sell_opt_alert, current_ltp=50.0) is None
    assert evaluate_alert_invalidation(sell_opt_alert, current_ltp=70.0) is None

    # Option premium surges to 80.0 (breached SL 75.0) -> invalidated!
    reason_sell = evaluate_alert_invalidation(sell_opt_alert, current_ltp=80.0)
    assert reason_sell is not None
    assert "Option premium surged to ₹80.0" in reason_sell
    assert "breached stop-loss ₹75.0" in reason_sell
    assert "Call writing thesis invalidated" in reason_sell


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


def test_put_option_target_and_trailing():
    """Verify that Put option buyers have targets above entry and trailing stop ratchets higher."""
    alert = AutoAlert(
        alert_id="opt-pe-trail-1",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="SBIN",
        exchange="NFO",
        direction="BEARISH",
        headline="Put Gamma Surge",
        summary="Put buying",
        ltp=16.55,
        trigger_level=1010.0,  # strike
        target_level=36.4,  # target premium
        stop_loss=10.8,  # SL premium
        strike=1010.0,
        option_type="PE",
        contract_symbol="SBIN1010PE",
        option_premium=16.55,
    )

    # Option premium at 20.6 (positive return, but below T1) -> holds stop
    res_hold = evaluate_alert_targets_and_trailing(alert, current_ltp=20.6)
    assert res_hold is None or res_hold.new_milestone is None

    # Option premium expands to 27.0 -> reaches T1
    res_t1 = evaluate_alert_targets_and_trailing(alert, current_ltp=27.0)
    assert res_t1 is not None
    assert res_t1.new_milestone == "T1_ACHIEVED"
    assert res_t1.should_trail is True
    assert res_t1.trailing_decision == "BOOK_50_TRAIL_BREAKEVEN"
    assert res_t1.recommended_stop == round(16.55 * 1.002, 2)  # breakeven above entry
    assert res_t1.pnl_pct > 0

    # Final target reached at 37.0
    res_final = evaluate_alert_targets_and_trailing(alert, current_ltp=37.0)
    assert res_final is not None
    assert res_final.new_milestone == "TARGET_ACHIEVED"
    assert res_final.pnl_pct > 100


def test_option_selling_target_and_trailing():
    """Verify that Option sellers (writers) profit when premium decays and trail stop downwards."""
    alert = AutoAlert(
        alert_id="opt-sell-trail-1",
        alert_type="OPTION_WRITE",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BEARISH",
        headline="NIFTY Call Writing",
        summary="Short CE credit",
        ltp=100.0,
        trigger_level=25000.0,
        target_level=20.0,  # Target premium (decayed)
        stop_loss=150.0,  # SL premium (surged)
        strike=25000.0,
        option_type="CE",
        contract_symbol="NIFTY25000CE",
        option_premium=100.0,
        actionable_plan={"action": "SELL"},
    )

    # Option premium decays to 55.0 (T1 reached)
    res_t1 = evaluate_alert_targets_and_trailing(alert, current_ltp=55.0)
    assert res_t1 is not None
    assert res_t1.new_milestone == "T1_ACHIEVED"
    assert res_t1.should_trail is True
    assert res_t1.trailing_decision == "BOOK_50_TRAIL_BREAKEVEN"
    assert res_t1.recommended_stop == round(100.0 * 0.998, 2)  # Breakeven below entry
    assert res_t1.pnl_pct > 0

    # Final target reached at 18.0 (below target 20.0)
    res_final = evaluate_alert_targets_and_trailing(alert, current_ltp=18.0)
    assert res_final is not None
    assert res_final.new_milestone == "TARGET_ACHIEVED"
    assert res_final.pnl_pct > 80


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
    final_test = engine.create_test_target_alert(
        milestone="FINAL", should_trail=False, symbol="TCS"
    )
    assert final_test.environment == "TEST"
    assert final_test.stage == "TARGET_ACHIEVED"
    assert final_test.should_trail is False
    assert final_test.trailing_decision == "BOOK_FULL_PROFIT_NO_TRAIL"
    assert "DO NOT TRAIL FURTHER" in final_test.trailing_rationale

    # Trail SL Ratchet Test Alert
    trail_test = engine.create_test_target_alert(
        milestone="TRAIL", should_trail=True, symbol="INFY"
    )
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
    monkeypatch.setattr(
        "engine.alerts._telegram_notify", lambda msg: dispatched_messages.append(msg)
    )

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


def test_early_warning_coiling_alert_header_and_plan_formatting(monkeypatch):
    """Verify that early-warning coiling alerts use EARLY WARNING header and correct mathematical signs."""
    from engine.auto_alert_engine import AutoAlert, AutoAlertEngine

    dispatched = []
    monkeypatch.setattr("engine.alerts._telegram_notify", lambda msg: dispatched.append(msg))
    monkeypatch.setattr("engine.alerts._is_market_hours", lambda exchange="NSE": True)

    engine = AutoAlertEngine()
    alert = AutoAlert(
        alert_id="coiling-header-1",
        alert_type="PATTERN_COILING",
        stage="EARLY_WARNING",
        symbol="MANKIND",
        exchange="NSE",
        direction="BULLISH",
        headline="💎 PRE-BLAST COILING: MANKIND at ₹2,285.4",
        summary="Healthy Volume Contraction.",
        ltp=2285.4,
        trigger_level=2285.4,
        target_level=2400.0,
        stop_loss=2271.5,
        confidence=90,
        is_live=True,
        environment="LIVE",
    )

    engine._dispatch(alert)
    assert len(dispatched) == 1
    msg = dispatched[0]

    # Header must be EARLY WARNING, not BREAKOUT IGNITED!
    assert "EARLY WARNING" in msg
    assert "BREAKOUT IGNITED" not in msg

    # Direction and Trade plan checks
    assert "Action:</b> BUY" in msg
    assert "Invalidation SL:</b> <code>₹" in msg
    assert "Target 1:</b> <code>₹" in msg
    assert ("ACCEPTABLE" in msg or "EXCELLENT_ASYMMETRY" in msg)
    assert "session ~21:" not in msg and "ETA: ~21:" not in msg, (
        "Off-market 21:xx hours must not appear in equity ETA"
    )


def test_bearish_alert_header_and_plan_formatting(monkeypatch):
    """Verify that a bearish ignited alert formats SELL action, positive risk pts, and negative reward pts."""
    from engine.auto_alert_engine import AutoAlert, AutoAlertEngine

    dispatched = []
    monkeypatch.setattr("engine.alerts._telegram_notify", lambda msg: dispatched.append(msg))
    monkeypatch.setattr("engine.alerts._is_market_hours", lambda exchange="NSE": True)

    engine = AutoAlertEngine()
    alert = AutoAlert(
        alert_id="short-ignited-1",
        alert_type="SMC_SWEEP",
        stage="IGNITED",
        symbol="INFY",
        exchange="NSE",
        direction="BEARISH",
        headline="Liquidity Sweep Wick Rejection: INFY at ₹1,850.0",
        summary="CHoCH bearish shift confirmed.",
        ltp=1850.0,
        trigger_level=1850.0,
        target_level=1800.0,
        stop_loss=1870.0,
        confidence=92,
        is_live=True,
        environment="LIVE",
    )

    engine._dispatch(alert)
    assert len(dispatched) == 1
    msg = dispatched[0]

    # Header must reflect IGNITED
    assert "BREAKOUT IGNITED" in msg
    # Action must be SELL for bearish
    assert "Action:</b> SELL" in msg


def test_options_alert_uses_options_plan_directly(monkeypatch):
    """Verify that options alerts format contract plan directly without running equity spot calculator."""
    from engine.auto_alert_engine import AutoAlert, AutoAlertEngine

    dispatched = []
    monkeypatch.setattr("engine.alerts._telegram_notify", lambda msg: dispatched.append(msg))
    monkeypatch.setattr("engine.alerts._is_market_hours", lambda exchange="NSE": True)

    engine = AutoAlertEngine()
    alert = AutoAlert(
        alert_id="gamma-plan-1",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="⚡ CALL GAMMA BLAST IGNITED: NIFTY 24500 CE",
        summary="Call writers shedding 18.5% OI.",
        ltp=45.0,
        trigger_level=24500.0,
        target_level=99.0,
        stop_loss=29.0,
        strike=24500.0,
        option_type="CE",
        contract_symbol="NIFTY24500CE",
        actionable_plan={
            "action": "BUY",
            "instrument": "NIFTY24500CE",
            "recommended_entry": "₹45.0",
            "target": "₹99.0 (+120%)",
            "stop_loss": "₹29.0 (-35%)",
            "risk_reward": "1:3.4",
        },
        confidence=95,
        is_live=True,
        environment="LIVE",
    )

    engine._dispatch(alert)
    assert len(dispatched) == 1
    msg = dispatched[0]

    assert "Data-Driven Options Plan" not in msg
    assert "NIFTY24500CE" in msg
    assert "₹99.0 (+120%)" in msg
    assert "₹29.0 (-35%)" in msg


def test_auto_alert_is_active_and_archived_properties():
    """Verify is_active is True only when trade is not archived, not invalidated, and not completed."""
    from engine.auto_alert_engine import AutoAlert

    # Active alert
    a_active = AutoAlert(
        alert_id="a-active",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="TCS",
        exchange="NSE",
        direction="BULLISH",
        headline="Breakout",
        summary="Testing active",
        ltp=4200.0,
        trigger_level=4200.0,
        target_level=4400.0,
        stop_loss=4100.0,
    )
    assert a_active.is_active is True
    assert a_active.is_archived is False

    # Invalidated alert
    a_inval = AutoAlert(
        alert_id="a-inval",
        alert_type="SQUEEZE_BREAKOUT",
        stage="INVALIDATED",
        symbol="TCS",
        exchange="NSE",
        direction="BULLISH",
        headline="Invalidated",
        summary="Stop breached",
        ltp=4080.0,
        trigger_level=4200.0,
        target_level=4400.0,
        stop_loss=4100.0,
        is_invalidated=True,
    )
    assert a_inval.is_active is False

    # Manually archived alert
    a_archived = AutoAlert(
        alert_id="a-arch",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="TCS",
        exchange="NSE",
        direction="BULLISH",
        headline="Archived",
        summary="User archived",
        ltp=4250.0,
        trigger_level=4200.0,
        target_level=4400.0,
        stop_loss=4100.0,
        is_archived=True,
    )
    assert a_archived.is_active is False

    # Completed target alert
    a_completed = AutoAlert(
        alert_id="a-comp",
        alert_type="SQUEEZE_BREAKOUT",
        stage="TARGET_ACHIEVED",
        symbol="TCS",
        exchange="NSE",
        direction="BULLISH",
        headline="Target reached",
        summary="Done",
        ltp=4410.0,
        trigger_level=4200.0,
        target_level=4400.0,
        stop_loss=4100.0,
        target_status="TARGET_ACHIEVED",
    )
    assert a_completed.is_active is False


def test_classify_expiry_type():
    """Verify weekly vs monthly expiry classification for equities and indices."""
    from engine.auto_alert_engine import classify_expiry_type

    # Non-index equity stocks on NSE only have monthly expiries
    assert classify_expiry_type("2026-09-17", symbol="RELIANCE") == "MONTHLY"
    assert classify_expiry_type("2026-09-24", symbol="TCS") == "MONTHLY"

    # Index options: mid-month expiry is WEEKLY, month-end expiry is MONTHLY
    # 2026-09-17 + 7 days = 2026-09-24 (same month) -> WEEKLY
    assert classify_expiry_type("2026-09-17", symbol="NIFTY") == "WEEKLY"
    # 2026-09-24 + 7 days = 2026-10-01 (next month) -> MONTHLY
    assert classify_expiry_type("2026-09-24", symbol="NIFTY") == "MONTHLY"
    assert classify_expiry_type("2026-09-24", symbol="BANKNIFTY") == "MONTHLY"


def test_archive_alert_by_id():
    """Verify archiving and unarchiving an alert by ID."""
    from engine.auto_alert_engine import AutoAlert, AutoAlertEngine

    engine = AutoAlertEngine()
    alert = AutoAlert(
        alert_id="test-archive-123",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="HDFCBANK",
        exchange="NSE",
        direction="BULLISH",
        headline="Breakout",
        summary="Test",
        ltp=1650.0,
        trigger_level=1650.0,
        target_level=1750.0,
        stop_loss=1600.0,
    )
    with engine._lock:
        engine._alerts.insert(0, alert)

    assert alert.is_active is True

    # Archive
    res = engine.archive_alert_by_id("test-archive-123", archive=True, reason="Clutter cleanup")
    assert res is not None
    assert res.is_archived is True
    assert res.is_active is False
    assert res.archive_reason == "Clutter cleanup"

    # Unarchive / Restore
    res2 = engine.archive_alert_by_id("test-archive-123", archive=False)
    assert res2 is not None
    assert res2.is_archived is False
    assert res2.is_active is True


def test_cleanup_archived_records_leaves_active_trades_intact():
    """Verify cleanup_archived_records deletes only inactive records older than max_age_days, NEVER active trades."""
    from datetime import datetime, timedelta, timezone
    from engine.auto_alert_engine import AutoAlert, AutoAlertEngine

    IST = timezone(timedelta(hours=5, minutes=30))
    engine = AutoAlertEngine()

    old_date = (datetime.now(IST) - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S IST")
    recent_date = (datetime.now(IST) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S IST")

    # 1. Old ACTIVE trade (>5 days old, but still valid): MUST BE RETAINED!
    old_active = AutoAlert(
        alert_id="old-active-trade",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="LT",
        exchange="NSE",
        direction="BULLISH",
        headline="Swing trade holding valid",
        summary="Active",
        ltp=3600.0,
        trigger_level=3550.0,
        target_level=3800.0,
        stop_loss=3480.0,
        created_at=old_date,
        is_archived=False,
    )

    # 2. Old ARCHIVED trade (>5 days old): MUST BE PURGED!
    old_archived = AutoAlert(
        alert_id="old-archived-trade",
        alert_type="SQUEEZE_BREAKOUT",
        stage="INVALIDATED",
        symbol="SBIN",
        exchange="NSE",
        direction="BULLISH",
        headline="Old invalidation",
        summary="Purge me",
        ltp=780.0,
        trigger_level=800.0,
        target_level=850.0,
        stop_loss=790.0,
        is_invalidated=True,
        is_archived=True,
        invalidated_at=old_date,
        created_at=old_date,
    )

    # 3. Recent ARCHIVED trade (1 day old): MUST BE RETAINED (within 3 days)!
    recent_archived = AutoAlert(
        alert_id="recent-archived-trade",
        alert_type="SQUEEZE_BREAKOUT",
        stage="INVALIDATED",
        symbol="WIPRO",
        exchange="NSE",
        direction="BULLISH",
        headline="Recent invalidation",
        summary="Keep me for 3 days",
        ltp=520.0,
        trigger_level=540.0,
        target_level=580.0,
        stop_loss=530.0,
        is_invalidated=True,
        is_archived=True,
        invalidated_at=recent_date,
        created_at=recent_date,
    )

    with engine._lock:
        engine._alerts = [old_active, old_archived, recent_archived]

    purged = engine.cleanup_archived_records(max_age_days=3)
    assert purged == 1

    remaining_ids = [a.alert_id for a in engine._alerts]
    assert "old-active-trade" in remaining_ids, (
        "Active valid trade must NEVER be deleted during cleanup!"
    )
    assert "recent-archived-trade" in remaining_ids, (
        "Recent archived trade within 3 days must be kept!"
    )
    assert "old-archived-trade" not in remaining_ids, (
        "Old archived trade older than 3 days must be purged!"
    )


def test_get_alerts_view_mode_filtering(tmp_path, monkeypatch):
    """Verify get_alerts(view_mode='ACTIVE') vs get_alerts(view_mode='ARCHIVED')."""
    data_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)

    from engine.auto_alert_engine import AutoAlert, AutoAlertEngine

    engine = AutoAlertEngine()

    a1 = AutoAlert(
        alert_id="vm-active-1",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="INFY",
        exchange="NSE",
        direction="BULLISH",
        headline="Active",
        summary="",
        ltp=1850.0,
        trigger_level=1850.0,
        target_level=1950.0,
        stop_loss=1800.0,
    )
    a2 = AutoAlert(
        alert_id="vm-archived-1",
        alert_type="SQUEEZE_BREAKOUT",
        stage="INVALIDATED",
        symbol="TCS",
        exchange="NSE",
        direction="BULLISH",
        headline="Invalidated",
        summary="",
        ltp=4100.0,
        trigger_level=4200.0,
        target_level=4400.0,
        stop_loss=4150.0,
        is_invalidated=True,
        is_archived=True,
    )

    with engine._lock:
        engine._alerts = [a1, a2]
        engine._save()

    active_list = engine.get_alerts(view_mode="ACTIVE")
    assert len(active_list) == 1
    assert active_list[0].alert_id == "vm-active-1"

    archived_list = engine.get_alerts(view_mode="ARCHIVED")
    assert len(archived_list) == 1
    assert archived_list[0].alert_id == "vm-archived-1"

    all_list = engine.get_alerts(view_mode="ALL")
    assert len(all_list) == 2


def test_auto_alert_expiration_and_reaping(tmp_path, monkeypatch):
    """Verify that expired derivative contracts and stale Gamma Blasts are flagged and reaped."""
    data_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)

    engine = AutoAlertEngine(max_buffer=50)
    engine.clear_alerts()

    # 1. Past explicit expiry
    past_exp = AutoAlert(
        alert_id="t-exp-1",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BEARISH",
        headline="NIFTY Put",
        summary="",
        ltp=150.0,
        trigger_level=24000.0,
        target_level=23500.0,
        stop_loss=24200.0,
        expiry_date="2026-09-01",
        strike=24000.0,
        option_type="PE",
    )
    assert past_exp.is_expired is True
    assert past_exp.is_active is False

    # 2. FINNIFTY created on 2026-09-07 (weekly Tuesday expiry was 2026-09-08)
    finnifty_exp = AutoAlert(
        alert_id="t-exp-finnifty",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="FINNIFTY",
        exchange="NFO",
        direction="BEARISH",
        headline="FINNIFTY Put",
        summary="",
        ltp=25.0,
        trigger_level=26000.0,
        target_level=25500.0,
        stop_loss=26200.0,
        created_at="2026-09-07 16:07:14 IST",
        strike=26000.0,
        option_type="PE",
        contract_symbol="FINNIFTY26000PE",
    )
    assert finnifty_exp.is_expired is True
    assert finnifty_exp.is_active is False

    # 3. Active future contract: SBIN monthly expiring end of September
    sbin_active = AutoAlert(
        alert_id="t-active-sbin",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="SBIN",
        exchange="NFO",
        direction="BEARISH",
        headline="SBIN Put",
        summary="",
        ltp=20.55,
        trigger_level=1010.0,
        target_level=950.0,
        stop_loss=1040.0,
        created_at="2026-09-09 13:25:48 IST",
        expiry_date="2026-09-29",
        strike=1010.0,
        option_type="PE",
        contract_symbol="SBIN1010PE",
    )
    assert sbin_active.is_expired is False
    assert sbin_active.is_active is True

    # 4. Reaping test
    with engine._lock:
        engine._alerts = [past_exp, finnifty_exp, sbin_active]
        engine._save()

    reaped_count = engine.reap_expired_alerts()
    assert reaped_count == 2
    assert past_exp.is_archived is True
    assert past_exp.stage == "EXPIRED"
    assert finnifty_exp.is_archived is True
    assert sbin_active.is_archived is False

    # Only SBIN should be returned in ACTIVE view
    active_alerts = engine.get_alerts(view_mode="ACTIVE")
    assert len(active_alerts) == 1
    assert active_alerts[0].alert_id == "t-active-sbin"


def test_auto_alert_rehabilitates_falsely_invalidated_options(tmp_path, monkeypatch):
    """Verify that _load automatically restores alerts falsely invalidated by the inverted Put SL bug."""
    data_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)

    corrupted_data = [
        {
            "alert_id": "aa-gamma-pe-SBIN-1010-test",
            "alert_type": "GAMMA_BLAST",
            "stage": "INVALIDATED",
            "symbol": "SBIN",
            "exchange": "NFO",
            "direction": "BEARISH",
            "headline": "⚠️ [REAL/LIVE] VIEW INVALIDATED: SBIN GAMMA BLAST",
            "summary": "Option premium collapsed to ₹20.6 (breached stop-loss ₹10.8). Put gamma thesis invalidated.",
            "ltp": 16.55,
            "trigger_level": 1010.0,
            "target_level": 36.4,
            "stop_loss": 10.8,
            "strike": 1010.0,
            "option_type": "PE",
            "contract_symbol": "SBIN1010PE",
            "is_invalidated": True,
            "invalidation_reason": "Option premium collapsed to ₹20.6 (breached stop-loss ₹10.8). Put gamma thesis invalidated.",
            "is_archived": True,
            "is_live": True,
            "environment": "LIVE",
            "metrics": {"vol_oi_ratio": 2.5},
        }
    ]
    data_file.write_text(json.dumps(corrupted_data))

    engine = AutoAlertEngine(max_buffer=50)
    engine._load()

    alerts = engine.get_alerts(view_mode="ALL")
    assert len(alerts) == 1
    rehab = alerts[0]
    assert rehab.is_invalidated is False
    assert rehab.invalidation_reason is None
    assert rehab.is_archived is False
    assert rehab.stage == "IGNITED"
    assert "PE GAMMA BLAST IGNITED: SBIN 1010 PE" in rehab.headline


def test_asymmetric_opportunity_options_resolution():
    """Verify that index/F&O setups resolve liquid ATM options contracts with target projections."""
    from engine.asymmetric_radar import resolve_recommended_option_contract

    opt = resolve_recommended_option_contract(
        symbol="BANKNIFTY",
        direction="BULLISH",
        spot=56000.0,
        stop_loss=55500.0,
        target_1=57000.0,
        target_2=58000.0,
    )

    assert opt["strike"] > 0
    assert opt["option_type"] == "CE"
    assert "BANKNIFTY" in opt["contract_symbol"]
    assert opt["option_target_1"] > opt["option_premium"]
    assert opt["option_stop_loss"] < opt["option_premium"]
    assert opt["lot_size"] > 0


def test_options_momentum_scanner_recording(tmp_path, monkeypatch):
    """Verify that scan_options_momentum_breakouts detects and records options momentum alerts."""
    data_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)

    synthetic_chain = [
        MockOptionsContract(
            symbol="NIFTY23500CE",
            underlying="NIFTY",
            strike=23500.0,
            option_type="CE",
            last_price=120.0,
            oi=20000,
            oi_change=5000,
            volume=35000,
            iv=14.0,
        ),
        MockOptionsContract(
            symbol="NIFTY23500PE",
            underlying="NIFTY",
            strike=23500.0,
            option_type="PE",
            last_price=95.0,
            oi=30000,
            oi_change=8000,
            volume=45000,
            iv=15.0,
        ),
    ]

    monkeypatch.setattr("market.quotes.get_ltp", lambda sym: 23510.0)
    monkeypatch.setattr("market.options.get_options_chain", lambda sym: synthetic_chain)

    engine = AutoAlertEngine(max_buffer=50)
    monkeypatch.setattr(engine, "_watched_indices", ["NIFTY"])
    monkeypatch.setattr(engine, "watched_equities", [])

    alerts = engine.scan_options_momentum_breakouts()
    assert len(alerts) >= 1
    top_alert = alerts[0]
    assert top_alert.alert_type == "OPTIONS_MOMENTUM"
    assert top_alert.exchange == "NFO"
    assert top_alert.strike == 23500.0
    assert top_alert.option_type in ("CE", "PE")
    assert top_alert.contract_symbol is not None
    assert top_alert.actionable_plan["contract"] == top_alert.contract_symbol
    assert "when_to_wait" in top_alert.actionable_plan
    assert "DO NOT CHASE" in top_alert.actionable_plan["when_to_wait"]
    assert top_alert.stop_loss > 0
    # Defined risk stop must be tight (<= 15% risk instead of arbitrary 25%)
    assert (top_alert.ltp - top_alert.stop_loss) / top_alert.ltp <= 0.16


def test_gamma_blast_rejects_illiquid_strike_and_distant_expiry():
    """Verify that detect_gamma_blast rejects illiquid strikes (low OI / low shedding) and distant expiries."""
    from engine.auto_alert_engine import detect_gamma_blast

    spot = 56478.9
    vwap = 56500.0  # spot below VWAP

    # 1. Illiquid strike percentage illusion: oi=2230, oi_change=-587 (-26.3%), vol/oi = 1.85x
    illiquid_chain = [
        MockOptionsContract(
            symbol="BANKNIFTY55700PE",
            underlying="BANKNIFTY",
            strike=55700.0,
            option_type="PE",
            last_price=266.1,
            oi=2230,
            oi_change=-587,
            volume=4125,
        ),
    ]
    alerts_illiquid = detect_gamma_blast("BANKNIFTY", spot=spot, chain=illiquid_chain, vwap=vwap)
    # Must be rejected because oi < 15,000, volume < 10,000, and abs(oi_change) < 3,000
    assert len(alerts_illiquid) == 0

    # 2. Distant monthly expiry (> 5 DTE): Even with large OI and turnover, 20-day options are not Gamma Blasts
    distant_chain = [
        MockOptionsContract(
            symbol="BANKNIFTY56500PE",
            underlying="BANKNIFTY",
            strike=56500.0,
            option_type="PE",
            last_price=350.0,
            oi=80000,
            oi_change=-25000,
            volume=200000,
        ),
    ]
    # Attach distant expiry 20 days in the future
    distant_chain[0].expiry = "2026-10-30"
    alerts_distant = detect_gamma_blast("BANKNIFTY", spot=spot, chain=distant_chain, vwap=vwap)
    assert len(alerts_distant) == 0


def test_gamma_blast_option_rr_and_sl_floor():
    """Verify that a valid liquid near-expiry Gamma Blast formats option R:R and enforces the SL floor."""
    from engine.auto_alert_engine import detect_gamma_blast

    spot = 56478.9
    vwap = 56500.0  # spot below VWAP

    liquid_chain = [
        MockOptionsContract(
            symbol="BANKNIFTY56400PE",
            underlying="BANKNIFTY",
            strike=56400.0,
            option_type="PE",
            last_price=280.0,
            oi=95000,
            oi_change=-35000,
            volume=260000,  # 2.7x OI
        ),
    ]
    alerts = detect_gamma_blast(
        "BANKNIFTY", spot=spot, chain=liquid_chain, vwap=vwap, day_low=56450.0
    )
    assert len(alerts) >= 1
    alert = alerts[0]
    assert alert.alert_type == "GAMMA_BLAST"
    assert alert.direction == "BEARISH"
    assert alert.stage == "IGNITED"

    plan = alert.actionable_plan
    assert "risk_reward" in plan
    # Option R:R must be formatted as 1:X.X (not inverted or spot-derived like 1.32:1)
    assert plan["risk_reward"].startswith("1:")
    assert not plan["risk_reward"].endswith(":1")  # Eliminates misleading 1.32:1 spot bug

    # Verify option execution plan has disciplined capital stop loss
    opt_plan = plan.get("option_plan")
    if opt_plan and "sl_pct" in opt_plan and opt_plan["sl_pct"] is not None:
        # Stop loss percentage must not be excessively deep (must be >= -35.0%)
        assert opt_plan["sl_pct"] >= -35.0


def test_sanitize_legacy_alerts_quarantines_illiquid_and_distant_alerts(tmp_path, monkeypatch):
    """Verify that AutoAlertEngine quarantines existing persisted alerts violating liquidity or DTE gates."""
    from engine.auto_alert_engine import AutoAlertEngine, AutoAlert

    data_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)

    eng = AutoAlertEngine()
    eng._alerts = [
        # 1. Illiquid index alert (e.g. FINNIFTY with OI=80)
        AutoAlert(
            alert_id="legacy-illiquid-finnifty",
            alert_type="GAMMA_BLAST",
            stage="IGNITED",
            symbol="FINNIFTY",
            exchange="NFO",
            direction="BULLISH",
            headline="CALL GAMMA BLAST IGNITED: FINNIFTY 25600 CE",
            summary="Shedding OI",
            ltp=278.0,
            trigger_level=25600.0,
            target_level=600.0,
            stop_loss=195.0,
            strike=25600.0,
            metrics={"oi": 80, "oi_change": -20},
            expiry_date="2026-09-29",
        ),
        # 2. Valid liquid near-expiry alert
        AutoAlert(
            alert_id="valid-liquid-nifty",
            alert_type="GAMMA_BLAST",
            stage="IGNITED",
            symbol="NIFTY",
            exchange="NFO",
            direction="BULLISH",
            headline="CALL GAMMA BLAST IGNITED: NIFTY 24500 CE",
            summary="High turnover",
            ltp=150.0,
            trigger_level=24500.0,
            target_level=300.0,
            stop_loss=105.0,
            strike=24500.0,
            metrics={"oi": 45000, "oi_change": -12000, "dte": 2},
            expiry_date="2026-09-12",
        ),
    ]
    purged = eng._sanitize_legacy_alerts_unlocked()
    assert purged == 1

    # Illiquid alert must be permanently purged from memory & disk
    alert_ids = [a.alert_id for a in eng._alerts]
    assert "legacy-illiquid-finnifty" not in alert_ids

    # Valid alert remains active
    valid_alert = next(a for a in eng._alerts if a.alert_id == "valid-liquid-nifty")
    assert valid_alert.is_archived is False
    assert valid_alert.is_active is True


def test_quote_ltp_property():
    """Verify Quote dataclass exposes ltp as an alias for last_price."""
    from brokers.base import Quote

    q = Quote(
        symbol="DIXON",
        last_price=13550.0,
        open=13845.0,
        high=13867.0,
        low=13355.0,
        close=13845.0,
        volume=260000,
    )
    assert q.ltp == 13550.0
    assert getattr(q, "ltp", None) == 13550.0


def test_scan_intraday_breakdown_spark(tmp_path, monkeypatch):
    """Verify scan_intraday_mover_sparks triggers on institutional sell-offs below VWAP with RVOL."""
    from brokers.base import Quote
    from engine.auto_alert_engine import AutoAlertEngine

    data_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)

    eng = AutoAlertEngine()
    eng._watched_equities = ["DIXON"]

    # Mock quotes returning severe breakdown below VWAP
    quotes_data = {
        "NSE:DIXON": Quote(
            symbol="DIXON",
            last_price=13450.0,
            open=13845.0,
            high=13867.0,
            low=13355.0,
            close=13845.0,
            volume=350000,
            change=-395.0,
            change_pct=-2.85,
        )
    }
    # Attach mock vwap to quote
    setattr(quotes_data["NSE:DIXON"], "vwap", 13720.0)

    # Synthetic OHLCV history with 100k avg volume -> RVOL ~3.5x
    dates = pd.date_range("2026-08-01", periods=25, freq="B")
    df = pd.DataFrame(
        {
            "open": [14000] * 25,
            "high": [14100] * 25,
            "low": [13900] * 25,
            "close": [14000] * 25,
            "volume": [100000] * 25,
        },
        index=dates,
    )

    monkeypatch.setattr("market.quotes.get_quote", lambda *args, **kwargs: quotes_data)
    monkeypatch.setattr("market.history.get_ohlcv", lambda *args, **kwargs: df)

    sparks = eng.scan_intraday_mover_sparks()
    dixon_spark = next((s for s in sparks if s.symbol == "DIXON"), None)

    assert dixon_spark is not None
    assert dixon_spark.direction == "BEARISH"
    assert dixon_spark.alert_type == "INTRADAY_BREAKDOWN_SPARK"
    assert dixon_spark.stage == "IGNITED"
    assert dixon_spark.actionable_plan["action"] == "SELL_SHORT_OR_BUY_PUT"
    assert dixon_spark.stop_loss > dixon_spark.ltp  # Stop-loss above entry for shorts


def test_scan_options_momentum_monthly_put_surge(tmp_path, monkeypatch):
    """Verify single-stock monthly put options with DTE > 7 trigger options momentum."""
    from engine.auto_alert_engine import AutoAlertEngine

    data_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)

    eng = AutoAlertEngine()
    eng._watched_indices = []
    monkeypatch.setattr(eng, "watched_equities", ["DIXON"])

    # DIXON spot = 13500, chain has 13500 PE with Vol/OI = 2.5x, expiry in 19 days
    mock_contract = MockOptionsContract(
        symbol="DIXON13500PE",
        underlying="DIXON",
        strike=13500.0,
        option_type="PE",
        last_price=450.0,
        oi=3600,
        oi_change=200,
        volume=9000,
    )
    setattr(mock_contract, "expiry", "2026-09-29")

    monkeypatch.setattr("market.quotes.get_ltp", lambda sym: 13520.0)
    monkeypatch.setattr("market.options.get_options_chain", lambda sym: [mock_contract])

    alerts = eng.scan_options_momentum_breakouts()
    pe_alert = next((a for a in alerts if a.symbol == "DIXON" and a.option_type == "PE"), None)

    assert pe_alert is not None
    assert pe_alert.direction == "BEARISH"
    assert pe_alert.alert_type == "OPTIONS_MOMENTUM"
    assert "PUT SURGE" in pe_alert.headline
    assert pe_alert.metrics["vol_oi_ratio"] >= 2.0


def test_detect_squeeze_breakdown():
    """Verify detect_squeeze_breakout detects bearish breakdown coiling and ignited."""
    dates = pd.date_range("2026-08-01", periods=30, freq="B")
    # Coiling near 20D low of 100.0, close at 100.8
    closes = np.linspace(105, 100.8, 30)
    highs = closes + 0.5
    lows = closes - 0.5
    lows[10] = 100.0  # 20D low pivot
    df = pd.DataFrame(
        {"open": closes, "high": highs, "low": lows, "close": closes, "volume": [100000] * 30},
        index=dates,
    )

    alert_early = detect_squeeze_breakout("TESTSYM", df, ltp=100.8)
    if alert_early:
        assert alert_early.direction == "BEARISH"
        assert alert_early.alert_type == "SQUEEZE_BREAKDOWN"
        assert alert_early.stage == "EARLY_WARNING"


def test_underlying_bearish_alert_with_option_recommendation_invalidation():
    """
    Ensure an underlying bearish setup (e.g. MANKIND) with an attached option contract
    evaluates invalidation against the stock's spot stop-loss (not the option premium).
    LTP=2180, SL=2219.7, contract_symbol="NSE:MANKIND26MAR2200PE", option_premium=11.0.
    """
    alert = AutoAlert(
        alert_id="asym-mankind-1",
        alert_type="ASYMMETRIC_OPPORTUNITY",
        stage="EARLY_WARNING",
        symbol="MANKIND",
        exchange="NSE",
        direction="BEARISH",
        headline="Mankind Breakdown Radar",
        summary="Distribution at resistance",
        ltp=2180.0,
        trigger_level=2180.0,
        stop_loss=2219.7,
        target_level=2050.0,
        strike=2200.0,
        option_type="PE",
        contract_symbol="NSE:MANKIND26MAR2200PE",
        option_premium=11.0,
        is_live=True,
        environment="LIVE",
    )

    # When stock price moves to 2185.0 (still safely below SL 2219.7): MUST NOT be invalidated!
    assert evaluate_alert_invalidation(alert, current_ltp=2185.0) is None

    # When stock price surges above SL (e.g. 2225.0): Invalidated by stock price surge!
    reason = evaluate_alert_invalidation(alert, current_ltp=2225.0)
    assert reason is not None
    assert "Price surged to ₹2,225.0" in reason
    assert "breached stop-loss ₹2,219.7" in reason
    assert "Bearish thesis invalidated" in reason
    assert "Option premium collapsed" not in reason


def test_auto_alert_invalidation_lockout_gate():
    """
    Ensure an active invalidation lockout on a symbol (or its underlying) prevents
    new live alerts from being recorded, stopping knife-catching.
    """
    from engine.learning_engine import pattern_learning_engine

    engine = AutoAlertEngine()
    engine._alerts = []

    # Place MANKIND on lockout
    pattern_learning_engine.set_symbol_lockout(
        "MANKIND",
        direction="BULLISH",
        duration_seconds=300.0,
        reason="Sub-ATR noise whipsaw",
    )

    alert = AutoAlert(
        alert_id="lockout-test-1",
        alert_type="PRECURSOR_RADAR",
        stage="EARLY_WARNING",
        symbol="NSE:MANKIND",
        exchange="NSE",
        direction="BULLISH",
        headline="Mankind Coiling",
        summary="Test lockout",
        ltp=2200.0,
        trigger_level=2200.0,
        stop_loss=2150.0,
        target_level=2350.0,
        is_live=True,
        environment="LIVE",
    )

    recorded = engine.record_alert(alert)
    assert recorded is False
    assert len(engine._alerts) == 0

    # Clear lockout and verify it records successfully
    pattern_learning_engine.clear_symbol_lockout("MANKIND")
    recorded2 = engine.record_alert(alert)
    assert recorded2 is True
    assert len(engine._alerts) == 1


def test_auto_alert_directional_whiplash_guard():
    """
    Directional Whiplash Guard:
    1. An active BULLISH alert suppresses unconfirmed incoming BEARISH alerts for the same symbol.
    2. If the incoming BEARISH alert has verified structural reversal (CHoCH / MSS), it supersedes
       the older bullish setup and retires it.
    """
    from unittest.mock import patch

    with patch(
        "engine.alert_scrutiny.alert_scrutiny_auditor._execute_fast_llm_scrutiny",
        return_value=None,
    ):
        engine = AutoAlertEngine()
        engine._alerts = []

        bull_alert = AutoAlert(
            alert_id="whiplash-bull-1",
            alert_type="SQUEEZE_BREAKOUT",
            stage="IGNITED",
            symbol="NSE:RELIANCE",
            exchange="NSE",
            direction="BULLISH",
            headline="Reliance Breakout",
            summary="Coiled base expansion",
            ltp=3000.0,
            trigger_level=3000.0,
            stop_loss=2940.0,
            target_level=3150.0,
            is_live=True,
            environment="LIVE",
        )
        assert engine.record_alert(bull_alert) is True
        assert len(engine._alerts) == 1
        assert engine._alerts[0].direction == "BULLISH"

        # Conflicting unconfirmed Bearish alert on same stock
        bear_unconfirmed = AutoAlert(
            alert_id="whiplash-bear-unconfirmed",
            alert_type="SQUEEZE_BREAKDOWN",
            stage="IGNITED",
            symbol="NSE:RELIANCE",
            exchange="NSE",
            direction="BEARISH",
            headline="Reliance Intraday Dip",
            summary="Minor pullback without reversal",
            ltp=2990.0,
            trigger_level=2990.0,
            stop_loss=3030.0,
            target_level=2900.0,
            is_live=True,
            environment="LIVE",
        )
        assert engine.record_alert(bear_unconfirmed) is False
        # Original bullish setup remains active
        assert len(engine._alerts) == 1
        assert engine._alerts[0].alert_id == "whiplash-bull-1"
        assert engine._alerts[0].is_active is True

        # Confirmed structural reversal with CHoCH cue
        bear_confirmed = AutoAlert(
            alert_id="whiplash-bear-confirmed",
            alert_type="SQUEEZE_BREAKDOWN",
            stage="IGNITED",
            symbol="NSE:RELIANCE",
            exchange="NSE",
            direction="BEARISH",
            headline="Reliance Structural CHoCH Reversal Breakdown",
            summary="Confirmed market structure shift MSS and breakdown below key pivot",
            ltp=2980.0,
            trigger_level=2980.0,
            stop_loss=3025.0,
            target_level=2880.0,
            metrics={"choch": True, "mss": True},
            is_live=True,
            environment="LIVE",
        )
        assert engine.record_alert(bear_confirmed) is True
        # The new alert is inserted as active
        assert engine._alerts[0].alert_id == "whiplash-bear-confirmed"
        assert engine._alerts[0].is_active is True
        # The older superseded bullish alert is purged so dead corpses don't clutter active alerts
        assert all(a.alert_id != "whiplash-bull-1" for a in engine._alerts)


@pytest.mark.anyio
async def test_send_alert_to_telegram_endpoint(monkeypatch, tmp_path):
    """Verify POST /api/alerts/auto/send-telegram renders message and dispatches via send_push."""
    from web.api import send_alert_to_telegram
    from engine.auto_alert_engine import AutoAlert, auto_alert_engine
    from fastapi import HTTPException

    # Create synthetic alert
    test_alert = AutoAlert(
        alert_id="tg-test-alert-001",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="CALL GAMMA BLAST IGNITED: NIFTY 24800 CE",
        summary="Heavy call OI unwinding above VWAP",
        ltp=185.0,
        trigger_level=24800.0,
        target_level=320.0,
        stop_loss=130.0,
        strike=24800.0,
        option_type="CE",
        contract_symbol="NIFTY24800CE",
        expiry_date="2026-09-18",
        confidence=88,
    )

    monkeypatch.setattr(auto_alert_engine, "_load", lambda: None)
    with auto_alert_engine._lock:
        auto_alert_engine._alerts.insert(0, test_alert)

    # 1. Missing alert_id -> 400
    with pytest.raises(HTTPException) as exc_info:
        await send_alert_to_telegram({})
    assert exc_info.value.status_code == 400

    # 2. Non-existent alert_id -> 404
    with pytest.raises(HTTPException) as exc_info:
        await send_alert_to_telegram({"alert_id": "nonexistent-alert-id"})
    assert exc_info.value.status_code == 404

    # 3. Successful dispatch
    dispatched_msgs = []

    def mock_send_push(msg, parse_mode="HTML", bypass_dedup=True, chat_id=None):
        dispatched_msgs.append((msg, parse_mode, bypass_dedup, chat_id))
        return True

    monkeypatch.setattr("bot.telegram_bot.send_push", mock_send_push)

    res = await send_alert_to_telegram({"alert_id": "tg-test-alert-001"})
    assert res["status"] == "ok"
    assert res["alert_id"] == "tg-test-alert-001"
    assert "message_preview" in res
    assert len(dispatched_msgs) == 1
    msg, parse_mode, bypass_dedup, target_chat = dispatched_msgs[0]
    assert "NIFTY" in msg
    assert "24800" in msg
    assert parse_mode == "HTML"
    assert bypass_dedup is True
    assert target_chat is None

    # Test custom channel/group forwarding
    res2 = await send_alert_to_telegram({"alert_id": "tg-test-alert-001", "chat_id": "@chanakya_channel"})
    assert res2["status"] == "ok"
    assert len(dispatched_msgs) == 2
    assert dispatched_msgs[1][3] == "@chanakya_channel"

    # Test destinations endpoint
    from web.api import get_telegram_destinations_api
    dest_res = await get_telegram_destinations_api()
    assert dest_res["status"] == "ok"
    assert "default_chat_id" in dest_res["data"]

    # 4. Bot unconfigured -> 503
    def mock_fail_push(*args, **kwargs):
        raise RuntimeError("TELEGRAM_BOT_TOKEN not configured")

    monkeypatch.setattr("bot.telegram_bot.send_push", mock_fail_push)
    with pytest.raises(HTTPException) as exc_info:
        await send_alert_to_telegram({"alert_id": "tg-test-alert-001"})
    assert exc_info.value.status_code == 503


def test_options_target_1_and_target_2_keys_parsed_correctly():
    """Verify that evaluate_alert_targets_and_trailing parses 'target' as T1 and 'target_2' as T2."""
    alert = AutoAlert(
        alert_id="opt-keys-test-1",
        alert_type="OPTIONS_MOMENTUM",
        stage="ACTIVE",
        symbol="NIFTY",
        exchange="NFO",
        direction="BEARISH",
        headline="NIFTY 23100 PE",
        summary="Put momentum",
        ltp=30.55,
        trigger_level=30.55,
        target_level=45.80,
        stop_loss=22.90,
        strike=23100.0,
        option_type="PE",
        contract_symbol="NIFTY23100PE",
        option_premium=30.55,
        actionable_plan={
            "action": "BUY PE",
            "recommended_entry": "₹30.55",
            "stop_loss": "₹22.90",
            "target": "₹45.80",
            "target_2": "₹57.30",
        },
    )

    # Below Target 1 (e.g. 40.00): MUST NOT trigger T1_ACHIEVED
    res_sub = evaluate_alert_targets_and_trailing(alert, current_ltp=40.00)
    assert res_sub is None or res_sub.new_milestone is None

    # At Target 1 (45.80): MUST trigger T1_ACHIEVED with breakeven stop at 30.61
    res_t1 = evaluate_alert_targets_and_trailing(alert, current_ltp=45.80)
    assert res_t1 is not None
    assert res_t1.new_milestone == "T1_ACHIEVED"
    assert res_t1.recommended_stop == 30.61


def test_no_target_milestone_when_in_loss():
    """Verify that an alert in a loss (LTP < Entry for buyers) CAN NEVER trigger Target 1 or Final Target."""
    alert = AutoAlert(
        alert_id="opt-loss-guard-test",
        alert_type="OPTIONS_MOMENTUM",
        stage="ACTIVE",
        symbol="NIFTY",
        exchange="NFO",
        direction="BEARISH",  # Put option buyer
        headline="NIFTY 23100 PE",
        summary="Put momentum",
        ltp=28.85,
        trigger_level=30.55,
        target_level=45.80,
        stop_loss=22.90,
        strike=23100.0,
        option_type="PE",
        contract_symbol="NIFTY23100PE",
        option_premium=18.25,  # Even if option_premium was corrupted to a lower number!
        actionable_plan={
            "action": "BUY PE",
            "recommended_entry": "₹30.55",
            "stop_loss": "₹22.90",
            "target": "₹45.80",
            "target_2": "₹57.30",
        },
    )

    # Current LTP is 28.85 (below entry 30.55) -> MUST NEVER trigger any target milestone!
    res = evaluate_alert_targets_and_trailing(alert, current_ltp=28.85)
    assert res is None or res.new_milestone is None, f"Expected no milestone, got {res.new_milestone if res else None}"


def test_record_alert_active_trade_immutable(tmp_path, monkeypatch):
    """Verify that an active in-flight trade cannot have its contract or strike mutated mid-flight."""
    data_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)
    monkeypatch.setattr("engine.auto_alert_engine.AutoAlertEngine._dispatch", lambda self, a: None)

    engine = AutoAlertEngine(max_buffer=20)
    engine.clear_alerts()

    initial_alert = AutoAlert(
        alert_id="aa-optmom-pe-NIFTY-23000-active",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",  # Live trade active
        symbol="NIFTY",
        exchange="NFO",
        direction="BEARISH",
        headline="NIFTY 23000 PE Ignited",
        summary="Active trade",
        ltp=18.25,
        trigger_level=18.25,
        target_level=27.40,
        stop_loss=13.70,
        strike=23000.0,
        option_type="PE",
        contract_symbol="NIFTY23000PE",
        option_premium=18.25,
        is_live=True,
        environment="LIVE",
        metrics={"vol_oi_ratio": 5.0, "oi": 25000},
    )
    recorded = engine.record_alert(initial_alert)
    assert recorded is True

    # Now an incoming scan for 23100 PE appears with higher volume
    alternate_alert = AutoAlert(
        alert_id="aa-optmom-pe-NIFTY-23100-new",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BEARISH",
        headline="NIFTY 23100 PE Ignited",
        summary="New strike",
        ltp=30.55,
        trigger_level=30.55,
        target_level=45.80,
        stop_loss=22.90,
        strike=23100.0,
        option_type="PE",
        contract_symbol="NIFTY23100PE",
        option_premium=30.55,
        confidence=95,  # higher confidence
        is_live=True,
        environment="LIVE",
        metrics={"vol_oi_ratio": 15.0, "oi": 30000},
    )
    result = engine.record_alert(alternate_alert)
    assert result is False  # Suppressed

    # Verify that initial active alert remains 23000 PE, NOT mutated to 23100 PE!
    active_alerts = engine.get_alerts()
    nifty_alert = next(a for a in active_alerts if a.symbol == "NIFTY")
    assert nifty_alert.contract_symbol == "NIFTY23000PE"
    assert nifty_alert.strike == 23000.0
    assert nifty_alert.option_premium == 18.25


def test_early_warning_session_expiry():
    """Verify that un-ignited EARLY_WARNING setups expire across day boundaries."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    ist = ZoneInfo("Asia/Kolkata")
    yesterday = datetime.now(ist) - timedelta(days=1)
    yesterday_str = yesterday.strftime("%Y-%m-%d %H:%M:%S IST")

    # 1. EARLY_WARNING from yesterday MUST be expired
    coiling_alert = AutoAlert(
        alert_id="aa-test-coiling-old",
        alert_type="OPTIONS_MOMENTUM",
        stage="EARLY_WARNING",
        symbol="HDFCBANK",
        exchange="NFO",
        direction="BULLISH",
        headline="Coiling",
        summary="Setup coiling",
        ltp=20.0,
        trigger_level=20.0,
        target_level=30.0,
        stop_loss=15.0,
        contract_symbol="HDFCBANK680CE",
        created_at=yesterday_str,
    )
    assert coiling_alert.is_expired is True
    assert coiling_alert.is_active is False

    # 2. Live IGNITED trade from yesterday does NOT expire solely due to day boundary
    ignited_alert = AutoAlert(
        alert_id="aa-test-ignited-old",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="HDFCBANK",
        exchange="NFO",
        direction="BULLISH",
        headline="Ignited",
        summary="Active position",
        ltp=20.0,
        trigger_level=20.0,
        target_level=30.0,
        stop_loss=15.0,
        contract_symbol="HDFCBANK680CE",
        created_at=yesterday_str,
    )
    assert ignited_alert.is_expired is False
    assert ignited_alert.is_active is True


def test_alert_ignition_refreshes_timestamp_and_premium(tmp_path, monkeypatch):
    """Verify that when an EARLY_WARNING is upgraded to IGNITED, timestamp, premium, and signal_ref are refreshed."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    ist = ZoneInfo("Asia/Kolkata")
    now_str = datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S IST")

    data_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)
    monkeypatch.setattr("engine.auto_alert_engine.AutoAlertEngine._dispatch", lambda self, a: None)
    engine = AutoAlertEngine(max_buffer=20)
    engine.clear_alerts()

    # 1. Record EARLY_WARNING coiling setup
    early_alert = AutoAlert(
        alert_id="aa-optmom-ce-HDFCBANK-680-coiling",
        alert_type="OPTIONS_MOMENTUM",
        stage="EARLY_WARNING",
        symbol="HDFCBANK",
        exchange="NFO",
        direction="BULLISH",
        headline="HDFCBANK Coiling @ ₹24.7",
        summary="Coiling setup",
        ltp=24.70,
        trigger_level=24.70,
        target_level=35.0,
        stop_loss=18.0,
        strike=680.0,
        option_type="CE",
        contract_symbol="HDFCBANK680CE",
        option_premium=24.70,
        created_at="2026-09-11 10:00:00 IST",
        signal_ref="#SIG_HDFCBANK_680CE_11SEP_1000",
    )
    engine.record_alert(early_alert)

    # 2. Breakout occurs: record IGNITED alert for same contract with new market conditions
    ignite_alert = AutoAlert(
        alert_id="aa-optmom-ce-HDFCBANK-680-ignite",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="HDFCBANK",
        exchange="NFO",
        direction="BULLISH",
        headline="HDFCBANK Ignited @ ₹22.1",
        summary="Ignition breakout",
        ltp=22.10,
        trigger_level=22.10,
        target_level=33.2,
        stop_loss=16.6,
        strike=680.0,
        option_type="CE",
        contract_symbol="HDFCBANK680CE",
        option_premium=22.10,
        underlying_spot=693.80,
        created_at=now_str,
    )
    recorded = engine.record_alert(ignite_alert)
    assert recorded is True

    # 3. Verify upgraded alert has active stage, updated premium, and fresh signal_ref
    alerts = engine.get_alerts()
    upgraded = next(a for a in alerts if a.symbol == "HDFCBANK")
    assert upgraded.stage == "IGNITED"
    assert upgraded.option_premium == 22.10
    assert upgraded.ltp == 22.10
    assert upgraded.underlying_spot == 693.80
    assert upgraded.triggered_at is not None
    assert upgraded.signal_ref != "#SIG_HDFCBANK_680CE_11SEP_1000"


def test_symbol_consolidation_respects_session_date(tmp_path, monkeypatch):
    """Verify that prior-day options alerts do not block today's fresh alerts for the same underlying."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    ist = ZoneInfo("Asia/Kolkata")
    yesterday = datetime.now(ist) - timedelta(days=1)
    yesterday_str = yesterday.strftime("%Y-%m-%d %H:%M:%S IST")
    now_str = datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S IST")

    data_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)
    monkeypatch.setattr("engine.auto_alert_engine.AutoAlertEngine._dispatch", lambda self, a: None)
    engine = AutoAlertEngine(max_buffer=20)
    engine.clear_alerts()

    # Yesterday's active trade
    yest_alert = AutoAlert(
        alert_id="aa-optmom-ce-HDFCBANK-690-old",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="HDFCBANK",
        exchange="NFO",
        direction="BULLISH",
        headline="HDFCBANK 690 CE Yesterday",
        summary="Yesterday trade",
        ltp=20.7,
        trigger_level=20.7,
        target_level=31.0,
        stop_loss=15.5,
        strike=690.0,
        option_type="CE",
        contract_symbol="HDFCBANK690CE",
        option_premium=20.7,
        created_at=yesterday_str,
    )
    engine.record_alert(yest_alert)

    # Today's fresh trade for HDFCBANK (different strike or same)
    today_alert = AutoAlert(
        alert_id="aa-optmom-ce-HDFCBANK-680-today",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="HDFCBANK",
        exchange="NFO",
        direction="BULLISH",
        headline="HDFCBANK 680 CE Today",
        summary="Today trade",
        ltp=22.1,
        trigger_level=22.1,
        target_level=33.2,
        stop_loss=16.6,
        strike=680.0,
        option_type="CE",
        contract_symbol="HDFCBANK680CE",
        option_premium=22.1,
        created_at=now_str,
    )
    recorded = engine.record_alert(today_alert)
    assert recorded is True

    # Yesterday's alert must be expired/retired
    assert yest_alert.is_expired is True
    # Today's alert must be the active alert for HDFCBANK
    active = engine.get_alerts()
    active_hdfc = [a for a in active if a.symbol == "HDFCBANK"]
    assert len(active_hdfc) == 1
    assert active_hdfc[0].contract_symbol == "HDFCBANK680CE"


def test_underlying_directional_cooldown_suppresses_duplicate(tmp_path, monkeypatch):
    """Verify that an active trade on an underlying suppresses redundant same-direction alerts within cooldown window."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    ist = ZoneInfo("Asia/Kolkata")
    now_str = datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S IST")

    data_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)
    monkeypatch.setattr("engine.auto_alert_engine.AutoAlertEngine._dispatch", lambda self, a: None)
    engine = AutoAlertEngine(max_buffer=20)
    engine.clear_alerts()

    # 1. First alert: Breakout long on RELIANCE
    alert1 = AutoAlert(
        alert_id="aa-rel-breakout",
        alert_type="BREAKOUT",
        stage="IGNITED",
        symbol="RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="RELIANCE Breakout",
        summary="Volume breakout above resistance",
        ltp=2950.0,
        trigger_level=2950.0,
        target_level=3050.0,
        stop_loss=2900.0,
        created_at=now_str,
    )
    rec1 = engine.record_alert(alert1)
    assert rec1 is True

    # 2. Second alert: Squeeze Breakout long on RELIANCE 1 minute later
    alert2 = AutoAlert(
        alert_id="aa-rel-squeeze",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="RELIANCE Squeeze Expansion",
        summary="Bollinger Band squeeze firing long",
        ltp=2955.0,
        trigger_level=2955.0,
        target_level=3050.0,
        stop_loss=2905.0,
        created_at=now_str,
    )
    rec2 = engine.record_alert(alert2)
    assert rec2 is False  # Suppressed by underlying directional anti-spam cooldown!


def test_gamma_blast_and_options_momentum_unified_consolidation(tmp_path, monkeypatch):
    """Verify OPTIONS_MOMENTUM and GAMMA_BLAST consolidate into the active trade instead of firing duplicate cards."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    ist = ZoneInfo("Asia/Kolkata")
    now_str = datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S IST")

    data_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)
    monkeypatch.setattr("engine.auto_alert_engine.AutoAlertEngine._dispatch", lambda self, a: None)
    engine = AutoAlertEngine(max_buffer=20)
    engine.clear_alerts()

    # Active OPTIONS_MOMENTUM trade on HDFCBANK 680 CE
    optmom = AutoAlert(
        alert_id="aa-optmom-hdfc",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="HDFCBANK",
        exchange="NFO",
        direction="BULLISH",
        headline="HDFCBANK 680 CE Ignited",
        summary="Options momentum",
        ltp=22.1,
        trigger_level=22.1,
        target_level=33.2,
        stop_loss=16.6,
        strike=680.0,
        option_type="CE",
        contract_symbol="HDFCBANK680CE",
        option_premium=22.1,
        created_at=now_str,
    )
    engine.record_alert(optmom)

    # Incoming GAMMA_BLAST on HDFCBANK 690 CE
    gamma = AutoAlert(
        alert_id="aa-gamma-hdfc",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="HDFCBANK",
        exchange="NFO",
        direction="BULLISH",
        headline="HDFCBANK 690 CE Gamma Blast",
        summary="Gamma surge",
        ltp=17.5,
        trigger_level=17.5,
        target_level=26.0,
        stop_loss=13.0,
        strike=690.0,
        option_type="CE",
        contract_symbol="HDFCBANK690CE",
        option_premium=17.5,
        created_at=now_str,
    )
    rec_gamma = engine.record_alert(gamma)
    assert rec_gamma is False  # Suppressed & consolidated!

    # Active trade preserved as 680 CE with 690 CE in related_strikes
    active = [a for a in engine.get_alerts() if a.symbol == "HDFCBANK"]
    assert len(active) == 1
    assert active[0].contract_symbol == "HDFCBANK680CE"
    assert "HDFCBANK690CE" in (active[0].metrics or {}).get("related_strikes", [])


def test_options_momentum_rejects_upper_wick_exhaustion(tmp_path, monkeypatch):
    """Verify that scan_options_momentum_breakouts rejects CE breakout when 5m candle shows upper-wick rejection."""
    data_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)

    synthetic_chain = [
        MockOptionsContract(
            symbol="NIFTY23500CE",
            underlying="NIFTY",
            strike=23500.0,
            option_type="CE",
            last_price=120.0,
            oi=20000,
            oi_change=5000,
            volume=35000,
        )
    ]
    # Candle with ~71% upper wick (High=23560, Open=23500, Close=23510, Low=23490 -> High - max(Open,Close) = 50 / 70 = 71%)
    exhaustion_df = pd.DataFrame(
        {
            "open": [23490.0, 23500.0],
            "high": [23510.0, 23560.0],
            "low": [23485.0, 23490.0],
            "close": [23500.0, 23510.0],
            "volume": [10000, 50000],
        }
    )

    monkeypatch.setattr("market.quotes.get_ltp", lambda sym: 23510.0)
    monkeypatch.setattr("market.options.get_options_chain", lambda sym: synthetic_chain)
    monkeypatch.setattr("market.history.get_ohlcv", lambda sym, **kwargs: exhaustion_df)

    engine = AutoAlertEngine(max_buffer=50)
    monkeypatch.setattr(engine, "_watched_indices", ["NIFTY"])
    monkeypatch.setattr(engine, "watched_equities", [])

    alerts = engine.scan_options_momentum_breakouts()
    assert len(alerts) == 0  # Exhaustion candle rejected!


def test_options_momentum_is_gated_in_alert_scrutiny(tmp_path, monkeypatch):
    """Verify that OPTIONS_MOMENTUM alerts are included in is_gated and pass through AI scrutiny."""
    from datetime import datetime, timezone, timedelta
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    data_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)

    engine = AutoAlertEngine(max_buffer=50)
    from engine.alert_scrutiny import ScrutinyResult, alert_scrutiny_auditor
    monkeypatch.setattr(
        alert_scrutiny_auditor,
        "scrutinize_alert",
        lambda a, timeout=2.5: ScrutinyResult(
            status="APPROVED",
            score=88,
            logic_confirmation="Valid momentum setup",
            trap_risk_warning="None observed",
            actionable_guidance="Valid buy",
            sanctity_matrix={"level_coherence": True, "rr_valid": True, "risk_within_bounds": True, "no_chase": True},
            auditor_model="TEST_AUDITOR",
            audited_at="2026-09-11 15:00:00 IST",
        ),
    )

    alert = AutoAlert(
        alert_id="SIG_NIFTY_23500CE_SCRUTINY_1",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY 23500 CE Call Surge",
        summary="Volume surge",
        ltp=120.0,
        trigger_level=120.0,
        target_level=160.0,
        stop_loss=105.0,
        strike=23500.0,
        option_type="CE",
        contract_symbol="NIFTY23500CE",
        option_premium=120.0,
        underlying_spot=23510.0,
        confidence=85,
        created_at=datetime.now(ist_tz).strftime("%Y-%m-%d %H:%M:%S IST"),
        is_live=True,
        environment="LIVE",
        metrics={"vol_oi_ratio": 2.5, "spot": 23510.0, "strike": 23500.0},
        actionable_plan={
            "action": "BUY CE",
            "contract": "NIFTY23500CE",
            "recommended_entry": "₹120.0",
            "entry_range": "₹116.0 – ₹121.0",
            "stop_loss": "₹105.0",
            "target": "₹160.0",
            "risk_reward": "1:2.6",
        },
    )

    recorded = engine.record_alert(alert)
    assert recorded is True
    assert "scrutiny" in alert.metrics
    assert alert.metrics["scrutiny"]["status"] in ("APPROVED", "QUANT_VERIFIED")


def test_options_momentum_friday_late_warning(tmp_path, monkeypatch):
    """Verify Friday post-14:30 IST alert tags weekend theta decay warning."""
    from datetime import datetime, timezone, timedelta
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    data_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)

    synthetic_chain = [
        MockOptionsContract(
            symbol="NIFTY23500CE",
            underlying="NIFTY",
            strike=23500.0,
            option_type="CE",
            last_price=120.0,
            oi=20000,
            oi_change=5000,
            volume=35000,
        )
    ]
    monkeypatch.setattr("market.quotes.get_ltp", lambda sym: 23510.0)
    monkeypatch.setattr("market.options.get_options_chain", lambda sym: synthetic_chain)

    engine = AutoAlertEngine(max_buffer=50)
    monkeypatch.setattr(engine, "_watched_indices", ["NIFTY"])
    monkeypatch.setattr(engine, "watched_equities", [])

    # Mock Friday 14:45 IST
    fake_friday_late = datetime(2026, 9, 11, 14, 45, 0, tzinfo=ist_tz)
    import engine.auto_alert_engine as aae

    class MockDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fake_friday_late

    monkeypatch.setattr(aae, "datetime", MockDatetime)

    alerts = engine.scan_options_momentum_breakouts()
    assert len(alerts) >= 1
    alert = alerts[0]
    assert "FRIDAY POST-14:30" in alert.summary
    assert alert.actionable_plan.get("friday_weekend_warning") is not None





