"""
tests/test_learning_engine.py
─────────────────────────────
Unit tests for PatternLearningEngine and Pre-Blast Deciding Factor Detection.
"""

from __future__ import annotations

from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from engine.learning_engine import (
    PatternLearningEngine,
    PatternMatchResult,
)


@pytest.fixture
def temp_learning_engine(tmp_path, monkeypatch):
    """Provides a fresh PatternLearningEngine backed by temporary storage."""
    temp_file = tmp_path / "pattern_memory.json"
    monkeypatch.setattr("engine.learning_engine.get_pattern_memory_file", lambda: temp_file)
    return PatternLearningEngine()


def test_new_engine_starts_without_unverified_fingerprints_or_performance_claims(
    temp_learning_engine,
):
    assert temp_learning_engine.get_learned_archetypes() == []
    analytics = temp_learning_engine.get_learning_analytics()
    assert analytics["total_archetypes_learned"] == 0
    assert analytics["win_rate_pct"] is None
    assert analytics["average_realized_rr"] is None


def test_market_mover_scan_uses_canonical_universe_and_stops_if_unavailable(
    temp_learning_engine, monkeypatch
):
    from analysis import universe as universe_module
    from market import history as history_module

    resolved: list[str] = []

    def resolve(name, **kwargs):
        resolved.append(name)
        return (["INFY", "TCS"], "test canonical universe")

    monkeypatch.setattr(universe_module, "resolve_dynamic_universe", resolve)
    monkeypatch.setattr(history_module, "get_ohlcv", lambda *args, **kwargs: None)

    assert temp_learning_engine.scan_and_learn_from_market_movers() == []
    assert resolved == ["nifty50"]

    resolved.clear()
    monkeypatch.setattr(
        universe_module,
        "resolve_dynamic_universe",
        lambda *args, **kwargs: ([], "unavailable"),
    )
    assert temp_learning_engine.scan_and_learn_from_market_movers() == []
    assert resolved == []


def test_register_new_explosive_move(temp_learning_engine):
    """Engine can register, learn from, and persist a new explosive move."""
    # Synthetic DataFrame
    dates = pd.date_range("2026-08-01", periods=25, freq="D")
    df = pd.DataFrame(
        {
            "open": np.linspace(100, 110, 25),
            "high": np.linspace(102, 112, 25),
            "low": np.linspace(99, 109, 25),
            "close": np.linspace(101, 111, 25),
            "volume": [100000] * 23 + [15000, 250000],  # Penultimate bar has 85% volume dry-up
        },
        index=dates,
    )

    fp = temp_learning_engine.register_explosive_move(
        symbol="HAL",
        move_pct=6.5,
        rvol_surge=2.5,
        catalyst="Defence Export Order Inflow",
        df=df,
        date_str="2026-09-08",
    )

    assert fp.symbol == "HAL"
    assert fp.move_pct == 6.5
    assert fp.prior_vol_ratio < 0.25  # Detected the dry-up!
    assert fp.fingerprint_score is None
    assert len(temp_learning_engine.get_learned_archetypes()) == 1
    assert temp_learning_engine.get_learned_archetypes()[0]["provenance"] == (
        "USER_SUBMITTED_UNVERIFIED"
    )


def test_historical_features_cannot_use_current_chain_sector_or_fundamentals(
    temp_learning_engine, monkeypatch
):
    from analysis import fundamental, sector_rotation

    current_sector = Mock(return_value={"quadrant": "LEADING"})
    current_fundamentals = Mock()
    monkeypatch.setattr(sector_rotation, "get_stock_sector_alignment", current_sector)
    monkeypatch.setattr(fundamental, "_fund_cache", current_fundamentals)
    df = pd.DataFrame(
        {
            "open": [100.0] * 25,
            "high": [101.0] * 25,
            "low": [99.0] * 25,
            "close": [100.0] * 25,
            "volume": [100_000] * 25,
        },
        index=pd.date_range("2025-01-01", periods=25),
    )
    chain = [Mock(option_type="CE", oi=10_000, oi_change=-3_000)]
    features = temp_learning_engine.extract_pre_blast_features(
        "TCS", df=df, chain=chain, is_historical_blast=True, allow_network=True
    )
    assert features["ce_unwind_pct"] is None
    assert features["rrg_quadrant"] is None
    assert features["sepa_qualified"] is None
    current_sector.assert_not_called()
    current_fundamentals.get.assert_not_called()


def test_market_mover_is_learned_once_on_observed_event_date(temp_learning_engine, monkeypatch):
    from market import history

    df = pd.DataFrame(
        {
            "open": [100.0] * 25,
            "high": [111.0] * 25,
            "low": [99.0] * 25,
            "close": [100.0] * 24 + [110.0],
            "volume": [100_000] * 24 + [250_000],
        },
        index=pd.date_range("2025-01-01", periods=25),
    )
    df.attrs["provenance"] = {"data_source": "HISTORICAL_EOD"}
    monkeypatch.setattr(history, "get_ohlcv", lambda *args, **kwargs: df)
    first = temp_learning_engine.scan_and_learn_from_market_movers(universe=["TCS"])
    assert len(first) == 1
    assert first[0].date == "2025-01-25"
    assert temp_learning_engine.scan_and_learn_from_market_movers(universe=["TCS"]) == []

    # A missing reference-volume baseline cannot be repaired with a one-unit floor.
    df.loc[df.index[:-1], "volume"] = 0
    assert temp_learning_engine.scan_and_learn_from_market_movers(universe=["INFY"]) == []


def test_evaluate_candidate_high_conviction(temp_learning_engine, monkeypatch):
    """Candidate meeting dry-up + squeeze + call unwinding yields explosive candidate status."""
    dates = pd.date_range("2026-08-01", periods=25, freq="D")
    df = pd.DataFrame(
        {
            "open": [200.0] * 25,
            "high": [201.0] * 25,
            "low": [199.0] * 25,
            "close": [200.0] * 25,
            "volume": [500000] * 23 + [50000, 100000],  # 90% dry-up on penultimate bar
        },
        index=dates,
    )

    class MockContract:
        option_type = "CE"
        strike = 200.0
        oi = 10000
        oi_change = -3000  # -30% unwind

    monkeypatch.setattr(
        temp_learning_engine,
        "extract_pre_blast_features",
        lambda *args, **kwargs: {
            "prior_vol_ratio": 0.10,
            "squeeze_bars": 4,
            "ce_unwind_pct": -30.0,
            "ob_distance_pct": 0.2,
            "rrg_quadrant": "LEADING",
            "coiling_pivot_high": 201.0,
            "sepa_qualified": True,
        },
    )

    res = temp_learning_engine.evaluate_candidate(
        symbol="TESTSTOCK",
        df=df,
        chain=[MockContract()],
    )

    assert isinstance(res, PatternMatchResult)
    assert res.similarity_score >= 70
    assert any("Volume Dry-Up" in f for f in res.matched_factors)
    assert any("Call writers capitulating" in f for f in res.matched_factors)
    assert res.expected_asymmetry_rr is None
