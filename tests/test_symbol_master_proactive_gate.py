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
    load_master,
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


def test_options_grid_pre_subscription_filter():
    """Verify generated options grid only contains listed contracts present in NSE_FO / BSE_FO."""
    grid = get_active_index_options_grid(num_strikes_per_side=4)
    assert len(grid) > 0

    # Ensure no phantom FINNIFTY strikes with 50-step increments on monthly contracts
    for sym in grid:
        if "FINNIFTY" in sym and "NOV" in sym:
            # Contract must be listed in official master
            info = get_symbol_info(sym)
            assert info is not None, f"Phantom unlisted option in grid: {sym}"

    # Verify every single returned contract exists in the master
    fo_nse = load_master("NSE_FO", offline_fallback=True)
    for sym in grid:
        if sym.startswith("NSE:"):
            assert sym in fo_nse, f"Symbol {sym} is not in NSE_FO exchange master"


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
