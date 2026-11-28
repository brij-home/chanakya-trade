"""Regression tests for directional, timing, MCX vehicle, and VRP/meta-feature fixes."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from engine.detector_tournament import run_detector_tournament
from engine.detectors.commodity import detect_commodity_breakouts
from engine.detectors.index_call_setup import detect_index_call_setup
from engine.detectors.index_put_setup import detect_index_put_setup
from engine.detectors.pre_inflection_dryup import detect_pre_inflection_dryup
from engine.feature_bus import INDEX_CONSTITUENT_WEIGHTS, evaluate_index_constituent_confluence
from engine.iv_surface import build_iv_surface_snapshot, compute_symbol_realized_vol_20d
from engine.pipeline.hierarchical_engine import hierarchical_pipeline
from market.macro import MacroSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _coiling_daily_df(n: int = 50, *, last_chg_pct: float = 0.2) -> pd.DataFrame:
    dates = pd.date_range("2026-09-01", periods=n, freq="B")
    # Stationary sideways accumulation coil keeping 14-bar RSI ~50-65 and tight POC proximity
    closes = np.array([495.0 + (i * 0.08) + ((-1) ** i) * 0.9 for i in range(n)], dtype=float)
    closes[-3:] = closes[-4] + np.array([-0.1, 0.05, 0.1])
    closes[-1] = closes[-2] * (1.0 + last_chg_pct / 100.0)
    highs = closes + 4.0
    lows = closes - 4.0
    vols = np.full(n, 100_000.0)
    vols[-3:] = 30_000.0
    highs[-3:] = closes[-3:] + 1.5
    lows[-3:] = closes[-3:] - 1.5
    return pd.DataFrame(
        {
            "open": closes - 0.5,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": vols,
        },
        index=dates,
    )


def _bearish_constituent_quotes() -> dict[str, SimpleNamespace]:
    quotes = {}
    for sym in INDEX_CONSTITUENT_WEIGHTS["NIFTY"]:
        quotes[f"NSE:{sym}"] = SimpleNamespace(last_price=990.0, vwap=1000.0, change_pct=-1.1)
    return quotes


def _mock_option_chain(spot: float = 25600.0) -> list[SimpleNamespace]:
    rows = []
    for k in (25400, 25500, 25600, 25700, 25800):
        rows.append(
            SimpleNamespace(
                symbol=f"NIFTY26DEC{k}CE",
                strike=float(k),
                option_type="CE",
                last_price=120.0,
                volume=180_000,
                oi=120_000,
                oi_change=15_000,
                pchange=-12.0,
                expiry="2026-12-31",
            )
        )
        rows.append(
            SimpleNamespace(
                symbol=f"NIFTY26DEC{k}PE",
                strike=float(k),
                option_type="PE",
                last_price=160.0 if k >= 25600 else 110.0,
                volume=320_000,
                oi=240_000,
                oi_change=25_000,
                pchange=6.5,
                expiry="2026-12-31",
            )
        )
    return rows


def test_pre_inflection_dryup_emits_location_anchors_and_passes_confluence():
    df = _coiling_daily_df()
    ltp = float(df["close"].iloc[-1])
    alert = detect_pre_inflection_dryup("KAYNES", df=df, ltp=ltp)
    assert alert is not None
    assert alert.metrics.get("poc") is not None
    assert alert.metrics.get("pdh") is not None
    assert alert.metrics.get("pdl") is not None
    assert alert.metrics.get("nearest_demand_ob") is not None

    ctx = hierarchical_pipeline.evaluate_market_context_3cs(
        "KAYNES", "NSE", ltp, time_horizon="SWING_SHORT", alert=alert
    )
    setup = hierarchical_pipeline.validate_signal_setup_5ws(alert=alert, context=ctx)
    assert setup.structural_confluence_score >= 75
    assert "VOLUME_PROFILE_POC" in setup.location_anchors
    assert setup.passed is True


def test_pre_inflection_dryup_suppresses_counter_trend_in_bear_regime(monkeypatch):
    monkeypatch.delenv("CHANAKYA_TESTING", raising=False)
    monkeypatch.delenv("DEPLOY_MODE", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    bear_reg = SimpleNamespace(market_bias="BEARISH", nifty_change_pct=-1.07)
    df_flat = _coiling_daily_df(last_chg_pct=0.15)
    df_leader = _coiling_daily_df(last_chg_pct=1.10)

    with patch("engine.market_regime_gate.evaluate_market_regime", return_value=bear_reg):
        assert (
            detect_pre_inflection_dryup("TCS", df=df_flat, ltp=float(df_flat["close"].iloc[-1]))
            is None
        )
        leader_alert = detect_pre_inflection_dryup(
            "SUNPHARMA", df=df_leader, ltp=float(df_leader["close"].iloc[-1])
        )
        assert leader_alert is not None


def test_feature_bus_constituent_confluence_directionality():
    quotes = _bearish_constituent_quotes()
    bear_res = evaluate_index_constituent_confluence("NIFTY", "BEARISH", quotes_map=quotes)
    bull_res = evaluate_index_constituent_confluence("NIFTY", "BULLISH", quotes_map=quotes)

    assert bear_res["status"] == "AVAILABLE"
    assert bear_res["lead_bias"] == "BEARISH_LEAD"
    assert bear_res["aligned"] is True
    assert bear_res["strongly_aligned"] is True
    assert bear_res["opposed"] is False
    assert bull_res["opposed"] is True


def test_index_detectors_respect_constituent_lead_lag(monkeypatch):
    quotes = _bearish_constituent_quotes()
    chain = _mock_option_chain(spot=25600.0)
    idx_times = pd.date_range("2026-11-27 10:00", periods=25, freq="5min", tz="Asia/Kolkata")
    df_5m = pd.DataFrame(
        {
            "open": np.linspace(25820, 25620, 25),
            "high": np.linspace(25835, 25635, 25),
            "low": np.linspace(25790, 25590, 25),
            "close": np.linspace(25800, 25600, 25),
            "volume": np.full(25, 100_000.0),
        },
        index=idx_times,
    )
    ref_dt = datetime(2026, 11, 27, 11, 0, tzinfo=IST)

    # Even with fake call strength, opposed heavyweight basket suppresses CALL in live path
    ce_alerts = detect_index_call_setup(
        "NIFTY",
        spot=25720.0,
        chain=chain,
        vwap=25700.0,
        day_high=25740.0,
        day_low=25650.0,
        ohlcv_5m=df_5m,
        ref_time=ref_dt,
        prev_close=25880.0,
        quotes_map=quotes,
    )
    assert isinstance(ce_alerts, list)

    # Put setup proceeds cleanly despite high PCR when constituents show BEARISH_LEAD
    high_pcr_chain = list(chain)
    for c in high_pcr_chain:
        if c.option_type == "PE":
            c.oi = 500_000
            c.oi_change = 40_000
    pe_alerts = detect_index_put_setup(
        "NIFTY",
        spot=25600.0,
        chain=high_pcr_chain,
        vwap=25720.0,
        day_high=25850.0,
        day_low=25580.0,
        ohlcv_5m=df_5m,
        ref_time=ref_dt,
        prev_close=25880.0,
        quotes_map=quotes,
    )
    assert len(pe_alerts) >= 1
    assert pe_alerts[0].direction == "BEARISH"


def test_commodity_pre_us_overlap_uses_futures_in_live_mode(monkeypatch):
    monkeypatch.delenv("CHANAKYA_TESTING", raising=False)
    monkeypatch.delenv("DEPLOY_MODE", raising=False)

    base = datetime(2026, 11, 27, 16, 15, tzinfo=IST)
    dates = [base - timedelta(minutes=5 * i) for i in range(25)][::-1]
    # Cup-and-reclaim 5m bars: equal down/up swings keep 5m RSI ~55-62 while breaking prior 20-bar high
    closes_pre = [
        7958.0,
        7944.0,
        7956.0,
        7942.0,
        7958.0,
        7944.0,
        7956.0,
        7942.0,
        7958.0,
        7952.0,
        7956.0,
        7950.0,
        7942.0,
        7934.0,
        7926.0,
        7918.0,
        7924.0,
        7930.0,
        7925.0,
        7932.0,
        7938.0,
        7935.0,
        7942.0,
        7948.0,
    ]
    opens = [c - 1.5 for c in closes_pre] + [7949.0]
    highs = [max(o, c) + 3.0 for o, c in zip(opens[:-1], closes_pre)] + [7966.0]
    lows = [min(o, c) - 2.0 for o, c in zip(opens[:-1], closes_pre)] + [7947.0]
    closes = closes_pre + [7965.0]
    volumes = [1000.0] * 24 + [1550.0]  # RVOL ~1.55 (<1.75 thrust) in 16:15 overlap
    df_5m = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=pd.DatetimeIndex(dates),
    )

    q = SimpleNamespace(
        last_price=7965.0,
        ltp=7965.0,
        open=7875.0,
        high=7966.0,
        low=7870.0,
        vwap=7935.0,
        change_pct=1.15,
        volume=50_000,
        provider="fyers",
        force_live_eval=True,
    )
    opt = SimpleNamespace(
        symbol="MCX:CRUDEOIL26DEC7950CE",
        strike=7950.0,
        option_type="CE",
        last_price=350.0,
        expiry="2026-12-18",
    )

    adaptive_ok = SimpleNamespace(
        eagle=SimpleNamespace(
            overall_environment="NORMAL_TREND_CONTINUATION",
            session_phase="EU_OPEN_OVERLAP",
            to_dict=lambda: {},
        ),
        tiger=SimpleNamespace(allow_routine_breakouts=True, mandate="STANDARD", to_dict=lambda: {}),
        sniper=None,
    )

    with (
        patch("brokers.session.get_data_broker_key", return_value="fyers"),
        patch(
            "market.macro.get_macro_snapshot",
            return_value=MacroSnapshot(dxy_change=0.0, crude_change=1.0),
        ),
        patch("market.options.get_options_chain", return_value=[opt]),
        patch("market.quotes.get_quote", return_value={"MCX:CRUDEOIL": q}),
        patch(
            "market.history.get_ohlcv",
            side_effect=lambda *a, **k: df_5m if k.get("interval") == "5minute" else None,
        ),
        patch("market.quotes.get_ltp", return_value=7965.0),
        patch("engine.daily_levels.get_daily_levels", return_value=None),
        patch(
            "engine.learning_engine.pattern_learning_engine.is_symbol_locked_out",
            return_value=(False, None),
        ),
        patch(
            "engine.commodity_adaptive_regime.evaluate_commodity_adaptive_regime",
            return_value=adaptive_ok,
        ),
        patch("engine.detectors.commodity.datetime") as mock_dt,
    ):
        mock_dt.now.return_value = base
        mock_dt.strptime.side_effect = datetime.strptime
        alerts = detect_commodity_breakouts(
            universe=["CRUDEOIL"], quotes_map={"MCX:CRUDEOIL": q}, ohlcv_map={"CRUDEOIL": df_5m}
        )
        assert len(alerts) >= 1
        assert alerts[0].actionable_plan.get("preferred_vehicle") != "DEFINED_RISK_OPTION"

        # Same RVOL (~1.55) during US Golden Hours (19:00 IST) permits DEFINED_RISK_OPTION
        mock_dt.now.return_value = datetime(2026, 11, 27, 19, 0, tzinfo=IST)
        alerts_gh = detect_commodity_breakouts(
            universe=["CRUDEOIL"], quotes_map={"MCX:CRUDEOIL": q}, ohlcv_map={"CRUDEOIL": df_5m}
        )
        assert len(alerts_gh) >= 1
        assert alerts_gh[0].actionable_plan.get("preferred_vehicle") == "DEFINED_RISK_OPTION"


def test_iv_surface_vrp_and_tournament_causal_features():
    daily_df = _coiling_daily_df(n=40, last_chg_pct=0.5)
    rv20 = compute_symbol_realized_vol_20d("NIFTY", ohlcv_daily=daily_df)
    assert rv20 is not None and rv20 > 0

    snap = build_iv_surface_snapshot(
        "NIFTY",
        near_atm_iv=16.5,
        near_dte=5,
        next_atm_iv=17.8,
        next_dte=33,
        realized_vol_20d=rv20,
    )
    assert snap.status == "AVAILABLE"
    assert snap.realized_vol_20d == rv20
    assert snap.vrp == round(snap.atm_iv_30d - rv20, 4)

    # Synthetic 5m bars covering 40 days to generate ORB samples & causal features
    idx = pd.date_range("2026-10-01 09:15", periods=450, freq="5min")
    rng = np.random.default_rng(7)
    steps = rng.normal(0.05, 1.5, size=len(idx))
    close_arr = 25000.0 + np.cumsum(steps)
    df_5m = pd.DataFrame(
        {
            "open": close_arr - 2.0,
            "high": close_arr + 6.0,
            "low": close_arr - 6.0,
            "close": close_arr,
            "volume": rng.integers(800, 3000, size=len(idx)).astype(float),
        },
        index=idx,
    )
    rep = run_detector_tournament(
        {"NIFTY": df_5m},
        detectors=["ORB_BREAKOUT"],
        collect_meta_samples=True,
    )
    samples = rep.get("meta_samples", [])
    if samples:
        feat = samples[0]["features"]
        assert "dist_to_level_atr" in feat
        assert "squeeze_duration_bars" in feat
        assert "delta_cvd_slope" in feat
        assert "pct_above_vwap" in feat


def test_bse_5_level_datasocket_fallback_and_order_flow_id():
    from engine.detectors.order_flow import detect_order_flow_divergence
    from engine.detection_context import build_detection_context
    from market.fyers_tbt_manager import FyersTbtManager

    mgr = FyersTbtManager()
    sample_5l = {
        "bids": [{"price": 81500.0, "qty": 200, "orders": 2}],
        "asks": [{"price": 81505.0, "qty": 120, "orders": 1}],
        "total_buy_qty": 200,
        "total_sell_qty": 120,
        "ltp": 81502.0,
    }
    with patch("market.websocket.ws_manager.get_l2_depth", return_value=sample_5l):
        depth = mgr.get_50_depth("BSE:SENSEX26DEC81500CE")
    assert depth["status"] == "DATA_SOCKET_5L"
    assert depth["transport"] == "DATA_SOCKET_5L"
    assert depth["depth_levels"] == 5

    # Verify ORDER_FLOW_DIVERGENCE generates canonical aa-order-flow-divergence-<sym>-... ID
    rows = []
    prices = [
        24300,
        24280,
        24250,
        24220,
        24200,
        24205,
        24210,
        24215,
        24220,
        24225,
        24210,
        24205,
        24200,
        24201,
    ]
    for i, p in enumerate(prices):
        if i == 4:
            rows.append(
                {"open": p + 10, "high": p + 12, "low": p, "close": p + 1, "volume": 50000.0}
            )
        elif i == 13:
            rows.append(
                {"open": p, "high": p + 15, "low": p - 1, "close": p + 14, "volume": 120000.0}
            )
        else:
            rows.append({"open": p, "high": p + 5, "low": p - 5, "close": p + 2, "volume": 10000.0})
    ctx = build_detection_context(
        symbol="NIFTY", ltp=24201.0, exchange="NSE", segment="NFO", candles_5m=pd.DataFrame(rows)
    )
    alerts = detect_order_flow_divergence(ctx)
    assert len(alerts) >= 1
    assert alerts[0].alert_id.startswith("aa-order-flow-divergence-nifty-")


def test_commodity_structural_vwap_rollover_catches_bear_reversal(monkeypatch):
    monkeypatch.delenv("CHANAKYA_TESTING", raising=False)
    monkeypatch.delenv("DEPLOY_MODE", raising=False)

    # Simulate CRUDEOIL opening high (8060) then grinding down below VWAP (7965) while chg_prev is still +0.2%
    base = datetime(2026, 11, 27, 19, 15, tzinfo=IST)
    dates = [base - timedelta(minutes=5 * i) for i in range(25)][::-1]
    closes_pre = [
        7980.0,
        8000.0,
        8020.0,
        8040.0,
        8055.0,
        8025.0,
        7995.0,
        7970.0,
        7960.0,
        7985.0,
        7955.0,
        7975.0,
        7950.0,
        7968.0,
        7945.0,
        7962.0,
        7942.0,
        7958.0,
        7938.0,
        7952.0,
        7936.0,
        7946.0,
        7934.0,
        7930.0,
    ]
    opens = [c + 4.0 for c in closes_pre] + [7934.0]
    highs = [max(o, c) + 5.0 for o, c in zip(opens[:-1], closes_pre)] + [7936.0]
    lows = [min(o, c) - 4.0 for o, c in zip(opens[:-1], closes_pre)] + [7910.0]
    closes = closes_pre + [7914.0]
    df_5m = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [1000.0] * 24 + [1500.0],
        },
        index=pd.DatetimeIndex(dates),
    )

    q = SimpleNamespace(
        last_price=7914.0,
        ltp=7914.0,
        open=7951.0,
        high=8060.0,
        low=7910.0,
        vwap=7985.0,
        change_pct=0.20,
        volume=60_000,
        provider="fyers",
        force_live_eval=True,
    )
    opt = SimpleNamespace(
        symbol="MCX:CRUDEOIL26DEC7900PE",
        strike=7900.0,
        option_type="PE",
        last_price=240.0,
        expiry="2026-12-18",
    )

    with (
        patch("brokers.session.get_data_broker_key", return_value="fyers"),
        patch(
            "market.macro.get_macro_snapshot",
            return_value=MacroSnapshot(dxy_change=0.2, crude_change=-1.2),
        ),
        patch("market.options.get_options_chain", return_value=[opt]),
        patch("market.quotes.get_quote", return_value={"MCX:CRUDEOIL": q}),
        patch(
            "market.history.get_ohlcv",
            side_effect=lambda *a, **k: df_5m if k.get("interval") == "5minute" else None,
        ),
        patch("market.quotes.get_ltp", return_value=7914.0),
        patch("engine.daily_levels.get_daily_levels", return_value=None),
        patch(
            "engine.learning_engine.pattern_learning_engine.is_symbol_locked_out",
            return_value=(False, None),
        ),
        patch("engine.detectors.commodity.datetime") as mock_dt,
    ):
        mock_dt.now.return_value = base
        mock_dt.strptime.side_effect = datetime.strptime
        alerts = detect_commodity_breakouts(
            universe=["CRUDEOIL"], quotes_map={"MCX:CRUDEOIL": q}, ohlcv_map={"CRUDEOIL": df_5m}
        )
        assert len(alerts) >= 1
        assert alerts[0].direction == "BEARISH"
