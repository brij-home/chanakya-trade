"""Deterministic verification tests for Phase 2A upgrades (Vanna/Charm, 50-depth OBI, symmetric Regime Governor, proportional SL)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import numpy as np

from config.constants import IST


def test_vectorized_greeks_computes_vanna_and_charm_and_chain_aggregates():
    from market.vectorized_greeks import (
        vectorized_black_scholes_greeks,
        vectorized_compute_gex,
    )

    spots = np.array([25000.0, 25000.0])
    strikes = np.array([24500.0, 25500.0])  # OTM put vs OTM call
    t_years = np.array([3.0 / 365.25, 3.0 / 365.25])
    sigmas = np.array([0.14, 0.14])
    is_call = np.array([False, True])

    g = vectorized_black_scholes_greeks(
        spots=spots, strikes=strikes, t_years=t_years, sigmas=sigmas, is_call=is_call
    )
    assert "vanna" in g and "charm" in g
    assert np.all(np.isfinite(g["vanna"]))
    assert np.all(np.isfinite(g["charm"]))
    # Opposite d2 signs around spot produce opposite Vanna signs for 24500 vs 25500
    assert g["vanna"][0] < 0.0 and g["vanna"][1] > 0.0

    chain = [
        SimpleNamespace(strike=24500.0, option_type="PE", oi=150000, iv=14.0, expiry="2026-12-03"),
        SimpleNamespace(strike=25500.0, option_type="CE", oi=200000, iv=14.0, expiry="2026-12-03"),
    ]
    res = vectorized_compute_gex(chain, spot=25000.0, lot_size=65, underlying="NIFTY")
    assert "net_vanna_cr" in res
    assert "net_charm_cr" in res
    assert isinstance(res["net_vanna_cr"], float)


def test_bisect_depth_book_multi_layer_obi_50_depth():
    from market.order_book import BisectDepthBook

    book = BisectDepthBook(max_depth=50)
    # Spoofed slight ask pressure at top 5 levels, but massive institutional bid wall at L6-25
    bids = [
        {"price": 25000.0 - i * 0.5, "quantity": 100 if i < 5 else 2500, "orders": 4}
        for i in range(15)
    ]
    asks = [
        {"price": 25000.5 + i * 0.5, "quantity": 300 if i < 5 else 200, "orders": 4}
        for i in range(15)
    ]
    book.batch_update(bids, asks)

    layers = book.multi_layer_obi()
    assert layers["has_50_depth"] is True
    assert layers["obi_l1_5"] < 0.0  # top 5 ask skewed (-0.5)
    assert layers["obi_l6_25"] > 0.70  # deep levels 6-25 heavily bid skewed!
    assert layers["deep_wall_skew"] > 1.0
    assert layers["weighted_micro_price"] > 0.0


def test_regime_governor_symmetric_institutional_accumulation():
    from analysis.regime_governor import (
        classify_market_regime,
        is_detector_eligible_for_regime,
    )

    dt = datetime(2026, 11, 20, 10, 30, tzinfo=IST)
    regime = classify_market_regime(
        vix=14.0,
        nifty_spot=25200.0,
        orb_high=25100.0,
        orb_low=24950.0,
        global_macro_score=35.0,
        ref_dt=dt,
    )
    assert regime.regime == "INSTITUTIONAL_ACCUMULATION"
    assert regime.dominant_bias == "BULLISH_EXPANSION"

    # Counter-trend general breakdown should be suppressed without structural sweep or high RVOL
    ok_weak, _ = is_detector_eligible_for_regime(
        "SQUEEZE_BREAKDOWN",
        regime,
        rvol=1.1,
        has_structural_sweep=False,
        direction="BEARISH",
    )
    assert ok_weak is False

    # Lagging RS breakdown with 1.7x RVOL passes calibrated floor
    ok_rs, _ = is_detector_eligible_for_regime(
        "SQUEEZE_BREAKDOWN",
        regime,
        rvol=1.7,
        direction="BEARISH",
        sector_rs_lagging=True,
    )
    assert ok_rs is True


def test_free_index_router_uses_proportional_option_sl_ceiling(monkeypatch):
    from engine.alert_model import AutoAlert
    from engine.free_index_router import FreeIndexRouter

    router = FreeIndexRouter()
    monkeypatch.setattr(router, "is_enabled", lambda: True)
    monkeypatch.setattr(router, "get_chat_id", lambda: "-100999")

    # 1. Major index (BANKNIFTY): 45 pts = 30% on 150 premium passes major proportional ceiling (<= max(35, 30%)=45)
    major_ok = AutoAlert(
        alert_id="aa-prop-sl-bn-20261125",
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        symbol="BANKNIFTY",
        exchange="NFO",
        segment="FNO_INDEX",
        direction="BULLISH",
        headline="BANKNIFTY CE Momentum",
        summary="Proportional SL test",
        ltp=150.0,
        trigger_level=150.0,
        stop_loss=105.0,
        target_level=240.0,
        strike=52000.0,
        option_type="CE",
        option_premium=150.0,
        option_stop_loss=105.0,
        confidence=80,
        is_live=False,
        environment="PAPER",
    )
    assert router.is_candidate(major_ok) is True

    # 2. NIFTY calibrated intraday SL: 28 pts on 150 premium (<= min(35, 28%)=35.0) passes;
    #    swing-sized 45 pts (> 35.0 intraday cap) is suppressed.
    nifty_ok = AutoAlert(
        alert_id="aa-prop-sl-nifty-ok-20261125",
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        segment="FNO_INDEX",
        direction="BULLISH",
        headline="NIFTY CE Momentum",
        summary="Calibrated intraday SL test",
        ltp=150.0,
        trigger_level=150.0,
        stop_loss=122.0,
        target_level=210.0,
        strike=25000.0,
        option_type="CE",
        option_premium=150.0,
        option_stop_loss=122.0,
        confidence=80,
        is_live=False,
        environment="PAPER",
    )
    assert router.is_candidate(nifty_ok) is True

    nifty_wide = AutoAlert(
        alert_id="aa-prop-sl-nifty-wide-20261125",
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        segment="FNO_INDEX",
        direction="BULLISH",
        headline="NIFTY CE Wide SL",
        summary="Oversized swing SL test",
        ltp=150.0,
        trigger_level=150.0,
        stop_loss=105.0,
        target_level=240.0,
        strike=25000.0,
        option_type="CE",
        option_premium=150.0,
        option_stop_loss=105.0,
        confidence=80,
        is_live=False,
        environment="PAPER",
    )
    assert router.is_candidate(nifty_wide) is False
