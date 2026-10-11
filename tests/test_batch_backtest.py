"""
tests/test_batch_backtest.py
----------------------------
Deterministic unit tests for BatchBacktester and NSECharges (#158).
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from engine.batch_backtest import BatchBacktester, NSECharges, BatchBacktestReport
from engine.backtest import RSIStrategy


def _make_synthetic_bars(n: int = 500, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2021-01-01", periods=n, freq="B")
    close = 1000.0 * np.cumprod(1 + rng.normal(0.0005, 0.015, size=n))
    high = close * (1 + rng.uniform(0, 0.02, size=n))
    low = close * (1 - rng.uniform(0, 0.02, size=n))
    open_ = close * (1 + rng.normal(0, 0.005, size=n))
    volume = rng.integers(100_000, 1_000_000, size=n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


class TestNSECharges:
    def test_delivery_charges_positive(self):
        charges = NSECharges.delivery_charges(entry_price=1000.0, quantity=100, exit_price=1100.0)
        assert charges > 0.0
        # Delivery STT on sell side is 0.1% = 110, plus stamp duty on buy side (15), brokerage (40), etc.
        assert 100.0 < charges < 300.0

    def test_intraday_charges_positive(self):
        charges = NSECharges.intraday_charges(entry_price=1000.0, quantity=100, exit_price=1050.0)
        assert charges > 0.0
        # Intraday charges should be lower than delivery due to lower STT
        deliv_charges = NSECharges.delivery_charges(
            entry_price=1000.0, quantity=100, exit_price=1050.0
        )
        assert charges < deliv_charges

    def test_zero_quantity_or_price(self):
        charges = NSECharges.delivery_charges(entry_price=0.0, quantity=0, exit_price=0.0)
        assert charges == 0.0


class TestBatchBacktester:
    def test_init_defaults(self):
        tester = BatchBacktester(strategy=RSIStrategy(), period="5y")
        assert tester.period == "5y"
        assert tester.include_charges is True
        assert tester.trade_type == "delivery"

    def test_batch_run_with_synthetic_injection(self, monkeypatch):
        # Mock get_local_ohlcv_batch to return synthetic bars for test symbols
        df1 = _make_synthetic_bars(n=500, seed=1)
        df2 = _make_synthetic_bars(n=500, seed=2)

        def mock_get_local_ohlcv_batch(symbols, **kwargs):
            return {"TESTA": df1, "TESTB": df2}

        monkeypatch.setattr(
            "engine.batch_backtest.get_local_ohlcv_batch",
            mock_get_local_ohlcv_batch,
        )

        tester = BatchBacktester(
            strategy=RSIStrategy(buy_level=30, sell_level=70),
            period="2y",
            n_workers=2,
            include_charges=True,
            persist_results=False,
        )

        report = tester.run(symbols=["TESTA", "TESTB"])
        assert isinstance(report, BatchBacktestReport)
        assert report.total_symbols == 2
        assert report.successful == 2
        assert report.failed == 0
        assert len(report.leaderboard) == 2
        assert report.leaderboard[0].ranked_position == 1
        assert report.leaderboard[1].ranked_position == 2
