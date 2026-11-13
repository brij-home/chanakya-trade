"""
tests/test_hierarchical_engine.py
───────────────────────────────────
Institutional test suite for Hierarchical Quantitative Decision Engine:
[Level 1: Market Context (3Cs)] ──> [Level 2: Signal Setup (5Ws)] ──> [Level 3: Execution (1H: HOW)]
"""

from __future__ import annotations

from datetime import datetime
import pytest

from config.constants import IST_ZONE as IST
from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine
from engine.pipeline.hierarchical_engine import (
    HierarchicalSignalPipeline,
    hierarchical_pipeline,
)


def make_test_alert(
    alert_id: str = "TEST-01",
    alert_type: str = "PREDATOR_SWEEP",
    stage: str = "IGNITED",
    symbol: str = "NIFTY",
    exchange: str = "NSE",
    direction: str = "BULLISH",
    headline: str = "Test Headline",
    summary: str = "Test Summary",
    ltp: float = 25000.0,
    trigger_level: float = 25000.0,
    target_level: float = 25200.0,
    stop_loss: float = 24900.0,
    **kwargs,
) -> AutoAlert:
    """Helper to construct complete AutoAlert instances with required fields."""
    return AutoAlert(
        alert_id=alert_id,
        alert_type=alert_type,
        stage=stage,
        symbol=symbol,
        exchange=exchange,
        direction=direction,
        headline=headline,
        summary=summary,
        ltp=ltp,
        trigger_level=trigger_level,
        target_level=target_level,
        stop_loss=stop_loss,
        **kwargs,
    )


@pytest.fixture
def clean_engine():
    """Provides a fresh AutoAlertEngine instance with clean in-memory state."""
    engine = AutoAlertEngine()
    engine._alerts = []
    engine._cooldowns = {}
    return engine


class TestLevel1MarketContext3Cs:
    """Tests Level 1: Market Context (Modernized 3Cs)."""

    def test_level1_favorable_market_context(self):
        """Verifies Level 1 passes under normal liquid market conditions."""
        pipeline = HierarchicalSignalPipeline()
        alert = make_test_alert(
            alert_id="NIFTY-TEST-L1-01",
            symbol="NIFTY",
            metrics={"volume": 1000000, "avg_daily_vol": 500000, "rvol": 2.0},
        )
        ctx = pipeline.evaluate_market_context_3cs(
            symbol="NIFTY",
            exchange="NSE",
            ltp=25000.0,
            time_horizon="INTRADAY",
            strategy_orientation="DIRECTIONAL",
            alert=alert,
        )
        assert ctx.liquidity_viable is True
        assert ctx.tod_rvol >= 1.0

    def test_level1_edgeless_chop_suppresses_directional_breakout(self, monkeypatch):
        """Verifies edgeless chop (VIX < 12.5 + balanced breadth) suppresses directional breakout."""
        from types import SimpleNamespace

        mock_regime = SimpleNamespace(
            is_edgeless=True,
            vix=11.8,
            ad_ratio=1.02,
            prefer_spreads=True,
        )
        monkeypatch.setattr("engine.market_regime_gate.evaluate_market_regime", lambda: mock_regime)

        pipeline = HierarchicalSignalPipeline()
        ctx = pipeline.evaluate_market_context_3cs(
            symbol="NIFTY",
            exchange="NSE",
            ltp=25000.0,
            time_horizon="INTRADAY",
            strategy_orientation="DIRECTIONAL",
        )
        assert ctx.passed is False
        assert ctx.status == "EDGELESS_CHOP"
        assert any("edgeless chop" in r.lower() for r in ctx.reasons)

    def test_level1_edgeless_chop_permits_non_directional_spread(self, monkeypatch):
        """Verifies edgeless chop permits and approves non-directional defined-risk spread strategies."""
        from types import SimpleNamespace

        mock_regime = SimpleNamespace(
            is_edgeless=True,
            vix=11.8,
            ad_ratio=1.02,
            prefer_spreads=True,
        )
        monkeypatch.setattr("engine.market_regime_gate.evaluate_market_regime", lambda: mock_regime)

        pipeline = HierarchicalSignalPipeline()
        ctx = pipeline.evaluate_market_context_3cs(
            symbol="NIFTY",
            exchange="NSE",
            ltp=25000.0,
            time_horizon="INTRADAY",
            strategy_orientation="NON_DIRECTIONAL",
        )
        assert ctx.passed is True
        assert ctx.status == "FAVORABLE"


class TestLevel2SignalSetup5Ws:
    """Tests Level 2: Signal Generation & Validation (Modified 5Ws)."""

    def test_level2_alpha_thesis_categorization(self):
        """Verifies WHY: Alpha thesis accurately maps to underlying structural mechanics."""
        pipeline = HierarchicalSignalPipeline()
        sweep_alert = make_test_alert(
            alert_id="SWEEP-01",
            alert_type="PREDATOR_SWEEP",
            symbol="BANKNIFTY",
            metrics={"sweep_type": "BULLISH_PREDATOR_SPRING"},
        )
        ctx = pipeline.evaluate_market_context_3cs(symbol="BANKNIFTY", alert=sweep_alert)
        setup = pipeline.validate_signal_setup_5ws(alert=sweep_alert, context=ctx)
        assert setup.alpha_thesis == "LIQUIDITY_SWEEP"
        assert setup.trapped_counterparty == "RETAIL_BEAR_TRAP"
        assert setup.has_trap_edge is True

    def test_level2_timing_window_intraday_vs_swing(self):
        """Verifies WHEN: Swing trades bypass intraday session clocks, while intraday trades enforce them."""
        pipeline = HierarchicalSignalPipeline()

        # 1. Swing trade at 14:45 IST -> Exempt from intraday cutoff
        swing_alert = make_test_alert(
            alert_id="SWING-01",
            alert_type="STAGE_1_TO_2_EXPANSION",
            symbol="RELIANCE",
            time_horizon="SWING",
        )
        ref_time = datetime(2026, 11, 10, 14, 45, tzinfo=IST)
        ctx_swing = pipeline.evaluate_market_context_3cs(
            symbol="RELIANCE", time_horizon="SWING", alert=swing_alert, ref_dt=ref_time
        )
        setup_swing = pipeline.validate_signal_setup_5ws(
            alert=swing_alert, context=ctx_swing, ref_dt=ref_time
        )
        assert setup_swing.session_window == "OFF_MARKET_SWING"
        assert setup_swing.timing_allowed is True

        # 2. Intraday option trade at 14:45 IST -> Intraday cutoff applied
        intraday_opt_alert = make_test_alert(
            alert_id="OPT-LATE-01",
            alert_type="OPTIONS_MOMENTUM",
            symbol="NIFTY",
            segment="FNO_INDEX",
            time_horizon="INTRADAY",
            actionable_plan={"action": "BUY_CALL", "instrument_type": "OPTION"},
        )
        ctx_intra = pipeline.evaluate_market_context_3cs(
            symbol="NIFTY", time_horizon="INTRADAY", alert=intraday_opt_alert, ref_dt=ref_time
        )
        setup_intra = pipeline.validate_signal_setup_5ws(
            alert=intraday_opt_alert, context=ctx_intra, ref_dt=ref_time
        )
        assert setup_intra.session_window == "AFTERNOON_EXPANSION"
        assert setup_intra.timing_allowed is False

    def test_level2_structural_location_confluence(self):
        """Verifies WHERE: High structural location confluence (Order Block + VWAP + POC)."""
        pipeline = HierarchicalSignalPipeline()
        alert = make_test_alert(
            alert_id="CONF-01",
            alert_type="SMC_ORDERBLOCK_RETEST",
            symbol="INFY",
            metrics={
                "nearest_demand_ob": 1850.0,
                "vwap": 1852.0,
                "poc": 1851.0,
                "has_flow": True,
            },
        )
        ctx = pipeline.evaluate_market_context_3cs(symbol="INFY", alert=alert)
        setup = pipeline.validate_signal_setup_5ws(alert=alert, context=ctx)
        assert "SMC_ORDER_BLOCK" in setup.location_anchors
        assert "INTRADAY_VWAP" in setup.location_anchors
        assert "VOLUME_PROFILE_POC" in setup.location_anchors
        assert setup.structural_confluence_score >= 80
        assert setup.has_sufficient_confluence is True


class TestLevel3ExecutionMatrixHow:
    """Tests Level 3: Execution Matrix (1H: HOW)."""

    def test_level3_anti_chase_boundary_violation_vetoed(self):
        """Verifies HOW: Setup where LTP has surged past no-chase boundary is vetoed."""
        pipeline = HierarchicalSignalPipeline()
        alert = make_test_alert(
            alert_id="CHASE-01",
            alert_type="INTRADAY_BREAKOUT_SPARK",
            symbol="TCS",
            direction="BULLISH",
            ltp=4120.0,
            trigger_level=4100.0,
            stop_loss=4070.0,
            target_level=4200.0,
            no_chase_boundary=4110.0,  # LTP 4120 > 4110
        )
        ctx = pipeline.evaluate_market_context_3cs(symbol="TCS", alert=alert)
        setup = pipeline.validate_signal_setup_5ws(alert=alert, context=ctx)
        exec_matrix = pipeline.build_execution_matrix_how(alert=alert, context=ctx, setup=setup)
        assert exec_matrix.is_chased is True
        assert exec_matrix.passed is False
        assert exec_matrix.status == "CHASED_ENTRY"

    def test_level3_poor_indicative_rr_vetoed(self):
        """Verifies HOW: Net executable R:R below 1:1.8 floor is vetoed."""
        pipeline = HierarchicalSignalPipeline()
        alert = make_test_alert(
            alert_id="POOR-RR-01",
            alert_type="INTRADAY_BREAKOUT_SPARK",
            symbol="SBIN",
            direction="BULLISH",
            ltp=800.0,
            trigger_level=800.0,
            stop_loss=785.0,  # 15 pts risk
            target_level=815.0,  # 15 pts reward -> 1.0 R:R < 1.8 floor
        )
        ctx = pipeline.evaluate_market_context_3cs(symbol="SBIN", alert=alert)
        setup = pipeline.validate_signal_setup_5ws(alert=alert, context=ctx)
        exec_matrix = pipeline.build_execution_matrix_how(alert=alert, context=ctx, setup=setup)
        assert exec_matrix.passed is False
        assert exec_matrix.status == "POOR_INDICATIVE_RR"
        assert exec_matrix.executable_indicative_rr < 1.8


class TestHierarchicalMasterPipeline:
    """Tests Master Institutional Orchestration & AutoAlertEngine Integration."""

    def test_master_pipeline_apex_confluence_approval(self):
        """Verifies an apex confluence setup passes all 3 tiers with APEX_APPROVED verdict."""
        alert = make_test_alert(
            alert_id="APEX-01",
            alert_type="PREDATOR_SWEEP",
            symbol="NIFTY",
            exchange="NSE",
            direction="BULLISH",
            ltp=25000.0,
            trigger_level=25000.0,
            stop_loss=24930.0,  # 70 pts risk
            target_level=25180.0,  # 180 pts reward (2.57 R:R)
            no_chase_boundary=25025.0,
            metrics={
                "sweep_type": "BULLISH_PREDATOR_SPRING",
                "nearest_demand_ob": 24980.0,
                "vwap": 25005.0,
                "poc": 24995.0,
                "has_flow": True,
                "rvol": 1.8,
            },
        )
        ref_time = datetime(2026, 11, 10, 10, 15, tzinfo=IST)  # Morning Trend window
        verdict = hierarchical_pipeline.evaluate(alert=alert, ref_dt=ref_time)
        assert verdict.passed is True
        assert verdict.conviction_tier == "APEX_CONFLUENCE"
        assert verdict.composite_confluence_score >= 85
        assert verdict.level1_context.passed is True
        assert verdict.level2_setup.passed is True
        assert verdict.level3_execution.passed is True

    def test_engine_record_alert_attaches_hierarchical_pipeline_metrics(self, clean_engine):
        """Verifies AutoAlertEngine records and stamps hierarchical_pipeline metrics into the alert."""
        alert = make_test_alert(
            alert_id="TITAN-HIERARCHICAL-01",
            alert_type="PREDATOR_SWEEP",
            stage="IGNITED",
            exchange="NSE",
            headline="Titan Company Predator Sweep",
            summary="Institutional liquidity sweep at PDL with wick rejection and Order Block retest",
            ltp=3500.0,
            symbol="TITAN",
            direction="BULLISH",
            trigger_level=3500.0,
            stop_loss=3460.0,  # 40 pts risk
            target_level=3620.0,  # 120 pts reward (3.0 R:R)
            no_chase_boundary=3514.0,
            confidence=92,
            metrics={
                "sweep_type": "BULLISH_PREDATOR_SPRING",
                "nearest_demand_ob": 3480.0,
                "vwap": 3495.0,
                "is_decoupler": True,
            },
            is_live=True,
            environment="LIVE",
        )
        recorded = clean_engine.record_alert(alert)
        assert recorded is True
        assert "hierarchical_pipeline" in alert.metrics
        h_dict = alert.metrics["hierarchical_pipeline"]
        assert h_dict["passed"] is True
        assert "composite_confluence_score" in alert.metrics
        # Audit trail must document hierarchical pipeline passage
        assert any(
            evt.get("event_type") == "HIERARCHICAL_PIPELINE_PASSED" for evt in alert.audit_trail
        )

    def test_defined_risk_spread_passes_non_directional_rr(self):
        """Verifies a Defined-Risk Iron Condor / Credit Spread is calibrated to credit return and not vetoed by directional R:R."""
        alert = make_test_alert(
            alert_id="CONDOR-01",
            alert_type="DEFINED_RISK_NEUTRAL",
            symbol="NIFTY",
            exchange="NSE",
            direction="NEUTRAL",
            derivative_type="SPREAD",
            headline="Defined-Risk Iron Condor: NIFTY Neutral Harvest",
            summary="Range-bound consolidation harvest with hedged wings",
            ltp=25000.0,
            trigger_level=25000.0,
            stop_loss=24800.0,
            target_level=25100.0,
            metrics={
                "net_credit": 2500.0,
                "max_loss": 7500.0,
                "max_profit": 2500.0,
                "strategy": "IRON_CONDOR",
            },
        )
        verdict = hierarchical_pipeline.evaluate(alert=alert)
        assert verdict.strategy_orientation == "NON_DIRECTIONAL"
        assert verdict.level3_execution.passed is True
        assert verdict.level3_execution.entry_style == "NET_CREDIT_LIMIT"
        assert verdict.level3_execution.status == "EXECUTABLE"

    def test_multibagger_swing_horizon_exempt_from_intraday_clock(self):
        """Verifies Swing / Multibagger setups auto-resolve non-intraday horizon and bypass session timing veto."""
        alert = make_test_alert(
            alert_id="MULTI-01",
            alert_type="MULTIBAGGER_COMPOUNDER",
            symbol="PERSISTENT",
            exchange="NSE",
            direction="BULLISH",
            headline="Multibagger Compounder Breakout",
            time_horizon="MULTIBAGGER",
            ltp=5500.0,
            trigger_level=5500.0,
            stop_loss=5100.0,  # 400 pts risk
            target_level=7500.0,  # 2000 pts reward (5:1 R:R)
            metrics={
                "nearest_demand_ob": 5300.0,
                "multibagger_score": 92,
            },
        )
        # Evaluated at 12:30 IST (midday compression where intraday momentum is vetoed)
        ref_time = datetime(2026, 11, 10, 12, 30, tzinfo=IST)
        verdict = hierarchical_pipeline.evaluate(alert=alert, ref_dt=ref_time)
        assert verdict.time_horizon in ("MULTIBAGGER", "SWING")
        assert verdict.level2_setup.session_window == "OFF_MARKET_SWING"
        assert verdict.level2_setup.timing_allowed is True
