"""
tests/test_multi_regime_intelligence.py
Unit tests verifying the multi-regime dynamic intelligence architecture:
1. Wyckoff Spring Reversal override in Smart Funnel Stage 1.
2. Telecom & Capital-Intensive forensic normalization.
3. Heavyweight Tug-of-War index polarization detector.
4. Low-VIX regime-adaptive defined-risk spread formulation.
5. 24-hour dead ticker 404 negative cache.
"""

import pytest
from unittest.mock import MagicMock, patch

from agent.smart_funnel import SmartFunnel, PreFilterReport
from analysis.forensic import audit_forensics, ForensicAuditResult
from market.indices import (
    IndexPolarization,
    get_index_polarization,
    MarketSnapshot,
    IndexSnapshot,
)
from market.yfinance_provider import _DEAD_TICKER_CACHE, yf_get_quote
from engine.asymmetric_radar import AsymmetricOpportunityRadar


def test_wyckoff_spring_stage1_qualification():
    """Verify that a stock emerging from an oversold condition with an intraday volume surge qualifies via Wyckoff Spring."""
    funnel = SmartFunnel(verbose=False)
    
    mock_reg = MagicMock()
    # Simulates an oversold stock like HDFC Bank prior to bounce (RSI 29, EMA20 < EMA50)
    mock_reg.execute.side_effect = lambda tool, args: {
        "technical_analyse": {
            "ltp": 731.0,
            "rsi": 29.5,
            "ema20": 715.0,
            "ema50": 735.0,
            "sma200": 780.0,
            "macd_hist": 1.2,
            "volume_ratio": 1.8,
        },
        "fundamental_analyse": {
            "pe": 18.5,
            "roe": 17.5,
            "debt_equity": 0.5,
            "free_cash_flow": 25000.0,
        },
    }.get(tool, {})
    
    funnel._registry = mock_reg
    
    # Mock quote with +2.5% intraday surge
    mock_quote = MagicMock()
    mock_quote.last_price = 731.0
    mock_quote.change_pct = 2.52
    mock_quote.volume = 39000000
    
    with patch("market.quotes.get_quote", return_value={"NSE:MOCKSTOCK": mock_quote, "MOCKSTOCK": mock_quote}):
        rep = funnel.evaluate_stock_quant("MOCKSTOCK")
        assert rep.qualified is True
        assert rep.score >= 60.0
        assert "Wyckoff Spring" in rep.pass_reason
        assert "EMA20 below EMA50 short-term downtrend" not in rep.rejection_reason


def test_falling_knife_rejected_stage1():
    """Verify that a falling stock (-3.8% dump, >12% below 200-DMA) is strictly rejected."""
    funnel = SmartFunnel(verbose=False)
    
    mock_reg = MagicMock()
    mock_reg.execute.side_effect = lambda tool, args: {
        "technical_analyse": {
            "ltp": 2100.0,
            "rsi": 25.0,
            "ema20": 2300.0,
            "ema50": 2400.0,
            "sma200": 2600.0,  # >12% below 200-DMA
            "macd_hist": -5.0,
            "volume_ratio": 2.0,
        },
        "fundamental_analyse": {
            "pe": 28.0,
            "roe": 12.0,
            "debt_equity": 0.1,
        },
    }.get(tool, {})
    
    funnel._registry = mock_reg
    
    # Severe negative day
    mock_quote = MagicMock()
    mock_quote.last_price = 2100.0
    mock_quote.change_pct = -3.88
    mock_quote.volume = 6000000
    
    with patch("market.quotes.get_quote", return_value={"NSE:FALLINGKNIFE": mock_quote, "FALLINGKNIFE": mock_quote}):
        rep = funnel.evaluate_stock_quant("FALLINGKNIFE")
        assert rep.qualified is False
        assert rep.score < 50.0
        assert rep.status_label == "FILTERED OUT"


def test_telecom_forensic_normalization():
    """Verify that a solvent telecom provider with high FCF is not penalized with false Altman Z distress red flags."""
    sample_telecom_data = {
        "working_capital": -80000.0,  # Prepaid negative working capital driving Z into DISTRESS
        "total_assets": 450000.0,
        "retained_earnings": 10000.0,
        "ebit": 25000.0,
        "book_value_equity": 50000.0,
        "total_liabilities": 400000.0,  # High spectrum/lease liabilities
        "dsri": 0.95,
        "gmi": 1.02,
        "aqi": 0.98,
        "sgi": 1.12,
        "depi": 1.01,
        "sgai": 0.96,
        "lvgi": 1.05,
        "tata": -0.02,
        "roe": 18.0,
        "free_cash_flow": 75000.0,  # Robust cash generation
        "profit_growth": 22.0,
        "debt_equity": 1.8,
        "current_ratio": 0.75,
        "pledged_pct": 0.0,
        "interest_coverage": 4.5,
        "sales_growth": 14.0,
        "roce": 15.0,
        "npm": 11.5,
    }
    
    with patch("analysis.universe.get_stock_sector", return_value=("telecom", "Telecom & Media")):
        res = audit_forensics("BHARTIARTL", data=sample_telecom_data, use_cache=False)
        assert len(res.governance_red_flags) == 0
        assert res.quality_rating in ("A", "A+")
        assert any("Capital-intensive subscription" in s for s in res.strengths)


def test_index_polarization_detector():
    """Verify that opposing momentum in benchmark heavyweights triggers TUG_OF_WAR_CHOP."""
    mock_quotes = {
        "NSE:HDFCBANK": MagicMock(last_price=731.0, change_pct=2.52),
        "NSE:BHARTIARTL": MagicMock(last_price=1890.0, change_pct=3.12),
        "NSE:RELIANCE": MagicMock(last_price=1226.0, change_pct=-1.41),
        "NSE:TCS": MagicMock(last_price=2105.0, change_pct=-3.88),
        "NSE:INFY": MagicMock(last_price=1050.0, change_pct=-0.68),
        "NSE:ICICIBANK": MagicMock(last_price=1338.0, change_pct=-0.65),
        "NSE:LT": MagicMock(last_price=3885.0, change_pct=1.27),
    }
    
    with patch("market.quotes.get_quote", return_value=mock_quotes):
        pol = get_index_polarization("NIFTY")
        assert pol.is_polarized is True
        assert pol.regime == "TUG_OF_WAR_CHOP"
        assert pol.spread_pct >= 6.0
        assert "Tug-of-War" in pol.summary


def test_asymmetric_radar_low_vix_adaptation():
    """Verify that 0DTE gamma setup switches to defined-risk credit spread under low VIX (<12.0)."""
    radar = AsymmetricOpportunityRadar()
    
    # Straddle with ATM 23350
    ce_contract = MagicMock(strike=23350, option_type="CE", ltp=45.0, last_price=45.0, symbol="NIFTY23350CE")
    pe_contract = MagicMock(strike=23350, option_type="PE", ltp=45.0, last_price=45.0, symbol="NIFTY23350PE")
    mock_chain = [ce_contract, pe_contract]
    
    # Spot unpinned upwards outside straddle breakeven (23350 + 90 = 23440)
    unpinned_spot = 23480.0
    
    # Mock VIX at 11.39 (today's level) and non-polarized index
    mock_polarization = MagicMock(is_polarized=False)
    
    with patch("market.indices.get_vix", return_value=11.39), \
         patch("market.indices.get_index_polarization", return_value=mock_polarization):
        opp = radar.detect_0dte_gamma_breakout("NIFTY", spot=unpinned_spot, chain=mock_chain)
        assert opp is not None
        assert opp.setup_type == "EXPIRY_0DTE_CREDIT_SPREAD"
        assert "Bull Put" in opp.setup_label
        assert "VIX" in opp.catalyst_summary
        assert "credit" in opp.profit_rule.lower()


def test_dead_ticker_cache():
    """Verify that a 404 delisted ticker is cached in _DEAD_TICKER_CACHE and skipped quickly."""
    import time
    
    fake_dead_ticker = "DEADCO.NS"
    _DEAD_TICKER_CACHE[fake_dead_ticker] = time.time()
    
    # Querying yf_get_quote should raise fast without hitting network
    with pytest.raises(RuntimeError) as exc_info:
        yf_get_quote("DEADCO", exchange="NSE")
    assert "24h negative cache" in str(exc_info.value)
