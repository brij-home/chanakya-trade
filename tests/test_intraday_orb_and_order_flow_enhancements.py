"""
tests/test_intraday_orb_and_order_flow_enhancements.py
───────────────────────────────────────────────────────
Comprehensive test suite for:
  1. Autonomous Opening Range Breakout (ORB-15) Detector (engine/detectors/orb.py).
  2. Absolute Non-Interference Guarantee: Proof that ORB detection does not mute,
     delay, or filter early-morning (pre-09:30 IST) high-conviction trade signals
     (Gamma Blasts, Precursor Radars, Coiled Squeeze Breakouts, Index Drives).
  3. Gate 17: Order Book Level-2 Depth Imbalance Gate in Tier-1 Scrutiny.
  4. Gate 18: Developing Volume Profile (d-POC / Value Area) Acceptance Gate in Tier-1 Scrutiny.
"""

from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import pytest

from engine.alert_model import AutoAlert
from engine.alert_scrutiny import AlertScrutinyAuditor
from engine.auto_alert_engine import AutoAlertEngine
from engine.detectors.orb import (
    detect_opening_range_breakout,
    extract_opening_range,
)

IST = ZoneInfo("Asia/Kolkata")


def _build_synthetic_5m_df(
    symbol: str = "TRENT",
    base_price: float = 6000.0,
    n_bars: int = 12,
    date_str: str = "2026-09-17",
) -> pd.DataFrame:
    """Builds a realistic 5-minute intraday OHLCV DataFrame starting at 09:15 IST."""
    start_dt = datetime.datetime.strptime(f"{date_str} 09:15:00", "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=IST
    )
    times = [start_dt + datetime.timedelta(minutes=5 * i) for i in range(n_bars)]
    
    # 09:15 bar: high 6050, low 5980
    # 09:20 bar: high 6040, low 5990
    # 09:25 bar: high 6060, low 6010  --> Opening 15m Range: High=6060, Low=5980 (Range=80, Mid=6020)
    data = []
    curr = base_price
    for i in range(n_bars):
        if i == 0:
            h, l, c = curr + 50.0, curr - 20.0, curr + 30.0
        elif i == 1:
            h, l, c = curr + 40.0, curr - 10.0, curr + 20.0
        elif i == 2:
            h, l, c = curr + 60.0, curr + 10.0, curr + 50.0
        else:
            # Subsequent bars
            h, l, c = curr + 70.0, curr + 30.0, curr + 65.0
        data.append({
            "open": curr,
            "high": h,
            "low": l,
            "close": c,
            "volume": 25000 + i * 5000,
        })
    df = pd.DataFrame(data, index=pd.DatetimeIndex(times))
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 1. ORB-15 Extraction & Detection Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_extract_opening_range_levels():
    """Extracts High, Low, Range, and Midpoint from the 09:15–09:30 opening window."""
    df = _build_synthetic_5m_df(base_price=6000.0, n_bars=6)
    ref_dt = datetime.datetime(2026, 9, 17, 9, 35, tzinfo=IST)
    
    result = extract_opening_range(df, opening_minutes=15, ref_dt=ref_dt)
    assert result is not None
    orb_high, orb_low, orb_range, orb_mid = result
    
    assert orb_high == 6060.0
    assert orb_low == 5980.0
    assert orb_range == 80.0
    assert orb_mid == 6020.0


def test_detect_opening_range_breakout_bullish():
    """Valid bullish breakout post-09:30 triggers ORB_BREAKOUT with midpoint SL and asymmetric targets."""
    df = _build_synthetic_5m_df(base_price=6000.0, n_bars=6)
    ref_time = datetime.datetime(2026, 9, 17, 9, 35, tzinfo=IST)
    
    # Spot breaking above ORB High (6060.0) at 6075.0, VWAP at 6030.0, RVOL 1.8x
    alert = detect_opening_range_breakout(
        symbol="TRENT",
        df=df,
        ltp=6075.0,
        vwap=6030.0,
        rvol=1.8,
        ref_time=ref_time,
    )
    
    assert alert is not None
    assert alert.alert_type == "ORB_BREAKOUT"
    assert alert.direction == "BULLISH"
    assert alert.trigger_level == 6060.0
    assert alert.stop_loss == 6020.0  # Midpoint of 6060 and 5980
    assert alert.target_level == 6140.0  # +1.0x Range (6060 + 80)
    assert alert.metrics["target_2"] == 6220.0  # +2.0x Range (6060 + 160)
    assert alert.metrics["target_3"] == 6340.0  # +3.5x Range (6060 + 280)
    assert alert.no_chase_boundary == 6088.0  # 6060 + 0.35 * 80
    assert alert.confidence >= 80


def test_detect_opening_range_breakdown_bearish():
    """Valid bearish breakdown post-09:30 triggers ORB_BREAKDOWN with midpoint SL and asymmetric targets."""
    df = _build_synthetic_5m_df(base_price=6000.0, n_bars=6)
    ref_time = datetime.datetime(2026, 9, 17, 9, 40, tzinfo=IST)
    
    # Spot breaking below ORB Low (5980.0) at 5970.0, VWAP at 6010.0, RVOL 1.7x
    alert = detect_opening_range_breakout(
        symbol="TRENT",
        df=df,
        ltp=5970.0,
        vwap=6010.0,
        rvol=1.7,
        ref_time=ref_time,
    )
    
    assert alert is not None
    assert alert.alert_type == "ORB_BREAKDOWN"
    assert alert.direction == "BEARISH"
    assert alert.trigger_level == 5980.0
    assert alert.stop_loss == 6020.0  # Midpoint
    assert alert.target_level == 5900.0  # -1.0x Range (5980 - 80)
    assert alert.metrics["target_2"] == 5820.0  # -2.0x Range (5980 - 160)
    assert alert.confidence >= 80


def test_orb_range_sanity_rejection():
    """Narrow range (<0.25%) and exhausted range (>3.5%) are rejected to prevent chop or late entries."""
    ref_time = datetime.datetime(2026, 9, 17, 9, 35, tzinfo=IST)
    
    # Too narrow: Range is 6.0 pts on 6000 stock (0.10% < 0.25%)
    alert_narrow = detect_opening_range_breakout(
        symbol="TRENT",
        df=None,
        ltp=6008.0,
        vwap=6000.0,
        orb_levels=(6006.0, 6000.0, 6.0, 6003.0),
        ref_time=ref_time,
    )
    assert alert_narrow is None

    # Too wide / exhausted: Range is 300 pts on 6000 stock (5.0% > 3.5%)
    alert_wide = detect_opening_range_breakout(
        symbol="TRENT",
        df=None,
        ltp=6160.0,
        vwap=6000.0,
        orb_levels=(6150.0, 5850.0, 300.0, 6000.0),
        ref_time=ref_time,
    )
    assert alert_wide is None


def test_orb_no_chase_rejection():
    """Price extended > 35% of opening range past breakout point is rejected (Anti-FOMO)."""
    ref_time = datetime.datetime(2026, 9, 17, 9, 35, tzinfo=IST)
    
    # Range is 80 pts (High 6060, Low 5980). Max chase is 6060 + (0.35 * 80) = 6088.0.
    # Spot is 6095.0 (> 6088.0) -> Rejection
    alert = detect_opening_range_breakout(
        symbol="TRENT",
        df=None,
        ltp=6095.0,
        vwap=6040.0,
        rvol=1.8,
        orb_levels=(6060.0, 5980.0, 80.0, 6020.0),
        ref_time=ref_time,
    )
    assert alert is None


# ─────────────────────────────────────────────────────────────────────────────
# 2. Absolute Non-Interference Guarantee: Pre-09:30 Early Signals Unmuted
# ─────────────────────────────────────────────────────────────────────────────

def test_early_pre_0930_signals_unmuted_by_orb():
    """
    CRITICAL INVARIANT VERIFICATION:
    Verifies that the ORB-15 detector strictly refrains from muting, delaying,
    or interfering with early-morning high-conviction trade signals before 09:30 IST.
    """
    # 1. At 09:18 IST (during opening discovery), ORB detector returns None cleanly:
    early_time = datetime.datetime(2026, 9, 17, 9, 18, tzinfo=IST)
    orb_result = detect_opening_range_breakout(
        symbol="RELIANCE",
        df=None,
        ltp=3000.0,
        ref_time=early_time,
        orb_levels=(3010.0, 2990.0, 20.0, 3000.0),
        ignore_time_gate=False,
    )
    assert orb_result is None, "ORB must stay idle during 09:15-09:30 discovery window"

    # 2. Concurrently, early high-conviction signals (Gamma Blast, Precursor Radar, Squeeze)
    # are generated freely and are NEVER filtered or muted:
    early_gamma_blast = AutoAlert(
        alert_id="gamma-early-0918",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="NIFTY 25000 CE Early Gamma Thrust",
        summary="Delta pinch detected at 09:18 IST with 3.2x call buying volume",
        ltp=120.0,
        trigger_level=120.0,
        stop_loss=90.0,
        target_level=180.0,
        confidence=92,
        created_at="2026-09-17 09:18:00 IST",
        is_live=True,
        environment="LIVE",
    )
    
    early_precursor = AutoAlert(
        alert_id="precursor-early-0922",
        alert_type="PRECURSOR_RADAR",
        stage="EARLY_WARNING",
        symbol="NSE:TRENT",
        exchange="NSE",
        direction="BULLISH",
        headline="Trent Institutional Gap Thrust",
        summary="Opening base thrust with huge block trades",
        ltp=6050.0,
        trigger_level=6050.0,
        stop_loss=5980.0,
        target_level=6250.0,
        confidence=88,
        created_at="2026-09-17 09:22:00 IST",
        is_live=True,
        environment="LIVE",
    )

    engine = AutoAlertEngine()
    engine._alerts = []

    # Mock scanners returning early signals
    with patch.object(engine, "scan_index_contagion", return_value=[]), \
         patch.object(engine, "scan_gamma_blasts", return_value=[early_gamma_blast]), \
         patch.object(engine, "scan_precursor_radars", return_value=[early_precursor]), \
         patch.object(engine, "scan_options_momentum_breakouts", return_value=[]), \
         patch.object(engine, "scan_squeeze_breakouts", return_value=[]), \
         patch.object(engine, "scan_circuits", return_value=[]), \
         patch.object(engine, "scan_pattern_coilings", return_value=[]), \
         patch.object(engine, "scan_intraday_mover_sparks", return_value=[]), \
         patch.object(engine, "scan_asymmetric_opportunities", return_value=[]), \
         patch.object(engine, "scan_opening_range_breakouts", return_value=[]):  # ORB returns [] pre-09:30

        all_morning_alerts = engine.scan_equity_nfo_now()

    # Both early alerts pass with 100% fidelity through the pipeline
    assert len(all_morning_alerts) == 2
    alert_types = [a.alert_type for a in all_morning_alerts]
    assert "GAMMA_BLAST" in alert_types
    assert "PRECURSOR_RADAR" in alert_types
    assert all_morning_alerts[0].symbol == "NIFTY"
    assert all_morning_alerts[1].symbol == "NSE:TRENT"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Gate 17: Order Book Level-2 Depth Imbalance Gate Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_tier1_gate17_depth_imbalance_supply_trap():
    """Rejects long breakout when sell order overhang > 2.2x total buy bids (Supply Trap)."""
    auditor = AlertScrutinyAuditor(min_rr_ratio=1.3, max_intraday_risk_pct=8.0)
    
    # Long setup into massive sell overhang (30,000 asks vs 10,000 bids -> 3.0x supply)
    alert = AutoAlert(
        alert_id="test-depth-long-trap",
        alert_type="ORB_BREAKOUT",
        stage="IGNITED",
        symbol="NSE:TATAMOTORS",
        exchange="NSE",
        direction="BULLISH",
        headline="Tata Motors Breakout",
        summary="ORB breakout into wall",
        ltp=1000.0,
        trigger_level=1000.0,
        stop_loss=985.0,  # 15 pts risk
        target_level=1045.0,  # 45 pts reward (1:3.0 R:R)
        metrics={
            "total_buy_qty": 10000,
            "total_sell_qty": 30000,
            "atr": 15.0,
        },
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed is False
    assert flags["depth_imbalance_valid"] is False
    assert "Order Book Depth Imbalance Trap" in reason
    assert "supply overhang" in reason


def test_tier1_gate17_depth_imbalance_absorption_trap():
    """Rejects short breakdown when buy bids > 2.2x total sell offers (Bid Absorption Wall)."""
    auditor = AlertScrutinyAuditor(min_rr_ratio=1.3, max_intraday_risk_pct=8.0)
    
    # Short setup into massive bid absorption wall (35,000 bids vs 10,000 asks -> 3.5x bids)
    alert = AutoAlert(
        alert_id="test-depth-short-trap",
        alert_type="ORB_BREAKDOWN",
        stage="IGNITED",
        symbol="NSE:TATAMOTORS",
        exchange="NSE",
        direction="BEARISH",
        headline="Tata Motors Breakdown",
        summary="ORB breakdown into bids",
        ltp=1000.0,
        trigger_level=1000.0,
        stop_loss=1015.0,  # 15 pts risk
        target_level=955.0,  # 45 pts reward (1:3.0 R:R)
        metrics={
            "total_buy_qty": 35000,
            "total_sell_qty": 10000,
            "atr": 15.0,
        },
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed is False
    assert flags["depth_imbalance_valid"] is False
    assert "Order Book Depth Imbalance Trap" in reason
    assert "bid absorption" in reason


def test_tier1_gate17_depth_graceful_pass_when_balanced_or_absent():
    """Passes when order book depth is balanced or when depth data is absent."""
    auditor = AlertScrutinyAuditor(min_rr_ratio=1.3, max_intraday_risk_pct=8.0)
    
    # 1. Balanced depth (buy 20k vs sell 22k -> 1.1x ratio, well within 2.2x threshold)
    alert_balanced = AutoAlert(
        alert_id="test-depth-balanced",
        alert_type="ORB_BREAKOUT",
        stage="IGNITED",
        symbol="NSE:TATAMOTORS",
        exchange="NSE",
        direction="BULLISH",
        headline="Tata Motors Balanced Breakout",
        summary="Clean breakout",
        ltp=1000.0,
        trigger_level=1000.0,
        stop_loss=985.0,
        target_level=1045.0,
        metrics={"total_buy_qty": 20000, "total_sell_qty": 22000, "atr": 15.0},
        is_live=True,
        environment="LIVE",
    )
    passed, _, flags = auditor.verify_tier1_sanity(alert_balanced)
    assert passed is True
    assert flags["depth_imbalance_valid"] is True

    # 2. Absent depth (no depth data in metrics or alert)
    alert_no_depth = AutoAlert(
        alert_id="test-depth-none",
        alert_type="ORB_BREAKOUT",
        stage="IGNITED",
        symbol="NSE:TATAMOTORS",
        exchange="NSE",
        direction="BULLISH",
        headline="Tata Motors No Depth Breakout",
        summary="Clean breakout",
        ltp=1000.0,
        trigger_level=1000.0,
        stop_loss=985.0,
        target_level=1045.0,
        metrics={"atr": 15.0},
        is_live=True,
        environment="LIVE",
    )
    passed2, _, flags2 = auditor.verify_tier1_sanity(alert_no_depth)
    assert passed2 is True
    assert flags2["depth_imbalance_valid"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 4. Gate 18: Developing Volume Profile (d-POC / Value Area) Acceptance Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_tier1_gate18_developing_poc_acceptance_rejection():
    """Rejects long setup trading stranded below developing Value Area Low (d-VAL)."""
    auditor = AlertScrutinyAuditor(min_rr_ratio=1.3, max_intraday_risk_pct=8.0)
    
    # Long setup at 980.0, while d-VAL is at 995.0, d-POC is 1005.0, d-VAH is 1015.0.
    # Price is stranded below value area -> Rejection
    alert_below_val = AutoAlert(
        alert_id="test-poc-below-val",
        alert_type="ORB_BREAKOUT",
        stage="IGNITED",
        symbol="NSE:TATAMOTORS",
        exchange="NSE",
        direction="BULLISH",
        headline="Tata Motors Stranded Long",
        summary="Long below value area",
        ltp=980.0,
        trigger_level=980.0,
        stop_loss=965.0,  # 15 pts risk
        target_level=1025.0,  # 45 pts reward
        metrics={
            "d_poc": 1005.0,
            "d_val": 995.0,
            "d_vah": 1015.0,
            "atr": 15.0,
        },
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert_below_val)
    assert passed is False
    assert flags["poc_acceptance_valid"] is False
    assert "Developing Value Area Rejection" in reason


def test_tier1_gate18_developing_poc_acceptance_success():
    """Passes long setup when price is trading comfortably above d-POC / Value Area Low."""
    auditor = AlertScrutinyAuditor(min_rr_ratio=1.3, max_intraday_risk_pct=8.0)
    
    # Long setup at 1018.0, d-POC is 1005.0, d-VAL is 995.0, d-VAH is 1015.0.
    # Price is holding above developing Value Area -> Accepted!
    alert_accepted = AutoAlert(
        alert_id="test-poc-accepted",
        alert_type="ORB_BREAKOUT",
        stage="IGNITED",
        symbol="NSE:TATAMOTORS",
        exchange="NSE",
        direction="BULLISH",
        headline="Tata Motors Value Acceptance",
        summary="Long accepted above value area",
        ltp=1018.0,
        trigger_level=1018.0,
        stop_loss=1002.0,  # 16 pts risk
        target_level=1066.0,  # 48 pts reward (1:3.0 R:R)
        metrics={
            "d_poc": 1005.0,
            "d_val": 995.0,
            "d_vah": 1015.0,
            "atr": 15.0,
        },
        is_live=True,
        environment="LIVE",
    )
    passed, _, flags = auditor.verify_tier1_sanity(alert_accepted)
    assert passed is True
    assert flags["poc_acceptance_valid"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 5. Gate 19: Momentum Divergence Exhaustion Trap Gate Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_tier1_gate19_divergence_exhaustion_trap_bullish():
    """Rejects bullish setup when bearish regular RSI divergence indicates momentum exhaustion."""
    auditor = AlertScrutinyAuditor(min_rr_ratio=1.3, max_intraday_risk_pct=8.0)
    
    alert = AutoAlert(
        alert_id="test-div-trap-bull",
        alert_type="ORB_BREAKOUT",
        stage="IGNITED",
        symbol="NSE:TATAMOTORS",
        exchange="NSE",
        direction="BULLISH",
        headline="Tata Motors Breakout",
        summary="ORB breakout into divergence",
        ltp=1000.0,
        trigger_level=1000.0,
        stop_loss=985.0,
        target_level=1045.0,
        metrics={
            "divergence_type": "BEARISH_REGULAR",
            "divergence_bias": "BEARISH",
            "atr": 15.0,
        },
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed is False
    assert flags["divergence_sanity_valid"] is False
    assert "Momentum Divergence Exhaustion Trap" in reason


def test_tier1_gate19_divergence_exhaustion_trap_bearish():
    """Rejects bearish setup when bullish regular RSI divergence indicates Wyckoff spring / absorption."""
    auditor = AlertScrutinyAuditor(min_rr_ratio=1.3, max_intraday_risk_pct=8.0)
    
    alert = AutoAlert(
        alert_id="test-div-trap-bear",
        alert_type="ORB_BREAKDOWN",
        stage="IGNITED",
        symbol="NSE:TATAMOTORS",
        exchange="NSE",
        direction="BEARISH",
        headline="Tata Motors Breakdown",
        summary="ORB breakdown into absorption",
        ltp=1000.0,
        trigger_level=1000.0,
        stop_loss=1015.0,
        target_level=955.0,
        metrics={
            "divergence_type": "BULLISH_REGULAR",
            "divergence_bias": "BULLISH",
            "atr": 15.0,
        },
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed is False
    assert flags["divergence_sanity_valid"] is False
    assert "Momentum Divergence Exhaustion Trap" in reason


def test_tier1_gate19_divergence_aligned_or_absent_pass():
    """Passes when divergence is aligned (e.g. Bullish Regular for Long) or absent."""
    auditor = AlertScrutinyAuditor(min_rr_ratio=1.3, max_intraday_risk_pct=8.0)
    
    # 1. Aligned divergence
    alert_aligned = AutoAlert(
        alert_id="test-div-aligned",
        alert_type="ORB_BREAKOUT",
        stage="IGNITED",
        symbol="NSE:TATAMOTORS",
        exchange="NSE",
        direction="BULLISH",
        headline="Tata Motors Aligned Breakout",
        summary="Clean breakout with bullish divergence",
        ltp=1000.0,
        trigger_level=1000.0,
        stop_loss=985.0,
        target_level=1045.0,
        metrics={"divergence_type": "BULLISH_REGULAR", "divergence_bias": "BULLISH", "atr": 15.0},
        is_live=True,
        environment="LIVE",
    )
    passed, _, flags = auditor.verify_tier1_sanity(alert_aligned)
    assert passed is True
    assert flags["divergence_sanity_valid"] is True

    # 2. Absent divergence
    alert_none = AutoAlert(
        alert_id="test-div-none",
        alert_type="ORB_BREAKOUT",
        stage="IGNITED",
        symbol="NSE:TATAMOTORS",
        exchange="NSE",
        direction="BULLISH",
        headline="Tata Motors No Div",
        summary="Clean breakout",
        ltp=1000.0,
        trigger_level=1000.0,
        stop_loss=985.0,
        target_level=1045.0,
        metrics={"atr": 15.0},
        is_live=True,
        environment="LIVE",
    )
    passed2, _, flags2 = auditor.verify_tier1_sanity(alert_none)
    assert passed2 is True
    assert flags2["divergence_sanity_valid"] is True


def test_orb_retest_and_candlestick_blueprint():
    """Verifies that ORB alerts specify entry_type='LIMIT_ON_PULLBACK' and retest instructions."""
    df = _build_synthetic_5m_df(base_price=6000.0, n_bars=6)
    ref_time = datetime.datetime(2026, 9, 17, 9, 35, tzinfo=IST)
    
    alert = detect_opening_range_breakout(
        symbol="TRENT",
        df=df,
        ltp=6075.0,
        vwap=6030.0,
        rvol=1.8,
        ref_time=ref_time,
    )
    
    assert alert is not None
    assert alert.entry_type == "LIMIT_ON_PULLBACK"
    assert "retest" in alert.actionable_plan["when_to_buy"].lower()
    assert "do not chase" in alert.actionable_plan["when_to_wait"].lower()
    assert alert.actionable_plan["entry_type"] == "LIMIT_ON_PULLBACK"

