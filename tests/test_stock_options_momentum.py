"""
tests/test_stock_options_momentum.py
────────────────────────────────────
Institutional test suite for:
  1. Stock Option Momentum Ignition & High-Torque Strike Selection
  2. Sector Alignment Support Gate & Extreme Catalyst / Decoupler Escape Hatch
  3. Micro-Impulse Trigger & Fast Scalp (+20% in 10-15m, 20m time-stop)
  4. AutoAlertEngine 1-Signal-Per-Sector Daily Throttle (eliminating sibling duplicates)
"""

from __future__ import annotations

import unittest.mock as mock
from datetime import datetime, timezone, timedelta

from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine
from engine.detectors.options_momentum import detect_options_momentum_breakouts
from analysis.sector_rotation import StockTailwind

IST = timezone(timedelta(hours=5, minutes=30))


class DummyOptionContract:
    def __init__(
        self,
        symbol: str,
        strike: float,
        option_type: str,
        last_price: float,
        volume: int,
        oi: int,
        pchange: float = 12.0,
        oi_change: int = -500,
        bid: float = 0.0,
        ask: float = 0.0,
        expiry: str = "2026-09-24",
    ):
        self.symbol = symbol
        self.strike = strike
        self.option_type = option_type
        self.last_price = last_price
        self.volume = volume
        self.oi = oi
        self.pchange = pchange
        self.change_pct = pchange
        self.oi_change = oi_change
        self.bid = bid or (last_price * 0.99)
        self.ask = ask or (last_price * 1.01)
        self.expiry = expiry


class DummyQuote:
    def __init__(self, ltp: float, open_p: float, vwap: float, chg: float = 1.2):
        self.last_price = ltp
        self.ltp = ltp
        self.open = open_p
        self.vwap = vwap
        self.change_pct = chg
        self.high = ltp * 1.005
        self.low = open_p * 0.998


def test_sector_support_gate_aligned_stock():
    """Stock with aligned sector support (LEADING/IMPROVING) passes the sector gate."""
    now_dt = datetime(2026, 9, 23, 10, 30, tzinfo=IST)
    quote = DummyQuote(ltp=1500.0, open_p=1480.0, vwap=1490.0, chg=1.35)
    contracts = [
        DummyOptionContract("INFY1520CE", 1520.0, "CE", 32.0, volume=3500, oi=2500, pchange=18.0)
    ]

    tailwind = StockTailwind(
        symbol="INFY",
        sector="IT",
        quadrant="LEADING",
        rs_ratio=103.5,
        rs_momentum=102.1,
        tailwind_score=85,
        alignment="STRONG_TAILWIND",
        analysis="Sector IT in strong tailwind",
        intraday_rs=1.1,
        intraday_alignment="STRONG_INTRADAY_TAILWIND",
    )

    with mock.patch(
        "market.quotes.get_quote",
        return_value={"NSE:INFY": quote, "NSE:NIFTY 50": DummyQuote(24500, 24450, 24480, 0.4)},
    ):
        with mock.patch("market.quotes.get_ltp", return_value=1500.0):
            with mock.patch("market.options.get_options_chain", return_value=contracts):
                with mock.patch("market.options.get_expiries", return_value=["2026-09-24"]):
                    with mock.patch("market.history.get_ohlcv", return_value=None):
                        with mock.patch(
                            "analysis.sector_rotation.get_stock_tailwind", return_value=tailwind
                        ):
                            with mock.patch(
                                "analysis.universe.get_stock_sector",
                                return_value=("it", "IT, Software & Technology"),
                            ):
                                alerts = detect_options_momentum_breakouts(
                                    targets=["INFY"],
                                    watched_indices=[],
                                    now_dt=now_dt,
                                )

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.symbol == "INFY"
    assert alert.direction == "BULLISH"
    assert alert.metrics["sector_tailwind_bonus"] == 10
    assert alert.metrics["sector_id"] == "it"
    assert "fast_scalp" in alert.actionable_plan
    assert alert.actionable_plan["fast_scalp"]["time_stop_mins"] == 20
    assert "impulse_trigger_level" in alert.actionable_plan


def test_sector_support_gate_unaligned_rejected():
    """Stock in conflicting/lagging sector without extreme catalyst is suppressed."""
    now_dt = datetime(2026, 9, 23, 10, 30, tzinfo=IST)
    quote = DummyQuote(ltp=1500.0, open_p=1495.0, vwap=1498.0, chg=0.6)
    contracts = [
        DummyOptionContract("INFY1520CE", 1520.0, "CE", 25.0, volume=800, oi=12000, pchange=8.0)
    ]

    tailwind = StockTailwind(
        symbol="INFY",
        sector="IT",
        quadrant="LAGGING",
        rs_ratio=97.0,
        rs_momentum=96.0,
        tailwind_score=25,
        alignment="HEADWIND",
        analysis="Sector IT in headwind",
        intraday_rs=-1.2,
        intraday_alignment="INTRADAY_HEADWIND",
    )

    with mock.patch(
        "market.quotes.get_quote",
        return_value={"NSE:INFY": quote, "NSE:NIFTY 50": DummyQuote(24500, 24450, 24480, 0.4)},
    ):
        with mock.patch("market.quotes.get_ltp", return_value=1500.0):
            with mock.patch("market.options.get_options_chain", return_value=contracts):
                with mock.patch("market.options.get_expiries", return_value=["2026-09-24"]):
                    with mock.patch("market.history.get_ohlcv", return_value=None):
                        with mock.patch(
                            "analysis.sector_rotation.get_stock_tailwind", return_value=tailwind
                        ):
                            with mock.patch(
                                "analysis.universe.get_stock_sector",
                                return_value=("it", "IT, Software & Technology"),
                            ):
                                alerts = detect_options_momentum_breakouts(
                                    targets=["INFY"],
                                    watched_indices=[],
                                    now_dt=now_dt,
                                )

    # Suppressed because sector is lagging and no extreme catalyst
    assert len(alerts) == 0


def test_sector_support_extreme_decoupler_escape_hatch():
    """Stock in conflicting sector with extreme catalyst (RVOL/Turnover surge) passes with DECOUPLER badge."""
    now_dt = datetime(2026, 9, 23, 10, 30, tzinfo=IST)
    quote = DummyQuote(ltp=1550.0, open_p=1495.0, vwap=1520.0, chg=3.2)
    contracts = [
        DummyOptionContract("INFY1540CE", 1540.0, "CE", 42.0, volume=9500, oi=3400, pchange=65.0)
    ]

    tailwind = StockTailwind(
        symbol="INFY",
        sector="IT",
        quadrant="LAGGING",
        rs_ratio=97.0,
        rs_momentum=96.0,
        tailwind_score=25,
        alignment="HEADWIND",
        analysis="Sector IT in headwind",
        intraday_rs=-1.2,
        intraday_alignment="INTRADAY_HEADWIND",
    )

    with mock.patch(
        "market.quotes.get_quote",
        return_value={"NSE:INFY": quote, "NSE:NIFTY 50": DummyQuote(24500, 24450, 24480, 0.4)},
    ):
        with mock.patch("market.quotes.get_ltp", return_value=1550.0):
            with mock.patch("market.options.get_options_chain", return_value=contracts):
                with mock.patch("market.options.get_expiries", return_value=["2026-09-24"]):
                    with mock.patch("market.history.get_ohlcv", return_value=None):
                        with mock.patch(
                            "analysis.sector_rotation.get_stock_tailwind", return_value=tailwind
                        ):
                            with mock.patch(
                                "analysis.universe.get_stock_sector",
                                return_value=("it", "IT, Software & Technology"),
                            ):
                                alerts = detect_options_momentum_breakouts(
                                    targets=["INFY"],
                                    watched_indices=[],
                                    now_dt=now_dt,
                                )

    # Passed via extreme catalyst escape hatch!
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.metrics["is_extreme_catalyst"] is True
    assert "DECOUPLER" in alert.headline


def test_one_signal_per_sector_daily_throttle():
    """AutoAlertEngine limits stock option alerts to at most 1 signal per sector per day."""
    engine = AutoAlertEngine()
    now_dt = datetime(2026, 9, 23, 11, 0, tzinfo=IST)
    today_key = "2026-09-23"
    engine._sector_daily_dispatched[today_key].clear()

    # Create 3 candidate alerts: 2 in Banking (HDFCBANK, ICICIBANK) and 1 in IT (INFY)
    h_alert = AutoAlert(
        alert_id="TEST-HDFC",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="HDFCBANK",
        exchange="NFO",
        direction="BULLISH",
        headline="🟢 OPTIONS MOMENTUM [BANKING]: HDFCBANK 1700 CE",
        summary="High conviction banking breakout",
        ltp=34.0,
        trigger_level=34.0,
        target_level=45.0,
        stop_loss=28.0,
        strike=1700.0,
        option_type="CE",
        contract_symbol="HDFCBANK1700CE",
        segment="FNO_STOCK",
        confidence=92,
        metrics={
            "sector_id": "banking",
            "sector_name": "Banking & Financial Services",
            "vol_oi_ratio": 2.4,
            "sector_rs": 1.2,
        },
        actionable_plan={"fast_scalp": {"time_stop_mins": 20}},
        created_at=now_dt.strftime("%Y-%m-%d %H:%M:%S IST"),
    )

    i_alert = AutoAlert(
        alert_id="TEST-ICICI",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="ICICIBANK",
        exchange="NFO",
        direction="BULLISH",
        headline="🟢 OPTIONS MOMENTUM [BANKING]: ICICIBANK 1300 CE",
        summary="Secondary banking breakout",
        ltp=28.0,
        trigger_level=28.0,
        target_level=36.0,
        stop_loss=23.0,
        strike=1300.0,
        option_type="CE",
        contract_symbol="ICICIBANK1300CE",
        segment="FNO_STOCK",
        confidence=85,
        metrics={
            "sector_id": "banking",
            "sector_name": "Banking & Financial Services",
            "vol_oi_ratio": 1.5,
            "sector_rs": 1.2,
        },
        actionable_plan={"fast_scalp": {"time_stop_mins": 20}},
        created_at=now_dt.strftime("%Y-%m-%d %H:%M:%S IST"),
    )

    it_alert = AutoAlert(
        alert_id="TEST-INFY",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="INFY",
        exchange="NFO",
        direction="BULLISH",
        headline="🟢 OPTIONS MOMENTUM [IT]: INFY 1520 CE",
        summary="IT sector leader breakout",
        ltp=32.0,
        trigger_level=32.0,
        target_level=42.0,
        stop_loss=26.0,
        strike=1520.0,
        option_type="CE",
        contract_symbol="INFY1520CE",
        segment="FNO_STOCK",
        confidence=90,
        metrics={
            "sector_id": "it",
            "sector_name": "IT, Software & Technology",
            "vol_oi_ratio": 2.1,
            "sector_rs": 0.9,
        },
        actionable_plan={"fast_scalp": {"time_stop_mins": 20}},
        created_at=now_dt.strftime("%Y-%m-%d %H:%M:%S IST"),
    )

    with mock.patch(
        "engine.detectors.options_momentum.detect_options_momentum_breakouts",
        return_value=[h_alert, i_alert, it_alert],
    ):
        with mock.patch.object(engine, "record_alert", return_value=True):
            with mock.patch("engine.auto_alert_engine.datetime") as mock_dt:
                mock_dt.now.return_value = now_dt
                mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

                # Cycle 1: Dispatches #1 Banking (HDFCBANK) and #1 IT (INFY); suppresses ICICIBANK
                found = engine.scan_options_momentum_breakouts()

    assert len(found) == 2
    symbols_found = [a.symbol for a in found]
    assert "HDFCBANK" in symbols_found
    assert "INFY" in symbols_found
    assert "ICICIBANK" not in symbols_found  # Suppressed by 1-signal-per-sector daily cap!
    assert "LEADER 1/1" in found[0].headline

    assert "banking" in engine._sector_daily_dispatched[today_key]
    assert "it" in engine._sector_daily_dispatched[today_key]

    # Cycle 2: Same day, another banking alert arrives (e.g. SBIN)
    s_alert = AutoAlert(
        alert_id="TEST-SBIN",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="SBIN",
        exchange="NFO",
        direction="BULLISH",
        headline="🟢 OPTIONS MOMENTUM: SBIN 850 CE",
        summary="Late banking breakout",
        ltp=18.0,
        trigger_level=18.0,
        target_level=24.0,
        stop_loss=14.0,
        strike=850.0,
        option_type="CE",
        contract_symbol="SBIN850CE",
        segment="FNO_STOCK",
        confidence=94,
        metrics={
            "sector_id": "banking",
            "sector_name": "Banking & Financial Services",
            "vol_oi_ratio": 3.0,
        },
        actionable_plan={},
        created_at=now_dt.strftime("%Y-%m-%d %H:%M:%S IST"),
    )

    with mock.patch(
        "engine.detectors.options_momentum.detect_options_momentum_breakouts",
        return_value=[s_alert],
    ):
        with mock.patch.object(engine, "record_alert", return_value=True):
            with mock.patch("engine.auto_alert_engine.datetime") as mock_dt:
                mock_dt.now.return_value = now_dt
                mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

                found_c2 = engine.scan_options_momentum_breakouts()

    # SBIN is suppressed because Banking already had 1 signal today!
    assert len(found_c2) == 0
