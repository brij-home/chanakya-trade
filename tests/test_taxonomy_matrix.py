"""
tests/test_taxonomy_matrix.py
───────────────────────────────
Holistic Multi-Asset Cross-Taxonomy Matrix Test Suite.

Ensures that all asset classes (Equities, Commodities, Forex, Indices, ETFs, Derivatives)
are resolved, normalized at API ingress, analyzed by quantitative engines, and formatted
without fallback leakage across the entire ChanakyaTrade stack.
"""

import pytest
from analysis.universe import normalize_symbol_exchange
from web.skills import (
    AnalyzeRequest,
    SymbolRequest,
    BacktestRequest,
    AlertAddRequest,
    HistoryRequest,
)
from agent.tools import build_registry
from analysis.pipeline import run_analysis_pipeline


# ── 1. Ingress Normalization Tests ──────────────────────────────────────────


@pytest.mark.parametrize(
    "raw_sym,raw_exch,expected_sym,expected_exch",
    [
        ("GOLD", "NSE", "GOLD", "MCX"),
        ("gold", "", "GOLD", "MCX"),
        ("MCX:GOLD", "NSE", "GOLD", "MCX"),
        ("CRUDEOIL", "NSE", "CRUDEOIL", "MCX"),
        ("crudeoilm", "NSE", "CRUDEOILM", "MCX"),
        ("SILVER", "NSE", "SILVER", "MCX"),
        ("NATURALGAS", "NSE", "NATURALGAS", "MCX"),
        ("COPPER", "NSE", "COPPER", "MCX"),
        ("USDINR", "NSE", "USDINR", "CDS"),
        ("usdinr", "", "USDINR", "CDS"),
        ("EURINR", "NSE", "EURINR", "CDS"),
        ("SENSEX", "NSE", "SENSEX", "BSE"),
        ("BANKEX", "NSE", "BANKEX", "BSE"),
        ("RELIANCE", "NSE", "RELIANCE", "NSE"),
        ("reliance", "", "RELIANCE", "NSE"),
        ("TCS", "NSE", "TCS", "NSE"),
        ("NIFTY50", "NSE", "NIFTY50", "NSE"),
        ("GOLDBEES", "NSE", "GOLDBEES", "NSE"),
        ("BAJAJ_AUTO", "NSE", "BAJAJ-AUTO", "NSE"),
    ],
)
def test_normalize_symbol_exchange_matrix(raw_sym, raw_exch, expected_sym, expected_exch):
    sym, exch = normalize_symbol_exchange(raw_sym, raw_exch)
    assert sym == expected_sym
    assert exch == expected_exch


# ── 2. Pydantic Ingress Boundary Request Normalization ──────────────────────


@pytest.mark.parametrize(
    "model_cls",
    [SymbolRequest, AnalyzeRequest, BacktestRequest, AlertAddRequest, HistoryRequest],
)
def test_pydantic_ingress_boundary_normalizes_exchange(model_cls):
    # Pass 'GOLD' with default exchange 'NSE'
    req = model_cls(symbol="GOLD")
    assert req.symbol == "GOLD"
    assert req.exchange == "MCX"

    # Pass 'CRUDEOIL' with explicit 'NSE'
    req2 = model_cls(symbol="CRUDEOIL", exchange="NSE")
    assert req2.symbol == "CRUDEOIL"
    assert req2.exchange == "MCX"

    # Pass 'USDINR'
    req3 = model_cls(symbol="USDINR")
    assert req3.symbol == "USDINR"
    assert req3.exchange == "CDS"

    # Pass 'SENSEX'
    req4 = model_cls(symbol="SENSEX")
    assert req4.symbol == "SENSEX"
    assert req4.exchange == "BSE"

    # Pass 'RELIANCE'
    req5 = model_cls(symbol="RELIANCE")
    assert req5.symbol == "RELIANCE"
    assert req5.exchange == "NSE"


# ── 3. Multi-Asset Fundamental Analyst Execution ────────────────────────────


def test_fundamental_analyst_macro_commodity_models():
    registry = build_registry()

    # Commodity (CRUDEOIL)
    ctx_crude = run_analysis_pipeline("CRUDEOIL", "MCX", registry, parallel=False)
    fund_crude = next(r for r in ctx_crude.reports if r.analyst == "Fundamental")
    assert fund_crude.verdict == "NEUTRAL"
    assert fund_crude.confidence >= 50
    assert any("Crude Oil" in pt for pt in fund_crude.key_points)

    # Bullion (GOLD)
    ctx_gold = run_analysis_pipeline("GOLD", "MCX", registry, parallel=False)
    fund_gold = next(r for r in ctx_gold.reports if r.analyst == "Fundamental")
    assert fund_gold.verdict == "NEUTRAL"
    assert any("Gold Bullion" in pt for pt in fund_gold.key_points)

    # Forex (USDINR)
    ctx_usd = run_analysis_pipeline("USDINR", "CDS", registry, parallel=False)
    fund_usd = next(r for r in ctx_usd.reports if r.analyst == "Fundamental")
    assert fund_usd.verdict == "NEUTRAL"
    assert any("Currency Derivative" in pt for pt in fund_usd.key_points)

    # Benchmark Index (NIFTY 50)
    ctx_nifty = run_analysis_pipeline("NIFTY50", "NSE", registry, parallel=False)
    fund_nifty = next(r for r in ctx_nifty.reports if r.analyst == "Fundamental")
    assert fund_nifty.verdict == "NEUTRAL"
    assert any("Benchmark Index" in pt for pt in fund_nifty.key_points)
