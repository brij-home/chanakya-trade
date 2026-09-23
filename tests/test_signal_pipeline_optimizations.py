"""
tests/test_signal_pipeline_optimizations.py
─────────────────────────────────────────────
Comprehensive institutional test suite verifying the signal pipeline optimizations:
  1. Intraday OHLCV Cache Normalization (5-day master slice re-use across intervals/days).
  2. YFinance Rate-Limit Backoff (exponential cooldown prevents 429 retry storms).
  3. Options Open Interest Delta Baseline Calculation & Hybrid Cross-Enrichment.
  4. Gamma Blast Volume Turnover Expansion Fallback (fires even when broker oi_change == 0).
  5. BSE/MCX Exchange Resolution (SENSEX/BANKEX route to BSE/BFO, commodities to MCX).
"""

import time
import pandas as pd
from unittest.mock import patch
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from engine.auto_alert_engine import AutoAlertEngine
from engine.detectors.gamma_blast import detect_gamma_blast
from market.history import (
    get_ohlcv,
    _df_memory_cache,
    _df_memory_cache_lock,
    _YF_BACKOFF,
    _YF_BACKOFF_LOCK,
    _yfinance_fallback,
)
from market.options import enrich_options_chain_deltas

IST = ZoneInfo("Asia/Kolkata")


# ── 1. Intraday OHLCV Cache Normalization ───────────────────────


def test_intraday_ohlcv_cache_normalization_single_fetch():
    """Verify that multiple intraday queries with different days (1, 2, 5) reuse the 5-day master slice."""
    # Construct a synthetic 5-day 5m intraday DataFrame
    now = datetime.now(IST)
    dates = pd.date_range(end=now, periods=150, freq="5min")
    synthetic_df = pd.DataFrame(
        {
            "open": [100.0] * 150,
            "high": [105.0] * 150,
            "low": [99.0] * 150,
            "close": [103.0] * 150,
            "volume": [1000] * 150,
        },
        index=dates,
    )
    synthetic_df.attrs["provenance"] = {"data_source": "TEST", "provider": "mock"}

    test_sym = "TESTSYM_NORM"
    norm_key = f"{test_sym}_NSE_5minute_intraday_norm"

    with _df_memory_cache_lock:
        _df_memory_cache[norm_key] = (time.time(), synthetic_df)

    try:
        # Call get_ohlcv for 1 day - should hit normalized cache and slice
        with (
            patch("market.history._yfinance_fallback") as mock_yf,
            patch("brokers.session.get_data_broker") as mock_broker,
        ):
            df_1d = get_ohlcv(test_sym, exchange="NSE", interval="5minute", days=1)
            assert df_1d is not None
            assert not df_1d.empty
            # Network/broker fetches must NOT be called because normalized intraday cache served it
            mock_yf.assert_not_called()
            mock_broker.assert_not_called()

            # Verify slice is bounded by days=1 cutoff
            cutoff = now - timedelta(days=1)
            assert df_1d.index.min() >= cutoff or len(df_1d) < len(synthetic_df)

        # Call get_ohlcv for 2 days - should also hit normalized cache
        with (
            patch("market.history._yfinance_fallback") as mock_yf,
            patch("brokers.session.get_data_broker") as mock_broker,
        ):
            df_2d = get_ohlcv(test_sym, exchange="NSE", interval="5minute", days=2)
            assert df_2d is not None
            assert not df_2d.empty
            mock_yf.assert_not_called()
            mock_broker.assert_not_called()
    finally:
        with _df_memory_cache_lock:
            _df_memory_cache.pop(norm_key, None)


# ── 2. YFinance Rate-Limit Backoff ──────────────────────────────


def test_yfinance_backoff_cooldown_prevents_retry_storm():
    """Verify that a 429/empty response sets a backoff cooldown preventing repeat calls."""
    sym_key = "NSE:TESTCOOLDOWN:15MINUTE"
    now = time.time()

    with _YF_BACKOFF_LOCK:
        _YF_BACKOFF[sym_key] = now + 60.0  # active 60s cooldown

    try:
        with patch("market.yfinance_provider.yf_available", return_value=True):
            with patch("market.yfinance_provider.yf_get_ohlcv") as mock_yf:
                res = _yfinance_fallback(
                    symbol="TESTCOOLDOWN",
                    exchange="NSE",
                    interval="15minute",
                    from_date=datetime.now() - timedelta(days=5),
                    to_date=datetime.now(),
                )
                assert res == []
                # yf_get_ohlcv must NOT be called while ticker is in backoff cooldown!
                mock_yf.assert_not_called()
    finally:
        with _YF_BACKOFF_LOCK:
            _YF_BACKOFF.pop(sym_key, None)


# ── 3. Options Open Interest Delta Tracking & Scraper Cross-Enrichment ────


def test_options_chain_oi_delta_calculation():
    """Verify that enrich_options_chain_deltas tracks opening session baseline and calculates delta."""
    from dataclasses import dataclass

    @dataclass
    class MockOptionQuote:
        tradingsymbol: str
        strike: float
        option_type: str
        oi: int
        oi_change: int
        volume: int
        last_price: float
        expiry: str = "2026-09-24"
        change_pct: float = 0.0

    chain = [
        MockOptionQuote(
            tradingsymbol="NIFTY26SEP24500CE",
            strike=24500.0,
            option_type="CE",
            oi=50000,
            oi_change=0,  # broker provides 0
            volume=15000,
            last_price=120.0,
        )
    ]

    with patch("market.nse_scraper.nse_get_options_chain", return_value=None):
        # First call: Sets baseline OI to 50,000
        enrich_options_chain_deltas(chain, "NIFTY")
        assert chain[0].oi_change == 0

        # Second call: OI expands to 58,500 (8,500 net contract addition)
        chain_t2 = [
            MockOptionQuote(
                tradingsymbol="NIFTY26SEP24500CE",
                strike=24500.0,
                option_type="CE",
                oi=58500,
                oi_change=0,  # broker still sends 0
                volume=25000,
                last_price=145.0,
            )
        ]
        enrich_options_chain_deltas(chain_t2, "NIFTY")
        # Delta should now be 58,500 - 50,000 = +8,500!
        assert chain_t2[0].oi_change == 8500


def test_options_chain_scraper_cross_enrichment():
    """Verify that if broker oi_change is 0, changeinOpenInterest from nse_scraper is adopted."""
    from dataclasses import dataclass

    @dataclass
    class MockOptionQuote:
        tradingsymbol: str
        strike: float
        option_type: str
        oi: int
        oi_change: int
        volume: int
        last_price: float
        expiry: str = "2026-09-24"
        change_pct: float = 0.0

    chain = [
        MockOptionQuote(
            tradingsymbol="NIFTY26SEP24600PE",
            strike=24600.0,
            option_type="PE",
            oi=40000,
            oi_change=0,  # broker provides 0
            volume=8000,
            last_price=95.0,
        )
    ]

    # Mock nse_scraper providing changeinOpenInterest = -3500 (unwinding)
    mock_scraper_chain = [
        MockOptionQuote(
            tradingsymbol="NIFTY26SEP24600PE",
            strike=24600.0,
            option_type="PE",
            oi=40000,
            oi_change=-3500,
            volume=8000,
            last_price=95.0,
        )
    ]

    with patch("market.nse_scraper.nse_get_options_chain", return_value=mock_scraper_chain):
        enrich_options_chain_deltas(chain, "NIFTY")
        assert chain[0].oi_change == -3500


# ── 4. Gamma Blast Turnover Expansion Fallback ──────────────────


def test_gamma_blast_triggers_on_high_volume_expansion_when_oi_change_zero():
    """
    Verify that when broker delivers oi_change == 0,
    a contract with massive volume turnover expansion (Vol/OI >= 1.8 and +5% gain)
    triggers the Gamma Blast detector instead of being dropped.
    """
    from dataclasses import dataclass

    @dataclass
    class MockContract:
        tradingsymbol: str
        strike: float
        option_type: str
        last_price: float
        volume: int
        oi: int
        oi_change: int
        pchange: float
        expiry_date: str = "2026-09-24"

    # NIFTY 24500 CE: spot at 24500 (ATM)
    # Volume 50,000 vs OI 15,000 -> Vol/OI = 3.33x (> 1.8x)
    # oi_change is 0 (m.Stock hardcoded 0 limitation)
    # pchange is +12%
    chain = [
        MockContract(
            tradingsymbol="NIFTY24500CE",
            strike=24500.0,
            option_type="CE",
            last_price=120.0,
            volume=50000,
            oi=15000,
            oi_change=0,
            pchange=12.0,
        )
    ]

    alerts = detect_gamma_blast(
        underlying="NIFTY",
        spot=24500.0,
        chain=chain,
        vwap=24490.0,
    )

    assert len(alerts) >= 1
    alert = alerts[0]
    assert alert.alert_type == "GAMMA_BLAST"
    assert alert.option_type == "CE"
    assert alert.strike == 24500.0
    assert alert.metrics.get("is_volume_expansion") is True


# ── 5. BSE/MCX Exchange Resolution ──────────────────────────────


def test_auto_alert_engine_exchange_resolution():
    """Verify that AutoAlertEngine resolves correct exchange and prefixes for BSE/MCX/NSE."""
    engine = AutoAlertEngine()

    # BSE Benchmarks
    assert engine._resolve_index_exchange("SENSEX") == "BSE"
    assert engine._resolve_index_exchange("BANKEX") == "BSE"
    assert engine._resolve_index_exchange("BSE:SENSEX") == "BSE"

    # Commodities on MCX
    assert engine._resolve_index_exchange("CRUDEOIL") == "MCX"
    assert engine._resolve_index_exchange("NATURALGAS") == "MCX"
    assert engine._resolve_index_exchange("GOLD") == "MCX"

    # NSE Equities and Indices
    assert engine._resolve_index_exchange("NIFTY") == "NSE"
    assert engine._resolve_index_exchange("BANKNIFTY") == "NSE"
    assert engine._resolve_index_exchange("RELIANCE") == "NSE"


def test_sensex_gamma_blast_assigns_bfo_exchange():
    """Verify that Gamma Blast detector on SENSEX sets exchange='BFO'."""
    from dataclasses import dataclass

    @dataclass
    class MockContract:
        tradingsymbol: str
        strike: float
        option_type: str
        last_price: float
        volume: int
        oi: int
        oi_change: int
        pchange: float
        expiry_date: str = "2026-09-18"

    chain = [
        MockContract(
            tradingsymbol="SENSEX80000CE",
            strike=80000.0,
            option_type="CE",
            last_price=350.0,
            volume=80000,
            oi=20000,
            oi_change=5000,
            pchange=18.0,
        )
    ]

    alerts = detect_gamma_blast(
        underlying="SENSEX",
        spot=80000.0,
        chain=chain,
        vwap=79950.0,
    )

    assert len(alerts) >= 1
    assert alerts[0].exchange == "BFO"
    assert alerts[0].symbol == "SENSEX"
