"""
tests/test_executable_rr_semantics.py
─────────────────────────────────────
Unit tests for executable R:R semantics:
- Bought Put (PE) operates in long premium coordinate space.
- Sold options operate in short premium coordinate space.
- Invalid anchors and losing paths do not produce positive reward.
- Missing underlying coordinates remain None (never fall back to option premium).
- Zero quantity is preserved (executable R is None).
- Charges failure sets executable R to None without fabricated fallbacks.
- Future exit quotes are modeled scenarios, never reused current market quotes.
"""

from __future__ import annotations


from engine.executable_risk_reward import (
    calculate_net_executable_rr,
)


def test_bought_put_premium_coordinate():
    """Verify bought PE is recognized as long premium coordinate."""
    res = calculate_net_executable_rr(
        symbol="NIFTY24NOV24500PE",
        direction="BEARISH",
        entry_price=150.0,
        stop_loss=120.0,
        target_price=240.0,
        quantity=50,
        segment="OPTIONS",
        ask=152.0,  # current ask
        bid=148.0,  # current bid
    )

    # Option Scenario R:R should be (240 - 150) / (150 - 120) = 90 / 30 = 3.0
    assert res.option_premium_scenario_rr == 3.0

    # Long coordinate buys at ask (152.0), not bid!
    assert res.entry_ask == 152.0

    # Modeled future exit target must be ~240 minus slippage, NOT today's bid (148.0)!
    assert res.exit_bid > 230.0
    assert res.exit_bid != 148.0

    # Executable R:R after fees should be positive and close to 3.0
    assert res.executable_indicative_rr is not None
    assert res.executable_indicative_rr > 2.0


def test_sold_call_short_premium_coordinate():
    """Verify sold CE is recognized as short premium coordinate."""
    res = calculate_net_executable_rr(
        symbol="NIFTY24NOV25000CE",
        direction="BEARISH",
        payoff_type="SHORT_OPTION",
        entry_price=150.0,
        stop_loss=180.0,
        target_price=90.0,
        quantity=50,
        segment="OPTIONS",
        ask=152.0,
        bid=148.0,
    )

    # Short option reward: 150 - 90 = 60; risk: 180 - 150 = 30 -> 2.0
    assert res.option_premium_scenario_rr == 2.0

    # Short coordinate enters at bid (148.0)
    assert res.entry_ask == 148.0

    # Future target exit buys back at target + slippage (~90)
    assert res.exit_bid < 100.0


def test_losing_path_or_inverted_anchors_rejected():
    """Verify target on wrong side does not turn into positive reward via abs()."""
    # For a long coordinate, target < entry is an invalid / losing path
    res = calculate_net_executable_rr(
        symbol="NIFTY24NOV24500CE",
        direction="BULLISH",
        entry_price=150.0,
        stop_loss=120.0,
        target_price=100.0,  # Target below entry!
        quantity=50,
        segment="OPTIONS",
    )
    assert res.option_premium_scenario_rr is None
    assert res.executable_indicative_rr is None


def test_missing_underlying_coordinates_remain_none():
    """Verify underlying_structural_rr is strictly None when underlying levels not supplied."""
    res = calculate_net_executable_rr(
        symbol="NIFTY24NOV24500CE",
        direction="BULLISH",
        entry_price=150.0,
        stop_loss=120.0,
        target_price=240.0,
        quantity=50,
        segment="OPTIONS",
        underlying_entry=None,  # No underlying levels
        underlying_sl=None,
        underlying_target=None,
    )
    # Must NOT fall back to option premium!
    assert res.underlying_structural_rr is None


def test_zero_quantity_preserved():
    """Verify quantity=0 leaves executable_indicative_rr as None."""
    res = calculate_net_executable_rr(
        symbol="NIFTY24NOV24500CE",
        direction="BULLISH",
        entry_price=150.0,
        stop_loss=120.0,
        target_price=240.0,
        quantity=0,
        segment="OPTIONS",
    )
    assert res.executable_indicative_rr is None


def test_charges_failure_sets_net_rr_unavailable(monkeypatch):
    """Verify charges calculation error sets executable R to None without fabricated fallback."""

    def fail_charges(*args, **kwargs):
        raise RuntimeError("Broker tax schedule unavailable")

    monkeypatch.setattr(
        "engine.executable_risk_reward.calculate_transaction_charges",
        fail_charges,
    )

    res = calculate_net_executable_rr(
        symbol="NIFTY24NOV24500CE",
        direction="BULLISH",
        entry_price=150.0,
        stop_loss=120.0,
        target_price=240.0,
        quantity=50,
        segment="OPTIONS",
    )
    assert res.executable_indicative_rr is None
    assert res.statutory_charges_total is None
