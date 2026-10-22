"""
tests/test_holistic_signals_architecture_rca.py
───────────────────────────────────────────────
Deterministic test suite verifying the holistic architectural resolution of Flaws 3 through 8:
  1. AlertFactory Scale Separation & Mandatory RVOL Invariant (Flaws 4, 5, 6).
  2. AutoAlert.__post_init__ Scale Guard against Spot Contamination (Flaw 4).
  3. Institutional Context 7-Factor Confluence Provider (Flaw 3).
  4. Pre-Entry Stagnation Immunity & Obstacle Runway Gates in Scrutiny (Flaw 7).
  5. Dynamic Regime Governor & Strategy Routing under Institutional Distribution (Flaw 8).
"""

import pytest
import pandas as pd
import numpy as np

from engine.alert_factory import (
    AlertFactory,
    ScaleContaminationError,
    UnverifiedRvolError,
)
from engine.alert_model import AutoAlert
from engine.institutional_context import build_institutional_context
from engine.alert_scrutiny import AlertScrutinyAuditor
from analysis.regime_governor import (
    is_detector_eligible_for_regime,
    MarketRegimeClassification,
)


def test_alert_factory_mandatory_rvol_rejection():
    """Flaw 5: AlertFactory must reject directional setups with rvol <= 0 or None."""
    with pytest.raises(UnverifiedRvolError) as exc_info:
        AlertFactory.create_equity_alert(
            alert_type="ORB_BREAKOUT",
            stage="IGNITED",
            symbol="RELIANCE",
            exchange="NSE",
            direction="BULLISH",
            headline="RELIANCE ORB Breakout",
            summary="Testing zero RVOL rejection",
            ltp=2800.0,
            trigger_level=2805.0,
            target_level=2830.0,
            stop_loss=2790.0,
            rvol=0.0,  # Zero RVOL must trigger fail-closed error
        )
    assert "rejected: RVOL must be strictly positive" in str(exc_info.value)


def test_alert_factory_option_scale_separation_invariant():
    """Flaw 4: AlertFactory must prevent spot prices from contaminating option premium SL."""
    # Attempting to pass Index Spot (24,800) into option SL must raise ScaleContaminationError
    with pytest.raises(ScaleContaminationError) as exc_info:
        AlertFactory.create_option_alert(
            alert_type="INDEX_CALL_SETUP",
            stage="IGNITED",
            underlying_symbol="NIFTY",
            contract_symbol="NIFTY26OCT25000CE",
            exchange="NFO",
            direction="BULLISH",
            strike=25000.0,
            option_type="CE",
            option_premium=120.0,
            option_trigger=122.0,
            option_target=180.0,
            option_sl=24800.0,  # CONTAMINATED: Spot price passed as option SL!
            underlying_spot=25010.0,
            underlying_sl=24950.0,
            rvol=1.85,
            lot_size=75,
            headline="NIFTY 25000 CE Thrust",
            summary="Testing scale contamination rejection",
        )
    assert "Fatal Scale Contamination" in str(exc_info.value)


def test_alert_factory_clean_option_creation():
    """Flaw 4: Valid option alert separates option coordinates from underlying spot coordinates cleanly."""
    alert = AlertFactory.create_option_alert(
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        underlying_symbol="NIFTY",
        contract_symbol="NIFTY26OCT25000CE",
        exchange="NFO",
        direction="BULLISH",
        strike=25000.0,
        option_type="CE",
        option_premium=120.0,
        option_trigger=122.0,
        option_target=180.0,
        option_sl=95.0,  # Valid option SL
        underlying_spot=25010.0,
        underlying_sl=24950.0,
        rvol=1.85,
        lot_size=75,
        headline="NIFTY 25000 CE Thrust",
        summary="Testing clean separation",
    )
    # Check absolute scale separation
    assert alert.ltp == 120.0
    assert alert.stop_loss == 95.0
    assert alert.tactical_sl == 95.0
    assert alert.disaster_stop_floor == round(120.0 * 0.68, 2)
    assert alert.underlying_spot == 25010.0
    assert alert.underlying_sl == 24950.0
    assert alert.structural_spot_sl == 24950.0
    assert alert.contract_symbol == "NIFTY26OCT25000CE"


def test_auto_alert_post_init_spot_sl_guard():
    """Flaw 4: AutoAlert.__post_init__ must not assign spot price to tactical_sl."""
    alert = AutoAlert(
        alert_id="aa-test-nifty-001",
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="NIFTY 25000 CE Setup",
        summary="Testing post init guard",
        ltp=120.0,
        trigger_level=122.0,
        target_level=180.0,
        stop_loss=24800.0,  # Legacy mistake: spot SL placed in stop_loss
        option_premium=120.0,
        strike=25000.0,
        option_type="CE",
    )
    # tactical_sl must NOT take 24800.0!
    assert alert.tactical_sl != 24800.0
    # Instead, structural_spot_sl adopts 24800.0
    assert alert.structural_spot_sl == 24800.0


def test_institutional_context_generation():
    """Flaw 3: Institutional Context unifies SMC, CPR, Momentum, and Velocity metrics."""
    # Synthetic 5-minute bars
    dates = pd.date_range("2026-10-21 09:15", periods=20, freq="5min")
    df_5m = pd.DataFrame(
        {
            "open": np.linspace(24900, 25020, 20),
            "high": np.linspace(24910, 25040, 20),
            "low": np.linspace(24890, 25010, 20),
            "close": np.linspace(24905, 25035, 20),
            "volume": np.ones(20) * 50000,
        },
        index=dates,
    )

    ctx = build_institutional_context(
        symbol="NIFTY",
        ltp=25035.0,
        df_5m=df_5m,
        rvol=2.1,
    )
    assert ctx.symbol == "NIFTY"
    assert ctx.smc.regime in ("BULLISH", "BEARISH", "RANGING")
    assert ctx.cpr.pivot > 0 or ctx.cpr.cpr_regime in ("NARROW_CPR", "WIDE_CPR", "AVERAGE_CPR")
    assert ctx.momentum.trigger_candle_body_ratio > 0
    assert ctx.velocity.adr_14 > 0
    assert ctx.confluence_score >= 50


def test_scrutiny_mandatory_rvol_and_stagnation_immunity():
    """Flaw 5 & 7: Scrutiny enforces mandatory RVOL and rejects ADR exhaustion traps."""
    auditor = AlertScrutinyAuditor()

    # 1. Breakout alert with RVOL = 0.0 must be rejected
    zero_rvol_alert = AutoAlert(
        alert_id="aa-orb-test-01",
        alert_type="ORB_BREAKOUT",
        stage="IGNITED",
        symbol="TCS",
        exchange="NSE",
        direction="BULLISH",
        headline="TCS Breakout",
        summary="Zero RVOL test",
        ltp=4100.0,
        trigger_level=4100.0,
        target_level=4220.0,
        stop_loss=4040.0,
        metrics={"rvol": 0.0, "atr_14": 50.0},
        environment="LIVE",
        is_live=True,
    )
    passed, reason, _ = auditor.verify_tier1_sanity(zero_rvol_alert)
    assert passed is False
    assert "Unverified Volume Veto" in reason

    # 2. Breakout alert with ADR consumed > 65% must be rejected as stagnation trap
    adr_exhausted_alert = AutoAlert(
        alert_id="aa-orb-test-02",
        alert_type="ORB_BREAKOUT",
        stage="IGNITED",
        symbol="INFY",
        exchange="NSE",
        direction="BULLISH",
        headline="INFY Breakout",
        summary="ADR Exhausted test",
        ltp=1800.0,
        trigger_level=1800.0,
        target_level=1850.0,
        stop_loss=1770.0,
        metrics={"rvol": 1.8, "atr_14": 20.0, "adr_consumed_pct": 78.5},
        environment="LIVE",
        is_live=True,
    )
    passed, reason, _ = auditor.verify_tier1_sanity(adr_exhausted_alert)
    assert passed is False
    assert "Stagnation Fuel Exhaustion Veto" in reason


def test_regime_governor_institutional_distribution_pivoting():
    """Flaw 8: Dynamic Regime Governor pivots actively to Put setups and suppresses Call setups."""
    regime = MarketRegimeClassification(
        regime="INSTITUTIONAL_DISTRIBUTION",
        vix=15.5,
        is_orb_trapped=False,
        is_expiry_session=False,
        min_scrutiny_score=75,
        dominant_bias="BEARISH_EXPANSION",
        guidance="Dalal Street in institutional distribution. Prioritize Puts.",
        active_detectors=["INDEX_PUT_SETUP", "INTRADAY_SPARK"],
        suppressed_detectors=["INDEX_CALL_SETUP", "OPENING_DRIVE"],
    )

    # Bullish Call setup during institutional distribution with normal RVOL (1.8x < 2.5x) must be suppressed
    is_elig_call, reason_call = is_detector_eligible_for_regime(
        alert_type="INDEX_CALL_SETUP",
        regime=regime,
        rvol=1.8,
    )
    assert is_elig_call is False
    assert "INSTITUTIONAL_DISTRIBUTION" in reason_call

    # Bearish Put setup must be 100% eligible and prioritized
    is_elig_put, reason_put = is_detector_eligible_for_regime(
        alert_type="INDEX_PUT_SETUP",
        regime=regime,
        rvol=1.8,
    )
    assert is_elig_put is True
    assert reason_put == ""


def test_index_active_trade_mutex_and_session_quota():
    """Anti-Churn: Index active trade mutex and per-symbol daily quota eliminate alert spam."""
    from engine.auto_alert_engine import AutoAlertEngine

    engine = AutoAlertEngine()
    engine._alerts.clear()
    engine._cooldowns.clear()

    # 1. First alert on NIFTY from INDEX_CALL_SETUP
    nifty_call_1 = AutoAlert(
        alert_id="aa-call-nifty-25000ce-01",
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="NIFTY 25000 CE Thrust",
        summary="First NIFTY call setup",
        ltp=120.0,
        trigger_level=122.0,
        target_level=180.0,
        stop_loss=95.0,
        strike=25000.0,
        option_type="CE",
        contract_symbol="NIFTY26OCT25000CE",
        metrics={"rvol": 2.0},
        confidence=85,
        environment="LIVE",
        is_live=True,
    )
    # Insert first alert
    res1 = engine.record_alert(nifty_call_1)
    assert res1 is True

    # 2. Second alert on NIFTY from GAMMA_BLAST in same direction while first is active
    nifty_call_2 = AutoAlert(
        alert_id="aa-gamma-nifty-25000ce-02",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="NIFTY 25000 CE Gamma Blast",
        summary="Second concurrent NIFTY call setup",
        ltp=125.0,
        trigger_level=125.0,
        target_level=185.0,
        stop_loss=100.0,
        strike=25000.0,
        option_type="CE",
        contract_symbol="NIFTY26OCT25000CE",
        metrics={"rvol": 2.2},
        confidence=85,
        environment="LIVE",
        is_live=True,
    )
    # Must be suppressed by the Active Trade Mutex to eliminate duplicate churn
    res2 = engine.record_alert(nifty_call_2)
    assert res2 is False


def test_option_spread_friction_veto_tightened():
    """Slippage Guard: Spreads > 2.5% on index options must be vetoed."""
    auditor = AlertScrutinyAuditor()
    wide_spread_opt = AutoAlert(
        alert_id="aa-opt-wide-01",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY 25000 CE Momentum",
        summary="Wide spread test",
        ltp=100.0,
        trigger_level=100.0,
        target_level=140.0,
        stop_loss=80.0,
        strike=25000.0,
        option_type="CE",
        contract_symbol="NIFTY26OCT25000CE",
        metrics={
            "rvol": 2.0,
            "best_bid": 97.0,
            "best_ask": 103.0,  # 6.0 pt spread on 100 pt option = 6.0% spread (> 2.5% limit)
        },
        environment="LIVE",
        is_live=True,
    )
    passed, reason, flags = auditor.verify_tier1_sanity(wide_spread_opt)
    # Must be rejected due to tightened spread friction limit (<= 2.5%)
    assert passed is False
    assert "2.5%" in reason
