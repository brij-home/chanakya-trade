"""
tests/test_symbol_facade.py
───────────────────────────
Institutional test suite for SymbolMasterFacade (SSOT) and Broker Protocol Parity.
"""

from market.symbol_facade import get_symbol_facade


def test_symbol_facade_canonicalization():
    facade = get_symbol_facade()

    # Exchange prefixes and suffixes
    assert facade.to_canonical("NSE:RELIANCE-EQ") == "RELIANCE"
    assert facade.to_canonical("BSE:SBIN") == "SBIN"
    assert facade.to_canonical("TCS.NS") == "TCS"
    assert facade.to_canonical("INFY.BO") == "INFY"

    # Corporate Restructuring & Demerger Aliases
    assert facade.to_canonical("TATAMOTORS") == "TMPV"
    assert facade.to_canonical("ZOMATO") == "ETERNAL"
    assert facade.to_canonical("CENTURYTEX") == "ABREL"
    assert facade.to_canonical("REC") == "RECLTD"

    # Benchmark Indices canonicalization
    assert facade.to_canonical("NSE:NIFTY50-INDEX") == "NIFTY"
    assert facade.to_canonical("NIFTY 50") == "NIFTY"
    assert facade.to_canonical("BANKNIFTY") == "BANKNIFTY"
    assert facade.to_canonical("NIFTY BANK") == "BANKNIFTY"
    assert facade.to_canonical("BSE SENSEX") == "SENSEX"
    assert facade.to_canonical("INDIA VIX") == "INDIAVIX"


def test_symbol_facade_fyers_protocol():
    facade = get_symbol_facade()

    # Index formats
    assert facade.to_fyers("NIFTY") == "NSE:NIFTY50-INDEX"
    assert facade.to_fyers("NIFTY 50") == "NSE:NIFTY50-INDEX"
    assert facade.to_fyers("BANKNIFTY") == "NSE:NIFTYBANK-INDEX"
    assert facade.to_fyers("SENSEX") == "BSE:SENSEX-INDEX"
    assert facade.to_fyers("INDIAVIX") == "NSE:INDIAVIX-INDEX"

    # Equities
    assert facade.to_fyers("RELIANCE") == "NSE:RELIANCE-EQ"
    assert facade.to_fyers("SBIN") == "NSE:SBIN-EQ"

    # Commodities
    assert facade.to_fyers("CRUDEOIL") == "MCX:CRUDEOIL"
    assert facade.to_fyers("GOLD") == "MCX:GOLD"


def test_symbol_facade_flattrade_protocol():
    facade = get_symbol_facade()

    # Static official index token mapping
    nifty = facade.to_flattrade("NIFTY")
    assert nifty["exch"] == "NSE"
    assert nifty["token"] == "26000"
    assert nifty["tsym"] == "Nifty 50"

    banknifty = facade.to_flattrade("BANKNIFTY")
    assert banknifty["exch"] == "NSE"
    assert banknifty["token"] == "26009"
    assert banknifty["tsym"] == "Nifty Bank"

    sensex = facade.to_flattrade("SENSEX")
    assert sensex["exch"] == "BSE"
    assert sensex["token"] == "1"
    assert sensex["tsym"] == "SENSEX"

    bankex = facade.to_flattrade("BANKEX")
    assert bankex["exch"] == "BSE"
    assert bankex["token"] == "12"
    assert bankex["tsym"] == "BANKEX"

    vix = facade.to_flattrade("INDIAVIX")
    assert vix["exch"] == "NSE"
    assert vix["token"] == "26017"
    assert vix["tsym"] == "INDIAVIX"


def test_symbol_facade_fno_universes():
    facade = get_symbol_facade()

    all_fno = facade.get_fno_universe("ALL")
    index_fno = facade.get_fno_universe("INDEX")
    eq_fno = facade.get_fno_universe("EQUITY")

    assert len(index_fno) == 7
    assert "NIFTY" in index_fno
    assert "BANKNIFTY" in index_fno
    assert "SENSEX" in index_fno

    assert len(eq_fno) == 217
    assert "RELIANCE" in eq_fno
    assert "SBIN" in eq_fno
    assert "TRENT" in eq_fno

    assert len(all_fno) == 224

    assert facade.is_fno("RELIANCE") is True
    assert facade.is_fno("NIFTY") is True
    assert facade.is_fno("NOT_A_REAL_SYMBOL_999") is False

    # Lot sizes
    assert facade.get_lot_size("NIFTY") == 65
    assert facade.get_lot_size("BANKNIFTY") == 30
    assert facade.get_lot_size("SENSEX") == 20
    assert facade.get_lot_size("RELIANCE") == 500
    assert facade.get_lot_size("SBIN") == 750
