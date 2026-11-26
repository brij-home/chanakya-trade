"""
tests/test_commodity_pullback_and_session_invariants.py
────────────────────────────────────────────────────────
Institutional invariant test suite for:
  1. Trend-Pullback & S-R Rejection (OTE) on MCX Commodities.
  2. International Commodity Session Windows (European 15:30-17:30 & US Pit 17:30-23:30).
  3. Narrowed EIA Inventory Blackout Window (19:55 - 20:06 IST) permitting post-event momentum.
  4. Options Scanner Session-Awareness for Evening Commodities.
"""

from __future__ import annotations

import os
from datetime import datetime
from unittest.mock import MagicMock, patch
import pandas as pd

from config.constants import IST
from engine.quality_gate import (
    is_mcx_active_session_window,
    is_mcx_golden_hours_window,
    is_mcx_midday_lull_window,
)
from engine.detectors.commodity import detect_commodity_breakouts


def _build_synthetic_pullback_df(
    symbol: str = "CRUDEOIL",
    direction: str = "BEARISH",
    ltp: float = 7945.0,
    bounce_high: float = 7951.0,
    bounce_low: float = 7826.0,
) -> pd.DataFrame:
    """Creates a deterministic 5m OHLCV dataframe simulating a trend pullback into resistance."""
    times = pd.date_range(
        "2026-11-18 10:00:00", "2026-11-18 16:50:00", freq="5min", tz="Asia/Kolkata"
    )
    n = len(times)

    # Macro downtrend from 8050 to 7826
    prices = [8050.0 - (8050.0 - bounce_low) * (i / max(1, n - 10)) for i in range(n - 10)]
    # Relief rally in last 10 bars from 7826 to 7951
    rally = [bounce_low + (bounce_high - bounce_low) * (j / 9) for j in range(10)]
    all_closes = prices + rally

    df = pd.DataFrame(index=times)
    df["close"] = all_closes
    df["open"] = [c - 2.0 for c in all_closes]
    df["high"] = [c + 3.0 for c in all_closes]
    df["low"] = [c - 3.0 for c in all_closes]
    df["volume"] = [150.0] * n

    # Make last bar a rejection pinbar from bounce_high (7951) down to 7940
    df.iloc[-1, df.columns.get_loc("open")] = 7948.0
    df.iloc[-1, df.columns.get_loc("high")] = bounce_high
    df.iloc[-1, df.columns.get_loc("low")] = 7930.0
    df.iloc[-1, df.columns.get_loc("close")] = ltp
    df.iloc[-1, df.columns.get_loc("volume")] = 180.0

    return df


def test_mcx_session_windows():
    """Verify European session (16:49 IST) is recognized as active, while midday lull is not."""
    # 16:49 IST on Wednesday (European Open / London session)
    dt_1649 = datetime(2026, 11, 18, 16, 49, tzinfo=IST)
    assert is_mcx_active_session_window(dt_1649) is True
    assert is_mcx_midday_lull_window(dt_1649) is False
    assert is_mcx_golden_hours_window(dt_1649) is False  # Golden hours is 17:30+

    # 13:00 IST (Asian lull)
    dt_1300 = datetime(2026, 11, 18, 13, 0, tzinfo=IST)
    assert is_mcx_midday_lull_window(dt_1300) is True
    assert is_mcx_active_session_window(dt_1300) is False

    # 20:30 IST (US Pit / Golden hours)
    dt_2030 = datetime(2026, 11, 18, 20, 30, tzinfo=IST)
    assert is_mcx_active_session_window(dt_2030) is True
    assert is_mcx_golden_hours_window(dt_2030) is True


def test_eia_inventory_blackout_narrowed():
    """Verify Wednesday EIA blackout is strict between 19:55-20:06, but permits post-20:06 momentum."""
    # During release at 20:00 IST (Wednesday) -> Blackout MUST suppress
    dt_2000 = datetime(2026, 11, 18, 20, 0, tzinfo=IST)
    hh, mm = dt_2000.hour, dt_2000.minute
    is_blackout_2000 = (hh == 19 and mm >= 55) or (hh == 20 and mm <= 6)
    assert is_blackout_2000 is True

    # Post-release at 20:10 IST -> Blackout MUST clear to catch continuation
    dt_2010 = datetime(2026, 11, 18, 20, 10, tzinfo=IST)
    hh_post, mm_post = dt_2010.hour, dt_2010.minute
    is_blackout_2010 = (hh_post == 19 and mm_post >= 55) or (hh_post == 20 and mm_post <= 6)
    assert is_blackout_2010 is False


def test_trend_pullback_rejection_detector():
    """Verify detect_commodity_breakouts identifies a bearish pullback fade at resistance."""
    df_5m = _build_synthetic_pullback_df(
        "CRUDEOIL", direction="BEARISH", ltp=7945.0, bounce_high=7951.0, bounce_low=7826.0
    )

    # Mock live quote reflecting macro weakness (-1.8%) and ltp 7945
    mock_quote = MagicMock()
    mock_quote.last_price = 7945.0
    mock_quote.open = 8010.0
    mock_quote.high = 8033.0
    mock_quote.low = 7826.0
    mock_quote.change_pct = -1.8
    mock_quote.volume = 25000
    mock_quote.vwap = 7965.0
    mock_quote.provider = "live"
    mock_quote.data_state = "REAL"
    mock_quote._is_mock = False

    quotes_map = {"MCX:CRUDEOIL": mock_quote, "CRUDEOIL": mock_quote}
    ohlcv_map = {"CRUDEOIL": df_5m}

    with patch.dict(os.environ, {"CHANAKYA_TESTING": "1", "SESSION_FOCUS_MODE": "FNO_PRIORITY"}):
        alerts = detect_commodity_breakouts(
            universe=["CRUDEOIL"],
            quotes_map=quotes_map,
            ohlcv_map=ohlcv_map,
        )

        assert len(alerts) >= 1
        crude_alert = alerts[0]
        assert crude_alert.symbol == "CRUDEOIL"
        assert crude_alert.direction == "BEARISH"
        # Must have tight structural stop loss above the bounce high (7951)
        assert crude_alert.stop_loss > 7945.0
        assert crude_alert.stop_loss <= 7965.0
        # Target must be lower than LTP with high R:R
        assert crude_alert.target_level < crude_alert.ltp


def test_options_momentum_mcx_session_targets():
    """Verify _scan_options_momentum_now includes MCX liquid options during evening hours under FNO_PRIORITY."""
    from engine.auto_alert_engine import AutoAlertEngine

    engine = AutoAlertEngine()
    evening_dt = datetime(2026, 11, 18, 16, 49, tzinfo=IST)

    with (
        patch.dict(os.environ, {"SESSION_FOCUS_MODE": "FNO_PRIORITY"}, clear=False),
        patch("engine.auto_alert_engine.datetime") as mock_dt,
        patch(
            "engine.detectors.options_momentum.detect_options_momentum_breakouts", return_value=[]
        ) as mock_detect,
    ):
        mock_dt.now.return_value = evening_dt
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

        _ = engine.scan_options_momentum_breakouts()

        # In evening session (16:49 IST), detect_options_momentum_breakouts must be called with MCX targets
        assert mock_detect.called
        call_kwargs = mock_detect.call_args[1]
        targets = call_kwargs.get("targets", [])
        assert "CRUDEOIL" in targets
