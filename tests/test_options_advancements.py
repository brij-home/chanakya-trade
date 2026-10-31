# -*- coding: utf-8 -*-
"""
tests/test_options_advancements.py
───────────────────────────────────
Institutional test suite for options execution advancements:
1. India VIX-Calibrated Strategy Matrix (classify_vix_strategy_regime)
2. Single-Stock Option Bid-Ask Spread Slippage Gate (audit_stock_option_liquidity_spread)
3. 0DTE Afternoon Theta Decay Acceleration Guard (veto_naked_otm)
4. Autonomous Breakeven Locking Volatility Wick Buffer (apply_autonomous_breakeven_lock)
5. Defined-Risk Hedge Plan Volatility Integration (build_defined_risk_hedge_plan)
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from engine.options_hedging import (
    audit_stock_option_liquidity_spread,
    build_defined_risk_hedge_plan,
    classify_vix_strategy_regime,
    get_0dte_intraday_phase,
)
from engine.trade_lifecycle import apply_autonomous_breakeven_lock

IST = ZoneInfo("Asia/Kolkata")


def test_classify_vix_strategy_regimes():
    """Validates the 4-tier India VIX institutional strategy matrix."""
    # 1. ULTRA_LOW_IV (< 12.0)
    low = classify_vix_strategy_regime(11.2)
    assert low.regime == "ULTRA_LOW_IV"
    assert low.mandate_spread is False
    assert low.preferred_moneyness == "DEEP_ITM"
    assert low.delta_target_long == 0.68
    assert "synthetic futures" in low.description.lower()

    # 2. NORMAL_IV (12.0 to 17.5)
    normal = classify_vix_strategy_regime(14.5)
    assert normal.regime == "NORMAL_IV"
    assert normal.mandate_spread is False
    assert normal.preferred_moneyness == "ATM_OR_1ITM"
    assert normal.delta_target_long == 0.55

    # 3. INFLATED_IV (17.5 to 25.0)
    inflated = classify_vix_strategy_regime(19.5)
    assert inflated.regime == "INFLATED_IV"
    assert inflated.mandate_spread is True
    assert inflated.preferred_moneyness == "SPREAD_MANDATORY"
    assert inflated.delta_target_long == 0.50
    assert "iv crush hazard" in inflated.description.lower()

    # 4. TAIL_RISK (> 25.0)
    tail = classify_vix_strategy_regime(28.0)
    assert tail.regime == "TAIL_RISK"
    assert tail.mandate_spread is True
    assert tail.preferred_moneyness == "SPREAD_MANDATORY"
    assert tail.delta_target_long == 0.45
    assert "haircut" in tail.description.lower()


def test_audit_stock_option_liquidity_spread():
    """Validates single-stock order book bid-ask spread audit & midpoint enforcement."""
    sym = "RELIANCE2600CE"

    # 1. Clean Liquid Spread (<= 4.5%): PASS
    # Midpoint = 101.50, Spread = 3.00 (2.96%)
    res_pass = audit_stock_option_liquidity_spread(sym, bid=100.0, ask=103.0)
    assert res_pass["status"] == "PASS"
    assert res_pass["is_acceptable"] is True
    assert res_pass["recommended_order_type"] == "LIMIT"
    assert res_pass["midpoint"] == 101.50
    assert res_pass["warning"] is None

    # 2. Moderate Spread Slippage Hazard (4.5% to 10.0%): CAUTION_MIDPOINT
    # Midpoint = 103.50, Spread = 7.00 (6.76%)
    res_caution = audit_stock_option_liquidity_spread(sym, bid=100.0, ask=107.0)
    assert res_caution["status"] == "CAUTION_MIDPOINT"
    assert res_caution["is_acceptable"] is True
    assert res_caution["recommended_order_type"] == "LIMIT_MIDPOINT"
    assert res_caution["midpoint"] == 103.50
    assert "Midpoint" in res_caution["warning"]

    # 3. Illiquid Contract (> 10.0%): REJECT
    # Midpoint = 107.50, Spread = 15.00 (13.95%)
    res_reject = audit_stock_option_liquidity_spread(sym, bid=100.0, ask=115.0)
    assert res_reject["status"] == "REJECT"
    assert res_reject["is_acceptable"] is False
    assert res_reject["recommended_order_type"] == "LIMIT_MIDPOINT"
    assert "rejected" in res_reject["warning"].lower()

    # 4. Missing depth quotes: UNAVAILABLE
    res_unavail = audit_stock_option_liquidity_spread(sym, bid=0.0, ask=0.0)
    assert res_unavail["status"] == "UNAVAILABLE"
    assert res_unavail["is_acceptable"] is False


def test_0dte_intraday_phase_afternoon_otm_veto():
    """Validates 0DTE afternoon phase vetoes naked OTM strikes post-13:00 IST."""
    # Thursday 13:30 IST on NIFTY (0DTE)
    thursday_afternoon = datetime(2026, 10, 29, 13, 30, tzinfo=IST)
    phase_afternoon = get_0dte_intraday_phase("NIFTY", now_dt=thursday_afternoon)
    assert phase_afternoon["is_0dte"] is True
    assert phase_afternoon["phase"] == "AFTERNOON_GAMMA_SQUEEZE"
    assert phase_afternoon["veto_naked_otm"] is True
    assert phase_afternoon["allowed_moneyness"] == "ATM_OR_ITM_ONLY"

    # Thursday 10:15 IST on NIFTY (0DTE Morning Drive)
    thursday_morning = datetime(2026, 10, 29, 10, 15, tzinfo=IST)
    phase_morning = get_0dte_intraday_phase("NIFTY", now_dt=thursday_morning)
    assert phase_morning["is_0dte"] is True
    assert phase_morning["veto_naked_otm"] is False

    # Tuesday 14:00 IST on NIFTY (Non-0DTE)
    tuesday_afternoon = datetime(2026, 10, 27, 14, 0, tzinfo=IST)
    phase_non_0dte = get_0dte_intraday_phase("NIFTY", now_dt=tuesday_afternoon)
    assert phase_non_0dte["is_0dte"] is False
    assert phase_non_0dte["veto_naked_otm"] is False


def test_options_autonomous_breakeven_lock_wick_buffer():
    """Validates that option positions receive a 2.5% volatility wick buffer at Target 1."""
    # 1. Equity position: SBIN bought at 800.00, T1 achieved at 820.00
    # Stop ratcheted to entry + 0.2% cost buffer = 801.60
    equity_res = apply_autonomous_breakeven_lock(
        symbol="SBIN",
        current_price=820.5,
        entry_price=800.0,
        initial_stop_loss=790.0,
        target_1=820.0,
        position_type="LONG",
        cost_buffer_pct=0.002,
        is_option=False,
    )
    assert equity_res["locked"] is True
    assert equity_res["breakeven_stop"] == 801.60

    # 2. Option position: NIFTY25000CE bought at 100.00, T1 achieved at 130.00 (+30%)
    # Stop ratcheted to entry - 2.5% volatility wick buffer = 97.50
    # Defends the remaining 50% runner against false stop-runs while preserving +13.75% net trade profit
    option_res = apply_autonomous_breakeven_lock(
        symbol="NIFTY25000CE",
        current_price=130.5,
        entry_price=100.0,
        initial_stop_loss=75.0,
        target_1=130.0,
        position_type="LONG",
        option_wick_buffer_pct=0.025,
    )
    assert option_res["locked"] is True
    assert option_res["milestone"] == "T1_ACHIEVED"
    assert option_res["breakeven_stop"] == 97.50


def test_build_defined_risk_hedge_plan_vix_regime_integration():
    """Validates that build_defined_risk_hedge_plan mandates spreads under high IV."""
    # 1. Normal IV (14.0): Spreads are optional, debit spread created
    normal_plan = build_defined_risk_hedge_plan(
        symbol="NIFTY",
        direction="BULLISH",
        spot=25000.0,
        strike=25000.0,
        opt_type="CE",
        opt_ltp=120.0,
        vix=14.0,
    )
    assert normal_plan is not None
    assert normal_plan["vix_regime"] == "NORMAL_IV"
    assert normal_plan["preferred_vehicle"] in ("NAKED_OPTION_OR_SPREAD", "HEDGED_SPREAD")
    assert normal_plan["strategy"] == "BULL_CALL_SPREAD"

    # 2. Inflated IV (20.0): Defined-risk spreads strictly mandated
    high_iv_plan = build_defined_risk_hedge_plan(
        symbol="NIFTY",
        direction="BULLISH",
        spot=25000.0,
        strike=25000.0,
        opt_type="CE",
        opt_ltp=180.0,
        vix=20.0,
    )
    assert high_iv_plan is not None
    assert high_iv_plan["vix_regime"] == "INFLATED_IV"
    assert high_iv_plan["preferred_vehicle"] == "SPREAD_ONLY"
    assert "iv crush" in high_iv_plan["execution_guidance"].lower()
    assert high_iv_plan["vix_strategy_regime"]["mandate_spread"] is True
