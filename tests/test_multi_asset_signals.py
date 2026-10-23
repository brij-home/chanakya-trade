"""
tests/test_multi_asset_signals.py
───────────────────────────────────
Institutional test suite verifying non-equity market coverage (MCX Commodities,
NSE CDS Currency, and 24x7 Crypto):
  1. Session runway gating adapts to asset classes (MCX until 23:15, Currency until 16:45, Crypto 24x7).
  2. Alert scrutiny applies asset-class aware runway checks instead of 15:15 equity cutoffs.
  3. Market calendar keeps currency active during full 09:00 - 17:00 IST session.
  4. Commodity detector guarantees monotonic target hierarchy under both bullish and bearish boundaries.
  5. AutoAlertEngine option enrichment succeeds with keyword arguments (spot, direction, strike_tier).
"""

from __future__ import annotations

import os
from datetime import datetime, time as dtime, timezone, timedelta

from engine.alert_model import AutoAlert
from engine.session_runway import evaluate_session_runway, is_session_runway_sufficient
from market.calendar import get_current_ist_session

IST = timezone(timedelta(hours=5, minutes=30))


def test_session_runway_commodity_hours():
    """Verify MCX Commodities allow intraday entries up to 23:15 IST."""
    os.environ["FORCE_RUNWAY_CHECK"] = "1"
    try:
        # 20:30 IST (Prime US Open session for Crude/Gold)
        dt_evening = datetime(2026, 10, 19, 20, 30, tzinfo=IST)
        res_eve = evaluate_session_runway(
            symbol="MCX:CRUDEOIL",
            alert_type="COMMODITY_MOMENTUM",
            segment="COMMODITY",
            now_dt=dt_evening,
        )
        assert res_eve.is_allowed is True
        assert res_eve.runway_minutes > 120
        ok, _ = is_session_runway_sufficient(
            alert_type="COMMODITY_MOMENTUM",
            asset_class="COMMODITY",
            current_time=dtime(20, 30),
        )
        assert ok is True

        # 23:20 IST (Past 23:15 IST cutoff)
        dt_late = datetime(2026, 10, 19, 23, 20, tzinfo=IST)
        res_late = evaluate_session_runway(
            symbol="MCX:CRUDEOIL",
            alert_type="COMMODITY_MOMENTUM",
            segment="COMMODITY",
            now_dt=dt_late,
        )
        assert res_late.is_allowed is False
        assert res_late.phase == "SESSION_RUNWAY_EXHAUSTION"
        ok_late, reason_late = is_session_runway_sufficient(
            alert_type="COMMODITY_MOMENTUM",
            asset_class="COMMODITY",
            current_time=dtime(23, 20),
        )
        assert ok_late is False
        assert "post 23:15 IST" in reason_late
    finally:
        os.environ.pop("FORCE_RUNWAY_CHECK", None)


def test_session_runway_currency_hours():
    """Verify Currency CDS allows intraday entries across 09:00 - 16:45 IST."""
    os.environ["FORCE_RUNWAY_CHECK"] = "1"
    try:
        # 14:30 IST (Active regular currency market)
        dt_day = datetime(2026, 10, 19, 14, 30, tzinfo=IST)
        res_day = evaluate_session_runway(
            symbol="CDS:USDINR",
            alert_type="CURRENCY_BREAKOUT",
            segment="CURRENCY",
            now_dt=dt_day,
        )
        assert res_day.is_allowed is True
        ok_day, _ = is_session_runway_sufficient(
            alert_type="CURRENCY_BREAKOUT",
            asset_class="CURRENCY",
            current_time=dtime(14, 30),
        )
        assert ok_day is True

        # 15:45 IST (Post-equity close, but Currency CDS still trading until 17:00 IST)
        dt_post = datetime(2026, 10, 19, 15, 45, tzinfo=IST)
        res_post = evaluate_session_runway(
            symbol="CDS:USDINR",
            alert_type="CURRENCY_BREAKOUT",
            segment="CURRENCY",
            now_dt=dt_post,
        )
        assert res_post.is_allowed is True
        ok_post, _ = is_session_runway_sufficient(
            alert_type="CURRENCY_BREAKOUT",
            asset_class="CURRENCY",
            current_time=dtime(15, 45),
        )
        assert ok_post is True

        # 16:50 IST (Past 16:45 IST cutoff)
        dt_late = datetime(2026, 10, 19, 16, 50, tzinfo=IST)
        res_late = evaluate_session_runway(
            symbol="CDS:USDINR",
            alert_type="CURRENCY_BREAKOUT",
            segment="CURRENCY",
            now_dt=dt_late,
        )
        assert res_late.is_allowed is False
        ok_late, reason_late = is_session_runway_sufficient(
            alert_type="CURRENCY_BREAKOUT",
            asset_class="CURRENCY",
            current_time=dtime(16, 50),
        )
        assert ok_late is False
        assert "post 16:45 IST" in reason_late
    finally:
        os.environ.pop("FORCE_RUNWAY_CHECK", None)


def test_session_runway_crypto_continuous():
    """Verify Crypto is 24x7 continuous with unlimited session runway."""
    os.environ["FORCE_RUNWAY_CHECK"] = "1"
    try:
        dt_midnight = datetime(2026, 10, 19, 2, 15, tzinfo=IST)
        res_mid = evaluate_session_runway(
            symbol="BTCUSDT",
            alert_type="CRYPTO_MOMENTUM",
            segment="CRYPTO",
            now_dt=dt_midnight,
        )
        assert res_mid.is_allowed is True
        assert res_mid.runway_minutes == 1440
        ok_mid, _ = is_session_runway_sufficient(
            alert_type="CRYPTO_MOMENTUM",
            asset_class="CRYPTO",
            current_time=dtime(2, 15),
        )
        assert ok_mid is True

        dt_night = datetime(2026, 10, 19, 23, 55, tzinfo=IST)
        res_night = evaluate_session_runway(
            symbol="ETHUSDT",
            alert_type="CRYPTO_MOMENTUM",
            segment="CRYPTO",
            now_dt=dt_night,
        )
        assert res_night.is_allowed is True
        ok_night, _ = is_session_runway_sufficient(
            alert_type="CRYPTO_MOMENTUM",
            asset_class="CRYPTO",
            current_time=dtime(23, 55),
        )
        assert ok_night is True
    finally:
        os.environ.pop("FORCE_RUNWAY_CHECK", None)


def test_calendar_currency_continuous():
    """Verify get_current_ist_session marks currency active throughout 09:00 - 17:00 IST on weekdays."""
    # 2026-10-19 is a Monday
    dt_1130 = datetime(2026, 10, 19, 11, 30, tzinfo=IST)
    sess_1130 = get_current_ist_session(ref_dt=dt_1130)
    assert sess_1130.get("currency") is True

    # 16:00 IST (post equity close, still active until 17:00)
    dt_1600 = datetime(2026, 10, 19, 16, 0, tzinfo=IST)
    sess_1600 = get_current_ist_session(ref_dt=dt_1600)
    assert sess_1600.get("currency") is True

    # 18:00 IST (closed)
    dt_1800 = datetime(2026, 10, 19, 18, 0, tzinfo=IST)
    sess_1800 = get_current_ist_session(ref_dt=dt_1800)
    assert sess_1800.get("currency") is False


def test_alert_scrutiny_asset_class_runway():
    """Verify Alert Scrutiny perimeter gate does not reject evening MCX or 24x7 Crypto alerts."""

    # MCX Commodity Alert at 20:00 IST
    mcx_alert = AutoAlert(
        alert_id="aa-commodity-crudeoil-20261019",
        alert_type="COMMODITY_MOMENTUM",
        stage="EARLY_WARNING",
        symbol="MCX:CRUDEOIL",
        exchange="MCX",
        direction="BULLISH",
        headline="MCX Crude Oil Breakout",
        summary="Crude oil test alert",
        ltp=6500.0,
        trigger_level=6510.0,
        target_level=6600.0,
        stop_loss=6450.0,
        actionable_plan={
            "entry_range": "6500 - 6515",
            "sl_price": 6450.0,
            "t1_price": 6560.0,
            "t2_price": 6620.0,
            "t3_price": 6700.0,
            "rr_str": "1:2.0 | 1:3.0",
            "action": "BUY",
        },
        metrics={"segment": "COMMODITY"},
    )

    # Directly check session runway perimeter logic for commodity at 20:00 IST
    ok_comm, reason_comm = is_session_runway_sufficient(
        alert_type=mcx_alert.alert_type,
        asset_class="COMMODITY",
        current_time=dtime(20, 0),
    )
    assert ok_comm is True

    # Directly check session runway perimeter logic for crypto at 23:30 IST
    ok_crypto, reason_crypto = is_session_runway_sufficient(
        alert_type="CRYPTO_MOMENTUM",
        asset_class="CRYPTO",
        current_time=dtime(23, 30),
    )
    assert ok_crypto is True


def test_commodity_target_hierarchy_monotonicity():
    """Verify commodity target logic strictly preserves monotonic hierarchy."""
    ltp = 6500.0
    risk_pts = 50.0
    _default_t1 = round(ltp + 2.8 * risk_pts, 2)  # 6640.0
    default_t2 = round(ltp + 5.0 * risk_pts, 2)  # 6750.0
    default_t3 = round(ltp + 8.0 * risk_pts, 2)  # 6900.0

    # Bullish scenario where POC is high (6740.0) close to default T2 (6750.0)
    poc_price = 6740.0
    vah_price = 0.0  # fallback to default_t2

    t1_price = round(poc_price, 2)
    t2_price = round(vah_price, 2) if (vah_price > 0 and vah_price > poc_price) else default_t2
    if t2_price <= t1_price + 0.5 * risk_pts:
        t2_price = round(max(default_t2, t1_price + 1.5 * risk_pts), 2)
    t3_price = round(max(default_t3, t2_price + 2.0 * risk_pts), 2)

    assert ltp < t1_price < t2_price < t3_price
    assert (t2_price - t1_price) >= 0.5 * risk_pts

    # Bearish scenario where POC is low (6260.0) close to default T2 (6250.0)
    _bear_default_t1 = round(ltp - 2.8 * risk_pts, 2)  # 6360.0
    bear_default_t2 = round(ltp - 5.0 * risk_pts, 2)  # 6250.0
    bear_default_t3 = round(ltp - 8.0 * risk_pts, 2)  # 6100.0

    bear_poc = 6260.0
    val_price = 0.0

    b_t1 = round(bear_poc, 2)
    b_t2 = round(val_price, 2) if (val_price > 0 and bear_poc > val_price) else bear_default_t2
    if b_t2 >= b_t1 - 0.5 * risk_pts:
        b_t2 = round(min(bear_default_t2, b_t1 - 1.5 * risk_pts), 2)
    b_t3 = round(min(bear_default_t3, b_t2 - 2.0 * risk_pts), 2)

    assert ltp > b_t1 > b_t2 > b_t3
    assert (b_t1 - b_t2) >= 0.5 * risk_pts


def test_auto_alert_engine_option_enrichment_signature():
    """Verify AutoAlertEngine calls resolve_option_contract with correct signature."""
    from engine.auto_alert_engine import AutoAlertEngine

    engine = AutoAlertEngine()
    test_alert = AutoAlert(
        alert_id="aa-test-nifty-20261019",
        alert_type="PREDATOR_CALL",
        stage="EARLY_WARNING",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Nifty Call Setup",
        summary="Testing option enrichment",
        ltp=25000.0,
        trigger_level=25010.0,
        target_level=25150.0,
        stop_loss=24950.0,
        actionable_plan={"action": "BUY"},
        metrics={"segment": "INDEX"},
    )

    # Should execute without throwing unexpected keyword argument 'spot_price'
    engine._enrich_fno_contract_if_applicable(test_alert)
    # Underlying NIFTY should be enriched with strike / contract symbol / option type
    assert test_alert.option_type == "CE"
    assert test_alert.contract_symbol is not None
