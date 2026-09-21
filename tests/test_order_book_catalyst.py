"""
tests/test_order_book_catalyst.py
─────────────────────────────────
Unit tests for SEBI Reg 30 Order-Inflow & Book-to-Bill Multiplier Engine.
"""

import pytest

from analysis.order_book_catalyst import (
    analyze_order_book_catalyst,
    parse_contract_announcement_text,
    get_top_order_book_titans,
    OrderBookReport,
)


def test_analyze_catalogued_titan():
    report = analyze_order_book_catalyst("MAZDOCK")
    assert isinstance(report, OrderBookReport)
    assert report.symbol == "MAZDOCK"
    assert report.book_to_bill_ratio >= 3.5
    assert report.operating_leverage_tier == "HYPER_EXPANSION"
    assert report.catalyst_verdict == "ORDER_BOOK_TITAN"
    assert report.revenue_runway_years >= 3.0
    assert len(report.insights) >= 2


def test_parse_contract_announcement_high_impact():
    filing_text = (
        "Mazagon Dock Shipbuilders has been awarded a major contract worth Rs. 4,500 Crore by the "
        "Ministry of Defence for construction of next-generation corvettes over 36 months."
    )
    contract = parse_contract_announcement_text(filing_text, annual_revenue_cr=9500.0)
    assert contract is not None
    assert contract.contract_value_cr == 4500.0
    assert contract.execution_months == 36
    assert contract.order_impact_ratio == pytest.approx(47.4, 0.1)
    assert contract.classification == "HIGH_IMPACT"


def test_parse_contract_announcement_transformative():
    filing_text = "Titagarh Rail Systems secures export order worth INR 2,200 Crores from European Rail Network."
    contract = parse_contract_announcement_text(filing_text, annual_revenue_cr=3900.0)
    assert contract is not None
    assert contract.contract_value_cr == 2200.0
    assert contract.order_impact_ratio >= 50.0
    assert contract.classification == "TRANSFORMATIVE"


def test_get_top_order_book_titans():
    titans = get_top_order_book_titans(min_book_to_bill=2.0)
    assert len(titans) >= 5
    # Must be sorted descending by book_to_bill_ratio
    for i in range(len(titans) - 1):
        assert titans[i].book_to_bill_ratio >= titans[i + 1].book_to_bill_ratio
