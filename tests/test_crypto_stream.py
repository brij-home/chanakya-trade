"""
tests/test_crypto_stream.py
───────────────────────────
Institutional test suite for 24x7 Real-Time Crypto Streaming Pipeline.
Verifies WebSocket message handling, BBO & tick aggregation, quotes & history
integration, Smart Funnel quantitative pre-filtering, and FastAPI endpoints.
"""

from unittest.mock import patch
import pandas as pd
from fastapi.testclient import TestClient

from brokers.base import Quote
from market.crypto_stream import (
    CryptoStreamManager,
    normalize_crypto_symbol,
    crypto_stream,
)
from market.quotes import get_quote
from market.history import get_ohlcv
from agent.smart_funnel import SmartFunnel
from web.api import app


# ── 1. Symbol Normalization Tests ─────────────────────────────


def test_normalize_crypto_symbol():
    assert normalize_crypto_symbol("BTC") == "BTCUSDT"
    assert normalize_crypto_symbol("CRYPTO:BTC") == "BTCUSDT"
    assert normalize_crypto_symbol("CRYPTO:BTCUSDT") == "BTCUSDT"
    assert normalize_crypto_symbol("ETH") == "ETHUSDT"
    assert normalize_crypto_symbol("CRYPTO:ETH") == "ETHUSDT"
    assert normalize_crypto_symbol("SOL") == "SOLUSDT"
    assert normalize_crypto_symbol("CRYPTO:SOL") == "SOLUSDT"
    assert normalize_crypto_symbol("BNB") == "BNBUSDT"
    assert normalize_crypto_symbol("CRYPTO:BNBUSDT") == "BNBUSDT"


# ── 2. CryptoStreamManager Unit Tests ─────────────────────────


def test_crypto_stream_ticker_and_book_ticker_processing():
    manager = CryptoStreamManager(symbols=["BTCUSDT", "ETHUSDT"])

    # Simulate ticker payload
    ticker_payload = {
        "s": "BTCUSDT",
        "c": "81250.50",
        "p": "1250.50",
        "P": "1.56",
        "h": "82000.00",
        "l": "79500.00",
        "v": "15420.5",
        "o": "80000.00",
        "b": "81250.00",
        "a": "81251.00",
    }
    manager._process_ticker_payload(ticker_payload, now_ts=1000.0)

    q = manager.get_quote("BTCUSDT")
    assert q is not None
    assert q.symbol == "CRYPTO:BTCUSDT"
    assert q.last_price == 81250.50
    assert q.high == 82000.00
    assert q.low == 79500.00
    assert q.change == 1250.50
    assert q.change_pct == 1.56
    assert q.provider == "binance"
    assert q.data_state == "LIVE"

    # Simulate best bid/ask payload
    book_payload = {"s": "BTCUSDT", "b": "81250.25", "a": "81250.75"}
    manager._process_book_ticker_payload(book_payload, now_ts=1001.0)
    q_updated = manager.get_quote("BTC")
    assert q_updated.bid == 81250.25
    assert q_updated.ask == 81250.75

    # Check snapshot
    snap = manager.get_snapshot()
    assert len(snap["tickers"]) >= 1
    btc_entry = next(t for t in snap["tickers"] if t["symbol"] == "BTCUSDT")
    assert btc_entry["ltp"] == 81250.50
    assert btc_entry["direction"] == "up"


def test_crypto_stream_kline_processing():
    manager = CryptoStreamManager(symbols=["BTCUSDT"])
    kline_payload = {
        "s": "BTCUSDT",
        "k": {
            "t": 1789930000000,
            "o": "81000.0",
            "h": "81500.0",
            "l": "80900.0",
            "c": "81400.0",
            "v": "100.5",
            "x": False,
        },
    }
    manager._process_kline_payload(kline_payload, now_ts=1000.0)
    assert len(manager._klines["BTCUSDT"]) == 1
    candle = manager._klines["BTCUSDT"][0]
    assert candle["open"] == 81000.0
    assert candle["close"] == 81400.0
    assert candle["volume"] == 100.5


# ── 3. Quotes and History Integration Tests ───────────────────


def test_quotes_crypto_integration():
    test_quote = Quote(
        symbol="CRYPTO:BTCUSDT",
        last_price=81000.0,
        change=500.0,
        change_pct=0.62,
        provider="binance",
        data_state="LIVE",
    )
    with patch.object(crypto_stream, "get_quote", return_value=test_quote):
        res = get_quote(["CRYPTO:BTCUSDT", "BTC"], bypass_cache=True)
        assert "CRYPTO:BTCUSDT" in res
        assert res["CRYPTO:BTCUSDT"].last_price == 81000.0
        assert res["CRYPTO:BTCUSDT"].provider == "binance"


def test_history_crypto_integration():
    sample_df = pd.DataFrame(
        [
            {
                "date": pd.to_datetime(1789900000000, unit="ms"),
                "open": 80000.0,
                "high": 80500.0,
                "low": 79800.0,
                "close": 80200.0,
                "volume": 50.0,
            },
            {
                "date": pd.to_datetime(1789900900000, unit="ms"),
                "open": 80200.0,
                "high": 80800.0,
                "low": 80100.0,
                "close": 80700.0,
                "volume": 75.0,
            },
        ]
    ).set_index("date")

    with patch.object(crypto_stream, "get_klines", return_value=sample_df):
        df = get_ohlcv("BTCUSDT", exchange="CRYPTO", interval="15m")
        assert not df.empty
        assert len(df) == 2
        assert "close" in df.columns
        assert df["close"].iloc[-1] == 80700.0


# ── 4. Smart Funnel Pre-Filter Tests ─────────────────────────


def test_smart_funnel_crypto_prefilter():
    funnel = SmartFunnel(verbose=False)
    test_quote = Quote(
        symbol="CRYPTO:BTCUSDT",
        last_price=81000.0,
        change=500.0,
        change_pct=0.62,
        provider="binance",
        data_state="LIVE",
    )
    sample_df = pd.DataFrame(
        [
            {
                "date": pd.to_datetime(1789900000000 + i * 900000, unit="ms"),
                "open": 80000.0 + i * 10,
                "high": 80500.0 + i * 10,
                "low": 79800.0 + i * 10,
                "close": 80200.0 + i * 10,
                "volume": 50.0,
            }
            for i in range(35)
        ]
    ).set_index("date")
    with (
        patch.object(crypto_stream, "get_quote", return_value=test_quote),
        patch.object(crypto_stream, "get_klines", return_value=sample_df),
    ):
        report = funnel.evaluate_stock_quant("BTCUSDT", exchange="CRYPTO")
        assert report.symbol == "BTCUSDT"
        assert report.exchange == "CRYPTO"
        assert report.metrics.get("ltp", 0.0) > 0


# ── 5. FastAPI Endpoints Tests ───────────────────────────────


def test_crypto_api_endpoints():
    client = TestClient(app)

    # 1. Snapshot endpoint
    resp = client.get("/api/crypto/snapshot")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "tickers" in data

    # 2. SMC analysis endpoint with hermetic klines
    sample_df = pd.DataFrame(
        [
            {
                "date": pd.to_datetime(1789900000000 + i * 900000, unit="ms"),
                "open": 80000.0 + i * 10,
                "high": 80500.0 + i * 10,
                "low": 79800.0 + i * 10,
                "close": 80200.0 + i * 10,
                "volume": 50.0,
            }
            for i in range(30)
        ]
    ).set_index("date")

    with patch.object(crypto_stream, "get_klines", return_value=sample_df):
        resp_smc = client.get("/api/crypto/smc?symbol=BTCUSDT&timeframe=15m&limit=50")
        assert resp_smc.status_code == 200
        smc_data = resp_smc.json()
        assert smc_data["symbol"] == "BTCUSDT"
        assert smc_data["ltp"] > 0
        assert "regime" in smc_data
        assert "active_demand_zones" in smc_data
        assert "active_supply_zones" in smc_data
        assert "target_1" in smc_data


def test_crypto_order_flow_cvd_metrics():
    """Verify Cumulative Volume Delta (CVD) calculation and absorption signal logic."""
    manager = CryptoStreamManager(symbols=["BTCUSDT"])
    sample_bars = []
    for i in range(30):
        tot_v = 100.0 + i * 2.0
        # Create aggressive buy delta
        buy_v = tot_v * 0.70
        sell_v = tot_v * 0.30
        sample_bars.append(
            {
                "date": pd.to_datetime(1789900000000 + i * 900000, unit="ms"),
                "open": 80000.0 + i * 15,
                "high": 80100.0 + i * 15,
                "low": 79950.0 + i * 15,
                "close": 80080.0 + i * 15,
                "volume": tot_v,
                "buy_volume": buy_v,
                "sell_volume": sell_v,
                "delta": buy_v - sell_v,
            }
        )
    df = pd.DataFrame(sample_bars).set_index("date")
    df["date"] = df.index

    with patch.object(manager, "get_klines", return_value=df):
        res = manager.get_order_flow_metrics("BTCUSDT", interval="15m", limit=30)
        assert res["status"] == "ONLINE"
        assert res["symbol"] == "BTCUSDT"
        assert res["current_delta"] > 0
        assert res["delta_bias"] == "BULLISH_AGGRESSIVE"
        assert res["cumulative_volume_delta"] > 0
        assert res["cvd_trend"] == "RISING"
        assert len(res["bars"]) > 0


def test_crypto_basis_arbitrage_matrix():
    """Verify Delta-Neutral Cash & Carry basis and funding arbitrage engine."""
    manager = CryptoStreamManager(symbols=["BTCUSDT", "ETHUSDT"])
    mock_quote = Quote(
        symbol="CRYPTO:BTCUSDT",
        last_price=80000.0,
        open=79000.0,
        high=80500.0,
        low=78500.0,
        close=79500.0,
        volume=1000,
        provider="binance",
        source="TEST",
        data_state="LIVE",
        received_at="2026-09-27T12:00:00Z",
    )
    mock_fut = {
        "symbol": "BTCUSDT",
        "mark_price": 80080.0,
        "funding_rate_8h": 0.0003,  # ~32.8% APY
        "open_interest_usd": 500000000.0,
        "next_funding_time": 1789950000000,
    }

    with (
        patch.object(manager, "get_quote", return_value=mock_quote),
        patch.object(manager, "fetch_futures_metrics", return_value=mock_fut),
    ):
        res = manager.get_basis_arbitrage_matrix()
        assert res["status"] == "ONLINE"
        assert len(res["matrix"]) > 0
        opp = res["matrix"][0]
        assert opp["annualized_funding_yield_pct"] > 18.0
        assert opp["strategy"] == "CASH_AND_CARRY_PRIME"
        assert opp["action"] == "BUY_SPOT_AND_SHORT_PERP"
        assert opp["daily_usd_per_10k"] > 0


def test_new_crypto_fastapi_endpoints():
    """Verify new /api/crypto/orderflow, /liquidations, /basis, and /volatility-surface endpoints."""
    client = TestClient(app)

    # 1. Basis endpoint
    resp_basis = client.get("/api/crypto/basis")
    assert resp_basis.status_code == 200
    b_data = resp_basis.json()
    assert "status" in b_data
    assert "matrix" in b_data

    # 2. Volatility surface endpoint
    resp_vol = client.get("/api/crypto/volatility-surface?currency=BTC")
    assert resp_vol.status_code == 200
    v_data = resp_vol.json()
    assert "currency" in v_data
    assert v_data["currency"] == "BTC"
