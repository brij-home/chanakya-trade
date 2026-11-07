"""
tests/test_executable_risk_reward.py
────────────────────────────────────
Unit tests for Institutional Executable Risk:Reward & Opportunity Concentration (S05).
Verifies:
  1. Distinct isolation of 5 R:R dimensions without mathematical mixing.
  2. Realistic execution friction (Ask entry, Bid exit, and dated statutory charges).
  3. Gap stress risk (1.5x stop distance).
  4. Execution slippage sensitivity bands (10bps, 25bps, 50bps).
  5. Opportunity ranking prioritizing Index options and penalizing over-concentrated exposure.
"""

from __future__ import annotations


from engine.executable_risk_reward import (
    calculate_net_executable_rr,
    rank_desk_opportunities,
    MultiHorizonRRMetrics,
)


def test_distinct_isolation_of_five_rr_dimensions():
    """Verify all 5 R:R dimensions are cleanly stored and accessible."""
    metrics = calculate_net_executable_rr(
        symbol="NIFTY",
        direction="BULLISH",
        entry_price=150.0,
        stop_loss=120.0,
        target_price=240.0,
        quantity=65,
        segment="OPTIONS",
        underlying_entry=25000.0,
        underlying_sl=24900.0,
        underlying_target=25300.0,
        spread_max_profit=90.0,
        spread_max_loss=30.0,
    )

    assert isinstance(metrics, MultiHorizonRRMetrics)

    # 1. Underlying Structural R:R: (25300 - 25000) / (25000 - 24900) = 300 / 100 = 3.0
    assert metrics.underlying_structural_rr == 3.0

    # 2. Option Premium Scenario R:R: (240 - 150) / (150 - 120) = 90 / 30 = 3.0
    assert metrics.option_premium_scenario_rr == 3.0

    # 3. Spread Expiry Payoff R:R: 90 / 30 = 3.0
    assert metrics.spread_expiry_payoff_rr == 3.0

    # 4. Executable Indicative R:R after friction: strictly less than 3.0 due to taxes & spread
    assert metrics.executable_indicative_rr is not None
    assert metrics.executable_indicative_rr < 3.0
    assert metrics.executable_indicative_rr >= 2.0

    # 5. Observed outcome starts as None prior to post-trade execution
    assert metrics.observed_outcome_rr is None


def test_realistic_friction_and_statutory_charges():
    """Verify Ask entry, Bid exit, and statutory transaction costs are deducted."""
    # Market quotes: entry at ask (152.0), exit at bid (238.0)
    metrics = calculate_net_executable_rr(
        symbol="BANKNIFTY",
        direction="BULLISH",
        entry_price=150.0,
        stop_loss=120.0,
        target_price=240.0,
        quantity=30,
        segment="OPTIONS",
        bid=238.0,
        ask=152.0,
        trade_date="2026-11-01",
    )

    assert metrics.entry_ask == 152.0
    assert metrics.exit_bid == 238.0
    assert metrics.spread_friction_pts == 2.0  # 152.0 - 150.0
    assert metrics.statutory_charges_total > 0.0  # STT + GST + Exchange + SEBI + Stamp Duty

    # Net executable R:R is lower than gross 3.0
    assert metrics.executable_indicative_rr < 3.0


def test_gap_stress_risk_scenario():
    """Stop-loss gap scenario models 1.5x stop distance risk for gap-down protection."""
    metrics = calculate_net_executable_rr(
        symbol="TATASTEEL",
        direction="BULLISH",
        entry_price=150.0,
        stop_loss=140.0,  # 10 pts stop
        target_price=180.0,
        quantity=100,
        segment="EQUITY_INTRADAY",
    )

    # Gap stress risk must be roughly 1.5x the base stop distance
    assert metrics.gap_stress_risk_pts >= 15.0


def test_sensitivity_bands():
    """Verify slippage sensitivity bands for 10bps, 25bps, and 50bps."""
    metrics = calculate_net_executable_rr(
        symbol="RELIANCE",
        direction="BULLISH",
        entry_price=2800.0,
        stop_loss=2750.0,
        target_price=2950.0,
        quantity=50,
        segment="EQUITY_INTRADAY",
    )

    bands = metrics.sensitivity_bands
    assert "10bps_slippage_rr" in bands
    assert "25bps_slippage_rr" in bands
    assert "50bps_slippage_rr" in bands
    # Higher slippage yields lower R:R
    assert bands["10bps_slippage_rr"] >= bands["25bps_slippage_rr"]
    assert bands["25bps_slippage_rr"] >= bands["50bps_slippage_rr"]


def test_opportunity_ranking_prioritizes_indices_and_hedges():
    """Index setups rank ahead of single-stock F&O; open exposure is deprioritized."""
    candidates = [
        {
            "symbol": "RELIANCE",
            "conviction_tier": "APEX_CONFLUENCE",
            "executable_indicative_rr": 3.5,
        },
        {
            "symbol": "NIFTY",
            "conviction_tier": "HIGH_CONVICTION",
            "executable_indicative_rr": 2.8,
        },
        {
            "symbol": "BANKNIFTY",
            "conviction_tier": "APEX_CONFLUENCE",
            "executable_indicative_rr": 3.2,
        },
        {
            "symbol": "INFY",
            "conviction_tier": "HIGH_CONVICTION",
            "executable_indicative_rr": 2.5,
        },
    ]

    # Portfolio already holds open exposure in BANKNIFTY
    ranked = rank_desk_opportunities(candidates, active_portfolio_exposures=["BANKNIFTY"])

    # 1. NIFTY should rank first (Index with NO existing open exposure)
    # 2. BANKNIFTY follows (Index with open exposure)
    # 3. RELIANCE (Apex stock F&O)
    # 4. INFY (High stock F&O)
    assert ranked[0]["symbol"] == "NIFTY"
    assert ranked[1]["symbol"] == "BANKNIFTY"
    assert ranked[2]["symbol"] == "RELIANCE"
    assert ranked[3]["symbol"] == "INFY"
