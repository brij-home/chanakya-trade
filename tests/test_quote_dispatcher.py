"""
tests/test_quote_dispatcher.py
──────────────────────────────
Tests for QuoteDispatcher serialized batching and coalescing.
"""

from unittest.mock import MagicMock, patch
import pytest

from market.quote_dispatcher import QuoteDispatcher
from market.fyers_rate_gate import FyersCallCategory


def test_quote_dispatcher_batch_chunking_and_aliases():
    dispatcher = QuoteDispatcher(chunk_size=50)

    # Generate 120 synthetic symbols with duplicates
    symbols = [f"NSE:STOCK_{i}" for i in range(120)]
    symbols.extend(["NSE:STOCK_0", "NSE:STOCK_1"])  # Duplicates

    captured_chunks = []

    def mock_get_quote(chunk):
        captured_chunks.append(chunk)
        return {s: MagicMock(last_price=100.0) for s in chunk}

    with patch("market.quotes.get_quote", side_effect=mock_get_quote):
        res = dispatcher.fetch_quotes_batch(symbols, category=FyersCallCategory.SCANNER_QUOTE)

        # 120 unique symbols with chunk size 50 should produce exactly 3 chunks: 50, 50, 20
        assert len(captured_chunks) == 3
        assert len(captured_chunks[0]) == 50
        assert len(captured_chunks[1]) == 50
        assert len(captured_chunks[2]) == 20

        # Verify short symbol aliases were created
        assert "NSE:STOCK_0" in res
        assert "STOCK_0" in res
        assert res["STOCK_0"] == res["NSE:STOCK_0"]
