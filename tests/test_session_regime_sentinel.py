"""
tests/test_session_regime_sentinel.py
─────────────────────────────────────
Institutional test suite for Autonomous Intraday Regime Shift Sentinel.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from config.constants import IST_ZONE as IST
from engine.alert_scrutiny import AlertScrutinyAuditor
from engine.session_regime_sentinel import (
    calculate_cpr,
    evaluate_symbol_session_regime,
)


def test_calculate_cpr_classification():
    """Verifies Narrow, Average, and Wide CPR classifications for Index and Equity."""
    # 1. Index Narrow CPR (e.g. Nifty prior range 25000 to 25030, close 25015)
    # Pivot = 25015, BC = 25015, TC = 25015 -> width 0
    cpr_narrow = calculate_cpr(high=25030.0, low=25000.0, close=25015.0, is_index=True)
    assert cpr_narrow.cpr_type == "NARROW"
    assert cpr_narrow.cpr_width_pct <= 0.15

    # 2. Index Wide CPR (e.g. Nifty prior range 24500 to 25000, close 24700)
    # Pivot = 24733.3, BC = 24750, TC = 24716.7 -> width = 33.3 pts (0.13%? Let's check wider)
    cpr_wide = calculate_cpr(high=25200.0, low=24800.0, close=24850.0, is_index=True)
    # Pivot = (25200 + 24800 + 24850) / 3 = 24950
    # BC = (25200 + 24800) / 2 = 25000
    # TC = (24950 - 25000) + 24950 = 24900
    # Width = 100 pts -> 100 / 24950 = 0.40% > 0.35%
    assert cpr_wide.cpr_type == "WIDE"
    assert cpr_wide.cpr_width_pct >= 0.35


def test_evaluate_symbol_session_regime_shifts():
    """Verifies dynamic regime shift from Trend Expansion to Chop Mean Reversion."""
    post_1130 = datetime(2026, 10, 18, 12, 15, tzinfo=IST)
    early_morning = datetime(2026, 10, 18, 9, 45, tzinfo=IST)

    # 1. Narrow CPR + 30% ADR consumed -> TREND_EXPANSION
    # Prior day: 25030 high, 25000 low, 25015 close. ADR = 180 pts.
    # Today: Range = 54 pts (30% ADR)
    reg_trend = evaluate_symbol_session_regime(
        symbol="NIFTY",
        current_high=25080.0,
        current_low=25026.0,
        current_ltp=25075.0,
        prev_high=25030.0,
        prev_low=25000.0,
        prev_close=25015.0,
        adr_5d=180.0,
        ref_time=early_morning,
    )
    assert reg_trend.regime == "TREND_EXPANSION"
    assert reg_trend.veto_breakout_chase is False
    assert reg_trend.adr_exhaustion_pct <= 50.0

    # 2. Wide CPR + 88% ADR consumed post-11:30 -> CHOP_MEAN_REVERSION
    # Prior day: 25200 high, 24800 low, 24850 close. ADR = 200 pts.
    # Today: Range = 180 pts (90% ADR consumed!)
    reg_chop = evaluate_symbol_session_regime(
        symbol="NIFTY",
        current_high=25180.0,
        current_low=25000.0,
        current_ltp=25175.0,
        prev_high=25200.0,
        prev_low=24800.0,
        prev_close=24850.0,
        adr_5d=200.0,
        ref_time=post_1130,
    )
    assert reg_chop.regime == "CHOP_MEAN_REVERSION"
    assert reg_chop.veto_breakout_chase is True
    assert reg_chop.favor_mean_reversion is True
    assert "ADR Exhaustion" in reg_chop.rationale


def test_session_regime_scrutiny_integration(monkeypatch):
    """Verifies AlertScrutinyAuditor vetoes breakout alerts when ADR is exhausted."""
    auditor = AlertScrutinyAuditor(min_rr_ratio=1.5)
    monkeypatch.setattr(auditor, "_execute_fast_llm_scrutiny", lambda *args, **kwargs: None)
    monkeypatch.setattr("market.order_book.get_depth_book", lambda *args, **kwargs: None)

    # 1. Breakout alert on an ADR-exhausted session -> Must be REJECTED
    exhausted_session = {
        "regime": "CHOP_MEAN_REVERSION",
        "veto_breakout_chase": True,
        "favor_mean_reversion": True,
        "adr_exhaustion_pct": 92.0,
        "rationale": "ADR Exhaustion (92.0% consumed of 200 pts) on WIDE CPR (0.42%).",
    }
    alert_breakout = SimpleNamespace(
        symbol="RELIANCE",
        ltp=2900.0,
        trigger_level=2900.0,
        stop_loss=2860.0,
        target_level=3000.0,
        direction="BULLISH",
        alert_type="BREAKOUT",
        rvol=2.2,
        environment="TEST",
        is_live=False,
        alert_id="test-reg-1",
        metrics={"session_regime": exhausted_session},
    )
    res_bo = auditor.scrutinize_alert(alert_breakout)
    assert res_bo.status == "REJECTED"
    assert "ADR Exhaustion" in str(res_bo.rejection_reason)

    # 2. Mean-Reversion fade on same exhausted session -> APPROVED with chop convergence rationale
    alert_fade = SimpleNamespace(
        symbol="RELIANCE",
        ltp=2900.0,
        trigger_level=2900.0,
        stop_loss=2930.0,
        target_level=2820.0,
        direction="BEARISH",
        alert_type="MEAN_REVERSION",
        rvol=2.0,
        environment="TEST",
        is_live=False,
        alert_id="test-reg-2",
        metrics={"session_regime": exhausted_session},
    )
    res_fade = auditor.scrutinize_alert(alert_fade)
    assert res_fade.status == "APPROVED"
    assert "CHOP REGIME CONVERGENCE" in res_fade.logic_confirmation
