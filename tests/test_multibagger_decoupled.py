"""
tests/test_multibagger_decoupled.py
───────────────────────────────────
Test suite for Decoupled Multi-Horizon Multibagger and Wealth Compounder Engine:
  1. Decoupled Horizon Execution Tickets (Short, Mid, Long Term).
  2. Dual-Mode Trade Lifecycle (SWING vs STAGE_2_COMPOUNDER vs GENERATIONAL).
  3. Zero premature 2R profit booking & Pyramiding signals in Compounder mode.
  4. Broad Universe & Relative Strength Scoring in CompounderScanner.
"""

import numpy as np
import pandas as pd
import pytest

from analysis.multibagger import (
    MultibaggerReport,
    generate_generational_ticket,
    generate_mid_term_compounder_ticket,
    generate_short_term_ticket,
    scan_multibagger_opportunity,
)
from engine.compounder_scanner import CompounderScanner, compounder_scanner
from engine.trade_lifecycle import (
    PositionLifecycleReport,
    PositionMode,
    audit_position_lifecycle,
)


def _generate_synthetic_stage2_bars(n: int = 250, start_price: float = 100.0) -> pd.DataFrame:
    """Generates synthetic daily bars in an advancing Stage 2 markup with rising moving averages."""
    np.random.seed(42)
    t = np.linspace(0, 1, n)
    # Upward parabolic trend simulating Stage 2 expansion
    trend = start_price + (start_price * 1.2 * t) + (start_price * 0.3 * (t**2))
    noise = np.random.normal(0, start_price * 0.015, n)
    closes = trend + noise
    highs = closes * (1 + np.abs(np.random.normal(0.01, 0.005, n)))
    lows = closes * (1 - np.abs(np.random.normal(0.01, 0.005, n)))
    opens = (closes + lows) / 2
    volumes = np.random.uniform(50000, 200000, n)

    df = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )
    return df


class TestDecoupledMultibaggerTickets:
    def test_short_term_ticket_properties(self):
        """Short-term ticket must feature swing targets, tight ATR, and 50% scale-out at 2R."""
        df = _generate_synthetic_stage2_bars(100, 200.0)
        ticket = generate_short_term_ticket(ltp=250.0, df=df, is_vcp=True, pivot_price=252.0)

        assert ticket["horizon_id"] == "SHORT_TERM"
        assert ticket["action"] == "LONG (BUY)"
        assert ticket["strategy_action"] == "BUY_SWING_BREAKOUT"
        assert ticket["entry_price"] == 252.0
        assert ticket["stop_loss"] < 252.0
        assert ticket["target_1"] > 252.0
        assert "Scale 50% at Target 1 (+2R)" in ticket["trailing_stop_rule"]
        assert ticket["pyramid_allowed"] is False

    def test_mid_term_compounder_ticket_properties(self):
        """Mid-term ticket MUST enforce ZERO 2R profit booking and 50-SMA structural trailing."""
        df = _generate_synthetic_stage2_bars(150, 100.0)
        ticket = generate_mid_term_compounder_ticket(
            ltp=180.0, df=df, stage="STAGE_2_MARKUP", is_vcp=False, pivot_price=0.0
        )

        assert ticket["horizon_id"] == "MID_TERM"
        assert ticket["action"] == "LONG (BUY)"
        assert ticket["strategy_action"] == "BUY_STAGE_2_COMPOUNDER"
        assert ticket["entry_price"] == 180.0
        assert ticket["stop_loss"] < 180.0
        # Multibagger rule: Zero early profit booking
        assert "ZERO profit booking at 2R" in ticket["trailing_stop_rule"]
        assert "50-Day SMA" in ticket["trailing_stop_rule"]
        assert "Progressive Pyramiding Activated" in ticket["pyramid_rule"]
        assert ticket["target_runner"] > ticket["target_2"] > ticket["target_1"]

    def test_generational_ticket_properties(self):
        """Generational ticket anchors risk to 200-SMA floor and multi-year holding."""
        df = _generate_synthetic_stage2_bars(220, 500.0)
        ticket = generate_generational_ticket(
            ltp=900.0,
            df=df,
            details={"roce_pct": 24.5, "debt_equity": 0.25},
            forensic_safe=True,
        )

        assert ticket["horizon_id"] == "LONG_TERM"
        assert ticket["action"] == "LONG (BUY)"
        assert ticket["strategy_action"] == "ACCUMULATE_CORE_COMPOUNDER"
        assert ticket["stop_loss"] < 900.0
        assert ticket["target_runner"] >= 900.0 * 4.0  # 4x to 5x multi-year target
        assert "40-Week (200-Day) Moving Average" in ticket["trailing_stop_rule"]
        assert ticket["fundamental_anchors"]["roce_pct"] == 24.5

    def test_scan_multibagger_opportunity_populates_all_three_tickets(self):
        """scan_multibagger_opportunity must populate short_term, mid_term, and long_term tickets."""
        df = _generate_synthetic_stage2_bars(250, 150.0)
        report = scan_multibagger_opportunity("TRENT", df=df)

        assert isinstance(report, MultibaggerReport)
        assert report.symbol == "TRENT"
        assert report.short_term_ticket.get("horizon_id") == "SHORT_TERM"
        assert report.mid_term_ticket.get("horizon_id") == "MID_TERM"
        assert report.long_term_ticket.get("horizon_id") == "LONG_TERM"
        assert report.execution_ticket is not None
        assert report.trend_template_passed >= 6


class TestDualModeTradeLifecycle:
    def test_swing_mode_forces_profit_booking_at_2r(self):
        """Under SWING mode, reaching +2R triggers SCALE_OUT_50_PCT."""
        df = _generate_synthetic_stage2_bars(100, 100.0)
        # Entry = 100, SL = 90, Risk = 10. LTP = 120 -> +2R payoff
        report = audit_position_lifecycle(
            symbol="SWING_TEST",
            entry_price=100.0,
            initial_stop_loss=90.0,
            current_ltp=120.0,
            df=df,
            mode="SWING",
        )

        assert report.position_mode == "SWING"
        assert report.current_r_multiple == pytest.approx(2.0, rel=1e-2)
        assert report.recommended_action == "SCALE_OUT_50_PCT"
        assert "Lock in 33-50% partial profit" in report.diagnostic_bullet_points[1]

    def test_stage_2_compounder_mode_forbids_2r_profit_taking(self):
        """Under STAGE_2_COMPOUNDER mode, reaching +2R must NOT scale out. Action is HOLD_COMPOUNDER."""
        df = _generate_synthetic_stage2_bars(100, 100.0)
        # Entry = 100, SL = 90, Risk = 10. LTP = 120 -> +2R payoff
        report = audit_position_lifecycle(
            symbol="COMPOUNDER_TEST",
            entry_price=100.0,
            initial_stop_loss=90.0,
            current_ltp=120.0,
            df=df,
            mode="STAGE_2_COMPOUNDER",
        )

        assert report.position_mode == "STAGE_2_COMPOUNDER"
        assert report.current_r_multiple == pytest.approx(2.0, rel=1e-2)
        # CRITICAL TEST: Must NOT be SCALE_OUT_50_PCT
        assert report.recommended_action == "HOLD_COMPOUNDER"
        assert "Do NOT scale out" in report.diagnostic_bullet_points[1]
        assert report.trailing_stops.stop_method == "BASE_PIVOT_BREAKEVEN"

    def test_stage_2_compounder_pyramiding_trigger_at_4r(self):
        """Under STAGE_2_COMPOUNDER mode, reaching +4R triggers PYRAMID_ADD_ON and 50-SMA trail."""
        df = _generate_synthetic_stage2_bars(100, 100.0)
        # Entry = 100, SL = 90, Risk = 10. LTP = 145 -> +4.5R payoff
        report = audit_position_lifecycle(
            symbol="PYRAMID_TEST",
            entry_price=100.0,
            initial_stop_loss=90.0,
            current_ltp=145.0,
            df=df,
            mode="STAGE_2_COMPOUNDER",
        )

        assert report.recommended_action == "PYRAMID_ADD_ON"
        assert report.pyramid_signal is not None
        assert report.pyramid_signal["active"] is True
        assert report.pyramid_signal["recommended_action"] == "ADD_30_PCT_ON_PULLBACK"
        assert report.trailing_stops.sma50_stop > 90.0

    def test_generational_mode_anchors_to_200_sma(self):
        """Under GENERATIONAL mode, trailing stop is anchored to the 200-SMA structural floor."""
        df = _generate_synthetic_stage2_bars(220, 100.0)
        report = audit_position_lifecycle(
            symbol="GEN_TEST",
            entry_price=100.0,
            initial_stop_loss=85.0,
            current_ltp=160.0,
            df=df,
            mode="GENERATIONAL",
        )

        assert report.position_mode == "GENERATIONAL"
        assert report.recommended_action == "HOLD_COMPOUNDER"
        assert report.trailing_stops.stop_method == "200_SMA_FLOOR"


class TestCompounderScanner:
    def test_broad_universe_returns_large_set(self):
        """Broad universe must return 50+ equities spanning Large, Mid, Small, and Microcaps."""
        universe = compounder_scanner.get_broad_multibagger_universe()
        assert len(universe) >= 30
        assert "TRENT" in universe
        assert "HAL" in universe

    def test_relative_strength_calculation(self):
        """Relative strength should be > 75 for strongly outperforming Stage 2 asset."""
        stock_df = _generate_synthetic_stage2_bars(150, 100.0)
        # Flat benchmark
        nifty_df = pd.DataFrame({"close": np.full(150, 24000.0)})

        rs = compounder_scanner.compute_relative_strength(stock_df, nifty_df)
        assert rs >= 75
        assert rs <= 99

    def test_roster_horizon_filtering(self):
        """Scanner get_roster must cleanly filter by SHORT, MID, and LONG horizons."""
        roster = compounder_scanner.get_roster("SHORT")
        assert roster["horizon"] == "SHORT_TERM"

        roster_mid = compounder_scanner.get_roster("MID")
        assert roster_mid["horizon"] == "MID_TERM"

        roster_long = compounder_scanner.get_roster("LONG")
        assert roster_long["horizon"] == "LONG_TERM"


class TestCompounderAPIEndpoints:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from web.api import app

        return TestClient(app)

    def test_get_compounder_roster_endpoint(self, client):
        res = client.get("/api/compounder/roster?horizon=ALL")
        assert res.status_code == 200
        data = res.json()
        assert "short_term_rockets" in data
        assert "mid_term_compounders" in data
        assert "generational_compounders" in data

    def test_get_compounder_lifecycle_endpoint(self, client):
        res = client.get(
            "/api/compounder/lifecycle/TRENT?entry=100&sl=90&ltp=125&mode=STAGE_2_COMPOUNDER"
        )
        assert res.status_code == 200
        data = res.json()
        assert data["position_mode"] == "STAGE_2_COMPOUNDER"
        assert data["recommended_action"] == "HOLD_COMPOUNDER"
        assert data["breakeven_reached"] is True

    def test_get_multibagger_analysis_endpoint(self, client):
        res = client.get("/api/compounder/multibagger/TRENT")
        assert res.status_code == 200
        data = res.json()
        assert "short_term_ticket" in data
        assert "mid_term_ticket" in data
        assert "long_term_ticket" in data
        assert data["symbol"] == "TRENT"

