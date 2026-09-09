"""
Tests for options and futures derivative quote streaming in market/quotes.py.
"""

from unittest.mock import MagicMock, patch

from market.quotes import (
    _OPTION_PATTERN,
    _FUT_PATTERN,
    normalize_instrument,
    get_quote,
)


def test_option_pattern_matching():
    # Weekly NIFTY format
    m1 = _OPTION_PATTERN.match("NIFTY2691124500CE")
    assert m1 is not None
    assert m1.group(1) == "NIFTY"
    assert m1.group(2) == "24500"
    assert m1.group(3) == "CE"

    # Monthly / standard strike format
    m2 = _OPTION_PATTERN.match("BANKNIFTY51000PE")
    assert m2 is not None
    assert m2.group(1) == "BANKNIFTY"
    assert m2.group(2) == "51000"
    assert m2.group(3) == "PE"

    # With exchange prefix
    m3 = _OPTION_PATTERN.match("NFO:RELIANCE3000CE")
    assert m3 is not None
    assert m3.group(1) == "RELIANCE"
    assert m3.group(2) == "3000"
    assert m3.group(3) == "CE"


def test_futures_pattern_matching():
    m1 = _FUT_PATTERN.match("RELIANCE26SEPFUT")
    assert m1 is not None
    assert m1.group(1) == "RELIANCE"

    m2 = _FUT_PATTERN.match("NFO:NIFTY26OCTFUT")
    assert m2 is not None
    assert m2.group(1) == "NIFTY"


def test_normalize_instrument_derivatives():
    assert normalize_instrument("NIFTY2691124500CE") == "NFO:NIFTY2691124500CE"
    assert normalize_instrument("RELIANCE26SEPFUT") == "NFO:RELIANCE26SEPFUT"
    assert normalize_instrument("TCS") == "NSE:TCS"
    assert normalize_instrument("MCX:GOLD") == "MCX:GOLD"


def test_options_quotes_resolution():
    from market.quotes import clear_quote_cache

    clear_quote_cache()

    mock_contract = MagicMock()
    mock_contract.last_price = 165.50
    mock_contract.pchange = 13.75
    mock_contract.volume = 54000
    mock_contract.oi = 120000
    mock_contract.strike = 99500.0
    mock_contract.option_type = "CE"

    snapshot_return = ([mock_contract], 24500.0, ["2026-09-11"], {"provider": "nse_scraper"})

    with patch("market.options.get_options_snapshot", return_value=snapshot_return):
        quotes = get_quote(["NFO:NIFTY99500CE"])
        assert "NFO:NIFTY99500CE" in quotes
        q = quotes["NFO:NIFTY99500CE"]
        assert q.last_price == 165.50
        assert q.change_pct == 13.75
        assert q.volume == 54000


def test_futures_quotes_resolution():
    from market.quotes import clear_quote_cache
    from brokers.base import Quote

    clear_quote_cache()

    mock_spot_quote = Quote(
        symbol="NSE:TESTSTOCK",
        last_price=3000.0,
        change=15.0,
        change_pct=0.5,
        open=2990.0,
        high=3010.0,
        low=2985.0,
        close=2985.0,
        volume=1000000,
    )

    mock_broker = MagicMock()
    mock_broker.get_quote.return_value = {"NSE:TESTSTOCK": mock_spot_quote}

    with (
        patch("market.quotes.get_data_broker", return_value=mock_broker),
        patch("market.quotes.get_data_broker_key", return_value="fyers"),
    ):
        quotes = get_quote(["NFO:TESTSTOCK26SEPFUT"])
        assert "NFO:TESTSTOCK26SEPFUT" in quotes
        fut = quotes["NFO:TESTSTOCK26SEPFUT"]
        # Fair value with cost of carry is >= spot
        assert fut.last_price >= 3000.0
        assert fut.change_pct == 0.5
