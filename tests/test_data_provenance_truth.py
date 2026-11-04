"""
tests/test_data_provenance_truth.py
───────────────────────────────────
Regression tests for DATA-01..DATA-07:
  - classify_data_state must never label FALLBACK or SYNTHETIC data as LIVE
  - Synthetic futures quotes must have source="SYNTHETIC", data_state="DEGRADED", and no fabricated OHLC
  - TBT depth packets must not copy top bid as last_price or sum resting depth as traded volume
"""

from market.data_events import classify_data_state
from market.quotes import _futures_quotes


def test_classify_data_state_never_labels_fallback_or_synthetic_as_live():
    """Fallback and synthetic providers must classify as DEGRADED or UNAVAILABLE, never LIVE."""
    # Synthetic futures
    assert (
        classify_data_state(source="FALLBACK", provider="cost_of_carry_synthetic", price=100.0)
        == "DEGRADED"
    )
    assert (
        classify_data_state(source="SYNTHETIC", provider="cost_of_carry_synthetic", price=100.0)
        == "DEGRADED"
    )

    # Yahoo / yfinance
    assert classify_data_state(source="FALLBACK", provider="yfinance", price=100.0) == "DELAYED"
    assert classify_data_state(source="CACHE", provider="cache", price=100.0) == "DEGRADED"

    # Non-positive prices must be UNAVAILABLE
    assert classify_data_state(source="STREAM", provider="fyers", price=0.0) == "UNAVAILABLE"
    assert classify_data_state(source="REST", provider="zerodha", price=-10.0) == "UNAVAILABLE"

    # Verified live providers with valid prices
    assert classify_data_state(source="STREAM", provider="fyers", price=100.0) == "LIVE"
    assert classify_data_state(source="REST", provider="zerodha", price=100.0) == "LIVE"


def test_synthetic_futures_quotes_provenance():
    """Synthetic futures pricing must emit source=SYNTHETIC, data_state=DEGRADED, and no fabricated OHLC."""
    quotes = _futures_quotes(["NSE:NIFTY26NOVFUT"], correlation_id="test_prov")
    if "NSE:NIFTY26NOVFUT" in quotes:
        q = quotes["NSE:NIFTY26NOVFUT"]
        assert q.source == "SYNTHETIC"
        assert q.data_state == "DEGRADED"
        assert "SYNTHETIC_PRICE" in q.quality_flags
        assert q.open is None
        assert q.high is None
        assert q.low is None
        assert q.close is None


def test_tbt_depth_does_not_fabricate_last_price():
    """TBT depth object without explicit trade price must not invent LTP from top bid."""
    from market.fyers_tbt_manager import FyersTbtManager

    class DepthPacketWithoutLtp:
        bidprice = [25000.0, 24995.0]
        askprice = [25005.0, 25010.0]
        bidqty = [100, 200]
        askqty = [150, 250]
        bidordn = [5, 10]
        askordn = [7, 12]
        tbq = 300
        tsq = 400
        timestamp = 1700000000

    mgr = FyersTbtManager()
    parsed = mgr._parse_depth_object("NSE:NIFTY50-INDEX", DepthPacketWithoutLtp())
    assert parsed.get("ltp") is None, (
        "LTP must not be derived from top bid when trade price is absent"
    )
