"""
tests/test_super_investor_pipeline.py
─────────────────────────────────────
Deterministic test suite for:
  1. 3-Axis (X, Y, Z) Super-Investor & Magic Trend Engine
  2. Institutional Thematic Baskets (100-Baggers, Lynch GARP, Jhunjhunwala Capex, CAN SLIM)
  3. Broker Portfolio AI Doctor & Wealth Optimizer
  4. FastAPI Sidecar Super-Investor Skills Routes
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from analysis.magic_trend import calculate_magic_trend_score
from analysis.thematic_baskets import (
    THEMATIC_BASKETS,
    list_all_thematic_baskets,
    scan_thematic_basket,
)
from engine.portfolio import HoldingRow, PortfolioSummary
from engine.portfolio_doctor import diagnose_portfolio
from web.api import app


def _create_synthetic_growth_df(n: int = 260) -> pd.DataFrame:
    """Generates an idealized Stage 2 breakout DataFrame."""
    np.random.seed(42)
    base = np.linspace(120, 310, n)
    noise = np.random.normal(0, 1.2, n)
    closes = base + noise
    highs = closes + np.random.uniform(0.5, 2.0, n)
    lows = closes - np.random.uniform(0.5, 2.0, n)
    volumes = np.random.uniform(100000, 400000, n)

    dates = pd.date_range(end="2026-08-30", periods=n, freq="B")
    return pd.DataFrame(
        {
            "open": closes * 0.99,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        },
        index=dates,
    )


# ── 1. Magic Trend 3-Axis Engine Tests ─────────────────────────


def test_magic_trend_3axis_scoring():
    df = _create_synthetic_growth_df()
    report = calculate_magic_trend_score("TRENT", df=df)

    assert report.symbol == "TRENT"
    assert report.magic_trend_score >= 60
    assert 0 <= report.x_quality_score <= 35
    assert 0 <= report.y_growth_score <= 35
    assert 0 <= report.z_timing_score <= 30
    assert len(report.axes) == 3
    assert report.execution_ticket["action"] == "LONG (BUY)"
    assert report.execution_ticket["entry_price"] > 0
    assert report.execution_ticket["stop_loss"] < report.execution_ticket["entry_price"]


# ── 2. Thematic Baskets Scanner Tests ──────────────────────────


def test_thematic_baskets_metadata_and_scanning():
    baskets = list_all_thematic_baskets()
    assert len(baskets) == 6

    # Test Mayer 100-baggers scan with synthetic df cache
    df = _create_synthetic_growth_df()
    cache = {sym: df for sym in THEMATIC_BASKETS["mayer_100_baggers"].symbols}

    result = scan_thematic_basket(
        basket_id="mayer_100_baggers",
        min_score=50,
        max_results=5,
        df_cache=cache,
    )

    assert result.basket_id == "mayer_100_baggers"
    assert result.total_scanned >= 4
    assert len(result.top_candidates) > 0
    assert result.top_candidates[0].magic_trend_score >= 50


# ── 3. Broker Portfolio AI Doctor Tests ────────────────────────


def test_portfolio_doctor_diagnosis():
    # Setup test portfolio with a high concentration and a Stage 4 loser
    demo_holdings = [
        HoldingRow(
            symbol="TRENT",
            qty=30,
            avg_price=5000.0,
            ltp=7000.0,
            value=210000.0,
            pnl=60000.0,
            pnl_pct=40.0,
            product="CNC",
        ),
        HoldingRow(
            symbol="HAL",
            qty=20,
            avg_price=4000.0,
            ltp=4600.0,
            value=92000.0,
            pnl=12000.0,
            pnl_pct=15.0,
            product="CNC",
        ),
        HoldingRow(
            symbol="IDEA",
            qty=2000,
            avg_price=16.0,
            ltp=8.0,
            value=16000.0,
            pnl=-16000.0,
            pnl_pct=-50.0,
            product="CNC",
        ),
    ]
    summary = PortfolioSummary(
        holdings=demo_holdings,
        positions=[],
        funds=type("FundsObj", (), {"available_cash": 35000.0})(),
        greeks=None,  # type: ignore
        risk=None,  # type: ignore
        total_value=318000.0,
        total_pnl=56000.0,
        day_pnl=0.0,
    )

    report = diagnose_portfolio(portfolio_summary=summary)

    assert report.total_net_worth > 0
    assert report.herfindahl_index > 0
    assert len(report.dead_money_holdings) >= 1  # IDEA flagged
    assert report.dead_money_holdings[0].symbol == "IDEA"
    assert len(report.tax_harvest_candidates) >= 1
    assert len(report.action_prescriptions) >= 1


# ── 4. FastAPI Endpoints Integration Tests ─────────────────────


def test_fastapi_super_investor_endpoints():
    client = TestClient(app)

    # 1. Thematic baskets list
    res_b = client.get("/skills/thematic_baskets/list")
    assert res_b.status_code == 200
    data_b = res_b.json()
    assert data_b["data"]["total_baskets"] == 6

    # 2. Portfolio doctor
    res_d = client.get("/skills/portfolio/doctor")
    assert res_d.status_code == 200
    data_d = res_d.json()
    assert "total_net_worth" in data_d["data"]
    assert "action_prescriptions" in data_d["data"]

    # 3. Proven prompts
    res_p = client.get("/skills/prompts/proven")
    assert res_p.status_code == 200
    data_p = res_p.json()
    assert data_p["data"]["total_prompts"] >= 5
