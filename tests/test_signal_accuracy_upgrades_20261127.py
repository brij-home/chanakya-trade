"""Regression tests for empirical signal calibration, ADR/friction gates, and expectancy reporting."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from engine.alert_model import AutoAlert
from engine.detector_circuit_breaker import DetectorCircuitBreaker
from engine.option_target_calibration import (
    compute_option_adr_headroom_targets,
    evaluate_option_friction_viability,
)
from engine.signal_expectancy import compute_signal_expectancy_report
from scripts.backfill_detector_circuit_breaker import backfill_detector_circuit_breaker

IST = ZoneInfo("Asia/Kolkata")


def _make_option_alert(
    *,
    alert_id: str = "aa-options_momentum-infy-20261127",
    alert_type: str = "OPTIONS_MOMENTUM",
    symbol: str = "INFY",
    stage: str = "IGNITED",
    ltp: float = 100.0,
    stop_loss: float = 85.0,
    target_level: float = 130.0,
    rvol: float = 1.6,
    confidence: int = 80,
    is_live: bool = True,
    environment: str = "LIVE",
    created_at: str = "2026-11-27 10:15:00 IST",
    exit_price: float | None = None,
    has_triggered: bool = True,
    achieved_milestones: list[str] | None = None,
) -> AutoAlert:
    trail = []
    if exit_price is not None:
        trail.append({"event": stage, "details": {"exit_price": exit_price}})
    return AutoAlert(
        alert_id=alert_id,
        alert_type=alert_type,
        stage=stage,
        symbol=symbol,
        exchange="NFO",
        segment="FNO_STOCK",
        direction="BULLISH",
        headline=f"{symbol} Option Setup",
        summary="Test summary",
        ltp=exit_price if exit_price is not None else ltp,
        trigger_level=ltp,
        initial_entry_premium=ltp,
        stop_loss=stop_loss,
        initial_stop_loss=stop_loss,
        target_level=target_level,
        option_type="CE",
        strike=1600.0,
        lot_size=400,
        confidence=confidence,
        time_horizon="INTRADAY",
        triggered_at=created_at if has_triggered else None,
        achieved_milestones=achieved_milestones or [],
        audit_trail=trail,
        metrics={"rvol": rvol, "vol_oi_ratio": 1.8, "lot_size": 400},
        created_at=created_at,
        is_live=is_live,
        environment=environment,
    )


class TestDetectorCircuitBreakerRecordingAndBackfill:
    def test_backfill_idempotently_records_unscaled_live_terminal_alerts(self, tmp_path):
        cb = DetectorCircuitBreaker(
            ledger_file=tmp_path / "perf.json", rolling_window=50, min_samples=3
        )
        loss_alert = _make_option_alert(
            alert_id="aa-options_momentum-tcs-20261127-1",
            symbol="TCS",
            stage="TIME_STOP_EXIT",
            ltp=100.0,
            stop_loss=85.0,
            exit_price=92.5,
        ).to_dict()
        win_alert = _make_option_alert(
            alert_id="aa-options_momentum-sbin-20261127-2",
            symbol="SBIN",
            stage="SESSION_CLOSE_EXIT",
            ltp=50.0,
            stop_loss=40.0,
            exit_price=68.0,
        ).to_dict()
        partial_runner = _make_option_alert(
            alert_id="aa-options_momentum-infy-20261127-3",
            symbol="INFY",
            stage="RUNNER_EXIT",
            ltp=100.0,
            stop_loss=85.0,
            exit_price=125.0,
            achieved_milestones=["T1_ACHIEVED"],
        ).to_dict()
        test_alert = _make_option_alert(
            alert_id="aa-options_momentum-wipro-20261127-4",
            symbol="WIPRO",
            stage="INVALIDATED",
            ltp=100.0,
            stop_loss=85.0,
            exit_price=85.0,
            is_live=False,
            environment="TEST",
        ).to_dict()

        dry = backfill_detector_circuit_breaker(
            breaker=cb,
            alerts=[loss_alert, win_alert, partial_runner, test_alert],
            dry_run=True,
        )
        assert dry["recorded"] == 2
        assert dry["ineligible"] == 2

        first = backfill_detector_circuit_breaker(
            breaker=cb,
            alerts=[loss_alert, win_alert, partial_runner, test_alert],
            dry_run=False,
        )
        assert first["recorded"] == 2
        assert first["conflicts"] == 0

        # Idempotent replay must skip already recorded items without error
        second = backfill_detector_circuit_breaker(
            breaker=cb,
            alerts=[loss_alert, win_alert, partial_runner, test_alert],
            dry_run=False,
        )
        assert second["recorded"] == 0
        assert second["already_seen"] == 2

        metrics = cb.get_metrics("OPTIONS_MOMENTUM")
        assert metrics.sample_count == 2
        assert metrics.status == "UNCALIBRATED"  # < min_samples=3

        # Add one more verified loss to satisfy min_samples=3
        third_alert = _make_option_alert(
            alert_id="aa-options_momentum-hcltech-20261127-5",
            symbol="HCLTECH",
            stage="INVALIDATED",
            ltp=100.0,
            stop_loss=85.0,
            exit_price=85.0,
        ).to_dict()
        backfill_detector_circuit_breaker(breaker=cb, alerts=[third_alert], dry_run=False)
        metrics_after = cb.get_metrics("OPTIONS_MOMENTUM")
        assert metrics_after.sample_count == 3
        assert metrics_after.status != "UNCALIBRATED"

    def test_terminal_outcome_records_live_time_stop_without_error(self, tmp_path, monkeypatch):
        cb = DetectorCircuitBreaker(ledger_file=tmp_path / "live_cb.json", min_samples=2)
        import engine.detector_circuit_breaker as cb_mod
        from engine.alert_outcomes import (
            calculate_terminal_forward_outcome,
            record_terminal_forward_outcome,
        )

        monkeypatch.setattr(cb_mod, "detector_circuit_breaker", cb)
        a_loss = _make_option_alert(
            alert_id="aa-options_momentum-vedl-loss",
            symbol="VEDL",
            stage="TIME_STOP_EXIT",
            ltp=40.0,
            stop_loss=34.0,
        )
        a_flat = _make_option_alert(
            alert_id="aa-options_momentum-vedl-flat",
            symbol="VEDL",
            stage="TIME_STOP_EXIT",
            ltp=40.0,
            stop_loss=34.0,
        )
        a_win = _make_option_alert(
            alert_id="aa-options_momentum-vedl-win",
            symbol="VEDL",
            stage="SESSION_CLOSE_EXIT",
            ltp=40.0,
            stop_loss=34.0,
        )
        record_terminal_forward_outcome(
            a_loss, calculate_terminal_forward_outcome(a_loss, 37.0), event="TIME_STOP_EXIT"
        )
        record_terminal_forward_outcome(
            a_flat, calculate_terminal_forward_outcome(a_flat, 40.0), event="TIME_STOP_EXIT"
        )
        record_terminal_forward_outcome(
            a_win, calculate_terminal_forward_outcome(a_win, 49.0), event="SESSION_CLOSE_EXIT"
        )
        m = cb.get_metrics("OPTIONS_MOMENTUM")
        assert m.sample_count == 3

    def test_afternoon_telegram_gate_rejects_missing_rvol_without_strong_flow(self, monkeypatch):
        monkeypatch.setenv("ENFORCE_AFTERNOON_STOCK_GATE", "1")
        from engine.auto_alert_engine import AutoAlertEngine

        eng = AutoAlertEngine()
        test_ts = datetime(2026, 11, 27, 13, 45, tzinfo=IST).timestamp()
        alert = _make_option_alert(
            alert_id="aa-options_momentum-wipro-pm",
            symbol="WIPRO",
            rvol=0.0,
            confidence=84,
            created_at="2026-11-27 13:45:00 IST",
        )
        allowed, reason = eng._eval_telegram_apex_gate(alert, now_ts=test_ts)
        assert allowed is False
        assert "missing RVOL" in reason


class TestOptionTargetCalibrationAndFriction:
    def test_adr_headroom_caps_unrealistic_late_session_target(self):
        # At 14:40 IST with most of daily ADR already spent, raw +140 pt target is scaled down
        late_dt = datetime(2026, 11, 27, 14, 40, tzinfo=IST)
        res = compute_option_adr_headroom_targets(
            spot=1600.0,
            opt_ltp=80.0,
            opt_sl=68.0,
            raw_t1=220.0,
            option_type="CE",
            strike=1600.0,
            dte_days=12,
            iv=0.22,
            spot_atr=26.0,
            day_high=1622.0,
            day_low=1598.0,
            now_dt=late_dt,
            segment="FNO_STOCK",
        )
        assert res.was_adr_capped is True
        assert res.calibrated_t1 < 220.0
        assert res.calibrated_t1 < res.calibrated_t2 < res.calibrated_t3
        assert 0.15 <= res.delta <= 0.98

    def test_friction_viability_rejects_wide_spread_and_tiny_target_edge(self):
        wide = evaluate_option_friction_viability(
            entry_price=50.0,
            target_1=65.0,
            stop_loss=42.0,
            quantity=100,
            bid=46.0,
            ask=51.0,
            max_spread_pct=4.5,
        )
        assert wide["viable"] is False
        assert "spread shock" in (wide["reason"] or "")

        tiny = evaluate_option_friction_viability(
            entry_price=400.0,
            target_1=402.0,
            stop_loss=398.5,
            quantity=25,
            bid=399.0,
            ask=401.0,
            max_spread_pct=5.0,
            max_friction_drag_pct=25.0,
        )
        assert tiny["viable"] is False

        healthy = evaluate_option_friction_viability(
            entry_price=120.0,
            target_1=150.0,
            stop_loss=105.0,
            quantity=400,
            bid=119.5,
            ask=120.2,
        )
        assert healthy["viable"] is True
        assert healthy["net_rr"] >= 1.05


class TestSignalExpectancyEvaluatorAndApi:
    def test_expectancy_segmentation_and_sample_qualification(self):
        alerts = []
        for idx in range(6):
            alerts.append(
                _make_option_alert(
                    alert_id=f"aa-om-s{idx}",
                    symbol="INFY",
                    stage="SESSION_CLOSE_EXIT" if idx < 4 else "TIME_STOP_EXIT",
                    ltp=100.0,
                    stop_loss=90.0,
                    exit_price=118.0 if idx < 4 else 94.0,
                    rvol=1.8 if idx < 4 else 0.0,
                    confidence=85 if idx < 4 else 52,
                    created_at="2026-11-27 09:45:00 IST" if idx < 4 else "2026-11-27 13:30:00 IST",
                ).to_dict()
            )
        # Non-live alert must be excluded by default
        alerts.append(
            _make_option_alert(
                alert_id="aa-om-test-skip",
                stage="INVALIDATED",
                exit_price=80.0,
                is_live=False,
                environment="TEST",
            ).to_dict()
        )

        report = compute_signal_expectancy_report(alerts=alerts, include_test=False)
        assert report["evaluated_trades"] == 6
        assert report["skipped_non_live"] == 1
        assert report["overall"]["qualification"] == "PRELIMINARY"
        assert report["overall"]["net_expectancy_r"] < report["overall"]["gross_expectancy_r"]
        assert "OPTIONS_MOMENTUM" in report["by_detector"]
        assert "MISSING_OR_ZERO" in report["by_rvol_bucket"]
        assert "HIGH_1.5_2.5" in report["by_rvol_bucket"]
        assert report["by_rvol_bucket"]["MISSING_OR_ZERO"]["qualification"] == "INSUFFICIENT_SAMPLE"

    def test_expectancy_endpoint_returns_valid_envelope(self, monkeypatch):
        from web.api import app
        import engine.signal_expectancy as exp_mod

        monkeypatch.setattr(exp_mod, "load_persisted_alerts", lambda limit=5000: [])
        client = TestClient(app)
        resp = client.get("/api/analytics/expectancy")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["data"]["evaluated_trades"] == 0
        assert body["data"]["overall"]["qualification"] == "INSUFFICIENT_SAMPLE"


class TestCommodityCounterVwapAndRsiRca:
    def test_commodity_blocks_counter_vwap_oversold_crudeoil_call(self, monkeypatch):
        import pandas as pd

        from brokers.base import Quote
        from engine.detectors.commodity import detect_commodity_breakouts

        monkeypatch.setenv("FORCE_LIVE_QUOTE", "1")
        now_dt = datetime.now(IST)
        idx = pd.date_range(end=now_dt, periods=28, freq="5min")
        # Trending down from 8040 to 7952 (RSI deeply oversold, well below VWAP 7975.5)
        closes = [8040.0 - i * 3.2 for i in range(28)]
        closes[-1] = 7952.0
        df_5m = pd.DataFrame(
            {
                "open": [c + 2.0 for c in closes],
                "high": [c + 8.0 for c in closes],
                "low": [c - 2.0 for c in closes],
                "close": closes,
                "volume": [1000] * 27 + [1600],
            },
            index=idx,
        )
        # Morning prev_close was lower (7875) so +1.0% chg_prev falsely passed macro_bull previously
        q_crude = Quote(
            symbol="MCX:CRUDEOIL",
            last_price=7952.0,
            open=7890.0,
            high=8050.0,
            low=7939.0,
            close=7873.0,
            volume=45000,
            vwap=7975.5,
            change_pct=1.0,
        )
        alerts = detect_commodity_breakouts(
            universe=["CRUDEOIL"],
            quotes_map={"MCX:CRUDEOIL": q_crude},
            ohlcv_map={"CRUDEOIL": df_5m},
        )
        assert alerts == []

    def test_commodity_quant_fallback_does_not_claim_vwap_reclaim_when_below_vwap(self):
        from engine.alert_scrutiny import alert_scrutiny_auditor

        alert = AutoAlert(
            alert_id="aa-commodity-crude-fallback",
            alert_type="COMMODITY_MOMENTUM",
            stage="IGNITED",
            symbol="CRUDEOIL",
            exchange="MCX",
            segment="COMMODITY",
            direction="BULLISH",
            headline="CRUDEOIL Test",
            summary="Test",
            ltp=362.4,
            trigger_level=362.4,
            target_level=440.0,
            stop_loss=300.1,
            underlying_spot=7952.0,
            confidence=82,
            metrics={"change_pct": 1.0, "spot": 7952.0, "vwap": 7975.5},
        )
        res = alert_scrutiny_auditor._generate_quantitative_fallback(alert, {"sanctity": True})
        assert "reclaiming VWAP" not in res.logic_confirmation
        assert "below VWAP" in res.logic_confirmation

    def test_silver_pullback_peak_target_never_inverts_target_hierarchy(self):
        import pandas as pd

        from brokers.base import Quote
        from engine.detectors.commodity import detect_commodity_breakouts

        now_dt = datetime.now(IST)
        idx = pd.date_range(end=now_dt, periods=25, freq="5min")
        # Early spike peak at 154,106 followed by controlled dip holding above VWAP (151,000)
        closes = [151500.0 + i * 60.0 for i in range(25)]
        highs = [c + 120.0 for c in closes]
        highs[-4] = 154106.0  # Intraday peak higher than standard +4.5R
        lows = [c - 100.0 for c in closes]
        closes[-1] = 152500.0
        lows[-1] = min(lows[-6:-1])  # Matches Demand Zone Support near trough_recent
        df_5m = pd.DataFrame(
            {
                "open": [c - 40.0 for c in closes],
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": [1000] * 24 + [1500],
            },
            index=idx,
        )
        q_silver = Quote(
            symbol="MCX:SILVER",
            last_price=152500.0,
            open=150000.0,
            high=154106.0,
            low=149800.0,
            close=149900.0,
            volume=20000,
            vwap=151000.0,
            change_pct=1.73,
        )
        alerts = detect_commodity_breakouts(
            universe=["SILVER"],
            quotes_map={"MCX:SILVER": q_silver},
            ohlcv_map={"SILVER": df_5m},
        )
        for alert in alerts:
            ok, msg = alert.validate_data_integrity()
            assert ok, f"Data integrity failed for SILVER: {msg}"
            plan = alert.actionable_plan or {}
            t1_v = float(str(plan.get("target_1", "0")).replace("₹", "").replace(",", ""))
            t2_v = float(str(plan.get("target_2", "0")).replace("₹", "").replace(",", ""))
            if t1_v > 0 and t2_v > 0:
                assert t2_v > t1_v


class TestDryupAndNeutralCostHardening:
    def test_pre_inflection_dryup_rejects_bearish_downtrend_coils(self):
        import pandas as pd

        from engine.detectors.pre_inflection_dryup import detect_pre_inflection_dryup

        # Trending steadily downward so price is below SMA20 and RSI < 42
        closes = [1000.0 - i * 3.5 for i in range(55)]
        df = pd.DataFrame(
            {
                "open": [c + 1.0 for c in closes],
                "high": [c + 2.0 for c in closes],
                "low": [c - 2.0 for c in closes],
                "close": closes,
                "volume": [5000] * 50 + [1000] * 5,
            }
        )
        alert = detect_pre_inflection_dryup("INFY", df, ltp=closes[-1])
        assert alert is None

    def test_defined_risk_neutral_rejects_high_friction_thin_credit_condor(self, monkeypatch):
        import pandas as pd

        from engine.detection_context import DetectionContext
        from engine.defined_risk_spreads import DefinedRiskSpread, SpreadLeg
        from engine.detectors import defined_risk_neutral as drn_mod

        candles = pd.DataFrame(
            {
                "open": [100.0] * 40,
                "high": [101.0] * 40,
                "low": [99.0] * 40,
                "close": [100.0] * 40,
                "volume": [1000] * 40,
            }
        )
        thin_spread = DefinedRiskSpread(
            strategy_name="IRON_CONDOR",
            underlying="HAVELLS",
            spot_price=1500.0,
            lot_size=500,
            legs=[
                SpreadLeg("HAVELLS1450PE", "PE", 1450.0, "SELL", 1.2, 500, 500),
                SpreadLeg("HAVELLS1430PE", "PE", 1430.0, "BUY", 1.0, 500, 500),
                SpreadLeg("HAVELLS1550CE", "CE", 1550.0, "SELL", 1.2, 500, 500),
                SpreadLeg("HAVELLS1570CE", "CE", 1570.0, "BUY", 1.0, 500, 500),
            ],
            net_debit_or_credit=-200.0,  # ₹200 total credit eaten completely by 4-leg brokerage/STT
            max_profit=200.0,
            max_loss=9800.0,
            risk_reward_ratio=0.02,
            breakeven_points=[1449.6, 1550.4],
            capital_required=9800.0,
            sentiment="NEUTRAL",
            thesis="Thin credit test",
        )
        monkeypatch.setattr(drn_mod, "build_defined_risk_spread", lambda **kwargs: thin_spread)
        ctx = DetectionContext(
            symbol="HAVELLS",
            canonical_symbol="HAVELLS",
            exchange="NSE",
            segment="FNO_STOCK",
            ltp=1500.0,
            prev_close=1500.0,
            vix=13.0,
            candles_15m=candles,
        )
        assert drn_mod.detect_defined_risk_neutral(ctx) is None
