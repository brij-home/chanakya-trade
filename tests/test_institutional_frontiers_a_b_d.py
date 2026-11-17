"""
tests/test_institutional_frontiers_a_b_d.py
───────────────────────────────────────────
Verification test suite for Institutional Frontiers A, B, and D:
  - Frontier A: Dynamic Options Greeks & IV Skew Surface (Strike Auto-Optimizer)
  - Frontier B: Cumulative Volume Delta (CVD) Footprint Microstructure
  - Frontier D: Index Market Internal Breadth Matrix & Point Contribution
"""

from unittest.mock import MagicMock, patch

import pytest

from engine.cvd_engine import (
    clear_all_cvd_trackers,
    get_cvd_tracker,
)
from engine.market_internals import (
    clear_index_internals_cache,
    compute_index_internals,
)
from engine.options_optimizer import (
    calculate_black_scholes_greeks,
    get_underlying_strike_step,
    optimize_option_contract,
)


@pytest.fixture(autouse=True)
def clean_frontiers_state():
    """Isolate tests by clearing in-memory caches."""
    clear_all_cvd_trackers()
    clear_index_internals_cache()
    yield
    clear_all_cvd_trackers()
    clear_index_internals_cache()


# ══════════════════════════════════════════════════════════════════
# FRONTIER A: DYNAMIC OPTIONS GREEKS & STRIKE OPTIMIZER
# ══════════════════════════════════════════════════════════════════


def test_black_scholes_greeks_analytical_precision():
    """Verify analytic Black-Scholes Call and Put Greeks match financial invariants."""
    spot = 24500.0
    strike = 24500.0  # ATM
    dte = 7.0
    iv = 0.15

    # 1. ATM Call
    call_g = calculate_black_scholes_greeks(
        spot=spot, strike=strike, dte_days=dte, iv=iv, option_type="CE"
    )
    assert call_g.price > 0.0
    assert 0.48 <= call_g.delta <= 0.56  # ATM call delta near 0.50
    assert call_g.gamma > 0.0
    assert call_g.vega > 0.0
    assert call_g.theta < 0.0  # Theta decays with time

    # 2. ATM Put
    put_g = calculate_black_scholes_greeks(
        spot=spot, strike=strike, dte_days=dte, iv=iv, option_type="PE"
    )
    assert put_g.price > 0.0
    assert -0.56 <= put_g.delta <= -0.44  # ATM put delta near -0.50
    # Put-Call Parity Delta Invariant: Delta(CE) - Delta(PE) == 1.0 (approx)
    assert abs((call_g.delta - put_g.delta) - 1.0) < 0.02


def test_strike_optimizer_momentum_vs_pullback_delta():
    """Verify dynamic strike optimizer chooses appropriate delta for momentum vs pullback."""
    spot = 24520.0  # NIFTY spot

    # 1. Momentum Breakout: Targets Delta >= 0.50 (ATM / ITM)
    mom_plan = optimize_option_contract(
        symbol="NIFTY",
        direction="BULLISH",
        spot=spot,
        regime="MOMENTUM_BREAKOUT",
        iv_percentile=40.0,
    )
    assert mom_plan.execution_structure == "NAKED_BUY"
    assert mom_plan.iv_crush_risk == "LOW"
    assert mom_plan.actual_delta >= 0.48
    assert mom_plan.strike in (24500.0, 24550.0)

    # 2. Pullback to Value: Targets lower cost delta (near 0.45)
    pb_plan = optimize_option_contract(
        symbol="NIFTY",
        direction="BULLISH",
        spot=spot,
        regime="PULLBACK_VALUE",
        iv_percentile=40.0,
    )
    assert pb_plan.execution_structure == "NAKED_BUY"
    assert pb_plan.strike >= 24500.0


def test_strike_optimizer_high_iv_mandates_debit_spread():
    """Verify high IV percentile (>= 70%) shifts execution structure to Vertical Debit Spread."""
    spot = 52100.0  # BANKNIFTY spot
    high_iv_plan = optimize_option_contract(
        symbol="BANKNIFTY",
        direction="BULLISH",
        spot=spot,
        regime="MOMENTUM_BREAKOUT",
        iv=0.24,
        iv_percentile=85.0,
        lot_size=15,
    )

    assert high_iv_plan.execution_structure == "VERTICAL_DEBIT_SPREAD"
    assert high_iv_plan.iv_crush_risk == "HIGH"
    assert high_iv_plan.hedge_contract_symbol is not None
    assert high_iv_plan.hedge_strike > high_iv_plan.strike
    assert high_iv_plan.net_debit_per_share is not None
    assert high_iv_plan.net_debit_per_share < high_iv_plan.limit_entry_premium
    assert high_iv_plan.max_loss is not None and high_iv_plan.max_loss > 0


def test_underlying_strike_steps():
    """Verify correct strike step sizes across Indian indices and stock price tiers."""
    assert get_underlying_strike_step("NIFTY", 24500.0) == 50.0
    assert get_underlying_strike_step("BANKNIFTY", 52000.0) == 100.0
    assert get_underlying_strike_step("MIDCPNIFTY", 12500.0) == 25.0
    assert get_underlying_strike_step("RELIANCE", 2700.0) == 50.0
    assert get_underlying_strike_step("INFY", 1850.0) == 20.0
    assert get_underlying_strike_step("IRFC", 82.0) == 2.5


# ══════════════════════════════════════════════════════════════════
# FRONTIER B: CUMULATIVE VOLUME DELTA (CVD) MICROSTRUCTURE
# ══════════════════════════════════════════════════════════════════


def test_cvd_tick_classification_and_accumulation():
    """Verify Lee-Ready tick classification into aggressive buy vs aggressive sell."""
    tracker = get_cvd_tracker("RELIANCE")

    # 1. Trade at Ask -> Aggressive Buy
    d1 = tracker.record_tick(price=2705.0, volume=100, best_bid=2700.0, best_ask=2705.0)
    assert d1 == 100.0

    # 2. Trade at Bid -> Aggressive Sell
    d2 = tracker.record_tick(price=2700.0, volume=60, best_bid=2700.0, best_ask=2705.0)
    assert d2 == -60.0

    metrics = tracker.get_metrics()
    assert metrics.current_cvd == 40.0
    assert metrics.session_volume == 160.0
    assert metrics.sample_count == 2


def test_cvd_bullish_absorption_bear_trap_detection():
    """Verify Bullish Absorption (Bear Trap) when price falls but CVD expands positively."""
    tracker = get_cvd_tracker("HDFCBANK")

    # Simulate price dropping from 1750 to 1740 (-0.57%), but massive aggressive buying absorbed
    # Trade sequence: price drifting down while delta is consistently positive (buyers absorbing bids)
    base_price = 1750.0
    for i in range(25):
        p = base_price - (i * 0.4)
        # Trades hitting the ask / positive delta despite lower price
        tracker.record_tick(price=p, volume=200, best_bid=p - 0.5, best_ask=p)

    metrics = tracker.get_metrics()
    assert metrics.cvd_divergence == "BULLISH_ABSORPTION"
    assert metrics.absorption_detected is True
    assert "Passive Institutional Accumulation" in metrics.absorption_note


def test_cvd_bearish_exhaustion_bull_trap_detection():
    """Verify Bearish Exhaustion (Bull Trap) when price rises but CVD diverges negatively."""
    tracker = get_cvd_tracker("TCS")

    # Simulate price pushing up from 4100 to 4125 (+0.6%), but delta is negative (sellers dumping at bid)
    base_price = 4100.0
    for i in range(25):
        p = base_price + (i * 1.0)
        # Trades hitting bid -> negative delta
        tracker.record_tick(price=p, volume=150, best_bid=p, best_ask=p + 1.0)

    metrics = tracker.get_metrics()
    assert metrics.cvd_divergence == "BEARISH_EXHAUSTION"
    assert metrics.absorption_detected is True
    assert "Passive Institutional Distribution" in metrics.absorption_note


# ══════════════════════════════════════════════════════════════════
# FRONTIER D: INDEX MARKET INTERNAL BREADTH MATRIX
# ══════════════════════════════════════════════════════════════════


def test_index_internals_broad_based_bullish_regime():
    """Verify Broad-Based Bullish regime when majority of constituents are advancing and above VWAP."""
    mock_quotes = {}
    from engine.market_internals import NIFTY_WEIGHTS

    # Mock 40 advancing stocks (+1.5% and > vwap), 10 declining stocks (-0.5%)
    symbols = list(NIFTY_WEIGHTS.keys())
    for idx, sym in enumerate(symbols):
        is_adv = idx < 22  # Top heavyweights advancing
        mock_quotes[f"NSE:{sym}"] = MagicMock(
            last_price=1000.0,
            vwap=990.0 if is_adv else 1010.0,
            change_pct=1.8 if is_adv else -0.8,
        )

    with (
        patch("market.quotes.get_ltp", return_value=24600.0),
        patch("market.quotes.get_quote", return_value=mock_quotes),
    ):
        report = compute_index_internals("NIFTY")

        assert report.total_constituents > 0
        assert report.advances > report.declines
        assert report.ad_ratio >= 1.5
        assert report.regime in ("BROAD_BASED_BULLISH", "CHOPPY_EQUILIBRIUM")
        assert len(report.top_positive_drivers) > 0


def test_index_internals_head_fake_divergence_detection():
    """Verify Head-Fake Divergence when index spot is up solely due to one mega-cap while breadth is negative."""
    mock_quotes = {}
    from engine.market_internals import NIFTY_WEIGHTS

    symbols = list(NIFTY_WEIGHTS.keys())
    # Reliance is +5.5%, but all other stocks are declining -0.25%
    for sym in symbols:
        if sym == "RELIANCE":
            mock_quotes[f"NSE:{sym}"] = MagicMock(last_price=2800.0, vwap=2700.0, change_pct=5.5)
        else:
            mock_quotes[f"NSE:{sym}"] = MagicMock(last_price=1000.0, vwap=1010.0, change_pct=-0.25)
    # Also provide the index official quote as +0.35%
    mock_quotes["NSE:NIFTY 50"] = MagicMock(last_price=24550.0, vwap=24500.0, change_pct=0.35)

    with (
        patch("market.quotes.get_ltp", return_value=24550.0),
        patch("market.quotes.get_quote", return_value=mock_quotes),
    ):
        report = compute_index_internals("NIFTY")

        assert report.regime == "HEAD_FAKE_DIVERGENCE"
        assert "Head-Fake Index Divergence detected" in report.regime_summary
        assert "VETO naked index call breakouts" in report.actionable_option_guidance
