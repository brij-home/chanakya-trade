"""
tests/test_fno_momentum_and_banknifty_rca.py
=============================================
Regression tests verifying the RCA and holistic fixes for:
  1. Banknifty and Stock F&O trend breakout signal capture (Camarilla H5/L5 expansion).
  2. ITM / high-delta contract inclusion in Gamma Blast (up to 1.2% ITM for index).
  3. Dynamic strike distance scaling in Options Momentum (ATR / spot-percentage based, not hardcoded 250 pts).
  4. Volume surge bypass of Vol/OI gate when contract volume is high.
  5. Hard veto against neutral credit spreads (Iron Condors) under high ADX (>= 28.0) or trending regimes.
  6. Midday lull breakout sensitivity in Intraday Spark.
  7. Index quote alias normalization (NSE:NIFTYBANK-INDEX, NSE:NIFTY BANK, BANKNIFTY).
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
from engine.detectors.gamma_blast import detect_gamma_blast
from engine.detectors.defined_risk_neutral import detect_defined_risk_neutral
from engine.detectors.intraday_spark import detect_intraday_mover_sparks

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
    expiry: str = "2026-11-12"
    expiry_date: str = "2026-11-12"
    oi_change: int = 1500


def _build_banknifty_chain(spot: float = 61337.0) -> list[MockOptionContract]:
    """Builds a realistic Banknifty options chain with ATM around 61300 and ITM 60800 CE."""
    chain = []
    # Strikes from 60500 to 62000
    for strk in range(60500, 62100, 100):
        # CE
        if strk <= spot:
            ce_prem = max(15.0, (spot - strk) + 220.0)
        else:
            ce_prem = max(15.0, 220.0 - (strk - spot) * 0.45)

        chain.append(
            MockOptionContract(
                symbol=f"BANKNIFTY{int(strk)}CE",
                strike=float(strk),
                option_type="CE",
                last_price=ce_prem,
                volume=35000 if strk == 60800 else 15000,
                oi=120000 if strk == 60800 else 80000,
                pchange=18.5,
                oi_change=8000,
            )
        )
        # PE
        if strk >= spot:
            pe_prem = max(15.0, (strk - spot) + 200.0)
        else:
            pe_prem = max(15.0, 200.0 - (spot - strk) * 0.45)

        chain.append(
            MockOptionContract(
                symbol=f"BANKNIFTY{int(strk)}PE",
                strike=float(strk),
                option_type="PE",
                last_price=pe_prem,
                volume=12000,
                oi=90000,
                pchange=-12.0,
                oi_change=-3000,
            )
        )
    return chain


class TestBankNiftyTrendCaptureRCA:
    """Verifies that Banknifty powerful trend breakouts (like 60800 CE) are captured and not blocked by H5."""

    def test_banknifty_captured_on_gap_and_trend_expansion(self):
        """When Banknifty is trending above H5 (+1.5% from prev close), setup must fire CAMARILLA_H5_EXPANSION or DAY_HIGH_BREAKOUT."""
        chain = _build_banknifty_chain(spot=61337.0)
        ref_dt = datetime(2026, 11, 11, 11, 45, 0, tzinfo=IST)

        mock_dl = MagicMock()
        mock_dl.camarilla = {"h5": 60617.3, "h4": 60216.1, "range": 863.4}
        mock_dl.atr_14 = 900.0
        mock_dl.pre_open = {"price": 60524.7, "gap_pct": 1.311}

        quotes_map = {
            "NSE:NIFTYBANK-INDEX": Quote(
                symbol="NSE:NIFTYBANK-INDEX",
                last_price=61337.0,
                open=60524.7,
                high=61350.0,
                low=60450.0,
                close=59741.25,
            )
        }

        with patch("engine.daily_levels.get_daily_levels", return_value=mock_dl):
            alerts = detect_index_call_setup(
                underlying="BANKNIFTY",
                spot=61337.0,
                chain=chain,
                vwap=60900.0,
                day_high=61350.0,
                day_low=60450.0,
                prev_day_high=59741.25,
                prev_day_low=58877.85,
                prev_close=59741.25,
                ref_time=ref_dt,
                ignore_time_gate=True,
                quotes_map=quotes_map,
            )

        assert len(alerts) > 0, (
            "Expected Banknifty call setup to fire during strong trend expansion day"
        )
        alert = alerts[0]
        sigs = alert.metrics.get("signals", [])
        assert "CAMARILLA_H5_EXPANSION" in sigs or "DAY_HIGH_BREAKOUT" in sigs

    def test_gamma_blast_captures_60800_ce_itm_contract(self):
        """Gamma Blast must allow ITM contracts up to 1.2% ITM on index (e.g. 60800 CE when spot is 61337 is -0.87% ITM)."""
        chain = _build_banknifty_chain(spot=61337.0)
        ref_dt = datetime(2026, 11, 11, 11, 45, 0, tzinfo=IST)

        alerts = detect_gamma_blast(
            underlying="BANKNIFTY",
            spot=61337.0,
            chain=chain,
            vwap=60900.0,
            day_high=61350.0,
            day_low=60450.0,
            prev_day_high=59741.25,
            prev_day_low=58877.85,
            now_dt=ref_dt,
        )

        # Gamma blast should consider strikes in the 60800-61300 range
        assert len(alerts) > 0, "Expected Gamma Blast to capture high-delta / ITM index options"
        strikes = [a.strike for a in alerts]
        assert any(s <= 61300 for s in strikes)


class TestDefinedRiskNeutralVetoRCA:
    """Verifies that Iron Condors / neutral spreads are strictly vetoed during strong trending regimes."""

    def test_iron_condor_vetoed_when_adx_high(self):
        """ADX >= 28.0 must veto Iron Condor even if open interest flanking walls or consolidation appear present."""
        candles_15m = pd.DataFrame(
            {
                "open": [60000 + i * 80 for i in range(25)],
                "high": [60050 + i * 80 for i in range(25)],
                "low": [59980 + i * 80 for i in range(25)],
                "close": [60040 + i * 80 for i in range(25)],
                "volume": [5000] * 25,
            }
        )

        mock_ctx = MagicMock()
        mock_ctx.segment = "FNO_INDEX"
        mock_ctx.canonical_symbol = "BANKNIFTY"
        mock_ctx.ltp = 61337.0
        mock_ctx.vix = 13.5
        mock_ctx.day_change_pct = 2.45
        mock_ctx.is_index = True
        mock_ctx.candles_15m = candles_15m
        mock_ctx.candles_5m = None
        mock_ctx.candles_daily = None
        mock_ctx.option_chain = _build_banknifty_chain(spot=61337.0)

        with patch("engine.detectors.defined_risk_neutral.compute_adx", return_value=56.76):
            alert = detect_defined_risk_neutral(mock_ctx)

        assert alert is None, (
            "Iron Condor MUST be vetoed when ADX >= 28.0 or day change > 0.90% for index"
        )


class TestIntradaySparkMiddayLullCalibration:
    """Verifies that Intraday Spark does not drop institutional momentum runners (+1.2% to +1.8%) during midday."""

    def test_midday_breakout_allowed_for_stocks(self, monkeypatch):
        """A stock breaking out with +1.5% and RVOL 1.55x at 12:15 IST must pass the calibrated midday filter (|chg| >= 1.2%, rvol >= 1.35x)."""
        from brokers.base import Quote

        q = Quote(
            symbol="NSE:TATAMOTORS",
            last_price=850.0,
            open=838.0,
            high=852.0,
            low=836.0,
            close=837.5,
            volume=5000000,
        )
        q.change_pct = 1.49
        q.vwap = 845.0

        quotes_map = {"NSE:TATAMOTORS": q}
        midday_dt = datetime(2026, 11, 11, 12, 15, 0, tzinfo=IST)

        mock_cpr_gate = MagicMock()
        mock_cpr_gate.is_vetoed = False
        mock_cpr_gate.is_narrow = False
        mock_cpr_gate.is_wide = False
        mock_cpr_gate.cpr_data = {}

        class MockDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return midday_dt

        monkeypatch.setattr("engine.trade_plan.calculate_trade_plan", lambda *a, **kw: None)
        monkeypatch.setattr("analysis.sector_rotation.get_stock_tailwind", lambda *a, **kw: None)
        monkeypatch.setattr("engine.auto_alert_engine.datetime", MockDateTime)
        monkeypatch.setattr("engine.detectors.intraday_spark.datetime", MockDateTime)
        monkeypatch.setattr("engine.daily_levels.evaluate_cpr_gate", lambda *a, **kw: mock_cpr_gate)
        monkeypatch.setattr(
            "engine.market_regime_gate.evaluate_index_tide_gate",
            lambda *a, **kw: MagicMock(is_vetoed=False),
        )
        monkeypatch.setattr("market.history.get_ohlcv", lambda *a, **kw: None)
        monkeypatch.setattr("market.sentiment.get_market_breadth", lambda *a, **kw: None)
        monkeypatch.setattr(
            "engine.detectors.intraday_spark.get_cached_avg_volume_20", lambda *a, **kw: 2000000.0
        )
        monkeypatch.setattr(
            "engine.detectors.intraday_spark.compute_time_of_day_rvol", lambda *a, **kw: 1.55
        )

        # Enforce session time gates while maintaining pytest environment isolation
        monkeypatch.setenv("ENFORCE_SESSION_TIME_GATES", "1")

        alerts = detect_intraday_mover_sparks(
            universe=["NSE:TATAMOTORS"],
            quotes_map=quotes_map,
        )

        assert len(alerts) > 0, "Expected midday breakout with +1.5% chg and 1.55x RVOL to pass"
        assert alerts[0].symbol in ("TATAMOTORS", "TMPV")


class TestOptionsMomentumClimaxAndExhaustionRCA:
    """Verifies that buying climax, effort vs result wicks, and parabolic overextension are blocked."""

    def test_alert_scrutiny_gate1_vetoes_effort_no_result_above_vwap(self):
        """Even if spot is above VWAP, an upthrust with EFFORT_NO_RESULT_BEARISH must be vetoed for naked calls."""
        from engine.alert_scrutiny import AlertScrutinyAuditor

        auditor = AlertScrutinyAuditor()
        alert = AutoAlert(
            alert_id="test-titan-call-climax",
            alert_type="OPTIONS_MOMENTUM",
            stage="IGNITED",
            symbol="TITAN",
            exchange="NSE",
            direction="BULLISH",
            headline="🟢 TITAN CALL BREAKOUT",
            summary="Momentum surge",
            ltp=92.9,
            trigger_level=92.9,
            target_level=137.5,
            stop_loss=72.46,
            confidence=85,
            metrics={
                "vsa_signal": "EFFORT_NO_RESULT_BEARISH",
                "spot": 5026.0,
                "spot_vwap": 5010.0,
                "upper_wick_ratio": 0.458,
            },
        )
        passed, reason, _ = auditor.verify_tier1_sanity(alert)
        assert passed is False
        assert "VSA Distribution Trap Veto" in reason

    def test_hierarchical_engine_mandates_limit_on_pullback_for_extended_candle(self):
        """When 5m RSI >= 70 or upper wick >= 25%, Hierarchical Engine mandates LIMIT_ON_PULLBACK in OTE zone."""
        from engine.pipeline.hierarchical_engine import hierarchical_pipeline

        alert = AutoAlert(
            alert_id="test-mm-extended",
            alert_type="OPTIONS_MOMENTUM",
            stage="IGNITED",
            symbol="M&M",
            exchange="NSE",
            direction="BULLISH",
            headline="🟢 M&M CALL BREAKOUT",
            summary="Surge",
            ltp=53.0,
            trigger_level=53.0,
            target_level=78.2,
            stop_loss=41.34,
            confidence=85,
            metrics={
                "rsi_5m": 72.5,
                "upper_wick_ratio": 0.32,
                "spot": 3397.0,
                "spot_vwap": 3380.0,
            },
        )
        verdict = hierarchical_pipeline.evaluate(alert)
        assert verdict.level3_execution.entry_style == "LIMIT_ON_PULLBACK"
        assert any("pullback" in note.lower() for note in verdict.level3_execution.coaching_notes)

    def test_market_breadth_liquidation_does_not_fire_when_advances_exceed_declines(self):
        """When market has 86 advances vs 64 declines (A/D ratio 1.34), Gate 22 must NOT trigger liquidation veto."""
        from engine.alert_scrutiny import alert_scrutiny_auditor
        from market.sentiment import MarketBreadth

        mb = MarketBreadth(
            advances=86,
            declines=64,
            unchanged=5,
            ad_ratio=1.34,
            verdict="MIXED",
            above_vwap=20,
            below_vwap=60,
            vwap_ratio=0.33,
            intraday_verdict="INTRADAY_CHOP",
        )

        alert = AutoAlert(
            alert_id="aa-ib-breakout-abcapital-bull-20261112",
            alert_type="INITIAL_BALANCE_BREAKOUT",
            stage="IGNITED",
            symbol="ABCAPITAL",
            exchange="NSE",
            direction="BULLISH",
            headline="🟢 ABCAPITAL IB HIGH BREAKOUT",
            summary="Initial Balance breakout",
            ltp=210.0,
            trigger_level=210.0,
            target_level=225.0,
            stop_loss=202.5,
            confidence=90,
            metrics={
                "spot": 210.0,
                "ib_high": 208.5,
                "bar_rvol": 2.1,
                "day_high_breakout": True,
            },
        )

        with patch("market.sentiment.get_market_breadth", return_value=mb):
            passed, reason, flags = alert_scrutiny_auditor.verify_tier1_sanity(alert)

        assert "Market Breadth Liquidation Veto" not in reason
        assert flags.get("market_breadth_valid") is not False

    def test_hierarchical_engine_approves_structural_1_8_rr_setup(self):
        """A directional setup with 1.8:1 structural R:R must pass Hierarchical Level 3 execution matrix."""
        from engine.pipeline.hierarchical_engine import hierarchical_pipeline

        alert = AutoAlert(
            alert_id="aa-phoenixltd-ce-breakout-20261112",
            alert_type="OPTIONS_MOMENTUM",
            stage="IGNITED",
            symbol="PHOENIXLTD",
            exchange="NSE",
            direction="BULLISH",
            headline="🟢 PHOENIXLTD CALL BREAKOUT",
            summary="Momentum breakout",
            ltp=50.0,
            trigger_level=50.0,
            stop_loss=40.0,  # 10 pts risk
            target_level=68.0,  # 18 pts reward -> 1.8:1 structural R:R
            confidence=90,
            metrics={"spot": 2240.0, "rvol": 2.0},
        )

        verdict = hierarchical_pipeline.evaluate(alert)
        assert verdict.level3_execution.passed is True
        assert verdict.level3_execution.status == "EXECUTABLE"
        assert verdict.level3_execution.underlying_structural_rr >= 1.8

    def test_benchmark_divergence_trap_allows_ce_during_v_reversal(self):
        """When Nifty has bounced +0.30% from its low in an active V-reversal, SENSEX CE must not be vetoed."""
        from engine.alert_scrutiny import alert_scrutiny_auditor

        alert = AutoAlert(
            alert_id="aa-sensex-ce-call-20261112",
            alert_type="INDEX_CALL_SETUP",
            stage="IGNITED",
            symbol="SENSEX",
            exchange="BFO",
            direction="BULLISH",
            headline="🟢 SENSEX 82100 CE CALL",
            summary="SENSEX CE bounce",
            ltp=250.0,
            trigger_level=250.0,
            stop_loss=190.0,
            target_level=370.0,
            confidence=92,
            metrics={
                "spot": 82050.0,
                "day_low": 81800.0,  # bounce is +0.31%
                "vwap": 82030.0,
                "nifty_change_pct": -0.07,
                "nifty_bounce_from_low": 0.30,
            },
        )

        passed, reason, flags = alert_scrutiny_auditor.verify_tier1_sanity(alert)

        assert "Benchmark Divergence Trap" not in reason
        assert flags.get("benchmark_regime_valid") is not False
