"""
tests/test_hbcm_and_cvd_ladder.py
─────────────────────────────────
Comprehensive Institutional Unit Tests for:
1. Heavyweight Breadth Confluence Matrix (HBCM) — 4 of 5 Confluence Gate
2. Cumulative Volume Delta (CVD) Footprint Check (>= 2.2x Volume Delta)
3. Automated Dynamic Profit Ladder (+2R Auto-Partial, +4R Target 2, Trailing Runner)
"""

import pytest
import pandas as pd
from unittest.mock import MagicMock

from engine.hbcm import evaluate_hbcm, get_hbcm_constituents, MIN_CONFLUENCE_THRESHOLD
from engine.alert_evaluator import evaluate_alert_targets_and_trailing, TargetTrailingEvaluation
from engine.trade_lifecycle import audit_position_lifecycle
from engine.alert_scrutiny import AlertScrutinyAuditor
from engine.auto_alert_engine import AutoAlert


# ─────────────────────────────────────────────────────────────────────────────
# 1. Heavyweight Breadth Confluence Matrix (HBCM) Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_hbcm_constituents_mapping():
    """Verify canonical top 5 constituents for NIFTY and BANKNIFTY."""
    nifty_constituents = get_hbcm_constituents("NIFTY")
    assert len(nifty_constituents) == 5
    symbols = [c["symbol"] for c in nifty_constituents]
    assert symbols == ["RELIANCE", "HDFCBANK", "ICICIBANK", "INFOSYS", "TCS"]

    bn_constituents = get_hbcm_constituents("BANKNIFTY")
    assert len(bn_constituents) == 5
    bn_symbols = [c["symbol"] for c in bn_constituents]
    assert bn_symbols == ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK"]


def test_hbcm_bullish_confluence_pass():
    """HBCM passes when >= 4 of 5 heavyweights are bullish above VWAP."""
    # 4 heavyweights bullish, 1 neutral/lagging
    mock_quotes = {
        "RELIANCE": MagicMock(last_price=2950.0, vwap=2930.0, change_pct=1.2),
        "HDFCBANK": MagicMock(last_price=1650.0, vwap=1640.0, change_pct=0.8),
        "ICICIBANK": MagicMock(last_price=1220.0, vwap=1210.0, change_pct=1.0),
        "INFOSYS": MagicMock(last_price=1850.0, vwap=1840.0, change_pct=0.5),
        "TCS": MagicMock(last_price=4100.0, vwap=4120.0, change_pct=-0.5),  # below VWAP
    }
    mock_candles = {
        "RELIANCE": {"open": 2940.0, "close": 2950.0},
        "HDFCBANK": {"open": 1645.0, "close": 1650.0},
        "ICICIBANK": {"open": 1215.0, "close": 1220.0},
        "INFOSYS": {"open": 1845.0, "close": 1850.0},
        "TCS": {"open": 4110.0, "close": 4100.0},
    }

    res = evaluate_hbcm(
        underlying="NIFTY",
        direction="BULLISH",
        mock_quotes=mock_quotes,
        mock_5m_candles=mock_candles,
    )
    assert res.confluence_pass is True
    assert res.bullish_count == 4
    assert res.rejection_reason is None
    assert "RELIANCE" in res.aligned_symbols
    assert "TCS" in res.unaligned_symbols


def test_hbcm_confluence_failure_rejects():
    """HBCM fails and rejects when only 2 of 5 heavyweights align with index."""
    mock_quotes = {
        "RELIANCE": MagicMock(last_price=2950.0, vwap=2930.0, change_pct=1.2),
        "HDFCBANK": MagicMock(last_price=1630.0, vwap=1645.0, change_pct=-0.9),  # Drag
        "ICICIBANK": MagicMock(last_price=1200.0, vwap=1215.0, change_pct=-0.8),  # Drag
        "INFOSYS": MagicMock(last_price=1850.0, vwap=1840.0, change_pct=0.6),
        "TCS": MagicMock(last_price=4090.0, vwap=4120.0, change_pct=-1.1),  # Drag
    }
    mock_candles = {
        "RELIANCE": {"open": 2940.0, "close": 2950.0},
        "HDFCBANK": {"open": 1635.0, "close": 1630.0},
        "ICICIBANK": {"open": 1205.0, "close": 1200.0},
        "INFOSYS": {"open": 1845.0, "close": 1850.0},
        "TCS": {"open": 4100.0, "close": 4090.0},
    }

    res = evaluate_hbcm(
        underlying="NIFTY",
        direction="BULLISH",
        mock_quotes=mock_quotes,
        mock_5m_candles=mock_candles,
    )
    assert res.confluence_pass is False
    assert res.bullish_count == 2
    assert "Heavyweight breadth unaligned" in res.rejection_reason


def test_alert_scrutiny_tier1_hbcm_gate():
    """Alert Scrutiny Tier-1 Sanity Gate vetoes index breakout alerts when HBCM fails."""
    auditor = AlertScrutinyAuditor()
    mock_alert = AutoAlert(
        alert_id="aa-test-hbcm-01",
        alert_type="INDEX_CALL_SETUP",
        stage="STAGE_1",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="NIFTY 24500 CE BREAKOUT",
        summary="Testing HBCM veto",
        ltp=150.0,
        trigger_level=150.0,
        target_level=210.0,
        stop_loss=120.0,  # 30 pts risk, 60 pts reward (2.0R)
        strike=24500.0,
        option_type="CE",
        contract_symbol="NIFTY24500CE",
        metrics={
            "hbcm": {
                "total_heavyweights": 5,
                "confluence_pass": False,
                "bullish_count": 2,
                "rejection_reason": "Heavyweight breadth unaligned: only 2/5 constituents bullish",
            }
        },
    )

    passed, reason, flags = auditor.verify_tier1_sanity(mock_alert)
    assert passed is False
    assert flags.get("heavyweight_confluence_valid") is False
    assert "HBCM Confluence Veto" in reason


# ─────────────────────────────────────────────────────────────────────────────
# 2. Cumulative Volume Delta (CVD) Footprint Check Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_cvd_footprint_calculation():
    """Verify CVD calculation and ratio threshold (>= 2.2x)."""
    last_vol = 100000.0
    last_o = 24500.0
    last_h = 24550.0
    last_l = 24490.0
    last_c = 24545.0  # Closed in top 10% of bar
    rng = last_h - last_l  # 60 pts

    buyer_vol = last_vol * max(0.01, (last_c - last_l)) / rng
    seller_vol = last_vol * max(0.01, (last_h - last_c)) / rng
    cvd_ratio = round(buyer_vol / max(1.0, seller_vol), 2)

    # buyer_vol = 100000 * 55 / 60 = 91,666
    # seller_vol = 100000 * 5 / 60 = 8,333
    # cvd_ratio = 91666 / 8333 = 11.0x >= 2.2x
    assert cvd_ratio >= 2.2
    assert cvd_ratio == pytest.approx(11.0, rel=0.1)

    # In a weak/exhaustion candle where close is mid-bar:
    last_c_weak = 24520.0
    buyer_vol_weak = last_vol * max(0.01, (last_c_weak - last_l)) / rng
    seller_vol_weak = last_vol * max(0.01, (last_h - last_c_weak)) / rng
    cvd_ratio_weak = round(buyer_vol_weak / max(1.0, seller_vol_weak), 2)
    # buyer = 30/60 = 50%, seller = 30/60 = 50%, ratio = 1.0 < 2.2
    assert cvd_ratio_weak < 2.2


# ─────────────────────────────────────────────────────────────────────────────
# 3. Automated Dynamic Profit Ladder Tests (+2R, +4R, Runner)
# ─────────────────────────────────────────────────────────────────────────────

def test_alert_evaluator_2r_milestone_auto_partial():
    """Alert evaluator auto-partials 50% at +2R and locks SL to Breakeven."""
    alert = AutoAlert(
        alert_id="aa-ladder-01",
        alert_type="OPTIONS_MOMENTUM",
        stage="TRIGGERED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="NIFTY CE LADDER",
        summary="Ladder Test",
        ltp=100.0,
        trigger_level=100.0,
        stop_loss=80.0,  # 20 pts risk
        target_level=220.0,  # 6.0R runner
        actionable_plan={"target_1": 140.0, "target_2": 180.0},
        metrics={"vol_oi_ratio": 1.2},
    )

    # Test at exactly +2R (LTP = 140.0 -> PnL = +40 pts / 20 risk = 2.0R)
    res: TargetTrailingEvaluation = evaluate_alert_targets_and_trailing(
        alert=alert,
        current_ltp=140.0,
    )

    assert res.target_status == "T1_ACHIEVED"
    assert res.new_milestone == "T1_ACHIEVED"
    assert res.trailing_decision == "BOOK_50_TRAIL_BREAKEVEN"
    assert res.should_trail is True
    # Breakeven stop: 100 * 1.002 = 100.2
    assert res.recommended_stop == pytest.approx(100.2, abs=0.1)
    assert "+2R Milestone" in res.trailing_rationale
    assert "BOOK 50% PARTIAL PROFIT" in res.trailing_rationale


def test_alert_evaluator_4r_milestone_trail_sl():
    """Alert evaluator locks SL to +2R (T1) at +4R milestone."""
    alert = AutoAlert(
        alert_id="aa-ladder-02",
        alert_type="OPTIONS_MOMENTUM",
        stage="TRIGGERED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="NIFTY CE LADDER",
        summary="Ladder Test",
        ltp=100.0,
        trigger_level=100.0,
        stop_loss=80.0,  # 20 pts risk
        target_level=220.0,  # 6.0R runner
        achieved_milestones=["T1_ACHIEVED"],  # Already passed T1
        actionable_plan={"target_2": 180.0},  # +4R level (100 + 4*20)
        metrics={"vol_oi_ratio": 1.5},
    )

    # Test at +4R (LTP = 180.0 -> PnL = +80 pts / 20 risk = 4.0R)
    res: TargetTrailingEvaluation = evaluate_alert_targets_and_trailing(
        alert=alert,
        current_ltp=180.0,
    )

    assert res.target_status == "T2_ACHIEVED"
    assert res.new_milestone == "T2_ACHIEVED"
    assert res.trailing_decision == "TRAIL_LOCK_T1"
    assert res.should_trail is True
    # SL should be locked to T1 (100 + 2*20 = 140.0)
    assert res.recommended_stop >= 140.0
    assert "+4R Milestone" in res.trailing_rationale
    assert "TRAIL STOP-LOSS TO T1 / +2R" in res.trailing_rationale


def test_trade_lifecycle_swing_ladder_milestones():
    """Position lifecycle auditor enforces +2R auto-partial, +4R T2, and 6R+ runner trail."""
    # Entry: 2400.0, SL: 2350.0 (Risk = 50.0)
    # At 2R (LTP = 2500.0):
    report_2r = audit_position_lifecycle(
        symbol="RELIANCE",
        entry_price=2400.0,
        initial_stop_loss=2350.0,
        current_ltp=2500.0,
        position_type="LONG",
        mode="SWING",
    )
    assert report_2r.current_r_multiple == pytest.approx(2.0, abs=0.01)
    assert report_2r.recommended_action == "SCALE_OUT_50_PCT"
    assert report_2r.breakeven_reached is True
    assert report_2r.trailing_stops.stop_method in ("BREAKEVEN", "STRUCTURE_HL")
    assert any("2R Auto-Partial Breakeven Pivot" in m.name and m.reached for m in report_2r.milestones)

    # At 4R (LTP = 2600.0):
    report_4r = audit_position_lifecycle(
        symbol="RELIANCE",
        entry_price=2400.0,
        initial_stop_loss=2350.0,
        current_ltp=2600.0,
        position_type="LONG",
        mode="SWING",
    )
    assert report_4r.current_r_multiple == pytest.approx(4.0, abs=0.01)
    assert report_4r.recommended_action == "HOLD_RUNNER"
    # At +4R, stop should lock at least +2R (2500.0)
    assert report_4r.trailing_stops.recommended_active_stop >= 2500.0
    assert any("4R Target 2 Scale" in m.name and m.reached for m in report_4r.milestones)
