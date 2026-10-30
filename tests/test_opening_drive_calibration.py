"""
tests/test_opening_drive_calibration.py
───────────────────────────────────────
Deterministic unit tests for calibrated Opening Drive Detector (09:15–09:25 IST).
Verifies:
  1. Bullish Opening Drive (Open == Low) on Nifty & Bank Nifty with zero lower wick.
  2. Bearish Opening Drive (Open == High) on Equities & Indices with zero upper wick.
  3. Seamless integration with unified VIX-regime aware option resolver.
  4. Automatic defined-risk spread attachment when India VIX is elevated (>= 19.0).
  5. Synthetic Spot Stop Loss anchoring to protect against freak option premium wicks.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd

from engine.detectors.opening_drive import detect_opening_drive
from engine.synthetic_sl import evaluate_synthetic_spot_sl

IST = ZoneInfo("Asia/Kolkata")


def _make_opening_bar(
    open_p: float, high_p: float, low_p: float, close_p: float, vol: float = 150000.0
) -> pd.DataFrame:
    """Helper to construct 5m OHLCV bar for today's open."""
    now_dt = datetime(2026, 10, 12, 9, 20, tzinfo=IST)
    df = pd.DataFrame(
        [
            {
                "open": open_p,
                "high": high_p,
                "low": low_p,
                "close": close_p,
                "volume": vol,
            }
        ],
        index=pd.to_datetime([now_dt]),
    )
    return df


def test_bullish_opening_drive_nifty(monkeypatch):
    """Verify textbook Bullish Opening Drive (Open == Low) on Nifty."""
    # Nifty opens at 25,000, low is 25,000 (0 wick), high 25,080, close 25,075 (expanded +0.32%)
    df = _make_opening_bar(25000.0, 25080.0, 25000.0, 25075.0)

    # Mock heavyweights posture to be bullish
    monkeypatch.setattr(
        "market.indices.get_heavyweights_posture",
        lambda *args, **kwargs: {
            "heavyweights": [{"symbol": "HDFCBANK", "change_pct": 1.2}],
            "bull_count": 4,
            "bear_count": 0,
            "all_bearish": False,
        },
    )

    alert = detect_opening_drive(
        symbol="NIFTY",
        df_5m=df,
        ltp=25075.0,
        prev_close=24950.0,
        prev_high=25020.0,
        ref_time=datetime(2026, 10, 12, 9, 20, tzinfo=IST),
        ignore_time_gate=True,
    )

    assert alert is not None
    assert alert.alert_type == "OPENING_DRIVE_IGNITION"
    assert alert.direction == "BULLISH"
    assert alert.symbol == "NIFTY"
    assert alert.confidence >= 92

    # Check synthetic spot SL anchors
    assert alert.metrics.get("spot_invalidation_anchor") is not None
    assert alert.metrics["underlying_symbol"] == "NIFTY"
    assert alert.actionable_plan["underlying_sl"] is not None

    # Verify that freak option wick is shielded using the synthetic spot SL engine
    eval_res = evaluate_synthetic_spot_sl(
        alert=alert,
        current_option_ltp=float(alert.stop_loss) * 0.95,  # Option dipped below nominal SL
        current_spot_override=25060.0,  # But spot is 25,060 (safely above 24,950 anchor)
    )
    assert eval_res.is_invalidated is False
    assert eval_res.is_freak_wick_shielded is True


def test_bearish_opening_drive_banknifty(monkeypatch):
    """Verify Bearish Opening Drive (Open == High) on Bank Nifty."""
    # Bank Nifty opens at 55,000, high is 55,000, low 54,750, close 54,760 (-0.45% expansion)
    df = _make_opening_bar(55000.0, 55000.0, 54750.0, 54760.0)

    monkeypatch.setattr(
        "market.indices.get_heavyweights_posture",
        lambda *args, **kwargs: {
            "heavyweights": [{"symbol": "HDFCBANK", "change_pct": -1.5}],
            "bull_count": 0,
            "bear_count": 4,
            "all_bullish": False,
        },
    )
    monkeypatch.setattr("engine.daily_levels.get_daily_levels", lambda *args, **kwargs: None)

    alert = detect_opening_drive(
        symbol="BANKNIFTY",
        df_5m=df,
        ltp=54760.0,
        prev_close=55100.0,
        prev_low=54900.0,
        ref_time=datetime(2026, 10, 12, 9, 20, tzinfo=IST),
        ignore_time_gate=True,
    )

    assert alert is not None
    assert alert.direction == "BEARISH"
    assert alert.symbol == "BANKNIFTY"
    assert alert.metrics["spot_invalidation_anchor"] is not None


def test_high_vix_attaches_defined_risk_spread(monkeypatch):
    """Verify high India VIX (>= 19.0) attaches hedged vertical spread to Opening Drive alert."""
    df = _make_opening_bar(25000.0, 25090.0, 25000.0, 25085.0)

    monkeypatch.setattr(
        "market.indices.get_heavyweights_posture",
        lambda *args, **kwargs: {"bull_count": 3, "bear_count": 0},
    )
    # Mock VIX to 21.0
    monkeypatch.setattr("market.indices.get_vix", lambda: 21.0)

    alert = detect_opening_drive(
        symbol="NIFTY",
        df_5m=df,
        ltp=25085.0,
        prev_close=24900.0,
        ref_time=datetime(2026, 10, 12, 9, 20, tzinfo=IST),
        ignore_time_gate=True,
    )

    assert alert is not None
    # Actionable plan must mandate hedged spread
    assert alert.actionable_plan.get("execution_style_mandate") == "HEDGED_SPREAD_MANDATORY"
    assert "hedged_spread" in alert.actionable_plan
    spread = alert.actionable_plan["hedged_spread"]
    assert spread["strategy_name"] == "BULL_CALL_SPREAD"
    assert len(spread["legs"]) == 2
    assert spread["legs"][0]["side"] == "BUY"
    assert spread["legs"][1]["side"] == "SELL"
