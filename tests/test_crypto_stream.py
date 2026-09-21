"""
tests/test_crypto_stream.py
───────────────────────────
Institutional test suite for 24x7 Real-Time Crypto Streaming Pipeline.
Verifies WebSocket message handling, BBO & tick aggregation, quotes & history
integration, Smart Funnel quantitative pre-filtering, and FastAPI endpoints.
"""

import json
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest
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

    # 2. SMC analysis endpoint
    resp_smc = client.get("/api/crypto/smc?symbol=BTCUSDT&timeframe=15m&limit=50")
    assert resp_smc.status_code == 200
    smc_data = resp_smc.json()
    assert smc_data["symbol"] == "BTCUSDT"
    assert smc_data["ltp"] > 0
    assert "regime" in smc_data
    assert "active_demand_zones" in smc_data
    assert "active_supply_zones" in smc_data
    assert "target_1" in smc_data
