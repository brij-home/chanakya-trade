"""
Unit tests for Intraday Rolling Breadth, Options Stop-Loss Bounding,
and Scrutiny Liquidation Approval.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from engine.market_matrix import MarketMatrix
from market.sentiment import MarketBreadth, get_market_breadth
from engine.alert_scrutiny import AlertScrutinyAuditor
from engine.alert_model import AutoAlert

IST = ZoneInfo("Asia/Kolkata")


def test_market_matrix_intraday_rolling_breadth():
    """Verify that MarketMatrix calculates rolling intraday breadth from in-RAM ticks."""
    matrix = MarketMatrix()

    # Simulate 10 F&O stock ticks: 7 below VWAP, 3 above VWAP
    ticks = [
        {"symbol": "NSE:RELIANCE-EQ", "ltp": 2400.0, "vwap": 2420.0, "open": 2430.0},
        {"symbol": "NSE:TCS-EQ", "ltp": 3800.0, "vwap": 3850.0, "open": 3860.0},
        {"symbol": "NSE:INFY-EQ", "ltp": 1750.0, "vwap": 1780.0, "open": 1790.0},
        {"symbol": "NSE:HDFCBANK-EQ", "ltp": 1650.0, "vwap": 1670.0, "open": 1675.0},
        {"symbol": "NSE:ICICIBANK-EQ", "ltp": 1150.0, "vwap": 1170.0, "open": 1180.0},
        {"symbol": "NSE:SBIN-EQ", "ltp": 780.0, "vwap": 795.0, "open": 800.0},
        {"symbol": "NSE:AXISBANK-EQ", "ltp": 1100.0, "vwap": 1120.0, "open": 1130.0},
        # 3 stocks above VWAP
        {"symbol": "NSE:ITC-EQ", "ltp": 475.0, "vwap": 470.0, "open": 468.0},
        {"symbol": "NSE:BHARTIARTL-EQ", "ltp": 1580.0, "vwap": 1560.0, "open": 1550.0},
        {"symbol": "NSE:LT-EQ", "ltp": 3500.0, "vwap": 3480.0, "open": 3470.0},
    ]

    for t in ticks:
        matrix.on_tick(t)

    breadth = matrix.get_intraday_breadth()
    assert breadth["total_symbols"] == 10
    assert breadth["above_vwap"] == 3
    assert breadth["below_vwap"] == 7
    assert breadth["vwap_ratio"] == 0.43  # 3 / 7 = 0.43
    assert breadth["verdict"] == "INTRADAY_LIQUIDATION"


def test_sentiment_get_market_breadth_uses_matrix(monkeypatch):
    """Verify that sentiment.get_market_breadth prioritizes in-RAM MarketMatrix breadth."""
    matrix = MarketMatrix()
    # 20 symbols (>= 15 required for streaming activation)
    ticks = []
    # 16 below VWAP
    for i in range(16):
        ticks.append(
            {
                "symbol": f"NSE:DOWN_{i}-EQ",
                "ltp": 100.0,
                "vwap": 105.0,
                "open": 108.0,
            }
        )
    # 4 above VWAP
    for i in range(4):
        ticks.append(
            {
                "symbol": f"NSE:UP_{i}-EQ",
                "ltp": 210.0,
                "vwap": 200.0,
                "open": 195.0,
            }
        )

    for t in ticks:
        matrix.on_tick(t)

    import engine.market_matrix as mm_module

    monkeypatch.setattr(mm_module, "get_market_matrix", lambda: matrix)

    b = get_market_breadth(force_refresh=True)
    assert b.above_vwap == 4
    assert b.below_vwap == 16
    assert b.vwap_ratio == 0.25
    assert b.intraday_verdict == "INTRADAY_LIQUIDATION"
    assert b.verdict == "BROAD_DECLINE"
    assert b.advances == 4
    assert b.declines == 16


def test_scrutiny_permits_put_during_intraday_retreat(monkeypatch):
    """
    Verify that AlertScrutiny does not trigger Market Breadth Rally Veto
    on Put setups when the underlying is retreating from its day high
    or trading below VWAP, even if morning A/D breadth was bullish.
    """
    monkeypatch.setenv("CHANAKYA_TESTING", "1")

    # Stale morning breadth: 350 advances vs 150 declines (A/D = 2.33, strongly bullish)
    stale_breadth = MarketBreadth(
        advances=350,
        declines=150,
        unchanged=10,
        ad_ratio=2.33,
        verdict="BROAD_RALLY",
        above_vwap=100,
        below_vwap=400,
        vwap_ratio=0.25,
        intraday_verdict="INTRADAY_LIQUIDATION",
    )
    monkeypatch.setattr("market.sentiment.get_market_breadth", lambda: stale_breadth)

    # Put alert on SENSEX retreating from day high
    alert = AutoAlert(
        alert_id="aa-index-put-setup-sensex-20261111",
        alert_type="INDEX_PUT_SETUP",
        stage="IGNITED",
        symbol="SENSEX",
        exchange="BFO",
        direction="BEARISH",
        headline="📉 SENSEX 81100 PE Institutional Breakdown",
        summary="SENSEX breaking down from day high into liquidation cascade.",
        ltp=250.0,
        trigger_level=250.0,
        target_level=450.0,
        stop_loss=190.0,
        no_chase_boundary=270.0,
        strike=81100.0,
        option_type="PE",
        contract_symbol="SENSEX81100PE",
        segment="OPTIONS",
        lot_size=10,
        option_premium=250.0,
        underlying_spot=81050.0,
        metrics={
            "day_high": 82000.0,  # Retreated 950 points from high (-1.16%)
            "day_low": 80900.0,
            "underlying_spot": 81050.0,
            "underlying_vwap": 81500.0,
            "spot_change_pct": -0.85,
            "signals": ["INSTITUTIONAL_EXPANSION_BREAKDOWN"],
            "rvol": 2.2,
        },
    )

    auditor = AlertScrutinyAuditor()
    passed, reason, checks = auditor.verify_tier1_sanity(alert)
    assert passed is True, f"Tier 1 unexpectedly rejected: {reason}"
    assert "Market Breadth Rally Veto" not in (reason or "")


def test_option_stop_loss_bounding_in_index_put_setup():
    """Verify that index_put_setup bounds option stop-loss between 8% and 25% of premium."""
    from engine.detectors.index_put_setup import detect_index_put_setup
    import pandas as pd

    # Synthetic 5m bars for SENSEX showing a breakdown
    bars = []
    base_p = 82000.0
    for i in range(25):
        base_p -= 30.0
        bars.append(
            {
                "open": base_p + 15.0,
                "high": base_p + 20.0,
                "low": base_p - 15.0,
                "close": base_p,
                "volume": 5000 + i * 200,
            }
        )
    df_5m = pd.DataFrame(bars)
    now_dt = datetime(2026, 11, 11, 11, 30, tzinfo=IST)

    alerts = detect_index_put_setup(
        underlying="SENSEX",
        spot=base_p,
        chain=[],
        vwap=81800.0,
        day_high=82100.0,
        day_low=base_p - 10.0,
        ohlcv_5m=df_5m,
        ref_time=now_dt,
        ignore_time_gate=True,
    )

    if alerts:
        alert = alerts[0]
        opt_ltp = alert.option_premium or alert.ltp
        opt_sl = alert.stop_loss
        if opt_ltp and opt_ltp > 5.0:
            loss_pct = (opt_ltp - opt_sl) / opt_ltp
            # Max loss must not exceed 25% of entry premium
            assert loss_pct <= 0.255, (
                f"Option SL loss {loss_pct * 100:.1f}% exceeds 25% bound: ltp={opt_ltp}, sl={opt_sl}"
            )
            # Option SL must never collapse to 0.50
            assert opt_sl >= (opt_ltp * 0.74), (
                f"Option SL {opt_sl} collapsed below 74% floor for ltp {opt_ltp}"
            )


def test_initial_balance_bounce_suppression_under_vwap():
    """Verify that Initial Balance bounce low is suppressed or converted when spot is dumping below VWAP."""
    from engine.detectors.initial_balance import detect_initial_balance_setups

    # IB High = 24500, IB Low = 24400. Post IB dumping from 24450 to 24395 with heavy volume
    post_moves = [
        (24450.0, 24460.0, 24420.0, 24425.0),
        (24425.0, 24430.0, 24400.0, 24405.0),
        (24405.0, 24410.0, 24390.0, 24395.0),
    ]

    from tests.test_initial_balance_and_sfp import _generate_synthetic_5m_bars

    df = _generate_synthetic_5m_bars(ib_high=24500.0, ib_low=24400.0, post_ib_moves=post_moves)
    test_time = datetime(2026, 10, 30, 11, 0, tzinfo=IST)

    alerts = detect_initial_balance_setups(
        symbol="NIFTY",
        spot=24395.0,
        df_5m=df,
        atr_14=120.0,
        ref_time=test_time,
        ignore_time_gate=True,
    )

    # It must NOT be a BULLISH bounce long
    for a in alerts:
        assert a.direction != "BULLISH", (
            "Bullish bounce was generated while spot is breaking down below VWAP!"
        )
        assert a.option_type != "CE", (
            "CE setup was generated while spot is breaking down below VWAP!"
        )
