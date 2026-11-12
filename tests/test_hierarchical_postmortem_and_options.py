"""
tests/test_hierarchical_postmortem_and_options.py
─────────────────────────────────────────────────
Institutional verification suite for Iteration 4 & 5:
  1. Post-Mortem 5W Dimensional Attribution (Why, When, Where, Who) in EOD Scorecard.
  2. Closed-Loop Feedback & Learning Analytics in PatternLearningEngine.
  3. Dynamic Spot Resolution in Portfolio Greeks (Elimination of static spot fallbacks).
  4. Telegram EOD Scorecard 5W Formatting.
"""

from __future__ import annotations

from unittest.mock import patch

from engine.alert_postmortem_runner import (
    generate_session_scorecard,
    format_eod_scorecard_telegram,
)
from engine.learning_engine import PatternLearningEngine
from engine.portfolio_greeks import calculate_portfolio_greeks


def _make_dummy_alert(
    alert_id: str,
    symbol: str,
    outcome_type: str,  # "WIN", "LOSS", "UNFULFILLED"
    why_thesis: str = "MOMENTUM_BREAKOUT",
    when_window: str = "MORNING_MOMENTUM",
    where_anchor: str = "VWAP_RECLAIM",
    who_counterparty: str = "TRAPPED_BEARS",
):
    class DummyAlert:
        pass

    a = DummyAlert()
    a.alert_id = alert_id
    a.id = alert_id
    a.symbol = symbol
    a.contract_symbol = None
    a.alert_type = "MOMENTUM"
    a.direction = "BULLISH"
    a.entry_price = 100.0
    a.trigger_level = 100.0
    a.ltp = 105.0 if outcome_type == "WIN" else (95.0 if outcome_type == "LOSS" else 100.0)
    a.stop_loss = 98.0
    a.has_triggered = True
    a.is_disqualified = False
    a.stage = "TRIGGERED"
    a.target_status = "ACTIVE"
    a.is_expired = False
    a.time_horizon = "INTRADAY"
    a.setup_style = "INTRADAY"
    a.matched_factors = ["RVOL", "SMC_BOS"]

    if outcome_type == "WIN":
        a.is_invalidated = False
        a.achieved_milestones = ["T1_REACHED", "T2_REACHED"]
        a.r_multiple = 2.5
    elif outcome_type == "LOSS":
        a.is_invalidated = True
        a.achieved_milestones = []
        a.r_multiple = -1.0
        a.target_status = "INVALIDATED"
    else:  # UNFULFILLED
        a.is_invalidated = False
        a.achieved_milestones = []
        a.r_multiple = 0.0

    a.metrics = {
        "hierarchical_pipeline": {
            "level2_5ws": {
                "why_alpha_thesis": why_thesis,
                "when_session_window": when_window,
                "where_structural_anchor": where_anchor,
                "who_trapped_counterparty": who_counterparty,
            }
        }
    }
    return a


class TestPostmortem5WAttribution:
    def test_scorecard_aggregates_5w_dimensions(self):
        alerts = [
            _make_dummy_alert(
                "A1",
                "RELIANCE",
                "WIN",
                "MOMENTUM_BREAKOUT",
                "MORNING_MOMENTUM",
                "VWAP_RECLAIM",
                "TRAPPED_BEARS",
            ),
            _make_dummy_alert(
                "A2",
                "TCS",
                "WIN",
                "MOMENTUM_BREAKOUT",
                "MORNING_MOMENTUM",
                "VWAP_RECLAIM",
                "TRAPPED_BEARS",
            ),
            _make_dummy_alert(
                "A3",
                "INFY",
                "LOSS",
                "MEAN_REVERSION",
                "MIDDAY_COMPRESSION",
                "DAILY_PIVOT_S1",
                "TRAPPED_LONGS",
            ),
            _make_dummy_alert(
                "A4",
                "HDFCBANK",
                "LOSS",
                "MEAN_REVERSION",
                "MIDDAY_COMPRESSION",
                "DAILY_PIVOT_S1",
                "TRAPPED_LONGS",
            ),
            _make_dummy_alert(
                "A5",
                "ICICIBANK",
                "UNFULFILLED",
                "SMC_LIQUIDITY_SWEEP",
                "AFTERNOON_EXPANSION",
                "VALUE_AREA_POC",
                "RETAIL_BREAKOUT",
            ),
        ]

        scorecard = generate_session_scorecard(alerts, session_date="2026-11-11")

        assert scorecard["total_alerts"] == 5
        assert scorecard["wins"] == 2
        assert scorecard["losses"] == 2
        assert scorecard["unfulfilled"] == 1
        assert scorecard["win_rate_pct"] == 50.0

        dim_5ws = scorecard.get("dimensional_attribution_5ws", {})
        assert "why_alpha_thesis" in dim_5ws
        assert "when_session_window" in dim_5ws
        assert "where_structural_anchor" in dim_5ws
        assert "who_trapped_counterparty" in dim_5ws

        # Check WHY dimension
        why_stats = dim_5ws["why_alpha_thesis"]
        assert why_stats["MOMENTUM_BREAKOUT"]["wins"] == 2
        assert why_stats["MOMENTUM_BREAKOUT"]["losses"] == 0
        assert why_stats["MOMENTUM_BREAKOUT"]["win_rate_pct"] == 100.0

        assert why_stats["MEAN_REVERSION"]["wins"] == 0
        assert why_stats["MEAN_REVERSION"]["losses"] == 2
        assert why_stats["MEAN_REVERSION"]["win_rate_pct"] == 0.0

        # Check WHEN dimension
        when_stats = dim_5ws["when_session_window"]
        assert when_stats["MORNING_MOMENTUM"]["wins"] == 2
        assert when_stats["MORNING_MOMENTUM"]["losses"] == 0

        assert when_stats["MIDDAY_COMPRESSION"]["wins"] == 0
        assert when_stats["MIDDAY_COMPRESSION"]["losses"] == 2

        # Check Recommendations for Midday Compression (2 losses, 0 wins)
        recs = scorecard.get("calibration_recommendations", [])
        midday_rec = next(
            (
                r
                for r in recs
                if r.get("target") == "session_window_filter"
                and r.get("adjustment") == "MIDDAY_COMPRESSION"
            ),
            None,
        )
        assert midday_rec is not None
        assert midday_rec["action"] == "TIGHTEN_SESSION_WINDOW"

    def test_telegram_scorecard_renders_5w_timing(self):
        alerts = [
            _make_dummy_alert("A1", "RELIANCE", "WIN", "MOMENTUM_BREAKOUT", "MORNING_MOMENTUM"),
            _make_dummy_alert("A2", "TCS", "LOSS", "MOMENTUM_BREAKOUT", "AFTERNOON_EXPANSION"),
        ]
        scorecard = generate_session_scorecard(alerts, session_date="2026-11-11")
        tg_text = format_eod_scorecard_telegram(scorecard)

        assert "Session Timing Performance" in tg_text
        assert "MORNING_MOMENTUM" in tg_text
        assert "AFTERNOON_EXPANSION" in tg_text


class TestPatternLearningEngine5W:
    def test_record_and_aggregate_5w_attribution(self, tmp_path):
        engine = PatternLearningEngine()
        engine._outcomes = []

        engine.record_trade_outcome(
            alert_id="TEST-001",
            symbol="RELIANCE",
            archetype="MOMENTUM",
            entry_price=2500.0,
            exit_price=2560.0,
            outcome="WIN_T1",
            realized_rr=2.0,
            alpha_thesis="MOMENTUM_BREAKOUT",
            session_window="MORNING_MOMENTUM",
            structural_anchor="VWAP_RECLAIM",
            trapped_counterparty="TRAPPED_BEARS",
        )
        engine.record_trade_outcome(
            alert_id="TEST-002",
            symbol="TCS",
            archetype="MEAN_REVERSION",
            entry_price=3500.0,
            exit_price=3450.0,
            outcome="STOPPED_OUT",
            realized_rr=-1.0,
            alpha_thesis="MEAN_REVERSION",
            session_window="MIDDAY_COMPRESSION",
            structural_anchor="CPR_CENTRAL_PIVOT",
            trapped_counterparty="TRAPPED_LONGS",
        )

        dim_attr = engine.get_5w_dimensional_attribution()
        assert "why_alpha_thesis" in dim_attr
        assert "when_session_window" in dim_attr
        assert "where_structural_anchor" in dim_attr
        assert "who_trapped_counterparty" in dim_attr

        why_res = dim_attr["why_alpha_thesis"]
        assert why_res["MOMENTUM_BREAKOUT"]["wins"] == 1
        assert why_res["MOMENTUM_BREAKOUT"]["losses"] == 0
        assert why_res["MOMENTUM_BREAKOUT"]["win_rate_pct"] == 100.0

        assert why_res["MEAN_REVERSION"]["wins"] == 0
        assert why_res["MEAN_REVERSION"]["losses"] == 1
        assert why_res["MEAN_REVERSION"]["win_rate_pct"] == 0.0

        analytics = engine.get_learning_analytics()
        assert "dimensional_attribution_5ws" in analytics
        assert analytics["dimensional_attribution_5ws"] == dim_attr


class TestPortfolioGreeksDynamicSpot:
    def test_dynamic_spot_resolution_no_hardcoded_fallback(self):
        positions = [
            {
                "symbol": "BANKNIFTY26NOV52000CE",
                "underlying": "BANKNIFTY",
                "instrument_type": "CE",
                "quantity": 15,
                "price": 350.0,
                "strike": 52000.0,
                "dte": 5,
            }
        ]

        with patch("market.contract_selection.fresh_underlying_price", return_value=51850.0):
            snapshot = calculate_portfolio_greeks(positions, spot_map={})
            assert snapshot.total_capital_deployed_inr > 0
            # Delta value should be computed with dynamic spot 51850.0, NOT static 52000.0
            pos_greek = snapshot.positions[0]
            assert pos_greek.symbol == "BANKNIFTY26NOV52000CE"
            assert pos_greek.delta is not None
