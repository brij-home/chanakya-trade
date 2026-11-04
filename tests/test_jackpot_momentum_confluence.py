"""
tests/test_jackpot_momentum_confluence.py
─────────────────────────────────────────
Comprehensive test suite for the 🚀 Jackpot Momentum Ignition detector:
Verifies Multi-Pillar Confluence (Volatility Coiling, Liquidity Headroom,
Order Book / Volume Thrust, and Sector Relative Strength).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from engine.asymmetric_radar import AsymmetricOpportunityRadar
from engine.auto_alert_engine import AutoAlertEngine
from bot.alert_templates import render_auto_alert


def _create_synthetic_coiling_df(
    base_price: float = 2500.0,
    n_bars: int = 30,
    mode: str = "breakout",  # "breakout", "breakdown", "drift"
) -> pd.DataFrame:
    """Creates a synthetic 5m OHLCV DataFrame with volatility compression coiling."""
    rng = np.random.default_rng(42)
    # 25 bars of tight coiling (0.2% range)
    tight_noise = rng.normal(0, base_price * 0.001, 25)
    coiling_closes = base_price + tight_noise

    # Last 5 bars: if breakout, surge up; if breakdown, plunge down; else drift
    if mode == "breakout":
        expansion = np.array(
            [
                base_price * 1.002,
                base_price * 1.005,
                base_price * 1.008,
                base_price * 1.012,
                base_price * 1.018,
            ]
        )
        closes = np.concatenate([coiling_closes, expansion])
    elif mode == "breakdown":
        contraction = np.array(
            [
                base_price * 0.998,
                base_price * 0.995,
                base_price * 0.992,
                base_price * 0.988,
                base_price * 0.982,
            ]
        )
        closes = np.concatenate([coiling_closes, contraction])
    else:
        drift = base_price + rng.normal(0, base_price * 0.005, 5)
        closes = np.concatenate([coiling_closes, drift])

    highs = closes + (base_price * 0.001)
    lows = closes - (base_price * 0.001)
    opens = np.roll(closes, 1)
    opens[0] = closes[0]

    # Volumes: normal in base, 2.8x surge on last bar if breakout or breakdown
    volumes = np.ones(len(closes)) * 10000.0
    if mode in ("breakout", "breakdown"):
        volumes[-1] = 28000.0  # 2.8x RVOL surge!

    return pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )


class TestJackpotMomentumConfluence:
    """Verifies that Jackpot Momentum Ignition detects genuine coiling breakouts."""

    def test_jackpot_confluence_detection_on_coiled_breakout(self, monkeypatch):
        radar = AsymmetricOpportunityRadar(min_rr=3.0, min_conviction=75)
        df = _create_synthetic_coiling_df(base_price=2500.0, mode="breakout")
        ltp = float(df["close"].iloc[-1])
        day_high = ltp * 1.001  # At day high

        quote = {
            "last_price": ltp,
            "ltp": ltp,
            "vwap": 2510.0,
            "change_pct": 1.8,
            "high": day_high,
            "low": 2490.0,
            "volume": 500000,
        }

        # Mock sector quote to provide positive sector tailwind
        monkeypatch.setattr(
            "market.quotes.get_quote",
            lambda sym: type("Quote", (), {"change_pct": 0.85})(),
        )

        opp = radar.detect_jackpot_momentum_confluence("RELIANCE", quote=quote, df=df)

        assert opp is not None
        assert opp.setup_type == "JACKPOT_MOMENTUM_CONFLUENCE"
        assert opp.direction == "BULLISH"
        assert opp.conviction_score >= 80
        assert opp.risk_reward_ratio >= 3.5
        assert "Multi-pillar confluence" in opp.catalyst_summary

        # Verify strict monotonic invariant: SL < Entry < T1 < T2 < Moonshot
        assert opp.stop_loss < opp.entry_price < opp.target_1 < opp.target_2 < opp.target_moonshot

    def test_jackpot_confluence_detection_on_coiled_breakdown(self, monkeypatch):
        radar = AsymmetricOpportunityRadar(min_rr=3.0, min_conviction=75)
        df = _create_synthetic_coiling_df(base_price=2500.0, mode="breakdown")
        ltp = float(df["close"].iloc[-1])
        day_low = ltp * 0.999  # Piercing day low

        quote = {
            "last_price": ltp,
            "ltp": ltp,
            "vwap": 2490.0,
            "change_pct": -1.8,
            "high": 2515.0,
            "low": day_low,
            "volume": 500000,
        }

        # Mock sector quote to provide sector breakdown tailwind
        monkeypatch.setattr(
            "market.quotes.get_quote",
            lambda sym: type("Quote", (), {"change_pct": -0.95})(),
        )

        opp = radar.detect_jackpot_momentum_confluence("RELIANCE", quote=quote, df=df)

        assert opp is not None
        assert opp.setup_type == "JACKPOT_MOMENTUM_CONFLUENCE"
        assert opp.direction == "BEARISH"
        assert opp.conviction_score >= 80
        assert opp.risk_reward_ratio >= 3.5

        # Verify strict bearish monotonic invariant: Moonshot < T2 < T1 < Entry < SL
        assert opp.target_moonshot < opp.target_2 < opp.target_1 < opp.entry_price < opp.stop_loss

    def test_jackpot_rejected_when_volatility_is_loose(self):
        radar = AsymmetricOpportunityRadar(min_rr=3.0, min_conviction=78)
        # Create uncoiled, wide random walk
        rng = np.random.default_rng(99)
        wide_closes = 2500.0 + np.cumsum(rng.normal(0, 35.0, 30))
        wide_df = pd.DataFrame(
            {
                "open": wide_closes,
                "high": wide_closes + 25.0,
                "low": wide_closes - 25.0,
                "close": wide_closes,
                "volume": np.ones(30) * 10000.0,
            }
        )
        ltp = float(wide_df["close"].iloc[-1])
        quote = {
            "last_price": ltp,
            "ltp": ltp,
            "vwap": ltp,
            "change_pct": 0.1,
            "high": ltp + 50.0,
            "low": ltp - 50.0,
            "volume": 10000,
        }

        opp = radar.detect_jackpot_momentum_confluence("TCS", quote=quote, df=wide_df)
        # Should return None because volatility is loose and no coiling/thrust is present
        assert opp is None

    def test_auto_alert_engine_jackpot_integration(self, monkeypatch):
        engine = AutoAlertEngine()
        radar = AsymmetricOpportunityRadar(min_rr=3.0, min_conviction=75)
        df = _create_synthetic_coiling_df(base_price=50000.0, mode="breakout")
        ltp = float(df["close"].iloc[-1])

        quote = {
            "last_price": ltp,
            "ltp": ltp,
            "vwap": ltp * 0.995,
            "change_pct": 1.2,
            "high": ltp * 1.001,
            "low": ltp * 0.990,
            "volume": 200000,
        }

        # Mock scan_asymmetric_opportunities on radar to return a jackpot opp
        opp = radar.detect_jackpot_momentum_confluence("BANKNIFTY", quote=quote, df=df)
        assert opp is not None

        monkeypatch.setattr(
            "engine.asymmetric_radar.asymmetric_radar.scan_asymmetric_opportunities",
            lambda top_n=6: [opp],
        )

        alerts = engine.scan_asymmetric_opportunities()
        assert len(alerts) >= 1
        jackpot_alert = alerts[0]

        assert "JACKPOT MOMENTUM IGNITION" in jackpot_alert.headline
        assert jackpot_alert.confidence >= 80
        assert jackpot_alert.is_do_not_miss is True

        # Verify formatting for Telegram
        tg_text = render_auto_alert(jackpot_alert)
        assert "JACKPOT MOMENTUM IGNITION" in tg_text
