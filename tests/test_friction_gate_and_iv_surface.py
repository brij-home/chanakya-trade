"""
tests/test_friction_gate_and_iv_surface.py
──────────────────────────────────────────
Verification of Phase 3 Mathematical & Microstructure Edge:
1. Statutory roundtrip transaction cost calculation (0.15% options STT, 0.05% futures STT post-April 2026).
2. Friction-aware net expectancy (deducting brokerage, statutory taxes, and half-spread slippage).
3. Constant-tenor 30-day implied volatility variance interpolation.
4. 25-delta Risk Reversal Skew computation.
5. Authentic empirical IV Rank & IV Percentile calculation without synthetic defaults.
6. Fail-closed IVSurfaceSnapshot availability contract.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from engine.charges import (
    calculate_roundtrip_charges,
    calculate_net_expectancy,
    calculate_transaction_charges,
)
from engine.iv_surface import (
    interpolate_constant_30d_variance,
    calculate_25delta_skew,
    compute_iv_rank_and_percentile,
    build_iv_surface_snapshot,
)


def test_stt_statutory_rates_effective_dates():
    """Verify 0.15% STT on options sale and 0.05% on futures sale post-April 1, 2026."""
    post_date = date(2026, 5, 1)
    pre_date = date(2026, 3, 1)

    # Options SELL leg: 100 qty @ 200 premium = 20,000 turnover
    post_opt = calculate_transaction_charges(
        200.0, 100, segment="OPTIONS", side="SELL", trade_date=post_date
    )
    pre_opt = calculate_transaction_charges(
        200.0, 100, segment="OPTIONS", side="SELL", trade_date=pre_date
    )

    # 20,000 * 0.15% = 30.0 vs 20,000 * 0.10% = 20.0
    assert post_opt.stt == Decimal("30.00")
    assert pre_opt.stt == Decimal("20.00")

    # Futures SELL leg: 50 qty @ 2000 price = 100,000 turnover
    post_fut = calculate_transaction_charges(
        2000.0, 50, segment="FUTURES", side="SELL", trade_date=post_date
    )
    pre_fut = calculate_transaction_charges(
        2000.0, 50, segment="FUTURES", side="SELL", trade_date=pre_date
    )

    # 100,000 * 0.05% = 50.0 vs 100,000 * 0.02% = 20.0
    assert post_fut.stt == Decimal("50.00")
    assert pre_fut.stt == Decimal("20.00")


def test_roundtrip_charges_computation():
    """Verify calculate_roundtrip_charges sums both legs accurately."""
    entry_chg, exit_chg, total = calculate_roundtrip_charges(
        entry_price=100.0,
        exit_price=150.0,
        quantity=50,
        segment="OPTIONS",
        entry_side="BUY",
        trade_date=date(2026, 6, 1),
    )
    assert total == entry_chg + exit_chg
    assert total > Decimal("0.00")


def test_net_expectancy_friction_deduction():
    """Verify net reward, net risk, and friction drag percentage."""
    # Buy 1 lot NIFTY option at 100, Target 160 (+60 pts), Stop 70 (-30 pts), Qty = 25
    res = calculate_net_expectancy(
        entry_price=100.0,
        target_price=160.0,
        stop_price=70.0,
        quantity=25,
        segment="OPTIONS",
        entry_side="BUY",
        trade_date=date(2026, 6, 1),
    )

    # Gross reward = 60 * 25 = 1500, Gross risk = 30 * 25 = 750 (Gross R:R = 2.0)
    assert res["gross_reward"] == 1500.0
    assert res["gross_risk"] == 750.0
    assert res["gross_rr"] == 2.0

    # Net reward is strictly less than gross reward due to STT, brokerage & spread
    assert res["net_reward"] < 1500.0
    assert res["net_risk"] > 750.0
    assert res["net_rr"] < 2.0
    assert res["friction_drag_pct"] > 0.0
    assert res["is_positive_expectancy"] is True


def test_sub_breakeven_friction_fails_positive_expectancy():
    """A setup with tiny gross profit gets wiped out by statutory friction."""
    # Buy option at 100, Target 101 (+1 pt), Stop 90 (-10 pts)
    res = calculate_net_expectancy(
        entry_price=100.0,
        target_price=101.0,
        stop_price=90.0,
        quantity=25,
        segment="OPTIONS",
        entry_side="BUY",
        trade_date=date(2026, 6, 1),
    )
    # 25 gross profit is completely eaten by roundtrip friction
    assert res["net_reward"] < 0 or res["net_rr"] < 1.0
    assert res["is_positive_expectancy"] is False


def test_constant_30d_variance_interpolation():
    """Verify constant 30-day DTE variance weighting."""
    # Near DTE=10 (IV=20%), Next DTE=40 (IV=25%)
    iv_30 = interpolate_constant_30d_variance(sigma_1=0.20, dte_1=10, sigma_2=0.25, dte_2=40)
    assert 0.20 < iv_30 < 0.25

    # Exact 30 days
    assert interpolate_constant_30d_variance(0.22, 30, 0.25, 45) == 0.22


def test_25delta_skew_calculation():
    """Verify Put vs Call skew normalized by ATM IV."""
    # 25D Put IV = 22%, 25D Call IV = 18%, ATM IV = 20%
    skew = calculate_25delta_skew(iv_25d_put=0.22, iv_25d_call=0.18, atm_iv=0.20)
    assert skew == 0.2000

    # Zero/negative inputs fail closed to None
    assert calculate_25delta_skew(0.0, 0.18, 0.20) is None


def test_iv_rank_and_percentile_sample_threshold():
    """Less than 20 samples returns None (Safety Contract #26: no fabricated 50.0)."""
    samples_few = [15.0, 16.0, 17.0, 18.0]
    ivr, ivp, count = compute_iv_rank_and_percentile(17.5, samples_few, min_samples=20)
    assert ivr is None
    assert ivp is None
    assert count == 4

    # 25 valid samples: min=10.0, max=30.0, current=20.0 -> IVR = 50.0
    samples_sufficient = list(range(10, 31)) + [15.0, 20.0, 25.0, 18.0]
    ivr2, ivp2, count2 = compute_iv_rank_and_percentile(20.0, samples_sufficient, min_samples=20)
    assert ivr2 is not None
    assert ivp2 is not None
    assert count2 >= 20
    assert 45.0 <= ivr2 <= 55.0


def test_iv_surface_snapshot_fail_closed():
    """Missing or non-positive ATM IV fails closed with UNAVAILABLE status."""
    snap_missing = build_iv_surface_snapshot(symbol="NIFTY", near_atm_iv=None, near_dte=10)
    assert snap_missing.status == "UNAVAILABLE"
    assert snap_missing.atm_iv_30d is None

    # Valid near and next tenors
    snap_valid = build_iv_surface_snapshot(
        symbol="NIFTY",
        near_atm_iv=0.18,
        near_dte=12,
        next_atm_iv=0.22,
        next_dte=42,
        iv_25d_put=0.21,
        iv_25d_call=0.17,
    )
    assert snap_valid.status == "AVAILABLE"
    assert snap_valid.atm_iv_30d is not None
    assert snap_valid.skew_25d is not None
    assert snap_valid.skew_25d > 0.0  # Put demand


def test_alert_scrutiny_friction_veto_rejects_sub_breakeven_trade():
    """Verify AlertScrutinyAuditor vetoes an alert where statutory friction erodes net reward."""
    from engine.alert_scrutiny import AlertScrutinyAuditor
    from engine.auto_alert_engine import AutoAlert

    auditor = AlertScrutinyAuditor(min_rr_ratio=1.3)
    # Scalp option alert where gross target is 10.15 vs entry 10.0 (gross +0.15) and SL is 9.90 (risk 0.10)
    # Gross R:R is 1.5, but 0.15% STT + fees + slippage erodes net reward to negative or net R:R < 0.8
    alert = AutoAlert(
        alert_id="test-friction-veto",
        alert_type="OPTIONS_MOMENTUM",
        stage="ACTIONABLE",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY Sub-Breakeven Scalp",
        summary="Gross profit is wiped out by statutory friction",
        ltp=10.0,
        trigger_level=10.0,
        stop_loss=9.90,
        target_level=10.15,
        option_type="CE",
        strike=24000.0,
        is_live=True,
        environment="LIVE",
        metrics={"volume": 100000, "oi": 500000, "spread_bps": 15.0},
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed is False
    assert (
        "Statutory Friction Veto" in reason
        or "Option Noise Trap" in reason
        or flags.get("friction_valid") is False
    )


def test_alert_scrutiny_friction_gate_passes_viable_trade():
    """Verify AlertScrutinyAuditor approves viable setups with authentic friction calculation."""
    from engine.alert_scrutiny import AlertScrutinyAuditor
    from engine.auto_alert_engine import AutoAlert

    auditor = AlertScrutinyAuditor(min_rr_ratio=1.3)
    alert = AutoAlert(
        alert_id="test-friction-pass",
        alert_type="PRECURSOR_RADAR",
        stage="ACTIONABLE",
        symbol="NSE:RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="Reliance Breakout",
        summary="High conviction setup",
        ltp=2800.0,
        trigger_level=2800.0,
        stop_loss=2750.0,
        target_level=2950.0,
        is_live=True,
        environment="LIVE",
        metrics={"atr": 40.0, "atr_5m": 8.0, "rvol": 2.2},
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed is True, f"Failed: {reason}"
    assert flags["friction_valid"] is True
    assert "friction_net_expectancy" in flags
    net_exp = flags["friction_net_expectancy"]
    assert net_exp["is_positive_expectancy"] is True
    assert net_exp["net_reward"] > 0


def test_compute_options_iv_skew_and_surface_snapshot():
    """Verify compute_options_iv_skew attaches 25-delta skew and get_iv_surface_snapshot operates cleanly."""
    from brokers.base import OptionsContract
    from market.options import compute_options_iv_skew, get_iv_surface_snapshot

    # Build dummy contracts
    c_atm = OptionsContract(
        symbol="NIFTY24000CE",
        underlying="NIFTY",
        expiry="2026-11-26",
        strike=24000.0,
        option_type="CE",
        last_price=150.0,
        oi=10000,
        oi_change=500,
        volume=20000,
        iv=16.0,
        delta=0.50,
    )
    p_atm = OptionsContract(
        symbol="NIFTY24000PE",
        underlying="NIFTY",
        expiry="2026-11-26",
        strike=24000.0,
        option_type="PE",
        last_price=140.0,
        oi=10000,
        oi_change=500,
        volume=20000,
        iv=17.0,
        delta=-0.50,
    )
    c_otm = OptionsContract(
        symbol="NIFTY24100CE",
        underlying="NIFTY",
        expiry="2026-11-26",
        strike=24100.0,
        option_type="CE",
        last_price=80.0,
        oi=10000,
        oi_change=500,
        volume=20000,
        iv=15.5,
        delta=0.25,
    )
    p_otm = OptionsContract(
        symbol="NIFTY23900PE",
        underlying="NIFTY",
        expiry="2026-11-26",
        strike=23900.0,
        option_type="PE",
        last_price=75.0,
        oi=10000,
        oi_change=500,
        volume=20000,
        iv=18.5,
        delta=-0.25,
    )
    chain = [c_atm, p_atm, c_otm, p_otm]

    skew_res = compute_options_iv_skew(chain, spot=24000.0, underlying="NIFTY")
    assert skew_res["status"] == "ACTIVE"
    assert skew_res["atm_strike"] == 24000.0
    assert "skew_25d" in skew_res
    assert skew_res["skew_25d"] is not None
    # 25D Put IV = 18.5, 25D Call IV = 15.5, ATM IV = 16.5 -> Skew = (18.5 - 15.5) / 16.5 ~ 0.1818
    assert skew_res["skew_25d"] > 0.0

    # Test get_iv_surface_snapshot fail-closed behavior on unknown underlying
    snap = get_iv_surface_snapshot("UNKNOWN_SYMBOL", spot=100.0)
    assert snap.status == "UNAVAILABLE"
    assert snap.atm_iv_30d is None
