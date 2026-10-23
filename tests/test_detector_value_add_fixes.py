"""
tests/test_detector_value_add_fixes.py
──────────────────────────────────────
Deterministic regression and invariant tests for the 5 institutional value-add fixes:
  1. Minimum Option Premium Volatility Floor in AlertScrutinyAuditor
  2. Follower RVOL Confirmation Gate in ThematicPeerSympathyEngine
  3. Cointegration Ruin Circuit Breaker in MultiBacktester
  4. Two-Strike Derivative-to-Underlying Lockout Propagation in PatternLearningEngine
  5. SMT Inter-Market Divergence Confirmation in TurtleSoupDetector
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from engine.alert_identity import generate_alert_id
from engine.alert_model import AutoAlert
from engine.alert_scrutiny import AlertScrutinyAuditor
from engine.learning_engine import PatternLearningEngine
from engine.thematic_peer_sympathy import ThematicPeerSympathyEngine
from engine.detectors.turtle_soup import detect_turtle_soup_sweep
from engine.backtest import MultiBacktester, Strategy


@pytest.fixture
def auditor() -> AlertScrutinyAuditor:
    return AlertScrutinyAuditor(min_rr_ratio=1.3, max_intraday_risk_pct=45.0)


def test_sub_noise_option_sl_rejection(auditor: AlertScrutinyAuditor):
    """
    Option alerts with premium stop-loss < max(3.0 pts, 10% of premium)
    must be rejected to prevent sub-ATR bid-ask noise liquidations.
    """
    # Option entry 120, SL 118 (risk 2 pts < 12 pts floor)
    alert = AutoAlert(
        alert_id="opt-tight-sl",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NSE:NIFTY26OCT25000CE",
        exchange="NFO",
        direction="BULLISH",
        headline="Nifty Call Option Tight",
        summary="Tight option",
        ltp=120.0,
        trigger_level=120.0,
        stop_loss=118.0,  # 2.0 pts risk (< 12.0 pts floor)
        target_level=160.0,
        strike=25000.0,
        option_type="CE",
        option_premium=120.0,
        is_live=True,
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed is False
    assert "Sub-ATR Option Noise Trap" in reason
    assert flags["risk_within_bounds"] is False


def test_valid_option_sl_approval(auditor: AlertScrutinyAuditor):
    """
    Option alert with disciplined stop loss (>= 10% of premium) passes Tier 1 sanity.
    """
    # Option entry 120, SL 105 (risk 15 pts >= 12 pts floor, R:R 1:2.0)
    alert = AutoAlert(
        alert_id="opt-valid-sl",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NSE:NIFTY26OCT25000CE",
        exchange="NFO",
        direction="BULLISH",
        headline="Nifty Call Option Valid",
        summary="Valid option setup",
        ltp=120.0,
        trigger_level=120.0,
        stop_loss=105.0,  # 15.0 pts risk (12.5% of premium)
        target_level=155.0,  # 35.0 pts reward (1:2.33 R:R)
        strike=25000.0,
        option_type="CE",
        option_premium=120.0,
        is_live=True,
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed is True, f"Failed Tier 1 sanity: {reason}"
    assert flags["risk_within_bounds"] is True
    assert flags["level_coherence"] is True


def test_thematic_sympathy_follower_low_rvol_rejection(monkeypatch):
    """
    Sympathy candidate with green slope & above VWAP must be rejected if relative volume is thin (RVOL < 0.80).
    """
    monkeypatch.delenv("CHANAKYA_TESTING", raising=False)
    engine = ThematicPeerSympathyEngine()

    leader = AutoAlert(
        alert_id=generate_alert_id("RVNL", "OPENING_DRIVE"),
        alert_type="OPENING_DRIVE",
        stage="IGNITED",
        symbol="NSE:RVNL",
        exchange="NSE",
        direction="BULLISH",
        headline="RVNL Lead",
        summary="Leader ignited",
        ltp=450.0,
        trigger_level=450.0,
        stop_loss=440.0,
        target_level=480.0,
        confidence=90,
    )
    engine.record_leader_alert(leader)

    # IRFC has price above VWAP, green on day, but volume is 10,000 vs avg 100,000 (RVOL = 0.10)
    mock_quotes = {
        "NSE:IRFC": {
            "symbol": "NSE:IRFC",
            "ltp": 155.0,
            "open": 150.0,
            "previous_close": 150.0,
            "low": 150.0,
            "high": 155.5,
            "vwap": 152.0,
            "volume": 10000,
            "average_volume": 100000,  # dyn_rvol = 0.10 (< 0.80)
        }
    }

    candidates = engine.evaluate_peer_sympathy(quotes_map=mock_quotes)
    # Must reject IRFC due to low relative volume
    irfc_alerts = [c for c in candidates if "IRFC" in c.symbol]
    assert len(irfc_alerts) == 0, (
        "Thin follower was incorrectly qualified without volume confirmation!"
    )


def test_option_derivative_lockout_propagates_to_underlying():
    """
    When an option contract is invalidated, the learning engine locks out both
    the derivative contract AND the underlying index/stock, preventing strike churn.
    """
    learning_engine = PatternLearningEngine()
    learning_engine.clear_symbol_lockout()

    opt_alert = AutoAlert(
        alert_id="opt-churn-inv",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NSE:NIFTY26OCT25000CE",
        exchange="NFO",
        direction="BULLISH",
        headline="Nifty Call Invalidation",
        summary="Stopped out",
        ltp=100.0,
        trigger_level=100.0,
        stop_loss=85.0,
        target_level=130.0,
        option_premium=100.0,
    )

    learning_engine.conduct_invalidation_post_mortem(
        alert=opt_alert,
        exit_price=84.0,
    )

    # 1. Option contract itself is locked out
    locked, reason = learning_engine.is_symbol_locked_out("NIFTY26OCT25000CE", direction="BULLISH")
    assert locked is True
    assert (
        "NIFTY" in reason
        or "Options" in reason
        or "Trap" in reason
        or "Invalidation" in reason
        or "Orderflow" in reason
        or "Vwap" in reason
        or "Noise" in reason
        or "Chop" in reason
        or "Auction" in reason
        or "Opening" in reason
    )

    # 2. Underlying NIFTY itself is locked out
    locked_idx, _ = learning_engine.is_symbol_locked_out("NIFTY", direction="BULLISH")
    assert locked_idx is True

    # 3. Another strike on same underlying (e.g. 25100CE) is ALSO locked out via underlying inheritance
    locked_sibling_strike, _ = learning_engine.is_symbol_locked_out(
        "NIFTY26OCT25100CE", direction="BULLISH"
    )
    assert locked_sibling_strike is True


def test_multi_backtester_cointegration_ruin_circuit_breaker():
    """
    MultiBacktester stops out diverging pairs when combined adverse excursion exceeds max_adverse_pct (5%).
    """
    dates = pd.date_range("2026-01-01", periods=30, freq="B")
    # Leg A drops 10%
    prices_a = [100.0 * (0.99**i) for i in range(30)]
    # Leg B also moves adversely: short leg rises 10%
    prices_b = [100.0 * (1.01**i) for i in range(30)]

    df_a = pd.DataFrame(
        {"close": prices_a, "open": prices_a, "high": prices_a, "low": prices_a}, index=dates
    )
    df_b = pd.DataFrame(
        {"close": prices_b, "open": prices_b, "high": prices_b, "low": prices_b}, index=dates
    )

    class DummyPairStrategy(Strategy):
        def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
            # Long A, Short B entered at bar 1, never flips
            sigs_a = pd.Series(0, index=df.index)
            sigs_b = pd.Series(0, index=df.index)
            sigs_a.iloc[1:] = 1
            sigs_b.iloc[1:] = -1
            return pd.DataFrame({"STOCKA": sigs_a, "STOCKB": sigs_b})

    bt = MultiBacktester(symbols=["STOCKA", "STOCKB"], max_adverse_pct=5.0)
    bt._data = {"STOCKA": df_a, "STOCKB": df_b}

    res = bt.run(DummyPairStrategy())
    # The trade must have stopped out early via the circuit breaker
    assert res.total_trades >= 1
    # Check that drawdown was bounded and trade did not ride down 30 bars
    first_trade = res.trades[0]
    assert first_trade.hold_days < 25, (
        f"Hold days {first_trade.hold_days} was not cut by circuit breaker!"
    )
    assert first_trade.combined_pnl_pct <= -4.5  # stopped around -5%


def test_turtle_soup_smt_confirmation():
    """
    Turtle soup on an index evaluates SMT divergence and boosts confidence to 89 when confirmed.
    """
    dates = pd.date_range("2026-01-01", periods=25, freq="D")
    # 24 prior bars with high=24000, low=23800
    highs = [24000.0] * 24 + [24050.0]  # Last bar sweeps 24000 up to 24050
    lows = [23800.0] * 24 + [23900.0]
    closes = [23900.0] * 24 + [23960.0]  # Last bar closes back below 24000 at 23960
    opens = [23850.0] * 24 + [23950.0]

    df_nifty = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes}, index=dates
    )

    mock_smt_res = MagicMock()
    mock_smt_res.has_divergence = True
    mock_smt_res.sibling_symbol = "BANKNIFTY"
    mock_smt_res.rationale = "BANKNIFTY made lower high while NIFTY swept higher"

    with patch("engine.smt_divergence.evaluate_smt_divergence", return_value=mock_smt_res):
        alert = detect_turtle_soup_sweep(
            symbol="NIFTY",
            df=df_nifty,
            ltp=23960.0,
        )

    assert alert is not None
    assert alert.metrics.get("smt_confirmed") is True
    assert alert.metrics.get("smt_sibling") == "BANKNIFTY"
    assert alert.confidence == 89
    assert "SMT Confirmed" in alert.headline
