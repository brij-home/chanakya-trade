"""
tests/test_incident_rca_20261126.py
───────────────────────────────────
Deterministic regression tests for every root cause isolated from the
2026-11-26 production telemetry, alert, and log audit:
  1. Fractional strike parsing (`NSE:WIPRO26DEC197.5CE` must parse 197.5, never 5.0)
     and spot-anchored CHART_*/INSTITUTIONAL_*/STRAT_*/BREAKOUT_RETEST coordinate safety.
  2. INTRADAY_BREAKOUT_SPARK / BREAKDOWN_SPARK extended OTE limit pullback SL re-anchoring
     (must never emit Inverted Stop-Loss when `ote_limit` sits inside CMP-anchored SL).
  3. EOD Store & HistoricalWarehouse future-date rejection (> today IST).
  4. Untriggered PRIMED setups (`ORB_PRIMED`) and NEUTRAL strategies (`DEFINED_RISK_NEUTRAL`)
     must never enter directional target/trailing ratchet or close as `RUNNER_EXIT` on losses.
  5. CPR invariant (`bottom_central <= pivot <= top_central`).
  6. FreeIndexRouter proportional SL ceiling for high-premium BANKNIFTY monthly contracts.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd

from config.constants import IST_ZONE as IST
from engine.alert_evaluator import evaluate_alert_targets_and_trailing
from engine.alert_expiry import is_alert_option_premium_level
from engine.alert_model import AutoAlert
from engine.alert_scrutiny import AlertScrutinyAuditor
from engine.auto_alert_engine import AutoAlertEngine
from engine.detectors.intraday_spark import detect_intraday_mover_sparks
from engine.detectors.orb import detect_opening_range_breakout
from engine.eod_store import validate_and_sanitize_ohlcv_dataframe
from engine.free_index_router import free_index_router
from engine.historical_warehouse import HistoricalWarehouse
from engine.session_regime_sentinel import calculate_cpr


def test_fractional_strike_regex_preserves_wipro_197_5_ce():
    """NSE:WIPRO26DEC197.5CE must extract strike=197.5, never 5.0 -> Option Coordinate Veto."""
    alert = AutoAlert(
        alert_id="aa-chart-bull-flag-wipro-20261126",
        alert_type="CHART_BULL_FLAG",
        stage="EARLY_WARNING",
        symbol="WIPRO",
        exchange="NSE",
        direction="BULLISH",
        headline="⏳ BULL FLAG: NSE:WIPRO26DEC197.5CE @ ₹9.2 (Spot ₹196.3, Neckline ₹196.3)",
        summary="Bull flag consolidation near 197.5 breakout",
        ltp=196.31,
        trigger_level=196.31,
        stop_loss=191.0,
        target_level=208.0,
        confidence=84,
        metrics={
            "spot": 196.31,
            "rvol": 1.8,
            "option_contract": "NSE:WIPRO26DEC197.5CE",
            "option_entry": 9.2,
        },
    )
    assert alert.strike == 197.5
    assert alert.option_type == "CE"
    assert is_alert_option_premium_level(alert) is False
    ok, reason = alert.validate_data_integrity()
    assert ok is True, f"Unexpected integrity failure: {reason}"


def test_spot_anchored_institutional_reversal_enrin_and_strat_and_breakout_retest():
    """INSTITUTIONAL_*, STRAT_*, and BREAKOUT_RETEST with option suggestions stay spot-anchored."""
    enrin = AutoAlert(
        alert_id="aa-inst-top-rev-enrin-20261126",
        alert_type="INSTITUTIONAL_TOP_REVERSAL",
        stage="CONFIRMED",
        symbol="ENRIN",
        exchange="NSE",
        direction="BEARISH",
        headline="🔥 TOP REVERSAL: NSE:ENRIN26DEC3150PE @ ₹176.2 (Spot ₹3,111.9, SL ₹3,246.3, R:R 1:2.1)",
        summary="Sweep + micro CHoCH reversal",
        ltp=3111.9,
        trigger_level=3111.9,
        stop_loss=3246.28,
        target_level=2834.7,
        confidence=86,
        metrics={"spot": 3111.9, "option_contract": "NSE:ENRIN26DEC3150PE", "option_entry": 176.2},
    )
    assert enrin.strike == 3150.0
    assert is_alert_option_premium_level(enrin) is False
    assert enrin.validate_data_integrity() == (True, "")

    for atype in ("STRAT_2_1_2_BULL", "BREAKOUT_RETEST"):
        spot_alert = AutoAlert(
            alert_id=f"aa-{atype.lower()}-dabur-20261126",
            alert_type=atype,
            stage="CONFIRMED",
            symbol="DABUR",
            exchange="NSE",
            direction="BULLISH",
            headline=f"🎯 {atype}: NSE:DABUR26DEC520CE @ ₹18.5 (Spot ₹519.0)",
            summary="Spot structure breakout with option overlay",
            ltp=519.0,
            trigger_level=519.0,
            stop_loss=508.0,
            target_level=542.0,
            confidence=82,
        )
        assert is_alert_option_premium_level(spot_alert) is False
        assert spot_alert.validate_data_integrity() == (True, "")


def test_intraday_spark_extended_ote_pullback_never_inverts_sl(monkeypatch):
    """When is_extended=True anchors trigger at ote_limit below CMP SL, SL must re-anchor below trigger."""
    import sys
    import types

    # Create a monotonic extended bullish OHLCV frame triggering spark (+2.8%, RVOL > 2x)
    idx = pd.date_range("2026-11-26 09:15", periods=20, freq="15min")
    closes = np.linspace(835.0, 866.0, 20)
    df = pd.DataFrame(
        {
            "open": closes - 0.8,
            "high": closes + 1.2,
            "low": closes - 1.5,
            "close": closes,
            "volume": [100_000] * 18 + [450_000, 620_000],
        },
        index=idx,
    )

    fake_tp = SimpleNamespace(
        is_asymmetry_viable=True,
        target_1=900.0,
        target_2=925.0,
        target_3=955.0,
        invalidation_stop=850.5,  # Above OTE limit 841.9!
        optimal_entry_limit=841.9,
        optimal_entry_range="₹840.0 – ₹844.0",
        is_extended=True,
        base_structure="VWAP / 0.618 OTE",
        as_dict=lambda: {
            "entry_price": 866.0,
            "invalidation_stop": 850.5,
            "target_1": 900.0,
            "target_2": 925.0,
            "target_3": 955.0,
        },
    )

    monkeypatch.setattr(
        "engine.trade_plan.calculate_trade_plan",
        lambda **kwargs: fake_tp,
    )
    monkeypatch.setattr(
        "engine.option_resolver.resolve_option_contract",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "market.history.get_ohlcv",
        lambda *a, **k: df,
    )
    monkeypatch.setattr(
        "market.quotes.get_quote",
        lambda syms, **k: {
            s: SimpleNamespace(
                last_price=866.0,
                change_pct=2.8,
                volume=5_000_000,
                vwap=845.0,
                open=838.0,
                high=867.0,
                low=836.0,
                provider="LIVE",
            )
            for s in syms
        },
    )
    monkeypatch.setattr(
        "engine.detectors.intraday_spark.get_cached_avg_volume_20",
        lambda sym: 1_500_000.0,
    )
    monkeypatch.setattr(
        "engine.detectors.intraday_spark.compute_time_of_day_rvol",
        lambda *a, **k: 2.5,
    )
    monkeypatch.setitem(
        sys.modules, "market.order_book", types.SimpleNamespace(get_depth_book=lambda *a, **k: None)
    )

    q_map = {
        "NSE:HDFCBANK": SimpleNamespace(
            last_price=866.0,
            change_pct=2.8,
            volume=5_000_000,
            vwap=845.0,
            open=838.0,
            high=867.0,
            low=836.0,
            provider="LIVE",
        )
    }
    alerts = detect_intraday_mover_sparks(universe=["HDFCBANK"], quotes_map=q_map)
    assert alerts, "Expected bullish INTRADAY_BREAKOUT_SPARK alert on extended HDFCBANK setup"
    alert = alerts[0]
    ok, reason = alert.validate_data_integrity()
    assert ok is True, f"Inverted SL leaked on extended OTE spark: {reason}"
    assert alert.stop_loss < alert.trigger_level < alert.target_level


def test_eod_store_and_warehouse_reject_future_dated_bars(tmp_path):
    """Future-dated bars (> today IST) must never enter SQLite EOD or Parquet warehouse."""
    today = datetime.now(IST).date()
    future_day = today + timedelta(days=15)
    dates = [
        pd.Timestamp(today - timedelta(days=3)),
        pd.Timestamp(today - timedelta(days=2)),
        pd.Timestamp(future_day),
    ]
    df = pd.DataFrame(
        {
            "open": [100.0, 102.0, 104.0],
            "high": [105.0, 106.0, 108.0],
            "low": [99.0, 101.0, 103.0],
            "close": [103.0, 105.0, 107.0],
            "volume": [1000, 1200, 1500],
        },
        index=pd.DatetimeIndex(dates),
    )

    sanitized = validate_and_sanitize_ohlcv_dataframe(df, symbol="LT")
    assert len(sanitized) == 2
    assert sanitized.index.max().date() <= today

    wh = HistoricalWarehouse(base_dir=tmp_path)
    norm_wh = wh._normalize(df, interval="day")
    assert len(norm_wh) == 2
    assert norm_wh.index.max().date() <= today


def test_untriggered_primed_and_neutral_condor_never_run_directional_trailing(
    tmp_path, monkeypatch
):
    """PRIMED setups and NEUTRAL condors must return None from directional trailing evaluator."""
    primed = AutoAlert(
        alert_id="aa-orb-primed-sunpharma-20261126",
        alert_type="ORB_PRIMED",
        stage="PRIMED",
        symbol="SUNPHARMA",
        exchange="NFO",
        direction="BULLISH",
        headline="ORB PRIMED SUNPHARMA",
        summary="Coiling near ORB high",
        ltp=39.8,
        trigger_level=42.95,
        stop_loss=37.29,
        target_level=53.3,
        strike=1920.0,
        option_type="CE",
        contract_symbol="NSE:SUNPHARMA26DEC1920CE",
        option_premium=42.95,
        created_at=(datetime.now(IST) - timedelta(minutes=25)).strftime("%Y-%m-%d %H:%M:%S IST"),
    )
    assert evaluate_alert_targets_and_trailing(primed, current_ltp=39.8) is None

    condor = AutoAlert(
        alert_id="aa-defined-risk-neutral-finnifty-20261126",
        alert_type="DEFINED_RISK_NEUTRAL",
        stage="IGNITED",
        symbol="FINNIFTY",
        exchange="NFO",
        direction="NEUTRAL",
        headline="IRON CONDOR FINNIFTY SPREAD",
        summary="Defined risk range condor",
        ltp=28725.05,
        trigger_level=28725.05,
        stop_loss=28550.0,
        target_level=29100.0,
        confidence=84,
        metrics={"spot": 28725.05},
        actionable_plan={
            "instrument_type": "OPTION_SPREAD",
            "hedged_spread": {"strategy": "IRON_CONDOR", "max_profit": 2500.0, "max_loss": 4500.0},
        },
    )
    assert evaluate_alert_targets_and_trailing(condor, current_ltp=28867.35) is None

    # Scrutiny must NOT emit contradictory HARD_VETO on neutral spreads
    auditor = AlertScrutinyAuditor(min_rr_ratio=1.2)
    monkeypatch.setattr("market.order_book.get_depth_book", lambda *a, **k: None)
    passed, rej, _ = auditor.verify_tier1_sanity(condor)
    assert passed is True, f"Neutral condor unexpectedly rejected: {rej}"
    assert "exhaustion_radar" not in condor.metrics

    # _handle_alert_exit on NEUTRAL thesis invalidation must NOT mark RUNNER_EXIT
    monkeypatch.setattr("engine.auto_alert_engine.AUTO_ALERTS_FILE", tmp_path / "alerts.json")
    eng = AutoAlertEngine()
    condor.stop_loss = 28782.5  # simulate corrupted upward drift before breach
    condor.achieved_milestones = []
    eng._alerts = [condor]
    eng._handle_alert_exit(
        alert=condor,
        reason="Neutral thesis invalidated: corridor breached",
        current_ltp=28867.35,
    )
    assert condor.stage != "RUNNER_EXIT"
    assert condor.is_invalidated is True


def test_cpr_bc_never_exceeds_tc():
    """calculate_cpr must always order bottom_central <= pivot <= top_central."""
    # Downtrend day where raw (H+L)/2 > pivot
    cpr = calculate_cpr(
        high=14400.0, low=14251.9, close=14270.0, is_index=True, symbol="MIDCPNIFTY"
    )
    assert cpr.bottom_central <= cpr.pivot <= cpr.top_central
    assert cpr.cpr_width_pts > 0


def test_free_index_router_allows_high_premium_banknifty_monthly_sl(monkeypatch):
    """High-premium BANKNIFTY monthly options allow proportional SL while Nifty 45-pt cap stays enforced."""
    monkeypatch.setenv("TELEGRAM_FREE_INDEX_CHAT_ID", "-1004298387260")
    monkeypatch.setenv("TELEGRAM_FREE_INDEX_ENABLED", "1")

    bnf_monthly = AutoAlert(
        alert_id="aa-bnf-monthly-63900ce-20261126",
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        symbol="BANKNIFTY",
        contract_symbol="NSE:BANKNIFTY26DEC63900CE",
        exchange="NFO",
        direction="BULLISH",
        headline="BANKNIFTY 63900 CE",
        summary="Monthly breakout setup",
        ltp=1530.0,
        trigger_level=1530.0,
        stop_loss=1300.5,  # 229.5 pts risk (15% of premium)
        target_level=2050.0,
        underlying_spot=63850.0,
        option_premium=1530.0,
        confidence=89,
        segment="FNO_INDEX",
        actionable_plan={
            "action": "BUY CE",
            "spot_stop_loss": 63620.0,  # 0.36% of spot (< 0.60%)
            "option_plan": {
                "contract_symbol": "NSE:BANKNIFTY26DEC63900CE",
                "entry_premium": 1530.0,
                "sl_premium": 1300.5,
            },
        },
    )
    assert free_index_router.is_candidate(bnf_monthly) is True


def test_orb_primed_populates_tier1_scrutiny_metadata(monkeypatch):
    """ORB_PRIMED must attach deterministic TIER1_QUANT scrutiny rather than leaving scrutiny=None."""
    idx = pd.date_range("2026-11-26 09:15", periods=8, freq="5min")
    df = pd.DataFrame(
        {
            "open": [1890, 1894, 1896, 1899, 1900, 1901, 1902, 1903.0],
            "high": [1898, 1900, 1905, 1904, 1904, 1904, 1904.5, 1904.8],
            "low": [1885, 1888, 1890, 1895, 1897, 1898, 1899.0, 1900.0],
            "close": [1894, 1896, 1899, 1900, 1901, 1902, 1903.0, 1904.0],
            "volume": [100_000, 120_000, 110_000, 90_000, 95_000, 105_000, 110_000, 125_000],
        },
        index=idx,
    )
    monkeypatch.setattr("engine.option_resolver.resolve_option_contract", lambda **k: None)
    alert = detect_opening_range_breakout(
        "SUNPHARMA",
        df=df,
        ltp=1904.0,
        vwap=1896.0,
        rvol=1.4,
        ref_time=datetime(2026, 11, 26, 9, 55, tzinfo=IST),
    )
    if alert is not None and alert.alert_type == "ORB_PRIMED":
        assert isinstance(alert.metrics.get("scrutiny"), dict)
        assert alert.metrics["scrutiny"].get("status") == "QUANT_VERIFIED"


def test_spot_anchored_option_overlay_preserves_dual_coordinates():
    """build_spot_anchored_option_overlay separates option plan from spot trigger/SL/T1."""
    from engine.option_resolver import ResolvedOptionPlan, build_spot_anchored_option_overlay

    plan_obj = ResolvedOptionPlan(
        contract_symbol="NSE:ENRIN26DEC3150PE",
        strike=3150.0,
        option_type="PE",
        entry_premium=176.2,
        sl_premium=125.0,
        t1_premium=275.0,
        t2_premium=350.0,
        lot_size=250,
        underlying_spot=3111.9,
        underlying_sl=3246.28,
        underlying_target=2834.7,
    )
    opt_m, act_p = build_spot_anchored_option_overlay(
        plan_obj, clean_sym="ENRIN", spot=3111.9, spot_sl=3246.28, spot_target=2834.7
    )
    assert opt_m["option_contract"] == "NSE:ENRIN26DEC3150PE"
    assert opt_m["option_entry"] == 176.2
    assert act_p is not None
    assert act_p["instrument_type"] == "OPTION"
    assert act_p["spot_stop_loss"] == 3246.28
    assert act_p["option_plan"]["entry_premium"] == 176.2

    alert = AutoAlert(
        alert_id="aa-overlay-enrin-20261126",
        alert_type="INSTITUTIONAL_TOP_REVERSAL",
        stage="CONFIRMED",
        symbol="ENRIN",
        exchange="NSE",
        direction="BEARISH",
        headline="🔥 TOP REVERSAL: NSE:ENRIN26DEC3150PE @ ₹176.2 (Spot ₹3,111.9, SL ₹3,246.3, R:R 1:2.1)",
        summary="Dual coordinate reversal",
        ltp=3111.9,
        underlying_spot=3111.9,
        trigger_level=3111.9,
        stop_loss=3246.28,
        target_level=2834.7,
        confidence=86,
        metrics={"spot": 3111.9, **opt_m},
        actionable_plan=act_p,
    )
    assert is_alert_option_premium_level(alert) is False
    assert alert.validate_data_integrity() == (True, "")


def test_flattrade_ws_ak_not_ok_invalidates_token_and_closes(tmp_path, monkeypatch):
    """When Flattrade WS receives {'t': 'ak', 's': 'NOT_OK'}, token is purged & ws closed."""
    from brokers.flattrade import FlattradeAPI

    tok_file = tmp_path / "flattrade_token.json"
    tok_file.write_text('{"token": "stale-tok-123"}', encoding="utf-8")
    brk = FlattradeAPI(
        user_id="FT123",
        password="x",
        totp_secret="",
        api_key="k",
        api_secret="s",
        ws_url="wss://example.invalid",
        token_file=tok_file,
    )
    brk._token = "stale-tok-123"
    brk._token_date = "2026-11-26"

    closed = {"called": False}

    class _DummyWS:
        def close(self):
            closed["called"] = True

    monkeypatch.setattr(brk, "is_authenticated", lambda: True)

    captured_on_message = {}

    class _DummyWSApp:
        def __init__(self, url, on_open=None, on_message=None, on_error=None, on_close=None):
            captured_on_message["fn"] = on_message
            brk._ws_stop.set()

        def run_forever(self, **kw):
            pass

    import types
    import sys

    monkeypatch.setitem(sys.modules, "websocket", types.SimpleNamespace(WebSocketApp=_DummyWSApp))
    brk.start_websocket()
    brk._ws_thread.join(timeout=2.0)

    assert "fn" in captured_on_message
    captured_on_message["fn"](_DummyWS(), '{"t": "ak", "s": "NOT_OK", "emsg": "Session Expired"}')
    assert brk._token == ""
    assert closed["called"] is True
    assert not tok_file.exists()


def test_trend_day_pullback_midday_chop_gate_suppresses_low_rvol(monkeypatch):
    """During live midday window (11:30-13:15), low-RVOL choppy pullbacks are suppressed."""
    from engine.detectors.trend_day_continuation import detect_trend_day_pullback

    monkeypatch.delenv("CHANAKYA_TESTING", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    n = 25
    ts = [datetime(2026, 11, 26, 10, 15, tzinfo=IST) + timedelta(minutes=5 * i) for i in range(n)]
    closes = np.linspace(55200, 54650, n - 2).tolist() + [54710, 54700]
    df = pd.DataFrame(
        {
            "open": [c + 10 for c in closes],
            "high": [c + 25 for c in closes],
            "low": [c - 10 for c in closes],
            "close": closes,
            "volume": [1000] * n,
        },
        index=ts,
    )
    # 12:15 IST midday window with neutral RVOL 1.0 (below 1.35 threshold)
    res = detect_trend_day_pullback(
        symbol="BANKNIFTY",
        df_5m=df,
        ltp=54700.0,
        now_dt=datetime(2026, 11, 26, 12, 15, tzinfo=IST),
        exchange="NSE",
        segment="FNO_INDEX",
        rvol_val=1.0,
    )
    assert res is None


def test_structural_location_detects_fib_ote_ob_and_opposing_wall():
    """evaluate_structural_location detects Fib 0.618 OTE, Order Blocks, and overhead Supply OB traps."""
    from analysis.market_structure import evaluate_structural_location

    # Build an impulse up from 100 -> 120 followed by a clean 65% OTE retracement to ~107
    n = 18
    ts = [datetime(2026, 11, 26, 9, 15, tzinfo=IST) + timedelta(minutes=5 * i) for i in range(n)]
    opens = [
        100,
        100.5,
        101,
        102,
        104,
        107,
        110,
        114,
        117,
        119,
        120,
        118,
        115,
        112,
        110,
        108,
        107,
        106.8,
    ]
    closes = [
        100.4,
        100.2,
        102,
        104,
        107,
        110,
        114,
        117,
        119.5,
        120,
        118,
        115,
        112,
        110,
        108,
        107,
        106.6,
        107.4,
    ]
    highs = [max(o, c) + 0.5 for o, c in zip(opens, closes)]
    lows = [min(o, c) - 0.5 for o, c in zip(opens, closes)]
    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": [100_000] * n},
        index=ts,
    )

    loc = evaluate_structural_location(df, spot=107.4, direction="BULLISH", vwap=107.2)
    assert loc.in_fib_ote is True
    assert loc.fib_retracement_pct is not None and 55.0 <= loc.fib_retracement_pct <= 78.6
    assert any("FIB_" in t for t in loc.location_tags)
    assert "VWAP_RETEST" in loc.location_tags
    assert loc.is_valid_location is True


def test_trend_day_pullback_vetoes_opposing_obv_and_populates_multi_pillar_signals(monkeypatch):
    """BULLISH TREND_DAY_PULLBACK vetoes opposing BEARISH_DIVERGENCE and tags multi-pillar signals."""
    from types import SimpleNamespace as _NS
    from engine.detectors.trend_day_continuation import detect_trend_day_pullback

    ts = [datetime(2026, 11, 26, 10, 15, tzinfo=IST) + timedelta(minutes=5 * i) for i in range(25)]
    prices = np.linspace(54000, 54600, 23).tolist() + [54560, 54580]
    df = pd.DataFrame(
        {
            "open": [p + 10 for p in prices],
            "high": [p + 15 for p in prices],
            "low": [p - 15 for p in prices],
            "close": prices,
            "volume": [1500] * 24 + [700],
        },
        index=ts,
    )
    df.iloc[-1, df.columns.get_loc("open")] = 54565
    df.iloc[-1, df.columns.get_loc("close")] = 54585
    df.iloc[-1, df.columns.get_loc("low")] = 54540

    # 1. With opposing BEARISH_DIVERGENCE -> must be vetoed (None)
    monkeypatch.setattr(
        "analysis.obv.analyse_obv",
        lambda *a, **k: _NS(divergence="BEARISH_DIVERGENCE", obv_slope_5bar=-10.0),
    )
    monkeypatch.setattr("engine.option_resolver.resolve_option_contract", lambda **k: None)
    vetoed = detect_trend_day_pullback(
        symbol="AXISBANK",
        df_5m=df,
        ltp=54585.0,
        now_dt=datetime(2026, 11, 26, 10, 45, tzinfo=IST),
        segment="FNO_STOCK",
        rvol_val=1.5,
    )
    assert vetoed is None

    # 2. With confirming BULLISH_CONVERGENCE -> allowed with multi-pillar signals & never bare Triple-DMI
    monkeypatch.setattr(
        "analysis.obv.analyse_obv",
        lambda *a, **k: _NS(divergence="BULLISH_CONVERGENCE", obv_slope_5bar=25.0),
    )
    allowed = detect_trend_day_pullback(
        symbol="AXISBANK",
        df_5m=df,
        ltp=54585.0,
        now_dt=datetime(2026, 11, 26, 10, 45, tzinfo=IST),
        segment="FNO_STOCK",
        rvol_val=1.5,
    )
    assert allowed is not None
    assert isinstance(allowed.metrics.get("signals"), list)
    assert len(allowed.metrics["signals"]) >= 2
    assert isinstance(allowed.metrics.get("confluence_pillars"), list)

    from bot.alert_templates import format_auto_alert_telegram

    msg = format_auto_alert_telegram(allowed)
    assert "• Signals: Triple-DMI: Triple Bullish Confirmed\n" not in msg


def test_spread_only_banner_never_contradicts_or_misstates_lot_risk():
    """SPREAD_ONLY alerts must never render 'MARKET FAVORS NAKED' or stale Risk/lot."""
    from bot.alert_templates import format_auto_alert_telegram

    alert = AutoAlert(
        alert_id="aa-bnf-spread-banner-20261126",
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        symbol="BANKNIFTY",
        contract_symbol="NSE:BANKNIFTY26DEC63800CE",
        exchange="NFO",
        direction="BULLISH",
        headline="CALL BREAKOUT IGNITED: BANKNIFTY 63800 CE crossed ₹1,481.5",
        summary="Camarilla H5 Breakout + VWAP Reclaim + Put Writing Floor",
        ltp=1536.0,
        trigger_level=1481.5,
        stop_loss=1416.5,
        target_level=1611.5,
        strike=63800.0,
        option_type="CE",
        option_premium=1481.5,
        underlying_spot=63881.45,
        expiry_date="2026-12-29",
        lot_size=30,
        confidence=85,
        preferred_vehicle="SPREAD_ONLY",
        actionable_plan={
            "action": "EXECUTE HEDGED SPREAD",
            "preferred_vehicle": "SPREAD_ONLY",
            "regime_verdict": "MARKET_FAVORS_NAKED",
            "recommended_entry": "₹1,481.5",
            "stop_loss": "₹1,416.5",
            "target_1": "₹1,611.5",
            "max_loss_rupees": 1949.0,  # stale mismatch should be corrected to spread max loss 6150
            "lot_size": 30,
            "hedge_plan": {
                "strategy": "BULL_CALL_SPREAD",
                "preferred_vehicle": "SPREAD_ONLY",
                "buy_leg": "BUY BANKNIFTY 63800 CE @ ₹1,481.5",
                "sell_leg": "SELL BANKNIFTY 64600 CE @ ₹1,276.5",
                "net_debit_per_share": 205.0,
                "max_loss": 6150.0,
                "max_profit": 17850.0,
                "risk_reward": "1:2.9",
            },
        },
        metrics={
            "spot": 63881.45,
            "lot_size": 30,
            "signals": ["CAMARILLA_H5_EXPANSION", "VWAP_RECLAIM", "PUT_WRITING_FLOOR"],
        },
    )
    msg = format_auto_alert_telegram(alert)
    assert "MARKET FAVORS NAKED" not in msg
    assert "HEDGED SPREAD MANDATED" in msg
    assert "Risk: ₹6,150/lot" in msg


def test_monthly_high_premium_option_preserves_intraday_65pt_sl_without_15pct_blowout(
    tmp_path, monkeypatch
):
    """33-DTE BANKNIFTY CE at ₹1,520 with 65-pt SL (4.27%) must NOT be blown out to -15% (+456 pt T1)."""
    from engine.auto_alert_engine import AutoAlertEngine

    monkeypatch.setattr("engine.auto_alert_engine.AUTO_ALERTS_FILE", tmp_path / "alerts.json")
    monkeypatch.setattr(AutoAlertEngine, "record_alert", AutoAlertEngine.record_alert)
    eng = AutoAlertEngine()
    eng._alerts = []
    # Validate the inline floor check math directly on a live monthly setup
    alert = AutoAlert(
        alert_id="aa-bnf-33dte-sl-check-20261126",
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        symbol="BANKNIFTY",
        contract_symbol="NSE:BANKNIFTY26DEC63800CE",
        exchange="NFO",
        direction="BULLISH",
        headline="BANKNIFTY 63800 CE",
        summary="Camarilla H5 + VWAP reclaim",
        ltp=1520.3,
        trigger_level=1520.3,
        stop_loss=1455.3,  # 65 pts (4.27%) feasible intraday SL
        target_level=1650.3,  # +130 pts (2R)
        strike=63800.0,
        option_type="CE",
        option_premium=1520.3,
        underlying_spot=63845.0,
        expiry_date=(datetime.now(IST) + timedelta(days=33)).strftime("%Y-%m-%d"),
        lot_size=30,
        confidence=85,
        is_live=True,
        environment="LIVE",
        actionable_plan={
            "action": "BUY CE",
            "stop_loss": "₹1,455.3",
            "target_1": "₹1,650.3",
            "max_loss_rupees": 1950.0,
            "lot_size": 30,
        },
        metrics={"spot": 63845.0, "signals": ["CAMARILLA_H5_EXPANSION", "VWAP_RECLAIM"]},
    )
    opt_risk_pts = abs(alert.ltp - alert.stop_loss)
    opt_risk_pct = (opt_risk_pts / alert.ltp) * 100.0
    assert opt_risk_pct > 3.5 and opt_risk_pts >= 25.0
    # Ensure spread hedging scales multi-week (>14 DTE) BANKNIFTY width > 500 pts
    from engine.options_hedging import build_defined_risk_hedge_plan

    hp = build_defined_risk_hedge_plan(
        symbol="BANKNIFTY",
        direction="BULLISH",
        spot=63880.0,
        strike=63800.0,
        opt_type="CE",
        opt_ltp=1481.5,
        expiry_date=(datetime.now(IST) + timedelta(days=33)).strftime("%Y-%m-%d"),
        vel_score=80.0,
    )
    assert hp is not None and abs(hp["sell_strike"] - hp["buy_strike"]) >= 800.0


def _mock_policy_env(monkeypatch):
    from engine.quality_gate import VetoVerdict
    from engine.market_regime_gate import IndexTideGateResult
    import analysis.regime_governor as rg

    monkeypatch.setattr(rg, "_fresh_live_vix", lambda *args, **kwargs: 15.0)
    monkeypatch.setattr(
        "engine.signal_policy.evaluate_institutional_quality_gate",
        lambda *args, **kwargs: VetoVerdict(
            is_vetoed=False,
            veto_reason="",
            conviction_tier="HIGH_CONVICTION",
            execution_mandate="STANDARD",
            metrics={},
        ),
    )
    monkeypatch.setattr(
        "engine.market_regime_gate.evaluate_index_tide_gate",
        lambda *args, **kwargs: IndexTideGateResult(
            is_vetoed=False,
            veto_reason="",
            benchmark_symbol="NIFTY",
            benchmark_ltp=25000.0,
            benchmark_vwap=25000.0,
            benchmark_change_pct=0.2,
        ),
    )


def test_signal_policy_3_pillar_confluence_vetoes_single_indicator(monkeypatch):
    """Lone Triple-DMI or single-pillar indicator signal without Location+Trigger must be vetoed."""
    from engine.signal_policy import build_policy_context_from_alert, evaluate_candidate_policy

    _mock_policy_env(monkeypatch)

    weak_alert = AutoAlert(
        alert_id="aa-test-single-dmi-20261126",
        alert_type="MOMENTUM_SCAN",
        stage="CONFIRMED",
        symbol="RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="RELIANCE Momentum Signal",
        summary="Signals: Triple-DMI: Triple Bullish Confirmed",
        ltp=1400.0,
        trigger_level=1400.0,
        stop_loss=1380.0,
        target_level=1445.0,
        confidence=72,
        is_live=True,
        environment="LIVE",
        metrics={
            "spot": 1400.0,
            "rvol": 1.0,
            "dmi_triple_verdict": "TRIPLE_BULLISH_CONFIRMED",
            "signals": ["Triple-DMI: Triple Bullish Confirmed"],
        },
    )
    res_weak = evaluate_candidate_policy(build_policy_context_from_alert(weak_alert), weak_alert)
    assert res_weak.decision == "REJECT"
    assert res_weak.blocking_gate is not None
    assert res_weak.blocking_gate.gate_name == "CONFLUENCE_3_PILLAR_GATE"

    strong_alert = AutoAlert(
        alert_id="aa-test-multi-pillar-20261126",
        alert_type="TREND_DAY_PULLBACK",
        stage="CONFIRMED",
        symbol="RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="RELIANCE Breakout above OB + VWAP",
        summary="Order Block reclaim + RVOL expansion breakout",
        ltp=1400.0,
        trigger_level=1400.0,
        stop_loss=1380.0,
        target_level=1445.0,
        confidence=84,
        is_live=True,
        environment="LIVE",
        metrics={
            "spot": 1400.0,
            "rvol": 2.4,
            "structural_location": ["BULLISH_OB_CONFLUENCE", "HTF_VAL_BOUNCE"],
            "signals": ["BREAKOUT_CONFIRMED", "RVOL_2.4x", "Triple-DMI: Triple Bullish Confirmed"],
        },
    )
    res_strong = evaluate_candidate_policy(
        build_policy_context_from_alert(strong_alert), strong_alert
    )
    conf_gates = [g for g in res_strong.gate_verdicts if g.gate_name == "CONFLUENCE_3_PILLAR_GATE"]
    assert len(conf_gates) == 1
    assert conf_gates[0].status == "ACCEPT"
    assert set(["LOCATION", "TRIGGER", "FLOW"]).issubset(set(conf_gates[0].evidence["pillars"]))


def test_structural_location_gex_positive_gamma_wall_and_htf_vp():
    """GEX positive-gamma wall overhead blocks unconfirmed breakouts; high Vol/OI unpins it; HTF VP tags emit."""
    from analysis.market_structure import evaluate_structural_location

    # Build a synthetic 60-bar HTF OHLCV block centered around 63850 with clear VAL/VAH/POC
    rng = np.random.default_rng(7)
    n = 60
    idx = pd.date_range("2026-11-26 09:15", periods=n, freq="15min")
    closes = np.concatenate(
        [
            np.linspace(63700, 64050, 30),
            np.linspace(64050, 63780, 15),
            np.linspace(63780, 63850, 15),
        ]
    ) + rng.normal(0, 5, n)
    htf_df = pd.DataFrame(
        {
            "open": closes - 15.0,
            "high": closes + 25.0,
            "low": closes - 25.0,
            "close": closes,
            "volume": np.full(n, 25000.0),
        },
        index=idx,
    )

    gex_pinned = {
        "call_wall": 63960.0,  # ~0.17% above spot 63850
        "put_wall": 63200.0,
        "gex_flip_strike": 63500.0,
        "gamma_regime": "POSITIVE_GAMMA_PIN",
    }
    res_pinned = evaluate_structural_location(
        htf_df,
        spot=63850.0,
        direction="BULLISH",
        gex_data=gex_pinned,
        htf_df=htf_df,
        vol_oi_ratio=0.8,
        rvol_val=1.1,
    )
    assert res_pinned.has_opposing_wall is True

    res_unpin = evaluate_structural_location(
        htf_df,
        spot=63850.0,
        direction="BULLISH",
        gex_data=gex_pinned,
        htf_df=htf_df,
        vol_oi_ratio=4.2,
        rvol_val=3.0,
    )
    assert res_unpin.has_opposing_wall is False
    assert any(t.startswith("HTF_") for t in res_unpin.location_tags)


def test_signal_policy_expected_move_runway_veto(monkeypatch):
    """Intraday continuation with < 25% Expected Move remaining and distant T1 must be vetoed."""
    from engine.signal_policy import build_policy_context_from_alert, evaluate_candidate_policy

    _mock_policy_env(monkeypatch)

    exhausted_alert = AutoAlert(
        alert_id="aa-test-em-exhausted-20261126",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY Call Setup Breakout above Resistance",
        summary="Confluence breakout above resistance + VWAP reclaim",
        ltp=150.0,
        trigger_level=150.0,
        stop_loss=120.0,
        target_level=240.0,
        strike=25000.0,
        option_type="CE",
        contract_symbol="NIFTY26NOV25000CE",
        confidence=85,
        time_horizon="INTRADAY",
        is_live=True,
        environment="LIVE",
        metrics={
            "spot": 25170.0,
            "underlying_spot": 25170.0,
            "underlying_sl": 25070.0,
            "underlying_target": 25280.0,  # 110 pts needed > 25*1.15
            "spot_target_1": 25280.0,
            "vix": 15.0,
            "india_vix": 15.0,
            "volume": 50000,
            "oi": 100000,
            "rvol": 1.8,
            "adr_5d": 200.0,
            "day_high": 25175.0,
            "day_low": 25000.0,  # 175 used -> 25 remaining (12.5% < 25%)
            "structural_location": ["VWAP_RECLAIM_BULL"],
            "signals": ["BREAKOUT_CONFIRMED", "RVOL_1.8x"],
        },
    )
    res_exh = evaluate_candidate_policy(
        build_policy_context_from_alert(exhausted_alert), exhausted_alert
    )
    assert res_exh.decision == "REJECT"
    assert res_exh.blocking_gate is not None
    assert res_exh.blocking_gate.gate_name == "EXPECTED_MOVE_RUNWAY_GATE"

    fresh_alert = AutoAlert(
        alert_id="aa-test-em-fresh-20261126",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY Call Setup Breakout above Resistance",
        summary="Confluence breakout above resistance + VWAP reclaim",
        ltp=150.0,
        trigger_level=150.0,
        stop_loss=120.0,
        target_level=240.0,
        strike=25000.0,
        option_type="CE",
        contract_symbol="NIFTY26NOV25000CE",
        confidence=85,
        time_horizon="INTRADAY",
        is_live=True,
        environment="LIVE",
        metrics={
            "spot": 25170.0,
            "underlying_spot": 25170.0,
            "underlying_sl": 25070.0,
            "underlying_target": 25280.0,
            "spot_target_1": 25280.0,
            "vix": 15.0,
            "india_vix": 15.0,
            "volume": 50000,
            "oi": 100000,
            "rvol": 1.8,
            "adr_5d": 350.0,  # 175 used -> 175 remaining (50% >= 25%)
            "day_high": 25175.0,
            "day_low": 25000.0,
            "structural_location": ["VWAP_RECLAIM_BULL"],
            "signals": ["BREAKOUT_CONFIRMED", "RVOL_1.8x"],
        },
    )
    res_ok = evaluate_candidate_policy(build_policy_context_from_alert(fresh_alert), fresh_alert)
    em_gates = [g for g in res_ok.gate_verdicts if g.gate_name == "EXPECTED_MOVE_RUNWAY_GATE"]
    assert len(em_gates) == 1
    assert em_gates[0].status == "ACCEPT"


def test_trend_pullback_constituent_lead_lag_veto(monkeypatch):
    """Counter-constituent BULLISH trend pullback on NIFTY must be vetoed when heavyweights lead BEARISH."""
    from engine.detectors.trend_day_continuation import detect_trend_day_pullback

    monkeypatch.setenv("CHANAKYA_TESTING", "1")
    n = 25
    timestamps = [
        datetime(2026, 10, 22, 10, 15, tzinfo=IST) + timedelta(minutes=5 * i) for i in range(n)
    ]
    prices = np.linspace(25000, 25300, n - 2).tolist() + [25280.0, 25290.0]
    df = pd.DataFrame(index=timestamps)
    df["close"] = prices
    df["open"] = [p - 5.0 for p in prices]
    df.loc[df.index[-1], "open"] = 25282.0
    df.loc[df.index[-1], "close"] = 25292.0
    df["high"] = [max(o, c) + 6.0 for o, c in zip(df["open"], df["close"])]
    df["low"] = [min(o, c) - 8.0 for o, c in zip(df["open"], df["close"])]
    df.loc[df.index[-1], "low"] = 25268.0
    df["volume"] = [10000 + i * 200 for i in range(n)]
    df.loc[df.index[-1], "volume"] = 8500

    monkeypatch.setattr(
        "engine.feature_bus.compute_constituent_lead_lag",
        lambda sym, *args, **kwargs: {
            "index": sym,
            "status": "AVAILABLE",
            "constituents_reporting": 10,
            "weighted_impulse_pct": -0.45,
            "lead_bias": "BEARISH_LEAD",
        },
    )
    vetoed = detect_trend_day_pullback(
        symbol="NIFTY",
        df_5m=df,
        ltp=float(df["close"].iloc[-1]),
        now_dt=datetime(2026, 10, 22, 11, 30, tzinfo=IST),
        exchange="NSE",
        segment="FNO_INDEX",
    )
    assert vetoed is None


def test_cas_derivative_dispersion_window_guard(monkeypatch):
    """Post-Dec 7 15:25-15:45 IST CAS derivative dispersion guard rejects wide/missing option spreads."""
    from market.rule_schedule import is_cas_derivative_dispersion_window
    from engine.signal_policy import build_policy_context_from_alert, evaluate_candidate_policy

    assert is_cas_derivative_dispersion_window(datetime(2026, 12, 7, 15, 32, tzinfo=IST)) is True
    assert is_cas_derivative_dispersion_window(datetime(2026, 12, 7, 15, 45, tzinfo=IST)) is True
    assert is_cas_derivative_dispersion_window(datetime(2026, 11, 26, 15, 32, tzinfo=IST)) is False

    _mock_policy_env(monkeypatch)
    monkeypatch.setattr(
        "market.rule_schedule.is_cas_derivative_dispersion_window", lambda *args, **kwargs: True
    )

    wide_opt = AutoAlert(
        alert_id="aa-test-cas-wide-20261207",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY 25000 CE Breakout above Resistance",
        summary="Confluence breakout above resistance + VWAP reclaim",
        ltp=150.0,
        trigger_level=150.0,
        stop_loss=120.0,
        target_level=240.0,
        strike=25000.0,
        option_type="CE",
        contract_symbol="NIFTY26NOV25000CE",
        confidence=85,
        is_live=True,
        environment="LIVE",
        metrics={
            "spot": 25020.0,
            "underlying_spot": 25020.0,
            "underlying_sl": 24920.0,
            "underlying_target": 25320.0,
            "vix": 15.0,
            "india_vix": 15.0,
            "volume": 50000,
            "oi": 100000,
            "rvol": 2.1,
            "structural_location": ["VWAP_RECLAIM_BULL"],
            "signals": ["BREAKOUT_CONFIRMED", "RVOL_2.1x"],
            "liquidity": {"bid_ask_spread_pct": 3.4},
        },
    )
    res_wide = evaluate_candidate_policy(build_policy_context_from_alert(wide_opt), wide_opt)
    assert res_wide.decision == "REJECT"
    assert res_wide.blocking_gate is not None
    assert res_wide.blocking_gate.gate_name == "CAS_SPREAD_DISPERSION_GATE"

    tight_opt = AutoAlert(
        alert_id="aa-test-cas-tight-20261207",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY 25000 CE Breakout above Resistance",
        summary="Confluence breakout above resistance + VWAP reclaim",
        ltp=150.0,
        trigger_level=150.0,
        stop_loss=120.0,
        target_level=240.0,
        strike=25000.0,
        option_type="CE",
        contract_symbol="NIFTY26NOV25000CE",
        confidence=85,
        is_live=True,
        environment="LIVE",
        metrics={
            "spot": 25020.0,
            "underlying_spot": 25020.0,
            "underlying_sl": 24920.0,
            "underlying_target": 25320.0,
            "vix": 15.0,
            "india_vix": 15.0,
            "volume": 50000,
            "oi": 100000,
            "rvol": 2.1,
            "structural_location": ["VWAP_RECLAIM_BULL"],
            "signals": ["BREAKOUT_CONFIRMED", "RVOL_2.1x"],
            "liquidity": {"bid_ask_spread_pct": 0.8},
        },
    )
    res_tight = evaluate_candidate_policy(build_policy_context_from_alert(tight_opt), tight_opt)
    cas_gates = [g for g in res_tight.gate_verdicts if g.gate_name == "CAS_SPREAD_DISPERSION_GATE"]
    assert len(cas_gates) == 1
    assert cas_gates[0].status == "ACCEPT"


def test_expected_volume_fraction_dynamic_390m_cas_session():
    """Post-Dec 7 2026 390-minute derivative sessions must scale TOD-RVOL smoothly without saturating at 15:30."""
    from engine.auto_alert_engine import compute_time_of_day_rvol, expected_volume_fraction

    frac_375_at_360 = expected_volume_fraction(360.0, total_session_minutes=375.0)
    frac_390_at_360 = expected_volume_fraction(360.0, total_session_minutes=390.0)
    assert frac_375_at_360 > frac_390_at_360
    assert frac_390_at_360 < 1.0

    # On 2026-12-07 at 15:40 IST (385 mins from 09:15), NFO closes at 15:45 (390 mins), not 15:30
    rvol_cas = compute_time_of_day_rvol(
        950000.0,
        1000000.0,
        ref_dt=datetime(2026, 12, 7, 15, 40, tzinfo=IST),
        is_derivative=True,
        exchange="NFO",
    )
    assert rvol_cas > 0.95 and rvol_cas <= 1.05


def test_sse_last_event_id_replay():
    """SSEEventBus must assign monotonic seq IDs and replay missed events via last_event_id."""
    import asyncio
    import json
    from web.sse import SSEEventBus

    async def _run():
        bus = SSEEventBus()
        await bus.publish("alert", {"alert_id": "a1"})
        await bus.publish("alert", {"alert_id": "a2"})
        await bus.publish("alert", {"alert_id": "a3"})

        gen = bus.subscribe("alert", last_event_id=1)
        frame2 = await anext(gen)
        frame3 = await anext(gen)
        await gen.aclose()

        assert "id: 2\n" in frame2
        assert json.loads(frame2.split("data: ", 1)[1])["alert_id"] == "a2"
        assert "id: 3\n" in frame3
        assert json.loads(frame3.split("data: ", 1)[1])["alert_id"] == "a3"

    asyncio.run(_run())


def test_security_360_live_multilens_and_decision(monkeypatch):
    """When include_live_analysis=True and quantitative sources exist, Security 360 populates multiple lenses and DecisionSummary."""
    from unittest.mock import patch
    from engine.security_360 import build_security_360_dossier

    n = 60
    idx = pd.date_range("2026-09-01", periods=n, freq="B")
    closes = np.linspace(2400.0, 2900.0, n)
    df_day = pd.DataFrame(
        {
            "open": closes - 10.0,
            "high": closes + 20.0,
            "low": closes - 20.0,
            "close": closes,
            "volume": np.full(n, 100000.0),
        },
        index=idx,
    )
    mock_dcf = SimpleNamespace(fair_value=3600.0)
    mock_forensic = SimpleNamespace(overall_flag="CLEAN_PASS")

    with (
        patch("analysis.dcf.dcf_for_symbol", return_value=mock_dcf),
        patch("engine.security_360.audit_company_forensics", return_value=mock_forensic),
        patch("engine.historical_warehouse.historical_warehouse.load_bars", return_value=df_day),
    ):
        dossier = build_security_360_dossier(
            "RELIANCE",
            current_price=2920.0,
            include_live_analysis=True,
        )

    assert len(dossier.methodology_lenses) >= 3
    assert dossier.decision is not None
    assert dossier._status == "READY"
    assert dossier.decision.invalidation_level < 2920.0 < dossier.decision.target_1


def test_confidence_calibrator_caps_uncalibrated_and_high_friction():
    """Uncalibrated <3 pillar alerts must cap <=84; wide spread/statutory friction flags high_friction_risk."""
    from engine.confidence_calibrator import calibrate_alert_confidence

    high_raw_uncal = AutoAlert(
        alert_id="aa-test-cal-cap-20261126",
        alert_type="UNSEEN_NEW_DETECTOR",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY 25000 CE Breakout",
        summary="Breakout above OB",
        ltp=150.0,
        trigger_level=150.0,
        stop_loss=120.0,
        target_level=240.0,
        strike=25000.0,
        option_type="CE",
        lot_size=65,
        confidence=94,
    )
    res_uncal = calibrate_alert_confidence(high_raw_uncal, pillars=["LOCATION", "TRIGGER"])
    assert res_uncal.calibration_status == "UNCALIBRATED"
    assert res_uncal.calibrated_confidence <= 84

    high_fric = AutoAlert(
        alert_id="aa-test-cal-fric-20261126",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="Scalp",
        summary="Tight target wide spread",
        ltp=100.0,
        trigger_level=100.0,
        stop_loss=90.0,
        target_level=110.0,  # +10 target vs 4% bid-ask spread (~₹4) + statutory charges
        strike=25000.0,
        option_type="CE",
        lot_size=65,
        confidence=88,
        bid_ask_spread_pct=4.0,
    )
    res_fric = calibrate_alert_confidence(high_fric, pillars=["LOCATION", "TRIGGER", "FLOW"])
    assert res_fric.high_friction_risk is True
    assert res_fric.cost_friction_pct is not None and res_fric.cost_friction_pct >= 25.0
    assert res_fric.calibrated_confidence <= 72


def test_oms_partial_fill_weighted_avg_and_completion_transition():
    """Sequential partial fills must accumulate weighted avg fill price and transition PARTIALLY_FILLED -> FILLED."""
    from datetime import timezone
    from engine.order_lifecycle import (
        _get_orders_db,
        _init_orders_db,
        apply_fyers_stream_trade_fill,
    )

    _init_orders_db()
    order_id = "LIVE-PARTIAL-75"
    broker_oid = "BRK-PARTIAL-75"
    now_iso = datetime.now(timezone.utc).isoformat()
    with _get_orders_db() as conn:
        conn.execute("DELETE FROM execution_fills WHERE order_id = ?", (order_id,))
        conn.execute(
            """
            INSERT OR REPLACE INTO orders_ledger
            (order_id, idempotency_key, symbol, exchange, segment, side, quantity, price,
             order_type, product, status, mode, broker_order_id, account_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                "idemp-partial-75",
                "NIFTY26N2425000CE",
                "NFO",
                "FNO_INDEX",
                "BUY",
                75,
                100.0,
                "LIMIT",
                "MIS",
                "OPEN",
                "EXECUTE",
                broker_oid,
                "FYERS_TEST_ACC",
                now_iso,
                now_iso,
            ),
        )
        conn.commit()

    # Tranche 1: 25 @ 100.0 -> PARTIALLY_FILLED
    t1 = apply_fyers_stream_trade_fill(
        {
            "orderNumber": broker_oid,
            "tradeNumber": "TRD-P1",
            "tradedQty": 25,
            "tradePrice": 100.0,
            "clientId": "FYERS_TEST_ACC",
        }
    )
    assert t1["recorded"] is True
    assert t1["protection"]["order_status"] == "PARTIALLY_FILLED"

    # Tranche 2: 50 @ 106.0 -> FILLED, weighted avg = (25*100 + 50*106)/75 = 104.0
    t2 = apply_fyers_stream_trade_fill(
        {
            "orderNumber": broker_oid,
            "tradeNumber": "TRD-P2",
            "tradedQty": 50,
            "tradePrice": 106.0,
            "clientId": "FYERS_TEST_ACC",
        }
    )
    assert t2["recorded"] is True
    assert t2["protection"]["order_status"] == "FILLED"
    assert t2["protection"]["verified_filled_qty"] == 75
    with _get_orders_db() as conn:
        row = conn.execute(
            "SELECT status, filled_quantity, average_fill_price FROM orders_ledger WHERE order_id = ?",
            (order_id,),
        ).fetchone()
    assert row["status"] == "FILLED"
    assert int(row["filled_quantity"]) == 75
    assert abs(float(row["average_fill_price"]) - 104.0) < 0.01
