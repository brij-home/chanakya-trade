"""
tests/test_data_reuse_pipeline.py
──────────────────────────────────
Unit tests validating architecture-wide data reuse, eliminating silos,
quote coalescing caching, and cross-subsystem sharing.
"""

import time
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock

from brokers.base import Quote
from market.quotes import get_quote, clear_quote_cache, _QUOTE_CACHE
from market.history import get_ohlcv, clear_df_memory_cache
from market.macro import get_macro_snapshot
from engine.backtest_vectorized import _fetch_ohlcv


def _generate_synthetic_ohlcv(days: int = 60) -> pd.DataFrame:
    dates = pd.date_range(end=pd.Timestamp.now(), periods=days, freq="B")
    data = {
        "open": np.linspace(100, 150, days),
        "high": np.linspace(105, 155, days),
        "low": np.linspace(95, 145, days),
        "close": np.linspace(102, 152, days),
        "volume": [500000.0] * days,
    }
    df = pd.DataFrame(data, index=dates)
    df.index.name = "date"
    return df


class TestDataReusePipeline:
    def setup_method(self):
        clear_quote_cache()
        clear_df_memory_cache()

    def teardown_method(self):
        clear_quote_cache()
        clear_df_memory_cache()

    def test_quote_coalescing_cache(self):
        """Verify rapid repeated calls to get_quote hit in-memory cache and avoid duplicate vendor calls."""
        fake_quote = Quote(
            symbol="INFY",
            last_price=1850.50,
            open=1840.0,
            high=1860.0,
            low=1835.0,
            close=1845.0,
            volume=1000000,
            change=5.50,
            change_pct=0.30,
        )

        with patch("market.quotes.get_data_broker") as mock_broker_fn, \
             patch("market.quotes._yf_fallback_quotes") as mock_yf:
            mock_broker = MagicMock()
            mock_broker.get_quote.return_value = {"NSE:INFY": fake_quote}
            mock_broker_fn.return_value = mock_broker

            # Call 1: Cache miss, hits broker
            q1 = get_quote(["NSE:INFY"])
            assert "NSE:INFY" in q1
            assert q1["NSE:INFY"].last_price == 1850.50
            assert mock_broker.get_quote.call_count == 1

            # Call 2 & 3: Within 3s TTL, should hit _QUOTE_CACHE with zero additional vendor calls
            q2 = get_quote(["NSE:INFY"])
            q3 = get_quote(["INFY"])
            assert q2["NSE:INFY"].last_price == 1850.50
            assert q3["INFY"].last_price == 1850.50
            assert mock_broker.get_quote.call_count == 1  # Unchanged!

            # Call 4: With bypass_cache=True, forces query
            q4 = get_quote(["NSE:INFY"], bypass_cache=True)
            assert mock_broker.get_quote.call_count == 2

    def test_get_ohlcv_reuses_eod_store(self):
        """Verify market.history.get_ohlcv retrieves from engine.eod_store when available."""
        df_sample = _generate_synthetic_ohlcv(50)

        with patch("engine.eod_store.get_ohlcv_batch", return_value={"TATAMOTORS": df_sample}) as mock_store, \
             patch("market.history._yfinance_fallback") as mock_yf:
            res_df = get_ohlcv("TATAMOTORS", interval="day", days=30)
            assert not res_df.empty
            assert len(res_df) >= 20  # 30 calendar days = ~21 business days
            assert res_df.attrs["provenance"]["provider"] == "eod_store"
            mock_store.assert_called_once_with(["TATAMOTORS"])
            mock_yf.assert_not_called()

    def test_get_ohlcv_persists_to_eod_store_on_vendor_fetch(self):
        """Verify market.history.get_ohlcv saves fresh vendor fetches to engine.eod_store."""
        raw_rows = [
            {"date": "2026-09-01", "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0, "volume": 10000.0},
            {"date": "2026-09-02", "open": 104.0, "high": 108.0, "low": 103.0, "close": 107.0, "volume": 12000.0},
            {"date": "2026-09-03", "open": 107.0, "high": 110.0, "low": 106.0, "close": 109.0, "volume": 15000.0},
            {"date": "2026-09-04", "open": 109.0, "high": 112.0, "low": 108.0, "close": 111.0, "volume": 14000.0},
        ]

        with patch("engine.eod_store.get_ohlcv_batch", return_value={}), \
             patch("engine.eod_store.save_ohlcv_batch") as mock_save, \
             patch("market.history._yfinance_fallback", return_value=raw_rows), \
             patch("market.history.save_ohlcv_cache"):
            res_df = get_ohlcv("NEWSTOCK", interval="day", days=10)
            assert not res_df.empty
            mock_save.assert_called_once()
            args, _ = mock_save.call_args
            assert "NEWSTOCK" in args[0]
            assert len(args[0]["NEWSTOCK"]) == 4

    def test_macro_snapshot_reuses_global_macro(self):
        """Verify market.macro.get_macro_snapshot reuses market.global_macro data."""
        mock_gm_item = MagicMock()
        mock_gm_item.ltp = 85.25
        mock_gm_item.change_pct = -0.15
        mock_gm_item.change = -0.12

        mock_gm = MagicMock()
        mock_gm.items = {
            "usdinr": mock_gm_item,
            "crude_oil": mock_gm_item,
            "gold": mock_gm_item,
            "us_10y": mock_gm_item,
            "dxy": mock_gm_item,
        }

        with patch("market.global_macro.get_global_macro_snapshot", return_value=mock_gm) as mock_fetch, \
             patch("engine.analysis_cache.analysis_cache.get_macro", return_value=None):
            snap = get_macro_snapshot()
            assert snap.usdinr == 85.25
            assert snap.usdinr_change == -0.15
            mock_fetch.assert_called_once()

    def test_backtest_vectorized_reuses_get_ohlcv(self):
        """Verify _fetch_ohlcv in backtest_vectorized routes through get_ohlcv."""
        df_sample = _generate_synthetic_ohlcv(100)

        with patch("market.history.get_ohlcv", return_value=df_sample) as mock_get_ohlcv:
            df = _fetch_ohlcv("INFY", period="1y")
            assert not df.empty
            assert len(df) == 100
            mock_get_ohlcv.assert_called_once()
