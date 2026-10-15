"""
tests/test_mtscm.py
───────────────────
Unit tests for Universal Multi-Timeframe Structural Confluence Matrix (MTSCM 3-Tier Score).
"""

from engine.mtscm import evaluate_mtscm


def test_mtscm_apex_confluence_full_alignment():
    """Verify that flawless 3-tier multi-timeframe alignment earns APEX_CONFLUENCE tier."""
    metrics = {
        "daily_200_ema": 2800.0,
        "daily_50_ema": 2900.0,
        "htf_bos": True,
        "market_structure": "BULLISH_EXPANSION",
        "sector_rrg_phase": "LEADING",
        "order_block": True,
        "fvg": True,
        "d_poc": 2980.0,
        "poc_migration": "ASCENDING",
        "squeeze_state": "SQUEEZE_FIRED",
        "cvd_ratio": 2.4,
        "vwap": 2990.0,
        "total_buy_qty": 300000,
        "total_sell_qty": 120000,
    }
    result = evaluate_mtscm(symbol="RELIANCE", ltp=3020.0, direction="BULLISH", metrics=metrics)

    assert result.tier == "APEX_CONFLUENCE"
    assert result.total_score >= 85.0
    assert result.lot_multiplier == 1.25
    assert len(result.headwinds) == 0
    assert len(result.confluences) >= 6


def test_mtscm_defensive_veto_on_timeframe_conflict():
    """Verify that trading against HTF moving average and market structure triggers DEFENSIVE_VETO."""
    metrics = {
        "daily_200_ema": 3100.0,  # Trading below 200 EMA!
        "market_structure": "BEARISH_LIQUIDATION",  # HTF bearish conflict
        "sector_rrg_phase": "LAGGING",  # Sector headwind
        "poc_migration": "DESCENDING",  # Developing POC migrating lower
        "cvd_ratio": 0.45,  # Seller delta dominance
        "vwap": 3030.0,  # Below VWAP!
    }
    result = evaluate_mtscm(symbol="RELIANCE", ltp=3000.0, direction="BULLISH", metrics=metrics)

    assert result.tier == "DEFENSIVE_VETO"
    assert result.total_score < 70.0
    assert result.lot_multiplier == 0.65
    assert len(result.headwinds) >= 3


def test_mtscm_strategic_momentum_tier():
    """Verify standard momentum setup without headwinds qualifies for STRATEGIC_MOMENTUM."""
    metrics = {
        "daily_200_ema": 2800.0,
        "market_structure": "BULLISH_EXPANSION",
        "order_block": True,
        "d_poc": 2950.0,
        "poc_migration": "STABLE",
        "cvd_ratio": 1.5,
        "vwap": 2980.0,
    }
    result = evaluate_mtscm(symbol="TCS", ltp=3000.0, direction="BULLISH", metrics=metrics)

    assert result.tier == "STRATEGIC_MOMENTUM"
    assert result.total_score >= 65.0
    assert result.lot_multiplier == 1.00
    assert len(result.headwinds) == 0
