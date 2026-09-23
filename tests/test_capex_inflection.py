"""
tests/test_capex_inflection.py
───────────────────────────────
Unit tests for Capex & CWIP-to-Gross-Block Inflection Engine.
"""

from analysis.capex_inflection import (
    analyze_capex_inflection,
    scan_capex_inflection_universe,
    CANONICAL_CAPEX_TITANS,
)


def test_canonical_capex_titans():
    dixon_rep = analyze_capex_inflection("DIXON")
    assert dixon_rep.symbol == "DIXON"
    assert dixon_rep.inflection_tier == "CAPEX_INFLECTION_TITAN"
    assert dixon_rep.conviction_score >= 90
    assert dixon_rep.debt_to_equity < 0.5
    assert dixon_rep.capacity_utilization_pct > 75.0


def test_dynamic_capex_inflection():
    # Healthy expanding company
    rep = analyze_capex_inflection(
        "CUSTOM_CO",
        gross_block_cr=500.0,
        cwip_cr=150.0,
        revenue_cr=1600.0,
        debt_equity=0.2,
    )
    assert rep.symbol == "CUSTOM_CO"
    assert rep.cwip_to_gross_block_pct == 30.0
    assert rep.inflection_tier == "CAPEX_INFLECTION_TITAN"
    assert rep.conviction_score >= 80

    # Overleveraged company
    bad_rep = analyze_capex_inflection(
        "DEBT_CO",
        gross_block_cr=500.0,
        cwip_cr=10.0,
        revenue_cr=300.0,
        debt_equity=1.8,
    )
    assert bad_rep.inflection_tier == "DEBT_CONSTRAINED"
    assert bad_rep.conviction_score < 60


def test_scan_capex_universe():
    titans = scan_capex_inflection_universe()
    assert len(titans) == len(CANONICAL_CAPEX_TITANS)
    # Check sorted descending by conviction score
    scores = [t.conviction_score for t in titans]
    assert scores == sorted(scores, reverse=True)
