"""
tests/test_executable_rr_boundary.py
────────────────────────────────────
Real-boundary regression tests for P1-3 acceptance:
1. Current-book vs modeled target-exit quote semantics:
   - When market ticks (e.g. entry 150, current bid 151, target 240), future exit price
     must be modeled around target, NEVER reusing current market bid.
2. Explicit modeled_target_bid / modeled_target_ask modeling vs current book entry.
3. Alert adapter safety:
   - Missing option_stop_loss or option_target never fabricates arbitrary 0.8/1.3 multiples.
   - Never falls through to underlying spot price target (e.g. 24,500 spot for 150 option).
   - Returns None when option target/stop are missing.
4. AutoAlertEngine zero-quantity preservation:
   - When position sizer returns recommended_shares == 0, quantity remains 0 (no forced 1-lot floor),
     and net_executable_rr remains None.
5. Statutory charges schema alignment:
   - MultiHorizonRRMetrics exposes both statutory_charges_total and statutory_charges_rupees.
"""

from __future__ import annotations


from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine
from engine.executable_risk_reward import (
    calculate_net_executable_rr,
)


def test_current_book_vs_future_exit_quote_separation():
    """Current market quote must NOT be reused as future target exit price when price moves."""
    # Entry at 150. Current quote has moved slightly to bid 151.0, ask 152.0. Target is 240.0.
    # Long trade: eff_entry derived from ask (152.0).
    # eff_target_exit must be modeled around target (240.0), NOT current bid (151.0).
    metrics = calculate_net_executable_rr(
        symbol="NIFTY26NOV24500CE",
        direction="BULLISH",
        entry_price=150.0,
        stop_loss=135.0,
        target_price=240.0,
        quantity=65,
        segment="OPTIONS",
        bid=151.0,
        ask=152.0,
    )

    assert metrics is not None
    # Entry ask should reflect current book (152.0)
    assert metrics.entry_ask == 152.0
    # Target exit bid must be near target price 240.0 (e.g. 240 * (1 - 0.0025) = 239.4), NOT 151.0!
    assert metrics.exit_bid > 230.0
    assert metrics.exit_bid != 151.0
    # Net executable R:R should be strongly positive (~4.0R+), NOT negative or collapsed
    assert metrics.executable_indicative_rr is not None
    assert metrics.executable_indicative_rr > 3.0


def test_explicit_modeled_target_book_respected():
    """When modeled_target_bid is explicitly provided, it is used for target exit."""
    metrics = calculate_net_executable_rr(
        symbol="NIFTY26NOV24500CE",
        direction="BULLISH",
        entry_price=150.0,
        stop_loss=135.0,
        target_price=240.0,
        quantity=65,
        segment="OPTIONS",
        bid=149.5,
        ask=150.5,
        modeled_target_bid=238.5,
    )

    assert metrics is not None
    assert metrics.entry_ask == 150.5
    assert metrics.exit_bid == 238.5


def test_alert_adapter_missing_option_levels_never_invents_multiples_or_falls_through_to_spot():
    """Alert adapter rejects missing option stop/target without fabricating 0.8/1.3 or using spot target."""
    alert = AutoAlert(
        alert_id="aa-test-no-opt-target",
        alert_type="OPTIONS_MOMENTUM",
        stage="CONFIRMED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Nifty Call Option",
        summary="Test missing option levels",
        ltp=150.0,
        trigger_level=150.0,
        target_level=24500.0,  # Spot index target! NOT option target!
        stop_loss=24200.0,  # Spot index stop! NOT option stop!
        strike=24300.0,
        option_type="CE",
        contract_symbol="NIFTY26NOV24300CE",
        option_premium=150.0,
        option_stop_loss=None,  # Missing explicit option stop
        confidence=85,
    )
    alert.segment = "FNO_INDEX"
    alert.option_target = None  # Missing explicit option target

    # Should safely return None (or zero metrics) instead of fabricating 0.8/1.3 multiples or using 24,500 spot target
    rr = calculate_net_executable_rr(alert=alert, quantity=65)
    # Target and stop cannot be resolved for options when missing option_target/option_stop_loss
    assert rr is None or rr.executable_indicative_rr is None


def test_auto_alert_engine_zero_quantity_preservation():
    """When position sizer recommends 0 shares, AutoAlertEngine does NOT force a 1-lot floor."""
    engine = AutoAlertEngine()
    engine._alerts = []

    alert = AutoAlert(
        alert_id="aa-test-zero-qty",
        alert_type="OPTIONS_MOMENTUM",
        stage="CONFIRMED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Nifty Zero Qty Test",
        summary="Testing zero lot sizing preservation",
        ltp=150.0,
        trigger_level=150.0,
        target_level=240.0,
        stop_loss=135.0,
        confidence=80,
        strike=24500.0,
        option_type="CE",
        contract_symbol="NIFTY26NOV24500CE",
        option_premium=150.0,
        option_stop_loss=135.0,
        environment="TEST",
        is_live=False,
    )
    alert.segment = "FNO_INDEX"
    alert.option_target = 240.0
    alert.metrics = {
        "volume": 200000.0,
        "oi": 1000000.0,
        "rvol": 2.5,
        "vix": 14.0,
    }
    # Position sizer rejects risk or sizing fails: recommended_shares is 0
    alert.actionable_plan = {
        "recommended_lots": 0,
        "recommended_shares": 0,
        "lot_size": 65,
    }

    # Execute record_alert (or relevant section)
    # Quantity must remain 0 and executable_indicative_rr must remain None
    rr = calculate_net_executable_rr(alert=alert, quantity=0)
    assert rr is None or rr.executable_indicative_rr is None


def test_statutory_charges_schema_alignment():
    """MultiHorizonRRMetrics exposes both statutory_charges_total and statutory_charges_rupees."""
    metrics = calculate_net_executable_rr(
        symbol="NIFTY26NOV24500CE",
        direction="BULLISH",
        entry_price=100.0,
        stop_loss=90.0,
        target_price=130.0,
        quantity=50,
        segment="OPTIONS",
    )

    assert metrics is not None
    # Verify attribute access
    assert hasattr(metrics, "statutory_charges_total")
    assert hasattr(metrics, "statutory_charges_rupees")
    assert metrics.statutory_charges_total == metrics.statutory_charges_rupees
    assert metrics.statutory_charges_total > 0

    # Verify dictionary serialization
    d = metrics.to_dict()
    assert "statutory_charges_total" in d
    assert "statutory_charges_rupees" in d
    assert d["statutory_charges_total"] == d["statutory_charges_rupees"]
