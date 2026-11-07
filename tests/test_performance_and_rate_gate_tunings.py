"""
tests/test_performance_and_rate_gate_tunings.py
─────────────────────────────────────────────────
Deterministic regression tests verifying:
1. Pre-warming chains_map in AutoAlertEngine to eliminate parallel detector REST races.
2. quotes_map and targets passthrough to asymmetric_radar.
3. AsymmetricRadar Stage 0 RAM pre-filter and 16.0s internal SLA timeout guard.
4. MarketMatrix in-RAM synthesized intraday bars resolution in market.history.get_ohlcv.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock
import pandas as pd

from engine.asymmetric_radar import AsymmetricOpportunityRadar
from engine.auto_alert_engine import AutoAlertEngine
from market.history import get_ohlcv


class TestAutoAlertEngineChainsPrewarming:
    """Pre-warming chains_map eliminates 12-thread parallel REST races on options chains."""

    def test_chains_map_prewarmed_for_core_indices(self, monkeypatch):
        mock_chain = [MagicMock(symbol="NSE:NIFTY26N0923500CE", last_price=150.0)]
        mock_get_chain = MagicMock(return_value=mock_chain)
        monkeypatch.setattr("market.options.get_options_chain", mock_get_chain)

        engine = AutoAlertEngine()
        # Mock session to active
        monkeypatch.setattr(
            "engine.auto_alert_engine.get_current_ist_session",
            lambda: {"equity_nfo": True, "commodity": False, "currency": False},
        )
        monkeypatch.setattr(engine, "_get_cycle_quotes", lambda: {})
        monkeypatch.setattr(engine, "_should_run_detector", lambda name, cadence: False)

        # Run scan
        engine.scan_equity_nfo_now()

        # Both NIFTY and BANKNIFTY should be pre-warmed
        called_symbols = [c.args[0] for c in mock_get_chain.call_args_list]
        assert "NIFTY" in called_symbols
        assert "BANKNIFTY" in called_symbols


class TestAsymmetricRadarTunings:
    """Asymmetric radar accepts quotes_map, scoped universe, and enforces Stage 0 RAM pre-filter."""

    def test_asymmetric_radar_uses_passed_quotes_map(self, monkeypatch):
        radar = AsymmetricOpportunityRadar()
        mock_quote = MagicMock(last_price=2500.0, ltp=2500.0, volume=1000000, change_pct=1.5)
        quotes_map = {"NSE:RELIANCE": mock_quote, "RELIANCE": mock_quote}

        mock_get_quote = MagicMock(
            side_effect=RuntimeError("Must not call get_quote when quotes_map is passed")
        )
        monkeypatch.setattr("market.quotes.get_quote", mock_get_quote)

        # Should execute using passed quotes_map without batch-fetching RELIANCE from get_quote
        res = radar.scan_asymmetric_opportunities(
            quotes_map=quotes_map,
            universe=["RELIANCE"],
            top_n=2,
        )
        assert isinstance(res, list)
        for c in mock_get_quote.call_args_list:
            arg = c.args[0]
            if isinstance(arg, list):
                assert "RELIANCE" not in arg and "NSE:RELIANCE" not in arg
            else:
                assert arg not in ("RELIANCE", "NSE:RELIANCE")

    def test_asymmetric_radar_stage_0_prefilter_drops_zero_ltp(self, monkeypatch):
        radar = AsymmetricOpportunityRadar()
        # Zero LTP quote
        mock_zero = MagicMock(last_price=0.0, ltp=0.0, volume=0)
        quotes_map = {"NSE:DEADSTOCK": mock_zero}

        mock_get_ohlcv = MagicMock(side_effect=RuntimeError("Must not fetch OHLCV for dead stock"))
        monkeypatch.setattr("market.history.get_ohlcv", mock_get_ohlcv)

        res = radar.scan_asymmetric_opportunities(
            quotes_map=quotes_map,
            universe=["DEADSTOCK"],
            top_n=2,
        )
        assert res == []
        mock_get_ohlcv.assert_not_called()

    def test_asymmetric_radar_sla_timeout_and_non_blocking_shutdown(self, monkeypatch):
        radar = AsymmetricOpportunityRadar()
        mock_quote = MagicMock(last_price=100.0, ltp=100.0, volume=50000)
        quotes_map = {"NSE:SLOW": mock_quote}

        def _slow_ohlcv(*args, **kwargs):
            time.sleep(0.3)
            return pd.DataFrame()

        monkeypatch.setattr("market.history.get_ohlcv", _slow_ohlcv)

        t0 = time.time()
        res = radar.scan_asymmetric_opportunities(
            quotes_map=quotes_map,
            universe=["SLOW"],
            top_n=2,
        )
        elapsed = time.time() - t0
        # Must finish gracefully without blocking
        assert elapsed < 5.0
        assert isinstance(res, list)


class TestMarketMatrixIntradayResolution:
    """get_ohlcv returns synthesized bars from MarketMatrix in RAM without broker /history REST calls."""

    def test_get_ohlcv_resolves_from_market_matrix(self, monkeypatch):
        df_synthesized = pd.DataFrame(
            [
                {"open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0, "volume": 5000},
                {"open": 104.0, "high": 106.0, "low": 103.0, "close": 105.5, "volume": 6000},
                {"open": 105.5, "high": 107.0, "low": 105.0, "close": 106.0, "volume": 7000},
            ],
            index=pd.date_range("2026-11-04 09:15:00", periods=3, freq="5min"),
        )

        mock_mm = MagicMock()
        mock_mm.get_candles_df.return_value = df_synthesized
        monkeypatch.setattr("engine.market_matrix.get_market_matrix", lambda: mock_mm)

        # Mock broker to verify it is NOT called
        mock_broker = MagicMock()
        mock_broker.get_historical_data.side_effect = RuntimeError(
            "Broker REST /history must not be called"
        )
        monkeypatch.setattr("brokers.session.get_data_broker", lambda: mock_broker)

        # Query 5m intraday bars for 1 day
        res = get_ohlcv("SBIN", exchange="NSE", interval="5m", days=1)
        assert not res.empty
        assert len(res) == 3
        assert list(res.columns) == ["open", "high", "low", "close", "volume"]
        mock_broker.get_historical_data.assert_not_called()
