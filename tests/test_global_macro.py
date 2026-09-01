"""
tests/test_global_macro.py
───────────────────────────
Unit tests for the Institutional Global Macro Correlation & Transmission Engine.
"""

from unittest.mock import MagicMock, patch

from market.global_macro import (
    GlobalMacroItem,
    GlobalMacroReport,
    SectorImpactItem,
    fetch_global_macro_report,
)


def test_global_macro_item_dataclass():
    item = GlobalMacroItem(
        key="nasdaq",
        symbol="^IXIC",
        name="NASDAQ 100",
        category="TECH_EQUITY",
        ltp=26370.0,
        change=45.0,
        change_pct=0.17,
        unit="pts",
        correlation_to_india="~0.82 with NIFTY IT",
        transmission_channel="Overnight US enterprise tech sentiment",
        impact_bias="BULLISH",
    )
    assert item.key == "nasdaq"
    assert item.impact_bias == "BULLISH"
    assert item.ltp == 26370.0


def test_sector_impact_item_dataclass():
    sec = SectorImpactItem(
        sector_id="it",
        sector_name="IT & Software",
        bias="BULLISH_TAILWIND",
        primary_driver="NASDAQ 100",
        rationale="Strong tech tailwind",
        score_modifier=12,
        affected_symbols=["TCS", "INFY"],
    )
    assert sec.sector_id == "it"
    assert sec.bias == "BULLISH_TAILWIND"
    assert len(sec.affected_symbols) == 2


def test_fetch_global_macro_report_mocked():
    """Test report generation with synthetic live quotes."""
    with patch("yfinance.Ticker") as mock_ticker:
        # Mock fast_info for tickers
        def make_ticker_mock(ticker_sym):
            mock_t = MagicMock()
            if ticker_sym == "^IXIC":
                mock_t.fast_info.last_price = 26500.0
                mock_t.fast_info.previous_close = 26000.0  # +1.92%
            elif ticker_sym == "DX-Y.NYB":
                mock_t.fast_info.last_price = 99.0
                mock_t.fast_info.previous_close = 100.0  # -1.0% (Bullish for EM)
            elif ticker_sym == "BZ=F":
                mock_t.fast_info.last_price = 85.0
                mock_t.fast_info.previous_close = 88.0  # -3.41% (Bullish for Paints/OMCs)
            elif ticker_sym == "^TNX":
                mock_t.fast_info.last_price = 4.5
                mock_t.fast_info.previous_close = 4.6  # -2.17% (Yields easing)
            elif ticker_sym == "^VIX":
                mock_t.fast_info.last_price = 13.5
                mock_t.fast_info.previous_close = 14.0  # Low fear
            else:
                mock_t.fast_info.last_price = 100.0
                mock_t.fast_info.previous_close = 100.0
            return mock_t

        mock_ticker.side_effect = make_ticker_mock

        report = fetch_global_macro_report(nifty_spot=24000.0, use_cache=False)
        assert isinstance(report, GlobalMacroReport)
        assert report.composite_score > 0  # Should be positive risk-on with these metrics
        assert report.global_posture == "RISK_ON"
        assert "nasdaq" in report.items
        assert "dxy" in report.items
        assert "brent" in report.items

        # Verify IT sector has tailwind from NASDAQ surge
        it_sec = next(s for s in report.sector_impacts if s.sector_id == "it")
        assert it_sec.bias == "BULLISH_TAILWIND"
        assert it_sec.score_modifier > 0

        # Verify Paints/Aviation has tailwind from crude drop
        crude_sec = next(s for s in report.sector_impacts if s.sector_id == "consumption_crude")
        assert crude_sec.bias == "BULLISH_TAILWIND"

        # Verify serialization
        d = report.to_dict()
        assert "composite_score" in d
        assert "global_posture" in d
        assert "items" in d
        assert "sector_impacts" in d


def test_fetch_global_macro_report_bearish_scenario():
    """Test report generation when global markets sell off."""
    with patch("yfinance.Ticker") as mock_ticker:

        def make_ticker_mock(ticker_sym):
            mock_t = MagicMock()
            if ticker_sym == "^IXIC":
                mock_t.fast_info.last_price = 25000.0
                mock_t.fast_info.previous_close = 26000.0  # -3.85%
            elif ticker_sym == "DX-Y.NYB":
                mock_t.fast_info.last_price = 104.0
                mock_t.fast_info.previous_close = 100.0  # +4.0% (Strong Dollar Headwind)
            elif ticker_sym == "BZ=F":
                mock_t.fast_info.last_price = 95.0
                mock_t.fast_info.previous_close = 90.0  # +5.5% (Crude Spike)
            elif ticker_sym == "^TNX":
                mock_t.fast_info.last_price = 4.9
                mock_t.fast_info.previous_close = 4.6  # +6.5% (Yields spike)
            elif ticker_sym == "^VIX":
                mock_t.fast_info.last_price = 26.0
                mock_t.fast_info.previous_close = 18.0  # Panic
            else:
                mock_t.fast_info.last_price = 100.0
                mock_t.fast_info.previous_close = 100.0
            return mock_t

        mock_ticker.side_effect = make_ticker_mock

        report = fetch_global_macro_report(nifty_spot=24000.0, use_cache=False)
        assert report.composite_score < 0
        assert report.global_posture in ("RISK_OFF", "VOLATILE_CAUTION")

        it_sec = next(s for s in report.sector_impacts if s.sector_id == "it")
        assert it_sec.bias == "BEARISH_HEADWIND"

        paints_sec = next(s for s in report.sector_impacts if s.sector_id == "consumption_crude")
        assert paints_sec.bias == "BEARISH_HEADWIND"

        upstream_sec = next(s for s in report.sector_impacts if s.sector_id == "energy_upstream")
        assert upstream_sec.bias == "BULLISH_TAILWIND"  # Crude spike helps ONGC
