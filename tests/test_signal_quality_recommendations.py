"""
tests/test_signal_quality_recommendations.py
─────────────────────────────────────────────
Unit tests for the three EOD-recommendation-driven signal quality improvements.
"""

import os
import pytest
from datetime import datetime, timezone, timedelta, time as dtime
from unittest.mock import MagicMock, patch

os.environ["CHANAKYA_TESTING"] = "1"
os.environ.setdefault("TRADING_MODE", "PAPER")

IST = timezone(timedelta(hours=5, minutes=30))

# --- Helper ---

def _make_alert(symbol="RELIANCE", alert_type="OPTIONS_MOMENTUM", exchange="NFO", segment="FNO_STOCK"):
    a = MagicMock()
    a.symbol = symbol
    a.alert_type = alert_type
    a.exchange = exchange
    a.segment = segment
    a.direction = "BULLISH"
    a.stage = "IGNITED"
    a.ltp = 100.0
    a.stop_loss = 85.0
    a.trigger_level = 100.0
    a.target_level = 140.0
    a.confidence = 82
    a.environment = "LIVE"
    a.is_live = True
    a.is_invalidated = False
    a.is_active = True
    a.alert_id = f"test-{symbol}-{alert_type}"
    a.achieved_milestones = []
    a.target_status = "PENDING"
    a.contract_symbol = None
    a.strike = None
    a.option_type = None
    a.metrics = {}
    a.actionable_plan = {}
    a.order_flow_signals = {}
    a.quant_snapshot = None
    a.option_premium = None
    a.underlying_spot = None
    a.original_call_time = None
    a.created_at = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    a.headline = f"Test {symbol}"
    a.summary = f"Test summary"
    return a

_INTRADAY_STOCK_MOMENTUM_TYPES = (
    "OPTIONS_MOMENTUM", "GAMMA_BLAST", "SQUEEZE_BREAKOUT",
    "INTRADAY_SPARK", "VOLUME_EXPANSION", "INTRADAY_MOVER_IGNITED",
)
_POSITIONAL_EXEMPT_TYPES = (
    "SWING_TRADE", "POSITIONAL", "PRECURSOR_RADAR",
    "ASYMMETRIC_OPPORTUNITY", "MULTIBAGGER",
)
_IDX_SYMS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"}

def _should_afternoon_block(alert, now_t):
    is_idx_alert = alert.symbol in _IDX_SYMS or getattr(alert, "segment", "") == "FNO_INDEX"
    _is_domestic = alert.exchange in ("NSE", "BSE", "NFO", "")
    _is_commodity_currency = alert.exchange in ("MCX", "CDS") or getattr(alert, "segment", "") in ("COMMODITY", "CURRENCY", "CRYPTO")
    return (
        now_t >= dtime(14, 0)
        and alert.alert_type in _INTRADAY_STOCK_MOMENTUM_TYPES
        and _is_domestic
        and not is_idx_alert
        and not (alert.alert_type in _POSITIONAL_EXEMPT_TYPES)
        and not _is_commodity_currency
    )

# ─── Test Group 1: 14:00 IST Afternoon Entry Cutoff Gate ───────────────────

def test_intraday_stock_momentum_blocked_after_1400():
    alert = _make_alert("RELIANCE", "OPTIONS_MOMENTUM", "NFO", "FNO_STOCK")
    assert _should_afternoon_block(alert, dtime(14, 5))

def test_intraday_stock_momentum_allowed_before_1400():
    alert = _make_alert("RELIANCE", "OPTIONS_MOMENTUM", "NFO", "FNO_STOCK")
    assert not _should_afternoon_block(alert, dtime(13, 55))

def test_index_hedge_exempt_post_1400():
    alert = _make_alert("NIFTY", "GAMMA_BLAST", "NFO", "FNO_INDEX")
    assert not _should_afternoon_block(alert, dtime(14, 30))

def test_positional_alert_exempt_post_1400():
    alert = _make_alert("RELIANCE", "SWING_TRADE", "NSE", "FNO_STOCK")
    assert not _should_afternoon_block(alert, dtime(14, 45))

def test_commodity_exempt_post_1400():
    alert = _make_alert("CRUDEOIL", "COMMODITY_MOMENTUM", "MCX", "COMMODITY")
    assert not _should_afternoon_block(alert, dtime(15, 0))

def test_squeeze_breakout_on_stock_blocked_after_1400():
    alert = _make_alert("INFY", "SQUEEZE_BREAKOUT", "NSE", "FNO_STOCK")
    assert _should_afternoon_block(alert, dtime(14, 1))

# ─── Test Group 2: Adaptive Scrutiny Threshold ─────────────────────────────

def test_returns_70_for_non_breakout_type():
    from engine.alert_scrutiny import AlertScrutinyAuditor
    auditor = AlertScrutinyAuditor()
    alert = _make_alert("RELIANCE", "PRECURSOR_RADAR")
    threshold = auditor._compute_regime_scrutiny_threshold(alert)
    assert threshold == 70

def test_returns_70_normal_vix():
    from engine.alert_scrutiny import AlertScrutinyAuditor
    auditor = AlertScrutinyAuditor()
    alert = _make_alert("NIFTY", "SQUEEZE_BREAKOUT")
    with patch("market.indices.get_vix", return_value=15.0):
        threshold = auditor._compute_regime_scrutiny_threshold(alert)
    assert threshold == 70

def test_returns_75_compressed_vix():
    from engine.alert_scrutiny import AlertScrutinyAuditor
    auditor = AlertScrutinyAuditor()
    alert = _make_alert("NIFTY", "OPTIONS_MOMENTUM")
    with patch("market.indices.get_vix", return_value=11.8):
        threshold = auditor._compute_regime_scrutiny_threshold(alert)
    assert threshold == 75

def test_returns_75_at_vix_12_4():
    from engine.alert_scrutiny import AlertScrutinyAuditor
    auditor = AlertScrutinyAuditor()
    alert = _make_alert("NIFTY", "GAMMA_BLAST")
    with patch("market.indices.get_vix", return_value=12.4):
        threshold = auditor._compute_regime_scrutiny_threshold(alert)
    assert threshold == 75

def test_returns_70_at_vix_12_5_boundary():
    from engine.alert_scrutiny import AlertScrutinyAuditor
    auditor = AlertScrutinyAuditor()
    alert = _make_alert("NIFTY", "GAMMA_BLAST")
    with patch("market.indices.get_vix", return_value=12.5):
        threshold = auditor._compute_regime_scrutiny_threshold(alert)
    assert threshold == 70

def test_vix_exception_falls_back_to_70():
    from engine.alert_scrutiny import AlertScrutinyAuditor
    auditor = AlertScrutinyAuditor()
    alert = _make_alert("NIFTY", "ORB_BREAKOUT")
    with patch("market.indices.get_vix", side_effect=Exception("unavailable")):
        threshold = auditor._compute_regime_scrutiny_threshold(alert)
    assert threshold == 70

# ─── Test Group 3: Detector-Specific Lot Quantization ──────────────────────

def test_orb_breakout_125_multiplier():
    from engine.position_sizer import get_detector_lot_multiplier
    assert get_detector_lot_multiplier("ORB_BREAKOUT") == 1.25

def test_index_call_setup_125_multiplier():
    from engine.position_sizer import get_detector_lot_multiplier
    assert get_detector_lot_multiplier("INDEX_CALL_SETUP") == 1.25

def test_index_put_setup_125_multiplier():
    from engine.position_sizer import get_detector_lot_multiplier
    assert get_detector_lot_multiplier("INDEX_PUT_SETUP") == 1.25

def test_gamma_blast_115_multiplier():
    from engine.position_sizer import get_detector_lot_multiplier
    assert get_detector_lot_multiplier("GAMMA_BLAST") == 1.15

def test_counter_trend_05_multiplier():
    from engine.position_sizer import get_detector_lot_multiplier
    assert get_detector_lot_multiplier("COUNTER_TREND") == 0.5

def test_reversal_bear_05_multiplier():
    from engine.position_sizer import get_detector_lot_multiplier
    assert get_detector_lot_multiplier("REVERSAL_BEAR") == 0.5

def test_options_momentum_10_multiplier():
    from engine.position_sizer import get_detector_lot_multiplier
    assert get_detector_lot_multiplier("OPTIONS_MOMENTUM") == 1.0

def test_unknown_type_defaults_to_10():
    from engine.position_sizer import get_detector_lot_multiplier
    assert get_detector_lot_multiplier("SOME_NEW_DETECTOR") == 1.0

def test_case_insensitive():
    from engine.position_sizer import get_detector_lot_multiplier
    assert get_detector_lot_multiplier("orb_breakout") == 1.25
    assert get_detector_lot_multiplier("counter_trend") == 0.5

def test_orb_breakout_increases_lots_vs_baseline():
    from engine.position_sizer import calculate_position_size, calculate_position_size_for_alert
    base = calculate_position_size("NIFTY", 500.0, 480.0, capital=1_000_000.0, is_fno=True)
    orb  = calculate_position_size_for_alert("ORB_BREAKOUT", "NIFTY", 500.0, 480.0, capital=1_000_000.0, is_fno=True)
    assert orb.lots >= base.lots

def test_counter_trend_halves_lots_vs_baseline():
    from engine.position_sizer import calculate_position_size, calculate_position_size_for_alert
    base = calculate_position_size("NIFTY", 500.0, 480.0, capital=1_000_000.0, is_fno=True)
    ct   = calculate_position_size_for_alert("COUNTER_TREND", "NIFTY", 500.0, 480.0, capital=1_000_000.0, is_fno=True)
    assert ct.lots <= base.lots
    assert ct.lots >= 1  # minimum 1 lot

def test_standard_type_unchanged():
    from engine.position_sizer import calculate_position_size, calculate_position_size_for_alert
    base = calculate_position_size("BANKNIFTY", 200.0, 185.0, capital=500_000.0, is_fno=True)
    std  = calculate_position_size_for_alert("OPTIONS_MOMENTUM", "BANKNIFTY", 200.0, 185.0, capital=500_000.0, is_fno=True)
    assert std.lots == base.lots and std.shares == base.shares

def test_minimum_1_lot_on_small_capital():
    from engine.position_sizer import calculate_position_size_for_alert
    # With adequate capital (500k), COUNTER_TREND (0.5x) must still produce >= 1 lot.
    result = calculate_position_size_for_alert("COUNTER_TREND", "NIFTY", 500.0, 490.0, capital=500_000.0, is_fno=True)
    assert result.lots >= 1, f"With adequate capital, minimum 1 lot must be enforced, got {result.lots}"
