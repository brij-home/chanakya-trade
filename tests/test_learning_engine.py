"""
tests/test_learning_engine.py
─────────────────────────────
Unit tests for PatternLearningEngine and Pre-Blast Deciding Factor Detection.
"""

from __future__ import annotations

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


def test_seed_foundational_fingerprints(temp_learning_engine):
    """Engine initializes with foundational explosive move archetypes."""
    archetypes = temp_learning_engine.get_learned_archetypes()
    assert len(archetypes) >= 3
    symbols = [a["symbol"] for a in archetypes]
    assert "ADANIENT" in symbols
    assert "TRENT" in symbols
    assert "DIXON" in symbols


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
    assert len(temp_learning_engine.get_learned_archetypes()) >= 4


def test_evaluate_candidate_high_conviction(temp_learning_engine):
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

    res = temp_learning_engine.evaluate_candidate(
        symbol="TESTSTOCK",
        df=df,
        chain=[MockContract()],
    )

    assert isinstance(res, PatternMatchResult)
    assert res.similarity_score >= 70
    assert any("Volume Dry-Up" in f for f in res.matched_factors)
    assert any("Call writers capitulating" in f for f in res.matched_factors)
    assert res.expected_asymmetry_rr >= 2.0
