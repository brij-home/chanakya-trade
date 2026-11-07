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


def test_index_tide_gate_vetoes_counter_trend_stock(monkeypatch):
    """Verifies that Index Tide Gate in Signal Policy strictly vetoes counter-trend setups."""

    from engine.market_regime_gate import IndexTideGateResult

    alert = AutoAlert(
        alert_id="aa-test-bank-short",
        alert_type="SMC_OB_RETEST",
        stage="IGNITED",
        symbol="BANKBARODA",
        exchange="NSE",
        direction="BEARISH",
        headline="BANKBARODA Supply OB",
        summary="Retest of overhead supply block",
        ltp=250.0,
        trigger_level=250.0,
        stop_loss=255.0,
        target_level=235.0,
        strike=250.0,
        option_type="PE",
        contract_symbol="BANKBARODA26NOV250PE",
        confidence=80,
        no_chase_boundary=248.0,
        is_live=True,
        environment="LIVE",
        metrics={"rvol": 1.0, "spot": 250.0, "vix": 15.0, "volume": 10000, "oi": 20000},
    )

    ctx = build_policy_context(
        symbol="BANKBARODA",
        direction="BEARISH",
        ltp=250.0,
        vwap=251.0,
        session_id="20261101",
    )

    # Mock evaluate_institutional_quality_gate to pass

    from engine.quality_gate import VetoVerdict

    mock_q = VetoVerdict(
        is_vetoed=False,
        veto_reason="",
        conviction_tier="HIGH_CONVICTION",
        execution_mandate="STANDARD",
        metrics={},
    )

    monkeypatch.setattr(
        "engine.signal_policy.evaluate_institutional_quality_gate",
        lambda *args, **kwargs: mock_q,
    )

    # Mock evaluate_index_tide_gate to return a veto (Benchmark BANKNIFTY is advancing)

    mock_tide_res = IndexTideGateResult(
        is_vetoed=True,
        veto_reason="Index Tide Veto: Benchmark BANKNIFTY is advancing (+3.33%, above VWAP); non-decoupled breakdown on BANKBARODA suppressed",
        benchmark_symbol="BANKNIFTY",
        benchmark_ltp=57700.0,
        benchmark_vwap=57300.0,
        benchmark_change_pct=3.33,
    )

    monkeypatch.setattr(
        "engine.market_regime_gate.evaluate_index_tide_gate",
        lambda *args, **kwargs: mock_tide_res,
    )

    res = evaluate_candidate_policy(ctx, alert)

    assert res.decision == "REJECT"

    assert res.primary_status == "SHADOW_ONLY"

    assert res.blocking_gate is not None

    assert res.blocking_gate.gate_name == "INDEX_TIDE_GATE"

    assert "Benchmark BANKNIFTY is advancing" in res.blocking_gate.reason


def test_sector_support_gate_vetoes_severe_headwind(monkeypatch):
    """Verifies Phase B3 SECTOR_SUPPORT_GATE vetoes counter-sector breakout when sector is lagging without catalyst."""

    from types import SimpleNamespace

    from engine.quality_gate import VetoVerdict

    from engine.market_regime_gate import IndexTideGateResult

    alert = AutoAlert(
        alert_id="aa-test-sec-veto",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="TATAMOTORS",
        exchange="NFO",
        direction="BULLISH",
        headline="TATAMOTORS Call Setup",
        summary="Breakout attempt",
        ltp=40.0,
        trigger_level=40.0,
        stop_loss=30.0,
        target_level=65.0,
        strike=1000.0,
        option_type="CE",
        contract_symbol="TATAMOTORS26NOV1000CE",
        confidence=80,
        is_live=True,
        environment="LIVE",
        lot_size=1425,
        metrics={
            "rvol": 1.1,
            "change_pct": 0.3,
            "spot": 1000.0,
            "underlying_spot": 1000.0,
            "underlying_sl": 990.0,
            "underlying_target": 1025.0,
            "vix": 15.0,
            "volume": 500000,
            "oi": 2000000,
            "no_chase_boundary": 43.0,
        },
    )

    alert.no_chase_boundary = 43.0

    ctx = build_policy_context(
        symbol="TATAMOTORS",
        direction="BULLISH",
        ltp=40.0,
        extra_features={"rvol": 1.1, "change_pct": 0.3},
    )

    mock_q = VetoVerdict(
        is_vetoed=False,
        veto_reason="",
        conviction_tier="HIGH_CONVICTION",
        execution_mandate="STANDARD",
        metrics={},
    )

    monkeypatch.setattr(
        "engine.signal_policy.evaluate_institutional_quality_gate",
        lambda *args, **kwargs: mock_q,
    )

    mock_tide_res = IndexTideGateResult(
        is_vetoed=False,
        veto_reason="",
        benchmark_symbol="NIFTY",
        benchmark_ltp=25000.0,
        benchmark_vwap=25000.0,
        benchmark_change_pct=0.2,
    )

    monkeypatch.setattr(
        "engine.market_regime_gate.evaluate_index_tide_gate",
        lambda *args, **kwargs: mock_tide_res,
    )

    mock_tailwind = SimpleNamespace(
        quadrant="LAGGING",
        intraday_rs=-0.80,
        alignment="HEADWIND",
    )

    monkeypatch.setattr("analysis.universe.get_stock_sector", lambda sym: ("auto", "Nifty Auto"))

    monkeypatch.setattr("analysis.sector_rotation.get_stock_tailwind", lambda sym: mock_tailwind)

    res = evaluate_candidate_policy(ctx, alert)

    assert res.decision == "REJECT"

    assert res.primary_status == "SHADOW_ONLY"

    assert res.blocking_gate is not None

    assert res.blocking_gate.gate_name == "SECTOR_SUPPORT_GATE"

    assert "Sector Headwind Veto" in res.blocking_gate.reason


def test_physical_settlement_gate_vetoes_naked_stock_option_in_expiry_week(monkeypatch):
    """Verifies Phase B4 PHYSICAL_SETTLEMENT_GATE vetoes naked stock option buying in monthly expiry week."""

    from engine.quality_gate import VetoVerdict

    from engine.market_regime_gate import IndexTideGateResult

    alert = AutoAlert(
        alert_id="aa-test-phys-veto",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="TATAMOTORS",
        exchange="NFO",
        direction="BULLISH",
        headline="TATAMOTORS Naked Call Setup",
        summary="Naked call near monthly expiry",
        ltp=40.0,
        trigger_level=40.0,
        stop_loss=30.0,
        target_level=65.0,
        strike=1000.0,
        option_type="CE",
        contract_symbol="TATAMOTORS26NOV1000CE",
        expiry_date="2026-11-26",
        preferred_vehicle="NAKED_OPTION",
        confidence=80,
        is_live=True,
        environment="LIVE",
        lot_size=1425,
        metrics={
            "rvol": 3.0,
            "change_pct": 3.5,
            "spot": 1000.0,
            "underlying_spot": 1000.0,
            "underlying_sl": 990.0,
            "underlying_target": 1025.0,
            "vix": 15.0,
            "volume": 500000,
            "oi": 2000000,
            "no_chase_boundary": 43.0,
        },
    )

    alert.no_chase_boundary = 43.0

    ctx = build_policy_context(
        symbol="TATAMOTORS",
        direction="BULLISH",
        ltp=40.0,
        extra_features={"rvol": 3.0, "change_pct": 3.5},
    )

    mock_q = VetoVerdict(
        is_vetoed=False,
        veto_reason="",
        conviction_tier="HIGH_CONVICTION",
        execution_mandate="STANDARD",
        metrics={},
    )

    monkeypatch.setattr(
        "engine.signal_policy.evaluate_institutional_quality_gate",
        lambda *args, **kwargs: mock_q,
    )

    mock_tide_res = IndexTideGateResult(
        is_vetoed=False,
        veto_reason="",
        benchmark_symbol="NIFTY",
        benchmark_ltp=25000.0,
        benchmark_vwap=25000.0,
        benchmark_change_pct=0.2,
    )

    monkeypatch.setattr(
        "engine.market_regime_gate.evaluate_index_tide_gate",
        lambda *args, **kwargs: mock_tide_res,
    )

    monkeypatch.setattr(
        "engine.alert_expiry.is_monthly_physical_expiry_week", lambda *args, **kwargs: True
    )

    res = evaluate_candidate_policy(ctx, alert)

    assert res.decision == "REJECT"

    assert res.primary_status == "VETOED"

    assert res.blocking_gate is not None

    assert res.blocking_gate.gate_name == "PHYSICAL_SETTLEMENT_GATE"

    assert "SEBI Physical Delivery" in res.blocking_gate.reason


def test_physical_settlement_gate_permits_spread(monkeypatch):
    """Verifies Phase B4 PHYSICAL_SETTLEMENT_GATE permits defined-risk spread during expiry week."""

    from engine.quality_gate import VetoVerdict

    from engine.market_regime_gate import IndexTideGateResult

    alert = AutoAlert(
        alert_id="aa-test-phys-spread",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="TATAMOTORS",
        exchange="NFO",
        direction="BULLISH",
        headline="TATAMOTORS Bull Call Spread",
        summary="Spread in monthly expiry week",
        ltp=40.0,
        trigger_level=40.0,
        stop_loss=30.0,
        target_level=65.0,
        strike=1000.0,
        option_type="CE",
        contract_symbol="TATAMOTORS26NOV1000CE",
        expiry_date="2026-11-26",
        preferred_vehicle="SPREAD_ONLY",
        confidence=80,
        is_live=True,
        environment="LIVE",
        lot_size=1425,
        metrics={
            "rvol": 3.0,
            "change_pct": 3.5,
            "spot": 1000.0,
            "underlying_spot": 1000.0,
            "underlying_sl": 990.0,
            "underlying_target": 1025.0,
            "vix": 15.0,
            "volume": 500000,
            "oi": 2000000,
            "no_chase_boundary": 43.0,
            "rollover_protected": True,
            "is_next_month_routed": True,
        },
    )

    alert.no_chase_boundary = 43.0

    ctx = build_policy_context(
        symbol="TATAMOTORS",
        direction="BULLISH",
        ltp=40.0,
        extra_features={"rvol": 3.0, "change_pct": 3.5},
    )

    mock_q = VetoVerdict(
        is_vetoed=False,
        veto_reason="",
        conviction_tier="HIGH_CONVICTION",
        execution_mandate="STANDARD",
        metrics={},
    )

    monkeypatch.setattr(
        "engine.signal_policy.evaluate_institutional_quality_gate",
        lambda *args, **kwargs: mock_q,
    )

    mock_tide_res = IndexTideGateResult(
        is_vetoed=False,
        veto_reason="",
        benchmark_symbol="NIFTY",
        benchmark_ltp=25000.0,
        benchmark_vwap=25000.0,
        benchmark_change_pct=0.2,
    )

    monkeypatch.setattr(
        "engine.market_regime_gate.evaluate_index_tide_gate",
        lambda *args, **kwargs: mock_tide_res,
    )

    monkeypatch.setattr(
        "engine.alert_expiry.is_monthly_physical_expiry_week", lambda *args, **kwargs: True
    )

    res = evaluate_candidate_policy(ctx, alert)

    phys_gates = [g for g in res.gate_verdicts if g.gate_name == "PHYSICAL_SETTLEMENT_GATE"]

    assert len(phys_gates) == 1

    assert phys_gates[0].status == "ACCEPT"
