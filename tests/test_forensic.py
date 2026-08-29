"""
tests/test_forensic.py
───────────────────────
Unit tests for Forensic accounting, Beneish M-Score, Altman Z-Score, and Piotroski F-Score.
"""

from __future__ import annotations

import pytest
from analysis.forensic import (
    ForensicAuditResult,
    audit_forensics,
    compute_altman_z_score,
    compute_beneish_m_score,
    compute_piotroski_f_score,
)


class TestBeneishMScore:
    def test_clean_financials_low_manipulation_risk(self):
        # Baseline neutral ratios
        m = compute_beneish_m_score(
            dsri=1.0, gmi=1.0, aqi=1.0, sgi=1.0, depi=1.0, sgai=1.0, lvgi=1.0, tata=0.0
        )
        assert m < -1.78

    def test_aggressive_accruals_flags_manipulation(self):
        # High receivables growth, high sales growth, high accruals
        m = compute_beneish_m_score(
            dsri=2.5, gmi=1.8, aqi=1.6, sgi=2.0, depi=1.2, sgai=1.5, lvgi=1.8, tata=0.35
        )
        assert m > -1.78


class TestAltmanZScore:
    def test_safe_zone(self):
        z, zone = compute_altman_z_score(
            working_capital=500.0,
            total_assets=1000.0,
            retained_earnings=400.0,
            ebit=200.0,
            book_value_equity=700.0,
            total_liabilities=300.0,
        )
        assert z > 2.60
        assert zone == "SAFE"

    def test_distress_zone(self):
        z, zone = compute_altman_z_score(
            working_capital=-200.0,
            total_assets=1000.0,
            retained_earnings=-300.0,
            ebit=-50.0,
            book_value_equity=100.0,
            total_liabilities=900.0,
        )
        assert z < 1.10
        assert zone == "DISTRESS"


class TestPiotroskiScore:
    def test_high_quality_data(self):
        data = {
            "roe": 22.0,
            "free_cash_flow": 500.0,
            "npm": 18.0,
            "profit_growth": 15.0,
            "debt_equity": 0.2,
            "current_ratio": 1.8,
            "pledged_pct": 0.0,
            "sales_growth": 12.0,
            "roce": 25.0,
        }
        score, checks = compute_piotroski_f_score(data)
        assert score >= 8
        assert len(checks) >= 8

    def test_weak_data(self):
        data = {
            "roe": -5.0,
            "free_cash_flow": -100.0,
            "npm": -2.0,
            "profit_growth": -20.0,
            "debt_equity": 3.5,
            "current_ratio": 0.8,
            "pledged_pct": 45.0,
            "sales_growth": -10.0,
            "roce": 3.0,
        }
        score, checks = compute_piotroski_f_score(data)
        assert score <= 3


class TestForensicAuditFull:
    def test_audit_forensics_returns_result(self):
        synthetic_data = {
            "roe": 18.0,
            "roce": 22.0,
            "npm": 14.0,
            "sales_growth": 10.0,
            "profit_growth": 12.0,
            "debt_equity": 0.3,
            "current_ratio": 1.5,
            "interest_coverage": 8.0,
            "free_cash_flow": 200.0,
            "promoter_holding": 52.0,
            "pledged_pct": 0.0,
            "market_cap": 50000.0,
        }
        res = audit_forensics("INFY", data=synthetic_data, use_cache=False)
        assert isinstance(res, ForensicAuditResult)
        assert res.symbol == "INFY"
        assert res.quality_rating in ("A+", "A", "B", "C", "D")
        assert res.distress_zone in ("SAFE", "GREY", "DISTRESS")
        assert 0 <= res.piotroski_f_score <= 9
        assert isinstance(res.governance_red_flags, list)
        assert len(res.summary_text) > 10

    def test_result_as_dict(self):
        synthetic_data = {
            "roe": 20.0,
            "roce": 24.0,
            "npm": 16.0,
            "sales_growth": 15.0,
            "profit_growth": 18.0,
            "debt_equity": 0.4,
            "current_ratio": 1.4,
            "interest_coverage": 6.0,
            "free_cash_flow": 800.0,
            "promoter_holding": 50.0,
            "pledged_pct": 2.0,
            "market_cap": 150000.0,
        }
        res = audit_forensics("RELIANCE", data=synthetic_data, use_cache=False)
        d = res.as_dict()
        assert "beneish_m_score" in d
        assert "altman_z_score" in d
        assert "piotroski_f_score" in d
        assert "quality_rating" in d
