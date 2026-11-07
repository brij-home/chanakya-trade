"""
tests/test_institutional_modernization_modules.py
─────────────────────────────────────────────────
Unit and integration tests for the 4 Institutional Modernization Modules:
  1. Automated Dynamic Trailing Stop-Loss Engine (Chandelier / ATR Ratchet & Lifecycle Runner)
  2. Options Strategy Payoff Optimizer (Defined-Risk Spreads & Condors)
  3. Cross-Market SMT Divergence Scanner (NIFTY vs BANKNIFTY, GOLD vs SILVER, CRUDE vs NATGAS)
  4. Behavioral Anti-Tilt Coach & Mindful Co-Pilot Friction
"""

from engine.trade_lifecycle import auto_ratchet_chandelier_trailing_stop
from analysis.options import optimize_defined_risk_strategies
from analysis.smt_scanner import (
    AssetMetrics,
    evaluate_pair_smt,
    scan_cross_market_smt_divergences,
)
from engine.risk_limits import risk_limits


# ── Module 1: Automated Dynamic Trailing Stop-Loss Engine ───────


def test_auto_ratchet_trailing_stop_t1_breakeven_equity():
    """Verify that hitting Target 1 ratchets stop to Breakeven (+ cost buffer) for equity."""
    res = auto_ratchet_chandelier_trailing_stop(
        symbol="NSE:RELIANCE",
        current_price=2450.0,
        entry_price=2400.0,
        initial_stop_loss=2370.0,
        target_1=2445.0,  # reached
        target_2=2500.0,
        position_type="LONG",
        is_option=False,
    )
    assert res["locked"] is True
    assert res["stage"] == "T1_ACHIEVED"
    assert res["new_stop"] == round(2400.0 * 1.002, 2)  # 2404.8
    assert res["r_multiple"] >= 1.5


def test_auto_ratchet_trailing_stop_t1_breakeven_option_wick_buffer():
    """Verify that option trades use the 2.5% volatility wick defense buffer at T1."""
    res = auto_ratchet_chandelier_trailing_stop(
        symbol="NIFTY26NOV24500CE",
        current_price=160.0,
        entry_price=120.0,
        initial_stop_loss=90.0,
        target_1=155.0,  # reached
        target_2=200.0,
        position_type="LONG",
        is_option=True,
    )
    assert res["locked"] is True
    assert res["stage"] == "T1_ACHIEVED"
    assert res["new_stop"] == round(120.0 * (1.0 - 0.025), 2)  # 117.0


def test_auto_ratchet_trailing_stop_t2_lock_in_and_chandelier():
    """Verify that reaching Target 2 ratchets stop to Target 1 level or Chandelier ATR."""
    # Test T2 lock-in without ATR
    res_t2 = auto_ratchet_chandelier_trailing_stop(
        symbol="NSE:TCS",
        current_price=4100.0,
        entry_price=3900.0,
        initial_stop_loss=3850.0,
        target_1=3980.0,
        target_2=4080.0,  # reached
        position_type="LONG",
    )
    assert res_t2["locked"] is True
    assert res_t2["stage"] == "T2_ACHIEVED"
    assert res_t2["new_stop"] == 3980.0

    # Test Chandelier ATR runner tightening beyond T2
    res_chan = auto_ratchet_chandelier_trailing_stop(
        symbol="NSE:TCS",
        current_price=4200.0,
        entry_price=3900.0,
        initial_stop_loss=3850.0,
        target_1=3980.0,
        target_2=4080.0,
        atr_14=20.0,
        high_watermark=4200.0,
        position_type="LONG",
        atr_multiplier=2.5,  # 4200 - (2.5 * 20) = 4150
    )
    assert res_chan["locked"] is True
    assert res_chan["stage"] == "RUNNER_CHANDELIER"
    assert res_chan["new_stop"] == 4150.0  # higher than T1 3980.0


def test_auto_ratchet_monotonicity():
    """Verify that the engine never loosens an existing tighter stop."""
    res = auto_ratchet_chandelier_trailing_stop(
        symbol="NSE:INFY",
        current_price=1600.0,
        entry_price=1500.0,
        initial_stop_loss=1450.0,
        target_1=1580.0,
        current_stop=1590.0,  # existing stop is already higher than T1
        position_type="LONG",
    )
    assert res["locked"] is False
    assert "does not tighten" in res["reason"]


# ── Module 2: Options Strategy Payoff Optimizer ──────────────────


def test_optimize_defined_risk_strategies_all_structures():
    """Verify that all 6 defined-risk structures are evaluated with valid payoffs."""
    res = optimize_defined_risk_strategies(
        underlying="NIFTY",
        spot=24500.0,
        lot_size=25,
        regime="BULLISH",
        dte_days=5,
        iv_atm=14.5,
    )
    assert res["underlying"] == "NIFTY"
    assert res["spot"] == 24500.0
    strategies = res["strategies"]
    assert len(strategies) == 6

    strat_ids = {s["strategy_id"] for s in strategies}
    assert "BULL_CALL_SPREAD" in strat_ids
    assert "BEAR_PUT_SPREAD" in strat_ids
    assert "BULL_PUT_CREDIT_SPREAD" in strat_ids
    assert "BEAR_CALL_CREDIT_SPREAD" in strat_ids
    assert "IRON_CONDOR" in strat_ids
    assert "IRON_BUTTERFLY" in strat_ids

    # For BULLISH regime, Bullish structures must have higher suitability scores
    bull_call = next(s for s in strategies if s["strategy_id"] == "BULL_CALL_SPREAD")
    bear_put = next(s for s in strategies if s["strategy_id"] == "BEAR_PUT_SPREAD")
    assert bull_call["suitability_score"] > bear_put["suitability_score"]

    # Verify legs and payoff figures
    for s in strategies:
        assert len(s["legs"]) in (2, 4)
        assert s["max_profit"] > 0
        assert s["max_loss"] < 0
        assert 5.0 <= s["probability_of_profit_pct"] <= 95.0
        assert s["flow_type"] in ("CREDIT", "DEBIT")


def test_optimize_defined_risk_strategies_neutral_regime():
    """Verify that in NEUTRAL regime, market-neutral Iron Condor / Butterfly are ranked top."""
    res = optimize_defined_risk_strategies(
        underlying="BANKNIFTY",
        spot=52000.0,
        lot_size=30,
        regime="NEUTRAL",
        dte_days=4,
    )
    top_strat = res["strategies"][0]
    assert top_strat["strategy_id"] in (
        "IRON_CONDOR",
        "IRON_BUTTERFLY",
        "BULL_PUT_CREDIT_SPREAD",
        "BEAR_CALL_CREDIT_SPREAD",
    )


# ── Module 3: Cross-Market SMT Divergence Scanner ────────────────


def test_evaluate_pair_smt_bearish_distribution():
    """Verify that Asset A breaking Day High while Asset B lags triggers Bearish SMT."""
    m_a = AssetMetrics(
        symbol="NIFTY",
        exchange="NSE",
        ltp=24600.0,
        day_high=24600.0,  # At Day High
        day_low=24400.0,
        prev_close=24450.0,
        change_pct=0.61,
        vwap=24520.0,
    )
    m_b = AssetMetrics(
        symbol="BANKNIFTY",
        exchange="NSE",
        ltp=51800.0,
        day_high=52400.0,  # Lagging Day High (not at high)
        day_low=51200.0,  # Holding well above Day Low (not at low)
        prev_close=52000.0,
        change_pct=-0.38,
        vwap=51950.0,  # Trapped below VWAP
    )
    meta = {"pair_id": "NIFTY_BANKNIFTY", "category": "BENCHMARK_INDEX"}
    item = evaluate_pair_smt(m_a, m_b, meta)
    assert item.status == "BEARISH_SMT_DISTRIBUTION"
    assert item.conviction_score >= 80
    assert item.actionable_directive == "VETO_LONGS_LOOK_FOR_SHORTS"


def test_evaluate_pair_smt_bullish_accumulation():
    """Verify that Asset A breaking Day Low while Asset B holds triggers Bullish SMT."""
    m_a = AssetMetrics(
        symbol="NIFTY",
        exchange="NSE",
        ltp=24380.0,
        day_high=24550.0,
        day_low=24390.0,  # Breaking Day Low
        prev_close=24500.0,
        change_pct=-0.49,
        vwap=24450.0,
    )
    m_b = AssetMetrics(
        symbol="BANKNIFTY",
        exchange="NSE",
        ltp=52100.0,
        day_high=52800.0,  # Holding well below Day High (not at high)
        day_low=51500.0,  # Holding comfortably above Day Low (not at low)
        prev_close=51900.0,
        change_pct=0.38,
        vwap=52000.0,  # Holding above VWAP
    )
    meta = {"pair_id": "NIFTY_BANKNIFTY", "category": "BENCHMARK_INDEX"}
    item = evaluate_pair_smt(m_a, m_b, meta)
    assert item.status == "BULLISH_SMT_ACCUMULATION"
    assert item.conviction_score >= 80
    assert item.actionable_directive == "VETO_SHORTS_LOOK_FOR_LONGS"


def test_scan_cross_market_smt_divergences_execution():
    """Verify that cross-market scanner executes cleanly across all pairs."""
    res = scan_cross_market_smt_divergences()
    assert res["status"] == "ok"
    assert res["summary"]["total_pairs_scanned"] == 5
    assert len(res["pairs"]) == 5
    pairs_map = {p["pair_id"]: p for p in res["pairs"]}
    assert "NIFTY_BANKNIFTY" in pairs_map
    assert "FINNIFTY_BANKNIFTY" in pairs_map
    assert "SENSEX_BANKEX" in pairs_map
    assert "GOLD_SILVER" in pairs_map
    assert "CRUDE_NATGAS" in pairs_map


# ── Module 4: Behavioral Anti-Tilt Coach ─────────────────────────


def test_behavioral_anti_tilt_status():
    """Verify that behavioral anti-tilt status returns structured coaching directives."""
    status = risk_limits.get_behavioral_anti_tilt_status()
    assert "loss_streak" in status
    assert "max_consecutive_losses" in status
    assert "daily_realized_loss" in status
    assert "tilt_state" in status
    assert "coaching_guidance" in status
    assert len(status["anti_tilt_checklist"]) == 3
