"""
tests/test_phase2_phase3_calibration.py
──────────────────────────────────────
Deterministic unit & regression tests for Phase 2 & Phase 3 calibrations:
  1. Telegram Calibrated Confidence Whitelist:
     - Verified quantitative strategies (STAGE_1_TO_2_EXPANSION, RRG_SECTOR_ROTATION,
       SMC_SPRING_SWEEP, SQUEEZE_BREAKOUT/DOWN, GAMMA_BLAST, etc.) pass the Apex gate at 80%.
     - TELEGRAM_MIN_CONFIDENCE environment variable override is honored.
     - Multi-target expansions (target_2, plan risk:reward) accurately satisfy R:R thresholds.
  2. AlertPreferences explain_alert_allowed:
     - Calibrated quant models evaluate with effective_min_conf=80.
  3. Universal Synthetic Spot SL Shielding:
     - Robust symbol and anchor extraction across AutoAlert instances and raw dicts.
     - Correctly isolates spot domain anchors (e.g. 190.82 vs 5.06) from option premiums.
     - Evaluates synthetic spot shielding safely on both objects and dictionaries.
"""

from __future__ import annotations

from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine
from engine.alert_preferences import AlertPreferencesManager
from engine.synthetic_sl import (
    extract_underlying_symbol,
    extract_spot_invalidation_anchor,
    evaluate_synthetic_spot_sl,
)


def test_telegram_apex_gate_quant_whitelist_80():
    """Verify that verified quantitative setups pass Telegram Apex Gate at 80% confidence."""
    engine = AutoAlertEngine()

    quant_types = [
        "STAGE_1_TO_2_EXPANSION",
        "RRG_SECTOR_ROTATION",
        "SMC_SPRING_SWEEP",
        "SQUEEZE_BREAKOUT",
        "SQUEEZE_BREAKDOWN",
        "TTM_SQUEEZE_EXPLOSION",
        "GAMMA_BLAST",
        "OPTIONS_MOMENTUM",
        "MULTIBAGGER",
    ]

    for atype in quant_types:
        alert = AutoAlert(
            alert_id=f"aa-{atype.lower()}-test-20261012",
            alert_type=atype,
            stage="IGNITED",
            symbol="TESTSTOCK",
            exchange="NSE",
            headline="Institutional Setup",
            summary="Test quant signal",
            direction="BULLISH",
            ltp=500.0,
            trigger_level=500.0,
            stop_loss=480.0,
            target_level=540.0,  # 40 / 20 = 2.0R
            confidence=80,  # Exactly 80% floor
            actionable_plan={"risk_reward": "1:2.0"},
            is_live=True,
            environment="LIVE",
        )
        allowed, reason = engine._eval_telegram_apex_gate(alert, in_market=True)
        assert allowed is True, f"Failed for {atype}: {reason}"
        assert reason == "PASSED_APEX_GATE"


def test_telegram_apex_gate_multi_target_rr_evaluation():
    """Verify setups with conservative target_1 scale-out but strong target_2 pass R:R filter."""
    engine = AutoAlertEngine()

    # NUVAMA style: Trigger=1886.5, SL=1767.93 (Risk=118.57), T1=1936.0 (+0.42R), T2=2064.7 (+1.5R)
    alert = AutoAlert(
        alert_id="aa-stage-1-to-2-expansion-nuvama-pull-20261012",
        alert_type="STAGE_1_TO_2_EXPANSION",
        stage="PRIMED",
        symbol="NUVAMA",
        exchange="NSE",
        headline="Stage 1 to 2 Base Expansion",
        summary="Nuvama base breakout",
        direction="BULLISH",
        ltp=1886.5,
        trigger_level=1886.5,
        stop_loss=1767.93,
        target_level=1936.0,  # Target 1 (scale 50%)
        confidence=82,
        actionable_plan={"risk_reward": "1:2.0", "target_1": 1936.0, "target_2": 2064.7},
        is_live=True,
        environment="LIVE",
    )

    allowed, reason = engine._eval_telegram_apex_gate(alert, in_market=True)
    assert allowed is True, f"Expected allowed, got {reason}"
    assert reason == "PASSED_APEX_GATE"


def test_telegram_min_confidence_env_var_override(monkeypatch):
    """Verify that TELEGRAM_MIN_CONFIDENCE env var allows lowering the general bar."""
    engine = AutoAlertEngine()
    monkeypatch.setenv("TELEGRAM_MIN_CONFIDENCE", "78")

    alert = AutoAlert(
        alert_id="aa-custom-test-20261012",
        alert_type="CUSTOM_SETUP",
        stage="IGNITED",
        symbol="TESTSTOCK",
        exchange="NSE",
        headline="Custom Setup",
        summary="Test signal",
        direction="BULLISH",
        ltp=100.0,
        trigger_level=100.0,
        stop_loss=90.0,
        target_level=120.0,
        confidence=79,  # Above 78 env var override
        is_live=True,
        environment="LIVE",
    )

    allowed, reason = engine._eval_telegram_apex_gate(alert, in_market=True)
    assert allowed is True, f"Expected allowed with TELEGRAM_MIN_CONFIDENCE=78, got {reason}"


def test_alert_preferences_quant_models_effective_min_conf():
    """Verify AlertPreferencesManager evaluates quant models with 80% threshold."""
    mgr = AlertPreferencesManager()

    # Raw dict alert
    dict_alert = {
        "alert_type": "STAGE_1_TO_2_EXPANSION",
        "segment": "EQUITY",
        "confidence": 80,
    }
    allowed, reason = mgr.explain_alert_allowed(dict_alert, channel="telegram")
    assert allowed is True, f"Expected allowed for dict quant alert, got {reason}"

    # AutoAlert object
    obj_alert = AutoAlert(
        alert_id="aa-rrg-persistent-20261012",
        alert_type="RRG_SECTOR_ROTATION",
        stage="IGNITED",
        symbol="PERSISTENT",
        exchange="NSE",
        headline="RRG Leading Rotation",
        summary="Persistent sector lead",
        direction="BULLISH",
        ltp=5200.0,
        trigger_level=5200.0,
        stop_loss=5100.0,
        target_level=5400.0,
        confidence=80,
    )
    allowed_obj, reason_obj = mgr.explain_alert_allowed(obj_alert, channel="telegram")
    assert allowed_obj is True, f"Expected allowed for AutoAlert quant alert, got {reason_obj}"


def test_synthetic_sl_extracts_spot_domain_anchor_correctly():
    """Verify extract_spot_invalidation_anchor isolates spot price anchor from option premium."""
    # Option alert where trade_plan has spot anchor (190.82) and option premium stop is 5.06
    rvnl_alert = {
        "alert_id": "aa-gamma-blast-rvnl-ce-195-20261012",
        "symbol": "RVNL",
        "contract_symbol": "NSE:RVNL26OCT195CE",
        "underlying_spot": 193.73,
        "option_type": "CE",
        "trigger_level": 7.05,
        "stop_loss": 5.06,
        "actionable_plan": {
            "initial_invalidation_stop": 5.06,  # Option premium stop
            "trade_plan": {
                "invalidation_stop": 190.82,  # Underlying SPOT anchor
                "entry_price": 193.73,
            },
        },
    }

    und = extract_underlying_symbol(rvnl_alert)
    assert und == "RVNL"

    spot_anchor = extract_spot_invalidation_anchor(rvnl_alert)
    assert spot_anchor == 190.82  # Must be spot level 190.82, NOT option premium 5.06!


def test_synthetic_sl_derived_fallback_spot_anchor():
    """Verify mathematical derivation of spot anchor when only spot and option levels are present."""
    micro_scalp = {
        "alert_id": "aa-index-micro-scalp-midcpnifty-pe-13650-20261012",
        "symbol": "MIDCPNIFTY",
        "contract_symbol": "NSE:MIDCPNIFTY26OCT13650PE",
        "underlying_spot": 13618.3,
        "option_type": "PE",
        "direction": "BEARISH",
        "trigger_level": 209.6,
        "stop_loss": 199.6,  # 10 pts risk
        "metrics": {"delta": 0.485},
    }

    und = extract_underlying_symbol(micro_scalp)
    assert und == "MIDCPNIFTY"

    spot_anchor = extract_spot_invalidation_anchor(micro_scalp)
    assert spot_anchor is not None
    # For Put / Bearish: spot_anchor is above live spot: 13618.3 + (10 / 0.485) ≈ 13638.9
    assert 13635.0 <= spot_anchor <= 13645.0


def test_synthetic_sl_shields_raw_dictionary():
    """Verify evaluate_synthetic_spot_sl shields raw dict alerts without TypeError/IndexError."""
    alert_dict = {
        "alert_id": "aa-gamma-rvnl-dict-test",
        "symbol": "RVNL",
        "contract_symbol": "NSE:RVNL26OCT195CE",
        "underlying_spot": 193.73,
        "option_type": "CE",
        "direction": "BULLISH",
        "option_premium": 7.05,
        "trigger_level": 7.05,
        "stop_loss": 5.06,
        "actionable_plan": {
            "trade_plan": {"invalidation_stop": 190.82},
        },
    }

    # Option dips to 4.80 (below 5.06 nominal SL), but spot is holding at 193.50 (well above 190.82)
    # Option drawdown: (7.05 - 4.80) / 7.05 = 31.9%
    eval_res = evaluate_synthetic_spot_sl(
        alert=alert_dict,
        current_option_ltp=4.80,
        current_spot_override=193.50,
    )

    assert eval_res.is_invalidated is False
    assert eval_res.is_freak_wick_shielded is True
    assert eval_res.spot_anchor == 190.82
    assert "Shielded RVNL" in (eval_res.shield_reason or "")
