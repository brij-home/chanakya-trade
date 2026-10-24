"""
tests/test_nse_bse_universe_standardization.py
──────────────────────────────────────────────
Validates:
1. Canonical corporate action and alias resolution (ZOMATO -> ETERNAL, TATAMOTORS -> TMPV, etc.).
2. Fyers broker format conversion with corporate alias mapping and BE series routing (HFCL -> NSE:HFCL-BE).
3. Centralized F&O lot size resolution and derivative eligibility for modern and aliased tickers.
4. Completeness of NSE all equity universe against Nifty 500, Total Market 750, and BSE 500 benchmarks.
5. yfinance ticker resolution for corporate aliases and special tickers.
"""

import json
from pathlib import Path

from market.instruments import (
    resolve_corporate_alias,
    get_fno_lot_size,
    is_derivative_eligible,
)
from brokers.fyers import _to_fyers_symbol
from market.websocket import _to_ws_symbol
from market.yfinance_provider import _to_yf_symbol


def test_corporate_alias_resolution():
    """Verify all major corporate actions and demergers map to active canonical tickers."""
    assert resolve_corporate_alias("ZOMATO") == "ETERNAL"
    assert resolve_corporate_alias("TATAMOTORS") == "TMPV"
    assert resolve_corporate_alias("CENTURYTEX") == "ABREL"
    assert resolve_corporate_alias("UNOINDA") == "UNOMINDA"
    assert resolve_corporate_alias("REC") == "RECLTD"
    assert resolve_corporate_alias("CEINFO") == "MAPMYINDIA"
    assert resolve_corporate_alias("ASTRA") == "ASTRAMICRO"
    assert resolve_corporate_alias("SWANENERGY") == "SWANCORP"
    assert resolve_corporate_alias("HITACHI") == "POWERINDIA"
    assert resolve_corporate_alias("KALPATPOWR") == "KPIL"
    assert resolve_corporate_alias("JUPITERWAG") == "JWL"
    assert resolve_corporate_alias("L&TFH") == "LTF"
    assert resolve_corporate_alias("IBULHSGFIN") == "SAMMAANCAP"
    assert resolve_corporate_alias("MOTHERSUMI") == "MOTHERSON"
    assert resolve_corporate_alias("IDFC") == "IDFCFIRSTB"
    assert resolve_corporate_alias("HDFC") == "HDFCBANK"
    assert resolve_corporate_alias("ADANITRANS") == "ADANIENSOL"
    assert resolve_corporate_alias("MCDOWELL-N") == "UNITDSPR"
    assert resolve_corporate_alias("L&T") == "LT"
    assert resolve_corporate_alias("NAMINDIA") == "NAM-INDIA"
    assert resolve_corporate_alias("BAJAJAUTO") == "BAJAJ-AUTO"
    assert resolve_corporate_alias("TATASTEELBSL") == "TATASTEEL"
    assert resolve_corporate_alias("NSLNISP") == "NMDCSTEEL"


def test_fyers_symbol_conversion_with_aliases_and_series():
    """Verify Fyers symbol conversion resolves aliases and Trade-for-Trade (BE) series."""
    # Aliased equities resolve to current active ticker
    assert _to_fyers_symbol("ZOMATO") == "NSE:ETERNAL-EQ"
    assert _to_fyers_symbol("TATAMOTORS") == "NSE:TMPV-EQ"
    assert _to_fyers_symbol("CENTURYTEX") == "NSE:ABREL-EQ"
    assert _to_fyers_symbol("UNOINDA") == "NSE:UNOMINDA-EQ"
    assert _to_fyers_symbol("REC") == "NSE:RECLTD-EQ"

    # BE Series stocks route to -BE
    assert _to_fyers_symbol("HFCL") == "NSE:HFCL-BE"
    assert _to_fyers_symbol("MTARTECH") == "NSE:MTARTECH-BE"
    assert _to_fyers_symbol("STLTECH") == "NSE:STLTECH-BE"
    assert _to_fyers_symbol("DIACABS") == "NSE:DIACABS-BE"
    assert _to_fyers_symbol("INDIAGLYCO") == "NSE:INDIAGLYCO-BE"
    assert _to_fyers_symbol("LOTUSDEV") == "NSE:LOTUSDEV-BE"

    # Regular EQ stocks route to -EQ
    assert _to_fyers_symbol("RELIANCE") == "NSE:RELIANCE-EQ"
    assert _to_fyers_symbol("TCS") == "NSE:TCS-EQ"
    assert _to_fyers_symbol("INFY") == "NSE:INFY-EQ"

    # BSE Benchmarks route to BSE:
    assert _to_fyers_symbol("SENSEX") == "BSE:SENSEX-INDEX"
    assert _to_fyers_symbol("BSE:SENSEX") == "BSE:SENSEX-INDEX"
    assert _to_fyers_symbol("BANKEX") == "BSE:BANKEX-INDEX"


def test_websocket_symbol_resolution():
    """Verify websocket symbol generator inherits corporate aliases and BE series."""
    assert _to_ws_symbol("ZOMATO") == "NSE:ETERNAL-EQ"
    assert _to_ws_symbol("TATAMOTORS") == "NSE:TMPV-EQ"
    assert _to_ws_symbol("HFCL") == "NSE:HFCL-BE"
    assert _to_ws_symbol("MTARTECH") == "NSE:MTARTECH-BE"


def test_fno_lot_size_and_derivative_eligibility():
    """Verify lot sizes and derivative eligibility work for both modern and legacy tickers."""
    # Zomato / Eternal
    assert is_derivative_eligible("ZOMATO") is True
    assert is_derivative_eligible("ETERNAL") is True
    assert get_fno_lot_size("ZOMATO") == 2425
    assert get_fno_lot_size("ETERNAL") == 2425

    # Tata Motors / TMPV
    assert is_derivative_eligible("TATAMOTORS") is True
    assert is_derivative_eligible("TMPV") is True
    assert get_fno_lot_size("TATAMOTORS") == 1600
    assert get_fno_lot_size("TMPV") == 1600

    # Uno Minda
    assert is_derivative_eligible("UNOINDA") is True
    assert is_derivative_eligible("UNOMINDA") is True
    assert get_fno_lot_size("UNOINDA") == 550
    assert get_fno_lot_size("UNOMINDA") == 550

    # REC Ltd
    assert is_derivative_eligible("REC") is True
    assert is_derivative_eligible("RECLTD") is True
    assert get_fno_lot_size("REC") == 1575
    assert get_fno_lot_size("RECLTD") == 1575

    # Century Textiles / ABREL
    assert is_derivative_eligible("CENTURYTEX") is True
    assert is_derivative_eligible("ABREL") is True
    assert get_fno_lot_size("CENTURYTEX") == 450
    assert get_fno_lot_size("ABREL") == 450

    # Non-derivative cash stock
    assert is_derivative_eligible("NONEXISTENT_STK") is False
    assert get_fno_lot_size("NONEXISTENT_STK") == 1


def test_nse_universe_benchmark_coverage():
    """Verify that nse_all_eq.json provides 100% constituent coverage for Nifty 500, Total Market 750, and BSE 500."""
    data_dir = Path("data/universes")
    nse_all = set(
        x["symbol"].strip().upper()
        for x in json.loads((data_dir / "nse_all_eq.json").read_text(encoding="utf-8"))
    )

    # Nifty 500
    nifty500 = set(
        x["symbol"].strip().upper()
        for x in json.loads((data_dir / "nifty500.json").read_text(encoding="utf-8"))
    )
    assert nifty500.issubset(nse_all), f"Missing from nse_all_eq: {nifty500 - nse_all}"

    # Nifty Total Market 750
    total_mkt = set(
        x["symbol"].strip().upper()
        for x in json.loads((data_dir / "nifty_total_market.json").read_text(encoding="utf-8"))
    )
    assert total_mkt.issubset(nse_all), f"Missing from nse_all_eq: {total_mkt - nse_all}"

    # S&P BSE 500
    bse500 = set(
        x["symbol"].strip().upper()
        for x in json.loads((data_dir / "bse500.json").read_text(encoding="utf-8"))
    )
    assert bse500.issubset(nse_all), f"Missing from nse_all_eq: {bse500 - nse_all}"


def test_yfinance_corporate_alias_mapping():
    """Verify yfinance provider resolves corporate aliases and ticker differences."""
    assert _to_yf_symbol("COCHINSHIP") == "COCHINSHIPYARD.NS"
    assert _to_yf_symbol("ZOMATO") == "ETERNAL.NS"
    assert _to_yf_symbol("TATAMOTORS") == "TMPV.NS"
    assert _to_yf_symbol("CENTURYTEX") == "ABREL.NS"
    assert _to_yf_symbol("UNOINDA") == "UNOMINDA.NS"
    assert _to_yf_symbol("REC") == "RECLTD.NS"
    assert _to_yf_symbol("L&TFH") == "LTF.NS"
    assert _to_yf_symbol("IBULHSGFIN") == "SAMMAANCAP.NS"


def test_core_base_symbols_preseeding():
    """Verify CORE_BASE_SYMBOLS has Total Market 750 pre-seeded with alias and series resolution."""
    from market.ws_subscription_manager import CORE_BASE_SYMBOLS

    # Over 780 core symbols pre-seeded
    assert len(CORE_BASE_SYMBOLS) >= 780
    assert "NSE:TMPV-EQ" in CORE_BASE_SYMBOLS
    assert "NSE:ETERNAL-EQ" in CORE_BASE_SYMBOLS
    assert "NSE:ABREL-EQ" in CORE_BASE_SYMBOLS
    # BE Series stocks correctly pre-seeded with -BE
    assert "NSE:HFCL-BE" in CORE_BASE_SYMBOLS
    assert "NSE:MTARTECH-BE" in CORE_BASE_SYMBOLS
    assert "NSE:STLTECH-BE" in CORE_BASE_SYMBOLS


def test_ws_quotes_serves_dual_listed_bse_and_aliases(monkeypatch):
    """Verify _ws_quotes serves dual-listed BSE equity and aliased symbols via live NSE tick."""
    from market.quotes import _ws_quotes
    from market.websocket import ws_manager

    class DummyTick:
        def __init__(self, symbol, ltp):
            self.symbol = symbol
            self.ltp = ltp
            self.open = ltp
            self.high = ltp + 1
            self.low = ltp - 1
            self.close = ltp
            self.volume = 100000
            self.bid = ltp - 0.05
            self.ask = ltp + 0.05
            self.change = 1.0
            self.change_pct = 0.5
            self.atp = ltp
            self.timestamp = 1729780000

    def mock_get_tick(sym):
        if sym == "NSE:RELIANCE-EQ":
            return DummyTick("NSE:RELIANCE-EQ", 2950.0)
        if sym == "NSE:ETERNAL-EQ":
            return DummyTick("NSE:ETERNAL-EQ", 280.0)
        if sym == "NSE:HFCL-BE":
            return DummyTick("NSE:HFCL-BE", 125.50)
        return None

    monkeypatch.setattr("market.quotes.get_data_broker_key", lambda: "fyers")
    monkeypatch.setattr(ws_manager, "_connected", True)
    monkeypatch.setattr(ws_manager, "get_tick", mock_get_tick)

    # 1. Dual-listed BSE:RELIANCE gets live quote from NSE:RELIANCE-EQ
    res = _ws_quotes(["BSE:RELIANCE"], correlation_id="test-cid")
    assert "BSE:RELIANCE" in res
    assert res["BSE:RELIANCE"].last_price == 2950.0
    assert res["BSE:RELIANCE"].provider == "fyers"

    # 2. Aliased ZOMATO gets live quote from NSE:ETERNAL-EQ
    res_alias = _ws_quotes(["NSE:ZOMATO-EQ"], correlation_id="test-cid")
    assert "NSE:ZOMATO-EQ" in res_alias
    assert res_alias["NSE:ZOMATO-EQ"].last_price == 280.0

    # 3. Surveillance series BE stock queried as -EQ resolves live -BE tick
    res_be = _ws_quotes(["NSE:HFCL-EQ"], correlation_id="test-cid")
    assert "NSE:HFCL-EQ" in res_be
    assert res_be["NSE:HFCL-EQ"].last_price == 125.50
