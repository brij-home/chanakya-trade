"""
tests/test_eod_store.py
───────────────────────
Unit tests for the High-Performance Local SQLite EOD Store and Liquidity/Circuit controls.
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
)
from analysis.inflection_scanner import (
    evaluate_single_stock_inflection,
    scan_inflections_universe,
)


@pytest.fixture(autouse=True)
def temp_eod_db(tmp_path, monkeypatch):
    test_db = tmp_path / "test_eod_bars.db"
    monkeypatch.setenv("CHANAKYA_EOD_DB_PATH", str(test_db))
    monkeypatch.setenv("CHANAKYA_TESTING", "1")
    init_eod_store()
    return test_db


def _generate_synthetic_df(
    symbol: str,
    days: int = 160,
    base_price: float = 100.0,
    daily_volume: int = 500000,
    is_uc: bool = False,
) -> pd.DataFrame:
    dates = pd.date_range(end="2026-09-04", periods=days, freq="B")
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

    # Test single retrieval
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


def test_eod_store_stale_detection():
    df = _generate_synthetic_df("TRENT", days=50)
    save_ohlcv_batch({"TRENT": df})

    stale = get_stale_symbols(["TRENT", "MISSING_SYM"])
    assert "MISSING_SYM" in stale


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
