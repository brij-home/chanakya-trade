"""
tests/test_active_market_readiness.py
──────────────────────────────────────
Verification suite for Active Market Data Ingestion & Derivations:
  1. Options Contract Canonical Lot Size Invariants (Zero hardcoded 50 fallback)
  2. Benchmark Daily Levels On-Demand Computation (compute_if_missing=True)
  3. Pre-market Priming Session Date Overrides (Weekend/Pre-open readiness)
"""

from __future__ import annotations

from brokers.base import OptionsContract
from market.options import enrich_options_chain_deltas
from engine.data_sync_scheduler import DataSyncScheduler
from engine.daily_levels import get_daily_levels_store


def test_fyers_options_chain_contract_lot_size():
    """Verify that Fyers option contract lot sizes resolve to canonical exchange masters, never default 50."""
    from brokers.fyers import _get_fyers_contract_lot_size

    # Key Index Contracts
    assert _get_fyers_contract_lot_size("NSE:NIFTY26N1724150CE", "NIFTY") == 65
    assert _get_fyers_contract_lot_size("NSE:BANKNIFTY26NOV59000PE", "BANKNIFTY") == 30
    assert _get_fyers_contract_lot_size("BSE:SENSEX26NOV82000CE", "SENSEX") == 20

    # Stock F&O
    assert _get_fyers_contract_lot_size("NSE:RELIANCE26NOV1340CE", "RELIANCE") == 500
    assert _get_fyers_contract_lot_size("NSE:TCS26NOV4200CE", "TCS") == 225


def test_market_options_enrichment_canonical_lot_size():
    """Verify that enrich_options_chain_deltas audits and replaces flawed broker lot sizes."""
    flawed_contracts = [
        OptionsContract(
            symbol="NSE:BANKNIFTY26NOV59000PE",
            underlying="BANKNIFTY",
            expiry="2026-11-26",
            strike=59000.0,
            option_type="PE",
            last_price=120.0,
            oi=10000,
            oi_change=0,
            volume=500,
            lot_size=50,  # Flawed broker value
        ),
        OptionsContract(
            symbol="NSE:NIFTY26N1724150CE",
            underlying="NIFTY",
            expiry="2026-11-17",
            strike=24150.0,
            option_type="CE",
            last_price=350.0,
            oi=25000,
            oi_change=0,
            volume=1500,
            lot_size=50,  # Flawed broker value
        ),
    ]

    enriched = enrich_options_chain_deltas(flawed_contracts, "BANKNIFTY")
    assert enriched[0].lot_size == 30, (
        f"BANKNIFTY lot size should be 30, got {enriched[0].lot_size}"
    )
    assert enriched[1].lot_size == 65, f"NIFTY lot size should be 65, got {enriched[1].lot_size}"


import pandas as pd
import pytest


def test_benchmark_daily_levels_compute_if_missing(monkeypatch: pytest.MonkeyPatch):
    """Verify that DailyLevelsStore computes missing benchmark levels deterministically."""
    mock_df = pd.DataFrame(
        [
            {"open": 24500, "high": 24700, "low": 24400, "close": 24600, "volume": 1000},
            {"open": 24650, "high": 25000, "low": 24600, "close": 24800, "volume": 1500},
        ],
        index=pd.to_datetime(["2026-11-13", "2026-11-14"]),
    )
    monkeypatch.setattr("market.history.get_ohlcv", lambda *a, **k: mock_df)
    monkeypatch.setattr("market.quotes.get_quote", lambda *a, **k: {})

    store = get_daily_levels_store()
    levels = store.get_levels("NIFTY", session_date="2026-11-16", compute_if_missing=True)
    assert levels is not None
    assert levels.symbol == "NIFTY"
    assert levels.pdh > 0
    assert levels.pdl > 0
    assert levels.cpr is not None
    assert "pivot" in levels.cpr
    assert levels.camarilla is not None
    assert "h3" in levels.camarilla
    assert "l3" in levels.camarilla


def test_data_sync_scheduler_premarket_session_override(monkeypatch: pytest.MonkeyPatch):
    """Verify sync_premarket_levels accepts an explicit target session date when forced on weekends."""
    mock_df = pd.DataFrame(
        [
            {"open": 24500, "high": 24700, "low": 24400, "close": 24600, "volume": 1000},
            {"open": 24650, "high": 25000, "low": 24600, "close": 24800, "volume": 1500},
        ],
        index=pd.to_datetime(["2026-11-13", "2026-11-14"]),
    )
    monkeypatch.setattr("market.history.get_ohlcv", lambda *a, **k: mock_df)
    monkeypatch.setattr("market.quotes.get_quote", lambda *a, **k: {})

    scheduler = DataSyncScheduler()
    res = scheduler.sync_premarket_levels(force=True, session_date="2026-11-16")
    assert res["status"] == "COMPLETED"
    assert res["session_date"] == "2026-11-16"
    assert res["primed_count"] > 0
    assert res["indices_count"] == 5


def test_oc_manager_index_protection_and_subscription_lifecycle():
    """Verify that OptionsChainManager protects index benchmarks and supports dynamic stock subscriptions."""
    from market.oc_manager import get_oc_manager, _DEFAULT_INDEX_SUBSCRIPTIONS

    ocm = get_oc_manager()
    # Permanent index subscriptions must be present
    for idx in _DEFAULT_INDEX_SUBSCRIPTIONS:
        assert idx in ocm.subscribed_symbols

    # Subscribing stock F&O candidate
    ocm.subscribe("RELIANCE")
    assert "RELIANCE" in ocm.subscribed_symbols

    # Attempting to unsubscribe protected index should be a no-op
    ocm.unsubscribe("NIFTY")
    assert "NIFTY" in ocm.subscribed_symbols

    # Unsubscribing stock F&O should succeed
    ocm.unsubscribe("RELIANCE")
    assert "RELIANCE" not in ocm.subscribed_symbols


def test_skill_gex_snapshot_enrichment_keys(monkeypatch):
    """Verify that skill_gex_snapshot enriches option chain rows with live LTP, symbols, and deltas."""
    import asyncio
    from brokers.base import OptionsContract, Quote
    from web.skills import skill_gex_snapshot

    sample_contracts = [
        OptionsContract(
            symbol="NSE:NIFTY26N1725150CE",
            underlying="NIFTY",
            expiry="2026-11-17",
            strike=25150.0,
            option_type="CE",
            last_price=137.75,
            oi=25000,
            oi_change=1200,
            volume=5000,
            delta=0.50,
            theta=-2.5,
            bid=137.0,
            ask=138.5,
            lot_size=65,
        ),
        OptionsContract(
            symbol="NSE:NIFTY26N1725150PE",
            underlying="NIFTY",
            expiry="2026-11-17",
            strike=25150.0,
            option_type="PE",
            last_price=136.6,
            oi=28000,
            oi_change=850,
            volume=4800,
            delta=-0.50,
            theta=-2.5,
            bid=136.0,
            ask=137.2,
            lot_size=65,
        ),
    ]
    sample_quote = Quote(
        symbol="NIFTY",
        last_price=25150.0,
        change=50.0,
        change_pct=0.2,
        open=25100.0,
        high=25200.0,
        low=25080.0,
        volume=100000,
    )

    def mock_fetch(clean_sym, norm_inst, req_exp):
        return (
            sample_quote,
            sample_contracts,
            25150.0,
            ["2026-11-17"],
            {
                "provider": "fyers",
                "source": "BROKER_REST",
                "is_realtime": True,
                "is_market_open": True,
            },
        )

    monkeypatch.setattr("web.skills._fetch_options_and_spot", mock_fetch)

    res = asyncio.run(skill_gex_snapshot(underlying="NIFTY"))
    assert isinstance(res, dict)
    data = res.get("data", {})
    assert data.get("underlying") == "NIFTY"
    assert (data.get("delta_hedge") or {}).get("lot_size") == 65
    rows = data.get("options_chain", [])
    assert len(rows) > 0
    sample = rows[0]
    assert sample.get("calls_ltp") == 137.75
    assert sample.get("puts_ltp") == 136.6
    assert sample.get("calls_symbol") == "NSE:NIFTY26N1725150CE"
    assert sample.get("puts_symbol") == "NSE:NIFTY26N1725150PE"
    assert sample.get("calls_delta") == 0.5
    assert sample.get("puts_delta") == -0.5
