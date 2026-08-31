"""
tests/test_retail_protection.py
───────────────────────────────
Unit test suite verifying retail protection guardrails:
1. Tilt & Revenge Trading Lockout (consecutive losses)
2. Post-budget Capital Gains & F&O Tax Calculations
3. Defined-Risk Option Spread Generator
4. Portfolio Health & Asset Allocation Auditor
"""

import pytest
from engine.risk_limits import RiskLimits, RiskLimitError
from engine.charges import (
    calculate_capital_gains_tax,
    calculate_fo_turnover,
    suggest_tax_loss_harvesting,
)
from engine.defined_risk_spreads import build_defined_risk_spread
from engine.portfolio import audit_portfolio_health, PortfolioSummary, HoldingRow, RiskMeter
from brokers.base import Funds


def test_consecutive_losses_tilt_lockout(tmp_path, monkeypatch):
    """Verify that 3 consecutive losing trades trigger tilt lockout."""
    db_file = tmp_path / "test_risk.db"
    monkeypatch.setenv("RISK_DB_PATH", str(db_file))
    monkeypatch.setenv("MAX_CONSECUTIVE_LOSSES", "3")
    monkeypatch.setenv("MAX_DAILY_LOSS", "50000")

    rl = RiskLimits()

    # Record 2 loss trades
    rl.record_trade("TCS", "BUY", 10, 3500.0, pnl=-500.0)
    rl.record_trade("INFY", "BUY", 10, 1500.0, pnl=-800.0)

    # Should still pass
    rl.check("RELIANCE", "BUY", 5, 2800.0)
    status = rl.get_status()
    assert status["consecutive_losses_today"] == 2
    assert status["tilt_lockout_active"] is False

    # Record 3rd consecutive loss
    rl.record_trade("HDFCBANK", "BUY", 10, 1600.0, pnl=-300.0)

    # 4th trade should be blocked by tilt lockout without override
    with pytest.raises(RiskLimitError) as exc_info:
        rl.check("RELIANCE", "BUY", 5, 2800.0)
    assert "tilt & revenge trading" in str(exc_info.value).lower()

    # Preflight should return structured advisory with requires_double_confirmation=True
    preflight = rl.evaluate_preflight("RELIANCE", "BUY", 5, 2800.0)
    assert preflight.allowed is False
    assert preflight.requires_double_confirmation is True
    assert "TILT_LOCKOUT" in preflight.flags
    assert len(preflight.disclaimers) > 0
    assert len(preflight.coaching_recommendations) > 0

    # With allow_override=True (double confirmed with awareness), order passes
    res = rl.check("RELIANCE", "BUY", 5, 2800.0, allow_override=True)
    assert res.allowed is True
    assert res.overridden is True

    # Verify status reflects lockout
    status = rl.get_status()
    assert status["consecutive_losses_today"] == 3
    assert status["tilt_lockout_active"] is True


def test_capital_gains_tax_stcg_and_ltcg():
    """Verify Post-Budget 2024 STCG (20%) and LTCG (12.5% above ₹1.25L)."""
    # STCG (<365 days)
    stcg = calculate_capital_gains_tax(
        gross_pnl=50000.0, holding_period_days=120, segment="EQUITY_DELIVERY"
    )
    assert stcg.tax_type == "STCG"
    assert stcg.tax_rate_pct == 20.0
    assert stcg.estimated_tax == 10000.0
    assert stcg.net_post_tax_pnl == 40000.0

    # LTCG (>=365 days, below exemption limit)
    ltcg_low = calculate_capital_gains_tax(
        gross_pnl=100000.0, holding_period_days=400, segment="EQUITY_DELIVERY"
    )
    assert ltcg_low.tax_type == "LTCG"
    assert ltcg_low.estimated_tax == 0.0
    assert ltcg_low.net_post_tax_pnl == 100000.0

    # LTCG (above ₹1.25L exemption: ₹2.25L gain -> ₹1.00L taxable @ 12.5% = ₹12,500)
    ltcg_high = calculate_capital_gains_tax(
        gross_pnl=225000.0, holding_period_days=450, segment="EQUITY_DELIVERY"
    )
    assert ltcg_high.tax_type == "LTCG"
    assert ltcg_high.tax_rate_pct == 12.5
    assert ltcg_high.estimated_tax == 12500.0
    assert ltcg_high.net_post_tax_pnl == 212500.0


def test_fo_turnover_calculation():
    """Verify ICAI Section 43(5) & 44AB turnover."""
    trades = [
        {"pnl": 15000.0, "segment": "FUTURES", "side": "SELL", "price": 24000.0, "quantity": 50},
        {"pnl": -8000.0, "segment": "OPTIONS", "side": "SELL", "price": 100.0, "quantity": 100},
    ]
    res = calculate_fo_turnover(trades)
    # Absolute sum of P&L: 15000 + 8000 = 23000
    # Option Sell Premium: 100 * 100 = 10000
    # Total = 33000
    assert res["total_abs_pnl"] == 23000.0
    assert res["options_premium_turnover"] == 10000.0
    assert res["icai_tax_turnover"] == 33000.0
    assert res["tax_audit_required"] is False


def test_tax_loss_harvesting_suggestions():
    """Verify harvesting suggestions prioritize largest loss positions."""
    holdings = [
        {"symbol": "INFY", "qty": 50, "ltp": 1400.0, "pnl": -15000.0, "days_held": 120},
        {"symbol": "TCS", "qty": 20, "ltp": 3500.0, "pnl": 20000.0, "days_held": 100},
        {"symbol": "WIPRO", "qty": 100, "ltp": 450.0, "pnl": -5000.0, "days_held": 200},
    ]
    recs = suggest_tax_loss_harvesting(holdings)
    assert len(recs) == 2
    assert recs[0]["symbol"] == "INFY"
    assert recs[0]["unrealized_loss"] == 15000.0
    assert recs[0]["potential_stcg_tax_saved"] == 3000.0
    assert recs[1]["symbol"] == "WIPRO"


def test_defined_risk_spread_builder():
    """Verify mathematical properties of Bull Call Spread and Iron Condor."""
    # Bull Call Spread
    bcs = build_defined_risk_spread("NIFTY", spot_price=24000.0, strategy="BULL_CALL_SPREAD", dte=7)
    assert bcs.strategy_name == "BULL_CALL_SPREAD"
    assert bcs.max_loss > 0
    assert bcs.max_profit > 0
    assert bcs.sentiment == "BULLISH"
    assert len(bcs.legs) == 2
    assert bcs.legs[0].side == "BUY"
    assert bcs.legs[1].side == "SELL"

    # Iron Condor (4 legs)
    ic = build_defined_risk_spread("NIFTY", spot_price=24000.0, strategy="IRON_CONDOR", dte=7)
    assert ic.strategy_name == "IRON_CONDOR"
    assert ic.sentiment == "RANGE_BOUND"
    assert len(ic.legs) == 4
    assert ic.max_profit > 0
    assert ic.max_loss > 0


def test_portfolio_health_audit():
    """Verify concentration scoring and wealth pyramid audit."""
    holdings = [
        HoldingRow(
            symbol="RELIANCE",
            qty=100,
            avg_price=2500.0,
            ltp=2800.0,
            value=280000.0,
            pnl=30000.0,
            pnl_pct=12.0,
            product="CNC",
        ),
        HoldingRow(
            symbol="TCS",
            qty=10,
            avg_price=3400.0,
            ltp=3500.0,
            value=35000.0,
            pnl=1000.0,
            pnl_pct=2.9,
            product="CNC",
        ),
    ]
    funds = Funds(available_cash=50000.0, used_margin=0.0, total_balance=365000.0)
    risk = RiskMeter(
        total_capital=365000.0,
        deployed_cash=315000.0,
        used_margin=0.0,
        free_cash=50000.0,
        deployment_pct=86.3,
        unrealised_pnl=31000.0,
        max_loss_estimate=315000.0,
        risk_rating="MEDIUM",
    )
    summary = PortfolioSummary(
        holdings=holdings,
        positions=[],
        funds=funds,
        greeks=None,  # type: ignore
        risk=risk,
        total_value=365000.0,
        total_pnl=31000.0,
        day_pnl=0.0,
    )

    audit = audit_portfolio_health(summary)
    assert audit.total_holdings_count == 2
    assert audit.top_holding["symbol"] == "RELIANCE"
    # Reliance is 280000 / 315000 = ~88.8% -> Critical Concentration
    assert audit.concentration_risk == "CRITICAL"
    assert any("RELIANCE" in r for r in audit.recommendations)


def test_all_defined_risk_spread_strategies():
    """Verify all defined risk strategies build properly."""
    from engine.defined_risk_spreads import recommend_defined_risk_spreads

    spreads = recommend_defined_risk_spreads("NIFTY", spot_price=24500.0)
    assert len(spreads) == 5
    strat_names = {s.strategy_name for s in spreads}
    assert "BULL_CALL_SPREAD" in strat_names
    assert "BEAR_PUT_SPREAD" in strat_names
    assert "BULL_PUT_SPREAD" in strat_names
    assert "BEAR_CALL_SPREAD" in strat_names
    assert "IRON_CONDOR" in strat_names


def test_statutory_charges_calculation():
    """Verify statutory charges computation across segments."""
    from engine.charges import calculate_transaction_charges

    # Equity delivery buy
    eq_buy = calculate_transaction_charges(
        price=1000.0, quantity=100, segment="EQUITY_DELIVERY", side="BUY"
    )
    assert eq_buy.notional_turnover == 100000.0
    assert eq_buy.stt > 0
    assert eq_buy.stamp_duty > 0

    # Options sell
    opt_sell = calculate_transaction_charges(
        price=150.0, quantity=75, segment="OPTIONS", side="SELL"
    )
    assert opt_sell.stt > 0
    assert opt_sell.total_charges > 0


def test_tool_registry_and_openclaw_skills():
    """Verify all retail tools are in default_tool_registry and openclaw manifest."""
    from agent.tools import build_registry
    from web.openclaw import MANIFEST

    reg = build_registry()
    assert "audit_portfolio_health" in reg._tools
    assert "calculate_capital_gains_tax" in reg._tools
    assert "suggest_tax_loss_harvesting" in reg._tools
    assert "build_defined_risk_spread" in reg._tools

    # OpenClaw manifest check
    skill_names = {s["name"] for s in MANIFEST["skills"]}
    assert "portfolio_health" in skill_names
    assert "tax_estimate" in skill_names
    assert "tax_harvesting" in skill_names
    assert "defined_risk_spreads" in skill_names
