"""
tests/test_insider_radar.py
───────────────────────────
Unit tests for Promoter De-Pledging & Open-Market Insider Buying Engine.
"""

from analysis.insider_radar import (
    analyze_insider_activity,
    scan_insider_radar,
    CANONICAL_INSIDER_LEDGER,
)


def test_canonical_insider_titans():
    cg_rep = analyze_insider_activity("CGPOWER")
    assert cg_rep.symbol == "CGPOWER"
    assert cg_rep.de_pledging_status == "ZERO_PLEDGE_CLEAN"
    assert cg_rep.skin_in_the_game_score >= 90
    assert cg_rep.insider_buying_3m_cr > 0

    hbl_rep = analyze_insider_activity("HBLPOWER")
    assert hbl_rep.symbol == "HBLPOWER"
    assert hbl_rep.pledged_pct == 0.0
    assert hbl_rep.insider_buying_verdict == "AGGRESSIVE_INSIDER_BUYING"


def test_dynamic_insider_analysis():
    # Dangerous high pledge company
    bad_rep = analyze_insider_activity(
        "RISK_CO",
        promoter_holding_pct=40.0,
        pledged_pct=65.0,
        pledge_reduction_1y_pct=0.0,
        insider_buying_3m_cr=-5.0,
    )
    assert bad_rep.de_pledging_status == "DANGEROUS_HIGH_PLEDGE"
    assert bad_rep.skin_in_the_game_score < 40
    assert bad_rep.insider_buying_verdict == "INSIDER_SELLING"

    # Aggressive de-pledging turnaround
    turnaround_rep = analyze_insider_activity(
        "RECOVERY_CO",
        promoter_holding_pct=60.0,
        pledged_pct=15.0,
        pledge_reduction_1y_pct=25.0,
        insider_buying_3m_cr=12.0,
    )
    assert turnaround_rep.de_pledging_status == "AGGRESSIVE_DEPLEDGING"
    assert turnaround_rep.skin_in_the_game_score >= 80


def test_scan_insider_universe():
    radar = scan_insider_radar()
    assert len(radar) == len(CANONICAL_INSIDER_LEDGER)
    scores = [r.skin_in_the_game_score for r in radar]
    assert scores == sorted(scores, reverse=True)
