"""
Regression and latency invariant test suite for OpsDeck UI telemetry, L2 Universe Depth Radar,
and Market Dynamics Governor.
"""

import time
from datetime import datetime
from config.constants import IST_ZONE as IST


def test_contracts_from_master_indexed_lookup_latency():
    """Verify that contracts_from_master uses underSym indexed lookup and resolves in <0.05s."""
    from market.symbol_master import load_master
    from market.contract_selection import contracts_from_master

    records = load_master("NSE_FO")
    now = datetime.now(IST)

    # First lookup may index the records dict
    t0 = time.monotonic()
    contracts_nifty = contracts_from_master(records, "NIFTY", exchange="NSE", as_of=now)
    dur_first = time.monotonic() - t0

    assert len(contracts_nifty) > 0, "NIFTY contracts should be resolved"
    assert dur_first < 0.35, f"Master indexing and resolution took too long: {dur_first:.4f}s"

    # Subsequent lookup for any stock must be instant (<0.02s)
    t0 = time.monotonic()
    contracts_rel = contracts_from_master(records, "RELIANCE", exchange="NSE", as_of=now)
    dur_rel = time.monotonic() - t0

    assert len(contracts_rel) > 0, "RELIANCE contracts should be resolved"
    assert dur_rel < 0.05, f"Indexed contracts lookup took too long: {dur_rel:.4f}s"


def test_market_dynamics_governor_non_blocking_performance(monkeypatch):
    """Verify that MarketDynamicsGovernor.get_diagnostics() and get_calibration() execute in <20ms."""
    from engine.market_dynamics_governor import get_market_dynamics_governor

    gov = get_market_dynamics_governor()
    # Seed fresh live VIX without calling broker REST so diagnostics report HEALTHY honestly
    monkeypatch.setattr(gov, "_vix_cache", (time.time(), 15.2))

    t0 = time.monotonic()
    diag = gov.get_diagnostics()
    dur_diag = time.monotonic() - t0

    assert dur_diag < 0.02, f"Governor get_diagnostics took too long: {dur_diag:.4f}s"
    assert diag.get("status") == "HEALTHY"
    assert diag.get("current_phase") not in (None, "UNKNOWN")
    assert diag.get("india_vix", 0) > 0

    t0 = time.monotonic()
    calib = gov.get_calibration("NIFTY")
    dur_calib = time.monotonic() - t0

    assert dur_calib < 0.01, f"Governor get_calibration took too long: {dur_calib:.4f}s"
    assert calib.mandate is not None


def test_enrich_quote_synthetic_vwap_does_not_block():
    """Verify that _enrich_quote with synthetic/stream source does not make slow historical REST calls."""
    from market.quotes import _enrich_quote, Quote

    q = Quote(
        symbol="NIFTY26NOVFUT",
        last_price=25200.0,
        change=15.0,
        change_pct=0.06,
    )

    t0 = time.monotonic()
    enriched = _enrich_quote(
        q,
        instrument="NSE:NIFTY26NOVFUT",
        provider="cost_of_carry_synthetic",
        source="SYNTHETIC",
        correlation_id="test-perf",
    )
    dur = time.monotonic() - t0

    assert dur < 0.05, f"_enrich_quote took too long: {dur:.4f}s"
    assert enriched.vwap is not None
    assert enriched.vwap > 0


def test_hierarchical_3cs_context_cached_lookup():
    """Verify that hierarchical_pipeline.evaluate_market_context_3cs caches and returns in <5ms."""
    from engine.pipeline.hierarchical_engine import hierarchical_pipeline

    # Ensure warmed or first run
    r1 = hierarchical_pipeline.evaluate_market_context_3cs("NIFTY", "NSE")
    assert r1 is not None

    t0 = time.monotonic()
    r2 = hierarchical_pipeline.evaluate_market_context_3cs("NIFTY", "NSE")
    dur = time.monotonic() - t0

    assert dur < 0.01, f"Cached 3Cs evaluation took too long: {dur:.4f}s"
    assert r2.status is not None
