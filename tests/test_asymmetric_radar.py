"""
tests/test_asymmetric_radar.py
──────────────────────────────
Unit tests for the Asymmetric Opportunity Radar (Low Risk : Big Reward).
Validates Pocket Pivots, F&O Ban Squeezes, Rubber Band 200-EMA Mean-Reversions,
0DTE Expiry Gamma Breakouts, and strict 1:3.0+ Risk:Reward mathematically guaranteed filters.
"""

from unittest.mock import MagicMock, patch
import numpy as np
import pandas as pd
import pytest

from engine.asymmetric_radar import (
    AsymmetricOpportunity,
    AsymmetricRadarScanner,
    scan_asymmetric_opportunities,
)


@pytest.fixture
def scanner():
    return AsymmetricRadarScanner()


def test_pocket_pivot_detection(scanner):
    """Test Pocket Pivot detection: volume exceeds highest down-day volume in 10 days while respecting 10-EMA in base."""
    dates = pd.date_range("2026-08-01", periods=30, freq="B")
    # Base around 1000
    closes = np.full(30, 1000.0)
    for i in range(29):
        closes[i] = 1000.0 + (i % 5) * 2 - 4  # 996 to 1004
    closes[-1] = 1010.0  # Pocket pivot breakout close

    highs = closes + 5.0
    lows = closes - 5.0
    opens = closes - 2.0

    # Volumes: down days max volume = 50,000; today's volume = 120,000 (exceeds all down days)
    volumes = np.full(30, 40000)
    volumes[15] = 50000  # Down day max
    volumes[-1] = 120000  # Pocket pivot ignition

    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )

    mock_quote = MagicMock()
    mock_quote.last_price = 1010.0
    mock_quote.vwap = 1008.0

    with patch("market.quotes.get_quote", return_value={"NSE:TRENT": mock_quote}), \
         patch("market.history.get_ohlcv", return_value=df), \
         patch("analysis.sector_rotation.get_stock_sector_alignment", return_value={"sector_name": "Retail", "quadrant": "LEADING"}):

        opp = scanner.detect_pocket_pivot("TRENT", df=df)

        assert opp is not None
        assert opp.symbol == "TRENT"
        assert opp.setup_type == "POCKET_PIVOT"
        assert opp.risk_reward_ratio >= 3.0
        assert opp.stop_loss < opp.ltp
        assert opp.target_1 > opp.ltp
        assert opp.moonshot_target > opp.target_2
        assert "Enter inside base" in opp.entry_rule or "10-EMA" in opp.entry_rule
        assert "DO NOT CHASE" in opp.no_chase_rule
        assert any("Pocket Pivot" in c for c in opp.confluences)


def test_fno_ban_squeeze_detection(scanner):
    """Test F&O Ban Squeeze detection for high MWPL (>= 88%) with price above VWAP."""
    mock_quote = MagicMock()
    mock_quote.last_price = 950.0
    mock_quote.vwap = 945.0
    mock_quote.change_pct = 2.4

    dates = pd.date_range("2026-08-01", periods=10, freq="B")
    df = pd.DataFrame(
        {
            "open": [945.0] * 10,
            "high": [955.0] * 10,
            "low": [940.0] * 10,
            "close": [950.0] * 10,
            "volume": [2000000] * 10,
        },
        index=dates,
    )

    with patch("market.quotes.get_quote", return_value={"NSE:TATAMOTORS": mock_quote}), \
         patch("market.history.get_ohlcv", return_value=df):

        # Test pre-ban squeeze at 92% MWPL
        opp = scanner.detect_fno_ban_squeeze("TATAMOTORS", mwpl_pct=92.0, is_in_ban=False, df=df)

        assert opp is not None
        assert opp.symbol == "TATAMOTORS"
        assert opp.setup_type == "FNO_BAN_SQUEEZE"
        assert opp.risk_reward_ratio >= 3.0
        assert "MWPL" in opp.confluences[0]
        assert opp.stop_loss < opp.ltp


def test_rubber_band_reversal_detection(scanner):
    """Test Rubber Band 200-EMA mean-reversion on high-grade stock with RSI <= 35 and clean forensics."""
    # 220 bars of data so 200 EMA can be computed
    dates = pd.date_range("2025-10-01", periods=220, freq="B")
    closes = np.full(220, 1550.0)
    # Chronological steep decline in the last 14 days to create oversold RSI <= 30
    for k in range(14):
        closes[-14 + k] = 1550.0 - (k + 1) * 4.0  # Drops from 1546 down to 1494

    # Today is candle with a bullish hammer lower-wick rejection
    # Close = 1495, Open = 1494, High = 1498, Low = 1475 (19 pt lower wick vs 1 pt body -> Hammer!)
    closes[-1] = 1495.0
    opens = closes.copy()
    opens[-1] = 1494.0
    highs = closes + 5.0
    lows = closes - 5.0
    lows[-1] = 1475.0
    volumes = np.full(220, 500000)

    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )

    mock_quote = MagicMock()
    mock_quote.last_price = 1495.0
    mock_quote.vwap = 1492.0

    mock_forensic = MagicMock()
    mock_forensic.is_clean = True
    mock_forensic.beneish_flagged = False
    mock_forensic.beneish_m_score = -2.4  # Clean (< -1.78)
    mock_forensic.altman_z_score = 3.5    # Safe (> 2.6)

    with patch("market.quotes.get_quote", return_value={"NSE:HDFCBANK": mock_quote}), \
         patch("market.history.get_ohlcv", return_value=df), \
         patch("analysis.forensic.audit_company_forensics", return_value=mock_forensic):

        opp = scanner.detect_rubber_band_reversal("HDFCBANK", df=df)

        assert opp is not None
        assert opp.symbol == "HDFCBANK"
        assert opp.setup_type == "RUBBER_BAND_200EMA"
        assert opp.risk_reward_ratio >= 3.0
        assert opp.stop_loss < opp.ltp
        assert opp.target_1 > opp.ltp


def test_0dte_gamma_breakout_detection(scanner):
    """Test 0DTE Expiry Gamma Breakout on Index unpinning beyond straddle cone."""
    mock_quote = MagicMock()
    mock_quote.last_price = 25150.0  # Above 25000 + 110 (25110 straddle cone)

    c_call = MagicMock()
    c_call.strike = 25000
    c_call.option_type = "CE"
    c_call.last_price = 65.0
    c_call.ltp = 65.0

    c_put = MagicMock()
    c_put.strike = 25000
    c_put.option_type = "PE"
    c_put.last_price = 45.0
    c_put.ltp = 45.0

    mock_opt_chain = [c_call, c_put]

    with patch("market.quotes.get_quote", return_value={"NSE:NIFTY": mock_quote}), \
         patch("market.options.get_options_chain", return_value=mock_opt_chain):

        opp = scanner.detect_0dte_gamma_breakout("NIFTY", spot=25150.0, chain=mock_opt_chain, expiry_date="TODAY")

        assert opp is not None
        assert opp.symbol == "NIFTY"
        assert opp.setup_type == "EXPIRY_0DTE_GAMMA"
        assert opp.risk_reward_ratio >= 3.0
        assert "Unpinned" in opp.confluences[0]
        assert opp.stop_loss < opp.ltp


def test_fail_closed_rr_gate(scanner):
    """Test that setups failing the strict 1:3.0 Risk:Reward ratio are rejected (fail-closed)."""
    opp = AsymmetricOpportunity(
        opportunity_id="test-rr",
        symbol="TEST",
        exchange="NSE",
        segment="FNO",
        setup_type="POCKET_PIVOT",
        direction="BULLISH",
        conviction_score=85,
        verdict="HIGH_CONVICTION",
        ltp=100.0,
        entry_range="₹99.5 – ₹100.5",
        stop_loss=95.0,  # Risk = 5 pts
        target_1=107.5,  # Reward = 7.5 pts -> R:R = 1.5 (< 3.0)
        target_2=115.0,
        moonshot_target=125.0,
        risk_reward_ratio=1.5,
        risk_pts=5.0,
        reward_t1_pts=7.5,
        confluences=["Test confluence"],
        entry_rule="Test entry",
        no_chase_rule="Test no chase",
        profit_rule="Test profit",
    )
    with patch.object(scanner, "scan_opportunities", return_value=[opp]):
        filtered = [o for o in scanner.scan_opportunities() if o.risk_reward_ratio >= 3.0]
        assert len(filtered) == 0


def test_scan_asymmetric_opportunities_returns_structured_dicts():
    """Test the module-level scan_asymmetric_opportunities convenience wrapper."""
    mock_opp = AsymmetricOpportunity(
        opportunity_id="asym-test-reliance",
        symbol="RELIANCE",
        exchange="NSE",
        segment="FNO",
        setup_type="POCKET_PIVOT",
        direction="BULLISH",
        conviction_score=86,
        verdict="HIGH_CONVICTION",
        ltp=3000.0,
        entry_range="₹2,995.0 – ₹3,010.0",
        stop_loss=2960.0,
        target_1=3120.0,
        target_2=3240.0,
        moonshot_target=3360.0,
        risk_reward_ratio=3.0,
        risk_pts=40.0,
        reward_t1_pts=120.0,
        confluences=["Pocket Pivot base breakout", "RRG Leading momentum"],
        entry_rule="Enter inside base off 10-EMA support.",
        no_chase_rule="DO NOT CHASE if price exceeds ₹3,010.0.",
        profit_rule="Scale 40% at T1, 40% at T2, trail 20% runner.",
    )

    with patch("engine.asymmetric_radar.asymmetric_radar.scan_asymmetric_opportunities", return_value=[mock_opp]):
        results = scan_asymmetric_opportunities(min_rr=3.0)
        assert len(results) == 1
        d = results[0]
        assert d["symbol"] == "RELIANCE"
        assert d["setup_type"] == "POCKET_PIVOT"
        assert d["risk_reward_ratio"] == 3.0
        assert "entry_range" in d
