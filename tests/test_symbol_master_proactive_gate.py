"""
tests/test_symbol_master_proactive_gate.py
──────────────────────────────────────────
Validates the proactive first-hand symbol master gate:
1. Dynamic series resolution against official exchange masters (EQ vs BE).
2. Broker-specific ticker resolution (LTIM -> LTM on Fyers).
3. Pre-subscription filtering of index options grid against listed contracts in NSE_FO/BSE_FO.
4. Pre-dispatch WebSocket invalid symbol rejection before wire transmission.
"""

from unittest.mock import MagicMock
from market.symbol_master import (
    resolve_fyers_equity_symbol,
    get_symbol_info,
)
from market.ws_subscription_manager import get_active_index_options_grid
from market.websocket import WebSocketManager


def test_resolve_fyers_equity_symbol_dynamic_series():
    """Verify surveillance series resolution reflects actual exchange master state."""
    # Graduated from BE surveillance back to rolling settlement
    assert resolve_fyers_equity_symbol("INDIAGLYCO") == "NSE:INDIAGLYCO-EQ"
    assert resolve_fyers_equity_symbol("MTARTECH") == "NSE:MTARTECH-EQ"

    # Active Trade-for-Trade (BE) surveillance stock
    assert resolve_fyers_equity_symbol("RAMASTEEL") == "NSE:RAMASTEEL-BE"

    # Standard equity
    assert resolve_fyers_equity_symbol("RELIANCE") == "NSE:RELIANCE-EQ"
    assert resolve_fyers_equity_symbol("TCS") == "NSE:TCS-EQ"


def test_resolve_fyers_equity_symbol_broker_ticker_mapping():
    """Verify Fyers-specific broker ticker mapping for LTI Mindtree."""
    assert resolve_fyers_equity_symbol("LTIM") == "NSE:LTM-EQ"
    assert resolve_fyers_equity_symbol("NSE:LTIM-EQ") == "NSE:LTM-EQ"
    assert resolve_fyers_equity_symbol("LTI") == "NSE:LTM-EQ"


def test_options_grid_holds_without_fresh_underlying_quotes(monkeypatch):
    """A missing live quote must hold subscription planning before master work."""
    from unittest.mock import Mock

    monkeypatch.setattr("market.quotes.get_quote", lambda *args, **kwargs: {})
    master_loader = Mock(side_effect=AssertionError("master must not be read without a live quote"))
    monkeypatch.setattr("market.symbol_master.load_master", master_loader)
    grid = get_active_index_options_grid(num_strikes_per_side=4)
    assert grid == []
    master_loader.assert_not_called()


def test_websocket_proactively_drops_unlisted_symbols_before_dispatch():
    """Verify WebSocket client drops unlisted symbols before sending to FyersDataSocket."""
    client = WebSocketManager()
    client._connected = True
    mock_ws = MagicMock()
    client._ws = mock_ws

    # Attempt to subscribe to phantom unlisted contracts
    phantom_symbols = [
        "NSE:COMPLETELY_INVALID_TICKER_12345-EQ",
        "NSE:FINNIFTY99NOV99999CE",
    ]
    client.subscribe(phantom_symbols)

    # Must NOT have dispatched phantom symbols to the underlying broker socket
    mock_ws.subscribe.assert_not_called()
    assert len(client._subscribed) == 0

    # Real symbol must be allowed through
    client.subscribe(["NSE:RELIANCE-EQ"])
    mock_ws.subscribe.assert_called_once_with(["NSE:RELIANCE-EQ"])
    assert "NSE:RELIANCE-EQ" in client._subscribed


def test_resolve_fyers_equity_symbol_icicipruli_and_special_tickers():
    """Verify ICICIPRULI resolves to ICICILIFE on Fyers, and -B series suffixes on NSE are preserved."""
    assert resolve_fyers_equity_symbol("ICICIPRULI") == "NSE:ICICILIFE-EQ"
    assert resolve_fyers_equity_symbol("NSE:ICICIPRULI-EQ") == "NSE:ICICILIFE-EQ"
    assert resolve_fyers_equity_symbol("HEG") == "NSE:HEGAM-EQ"
    assert resolve_fyers_equity_symbol("NSE:HEG-EQ") == "NSE:HEGAM-EQ"
    assert resolve_fyers_equity_symbol("KLBRENG-B") == "NSE:KLBRENG-B-EQ"
    assert resolve_fyers_equity_symbol("MCCHRLS-B") == "NSE:MCCHRLS-B-EQ"


def test_get_symbol_info_alias_fallback():
    """Verify get_symbol_info transparently resolves aliases (e.g. ICICIPRULI-EQ -> ICICILIFE)."""
    info = get_symbol_info("NSE:ICICIPRULI-EQ")
    assert info is not None
    assert info.get("exSymbol") == "ICICILIFE"
    assert info.get("symTicker") == "NSE:ICICILIFE-EQ"


def test_websocket_subscribes_icicipruli_as_canonical_fyers_symbol():
    """Verify WebSocket subscribes ICICIPRULI-EQ as canonical NSE:ICICILIFE-EQ without dropping it."""
    client = WebSocketManager()
    client._connected = True
    mock_ws = MagicMock()
    client._ws = mock_ws

    client.subscribe(["NSE:ICICIPRULI-EQ"])

    # Must have dispatched canonical Fyers symbol NSE:ICICILIFE-EQ to the broker socket
    mock_ws.subscribe.assert_called_once_with(["NSE:ICICILIFE-EQ"])
    assert "NSE:ICICILIFE-EQ" in client._subscribed
