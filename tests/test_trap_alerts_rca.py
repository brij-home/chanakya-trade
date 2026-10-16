"""
tests/test_trap_alerts_rca.py
──────────────────────────────
Institutional regression tests validating Root Cause Analysis (RCA) fixes for:
  1. BANKNIFTY Call Setup afternoon Call Wall trap & Camarilla H5 exhaustion suppression.
  2. NIFTY Contagion fatigue trap (DAY_HIGH_FATIGUE_TRAP / Terminal ADR expansion) suppression.
  3. MIDCPNIFTY Micro-Scalp Wide CPR chop filter & dynamic SL sizing (no 10pt clamping on high premium).
  4. Alert Evaluator runway extension bounded by 15:15 IST intraday session cutoff.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo
import pandas as pd

from brokers.base import Quote
from engine.alert_model import AutoAlert
from engine.detectors.index_call_setup import detect_index_call_setup
from engine.detectors.index_put_setup import detect_index_put_setup
from engine.detectors.index_micro_scalp import detect_index_micro_scalp
from engine.index_contagion import index_contagion_engine
from engine.alert_evaluator import evaluate_alert_targets_and_trailing

IST = ZoneInfo("Asia/Kolkata")


@dataclass
class MockOptionContract:
    symbol: str
    strike: float
    option_type: str
    last_price: float
    volume: int
    oi: int
    pchange: float = 0.0
    change_pct: float = 0.0
    expiry: str = "2026-10-15"
    expiry_date: str = "2026-10-15"
    oi_change: int = 1500


def _build_mock_chain(
    base_strike: float, step: float = 100.0, spot: float = 55800.0, max_call_strike: float = 56000.0
) -> list[MockOptionContract]:
    chain = []
    for i in range(-5, 6):
        strk = base_strike + i * step
        # CE contract
        call_oi = 500000 if strk == max_call_strike else 100000
        chain.append(
            MockOptionContract(
                symbol=f"BANKNIFTY{int(strk)}CE",
                strike=strk,
                option_type="CE",
                last_price=max(
                    10.0, (spot - strk) + 150.0 if strk <= spot else 150.0 - (strk - spot) * 0.4
                ),
                volume=25000,
                oi=call_oi,
                pchange=15.0,
                oi_change=50000 if strk == max_call_strike else 5000,
            )
        )
        # PE contract
        chain.append(
            MockOptionContract(
                symbol=f"BANKNIFTY{int(strk)}PE",
                strike=strk,
                option_type="PE",
                last_price=max(
                    10.0, (strk - spot) + 150.0 if strk >= spot else 150.0 - (spot - strk) * 0.4
                ),
                volume=20000,
                oi=120000,
                pchange=-10.0,
                oi_change=-2000,
            )
        )
    return chain


class TestBankNiftyCallSetupRCA:
    """Verifies that BANKNIFTY Call Setups are suppressed at Call Walls and Camarilla H5."""

    def test_suppressed_near_call_wall_afternoon(self):
        """Spot at 55,864 is 136 pts (0.24%) below 56,000 Call Wall at 14:19 IST with call writers active -> MUST BE SUPPRESSED."""
        chain = _build_mock_chain(
            base_strike=55800.0, step=100.0, spot=55864.0, max_call_strike=56000.0
        )
        ref_dt = datetime(2026, 10, 15, 14, 19, 0, tzinfo=IST)

        alerts = detect_index_call_setup(
            underlying="BANKNIFTY",
            spot=55864.0,
            chain=chain,
            vwap=55700.0,
            day_high=55880.0,
            day_low=55300.0,
            prev_day_high=55600.0,
            prev_day_low=55100.0,
            ref_time=ref_dt,
            ignore_time_gate=True,
        )

        assert len(alerts) == 0, (
            "Expected call setup to be suppressed due to afternoon Call Wall collision at 56,000"
        )

    def test_suppressed_at_camarilla_h5(self):
        """Spot >= Camarilla H5 ceiling -> MUST BE SUPPRESSED."""
        chain = _build_mock_chain(
            base_strike=55800.0, step=100.0, spot=55860.0, max_call_strike=56500.0
        )
        ref_dt = datetime(2026, 10, 15, 11, 30, 0, tzinfo=IST)

        mock_dl = MagicMock()
        mock_dl.camarilla = {"h5": 55856.41, "h4": 55650.0}
        mock_dl.atr_14 = 400.0

        with patch("engine.daily_levels.get_daily_levels", return_value=mock_dl):
            alerts = detect_index_call_setup(
                underlying="BANKNIFTY",
                spot=55860.0,
                chain=chain,
                vwap=55600.0,
                day_high=55865.0,
                day_low=55300.0,
                prev_day_high=55600.0,
                prev_day_low=55100.0,
                ref_time=ref_dt,
                ignore_time_gate=True,
            )

            assert len(alerts) == 0, "Expected call setup to be suppressed at Camarilla H5 ceiling"


class TestIndexContagionRCA:
    """Verifies that NIFTY Contagion suppresses non-viable fatigue traps fail-closed."""

    def test_contagion_suppressed_when_fatigue_trap(self):
        """When index spot is pinned at Day High and overextended from VWAP, contagion must return None (fail closed)."""
        dt = datetime(2026, 10, 15, 14, 21, tzinfo=IST)

        # Quotes with spot 23,000, VWAP 22,920 (+0.35% from VWAP), Day High 23,005
        quotes = {
            "NSE:NIFTY": Quote(
                symbol="NIFTY",
                last_price=23000.0,
                vwap=22920.0,
                change_pct=1.5,
                high=23005.0,
                low=22540.0,
            ),
            "NSE:RELIANCE": Quote(
                symbol="RELIANCE",
                last_price=3050.0,
                vwap=3000.0,
                change_pct=3.3,
                volume=1_500_000,
                high=3055.0,
            ),
            "NSE:ICICIBANK": Quote(
                symbol="ICICIBANK",
                last_price=1350.0,
                vwap=1320.0,
                change_pct=3.4,
                volume=1_200_000,
                high=1352.0,
            ),
            "NSE:HDFCBANK": Quote(
                symbol="HDFCBANK",
                last_price=1750.0,
                vwap=1720.0,
                change_pct=2.0,
                volume=1_800_000,
                high=1752.0,
            ),
            "NSE:INFY": Quote(
                symbol="INFY",
                last_price=1900.0,
                vwap=1880.0,
                change_pct=1.8,
                volume=900_000,
                high=1902.0,
            ),
            "NSE:TCS": Quote(
                symbol="TCS",
                last_price=4300.0,
                vwap=4250.0,
                change_pct=1.5,
                volume=700_000,
                high=4305.0,
            ),
        }

        res = index_contagion_engine.evaluate_index("NIFTY", quotes_map=quotes, ref_dt=dt)
        assert res is not None
        assert res.bullish_weight_pct >= 68.0
        # The alert MUST be suppressed fail-closed because spot is pinned at Day High (DAY_HIGH_FATIGUE_TRAP)
        assert res.alert is None, (
            "Contagion alert must be None when spot is pinned at Day High fatigue trap"
        )

    def test_contagion_suppressed_on_terminal_adr(self):
        """When index has expanded >= 1.25x ATR from day low, contagion alert must be suppressed."""
        dt = datetime(2026, 10, 15, 14, 21, tzinfo=IST)

        quotes = {
            "NSE:NIFTY": Quote(
                symbol="NIFTY",
                last_price=23000.0,
                vwap=22960.0,
                change_pct=1.8,
                high=23050.0,
                low=22540.0,
            ),
            "NSE:RELIANCE": Quote(
                symbol="RELIANCE",
                last_price=3050.0,
                vwap=3000.0,
                change_pct=3.3,
                volume=1_500_000,
                high=3055.0,
            ),
            "NSE:ICICIBANK": Quote(
                symbol="ICICIBANK",
                last_price=1350.0,
                vwap=1320.0,
                change_pct=3.4,
                volume=1_200_000,
                high=1352.0,
            ),
            "NSE:HDFCBANK": Quote(
                symbol="HDFCBANK",
                last_price=1750.0,
                vwap=1720.0,
                change_pct=2.0,
                volume=1_800_000,
                high=1752.0,
            ),
            "NSE:INFY": Quote(
                symbol="INFY",
                last_price=1900.0,
                vwap=1880.0,
                change_pct=1.8,
                volume=900_000,
                high=1902.0,
            ),
            "NSE:TCS": Quote(
                symbol="TCS",
                last_price=4300.0,
                vwap=4250.0,
                change_pct=1.5,
                volume=700_000,
                high=4305.0,
            ),
        }

        mock_dl = MagicMock()
        mock_dl.camarilla = {"h5": 23200.0, "l5": 22400.0}
        mock_dl.atr_14 = 300.0  # 1.25 * 300 = 375 pts. Spot moved 23000 - 22540 = 460 pts!

        with patch("engine.daily_levels.get_daily_levels", return_value=mock_dl):
            res = index_contagion_engine.evaluate_index("NIFTY", quotes_map=quotes, ref_dt=dt)
            assert res is not None
            assert res.alert is None, (
                "Contagion alert must be None due to Terminal ADR exhaustion expansion"
            )


class TestMidcpNiftyMicroScalpRCA:
    """Verifies that MIDCPNIFTY Micro-Scalp suppresses Wide CPR chop and sizes SL dynamically."""

    def test_suppressed_in_wide_cpr_chop_zone(self):
        """Spot inside Camarilla L3-H3 on a Wide CPR day -> MUST BE SUPPRESSED."""
        ref_dt = datetime(2026, 10, 14, 13, 25, 0, tzinfo=IST)
        strikes = [13700.0, 13750.0, 13775.0, 13800.0, 13850.0]
        chain = []
        for s in strikes:
            chain.append(
                MockOptionContract(
                    symbol=f"MIDCPNIFTY26OCT{int(s)}CE",
                    strike=s,
                    option_type="CE",
                    last_price=220.0 if s == 13775.0 else 180.0,
                    volume=50000,
                    oi=80000,
                    pchange=20.0,
                    oi_change=12000,
                )
            )

        mock_dl = MagicMock()
        mock_dl.cpr = {"pivot": 13750.0, "tc": 13790.0, "bc": 13710.0, "width_pct": 0.58}
        mock_dl.camarilla = {"h3": 13800.0, "l3": 13730.0}

        with patch("engine.daily_levels.get_daily_levels", return_value=mock_dl):
            alerts = detect_index_micro_scalp(
                underlying="MIDCPNIFTY",
                spot=13770.0,  # Inside 13730 (L3) and 13800 (H3)
                chain=chain,
                vwap=13765.0,
                day_high=13810.0,
                day_low=13720.0,
                ref_time=ref_dt,
                ignore_time_gate=True,
            )

            assert len(alerts) == 0, (
                "Expected micro scalp alert to be suppressed in Wide CPR range-bound chop zone"
            )

    def test_dynamic_stop_loss_on_high_premium_not_clamped_to_10_pts(self):
        """When premium is ₹220, stop loss must be sized proportionally (~10% = 22 pts), NOT clamped to 10 pts."""
        ref_dt = datetime(2026, 10, 14, 10, 15, 0, tzinfo=IST)
        chain = [
            MockOptionContract(
                symbol="MIDCPNIFTY26OCT13775CE",
                strike=13775.0,
                option_type="CE",
                last_price=220.0,
                volume=80000,
                oi=120000,
                pchange=25.0,
                oi_change=25000,
            )
        ]

        mock_dl = MagicMock()
        # Narrow CPR outside chop zone
        mock_dl.cpr = {"pivot": 13750.0, "tc": 13760.0, "bc": 13740.0, "width_pct": 0.15}
        mock_dl.camarilla = {"h3": 13780.0, "l3": 13720.0}

        with patch("engine.daily_levels.get_daily_levels", return_value=mock_dl):
            alerts = detect_index_micro_scalp(
                underlying="MIDCPNIFTY",
                spot=13810.0,  # Above H3, clear momentum breakout
                chain=chain,
                vwap=13780.0,
                day_high=13815.0,
                day_low=13740.0,
                ref_time=ref_dt,
                ignore_time_gate=True,
            )

            assert len(alerts) > 0, "Expected ignited micro scalp alert"
            alert = alerts[0]
            # Risk must NOT be 10.0 pts! On ₹220, 10% risk is 22.0 pts
            risk = alert.trigger_level - alert.stop_loss
            assert risk >= 18.0, f"Expected dynamic risk >= 18 pts on ₹220 premium, got {risk} pts"
            assert alert.stop_loss <= 202.0, (
                f"Stop loss should be ~₹198 (not ₹210), got {alert.stop_loss}"
            )


class TestAlertEvaluatorRunwayCutoff:
    """Verifies that intraday runway extension is strictly capped before 15:15 IST."""

    def test_afternoon_runway_capped_by_session_close(self, monkeypatch):
        """Intraday alert created at 14:45 IST has only 30 mins before 15:15 IST cutoff."""
        alert = MagicMock(spec=AutoAlert)
        alert.alert_type = "INDEX_CALL_SETUP"
        alert.option_type = "CE"
        alert.symbol = "BANKNIFTY"
        alert.contract_symbol = "BANKNIFTY55900CE"
        alert.created_at = "2026-10-15 14:45:00 IST"
        alert.triggered_at = "2026-10-15 14:45:00 IST"
        alert.time_horizon = "INTRADAY"
        alert.exchange = "NSE"
        alert.expiry_date = None
        alert.stage = "IGNITED"
        alert.direction = "BULLISH"
        alert.entry_price = 100.0
        alert.stop_loss = 90.0
        alert.target_level = 120.0
        alert.trigger_level = 100.0
        alert.target_status = "PENDING"
        alert.achieved_milestones = []
        alert.is_live = False
        alert.environment = "TEST"
        alert.underlying_spot = 55800.0
        alert.vwap = 55750.0
        alert.strike = 55900.0
        alert.trailing_stop = None
        alert.is_invalidated = False
        alert.ltp = 100.0
        alert.option_premium = 100.0
        alert.initial_stop_loss = 90.0
        alert.initial_entry_premium = 100.0
        alert.confidence = 75
        alert.confidence_score = 75
        alert.hedged_spread = None
        alert.metrics = {
            "is_trend_day": True,
            "vwap": 55750.0,
        }
        alert.actionable_plan = {"fast_scalp": {"time_stop_mins": 45.0}}

        # Evaluate at 15:05 IST (20 mins elapsed)
        eval_dt = datetime(2026, 10, 15, 15, 5, 0, tzinfo=IST)

        class MockDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return eval_dt

        monkeypatch.setattr("engine.alert_evaluator.datetime", MockDateTime)

        res = evaluate_alert_targets_and_trailing(
            alert,
            current_ltp=98.0,  # -2% pnl, structure intact, coiling
        )

        assert res is not None
        assert res.new_milestone == "COMPRESS_STALL_RISK"
        # Runway should mention 30m, NOT 60m or 112m!
        assert "30m" in res.trailing_rationale


class TestIndexCandleWickAndExhaustionRCA:
    """Tests Camarilla H5/L5 exhaustion, terminal ADR exhaustion, and candle rejection wicks."""

    def test_call_setup_suppressed_at_camarilla_h5(self):
        chain = _build_mock_chain(
            base_strike=55800.0, step=100.0, spot=55950.0, max_call_strike=57000.0
        )
        ref_dt = datetime(2026, 10, 15, 11, 0, 0, tzinfo=IST)
        mock_dl = MagicMock()
        mock_dl.camarilla = {"h5": 55950.0, "h4": 55800.0}
        mock_dl.atr_14 = 400.0

        with patch("engine.daily_levels.get_daily_levels", return_value=mock_dl):
            alerts = detect_index_call_setup(
                underlying="BANKNIFTY",
                spot=55950.0,
                chain=chain,
                vwap=55700.0,
                day_high=55950.0,
                day_low=55400.0,
                ref_time=ref_dt,
                ignore_time_gate=True,
            )
        assert len(alerts) == 0, "Expected call setup suppressed at Camarilla H5 exhaustion"

    def test_put_setup_suppressed_at_camarilla_l5(self):
        chain = _build_mock_chain(
            base_strike=55800.0, step=100.0, spot=55100.0, max_call_strike=57000.0
        )
        ref_dt = datetime(2026, 10, 15, 11, 0, 0, tzinfo=IST)
        mock_dl = MagicMock()
        mock_dl.camarilla = {"l5": 55100.0, "l4": 55300.0}
        mock_dl.atr_14 = 400.0

        with patch("engine.daily_levels.get_daily_levels", return_value=mock_dl):
            alerts = detect_index_put_setup(
                underlying="BANKNIFTY",
                spot=55100.0,
                chain=chain,
                vwap=55400.0,
                day_high=55800.0,
                day_low=55100.0,
                ref_time=ref_dt,
                ignore_time_gate=True,
            )
        assert len(alerts) == 0, "Expected put setup suppressed at Camarilla L5 exhaustion"

    def test_call_setup_suppressed_on_shooting_star_wick(self):
        import pandas as pd

        chain = _build_mock_chain(
            base_strike=55800.0, step=100.0, spot=55820.0, max_call_strike=57000.0
        )
        ref_dt = datetime(2026, 10, 15, 11, 0, 0, tzinfo=IST)
        # 5m bar with huge upper wick: open 55800, high 55920, low 55790, close 55810 (range 130, upper wick 110 = 85%)
        df_5m = pd.DataFrame(
            [
                {"open": 55700, "high": 55750, "low": 55690, "close": 55740, "volume": 1000},
                {"open": 55800, "high": 55920, "low": 55790, "close": 55810, "volume": 5000},
            ]
        )
        mock_dl = MagicMock()
        mock_dl.camarilla = {"h5": 56500.0, "h4": 55800.0}
        mock_dl.atr_14 = 500.0

        with patch("engine.daily_levels.get_daily_levels", return_value=mock_dl):
            alerts = detect_index_call_setup(
                underlying="BANKNIFTY",
                spot=55820.0,
                chain=chain,
                vwap=55750.0,
                day_high=55920.0,
                day_low=55500.0,
                ohlcv_5m=df_5m,
                ref_time=ref_dt,
                ignore_time_gate=True,
            )
        assert len(alerts) == 0, (
            "Expected call breakout suppressed on shooting star upper rejection wick"
        )


class TestCoherenceGateRapidCascadeThrottle:
    """Verifies that coherence_gate blocks unhedged index alerts fired within 5 minutes of an existing un-derisked index alert."""

    def test_rapid_cascade_throttle_blocks_second_naked_call(self):
        from datetime import timezone
        from engine.pipeline.coherence_gate import coherence_gate

        now_dt = datetime.now(timezone.utc)
        alert1 = AutoAlert(
            alert_id="aa-call-banknifty-1",
            alert_type="INDEX_CALL_SETUP",
            stage="IGNITED",
            symbol="NSE:BANKNIFTY",
            exchange="NFO",
            direction="BULLISH",
            headline="BANKNIFTY Long Call",
            summary="Bank Nifty Breakout",
            ltp=250.0,
            trigger_level=250.0,
            target_level=350.0,
            stop_loss=200.0,
            confidence=85,
            is_invalidated=False,
            created_at=now_dt.isoformat(),
        )
        alert1.achieved_milestones = []

        # Alert 2 fired on NIFTY in the same direction
        alert2 = AutoAlert(
            alert_id="aa-call-nifty-2",
            alert_type="INDEX_CALL_SETUP",
            stage="IGNITED",
            symbol="NSE:NIFTY",
            exchange="NFO",
            direction="BULLISH",
            headline="NIFTY Long Call",
            summary="Nifty Breakout",
            ltp=120.0,
            trigger_level=120.0,
            target_level=160.0,
            stop_loss=100.0,
            confidence=85,
            is_invalidated=False,
            created_at=now_dt.isoformat(),
        )

        is_allowed, reason = coherence_gate.validate_multi_index_coherence(alert2, [alert1])
        assert is_allowed is False
        assert "Rapid Benchmark Cascade Throttle" in reason


class Test0DteAfternoonTrailingRatchet:
    """Verifies that on 0-DTE afternoons (>= 13:30 IST), reaching T1 ratchets SL to +0.5R locked profit."""

    def test_0dte_afternoon_t1_locks_half_r_profit(self, monkeypatch):
        from engine.alert_evaluator import evaluate_alert_targets_and_trailing

        alert = AutoAlert(
            alert_id="aa-call-bn-0dte-1",
            alert_type="INDEX_CALL_SETUP",
            stage="IGNITED",
            symbol="BANKNIFTY",
            exchange="NFO",
            direction="BULLISH",
            headline="BANKNIFTY 55800 CE",
            summary="Bank Nifty Call",
            ltp=100.0,
            trigger_level=100.0,
            target_level=200.0,
            stop_loss=80.0,
            confidence=85,
            is_invalidated=False,
            created_at=datetime(2026, 10, 15, 13, 0, 0, tzinfo=IST).isoformat(),
        )
        alert.option_type = "CE"
        alert.contract_symbol = "BANKNIFTY55800CE"
        alert.strike = 55800.0
        alert.initial_entry_premium = 100.0
        alert.initial_stop_loss = 80.0  # risk = 20 pts
        alert.achieved_milestones = []
        alert.metrics = {"is_0dte": True}
        alert.expiry_date = "2026-10-15"

        # Mock current time to 14:00 IST on 2026-10-15
        eval_dt = datetime(2026, 10, 15, 14, 0, 0, tzinfo=IST)

        class MockDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return eval_dt

        monkeypatch.setattr("engine.alert_evaluator.datetime", MockDateTime)

        # Price hits T1 at 140 (+2R)
        res = evaluate_alert_targets_and_trailing(alert, current_ltp=140.0)
        assert res is not None
        assert res.new_milestone == "T1_ACHIEVED"
        # Since initial_risk = 20 pts, +0.5R lock means SL = 100 + (20 * 0.5) = 110.0!
        assert res.recommended_stop == 110.0
        assert res.locked_profit_pts == 10.0
        assert "LOCKED +0.5R PROFIT" in res.trailing_rationale


class TestIndexCvdAndSyntheticSpotSlRCA:
    """Verifies Order Flow CVD Absorption/Exhaustion Gates and Synthetic Spot SL on Index Setups."""

    def test_call_setup_suppressed_on_bearish_cvd_exhaustion(self, monkeypatch):
        """When 5m CVD shows bearish exhaustion (passive sellers absorbing buyers), breakout CE is suppressed."""
        from engine.detectors.index_call_setup import detect_index_call_setup

        mock_cvd = {
            "is_bearish_exhaustion": True,
            "is_bullish_absorption": False,
            "cvd_divergence_ratio": 0.40,
            "current_cvd": -5000.0,
        }
        monkeypatch.setattr(
            "engine.detectors.order_flow.compute_order_flow_cvd_divergence",
            lambda df, p: mock_cvd,
        )

        # Create dummy 5m ohlcv with 15 bars
        times = pd.date_range("2026-10-15 09:15", periods=15, freq="5min", tz=IST)
        df_5m = pd.DataFrame(
            {
                "open": [55500.0 + i * 20 for i in range(15)],
                "high": [55520.0 + i * 20 for i in range(15)],
                "low": [55490.0 + i * 20 for i in range(15)],
                "close": [55515.0 + i * 20 for i in range(15)],
                "volume": [1000.0] * 15,
            },
            index=times,
        )

        mock_contract = MagicMock(
            strike=55800.0,
            option_type="CE",
            last_price=120.0,
            volume=50000,
            oi=200000,
            delta=0.55,
            gamma=0.001,
            symbol="BANKNIFTY55800CE",
        )

        alerts = detect_index_call_setup(
            underlying="BANKNIFTY",
            spot=55800.0,
            chain=[mock_contract],
            vwap=55750.0,
            day_high=55800.0,
            day_low=55400.0,
            prev_day_high=55600.0,
            prev_day_low=55200.0,
            ohlcv_5m=df_5m,
            ignore_time_gate=True,
            ref_time=datetime(2026, 10, 15, 10, 30, tzinfo=IST),
        )

        # Breakout setups like DAY_HIGH_BREAKOUT or CAMARILLA_H4_BREAKOUT must be vetoed
        breakout_types = {"DAY_HIGH_BREAKOUT", "CAMARILLA_H4_BREAKOUT", "VWAP_BREAKOUT"}
        for a in alerts:
            for s in a.metrics.get("signals", []):
                assert s not in breakout_types

    def test_call_setup_attaches_structural_spot_sl(self):
        """Index Call setup must compute and attach structural spot stop loss."""
        from engine.detectors.index_call_setup import detect_index_call_setup

        mock_contract = MagicMock(
            strike=55800.0,
            option_type="CE",
            last_price=120.0,
            volume=50000,
            oi=200000,
            delta=0.55,
            gamma=0.001,
            symbol="BANKNIFTY55800CE",
        )

        alerts = detect_index_call_setup(
            underlying="BANKNIFTY",
            spot=55800.0,
            chain=[mock_contract],
            vwap=55750.0,
            day_high=55850.0,
            day_low=55600.0,
            prev_day_high=55700.0,
            prev_day_low=55300.0,
            ignore_time_gate=True,
            ref_time=datetime(2026, 10, 15, 10, 30, tzinfo=IST),
        )

        if alerts:
            alert = alerts[0]
            assert alert.structural_spot_sl is not None
            assert alert.metrics.get("spot_invalidation_anchor") is not None
            assert alert.actionable_plan.get("structural_spot_sl") is not None
            # Invalidation anchor must be below spot (55,800) and within realistic index coordinate
            assert alert.structural_spot_sl < 55800.0
            assert alert.structural_spot_sl > 55000.0
