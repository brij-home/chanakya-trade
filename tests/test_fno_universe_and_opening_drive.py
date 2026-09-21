import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass
from datetime import datetime

from engine.auto_alert_engine import AutoAlertEngine
from brokers.base import Quote


@pytest.fixture
def engine():
    eng = AutoAlertEngine()
    return eng


def test_watched_equities_includes_full_fno_universe(engine):
    """Verifies that watched_equities includes all 218 F&O stocks including OFSS, MFSL, HDFCLIFE."""
    equities = engine.watched_equities
    assert len(equities) >= 200
    assert "OFSS" in equities
    assert "MFSL" in equities
    assert "HDFCLIFE" in equities
    assert "PATANJALI" in equities
    assert "OBEROIRLTY" in equities
    assert "KPITTECH" in equities
    assert "TATAELXSI" in equities


def test_mstock_known_tokens():
    """Verifies that mStock API knows tokens for major market movers."""
    from brokers.mstock import MStockAPI
    api = MStockAPI()
    assert api.get_symbol_token("OFSS", "NSE") == "10738"
    assert api.get_symbol_token("MFSL", "NSE") == "2142"
    assert api.get_symbol_token("HDFCLIFE", "NSE") == "467"
    assert api.get_symbol_token("PATANJALI", "NSE") == "17029"


@dataclass
class MockOptionContract:
    symbol: str = "OFSS11400PE"
    strike: float = 11400.0
    option_type: str = "PE"
    last_price: float = 120.0
    volume: int = 15000
    oi: int = 8000
    oi_change: int = -500
    pchange: float = 45.0
    expiry: str = "2026-09-24"
    high: float = 135.0
    low: float = 60.0
    open: float = 65.0
    close: float = 120.0


def test_opening_drive_detection_and_profit_playbook(engine):
    """
    Verifies that a stock with Open=High (Bearish Opening Drive) passing Stage 1
    generates an OPTIONS_MOMENTUM alert with Opening Drive tag and 3-Tier profit rule.
    """
    engine._cooldowns.clear()
    engine._alerts.clear()
    mock_quote_ofss = Quote(
        symbol="OFSS",
        last_price=11300.0,
        open=11750.0,
        high=11750.0,  # Open == High !
        low=11280.0,
        close=11300.0,
        volume=250000,
        change=-450.0,
        change_pct=-3.83,
        vwap=11500.0,
    )
    mock_quotes_batch = {
        "NSE:OFSS": mock_quote_ofss,
        "OFSS": mock_quote_ofss,
    }

    mock_contracts = [
        MockOptionContract(strike=11400.0, option_type="PE", last_price=125.0, volume=15000, oi=8000, pchange=50.0)
    ]

    with patch.object(engine, "_watched_indices", []), \
         patch.object(AutoAlertEngine, "watched_equities", new_callable=lambda: ["OFSS"]), \
         patch("market.quotes.get_quote", return_value=mock_quotes_batch), \
         patch("market.quotes.get_ltp", return_value=11300.0), \
         patch("market.options.get_options_chain", return_value=mock_contracts), \
         patch("market.history.get_ohlcv", return_value=None):

        alerts = engine.scan_options_momentum_breakouts()

        assert len(alerts) >= 1
        alert = alerts[0]
        assert alert.symbol == "OFSS"
        assert alert.option_type == "PE"
        assert alert.metrics.get("is_opening_drive") is True
        assert alert.metrics.get("opening_drive_type") == "BEARISH_OPEN_EQUALS_HIGH"
        assert "OPENING DRIVE" in alert.summary
        assert "3-TIER PROFIT-TAKING" in alert.actionable_plan.get("profit_rule", "")
        assert alert.confidence >= 85


def test_stage_1_skips_flat_sideways_stock(engine):
    """
    Verifies that a sideways, flat stock with 0 momentum and no opening drive
    is skipped in Stage 1 without calling get_options_chain.
    """
    mock_quote_flat = Quote(
        symbol="FLATSTOCK",
        last_price=500.0,
        open=499.8,
        high=501.0,
        low=499.5,
        close=500.0,
        volume=10000,
        change=0.2,
        change_pct=0.04,  # flat 0.04%
        vwap=500.0,  # on VWAP
    )
    mock_quotes_batch = {
        "NSE:FLATSTOCK": mock_quote_flat,
        "FLATSTOCK": mock_quote_flat,
    }

    with patch.object(engine, "_watched_indices", []), \
         patch.object(AutoAlertEngine, "watched_equities", new_callable=lambda: ["FLATSTOCK"]), \
         patch("market.quotes.get_quote", return_value=mock_quotes_batch), \
         patch("market.quotes.get_ltp", return_value=500.0), \
         patch("market.options.get_options_chain") as mock_chain:

        alerts = engine.scan_options_momentum_breakouts()
        assert len(alerts) == 0
        # Crucial invariant: get_options_chain should NOT be called for flat stocks
        mock_chain.assert_not_called()
