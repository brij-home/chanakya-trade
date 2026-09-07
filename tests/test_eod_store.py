"""
tests/test_eod_store.py
───────────────────────
Unit tests for the High-Performance Multi-Tier Local SQLite EOD Store,
Delta Sync, Fundamentals/Forensics Caching, and Liquidity/Circuit controls.
"""

from __future__ import annotations

import os
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from engine.eod_store import (
    init_eod_store,
    save_ohlcv_batch,
    get_cached_ohlcv,
    get_cached_ohlcv_batch,
    get_symbol_meta,
    get_stale_symbols,
    get_stale_symbols_detailed,
    save_fundamentals,
    save_fundamentals_batch,
    get_cached_fundamentals,
    get_cached_fundamentals_batch,
    save_forensics,
    save_forensics_batch,
    get_cached_forensics,
    get_cached_forensics_batch,
    get_store_statistics,
    clear_l1_caches,
)
from analysis.inflection_scanner import (
    evaluate_single_stock_inflection,
    scan_inflections_universe,
)


@pytest.fixture(autouse=True)
def temp_eod_db(tmp_path, monkeypatch):
    from engine.eod_store import reset_store_connections

    reset_store_connections()
    test_db = tmp_path / "test_eod_bars.db"
    monkeypatch.setenv("CHANAKYA_EOD_DB_PATH", str(test_db))
    monkeypatch.setenv("CHANAKYA_TESTING", "1")
    init_eod_store()
    yield test_db
    reset_store_connections()


def _generate_synthetic_df(
    symbol: str,
    days: int = 160,
    base_price: float = 100.0,
    daily_volume: int = 500000,
    is_uc: bool = False,
    end_date: str = "2026-09-04",
) -> pd.DataFrame:
    dates = pd.date_range(end=end_date, periods=days, freq="B")
    trend = np.linspace(0, 50, days)
    noise = np.sin(np.linspace(0, 10, days)) * 2

    closes = base_price + trend + noise
    highs = closes + 2.0
    lows = closes - 2.0
    opens = closes - 0.5
    volumes = [daily_volume] * days

    if is_uc:
        # Latest day locked at upper circuit (high == low == close, big jump)
        closes[-1] = closes[-2] * 1.05
        highs[-1] = closes[-1]
        lows[-1] = closes[-1]
        opens[-1] = closes[-1]
        volumes[-1] = 1000

    df = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        },
        index=dates,
    )
    df.index.name = "date"
    return df


def test_eod_store_crud_and_metadata():
    df_trent = _generate_synthetic_df("TEST_TRENT", days=160, base_price=200.0, daily_volume=800000)
    df_dixon = _generate_synthetic_df("TEST_DIXON", days=160, base_price=500.0, daily_volume=300000)

    saved = save_ohlcv_batch({"TEST_TRENT": df_trent, "TEST_DIXON": df_dixon})
    assert saved == 320

    # Test single retrieval (hits L1 cache or SQLite)
    cached_trent = get_cached_ohlcv("TEST_TRENT")
    assert cached_trent is not None
    assert len(cached_trent) == 160
    assert "close" in cached_trent.columns

    # Test batch retrieval
    batch = get_cached_ohlcv_batch(["TEST_TRENT", "TEST_DIXON"])
    assert "TEST_TRENT" in batch
    assert "TEST_DIXON" in batch
    assert len(batch["TEST_DIXON"]) == 160

    # Test metadata
    meta = get_symbol_meta("TEST_TRENT")
    assert meta is not None
    assert meta["bar_count"] == 160
    assert meta["median_turnover_20d"] > 0
    assert meta["high_52w"] >= meta["low_52w"]


def test_delta_append_and_metadata_integrity():
    # Initial 100 days
    df_base = _generate_synthetic_df("TEST_RELIANCE", days=100, end_date="2026-08-28")
    save_ohlcv_batch({"TEST_RELIANCE": df_base})

    meta1 = get_symbol_meta("TEST_RELIANCE")
    assert meta1["bar_count"] == 100

    # Append 5 new delta days
    df_delta = _generate_synthetic_df("TEST_RELIANCE", days=5, end_date="2026-09-04", base_price=160.0)
    save_ohlcv_batch({"TEST_RELIANCE": df_delta})

    meta2 = get_symbol_meta("TEST_RELIANCE")
    assert meta2["bar_count"] == 105
    assert meta2["last_date"] == "2026-09-04"

    # Verify cached retrieval contains full merged 105 bars
    full_cached = get_cached_ohlcv("TEST_RELIANCE")
    assert len(full_cached) == 105


def test_stale_detection_detailed():
    df = _generate_synthetic_df("TEST_TRENT", days=50, end_date="2026-08-01")
    save_ohlcv_batch({"TEST_TRENT": df})

    new_syms, delta_syms = get_stale_symbols_detailed(["TEST_TRENT", "TEST_MISSING"])
    assert "TEST_MISSING" in new_syms
    assert "TEST_TRENT" in delta_syms


def test_fundamentals_and_forensics_caching():
    fund_sample = {
        "pe": 24.5,
        "pb": 4.2,
        "roe": 18.5,
        "roce": 22.0,
        "debt_equity": 0.35,
        "promoter_holding": 52.0,
        "pledged_pct": 0.0,
        "market_cap": 125000.0,
        "sector": "Information Technology",
    }
    save_fundamentals("TEST_INFY", fund_sample)

    cached_fund = get_cached_fundamentals("TEST_INFY", max_age_days=30)
    assert cached_fund is not None
    assert cached_fund["roe"] == 18.5
    assert cached_fund["sector"] == "Information Technology"

    forensic_sample = {
        "beneish_m_score": -2.45,
        "is_manipulator_risk": False,
        "altman_z_score": 4.8,
        "distress_zone": "SAFE",
        "piotroski_f_score": 8,
        "quality_rating": "A+",
        "overall_forensic_verdict": "CLEAN_PASS",
        "governance_red_flags": [],
        "strengths": ["Clean earnings", "Strong liquidity"],
    }
    save_forensics("TEST_INFY", forensic_sample)

    cached_for = get_cached_forensics("TEST_INFY", max_age_days=30)
    assert cached_for is not None
    assert cached_for["quality_rating"] == "A+"
    assert cached_for["piotroski_f_score"] == 8

    # Verify store diagnostics
    stats = get_store_statistics()
    assert stats["fundamentals_count"] >= 1
    assert stats["forensics_count"] >= 1


def test_liquidity_filter_control():
    # Low turnover stock: 500 shares at ₹20 = ₹10,000 daily turnover (< 0.001 Cr)
    df_illiquid = _generate_synthetic_df("PENNY_STOCK", days=50, base_price=20.0, daily_volume=500)

    # Should be rejected with min_turnover_cr = 0.5 (₹50 Lakhs)
    setup = evaluate_single_stock_inflection("PENNY_STOCK", df=df_illiquid, min_turnover_cr=0.5)
    assert setup is None

    # Should be accepted when min_turnover_cr is 0.0
    setup_allow = evaluate_single_stock_inflection("PENNY_STOCK", df=df_illiquid, min_turnover_cr=0.0)
    assert setup_allow is not None
    assert setup_allow.turnover_20d_cr < 0.05


def test_circuit_lock_and_weekly_alignment():
    # Upper circuit stock
    df_uc = _generate_synthetic_df("UC_STOCK", days=160, base_price=100.0, is_uc=True)
    setup = evaluate_single_stock_inflection("UC_STOCK", df=df_uc)
    assert setup is not None
    assert setup.circuit_state == "UPPER_CIRCUIT_LOCKED"
    assert setup.execution_ticket["is_executable"] is False
    assert "Upper Circuit" in setup.confluence_factors[0] or any("Circuit" in c for c in setup.confluence_factors)
    assert setup.weekly_stage == "WEEKLY_STAGE_2"
