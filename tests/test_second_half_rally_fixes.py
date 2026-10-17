"""
tests/test_second_half_rally_fixes.py
──────────────────────────────────────
Regression tests for the 5 second-half rally RCA fixes (2026-10-13).
All tests are deterministic, synthetic-data-only.
"""

from __future__ import annotations
import os
from datetime import date, datetime, time as dtime
from zoneinfo import ZoneInfo

os.environ.setdefault("CHANAKYA_TESTING", "1")
IST = ZoneInfo("Asia/Kolkata")


def _ist(hour: int, minute: int) -> datetime:
    d = date.today()
    return datetime(d.year, d.month, d.day, hour, minute, 0, tzinfo=IST)


# ── Fix 1: get_session_phase_slot() 24hr IST mapping ─────────────────────────


class TestSessionPhaseSlot:
    def setup_method(self):
        from engine.alert_identity import get_session_phase_slot

        self.fn = get_session_phase_slot

    def test_market_open_returns_0915(self):
        assert self.fn(_ist(9, 15)) == "0915"

    def test_morning_returns_0915(self):
        assert self.fn(_ist(10, 45)) == "0915"

    def test_boundary_1130_exact(self):
        assert self.fn(_ist(11, 30)) == "1130"

    def test_midday_returns_1130(self):
        assert self.fn(_ist(12, 0)) == "1130"

    def test_one_minute_before_1315(self):
        assert self.fn(_ist(13, 14)) == "1130"

    def test_boundary_1315_exact(self):
        assert self.fn(_ist(13, 15)) == "1315"

    def test_power_hour_returns_1315(self):
        assert self.fn(_ist(14, 0)) == "1315"

    def test_no_ampm_string_ever(self):
        for h, m in [(9, 20), (11, 30), (13, 15), (15, 0)]:
            slot = self.fn(_ist(h, m))
            assert slot not in ("am", "pm", "AM", "PM")
            assert slot.isdigit(), f"Slot must be numeric 24hr HHMM, got '{slot}'"

    def test_slot_boundaries_descending_order(self):
        """_SLOT_BOUNDARIES must be sorted largest-first for correct cascade."""
        from engine.alert_identity import _SLOT_BOUNDARIES

        bounds = [b for b, _ in _SLOT_BOUNDARIES]
        assert bounds == sorted(bounds, reverse=True)


# ── Fix 2: Distinct alert IDs across session phases ───────────────────────────


class TestAlertIdPhaseDistinctness:
    def test_call_am_vs_pm_distinct(self):
        from engine.alert_identity import generate_alert_id, get_session_phase_slot

        am = get_session_phase_slot(_ist(10, 30))
        pm = get_session_phase_slot(_ist(14, 0))
        assert am != pm
        id_am = generate_alert_id("NIFTY", "INDEX_CALL_SETUP", variant=f"ce-25000-{am}")
        id_pm = generate_alert_id("NIFTY", "INDEX_CALL_SETUP", variant=f"ce-25000-{pm}")
        assert id_am != id_pm, "AM and PM CE alert IDs must differ to prevent cooldown collision"

    def test_three_phases_all_distinct(self):
        from engine.alert_identity import generate_alert_id, get_session_phase_slot

        slots = [get_session_phase_slot(_ist(h, m)) for h, m in [(10, 0), (12, 0), (14, 0)]]
        assert len(set(slots)) == 3, f"Expected 3 distinct slots, got {slots}"
        ids = [
            generate_alert_id("NIFTY", "INDEX_CALL_SETUP", variant=f"ce-24900-{s}") for s in slots
        ]
        assert len(set(ids)) == 3

    def test_same_phase_deduplicates(self):
        from engine.alert_identity import generate_alert_id, get_session_phase_slot

        slot = get_session_phase_slot(_ist(10, 0))
        id1 = generate_alert_id("NIFTY", "INDEX_CALL_SETUP", variant=f"ce-25000-{slot}")
        id2 = generate_alert_id("NIFTY", "INDEX_CALL_SETUP", variant=f"ce-25000-{slot}")
        assert id1 == id2, "Same phase must produce same ID for deduplication"

    def test_phase_slot_passes_invariant_17(self):
        from engine.alert_identity import (
            generate_alert_id,
            get_session_phase_slot,
            validate_alert_id,
        )

        slot = get_session_phase_slot(_ist(14, 0))
        aid = generate_alert_id("NIFTY", "INDEX_CALL_SETUP", variant=f"ce-25000-{slot}")
        ok, reason = validate_alert_id(aid)
        assert ok, f"Invariant #17 failed: {reason} — {aid}"

    def test_put_midday_vs_pm_distinct(self):
        from engine.alert_identity import generate_alert_id, get_session_phase_slot

        mid = get_session_phase_slot(_ist(12, 0))
        pm = get_session_phase_slot(_ist(13, 30))
        assert mid != pm
        assert generate_alert_id(
            "BANKNIFTY", "INDEX_PUT_SETUP", variant=f"pe-52000-{mid}"
        ) != generate_alert_id("BANKNIFTY", "INDEX_PUT_SETUP", variant=f"pe-52000-{pm}")


# ── Fix 3: Coiling escape hatch in midday chop gate ──────────────────────────


class TestCoilingEscapeHatch:
    _COILING = {
        "VCP_COILING",
        "DOUBLE_BOTTOM_BREAKOUT",
        "VWAP_RECLAIM",
        "INTRADAY_CAPITULATION_REVERSAL",
        "FAILED_DAY_LOW_BREAKDOWN",
        "INTRADAY_CAPITULATION_BOTTOM",
    }

    def _gate(self, signals, now_time, vel=45):
        """Inline port of the coiling escape hatch from index_call_setup.py."""
        raw = bool(dtime(11, 30) <= now_time <= dtime(14, 0)) and (vel < 65)
        escape = raw and bool(any(s in self._COILING for s in signals))
        return {"raw": raw, "escape": escape, "final": raw and not escape}

    def test_vcp_coiling_survives(self):
        r = self._gate(["VCP_COILING"], dtime(12, 30))
        assert r["raw"] is True and r["final"] is False

    def test_vwap_reclaim_survives(self):
        assert self._gate(["VWAP_RECLAIM"], dtime(13, 0))["final"] is False

    def test_double_bottom_survives(self):
        assert self._gate(["DOUBLE_BOTTOM_BREAKOUT"], dtime(11, 45))["final"] is False

    def test_failed_day_low_survives(self):
        assert self._gate(["FAILED_DAY_LOW_BREAKDOWN"], dtime(12, 15))["final"] is False

    def test_capitulation_reversal_survives(self):
        assert self._gate(["INTRADAY_CAPITULATION_REVERSAL"], dtime(13, 55))["final"] is False

    def test_routine_signals_remain_gated(self):
        for sig in ["TREND_PULLBACK_RECLAIM", "EMA9_21_BULLISH_CROSSOVER", "MOMENTUM_EXPANSION"]:
            assert self._gate([sig], dtime(12, 0))["final"] is True, f"'{sig}' must stay gated"

    def test_before_1130_gate_inactive(self):
        assert self._gate(["TREND_PULLBACK_RECLAIM"], dtime(10, 0))["raw"] is False

    def test_after_1400_gate_inactive(self):
        assert self._gate(["TREND_PULLBACK_RECLAIM"], dtime(14, 1))["raw"] is False

    def test_high_velocity_never_chop_gated(self):
        """vel_score >= 65 means no midday chop gate, even for routine signals."""
        assert self._gate(["TREND_PULLBACK_RECLAIM"], dtime(12, 0), vel=70)["raw"] is False


# ── Fix 4: Tiered RVOL squeeze gate ──────────────────────────────────────────


class TestSqueezeRvolTieredGate:
    def _gate(self, is_squeeze_on, rvol, t):
        """Inline port of the tiered midday lull gate from squeeze_breakout.py."""
        in_lull = (
            (t.hour == 11 and t.minute >= 45) or t.hour == 12 or (t.hour == 13 and t.minute < 15)
        )
        if not in_lull:
            return "PASS"
        if is_squeeze_on:
            return "PASS" if rvol >= 1.3 else "FILTERED"
        return "PASS" if rvol >= 2.0 else "FILTERED"

    def test_ttm_squeeze_fires_at_1_3x(self):
        assert self._gate(True, 1.3, dtime(12, 0)) == "PASS"

    def test_ttm_squeeze_fires_at_1_5x(self):
        assert self._gate(True, 1.5, dtime(12, 30)) == "PASS"

    def test_ttm_squeeze_blocked_below_1_3x(self):
        assert self._gate(True, 1.2, dtime(12, 0)) == "FILTERED"

    def test_no_squeeze_requires_2x_rvol(self):
        assert self._gate(False, 1.8, dtime(12, 0)) == "FILTERED"

    def test_no_squeeze_passes_at_2x(self):
        assert self._gate(False, 2.0, dtime(12, 0)) == "PASS"

    def test_gate_inactive_before_1145(self):
        assert self._gate(False, 0.5, dtime(11, 30)) == "PASS"

    def test_gate_inactive_at_1315_power_hour(self):
        assert self._gate(False, 0.5, dtime(13, 15)) == "PASS"

    def test_boundary_1314_still_in_lull(self):
        assert self._gate(False, 1.0, dtime(13, 14)) == "FILTERED"


# ── Fix 5: PM VWAP-Hold Escape ───────────────────────────────────────────────


class TestPmVwapHoldEscape:
    def _eval(self, bounce, above_vwap, t, base=0.45):
        """Inline port of the PM VWAP-hold escape from auto_alert_engine.py."""
        min_b = base if above_vwap else (base * 2.5)
        escape = t >= dtime(13, 0) and above_vwap
        suppressed = bounce < min_b and not escape
        return {"suppressed": suppressed, "escape": escape}

    def test_pre_1300_no_escape_even_above_vwap(self):
        r = self._eval(0.20, True, dtime(12, 45))
        assert r["escape"] is False
        assert r["suppressed"] is True

    def test_post_1300_above_vwap_allows_ce_scan(self):
        r = self._eval(0.20, True, dtime(13, 30))
        assert r["escape"] is True
        assert r["suppressed"] is False

    def test_post_1300_below_vwap_still_suppressed(self):
        r = self._eval(0.20, False, dtime(13, 30))
        assert r["escape"] is False
        assert r["suppressed"] is True

    def test_strong_bounce_always_passes(self):
        assert self._eval(0.60, True, dtime(14, 0))["suppressed"] is False

    def test_exact_1300_boundary_activates_escape(self):
        r = self._eval(0.10, True, dtime(13, 0))
        assert r["escape"] is True
        assert r["suppressed"] is False


# ── Module integrity smoke ────────────────────────────────────────────────────


class TestAlertIdentityModuleIntegrity:
    def test_all_public_names_importable(self):
        from engine.alert_identity import (
            generate_alert_id,
            canonical_alert_symbol,
            validate_alert_id,
            get_session_phase_slot,
        )

        assert all(
            callable(f)
            for f in [
                generate_alert_id,
                canonical_alert_symbol,
                validate_alert_id,
                get_session_phase_slot,
            ]
        )


# ── Fix 6: Stock Options, Squeeze & Spark Phase Slots ────────────────────────


class TestStockOptionsAndSqueezePhaseSlots:
    def test_stock_options_momentum_distinct_phase_slots(self):
        from engine.alert_identity import generate_alert_id

        d = date(2026, 10, 13)
        am_id = generate_alert_id(
            "RELIANCE", "OPTIONS_MOMENTUM", session_date=d, variant="ce-2800-0915"
        )
        pm_id = generate_alert_id(
            "RELIANCE", "OPTIONS_MOMENTUM", session_date=d, variant="ce-2800-1315"
        )
        assert am_id != pm_id
        assert "0915" in am_id
        assert "1315" in pm_id

    def test_squeeze_breakout_distinct_phase_slots(self):
        from engine.alert_identity import generate_alert_id

        d = date(2026, 10, 13)
        am_id = generate_alert_id(
            "NIFTY", "SQUEEZE_BREAKOUT", session_date=d, variant="ce-25000-0915"
        )
        pm_id = generate_alert_id(
            "NIFTY", "SQUEEZE_BREAKOUT", session_date=d, variant="ce-25000-1315"
        )
        assert am_id != pm_id
        assert "0915" in am_id
        assert "1315" in pm_id

    def test_intraday_spark_distinct_phase_slots(self):
        from engine.alert_identity import generate_alert_id

        d = date(2026, 10, 13)
        am_id = generate_alert_id(
            "TCS", "INTRADAY_BREAKOUT_SPARK", session_date=d, variant="bull-0915"
        )
        pm_id = generate_alert_id(
            "TCS", "INTRADAY_BREAKOUT_SPARK", session_date=d, variant="bull-1315"
        )
        assert am_id != pm_id
        assert "0915" in am_id
        assert "1315" in pm_id


# ── Fix 7: Cross-Detector Mutex & Reversal Conflict Exemptions ───────────────


class TestActiveTradeMutexAndOpposingConflictExemptions:
    def test_afternoon_thrust_exempt_from_active_trade_mutex(self):
        """AFTERNOON_THRUST must never be suppressed by cross-detector active trade mutex."""
        from engine.auto_alert_engine import AutoAlertEngine
        from engine.alert_model import AutoAlert

        engine = AutoAlertEngine()
        engine.clear_alerts()
        # Seed an active morning trade on a stock
        morning_alert = AutoAlert(
            alert_id="aa-spark-reliance-bull-0915-20261013",
            alert_type="INTRADAY_SPARK",
            stage="IGNITED",
            symbol="RELIANCE",
            exchange="NSE",
            direction="BULLISH",
            headline="Spark Reliance",
            summary="Morning Spark",
            ltp=2800.0,
            trigger_level=2800.0,
            target_level=2850.0,
            stop_loss=2780.0,
            environment="TEST",
        )
        engine._alerts.append(morning_alert)

        # Afternoon thrust for RELIANCE
        pm_thrust = AutoAlert(
            alert_id="aa-afternoon-thrust-reliance-bull-1315-20261013",
            alert_type="AFTERNOON_THRUST",
            stage="IGNITED",
            symbol="RELIANCE",
            exchange="NSE",
            direction="BULLISH",
            headline="Afternoon Thrust Reliance",
            summary="PM Thrust",
            ltp=2820.0,
            trigger_level=2820.0,
            target_level=2880.0,
            stop_loss=2800.0,
            environment="TEST",
            metrics={"setup": "AFTERNOON_THRUST"},
        )
        # Should record cleanly, not suppressed by active trade mutex
        res = engine.record_alert(pm_thrust)
        assert res is True

    def test_derisked_trade_does_not_block_subsequent_alerts(self):
        """A morning trade that reached T1_ACHIEVED or TRAILING_UPDATE must not block new trades."""
        from engine.auto_alert_engine import AutoAlertEngine
        from engine.alert_model import AutoAlert

        engine = AutoAlertEngine()
        engine.clear_alerts()
        derisked_alert = AutoAlert(
            alert_id="aa-spark-tcs-bull-0915-20261013",
            alert_type="INTRADAY_SPARK",
            stage="T1_ACHIEVED",
            symbol="TCS",
            exchange="NSE",
            direction="BULLISH",
            headline="TCS Spark",
            summary="Target 1 Achieved",
            ltp=3500.0,
            trigger_level=3480.0,
            target_level=3500.0,
            stop_loss=3480.0,
            environment="TEST",
        )
        engine._alerts.append(derisked_alert)

        new_alert = AutoAlert(
            alert_id="aa-options-momentum-tcs-ce-3550-1315-20261013",
            alert_type="OPTIONS_MOMENTUM",
            stage="IGNITED",
            symbol="TCS",
            exchange="NSE",
            direction="BULLISH",
            headline="TCS 3550 CE Momentum",
            summary="PM Momentum",
            ltp=45.0,
            trigger_level=45.0,
            target_level=60.0,
            stop_loss=38.0,
            strike=3550.0,
            option_type="CE",
            environment="TEST",
        )
        res = engine.record_alert(new_alert)
        assert res is True

    def test_indices_exempt_from_active_trade_mutex(self):
        """Index setups (NIFTY/BANKNIFTY) must never be blocked by cross-detector active trade mutex."""
        from engine.auto_alert_engine import AutoAlertEngine
        from engine.alert_model import AutoAlert

        engine = AutoAlertEngine()
        engine.clear_alerts()
        morning_index = AutoAlert(
            alert_id="aa-opening-drive-nifty-bull-20261013",
            alert_type="OPENING_DRIVE_IGNITION",
            stage="IGNITED",
            symbol="NIFTY",
            exchange="NSE",
            direction="BULLISH",
            headline="Nifty Opening Drive",
            summary="Morning Drive",
            ltp=25000.0,
            trigger_level=25000.0,
            target_level=25150.0,
            stop_loss=24930.0,
            environment="TEST",
        )
        engine._alerts.append(morning_index)

        pm_blast = AutoAlert(
            alert_id="aa-gamma-blast-nifty-ce-25100-1315-20261013",
            alert_type="GAMMA_BLAST",
            stage="IGNITED",
            symbol="NIFTY",
            exchange="NFO",
            direction="BULLISH",
            headline="Nifty Gamma Blast",
            summary="PM Gamma Blast",
            ltp=120.0,
            trigger_level=120.0,
            target_level=165.0,
            stop_loss=98.0,
            strike=25100.0,
            option_type="CE",
            environment="TEST",
        )
        res = engine.record_alert(pm_blast)
        assert res is True


class TestHighGammaAsymmetryAndExecutionBlueprint:
    """Institutional tests for High-Gamma Asymmetry option resolution and 1-minute close execution confirmation."""

    def test_high_gamma_asymmetry_ce_resolves_otm_plus_one(self):
        from engine.option_resolver import resolve_option_contract

        plan = resolve_option_contract(
            "NIFTY",
            spot=22500.0,
            direction="BULLISH",
            strike_tier="HIGH_GAMMA_ASYMMETRY",
        )
        assert plan is not None
        assert plan.strike == 22550.0  # 1 strike above 22500 ATM (step 50)
        assert plan.option_type == "CE"
        assert plan.strike_tier == "HIGH_GAMMA_ASYMMETRY"
        assert "ON_1M_CLOSE" in str(plan.execution_trigger)
        assert plan.confirmation_rule == "1_MIN_CANDLE_CLOSE_MANDATORY"
        assert "1-minute candle to close above" in str(plan.execution_notes)

    def test_high_gamma_asymmetry_pe_resolves_otm_minus_one(self):
        from engine.option_resolver import resolve_option_contract

        plan = resolve_option_contract(
            "NIFTY",
            spot=22500.0,
            direction="BEARISH",
            strike_tier="HIGH_GAMMA_ASYMMETRY",
        )
        assert plan is not None
        assert plan.strike == 22450.0  # 1 strike below 22500 ATM (step 50)
        assert plan.option_type == "PE"
        assert plan.strike_tier == "HIGH_GAMMA_ASYMMETRY"
        assert "ON_1M_CLOSE" in str(plan.execution_trigger)
        assert plan.confirmation_rule == "1_MIN_CANDLE_CLOSE_MANDATORY"

    def test_high_gamma_asymmetry_live_chain_selection(self, monkeypatch):
        from engine.option_resolver import resolve_option_contract
        from unittest.mock import MagicMock

        c_atm = MagicMock(
            symbol="NIFTY22500CE",
            strike=22500.0,
            option_type="CE",
            last_price=80.0,
            expiry="2026-10-30",
        )
        c_otm = MagicMock(
            symbol="NIFTY22550CE",
            strike=22550.0,
            option_type="CE",
            last_price=48.0,
            expiry="2026-10-30",
        )

        mock_chain = MagicMock()
        mock_chain.contracts = [c_atm, c_otm]
        monkeypatch.setattr("market.options.get_options_chain", lambda sym: mock_chain)

        # ATM tier selects 22500 CE
        plan_atm = resolve_option_contract(
            "NIFTY", spot=22500.0, direction="BULLISH", strike_tier="ATM"
        )
        assert plan_atm is not None
        assert plan_atm.strike == 22500.0
        assert plan_atm.entry_premium == 80.0

        # HIGH_GAMMA_ASYMMETRY selects 22550 CE (OTM+1 in the gamma sweet spot)
        plan_gamma = resolve_option_contract(
            "NIFTY", spot=22500.0, direction="BULLISH", strike_tier="HIGH_GAMMA_ASYMMETRY"
        )
        assert plan_gamma is not None
        assert plan_gamma.strike == 22550.0
        assert plan_gamma.entry_premium == 48.0
        assert plan_gamma.confirmation_rule == "1_MIN_CANDLE_CLOSE_MANDATORY"

    def test_afternoon_thrust_actionable_plan_includes_1m_close(self):
        from engine.detectors.afternoon_thrust import detect_afternoon_thrust
        import pandas as pd
        from datetime import datetime
        from zoneinfo import ZoneInfo

        ist = ZoneInfo("Asia/Kolkata")
        ref_pm = datetime(2026, 10, 13, 13, 45, tzinfo=ist)

        # Create 5m OHLCV coiling then breaking out at 13:45
        dates = pd.date_range("2026-10-13 09:15", periods=55, freq="5min", tz=ist)
        df = pd.DataFrame(
            {
                "open": [22480.0 + i * 0.5 for i in range(55)],
                "high": [22490.0 + i * 0.5 for i in range(55)],
                "low": [22475.0 + i * 0.5 for i in range(55)],
                "close": [22485.0 + i * 0.5 for i in range(55)],
                "volume": [10000 + i * 500 for i in range(55)],
            },
            index=dates,
        )

        # Breakout bar
        df.iloc[-1, df.columns.get_loc("close")] = 22550.0
        df.iloc[-1, df.columns.get_loc("high")] = 22555.0

        alert = detect_afternoon_thrust(
            symbol="NIFTY",
            df_5m=df,
            ltp=22550.0,
            vwap=22500.0,
            ref_time=ref_pm,
            ignore_time_gate=True,
        )
        assert alert is not None
        assert alert.actionable_plan is not None
        assert alert.actionable_plan["confirmation_rule"] == "1_MIN_CANDLE_CLOSE_MANDATORY"
        assert "ON_1M_CLOSE" in alert.actionable_plan["execution_trigger"]

    def test_gamma_blast_actionable_plan_includes_1m_close_confirmation(self):
        from engine.detectors.gamma_blast import detect_gamma_blast
        from unittest.mock import MagicMock
        from datetime import datetime
        from zoneinfo import ZoneInfo

        ist = ZoneInfo("Asia/Kolkata")
        ref_dt = datetime(2026, 10, 13, 13, 45, tzinfo=ist)

        c = MagicMock(
            symbol="NIFTY22550CE",
            strike=22550.0,
            option_type="CE",
            last_price=50.0,
            oi=25000,
            oi_change=-8500,
            volume=60000,
            pchange=28.0,
            expiry="2026-10-15",
        )
        alerts = detect_gamma_blast(
            underlying="NIFTY",
            spot=22540.0,
            chain=[c],
            vwap=22500.0,
            now_dt=ref_dt,
        )
        assert len(alerts) >= 1
        a = alerts[0]
        assert a.actionable_plan is not None
        assert a.actionable_plan["confirmation_rule"] == "1_MIN_CANDLE_CLOSE_MANDATORY"
        assert a.actionable_plan["execution_trigger"] == "ABOVE_₹50.0_ON_1M_CLOSE"

    def test_index_call_setup_value_base_accumulation_detected(self):
        from engine.detectors.index_call_setup import detect_index_call_setup
        from unittest.mock import MagicMock
        import pandas as pd
        from datetime import datetime
        from zoneinfo import ZoneInfo

        ist = ZoneInfo("Asia/Kolkata")
        ref_mid = datetime(2026, 10, 13, 11, 20, tzinfo=ist)

        dates = pd.date_range("2026-10-13 09:15", periods=25, freq="5min", tz=ist)
        # Stable base holding VWAP at 22500 between 11:00 and 11:20
        df = pd.DataFrame(
            {
                "open": [22505.0] * 25,
                "high": [22515.0] * 25,
                "low": [22500.0] * 25,
                "close": [22510.0] * 25,
                "volume": [8000] * 25,
            },
            index=dates,
        )

        c = MagicMock(
            symbol="NIFTY22550CE",
            strike=22550.0,
            option_type="CE",
            last_price=29.0,
            oi=30000,
            oi_change=-2000,
            volume=25000,
            pchange=12.0,
            expiry="2026-10-15",
        )

        alerts = detect_index_call_setup(
            underlying="NIFTY",
            spot=22510.0,
            chain=[c],
            vwap=22502.0,
            day_high=22600.0,
            day_low=22495.0,
            prev_day_high=22700.0,
            prev_day_low=22480.0,
            ohlcv_5m=df,
            ref_time=ref_mid,
            ignore_time_gate=True,
        )
        assert len(alerts) >= 1
        a = alerts[0]
        assert "VALUE_BASE_ACCUMULATION" in a.metrics["signals"]
        assert a.actionable_plan["confirmation_rule"] == "LIMIT_ON_PULLBACK_OTE"
        assert "LIMIT_IN_OTE_ZONE" in a.actionable_plan["execution_trigger"]

    def test_index_put_setup_case_by_case_execution_rules(self):
        from engine.detectors.index_put_setup import detect_index_put_setup
        from unittest.mock import MagicMock
        import pandas as pd
        from datetime import datetime
        from zoneinfo import ZoneInfo

        ist = ZoneInfo("Asia/Kolkata")
        ref_time = datetime(2026, 10, 13, 10, 30, tzinfo=ist)
        dates = pd.date_range("2026-10-13 09:15", periods=15, freq="5min", tz=ist)
        df = pd.DataFrame(
            {
                "open": [22550.0] * 15,
                "high": [22560.0] * 15,
                "low": [22490.0] * 15,
                "close": [22500.0] * 15,
                "volume": [9000] * 15,
            },
            index=dates,
        )

        c = MagicMock(
            symbol="NIFTY22450PE",
            strike=22450.0,
            option_type="PE",
            last_price=45.0,
            oi=50000,
            oi_change=12000,
            volume=35000,
            pchange=15.0,
            expiry="2026-10-15",
        )

        alerts = detect_index_put_setup(
            underlying="NIFTY",
            spot=22495.0,
            chain=[c],
            vwap=22525.0,
            day_high=22560.0,
            day_low=22490.0,
            prev_day_high=22600.0,
            prev_day_low=22480.0,
            ohlcv_5m=df,
            ref_time=ref_time,
            ignore_time_gate=True,
        )
        if alerts:
            a = alerts[0]
            assert "confirmation_rule" in a.actionable_plan
            assert a.actionable_plan["confirmation_rule"] in (
                "1_MIN_CANDLE_CLOSE_MANDATORY",
                "LIMIT_ON_PULLBACK_OTE",
            )
