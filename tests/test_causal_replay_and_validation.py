"""
tests/test_causal_replay_and_validation.py
──────────────────────────────────────────
Unit tests for causal replay, controllable clock, dataset manifest generation,
and conservative same-bar fill logic (R01 / R02).
"""

from __future__ import annotations

from datetime import datetime
import pandas as pd
import pytest

from engine.backtest import (
    Backtester,
    Strategy,
    generate_dataset_manifest,
)
from engine.options_backtest import (
    OptionsBacktester,
)


class DummyClock:
    def __init__(self, current_dt: datetime):
        self._dt = current_dt

    def now(self) -> datetime:
        return self._dt


class SimpleSignalStrategy(Strategy):
    name = "SimpleSignal"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        # Buy on day 2, sell on day 4
        signals = pd.Series(0, index=df.index)
        if len(signals) > 4:
            signals.iloc[2] = 1
            signals.iloc[4] = -1
        return signals


def _build_test_df(n: int = 10) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    data = {
        "open": [100.0 + i for i in range(n)],
        "high": [105.0 + i for i in range(n)],
        "low": [98.0 + i for i in range(n)],
        "close": [102.0 + i for i in range(n)],
        "volume": [10000] * n,
    }
    return pd.DataFrame(data, index=idx)


def test_dataset_manifest_generation():
    df = _build_test_df(10)
    manifest = generate_dataset_manifest(df, symbol="RELIANCE", source="TEST_SOURCE")

    assert manifest.symbol == "RELIANCE"
    assert manifest.source == "TEST_SOURCE"
    assert manifest.schema_version == "1.0"
    assert len(manifest.sha256) == 64
    assert manifest.row_count == 10
    assert manifest.start_session == "2026-01-01"
    assert manifest.end_session == "2026-01-10"
    assert manifest.session_count == 10
    assert "close" in manifest.columns

    manifest_dict = manifest.to_dict()
    assert manifest_dict["sha256"] == manifest.sha256

    with pytest.raises(ValueError, match="Cannot generate manifest for empty dataset"):
        generate_dataset_manifest(pd.DataFrame(), symbol="RELIANCE")


def test_backtester_clock_causality():
    df = _build_test_df(10)
    clock = DummyClock(datetime(2026, 1, 5, 15, 30))

    bt = Backtester(symbol="TEST", period="1y", clock=clock)
    bt._df = df  # preset DataFrame
    loaded = bt._load_data()

    # Dates after 2026-01-05 should be excluded
    assert len(loaded) == 5
    assert str(loaded.index[-1])[:10] == "2026-01-05"


def test_backtester_conservative_fills_adverse_pricing():
    df = _build_test_df(10)
    strat = SimpleSignalStrategy()

    # Naive fills
    bt_naive = Backtester(symbol="TEST", capital=100000, conservative_fills=False)
    bt_naive._df = df.copy()
    res_naive = bt_naive.run(strat)

    # Conservative fills with 50bps slippage
    bt_cons = Backtester(symbol="TEST", capital=100000, conservative_fills=True, slippage_bps=50.0)
    bt_cons._df = df.copy()
    res_cons = bt_cons.run(strat)

    assert len(res_naive.trades) == 1
    assert len(res_cons.trades) == 1

    t_naive = res_naive.trades[0]
    t_cons = res_cons.trades[0]

    # In conservative fills:
    # Entry price should be higher than naive (paying adverse ask / intrabar high)
    assert t_cons.entry_price > t_naive.entry_price
    # Exit price should be lower than naive (receiving adverse bid / intrabar low)
    assert t_cons.exit_price < t_naive.exit_price
    # Net PnL must be strictly less for conservative fills
    assert t_cons.pnl < t_naive.pnl


def test_options_backtester_conservative_fills():
    bt_naive = OptionsBacktester(
        underlying="NIFTY",
        period="1mo",
        capital=100000,
        conservative_fills=False,
    )
    bt_cons = OptionsBacktester(
        underlying="NIFTY",
        period="1mo",
        capital=100000,
        conservative_fills=True,
        slippage_bps=50.0,
    )

    assert bt_cons.conservative_fills is True
    assert bt_cons.slippage_bps == 50.0
    assert bt_naive.conservative_fills is False
