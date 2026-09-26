"""
tests/test_index_hedge_and_breakout_scrutiny.py
───────────────────────────────────────────────
Verification suite for index signal accuracy, breakout scrutiny veto repair,
trend-pullback signals, and institutional defined-risk hedge plans.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pandas as pd

from engine.alert_model import AutoAlert
from engine.alert_scrutiny import alert_scrutiny_auditor
from engine.auto_alert_engine import AutoAlertEngine
from engine.detectors.index_call_setup import detect_index_call_setup
from engine.detectors.index_put_setup import detect_index_put_setup
from engine.detectors.orb import detect_opening_range_breakout

IST = timezone(timedelta(hours=5, minutes=30))


class DummyContract:
    def __init__(self, strike: float, opt_type: str, ltp: float, vol: int = 50000, oi: int = 20000):
        self.strike = strike
        self.option_type = opt_type
        self.last_price = ltp
        self.volume = vol
        self.oi = oi
        self.pchange = 12.0
        self.symbol = f"BANKNIFTY26SEP{int(strike)}{opt_type}"
        self.expiry = "2026-09-29"


def _make_dummy_ohlcv(
    bars: int = 20, trend: str = "UP", base_price: float = 56200.0
) -> pd.DataFrame:
    records = []
    curr = base_price
    start_time = datetime(2026, 9, 23, 9, 15, tzinfo=IST)
    for i in range(bars):
        t = start_time + timedelta(minutes=5 * i)
        if trend == "UP":
            step = 25.0
            o = curr
            h = o + 20.0
            l = o - 5.0
            c = o + step
            curr = c
        elif trend == "DOWN":
            step = -25.0
            o = curr
            h = o + 5.0
            l = o - 20.0
            c = o + step
            curr = c
        else:  # FLAT / CHOP
            o = base_price + (i % 2) * 5.0
            h = o + 8.0
            l = o - 8.0
            c = o + 2.0
        records.append(
            {
                "datetime": t,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": 20000 + i * 500,
            }
        )
    df = pd.DataFrame(records)
    df.set_index("datetime", inplace=True)
    return df


# ── Test 1: Day High Breakout Not Vetoed by Opposing Supply Gate ───────────────


def test_day_high_breakout_not_vetoed_by_opposing_supply():
    """Spot testing or coiled within 0.15% below Day High must NOT be killed as Opposing Supply Collision."""
    spot = 56550.0
    day_high = 56600.0  # 50 pts (0.088%) headroom

    alert = AutoAlert(
        alert_id="test-dhb-banknifty",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="BANKNIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="🚀 DAY HIGH BREAKOUT: BANKNIFTY 56500 CE",
        summary="Spot breaking out through Day High",
        ltp=410.0,
        trigger_level=410.0,
        target_level=520.0,
        stop_loss=340.0,
        strike=56500.0,
        option_type="CE",
        segment="FNO_INDEX",
        underlying_spot=spot,
        metrics={
            "day_high": day_high,
            "day_low": 56200.0,
            "signals": ["DAY_HIGH_BREAKOUT"],
            "rvol": 1.5,
            "ce_pchange": 14.0,
            "vol_oi_ratio": 2.5,
            "lot_size": 30,
        },
        actionable_plan={"target_1": "₹520.0", "stop_loss": "₹340.0"},
    )

    ok, reason, flags = alert_scrutiny_auditor.verify_tier1_sanity(alert)
    assert ok is True, f"Expected alert to pass Tier-1 sanity, but failed with: {reason}"
    assert "Opposing Supply Collision" not in (reason or "")


# ── Test 2: Day Low Breakdown Not Vetoed by Opposing Demand Gate ───────────────


def test_day_low_breakdown_not_vetoed_by_opposing_demand():
    """Spot testing or coiled within 0.15% above Day Low must NOT be killed as Opposing Demand Collision."""
    spot = 56220.0
    day_low = 56180.0  # 40 pts (0.071%) headroom

    alert = AutoAlert(
        alert_id="test-dlb-banknifty",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="BANKNIFTY",
        exchange="NSE",
        direction="BEARISH",
        headline="📉 DAY LOW BREAKDOWN: BANKNIFTY 56200 PE",
        summary="Spot breaking down through Day Low",
        ltp=380.0,
        trigger_level=380.0,
        target_level=490.0,
        stop_loss=315.0,
        strike=56200.0,
        option_type="PE",
        segment="FNO_INDEX",
        underlying_spot=spot,
        metrics={
            "day_high": 56600.0,
            "day_low": day_low,
            "signals": ["DAY_LOW_BREAKDOWN"],
            "rvol": 1.6,
            "pe_pchange": 16.0,
            "vol_oi_ratio": 2.2,
            "lot_size": 30,
        },
        actionable_plan={"target_1": "₹490.0", "stop_loss": "₹315.0"},
    )

    ok, reason, flags = alert_scrutiny_auditor.verify_tier1_sanity(alert)
    assert ok is True, f"Expected alert to pass Tier-1 sanity, but failed with: {reason}"
    assert "Opposing Demand Collision" not in (reason or "")


# ── Test 3: ORB Breakout Target & R:R Sanity ─────────────────────────────────


def test_orb_breakout_rr_ratio_valid():
    """ORB-15 breakout must satisfy institutional R:R >= 1:1.5 and pass Tier-1 sanity."""
    ref_time = datetime(2026, 9, 23, 9, 35, tzinfo=IST)
    records = [
        {
            "datetime": datetime(2026, 9, 23, 9, 15, tzinfo=IST),
            "open": 56250.0,
            "high": 56350.0,
            "low": 56200.0,
            "close": 56300.0,
            "volume": 50000,
        },
        {
            "datetime": datetime(2026, 9, 23, 9, 20, tzinfo=IST),
            "open": 56300.0,
            "high": 56400.0,
            "low": 56250.0,
            "close": 56350.0,
            "volume": 60000,
        },
        {
            "datetime": datetime(2026, 9, 23, 9, 25, tzinfo=IST),
            "open": 56350.0,
            "high": 56380.0,
            "low": 56300.0,
            "close": 56370.0,
            "volume": 55000,
        },
        {
            "datetime": datetime(2026, 9, 23, 9, 30, tzinfo=IST),
            "open": 56380.0,
            "high": 56440.0,
            "low": 56370.0,
            "close": 56430.0,
            "volume": 95000,
        },
    ]
    df_5m = pd.DataFrame(records).set_index("datetime")
    ltp = 56430.0  # Broke above orb_high (56400.0), well within no_chase (56400 + 70 = 56470)

    alert = detect_opening_range_breakout(
        symbol="BANKNIFTY",
        df=df_5m,
        ltp=ltp,
        vwap=56350.0,
        exchange="NSE",
        rvol=1.8,
        ref_time=ref_time,
        ignore_time_gate=True,
    )
    assert alert is not None
    assert alert.direction == "BULLISH"
    assert "ORB" in alert.headline

    ok, reason, flags = alert_scrutiny_auditor.verify_tier1_sanity(alert)
    assert ok is True, f"ORB alert failed Tier-1 sanity: {reason}"


# ── Test 4: Index Call Setup Generates Hedged Spread (Bull Call Spread) ────────


def test_index_call_setup_generates_hedge_plan():
    """detect_index_call_setup must produce a complete defined-risk BULL_CALL_SPREAD hedge_plan."""
    spot = 56500.0
    chain = [
        DummyContract(56400.0, "CE", 480.0),
        DummyContract(56500.0, "CE", 410.0),
        DummyContract(56600.0, "CE", 345.0),
        DummyContract(56700.0, "CE", 285.0),
        DummyContract(56800.0, "CE", 230.0),
        DummyContract(56900.0, "CE", 185.0),
    ]
    df_5m = _make_dummy_ohlcv(bars=12, trend="UP", base_price=56300.0)

    alerts = detect_index_call_setup(
        underlying="BANKNIFTY",
        spot=spot,
        chain=chain,
        vwap=56450.0,
        day_high=56510.0,
        day_low=56250.0,
        prev_day_high=56200.0,
        prev_day_low=55900.0,
        ohlcv_5m=df_5m,
    )
    assert len(alerts) >= 1
    alert = alerts[0]

    # Check actionable_plan has hedge_plan
    assert "hedge_plan" in alert.actionable_plan
    hedge = alert.actionable_plan["hedge_plan"]
    assert hedge is not None
    assert hedge["strategy"] == "BULL_CALL_SPREAD"
    assert hedge["sentiment"] == "BULLISH"
    assert hedge["max_loss"] > 0
    assert hedge["max_profit"] > 0
    assert len(hedge["legs"]) == 2
    assert hedge["legs"][0]["side"] == "BUY" and hedge["legs"][0]["option_type"] == "CE"
    assert hedge["legs"][1]["side"] == "SELL" and hedge["legs"][1]["option_type"] == "CE"
    assert "preferred_vehicle" in alert.actionable_plan


# ── Test 5: Index Put Setup Generates Hedged Spread (Bear Put Spread) ──────────


def test_index_put_setup_generates_hedge_plan():
    """detect_index_put_setup must produce a complete defined-risk BEAR_PUT_SPREAD hedge_plan."""
    spot = 56250.0
    chain = [
        DummyContract(56400.0, "PE", 510.0),
        DummyContract(56300.0, "PE", 440.0),
        DummyContract(56200.0, "PE", 380.0),
        DummyContract(56100.0, "PE", 320.0),
        DummyContract(56000.0, "PE", 265.0),
        DummyContract(55900.0, "PE", 215.0),
    ]
    df_5m = _make_dummy_ohlcv(bars=12, trend="DOWN", base_price=56500.0)

    alerts = detect_index_put_setup(
        underlying="BANKNIFTY",
        spot=spot,
        chain=chain,
        vwap=56350.0,
        day_high=56550.0,
        day_low=56240.0,
        prev_day_high=56700.0,
        prev_day_low=56400.0,
        ohlcv_5m=df_5m,
    )
    assert len(alerts) >= 1
    alert = alerts[0]

    assert "hedge_plan" in alert.actionable_plan
    hedge = alert.actionable_plan["hedge_plan"]
    assert hedge is not None
    assert hedge["strategy"] == "BEAR_PUT_SPREAD"
    assert hedge["sentiment"] == "BEARISH"
    assert hedge["max_loss"] > 0
    assert hedge["max_profit"] > 0
    assert len(hedge["legs"]) == 2
    assert hedge["legs"][0]["side"] == "BUY" and hedge["legs"][0]["option_type"] == "PE"
    assert hedge["legs"][1]["side"] == "SELL" and hedge["legs"][1]["option_type"] == "PE"


# ── Test 6: Midday Chop Regime Detection Enforces Spread Preference ────────────


def test_midday_chop_regime_sets_spread_preference():
    """During tight midday chop (<0.20% 1h range), regime is CHOP_CONSOLIDATION and preferred_vehicle is HEDGED_SPREAD."""
    engine = AutoAlertEngine()

    # 1. Test flat chop DataFrame (< 0.20% range)
    df_flat = _make_dummy_ohlcv(bars=15, trend="FLAT", base_price=56500.0)

    with patch("engine.auto_alert_engine.datetime") as mock_dt:
        mock_now = datetime(2026, 9, 23, 12, 30, tzinfo=IST)
        mock_dt.now.return_value = mock_now

        regime = engine._get_index_intraday_regime(df_flat, spot=56500.0)
        assert regime == "CHOP_CONSOLIDATION"

    # 2. Test trending DataFrame (>= 0.50% range)
    df_trend = _make_dummy_ohlcv(bars=15, trend="UP", base_price=56200.0)
    regime_trend = engine._get_index_intraday_regime(df_trend, spot=56550.0)
    assert regime_trend == "TRENDING"


def test_market_breadth_sanity_veto_call_spreads_in_broad_decline(monkeypatch):
    """
    Gate 22 Verification:
    When broad market breadth is in severe decline (BROAD_DECLINE, e.g. A/D 0.17, 73 Adv vs 426 Dec),
    Bullish index Call spreads must be strictly VETOED by Tier-1 sanity.
    Symmetrically, Bearish Put setups must be permitted.
    """
    from market.sentiment import MarketBreadth
    from engine.alert_model import AutoAlert
    from engine.learning_engine import pattern_learning_engine

    pattern_learning_engine.clear_symbol_lockout("NIFTY")
    monkeypatch.setenv("ENFORCE_TEST_BREADTH", "1")
    monkeypatch.setattr(
        "market.sentiment.get_market_breadth",
        lambda *args, **kwargs: MarketBreadth(
            advances=73, declines=426, unchanged=2, ad_ratio=0.17, verdict="BROAD_DECLINE"
        ),
    )

    # 1. Bullish Call Alert on NIFTY
    call_alert = AutoAlert(
        alert_id="live-nifty-call-breadth-veto",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY 24800 CE BOUNCE OFF 200 EMA",
        summary="Oversold RSI bounce",
        ltp=150.0,
        trigger_level=150.0,
        target_level=220.0,
        stop_loss=110.0,
        option_type="CE",
        strike=24800.0,
        confidence=92,
        is_live=True,
        environment="LIVE",
        segment="FNO_INDEX",
        metrics={"enforce_breadth": True},
    )

    ok, reason, flags = alert_scrutiny_auditor.verify_tier1_sanity(call_alert)
    assert ok is False
    assert flags["market_breadth_valid"] is False
    assert "Market Breadth Liquidation Veto" in reason

    # 2. Bearish Put Alert on NIFTY (aligned with negative breadth tide)
    put_alert = AutoAlert(
        alert_id="live-nifty-put-breadth-allow",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BEARISH",
        headline="NIFTY 24600 PE BREAKDOWN ACCELERATION",
        summary="Support break",
        ltp=150.0,
        trigger_level=150.0,
        target_level=220.0,
        stop_loss=110.0,
        option_type="PE",
        strike=24600.0,
        confidence=92,
        is_live=True,
        environment="LIVE",
        segment="FNO_INDEX",
        metrics={"enforce_breadth": True},
    )

    ok_put, reason_put, flags_put = alert_scrutiny_auditor.verify_tier1_sanity(put_alert)
    assert flags_put["market_breadth_valid"] is True


# ── Test 8: Optimization 1 — Intraday PCR Confluence Gate ─────────────────────


def test_index_call_setup_suppressed_on_low_pcr_call_wall():
    """When PCR < 0.65 (heavy Call writing wall), index call setup must be suppressed."""
    spot = 56250.0
    # Chain with 60k CE OI vs 20k PE OI -> PCR = 0.33
    chain = [
        DummyContract(56200.0, "CE", 380.0, vol=15000, oi=30000),
        DummyContract(56300.0, "CE", 310.0, vol=15000, oi=30000),
        DummyContract(56200.0, "PE", 350.0, vol=5000, oi=10000),
        DummyContract(56100.0, "PE", 290.0, vol=5000, oi=10000),
    ]
    df_5m = _make_dummy_ohlcv(bars=12, trend="UP", base_price=56100.0)

    alerts = detect_index_call_setup(
        underlying="BANKNIFTY",
        spot=spot,
        chain=chain,
        vwap=56200.0,
        day_high=56300.0,
        day_low=56100.0,
        prev_day_high=56500.0,
        prev_day_low=56000.0,
        ohlcv_5m=df_5m,
    )
    # Must be suppressed due to low PCR call wall
    assert len(alerts) == 0


def test_index_put_setup_suppressed_on_high_pcr_put_cushion():
    """When PCR > 1.45 (heavy Put writing floor cushion), index put setup must be suppressed."""
    spot = 56250.0
    # Chain with 15k CE OI vs 35k PE OI -> PCR = 2.33
    chain = [
        DummyContract(56300.0, "CE", 310.0, vol=5000, oi=8000),
        DummyContract(56400.0, "CE", 250.0, vol=5000, oi=7000),
        DummyContract(56200.0, "PE", 350.0, vol=15000, oi=18000),
        DummyContract(56100.0, "PE", 290.0, vol=15000, oi=17000),
    ]
    df_5m = _make_dummy_ohlcv(bars=12, trend="DOWN", base_price=56400.0)

    alerts = detect_index_put_setup(
        underlying="BANKNIFTY",
        spot=spot,
        chain=chain,
        vwap=56300.0,
        day_high=56450.0,
        day_low=56200.0,
        prev_day_high=56600.0,
        prev_day_low=56350.0,
        ohlcv_5m=df_5m,
    )
    # Must be suppressed due to high PCR put floor cushion
    assert len(alerts) == 0


# ── Test 9: Optimization 2 — Index Heavyweight Locomotive Gate ────────────────


def test_index_call_setup_suppressed_on_heavyweights_markdown(monkeypatch):
    """When primary index heavyweights (e.g. HDFCBANK & RELIANCE) are all in markdown, Call setups are suppressed."""
    spot = 24850.0
    chain = [
        DummyContract(24850.0, "CE", 120.0, vol=15000, oi=15000),
        DummyContract(24900.0, "CE", 95.0, vol=15000, oi=15000),
        DummyContract(24850.0, "PE", 115.0, vol=15000, oi=15000),
        DummyContract(24800.0, "PE", 90.0, vol=15000, oi=15000),
    ]
    df_5m = _make_dummy_ohlcv(bars=12, trend="UP", base_price=24800.0)

    # Mock heavyweights posture returning all_bearish=True
    monkeypatch.setattr(
        "market.indices.get_heavyweights_posture",
        lambda sym: {
            "underlying": sym,
            "all_bearish": True,
            "all_bullish": False,
            "heavyweights": [
                {"symbol": "RELIANCE", "change_pct": -0.85},
                {"symbol": "HDFCBANK", "change_pct": -0.62},
            ],
            "summary": "ALL_BEARISH",
        },
    )

    alerts = detect_index_call_setup(
        underlying="NIFTY",
        spot=spot,
        chain=chain,
        vwap=24820.0,
        day_high=24880.0,
        day_low=24800.0,
        prev_day_high=25100.0,
        prev_day_low=24750.0,
        ohlcv_5m=df_5m,
    )
    assert len(alerts) == 0


# ── Test 10: Optimization 4 — Market Regime Posture & Stand Aside Discipline ──


def test_market_regime_posture_stand_aside_discipline(monkeypatch):
    """When Market Breadth is MIXED and midday 1-hour price range is tight (<0.22%), signals STAND_ASIDE."""
    from market.sentiment import MarketBreadth, get_market_regime_posture

    monkeypatch.setattr(
        "market.sentiment.get_market_breadth",
        lambda *args, **kwargs: MarketBreadth(
            advances=240, declines=255, unchanged=5, ad_ratio=0.94, verdict="MIXED"
        ),
    )

    df_chop = _make_dummy_ohlcv(bars=15, trend="FLAT", base_price=24800.0)
    midday_now = datetime(2026, 9, 24, 12, 30, tzinfo=IST)

    posture = get_market_regime_posture(df_5m=df_chop, spot=24800.0, now_dt=midday_now)
    assert posture.is_stand_aside is True
    assert posture.action == "STAND_ASIDE"
    assert posture.regime == "CHOP_CONSOLIDATION"
    assert "STAND ASIDE & PRESERVE CAPITAL" in posture.verdict_message


