"""
tests/test_rrg_orderbook_convergence.py
───────────────────────────────────────
Unit tests for RRG Sector Momentum x Order-Book Convergence Engine.
"""

import pytest
from analysis.rrg_orderbook_convergence import (
    evaluate_rrg_orderbook_convergence,
    scan_rrg_orderbook_matrix,
)


def test_apex_convergence():
    rep = evaluate_rrg_orderbook_convergence("TITAGARH", rrg_quadrant_override="LEADING")
    assert rep.symbol == "TITAGARH"
    assert rep.book_to_bill_ratio >= 5.0
    assert rep.rrg_quadrant == "LEADING"
    assert rep.convergence_tier == "APEX_CONVERGENCE"
    assert rep.composite_conviction >= 90


def test_lagging_sector_dampening():
    rep = evaluate_rrg_orderbook_convergence("TITAGARH", rrg_quadrant_override="LAGGING")
    assert rep.rrg_quadrant == "LAGGING"
    # Still has strong order book, but convergence tier reflects micro only or lower score
    assert rep.composite_conviction < 85


def test_scan_rrg_orderbook_matrix():
    matrix = scan_rrg_orderbook_matrix()
    assert len(matrix) > 0
    scores = [m.composite_conviction for m in matrix]
    assert scores == sorted(scores, reverse=True)
