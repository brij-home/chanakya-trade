"""
tests/test_cross_asset_lead_lag.py
──────────────────────────────────
Institutional test suite for Cross-Asset Macro Lead-Lag Arbitrage Engine.
"""

from __future__ import annotations

from types import SimpleNamespace
import pytest

from engine.alert_scrutiny import AlertScrutinyAuditor
from market.cross_asset_lead_lag import (
    CrossAssetLeadLagSentinel,
    cross_asset_lead_lag_sentinel,
)


@pytest.fixture(autouse=True)
def reset_lead_lag_pulses():
    """Ensure clean pulse state before and after each test."""
    cross_asset_lead_lag_sentinel.update_pulses(crude_delta_pct=0.0, usdinr_delta_pct=0.0)
    yield
    cross_asset_lead_lag_sentinel.update_pulses(crude_delta_pct=0.0, usdinr_delta_pct=0.0)


def test_crude_surge_headwind_and_tailwind():
    """Verifies Crude Oil fast pulse transmission to Paints and Upstream Oil & Gas."""
    sentinel = CrossAssetLeadLagSentinel()
    # Simulate MCX Crude 15m surge (+1.80%)
    sentinel.update_pulses(crude_delta_pct=1.80, usdinr_delta_pct=0.0)

    # 1. Asian Paints Long -> Vetoed (Severe margin compression)
    eval_paint_long = sentinel.evaluate_lead_lag_shock(symbol="ASIANPAINT", direction="BULLISH")
    assert eval_paint_long.status == "HEADWIND_VETO"
    assert eval_paint_long.veto_recommended is True
    assert eval_paint_long.is_headwind is True
    assert eval_paint_long.conviction_adj <= -10
    assert "margin compression" in eval_paint_long.rationale

    # 2. Asian Paints Short -> Tailwind (Aligns with oil shock breakdown)
    eval_paint_short = sentinel.evaluate_lead_lag_shock(symbol="ASIANPAINT", direction="BEARISH")
    assert eval_paint_short.status == "TAILWIND_BOOST"
    assert eval_paint_short.is_tailwind is True
    assert eval_paint_short.conviction_adj > 0

    # 3. ONGC Long -> Tailwind (Direct beneficiary of higher crude realizations)
    eval_ongc_long = sentinel.evaluate_lead_lag_shock(symbol="ONGC", direction="BULLISH")
    assert eval_ongc_long.status == "TAILWIND_BOOST"
    assert eval_ongc_long.is_tailwind is True
    assert eval_ongc_long.conviction_adj > 0

    # 4. ONGC Short -> Vetoed (Shorting upstream oil when crude is surging)
    eval_ongc_short = sentinel.evaluate_lead_lag_shock(symbol="ONGC", direction="BEARISH")
    assert eval_ongc_short.status == "HEADWIND_VETO"
    assert eval_ongc_short.veto_recommended is True


def test_usdinr_spike_banking_and_it():
    """Verifies USD/INR sharp currency flight transmission to Bank Nifty vs IT exporters."""
    sentinel = CrossAssetLeadLagSentinel()
    # Simulate USD/INR 15m spike (+0.25%, INR weakening)
    sentinel.update_pulses(crude_delta_pct=0.0, usdinr_delta_pct=0.25)

    # 1. Bank Nifty Long -> Vetoed (Foreign capital flight)
    eval_bank_long = sentinel.evaluate_lead_lag_shock(symbol="BANKNIFTY", direction="BULLISH")
    assert eval_bank_long.status == "HEADWIND_VETO"
    assert eval_bank_long.veto_recommended is True
    assert "Currency Flight VETO" in eval_bank_long.rationale

    # 2. Bank Nifty Short -> Tailwind
    eval_bank_short = sentinel.evaluate_lead_lag_shock(symbol="BANKNIFTY", direction="BEARISH")
    assert eval_bank_short.status == "TAILWIND_BOOST"
    assert eval_bank_short.is_tailwind is True

    # 3. Infosys Long -> Tailwind (Export revenue translation advantage)
    eval_infy_long = sentinel.evaluate_lead_lag_shock(symbol="INFY", direction="BULLISH")
    assert eval_infy_long.status == "TAILWIND_BOOST"
    assert eval_infy_long.is_tailwind is True
    assert "Export Currency TAILWIND" in eval_infy_long.rationale


def test_neutral_macro_clearance():
    """Verifies that sub-threshold moves produce neutral clearance."""
    sentinel = CrossAssetLeadLagSentinel()
    # Micro-fluctuations below threshold (0.3% crude, 0.04% usdinr)
    sentinel.update_pulses(crude_delta_pct=0.30, usdinr_delta_pct=0.04)

    eval_res = sentinel.evaluate_lead_lag_shock(symbol="ASIANPAINT", direction="BULLISH")
    assert eval_res.status == "NEUTRAL_CLEAR"
    assert eval_res.veto_recommended is False
    assert eval_res.is_headwind is False


def test_lead_lag_scrutiny_integration(monkeypatch):
    """Verifies AlertScrutinyAuditor vetoes long paint setups during crude surge."""
    auditor = AlertScrutinyAuditor(min_rr_ratio=1.5)
    monkeypatch.setattr(auditor, "_execute_fast_llm_scrutiny", lambda *args, **kwargs: None)

    # Set active crude surge on global sentinel
    cross_asset_lead_lag_sentinel.update_pulses(crude_delta_pct=2.10)

    # 1. Asian Paints Long alert under crude surge -> Must be REJECTED
    alert_paint_long = SimpleNamespace(
        symbol="ASIANPAINT",
        ltp=2800.0,
        trigger_level=2800.0,
        stop_loss=2750.0,
        target_level=2950.0,
        direction="BULLISH",
        alert_type="BREAKOUT",
        rvol=2.5,
        environment="TEST",
        is_live=False,
        alert_id="test-ll-1",
        metrics={},
    )
    res_paint = auditor.scrutinize_alert(alert_paint_long)
    assert res_paint.status == "REJECTED"
    assert "Macro Shock VETO" in str(res_paint.rejection_reason)
    assert alert_paint_long.metrics["predatory_pipeline"]["eagle"]["macro_aligned"] is False

    # 2. ONGC Long alert under crude surge -> Approved with score bonus & tailwind rationale
    alert_ongc_long = SimpleNamespace(
        symbol="ONGC",
        ltp=280.0,
        trigger_level=280.0,
        stop_loss=274.0,
        target_level=300.0,
        direction="BULLISH",
        alert_type="BREAKOUT",
        rvol=2.5,
        environment="TEST",
        is_live=False,
        alert_id="test-ll-2",
        metrics={},
    )
    res_ongc = auditor.scrutinize_alert(alert_ongc_long)
    assert res_ongc.status == "APPROVED"
    assert "Macro Shock TAILWIND" in res_ongc.logic_confirmation
    assert alert_ongc_long.metrics["predatory_pipeline"]["eagle"]["macro_aligned"] is True
