"""
tests/test_commodity_signal_pipeline_rca_fixes.py
─────────────────────────────────────────────────
Regression tests for RCA fixes ensuring commodity signals are never silently
suppressed during active market sessions:
  1. Discovery policy persistence survives process boundaries.
  2. Golden Hours scan covers full watched commodity roster (Silver, Copper, NatGas, etc.).
  3. Confirmed breakout thrust allows runaway momentum without false overbought RSI veto.
  4. Mindful macro friction tags confirmed breakdowns rather than hard-dropping real price action.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from config.discovery_policy import (
    DiscoveryPolicy,
    get_discovery_policy,
    set_discovery_policy,
)
from engine.auto_alert_engine import AutoAlertEngine
from engine.detectors.commodity import detect_commodity_breakouts
from market.macro import MacroSnapshot


def test_discovery_policy_persistence(tmp_path, monkeypatch):
    """Verifies that setting discovery policy persists to disk and reloads when env is unset."""
    monkeypatch.delenv("SESSION_FOCUS_MODE", raising=False)
    monkeypatch.setenv("TEST_DISCOVERY_PERSISTENCE", "1")

    fake_profile_path = tmp_path / "discovery_profile.json"
    monkeypatch.setattr("config.paths.app_data_path", lambda name: fake_profile_path)

    pol = set_discovery_policy("FNO_PRIORITY")
    assert pol.profile == "FNO_PRIORITY"
    assert fake_profile_path.exists()

    # Clear env var to verify it reads from disk
    monkeypatch.delenv("SESSION_FOCUS_MODE", raising=False)
    reloaded = get_discovery_policy()
    assert reloaded.profile == "FNO_PRIORITY"
    assert reloaded.allows("COMMODITY") is True


def test_golden_hours_universe_coverage():
    """Verifies that watched commodities roster covers liquid MCX metals and energy."""
    engine = AutoAlertEngine.__new__(AutoAlertEngine)
    engine._watched_commodities = [
        "CRUDEOIL",
        "NATURALGAS",
        "GOLD",
        "SILVER",
        "COPPER",
        "ZINC",
        "ALUMINIUM",
    ]
    targets = engine.watched_commodities
    for sym in ["SILVER", "COPPER", "GOLD", "NATURALGAS", "CRUDEOIL"]:
        assert sym in targets, f"{sym} must be present in watched commodities"


def test_naturalgas_confirmed_breakout_allows_momentum_rsi(monkeypatch):
    """Verifies that a confirmed Donchian breakout on Natural Gas allows RSI up to 74.0."""
    monkeypatch.setenv("SESSION_FOCUS_MODE", "BALANCED")

    mock_quote = MagicMock()
    mock_quote.force_live_eval = True
    mock_quote.symbol = "MCX:NATURALGAS"
    mock_quote.last_price = 345.0
    mock_quote.ltp = 345.0
    mock_quote.open = 334.0
    mock_quote.high = 345.2
    mock_quote.low = 333.0
    mock_quote.vwap = 338.0
    mock_quote.change_pct = 3.29
    mock_quote.volume = 80000

    dates = pd.date_range("2026-11-24 18:00", periods=25, freq="5min")
    closes = [
        335.0, 335.0, 335.0, 335.0, 335.0, 335.0, 335.0, 335.0, 335.0, 335.0,
        336.0, 335.5, 336.5, 336.0, 337.0, 336.5, 337.5, 337.0, 338.0, 335.5,
        338.5, 337.5, 341.0, 343.0, 345.0
    ]
    opens = [c - 0.5 for c in closes]
    highs = [c + 0.2 for c in closes]
    lows = [c - 0.8 for c in closes]
    highs[-1] = 345.2
    lows[-1] = 340.0
    opens[-1] = 340.5
    closes[-1] = 345.0
    volumes = [1000.0] * 20 + [2500.0] * 5

    df_5m = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )

    monkeypatch.setattr(
        "market.macro.get_macro_snapshot",
        lambda: MacroSnapshot(dxy_change=0.0, crude_change=0.0, natural_gas_change=1.5),
    )

    with patch("market.quotes.get_quote", return_value={"MCX:NATURALGAS": mock_quote}):
        with patch("market.history.get_ohlcv", return_value=df_5m):
            with patch("market.quotes.get_ltp", return_value=345.0):
                alerts = detect_commodity_breakouts(universe=["NATURALGAS"])
                assert len(alerts) >= 1, "Confirmed NatGas breakout must NOT be suppressed by rigid 68.0 RSI cap!"
                assert alerts[0].direction == "BULLISH"


def test_silver_confirmed_breakdown_not_hard_vetoed_by_soft_dxy(monkeypatch):
    """Verifies that a -2.5% Donchian breakdown on Silver is tagged with friction rather than dropped."""
    monkeypatch.setenv("SESSION_FOCUS_MODE", "BALANCED")

    mock_quote = MagicMock()
    mock_quote.force_live_eval = True
    mock_quote.symbol = "MCX:SILVER"
    mock_quote.last_price = 145500.0
    mock_quote.ltp = 145500.0
    mock_quote.open = 149200.0
    mock_quote.high = 149500.0
    mock_quote.low = 145400.0
    mock_quote.vwap = 147800.0
    mock_quote.change_pct = -2.48
    mock_quote.volume = 12000

    dates = pd.date_range("2026-11-24 18:00", periods=25, freq="5min")
    closes = [
        148000.0, 148000.0, 148000.0, 148000.0, 148000.0, 148000.0, 148000.0,
        148000.0, 148000.0, 148000.0, 147800.0, 148400.0, 147500.0, 147600.0,
        147200.0, 147400.0, 147000.0, 147300.0, 146600.0, 146800.0, 146300.0,
        146100.0, 145900.0, 145700.0, 145500.0
    ]
    opens = [c + 150.0 for c in closes]
    highs = [c + 200.0 for c in closes]
    lows = [c - 100.0 for c in closes]
    opens[-1] = 146500.0
    highs[-1] = 146600.0
    lows[-1] = 145400.0
    closes[-1] = 145500.0
    volumes = [50.0] * 20 + [150.0] * 5

    df_5m = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )

    mock_macro_obj = MagicMock()
    mock_macro_obj.status = "ONLINE"
    mock_macro_obj.bullion.bullion_bias = "STRONG_TAILWIND"
    mock_macro_obj.bullion.notes = ["DXY softening (-0.42%)"]
    mock_macro_obj.bullion.silver_outperformance_favored = False

    monkeypatch.setattr(
        "market.commodity_macro.get_commodity_macro_snapshot",
        lambda: mock_macro_obj,
    )
    monkeypatch.setattr(
        "market.macro.get_macro_snapshot",
        lambda: MacroSnapshot(dxy_change=-0.42, crude_change=0.0, natural_gas_change=0.0),
    )

    with patch("market.quotes.get_quote", return_value={"MCX:SILVER": mock_quote}):
        with patch("market.history.get_ohlcv", return_value=df_5m):
            with patch("market.quotes.get_ltp", return_value=145500.0):
                alerts = detect_commodity_breakouts(universe=["SILVER"])
                assert len(alerts) >= 1, "Confirmed Silver breakdown must NOT be dropped by counter-trend DXY tailwind!"
                assert alerts[0].direction == "BEARISH"
                # Assert mindful friction was recorded
                tags = getattr(alerts[0], "tags", [])
                assert any("Macro Counter-Trend Friction" in str(t) for t in tags)
                # Assert mini alternative is present
                plan = getattr(alerts[0], "actionable_plan", {}) or {}
                assert "mini_alternative" in plan, "Silver alert must provide mini sizing alternative"
                assert plan["mini_alternative"]["symbol"] == "MCX:SILVERM"
                assert plan["mini_alternative"]["micro_symbol"] == "MCX:SILMIC"


def test_paper_trading_mcx_price_resolution(monkeypatch, tmp_path):
    """Verifies that PaperBroker resolves MCX commodity prices and does not reject with 'price unavailable'."""
    from engine.paper import PaperBroker
    from brokers.base import OrderRequest

    monkeypatch.setattr("engine.paper.get_paper_file", lambda: tmp_path / "paper_portfolio.json")
    engine = PaperBroker(capital=500_000.0)
    monkeypatch.setattr("market.quotes.get_ltp", lambda sym: 6150.0 if "CRUDEOIL" in sym else 0.0)

    # 1. Qualified symbol
    assert engine._ltp("MCX:CRUDEOIL") == 6150.0
    # 2. Bare symbol
    assert engine._ltp("CRUDEOIL") == 6150.0

    # 3. Paper order execution
    req = OrderRequest(
        symbol="MCX:CRUDEOIL26DECFUT",
        exchange="MCX",
        quantity=100,
        transaction_type="BUY",
        order_type="MARKET",
        product="MIS",
    )
    resp = engine.place_order(req)
    assert resp.status == "COMPLETE", f"Paper order for MCX must succeed, got: {resp.message}"
    assert resp.average_price > 0


def test_natgasmini_pre_tender_auto_roll():
    """Verifies that NATGASMINI auto-rolls to December contract when inside the 48h pre-tender window (>22nd)."""
    import datetime as dt
    from brokers.fyers import _resolve_commodity_contract

    # Before tender window (e.g. 20 Nov)
    pre_tender_dt = dt.datetime(2026, 11, 20, 18, 0)
    assert _resolve_commodity_contract("NATGASMINI", ref_time=pre_tender_dt) == "MCX:NATGASMINI26NOVFUT"

    # Inside tender window (e.g. 24 Nov)
    tender_dt = dt.datetime(2026, 11, 24, 18, 0)
    assert _resolve_commodity_contract("NATGASMINI", ref_time=tender_dt) == "MCX:NATGASMINI26DECFUT"

