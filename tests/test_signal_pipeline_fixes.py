"""Regression tests for RCA fixes: unit-safe no-chase, RRG decouplers, confluence, and Telegram gates."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine
from engine.confidence_calibrator import calibrate_alert_confidence
from engine.confluence_engine import evaluate_confluence
from engine.pipeline.hierarchical_engine import HierarchicalSignalPipeline
from engine.signal_enrichment import enrich_alert_with_feature_bus


def test_hierarchical_no_chase_never_compares_spot_ltp_to_option_premium():
    """Regression for ANGELONE/BDL false veto: spot ₹380 must compare vs spot_no_chase_boundary, not ₹18.32 option NC."""
    engine = HierarchicalSignalPipeline()
    alert = AutoAlert(
        alert_id="aa-intraday-breakout-spark-angelone-20261127",
        alert_type="INTRADAY_BREAKOUT_SPARK",
        stage="PRIMED",
        symbol="ANGELONE",
        exchange="NFO",
        segment="FNO_STOCK",
        direction="BULLISH",
        headline="Spark ANGELONE",
        summary="Test",
        ltp=380.0,
        underlying_spot=380.0,
        trigger_level=377.4,
        target_level=410.0,
        stop_loss=366.0,
        contract_symbol="NSE:ANGELONE26DEC380CE",
        option_type="CE",
        option_premium=17.5,
        no_chase_boundary=18.32,
        spot_no_chase_boundary=384.0,
        confidence=95,
        metrics={"rvol": 4.2, "spot_change_pct": 5.4, "spot_no_chase_boundary": 384.0},
    )
    ctx = engine.evaluate_market_context_3cs(
        symbol="ANGELONE", exchange="NSE", ltp=380.0, alert=alert
    )
    setup = engine.validate_signal_setup_5ws(alert=alert, context=ctx)
    exe = engine.build_execution_matrix_how(alert, ctx, setup)

    assert exe.is_chased is False
    assert not any("surged past no-chase" in r for r in exe.reasons)


def test_hierarchical_rrg_allows_high_rvol_institutional_decoupler(monkeypatch):
    """Regression for HAL/MAZDOCK false veto: high-RVOL surge in LAGGING sector is a decoupler, not blocked."""
    monkeypatch.setattr(
        "analysis.sector_rotation.get_stock_sector_alignment",
        lambda _sym: {"sector": "INFRA", "quadrant": "LAGGING"},
    )
    engine = HierarchicalSignalPipeline()
    alert = AutoAlert(
        alert_id="aa-intraday-breakout-spark-hal-20261127",
        alert_type="INTRADAY_BREAKOUT_SPARK",
        stage="IGNITED",
        symbol="HAL",
        exchange="NSE",
        segment="FNO_STOCK",
        direction="BULLISH",
        headline="HAL surge",
        summary="Test",
        ltp=5120.0,
        trigger_level=5120.0,
        target_level=5320.0,
        stop_loss=5010.0,
        confidence=95,
        metrics={"rvol": 2.6, "spot_change_pct": 4.3, "is_decoupler": True},
    )
    ctx = engine.evaluate_market_context_3cs(symbol="HAL", exchange="NSE", ltp=5120.0, alert=alert)
    assert ctx.sector_aligned is True


def test_confluence_intraday_renormalization_and_enrichment():
    """Verify intraday setups without pre-open gap score >= 65 instead of permanent 41-54 cap."""
    rep = evaluate_confluence(
        symbol="VOLTAS",
        direction="BEARISH",
        ltp=1186.5,
        vwap=1205.0,
        rvol=2.3,
        change_pct=-3.1,
        pre_open_gap_pct=None,
        sector_quadrant="LAGGING",
        market_structure_signal="BOS",
    )
    assert rep.total_score >= 70.0
    assert rep.is_qualified is True

    # Verify signal_enrichment pulls rvol_ratio / feature_bus tod_rvol & maps structural archetype
    idx = pd.date_range("2026-11-27 09:15", periods=25, freq="5min")
    c = np.linspace(1210.0, 1185.0, 25)
    df_5m = pd.DataFrame(
        {
            "Open": c + 2.0,
            "High": c + 3.0,
            "Low": c - 3.0,
            "Close": c,
            "Volume": np.concatenate([np.full(20, 10_000.0), np.full(5, 45_000.0)]),
        },
        index=idx,
    )
    alert = AutoAlert(
        alert_id="aa-options-momentum-voltas-20261127",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="VOLTAS",
        exchange="NFO",
        segment="FNO_STOCK",
        direction="BEARISH",
        headline="VOLTAS breakdown",
        summary="Test",
        ltp=39.9,
        underlying_spot=1185.0,
        trigger_level=41.3,
        target_level=52.2,
        stop_loss=47.0,
        contract_symbol="NSE:VOLTAS26DEC1180PE",
        option_type="PE",
        metrics={"vwap": 1202.0, "rrg_quadrant": "LAGGING", "prev_close": 1215.0},
    )
    enriched = enrich_alert_with_feature_bus(alert, df_5m=df_5m)
    assert float(enriched["confluence_score"]) >= 65.0


def test_confidence_calibrator_friction_uses_planned_target_distance_on_extended_option():
    """Regression for SHRIRAMFIN 28.2% friction false cap when premium accelerated toward T1."""
    alert = AutoAlert(
        alert_id="aa-options-momentum-shriramfin-20261127",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="SHRIRAMFIN",
        exchange="NFO",
        segment="FNO_STOCK",
        direction="BEARISH",
        headline="SHRIRAMFIN dump",
        summary="Test",
        ltp=44.5,
        trigger_level=33.85,
        target_level=42.8,
        stop_loss=30.5,
        lot_size=150,
        option_type="PE",
        confidence=96,
        metrics={"composite_confluence_score": 82},
    )
    rep = calibrate_alert_confidence(alert)
    assert rep.cost_friction_pct is not None and rep.cost_friction_pct < 15.0
    assert rep.high_friction_risk is False


def test_auto_alert_engine_telegram_recognizes_strat_apex_and_composite_confluence(monkeypatch):
    """Verify SENSEX STRAT_2_1_2_BEARISH (APEX_CONFLUENCE) and composite confluence 84 pass Telegram gate."""
    monkeypatch.setenv("TELEGRAM_APEX_ONLY", "1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dummy")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("CHANAKYA_TESTING", raising=False)
    monkeypatch.delenv("DEPLOY_MODE", raising=False)
    engine = AutoAlertEngine.__new__(AutoAlertEngine)
    engine._lock = __import__("threading").RLock()
    engine._hourly_telegram_dispatches = {"INDEX": [], "STOCKS": [], "FNO_STOCK": [], "EQUITY": []}
    engine._hourly_index_directional = []
    engine._hourly_fno_stock_directional = []
    engine._dispatch_cooldowns = {}
    engine._watched_indices = ("NIFTY", "BANKNIFTY", "SENSEX", "MIDCPNIFTY", "FINNIFTY")
    engine.alerts = []

    sensex_alert = AutoAlert(
        alert_id="aa-strat-2-1-2-bearish-sensex-20261127",
        alert_type="STRAT_2_1_2_BEARISH",
        stage="CONFIRMED",
        symbol="SENSEX",
        exchange="BFO",
        segment="FNO_INDEX",
        direction="BEARISH",
        headline="SENSEX 2-1-2 Bearish",
        summary="Test",
        ltp=83600.0,
        trigger_level=83600.0,
        target_level=83000.0,
        stop_loss=83800.0,
        confidence=98,
        order_flow_signals={"call_writing": True, "vwap_breakdown": True},
        is_live=True,
        environment="LIVE",
        metrics={
            "conviction_tier": "APEX_CONFLUENCE",
            "composite_confluence_score": 84,
            "confluence_score": 60.0,
            "signals": ["STRAT_2_1_2_BEARISH", "VWAP_BREAKDOWN"],
        },
    )
    allowed, reason = engine._eval_telegram_apex_gate(sensex_alert, in_market=True)
    assert allowed is True, reason


def test_scan_pre_inflection_suppresses_bullish_dryup_during_nifty_markdown(monkeypatch):
    """Verify pre_inflection skips noisy counter-trend bullish scans when NIFTY is in markdown."""
    engine = AutoAlertEngine.__new__(AutoAlertEngine)
    engine._cached_pre_inflection = None
    engine.watched_equities = ["HAL", "RELIANCE"]

    monkeypatch.setattr(
        "engine.auto_alert_engine.AutoAlertEngine._should_run_detector",
        lambda self, n, c: True,
        raising=False,
    )
    nq = SimpleNamespace(change_pct=-0.75, last_price=25680.0, ltp=25680.0, vwap=25800.0)
    out = engine.scan_pre_inflection_dryup(quotes_map={"NSE:NIFTY 50": nq})
    assert out == []
