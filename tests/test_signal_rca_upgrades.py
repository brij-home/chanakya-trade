"""
tests/test_signal_rca_upgrades.py
─────────────────────────────────
Regression tests for signal timing, directional supremacy, session-VWAP isolation,
intraday sector breadth prioritization, and confluence enrichment.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd

from config.constants import IST
from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine
from engine.detectors.options_momentum import detect_options_momentum_breakouts
from engine.detectors.trend_day_continuation import detect_trend_day_pullback
from engine.signal_enrichment import enrich_alert_with_feature_bus


def test_trend_pullback_session_vwap_resets_and_blocks_counter_session(monkeypatch):
    """Multi-day df_5m must not bleed prior session VWAP into today's session,
    and sharp counter-session drops must not trigger BULLISH pullbacks."""
    monkeypatch.setenv("CHANAKYA_TESTING", "1")
    # Yesterday: surged 1200 -> 1250 (creates high prior-day EMA/VWAP baseline)
    y_times = [
        datetime(2026, 11, 25, 14, 0, tzinfo=IST) + timedelta(minutes=5 * i) for i in range(12)
    ]
    y_prices = np.linspace(1200.0, 1250.0, 12).tolist()
    # Today: gapped down and falling 1225 -> 1210 (-3.2% from prev_close=1250), small dead-cat bounce
    t_times = [
        datetime(2026, 11, 26, 9, 15, tzinfo=IST) + timedelta(minutes=5 * i) for i in range(10)
    ]
    t_prices = [1225.0, 1222.0, 1219.0, 1217.0, 1215.0, 1214.0, 1212.0, 1211.0, 1210.0, 1212.0]

    times = y_times + t_times
    prices = y_prices + t_prices
    df = pd.DataFrame(
        {
            "open": [p - 1.0 for p in prices],
            "high": [p + 2.0 for p in prices],
            "low": [p - 3.0 for p in prices],
            "close": prices,
            "volume": [10000.0] * (len(prices) - 1) + [4000.0],
        },
        index=pd.DatetimeIndex(times),
    )

    alert = detect_trend_day_pullback(
        symbol="BAJFINANCE",
        df_5m=df,
        ltp=1212.0,
        now_dt=datetime(2026, 11, 26, 10, 48, tzinfo=IST),
        exchange="NSE",
        segment="FNO_STOCK",
        prev_close=1250.0,
    )
    assert alert is None or alert.direction != "BULLISH"


def test_trend_pullback_symmetric_bearish_blocked_on_counter_session_rally(monkeypatch):
    """Symmetric check: sharp up-day (+3% from prev_close) must not emit BEARISH pullback."""
    monkeypatch.setenv("CHANAKYA_TESTING", "1")
    y_times = [
        datetime(2026, 11, 25, 14, 0, tzinfo=IST) + timedelta(minutes=5 * i) for i in range(12)
    ]
    y_prices = np.linspace(1250.0, 1200.0, 12).tolist()
    t_times = [
        datetime(2026, 11, 26, 9, 15, tzinfo=IST) + timedelta(minutes=5 * i) for i in range(10)
    ]
    t_prices = [1225.0, 1228.0, 1230.0, 1232.0, 1234.0, 1235.0, 1236.0, 1237.0, 1238.0, 1236.0]

    times = y_times + t_times
    prices = y_prices + t_prices
    df = pd.DataFrame(
        {
            "open": [p + 1.0 for p in prices],
            "high": [p + 3.0 for p in prices],
            "low": [p - 2.0 for p in prices],
            "close": prices,
            "volume": [10000.0] * (len(prices) - 1) + [4000.0],
        },
        index=pd.DatetimeIndex(times),
    )

    alert = detect_trend_day_pullback(
        symbol="INFY",
        df_5m=df,
        ltp=1236.0,
        now_dt=datetime(2026, 11, 26, 10, 48, tzinfo=IST),
        exchange="NSE",
        segment="FNO_STOCK",
        prev_close=1200.0,
    )
    assert alert is None or alert.direction != "BEARISH"


def test_directional_supremacy_requires_higher_score_and_defers_commit(tmp_path, monkeypatch):
    """Weaker opposing reversal must not kill higher-score active alert, and rejected incoming
    candidates must never leave the existing alert invalidated."""
    monkeypatch.setenv("CHANAKYA_TESTING", "0")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(
        "engine.auto_alert_engine.AutoAlertEngine._save",
        lambda self, *a, **kw: None,
    )
    engine = AutoAlertEngine()
    engine._alerts_file = tmp_path / "auto_alerts.json"
    engine._alerts = []

    now_dt = datetime.now(IST)
    active_time = (now_dt - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S IST")
    active_ce = AutoAlert(
        alert_id="aa-liquidity-inversion-bse-beartrapsqueeze-20261126",
        alert_type="LIQUIDITY_INVERSION",
        stage="IGNITED",
        symbol="BSE",
        exchange="NFO",
        segment="FNO_STOCK",
        direction="BULLISH",
        headline="BSE CE",
        summary="Bullish squeeze",
        ltp=145.0,
        trigger_level=145.0,
        stop_loss=130.0,
        target_level=180.0,  # RR ~2.33 -> score ~98 * 2.33 = 228
        strike=3950.0,
        option_type="CE",
        contract_symbol="NSE:BSE26DEC3950CE",
        confidence=98,
        created_at=active_time,
        is_live=True,
        environment="LIVE",
    )
    engine._alerts.append(active_ce)

    # Case 1: Lower-score opposing alert even with has_rev (choch=True) must be blocked, keeping active_ce intact
    weaker_pe = AutoAlert(
        alert_id="aa-gamma-blast-bse-pe-3900-0915-20261126",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="BSE",
        exchange="NFO",
        segment="FNO_STOCK",
        direction="BEARISH",
        headline="BSE PE",
        summary="Bearish blast",
        ltp=120.0,
        trigger_level=120.0,
        stop_loss=100.0,
        target_level=160.0,  # RR = 2.0 -> score = 88 * 2.0 = 176 < 228
        strike=3900.0,
        option_type="PE",
        contract_symbol="NSE:BSE26DEC3900PE",
        confidence=88,
        created_at=now_dt.strftime("%Y-%m-%d %H:%M:%S IST"),
        metrics={"choch": True, "spot": 3910.0, "vwap": 3920.0, "rvol": 1.8},
        is_live=True,
        environment="LIVE",
    )
    recorded = engine.record_alert(weaker_pe)
    assert recorded is False
    assert active_ce.is_invalidated is False
    assert active_ce.is_active is True

    # Case 2: Stronger opposing alert that fails Tier-1 sanity (target < entry for long option)
    # must NOT prematurely invalidate active_ce!
    invalid_stronger_pe = AutoAlert(
        alert_id="aa-smc-ob-retest-bse-bear-20261126",
        alert_type="SMC_ORDERBLOCK_RETEST",
        stage="IGNITED",
        symbol="BSE",
        exchange="NFO",
        segment="FNO_STOCK",
        direction="BEARISH",
        headline="Invalid PE",
        summary="Invalid levels",
        ltp=120.0,
        trigger_level=120.0,
        stop_loss=100.0,
        target_level=110.0,  # Invalid for option buy (target < entry) -> Tier 1 rejects!
        strike=3900.0,
        option_type="PE",
        contract_symbol="NSE:BSE26DEC3900PE",
        confidence=99,
        created_at=now_dt.strftime("%Y-%m-%d %H:%M:%S IST"),
        metrics={"choch": True},
        is_live=True,
        environment="LIVE",
    )
    recorded_inv = engine.record_alert(invalid_stronger_pe)
    assert recorded_inv is False
    assert active_ce.is_invalidated is False
    assert active_ce.is_active is True


def test_options_momentum_enforces_20m_runway_cutoff(monkeypatch):
    """Late-session entries within 20m of squareoff cutoff (e.g. 15:05 pre-Dec 7) must be suppressed."""
    monkeypatch.delenv("CHANAKYA_TESTING", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("DEPLOY_MODE", raising=False)

    quote_map = {
        "NSE:NIFTY50-INDEX": SimpleNamespace(last_price=25880.0, vwap=25800.0, change_pct=0.4),
        "NSE:TCS": SimpleNamespace(
            last_price=2600.0, vwap=2560.0, change_pct=3.5, open=2520.0, high=2605.0, low=2515.0
        ),
    }
    chain = [
        SimpleNamespace(
            symbol="NSE:TCS26DEC2600CE",
            strike=2600.0,
            option_type="CE",
            last_price=92.0,
            volume=12000,
            oi=5000,
            oi_change=-800,
            pchange=25.0,
            expiry="2026-12-29",
            bid=91.5,
            ask=92.5,
        )
    ]
    monkeypatch.setattr("market.quotes.get_quote", lambda syms: quote_map)
    monkeypatch.setattr("market.indices.get_vix", lambda: 16.5)

    # 15:05 IST on 2026-11-26 (10m before 15:15 squareoff) -> suppressed!
    late_dt = datetime(2026, 11, 26, 15, 5, tzinfo=IST)
    res = detect_options_momentum_breakouts(
        targets=["TCS"],
        batch_quotes=quote_map,
        now_dt=late_dt,
        chains_map={"TCS": chain},
    )
    assert res == []


def test_signal_enrichment_attaches_confluence_score():
    """enrich_alert_with_feature_bus must populate confluence_score without extra REST calls."""
    alert = AutoAlert(
        alert_id="aa-options-momentum-tcs-ce-2580-0915-20261126",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="TCS",
        exchange="NFO",
        segment="FNO_STOCK",
        direction="BULLISH",
        headline="TCS 2580 CE",
        summary="IT breakout",
        ltp=95.0,
        trigger_level=95.0,
        stop_loss=80.0,
        target_level=125.0,
        underlying_spot=2590.0,
        metrics={
            "spot": 2590.0,
            "vwap": 2555.0,
            "rvol": 2.4,
            "spot_change_pct": 2.1,
            "rrg_quadrant": "LEADING",
        },
    )
    enriched = enrich_alert_with_feature_bus(alert)
    assert "confluence_score" in enriched
    assert alert.metrics["confluence_score"] > 0
    assert "confluence_report" in alert.details
    assert alert.confluence_alignment in ("HIGH_CONFLUENCE", "PARTIAL_CONFLUENCE")


def test_feature_bus_computes_tod_rvol_across_sessions():
    """Time-of-day normalized RVOL compares current bar against same (hour, minute) prior sessions."""
    from engine.feature_bus import clear_feature_bus_cache, compute_shared_features

    clear_feature_bus_cache()
    # Build 2 sessions with identical 5m timestamps (09:15..11:00)
    d1 = pd.date_range("2026-11-25 09:15", periods=20, freq="5min")
    d2 = pd.date_range("2026-11-26 09:15", periods=20, freq="5min")
    idx = d1.append(d2)
    vols = [1000.0] * 39 + [2600.0]  # Last bar at 10:50 is 2.6x prior day's 10:50 bar
    df = pd.DataFrame(
        {
            "open": [100.0] * 40,
            "high": [101.0] * 40,
            "low": [99.5] * 40,
            "close": [100.5] * 40,
            "volume": vols,
        },
        index=idx,
    )
    feats = compute_shared_features("TCS", df, use_cache=False)
    assert feats["status"] == "AVAILABLE"
    assert feats["tod_rvol"] == 2.6


def test_pre_inflection_dryup_intraday_15m_fno_staging():
    """Intraday 15m coil on an F&O stock emits STALK with FNO_STOCK/NFO metadata."""
    from engine.detectors.pre_inflection_dryup import detect_pre_inflection_dryup

    n = 30
    idx = pd.date_range("2026-11-26 09:15", periods=n, freq="15min")
    vols = [20000.0] * (n - 3) + [8000.0, 7500.0, 7000.0]
    df = pd.DataFrame(
        {
            "open": [1400.0] * n,
            "high": [1408.0] * (n - 3) + [1402.0, 1402.0, 1402.0],
            "low": [1392.0] * (n - 3) + [1398.0, 1398.0, 1398.0],
            "close": [1400.0] * n,
            "volume": vols,
        },
        index=idx,
    )
    alert = detect_pre_inflection_dryup("HCLTECH", df, 1400.0, timeframe="15m")
    assert alert is not None
    assert alert.stage == "STALK"
    assert alert.segment == "FNO_STOCK"
    assert alert.exchange == "NFO"
    assert alert.time_horizon == "INTRADAY"


def test_synthetic_sl_shields_healthy_option_on_shallow_spot_wick():
    """Healthy option premium (>= 0.96x entry) shields against shallow <0.25% spot micro-wick."""
    from engine.synthetic_sl import evaluate_synthetic_spot_sl

    alert = AutoAlert(
        alert_id="aa-trend-pullback-ultracemco-ce-12800-20261126",
        alert_type="TREND_DAY_PULLBACK",
        stage="IGNITED",
        symbol="ULTRACEMCO",
        exchange="NFO",
        segment="FNO_STOCK",
        direction="BULLISH",
        headline="ULTRACEMCO 12800 CE",
        summary="Test",
        ltp=322.0,
        trigger_level=322.0,
        option_premium=322.0,
        stop_loss=274.0,
        target_level=419.0,
        strike=12800.0,
        option_type="CE",
        contract_symbol="NSE:ULTRACEMCO26DEC12800CE",
        underlying_spot=12800.0,
        structural_spot_sl=12740.0,
        created_at="2026-11-26 11:00:00 IST",
    )
    # Shallow breach (-0.12% beyond anchor 12740 -> live_spot = 12725) with healthy option premium (315 >= 322*0.96=309.1)
    res_shield = evaluate_synthetic_spot_sl(
        alert, current_option_ltp=315.0, current_spot_override=12725.0
    )
    assert res_shield.is_invalidated is False
    assert res_shield.spot_distance_pct < 0

    # Deep structural breach (-0.50% beyond anchor -> live_spot = 12676) MUST still invalidate
    res_breach = evaluate_synthetic_spot_sl(
        alert, current_option_ltp=290.0, current_spot_override=12676.0
    )
    assert res_breach.is_invalidated is True


def test_adaptive_velocity_time_stop_morning_grace_and_fast_fade(monkeypatch):
    """Morning high-RVOL mild coils get 75m grace; dead-volume -9% fades scratch early at 35m."""
    import engine.alert_evaluator as ae_mod

    fixed_now = datetime(2026, 11, 26, 11, 30, 0, tzinfo=IST)

    class _MockDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now.astimezone(tz) if tz else fixed_now.replace(tzinfo=None)

    monkeypatch.setattr(ae_mod, "datetime", _MockDT)

    # Case 1: 50m elapsed, morning (<13:00), RVOL=1.45, mild -2% pullback -> grace extended (None)
    t_50 = (fixed_now - timedelta(minutes=50)).strftime("%Y-%m-%d %H:%M:%S IST")
    healthy_coil = AutoAlert(
        alert_id="aa-options-momentum-hcltech-ce-1420-0915-20261126",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="HCLTECH",
        exchange="NFO",
        direction="BULLISH",
        headline="HCLTECH 1420 CE",
        summary="Morning coil",
        option_type="CE",
        contract_symbol="NSE:HCLTECH26DEC1420CE",
        created_at=t_50,
        triggered_at=t_50,
        initial_entry_premium=50.0,
        trigger_level=50.0,
        option_premium=50.0,
        stop_loss=40.0,
        target_level=65.0,
        ltp=49.0,
        metrics={"rvol": 1.45},
    )
    healthy_coil._force_test_expiry = True
    assert ae_mod.evaluate_alert_invalidation(healthy_coil, current_ltp=49.0) is None

    # Case 2: 35m elapsed, dead volume (rvol=0.55) and -10% fade -> early scratch
    t_35 = (fixed_now - timedelta(minutes=35)).strftime("%Y-%m-%d %H:%M:%S IST")
    dead_fade = AutoAlert(
        alert_id="aa-options-momentum-dead-ce-100-0915-20261126",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="RECLTD",
        exchange="NFO",
        direction="BULLISH",
        headline="RECLTD 300 CE",
        summary="Dead fade",
        option_type="CE",
        contract_symbol="NSE:RECLTD26DEC300CE",
        created_at=t_35,
        triggered_at=t_35,
        initial_entry_premium=50.0,
        trigger_level=50.0,
        option_premium=50.0,
        stop_loss=38.0,
        target_level=65.0,
        ltp=45.0,
        metrics={"rvol": 0.55},
    )
    dead_fade._force_test_expiry = True
    reason = ae_mod.evaluate_alert_invalidation(dead_fade, current_ltp=45.0)
    assert reason is not None
    assert "Velocity Stagnation Time-Stop" in reason


def test_eod_report_uses_initial_stop_loss_and_isolates_neutral_condors(tmp_path, monkeypatch):
    """Ratcheted SL near entry must not inflate Realized R to -15R, and neutral condors stay 0.0R."""
    import json
    from engine.eod_report_generator import EODReportGenerator

    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))
    alerts = [
        {
            "alert_id": "aa-ratchet-test-1",
            "alert_type": "OPTIONS_MOMENTUM",
            "stage": "RUNNER_EXIT",
            "symbol": "TRENT",
            "contract_symbol": "NSE:TRENT26DEC3350CE",
            "segment": "FNO_STOCK",
            "direction": "BULLISH",
            "option_type": "CE",
            "strike": 3350.0,
            "ltp": 113.45,
            "trigger_level": 117.0,
            "stop_loss": 117.23,  # Ratcheted tight near entry
            "initial_stop_loss": 97.0,  # True initial risk = 20.0 pts
            "target_level": 162.5,
            "target_status": "RUNNER_CLOSED",
            "created_at": "2026-12-08 11:04:00 IST",
            "is_invalidated": False,
        },
        {
            "alert_id": "aa-neutral-condor-1",
            "alert_type": "DEFINED_RISK_NEUTRAL",
            "stage": "COMPLETED",
            "symbol": "SENSEX",
            "segment": "FNO_INDEX",
            "direction": "NEUTRAL",
            "ltp": 83938.0,
            "trigger_level": 84389.0,
            "stop_loss": 85401.0,
            "target_level": 78819.0,
            "target_status": "TARGET_ACHIEVED",
            "created_at": "2026-12-08 11:40:00 IST",
            "is_invalidated": False,
        },
    ]
    p = tmp_path / "auto_alerts.json"
    p.write_text(json.dumps(alerts), encoding="utf-8")
    report = EODReportGenerator(data_file=p).generate(target_date="2026-12-08")
    trent_row = next(j for j in report.journal_entries if "TRENT" in j.symbol)
    assert abs(trent_row.realized_r) <= 5.0
    condor_row = next(j for j in report.journal_entries if j.strategy == "DEFINED_RISK_NEUTRAL")
    assert condor_row.outcome == "NEUTRAL_CONDOR_MONITORED"
    assert condor_row.realized_r == 0.0


def test_dec7_rule_schedule_signal_helpers_effective_dated():
    """Dec 7 CAS dispersion stays INACTIVE before 2026-12-07 and activates inside 15:25-15:45 after."""
    from engine.rule_schedule_signals import (
        evaluate_cas_derivative_dispersion,
        evaluate_expiry_vwap_window,
    )

    pre_dec7 = datetime(2026, 11, 26, 15, 30, tzinfo=IST)
    assert (
        evaluate_cas_derivative_dispersion("NIFTY", 25920.0, 25884.0, pre_dec7)["status"]
        == "INACTIVE"
    )

    post_dec7 = datetime(2026, 12, 8, 15, 32, tzinfo=IST)
    disp = evaluate_cas_derivative_dispersion("NIFTY", 25950.0, 25900.0, post_dec7)
    assert disp["status"] == "AVAILABLE"
    assert disp["cas_active"] is True
    assert disp["dispersion_regime"] == "FUTURES_PREMIUM_EXPANSION"

    # Expiry 15:00-15:30 VWAP window
    idx = pd.date_range("2026-12-08 15:00", periods=4, freq="5min", tz=IST)
    df = pd.DataFrame(
        {
            "high": [25910.0, 25920.0, 25915.0, 25925.0],
            "low": [25890.0, 25900.0, 25900.0, 25905.0],
            "close": [25900.0, 25910.0, 25910.0, 25920.0],
            "volume": [1000.0, 1200.0, 1100.0, 1500.0],
        },
        index=idx,
    )
    vw_res = evaluate_expiry_vwap_window(
        "NIFTY", df, 25920.0, datetime(2026, 12, 8, 15, 16, tzinfo=IST), is_expiry=True
    )
    assert vw_res["status"] == "AVAILABLE"
    assert vw_res["vwap_1500"] > 0
    assert (
        evaluate_expiry_vwap_window(
            "NIFTY", df, 25920.0, datetime(2026, 12, 8, 15, 16, tzinfo=IST), is_expiry=False
        )["status"]
        == "INACTIVE"
    )


def test_capital_markets_and_fintech_sector_split():
    """Exchange/depository/wealth tickers and fintech tickers isolate from banking/IT caps."""
    from analysis.universe import get_stock_sector, resolve_sector_taxonomy
    from bot.alert_templates import shorten_sector_name

    for sym in ("BSE", "CDSL", "MCX", "KFINTECH", "ANANDRATHI", "ANGELONE", "360ONE", "MOTILALOFS"):
        sec_id, sec_name = get_stock_sector(sym)
        assert sec_id == "capital_markets", f"{sym} got {sec_id}"
        assert shorten_sector_name(sec_name, symbol=sym) == "Cap Mkts"

    for sym in ("POLICYBZR", "PAYTM", "ETERNAL", "SWIGGY"):
        sec_id, sec_name = get_stock_sector(sym)
        assert sec_id == "fintech_internet", f"{sym} got {sec_id}"
        assert shorten_sector_name(sec_name, symbol=sym) == "Fintech"

    assert get_stock_sector("HDFCBANK")[0] == "banking"
    assert get_stock_sector("TCS")[0] == "it"
    assert resolve_sector_taxonomy("capital markets")[0] == "capital_markets"
    assert resolve_sector_taxonomy("fintech")[0] == "fintech_internet"


def test_telegram_confluence_gate_and_trend_pullback_filter(monkeypatch):
    """Stock confluence <65 and non-elite TREND_DAY_PULLBACK are held in UI, not sent to Telegram."""
    from engine.alert_model import AutoAlert
    from engine.auto_alert_engine import AutoAlertEngine

    monkeypatch.delenv("TELEGRAM_ALLOW_TREND_DAY_PULLBACK", raising=False)
    monkeypatch.setenv("TELEGRAM_APEX_ONLY", "0")

    engine = AutoAlertEngine()

    low_conf_stk = AutoAlert(
        alert_id="aa-optmom-RELIANCE-20261126",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="RELIANCE",
        exchange="NFO",
        direction="BULLISH",
        headline="RELIANCE 1300 CE",
        summary="Options momentum",
        ltp=42.0,
        trigger_level=40.0,
        stop_loss=30.0,
        target_level=70.0,
        confidence=88,
        strike=1300.0,
        option_type="CE",
        metrics={"spot": 1295.0, "confluence_score": 45.0},
    )
    ok_low, reason_low = engine._eval_telegram_apex_gate(low_conf_stk, in_market=True)
    assert ok_low is False
    assert "confluence" in reason_low.lower()

    high_conf_stk = AutoAlert(
        alert_id="aa-optmom-RELIANCE-hi-20261126",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="RELIANCE",
        exchange="NFO",
        direction="BULLISH",
        headline="RELIANCE 1300 CE",
        summary="Options momentum",
        ltp=42.0,
        trigger_level=40.0,
        stop_loss=30.0,
        target_level=70.0,
        confidence=88,
        strike=1300.0,
        option_type="CE",
        metrics={"spot": 1295.0, "confluence_score": 74.0},
    )
    ok_hi, _ = engine._eval_telegram_apex_gate(high_conf_stk, in_market=True)
    assert ok_hi is True

    weak_pb = AutoAlert(
        alert_id="aa-tdpb-NIFTY-20261126",
        alert_type="TREND_DAY_PULLBACK",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY 25900 CE",
        summary="Trend day pullback",
        ltp=120.0,
        trigger_level=118.0,
        stop_loss=90.0,
        target_level=190.0,
        confidence=86,
        strike=25900.0,
        option_type="CE",
        metrics={"spot": 25910.0, "confluence_score": 70.0},
    )
    ok_pb_weak, reason_pb = engine._eval_telegram_apex_gate(weak_pb, in_market=True)
    assert ok_pb_weak is False
    assert "TREND_DAY_PULLBACK" in reason_pb

    elite_pb = AutoAlert(
        alert_id="aa-tdpb-NIFTY-elite-20261126",
        alert_type="TREND_DAY_PULLBACK",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY 25900 CE",
        summary="Trend day pullback",
        ltp=120.0,
        trigger_level=118.0,
        stop_loss=90.0,
        target_level=190.0,
        confidence=90,
        strike=25900.0,
        option_type="CE",
        metrics={"spot": 25910.0, "confluence_score": 82.0},
    )
    ok_pb_elite, _ = engine._eval_telegram_apex_gate(elite_pb, in_market=True)
    assert ok_pb_elite is True


def test_telegram_dispatch_recovers_root_id_and_fails_closed(monkeypatch):
    """Primary dispatch recovers root ID from registry or marks FAILED (never fake SENT) when push fails."""
    from unittest.mock import patch
    from engine.alert_model import AutoAlert
    from engine.auto_alert_engine import AutoAlertEngine

    monkeypatch.setenv("TELEGRAM_APEX_ONLY", "0")
    monkeypatch.delenv("CHANAKYA_TESTING", raising=False)
    monkeypatch.delenv("DEPLOY_MODE", raising=False)

    eng = AutoAlertEngine()
    eng._alerts = []
    eng._save = lambda *a, **kw: None
    eng._eval_telegram_apex_gate = lambda *a, **kw: (True, "allowed")

    a_fail = AutoAlert(
        alert_id="aa-optmom-TCS-fail-20261126",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="TCS",
        exchange="NFO",
        direction="BULLISH",
        headline="TCS 4100 CE",
        summary="Momentum",
        ltp=65.0,
        trigger_level=64.0,
        stop_loss=50.0,
        target_level=100.0,
        confidence=90,
        strike=4100.0,
        option_type="CE",
        is_live=True,
        environment="LIVE",
    )
    eng._alerts.append(a_fail)
    with (
        patch("engine.alerts._telegram_notify", return_value=False),
        patch("bot.telegram_bot.get_signal_message_id", return_value=None),
        patch("engine.alert_preferences.alert_preferences.is_alert_allowed", return_value=True),
    ):
        eng._dispatch(a_fail)

    assert a_fail.telegram_dispatched is False
    assert a_fail.telegram_delivery_status == "FAILED"
    assert a_fail.telegram_root_message_id is None

    a_rec = AutoAlert(
        alert_id="aa-optmom-INFY-rec-20261126",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="INFY",
        exchange="NFO",
        direction="BULLISH",
        headline="INFY 1900 CE",
        summary="Momentum",
        ltp=45.0,
        trigger_level=44.0,
        stop_loss=34.0,
        target_level=72.0,
        confidence=90,
        strike=1900.0,
        option_type="CE",
        is_live=True,
        environment="LIVE",
    )
    eng._alerts.append(a_rec)
    with (
        patch("engine.alerts._telegram_notify", return_value=None),
        patch("bot.telegram_bot.get_signal_message_id", return_value=778899),
        patch("engine.alert_preferences.alert_preferences.is_alert_allowed", return_value=True),
    ):
        eng._dispatch(a_rec)

    assert a_rec.telegram_dispatched is True
    assert a_rec.telegram_delivery_status == "SENT"
    assert a_rec.telegram_root_message_id == 778899
    assert a_rec.telegram_message_id == 778899


def test_telemetry_stage_history_prev_close_and_structural_spot_sl():
    """New alerts record stage_history transitions, prev_close, and directional structural_spot_sl."""
    from engine.alert_model import AutoAlert
    from engine.signal_enrichment import enrich_alert_with_feature_bus

    a_ce = AutoAlert(
        alert_id="aa-optmom-SBIN-20261126",
        alert_type="OPTIONS_MOMENTUM",
        stage="STALK",
        symbol="SBIN",
        exchange="NFO",
        direction="BULLISH",
        headline="SBIN 840 CE",
        summary="Setup",
        ltp=18.5,
        trigger_level=19.0,
        stop_loss=14.0,
        target_level=29.0,
        confidence=88,
        strike=840.0,
        option_type="CE",
        underlying_spot=842.0,
        structural_spot_sl=None,
    )
    a_ce.structural_spot_sl = None
    a_ce.ensure_initial_stage_history()
    assert a_ce.promote_stage("PRIMED", reason="Near trigger", ltp=18.9) is True
    assert a_ce.promote_stage("IGNITED", reason="Crossed trigger", ltp=19.2) is True
    assert [s["to_stage"] for s in a_ce.stage_history] == ["STALK", "PRIMED", "IGNITED"]

    enr = enrich_alert_with_feature_bus(
        a_ce,
        quotes_map={"NSE:SBIN": {"ltp": 842.0, "prev_close": 828.5}},
    )
    assert a_ce.metrics["prev_close"] == 828.5
    assert enr["prev_close"] == 828.5
    assert a_ce.structural_spot_sl is not None and a_ce.structural_spot_sl < 842.0

    # Symmetric PUT / BEARISH spot SL must sit ABOVE underlying spot
    a_pe = AutoAlert(
        alert_id="aa-optmom-SBIN-pe-20261126",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="SBIN",
        exchange="NFO",
        direction="BEARISH",
        headline="SBIN 840 PE",
        summary="Bear setup",
        ltp=20.0,
        trigger_level=20.0,
        stop_loss=15.0,
        target_level=32.0,
        confidence=88,
        strike=840.0,
        option_type="PE",
        underlying_spot=835.0,
        structural_spot_sl=None,
    )
    a_pe.structural_spot_sl = None
    enrich_alert_with_feature_bus(a_pe, quotes_map={"SBIN": {"prev_close": 845.0}})
    assert a_pe.structural_spot_sl is not None and a_pe.structural_spot_sl > 835.0

    # Neutral condor must NOT receive a directional spot SL override
    a_condor = AutoAlert(
        alert_id="aa-condor-NIFTY-20261126",
        alert_type="DEFINED_RISK_NEUTRAL",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="NEUTRAL",
        headline="NIFTY IRON CONDOR",
        summary="Neutral",
        ltp=25900.0,
        trigger_level=25900.0,
        stop_loss=0.0,
        target_level=0.0,
        confidence=86,
        strike=25900.0,
        underlying_spot=25900.0,
    )
    a_condor.structural_spot_sl = None
    enrich_alert_with_feature_bus(a_condor)
    assert a_condor.structural_spot_sl is None


def test_full_nse_bse_fno_sector_alignment_and_zero_split_brain(monkeypatch):
    """All BSE/F&O/Insurance/PSU-Bank/Fintech/Index tickers resolve consistently across universe & sector_rotation."""
    import json
    from pathlib import Path
    from analysis import universe, sector_rotation
    from market.instruments import STANDARD_LOT_SIZES

    monkeypatch.setattr("analysis.fundamental.analyse", lambda sym: None)

    # 1. Explicit taxonomy splits must agree across universe.py & sector_rotation.py
    expected = {
        "BSE": ("capital_markets", "CAPITAL_MARKETS"),
        "MCX": ("capital_markets", "CAPITAL_MARKETS"),
        "CDSL": ("capital_markets", "CAPITAL_MARKETS"),
        "KFINTECH": ("capital_markets", "CAPITAL_MARKETS"),
        "ANANDRATHI": ("capital_markets", "CAPITAL_MARKETS"),
        "HDFCLIFE": ("insurance", "FIN_SERV"),
        "SBILIFE": ("insurance", "FIN_SERV"),
        "ICICIGI": ("insurance", "FIN_SERV"),
        "LICI": ("insurance", "FIN_SERV"),
        "POLICYBZR": ("fintech_internet", "FINTECH"),
        "PAYTM": ("fintech_internet", "FINTECH"),
        "ETERNAL": ("fintech_internet", "FINTECH"),
        "SWIGGY": ("fintech_internet", "FINTECH"),
        "SBIN": ("banking", "PSU_BANK"),
        "BANKINDIA": ("banking", "PSU_BANK"),
        "MAHABANK": ("banking", "PSU_BANK"),
        "TCS": ("it", "IT"),
        "INFY": ("it", "IT"),
        "HDFCBANK": ("banking", "BANK"),
    }
    for sym, (u_exp, sr_exp) in expected.items():
        u_id, _ = universe.get_stock_sector(sym)
        assert u_id == u_exp, f"{sym} universe={u_id} != {u_exp}"
        assert sector_rotation.STOCK_SECTOR_MAP.get(sym) == sr_exp
        assert sector_rotation.get_stock_sector_alignment(sym, rrg_matrix={}).sector == sr_exp

    # 2. Indices must classify as "index", never "broad_market"
    for idx_sym in ("NIFTY", "NIFTY 50", "BANKNIFTY", "SENSEX", "BANKEX", "FINNIFTY"):
        assert universe.get_stock_sector(idx_sym)[0] == "index"

    # 3. Zero F&O / Nifty500 / BSE500 stocks fall back to broad_market
    for fn in ("bse500.json", "nifty500.json", "nifty_total_market.json"):
        rows = json.loads((Path("data/universes") / fn).read_text(encoding="utf-8"))
        unmapped = [
            r["symbol"].strip().upper()
            for r in rows
            if isinstance(r, dict)
            and r.get("symbol")
            and universe.get_stock_sector(r["symbol"])[0] == "broad_market"
        ]
        assert unmapped == [], f"{fn} unmapped broad_market symbols: {unmapped}"

    fno_unmapped = [
        s for s in STANDARD_LOT_SIZES if universe.get_stock_sector(s)[0] == "broad_market"
    ]
    assert fno_unmapped == [], f"F&O STANDARD_LOT_SIZES unmapped symbols: {fno_unmapped}"


def test_early_rvol_breakout_and_bse_quote_prioritization(monkeypatch):
    """Early RVOL breakouts (+0.55% at 2.3x RVOL) prioritize before stale moves & support BSE: keys."""
    from types import SimpleNamespace
    from engine.auto_alert_engine import AutoAlertEngine

    eng = AutoAlertEngine()
    eng._watched_indices = ["NIFTY", "SENSEX"]
    eng._watched_equities = ["FLAT1", "FLAT2", "BSE", "MCX", "TCS"]
    eng._override_watched_equities = True

    quotes = {
        "BSE:BSE": SimpleNamespace(
            last_price=2415.0, open=2400.0, change_pct=0.55, rvol=2.4, volume=900000
        ),
        "NSE:MCX": SimpleNamespace(
            last_price=6150.0, open=6100.0, change_pct=1.40, rvol=1.9, volume=600000
        ),
        "NSE:TCS": SimpleNamespace(
            last_price=4120.0, open=4110.0, change_pct=0.45, rvol=2.3, volume=1800000
        ),
        "NSE:FLAT1": SimpleNamespace(
            last_price=100.0, open=100.0, change_pct=0.05, rvol=0.7, volume=10000
        ),
        "NSE:FLAT2": SimpleNamespace(
            last_price=200.0, open=200.0, change_pct=0.10, rvol=0.8, volume=10000
        ),
    }
    monkeypatch.setattr(
        "engine.auto_alert_engine.AutoAlertEngine._get_cycle_quotes", lambda self, *a, **kw: quotes
    )

    targets = eng._get_prioritized_targets(max_targets=5, quotes_map=quotes, stagger_rotate=False)
    assert "BSE" in targets
    assert "MCX" in targets
    assert "TCS" in targets
    assert "FLAT1" not in targets


def test_forensic_financial_classification_and_indices_sync(monkeypatch):
    """Capital markets & insurance route through financial forensic path & indices map RRG keys."""
    from analysis.forensic import audit_company_forensics
    from analysis.universe import get_stock_sector
    from analysis.sector_rotation import NSE_SECTORS
    from market.indices import INDEX_INSTRUMENTS, _YF_SECTOR_MAP

    for sec_key in NSE_SECTORS:
        if sec_key != "BROAD_MARKET":
            assert sec_key in INDEX_INSTRUMENTS, f"{sec_key} missing from INDEX_INSTRUMENTS"
            assert sec_key in _YF_SECTOR_MAP or sec_key == "BANK", (
                f"{sec_key} missing from _YF_SECTOR_MAP"
            )

    # Financial forensic check: financial/capital_markets/insurance entities omit Altman working_capital requirement
    monkeypatch.setattr("analysis.forensic.fetch_reported_accounting_inputs", lambda s: {})
    for sym in ("BSE", "MCX", "HDFCLIFE"):
        res = audit_company_forensics(sym)
        assert not any("Altman" in r for r in res.unavailable_reasons), (
            f"{sym} ({get_stock_sector(sym)[0]}) triggered manufacturing Altman requirement: {res.unavailable_reasons}"
        )


def test_neutral_not_blocked_by_unignited_stalk_watch(monkeypatch):
    """Unignited STALK/EARLY_WARNING directional watch must not suppress neutral Iron Condors."""
    import pandas as pd
    from engine.alert_model import AutoAlert
    from engine.auto_alert_engine import AutoAlertEngine

    eng = AutoAlertEngine()
    eng._watched_indices = []
    eng._watched_equities = ["TCS"]
    eng._override_watched_equities = True
    eng._alerts = [
        AutoAlert(
            alert_id="aa-stalk-TCS-20261126",
            alert_type="PRE_INFLECTION_DRYUP",
            stage="STALK",
            symbol="TCS",
            exchange="NSE",
            direction="BULLISH",
            headline="TCS STALK",
            summary="Unignited watch",
            ltp=4100.0,
            trigger_level=4150.0,
            stop_loss=4050.0,
            target_level=4300.0,
            confidence=82,
        )
    ]

    df_15m = pd.DataFrame(
        {
            "open": [4095.0, 4102.0] * 12,
            "high": [4108.0, 4108.0] * 12,
            "low": [4092.0, 4092.0] * 12,
            "close": [4104.0, 4096.0] * 12,
            "volume": [10000] * 24,
        },
        index=pd.date_range("2026-11-26 09:30", periods=24, freq="15min"),
    )
    called_syms: list[str] = []

    def _fake_neutral(ctx):
        called_syms.append(ctx.canonical_symbol)
        return None

    monkeypatch.setattr(
        "engine.detectors.defined_risk_neutral.detect_defined_risk_neutral", _fake_neutral
    )
    monkeypatch.setattr("market.indices.get_vix", lambda: 13.0)
    eng.scan_defined_risk_neutral(
        quotes_map={
            "NSE:TCS": type(
                "Q",
                (),
                {"last_price": 4100.0, "prev_close": 4098.0, "change_pct": 0.05, "volume": 500000},
            )()
        },
        ohlcv_map={"TCS:15m": df_15m},
        targets=["TCS"],
    )
    assert "TCS" in called_syms


def test_fno_priority_default_zero_unmapped_cash_and_ui_slot_recovery(monkeypatch):
    """FNO_PRIORITY is default, offline cash universe maps cleanly, and invalidated options free UI quota."""
    from datetime import datetime
    from unittest.mock import patch
    from config.constants import SESSION_FOCUS_MODE, IST
    from config.discovery_policy import get_discovery_policy
    from analysis import universe
    from engine.alert_model import AutoAlert
    from engine.auto_alert_engine import AutoAlertEngine

    monkeypatch.delenv("SESSION_FOCUS_MODE", raising=False)
    monkeypatch.setattr("analysis.fundamental.analyse", lambda sym: None)

    assert SESSION_FOCUS_MODE == "FNO_PRIORITY"
    pol = get_discovery_policy()
    assert pol.profile == "FNO_PRIORITY"
    assert pol.allows("CASH") is True
    assert pol.allows("FNO_STOCK") is True

    # Verify key cash/capital-market/media/chemical NSE equities map offline cleanly (never broad_market)
    for cash_sym, exp_sec in (
        ("ARSSBL", "capital_markets"),
        ("BIRLAMONEY", "capital_markets"),
        ("CARERATING", "capital_markets"),
        ("ICRA", "capital_markets"),
        ("PNBGILTS", "capital_markets"),
        ("ALEMBICLTD", "pharma"),
        ("ASTEC", "pharma"),
        ("GALAXYSURF", "chemicals"),
        ("CAMLINFINE", "chemicals"),
        ("MTNL", "telecom"),
        ("NDTV", "telecom"),
        ("EASEMYTRIP", "telecom"),
        ("RAYMOND", "fmcg"),
        ("EMUDHRA", "it"),
    ):
        got_sec = universe.get_stock_sector(cash_sym)[0]
        assert got_sec == exp_sec, f"{cash_sym}: expected {exp_sec}, got {got_sec}"

    # Verify invalidated OPTIONS_MOMENTUM setup frees its daily sector UI slot
    from collections import defaultdict

    now_dt = datetime(2026, 11, 26, 11, 30, tzinfo=IST)
    today_key = "2026-11-26"
    eng = AutoAlertEngine()
    eng._sector_ui_counts = defaultdict(lambda: defaultdict(int))
    eng._sector_ui_counts[today_key]["capital_markets"] = 5
    dead = AutoAlert(
        alert_id="aa-dead-bse",
        alert_type="OPTIONS_MOMENTUM",
        stage="INVALIDATED",
        symbol="BSE",
        exchange="NFO",
        direction="BULLISH",
        headline="Dead BSE",
        summary="Invalidated without target",
        ltp=100.0,
        trigger_level=100.0,
        stop_loss=80.0,
        target_level=150.0,
        confidence=88,
        metrics={"sector_id": "capital_markets"},
        created_at=f"{today_key} 09:35:00 IST",
    )
    dead.is_invalidated = True
    eng._alerts = [dead]

    fresh_bse = AutoAlert(
        alert_id="aa-fresh-bse",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="BSE",
        exchange="NFO",
        direction="BULLISH",
        headline="Fresh BSE CE",
        summary="Fresh breakout",
        ltp=110.0,
        trigger_level=110.0,
        stop_loss=90.0,
        target_level=170.0,
        confidence=92,
        strike=2450.0,
        option_type="CE",
        contract_symbol="NSE:BSE26NOV2450CE",
        metrics={"sector_id": "capital_markets", "vol_oi_ratio": 2.5},
        created_at=now_dt.strftime("%Y-%m-%d %H:%M:%S IST"),
    )
    with patch(
        "engine.detectors.options_momentum.detect_options_momentum_breakouts",
        return_value=[fresh_bse],
    ):
        with patch.object(eng, "record_alert", return_value=True):
            with patch("engine.auto_alert_engine.datetime") as mock_dt:
                mock_dt.now.return_value = now_dt
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                res = eng.scan_options_momentum_breakouts()
    assert len(res) == 1 and res[0].symbol == "BSE"
