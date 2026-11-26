"""Regression tests for #SIG_SENSEX_83600PE_25NOV_1322 RCA and symmetric index signal quality gates."""

from types import SimpleNamespace

import pandas as pd

from engine.daily_levels import DailyLevels, evaluate_cpr_gate
from engine.detectors.index_call_setup import detect_index_call_setup
from engine.detectors.index_put_setup import detect_index_put_setup


def _make_chain_sensex(pe_oi_chg_total: int = 18_356_000, ce_oi_chg_total: int = 14_225_440):
    contracts = []
    for k in (83400.0, 83600.0, 83800.0):
        contracts.append(
            SimpleNamespace(
                symbol=f"BSE:SENSEX26NOV{int(k)}PE",
                underlying="SENSEX",
                strike=k,
                option_type="PE",
                ltp=469.85 if k == 83600.0 else 360.0,
                bid=469.5,
                ask=470.5,
                oi=600_000,
                oi_change=int(pe_oi_chg_total / 3),
                volume=30_000_000,
                pchange=12.0,
                delta=-0.50 if k == 83600.0 else -0.40,
                gamma=0.0004,
                iv=24.0,
                expiry="2026-11-26",
            )
        )
        contracts.append(
            SimpleNamespace(
                symbol=f"BSE:SENSEX26NOV{int(k)}CE",
                underlying="SENSEX",
                strike=k,
                option_type="CE",
                ltp=420.0 if k == 83600.0 else 310.0,
                bid=419.5,
                ask=420.5,
                oi=550_000,
                oi_change=int(ce_oi_chg_total / 3),
                volume=18_000_000,
                pchange=-4.0,
                delta=0.50 if k == 83600.0 else 0.40,
                gamma=0.0004,
                iv=23.8,
                expiry="2026-11-26",
            )
        )
    return contracts


def _make_5m_df(closes, highs=None, lows=None, opens=None):
    n = len(closes)
    idx = pd.date_range("2026-11-25 12:30", periods=n, freq="5min")
    opens = opens or [c * 0.9999 for c in closes]
    highs = highs or [max(o, c) + 25.0 for o, c in zip(opens, closes)]
    lows = lows or [min(o, c) - 25.0 for o, c in zip(opens, closes)]
    return pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [100_000] * n,
        },
        index=idx,
    )


def test_evaluate_cpr_gate_vetoes_wide_cpr_top_support_on_bearish():
    """
    Reproduces SENSEX at 83553.61 (+0.029% above Wide CPR Top 83529.42):
    Bearish continuation above Wide CPR approaching cpr_top MUST be vetoed.
    """
    dl = DailyLevels(
        symbol="SENSEX",
        canonical_symbol="SENSEX",
        exchange="BSE",
        session_date="2026-11-25",
        pdh=84450.0,
        pdl=82600.0,
        pdc=83700.0,
        cpr={
            "pivot": 83164.94,
            "tc": 82800.47,
            "bc": 83529.42,
            "top": 83529.42,
            "bottom": 82800.47,
            "width_pct": 0.8765,
            "is_wide": True,
            "is_narrow": False,
            "cpr_type": "WIDE",
        },
    )
    res_bear = evaluate_cpr_gate("SENSEX", spot=83553.61, direction="BEARISH", dl=dl)
    assert res_bear.is_vetoed is True
    assert "83,529.4" in (res_bear.veto_reason or "")

    # Symmetric bullish check just below Wide CPR Bottom resistance
    res_bull = evaluate_cpr_gate("SENSEX", spot=82780.0, direction="BULLISH", dl=dl)
    assert res_bull.is_vetoed is True
    assert "82,800.5" in (res_bull.veto_reason or "")

    # Reversals explicitly bypass boundary veto
    res_rev = evaluate_cpr_gate(
        "SENSEX", spot=83553.61, direction="BEARISH", dl=dl, is_reversal=True
    )
    assert res_rev.is_vetoed is False


def test_index_put_setup_suppresses_stalling_bottom_bounce_and_pe_writer_floor(monkeypatch):
    """
    Reproduces #SIG_SENSEX_83600PE_25NOV_1322:
    5m bar bouncing (+0.091% after -0.039% = STALLING_AT_BOTTOM) + PE writers dominating CE writers
    MUST NOT trigger a PE breakdown alert.
    """
    # Prior bar dropped (-0.15%), latest bar bounced +0.09% -> STALLING_AT_BOTTOM with green bar
    closes = [
        83780.0,
        83740.0,
        83700.0,
        83680.0,
        83650.0,
        83620.0,
        83600.0,
        83510.0,
        83478.0,
        83553.61,
    ]
    opens = closes[:-1] + [83480.0]
    df = _make_5m_df(closes, opens=opens)

    chain = _make_chain_sensex(pe_oi_chg_total=18_356_000, ce_oi_chg_total=14_225_440)
    monkeypatch.setattr("market.indices.get_vix", lambda: 18.0)

    alerts = detect_index_put_setup(
        underlying="SENSEX",
        spot=83553.61,
        chain=chain,
        vwap=83717.37,
        day_high=84450.0,
        day_low=83470.0,
        ohlcv_5m=df,
        prev_close=83700.0,
        ignore_time_gate=True,
    )
    assert alerts == []


def test_index_put_setup_bounds_spot_invalidation_anchor_on_vwap_breakdown(monkeypatch):
    """
    Even when day_high or older bars in ohlcv_5m are +1000 pts higher (84450+),
    spot_invalidation_anchor on a VWAP_BREAKDOWN PE must NEVER exceed spot + max_allowable_spot_risk
    and must stay anchored near VWAP reclaim.
    """
    # Clean accelerating red breakdown below VWAP (83717) with call writers dominating put writers
    closes = [
        83820.0,
        83800.0,
        83780.0,
        83760.0,
        83740.0,
        83725.0,
        83700.0,
        83650.0,
        83600.0,
        83520.0,
    ]
    opens = [c + 20.0 for c in closes]
    # Simulate an earlier bar in iloc[-4:] having an anomalous wick high at 84480 (the root cause of 84565 SL!)
    highs = [max(o, c) + 10.0 for o, c in zip(opens, closes)]
    highs[-4] = 84480.0
    df = _make_5m_df(closes, highs=highs, opens=opens)

    chain = _make_chain_sensex(pe_oi_chg_total=4_000_000, ce_oi_chg_total=12_000_000)
    monkeypatch.setattr("market.indices.get_vix", lambda: 18.0)

    alerts = detect_index_put_setup(
        underlying="SENSEX",
        spot=83520.0,
        chain=chain,
        vwap=83717.0,
        day_high=84480.0,
        day_low=83510.0,
        ohlcv_5m=df,
        prev_close=83700.0,
        ignore_time_gate=True,
    )
    if alerts:
        sl_anchor = float(alerts[0].actionable_plan["spot_invalidation_anchor"])
        assert sl_anchor <= 83520.0 + 450.0, f"Spot SL leaked too far: {sl_anchor}"
        assert sl_anchor <= 83717.0 + 180.0, (
            f"VWAP breakdown SL must track VWAP reclaim, got {sl_anchor}"
        )


def test_index_call_setup_suppresses_stalling_at_top_pullback(monkeypatch):
    """Symmetric guard: STALLING_AT_TOP red pullback bar suppresses routine CE breakout entries."""
    closes = [
        84100.0,
        84150.0,
        84200.0,
        84240.0,
        84280.0,
        84320.0,
        84360.0,
        84380.0,
        84460.0,
        84395.0,
    ]
    opens = closes[:-1] + [84455.0]
    df = _make_5m_df(closes, opens=opens)

    chain = _make_chain_sensex(pe_oi_chg_total=15_000_000, ce_oi_chg_total=5_000_000)
    monkeypatch.setattr("market.indices.get_vix", lambda: 17.5)

    alerts = detect_index_call_setup(
        underlying="SENSEX",
        spot=84395.0,
        chain=chain,
        vwap=84200.0,
        day_high=84480.0,
        day_low=84050.0,
        ohlcv_5m=df,
        prev_close=84100.0,
        ignore_time_gate=True,
    )
    # Any surviving alert must not be a routine breakout when STALLING_AT_TOP is active
    for a in alerts:
        sigs = (a.metrics or {}).get("signals") or []
        assert not any(
            s in sigs for s in ("VWAP_BREAKOUT", "DAY_HIGH_BREAKOUT", "MOMENTUM_EXPANSION")
        )


def test_afternoon_thrust_blocks_stalling_bottom_and_emits_signals(monkeypatch):
    """
    detect_afternoon_thrust must:
    1. Suppress BEARISH flush when 5m ROC is STALLING_AT_BOTTOM with a green bounce bar.
    2. Populate metrics['signals'] cleanly (never '([])') when a genuine flush triggers.
    """
    from datetime import datetime
    from unittest.mock import patch
    from config.constants import IST
    from engine.detectors.afternoon_thrust import detect_afternoon_thrust

    monkeypatch.setattr("market.indices.get_vix", lambda: 17.5)

    # Stalling bounce at low -> suppressed when ignore_time_gate=False (during 13:45 session)
    closes_stall = [
        83850.0,
        83820.0,
        83790.0,
        83760.0,
        83740.0,
        83720.0,
        83700.0,
        83680.0,
        83630.0,
        83690.0,
    ]
    opens_stall = closes_stall[:-1] + [83640.0]
    df_stall = _make_5m_df(closes_stall, opens=opens_stall)
    df_stall.index = pd.date_range(
        "2026-11-25 13:00", periods=len(closes_stall), freq="5min", tz=IST
    )

    with patch("engine.daily_levels.get_daily_levels", return_value=None):
        res_stall = detect_afternoon_thrust(
            symbol="SENSEX",
            df_5m=df_stall,
            ltp=83690.0,
            vwap=83800.0,
            day_high=84200.0,
            day_low=83630.0,
            rvol=1.4,
            ref_time=datetime(2026, 11, 25, 13, 45, 0, tzinfo=IST),
            ignore_time_gate=False,
        )
    assert res_stall is None

    # Genuine red breakdown flush -> emits non-empty signals list
    closes_bear = [
        83900.0,
        83880.0,
        83850.0,
        83820.0,
        83790.0,
        83760.0,
        83730.0,
        83700.0,
        83650.0,
        83580.0,
    ]
    opens_bear = [c + 20.0 for c in closes_bear]
    df_bear = _make_5m_df(closes_bear, opens=opens_bear)
    df_bear.index = pd.date_range("2026-11-25 13:00", periods=len(closes_bear), freq="5min", tz=IST)

    with patch("engine.daily_levels.get_daily_levels", return_value=None):
        res_bear = detect_afternoon_thrust(
            symbol="SENSEX",
            df_5m=df_bear,
            ltp=83580.0,
            vwap=83800.0,
            day_high=84200.0,
            day_low=83580.0,
            rvol=1.5,
            ref_time=datetime(2026, 11, 25, 13, 45, 0, tzinfo=IST),
            ignore_time_gate=False,
        )
    assert res_bear is not None
    sigs = (res_bear.metrics or {}).get("signals") or []
    assert "AFTERNOON_THRUST" in sigs
    assert "VWAP_BREAKDOWN" in sigs


def test_post_expired_strike_cooldown_and_time_stop_pnl_accuracy(monkeypatch):
    """
    1. Post-EXPIRED cooldown blocks immediate re-dispatch of exact same strike in live mode.
    2. TIME_STOP_EXIT overwrites stale pnl_pct with actual realized exit PnL (-6.9%, not -38.2%).
    3. APEX_CONFLUENCE_UPGRADE ignores already-closed TIME_STOP_EXIT alerts.
    """
    from datetime import datetime
    from config.constants import IST
    from engine.alert_model import AutoAlert
    from engine.auto_alert_engine import AutoAlertEngine

    engine = AutoAlertEngine()
    engine._alerts.clear()

    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    expired_jindal = AutoAlert(
        alert_id="aa-options-momentum-jindalstel-pe-1100-1300-20261125",
        alert_type="OPTIONS_MOMENTUM",
        stage="EXPIRED",
        symbol="JINDALSTEL",
        exchange="NFO",
        direction="BEARISH",
        headline="JINDALSTEL 1100 PE",
        summary="Expired",
        ltp=17.6,
        trigger_level=30.2,
        target_level=42.6,
        stop_loss=23.1,
        strike=1100.0,
        option_type="PE",
        contract_symbol="NSE:JINDALSTEL26DEC1100PE",
        confidence=96,
        created_at=now_str,
        archived_at=now_str,
        is_live=True,
        environment="LIVE",
        is_archived=True,
    )
    engine._alerts.append(expired_jindal)

    monkeypatch.setenv("CHANAKYA_TESTING", "0")
    nestle = AutoAlert(
        alert_id="aa-options-momentum-nestleind-ce-1340-1130-20261125",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NESTLEIND",
        exchange="NFO",
        direction="BULLISH",
        headline="NESTLEIND 1340 CE",
        summary="Test",
        ltp=36.25,
        trigger_level=38.95,
        target_level=55.3,
        stop_loss=33.63,
        strike=1340.0,
        option_type="CE",
        contract_symbol="NSE:NESTLEIND26DEC1340CE",
        option_premium=38.95,
        confidence=96,
        pnl_pct=-38.23,  # stale incorrect pnl
        created_at=now_str,
        is_live=False,
        environment="TEST",
    )
    engine._alerts.append(nestle)
    monkeypatch.setattr(engine, "_save", lambda **kw: None)
    monkeypatch.setattr(engine, "_dispatch", lambda *a, **kw: None)
    engine._handle_alert_exit(
        nestle,
        "Velocity Stagnation Time-Stop: Option momentum stalled for 45m without reaching +0.5R expansion. Exited at scratch level ₹36.2 to prevent theta decay.",
        current_ltp=36.25,
        now_iso=now_str,
        loop_context="Test",
    )
    assert nestle.stage == "TIME_STOP_EXIT"
    assert abs(float(nestle.pnl_pct) - (-6.9)) <= 0.2, f"Expected ~-6.9%, got {nestle.pnl_pct}"

    # Ensure APEX_CONFLUENCE_UPGRADE does NOT touch already-closed TIME_STOP_EXIT alert
    bnf_closed = AutoAlert(
        alert_id="aa-index-call-setup-banknifty-ce-63900-0915-20261125",
        alert_type="INDEX_CALL_SETUP",
        stage="TIME_STOP_EXIT",
        symbol="BANKNIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="BNF",
        summary="Closed",
        ltp=1582.85,
        trigger_level=1643.65,
        target_level=2000.0,
        stop_loss=1400.0,
        strike=63900.0,
        option_type="CE",
        confidence=92,
        created_at=now_str,
        is_live=False,
        environment="TEST",
    )
    engine._alerts.append(bnf_closed)
    bnf_new = AutoAlert(
        alert_id="aa-chart-db-banknifty-20261125",
        alert_type="CHART_DOUBLE_BOTTOM",
        stage="IGNITED",
        symbol="BANKNIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="BNF DB",
        summary="DB",
        ltp=64000.0,
        trigger_level=64000.0,
        target_level=64500.0,
        stop_loss=63800.0,
        confidence=88,
        created_at=now_str,
        is_live=False,
        environment="TEST",
    )
    # Run real record_alert() path; because bnf_closed is TIME_STOP_EXIT it must NOT be upgraded
    monkeypatch.setattr(engine, "_repository", __import__("unittest.mock").mock.MagicMock())
    engine.record_alert(bnf_new)
    assert bnf_closed.confidence == 92
    assert "CHART_DOUBLE_BOTTOM" not in (
        (bnf_closed.metrics or {}).get("confluence_detectors") or []
    )
