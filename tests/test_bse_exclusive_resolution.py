"""
tests/test_bse_exclusive_resolution.py
───────────────────────────────────────
Verifies cross-exchange resolution and data retrieval for BSE-exclusive stocks
(e.g. SHREEREF), preventing false INSUFFICIENT DATA errors and misleading
zero-valued indicators.
"""

from unittest.mock import MagicMock

from web.skills import _normalize_symbol_and_exchange
from agent.multi_agent import TechnicalAnalyst


def test_normalize_symbol_and_exchange_variants():
    """Validates exchange parsing for natural formats and edge cases."""
    # Explicit BSE
    sym, exch = _normalize_symbol_and_exchange("SHREEREF", "BSE")
    assert sym == "SHREEREF"
    assert exch == "BSE"

    # Colon prefix
    sym, exch = _normalize_symbol_and_exchange("BSE:SHREEREF", "NSE")
    assert sym == "SHREEREF"
    assert exch == "BSE"

    # Garbage exchange fallback to NSE default
    sym, exch = _normalize_symbol_and_exchange("SHREEREF", "OF")
    assert sym == "SHREEREF"
    assert exch == "NSE"

    # Known universe checks
    assert _normalize_symbol_and_exchange("SENSEX")[1] == "BSE"
    assert _normalize_symbol_and_exchange("GOLD")[1] == "MCX"
    assert _normalize_symbol_and_exchange("USDINR")[1] == "CDS"


def test_technical_analyst_honesty_on_insufficient_data():
    """Ensures TechnicalAnalyst does NOT output fake 0.0 (oversold) indicators."""
    registry = MagicMock()
    empty_result = {
        "symbol": "SHREEREF",
        "exchange": "NSE",
        "timeframe": "1D (Daily)",
        "verdict": "INSUFFICIENT DATA",
        "score": 0,
        "summary": "Insufficient historical bars",
        "is_valid": False,
        "rsi": None,
        "macd": None,
    }
    registry.execute.return_value = empty_result
    analyst = TechnicalAnalyst(registry)

    report = analyst.analyze("SHREEREF", "NSE")
    assert report.verdict == "INSUFFICIENT DATA"
    text = " ".join(report.key_points).lower()
    assert "oversold" not in text
    assert "rsi" not in text
    assert "macd" not in text


def test_technical_snapshot_valid_bse_computation():
    """Ensures valid BSE data computes non-zero indicators properly."""
    registry = MagicMock()
    valid_result = {
        "symbol": "SHREEREF",
        "exchange": "BSE",
        "timeframe": "1D (Daily)",
        "verdict": "BULLISH",
        "score": 35,
        "is_valid": True,
        "rsi": 58.2,
        "macd": 4.5,
        "macd_hist": 0.7,
        "macd_detail": "Bullish momentum",
    }
    registry.execute.return_value = valid_result
    analyst = TechnicalAnalyst(registry)

    report = analyst.analyze("SHREEREF", "BSE")
    assert report.verdict == "BULLISH"
    text = " ".join(report.key_points)
    assert "58.2" in text
    assert "4.50" in text
