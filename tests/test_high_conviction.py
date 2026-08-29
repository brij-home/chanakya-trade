"""
tests/test_high_conviction.py
─────────────────────────────
Deterministic unit tests for high-conviction opportunity ranking engine.
"""

from unittest.mock import patch, MagicMock
import pandas as pd
import pytest

from analysis.high_conviction import (
    HighConvictionOpportunity,
    HighConvictionScanResult,
    _evaluate_single_stock,
    scan_high_conviction_opportunities,
)
from analysis.market_structure import MarketStructureReport
from analysis.multibagger import MultibaggerReport
from analysis.volume_profile import VolumeProfileReport
from analysis.forensic import ForensicAuditResult


@pytest.fixture
def fake_ohlcv_df():
    dates = pd.date_range("2025-01-01", periods=100, freq="D")
    closes = [100.0 + i * 1.5 for i in range(100)]
    return pd.DataFrame({
        "date": dates,
        "open": closes,
        "high": [c + 2.0 for c in closes],
        "low": [c - 2.0 for c in closes],
        "close": closes,
        "volume": [500000] * 100,
    })


def test_evaluate_single_stock_bullish_breakout():
    fake_ms = MarketStructureReport(
        symbol="TRENT",
        ltp=6500.0,
        regime="BULLISH",
        structure_score=85,
        setup_type="BREAKOUT_EXPANSION",
        setup_confidence=90,
        invalidation_level=6250.0,
        target_1=7000.0,
        target_2=7500.0,
    )
    fake_vp = VolumeProfileReport(
        symbol="TRENT",
        ltp=6500.0,
        rvol_20d=2.4,
        rvol_50d=2.1,
        volume_tier="HIGH",
        footprint_bias="ACCUMULATION",
        footprint_score=80,
        poc_price=6400.0,
        vah_price=6550.0,
        val_price=6300.0,
        price_vs_value_area="INSIDE_VALUE_AREA",
    )
    fake_mb = MultibaggerReport(
        symbol="TRENT",
        ltp=6500.0,
        multibagger_score=92,
        category="STAGE_2_SUPERPERFORMER",
        trend_template_passed=8,
        trend_template_qualified=True,
        weinstein_stage="STAGE_2_MARKUP",
        vcp_detected=True,
    )
    fake_forensic = ForensicAuditResult(
        symbol="TRENT",
        beneish_m_score=-2.5,
        is_manipulator_risk=False,
        altman_z_score=4.2,
        distress_zone="SAFE",
        piotroski_f_score=8,
        quality_rating="A+",
    )

    with (
        patch("analysis.high_conviction.analyze_market_structure", return_value=fake_ms),
        patch("analysis.high_conviction.analyze_volume_profile", return_value=fake_vp),
        patch("analysis.high_conviction.scan_multibagger_opportunity", return_value=fake_mb),
        patch("analysis.high_conviction.audit_forensics", return_value=fake_forensic),
        patch(
            "analysis.high_conviction.get_stock_sector_alignment",
            return_value={"sector": "Retail", "tailwind_score": 85, "quadrant": "LEADING"},
        ),
    ):
        opp = _evaluate_single_stock("TRENT")
        assert opp is not None
        assert opp.symbol == "TRENT"
        assert opp.conviction_score >= 80
        assert opp.setup_type == "VCP_CONTRACTION"
        assert opp.trade_bias == "LONG"
        assert opp.risk_reward_ratio >= 1.5


def test_scan_high_conviction_opportunities_sorting():
    opp1 = HighConvictionOpportunity(
        rank=0,
        symbol="TRENT",
        sector="Retail",
        ltp=6500.0,
        conviction_score=95,
        setup_type="VCP_CONTRACTION",
        setup_title="⚡ VCP Contraction",
        trade_bias="LONG",
        entry_price=6500.0,
        stop_loss=6250.0,
        target_1=7000.0,
        target_2=7500.0,
        risk_reward_ratio=2.0,
        risk_pts=250.0,
        reward_pts=500.0,
        catalyst_summary="Stage 2 Superperformer",
        structure_regime="BULLISH",
        weinstein_stage="STAGE_2_MARKUP",
        trend_template_passed=8,
        rvol_20d=2.4,
        vcp_detected=True,
        forensic_quality="A+",
    )
    opp2 = HighConvictionOpportunity(
        rank=0,
        symbol="INFY",
        sector="IT",
        ltp=1800.0,
        conviction_score=82,
        setup_type="PULLBACK_DEMAND_OB",
        setup_title="🎯 Pullback to Demand",
        trade_bias="LONG",
        entry_price=1800.0,
        stop_loss=1740.0,
        target_1=1920.0,
        target_2=2000.0,
        risk_reward_ratio=2.0,
        risk_pts=60.0,
        reward_pts=120.0,
        catalyst_summary="Pullback to Demand OB",
        structure_regime="BULLISH",
        weinstein_stage="STAGE_2_MARKUP",
        trend_template_passed=7,
        rvol_20d=1.6,
        vcp_detected=False,
        forensic_quality="A+",
    )

    with (
        patch("analysis.high_conviction._evaluate_single_stock", side_effect=[opp1, opp2]),
        patch(
            "analysis.high_conviction.get_sector_rrg_matrix",
            return_value={"leading": [{"sector": "Retail"}, {"sector": "IT"}]},
        ),
    ):
        result = scan_high_conviction_opportunities(
            universe=["TRENT", "INFY"],
            top_n=2,
            use_cache=False,
        )

        assert len(result.opportunities) == 2
        assert result.opportunities[0].symbol == "TRENT"
        assert result.opportunities[0].rank == 1
        assert result.opportunities[1].symbol == "INFY"
        assert result.opportunities[1].rank == 2
        assert result.market_posture == "BULLISH_EXPANSION"
