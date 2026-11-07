"""
tests/test_symbol_master.py
────────────────────────────
Deterministic unit tests for market/symbol_master.py.
"""

import pytest

import market.symbol_master as sm


@pytest.fixture
def mock_master_data():
    return {
        "NSE:SBIN-EQ": {
            "symTicker": "NSE:SBIN-EQ",
            "exSymName": "STATE BANK OF INDIA",
            "minLotSize": 1,
            "tickSize": 0.05,
            "optType": "XX",
            "strikePrice": -1,
            "expiryDate": "",
            "fyToken": "10100000003045",
            "isin": "INE062A01020",
            "lastUpdate": "2026-10-03",
        },
        "NSE:NIFTY26NOV25000CE": {
            "symTicker": "NSE:NIFTY26NOV25000CE",
            "exSymName": "NIFTY 03 NOV 26 25000 CE",
            "minLotSize": 65,
            "tickSize": 0.05,
            "optType": "CE",
            "strikePrice": 25000,
            "expiryDate": "1793700000",
            "fyToken": "1011126102925000",
            "isin": "",
            "lastUpdate": "2026-10-30",
        },
    }


def test_search_symbols(mock_master_data, monkeypatch):
    monkeypatch.setattr(sm, "load_master", lambda master, **kwargs: mock_master_data)

    res = sm.search_symbols("SBIN", master="NSE_CM")
    assert len(res) == 1
    assert res[0]["symbol"] == "NSE:SBIN-EQ"
    assert res[0]["lot_size"] == 1
    assert res[0]["tick_size"] == 0.05

    res_opt = sm.search_symbols("NIFTY", opt_type="CE")
    assert len(res_opt) == 1
    assert res_opt[0]["symbol"] == "NSE:NIFTY26NOV25000CE"
    assert res_opt[0]["lot_size"] == 65


def test_get_symbol_info_and_validation(mock_master_data, monkeypatch):
    monkeypatch.setattr(sm, "load_master", lambda master, **kwargs: mock_master_data)

    info = sm.get_symbol_info("NSE:SBIN-EQ")
    assert info is not None
    assert info["minLotSize"] == 1

    val = sm.validate_symbol("NSE:NIFTY26NOV25000CE")
    assert val["minLotSize"] == 65
    # Broker order symbols use NFO, while the canonical FYERS row is keyed NSE.
    assert sm.get_symbol_info("NFO:NIFTY26NOV25000CE") is mock_master_data["NSE:NIFTY26NOV25000CE"]

    with pytest.raises(ValueError, match="not found in exchange master"):
        sm.validate_symbol("NSE:NONEXISTENT999")


def test_get_lot_size_and_tick_size(mock_master_data, monkeypatch):
    monkeypatch.setattr(sm, "load_master", lambda master, **kwargs: mock_master_data)

    assert sm.get_lot_size("NSE:NIFTY26NOV25000CE") == 65
    assert sm.get_lot_size("NSE:UNKNOWN", fallback=50) == 50

    assert sm.get_tick_size("NSE:SBIN-EQ") == 0.05
    assert sm.get_tick_size("NSE:UNKNOWN", fallback=0.1) == 0.1


def test_expiry_iso_conversion():
    # 1793260800 -> 2026-10-29
    iso = sm._expiry_iso("1793260800")
    assert iso.startswith("2026-10")
    assert sm._expiry_iso("") == ""
