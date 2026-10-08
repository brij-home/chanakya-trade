"""
tests/test_fyers_skills_enhancements.py
─────────────────────────────────────────
Deterministic unit tests for Fyers API v3 enhancements inspired by FyersDev/fyers-skills:
  - Weekly option expiry parsing for all 12 months (specifically Q4: O, N, D)
  - Decimal tick-size rounding (eliminating IEEE 754 float drift)
  - Lot quantity validation and lot rounding
  - Sliding-window FyersRateLimiter
  - Historical candle chunking windows
"""

import pytest
from datetime import datetime, timedelta
from brokers.fyers import (
    _parse_expiry_from_fyers_symbol,
    round_price_to_tick,
    validate_lot_qty,
    round_qty_to_lot,
    FyersRateLimiter,
)


class TestFyersExpiryParsing:
    """Test Fyers weekly and monthly option symbol expiry parsing."""

    def test_parse_weekly_single_digit_months(self):
        """Jan-Sep use single digits 1-9."""
        # 7th April 2026: 407
        assert _parse_expiry_from_fyers_symbol("NSE:NIFTY2640722100CE") == "2026-04-07"
        # 15th January 2026: 115
        assert _parse_expiry_from_fyers_symbol("NSE:BANKNIFTY2611548000PE") == "2026-01-15"
        # 24th September 2026: 924
        assert _parse_expiry_from_fyers_symbol("NSE:FINNIFTY2692423000CE") == "2026-09-24"

    def test_parse_weekly_q4_months_ond(self):
        """Oct, Nov, Dec use single letter codes: O (Oct), N (Nov), D (Dec)."""
        # 8th October 2026: O08
        assert _parse_expiry_from_fyers_symbol("NSE:NIFTY26O0824000CE") == "2026-10-08"
        # 15th November 2026: N15
        assert _parse_expiry_from_fyers_symbol("NSE:BANKNIFTY26N1548000PE") == "2026-11-15"
        # 24th December 2026: D24
        assert _parse_expiry_from_fyers_symbol("NSE:FINNIFTY26D2423000CE") == "2026-12-24"

    def test_parse_weekly_q4_full_spectrum(self):
        """Verify October (O), November (N), December (D) weekly options across strikes."""
        assert _parse_expiry_from_fyers_symbol("NSE:NIFTY26O2424000CE") == "2026-10-24"
        assert _parse_expiry_from_fyers_symbol("NSE:NIFTY26N1224000CE") == "2026-11-12"
        assert _parse_expiry_from_fyers_symbol("NSE:NIFTY26D3124000CE") == "2026-12-31"

    def test_parse_monthly_options(self):
        """Monthly options use 3-letter month (e.g. APR, OCT) expiring on the last Thursday."""
        # April 2026: last Thursday is 2026-04-30
        assert _parse_expiry_from_fyers_symbol("NSE:NIFTY26APR22100CE") == "2026-04-30"
        # October 2026: last Thursday is 2026-10-29
        assert _parse_expiry_from_fyers_symbol("NSE:NIFTY26OCT24000CE") == "2026-10-29"

    def test_parse_invalid_symbol(self):
        """Invalid or malformed symbol returns empty string."""
        assert _parse_expiry_from_fyers_symbol("INVALID_SYMBOL") == ""
        assert _parse_expiry_from_fyers_symbol("") == ""


class TestPrecisionOrderUtilities:
    """Test Decimal tick rounding and lot-sizing functions."""

    def test_round_price_to_tick_standard_equity(self):
        """0.05 tick size rounding without float representation drift."""
        assert round_price_to_tick(805.03, 0.05) == 805.05
        assert round_price_to_tick(805.02, 0.05) == 805.00
        assert round_price_to_tick(125.100000000002, 0.05) == 125.10

    def test_round_price_to_tick_futures_options(self):
        """F&O tick sizes (0.05 or 0.25)."""
        assert round_price_to_tick(23.47, 0.05) == 23.45
        assert round_price_to_tick(23.48, 0.05) == 23.50
        assert round_price_to_tick(1450.30, 0.25) == 1450.25
        assert round_price_to_tick(1450.40, 0.25) == 1450.50

    def test_round_price_to_tick_edge_cases(self):
        assert round_price_to_tick(0.0) == 0.0
        assert round_price_to_tick(None) == 0.0
        assert round_price_to_tick(-10.0) == 0.0

    def test_validate_lot_qty(self):
        """Validates that quantity is a multiple of lot size."""
        validate_lot_qty(50, 25)  # valid (2 lots of NIFTY)
        validate_lot_qty(30, 15)  # valid (2 lots of BANKNIFTY)
        validate_lot_qty(1, 1)  # valid (equity)

        with pytest.raises(ValueError, match="not a multiple of lot size"):
            validate_lot_qty(30, 25)

        with pytest.raises(ValueError, match="qty must be positive"):
            validate_lot_qty(0, 25)

    def test_round_qty_to_lot(self):
        """Rounds down to nearest lot multiple."""
        assert round_qty_to_lot(70, 25) == 50
        assert round_qty_to_lot(50, 25) == 50
        assert round_qty_to_lot(25, 25) == 25

        with pytest.raises(ValueError, match="smaller than one lot"):
            round_qty_to_lot(20, 25)


class TestFyersRateLimiter:
    """Test client-side sliding window rate limiter."""

    def test_rate_limiter_instant_acquire(self):
        limiter = FyersRateLimiter(max_per_sec=10.0, max_per_min=100.0)
        t0 = datetime.now()
        for _ in range(5):
            limiter.acquire()
        t1 = datetime.now()
        # 5 calls within max_per_sec=10 should execute immediately (< 50ms)
        assert (t1 - t0).total_seconds() < 0.2


class TestFyersHistoricalChunking:
    """Verify that requests exceeding single-window caps are chunked properly."""

    def test_chunking_intraday_multi_chunk(self, monkeypatch):
        from brokers.fyers import FyersAPI

        api = FyersAPI(app_id="TEST-100", secret_key="test_secret")
        api._access_token = "mock_token"

        captured_payloads = []

        class MockFyersClient:
            def history(self, payload):
                captured_payloads.append(payload)
                start_dt = datetime.strptime(payload["range_from"], "%Y-%m-%d")
                epoch = int(start_dt.timestamp())
                return {
                    "s": "ok",
                    "candles": [
                        [epoch, 100.0, 105.0, 99.0, 104.0, 1000],
                        [epoch + 300, 104.0, 106.0, 103.0, 105.0, 1200],
                    ],
                }

        monkeypatch.setattr(api, "_get_fyers", lambda: MockFyersClient())

        # Request 200 days of 5-minute data (should split into at least 3 chunks of <= 95 days)
        from_dt = datetime(2026, 1, 1)
        to_dt = from_dt + timedelta(days=200)

        rows = api.get_historical_data(
            "RELIANCE", interval="5minute", from_date=from_dt, to_date=to_dt
        )
        assert len(captured_payloads) >= 3
        assert len(rows) > 0
        # All chunk ranges should be <= 95 days
        for payload in captured_payloads:
            d_from = datetime.strptime(payload["range_from"], "%Y-%m-%d")
            d_to = datetime.strptime(payload["range_to"], "%Y-%m-%d")
            assert (d_to - d_from).days <= 95
