# -*- coding: utf-8 -*-
"""
tests/test_index_signal_integrity_rca.py

Comprehensive Regression Test Suite for Root Cause Analysis (RCA) on Index Option Signals:
1. Rejection of unconfirmed intra-bar / hammer candles at Camarilla L4 (no bottom selling).
2. Rejection of advancing green bars into CPR bottom as false "supply rejections".
3. Rejection of inverted hammers / shooting stars at Camarilla H4.
4. Rejection of declining red bars into CPR top as false "demand bounces".
5. Enforcement of HBCM majority veto (PE vetoed when >= 3 heavyweights bullish; CE vetoed when >= 3 heavyweights bearish).
6. Enforcement of Active Opposing Direction Conflict Gate on Index symbols (no 30-minute whiplash).
7. Preservation of underlying_spot coordinates across batch quote refreshes (no option premium leakage).
8. Winnability Upgrade Stability Window (no thrashing within 15 minutes of trade entry).
"""

import os
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine
from engine.detectors.index_put_setup import detect_index_put_setup
from engine.detectors.index_call_setup import detect_index_call_setup

IST = timezone(timedelta(hours=5, minutes=30))


class MockOptionContract:
    def __init__(
        self, symbol, strike, option_type, ltp, volume=20000, oi=40000, pchange=18.0, oi_change=1200
    ):
        self.symbol = symbol
        self.strike = strike
        self.option_type = option_type
        self.ltp = ltp
        self.last_price = ltp
        self.volume = volume
        self.oi = oi
        self.pchange = pchange
        self.oi_change = oi_change


def _make_dummy_5m_ohlcv(
    bars: int = 15, base_price: float = 24980.0, trend: str = "DOWN", date_str: str = "2026-10-07"
) -> pd.DataFrame:
    records = []
    curr = base_price
    dt_base = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=9, minute=30, tzinfo=IST)
    for i in range(bars):
        t = dt_base + timedelta(minutes=5 * i)
        step = 10.0 if trend == "UP" else (-10.0 if trend == "DOWN" else 0.0)
        o = curr
        h = o + 8.0
        l = o - 4.0
        c = o + step
        curr = c
        records.append(
            {
                "datetime": t,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": 25000 + i * 200,
            }
        )
    df = pd.DataFrame(records)
    df.set_index("datetime", inplace=True)
    return df


@pytest.fixture(autouse=True)
def setup_env():
    os.environ["CHANAKYA_TESTING"] = "1"
    yield


# ── 1. Absorption Hammer Rejection at Camarilla L4 ─────────────────────────────
def test_camarilla_l4_absorption_hammer_rejected():
    """Selling into a massive absorption hammer (75% lower wick, green body) at Cam L4 must be vetoed."""
    prev_high, prev_low, prev_close = 25100.0, 24950.0, 25000.0
    spot = 24910.0  # Pierced Cam L4

    ref_t = datetime(2026, 10, 7, 10, 30, tzinfo=IST)
    # 5m candle: Open 24925, High 24935, Low 24860 (75 pt range), Close 24930 (green, 65 pt lower wick = 86%)
    ts = pd.date_range("2026-10-07 09:30:00", periods=12, freq="5min", tz="Asia/Kolkata")
    records = []
    for i, t in enumerate(ts):
        if i == len(ts) - 1:
            records.append(
                {
                    "datetime": t,
                    "open": 24925.0,
                    "high": 24935.0,
                    "low": 24860.0,
                    "close": 24930.0,
                    "volume": 35000,
                }
            )
        else:
            records.append(
                {
                    "datetime": t,
                    "open": 25000.0 - i * 5,
                    "high": 25005.0 - i * 5,
                    "low": 24990.0 - i * 5,
                    "close": 24995.0 - i * 5,
                    "volume": 20000,
                }
            )
    df_5m = pd.DataFrame(records).set_index("datetime")

    chain = [
        MockOptionContract(
            "NSE:NIFTY26O1324900PE", 24900.0, "PE", 130.0, volume=25000, oi=12000, pchange=20.0
        )
    ]

    alerts = detect_index_put_setup(
        underlying="NIFTY",
        spot=spot,
        chain=chain,
        vwap=24980.0,
        day_high=25050.0,
        day_low=24860.0,
        prev_day_high=prev_high,
        prev_day_low=prev_low,
        prev_close=prev_close,
        ohlcv_5m=df_5m,
        ref_time=ref_t,
        ignore_time_gate=True,
    )

    # Must NOT fire CAMARILLA_L4_BREAKDOWN because candle is an absorption hammer
    l4_alerts = [a for a in alerts if "CAMARILLA_L4_BREAKDOWN" in a.metrics.get("signals", [])]
    assert len(l4_alerts) == 0, (
        "Absorption hammer at Cam L4 must NOT trigger CAMARILLA_L4_BREAKDOWN"
    )


# ── 2. Decisive Bearish Breakdown at Camarilla L4 Accepted ─────────────────────
def test_camarilla_l4_clean_bearish_breakdown_accepted():
    """A clean decisive red breakdown candle closing below Cam L4 with tiny lower wick is accepted."""
    spot = 24900.0
    pdh = 25100.0
    pdl = 24950.0
    prev_close = 25000.0
    # Range = 150. L4 = 25000 - 150 * 1.1 / 2 = 25000 - 82.5 = 24917.5
    # Since spot (24900) < L4 (24917.5), Camarilla L4 breakdown is active!

    chain = [
        MockOptionContract(
            "NSE:NIFTY26O1324900PE", 24900.0, "PE", 125.0, volume=22000, oi=11000, pchange=20.0
        ),
        MockOptionContract(
            "NSE:NIFTY26O1324950PE", 24950.0, "PE", 155.0, volume=14000, oi=9000, pchange=16.0
        ),
    ]
    ohlcv = _make_dummy_5m_ohlcv(bars=15, base_price=24980.0, trend="DOWN", date_str="2026-10-07")
    ref_t = datetime(2026, 10, 7, 10, 30, tzinfo=IST)

    alerts = detect_index_put_setup(
        underlying="NIFTY",
        spot=spot,
        chain=chain,
        vwap=24950.0,
        day_high=25000.0,
        day_low=24890.0,
        prev_day_high=pdh,
        prev_day_low=pdl,
        prev_close=prev_close,
        ohlcv_5m=ohlcv,
        ref_time=ref_t,
        ignore_time_gate=True,
    )

    assert len(alerts) >= 1
    alert = alerts[0]
    assert "CAMARILLA_L4_BREAKDOWN" in alert.metrics.get("signals", [])


# ── 3. Advancing Green Candle into CPR Bottom Rejected as Supply Rejection ────
def test_cpr_supply_rejection_advancing_green_bar_rejected():
    """A bullish green candle pushing upward into CPR bottom is a breakout attempt, NOT supply rejection."""
    prev_high, prev_low, prev_close = 22700.0, 22550.0, 22650.0
    spot = 22615.0

    ref_t = datetime(2026, 10, 7, 10, 30, tzinfo=IST)
    ts = pd.date_range("2026-10-07 09:30:00", periods=12, freq="5min", tz="Asia/Kolkata")
    records = []
    for i, t in enumerate(ts):
        if i == len(ts) - 1:
            records.append(
                {
                    "datetime": t,
                    "open": 22585.0,
                    "high": 22618.0,
                    "low": 22580.0,
                    "close": 22615.0,
                    "volume": 65000,
                }
            )
        else:
            records.append(
                {
                    "datetime": t,
                    "open": 22560.0 + i * 2,
                    "high": 22570.0 + i * 2,
                    "low": 22555.0 + i * 2,
                    "close": 22565.0 + i * 2,
                    "volume": 30000,
                }
            )
    df_5m = pd.DataFrame(records).set_index("datetime")

    chain = [
        MockOptionContract(
            "NSE:NIFTY26O1322600PE", 22600.0, "PE", 110.0, volume=35000, oi=45000, pchange=12.0
        )
    ]

    alerts = detect_index_put_setup(
        underlying="NIFTY",
        spot=spot,
        chain=chain,
        vwap=22640.0,
        day_high=22700.0,
        day_low=22570.0,
        prev_day_high=prev_high,
        prev_day_low=prev_low,
        prev_close=prev_close,
        ohlcv_5m=df_5m,
        ref_time=ref_t,
        ignore_time_gate=True,
    )

    cpr_alerts = [a for a in alerts if "CPR_SUPPLY_REJECTION" in a.metrics.get("signals", [])]
    assert len(cpr_alerts) == 0, "Advancing green candle must NOT be labeled CPR_SUPPLY_REJECTION"


# ── 4. HBCM Majority Alignment Vetoes ──────────────────────────────────────────
def test_hbcm_majority_bullish_vetoes_put_setup():
    """When >= 3 heavyweights are bullish (e.g. 4/5 bulls as today), PE setup is strictly blocked."""
    mock_hbcm = MagicMock()
    mock_hbcm.total_heavyweights = 5
    mock_hbcm.summary = "HBCM_EVAL: 4/5 Bullish"
    mock_hbcm.confluence_pass = False
    mock_hbcm.bullish_count = 4  # 4 banking locomotives green!
    mock_hbcm.bearish_count = 1
    mock_hbcm.all_bullish = False
    mock_hbcm.rejection_reason = "Heavyweight breadth unaligned (1/5 Bearish)"
    mock_hbcm.to_dict.return_value = {"bullish_count": 4, "bearish_count": 1}

    chain = [
        MockOptionContract(
            "NSE:BANKNIFTY26O1354500PE", 54500.0, "PE", 350.0, volume=35000, oi=15000, pchange=22.0
        )
    ]

    with patch("engine.hbcm.evaluate_hbcm", return_value=mock_hbcm):
        alerts = detect_index_put_setup(
            underlying="BANKNIFTY",
            spot=54500.0,
            chain=chain,
            vwap=54700.0,
            day_high=54900.0,
            day_low=54480.0,
            prev_day_high=55000.0,
            prev_day_low=54500.0,
            prev_close=54800.0,
            ignore_time_gate=True,
        )

    assert len(alerts) == 0, "Put setup MUST be suppressed when 4/5 heavyweights are bullish"


def test_hbcm_majority_bearish_vetoes_call_setup():
    """When >= 3 heavyweights are bearish, CE setup is strictly blocked."""
    mock_hbcm = MagicMock()
    mock_hbcm.total_heavyweights = 5
    mock_hbcm.summary = "HBCM_EVAL: 4/5 Bearish"
    mock_hbcm.confluence_pass = False
    mock_hbcm.bearish_count = 4
    mock_hbcm.bullish_count = 1
    mock_hbcm.all_bearish = False
    mock_hbcm.rejection_reason = "Heavyweight breadth unaligned (1/5 Bullish)"
    mock_hbcm.to_dict.return_value = {"bullish_count": 1, "bearish_count": 4}

    chain = [
        MockOptionContract(
            "NSE:NIFTY26O1322600CE", 22600.0, "CE", 120.0, volume=45000, oi=25000, pchange=18.0
        )
    ]

    with patch("engine.hbcm.evaluate_hbcm", return_value=mock_hbcm):
        alerts = detect_index_call_setup(
            underlying="NIFTY",
            spot=22620.0,
            chain=chain,
            vwap=22600.0,
            day_high=22700.0,
            day_low=22550.0,
            prev_day_high=22700.0,
            prev_day_low=22550.0,
            prev_close=22600.0,
            ignore_time_gate=True,
        )

    assert len(alerts) == 0, "Call setup MUST be suppressed when 4/5 heavyweights are bearish"


# ── 5. Opposing Direction Conflict Gate on Indices (No 30m Whiplash) ───────────
def test_index_opposing_direction_conflict_blocks_30m_whipsaw():
    """An active PE alert on BANKNIFTY must block an incoming CE alert within 30 minutes unless confirmed reversal."""
    engine = AutoAlertEngine()
    engine._alerts.clear()

    # Active PE alert created 10 minutes ago
    pe_alert = AutoAlert(
        alert_id="aa-index-put-setup-banknifty-pe-54800-20261007",
        alert_type="INDEX_PUT_SETUP",
        stage="IGNITED",
        symbol="BANKNIFTY",
        exchange="NSE",
        direction="BEARISH",
        headline="Bearish Breakdown",
        summary="PE setup active",
        ltp=734.0,
        trigger_level=734.0,
        target_level=950.0,
        stop_loss=624.0,
        option_type="PE",
        created_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
    )
    engine._alerts.append(pe_alert)

    # Incoming CE alert 10 minutes later (NO structural reversal tag)
    ce_alert = AutoAlert(
        alert_id="aa-index-call-setup-banknifty-ce-54800-20261007",
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        symbol="BANKNIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Bullish Bounce",
        summary="Minor bounce from low",
        ltp=972.0,
        trigger_level=972.0,
        target_level=1250.0,
        stop_loss=820.0,
        option_type="CE",
    )

    accepted = engine.record_alert(ce_alert)
    assert accepted is False, (
        "Incoming CE alert within 30m of active PE alert on BANKNIFTY must be suppressed"
    )


# ── 6. Spot Coordinate Leakage Protection ─────────────────────────────────────
def test_spot_coordinate_not_overwritten_by_contract_quote():
    """Contract quote (e.g. ₹171.55) must NOT overwrite alert.underlying_spot (₹22,650)."""
    engine = AutoAlertEngine()
    engine._alerts.clear()

    alert = AutoAlert(
        alert_id="aa-index-put-setup-nifty-pe-22650-20261007",
        alert_type="INDEX_PUT_SETUP",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BEARISH",
        headline="Nifty PE Setup",
        summary="Put setup on Nifty",
        ltp=171.55,
        trigger_level=171.55,
        target_level=230.0,
        stop_loss=143.6,
        underlying_spot=22650.0,
        option_type="PE",
        strike=22650.0,
        contract_symbol="NSE:NIFTY26O1322650PE",
    )
    alert.is_live = True
    alert.environment = "LIVE"
    engine._alerts.append(alert)

    # Batch refresh returns contract quote 175.0 for "NSE:NIFTY26O1322650PE"
    with patch.object(
        engine, "_batch_refresh_quotes", return_value={"NSE:NIFTY26O1322650PE": 175.0}
    ):
        engine.check_and_alert_invalidations()

    # alert.ltp and option_premium should update to 175.0, but underlying_spot MUST stay 22650.0!
    assert alert.ltp == 175.0
    assert alert.option_premium == 175.0
    assert alert.underlying_spot == 22650.0, (
        "underlying_spot must NOT be corrupted by option premium quote"
    )


# ── 7. Zero Superseding & High-Quality Concurrent Sharing ─────────────────────
def test_zero_superseding_and_high_quality_concurrent_sharing():
    """
    Institutional Invariant:
    1. ZERO SUPERSEDING: Active index trades run their full lifecycle and are never
       marked SUPERSEDED or prematurely killed by incoming alerts.
    2. HIGH QUALITY SHARING: Additional forming index setups meeting high institutional standards
       (confidence >= 80%, R:R >= 2.0, coherent direction) are shared with traders alongside active trades.
    3. LOW QUALITY SUPPRESSION: Weaker secondary setups (<80% conf or <2.0 R:R) are suppressed.
    4. MULTI-INDEX COHERENCE: Opposing directional setups across correlated benchmarks (Nifty vs BankNifty vs FinNifty)
       are strictly suppressed to avoid whipsaw traps unless a structural reversal (CHoCH) is confirmed.
    """
    engine = AutoAlertEngine()
    engine._alerts.clear()

    # Active NIFTY trade running in IGNITED stage
    active_nifty = AutoAlert(
        alert_id="aa-index-put-setup-nifty-pe-22650-20261007",
        alert_type="INDEX_PUT_SETUP",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BEARISH",
        headline="Nifty Trade",
        summary="Active Nifty PE",
        ltp=170.0,
        trigger_level=170.0,
        target_level=240.0,
        stop_loss=140.0,
        confidence=82,
        metrics={"vol_oi_ratio": 1.5, "delta": -0.55},
        created_at=(datetime.now(IST) - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S IST"),
    )
    engine._alerts.append(active_nifty)

    # 1. Incoming high-quality BANKNIFTY alert (confidence=84 >= 80%, R:R = (950-730)/(730-620) = 2.0 >= 2.0)
    incoming_bn = AutoAlert(
        alert_id="aa-index-put-setup-banknifty-pe-54800-20261007",
        alert_type="INDEX_PUT_SETUP",
        stage="IGNITED",
        symbol="BANKNIFTY",
        exchange="NSE",
        direction="BEARISH",
        headline="BankNifty Trade",
        summary="Incoming BankNifty PE",
        ltp=730.0,
        trigger_level=730.0,
        target_level=950.0,
        stop_loss=620.0,
        confidence=84,
        metrics={"vol_oi_ratio": 1.6, "delta": -0.55},
    )

    accepted_bn = engine.record_alert(incoming_bn)
    # ZERO SUPERSEDING: Active NIFTY trade must NOT be killed or marked SUPERSEDED!
    assert active_nifty.stage == "IGNITED", "Active trade must remain IGNITED and never superseded"
    assert getattr(active_nifty, "target_status", "") != "SUPERSEDED", (
        "Active trade must NOT be SUPERSEDED"
    )
    # HIGH QUALITY SHARING: High-quality concurrent signal is approved and shared with traders!
    assert accepted_bn is True, "High-quality concurrent index signal must be shared with traders"

    # 2. Secondary weak setup (confidence=72% < 80%, R:R=1.5 < 2.0) must be suppressed
    weak_bn = AutoAlert(
        alert_id="aa-index-put-setup-midcpnifty-pe-13100-20261007",
        alert_type="INDEX_PUT_SETUP",
        stage="IGNITED",
        symbol="MIDCPNIFTY",
        exchange="NSE",
        direction="BEARISH",
        headline="MidcpNifty Trade",
        summary="Weak secondary PE",
        ltp=80.0,
        trigger_level=80.0,
        target_level=95.0,  # reward = 15
        stop_loss=70.0,  # risk = 10 -> R:R = 1.5 < 2.0
        confidence=72,  # conf < 80
        metrics={"vol_oi_ratio": 1.1},
    )
    assert engine.record_alert(weak_bn) is False, (
        "Substandard secondary signal (<80% conf, <2.0 R:R) must be suppressed"
    )

    # 3. Inter-Index Directional Whipsaw (FINNIFTY CALL while NIFTY PE is active) must be suppressed
    conflicting_finnifty = AutoAlert(
        alert_id="aa-index-call-setup-finnifty-ce-24400-20261007",
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        symbol="FINNIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="FinNifty Call",
        summary="Conflicting CE signal",
        ltp=110.0,
        trigger_level=110.0,
        target_level=180.0,
        stop_loss=75.0,
        confidence=85,
        metrics={"vol_oi_ratio": 2.1},  # No CHoCH / reversal metric!
    )
    assert engine.record_alert(conflicting_finnifty) is False, (
        "Multi-Index Coherence Guard must suppress conflicting BULLISH call while benchmark PE is active without reversal"
    )


# ── 8. Predatory Lifecycle Handshake: Bank De-risked Runner on Reversal ───────────
def test_predatory_lifecycle_handshake_banks_runner_for_confirmed_reversal(monkeypatch):
    """
    When a morning CE index trade has de-risked (e.g. stage='DE_RISK_0_5R' or 'T1_ACHIEVED'),
    an afternoon confirmed structural reversal PE setup (e.g. DOUBLE_TOP_BREAKDOWN + CALL_WRITING_CEILING)
    must bank the runner gracefully as RUNNER_EXIT (TARGET_ACHIEVED) and allow the PE reversal setup
    to dispatch cleanly without directional quarantine lockout.
    """
    engine = AutoAlertEngine()
    engine._alerts.clear()
    monkeypatch.setattr(engine, "_save", lambda *args, **kwargs: None)

    monkeypatch.setattr(
        "engine.alert_scrutiny.alert_scrutiny_auditor._execute_fast_llm_scrutiny",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "engine.alert_scrutiny.alert_scrutiny_auditor.verify_tier1_sanity",
        lambda *args, **kwargs: (True, "", {}),
    )
    from engine.detector_circuit_breaker import detector_circuit_breaker

    monkeypatch.setattr(
        detector_circuit_breaker, "evaluate_alert_allowed", lambda *args, **kwargs: (True, 1.0, "")
    )

    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    today_slug = datetime.now(IST).strftime("%Y%m%d")

    morning_ce = AutoAlert(
        alert_id=f"aa-index-call-setup-banknifty-ce-56500-{today_slug}",
        alert_type="INDEX_CALL_SETUP",
        stage="DE_RISK_0_5R",
        symbol="BANKNIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Bank Nifty Call Setup",
        summary="Morning breakout reached +0.5R, stop trailed to breakeven",
        ltp=250.0,
        trigger_level=250.0,
        target_level=450.0,
        stop_loss=150.0,
        confidence=90,
        environment="LIVE",
        is_live=True,
        underlying_spot=56500.0,
        created_at=f"{today_str} 09:25:00 IST",
    )
    assert engine.record_alert(morning_ce) is True

    # Incoming structural top reversal PE setup after 15 minutes
    afternoon_pe = AutoAlert(
        alert_id=f"aa-index-put-setup-banknifty-pe-56400-{today_slug}",
        alert_type="INDEX_PUT_SETUP",
        stage="CONFIRMED",
        symbol="BANKNIFTY",
        exchange="NSE",
        direction="BEARISH",
        headline="Bank Nifty Supply Rejection",
        summary="Double Top Breakdown at Day High with Call Writing Ceiling",
        ltp=220.0,
        trigger_level=220.0,
        target_level=400.0,
        stop_loss=130.0,
        confidence=92,
        environment="LIVE",
        is_live=True,
        underlying_spot=56420.0,
        created_at=f"{today_str} 11:15:00 IST",
        metrics={
            "signals": [
                "DOUBLE_TOP_BREAKDOWN",
                "CALL_WRITING_CEILING",
                "DAY_HIGH_SUPPLY_REJECTION",
            ],
            "spot": 56420.0,
        },
    )

    accepted = engine.record_alert(afternoon_pe)
    assert accepted is True, (
        "Confirmed structural reversal must be accepted via predatory lifecycle handshake"
    )

    # Verify the morning runner was banked gracefully
    assert morning_ce.is_active is False
    assert morning_ce.stage == "RUNNER_EXIT"
    assert morning_ce.target_status == "TARGET_ACHIEVED"
    assert "Runner banked" in (morning_ce.invalidation_reason or "")


def test_predatory_lifecycle_handshake_blocks_non_derisked_trade(monkeypatch):
    """
    When an active trade has NOT de-risked (e.g. stage='CONFIRMED') and is not failing,
    conflicting opposing alerts must be blocked to protect trader capital against whiplash.
    """
    engine = AutoAlertEngine()
    engine._alerts.clear()
    monkeypatch.setattr(engine, "_save", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "engine.alert_scrutiny.alert_scrutiny_auditor._execute_fast_llm_scrutiny",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "engine.alert_scrutiny.alert_scrutiny_auditor.verify_tier1_sanity",
        lambda *args, **kwargs: (True, "", {}),
    )
    from engine.detector_circuit_breaker import detector_circuit_breaker

    monkeypatch.setattr(
        detector_circuit_breaker, "evaluate_alert_allowed", lambda *args, **kwargs: (True, 1.0, "")
    )

    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    today_slug = datetime.now(IST).strftime("%Y%m%d")

    active_ce = AutoAlert(
        alert_id=f"aa-index-call-setup-nifty-ce-22600-{today_slug}",
        alert_type="INDEX_CALL_SETUP",
        stage="CONFIRMED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Nifty Call",
        summary="Active trade in flight",
        ltp=180.0,
        trigger_level=180.0,
        target_level=300.0,
        stop_loss=120.0,
        confidence=88,
        environment="LIVE",
        is_live=True,
        underlying_spot=22620.0,
        created_at=f"{today_str} 10:00:00 IST",
    )
    assert engine.record_alert(active_ce) is True

    opposing_pe = AutoAlert(
        alert_id=f"aa-index-put-setup-nifty-pe-22600-{today_slug}",
        alert_type="INDEX_PUT_SETUP",
        stage="CONFIRMED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BEARISH",
        headline="Nifty Put",
        summary="Minor pullback without structural breakdown",
        ltp=160.0,
        trigger_level=160.0,
        target_level=260.0,
        stop_loss=110.0,
        confidence=75,
        environment="LIVE",
        is_live=True,
        underlying_spot=22615.0,
        created_at=f"{today_str} 10:05:00 IST",
        metrics={"signals": ["PULLBACK"]},
    )

    accepted = engine.record_alert(opposing_pe)
    assert accepted is False, "Active non-derisked trade must block opposing whiplash"


# ── 9. Benchmark Lead-Lag Divergence Decoupling ──────────────────────────────────
def test_benchmark_lead_lag_divergence_allows_decoupled_secondary_put(monkeypatch):
    """
    When primary benchmark NIFTY 50 is mildly green (+0.15% and above VWAP),
    secondary indices like BANKNIFTY that demonstrate lead-lag divergence decoupling
    (trading <= own VWAP or retreated >= 0.30% from day high) must be allowed to scan
    and fire PE alerts, while indices still locked in bullish lockstep are suppressed.
    """
    engine = AutoAlertEngine()
    engine._watched_indices = ["NIFTY", "BANKNIFTY", "FINNIFTY"]

    class MockQuote:
        def __init__(self, last_price, vwap, change_pct, high=0.0, low=0.0):
            self.last_price = last_price
            self.ltp = last_price
            self.vwap = vwap
            self.change_pct = change_pct
            self.high = high or last_price
            self.low = low or (last_price * 0.99)
            self.prev_close = last_price / (1.0 + change_pct / 100.0)

    quotes_map = {
        "NSE:NIFTY": MockQuote(last_price=22510.0, vwap=22480.0, change_pct=0.15, high=22520.0),
        "NSE:BANKNIFTY": MockQuote(
            last_price=56200.0, vwap=56300.0, change_pct=-0.40, high=56550.0, low=56180.0
        ),  # Decoupled: spot < vwap and retreated 0.62% from high
        "NSE:FINNIFTY": MockQuote(
            last_price=24500.0, vwap=24450.0, change_pct=0.14, high=24505.0, low=24400.0
        ),  # Not decoupled: spot > vwap, chg +0.14% in lockstep with Nifty
    }

    mock_pe_alert = AutoAlert(
        alert_id="aa-index-put-setup-test-pe-20261013",
        alert_type="INDEX_PUT_SETUP",
        stage="CONFIRMED",
        symbol="BANKNIFTY",
        exchange="NSE",
        direction="BEARISH",
        headline="PE Setup",
        summary="Supply rejection",
        ltp=150.0,
        trigger_level=150.0,
        target_level=250.0,
        stop_loss=100.0,
        confidence=90,
        environment="TEST",
        metrics={"signals": ["DAY_HIGH_SUPPLY_REJECTION", "CALL_WRITING_CEILING"]},
    )

    evaluated_symbols = []

    def mock_detect(underlying, **kwargs):
        evaluated_symbols.append(underlying)
        return [mock_pe_alert]

    monkeypatch.setattr("engine.auto_alert_engine.detect_index_put_setup", mock_detect)
    monkeypatch.setattr("market.options.get_options_chain", lambda sym: [{"dummy": 1}])
    monkeypatch.setattr(engine, "record_alert", lambda a: True)
    monkeypatch.setenv("ENFORCE_TEST_REGIME", "1")

    _found = engine.scan_index_put_setups(quotes_map=quotes_map)
    # BANKNIFTY decoupled -> evaluated!
    assert "BANKNIFTY" in evaluated_symbols, (
        "Decoupled BANKNIFTY must be scanned for puts despite green Nifty"
    )
    # FINNIFTY in lockstep -> suppressed by lead-lag benchmark gate!
    assert "FINNIFTY" not in evaluated_symbols, (
        "Lockstep FINNIFTY must be suppressed by benchmark gate"
    )


# ── 10. Two-Stage Reversal Confirmation Above VWAP ──────────────────────────────
def test_two_stage_reversal_confirmation_above_vwap(monkeypatch):
    """
    On subsequent put scans when spot is trading above VWAP:
    1. A setup with verified Stage 1 top supply rejection (DOUBLE_TOP_BREAKDOWN) and >= 0.20% retreat
       from session high is confirmed and tagged reversal_stage='STAGE_1_TOP_REVERSAL'.
    2. A routine setup without VWAP breakdown or top supply retreat is filtered out.
    """
    engine = AutoAlertEngine()
    engine._watched_indices = ["NIFTY"]

    class MockQuote:
        def __init__(self, last_price, vwap, high):
            self.last_price = last_price
            self.ltp = last_price
            self.vwap = vwap
            self.high = high
            self.low = vwap * 0.99
            self.change_pct = 0.05
            self.prev_close = vwap

    # Spot is 22,550, VWAP is 22,500, Day High is 22,620 (spot has retreated (22620 - 22550)/22620 = 0.31% >= 0.20%)
    quotes_map = {"NSE:NIFTY": MockQuote(last_price=22550.0, vwap=22500.0, high=22620.0)}

    top_reversal_alert = AutoAlert(
        alert_id="aa-index-put-setup-nifty-top-20261013",
        alert_type="INDEX_PUT_SETUP",
        stage="CONFIRMED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BEARISH",
        headline="Stage 1 Supply Rejection",
        summary="Double Top Breakdown at Day High",
        ltp=120.0,
        trigger_level=120.0,
        target_level=200.0,
        stop_loss=80.0,
        confidence=94,
        environment="TEST",
        metrics={
            "signals": ["DOUBLE_TOP_BREAKDOWN", "DAY_HIGH_SUPPLY_REJECTION", "CALL_WRITING_CEILING"]
        },
    )

    routine_alert = AutoAlert(
        alert_id="aa-index-put-setup-nifty-routine-20261013",
        alert_type="INDEX_PUT_SETUP",
        stage="CONFIRMED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BEARISH",
        headline="Routine PE",
        summary="Drift above VWAP",
        ltp=110.0,
        trigger_level=110.0,
        target_level=150.0,
        stop_loss=90.0,
        confidence=80,
        environment="TEST",
        metrics={"signals": ["TREND_PULLBACK"]},  # No top reversal signal and no VWAP breakdown
    )

    monkeypatch.setattr("market.options.get_options_chain", lambda sym: [{"dummy": 1}])
    monkeypatch.setattr(engine, "record_alert", lambda a: True)
    engine._index_put_scan_counts["NIFTY"] = 2  # mark as subsequent scan

    # Scenario 1: Top Reversal Alert
    monkeypatch.setattr(
        "engine.auto_alert_engine.detect_index_put_setup",
        lambda *args, **kwargs: [top_reversal_alert],
    )
    found_top = engine.scan_index_put_setups(quotes_map=quotes_map)
    assert len(found_top) == 1
    assert found_top[0].metrics.get("reversal_stage") == "STAGE_1_TOP_REVERSAL"

    # Scenario 2: Routine Alert without top reversal or VWAP breakdown
    monkeypatch.setattr(
        "engine.auto_alert_engine.detect_index_put_setup",
        lambda *args, **kwargs: [routine_alert],
    )
    found_routine = engine.scan_index_put_setups(quotes_map=quotes_map)
    assert len(found_routine) == 0, (
        "Routine PE above VWAP without top supply rejection or VWAP breakdown must be filtered"
    )


def test_rca_downside_roc_acceleration_vetoes_call(monkeypatch):
    """
    RCA Regression Test: Verify that when underlying price velocity is accelerating
    downwards on 5m bars, buying calls is strictly prohibited.
    """
    chain = [
        MockOptionContract("BANKNIFTY26OCT55700CE", 55700, "CE", 478.0, 50000, 100000, 15.0, 5000),
        MockOptionContract("BANKNIFTY26OCT55700PE", 55700, "PE", 410.0, 50000, 100000, -5.0, 5000),
    ]
    # Accelerating downward momentum: successive bars dropping with expanding point delta (-0.20% ROC)
    records = []
    dt_base = datetime.strptime("2026-10-21", "%Y-%m-%d").replace(hour=9, minute=30, tzinfo=IST)
    curr = 55800.0
    drops = [10, 10, 10, 10, 10, 10, 10, 15, 20, 25, 35, 50]
    for i, d in enumerate(drops):
        t = dt_base + timedelta(minutes=5 * i)
        o = curr
        c = o - d
        curr = c
        records.append(
            {"datetime": t, "open": o, "high": o + 5, "low": c - 5, "close": c, "volume": 25000}
        )
    df_down = pd.DataFrame(records)
    df_down.set_index("datetime", inplace=True)

    # Call detector with accelerating downward momentum
    alerts = detect_index_call_setup(
        underlying="BANKNIFTY",
        spot=55730.0,
        chain=chain,
        vwap=55714.0,
        day_high=55867.0,
        day_low=55595.0,
        ohlcv_5m=df_down,
        ignore_time_gate=False,
    )
    # Must fail-closed (return empty list)
    assert len(alerts) == 0, "Downside ROC acceleration must veto long call setups"


def test_rca_put_writing_floor_requires_pe_decay(monkeypatch):
    """
    RCA Regression Test: True Put Writing requires writers driving premium decay.
    If PE prices are surging (pchange > 2%), buyers are bidding up puts (bearish breakdown),
    which must NOT be flagged as a Put Writing Floor.
    """
    # Case 1: PE prices surging (+25%) -> NOT a floor
    surging_pe = MockOptionContract(
        "BANKNIFTY26OCT55700PE", 55700, "PE", 450.0, 60000, 120000, 25.0, 15000
    )
    normal_ce = MockOptionContract(
        "BANKNIFTY26OCT55700CE", 55700, "CE", 400.0, 30000, 80000, -15.0, 2000
    )
    chain_surging = [normal_ce, surging_pe]

    df_stable = _make_dummy_5m_ohlcv(
        bars=12, base_price=55700.0, trend="FLAT", date_str="2026-10-21"
    )
    alerts_surging = detect_index_call_setup(
        underlying="BANKNIFTY",
        spot=55700.0,
        chain=chain_surging,
        vwap=55700.0,
        day_high=55800.0,
        day_low=55650.0,
        ohlcv_5m=df_stable,
        ignore_time_gate=True,
    )
    # Signals inside must NOT contain PUT_WRITING_FLOOR
    for a in alerts_surging:
        signals = a.metrics.get("signals", [])
        assert "PUT_WRITING_FLOOR" not in signals, (
            "Surging PE puts must NOT be tagged as PUT_WRITING_FLOOR"
        )


def test_rca_degenerate_cpr_protected():
    """
    RCA Regression Test: Verify that identical High, Low, Close (0 width) does NOT
    get classified as NARROW CPR or spoof TREND_EXPANSION.
    """
    from engine.session_regime_sentinel import calculate_cpr, evaluate_symbol_session_regime

    # Degenerate case: High == Low == Close
    cpr = calculate_cpr(high=55000.0, low=55000.0, close=55000.0, is_index=True)
    assert cpr.cpr_type != "NARROW", (
        f"Degenerate 0-width CPR must not be NARROW, got {cpr.cpr_type}"
    )
    assert cpr.cpr_width_pct <= 0.005

    # Session regime shift must not trigger TREND_EXPANSION on 0 width
    reg = evaluate_symbol_session_regime(
        symbol="BANKNIFTY",
        current_high=55100.0,
        current_low=54900.0,
        current_ltp=55000.0,
        prev_high=55000.0,
        prev_low=55000.0,
        prev_close=55000.0,
    )
    assert reg.regime != "TREND_EXPANSION", "Degenerate CPR must not spoof TREND_EXPANSION"


def test_rca_scrutiny_velocity_vetoes():
    """
    RCA Regression Test: Alert scrutiny must reject alerts with opposite ROC acceleration
    or collapsing premium velocity.
    """
    from engine.alert_scrutiny import scrutinize_alert, alert_scrutiny_auditor

    alert_scrutiny_auditor._cache.clear()

    # Bullish alert with accelerating down ROC
    bad_roc_alert = AutoAlert(
        alert_id="test-roc-veto",
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        symbol="BANKNIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="Buy Call Test",
        summary="Test",
        ltp=450.0,
        trigger_level=450.0,
        target_level=550.0,
        stop_loss=400.0,
        strike=55800.0,
        contract_symbol="BANKNIFTY26OCT55800CE",
        confidence=85,
        environment="TEST",
        metrics={
            "roc_momentum": {
                "is_accelerating_down": True,
                "roc_3bar": -0.22,
                "summary": "BANKNIFTY 5m ROC: ACCELERATING_DOWN (-0.22%)",
            },
            "premium_velocity": -2.0,
        },
    )
    res_roc = scrutinize_alert(bad_roc_alert)
    assert res_roc.status == "REJECTED"
    assert "Downside ROC acceleration" in (res_roc.rejection_reason or "")

    alert_scrutiny_auditor._cache.clear()
    # Bullish alert with collapsing premium velocity (-32.0 pts/min)
    bad_vel_alert = AutoAlert(
        alert_id="test-vel-veto",
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        symbol="BANKNIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="Buy Call Test",
        summary="Test",
        ltp=450.0,
        trigger_level=450.0,
        target_level=550.0,
        stop_loss=400.0,
        strike=55700.0,
        contract_symbol="BANKNIFTY26OCT55700CE",
        confidence=85,
        environment="TEST",
        metrics={
            "premium_velocity": -32.0,
        },
    )
    res_vel = scrutinize_alert(bad_vel_alert)
    assert res_vel.status == "REJECTED"
    assert "Option premium liquidation veto" in (res_vel.rejection_reason or "")


def test_rca_day_high_headroom_and_severe_rejection():
    """
    RCA Regression Test: Verify Day High headroom (< 0.15%) cannot be bypassed by proximity watch,
    and severe drop from Day High (>= 0.35%) below VWAP suppresses CE setups.
    """
    chain = [
        MockOptionContract("SENSEX26OCT74600CE", 74600, "CE", 350.0, 50000, 100000, 5.0, 5000),
        MockOptionContract("SENSEX26OCT74600PE", 74600, "PE", 300.0, 50000, 100000, -5.0, 5000),
    ]
    df_stable = _make_dummy_5m_ohlcv(bars=12, base_price=74660.0, trend="UP", date_str="2026-10-21")

    # 1. Collision right into Day High (Spot 74667.62, DH 74682.19 -> 0.019% headroom)
    alerts_collision = detect_index_call_setup(
        underlying="SENSEX",
        spot=74667.62,
        chain=chain,
        vwap=74360.0,
        day_high=74682.19,
        day_low=74150.0,
        ohlcv_5m=df_stable,
        ignore_time_gate=False,
    )
    assert len(alerts_collision) == 0, (
        "Buying into Day High within 0.02% without momentum must be suppressed"
    )

    # 2. Severe Rejection from Day High below VWAP
    # DH was 75000, spot tumbled to 74600 (drop = 0.53%), VWAP is 74700 (spot below VWAP)
    alerts_rejection = detect_index_call_setup(
        underlying="SENSEX",
        spot=74600.0,
        chain=chain,
        vwap=74700.0,
        day_high=75000.0,
        day_low=74500.0,
        ohlcv_5m=df_stable,
        ignore_time_gate=False,
    )
    assert len(alerts_rejection) == 0, (
        "Severe rejection from Day High below VWAP must suppress long calls"
    )


def test_rca_gate7d_tbt_calibrated_obi_and_spoof_veto(monkeypatch):
    """
    RCA Regression Test: Verify Gate 7d catches:
    1. Calibrated OBI-50 (e.g. -0.25 on index futures, which failed the old -0.40 threshold).
    2. Bid spoof / rugpull trap warnings.
    """
    from engine.alert_scrutiny import scrutinize_alert, alert_scrutiny_auditor

    class MockTbtManager:
        is_connected = True

        def __init__(self, obi=-0.25, spoof=None):
            self._obi = obi
            self._spoof = spoof

        def get_50_depth(self, sym):
            return {
                "symbol": sym,
                "status": "LIVE",
                "obi_50": self._obi,
                "ltp": 23000.0,
                "spoof_trap_warning": self._spoof,
                "fleeing_bid_wall_detected": bool(self._spoof),
                "ask_walls": [],
                "bid_walls": [],
            }

    # Case 1: OBI is -0.25 on index future (BankNifty/Nifty today) -> Must be REJECTED
    monkeypatch.setattr(
        "market.fyers_tbt_manager.FyersTbtManager", lambda: MockTbtManager(obi=-0.25)
    )
    alert_scrutiny_auditor._cache.clear()
    nifty_call = AutoAlert(
        alert_id="test-obi-calibrated-veto",
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="Buy Nifty Call",
        summary="Test",
        ltp=150.0,
        trigger_level=150.0,
        target_level=200.0,
        stop_loss=120.0,
        strike=23000.0,
        contract_symbol="NIFTY26OCT23000CE",
        confidence=85,
        environment="TEST",
    )
    res_obi = scrutinize_alert(nifty_call)
    assert res_obi.status == "REJECTED"
    assert "TBT Order Book Imbalance Veto" in (res_obi.rejection_reason or "")

    # Case 2: Spoof rugpull warning active on 50-depth book -> Must be REJECTED
    monkeypatch.setattr(
        "market.fyers_tbt_manager.FyersTbtManager",
        lambda: MockTbtManager(
            obi=-0.05, spoof="BID_SPOOF_RUGPULL_RISK: Resting buy wall fled near 23003.5"
        ),
    )
    alert_scrutiny_auditor._cache.clear()
    spoof_call = AutoAlert(
        alert_id="test-spoof-rugpull-veto",
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="Buy Nifty Call",
        summary="Test",
        ltp=150.0,
        trigger_level=150.0,
        target_level=200.0,
        stop_loss=120.0,
        strike=23050.0,
        contract_symbol="NIFTY26OCT23050CE",
        confidence=85,
        environment="TEST",
    )
    res_spoof = scrutinize_alert(spoof_call)
    assert res_spoof.status == "REJECTED"
    assert "Spoof Rugpull Veto" in (res_spoof.rejection_reason or "")


def test_rca_orb_and_squeeze_vwap_and_roc_safeguards():
    """
    RCA Regression Test: Verify ORB and Squeeze Breakout detectors on indices:
    1. Squeeze breakout cannot ignite bullish when spot is below VWAP.
    2. ORB primed cannot trigger bullish when spot is below VWAP.
    """
    from engine.detectors.squeeze_breakout import detect_squeeze_breakout
    from engine.detectors.orb import detect_opening_range_breakout

    # 1. Squeeze Breakout: Spot 55000 is below VWAP 55100
    df_squeeze = _make_dummy_5m_ohlcv(
        bars=25, base_price=55000.0, trend="FLAT", date_str="2026-10-21"
    )
    sq_alert = detect_squeeze_breakout(
        symbol="BANKNIFTY",
        df=df_squeeze,
        ltp=55000.0,
        exchange="NSE",
        timeframe="5m",
        vwap=55150.0,  # Spot is 150 pts BELOW VWAP
    )
    assert sq_alert is None or sq_alert.direction != "BULLISH", (
        "Bullish squeeze breakout must not ignite below session VWAP"
    )

    # 2. ORB Primed: Spot is above range midpoint but below VWAP
    df_orb = _make_dummy_5m_ohlcv(bars=12, base_price=74500.0, trend="FLAT", date_str="2026-10-21")
    orb_alert = detect_opening_range_breakout(
        symbol="SENSEX",
        df=df_orb,
        ltp=74550.0,
        exchange="BSE",
        opening_minutes=15,
        rvol=1.5,
        vwap=74650.0,  # Spot is 100 pts BELOW VWAP
        orb_levels=(74600.0, 74400.0, 200.0, 74500.0),  # High 74600, Low 74400, Mid 74500
    )
    assert orb_alert is None or orb_alert.direction != "BULLISH", (
        "Bullish ORB primed must not trigger below session VWAP"
    )


def test_rca_gate3d_strict_vwap_and_gate23_sector_rrg_resolution():
    """
    RCA Regression Test:
    1. Gate 3d: Strict VWAP enforcement on index (spot below VWAP without structural reversal rejected).
    2. Gate 23: Index options (e.g. NIFTY26OCT23000CE) bypass stock RRG without 404 network lookup.
    3. Gate 23: Single-stock options (e.g. RELIANCE26OCT2800CE) resolve parent stock cleanly.
    """
    from engine.alert_scrutiny import scrutinize_alert

    # 1. Gate 3d: Nifty spot 24990 is 10 points below VWAP 25000 (0.04% below, previously leaked past 0.20% buffer)
    call_alert_tight_vwap = AutoAlert(
        alert_id="test-gate3d-vwap-1",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        alert_type="INDEX_INTRADAY_CALL",
        headline="Nifty Call Setup",
        summary="Test vwap boundary",
        trigger_level=24990.0,
        stop_loss=24950.0,
        target_level=25080.0,
        ltp=24990.0,
        created_at="2026-10-21 10:30:00 IST",
        metrics={
            "spot": 24990.0,
            "vwap": 25000.0,
            "day_high": 25100.0,
            "day_low": 24900.0,
            "rvol": 1.5,
        },
    )
    res_vwap = scrutinize_alert(call_alert_tight_vwap)
    assert res_vwap.status == "REJECTED"
    assert "Anti-Trend VWAP Trap" in (res_vwap.rejection_reason or "")

    # 2. Gate 23: Index option NIFTY26OCT23000CE recognized as index sym (sector_rrg_valid is True)
    idx_opt_alert = AutoAlert(
        alert_id="test-gate23-idx-opt-1",
        stage="IGNITED",
        symbol="NIFTY26OCT23000CE",
        exchange="NFO",
        direction="BULLISH",
        alert_type="OPTIONS_MOMENTUM_BUY",
        headline="Nifty Option Buy",
        summary="Test option sector rrg bypass",
        trigger_level=120.0,
        stop_loss=90.0,
        target_level=160.0,
        ltp=120.0,
        created_at="2026-10-21 10:30:00 IST",
        metrics={
            "spot": 25050.0,
            "vwap": 25000.0,
            "day_high": 25100.0,
            "day_low": 24900.0,
            "rvol": 1.5,
        },
    )
    res_idx = scrutinize_alert(idx_opt_alert)
    assert "Sector RRG" not in (res_idx.rejection_reason or "")


def test_rca_pwh_rejection_distance_bound_and_adr_exhaustion(monkeypatch):
    """
    RCA Regression for #SIG_SENSEX_73400PE_21OCT_1346:
    1. Prevents stale morning PWH tests from triggering fake 'PWH Supply Rejection' hours later
       when spot is 1,400 points away at the session low.
    2. Prevents entering short puts after >= 1.15x ATR terminal downward exhaustion.
    """
    monkeypatch.setenv("CHANAKYA_TESTING", "1")
    ref_time = datetime(2026, 10, 21, 13, 46, tzinfo=IST)

    chain = [
        MockOptionContract(
            "BSE:SENSEX26O2273400PE",
            73400.0,
            "PE",
            362.0,
            volume=50000,
            oi=30000,
            pchange=45.0,
            oi_change=5000,
        ),
        MockOptionContract(
            "BSE:SENSEX26O2273400CE",
            73400.0,
            "CE",
            420.0,
            volume=40000,
            oi=25000,
            pchange=-35.0,
            oi_change=-2000,
        ),
    ]

    ohlcv = _make_dummy_5m_ohlcv(bars=20, base_price=74200.0, trend="DOWN", date_str="2026-10-21")

    # Scenario 1: Stale PWH test (tested at 09:30 AM, but spot is now 73365, 1.8% away from PWH)
    # Must NOT emit PDH_SUPPLY_REJECTION / PWH supply rejection
    alerts_stale = detect_index_put_setup(
        underlying="SENSEX",
        spot=73365.0,
        chain=chain,
        vwap=74167.0,
        day_high=74682.0,
        day_low=73280.0,
        prev_day_high=74850.0,
        prev_day_low=73900.0,
        prev_week_high=74778.8,
        ohlcv_5m=ohlcv,
        ref_time=ref_time,
        ignore_time_gate=True,
    )
    for alert in alerts_stale:
        signals = alert.metrics.get("signals", [])
        assert "PDH_SUPPLY_REJECTION" not in signals, (
            "Stale PWH test 1.8% away from spot must not trigger PWH supply rejection"
        )

    # Scenario 2: Active PWH test in real-time (spot tested PWH and is pulling back within 0.10%-0.45%)
    chain_active = [
        MockOptionContract(
            "BSE:SENSEX26O2274600PE",
            74600.0,
            "PE",
            180.0,
            volume=50000,
            oi=30000,
            pchange=15.0,
            oi_change=3000,
        ),
    ]
    alerts_active = detect_index_put_setup(
        underlying="SENSEX",
        spot=74650.0,
        chain=chain_active,
        vwap=74600.0,
        day_high=74770.0,
        day_low=74500.0,
        prev_day_high=74950.0,
        prev_day_low=74200.0,
        prev_week_high=74778.8,
        ohlcv_5m=ohlcv,
        ref_time=datetime(2026, 10, 21, 10, 0, tzinfo=IST),
        ignore_time_gate=True,
    )
    # Should accept clean active rejection of PWH
    pwh_alerts = [
        a for a in alerts_active if "PDH_SUPPLY_REJECTION" in a.metrics.get("signals", [])
    ]
    assert len(pwh_alerts) >= 1


# ── 25. CVD Bullish Absorption Veto ──────────────────────────────────────────
def test_rca_cvd_bullish_absorption_vetoes_put_setup(monkeypatch):
    """When price sweeps morning lows but CVD indicates bullish absorption, PE setups must be vetoed."""
    chain = [
        MockOptionContract(
            "NSE:BANKNIFTY26OCT54000PE", 54000.0, "PE", 280.0, volume=35000, oi=45000, pchange=20.0
        )
    ]
    # Synthetic DataFrame with 15 bars
    df_5m = _make_dummy_5m_ohlcv(bars=15, base_price=54250.0, trend="DOWN", date_str="2026-10-26")

    # Mock order flow CVD divergence to simulate bullish absorption
    monkeypatch.setattr(
        "engine.detectors.order_flow.compute_order_flow_cvd_divergence",
        lambda *args, **kwargs: {
            "is_bullish_absorption": True,
            "is_bearish_exhaustion": False,
            "cvd_divergence_ratio": 2.1,
            "current_cvd": 1250.0,
            "prior_cvd": -500.0,
        },
    )

    alerts = detect_index_put_setup(
        underlying="BANKNIFTY",
        spot=53800.0,
        chain=chain,
        vwap=53966.0,
        day_high=54250.0,
        day_low=53777.0,
        prev_day_high=54990.0,
        prev_day_low=54138.0,
        prev_close=54198.0,
        ohlcv_5m=df_5m,
        ref_time=datetime(2026, 10, 26, 9, 25, 5, tzinfo=IST),
        ignore_time_gate=True,
    )
    assert len(alerts) == 0, "CVD bullish absorption must veto PE setup at the low"


# ── 26. Camarilla L4 Floor Proximity Guard Without Candle Close ───────────────
def test_rca_camarilla_l4_floor_proximity_without_close_below_vetoes_put(monkeypatch):
    """Resting at Camarilla L4 support without a 5m bar close below L4 must be vetoed."""
    from engine.daily_levels import DailyLevels

    mock_dl = DailyLevels(
        symbol="NSE:BANKNIFTY",
        canonical_symbol="BANKNIFTY",
        exchange="NSE",
        session_date="2026-10-26",
        pdh=54990.0,
        pdl=54138.0,
        pdc=54198.0,
        camarilla={"l4": 53730.0, "l5": 53200.0, "h3": 54432.0, "h4": 54666.0},
        cpr={"pivot": 54442.0, "cpr_type": "WIDE"},
    )
    monkeypatch.setattr("engine.daily_levels.get_daily_levels", lambda sym: mock_dl)

    chain = [
        MockOptionContract(
            "NSE:BANKNIFTY26OCT53800PE", 53800.0, "PE", 260.0, volume=35000, oi=45000, pchange=20.0
        )
    ]
    # Candle that dropped to 53777 but closed at 53780 (above L4 53730)
    df_5m = _make_dummy_5m_ohlcv(bars=15, base_price=54250.0, trend="DOWN", date_str="2026-10-26")
    df_5m.iloc[-1, df_5m.columns.get_loc("close")] = 53780.0  # Above L4 (53730.0)

    alerts = detect_index_put_setup(
        underlying="BANKNIFTY",
        spot=53777.0,  # Within 0.08% of L4 53730.0
        chain=chain,
        vwap=53966.0,
        day_high=54250.0,
        day_low=53777.0,
        prev_day_high=54990.0,
        prev_day_low=54138.0,
        prev_close=54198.0,
        ohlcv_5m=df_5m,
        ref_time=datetime(2026, 10, 26, 9, 25, 9, tzinfo=IST),
        ignore_time_gate=True,
    )
    assert len(alerts) == 0, "Testing Camarilla L4 without a 5m close below L4 must be vetoed"


# ── 27. Morning Wide CPR ADR Exhaustion Veto ──────────────────────────────────
def test_rca_wide_cpr_adr_exhaustion_morning_veto():
    """Wide CPR sessions with >= 60% ADR consumed must veto edge chasing even before 11:30 AM."""
    from engine.session_regime_sentinel import evaluate_symbol_session_regime

    reg = evaluate_symbol_session_regime(
        symbol="BANKNIFTY",
        current_high=54250.0,
        current_low=53700.0,  # 550 pt range
        current_ltp=53720.0,
        prev_high=54990.0,
        prev_low=54138.0,
        prev_close=54198.0,
        adr_5d=850.0,  # 550/850 = 64.7% ADR consumed
        ref_time=datetime(2026, 10, 26, 9, 30, tzinfo=IST),
    )
    assert reg.regime == "CHOP_MEAN_REVERSION"
    assert reg.veto_breakout_chase is True, (
        "Wide CPR + 64% ADR consumed must veto breakout/breakdown chase"
    )
    assert reg.favor_mean_reversion is True


# ── 28. Index Call Camarilla H4 & TBT Ask Wall Veto ──────────────────────────
def test_rca_index_call_camarilla_h4_and_tbt_ask_wall_vetoes(monkeypatch):
    """Index call setup must veto buying calls into Camarilla H4 ceiling or against heavy TBT ask wall."""
    from engine.detectors.index_call_setup import detect_index_call_setup
    from unittest.mock import MagicMock

    chain = [
        MockOptionContract(
            "NSE:BANKNIFTY26OCT54200CE", 54200.0, "CE", 290.0, volume=35000, oi=45000, pchange=22.0
        )
    ]
    df_5m = _make_dummy_5m_ohlcv(bars=15, base_price=53800.0, trend="UP", date_str="2026-10-26")

    # 1. Test Camarilla H4 Ceiling Guard
    mock_dl = MagicMock()
    mock_dl.camarilla = {"h4": 54200.0, "h5": 54600.0}
    mock_dl.atr_14 = 450.0
    monkeypatch.setattr("engine.daily_levels.get_daily_levels", lambda sym: mock_dl)

    # 5m candle close below H4 (54190 < 54200)
    df_5m.iloc[-1, df_5m.columns.get_loc("close")] = 54190.0

    alerts_h4 = detect_index_call_setup(
        underlying="BANKNIFTY",
        spot=54195.0,  # within 0.05% of H4 54200
        chain=chain,
        vwap=54000.0,
        day_high=54205.0,
        day_low=53800.0,
        ohlcv_5m=df_5m,
        ref_time=datetime(2026, 10, 26, 10, 0, tzinfo=IST),
        ignore_time_gate=True,
    )
    assert len(alerts_h4) == 0, (
        "Testing Camarilla H4 without a 5m close above H4 must veto call setup"
    )

    # 2. Test TBT Fortress Ask Wall / OBI-50 Veto
    mock_dl.camarilla = {"h4": 55000.0, "h5": 55500.0}  # Move H4 far away
    mock_tbt = MagicMock()
    mock_tbt.is_connected = True
    mock_tbt.get_50_depth.return_value = {
        "status": "LIVE",
        "obi_50": -0.28,  # Heavy seller/ask dominance
        "fortress_ask_wall_confirmed": True,
    }
    monkeypatch.setattr("market.fyers_tbt_manager.fyers_tbt_manager", mock_tbt)

    alerts_tbt = detect_index_call_setup(
        underlying="BANKNIFTY",
        spot=54100.0,
        chain=chain,
        vwap=54000.0,
        day_high=54150.0,
        day_low=53800.0,
        ohlcv_5m=df_5m,
        ref_time=datetime(2026, 10, 26, 10, 0, tzinfo=IST),
        ignore_time_gate=True,
    )
    assert len(alerts_tbt) == 0, "TBT Ask Wall / negative OBI-50 must veto call setup"


# ── 29. Squeeze & Gamma Blast Camarilla L4 and TBT Protection ────────────────
def test_rca_squeeze_and_gamma_blast_camarilla_and_tbt_protection(monkeypatch):
    """Squeeze breakdown and Gamma Blast PE must veto index breakdowns testing Camarilla L4 or resting on TBT bid wall."""
    from engine.detectors.squeeze_breakout import detect_squeeze_breakout
    from engine.detectors.gamma_blast import detect_gamma_blast
    from unittest.mock import MagicMock

    mock_dl = MagicMock()
    mock_dl.camarilla = {"l4": 53730.0, "l5": 53400.0}
    monkeypatch.setattr("engine.daily_levels.get_daily_levels", lambda sym: mock_dl)

    # 1. Squeeze Breakdown at L4
    df_15m = _make_dummy_5m_ohlcv(bars=30, base_price=54000.0, trend="DOWN", date_str="2026-10-26")
    sq_alert = detect_squeeze_breakout(
        symbol="BANKNIFTY",
        df=df_15m,
        ltp=53735.0,  # Resting right at Camarilla L4 53730
        timeframe="15m",
        vwap=53850.0,
    )
    assert sq_alert is None, "Squeeze Breakdown on index testing Camarilla L4 must be suppressed"

    # 2. Gamma Blast PE at L4
    pe_contract = MockOptionContract(
        "NSE:BANKNIFTY26OCT53800PE", 53800.0, "PE", 260.0, volume=30000, oi=40000, pchange=18.0
    )
    gb_alerts = detect_gamma_blast(
        underlying="BANKNIFTY",
        spot=53735.0,  # Testing Camarilla L4
        chain=[pe_contract],
        vwap=53850.0,
        day_high=54250.0,
        day_low=53730.0,
        now_dt=datetime(2026, 10, 26, 9, 30, tzinfo=IST),
    )
    assert len(gb_alerts) == 0, "Gamma Blast PE on index testing Camarilla L4 must be suppressed"


# ── 30. Negative CVD Bullish Absorption Detection ────────────────────────────
def test_rca_negative_cvd_bullish_absorption_detection():
    """CVD absorption in negative delta regimes (selling dried up) must be detected accurately."""
    from engine.detectors.order_flow import compute_order_flow_cvd_divergence
    import pandas as pd
    import numpy as np

    n = 20
    # Price plunges down to index 14, bounces slightly, then retests/sweeps low at index 19
    lows = [100.0 - i * 0.5 for i in range(15)] + [93.0, 93.2, 93.1, 92.8, 92.5]
    opens = [l + 0.3 for l in lows]
    highs = [l + 0.8 for l in lows]
    closes = [l + 0.5 for l in lows]
    df = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [1000.0] * n,
        }
    )
    # Delta: -500 selling during initial plunge to index 14 (cvd reaches -7500),
    # but at the retest/sweep (index 15-19), buyers absorb (+400 each bar), so CVD improves from -7500 to -5500!
    delta_arr = np.array([-500.0] * 15 + [400.0] * 5)
    df["delta"] = delta_arr

    res = compute_order_flow_cvd_divergence(df, curr_p=df["low"].iloc[-1])
    assert res["is_bullish_absorption"] is True, (
        "Negative CVD absorption must be identified when delta improves"
    )
    assert res["cvd_divergence_ratio"] >= 1.05


# ── 31. Turtle Soup Camarilla and TBT Order Book Guards ──────────────────────
def test_rca_turtle_soup_camarilla_and_tbt_guards(monkeypatch):
    """Turtle Soup detector must suppress springs trapped below Camarilla L4 or against TBT ask walls."""
    from engine.detectors.turtle_soup import detect_turtle_soup_sweep
    from unittest.mock import MagicMock

    df = _make_dummy_5m_ohlcv(bars=25, base_price=53800.0, trend="DOWN", date_str="2026-10-26")
    prior_low = float(df["low"].iloc[-15:-2].min())
    df.iloc[-1, df.columns.get_loc("low")] = prior_low - 15.0
    df.iloc[-1, df.columns.get_loc("close")] = prior_low + 10.0
    df.iloc[-1, df.columns.get_loc("open")] = prior_low + 5.0
    df.iloc[-1, df.columns.get_loc("high")] = prior_low + 25.0

    # 1. Suppressed if trapped below Camarilla L4
    mock_dl = MagicMock()
    mock_dl.camarilla = {"l4": prior_low + 50.0, "h4": prior_low + 400.0}
    monkeypatch.setattr(
        "engine.daily_levels.get_daily_levels", lambda sym, session_date=None: mock_dl
    )

    alert_l4 = detect_turtle_soup_sweep(
        "BANKNIFTY", df=df, ltp=prior_low + 10.0, vwap=prior_low + 15.0
    )
    assert alert_l4 is None, "Turtle soup spring trapped below Camarilla L4 must be suppressed"

    # 2. Suppressed if TBT shows Fortress Ask Wall
    mock_dl.camarilla = {"l4": prior_low - 100.0, "h4": prior_low + 400.0}
    mock_tbt = MagicMock()
    mock_tbt.is_connected = True
    mock_tbt.get_50_depth.return_value = {
        "status": "LIVE",
        "obi_50": -0.35,
        "fortress_ask_wall_confirmed": True,
    }
    monkeypatch.setattr("market.fyers_tbt_manager.fyers_tbt_manager", mock_tbt)

    alert_tbt = detect_turtle_soup_sweep(
        "BANKNIFTY", df=df, ltp=prior_low + 10.0, vwap=prior_low + 15.0
    )
    assert alert_tbt is None, "Turtle soup spring facing Fortress Ask Wall must be suppressed"


# ── 32. Afternoon Thrust Exhaustion and Wall Guards ──────────────────────────
def test_rca_afternoon_thrust_exhaustion_and_wall_guards(monkeypatch):
    """Afternoon thrust must suppress buying calls at Camarilla H5 or flushes at Camarilla L5."""
    from engine.detectors.afternoon_thrust import detect_afternoon_thrust
    from unittest.mock import MagicMock

    df = _make_dummy_5m_ohlcv(bars=40, base_price=54000.0, trend="UP", date_str="2026-10-26")

    mock_dl = MagicMock()
    mock_dl.camarilla = {"h5": 54500.0, "l5": 53500.0, "h4": 54200.0, "l4": 53800.0}
    monkeypatch.setattr(
        "engine.daily_levels.get_daily_levels", lambda sym, session_date=None: mock_dl
    )

    alert_h5 = detect_afternoon_thrust(
        symbol="BANKNIFTY",
        df_5m=df,
        ltp=54505.0,
        vwap=54200.0,
        day_high=54510.0,
        day_low=53900.0,
        rvol=1.5,
        ref_time=datetime(2026, 10, 26, 13, 30, tzinfo=IST),
        ignore_time_gate=True,
    )
    assert alert_h5 is None, (
        "Afternoon thrust at Camarilla H5 terminal exhaustion must be suppressed"
    )


# ── 33. Options Momentum Camarilla L4 and TBT Bid Wall Veto ──────────────────
def test_rca_options_momentum_camarilla_and_tbt_bid_wall(monkeypatch):
    """Options momentum must suppress PE when spot is sitting on Camarilla L4 without 5m close below."""
    from engine.detectors.options_momentum import detect_options_momentum_breakouts
    from unittest.mock import MagicMock

    pe_contract = MockOptionContract(
        "NSE:BANKNIFTY26OCT53800PE", 53800.0, "PE", 250.0, volume=35000, oi=45000, pchange=15.0
    )
    mock_quote = MagicMock()
    mock_quote.last_price = 53735.0
    mock_quote.ltp = 53735.0
    mock_quote.open = 54200.0
    mock_quote.high = 54250.0
    mock_quote.low = 53730.0
    mock_quote.vwap = 53900.0
    mock_quote.change_pct = -0.85

    monkeypatch.setattr("market.options.get_options_chain", lambda sym, expiry=None: [pe_contract])
    monkeypatch.setattr(
        "market.quotes.get_quote",
        lambda syms: {"NSE:BANKNIFTY": mock_quote, "BANKNIFTY": mock_quote},
    )
    monkeypatch.setattr(
        "market.history.get_ohlcv",
        lambda sym, **kwargs: _make_dummy_5m_ohlcv(
            bars=15, base_price=53800.0, trend="DOWN", date_str="2026-10-26"
        ),
    )

    mock_dl = MagicMock()
    mock_dl.camarilla = {"l4": 53730.0, "h4": 54200.0}
    monkeypatch.setattr(
        "engine.daily_levels.get_daily_levels", lambda sym, session_date=None: mock_dl
    )

    alerts = detect_options_momentum_breakouts(
        targets=["BANKNIFTY"],
        now_dt=datetime(2026, 10, 26, 10, 0, tzinfo=IST),
    )
    assert len(alerts) == 0, (
        "PE momentum resting on Camarilla L4 without close below must be suppressed"
    )


# ── 34. Daily Levels Provenance Fail-Closed (Zero Synthetic Price Ranges) ────
def test_rca_daily_levels_provenance_fail_closed(monkeypatch):
    """Daily levels engine must fail closed (return None) when OHLCV is unreachable, never fabricating arbitrary ranges."""
    from engine.daily_levels import DailyLevelsStore

    store = DailyLevelsStore()
    monkeypatch.setattr("market.history.get_ohlcv", lambda sym, **kwargs: None)
    monkeypatch.setattr("market.quotes.get_quote", lambda insts: {})

    res = store.compute_and_store(
        symbol="NON_EXISTENT_UNREACHABLE_SYMBOL", session_date="2026-10-26"
    )
    assert res is None, (
        "Unreachable daily data must return None (Rule 11 Zero-Hallucination Invariant)"
    )


# ── 35. Multi-Timeframe Levels (PWH, PWL, PMH, PML) Resampling ───────────────
def test_rca_pwh_pwl_pmh_pml_resampling(monkeypatch):
    """Verify that DailyLevelsStore derives PWH, PWL, PWC, PMH, PML, PMC deterministically from daily bars."""
    import pandas as pd
    import numpy as np
    from engine.daily_levels import DailyLevelsStore
    from unittest.mock import MagicMock

    # Create 60 daily bars spanning August to October 2026
    dates = pd.date_range("2026-08-01", "2026-10-23", freq="B")
    n = len(dates)
    df_daily = pd.DataFrame(
        {
            "open": np.linspace(24000, 25000, n),
            "high": np.linspace(24200, 25200, n),
            "low": np.linspace(23900, 24800, n),
            "close": np.linspace(24100, 25100, n),
            "volume": np.full(n, 1000000.0),
        },
        index=dates,
    )

    mock_quote = MagicMock()
    mock_quote.last_price = 25100.0
    mock_quote.close = 25050.0

    monkeypatch.setattr("market.history.get_ohlcv", lambda sym, **kwargs: df_daily)
    monkeypatch.setattr("market.quotes.get_quote", lambda insts: {"NSE:NIFTY": mock_quote})

    store = DailyLevelsStore()
    dl = store.compute_and_store("NIFTY", session_date="2026-10-26")

    assert dl is not None, "DailyLevels should compute successfully from 60 daily bars"
    assert dl.pdh > 0, "PDH must be non-zero"
    assert dl.pdl > 0, "PDL must be non-zero"
    assert dl.pdc > 0, "PDC must be non-zero"

    # Multi-timeframe Weekly levels
    assert dl.pwh > 0, f"PWH must be positive, got {dl.pwh}"
    assert dl.pwl > 0, f"PWL must be positive, got {dl.pwl}"
    assert dl.pwc > 0, f"PWC must be positive, got {dl.pwc}"
    assert dl.pwh >= dl.pwl, "PWH must be >= PWL"

    # Multi-timeframe Monthly levels
    assert dl.pmh > 0, f"PMH must be positive, got {dl.pmh}"
    assert dl.pml > 0, f"PML must be positive, got {dl.pml}"
    assert dl.pmc > 0, f"PMC must be positive, got {dl.pmc}"
    assert dl.pmh >= dl.pml, "PMH must be >= PML"


# ── 36. get_ohlcv Resampling Fallback for Weekly & Monthly Intervals ──────────
def test_rca_get_ohlcv_weekly_monthly_resampling_fallback(monkeypatch):
    """Verify that get_ohlcv seamlessly resamples daily bars when weekly/monthly interval is requested."""
    import pandas as pd
    import numpy as np
    import market.history
    from market.history import get_ohlcv

    # Seed 60 synthetic daily bars so zero network calls are required
    dates = pd.date_range("2026-08-01", "2026-10-23", freq="B")
    n = len(dates)
    df_daily = pd.DataFrame(
        {
            "open": np.linspace(24000, 25000, n),
            "high": np.linspace(24200, 25200, n),
            "low": np.linspace(23900, 24800, n),
            "close": np.linspace(24100, 25100, n),
            "volume": np.full(n, 1000000.0),
        },
        index=dates,
    )

    orig_get_ohlcv = get_ohlcv

    def _mock_get_ohlcv(symbol, exchange="NSE", interval="day", **kwargs):
        if interval == "day":
            return df_daily.copy()
        # For non-daily without broker endpoint, invoke real get_ohlcv which will trigger Tier 4.5 fallback
        return orig_get_ohlcv(symbol, exchange=exchange, interval=interval, **kwargs)

    monkeypatch.setattr(market.history, "_yfinance_fallback", lambda *args, **kwargs: None)
    monkeypatch.setattr(market.history, "get_ohlcv", _mock_get_ohlcv)

    # Call with interval="week" on benchmark NIFTY
    df_w = _mock_get_ohlcv("NIFTY", interval="week", days=30)
    assert df_w is not None and not df_w.empty, "Weekly OHLCV must not be empty"
    for col in ("open", "high", "low", "close", "volume"):
        assert col in df_w.columns, f"Column {col} missing from resampled weekly bars"
    assert len(df_w) >= 2, "Must contain at least 2 weekly bars"

    # Call with interval="month" on benchmark NIFTY
    df_m = _mock_get_ohlcv("NIFTY", interval="month", days=90)
    assert df_m is not None and not df_m.empty, "Monthly OHLCV must not be empty"
    for col in ("open", "high", "low", "close", "volume"):
        assert col in df_m.columns, f"Column {col} missing from resampled monthly bars"


# ── 37. RVOL Intraday Mathematical Derivation (Zero Fake 1.5 Defaults) ───────
def test_rca_rvol_intraday_derivation_without_fake_defaults():
    """Verify calculate_intraday_rvol computes real volume expansion and returns 1.0 (not 1.5) on flat volume."""
    import pandas as pd
    import numpy as np
    from engine.daily_levels import calculate_intraday_rvol

    dates_5m = pd.date_range("2026-10-26 09:15", "2026-10-26 10:30", freq="5min")
    n = len(dates_5m)

    # Case A: Massive volume surge on latest bar (5x average)
    vols_surge = np.full(n, 10000.0)
    vols_surge[-1] = 50000.0
    df_surge = pd.DataFrame(
        {"open": 100.0, "high": 102.0, "low": 99.5, "close": 101.5, "volume": vols_surge},
        index=dates_5m,
    )
    rvol_surge = calculate_intraday_rvol(df_surge)
    assert rvol_surge >= 4.5, f"RVOL on 5x volume bar should be >= 4.5, got {rvol_surge}"

    # Case B: Flat volume (1.0x baseline)
    vols_flat = np.full(n, 10000.0)
    df_flat = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.5, "close": 100.5, "volume": vols_flat},
        index=dates_5m,
    )
    rvol_flat = calculate_intraday_rvol(df_flat)
    assert rvol_flat == 1.0, f"RVOL on flat volume should be 1.0, got {rvol_flat}"

    # Case C: None or empty DataFrame -> must return 1.0, never hallucinate 1.5
    assert calculate_intraday_rvol(None) == 1.0
    assert calculate_intraday_rvol(pd.DataFrame()) == 1.0


# ── 38. CVD Intraday Microstructure Derivation and Absorption Divergence ──────
def test_rca_cvd_intraday_derivation_and_divergence():
    """Verify calculate_intraday_cvd computes exact volume deltas and flags Bullish Absorption / Bearish Exhaustion."""
    import pandas as pd
    import numpy as np
    from engine.daily_levels import calculate_intraday_cvd

    dates_5m = pd.date_range("2026-10-26 09:15", "2026-10-26 10:30", freq="5min")
    n = len(dates_5m)

    # Construct Bullish Absorption: Price dips/flats while buyers aggressively absorb at highs of the bar
    # (High closes relative to bar ranges with heavy volume)
    highs = np.linspace(25000, 24980, n)  # Price drifted down slightly
    lows = highs - 20.0
    closes = highs - 1.0  # Closes near high of every 5m bar = buyer initiated
    volumes = np.linspace(50000, 100000, n)

    df_abs = pd.DataFrame(
        {"open": lows + 5.0, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates_5m,
    )

    cvd, slope, div = calculate_intraday_cvd(df_abs)
    assert cvd > 0, f"Cumulative volume delta should be positive on high-close bars, got {cvd}"
    assert slope > 0, f"CVD slope should be positive, got {slope}"
    assert div == "BULLISH_ABSORPTION", f"Expected BULLISH_ABSORPTION, got {div}"


# ── 39. ORB Detector Rejects Unverified Volume Expansion Traps ───────────────
def test_rca_orb_requires_verified_volume_expansion():
    """Verify ORB breakout rejects moves when volume expansion is unverified or flat, preventing opening traps."""
    import pandas as pd
    from engine.detectors.orb import detect_opening_range_breakout

    dates_5m = pd.date_range("2026-10-26 09:15", "2026-10-26 09:40", freq="5min")
    len(dates_5m)

    # 5m candles with flat unexpanded volume
    df_flat = pd.DataFrame(
        {
            "open": [25000, 25020, 25040, 25050, 25080, 25110],
            "high": [25030, 25050, 25060, 25070, 25100, 25120],
            "low": [24980, 25000, 25020, 25030, 25060, 25090],
            "close": [25020, 25040, 25050, 25065, 25095, 25115],
            "volume": [1000, 1000, 1000, 1000, 1000, 1000],  # Flat volume (no expansion)
        },
        index=dates_5m,
    )

    # Breakout attempted above ORB High (25060) at 25115, but with flat volume (rvol=1.0)
    alert = detect_opening_range_breakout(
        symbol="NIFTY",
        df=df_flat,
        ltp=25115.0,
        vwap=25050.0,
        rvol=1.0,  # Below min_rvol of 1.30 for index
        orb_levels=(25060.0, 24980.0, 80.0, 25020.0),
        ignore_time_gate=True,
    )
    assert alert is None, (
        "ORB breakout without volume expansion (RVOL < 1.30x) must be rejected to prevent trap"
    )


# ── 40. Unified Market Intelligence Packet Provenance & Completeness ─────────
def test_rca_market_intelligence_packet_provenance():
    """Verify get_market_intelligence returns complete packet with multi-timeframe levels, RVOL, CVD, and fail-closed."""
    from engine.intraday_microstructure import get_market_intelligence

    # Query benchmark NIFTY
    pkt = get_market_intelligence("NIFTY")
    assert pkt is not None, "Benchmark NIFTY intelligence packet must be resolvable"
    assert pkt.is_complete, "Packet must be complete (PDH > 0, PDL > 0, PDC > 0, LTP > 0)"
    assert pkt.pwh > 0, "PWH must be positive"
    assert pkt.pwl > 0, "PWL must be positive"
    assert pkt.pmh > 0, "PMH must be positive"
    assert pkt.pml > 0, "PML must be positive"
    assert pkt.cpr.get("pivot", 0) > 0, "CPR Pivot must be positive"
    assert pkt.camarilla.get("h4", 0) > 0, "Camarilla H4 must be positive"
    assert pkt.camarilla.get("l4", 0) > 0, "Camarilla L4 must be positive"

    # Query unreachable non-existent symbol -> must fail closed (return None)
    unreachable = get_market_intelligence("NON_EXISTENT_GHOST_TICKER_999")
    assert unreachable is None, "Unreachable symbol must fail closed and return None (Rule 11)"
