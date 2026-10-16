"""
tests/test_sector_governance_and_session_timing.py
──────────────────────────────────────────────────
Deterministic unit tests verifying institutional signal governance:
1. Telegram Sector Push Governance:
   - Index F&O: Unrestricted throughput (no sector burst limit).
   - Stock F&O: Max 3 alerts per sector per hour.
   - Stock Equity (Cash): Max 5 alerts per sector per hour.
   - Lifecycle Milestones: 100% exempt from sector burst caps.
2. Intraday Option Entry Timing Window:
   - 14:00:00 IST Entry Cutoff for standard intraday options.
   - 13:45:00 IST Entry Cutoff for 0-DTE options.
   - 09:16:00 IST Pre-market opening auction lockout.
   - In-flight milestones, cash swing, hedged spreads, and MCX commodities exempt.
3. Call Wall & Put Wall Proximity Traps:
   - Proximity <= 0.15% to Call Wall with active writers: suppressed.
   - Proximity <= 0.15% to Put Wall with active writers: suppressed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine
from engine.pipeline.coherence_gate import CoherenceGate

IST = ZoneInfo("Asia/Kolkata")


def make_alert(
    symbol: str = "NIFTY",
    alert_type: str = "GAMMA_BLAST",
    stage: str = "IGNITED",
    direction: str = "BULLISH",
    ltp: float = 25000.0,
    trigger_level: float = 25000.0,
    stop_loss: float = 24950.0,
    target_level: float = 25150.0,
    segment: str = "FNO_INDEX",
    sector: str = "INDEX",
    confidence: int = 85,
    metrics: dict[str, Any] | None = None,
    actionable_plan: dict[str, Any] | None = None,
    achieved_milestones: list[str] | None = None,
    headline: str = "Headline",
    summary: str = "Summary",
    alert_id: str | None = None,
) -> AutoAlert:
    m = dict(metrics or {})
    if sector:
        m["sector"] = sector
    p = dict(actionable_plan or {})
    aid = alert_id or f"test-{symbol}-{alert_type}"
    return AutoAlert(
        alert_id=aid,
        alert_type=alert_type,
        stage=stage,
        symbol=symbol,
        exchange="NSE",
        direction=direction,
        headline=headline,
        summary=summary,
        ltp=ltp,
        trigger_level=trigger_level,
        target_level=target_level,
        stop_loss=stop_loss,
        confidence=confidence,
        segment=segment,
        metrics=m,
        actionable_plan=p,
        achieved_milestones=achieved_milestones or [],
    )


# ── 1. Telegram Sector Governance Tests ──────────────────────────────


class TestTelegramSectorGovernance:
    """Verifies calibrated Telegram sector pacing rules."""

    @pytest.fixture
    def engine(self):
        eng = AutoAlertEngine()
        eng._running = False
        eng._alerts = []
        eng._sector_hourly_telegram = {}
        return eng

    def test_index_fno_bypasses_sector_limit(self, engine):
        """Index F&O setups have zero sector limits and bypass pacing."""
        now = datetime(2026, 10, 15, 10, 0, tzinfo=IST)

        for i in range(10):
            alert = make_alert(
                symbol="NIFTY",
                alert_type="GAMMA_BLAST",
                segment="FNO_INDEX",
                sector="INDEX",
                confidence=90,
                alert_id=f"idx-{i}",
                actionable_plan={"action": "BUY_CALL"},
            )
            should_dispatch, reason = engine._eval_telegram_apex_gate(alert, now_ts=now.timestamp())
            assert should_dispatch is True, f"Alert {i} failed: {reason}"
            # Record sector pacing
            engine._sector_hourly_telegram.setdefault("index", []).append(now.timestamp())

    def test_stock_fno_capped_at_3_per_sector_per_hour(self, engine):
        """Stock F&O alerts are capped at max 3 per sector per hour."""
        now = datetime(2026, 10, 15, 10, 0, tzinfo=IST)
        t = now.timestamp()
        sector_name = "banking"
        symbols = ["HDFCBANK", "ICICIBANK", "AXISBANK", "KOTAKBANK"]

        for i, sym in enumerate(symbols[:3]):
            alert = make_alert(
                symbol=sym,
                alert_type="THEMATIC_SYMPATHY_IGNITION",
                segment="FNO_STK",
                sector=sector_name,
                confidence=90,
                alert_id=f"fno-{sym}",
                actionable_plan={"action": "BUY_CALL"},
            )
            should_dispatch, reason = engine._eval_telegram_apex_gate(alert, now_ts=t + i * 60)
            assert should_dispatch is True, f"Alert {i} for {sym} failed: {reason}"
            # Record under fno:<sector>
            engine._sector_hourly_telegram.setdefault(f"fno:{sector_name}", []).append(t + i * 60)

        # 4th Stock F&O alert in same sector within 60 minutes must be held
        alert_4 = make_alert(
            symbol="KOTAKBANK",
            alert_type="THEMATIC_SYMPATHY_IGNITION",
            segment="FNO_STK",
            sector=sector_name,
            confidence=90,
            alert_id="fno-KOTAKBANK",
            actionable_plan={"action": "BUY_CALL"},
        )
        should_dispatch, reason = engine._eval_telegram_apex_gate(alert_4, now_ts=t + 200)
        assert should_dispatch is False
        assert "sector hourly limit reached" in reason

    def test_stock_cash_equity_capped_at_5_per_sector_per_hour(self, engine):
        """Cash equity alerts are capped at max 5 per sector per hour."""
        now = datetime(2026, 10, 15, 10, 0, tzinfo=IST)
        t = now.timestamp()
        sector_name = "it"

        for i, sym in enumerate(["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM"]):
            alert = make_alert(
                symbol=sym,
                alert_type="MOMENTUM_RUNNER",
                segment="EQUITY",
                sector=sector_name,
                confidence=90,
                alert_id=f"eq-{sym}",
                actionable_plan={"action": "BUY"},
            )
            should_dispatch, reason = engine._eval_telegram_apex_gate(alert, now_ts=t + i * 30)
            assert should_dispatch is True, f"Cash alert {i} failed: {reason}"
            engine._sector_hourly_telegram.setdefault(f"eq:{sector_name}", []).append(t + i * 30)

        # 6th Cash Equity alert in same sector within 60 minutes must be held
        alert_6 = make_alert(
            symbol="LTIM",
            alert_type="MOMENTUM_RUNNER",
            segment="EQUITY",
            sector=sector_name,
            confidence=90,
            alert_id="eq-LTIM",
            actionable_plan={"action": "BUY"},
        )
        should_dispatch, reason = engine._eval_telegram_apex_gate(alert_6, now_ts=t + 200)
        assert should_dispatch is False
        assert "sector hourly limit reached" in reason

    def test_milestone_updates_bypass_sector_caps(self, engine):
        """In-flight lifecycle milestones always bypass sector pacing."""
        now = datetime(2026, 10, 15, 10, 0, tzinfo=IST)
        t = now.timestamp()
        sector_name = "auto"

        # Saturate sector burst history with 10 timestamps
        engine._sector_hourly_telegram[f"fno:{sector_name}"] = [t - 100 + i for i in range(10)]

        # In-flight milestone alert
        alert = make_alert(
            symbol="TATAMOTORS",
            alert_type="THEMATIC_SYMPATHY_IGNITION",
            segment="FNO_STK",
            sector=sector_name,
            confidence=90,
            stage="TARGET_1",
            achieved_milestones=["T1_ACHIEVED"],
        )
        should_dispatch, reason = engine._eval_telegram_apex_gate(alert, now_ts=t + 10)
        assert should_dispatch is True


# ── 2. Session Entry Timing & Cutoff Gate Tests ───────────────────────


class TestSessionEntryTimingGate:
    """Verifies 14:00 IST option cutoff, 13:45 0-DTE cutoff, and 09:16 AM opening lockout."""

    def test_intraday_option_cutoff_at_1400_rejected(self):
        """Standard intraday option buy at 14:05 IST is rejected."""
        gate = CoherenceGate()
        alert = make_alert(
            symbol="NIFTY",
            alert_type="INDEX_CALL_SETUP",
            segment="FNO_INDEX",
            stage="IGNITED",
            metrics={"is_0dte": False},
            actionable_plan={"action": "BUY_CALL", "option_type": "CE"},
        )
        eval_dt = datetime(2026, 10, 15, 14, 5, 0, tzinfo=IST)
        is_allowed, reason = gate.validate_session_entry_window(alert, ref_dt=eval_dt)
        assert is_allowed is False
        assert "Terminal Session Cutoff" in reason
        assert "14:00 IST" in reason

    def test_0dte_option_cutoff_at_1345_rejected(self):
        """0-DTE option buy at 13:50 IST is rejected."""
        gate = CoherenceGate()
        alert = make_alert(
            symbol="NIFTY",
            alert_type="GAMMA_BLAST",
            segment="FNO_INDEX",
            stage="IGNITED",
            metrics={"is_0dte": True},
            actionable_plan={"action": "BUY_CALL", "option_type": "CE"},
        )
        eval_dt = datetime(2026, 10, 15, 13, 50, 0, tzinfo=IST)
        is_allowed, reason = gate.validate_session_entry_window(alert, ref_dt=eval_dt)
        assert is_allowed is False
        assert "Terminal Session Cutoff" in reason
        assert "13:45 IST" in reason
        assert "0-DTE Expiry" in reason

    def test_option_entry_before_cutoff_accepted(self):
        """Intraday option buy at 13:30 IST is accepted."""
        gate = CoherenceGate()
        alert = make_alert(
            symbol="BANKNIFTY",
            alert_type="INDEX_CALL_SETUP",
            segment="FNO_INDEX",
            stage="IGNITED",
            metrics={"is_0dte": False},
            actionable_plan={"action": "BUY_CALL", "option_type": "CE"},
        )
        eval_dt = datetime(2026, 10, 15, 13, 30, 0, tzinfo=IST)
        is_allowed, reason = gate.validate_session_entry_window(alert, ref_dt=eval_dt)
        assert is_allowed is True
        assert "Within allowable" in reason

    def test_pre_0916_opening_lockout_rejected(self):
        """Option setup triggering before 09:16:00 IST opening discovery is locked out."""
        gate = CoherenceGate()
        alert = make_alert(
            symbol="NIFTY",
            alert_type="INDEX_CALL_SETUP",
            segment="FNO_INDEX",
            stage="IGNITED",
            actionable_plan={"action": "BUY_CALL", "option_type": "CE"},
        )
        eval_dt = datetime(2026, 10, 15, 9, 15, 30, tzinfo=IST)
        is_allowed, reason = gate.validate_session_entry_window(alert, ref_dt=eval_dt)
        assert is_allowed is False
        assert "Opening Lockout" in reason
        assert "pre-09:16 IST" in reason

    def test_in_flight_milestone_at_1430_accepted(self):
        """In-flight milestone updates after 14:00 IST are 100% accepted."""
        gate = CoherenceGate()
        alert = make_alert(
            symbol="NIFTY",
            alert_type="GAMMA_BLAST",
            segment="FNO_INDEX",
            stage="TARGET_1",
            achieved_milestones=["T1_ACHIEVED"],
            actionable_plan={"action": "BUY_CALL", "option_type": "CE"},
        )
        eval_dt = datetime(2026, 10, 15, 14, 30, 0, tzinfo=IST)
        is_allowed, reason = gate.validate_session_entry_window(alert, ref_dt=eval_dt)
        assert is_allowed is True
        assert "In-flight milestone/lifecycle update" in reason

    def test_cash_equity_swing_after_1400_accepted(self):
        """Cash equity setups after 14:00 IST are exempt from option cutoff."""
        gate = CoherenceGate()
        alert = make_alert(
            symbol="RELIANCE",
            alert_type="MOMENTUM_RUNNER",
            segment="EQUITY",
            stage="IGNITED",
            actionable_plan={"action": "BUY"},
        )
        eval_dt = datetime(2026, 10, 15, 14, 15, 0, tzinfo=IST)
        is_allowed, reason = gate.validate_session_entry_window(alert, ref_dt=eval_dt)
        assert is_allowed is True
        assert "Cash equity / non-option setup" in reason

    def test_hedged_spread_after_1400_accepted(self):
        """Defined-risk hedged spreads after 14:00 IST are exempt."""
        gate = CoherenceGate()
        alert = make_alert(
            symbol="NIFTY",
            alert_type="GAMMA_BLAST",
            segment="FNO_INDEX",
            stage="IGNITED",
            headline="NIFTY BULL CALL SPREAD",
            actionable_plan={
                "action": "BULL_CALL_SPREAD",
                "hedge_plan": {"long_strike": 25000, "short_strike": 25200},
            },
        )
        eval_dt = datetime(2026, 10, 15, 14, 15, 0, tzinfo=IST)
        is_allowed, reason = gate.validate_session_entry_window(alert, ref_dt=eval_dt)
        assert is_allowed is True
        assert "Defined-risk hedged spread" in reason


# ── 3. Call Wall & Put Wall Proximity Trap Tests ──────────────────────


class TestWallProximityTraps:
    """Verifies that setups within <= 0.15% of Call/Put Walls with active writers are suppressed."""

    def test_index_call_within_015_call_wall_suppressed(self):
        """detect_index_call_setup suppresses when spot is within 0.15% of Call Wall with writers adding."""
        from engine.detectors.index_call_setup import detect_index_call_setup

        class MockContract:
            def __init__(self, strike, opt_type, lp, oi, oi_chg, vol):
                self.strike = strike
                self.option_type = opt_type
                self.last_price = lp
                self.oi = oi
                self.oi_change = oi_chg
                self.volume = vol
                self.pchange = 10.0
                self.expiry_date = "2026-10-22"

        # Spot at 25,000; Call Wall at 25,030 (distance = 30 / 25000 = 0.12% <= 0.15%)
        # Call writers actively adding (oi_change = +15,000)
        chain = [
            MockContract(25000, "CE", 100.0, 10000, 2000, 5000),
            MockContract(25030, "CE", 80.0, 50000, 15000, 8000),  # Max Call OI Wall
            MockContract(25000, "PE", 90.0, 10000, 1000, 5000),
        ]

        ref_time = datetime(2026, 10, 15, 10, 30, tzinfo=IST)
        res = detect_index_call_setup(
            underlying="NIFTY",
            spot=25000.0,
            chain=chain,
            vwap=24980.0,
            ref_time=ref_time,
            ignore_time_gate=True,
        )
        assert len(res) == 0, "Expected severe Call Wall trap suppression"

    def test_index_put_within_015_put_wall_suppressed(self):
        """detect_index_put_setup suppresses when spot is within 0.15% of Put Wall with writers adding."""
        from engine.detectors.index_put_setup import detect_index_put_setup

        class MockContract:
            def __init__(self, strike, opt_type, lp, oi, oi_chg, vol):
                self.strike = strike
                self.option_type = opt_type
                self.last_price = lp
                self.oi = oi
                self.oi_change = oi_chg
                self.volume = vol
                self.pchange = 10.0
                self.expiry_date = "2026-10-22"

        # Spot at 25,000; Put Wall at 24,970 (distance = 30 / 25000 = 0.12% <= 0.15%)
        # Put writers actively adding (oi_change = +20,000)
        chain = [
            MockContract(25000, "PE", 100.0, 10000, 2000, 5000),
            MockContract(24970, "PE", 80.0, 60000, 20000, 8000),  # Max Put OI Wall
            MockContract(25000, "CE", 90.0, 10000, 1000, 5000),
        ]

        ref_time = datetime(2026, 10, 15, 10, 30, tzinfo=IST)
        res = detect_index_put_setup(
            underlying="NIFTY",
            spot=25000.0,
            chain=chain,
            vwap=25020.0,
            ref_time=ref_time,
            ignore_time_gate=True,
        )
        assert len(res) == 0, "Expected severe Put Wall trap suppression"
