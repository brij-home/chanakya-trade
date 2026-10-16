"""
tests/test_fyers_options_chain_cache.py
───────────────────────────────────────
Verifies that FyersBroker.get_options_chain() populates expiry timestamp
and expiry date caches directly from response payload, preventing redundant
exploratory optionchain API calls.
"""

from unittest.mock import MagicMock, patch
from brokers.fyers import FyersAPI


def test_fyers_options_chain_proactive_expiry_caching():
    broker = FyersAPI()
    mock_fyers_sdk = MagicMock()

    # Synthetic option chain response containing expiryData
    mock_fyers_sdk.optionchain.return_value = {
        "s": "ok",
        "data": {
            "expiryData": [
                {"date": "23-10-2026", "expiry": 1792751400},
                {"date": "30-10-2026", "expiry": 1793356200},
            ],
            "optionsChain": [
                {
                    "symbol": "NSE:NIFTY26OCT25000CE",
                    "strike_price": 25000,
                    "option_type": "CE",
                    "ltp": 120.0,
                    "oi": 50000,
                    "lotSize": 50,
                }
            ],
            "callOi": 100000,
            "putOi": 120000,
        },
    }

    with (
        patch.object(broker, "_get_fyers", return_value=mock_fyers_sdk),
        patch("brokers.fyers._fyers_rate_limiter.acquire") as mock_acquire,
    ):
        # 1. First call: get_options_chain
        chain = broker.get_options_chain("NIFTY")
        assert len(chain) == 1
        assert mock_fyers_sdk.optionchain.call_count == 1
        assert mock_acquire.call_count == 1

        # 2. Subsequent call to _resolve_expiry_timestamp for '2026-10-23'
        # Must hit the in-memory cache and NOT call fyers.optionchain
        resolved_ts = broker._resolve_expiry_timestamp("NSE:NIFTY50-INDEX", "2026-10-23")
        assert resolved_ts == "1792751400"
        assert mock_fyers_sdk.optionchain.call_count == 1  # Still 1, no new API call!

        # 3. Subsequent call to get_expiries("NIFTY")
        # Must hit the in-memory cache and NOT call fyers.optionchain
        expiries = broker.get_expiries("NIFTY")
        assert expiries == ["2026-10-23", "2026-10-30"]
        assert mock_fyers_sdk.optionchain.call_count == 1  # Still 1, zero exploratory calls!
