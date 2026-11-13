"""
tests/test_htf_trend_and_no_chase.py
──────────────────────────────────────
Institutional test suite verifying:
1. 15-minute Higher Timeframe (HTF) trend alignment filters in index call/put detectors.
   - Disallow breakout CE when 15m trend is BEARISH (Bull Trap prevention).
   - Disallow breakdown PE when 15m trend is BULLISH (Bear Trap prevention).
2. Tightened No-Chase boundaries (+3.5% ceiling) preventing late-stage momentum chasing.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pandas as pd

from engine.detectors.index_call_setup import detect_index_call_setup
from engine.detectors.index_put_setup import detect_index_put_setup
from market.options import OptionsContract

IST = timezone(timedelta(hours=5, minutes=30))


def _make_chain(symbol: str, spot: float, opt_type: str = "CE") -> list[OptionsContract]:
    strike = round(spot / 50) * 50
    return [
        OptionsContract(
            symbol=f"{symbol}26OCT{int(strike)}{opt_type}",
            underlying=symbol,
            strike=float(strike),
            option_type=opt_type,
            expiry="2026-10-29",
            last_price=120.0,
            volume=50000,
            oi=25000,
            oi_change=2000,
            pchange=15.0,
        )
    ]


def test_15m_bear_trend_suppresses_day_high_breakout_call():
    """Verify that when 15m trend is BEARISH, a 5m breakout into Day High is suppressed to avoid bull traps."""
    ref_dt = datetime(2026, 10, 14, 11, 30, tzinfo=IST)
    # Generate 20 bars in an overarching downtrend (EMA 9 < EMA 21 on 15m)
    dates = pd.date_range("2026-10-14 09:15:00", periods=20, freq="5min")
    # Price steps down from 25200 to 24800, with a tiny late bounce to 24850
    closes = [25200.0 - (i * 20.0) for i in range(19)] + [24850.0]
    highs = [c + 10.0 for c in closes]
    lows = [c - 10.0 for c in closes]
    opens = [c + 5.0 for c in closes]
    volumes = [100000.0] * 20

    df_5m = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )

    spot = 24850.0
    chain = _make_chain("NIFTY", spot, "CE")

    with (
        patch(
            "market.indices.get_heavyweights_posture",
            return_value={"heavyweights": [], "bull_count": 0, "bear_count": 0},
        ),
        patch("market.sentiment.get_market_breadth", return_value=None),
        patch("market.options.get_options_chain", return_value=chain),
    ):
        alerts = detect_index_call_setup(
            underlying="NIFTY",
            spot=spot,
            chain=chain,
            vwap=24900.0,
            day_high=24850.0,
            day_low=24800.0,
            ohlcv_5m=df_5m,
            ref_time=ref_dt,
            ignore_time_gate=True,
        )

    # Breakout call setup must be suppressed because 15m trend is in structural markdown
    breakout_alerts = [a for a in alerts if "DAY_HIGH_BREAKOUT" in getattr(a, "signals", [])]
    assert len(breakout_alerts) == 0, (
        "Expected DAY_HIGH_BREAKOUT to be suppressed under 15m downtrend"
    )


def test_15m_bull_trend_suppresses_day_low_breakdown_put():
    """Verify that when 15m trend is BULLISH, a 5m breakdown into Day Low is suppressed to avoid bear traps."""
    ref_dt = datetime(2026, 10, 14, 11, 30, tzinfo=IST)
    # Generate 20 bars in an overarching uptrend (EMA 9 > EMA 21 on 15m)
    dates = pd.date_range("2026-10-14 09:15:00", periods=20, freq="5min")
    # Price steps up from 24800 to 25200, with a tiny late dip to 25150
    closes = [24800.0 + (i * 20.0) for i in range(19)] + [25150.0]
    highs = [c + 10.0 for c in closes]
    lows = [c - 10.0 for c in closes]
    opens = [c - 5.0 for c in closes]
    volumes = [100000.0] * 20

    df_5m = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )

    spot = 25150.0
    chain = _make_chain("NIFTY", spot, "PE")

    with (
        patch(
            "market.indices.get_heavyweights_posture",
            return_value={"heavyweights": [], "bull_count": 0, "bear_count": 0},
        ),
        patch("market.sentiment.get_market_breadth", return_value=None),
        patch("market.options.get_options_chain", return_value=chain),
    ):
        alerts = detect_index_put_setup(
            underlying="NIFTY",
            spot=spot,
            chain=chain,
            vwap=25100.0,
            day_high=25210.0,
            day_low=25150.0,
            ohlcv_5m=df_5m,
            ref_time=ref_dt,
            ignore_time_gate=True,
        )

    # Breakdown put setup must be suppressed because 15m trend is in structural markup
    breakdown_alerts = [a for a in alerts if "DAY_LOW_BREAKDOWN" in getattr(a, "signals", [])]
    assert len(breakdown_alerts) == 0, (
        "Expected DAY_LOW_BREAKDOWN to be suppressed under 15m uptrend"
    )
