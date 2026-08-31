"""
Unit tests for analysis/whale_tracker.py
Deterministic testing of Indian Marquee Whale Tracker.
"""

from analysis.whale_tracker import get_whale_flows, MARQUEE_INVESTORS


def test_whale_flows_retrieval():
    res = get_whale_flows()
    assert res["status"] == "success"
    assert res["total_deals"] >= 5
    assert len(res["deals"]) >= 5
    assert res["total_capital_deployed_cr"] > 100.0
    assert len(res["marquee_investors"]) == len(MARQUEE_INVESTORS)

    # Verify deal structure
    first_deal = res["deals"][0]
    assert "symbol" in first_deal
    assert "investor_name" in first_deal
    assert "deal_value_cr" in first_deal
    assert "gain_pct_since_deal" in first_deal
    assert "pnl_status" in first_deal


def test_whale_flows_filtering():
    # Filter by investor
    res_kacholia = get_whale_flows(investor_filter="Kacholia")
    for d in res_kacholia["deals"]:
        assert "Kacholia" in d["investor_name"]

    # Filter by min deal value
    res_large = get_whale_flows(min_deal_cr=40.0)
    for d in res_large["deals"]:
        assert d["deal_value_cr"] >= 40.0
