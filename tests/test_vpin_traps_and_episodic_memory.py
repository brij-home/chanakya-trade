# -*- coding: utf-8 -*-
"""
tests/test_vpin_traps_and_episodic_memory.py
────────────────────────────────────────────
Test suite for Next-Gen 2026 Quantitative Frontiers:
  1. Microstructure VPIN (Volume-Synchronized Probability of Toxicity)
  2. Adversarial Red-Teaming Trap Invalidator Gate
  3. Episodic Trade Memory & Reflective Experience Replay RAG
  4. Test-Time Reasoning Trajectory Simulator (Agentic MCTS)
"""

from __future__ import annotations

import tempfile
from pathlib import Path
import pandas as pd

from analysis.order_flow import compute_vpin
from engine.trap_invalidator import audit_trade_for_traps
from engine.episodic_memory import (
    EpisodicTradeMemoryStore,
    TradeEpisode,
)
from analysis.trajectory_search import (
    simulate_trade_trajectories,
)


def test_compute_vpin_directional_vs_balanced():
    """Verify VPIN correctly distinguishes toxic informed flow from balanced liquidity."""
    # 1. Toxic Informed Directional Flow (Price constantly runs up with accelerating volume)
    df_toxic = pd.DataFrame(
        {
            "close": [24500.0, 24520.0, 24545.0, 24580.0, 24620.0, 24660.0, 24710.0],
            "volume": [10000.0, 15000.0, 20000.0, 25000.0, 30000.0, 35000.0, 40000.0],
        }
    )
    res_toxic = compute_vpin("NIFTY", df_toxic, num_buckets=5)
    assert res_toxic.vpin >= 0.70
    assert res_toxic.toxicity_regime in ("HIGH_TOXICITY", "EXTREME_TOXICITY")
    assert res_toxic.directional_bias == "BUY_DOMINATED"
    assert res_toxic.adverse_selection_risk >= 0.70

    # 2. Balanced Oscillating Flow (Price chops back and forth, volumes equal)
    df_balanced = pd.DataFrame(
        {
            "close": [24500.0, 24504.0, 24500.0, 24504.0, 24500.0, 24504.0, 24500.0, 24504.0] * 5,
            "volume": [10000.0] * 40,
        }
    )
    res_balanced = compute_vpin("NIFTY", df_balanced, num_buckets=8)
    assert res_balanced.vpin < 0.40
    assert res_balanced.toxicity_regime == "LOW_TOXICITY"
    assert res_balanced.directional_bias == "BALANCED"


def test_audit_trade_for_traps_dry_volume():
    """Trap Invalidator must catch dry volume breakouts (RVOL < 0.85x) and demote them."""
    # 20 bars with volume 10,000, then breakout bar with volume 5,000 (RVOL = 0.50x)
    closes = [24500.0 + (i * 2.0) for i in range(21)]
    vols = [10000.0] * 20 + [5000.0]
    df = pd.DataFrame(
        {
            "open": [c - 5.0 for c in closes],
            "high": [c + 1.0 for c in closes],
            "low": [c - 5.0 for c in closes],
            "close": closes,
            "volume": vols,
        }
    )

    audit = audit_trade_for_traps(
        symbol="NIFTY",
        direction="LONG",
        entry_price=24540.0,
        stop_loss=24500.0,
        target_1=24620.0,
        df_bars=df,
    )

    assert audit.is_trap is False or audit.trap_score >= 35
    assert "DRY_VOLUME_BREAKOUT" in audit.flags
    assert audit.recommended_action == "DEMOTE_TO_LIMIT_RETEST"


def test_audit_trade_for_traps_rejection_wick():
    """Trap Invalidator must catch severe rejection wicks (>= 50%) and issue HARD_VETO."""
    # Last bar: high 24600, close 24520, open 24510, low 24505
    # Range is 95 pts. Upper wick = 24600 - 24520 = 80 pts (80/95 = 84% upper wick)
    df = pd.DataFrame(
        {
            "open": [24500.0] * 19 + [24510.0],
            "high": [24510.0] * 19 + [24600.0],
            "low": [24490.0] * 19 + [24505.0],
            "close": [24505.0] * 19 + [24520.0],
            "volume": [10000.0] * 20,
        }
    )

    audit = audit_trade_for_traps(
        symbol="NIFTY",
        direction="LONG",
        entry_price=24520.0,
        stop_loss=24470.0,
        target_1=24620.0,
        df_bars=df,
    )

    assert audit.is_trap is True
    assert audit.severity == "CRITICAL_INVALIDATION"
    assert audit.recommended_action == "HARD_VETO"
    assert "LONG_EXHAUSTION_REJECTION_WICK" in audit.flags


def test_audit_trade_for_traps_structural_resistance_collision():
    """Trap Invalidator must veto trades running directly into structural barriers (< 0.5R headroom)."""

    class MockDailyLevels:
        pdh = 24515.0  # Only 15 pts above entry
        pdl = 24300.0
        cpr = {"tc": 24512.0, "bc": 24480.0, "pivot": 24500.0}
        camarilla = {}

    dl = MockDailyLevels()
    audit = audit_trade_for_traps(
        symbol="NIFTY",
        direction="LONG",
        entry_price=24500.0,
        stop_loss=24450.0,  # 50 pts risk
        target_1=24600.0,
        daily_levels=dl,
    )

    # Headroom to CPR_TC (24512) is 12 pts. 12 / 50 = 0.24R (< 0.50R)
    assert audit.is_trap is True
    assert audit.severity == "CRITICAL_INVALIDATION"
    assert audit.recommended_action == "HARD_VETO"
    assert any("STRUCTURAL_COLLISION" in flag for flag in audit.flags)


def test_episodic_trade_memory_store_workflow():
    """Verify storing trade episodes and retrieving regime-conditioned analogies."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = Path(tmp_dir) / "test_episodes.db"
        store = EpisodicTradeMemoryStore(db_path=db_file)

        # Record 3 episodes
        ep1 = TradeEpisode(
            episode_id="ep-01",
            session_date="2026-10-25",
            symbol="NIFTY",
            direction="LONG",
            entry_price=24400.0,
            exit_price=24600.0,
            stop_loss=24300.0,
            target_1=24600.0,
            pnl_pts=200.0,
            pnl_pct=0.82,
            r_multiple=2.0,
            mfe_r=2.5,
            mae_r=0.25,
            execution_efficiency=0.80,
            vix_regime="NORMAL_IV",
            day_archetype="TREND_DAY",
            vpin_regime="HIGH_TOXICITY",
            holding_duration_mins=40.0,
            exit_reason="T1_HIT",
            win_loss="WIN",
        )
        ep2 = TradeEpisode(
            episode_id="ep-02",
            session_date="2026-10-26",
            symbol="NIFTY",
            direction="LONG",
            entry_price=24450.0,
            exit_price=24650.0,
            stop_loss=24350.0,
            target_1=24650.0,
            pnl_pts=200.0,
            pnl_pct=0.82,
            r_multiple=2.0,
            mfe_r=2.2,
            mae_r=0.30,
            execution_efficiency=0.85,
            vix_regime="NORMAL_IV",
            day_archetype="TREND_DAY",
            vpin_regime="HIGH_TOXICITY",
            holding_duration_mins=55.0,
            exit_reason="T1_HIT",
            win_loss="WIN",
        )

        assert store.record_episode(ep1) is True
        assert store.record_episode(ep2) is True

        res = store.query_analogous_episodes(
            symbol="NIFTY",
            direction="LONG",
            vix_regime="NORMAL_IV",
            day_archetype="TREND_DAY",
            vpin_regime="HIGH_TOXICITY",
            top_k=2,
        )

        assert res.sample_size == 2
        assert res.win_rate_pct == 100.0
        assert res.avg_mfe_r >= 2.0
        assert res.confidence_calibration == "HIGH_CONFIDENCE_SETUP"


def test_simulate_trade_trajectories_scenarios():
    """Verify trajectory simulation computes EV and identifies optimal execution styles."""
    # Scenario A: Trend Day with high institutional VPIN flow
    res_a = simulate_trade_trajectories(
        symbol="NIFTY",
        direction="LONG",
        spot=24500.0,
        entry_price=24500.0,
        stop_loss=24400.0,
        target_1=24700.0,
        vpin=0.75,
        day_archetype="TREND_DAY",
        rvol=1.60,
    )
    assert res_a.optimal_execution_style == "AGGRESSIVE_MOMENTUM"
    assert res_a.prob_expansion >= 0.55
    assert res_a.ev_market_chase_pts > 0.0

    # Scenario B: Normal Day with tight headroom and dry volume (Trap dominance)
    res_b = simulate_trade_trajectories(
        symbol="NIFTY",
        direction="LONG",
        spot=24500.0,
        entry_price=24500.0,
        stop_loss=24400.0,
        target_1=24700.0,
        vpin=0.35,
        day_archetype="NORMAL_DAY",
        rvol=0.70,
        has_exhaustion_wick=True,
        headroom_r=0.60,
    )
    assert res_b.optimal_execution_style == "ABORT_NEGATIVE_EXPECTANCY"
    assert res_b.prob_trap >= 0.45
