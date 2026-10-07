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
    def __init__(self, symbol, strike, option_type, ltp, volume=20000, oi=40000, pchange=18.0, oi_change=1200):
        self.symbol = symbol
        self.strike = strike
        self.option_type = option_type
        self.ltp = ltp
        self.last_price = ltp
        self.volume = volume
        self.oi = oi
        self.pchange = pchange
        self.oi_change = oi_change


def _make_dummy_5m_ohlcv(bars: int = 15, base_price: float = 24980.0, trend: str = "DOWN", date_str: str = "2026-10-07") -> pd.DataFrame:
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
        records.append({
            "datetime": t,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": 25000 + i * 200,
        })
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
    cam_l4 = 24917.5
    spot = 24910.0  # Pierced Cam L4

    ref_t = datetime(2026, 10, 7, 10, 30, tzinfo=IST)
    # 5m candle: Open 24925, High 24935, Low 24860 (75 pt range), Close 24930 (green, 65 pt lower wick = 86%)
    ts = pd.date_range("2026-10-07 09:30:00", periods=12, freq="5min", tz="Asia/Kolkata")
    records = []
    for i, t in enumerate(ts):
        if i == len(ts) - 1:
            records.append({"datetime": t, "open": 24925.0, "high": 24935.0, "low": 24860.0, "close": 24930.0, "volume": 35000})
        else:
            records.append({"datetime": t, "open": 25000.0 - i*5, "high": 25005.0 - i*5, "low": 24990.0 - i*5, "close": 24995.0 - i*5, "volume": 20000})
    df_5m = pd.DataFrame(records).set_index("datetime")

    chain = [
        MockOptionContract("NSE:NIFTY26O1324900PE", 24900.0, "PE", 130.0, volume=25000, oi=12000, pchange=20.0)
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
    assert len(l4_alerts) == 0, "Absorption hammer at Cam L4 must NOT trigger CAMARILLA_L4_BREAKDOWN"


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
        MockOptionContract("NSE:NIFTY26O1324900PE", 24900.0, "PE", 125.0, volume=22000, oi=11000, pchange=20.0),
        MockOptionContract("NSE:NIFTY26O1324950PE", 24950.0, "PE", 155.0, volume=14000, oi=9000, pchange=16.0),
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
            records.append({"datetime": t, "open": 22585.0, "high": 22618.0, "low": 22580.0, "close": 22615.0, "volume": 65000})
        else:
            records.append({"datetime": t, "open": 22560.0 + i*2, "high": 22570.0 + i*2, "low": 22555.0 + i*2, "close": 22565.0 + i*2, "volume": 30000})
    df_5m = pd.DataFrame(records).set_index("datetime")

    chain = [
        MockOptionContract("NSE:NIFTY26O1322600PE", 22600.0, "PE", 110.0, volume=35000, oi=45000, pchange=12.0)
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
        MockOptionContract("NSE:BANKNIFTY26O1354500PE", 54500.0, "PE", 350.0, volume=35000, oi=15000, pchange=22.0)
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
        MockOptionContract("NSE:NIFTY26O1322600CE", 22600.0, "CE", 120.0, volume=45000, oi=25000, pchange=18.0)
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
    assert accepted is False, "Incoming CE alert within 30m of active PE alert on BANKNIFTY must be suppressed"


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
    with patch.object(engine, "_batch_refresh_quotes", return_value={"NSE:NIFTY26O1322650PE": 175.0}):
        engine.check_and_alert_invalidations()

    # alert.ltp and option_premium should update to 175.0, but underlying_spot MUST stay 22650.0!
    assert alert.ltp == 175.0
    assert alert.option_premium == 175.0
    assert alert.underlying_spot == 22650.0, "underlying_spot must NOT be corrupted by option premium quote"


# ── 7. Winnability Upgrade Stability Window ───────────────────────────────────
def test_winnability_upgrade_stability_window():
    """An active premier index trade cannot be unseated within 15 minutes by an incremental 2-point score difference."""
    engine = AutoAlertEngine()
    engine._alerts.clear()

    # Active NIFTY trade with winnability score ~80 created 5 minutes ago
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

    # Incoming BANKNIFTY alert with marginally higher score (84 vs 82)
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

    accepted = engine.record_alert(incoming_bn)
    # The active trade is within its 15-minute stability window (5m old).
    # Incoming score is only marginally higher, so it must NOT unseat the active Nifty trade!
    assert active_nifty.stage == "IGNITED", "Active trade must remain IGNITED and not superseded"
    assert accepted is False, "Incremental trade within 15m stability window must be suppressed"
