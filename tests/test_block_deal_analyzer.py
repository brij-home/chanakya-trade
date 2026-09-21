"""
tests/test_block_deal_analyzer.py
─────────────────────────────────
Unit tests for Institutional Block Deal Absorption vs Distribution Anchoring.
"""

import pytest

from analysis.block_deal_analyzer import analyze_block_deal_absorption, BlockDealAbsorptionReport
from market.bulk_deals import Deal


def test_block_deal_absorption_above_vwap():
    deals = [
        Deal(
            date="2026-09-18",
            symbol="TRENT",
            client="GOLDMAN SACHS INDIA",
            deal_type="BUY",
            quantity=100_000,
            price=7000.0,
            entity_type="FII",
            deal_class="BLOCK",
        ),
        Deal(
            date="2026-09-18",
            symbol="TRENT",
            client="HDFC MUTUAL FUND",
            deal_type="BUY",
            quantity=150_000,
            price=7050.0,
            entity_type="MF",
            deal_class="BLOCK",
        ),
    ]

    # Current price 7200 is above VWAP (~7030) -> Absorption!
    report = analyze_block_deal_absorption("TRENT", current_price=7200.0, deals_list=deals)
    assert isinstance(report, BlockDealAbsorptionReport)
    assert report.symbol == "TRENT"
    assert report.status == "INSTITUTIONAL_ABSORPTION"
    assert report.vwap_institutional_buy_price == pytest.approx(7030.0, 1.0)
    assert report.support_anchor_price == pytest.approx(7030.0, 1.0)
    assert report.deal_count == 2
    assert len(report.insights) >= 2


def test_block_deal_breakdown_below_vwap():
    deals = [
        Deal(
            date="2026-09-15",
            symbol="ABC",
            client="MORGAN STANLEY",
            deal_type="BUY",
            quantity=50_000,
            price=1000.0,
            entity_type="FII",
            deal_class="BLOCK",
        ),
    ]

    # Current price 940 is cracked -6% below 1000 -> Distribution Breakdown!
    report = analyze_block_deal_absorption("ABC", current_price=940.0, deals_list=deals)
    assert report.symbol == "ABC"
    assert report.status == "DISTRIBUTION_BREAKDOWN"
    assert report.vwap_institutional_buy_price == 1000.0


def test_block_deal_empty_deals():
    report = analyze_block_deal_absorption("XYZ", current_price=500.0, deals_list=[])
    assert report.symbol == "XYZ"
    assert report.status == "NO_RECENT_BLOCKS"
    assert report.support_anchor_price is None
