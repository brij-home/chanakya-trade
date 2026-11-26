"""Regression tests for Nov 25, 2026 market readiness, Dec 7 CAS cutover, and pipeline wiring."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from config.constants import IST
from config.paths import app_data_dir


def test_app_data_dir_ignores_boolean_env_sentinels(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADING_PLATFORM_DATA", "1")
    monkeypatch.setenv("TRADING_PLATFORM_HOME", str(tmp_path))
    assert app_data_dir() == tmp_path

    monkeypatch.setenv("TRADING_PLATFORM_DATA", "true")
    monkeypatch.delenv("TRADING_PLATFORM_HOME", raising=False)
    assert app_data_dir() == Path.home() / ".trading_platform"


def test_instruments_session_state_respects_dec7_derivative_close():
    from market.instruments import get_market_session_state

    # Dec 8, 2026 15:40 IST (after Dec 7 cutover: NFO open until 15:45, NSE cash closed at 15:30)
    dt_ist = datetime(2026, 12, 8, 15, 40, tzinfo=IST)
    nfo_state = get_market_session_state("NFO", now_utc=dt_ist)
    nse_state = get_market_session_state("NSE", now_utc=dt_ist)

    assert nfo_state.is_open is True
    assert nfo_state.session_state == "OPEN"
    assert nfo_state.session_close_ist == "15:45:00 IST"

    assert nse_state.is_open is False
    assert nse_state.session_state == "POST_CLOSE"
    assert nse_state.session_close_ist == "15:30:00 IST"


def test_rule_schedule_phase2_cas_date_gate():
    from market.rule_schedule import is_cas_order_transition_active

    assert is_cas_order_transition_active(date(2026, 12, 7)) is False
    assert is_cas_order_transition_active(date(2027, 2, 7)) is False
    assert is_cas_order_transition_active(date(2027, 2, 8)) is True


def test_alert_postmortem_runner_respects_dec7_close(monkeypatch):
    from engine import alert_postmortem_runner as apr

    class _FakeDt(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 12, 8, 15, 35, tzinfo=IST)

    monkeypatch.setattr(apr, "datetime", _FakeDt)
    res = apr.run_eod_alert_postmortems(force=False, broadcast=False)
    assert res["status"] == "SKIPPED_MARKET_OPEN"
    assert "15:45" in res["reason"]


def test_fno_ban_csv_parser_and_fetch_wiring(monkeypatch, tmp_path):
    from market import fno_ban

    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))
    monkeypatch.setattr(fno_ban, "_BAN_CACHE_FILE", tmp_path / "cache" / "fno_ban_latest.json")
    monkeypatch.setattr(fno_ban, "_LATEST_SNAPSHOT", None)

    sample_csv = "Securities in Ban For Trade Date 25-NOV-2026:\n1,SAIL\n2,AARTIIND\n"
    parsed_date, syms = fno_ban._parse_nse_secban_csv(sample_csv)
    assert parsed_date == "2026-11-25"
    assert syms == ["AARTIIND", "SAIL"]

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return sample_csv.encode("utf-8")

    with patch("urllib.request.urlopen", return_value=_Resp()):
        snap = fno_ban.fetch_and_record_nse_fno_ban()
    assert snap is not None
    assert snap.as_of_date == "2026-11-25"
    assert "SAIL" in fno_ban.get_fno_ban_list()
    assert fno_ban.is_in_fno_ban("NFO:SAIL26NOVFUT") is True
    assert fno_ban.is_in_fno_ban("NIFTY") is False


def test_iv_surface_persistence_and_honest_min_samples(monkeypatch, tmp_path):
    from analysis.options import compute_iv_rank_from_history
    from engine.iv_surface import (
        build_iv_surface_snapshot,
        extract_surface_inputs_from_chain,
        load_historical_30d_ivs,
        record_iv_observation,
    )

    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))

    chain = [
        SimpleNamespace(strike=24000, option_type="CE", iv=14.2, delta=0.52, expiry="2026-12-01"),
        SimpleNamespace(strike=24000, option_type="PE", iv=14.8, delta=-0.48, expiry="2026-12-01"),
        SimpleNamespace(strike=23600, option_type="PE", iv=16.5, delta=-0.25, expiry="2026-12-01"),
        SimpleNamespace(strike=24400, option_type="CE", iv=13.1, delta=0.25, expiry="2026-12-01"),
        SimpleNamespace(strike=24000, option_type="CE", iv=15.0, delta=0.51, expiry="2026-12-29"),
        SimpleNamespace(strike=24000, option_type="PE", iv=15.4, delta=-0.49, expiry="2026-12-29"),
    ]
    inputs = extract_surface_inputs_from_chain(chain, 24010.0, as_of_date=date(2026, 11, 25))
    assert inputs["near_dte"] == 6
    assert inputs["next_dte"] == 34
    assert inputs["iv_25d_put"] == 16.5
    assert inputs["iv_25d_call"] == 13.1

    snap = build_iv_surface_snapshot(
        symbol="NIFTY",
        near_atm_iv=inputs["near_atm_iv"],
        near_dte=inputs["near_dte"],
        next_atm_iv=inputs["next_atm_iv"],
        next_dte=inputs["next_dte"],
        iv_25d_put=inputs["iv_25d_put"],
        iv_25d_call=inputs["iv_25d_call"],
        now_dt=datetime(2026, 11, 25, 14, 0, tzinfo=IST),
    )
    assert snap.status == "AVAILABLE"
    assert snap.atm_iv_30d is not None and snap.atm_iv_30d > 0
    assert record_iv_observation(snap, session_date="2026-11-25") is True
    # < 20 authentic sessions MUST remain UNAVAILABLE (None)
    assert compute_iv_rank_from_history("NIFTY") is None

    # After >= 20 real daily sessions accumulate, IV rank becomes computable
    for i in range(1, 21):
        s_i = build_iv_surface_snapshot(
            symbol="NIFTY",
            near_atm_iv=12.0 + i * 0.25,
            near_dte=30,
            now_dt=datetime(2026, 11, i, 14, 0, tzinfo=IST),
        )
        record_iv_observation(s_i, session_date=f"2026-11-{i:02d}")
    hist = load_historical_30d_ivs("NIFTY")
    assert len(hist) >= 20
    rank = compute_iv_rank_from_history("NIFTY")
    assert rank is not None and 0.0 <= rank <= 100.0


def test_vectorized_bs_premium_grid_matches_scalar():
    from engine.options_backtest import bs_premium, vectorized_bs_premium_grid

    strikes = np.array([23500.0, 24000.0, 24500.0])
    vec = vectorized_bs_premium_grid(24000.0, strikes, 14, 0.16, option_type="CE")
    scalar = np.array([bs_premium(24000.0, float(k), 14, 0.16, "CE") for k in strikes])
    assert np.allclose(vec, scalar, atol=1e-6)


def test_security_360_opt_in_dcf_preserves_default_contract():
    from engine.security_360 import build_security_360_dossier

    default_d = build_security_360_dossier("RELIANCE", current_price=2800.0)
    assert default_d.valuation_fair_value is None
    assert default_d.valuation_status == "UNAVAILABLE"

    with patch("analysis.dcf.dcf_for_symbol", return_value=SimpleNamespace(fair_value=3500.0)):
        enriched = build_security_360_dossier(
            "RELIANCE", current_price=2800.0, include_live_analysis=True
        )
    assert enriched.valuation_fair_value == 3500.0
    assert enriched.valuation_status == "UNDERVALUED"


def test_phase2_cas_gate_blocks_market_orders_only_from_feb8_2027():
    from engine.pretrade import _gate_cas_window_transition

    # Pre-Feb 8, 2027 during Dec 7 CAS window (15:37 IST): Phase 2 gate stays inactive
    pre_dt = datetime(2026, 12, 8, 15, 37, tzinfo=IST)
    assert _gate_cas_window_transition("RELIANCE", "EQ", "MARKET", ref_dt=pre_dt).passed is True

    # From Feb 8, 2027 during 15:36-15:40 CAS window: MARKET blocked, LIMIT allowed with warning
    post_dt = datetime(2027, 2, 8, 15, 37, tzinfo=IST)
    mkt_res = _gate_cas_window_transition("RELIANCE", "EQ", "MARKET", ref_dt=post_dt)
    lmt_res = _gate_cas_window_transition("RELIANCE", "EQ", "LIMIT", ref_dt=post_dt)
    assert mkt_res.passed is False
    assert lmt_res.passed is True and "warning" in lmt_res.details


def test_mwpl_combineoi_parser_and_futeq_utilization(monkeypatch, tmp_path):
    from market import fno_ban

    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))
    monkeypatch.setattr(fno_ban, "_BAN_CACHE_FILE", tmp_path / "cache" / "fno_ban_latest.json")
    monkeypatch.setattr(fno_ban, "_LATEST_SNAPSHOT", None)

    csv_txt = (
        "Date,ISIN,Scrip Name,NSE Symbol,MWPL,Open Interest,Limit for Next Day\n"
        "25-NOV-2026,INE114A01011,SAIL,SAIL,100000,96000,BAN\n"
        "25-NOV-2026,INE040A01034,RELIANCE,RELIANCE,500000,250000,225000\n"
    )
    as_of, limits, banned = fno_ban._parse_nse_combineoi_csv(csv_txt)
    assert as_of == "2026-11-25"
    assert limits["SAIL"] == 100000.0
    assert "SAIL" in banned

    fno_ban.record_fno_ban_update(banned_symbols=banned, as_of_date=as_of, mwpl_limits_map=limits)
    chain = [
        {"strike": 120, "option_type": "CE", "oi": 50000, "delta": 0.6},
        {"strike": 115, "option_type": "PE", "oi": 50000, "delta": -0.4},
    ]
    res = fno_ban.update_intraday_futeq_for_symbol("SAIL", chain, fut_oi=20000)
    assert res["status"] == "AVAILABLE"
    assert res["futeq_oi"] == 70000.0
    assert res["mwpl_utilization_pct"] == 70.0
    assert fno_ban.get_mwpl_utilization("SAIL") == 70.0


def test_order_book_bse_5_depth_capability_flags():
    from market.order_book import compute_order_book_metrics

    raw = {
        "buy": [{"price": 80000.0, "quantity": 50, "orders": 2}],
        "sell": [{"price": 80010.0, "quantity": 60, "orders": 3}],
    }
    bse_snap = compute_order_book_metrics("BSE:SENSEX26NOVFUT", raw, ltp=80005.0)
    assert bse_snap.tbt_supported is False
    assert bse_snap.depth_levels <= 5
    assert bse_snap.depth_capability == "BSE_DATA_SOCKET_5_DEPTH"

    nse_snap = compute_order_book_metrics(
        "NSE:NIFTY26NOVFUT", raw, ltp=24500.0, provenance="LIVE_STREAM_TBT_50"
    )
    assert nse_snap.tbt_supported is True
    assert nse_snap.depth_capability == "NSE_TBT_50_DEPTH"


def test_alert_stage_transition_and_replay_ablation():
    import pandas as pd
    from engine.alert_model import AutoAlert
    from engine.options_replay import run_detector_ablation_comparison

    a = AutoAlert(
        alert_id="aa-test-watch-nifty-20261125",
        alert_type="SQUEEZE_BREAKOUT",
        stage="WATCH",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="h",
        summary="s",
        ltp=24500.0,
        trigger_level=24520.0,
        target_level=24600.0,
        stop_loss=24480.0,
    )
    tr = a.record_stage_transition("ARMED", reason="Squeeze coiling", evidence={"rvol": 1.4})
    assert a.stage == "ARMED"
    assert tr["from_stage"] == "WATCH"
    assert len(a.stage_history) == 1

    idx = pd.date_range("2026-11-01 09:15", periods=40, freq="5min")
    df = pd.DataFrame(
        {
            "open": [100.0 + i * 0.2 for i in range(40)],
            "high": [101.0 + i * 0.2 for i in range(40)],
            "low": [99.5 + i * 0.2 for i in range(40)],
            "close": [100.5 + i * 0.2 for i in range(40)],
        },
        index=idx,
    )
    comp = run_detector_ablation_comparison(df, [2, 18], [2])
    assert comp["status"] == "UNCALIBRATED"
    assert comp["baseline"]["trades"] >= 1


def test_anti_fomo_entry_and_base_quality_checks():
    import pandas as pd
    from analysis.pullback_engine import check_base_quality_and_supply, evaluate_anti_fomo_entry

    dates = pd.date_range("2026-06-01", periods=70, freq="B")
    # Build steady uptrend then a sharp vertical 22% chase in last 5 bars
    closes = [100.0 + i * 0.4 for i in range(65)] + [130.0, 136.0, 142.0, 149.0, 156.0]
    highs = [c * 1.01 for c in closes]
    lows = [c * 0.99 for c in closes]
    opens = [c * 0.995 for c in closes]
    vols = [100_000.0] * 65 + [350_000.0] * 5
    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols},
        index=dates,
    )

    res = evaluate_anti_fomo_entry(df, 156.0, pivot_price=126.0, direction="BULLISH", symbol="TEST")
    assert res.is_extended is True
    assert res.extension_status == "OVEREXTENDED_WAIT"
    assert res.no_chase_boundary == round(126.0 * 1.025, 2)
    assert res.pullback_limit_entry < 156.0
    assert res.recommended_entry == res.pullback_limit_entry

    # Test 3-weeks-tight & pocket pivot detection
    tight_closes = [100.0 + i * 0.6 for i in range(45)] + [
        127.0,
        127.5,
        128.0,
        128.1,
        127.9,  # W1 ~127.9
        128.0,
        128.2,
        127.8,
        128.3,
        128.1,  # W2 ~128.1
        127.9,
        128.0,
        128.2,
        127.9,
        128.2,  # W3 ~128.2 (tight!)
    ]
    tight_vols = [100_000.0] * 55 + [140_000.0, 80_000.0, 90_000.0, 70_000.0, 260_000.0]
    tight_opens = [c - 0.3 for c in tight_closes]
    tight_df = pd.DataFrame(
        {
            "open": tight_opens,
            "high": [c + 0.4 for c in tight_closes],
            "low": [c - 0.5 for c in tight_closes],
            "close": tight_closes,
            "volume": tight_vols,
        },
        index=dates[:60],
    )
    bq = check_base_quality_and_supply(tight_df, entry_price=128.2, risk_pts=5.0, pivot_price=128.5)
    assert bq["is_tight_flag"] is True
    assert bq["has_pocket_pivot"] is True
    assert bq["has_clear_runway"] is True


def test_swing_inflection_no_chase_never_drifts_to_extended_ltp():
    from analysis.inflection_scanner import InflectionSetup
    from engine.detectors.swing_inflection import _format_swing_inflection_alert

    setup = InflectionSetup(
        symbol="TESTEXT",
        name="Test Extended Co",
        sector="IT",
        sector_icon="💻",
        ltp=1500.0,
        day_change_pct=6.5,
        inflection_score=86,
        primary_archetype="VCP_PIVOT_BREAKOUT",
        archetype_label="VCP Volatility Pivot Breakout",
        timing_state="PULLBACK_RETEST",
        timing_label="WAIT PULLBACK",
        weinstein_stage="STAGE_2_MARKUP",
        vcp_detected=True,
        vcp_tightness_pct=3.5,
        vcp_pivot_price=1280.0,
        squeeze_state="FIRED_LONG",
        squeeze_duration=4,
        rvol_20d=2.4,
        trend_template_passed=8,
        sector_tailwind_score=80.0,
        rrg_quadrant="LEADING",
        forensic_safe=True,
        smc_regime="MARKUP",
        smc_setup="OB_RETEST",
        entry_price=1295.0,
        stop_loss=1220.0,
        target_1=1445.0,
        target_2=1557.5,
        target_moonshot=1782.5,
        risk_reward_ratio=3.5,
        risk_pts=75.0,
        reward_pts=262.5,
        confluence_factors=["VCP Pivot", "RS Leading"],
        catalyst_summary="Extended after breakout",
        suggested_action="Wait pullback",
        execution_ticket={"atr_14d": 35.0, "min_noise_sl_pts": 43.75},
        is_extended=True,
        extension_status="OVEREXTENDED_WAIT",
        no_chase_boundary=1312.0,
        pullback_limit_entry=1295.0,
        dist_ema20_atr=3.1,
    )
    alert = _format_swing_inflection_alert(
        setup, session_dt=datetime(2026, 11, 25, 11, 0, tzinfo=IST), mkt_open=True
    )
    assert alert.stage == "PRIMED"
    assert alert.trigger_level <= alert.ltp
    assert alert.no_chase_boundary == 1312.0
    assert alert.actionable_plan["recommended_entry"] == 1295.0
    assert "OVEREXTENDED" in alert.actionable_plan["when_to_wait"]
    assert "WAIT FOR PULLBACK" in alert.actionable_plan["when_to_buy"]


def test_century_and_multibagger_tickets_anchor_pullback_when_extended():
    import pandas as pd
    from analysis.century_compounder import evaluate_century_compounder
    from analysis.multibagger import (
        generate_generational_ticket,
        generate_mid_term_compounder_ticket,
        generate_short_term_ticket,
    )

    dates = pd.date_range("2025-12-01", periods=220, freq="B")
    closes = [100.0 + i * 0.25 for i in range(214)] + [162.0, 169.0, 177.0, 185.0, 192.0, 200.0]
    df = pd.DataFrame(
        {
            "open": [c * 0.995 for c in closes],
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [120_000.0] * 220,
        },
        index=dates,
    )

    cc = evaluate_century_compounder("TESTCC", df=df, ltp=200.0)
    assert cc.anti_fomo.action_directive == "WAIT_FOR_PULLBACK"
    assert cc.anti_fomo.pullback_limit_entry < 200.0

    st = generate_short_term_ticket(200.0, df, is_vcp=True, pivot_price=154.0)
    mt = generate_mid_term_compounder_ticket(
        200.0, df, stage="STAGE_2_MARKUP", is_vcp=True, pivot_price=154.0
    )
    lt = generate_generational_ticket(200.0, df, details={}, forensic_safe=True)
    for t in (st, mt, lt):
        assert t["is_extended"] is True
        assert t["entry_price"] < 200.0
        assert t["no_chase_boundary"] < 200.0


def test_bearish_fno_swing_detector_and_option_no_chase_parity():
    import pandas as pd
    from engine.detectors.swing_inflection import detect_bearish_fno_swing_setups

    dates = pd.date_range("2026-07-01", periods=70, freq="B")
    # Uptrend early then distribution & Stage 4 breakdown below 50-SMA
    closes = (
        [220.0] * 25
        + [218.0 - i * 0.6 for i in range(35)]
        + [195.0, 192.0, 189.0, 186.0, 183.0, 180.0, 177.0, 174.0, 171.0, 168.0]
    )
    df = pd.DataFrame(
        {
            "open": [c * 1.005 for c in closes],
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [250_000.0] * 70,
        },
        index=dates,
    )
    alerts = detect_bearish_fno_swing_setups(
        symbols_override=["INFY"],
        ohlcv_map={"INFY": df},
        min_score=65,
        min_turnover_cr=0.1,
        session_dt=datetime(2026, 11, 25, 11, 0, tzinfo=IST),
    )
    assert len(alerts) == 1
    a = alerts[0]
    assert a.direction == "BEARISH"
    assert a.stop_loss > a.ltp
    assert a.target_level < a.trigger_level
    assert a.no_chase_boundary < a.trigger_level

    # Verify scan_fno_stock_swing_setups propagates spot & option no-chase boundaries for bearish PUTs
    from engine.auto_alert_engine import AutoAlertEngine

    engine_inst = AutoAlertEngine.__new__(AutoAlertEngine)
    engine_inst.record_alert = lambda al: True
    fake_contracts = [
        SimpleNamespace(
            symbol="NFO:INFY26DECPUT170PE",
            option_type="PE",
            strike=170.0,
            expiry="2026-12-31",
            lot_size=400,
            ltp=7.5,
            bid=7.4,
            ask=7.6,
            oi=50000,
            volume=12000,
            iv=22.0,
        )
    ]
    with (
        patch("engine.detectors.swing_inflection.detect_swing_inflection_setups", return_value=[]),
        patch(
            "engine.detectors.swing_inflection.detect_bearish_fno_swing_setups", return_value=[a]
        ),
        patch("market.instruments.is_derivative_eligible", return_value=True),
        patch("market.fno_ban.is_in_fno_ban", return_value=False),
    ):
        fno_alerts = AutoAlertEngine.scan_fno_stock_swing_setups(
            engine_inst,
            min_score=65,
            top_n=5,
            contracts_override=fake_contracts,
        )
    assert len(fno_alerts) == 1
    out = fno_alerts[0]
    assert out.contract_symbol == "NFO:INFY26DECPUT170PE"
    assert out.product == "NRML"
    assert out.option_type == "PE"
    assert out.actionable_plan["spot_no_chase_boundary"] == a.no_chase_boundary
    assert out.actionable_plan["option_no_chase_boundary"] > 0
    if out.actionable_plan["is_extended"]:
        assert out.stage == "PRIMED"


def test_option_resolver_blocks_fno_ban_and_premarket_checks_nfo_swings():
    import threading
    from engine.alert_model import AutoAlert
    from engine.auto_alert_engine import AutoAlertEngine
    from engine.option_resolver import resolve_option_contract

    fake_contract = SimpleNamespace(
        symbol="NFO:SAIL26DECCALL120CE",
        option_type="CE",
        strike=120.0,
        expiry="2026-12-31",
        lot_size=4000,
        ltp=5.5,
        bid=5.4,
        ask=5.6,
        iv=12.0,
    )
    with patch("market.fno_ban.is_in_fno_ban", return_value=True):
        assert (
            resolve_option_contract(
                symbol="SAIL",
                spot=120.0,
                direction="BULLISH",
                india_vix=14.0,
                prefer_options=True,
                contracts_override=[fake_contract],
            )
            is None
        )

    with patch("market.fno_ban.is_in_fno_ban", return_value=False):
        plan = resolve_option_contract(
            symbol="SAIL",
            spot=120.0,
            direction="BULLISH",
            india_vix=14.0,
            prefer_options=True,
            contracts_override=[fake_contract],
        )
        assert plan is not None
        assert plan.contract_symbol == "NFO:SAIL26DECCALL120CE"
        assert plan.is_estimated is False
        assert plan.entry_premium == 5.5

    # Verify check_premarket_gap_invalidation evaluates NFO-wrapped swing alerts in spot coordinates
    eng = AutoAlertEngine.__new__(AutoAlertEngine)
    eng._lock = threading.RLock()
    eng._dispatch = lambda al: None
    eng._save = lambda: None

    a_chase = AutoAlert(
        alert_id="aa-vcp-sail-20261125",
        alert_type="VCP_PIVOT_BREAKOUT",
        stage="ACTIONABLE",
        symbol="SAIL",
        exchange="NFO",
        segment="NFO",
        direction="BULLISH",
        headline="h",
        summary="s",
        ltp=120.0,
        trigger_level=121.0,
        target_level=132.0,
        stop_loss=5.5,  # option premium SL (must NOT confuse spot check)
        no_chase_boundary=6.0,
        spot_no_chase_boundary=124.0,
        time_horizon="SWING_MID",
        metrics={
            "underlying_sl": 114.0,
            "underlying_target": 132.0,
            "spot_no_chase_boundary": 124.0,
        },
    )
    a_sl = AutoAlert(
        alert_id="aa-vcp-infy-20261125",
        alert_type="VCP_PIVOT_BREAKOUT",
        stage="ACTIONABLE",
        symbol="INFY",
        exchange="NFO",
        segment="NFO",
        direction="BULLISH",
        headline="h",
        summary="s",
        ltp=1500.0,
        trigger_level=1510.0,
        target_level=1620.0,
        stop_loss=20.0,  # option premium SL
        spot_no_chase_boundary=1545.0,
        time_horizon="SWING_MID",
        metrics={
            "underlying_sl": 1440.0,
            "underlying_target": 1620.0,
            "spot_no_chase_boundary": 1545.0,
        },
    )
    eng._alerts = [a_chase, a_sl]

    updated = eng.check_premarket_gap_invalidation(
        quotes_map={
            "NSE:SAIL": {"last_price": 126.5},  # > spot_no_chase_boundary 124.0
            "NSE:INFY": {"last_price": 1425.0},  # < underlying_sl 1440.0
        }
    )
    assert len(updated) == 2
    assert a_chase.premarket_gap_risk == "GAP_NO_CHASE"
    assert a_sl.premarket_gap_risk == "GAP_OVER_SL"
    assert a_sl.is_invalidated is True
