"""Regression tests for 2026-11-27 signal audit fixes (2026-11-28)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

from engine.alert_evaluator import evaluate_alert_targets_and_trailing
from engine.alert_model import AutoAlert
from engine.alert_postmortem_runner import generate_session_scorecard
from engine.confluence_engine import evaluate_confluence
from engine.detectors.pre_inflection_dryup import detect_pre_inflection_dryup
from engine.eod_report_generator import EODReportGenerator
from engine.synthetic_sl import evaluate_synthetic_spot_sl, extract_dte

IST = ZoneInfo("Asia/Kolkata")


def test_extract_dte_prioritizes_future_expiry_over_stale_zero_metric() -> None:
    """32-DTE monthly option (WIPRO26DEC192.5PE) must never be treated as 0-DTE because metrics['dte'] == 0."""
    alert = AutoAlert(
        alert_id="aa-options-momentum-wipro-pe-192p5-1130-20261127",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="WIPRO",
        exchange="NFO",
        segment="FNO_STOCK",
        direction="BEARISH",
        headline="WIPRO 192.5 PE",
        summary="Test",
        ltp=6.08,
        trigger_level=6.08,
        option_premium=6.08,
        stop_loss=4.74,
        initial_stop_loss=4.74,
        target_level=8.20,
        strike=192.5,
        option_type="PE",
        contract_symbol="NSE:WIPRO26DEC192.5PE",
        expiry_date="2026-12-29",
        expiry_type="MONTHLY",
        underlying_spot=192.65,
        structural_spot_sl=194.50,
        created_at="2026-11-27 11:34:20 IST",
        triggered_at="2026-11-27 11:34:20 IST",
        metrics={"dte": 0, "is_0dte": False, "spot_vwap": 193.5},
    )
    assert extract_dte(alert) == 32

    # Ensure 22m velocity check does not label a 32-DTE contract as 0-DTE Theta Expiry
    fake_now = datetime(2026, 11, 27, 11, 57, 0, tzinfo=IST)
    with patch("engine.alert_evaluator.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.strptime = datetime.strptime
        res = evaluate_alert_targets_and_trailing(alert, current_ltp=5.87)
    if res is not None and res.trailing_rationale:
        assert "0-DTE Theta Expiry" not in res.trailing_rationale


def test_compress_stall_risk_does_not_trigger_premature_breakeven_or_disable_shield() -> None:
    """COMPRESS_STALL_RISK tightens SL below entry; it must NOT disable spot freak-wick shielding."""
    alert = AutoAlert(
        alert_id="aa-options-momentum-hyundai-pe-2000-0915-20261127",
        alert_type="OPTIONS_MOMENTUM",
        stage="COMPRESS_STALL_RISK",
        symbol="HYUNDAI",
        exchange="NFO",
        segment="FNO_STOCK",
        direction="BEARISH",
        headline="HYUNDAI 2000 PE",
        summary="Test",
        ltp=80.55,
        trigger_level=82.70,
        option_premium=82.70,
        stop_loss=73.88,
        initial_stop_loss=68.02,
        target_level=104.50,
        strike=2000.0,
        option_type="PE",
        contract_symbol="NSE:HYUNDAI26DEC2000PE",
        expiry_date="2026-12-29",
        underlying_spot=2015.0,
        structural_spot_sl=2035.0,
        achieved_milestones=["COMPRESS_STALL_RISK"],
        created_at="2026-11-27 11:17:19 IST",
        triggered_at="2026-11-27 11:17:19 IST",
    )
    with patch("engine.synthetic_sl.fetch_live_underlying_spot", return_value=2014.0):
        # Dip below compressed SL while spot (2014 < 2035) is intact -> shielded, NOT invalidated
        ev = evaluate_synthetic_spot_sl(
            alert, current_option_ltp=72.5, current_spot_override=2014.0
        )
    assert ev.is_invalidated is False
    assert ev.is_freak_wick_shielded is True


def test_pre_ignition_hierarchical_veto_is_untriggered_and_zero_r() -> None:
    """Pre-ignition STALK->PRIMED->INVALIDATED alerts must not book phantom -1.0R losses."""
    vetoed = AutoAlert(
        alert_id="aa-pre-inflection-dryup-drreddy-dryup-15m-20261127",
        alert_type="PRE_INFLECTION_DRYUP",
        stage="INVALIDATED",
        symbol="DRREDDY",
        exchange="NFO",
        segment="FNO_STOCK",
        direction="BULLISH",
        headline="DRREDDY dryup",
        summary="Test",
        ltp=38.25,
        trigger_level=38.10,
        stop_loss=29.72,
        initial_stop_loss=29.72,
        target_level=47.24,
        is_invalidated=True,
        invalidation_reason="Hierarchical veto on ignition: Setup lacks structural location confluence (score 65 < 75)",
        created_at="2026-11-27 10:12:26 IST",
        triggered_at=None,
        stage_history=[
            {"from_stage": None, "to_stage": "STALK", "at": "2026-11-27 10:12:26 IST"},
            {"from_stage": "STALK", "to_stage": "PRIMED", "at": "2026-11-27 10:13:40 IST"},
            {"from_stage": "PRIMED", "to_stage": "INVALIDATED", "at": "2026-11-27 10:14:45 IST"},
        ],
    )
    assert vetoed.has_triggered is False

    sc = generate_session_scorecard([vetoed], session_date="2026-11-27")
    assert sc["losses"] == 0
    assert sc["unfulfilled"] == 1
    assert sc["net_realized_r"] == 0.0

    # EOD report also keeps immutable initial_stop_loss in journal and classifies veto as SETUP_DISQUALIFIED
    trailed_win = AutoAlert(
        alert_id="aa-index-call-setup-banknifty-ce-63600-0915-20261127",
        alert_type="INDEX_CALL_SETUP",
        stage="RUNNER_EXIT",
        symbol="BANKNIFTY",
        exchange="NFO",
        segment="FNO_INDEX",
        direction="BULLISH",
        headline="BANKNIFTY 63600 CE",
        summary="Test",
        ltp=1571.60,
        trigger_level=1441.65,
        stop_loss=1580.00,  # Mutated trailing SL above target!
        initial_stop_loss=1280.00,
        target_level=1571.60,
        strike=63600.0,
        option_type="CE",
        contract_symbol="NSE:BANKNIFTY26DEC63600CE",
        achieved_milestones=["T1_ACHIEVED", "RUNNER_EXIT"],
        created_at="2026-11-27 09:34:02 IST",
        triggered_at="2026-11-27 09:34:02 IST",
    )
    gen = EODReportGenerator()
    with (
        patch.object(gen, "_load_alerts", return_value=[vetoed.to_dict(), trailed_win.to_dict()]),
        patch.object(
            gen,
            "_get_market_context",
            return_value={
                "nifty_ltp": 25607.2,
                "nifty_change_pct": -1.07,
                "banknifty_ltp": 63040.9,
                "banknifty_change_pct": -0.78,
                "sensex_ltp": 83339.26,
                "sensex_change_pct": -1.17,
                "vix_ltp": 16.55,
                "market_posture": "BEARISH",
                "fii_net_cr": 0.0,
                "dii_net_cr": 0.0,
            },
        ),
    ):
        rep = gen.generate(target_date="2026-11-27", use_ai=False)
    assert rep.loss_count == 0
    assert rep.untriggered_count == 1
    assert rep.win_count == 1
    bn_entry = next(j for j in rep.journal_entries if "BANKNIFTY" in j.symbol)
    assert bn_entry.stop_loss == 1280.00


def test_pre_inflection_dryup_symmetry_and_real_regime_snapshot(monkeypatch) -> None:
    """Dryup supports symmetric BEARISH coils and respects real RegimeSnapshot(ad_ratio) + NIFTY quote."""
    monkeypatch.delenv("CHANAKYA_TESTING", raising=False)
    monkeypatch.delenv("DEPLOY_MODE", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    # Bearish distribution coil near POC below SMA20 (with natural two-way oscillation so RSI in 26..58)
    n = 30
    idx = pd.date_range("2026-11-27 09:15", periods=n, freq="15min")
    closes = (
        [1015.0, 1012.0, 1014.0, 1010.0, 1012.0, 1008.0, 1010.0, 1006.0, 1008.0, 1005.0]
        + [1007.0, 1004.0, 1006.0, 1002.0, 1004.0, 1000.0, 1002.0, 999.0, 1001.0, 998.5]
        + [1000.0, 998.0, 999.5, 997.8, 999.2, 998.0, 998.8, 998.2, 998.5, 998.0]
    )
    df_bear = pd.DataFrame(
        {
            "open": [c + 0.5 for c in closes],
            "high": [c + 6.0 for c in closes[:-3]] + [999.8, 999.5, 999.2],
            "low": [c - 6.0 for c in closes[:-3]] + [997.2, 997.2, 997.0],
            "close": closes,
            "volume": [30000.0] * (n - 3) + [9000.0, 8500.0, 8000.0],
        },
        index=idx,
    )

    real_bear_reg = SimpleNamespace(is_edgeless=False, ad_ratio=0.55)
    with (
        patch("engine.market_regime_gate.evaluate_market_regime", return_value=real_bear_reg),
        patch("engine.option_resolver.resolve_option_contract", return_value=None),
    ):
        bear_alert = detect_pre_inflection_dryup(
            "TCS",
            df_bear,
            ltp=998.0,
            timeframe="15m",
            nifty_change_pct=-1.07,
            prev_close=1010.0,
        )
    assert bear_alert is not None
    assert bear_alert.direction == "BEARISH"
    assert bear_alert.stop_loss > bear_alert.trigger_level
    assert bear_alert.target_level < bear_alert.trigger_level
    assert bear_alert.metrics.get("nearest_supply_ob") is not None

    # Bullish coil is suppressed when real RegimeSnapshot has weak A/D (0.55) even without market_bias attr
    df_bull = df_bear.copy()
    bull_closes = [985.0] * 10 + [995.0] * 10 + [1005.0] * 7 + [1006.0, 1006.2, 1006.5]
    df_bull["close"] = bull_closes
    df_bull["open"] = [c - 0.5 for c in bull_closes]
    df_bull["high"] = [c + 5.0 for c in bull_closes[:-3]] + [1007.5, 1007.5, 1007.5]
    df_bull["low"] = [c - 5.0 for c in bull_closes[:-3]] + [1005.5, 1005.5, 1005.5]
    with patch("engine.market_regime_gate.evaluate_market_regime", return_value=real_bear_reg):
        assert (
            detect_pre_inflection_dryup(
                "RELIANCE",
                df_bull,
                ltp=1006.5,
                timeframe="15m",
                nifty_change_pct=-1.07,
                prev_close=1005.0,
            )
            is None
        )


def test_confluence_renormalizes_when_preopen_and_rvol_unrecorded() -> None:
    """Missing RVOL + missing pre-open gap must not artificially floor VWAP/BOS/RRG setups below 65."""
    rep = evaluate_confluence(
        symbol="SHRIRAMFIN",
        direction="BEARISH",
        ltp=925.0,
        vwap=945.0,
        rvol=None,
        pre_open_gap_pct=None,
        sector_quadrant="LAGGING",
        put_oi_change_pct=-12.0,
        market_structure_signal="BOS",
    )
    assert rep.total_score >= 70.0
    assert rep.is_qualified is True


def test_confidence_calibrator_outlier_spread_and_net_rr_friction() -> None:
    """Ignore corrupt >25% spread glitches and permit 25-40% friction when post-cost R:R >= 1.15."""
    from engine.confidence_calibrator import calibrate_alert_confidence

    high_rr_shriram = AutoAlert(
        alert_id="aa-options-momentum-shriramfin-pe-940-0915-20261127",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="SHRIRAMFIN",
        exchange="NFO",
        segment="FNO_STOCK",
        direction="BEARISH",
        headline="SHRIRAMFIN 940 PE",
        summary="Test",
        ltp=40.0,
        trigger_level=40.0,
        stop_loss=33.0,  # 7 pt risk vs 32 pt T1 -> net R:R well > 1.15 even with ~28% friction
        target_level=72.0,
        strike=940.0,
        option_type="PE",
        lot_size=825,
        confidence=88,
        bid_ask_spread_pct=0.0,
    )
    # 40 -> 72 with tight stop and statutory charges is viable, never falsely capped at 72
    rep_ok = calibrate_alert_confidence(high_rr_shriram, pillars=["LOCATION", "TRIGGER", "FLOW"])
    assert rep_ok.high_friction_risk is False

    corrupt_spread = AutoAlert(
        alert_id="aa-index-call-setup-banknifty-ce-63600-0915-20261127",
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        symbol="BANKNIFTY",
        exchange="NFO",
        segment="FNO_INDEX",
        direction="BULLISH",
        headline="BANKNIFTY 63600 CE",
        summary="Test",
        ltp=1441.65,
        trigger_level=1441.65,
        stop_loss=1280.0,
        target_level=1700.0,
        strike=63600.0,
        option_type="CE",
        lot_size=30,
        confidence=86,
        bid_ask_spread_pct=45.0,  # Broken ask-bid quote glitch (>25% at premium >= 50)
    )
    rep_clean = calibrate_alert_confidence(corrupt_spread, pillars=["LOCATION", "TRIGGER", "FLOW"])
    assert rep_clean.high_friction_risk is False
    assert any("outlier bid-ask spread" in n.lower() for n in rep_clean.notes)


def test_free_index_router_stages_and_acknowledges_free_telegram_outbox(monkeypatch) -> None:
    """FreeIndexRouter.dispatch must stage & acknowledge a FREE_TELEGRAM outbox record."""
    from unittest.mock import MagicMock
    from engine.free_index_router import FreeIndexRouter

    monkeypatch.setenv("TELEGRAM_FREE_INDEX_ENABLED", "1")
    monkeypatch.setenv("TELEGRAM_FREE_INDEX_CHAT_ID", "-100999999")
    router = FreeIndexRouter()
    repo = MagicMock()
    repo.get_latest_outbox_version.return_value = 1

    alert = AutoAlert(
        alert_id="aa-strat-sensex-pe-84000-20261127",
        alert_type="STRAT_2_1_2_BEARISH",
        stage="IGNITED",
        symbol="SENSEX",
        exchange="BFO",
        segment="FNO_INDEX",
        direction="BEARISH",
        headline="SENSEX 84000 PE",
        summary="Test",
        ltp=320.0,
        trigger_level=320.0,
        stop_loss=265.0,
        target_level=450.0,
        strike=84000.0,
        option_type="PE",
        lot_size=20,
        confidence=90,
        is_live=True,
        environment="LIVE",
        actionable_plan={"action": "BUY_PUT", "contract": "SENSEX 84000 PE"},
    )

    with patch("engine.alerts._telegram_notify", return_value=True):
        ok = router.dispatch(alert, in_market=True, is_milestone=False, repository=repo)
    assert ok is True
    repo.save_alert_with_outbox.assert_called_once()
    staged_entries = repo.save_alert_with_outbox.call_args[0][1]
    assert staged_entries[0]["channel"] == "FREE_TELEGRAM"
    repo.acknowledge_outbox_by_alert_channel.assert_called_once_with(
        alert.alert_id, "FREE_TELEGRAM"
    )


def test_identify_early_fno_movers_surfaces_tail_leaders() -> None:
    """Zero-chain full-F&O pre-filter must surface opening drives sitting past static index [:40]."""
    from engine.pipeline.universe_scheduler import identify_early_fno_movers

    universe = [f"STOCK{i}" for i in range(180)] + ["SOLARINDS", "BDL", "MAZDOCK"]
    quotes = {
        f"NSE:STOCK{i}": SimpleNamespace(
            change_pct=0.2, open=100.0, high=101.0, low=99.5, last_price=100.2, volume=200000
        )
        for i in range(180)
    }
    quotes["NSE:SOLARINDS"] = SimpleNamespace(
        change_pct=4.5,
        open=1000.0,
        high=1048.0,
        low=999.0,
        last_price=1045.0,
        volume=650000,
        rvol=2.6,
    )
    quotes["NSE:BDL"] = SimpleNamespace(
        change_pct=3.8,
        open=1200.0,
        high=1246.0,
        low=1198.0,
        last_price=1244.0,
        volume=800000,
        rvol=2.1,
    )
    quotes["NSE:MAZDOCK"] = SimpleNamespace(
        change_pct=3.2,
        open=2100.0,
        high=2169.0,
        low=2098.0,
        last_price=2167.0,
        volume=500000,
        rvol=1.9,
    )

    with patch("engine.position_sizer.get_lot_size", return_value=100):
        top = identify_early_fno_movers(universe, quotes, top_n=10)
    assert top[:3] == ["SOLARINDS", "BDL", "MAZDOCK"]


def test_ws_subscription_manager_prunes_expired_purposes(monkeypatch, tmp_path) -> None:
    """cleanse_expired_derivatives must remove expired contract entries from both symbols & _purposes."""
    from market.ws_subscription_manager import WsSubscriptionManager

    cache_file = tmp_path / "ws_active_subscriptions.json"
    monkeypatch.setattr("market.ws_subscription_manager._get_cache_path", lambda: cache_file)
    mgr = WsSubscriptionManager(max_subscriptions=200)
    mgr._core_symbols.add("NSE:NIFTY25JAN24000CE")
    mgr._purposes["NSE:NIFTY25JAN24000CE"] = "OPTION_GRID"
    mgr._purposes["NSE:RELIANCE-EQ"] = "FNO_STOCK"

    with patch(
        "market.ws_subscription_manager.is_contract_expired",
        side_effect=lambda s: "25JAN" in s,
    ):
        purged = mgr.cleanse_expired_derivatives()
    assert "NSE:NIFTY25JAN24000CE" in purged
    assert "NSE:NIFTY25JAN24000CE" not in mgr._purposes
    assert mgr._purposes.get("NSE:RELIANCE-EQ") == "FNO_STOCK"


def test_backfill_rebuild_dry_run_no_deadlock(tmp_path) -> None:
    """backfill_detector_circuit_breaker(rebuild=True, dry_run=True) must not deadlock on _lock."""
    from engine.detector_circuit_breaker import DetectorCircuitBreaker
    from scripts.backfill_detector_circuit_breaker import backfill_detector_circuit_breaker

    cb = DetectorCircuitBreaker(ledger_file=tmp_path / "cb.json")
    sample_alert = {
        "alert_id": "aa-options-momentum-tcs-pe-3000-20261127",
        "alert_type": "OPTIONS_MOMENTUM",
        "symbol": "TCS",
        "direction": "BEARISH",
        "stage": "SESSION_CLOSE_EXIT",
        "target_status": "SESSION_CLOSE_EXIT",
        "has_triggered": True,
        "ltp": 65.0,
        "trigger_level": 40.0,
        "initial_stop_loss": 28.0,
        "stop_loss": 28.0,
        "target_level": 64.0,
        "achieved_milestones": [],
        "exit_price": 65.0,
        "is_live": True,
        "environment": "LIVE",
        "created_at": "2026-11-27 09:26:00 IST",
        "triggered_at": "2026-11-27 09:26:00 IST",
    }
    res = backfill_detector_circuit_breaker(
        breaker=cb, alerts=[sample_alert], dry_run=True, rebuild=True
    )
    assert res["scanned"] == 1
    assert res["recorded"] == 1


def test_ws_subscription_purpose_distinguishes_fno_from_cash_context(monkeypatch, tmp_path) -> None:
    """FNO_PRIORITY must classify F&O stocks as FNO_STOCK and cash equities as CONTEXT_CASH."""
    from market.ws_subscription_manager import WsSubscriptionManager

    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))
    monkeypatch.setenv("SESSION_FOCUS_MODE", "FNO_PRIORITY")
    mgr = WsSubscriptionManager(max_subscriptions=2500)
    mgr._core_symbols.add("NSE:RELIANCE-EQ")
    mgr._core_symbols.add("NSE:MODISONLTD-BE")
    purposes = mgr.reconcile_subscription_purposes()
    assert purposes["NSE:RELIANCE-EQ"] == "FNO_STOCK"
    assert purposes["NSE:MODISONLTD-BE"] == "CONTEXT_CASH"
