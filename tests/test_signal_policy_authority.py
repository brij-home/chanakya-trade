"""
tests/test_signal_policy_authority.py
─────────────────────────────────────
Unit tests for Consolidated Signal Policy Authority (engine/signal_policy.py).
Verifies:
  1. Standardized SignalPolicyEvaluationContext construction and deterministic cache keys.
  2. Non-negotiable safety gate fail-closed behavior (Sanity, Zero Futures).
  3. Empirical strategy filter separation (Shadow-only status on learning lockout).
  4. End-to-end policy acceptance and audit entry generation.
"""

from __future__ import annotations

import pytest

from engine.alert_model import AutoAlert
from engine.signal_policy import (
    build_policy_context,
    evaluate_candidate_policy,
    CandidatePolicyResult,
)


@pytest.fixture(autouse=True)
def supply_vix(monkeypatch):
    monkeypatch.setattr("analysis.regime_governor._fresh_live_vix", lambda *args, **kwargs: 15.0)
    import analysis.regime_governor as rg

    monkeypatch.setattr(rg, "_fresh_live_vix", lambda *args, **kwargs: 15.0)


@pytest.fixture
def base_valid_alert():
    return AutoAlert(
        alert_id="aa-test-sp-1",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY Call Setup",
        summary="Confluence breakout above resistance",
        ltp=150.0,
        trigger_level=150.0,
        stop_loss=120.0,
        target_level=240.0,
        strike=25000.0,
        option_type="CE",
        contract_symbol="NIFTY26NOV25000CE",
        confidence=85,
        is_live=True,
        environment="LIVE",
        metrics={
            "rvol": 1.5,
            "underlying_spot": 25000.0,
            "underlying_sl": 24900.0,
            "underlying_target": 25300.0,
            "spot": 25000.0,
            "vix": 15.0,
            "india_vix": 15.0,
            "volume": 50000,
            "oi": 100000,
        },
    )


def test_build_policy_context_and_cache_key():
    """Verify context construction derives canonical symbol and deterministic cache key."""
    ctx = build_policy_context(
        symbol="NSE:NIFTY50-INDEX",
        direction="BULLISH",
        ltp=25000.0,
        vwap=24950.0,
        rvol=1.8,
        session_id="20261101",
    )

    assert ctx.canonical_symbol == "NIFTY"
    assert ctx.direction == "BULLISH"
    assert ctx.session_id == "20261101"
    assert ctx.payoff_type == "LONG"

    key1 = ctx.compute_cache_key("OPTIONS_MOMENTUM")
    key2 = ctx.compute_cache_key("OPTIONS_MOMENTUM")
    assert key1 == key2
    assert "NIFTY:BULLISH:OPTIONS_MOMENTUM:20261101" in key1


def test_safety_gate_mathematical_sanity_failure(base_valid_alert):
    """Sanity failure (e.g. stop loss above entry on a bull setup) strictly vetoes candidate."""
    alert = base_valid_alert
    alert.stop_loss = 180.0  # Invalid! SL > Entry for bullish premium

    ctx = build_policy_context(
        symbol="NIFTY",
        direction="BULLISH",
        ltp=150.0,
        session_id="20261101",
    )

    res = evaluate_candidate_policy(ctx, alert)

    assert isinstance(res, CandidatePolicyResult)
    assert res.decision == "REJECT"
    assert res.primary_status == "VETOED"
    assert res.blocking_gate is not None
    assert res.blocking_gate.gate_name == "TIER1_SANITY_GATE"
    assert res.blocking_gate.is_safety_gate is True
    assert res.audit_trail_entry["decision"] == "REJECT"


def test_safety_gate_zero_futures_invariant(base_valid_alert):
    """Domestic index/equity futures contracts must be strictly vetoed by safety gate."""
    alert = base_valid_alert
    alert.contract_symbol = "NIFTY26NOVFUT"
    alert.instrument_type = "FUTURES"

    ctx = build_policy_context(
        symbol="NIFTY",
        direction="BULLISH",
        instrument_type="FUTURES",
        ltp=25000.0,
        session_id="20261101",
    )

    res = evaluate_candidate_policy(ctx, alert)

    assert res.decision == "REJECT"
    assert res.primary_status == "VETOED"
    assert res.blocking_gate is not None
    assert res.blocking_gate.gate_name == "ZERO_FUTURES_GATE"
    assert res.blocking_gate.is_safety_gate is True


def test_empirical_filter_routes_to_shadow(base_valid_alert, monkeypatch):
    """When safety passes but learning lockout blocks, status is SHADOW_ONLY (not safety VETOED)."""
    alert = base_valid_alert

    # Mock lockout active
    from engine.learning_engine import pattern_learning_engine

    monkeypatch.setattr(
        pattern_learning_engine,
        "is_symbol_locked_out",
        lambda *args, **kwargs: (True, "Recent 2-strike stop out cooldown active"),
    )

    ctx = build_policy_context(
        symbol="NIFTY",
        direction="BULLISH",
        ltp=25000.0,
        session_id="20261101",
    )

    res = evaluate_candidate_policy(ctx, alert)

    assert res.decision == "HOLD"
    assert res.primary_status == "SHADOW_ONLY"
    assert res.blocking_gate is not None
    assert res.blocking_gate.gate_name == "LEARNING_LOCKOUT_GATE"
    assert res.blocking_gate.is_safety_gate is False


def test_successful_policy_acceptance(base_valid_alert, monkeypatch):
    """Clean candidate passing all safety, quality, and empirical gates returns ACTIONABLE."""
    alert = base_valid_alert

    from engine.learning_engine import pattern_learning_engine

    monkeypatch.setattr(
        pattern_learning_engine,
        "is_symbol_locked_out",
        lambda *args, **kwargs: (False, ""),
    )

    ctx = build_policy_context(
        symbol="NIFTY",
        direction="BULLISH",
        ltp=25000.0,
        vwap=24950.0,
        session_id="20261101",
    )

    # Warmup first call
    _ = evaluate_candidate_policy(ctx, alert)

    res = evaluate_candidate_policy(ctx, alert)

    assert res.decision == "ACCEPT"
    assert res.primary_status == "ACTIONABLE"
    assert res.blocking_gate is None
    assert res.conviction_tier in ("APEX_CONFLUENCE", "HIGH_CONVICTION", "DEFINED_RISK_ONLY")
    assert res.audit_trail_entry["decision"] == "ACCEPT"
    assert res.latency_ms < 1000.0  # Sub-second policy evaluation SLA
