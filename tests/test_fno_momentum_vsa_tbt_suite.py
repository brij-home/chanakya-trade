"""
tests/test_fno_momentum_vsa_tbt_suite.py
─────────────────────────────────────────
Comprehensive integration and invariant test suite for:
  1. Stock F&O Decoupling from broad index markdown in options_momentum.py
  2. Midday lull volume relaxation (1.35x vs 2.5x) and afternoon spread conversion
  3. Fyers Prime TBT 15-slot dynamic priority pool rotation
  4. Volume Price Spread Analysis (VSA) Tom Williams signals
  5. Anchored VWAP (AVWAP) intraday anchors (09:15 Open & 09:30 ORB)
  6. Telegram alert rendering of institutional flow footprint badges
"""

import pandas as pd
import numpy as np
from types import SimpleNamespace
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from analysis.vsa import analyse_vsa
from analysis.anchored_vwap import detect_intraday_anchors
from market.fyers_tbt_manager import fyers_tbt_manager
from bot.alert_templates import render_fno_alert, render_auto_alert
from engine.alert_model import AutoAlert
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
        oi_change: int = 1200,
        expiry: str = "2026-11-26",
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
        self.bid = last_price * 0.99
        self.ask = last_price * 1.01
        self.expiry = expiry


class DummyQuote:
    def __init__(self, ltp: float, open_p: float, vwap: float, chg: float = 1.85):
        self.last_price = ltp
        self.ltp = ltp
        self.open = open_p
        self.vwap = vwap
        self.change_pct = chg
        self.high = ltp * 1.008
        self.low = open_p * 0.995


class TestVSAEngine:
    """Verifies Tom Williams & Wyckoff Volume Price Spread Analysis logic."""

    def test_stopping_volume_absorption(self):
        dates = pd.date_range("2026-11-05 09:15", periods=25, freq="5min", tz=IST)
        df = pd.DataFrame(
            {
                "open": [100.0] * 25,
                "high": [101.0] * 25,
                "low": [99.0] * 25,
                "close": [100.0] * 25,
                "volume": [1000] * 25,
            },
            index=dates,
        )

        df.iloc[-1, df.columns.get_loc("open")] = 100.0
        df.iloc[-1, df.columns.get_loc("high")] = 100.5
        df.iloc[-1, df.columns.get_loc("low")] = 96.0
        df.iloc[-1, df.columns.get_loc("close")] = 99.5
        df.iloc[-1, df.columns.get_loc("volume")] = 3500

        snap = analyse_vsa(df, symbol="RELIANCE", is_intraday=True)
        assert snap.vsa_signal == "STOPPING_VOLUME"
        assert snap.bias == "BULLISH"
        assert snap.conviction_modifier > 0
        assert "Stopping Volume" in snap.summary

    def test_effort_vs_result_bearish_climax(self):
        dates = pd.date_range("2026-11-05 09:15", periods=25, freq="5min", tz=IST)
        df = pd.DataFrame(
            {
                "open": [100.0] * 25,
                "high": [102.0] * 25,
                "low": [98.0] * 25,
                "close": [100.0] * 25,
                "volume": [1000] * 25,
            },
            index=dates,
        )

        df.iloc[-1, df.columns.get_loc("open")] = 101.0
        df.iloc[-1, df.columns.get_loc("high")] = 101.5
        df.iloc[-1, df.columns.get_loc("low")] = 100.7
        df.iloc[-1, df.columns.get_loc("close")] = 100.8
        df.iloc[-1, df.columns.get_loc("volume")] = 3200

        snap = analyse_vsa(df, symbol="INFY", is_intraday=True)
        assert snap.vsa_signal == "EFFORT_NO_RESULT_BEARISH"
        assert snap.bias == "BEARISH"
        assert snap.conviction_modifier < 0
        assert snap.is_fake_breakout_risk is True

    def test_absorption_breakout(self):
        dates = pd.date_range("2026-11-05 09:15", periods=25, freq="5min", tz=IST)
        df = pd.DataFrame(
            {
                "open": [100.0] * 25,
                "high": [101.0] * 25,
                "low": [99.0] * 25,
                "close": [100.0] * 25,
                "volume": [1000] * 25,
            },
            index=dates,
        )

        df.iloc[-1, df.columns.get_loc("open")] = 100.0
        df.iloc[-1, df.columns.get_loc("high")] = 106.0
        df.iloc[-1, df.columns.get_loc("low")] = 99.8
        df.iloc[-1, df.columns.get_loc("close")] = 105.8
        df.iloc[-1, df.columns.get_loc("volume")] = 2600

        snap = analyse_vsa(df, symbol="TCS", is_intraday=True)
        assert snap.vsa_signal == "ABSORPTION_BREAKOUT"
        assert snap.bias == "BULLISH"
        assert snap.conviction_modifier >= 10


class TestAnchoredVWAPEngine:
    """Verifies intraday anchor detection from 09:15 and 09:30 ORB."""

    def test_intraday_anchors_bullish_above_both(self):
        dates = pd.date_range("2026-11-05 09:15", periods=20, freq="5min", tz=IST)
        closes = np.linspace(24000, 24300, 20)
        df = pd.DataFrame(
            {
                "open": closes - 10,
                "high": closes + 15,
                "low": closes - 15,
                "close": closes,
                "volume": [5000] * 20,
            },
            index=dates,
        )

        anchors = detect_intraday_anchors(df, spot_price=24300.0)
        assert anchors["bias"] == "BULLISH"
        assert anchors["above_session_vwap"] is True
        assert anchors["above_orb_vwap"] is True
        assert anchors["session_vwap"] > 0
        assert anchors["orb_vwap"] > 0
        assert "Spot" in anchors["summary"]

    def test_intraday_anchors_bearish_below_both(self):
        dates = pd.date_range("2026-11-05 09:15", periods=20, freq="5min", tz=IST)
        closes = np.linspace(24500, 24100, 20)
        df = pd.DataFrame(
            {
                "open": closes + 10,
                "high": closes + 15,
                "low": closes - 15,
                "close": closes,
                "volume": [5000] * 20,
            },
            index=dates,
        )

        anchors = detect_intraday_anchors(df, spot_price=24050.0)
        assert anchors["bias"] == "BEARISH"
        assert anchors["above_session_vwap"] is False
        assert anchors["above_orb_vwap"] is False


class TestFyersTBTPriorityGridRotation:
    """Verifies dynamic pool rotation of the 15-slot 50-Depth TBT pool."""

    def test_auto_rotate_dynamic_grid_preserves_anchor_indices(self):
        top_movers = ["NSE:TATAMOTORS-EQ", "NSE:RELIANCE-EQ", "NSE:BAJFINANCE-EQ", "NSE:MARUTI-EQ"]
        rotated = fyers_tbt_manager.auto_rotate_dynamic_grid(top_movers)

        assert isinstance(rotated, list)
        assert len(rotated) <= 15
        assert any("RELIANCE" in s for s in rotated)
        assert any("HDFCBANK" in s for s in rotated)


class TestTelegramAlertFootprintBadges:
    """Verifies rendering of institutional flow badges (OBV, DMI, VSA, AVWAP)."""

    def test_render_fno_alert_surfaces_flow_badges(self):
        fno_dict = {
            "underlying": "NIFTY",
            "contract": "NIFTY 24500 CE",
            "option_type": "CE",
            "premium": 150.0,
            "entry_range": "₹145 – ₹152",
            "stop_loss": 120.0,
            "target_1": 195.0,
            "target_2": 240.0,
            "risk_reward": "1:2.5",
            "vol_oi_ratio": 2.4,
            "imbalance_ratio": 1.8,
            "score": 88,
            "obv_divergence": "BULLISH_DIVERGENCE",
            "dmi_triple_verdict": "TRIPLE_BULLISH_CONFIRMED",
            "vsa_signal": "STOPPING_VOLUME",
            "avwap_bias": "BULLISH",
            "environment": "LIVE",
            "is_live": True,
        }
        msg = render_fno_alert(fno_dict)
        assert "Flow:" in msg
        assert "OBV: Bullish Divergence" in msg
        assert "Triple-DMI: Triple Bullish Confirmed" in msg
        assert "VSA: Stopping Volume" in msg
        assert "AVWAP: Bullish" in msg

    def test_render_auto_alert_includes_flow_in_signals(self):
        alert = AutoAlert(
            alert_id="aa-call-nifty-20261105",
            alert_type="INDEX_CALL_SETUP",
            stage="IGNITED",
            symbol="NIFTY",
            exchange="NFO",
            direction="BULLISH",
            headline="NIFTY 24500 CE · Institutional Thrust",
            summary="SMC Demand Rejection at PDL",
            ltp=150.0,
            trigger_level=150.0,
            strike=24500,
            option_type="CE",
            contract_symbol="NIFTY 24500 CE",
            stop_loss=120.0,
            target_level=195.0,
            metrics={
                "obv_divergence": "BULLISH_DIVERGENCE",
                "dmi_triple_verdict": "TRIPLE_BULLISH_CONFIRMED",
                "vsa_signal": "ABSORPTION_BREAKOUT",
                "avwap_bias": "BULLISH",
            },
        )
        msg = render_auto_alert(alert, in_market=True)
        assert "OBV: Bullish Divergence" in msg
        assert "Triple-DMI: Triple Bullish Confirmed" in msg
        assert "VSA: Absorption Breakout" in msg
        assert "AVWAP: Bullish" in msg


class TestOptionsMomentumDecouplingAndMidday:
    """Verifies that stock F&O setups decouple from index markdown and handle midday lull & spreads."""

    def test_stock_fno_call_decouples_from_nifty_markdown(self):
        now_dt = datetime(2026, 11, 5, 10, 15, tzinfo=IST)
        tata_quote = DummyQuote(ltp=998.0, open_p=980.0, vwap=988.0, chg=1.85)
        # NIFTY is in structural markdown (-0.6% drop)
        nifty_quote = DummyQuote(ltp=24100.0, open_p=24250.0, vwap=24200.0, chg=-0.60)
        quotes = {
            "NSE:TATAMOTORS": tata_quote,
            "NSE:TMPV": tata_quote,
            "TMPV": tata_quote,
            "NSE:NIFTY 50": nifty_quote,
            "NSE:NIFTY50-INDEX": nifty_quote,
        }

        contracts = [
            DummyOptionContract(
                "TATAMOTORS1000CE", 1000.0, "CE", 45.0, volume=12000, oi=5000, pchange=14.0
            )
        ]

        tailwind = StockTailwind(
            symbol="TATAMOTORS",
            sector="AUTO",
            quadrant="LEADING",
            rs_ratio=104.5,
            rs_momentum=102.8,
            tailwind_score=88,
            alignment="STRONG_TAILWIND",
            analysis="Sector AUTO leading",
            intraday_rs=1.5,
            intraday_alignment="STRONG_INTRADAY_TAILWIND",
        )

        with patch("market.quotes.get_quote", return_value=quotes):
            with patch("market.quotes.get_ltp", return_value=998.0):
                with patch("market.options.get_options_chain", return_value=contracts):
                    with patch("market.options.get_expiries", return_value=["2026-11-26"]):
                        with patch("market.history.get_ohlcv", return_value=None):
                            with patch(
                                "engine.daily_levels.get_daily_levels",
                                return_value=SimpleNamespace(cpr={}, camarilla={}),
                            ):
                                with patch(
                                    "analysis.sector_rotation.get_stock_tailwind",
                                    return_value=tailwind,
                                ):
                                    with patch(
                                        "analysis.universe.get_stock_sector",
                                        return_value=("auto", "Automotive"),
                                    ):
                                        alerts = detect_options_momentum_breakouts(
                                            targets=["TATAMOTORS"],
                                            watched_indices=[],
                                            now_dt=now_dt,
                                        )

        # Before fix: This was strictly suppressed (0 alerts) because Nifty was down.
        # After holistic fix: Individual momentum decouples and fires the alert!
        assert len(alerts) == 1
        assert alerts[0].symbol in ("TATAMOTORS", "TMPV")
        assert alerts[0].option_type == "CE"
        assert alerts[0].direction == "BULLISH"

    def test_afternoon_converts_to_spread_only(self):
        # Post 14:45 IST (14:50 IST)
        now_dt = datetime(2026, 11, 5, 14, 50, tzinfo=IST)
        tata_quote = DummyQuote(ltp=1010.0, open_p=980.0, vwap=995.0, chg=2.8)
        quotes = {
            "NSE:TATAMOTORS": tata_quote,
            "NSE:TMPV": tata_quote,
            "TMPV": tata_quote,
            "NSE:NIFTY 50": DummyQuote(24300.0, 24200.0, 24250.0, 0.4),
            "NSE:NIFTY50-INDEX": DummyQuote(24300.0, 24200.0, 24250.0, 0.4),
        }

        contracts = [
            DummyOptionContract(
                "TATAMOTORS1020CE", 1020.0, "CE", 42.0, volume=15000, oi=5000, pchange=18.0
            )
        ]

        tailwind = StockTailwind(
            symbol="TATAMOTORS",
            sector="AUTO",
            quadrant="LEADING",
            rs_ratio=105.0,
            rs_momentum=103.0,
            tailwind_score=90,
            alignment="STRONG_TAILWIND",
            analysis="Leading",
            intraday_rs=1.8,
            intraday_alignment="STRONG_INTRADAY_TAILWIND",
        )

        with patch("market.quotes.get_quote", return_value=quotes):
            with patch("market.quotes.get_ltp", return_value=1010.0):
                with patch("market.options.get_options_chain", return_value=contracts):
                    with patch("market.options.get_expiries", return_value=["2026-11-26"]):
                        with patch("market.history.get_ohlcv", return_value=None):
                            with patch(
                                "engine.daily_levels.get_daily_levels",
                                return_value=SimpleNamespace(cpr={}, camarilla={}),
                            ):
                                with patch(
                                    "analysis.sector_rotation.get_stock_tailwind",
                                    return_value=tailwind,
                                ):
                                    with patch(
                                        "analysis.universe.get_stock_sector",
                                        return_value=("auto", "Automotive"),
                                    ):
                                        alerts = detect_options_momentum_breakouts(
                                            targets=["TATAMOTORS"],
                                            watched_indices=[],
                                            now_dt=now_dt,
                                        )

        assert len(alerts) == 1
        # In afternoon post 14:45, naked options are capped or mandated as defined-risk spreads
        assert alerts[0].preferred_vehicle == "SPREAD_ONLY"
        assert alerts[0].metrics.get("mandate_spread_afternoon") is True
