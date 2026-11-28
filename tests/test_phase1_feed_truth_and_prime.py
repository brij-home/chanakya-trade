"""Regression tests for Phase 1: Feed Truth, Delta-Vol CVD, TickWarehouse, and Unified Internals."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from engine.cvd_engine import clear_all_cvd_trackers, get_cvd_metrics
from engine.market_internals import (
    NIFTY_WEIGHTS,
    clear_index_internals_cache,
    compute_index_internals,
)
from engine.tick_warehouse import TickWarehouse
from market.order_book import get_depth_book
from market.websocket import WebSocketManager


def test_websocket_computes_delta_volume_for_cvd_and_avoids_synthetic_depth():
    clear_all_cvd_trackers()
    get_depth_book("RELIANCE").clear()
    ws = WebSocketManager()

    # Packet 1: establishes baseline day volume (1,000,000) without L2 depth sizes
    p1 = {
        "symbol": "NSE:RELIANCE-EQ",
        "ltp": 1350.0,
        "vol_traded_today": 1_000_000,
        "bid": 1349.5,
        "ask": 1350.5,
        "exch_feed_time": 1764215000.0,
    }
    # Packet 2: traded +250 shares at ask -> +250 aggressive buy delta
    p2 = {
        "symbol": "NSE:RELIANCE-EQ",
        "ltp": 1350.5,
        "vol_traded_today": 1_000_250,
        "bid": 1349.5,
        "ask": 1350.5,
        "exch_feed_time": 1764215001.0,
    }
    # Packet 3: quote-only update (volume unchanged) -> must NOT pollute CVD
    p3 = {
        "symbol": "NSE:RELIANCE-EQ",
        "ltp": 1350.5,
        "vol_traded_today": 1_000_250,
        "bid": 1350.0,
        "ask": 1350.5,
        "exch_feed_time": 1764215002.0,
    }
    # Packet 4: traded +150 shares at bid -> -150 aggressive sell delta
    p4 = {
        "symbol": "NSE:RELIANCE-EQ",
        "ltp": 1350.0,
        "vol_traded_today": 1_000_400,
        "bid": 1350.0,
        "ask": 1350.5,
        "exch_feed_time": 1764215003.0,
    }

    ws._on_message(json.dumps([p1, p2, p3, p4]))

    tick = ws._ticks["NSE:RELIANCE-EQ"]
    assert tick.volume == 1_000_400
    assert tick.delta_volume == 150

    # Synthetic tick.volume // 10 depth must not be fabricated when bid_size/ask_size absent
    book = get_depth_book("RELIANCE")
    assert book.total_bid_qty == 0
    assert book.total_ask_qty == 0

    # CVD must sum only true delta volumes (250 + 150 = 400), never 4,000,900
    cvd = get_cvd_metrics("RELIANCE")
    assert cvd.session_volume == 400.0
    assert cvd.current_cvd == 100.0
    assert cvd.sample_count == 2

    ws.stop(timeout=0.5)
    clear_all_cvd_trackers()
    get_depth_book("RELIANCE").clear()


def test_tick_warehouse_builds_seconds_bars_and_archives_option_chains(tmp_path: Path):
    wh = TickWarehouse(base_dir=tmp_path, auto_flush_threshold=100)
    base_ms = int(datetime(2026, 11, 27, 9, 30, 0, tzinfo=timezone.utc).timestamp() * 1000)

    # Record L1 ticks across two 5-second buckets plus one ltp=0 L2-only row that must be ignored
    wh.record_tick("NIFTY", ltp=25000.0, volume=100, timestamp_ms=base_ms + 500)
    wh.record_tick("NIFTY", ltp=25010.0, volume=200, timestamp_ms=base_ms + 2500)
    wh.record_tick(
        "NIFTY", ltp=0.0, bid=25009.0, ask=25011.0, flag="TBT_L2", timestamp_ms=base_ms + 3000
    )
    wh.record_tick("NIFTY", ltp=25005.0, volume=50, timestamp_ms=base_ms + 4000)
    wh.record_tick("NIFTY", ltp=25020.0, volume=300, timestamp_ms=base_ms + 6000)

    bars = wh.build_seconds_bars("NIFTY", interval_sec=5)
    assert len(bars) == 2
    assert list(bars.columns) == ["open", "high", "low", "close", "volume"]
    assert bars.index.tz is None
    assert bars.iloc[0]["open"] == 25000.0
    assert bars.iloc[0]["high"] == 25010.0
    assert bars.iloc[0]["close"] == 25005.0
    assert bars.iloc[0]["volume"] == 350.0
    assert bars.iloc[1]["open"] == 25020.0

    # Option chain archival preserves nulls honestly
    contracts = [
        SimpleNamespace(
            symbol="NSE:NIFTY26DEC25000CE",
            expiry="2026-12-01",
            strike=25000.0,
            option_type="CE",
            last_price=180.0,
            bid=179.5,
            ask=180.5,
            oi=50000,
            oi_change=1200,
            volume=15000,
            iv=14.2,
            delta=0.52,
            gamma=0.001,
            theta=-12.0,
            vega=8.5,
        ),
        SimpleNamespace(
            symbol="NSE:NIFTY26DEC25000PE",
            expiry="2026-12-01",
            strike=25000.0,
            option_type="PE",
            last_price=165.0,
            bid=None,
            ask=None,
            oi=48000,
            oi_change=-500,
            volume=12000,
            iv=None,
            delta=None,
            gamma=None,
            theta=None,
            vega=None,
        ),
    ]
    written = wh.record_option_chain_snapshot("NIFTY", contracts, spot=25010.0, vix=13.4)
    assert written == 2

    chain_df = wh.query_option_chain_snapshots("NIFTY")
    assert len(chain_df) == 2
    ce_row = chain_df[chain_df["option_type"] == "CE"].iloc[0]
    pe_row = chain_df[chain_df["option_type"] == "PE"].iloc[0]
    assert ce_row["iv"] == 14.2
    assert pd.isna(pe_row["iv"])
    assert pd.isna(pe_row["delta"])
    assert pd.isna(pe_row["bid"])


def test_market_internals_fails_closed_without_quotes_and_uses_unified_weights():
    clear_index_internals_cache()
    assert "TMPV" in NIFTY_WEIGHTS
    assert "TATAMOTORS" not in NIFTY_WEIGHTS

    from engine.feature_bus import INDEX_CONSTITUENT_WEIGHTS
    from engine.index_contagion import INDEX_CONSTITUENTS

    assert INDEX_CONSTITUENTS == INDEX_CONSTITUENT_WEIGHTS

    with (
        patch("market.quotes.get_ltp", return_value=0.0),
        patch("market.quotes.get_quote", return_value={}),
    ):
        rep = compute_index_internals("NIFTY")
        assert rep.status == "UNAVAILABLE"
        assert rep.regime == "UNAVAILABLE"
        assert rep.spot == 0.0


def test_signal_enrichment_passes_all_confluence_factors():
    from engine.alert_model import AutoAlert
    from engine.signal_enrichment import enrich_alert_with_feature_bus

    idx = pd.date_range("2026-11-27 09:15", periods=20, freq="5min")
    df_5m = pd.DataFrame(
        {
            "open": [25000.0] * 20,
            "high": [25020.0] * 20,
            "low": [24990.0] * 20,
            "close": [25010.0] * 20,
            "volume": [10000.0] * 20,
        },
        index=idx,
    )
    alert = AutoAlert(
        alert_id="aa-test-nifty-20261127",
        alert_type="GAMMA_BLAST",
        stage="PRIMED",
        symbol="NIFTY",
        contract_symbol="NSE:NIFTY26DEC25000CE",
        exchange="NFO",
        segment="FNO_INDEX",
        direction="BULLISH",
        headline="Test",
        summary="Test",
        ltp=25080.0,
        trigger_level=25080.0,
        stop_loss=25010.0,
        target_level=25220.0,
        confidence=85,
        is_live=True,
        environment="PAPER",
        metrics={
            "underlying_spot": 25080.0,
            "vwap": 25010.0,
            "rvol": 2.3,
            "pre_open_gap_pct": 0.9,
            "call_oi_change_pct": -14.0,
            "put_oi_change_pct": 18.0,
            "market_structure_signal": "BOS",
        },
    )

    enrich_alert_with_feature_bus(alert, df_5m=df_5m, quotes_map={})
    rep = alert.details["confluence_report"]
    by_name = {f["name"]: f for f in rep["factors"]}
    assert by_name["Pre-Open Imbalance"]["status"] == "CONFIRMED"
    assert by_name["Derivatives Order Flow"]["status"] == "CONFIRMED"
    assert by_name["Market Structure"]["status"] == "CONFIRMED"
    assert rep["score"] >= 85.0


def test_history_seconds_interval_skips_yfinance_and_reads_tick_warehouse(
    tmp_path: Path, monkeypatch
):
    from market.history import clear_df_memory_cache, get_ohlcv

    clear_df_memory_cache()
    wh = TickWarehouse(base_dir=tmp_path, auto_flush_threshold=50)
    base_ms = int(datetime(2026, 11, 27, 10, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    for i in range(6):
        wh.record_tick("NSE:NIFTY 50", ltp=25000.0 + i, volume=100, timestamp_ms=base_ms + i * 5000)

    monkeypatch.setattr("engine.tick_warehouse.get_tick_warehouse", lambda *a, **k: wh)
    yf_called = []
    monkeypatch.setattr(
        "market.history._yfinance_fallback", lambda *a, **k: yf_called.append(True) or []
    )

    df = get_ohlcv("NIFTY 50", exchange="NSE", interval="5s", days=1)
    assert len(df) >= 5
    assert yf_called == []
    assert df.attrs["provenance"]["data_source"] == "TICK_WAREHOUSE_SECONDS"
