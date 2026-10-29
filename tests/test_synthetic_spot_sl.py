"""
tests/test_synthetic_spot_sl.py
───────────────────────────────
Deterministic unit tests for the Synthetic Spot-Anchored Stop Loss Engine.
Verifies:
  1. Freak Option Wick Shielding: When option dips below nominal SL, but underlying
     spot holds safely above/below anchor, invalidation is suppressed.
  2. Decisive Structural Invalidation: When underlying spot genuinely violates the
     structural anchor, the trade is decisively invalidated.
  3. Catastrophic Drawdown Protection: When option premium collapses >= 32%,
     invalidation triggers to prevent total capital wipeout.
  4. Integration with evaluate_alert_invalidation in alert_evaluator.py.
"""

from __future__ import annotations

from engine.alert_model import AutoAlert
from engine.alert_evaluator import evaluate_alert_invalidation
from engine.synthetic_sl import (
    evaluate_synthetic_spot_sl,
    extract_underlying_symbol,
    extract_spot_invalidation_anchor,
)


def test_extract_underlying_symbol_and_anchor():
    """Verify symbol and spot anchor extraction from diverse alert formats."""
    alert1 = AutoAlert(
        alert_id="aa-call-nifty-ce-25000-20261012",
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        headline="Nifty Call Setup",
        summary="Test summary",
        direction="BULLISH",
        underlying_spot=25100.0,
        strike=25000.0,
        option_type="CE",
        contract_symbol="NIFTY26OCT25000CE",
        ltp=120.0,
        trigger_level=120.0,
        stop_loss=90.0,
        target_level=180.0,
        actionable_plan={"underlying_sl": 24980.0},
        metrics={"spot_invalidation_anchor": 24980.0},
        is_live=True,
    )
    assert extract_underlying_symbol(alert1) == "NIFTY"
    assert extract_spot_invalidation_anchor(alert1) == 24980.0

    # Stock option alert
    alert2 = AutoAlert(
        alert_id="aa-orb-reliance-20261012",
        alert_type="ORB",
        stage="IGNITED",
        symbol="RELIANCE",
        exchange="NSE",
        headline="Reliance Breakout",
        summary="Test summary",
        direction="BULLISH",
        strike=3000.0,
        option_type="CE",
        contract_symbol="RELIANCE26OCT3000CE",
        ltp=45.0,
        trigger_level=45.0,
        stop_loss=32.0,
        target_level=70.0,
        metrics={"spot_invalidation_anchor": 2960.0, "underlying_symbol": "RELIANCE"},
        is_live=True,
    )
    assert extract_underlying_symbol(alert2) == "RELIANCE"
    assert extract_spot_invalidation_anchor(alert2) == 2960.0


def test_freak_wick_shielding_bullish():
    """Verify that a temporary option wick below SL is shielded if spot is holding."""
    alert = AutoAlert(
        alert_id="aa-gamma-banknifty-ce-55000-20261012",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="BANKNIFTY",
        exchange="NSE",
        headline="Bank Nifty Call Setup",
        summary="Test summary",
        direction="BULLISH",
        strike=55000.0,
        option_type="CE",
        contract_symbol="BANKNIFTY26OCT55000CE",
        expiry_date="2026-11-05",
        ltp=250.0,  # Entry was around 250
        trigger_level=250.0,
        stop_loss=200.0,  # Nominal SL = 200
        target_level=350.0,
        underlying_spot=55100.0,
        metrics={"spot_invalidation_anchor": 54800.0, "option_entry_premium": 250.0},
        actionable_plan={"underlying_sl": 54800.0},
        is_live=True,
        environment="LIVE",
    )

    # Option dipped to 192 (below 200 SL), but Bank Nifty spot is 55,050 (well above 54,800)
    # Option drawdown: (250 - 192) / 250 = 23.2% (< 32%)
    eval_res = evaluate_synthetic_spot_sl(
        alert=alert,
        current_option_ltp=192.0,
        current_spot_override=55050.0,
    )

    assert eval_res.is_invalidated is False
    assert eval_res.is_freak_wick_shielded is True
    assert "Shielded BANKNIFTY from momentary option premium freak dip" in (
        eval_res.shield_reason or ""
    )


def test_decisive_spot_invalidation_bullish():
    """Verify that when spot breaches structural support, trade is invalidated decisively."""
    alert = AutoAlert(
        alert_id="aa-gamma-banknifty-ce-55000-20261012",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="BANKNIFTY",
        exchange="NSE",
        headline="Bank Nifty Call Setup",
        summary="Test summary",
        direction="BULLISH",
        strike=55000.0,
        option_type="CE",
        contract_symbol="BANKNIFTY26OCT55000CE",
        expiry_date="2026-11-05",
        ltp=250.0,
        trigger_level=250.0,
        stop_loss=200.0,
        target_level=350.0,
        underlying_spot=55100.0,
        metrics={"spot_invalidation_anchor": 54800.0, "option_entry_premium": 250.0},
        actionable_plan={"underlying_sl": 54800.0},
        is_live=True,
        environment="LIVE",
    )

    # Bank Nifty spot collapsed to 54,750 (below 54,800 anchor)
    eval_res = evaluate_synthetic_spot_sl(
        alert=alert,
        current_option_ltp=190.0,
        current_spot_override=54700.0,
    )

    assert eval_res.is_invalidated is True
    assert eval_res.is_freak_wick_shielded is False
    assert "breached thesis invalidation anchor below support" in (eval_res.rejection_reason or "")


def test_freak_wick_shielding_bearish_put():
    """Verify that a Bearish Put setup shields against option wicks when spot is below resistance."""
    alert = AutoAlert(
        alert_id="aa-put-nifty-pe-24800-20261012",
        alert_type="INDEX_PUT_SETUP",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        headline="Nifty Put Setup",
        summary="Test summary",
        direction="BEARISH",
        strike=24800.0,
        option_type="PE",
        contract_symbol="NIFTY26OCT24800PE",
        expiry_date="2026-11-05",
        ltp=110.0,
        trigger_level=110.0,
        stop_loss=85.0,
        target_level=160.0,
        underlying_spot=24750.0,
        metrics={"spot_invalidation_anchor": 24860.0, "option_entry_premium": 110.0},
        actionable_plan={"underlying_sl": 24860.0},
        is_live=True,
        environment="LIVE",
    )

    # Option premium dips to 80 (below 85 SL), but Nifty spot is 24,730 (well below 24,860 resistance)
    eval_res = evaluate_synthetic_spot_sl(
        alert=alert,
        current_option_ltp=80.0,
        current_spot_override=24730.0,
    )

    assert eval_res.is_invalidated is False
    assert eval_res.is_freak_wick_shielded is True


def test_catastrophic_drawdown_protection():
    """Verify that an extreme option loss (>= 32%) triggers invalidation even if spot is barely holding."""
    alert = AutoAlert(
        alert_id="aa-call-midcp-ce-12800-20261012",
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        symbol="MIDCPNIFTY",
        exchange="NSE",
        headline="Midcap Nifty Call Setup",
        summary="Test summary",
        direction="BULLISH",
        strike=12800.0,
        option_type="CE",
        contract_symbol="MIDCPNIFTY26OCT12800CE",
        expiry_date="2026-11-05",
        ltp=100.0,
        trigger_level=100.0,
        stop_loss=75.0,
        target_level=150.0,
        underlying_spot=12850.0,
        metrics={"spot_invalidation_anchor": 12800.0, "option_entry_premium": 100.0},
        actionable_plan={"underlying_sl": 12800.0},
        is_live=True,
        environment="LIVE",
    )

    # Option premium crashed from 100 to 62 (-38% drawdown >= 32%)
    eval_res = evaluate_synthetic_spot_sl(
        alert=alert,
        current_option_ltp=62.0,
        current_spot_override=12810.0,
    )

    assert eval_res.is_invalidated is True
    assert "exceeding 32% risk floor" in (eval_res.rejection_reason or "")


def test_evaluate_alert_invalidation_integration_with_synthetic_sl(monkeypatch):
    """Verify evaluate_alert_invalidation uses synthetic spot SL seamlessly."""
    alert = AutoAlert(
        alert_id="aa-call-banknifty-ce-56000-20261012",
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        symbol="BANKNIFTY",
        exchange="NSE",
        headline="Bank Nifty Call Setup",
        summary="Test summary",
        direction="BULLISH",
        strike=56000.0,
        option_type="CE",
        contract_symbol="BANKNIFTY26OCT56000CE",
        expiry_date="2026-11-05",
        ltp=200.0,
        trigger_level=200.0,
        stop_loss=160.0,
        target_level=280.0,
        underlying_spot=56100.0,
        metrics={"spot_invalidation_anchor": 55850.0, "option_entry_premium": 200.0},
        actionable_plan={"underlying_sl": 55850.0},
        is_live=True,
        environment="LIVE",
    )

    # Mock fetch_live_underlying_spot to return healthy spot: 56,080
    monkeypatch.setattr(
        "engine.synthetic_sl.fetch_live_underlying_spot",
        lambda *args, **kwargs: 56080.0,
    )

    # Option dipped to 155 (below 160 SL), but spot is 56,080
    # Invalidation must be shielded!
    res = evaluate_alert_invalidation(alert, current_ltp=155.0)
    assert res is None  # Shielded from premature stop-out!


def test_0dte_option_rejects_freak_wick_shielding():
    """Verify that on 0-DTE expiry contracts, option SL breach is NOT shielded, preventing theta wipeout."""
    alert = AutoAlert(
        alert_id="aa-nifty-22550ce-0dte-20261013",
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        headline="Nifty 0-DTE Call Setup",
        summary="Test 0-DTE decay",
        direction="BULLISH",
        strike=22550.0,
        option_type="CE",
        contract_symbol="NIFTY26OCT22550CE",
        ltp=66.50,
        trigger_level=66.50,
        stop_loss=54.57,
        target_level=90.0,
        underlying_spot=22557.0,
        metrics={"spot_invalidation_anchor": 22517.0, "option_entry_premium": 66.50, "dte": 0},
        actionable_plan={"underlying_sl": 22517.0},
        is_live=True,
        environment="LIVE",
    )

    # Option dropped to 52.0 (below 54.57 SL by >3%, drawdown = 21.8% >= 18%)
    # Even though spot is 22,530 (above 22,517 anchor), 0-DTE theta mandates fail-closed exit!
    eval_res = evaluate_synthetic_spot_sl(
        alert=alert,
        current_option_ltp=52.0,
        current_spot_override=22530.0,
    )

    assert eval_res.is_invalidated is True
    assert eval_res.is_freak_wick_shielded is False
    assert "0-DTE Theta Invalidation" in (eval_res.rejection_reason or "")


def test_derisked_milestone_enforces_breakeven_protection():
    """Verify that a trade which achieved T0.5 milestone cuts at breakeven rather than taking a full loss."""
    alert = AutoAlert(
        alert_id="aa-derisked-nifty-ce-20261013",
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        headline="Nifty De-risked Call Setup",
        summary="Test de-risk protection",
        direction="BULLISH",
        strike=22550.0,
        option_type="CE",
        contract_symbol="NIFTY26OCT22550CE",
        ltp=100.0,
        trigger_level=100.0,
        stop_loss=80.0,
        target_level=140.0,
        underlying_spot=22500.0,
        metrics={"spot_invalidation_anchor": 22460.0, "option_entry_premium": 100.0},
        actionable_plan={"underlying_sl": 22460.0},
        achieved_milestones=["T0_5_ACHIEVED"],
        is_live=True,
        environment="LIVE",
    )

    # Option falls back to 96.0 (< 100 * 0.98), while spot is 22,490 (still above 22,460 anchor)
    eval_res = evaluate_synthetic_spot_sl(
        alert=alert,
        current_option_ltp=96.0,
        current_spot_override=22490.0,
    )

    assert eval_res.is_invalidated is True
    assert eval_res.is_freak_wick_shielded is False
    assert "Breakeven Protection Triggered" in (eval_res.rejection_reason or "")
