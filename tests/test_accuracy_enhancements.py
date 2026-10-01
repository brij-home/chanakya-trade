"""
tests/test_accuracy_enhancements.py
───────────────────────────────────
Unit tests for the Institutional Accuracy & Asymmetric R:R Enhancements:
  1. Multi-Timeframe Alignment (compute_mtf_alignment)
  2. ADR (Average Daily Range) Exhaustion Gate
  3. Circuit Limit Headroom Gate
  4. Midday Liquidity Lull Gate (11:30–13:15 IST)
  5. TradePlan ADR Exhaustion Note
"""

import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from analysis.market_structure import compute_mtf_alignment
from engine.alert_scrutiny import AlertScrutinyAuditor
from engine.trade_plan import calculate_trade_plan

IST = timezone(timedelta(hours=5, minutes=30))


# ── 1. Multi-Timeframe (MTF) Alignment Tests ─────────────────────────────────


def test_compute_mtf_alignment_bullish():
    """Verify that compute_mtf_alignment detects full bullish alignment."""
    # 5m: trending up
    dates_5m = pd.date_range("2026-09-23 09:15", periods=20, freq="5min")
    df_5m = pd.DataFrame(
        {
            "open": np.linspace(100, 110, 20),
            "high": np.linspace(101, 111, 20),
            "low": np.linspace(99.5, 109.5, 20),
            "close": np.linspace(100.5, 110.5, 20),
            "volume": [10000] * 20,
        },
        index=dates_5m,
    )

    # 15m: trending up
    dates_15m = pd.date_range("2026-09-20 09:15", periods=20, freq="15min")
    df_15m = pd.DataFrame(
        {
            "open": np.linspace(90, 110, 20),
            "high": np.linspace(92, 112, 20),
            "low": np.linspace(89, 109, 20),
            "close": np.linspace(91, 111, 20),
            "volume": [25000] * 20,
        },
        index=dates_15m,
    )

    # Daily: trending up
    dates_d = pd.date_range("2026-08-01", periods=30, freq="B")
    df_d = pd.DataFrame(
        {
            "open": np.linspace(80, 110, 30),
            "high": np.linspace(82, 112, 30),
            "low": np.linspace(79, 109, 30),
            "close": np.linspace(81, 111, 30),
            "volume": [100000] * 30,
        },
        index=dates_d,
    )

    res = compute_mtf_alignment(df_5m=df_5m, df_15m=df_15m, df_daily=df_d, direction="BULLISH")
    assert res["alignment_count"] >= 2
    assert res["opposing_trend"] is None
    assert res["tf_5m_trend"] == "BULLISH"
    assert res["tf_15m_trend"] == "BULLISH"
    assert res["htf_trend"] == "BULLISH"


def test_compute_mtf_alignment_opposing_trend():
    """Verify that compute_mtf_alignment detects opposing higher timeframe trend."""
    # 5m: temporary bounce up
    dates_5m = pd.date_range("2026-09-23 09:15", periods=10, freq="5min")
    df_5m = pd.DataFrame(
        {
            "open": np.linspace(95, 100, 10),
            "high": np.linspace(96, 101, 10),
            "low": np.linspace(94, 99, 10),
            "close": np.linspace(95.5, 100.5, 10),
            "volume": [5000] * 10,
        },
        index=dates_5m,
    )

    # 15m & Daily: in strong downtrend
    dates_15m = pd.date_range("2026-09-20 09:15", periods=20, freq="15min")
    df_15m = pd.DataFrame(
        {
            "open": np.linspace(150, 100, 20),
            "high": np.linspace(151, 101, 20),
            "low": np.linspace(149, 99, 20),
            "close": np.linspace(149.5, 99.5, 20),
            "volume": [25000] * 20,
        },
        index=dates_15m,
    )

    dates_d = pd.date_range("2026-08-01", periods=30, freq="B")
    df_d = pd.DataFrame(
        {
            "open": np.linspace(200, 100, 30),
            "high": np.linspace(202, 102, 30),
            "low": np.linspace(198, 98, 30),
            "close": np.linspace(199, 99, 30),
            "volume": [100000] * 30,
        },
        index=dates_d,
    )

    res = compute_mtf_alignment(df_5m=df_5m, df_15m=df_15m, df_daily=df_d, direction="BULLISH")
    assert res["opposing_trend"] is not None
    assert "BEARISH" in res["opposing_trend"]


# ── 2. ADR Exhaustion Gate Tests ─────────────────────────────────────────────


def test_adr_exhaustion_gate_rejects_at_extreme():
    """Verify that an alert where 85% of ADR is consumed and price is at day high is rejected."""
    auditor = AlertScrutinyAuditor()

    # Synthetic alert buying near Day High (₹1,084.5 on Day High ₹1,085.0)
    # Day range: 1085 - 1000 = 85 pts. ADR: 100 pts -> 85% consumed!
    alert = MagicMock()
    alert.symbol = "TATAMOTORS"
    alert.direction = "BULLISH"
    alert.ltp = 1084.5
    alert.entry = 1084.5
    alert.trigger = 1084.5
    alert.stop_loss = 1060.0
    alert.target_1 = 1140.0
    alert.target_2 = 1180.0
    alert.target_3 = 1220.0
    alert.alert_type = "INTRADAY_SPARK"
    alert.metrics = {
        "adr": 100.0,
        "day_high": 1085.0,
        "day_low": 1000.0,
        "adr_consumed_pct": 85.0,
        "rvol": 2.2,
    }

    # Pass through Tier-1 sanity
    alert.target_level = alert.target_1
    alert.trigger_level = alert.trigger
    alert.contract_symbol = None
    alert.option_type = None
    alert.environment = "PROD"
    alert.is_live = True

    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert not passed
    assert "ADR Exhaustion Trap" in reason


def test_adr_exhaustion_gate_allows_healthy_range():
    """Verify that an alert with only 45% ADR consumed passes through."""
    auditor = AlertScrutinyAuditor()

    alert = MagicMock()
    alert.symbol = "TATAMOTORS"
    alert.direction = "BULLISH"
    alert.ltp = 1030.0
    alert.entry = 1030.0
    alert.trigger = 1030.0
    alert.stop_loss = 1015.0
    alert.target_1 = 1065.0
    alert.target_level = 1065.0
    alert.trigger_level = 1030.0
    alert.target_2 = 1100.0
    alert.target_3 = 1140.0
    alert.alert_type = "INTRADAY_SPARK"
    alert.contract_symbol = None
    alert.option_type = None
    alert.environment = "PROD"
    alert.is_live = True
    alert.metrics = {
        "adr": 100.0,
        "day_high": 1045.0,
        "day_low": 1000.0,
        "adr_consumed_pct": 45.0,
        "rvol": 2.2,
    }

    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed or "ADR Exhaustion Trap" not in reason


# ── 3. Circuit Limit Headroom Gate Tests ─────────────────────────────────────


def test_circuit_limit_headroom_gate_rejects_truncated():
    """Verify that a stock within 0.5% of upper circuit with 2.0% stop risk is rejected."""
    auditor = AlertScrutinyAuditor()

    # Stock at 104.5, Upper Circuit is 105.0 (0.47% away, risk is 3.5 pts = 3.3%)
    alert = MagicMock()
    alert.symbol = "IDEA"
    alert.direction = "BULLISH"
    alert.ltp = 104.5
    alert.entry = 104.5
    alert.trigger = 104.5
    alert.stop_loss = 101.0  # 3.5 pts risk
    alert.target_1 = 112.0
    alert.target_level = 112.0
    alert.trigger_level = 104.5
    alert.target_2 = 118.0
    alert.target_3 = 125.0
    alert.alert_type = "INTRADAY_SPARK"
    alert.upper_circuit = 105.0
    alert.contract_symbol = None
    alert.option_type = None
    alert.environment = "PROD"
    alert.is_live = True
    alert.metrics = {
        "upper_circuit": 105.0,
        "rvol": 2.0,
    }

    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert not passed
    assert "Insufficient Circuit Headroom" in reason


def test_circuit_limit_headroom_gate_allows_room():
    """Verify that a stock with ample room to upper circuit passes."""
    auditor = AlertScrutinyAuditor()

    alert = MagicMock()
    alert.symbol = "IDEA"
    alert.direction = "BULLISH"
    alert.ltp = 100.0
    alert.entry = 100.0
    alert.trigger = 100.0
    alert.stop_loss = 98.0  # 2.0 pts risk
    alert.target_1 = 105.0
    alert.target_level = 105.0
    alert.trigger_level = 100.0
    alert.target_2 = 108.0
    alert.target_3 = 112.0
    alert.alert_type = "INTRADAY_SPARK"
    alert.upper_circuit = 115.0  # 15% away
    alert.contract_symbol = None
    alert.option_type = None
    alert.environment = "PROD"
    alert.is_live = True
    alert.metrics = {
        "upper_circuit": 115.0,
        "rvol": 2.0,
    }

    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed or "Insufficient Circuit Headroom" not in reason


# ── 4. Midday Liquidity Lull Gate Tests ──────────────────────────────────────


def test_midday_lull_gate_rejects_low_rvol():
    """Verify that a breakout attempted at 12:15 IST with RVOL 1.2x is vetoed."""
    auditor = AlertScrutinyAuditor()

    midday_time = datetime(2026, 9, 23, 12, 15, 0, tzinfo=IST)
    alert = MagicMock()
    alert.symbol = "RELIANCE"
    alert.direction = "BULLISH"
    alert.ltp = 3000.0
    alert.entry = 3000.0
    alert.trigger = 3000.0
    alert.stop_loss = 2960.0
    alert.target_1 = 3090.0
    alert.target_level = 3090.0
    alert.trigger_level = 3000.0
    alert.target_2 = 3150.0
    alert.target_3 = 3200.0
    alert.alert_type = "INTRADAY_SPARK"
    alert.created_at = midday_time
    alert.contract_symbol = None
    alert.option_type = None
    alert.environment = "PROD"
    alert.is_live = True
    alert.metrics = {
        "rvol": 1.2,  # < 1.8x threshold
    }

    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert not passed
    assert "Midday False Breakout Trap" in reason


def test_midday_lull_gate_allows_high_rvol_decoupler():
    """Verify that a breakout attempted at 12:15 IST with explosive RVOL 2.5x passes."""
    auditor = AlertScrutinyAuditor()

    midday_time = datetime(2026, 9, 23, 12, 15, 0, tzinfo=IST)
    alert = MagicMock()
    alert.symbol = "RELIANCE"
    alert.direction = "BULLISH"
    alert.ltp = 3000.0
    alert.entry = 3000.0
    alert.trigger = 3000.0
    alert.stop_loss = 2960.0
    alert.target_1 = 3090.0
    alert.target_level = 3090.0
    alert.trigger_level = 3000.0
    alert.target_2 = 3150.0
    alert.target_3 = 3200.0
    alert.alert_type = "INTRADAY_SPARK"
    alert.created_at = midday_time
    alert.contract_symbol = None
    alert.option_type = None
    alert.environment = "PROD"
    alert.is_live = True
    alert.metrics = {
        "rvol": 2.5,  # >= 1.8x threshold
    }

    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed or "Midday False Breakout Trap" not in reason


# ── 5. TradePlan ADR Exhaustion Note Tests ───────────────────────────────────


def test_trade_plan_adr_exhaustion_note():
    """Verify that calculate_trade_plan appends an ADR warning when >=80% range is consumed."""
    dates = pd.date_range("2026-08-01", periods=20, freq="B")
    # Consistently 20-pt range daily
    highs = [1020.0] * 19 + [1040.0]  # Today's high 1040, low 1000 = 40 pts (> 80% of 20 pt ATR)
    lows = [1000.0] * 20
    closes = [1015.0] * 19 + [1038.0]
    df = pd.DataFrame(
        {
            "open": [1005.0] * 20,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [100000] * 20,
        },
        index=dates,
    )

    plan = calculate_trade_plan("INFY", direction="BUY", spot=1038.0, df=df)
    assert "ADR Alert" in plan.asymmetry_note or "consumed" in plan.asymmetry_note
