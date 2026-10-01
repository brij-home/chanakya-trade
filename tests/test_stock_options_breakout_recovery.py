"""
tests/test_stock_options_breakout_recovery.py
─────────────────────────────────────────────
Verifies fixes for high-momentum stock options (SONACOMS, MCX, etc.):
1. Gamma blast detection for low-OI-change high-turnover options (MCX 3350 CE pattern).
2. Alert scrutiny Tier-1 approval for staged scale-out trade plans (SONACOMS 840 CE pattern).
3. Options momentum explosive volume bypass for 5-min RSI divergence traps.
4. AutoAlert engine target prioritization: active intraday movers (|change_pct| >= 1.2%)
   prioritized ahead of idle equities.
"""

from datetime import datetime, timedelta
from unittest.mock import patch
import pandas as pd
from config.constants import IST

from brokers.base import OptionsContract, Quote
from engine.alert_scrutiny import alert_scrutiny_auditor
from engine.detectors.gamma_blast import detect_gamma_blast
from engine.detectors.options_momentum import detect_options_momentum_breakouts


def test_mcx_gamma_blast_low_oi_change_recovery():
    """Verifies that an explosive option like MCX 3350 CE (+155%, Vol 1.16M, Vol/OI 2.37x)
    is detected by gamma_blast even if absolute OI change is small (e.g. 700 shares / 3 contracts).
    """
    spot = 3374.0
    now_dt = datetime.now(IST)
    exp_dt = (now_dt + timedelta(days=14)).strftime("%Y-%m-%d")
    contracts = [
        OptionsContract(
            symbol="MCX26SEP3350CE",
            underlying="MCX",
            strike=3350.0,
            option_type="CE",
            expiry=exp_dt,
            last_price=48.5,
            volume=1160000,
            oi=489000,
            oi_change=704,  # Small OI change (< 20 contracts), previously blocked by line 350
            pchange=155.8,
            bid=48.0,
            ask=49.0,
        ),
        OptionsContract(
            symbol="MCX26SEP3350PE",
            underlying="MCX",
            strike=3350.0,
            option_type="PE",
            expiry=exp_dt,
            last_price=12.0,
            volume=150000,
            oi=250000,
            oi_change=5000,
            pchange=-45.0,
            bid=11.5,
            ask=12.5,
        ),
    ]

    alerts = detect_gamma_blast("MCX", spot, contracts, now_dt=now_dt)

    assert len(alerts) >= 1
    mcx_ce = next((a for a in alerts if a.strike == 3350.0 and a.option_type == "CE"), None)
    assert mcx_ce is not None
    assert mcx_ce.symbol == "MCX"
    assert mcx_ce.metrics["vol_oi_ratio"] > 2.0


def test_sonacoms_staged_scaleout_scrutiny_approval():
    """Verifies that multi-target trade plans with T1 anchored to an immediate barrier (R:R >= 1.0)
    and T2 offering expansion (R:R >= 1.5, blended R:R >= req_rr) pass Tier-1 scrutiny.
    """
    spot = 835.0
    now_dt = datetime.now(IST)
    exp_dt = (now_dt + timedelta(days=14)).strftime("%Y-%m-%d")
    contracts = [
        OptionsContract(
            symbol="SONACOMS26SEP840CE",
            underlying="SONACOMS",
            strike=840.0,
            option_type="CE",
            expiry=exp_dt,
            last_price=7.80,
            volume=1040000,
            oi=830000,
            oi_change=-45000,  # Unwinding
            pchange=28.5,
            bid=7.70,
            ask=7.90,
        ),
        OptionsContract(
            symbol="SONACOMS26SEP840PE",
            underlying="SONACOMS",
            strike=840.0,
            option_type="PE",
            expiry=exp_dt,
            last_price=15.0,
            volume=80000,
            oi=400000,
            oi_change=12000,
            pchange=-18.0,
            bid=14.8,
            ask=15.2,
        ),
    ]

    alerts = detect_gamma_blast("SONACOMS", spot, contracts, now_dt=now_dt)

    assert len(alerts) >= 1
    alert = alerts[0]

    # Verify that Tier-1 sanity passes with staged scale-out
    passed, reason, flags = alert_scrutiny_auditor.verify_tier1_sanity(alert)
    assert passed is True, f"Tier-1 scrutiny failed unexpectedly: {reason}"
    assert flags.get("rr_valid") is True


def test_options_momentum_explosive_volume_bypasses_rsi_divergence():
    """Verifies that explosive breakout options (e.g. Vol/OI >= 1.8x or pchange >= 8%)
    are not falsely suppressed by minor 5-minute RSI divergence.
    """
    spot = 3374.0
    exp_dt = (datetime.now(IST) + timedelta(days=14)).strftime("%Y-%m-%d")
    contracts = [
        OptionsContract(
            symbol="MCX26SEP3350CE",
            underlying="MCX",
            strike=3350.0,
            option_type="CE",
            expiry=exp_dt,
            last_price=48.5,
            volume=1160000,
            oi=489000,
            oi_change=704,
            pchange=155.8,
            bid=48.0,
            ask=49.0,
        ),
    ]

    df_5m = pd.DataFrame(
        {
            "open": [3350.0, 3355.0, 3360.0, 3365.0, 3370.0, 3374.0],
            "high": [3355.0, 3362.0, 3368.0, 3372.0, 3375.0, 3378.0],
            "low": [3348.0, 3352.0, 3358.0, 3362.0, 3368.0, 3372.0],
            "close": [3354.0, 3360.0, 3366.0, 3370.0, 3373.0, 3374.0],
            "volume": [10000, 12000, 15000, 18000, 22000, 25000],
        }
    )

    quote_mcx = Quote(
        symbol="MCX",
        last_price=spot,
        open=3350.0,
        high=3378.0,
        low=3348.0,
        change_pct=3.41,
        vwap=3360.0,
    )

    with (
        patch("market.options.get_options_chain", return_value=contracts),
        patch("market.history.get_ohlcv", return_value=df_5m),
        patch(
            "analysis.market_structure.detect_divergence",
            return_value={"type": "REGULAR", "bias": "BEARISH"},
        ),
        patch("engine.alert_preferences.alert_preferences.is_segment_allowed", return_value=True),
        patch("engine.position_sizer.get_lot_size", return_value=200),
    ):
        alerts = detect_options_momentum_breakouts(
            targets=["MCX"],
            batch_quotes={"MCX": quote_mcx, "NSE:MCX": quote_mcx},
        )

    # Should not be killed by the bearish divergence because momentum is explosive
    assert len(alerts) >= 1
    assert alerts[0].symbol == "MCX"
    assert alerts[0].option_type == "CE"


def test_auto_alert_engine_prioritizes_active_intraday_movers():
    """Verifies that _get_prioritized_targets in AutoAlertEngine sorts stocks with
    |change_pct| >= 1.2% ahead of quiescent equities.
    """
    from engine.auto_alert_engine import AutoAlertEngine
    from market.quotes import _QUOTE_CACHE, _quote_cache_lock

    engine = AutoAlertEngine()
    engine._watched_indices = ["NIFTY", "BANKNIFTY"]
    engine.watched_equities = ["RELIANCE", "TCS", "MCX", "SONACOMS", "INFY"]

    with _quote_cache_lock:
        _QUOTE_CACHE["MCX"] = (
            9999999999.0,
            Quote(symbol="MCX", last_price=3374.0, change_pct=3.41),
        )
        _QUOTE_CACHE["SONACOMS"] = (
            9999999999.0,
            Quote(symbol="SONACOMS", last_price=835.0, change_pct=2.97),
        )
        _QUOTE_CACHE["RELIANCE"] = (
            9999999999.0,
            Quote(symbol="RELIANCE", last_price=3000.0, change_pct=0.20),
        )
        _QUOTE_CACHE["TCS"] = (
            9999999999.0,
            Quote(symbol="TCS", last_price=4200.0, change_pct=-0.15),
        )
        _QUOTE_CACHE["INFY"] = (
            9999999999.0,
            Quote(symbol="INFY", last_price=1900.0, change_pct=0.40),
        )

    try:
        with patch(
            "engine.alert_preferences.alert_preferences.is_segment_allowed", return_value=False
        ):
            targets = engine._get_prioritized_targets()
        # Active movers MCX and SONACOMS must appear first in the returned targets
        assert targets[0] == "MCX"
        assert targets[1] == "SONACOMS"
        # Quiescent equities appear afterwards
        assert set(targets[2:]) == {"RELIANCE", "TCS", "INFY"}
    finally:
        with _quote_cache_lock:
            for k in ("MCX", "SONACOMS", "RELIANCE", "TCS", "INFY"):
                _QUOTE_CACHE.pop(k, None)


def test_stock_options_gamma_blast_smc_momentum_override_on_opposing_zone_collision():
    """Verifies that single-stock options with heavy call writer unwinding (oi_change < 0,
    is_oi_shedding or vol_oi_ratio >= 1.5) are NOT killed by trade plan opposing zone collision.
    The SMC momentum expansion override must apply to both single-stock options and indices.
    """
    from engine.trade_plan import TradePlan

    spot = 835.0
    now_dt = datetime.now(IST)
    exp_dt = (now_dt + timedelta(days=14)).strftime("%Y-%m-%d")
    contracts = [
        OptionsContract(
            symbol="SONACOMS26SEP840CE",
            underlying="SONACOMS",
            strike=840.0,
            option_type="CE",
            expiry=exp_dt,
            last_price=7.80,
            volume=1040000,
            oi=830000,
            oi_change=-45000,  # Heavy unwinding
            pchange=28.5,
            bid=7.70,
            ask=7.90,
        ),
    ]

    mock_tp = TradePlan(
        symbol="SONACOMS",
        direction="BUY",
        timeframe="INTRADAY",
        entry_price=835.0,
        invalidation_stop=827.0,
        stop_distance_pts=8.0,
        stop_distance_pct=0.96,
        sl_rationale="Dynamic ATR stop",
        target_1=842.0,
        t1_distance_pts=7.0,
        t1_distance_pct=0.84,
        rr_t1=0.88,
        t1_rationale="Supply barrier",
        target_2=850.0,
        t2_distance_pts=15.0,
        t2_distance_pct=1.80,
        rr_t2=1.88,
        t2_rationale="Expansion target",
        is_asymmetry_viable=False,
        asymmetry_verdict="OPPOSING_ZONE_COLLISION_REJECTED",
        asymmetry_note="Supply OB collision test",
        atr_points=10.0,
        velocity_pts_per_bar=2.0,
        expected_bars_t1=3,
        expected_bars_t2=6,
        eta_t1_minutes=15,
        eta_t2_minutes=30,
        eta_t1_str="~15 mins",
        eta_t2_str="~30 mins",
        session_overrun_risk=False,
        session_clock_note="Normal",
        options_recommended_structure="NAKED_OPTION",
        estimated_theta_drag_pts=0.2,
        theta_drag_pct_of_gain=2.5,
        structure_advice="Direct call purchase",
    )

    with patch("engine.trade_plan.calculate_trade_plan", return_value=mock_tp):
        alerts = detect_gamma_blast("SONACOMS", spot, contracts, now_dt=now_dt)

    assert len(alerts) >= 1
    alert = alerts[0]
    assert alert.symbol == "SONACOMS"
    assert (
        alert.actionable_plan.get("trade_plan", {}).get("asymmetry_verdict")
        == "SMC_MOMENTUM_OVERRIDE"
    )
    assert alert.actionable_plan.get("trade_plan", {}).get("is_asymmetry_viable") is True
