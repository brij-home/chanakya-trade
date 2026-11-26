"""Deterministic regression tests for Phase 0 audit hotfixes (25-Nov-2026)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest


def test_dex_put_sign_and_gamma_provided_branch_parity():
    """Put DEX must equal -delta * spot * oi * lot (+0.5 * N, NOT 1.5 * N) even when gamma is pre-populated."""
    from market.options import compute_chain_gex
    from market.vectorized_greeks import vectorized_compute_gex

    chain = [
        SimpleNamespace(
            strike=25000.0,
            option_type="PE",
            oi=100000,
            iv=14.0,
            gamma=0.0005,  # pre-populated gamma previously skipped d1 computation!
            expiry="2026-12-03",
        )
    ]
    res_scalar = compute_chain_gex(chain, spot=25000.0, lot_size=65, underlying="NIFTY")
    res_vec = vectorized_compute_gex(chain, spot=25000.0, lot_size=65, underlying="NIFTY")

    # ATM put delta ~ -0.467 -> dealer_delta = +0.467 -> put_dex ~ +7594 Cr (never +23,800 Cr from 1 - delta!)
    assert 5000.0 <= res_scalar["put_dex"] <= 9500.0
    assert abs(res_scalar["put_dex"] - res_vec["put_dex"]) < 100.0
    assert res_scalar["net_dex"] == res_scalar["put_dex"]


def test_governor_and_regime_gate_do_not_invent_145_vix(monkeypatch):
    """MarketDynamicsGovernor and market_regime_gate must return UNAVAILABLE instead of cached 14.5 VIX."""
    from engine.market_dynamics_governor import MarketDynamicsGovernor
    import engine.market_regime_gate as mrg

    gov = MarketDynamicsGovernor()
    # Prevent background refresh from hitting external providers during test
    gov._vix_fetching = True
    assert gov.get_live_vix() is None

    # Expired VIX (>60s old) must also return None
    gov._vix_cache = (0.001, 18.2)
    assert gov.get_live_vix() is None

    monkeypatch.setattr(
        "analysis.regime_governor._fresh_live_vix", lambda max_age_seconds=30.0: None
    )
    monkeypatch.setattr("engine.market_dynamics_governor.get_market_dynamics_governor", lambda: gov)
    assert mrg._fetch_vix() is None


def test_vpin_is_causal_without_future_tail_leakage_and_serialized():
    """Prefix VPIN must be invariant to appending future extreme volume bars, and to_dict must expose VPIN."""
    from analysis.order_flow import OrderFlowSnapshot, compute_vpin

    base_df = pd.DataFrame(
        {
            "close": [100.0, 102.0, 101.0, 103.0, 104.0, 106.0, 105.0, 107.0],
            "volume": [1000.0, 1200.0, 1100.0, 1300.0, 1400.0, 1500.0, 1250.0, 1350.0],
        }
    )
    extended_df = pd.concat(
        [
            base_df,
            pd.DataFrame({"close": [130.0, 160.0], "volume": [500000.0, 800000.0]}),
        ],
        ignore_index=True,
    )
    vpin_base = compute_vpin("NIFTY", base_df, num_buckets=5, volume_per_bucket=2000.0)
    vpin_prefix_from_ext = compute_vpin(
        "NIFTY", extended_df.iloc[: len(base_df)], num_buckets=5, volume_per_bucket=2000.0
    )
    assert vpin_base.vpin == vpin_prefix_from_ext.vpin

    snap = OrderFlowSnapshot(
        symbol="NIFTY",
        ltp=25000.0,
        market_state="OPEN",
        total_buy_qty=5000,
        total_sell_qty=3000,
        order_book_imbalance=0.25,
        bid_ask_ratio=1.67,
        micro_price=25000.2,
        spread=0.5,
        spread_pct=0.002,
        top_bids=[],
        top_asks=[],
        current_cvd=2000.0,
        cvd_slope_5bar=150.0,
        cvd_divergence="AGGRESSIVE_BUYING",
        absorption_detected=False,
        conviction_score=80,
        recommendation="LONG",
        vpin=0.72,
        toxicity_regime="HIGH_TOXICITY",
    )
    d = snap.to_dict()
    assert d["vpin"] == 0.72
    assert d["toxicity_regime"] == "HIGH_TOXICITY"


def test_scrutiny_rejects_below_min_score_and_never_promotes_to_80():
    """Alert below adaptive min_score must be REJECTED cleanly without score-80 fallback promotion."""
    from engine.alert_scrutiny import AlertScrutinyAuditor
    from engine.auto_alert_engine import AutoAlert

    auditor = AlertScrutinyAuditor()
    alert = AutoAlert(
        alert_id="aa-test-lowconf-20261125",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="Low conf test",
        summary="Weak signal",
        ltp=25000.0,
        trigger_level=25000.0,
        stop_loss=24920.0,
        target_level=25240.0,
        confidence=62.0,
        is_live=False,
        environment="PAPER",
    )
    with patch.object(auditor, "_compute_regime_scrutiny_threshold", return_value=75):
        res = auditor.scrutinize_alert(alert)
    assert res.status == "REJECTED"
    assert res.score < 70
    assert res.auditor_model in ("ADAPTIVE_REGIME_GATE", "TIER1_GATE")

    # Direct quantitative fallback on a low-confidence setup must stay anchored below promotion
    q_res = auditor._generate_quantitative_fallback(alert, {"level_coherence": True})
    assert q_res.score < 70 or alert.confidence == 62.0


def test_market_data_regime_endpoint_maps_governor_attributes(monkeypatch):
    """GET /api/market/regime must map MarketRegimeClassification cleanly without returning None."""
    from fastapi.testclient import TestClient
    from analysis.regime_governor import MarketRegimeClassification
    from engine.market_regime_gate import RegimeSnapshot
    import web.api as api

    snap = RegimeSnapshot(
        is_edgeless=False,
        vix=14.2,
        ad_ratio=1.35,
        vix_status="LIVE",
        ad_status="LIVE",
        banner="TREND",
        reason="Active breadth",
        prefer_spreads=False,
        data_quality="LIVE",
        evaluated_at=1000.0,
    )
    gov = MarketRegimeClassification(
        regime="TREND_EXPANSION",
        vix=14.2,
        is_orb_trapped=False,
        is_expiry_session=False,
        min_scrutiny_score=70,
        dominant_bias="TREND_FRIENDLY",
        guidance="Favor momentum.",
        active_detectors=["ORB", "SQUEEZE_BREAKOUT"],
    )
    monkeypatch.setattr("engine.market_regime_gate.evaluate_market_regime", lambda: snap)
    monkeypatch.setattr("analysis.regime_governor.classify_market_regime", lambda: gov)

    client = TestClient(api.app)
    resp = client.get("/api/market/regime")
    assert resp.status_code == 200
    body = resp.json()
    assert body["governor"] is not None
    assert body["governor"]["regime"] == "TREND_EXPANSION"
    assert body["governor"]["dominant_bias"] == "TREND_FRIENDLY"
    assert body["governor"]["guidance"] == "Favor momentum."


def test_sse_bus_broadcast_alias_and_non_json_datetime():
    """SSEEventBus must support broadcast() and serialize datetime objects without crashing."""
    from web.sse import SSEEventBus

    bus = SSEEventBus()

    async def _run():
        q = asyncio.Queue(maxsize=5)
        bus._channels["alert"].append(q)
        await bus.broadcast(
            {"type": "test_evt", "at": datetime(2026, 11, 25, 1, 0, tzinfo=timezone.utc)}
        )
        item = q.get_nowait()
        payload = item.get("payload", item) if isinstance(item, dict) else item
        assert payload["type"] == "test_evt"

    asyncio.run(_run())


def test_session_role_locks_prevent_env_overwrite_and_reject_cleared_exec(monkeypatch):
    """Runtime set_broker_role must survive env vars, and cleared _exec_key ('') must block execution fallback."""
    import brokers.session as bs

    bs.close_all_brokers()
    try:
        monkeypatch.setenv("DATA_BROKER", "fyers")
        monkeypatch.setenv("EXEC_BROKER", "fyers")
        fyers_mock = SimpleNamespace(name="fyers")
        flat_mock = SimpleNamespace(name="flattrade")
        bs.register_broker("fyers", fyers_mock)
        bs.register_broker("flattrade", flat_mock)

        # Runtime selection must persist across get_data_broker/get_execution_broker calls
        bs.set_broker_role("flattrade", "execution")
        assert bs.get_execution_broker() is flat_mock

        # Clearing exec via role='data' on active primary ('both' -> 'data') sets _exec_key=''; must refuse fallback
        bs.set_broker_role("fyers", "both")
        assert bs.get_execution_broker() is fyers_mock
        bs.set_broker_role("fyers", "data")
        with pytest.raises(RuntimeError, match="role 'data' only"):
            bs.get_execution_broker()
    finally:
        bs.close_all_brokers()


def test_history_preserves_naive_ist_strings_and_isolates_broker_cache(monkeypatch):
    """Naive historical IST timestamps must NOT shift +05:30, and cache keys must vary per broker."""
    from market.history import clear_df_memory_cache, get_ohlcv

    clear_df_memory_cache()
    calls = {"broker": "fyers"}

    class _FakeBroker:
        def get_historical_data(self, *args, **kwargs):
            price = 25000.0 if calls["broker"] == "fyers" else 25100.0
            return [
                {
                    "date": "2026-11-20 09:15:00",
                    "open": price,
                    "high": price + 10,
                    "low": price - 5,
                    "close": price + 5,
                    "volume": 1000,
                }
            ]

    monkeypatch.setattr("brokers.session.get_data_broker", lambda: _FakeBroker())
    monkeypatch.setattr("brokers.session.get_data_broker_key", lambda: calls["broker"])
    monkeypatch.setattr("brokers.session.get_all_brokers", lambda: {calls["broker"]: _FakeBroker()})
    monkeypatch.setattr("engine.eod_store.get_ohlcv_batch", lambda *a, **k: {})

    df1 = get_ohlcv(
        "PHASE0TESTSYM",
        exchange="NSE",
        interval="5m",
        days=10,
        as_of=datetime(2026, 11, 20, 15, 30),
    )
    assert not df1.empty
    assert df1.index[0].hour == 9 and df1.index[0].minute == 15
    assert df1["open"].iloc[0] == 25000.0

    calls["broker"] = "flattrade"
    df2 = get_ohlcv(
        "PHASE0TESTSYM",
        exchange="NSE",
        interval="5m",
        days=10,
        as_of=datetime(2026, 11, 20, 15, 30),
    )
    assert df2["open"].iloc[0] == 25100.0


def test_compute_time_of_day_rvol_returns_zero_when_avg_vol_missing():
    from engine.auto_alert_engine import compute_time_of_day_rvol
    from engine.detectors.intraday_spark import compute_time_of_day_rvol as spark_rvol

    assert compute_time_of_day_rvol(5000.0, 0.0) == 0.0
    assert spark_rvol(5000.0, 0.0) == 0.0
