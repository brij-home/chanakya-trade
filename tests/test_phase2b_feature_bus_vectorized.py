"""Deterministic unit & integration tests for Phase 2B & Phase 3 upgrades (25-Nov-2026)."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd


def test_feature_bus_compression_pre_breakout_and_cache():
    from engine.detection_context import DetectionContext
    from engine.feature_bus import clear_feature_bus_cache, compute_shared_features

    clear_feature_bus_cache()
    dates = pd.date_range("2026-11-24 09:15", periods=40, freq="5min")
    # Tight coiling compression followed by a modest priming bar
    close = np.array([25000.0 + (i % 2) * 2.0 for i in range(39)] + [25005.0])
    df = pd.DataFrame(
        {
            "open": close - 1.0,
            "high": close + 3.0,
            "low": close - 3.0,
            "close": close,
            "volume": [10000.0] * 39 + [14000.0],
        },
        index=dates,
    )
    f1 = compute_shared_features("NSE:NIFTY", df)
    f2 = compute_shared_features("NIFTY", df)
    assert f1["status"] == "AVAILABLE"
    assert f1 == f2
    assert f1["atr_14"] > 0
    assert f1["pre_breakout_stage"] in ("STALK", "PRIMED", "IGNITED", "NEUTRAL")

    ctx = DetectionContext(symbol="NSE:NIFTY", canonical_symbol="NIFTY", ltp=25005.0, candles_5m=df)
    assert ctx.shared_features["status"] == "AVAILABLE"


def test_feature_bus_constituent_lead_lag_predictor():
    from engine.feature_bus import compute_constituent_lead_lag

    quotes = {
        "NSE:HDFCBANK": SimpleNamespace(last_price=1720.0, vwap=1700.0, change_pct=0.85),
        "NSE:ICICIBANK": SimpleNamespace(last_price=1310.0, vwap=1295.0, change_pct=0.65),
        "NSE:RELIANCE": SimpleNamespace(last_price=1350.0, vwap=1340.0, change_pct=0.45),
        "NSE:INFY": SimpleNamespace(last_price=1890.0, vwap=1880.0, change_pct=0.50),
    }
    res = compute_constituent_lead_lag("NIFTY", quotes_map=quotes)
    assert res["status"] == "AVAILABLE"
    assert res["lead_bias"] == "BULLISH_LEAD"
    assert res["bullish_vwap_weight_pct"] == 100.0

    # Empty quotes returns UNAVAILABLE honestly
    empty_res = compute_constituent_lead_lag("NIFTY", quotes_map={})
    assert empty_res["status"] == "UNAVAILABLE"
    assert empty_res["lead_bias"] == "NEUTRAL"


def test_futeq_intraday_mwpl_calculation_and_warnings():
    from market.fno_ban import compute_intraday_futeq_utilization

    chain = [
        SimpleNamespace(strike=100.0, option_type="CE", oi=300000, delta=0.50, iv=25.0),
        SimpleNamespace(strike=100.0, option_type="PE", oi=200000, delta=-0.50, iv=25.0),
    ]
    # FutEq OI = 400k + 0.5*300k + 0.5*200k = 650k out of 1,000,000 = 65% -> BAN_APPROACH_RISK
    res = compute_intraday_futeq_utilization(
        "SAIL", chain, fut_oi=400000, mwpl_limit=1_000_000, spot=100.0
    )
    assert res["status"] == "AVAILABLE"
    assert res["futeq_oi"] == 650000.0
    assert res["mwpl_utilization_pct"] == 65.0
    assert res["warning_level"] == "BAN_APPROACH_RISK"

    unavail = compute_intraday_futeq_utilization("SAIL", chain, fut_oi=1000, mwpl_limit=0.0)
    assert unavail["status"] == "UNAVAILABLE"


def test_semantic_cluster_key_coalesces_nearby_triggers():
    from datetime import date
    from engine.alert_identity import semantic_cluster_key

    d = date(2026, 11, 25)
    k1 = semantic_cluster_key(
        "NSE:NIFTY",
        direction="BULLISH",
        horizon="INTRADAY",
        trigger_price=25010.0,
        atr=35.0,
        session_date=d,
    )
    k2 = semantic_cluster_key(
        "NIFTY",
        direction="LONG",
        horizon="INTRADAY",
        trigger_price=25015.0,
        atr=35.0,
        session_date=d,
    )
    k_bear = semantic_cluster_key(
        "NIFTY",
        direction="BEARISH",
        horizon="INTRADAY",
        trigger_price=25010.0,
        atr=35.0,
        session_date=d,
    )
    assert k1 == k2
    assert k1 != k_bear


def test_vectorized_backtest_deducts_charges_and_slippage():
    from engine.backtest_vectorized import vectorized_backtest

    rng = np.random.default_rng(7)
    dates = pd.date_range("2025-01-01", periods=180, freq="B")
    # Oscillating synthetic series to force multiple RSI entries/exits
    t = np.arange(180, dtype=float)
    close = 500.0 + 40.0 * np.sin(t / 4.5) + rng.normal(0, 1.0, size=180)
    df = pd.DataFrame(
        {
            "open": close,
            "high": close + 4.0,
            "low": close - 4.0,
            "close": close,
            "volume": np.full(180, 100_000.0),
        },
        index=dates,
    )
    res_gross = vectorized_backtest(
        df, strategy_name="rsi", symbol="TEST", slippage_bps=0.0, include_charges=False
    )
    res_net = vectorized_backtest(
        df, strategy_name="rsi", symbol="TEST", slippage_bps=10.0, include_charges=True
    )
    assert res_gross.total_trades >= 1
    assert res_net.total_trades == res_gross.total_trades
    assert res_net.total_return < res_gross.total_return


def test_mcp_blocks_destructive_or_unpermitted_tool():
    from agent.tools import ToolRegistry
    from web.mcp import MCPServer

    reg = ToolRegistry()
    reg.register(
        name="unsafe_order_tool",
        description="Unsafe mutation",
        parameters={"type": "object", "properties": {}},
        fn=lambda: {"ok": True},
    )
    reg._tools["unsafe_order_tool"]["is_read_only"] = False
    reg._tools["unsafe_order_tool"]["is_destructive"] = True
    reg._tools["unsafe_order_tool"]["permission"] = "confirm"

    mcp = MCPServer(registry=reg)
    resp = mcp.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "unsafe_order_tool", "arguments": {}},
        }
    )
    assert "error" in resp
    assert resp["error"]["code"] == -32003
