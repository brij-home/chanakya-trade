"""
tests/test_dynamic_risk.py
──────────────────────────
Deterministic regression test suite for the Hierarchical Dynamic Risk Scaling Engine:
  - Price Tier Resolvers & Absolute Floors (Sub-₹100 to >₹10,000)
  - Sector Risk Profiles & Volatility Parity Beta
  - Macro India VIX Regime Multipliers
  - Structural Clamping (Monotonicity, Volatility Bounding & Asymmetric R:R >= 1:2.0)
  - Hierarchical Position Sizing (Lot Quantization, Circuit Headroom & SEBI Physical Delivery)
"""

from __future__ import annotations


from engine.dynamic_risk import (
    resolve_price_tier,
    resolve_sector_risk_profile,
    get_vix_regime_multiplier,
    clamp_dynamic_risk,
    calculate_hierarchical_position_size,
)


def test_resolve_price_tier_across_all_bands():
    """Verifies that nominal price accurately maps to appropriate absolute floors."""
    # Sub-₹100 Micro
    t1 = resolve_price_tier(38.50)
    assert t1.tier_name == "SUB_100_MICRO"
    assert t1.abs_min_risk_pts == 0.10
    assert t1.min_opt_premium == 0.50

    # ₹100 - ₹500 Mid
    t2 = resolve_price_tier(395.0)
    assert t2.tier_name == "SMALL_MID_100_500"
    assert t2.abs_min_risk_pts == 0.50
    assert t2.min_opt_premium == 1.50

    # ₹500 - ₹2,500 Core Heavyweight
    t3 = resolve_price_tier(1450.0)
    assert t3.tier_name == "MID_LARGE_500_2500"
    assert t3.abs_min_risk_pts == 2.00
    assert t3.min_opt_premium == 3.00

    # ₹2,500 - ₹10,000 High-Ticket
    t4 = resolve_price_tier(3500.0)
    assert t4.tier_name == "HIGH_TICKET_2500_10000"
    assert t4.abs_min_risk_pts == 6.00
    assert t4.min_opt_premium == 8.00

    # >₹10,000 Ultra-High Ticket
    t5 = resolve_price_tier(140000.0)
    assert t5.tier_name == "ULTRA_HIGH_ABOVE_10000"
    assert t5.abs_min_risk_pts == 25.00
    assert t5.min_opt_premium == 20.00


def test_resolve_sector_risk_profile_and_beta():
    """Verifies sector categorization, beta allocation, and trailing ATR multipliers."""
    # High-Beta Momentum (Railways / Defence)
    p_rail = resolve_sector_risk_profile("railways")
    assert p_rail.category == "HIGH_BETA_MOMENTUM"
    assert p_rail.default_beta >= 1.8
    assert p_rail.trailing_atr_multiplier == 2.0
    assert p_rail.max_sector_capital_pct == 25.0

    # Cyclical / Commodities (Metals)
    p_metal = resolve_sector_risk_profile("metals")
    assert p_metal.category == "CYCLICAL_COMMODITY"
    assert p_metal.default_beta == 1.4

    # Defensive Quality (FMCG)
    p_fmcg = resolve_sector_risk_profile("fmcg")
    assert p_fmcg.category == "DEFENSIVE_QUALITY"
    assert p_fmcg.default_beta <= 0.8
    assert p_fmcg.trailing_atr_multiplier == 1.1

    # Core Benchmark (Banking)
    p_bank = resolve_sector_risk_profile("banking")
    assert p_bank.category == "CORE_BENCHMARK"
    assert p_bank.default_beta == 1.0


def test_vix_regime_multipliers():
    """Verifies dynamic risk scaling adapts to macro volatility regimes."""
    # Compression chop
    mult, note = get_vix_regime_multiplier(10.5)
    assert mult == 0.75
    assert "COMPRESSION" in note

    # Optimal normal regime
    mult, note = get_vix_regime_multiplier(14.0)
    assert mult == 1.00
    assert "OPTIMAL" in note

    # Elevated volatility defense
    mult, note = get_vix_regime_multiplier(22.0)
    assert mult == 0.70
    assert "ELEVATED" in note

    # Tail risk crisis
    mult, note = get_vix_regime_multiplier(29.0)
    assert mult == 0.50
    assert "TAIL_RISK" in note


def test_clamp_dynamic_risk_sub_100_equity():
    """
    Sub-₹100 equity (e.g. SUZLON at ₹38.50) with tiny micro-range (0.04 pts)
    must clamp to ₹0.10 floor, producing valid R:R >= 1:2.0 without inverted levels.
    """
    res = clamp_dynamic_risk(
        symbol="SUZLON",
        entry_price=38.50,
        raw_stop_loss=38.46,  # 0.04 pts raw risk
        direction="BULLISH",
    )
    assert res.price_tier == "SUB_100_MICRO"
    assert res.abs_min_risk_pts == 0.10
    assert res.risk_points >= 0.10
    assert res.clamped_stop_loss < res.entry_price < res.target_1 < res.target_2 < res.runner_target
    assert res.rr_ratio >= 1.95


def test_clamp_dynamic_risk_bearish_monotonicity():
    """
    Bearish trade plan enforces strict monotonicity:
    Runner < Target 2 < Target 1 < Entry < Stop Loss.
    """
    res = clamp_dynamic_risk(
        symbol="ITC",
        entry_price=480.0,
        raw_stop_loss=484.5,
        direction="BEARISH",
        sector="fmcg",
    )
    assert res.direction == "BEARISH"
    assert res.runner_target < res.target_2 < res.target_1 < res.entry_price < res.clamped_stop_loss
    assert res.rr_ratio >= 1.95
    assert res.no_chase_boundary < res.entry_price


def test_clamp_dynamic_risk_atr_volatility_bounding():
    """When ATR is supplied, risk distance is bounded between 0.35x ATR and 2.0x ATR."""
    entry = 1200.0
    atr = 30.0  # 15m ATR = 30 pts

    # Very small technical stop (e.g. 5 pts) -> bounded up to at least 0.35 * 30 = 10.5 pts
    res_tight = clamp_dynamic_risk(
        symbol="INFY",
        entry_price=entry,
        raw_stop_loss=entry - 5.0,
        direction="BULLISH",
        atr=atr,
    )
    assert res_tight.risk_points >= (atr * 0.35)

    # Very wide technical stop (e.g. 100 pts) -> bounded down to at most 2.0 * 30 = 60 pts
    res_wide = clamp_dynamic_risk(
        symbol="INFY",
        entry_price=entry,
        raw_stop_loss=entry - 100.0,
        direction="BULLISH",
        atr=atr,
    )
    assert res_wide.risk_points <= (atr * 2.05)


def test_hierarchical_position_sizing_volatility_parity():
    """
    High-Beta stock (RVNL, beta=2.0) receives a smaller position size than
    Defensive stock (DABUR, beta=0.7) of identical price to equalize portfolio variance risk.
    """
    entry = 500.0
    sl = 490.0
    capital = 200000.0

    size_high_beta = calculate_hierarchical_position_size(
        symbol="RVNL",
        entry_price=entry,
        stop_loss=sl,
        capital=capital,
        max_capital_pct=50.0,
        sector="railways",
        is_fno=False,
    )

    size_defensive = calculate_hierarchical_position_size(
        symbol="DABUR",
        entry_price=entry,
        stop_loss=sl,
        capital=capital,
        max_capital_pct=50.0,
        sector="fmcg",
        is_fno=False,
    )

    assert size_high_beta["shares"] < size_defensive["shares"]
    assert size_high_beta["capital_allocated"] < size_defensive["capital_allocated"]


def test_hierarchical_position_sizing_circuit_headroom_haircut():
    """When upper circuit is closer than 1.5R, position size is automatically halved for safety."""
    entry = 100.0
    sl = 96.0  # 4% risk -> requires 6% circuit headroom
    capital = 100000.0

    # Normal headroom (10% away)
    size_normal = calculate_hierarchical_position_size(
        symbol="ABC",
        entry_price=entry,
        stop_loss=sl,
        capital=capital,
        max_capital_pct=50.0,
        circuit_distance_pct=10.0,
    )

    # Tight headroom (only 2.0% away)
    size_tight = calculate_hierarchical_position_size(
        symbol="ABC",
        entry_price=entry,
        stop_loss=sl,
        capital=capital,
        max_capital_pct=50.0,
        circuit_distance_pct=2.0,
    )

    assert size_tight["shares"] < size_normal["shares"]
    assert "CIRCUIT HEADROOM WARNING" in size_tight["notes"]


def test_hierarchical_position_sizing_sebi_physical_delivery_warning():
    """In expiry week (DTE <= 4), single-stock F&O flags SEBI physical settlement margin notice."""
    size = calculate_hierarchical_position_size(
        symbol="RELIANCE",
        entry_price=1400.0,
        stop_loss=1380.0,
        capital=100000.0,
        dte=2,
    )
    assert "SEBI PHYSICAL SETTLEMENT NOTICE" in size["notes"]


def test_timeframe_adaptive_risk_scaling():
    """
    Verifies that dynamic risk is timeframe-agnostic and adaptively scales
    from Intraday scalps to Swing and Positional holding horizons.
    """
    symbol = "INFY"
    entry = 1500.0
    atr = 25.0  # Daily ATR = 25 pts (1.67%)

    # 1. Intraday Scalp / Session Trade
    scale_intra = clamp_dynamic_risk(
        symbol=symbol,
        entry_price=entry,
        raw_stop_loss=1485.0,
        direction="BULLISH",
        atr=atr,
        timeframe="INTRADAY",
    )
    assert scale_intra.timeframe == "INTRADAY"
    # Intraday risk should be tightly bounded (0.35x - 1.5x ATR = 8.75 to 37.5 pts)
    assert 8.75 <= scale_intra.risk_points <= 37.5
    assert scale_intra.risk_pct <= 3.5

    # 2. Swing Short (2-5 Days overnight holding)
    scale_swing = clamp_dynamic_risk(
        symbol=symbol,
        entry_price=entry,
        raw_stop_loss=1460.0,
        direction="BULLISH",
        atr=atr,
        timeframe="SWING_SHORT",
    )
    assert scale_swing.timeframe == "SWING_SHORT"
    # Swing risk must tolerate overnight gap risk (0.8x - 2.2x ATR = 20 to 55 pts)
    assert 20.0 <= scale_swing.risk_points <= 55.0
    assert scale_swing.target_1 > scale_intra.target_1

    # 3. Positional (1-6 Months structural accumulation)
    scale_pos = clamp_dynamic_risk(
        symbol=symbol,
        entry_price=entry,
        raw_stop_loss=1410.0,
        direction="BULLISH",
        atr=atr,
        timeframe="POSITIONAL",
    )
    assert scale_pos.timeframe == "POSITIONAL"
    # Positional risk accommodates major weekly swings (1.8x - 5.0x ATR = 45 to 125 pts)
    assert scale_pos.risk_points >= 45.0
    assert scale_pos.runner_target > scale_swing.runner_target
