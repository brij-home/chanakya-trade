"""
tests/test_analysis_cache.py
────────────────────────────
Unit tests for AnalysisCache (SQLite persistence, TTL, price drift, pruning, token savings).
"""

import pytest
import time
from pathlib import Path
from engine.analysis_cache import AnalysisCache


@pytest.fixture
def temp_cache(tmp_path):
    db_file = tmp_path / "test_cache.db"
    return AnalysisCache(db_path=db_file, max_records=5)


def test_cache_save_and_get(temp_cache):
    temp_cache.save_analysis(
        symbol="RELIANCE",
        exchange="NSE",
        spot_price=2800.0,
        verdict="BUY",
        confidence=85,
        report="# Analysis Report",
        trade_plans={"strategy": "Delivery"},
        analyst_signals=[{"persona": "Technical", "verdict": "BUY"}],
        ttl_minutes=10,
    )

    cached = temp_cache.get_analysis("RELIANCE", "NSE", current_spot=2805.0)
    assert cached is not None
    assert cached["symbol"] == "RELIANCE"
    assert cached["verdict"] == "BUY"
    assert cached["trade_plans"]["strategy"] == "Delivery"
    assert cached["is_cached"] is True


def test_cache_price_drift_invalidation(temp_cache):
    temp_cache.save_analysis(
        symbol="INFY",
        exchange="NSE",
        spot_price=1500.0,
        verdict="BUY",
        report="Report",
        ttl_minutes=15,
    )

    # 0.5% drift -> Valid (below 1.0% limit)
    assert temp_cache.get_analysis("INFY", "NSE", current_spot=1507.0, max_price_drift_pct=1.0) is not None

    # 2.0% drift (1500 -> 1535) -> Invalidated due to market price movement
    assert temp_cache.get_analysis("INFY", "NSE", current_spot=1535.0, max_price_drift_pct=1.0) is None


def test_cache_macro_storage(temp_cache):
    temp_cache.save_macro("usdinr_snapshot", {"rate": 86.5, "trend": "UP"}, ttl_minutes=5)
    macro = temp_cache.get_macro("usdinr_snapshot")
    assert macro is not None
    assert macro["rate"] == 86.5


def test_cache_pruning_and_stats(temp_cache):
    # Insert 6 records (max is 5)
    for i in range(6):
        temp_cache.save_analysis(
            symbol=f"SYM{i}",
            exchange="NSE",
            spot_price=100.0 + i,
            report=f"Report {i}",
            ttl_minutes=10,
        )

    stats = temp_cache.get_stats()
    assert stats["total_cached_analyses"] <= 5
    assert stats["db_size_kb"] > 0
