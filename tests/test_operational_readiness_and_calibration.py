"""
tests/test_operational_readiness_and_calibration.py
───────────────────────────────────────────────────
Tests for runtime calibration pipeline integration, warning-free sparse Meta-Model fit,
TickWarehouse compaction + IV backfill wiring, and honest Operational Readiness audit.
"""

from __future__ import annotations

import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from config.constants import IST


def test_meta_model_sparse_all_nan_columns_no_runtime_warning():
    from engine.meta_labeler import train_purged_meta_model

    records = [
        {
            "trigger_time": f"2026-10-{1 + (i // 3):02d}T{10 + (i % 3):02d}:00:00+05:30",
            "features": {"tod_rvol": 1.2 + (i % 5) * 0.4, "spread_bps": 8.0},
            "net_r": 2.0 if i % 2 == 0 else -1.0,
        }
        for i in range(40)
    ]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model = train_purged_meta_model(records)
    nan_warnings = [w for w in caught if "Mean of empty slice" in str(w.message)]
    assert not nan_warnings
    assert model.status == "CALIBRATED"


def test_calibration_runner_replay_trains_meta_model_and_backfills_iv(monkeypatch, tmp_path: Path):
    from engine.calibration_runner import CalibrationRunner
    from engine.iv_surface import load_historical_30d_ivs
    from engine.meta_labeler import load_meta_model
    from engine.tick_warehouse import TickWarehouse
    import engine.tick_warehouse as tw_mod

    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))
    monkeypatch.setattr(tw_mod, "_GLOBAL_WAREHOUSE", TickWarehouse(base_dir=tmp_path / "ticks"))

    # Seed synthetic warehouse 5m bars across NIFTY & RELIANCE with enough swings for >= 30 trades
    rng = np.random.default_rng(99)
    n = 420
    idx = pd.date_range("2026-11-10 09:15", periods=n, freq="5min")
    t = np.arange(n, dtype=float)
    nifty_c = 25000.0 + 110.0 * np.sin(t / 4.0) + rng.normal(0.0, 8.0, size=n)
    rel_c = 1400.0 + 18.0 * np.sin(t / 4.0) + rng.normal(0.0, 2.0, size=n)

    def _df(c_arr: np.ndarray) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "open": c_arr - 2.0,
                "high": c_arr + 9.0,
                "low": c_arr - 9.0,
                "close": c_arr,
                "volume": rng.integers(20_000, 90_000, size=n).astype(float),
            },
            index=idx,
        )

    mock_bars = {"NIFTY": _df(nifty_c), "RELIANCE": _df(rel_c)}
    monkeypatch.setattr(
        "engine.historical_warehouse.historical_warehouse.load_bars",
        lambda sym, interval="5m": mock_bars.get(sym, pd.DataFrame()),
    )

    # Seed one TickWarehouse option chain snapshot partition to test IV surface backfill
    wh = tw_mod.get_tick_warehouse()
    snap_dt = datetime(2026, 11, 27, 14, 0, tzinfo=IST)
    wh.record_option_chain_snapshot(
        "NIFTY",
        [
            {
                "symbol": "NSE:NIFTY26DEC25000CE",
                "expiry": "2026-12-01",
                "strike": 25000.0,
                "option_type": "CE",
                "last_price": 120.0,
                "iv": 15.0,
                "delta": 0.51,
            },
            {
                "symbol": "NSE:NIFTY26DEC25000PE",
                "expiry": "2026-12-01",
                "strike": 25000.0,
                "option_type": "PE",
                "last_price": 115.0,
                "iv": 15.4,
                "delta": -0.49,
            },
            {
                "symbol": "NSE:NIFTY26DEC25000CE_N",
                "expiry": "2026-12-29",
                "strike": 25000.0,
                "option_type": "CE",
                "last_price": 290.0,
                "iv": 16.2,
                "delta": 0.52,
            },
        ],
        spot=25010.0,
        vix=14.8,
        timestamp_ms=int(snap_dt.timestamp() * 1000),
    )

    runner = CalibrationRunner()
    diag = runner._collect_options_replay_diagnostics()
    assert diag["status"] == "COMPLETED"
    assert diag["iv_snapshots_persisted"] >= 1
    assert len(load_historical_30d_ivs("NIFTY")) >= 1
    assert load_meta_model() is not None


def test_operational_readiness_audit_reports_honest_safety_and_gaps(monkeypatch, tmp_path: Path):
    from engine.operational_readiness import audit_operational_readiness

    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))
    monkeypatch.setenv("SESSION_FOCUS_MODE", "FNO_ONLY")
    monkeypatch.delenv("LIVE_EXECUTION_QUALIFIED", raising=False)
    monkeypatch.delenv("ALLOW_LIVE_TRADING", raising=False)
    monkeypatch.setenv("TRADING_MODE", "PAPER")

    rep = audit_operational_readiness(check_warehouse_bars=False)
    assert rep["execution_safety"]["trading_mode"] == "PAPER"
    assert rep["execution_safety"]["live_execution_qualified"] is False
    assert rep["execution_safety"]["live_orders_blocked"] is True
    assert rep["discovery_policy"]["profile"] == "FNO_ONLY"
    assert rep["calibration_and_research"]["meta_model_status"] == "UNCALIBRATED"
    assert rep["calibration_and_research"]["iv_rank_ready"] is False
    assert any("LIVE_EXECUTION_QUALIFIED" in g for g in rep["open_gaps"])


def test_options_replay_applies_statutory_stt_for_fno_not_zero():
    from engine.options_replay import evaluate_triple_barrier_outcomes

    idx = pd.date_range("2026-11-10 09:15", periods=40, freq="5min")
    df = pd.DataFrame(
        {
            "open": [200.0 + i * 0.5 for i in range(40)],
            "high": [203.0 + i * 0.5 for i in range(40)],
            "low": [199.0 + i * 0.5 for i in range(40)],
            "close": [201.0 + i * 0.5 for i in range(40)],
            "volume": [10_000.0] * 40,
        },
        index=idx,
    )
    ev = evaluate_triple_barrier_outcomes(
        df, [10], horizon_bars=10, segment="FNO", slippage_bps=0.0, quantity=75
    )
    assert ev["trades"] == 1
    assert ev["outcomes"][0]["charges"] > 45.0  # Includes brokerage + GST + 0.15% Option Sell STT


def test_warehouse_iv_surface_recovers_missing_spot_from_bars(monkeypatch, tmp_path: Path):
    """Archived option chain snapshots with NaN spot resolve causal spot from historical bars."""
    from engine.iv_surface import build_iv_surface_from_warehouse
    from engine.tick_warehouse import TickWarehouse
    import engine.tick_warehouse as tw_mod

    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))
    monkeypatch.setattr(tw_mod, "_GLOBAL_WAREHOUSE", TickWarehouse(base_dir=tmp_path / "ticks"))

    wh = tw_mod.get_tick_warehouse()
    snap_dt = datetime(2026, 11, 27, 11, 30, tzinfo=IST)
    wh.record_option_chain_snapshot(
        "SENSEX",
        [
            {
                "symbol": "BSE:SENSEX26DEC84000CE",
                "expiry": "2026-12-03",
                "strike": 84000.0,
                "option_type": "CE",
                "last_price": 450.0,
                "iv": 16.5,
                "delta": 0.51,
            },
            {
                "symbol": "BSE:SENSEX26DEC84000PE",
                "expiry": "2026-12-03",
                "strike": 84000.0,
                "option_type": "PE",
                "last_price": 440.0,
                "iv": 16.9,
                "delta": -0.49,
            },
        ],
        spot=None,
        timestamp_ms=int(snap_dt.timestamp() * 1000),
    )

    idx = pd.date_range("2026-11-27 09:15", periods=30, freq="5min")
    mock_bars = pd.DataFrame(
        {"open": 83980.0, "high": 84020.0, "low": 83950.0, "close": 84010.0, "volume": 1000.0},
        index=idx,
    )
    monkeypatch.setattr(
        "engine.historical_warehouse.historical_warehouse.load_bars",
        lambda sym, interval="5m": mock_bars if sym == "SENSEX" else pd.DataFrame(),
    )

    snap = build_iv_surface_from_warehouse("SENSEX", persist=False)
    assert snap.status == "AVAILABLE"
    assert snap.atm_iv_30d is not None and 15.0 <= snap.atm_iv_30d <= 18.0


def test_storage_stats_and_readiness_ttl_cache(monkeypatch, tmp_path: Path):
    """Verify fast os.scandir storage stats and readiness TTL caching return identical metrics."""
    from engine.operational_readiness import audit_operational_readiness
    from engine.tick_warehouse import TickWarehouse
    import engine.tick_warehouse as tw_mod

    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))
    wh = TickWarehouse(base_dir=tmp_path / "ticks")
    monkeypatch.setattr(tw_mod, "_GLOBAL_WAREHOUSE", wh)

    s1 = wh.get_storage_stats(max_cache_sec=15.0)
    s2 = wh.get_storage_stats(max_cache_sec=15.0)
    assert s1["parquet_files"] == 0 and s1 == s2

    r1 = audit_operational_readiness(check_warehouse_bars=False, max_cache_sec=15.0)
    r2 = audit_operational_readiness(check_warehouse_bars=False, max_cache_sec=15.0)
    assert r1["as_of"] == r2["as_of"]
