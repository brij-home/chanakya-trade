"""
tests/test_institutional_convergence.py
───────────────────────────────────────
Unit tests for Master Institutional Edge Convergence Matrix (All 6 Pillars).
"""

import pytest
from analysis.institutional_convergence import (
    evaluate_master_institutional_convergence,
    scan_master_institutional_radar,
)


def test_master_convergence_titagarh():
    rep = evaluate_master_institutional_convergence("TITAGARH", ltp=1250.0)
    assert rep.symbol == "TITAGARH"
    assert 0 <= rep.composite_institutional_score <= 100
    assert 0 <= rep.active_pillars_count <= 6
    assert rep.order_book_score >= 80
    assert rep.institutional_tier in (
        "APEX_INSTITUTIONAL_CONVERGENCE",
        "HIGH_INSTITUTIONAL_CONVERGENCE",
        "SELECTIVE_PILLAR_EDGE",
    )


def test_master_convergence_dixon():
    rep = evaluate_master_institutional_convergence("DIXON", ltp=13500.0)
    assert rep.symbol == "DIXON"
    assert rep.capex_inflection_score >= 80
    assert rep.insider_skin_score >= 80
    assert rep.active_pillars_count >= 2


def test_scan_master_institutional_radar():
    radar = scan_master_institutional_radar()
    assert len(radar) > 5
    # The top ranked stocks should have multiple active pillars firing
    assert radar[0].active_pillars_count >= 3
    assert radar[0].composite_institutional_score >= 70
