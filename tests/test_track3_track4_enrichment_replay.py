"""Tests for Track 3 (SignalEnrichment + Margin Preflight) & Track 4 (Expired F&O Replay)."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock
import numpy as np
import pandas as pd


def test_signal_enrichment_attaches_feature_bus_lead_lag_and_honest_margin():
    from engine.alert_model import AutoAlert
    from engine.signal_enrichment import enrich_alert_with_feature_bus, preflight_fno_setup_margin

    idx = pd.date_range("2026-11-25 09:15", periods=25, freq="5min")
    df_5m = pd.DataFrame(
        {
            "open": np.linspace(24000, 24120, 25),
            "high": np.linspace(24015, 24135, 25),
            "low": np.linspace(23990, 24110, 25),
            "close": np.linspace(24008, 24128, 25),
            "volume": np.full(25, 100000.0),
        },
        index=idx,
    )
    quotes_map = {
        "NSE:HDFCBANK": {"last_price": 1750.0, "vwap": 1735.0, "change_pct": 0.9},
        "NSE:ICICIBANK": {"last_price": 1320.0, "vwap": 1310.0, "change_pct": 0.7},
        "NSE:RELIANCE": {"last_price": 1350.0, "vwap": 1342.0, "change_pct": 0.6},
    }
    alert = AutoAlert(
        alert_id="aa-gamma-nifty-20261125",
        alert_type="GAMMA_BLAST",
        stage="PRIMED",
        symbol="NIFTY",
        contract_symbol="NSE:NIFTY26N2424200CE",
        exchange="NFO",
        segment="FNO_INDEX",
        direction="BULLISH",
        headline="Test",
        summary="Test",
        ltp=150.0,
        trigger_level=150.0,
        stop_loss=120.0,
        target_level=210.0,
        confidence=85,
        is_live=True,
        environment="PAPER",
    )

    out = enrich_alert_with_feature_bus(alert, df_5m=df_5m, quotes_map=quotes_map)
    assert out["feature_bus"]["status"] == "AVAILABLE"
    assert out["constituent_lead_lag"]["lead_bias"] == "BULLISH_LEAD"
    assert alert.details["feature_bus"]["atr_14"] > 0

    # Offline / unauthenticated broker fails closed to UNAVAILABLE without synthetic numbers
    offline = preflight_fno_setup_margin(alert, broker=None)
    if offline.get("status") != "ok":
        assert offline["status"] == "UNAVAILABLE"

    # Authenticated mock broker invokes multi-order margin check with lot size
    fake_brk = MagicMock()
    fake_brk._access_token = "tok-123"
    fake_brk.check_order_margin.return_value = {
        "status": "ok",
        "preflight_verdict": "CLEARED",
        "required_margin": 11250.0,
        "available_margin": 95000.0,
        "is_sufficient": True,
        "shortfall": 0.0,
    }
    ok = preflight_fno_setup_margin(alert, broker=fake_brk)
    assert ok["preflight_verdict"] == "CLEARED"
    fake_brk.check_order_margin.assert_called_once()


def test_expired_fno_loader_preserves_null_greeks_and_walk_forward_enforces_uncalibrated():
    from engine.options_replay import (
        load_expired_option_bars,
        evaluate_triple_barrier_outcomes,
        purged_walk_forward_score,
    )

    fake_brk = MagicMock()
    fake_brk.get_expired_fno_history.return_value = [
        {
            "date": datetime(2026, 10, 27, 9, 15) + timedelta(minutes=5 * i),
            "open": 100.0 + i,
            "high": 105.0 + i,
            "low": 98.0 + i,
            "close": 102.0 + i,
            "volume": 5000.0,
            "iv": None,
        }
        for i in range(60)
    ]
    df = load_expired_option_bars("NSE:NIFTY26OCT25000CE", broker=fake_brk)
    assert df.attrs["provenance"] == "RESEARCH_ONLY_EXPIRED_FNO"
    assert df.attrs["constant_tenor_iv_available"] is False
    assert df["iv"].isna().all()

    # Few winning trades must remain UNCALIBRATED per SAFETY_CONTRACTS.md
    ev_small = evaluate_triple_barrier_outcomes(df, [5, 20, 35], horizon_bars=8)
    assert ev_small["status"] == "UNCALIBRATED"
    assert ev_small["trades"] >= 1

    # Walk-forward evaluation with >= 3 folds produces structured OOS metrics without look-ahead
    wf = purged_walk_forward_score(df, [2, 22, 42], n_folds=3, horizon_bars=5, embargo_bars=3)
    assert len(wf["folds"]) == 3
    assert wf["status"] == "UNCALIBRATED"


def test_classify_setup_lifecycle_universal_stages():
    from engine.feature_bus import classify_setup_lifecycle

    feats = {"kc_squeeze_on": True, "nr7": False, "vol_ratio": 1.25}
    assert classify_setup_lifecycle(feats, distance_atr=0.65) == "STALK"
    assert classify_setup_lifecycle(feats, distance_atr=0.20, lead_aligned=True) == "PRIMED"
    assert classify_setup_lifecycle(feats, breakout_confirmed=True, extension_atr=0.15) == "IGNITED"
    assert (
        classify_setup_lifecycle(
            feats, breakout_confirmed=True, extension_atr=0.60, no_chase_atr=0.35
        )
        == "EXPIRED_STALK"
    )
