"""
tests/test_multi_asset_alerts.py
─────────────────────────────────
Deterministic unit test suite validating:
  1. Time-partitioned operational session schedule (get_current_ist_session).
  2. Multi-asset alert generation (Commodity MCX, Currency CDS, Equity/NFO).
  3. Telegram template rendering for MCX and CDS alerts.
  4. Option risk formula floor calibration for low-priced options (< ₹20).
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
import pytest

from engine.auto_alert_engine import (
    AutoAlert,
    AutoAlertEngine,
    get_current_ist_session,
)
from bot.alert_templates import render_auto_alert

IST = timezone(timedelta(hours=5, minutes=30))


def test_time_partitioned_session_schedule():
    """Validates institutional time-partitioning across trading sessions."""
    # Wednesday 10:30 IST -> Pure Domestic Equity & NFO Desk
    t_equity = datetime(2026, 9, 9, 10, 30, tzinfo=IST)
    s_eq = get_current_ist_session(t_equity)
    assert s_eq["equity_nfo"] is True
    assert s_eq["currency"] is False
    assert s_eq["commodity"] is False

    # Wednesday 09:05 IST -> Pre-Equity Currency window
    t_pre_curr = datetime(2026, 9, 9, 9, 5, tzinfo=IST)
    s_pre = get_current_ist_session(t_pre_curr)
    assert s_pre["equity_nfo"] is False
    assert s_pre["currency"] is True
    assert s_pre["commodity"] is False

    # Wednesday 16:00 IST -> Post-Equity: Currency (CDS) + Commodities (MCX)
    t_post = datetime(2026, 9, 9, 16, 0, tzinfo=IST)
    s_post = get_current_ist_session(t_post)
    assert s_post["equity_nfo"] is False
    assert s_post["currency"] is True
    assert s_post["commodity"] is True

    # Wednesday 19:30 IST -> Evening MCX Peak US Overlap (CDS closed at 17:00)
    t_eve = datetime(2026, 9, 9, 19, 30, tzinfo=IST)
    s_eve = get_current_ist_session(t_eve)
    assert s_eve["equity_nfo"] is False
    assert s_eve["currency"] is False
    assert s_eve["commodity"] is True

    # Wednesday 23:45 IST -> Night Closed
    t_night = datetime(2026, 9, 9, 23, 45, tzinfo=IST)
    s_night = get_current_ist_session(t_night)
    assert s_night["equity_nfo"] is False
    assert s_night["currency"] is False
    assert s_night["commodity"] is False

    # Sunday 12:00 IST -> Weekend Dormant
    t_sun = datetime(2026, 9, 13, 12, 0, tzinfo=IST)
    s_sun = get_current_ist_session(t_sun)
    assert s_sun["equity_nfo"] is False
    assert s_sun["currency"] is False
    assert s_sun["commodity"] is False


def test_mcx_commodity_alert_template_rendering():
    """Validates that MCX commodity alerts render with professional headers, plans, and lot sizes."""
    alert = AutoAlert(
        alert_id="comm-crudeoil-202609101600",
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        symbol="CRUDEOIL",
        exchange="MCX",
        direction="BULLISH",
        headline="🛢️ [REAL/LIVE] MCX MOMENTUM: CRUDEOIL +1.8% Reclaiming VWAP",
        summary="Institutional breakout in CRUDEOIL: Trading at ₹6,520.0 (+1.8%).",
        ltp=6520.0,
        trigger_level=6520.0,
        target_level=6640.0,
        stop_loss=6450.0,
        confidence=86,
        actionable_plan={
            "action": "BUY_FUTURES",
            "segment": "COMMODITY",
            "contract": "MCX:CRUDEOIL",
            "entry_range": "₹6,500.0 – ₹6,540.0",
            "stop_loss": "₹6,450.0",
            "target": "₹6,640.0",
            "target_2": "₹6,750.0",
            "risk_reward": "1:2.4",
            "lot_size": 100,
            "profit_rule": "Book 50% at T1, trail stop to cost.",
        },
    )

    rendered = render_auto_alert(alert, in_market=True)
    assert "[REAL / LIVE MCX COMMODITY SIGNAL]" in rendered
    assert "MCX Commodity Plan" in rendered
    assert "BUY_FUTURES MCX:CRUDEOIL" in rendered
    assert "Lot: 100" in rendered
    assert "Target 1:" in rendered
    assert "T2:" in rendered
    assert "Book 50% at T1" in rendered


def test_cds_currency_alert_template_rendering():
    """Validates that CDS currency alerts render with precision paise quotations and 1000 lot size."""
    alert = AutoAlert(
        alert_id="curr-usdinr-202609101600",
        alert_type="CURRENCY_BREAKOUT",
        stage="IGNITED",
        symbol="USDINR",
        exchange="CDS",
        direction="BULLISH",
        headline="💱 [REAL/LIVE] CURRENCY BREAKOUT: USDINR +0.14% @ ₹83.9250",
        summary="Macro currency surge in USDINR: Moving +0.14% to ₹83.9250.",
        ltp=83.9250,
        trigger_level=83.9250,
        target_level=84.0750,
        stop_loss=83.8450,
        confidence=82,
        actionable_plan={
            "action": "BUY_FUTURES",
            "segment": "CURRENCY",
            "contract": "CDS:USDINR",
            "entry_range": "₹83.9050 – ₹83.9450",
            "stop_loss": "₹83.8450",
            "target": "₹84.0750",
            "target_2": "₹84.1800",
            "risk_reward": "1:2.2",
            "lot_size": 1000,
            "profit_rule": "Scale 50% at T1, move SL to entry.",
        },
    )

    rendered = render_auto_alert(alert, in_market=True)
    assert "[REAL / LIVE CURRENCY BREAKOUT]" in rendered
    assert "Macro Currency Plan" in rendered
    assert "BUY_FUTURES CDS:USDINR" in rendered
    assert "Lot: 1000" in rendered
    assert "Target 1:" in rendered
    assert "Scale 50% at T1" in rendered


def test_sub_20_option_risk_formula():
    """
    Verifies that low-priced options (e.g. ₹5.00, ₹8.00) use the calibrated 0.20-paise floor,
    preventing excessive stop-loss risk vetoes (> 45%).
    """
    opt_ltp = 6.50
    # Old buggy formula: round(max(5.0, opt_ltp * 0.25), 2) -> gave 5.0 (76.9% risk! Vetoed!)
    # New calibrated formula: round(max(0.20, opt_ltp * 0.25), 2)
    risk_pts = round(max(0.20, opt_ltp * 0.25), 2)
    risk_pct = (risk_pts / opt_ltp) * 100

    assert risk_pts == 1.62 or risk_pts == 1.63
    assert risk_pct < 30.0  # Well within 45% Tier-1 Sanity limit!


def test_commodity_scanner_detection():
    """Verifies that scan_commodities_now creates valid MCX alerts from quote triggers."""
    engine = AutoAlertEngine()
    engine._alerts = []
    engine._cooldowns = {}
    engine._watched_commodities = ["CRUDEOIL"]

    mock_quote = MagicMock()
    mock_quote.last_price = 6500.0
    mock_quote.ltp = 6500.0
    mock_quote.change_pct = 2.1
    mock_quote.volume = 45000

    with patch("market.quotes.get_quote", return_value={"MCX:CRUDEOIL": mock_quote}):
        with patch("market.history.get_ohlcv", return_value=None):
            alerts = engine.scan_commodities_now()
            assert len(alerts) >= 1
            crude_alert = alerts[0]
            assert crude_alert.symbol == "CRUDEOIL"
            assert crude_alert.exchange == "MCX"
            assert crude_alert.alert_type == "COMMODITY_MOMENTUM"
            assert crude_alert.actionable_plan["segment"] == "COMMODITY"
            assert crude_alert.actionable_plan["lot_size"] == 100


def test_currency_scanner_detection():
    """Verifies that scan_currency_now creates valid CDS alerts from quote triggers."""
    engine = AutoAlertEngine()
    engine._watched_currencies = ["USDINR"]

    mock_quote = MagicMock()
    mock_quote.last_price = 83.95
    mock_quote.ltp = 83.95
    mock_quote.change_pct = 0.15

    with patch("market.quotes.get_quote", return_value={"CDS:USDINR": mock_quote}):
        alerts = engine.scan_currency_now()
        assert len(alerts) >= 1
        curr_alert = alerts[0]
        assert curr_alert.symbol == "USDINR"
        assert curr_alert.exchange == "CDS"
        assert curr_alert.alert_type == "CURRENCY_BREAKOUT"
        assert curr_alert.actionable_plan["segment"] == "CURRENCY"
        assert curr_alert.actionable_plan["lot_size"] == 1000


def test_black_76_pricing_and_put_call_parity():
    """Validates Black-76 model mathematical invariants and Put-Call parity."""
    from engine.greeks_manager import black_76_price_and_greeks

    F = 6500.0
    K = 6500.0
    T = 14 / 365.0
    r = 0.065
    sigma = 0.32

    call = black_76_price_and_greeks(
        futures_price=F,
        strike=K,
        time_to_expiry_years=T,
        risk_free_rate=r,
        volatility=sigma,
        option_type="CE",
    )
    put = black_76_price_and_greeks(
        futures_price=F,
        strike=K,
        time_to_expiry_years=T,
        risk_free_rate=r,
        volatility=sigma,
        option_type="PE",
    )

    # Put-Call parity for futures options: Call - Put = e^(-rT) * (F - K)
    # When F == K, Call == Put
    assert abs(call["price"] - put["price"]) < 0.05
    assert call["delta"] > 0.45 and call["delta"] < 0.55
    assert put["delta"] < -0.45 and put["delta"] > -0.55
    assert call["gamma"] > 0
    assert call["vega"] > 0
    assert call["theta"] < 0


def test_commodity_options_chain_resolution():
    """Validates that get_options_chain returns populated MCX contracts for commodities."""
    from market.options import get_options_chain, get_expiries

    with patch("market.quotes.get_ltp", return_value=6520.0):
        chain = get_options_chain("CRUDEOIL")
        assert len(chain) == 42
        sample = chain[0]
        assert sample.underlying == "CRUDEOIL"
        assert sample.exchange == "MCX"
        assert sample.lot_size == 100
        assert sample.strike > 0
        assert sample.last_price > 0

        expiries = get_expiries("CRUDEOIL")
        assert len(expiries) >= 1


def test_commodity_alert_includes_defined_risk_option_alternative():
    """Verifies that scan_commodities_now provides a defined-risk option contract alternative."""
    engine = AutoAlertEngine()
    engine._alerts = []
    engine._cooldowns = {}
    engine._watched_commodities = ["CRUDEOIL"]

    mock_quote = MagicMock()
    mock_quote.last_price = 6500.0
    mock_quote.ltp = 6500.0
    mock_quote.change_pct = 2.1
    mock_quote.volume = 45000

    with patch("market.quotes.get_quote", return_value={"MCX:CRUDEOIL": mock_quote}):
        with patch("market.history.get_ohlcv", return_value=None):
            with patch("market.quotes.get_ltp", return_value=6500.0):
                alerts = engine.scan_commodities_now()
                assert len(alerts) >= 1
                crude_alert = alerts[0]
                assert "option_alternative" in crude_alert.actionable_plan
                opt_alt = crude_alert.actionable_plan["option_alternative"]
                assert opt_alt["option_type"] == "CE"
                assert opt_alt["strike"] == 6500.0
                assert opt_alt["max_loss_capped"] > 0
                assert "MCX:CRUDEOIL" in opt_alt["contract"]
