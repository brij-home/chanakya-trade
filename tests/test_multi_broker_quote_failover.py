"""
Unit tests for multi-broker REST quote failover in market/quotes.py.
Ensures continuous market data feed during single-broker outages.
"""

from unittest.mock import MagicMock, patch

from market.quotes import get_quote, Quote


def test_secondary_broker_failover_when_primary_fails():
    """Verify that when the primary broker fails, secondary broker is queried and quotes are returned."""
    mock_primary_broker = MagicMock()
    mock_primary_broker.get_quote.side_effect = RuntimeError(
        "Primary broker network timeout (HTTP 504)"
    )

    mock_secondary_broker = MagicMock()
    mock_sec_quote = Quote(
        symbol="NSE:NIFTY50-INDEX",
        last_price=24850.50,
        open=24800.0,
        high=24900.0,
        low=24780.0,
        close=24820.0,
        volume=1500000,
        change=30.5,
        change_pct=0.12,
        bid=24850.0,
        ask=24851.0,
    )
    mock_secondary_broker.get_quote.return_value = {"NSE:NIFTY50-INDEX": mock_sec_quote}

    all_brokers = {
        "fyers": mock_primary_broker,
        "shoonya": mock_secondary_broker,
    }

    with patch("market.quotes.get_data_broker_key", return_value="fyers"):
        with patch("market.quotes.get_data_broker", return_value=mock_primary_broker):
            with patch("brokers.session.get_all_brokers", return_value=all_brokers):
                res = get_quote(
                    ["NSE:NIFTY50-INDEX"], bypass_cache=True, priority="NORMAL", ws_only=False
                )

                assert "NSE:NIFTY50-INDEX" in res, "Quote should be resolved via secondary broker"
                quote = res["NSE:NIFTY50-INDEX"]
                assert quote.last_price == 24850.50
                assert quote.provider == "shoonya"
                assert quote.source == "REST"
                mock_secondary_broker.get_quote.assert_called_once()


def test_primary_broker_success_does_not_call_secondary():
    """Verify that when primary broker succeeds, secondary broker is never invoked."""
    mock_primary_broker = MagicMock()
    mock_pri_quote = Quote(
        symbol="BSE:SENSEX-INDEX",
        last_price=74200.0,
        open=74000.0,
        high=74300.0,
        low=73900.0,
        close=74100.0,
        volume=800000,
        change=100.0,
        change_pct=0.14,
        bid=74199.0,
        ask=74201.0,
    )
    mock_primary_broker.get_quote.return_value = {"BSE:SENSEX-INDEX": mock_pri_quote}

    mock_secondary_broker = MagicMock()
    all_brokers = {
        "fyers": mock_primary_broker,
        "angelone": mock_secondary_broker,
    }

    with patch("market.quotes.get_data_broker_key", return_value="fyers"):
        with patch("market.quotes.get_data_broker", return_value=mock_primary_broker):
            with patch("brokers.session.get_all_brokers", return_value=all_brokers):
                res = get_quote(
                    ["BSE:SENSEX-INDEX"], bypass_cache=True, priority="NORMAL", ws_only=False
                )

                assert "BSE:SENSEX-INDEX" in res
                assert res["BSE:SENSEX-INDEX"].provider == "fyers"
                mock_secondary_broker.get_quote.assert_not_called()
