"""
tests/test_vix_regime_option_resolver.py
────────────────────────────────────────
Deterministic unit tests for VIX-regime aware option contract resolution & defined-risk spreads.
Verifies:
  1. Elevated VIX (>= 19.0) automatically mandates defined-risk vertical spreads (Bull Call / Bear Put).
  2. Normal VIX (13.5–19.0) selects disciplined ATM/near-ITM directional options.
  3. Compressed VIX (<= 13.5) classifies as COMPRESSED_VOL with gamma expansion potential.
  4. Spread details contain accurate 2-leg structure, net cashflow, max profit, and max loss.
  5. Works seamlessly across Index F&O (NIFTY, BANKNIFTY, MIDCPNIFTY) and Stock F&O.
"""

from __future__ import annotations

from engine.option_resolver import resolve_option_contract


def test_normal_vix_resolves_naked_directional():
    """Verify normal VIX (14.2) resolves standard directional option."""
    plan = resolve_option_contract(
        symbol="NIFTY",
        spot=25000.0,
        direction="BULLISH",
        underlying_sl=24900.0,
        underlying_target=25200.0,
        india_vix=14.2,
    )
    assert plan is not None
    assert plan.option_type == "CE"
    assert plan.strike == 25000.0
    assert plan.strategy_type == "NAKED_DIRECTIONAL"
    assert plan.vix_regime == "NORMAL_MOMENTUM"
    assert plan.execution_style_mandate == "STANDARD"
    assert plan.hedge_contract_symbol is None
    assert plan.spread_details is None


def test_compressed_vix_classification():
    """Verify low VIX (12.0) classifies as COMPRESSED_VOL."""
    plan = resolve_option_contract(
        symbol="BANKNIFTY",
        spot=55000.0,
        direction="BEARISH",
        underlying_sl=55300.0,
        underlying_target=54400.0,
        india_vix=12.0,
    )
    assert plan is not None
    assert plan.option_type == "PE"
    assert plan.strike == 55000.0
    assert plan.strategy_type == "NAKED_DIRECTIONAL"
    assert plan.vix_regime == "COMPRESSED_VOL"
    assert plan.execution_style_mandate == "STANDARD"


def test_elevated_vix_mandates_bull_call_spread():
    """Verify high VIX (21.5 >= 19.0) mandates Bull Call Spread with hedge leg."""
    plan = resolve_option_contract(
        symbol="NIFTY",
        spot=25000.0,
        direction="BULLISH",
        underlying_sl=24900.0,
        underlying_target=25250.0,
        india_vix=21.5,
    )
    assert plan is not None
    assert plan.strategy_type == "BULL_CALL_SPREAD"
    assert plan.vix_regime == "ELEVATED_VOL_SPREAD"
    assert plan.execution_style_mandate == "HEDGED_SPREAD_MANDATORY"
    assert plan.option_type == "CE"
    assert plan.strike == 25000.0

    # Hedge leg should be OTM Call (2 steps = +100 pts for Nifty)
    assert plan.hedge_strike == 25100.0
    assert plan.hedge_contract_symbol is not None
    assert "25100 CE" in plan.hedge_contract_symbol or "25100" in plan.hedge_contract_symbol
    assert plan.net_debit is not None and plan.net_debit > 0
    assert plan.max_loss is not None and plan.max_loss > 0
    assert plan.max_profit is not None and plan.max_profit > 0

    # Verify spread details dict for UI / ActionablePlan
    d = plan.as_dict()
    assert d["execution_style_mandate"] == "HEDGED_SPREAD_MANDATORY"
    assert "hedged_spread" in d
    spread_info = d["hedged_spread"]
    assert spread_info["strategy_name"] == "BULL_CALL_SPREAD"
    assert spread_info["sentiment"] == "BULLISH"
    assert len(spread_info["legs"]) == 2
    assert spread_info["legs"][0]["side"] == "BUY"
    assert spread_info["legs"][1]["side"] == "SELL"


def test_elevated_vix_mandates_bear_put_spread_banknifty():
    """Verify high VIX (20.0) mandates Bear Put Spread on Bank Nifty."""
    plan = resolve_option_contract(
        symbol="BANKNIFTY",
        spot=54000.0,
        direction="BEARISH",
        underlying_sl=54350.0,
        underlying_target=53400.0,
        india_vix=20.0,
    )
    assert plan is not None
    assert plan.strategy_type == "BEAR_PUT_SPREAD"
    assert plan.vix_regime == "ELEVATED_VOL_SPREAD"
    assert plan.execution_style_mandate == "HEDGED_SPREAD_MANDATORY"
    assert plan.strike > 0
    # Hedge strike for Bank Nifty = 3 steps (300 pts) OTM below resolved strike
    assert plan.hedge_strike == plan.strike - 300.0
    assert plan.net_debit > 0
    assert plan.max_loss > 0
    assert plan.max_profit > 0

    spread_info = plan.spread_details
    assert spread_info is not None
    assert spread_info["strategy_name"] == "BEAR_PUT_SPREAD"
    assert spread_info["sentiment"] == "BEARISH"


def test_stock_fno_spread_support():
    """Verify stock option (e.g. RELIANCE) constructs spread in high VIX or prefer_spread."""
    plan = resolve_option_contract(
        symbol="RELIANCE",
        spot=3000.0,
        direction="BULLISH",
        underlying_sl=2950.0,
        underlying_target=3100.0,
        india_vix=22.0,
        prefer_options=True,
    )
    assert plan is not None
    assert plan.strategy_type == "BULL_CALL_SPREAD"
    assert plan.strike == 3000.0
    assert plan.hedge_strike > 3000.0
    assert plan.execution_style_mandate == "HEDGED_SPREAD_MANDATORY"
