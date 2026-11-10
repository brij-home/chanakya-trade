"""
Unit tests for multi-broker failover across historical OHLCV data (market/history.py)
and options chain discovery (market/options.py).
Ensures Fyers is primary, Flattrade/secondary brokers are backup, and yfinance/scrapers
are strictly last-resort.
"""

from unittest.mock import MagicMock, patch
import pandas as pd

from brokers.base import OptionsContract
from market.history import get_ohlcv
from market.options import get_options_chain


def test_secondary_broker_history_failover_when_primary_fails():
    """Verify that when primary broker get_historical_data fails, secondary broker is queried before yfinance."""
    mock_primary = MagicMock()
    mock_primary._is_mock = False
    mock_primary.get_historical_data.side_effect = RuntimeError("Fyers rate limit HTTP 429")

    mock_secondary = MagicMock()
    mock_secondary._is_mock = False
    mock_candles = [
        {
            "date": "2026-11-09 09:15:00",
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 101.0,
            "volume": 5000,
        },
        {
            "date": "2026-11-09 09:20:00",
            "open": 101.0,
            "high": 103.0,
            "low": 100.5,
            "close": 102.5,
            "volume": 6000,
        },
    ]
    mock_secondary.get_historical_data.return_value = mock_candles

    all_brokers = {
        "fyers": mock_primary,
        "flattrade": mock_secondary,
    }

    with patch(
        "engine.historical_warehouse.historical_warehouse.load_bars", return_value=pd.DataFrame()
    ):
        with patch("brokers.session.get_data_broker_key", return_value="fyers"):
            with patch("brokers.session.get_data_broker", return_value=mock_primary):
                with patch("brokers.session.get_all_brokers", return_value=all_brokers):
                    with patch("market.history._yfinance_fallback") as mock_yf:
                        df = get_ohlcv(
                            "FAILOVER_TEST_SYM", exchange="NSE", interval="5minute", days=1
                        )

                        assert not df.empty, "DataFrame should be populated from secondary broker"
                        assert len(df) == 2
                        assert df.attrs.get("provenance", {}).get("provider") == "flattrade"
                        mock_primary.get_historical_data.assert_called_once()
                        mock_secondary.get_historical_data.assert_called_once()
                        mock_yf.assert_not_called()


def test_primary_broker_history_success_does_not_call_secondary():
    """Verify that when primary broker succeeds for OHLCV, secondary broker is never queried."""
    mock_primary = MagicMock()
    mock_primary._is_mock = False
    mock_candles = [
        {
            "date": "2026-11-09 09:15:00",
            "open": 200.0,
            "high": 205.0,
            "low": 199.0,
            "close": 204.0,
            "volume": 12000,
        },
    ]
    mock_primary.get_historical_data.return_value = mock_candles

    mock_secondary = MagicMock()
    mock_secondary._is_mock = False

    all_brokers = {
        "fyers": mock_primary,
        "flattrade": mock_secondary,
    }

    with patch(
        "engine.historical_warehouse.historical_warehouse.load_bars", return_value=pd.DataFrame()
    ):
        with patch("brokers.session.get_data_broker_key", return_value="fyers"):
            with patch("brokers.session.get_data_broker", return_value=mock_primary):
                with patch("brokers.session.get_all_brokers", return_value=all_brokers):
                    df = get_ohlcv("UNKNOWN_PRI_SYM", exchange="NSE", interval="5minute", days=1)

                    assert not df.empty
                    assert df.attrs.get("provenance", {}).get("provider") == "fyers"
                    mock_primary.get_historical_data.assert_called_once()
                    mock_secondary.get_historical_data.assert_not_called()


def test_secondary_broker_options_failover_when_primary_fails():
    """Verify that when primary broker options chain fails, secondary broker options chain is used before web scraper."""
    mock_primary = MagicMock()
    mock_primary._is_mock = False
    mock_primary.get_options_chain.side_effect = RuntimeError("Fyers options timeout")

    mock_secondary = MagicMock()
    mock_secondary._is_mock = False
    contract = OptionsContract(
        symbol="NIFTY26NOV24500CE",
        underlying="NIFTY",
        expiry="2026-11-26",
        strike=24500.0,
        option_type="CE",
        last_price=150.0,
        oi=50000,
        oi_change=1200,
        volume=25000,
    )
    mock_secondary.get_options_chain.return_value = [contract]

    all_brokers = {
        "fyers": mock_primary,
        "flattrade": mock_secondary,
    }

    with patch("market.options.get_data_broker", return_value=mock_primary):
        with patch("brokers.session.get_data_broker_key", return_value="fyers"):
            with patch("brokers.session.get_all_brokers", return_value=all_brokers):
                with patch("market.options.nse_get_options_chain") as mock_scraper:
                    chain = get_options_chain("NIFTY", expiry="2026-11-26")

                    assert len(chain) == 1
                    assert chain[0].strike == 24500.0
                    mock_primary.get_options_chain.assert_called_once()
                    mock_secondary.get_options_chain.assert_called_once()
                    mock_scraper.assert_not_called()
