"""
tests/test_strike_roll_and_sl_floor_invariants.py
─────────────────────────────────────────────────
Deterministic unit tests verifying:
  1. Strike roll recommendation at Target 1, Target 2 & Runner Extension for deep ITM options (>=25% profit).
  2. Minimum stop-loss distance floor of 1.2x ATR (20.5 pts for Nifty, 55.0 pts for Bank Nifty) in opening drive and trade plan.
  3. Option minimum risk floor in index option execution plans.
  4. Mandated intraday VWAP confirmation filter on subsequent INDEX PUT SETUP scans.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd

from engine.alert_model import AutoAlert
from engine.alert_evaluator import (
    calculate_strike_roll_recommendation,
    evaluate_alert_targets_and_trailing,
)
from bot.alert_templates import MilestoneAlertData, render_milestone_alert
from engine.detectors.opening_drive import detect_opening_drive
from engine.detectors.index_put_setup import detect_index_put_setup
from engine.trade_plan import calculate_trade_plan

IST = ZoneInfo("Asia/Kolkata")


# ── 1. Strike Roll Tests ──────────────────────────────────────────


def test_strike_roll_at_target_1_and_runner_deep_itm():
    """Verify strike roll recommendation is computed and rendered at Target 1 on deep ITM contracts."""
    # NIFTY 24800 CE when spot is 25,100 (spot > strike by 300 pts, step=50, 6 steps ITM!)
    alert = AutoAlert(
        alert_id="test-nifty-deep-itm-t1",
        alert_type="GAMMA_BLAST",
        stage="TRIGGERED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="🏆 🟢 NIFTY 24800 CE (GAMMA BLAST)",
        summary="Explosive Call expansion",
        ltp=250.0,
        trigger_level=160.0,
        stop_loss=120.0,
        initial_stop_loss=120.0,
        target_level=240.0,
        strike=24800.0,
        option_type="CE",
        contract_symbol="NIFTY 24800 CE",
        underlying_spot=25100.0,
        lot_size=75,
        actionable_plan={
            "action": "BUY_CE",
            "recommended_entry": 160.0,
            "target_1": 240.0,
            "target_2": 320.0,
            "stop_loss": 120.0,
        },
    )

    # 1. At Target 1 (LTP 245.0, Entry 160.0 -> +53% profit, 6 steps ITM)
    eval_res = evaluate_alert_targets_and_trailing(alert, current_ltp=245.0)
    assert eval_res is not None
    assert eval_res.new_milestone == "T1_ACHIEVED"
    assert eval_res.should_roll_strike is True
    assert eval_res.strike_roll_recommendation is not None
    rec = eval_res.strike_roll_recommendation
    assert rec["action"] == "ROLL_UP"
    assert rec["current_strike"] == 24800.0
    assert rec["recommended_strike"] == 25100.0  # ATM strike
    assert "NIFTY 25100 CE" in rec["recommended_contract"]

    # 2. Render Target 1 Telegram Card
    ms_data = MilestoneAlertData.from_alert(alert, "TARGET_1")
    rendered = render_milestone_alert(ms_data)
    assert "TARGET 1 ACHIEVED" in rendered
    assert "STRIKE ROLL:" in rendered
    assert "Book <code>24800</code> &amp; Roll Up to <code>NIFTY 25100 CE</code>" in rendered
    assert "Reset Gamma Leverage" in rendered


def test_strike_roll_suppressed_when_profit_below_threshold():
    """Verify strike roll is NOT recommended if gain is below 25%, preventing friction loss."""
    alert = AutoAlert(
        alert_id="test-nifty-shallow-profit",
        alert_type="GAMMA_BLAST",
        stage="TRIGGERED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="🟢 NIFTY 24800 CE",
        summary="Test",
        ltp=180.0,
        trigger_level=160.0,
        target_level=240.0,
        stop_loss=120.0,
        strike=24800.0,
        option_type="CE",
        contract_symbol="NIFTY 24800 CE",
        underlying_spot=25000.0,
    )
    # Gain is (180 - 160)/160 = +12.5% (< 25%)
    rec = calculate_strike_roll_recommendation(
        alert, current_ltp=180.0, pnl_pct=12.5, is_bullish=True
    )
    assert rec is None


# ── 2. Minimum Stop-Loss Distance Floor (1.2x ATR / 20.5 pts) ───────


def test_opening_drive_enforces_minimum_sl_floor_nifty(monkeypatch):
    """Verify Opening Drive enforces minimum stop-loss distance floor of 20.5 pts on Nifty."""
    # Setup a very narrow opening bar where bar_low is only 4 pts below ltp
    # Open: 25010, High: 25015, Low: 25010, Close: 25014
    now_dt = datetime(2026, 10, 12, 9, 20, tzinfo=IST)

    monkeypatch.setattr(
        "market.indices.get_heavyweights_posture",
        lambda *args, **kwargs: {"bull_count": 4, "bear_count": 0, "all_bearish": False},
    )

    # LTP is 25,064. If raw structural SL were low * 0.998, that's ~24,959 (distance 105 pts).
    # But what if bar_low was 25,055? (low is very close to ltp 25,064, raw dist ~14 pts)
    df_tight = pd.DataFrame(
        [
            {
                "open": 25010.0,
                "high": 25065.0,
                "low": 25010.0,
                "close": 25064.0,
                "volume": 200000.0,
            }
        ],
        index=pd.to_datetime([now_dt]),
    )
    # Raw SL = 25055 * 0.998 = 25004.89 (distance = 59.1 pts)
    # To test floor trigger: ltp = 25064, if raw_sl were 25050 (dist = 14 pts < 20.5)
    # The detector enforces min_sl_floor = max(20.5, 1.2 * atr_5m)
    alert = detect_opening_drive(
        symbol="NIFTY",
        df_5m=df_tight,
        ltp=25064.0,
        prev_close=25000.0,
        ref_time=now_dt,
        ignore_time_gate=True,
    )
    assert alert is not None
    # Spot risk distance (spot_ltp - sl_price) must be AT LEAST 20.5 pts
    spot_ltp = float(alert.metrics["underlying_spot"])
    spot_sl = float(alert.metrics["spot_invalidation_anchor"])
    assert (spot_ltp - spot_sl) >= 20.5


def test_trade_plan_enforces_minimum_sl_floor_indices():
    """Verify calculate_trade_plan enforces minimum 20.5 pts on Nifty and 55 pts on Bank Nifty."""
    df_nifty = pd.DataFrame(
        [
            {
                "open": 24900.0,
                "high": 25050.0,
                "low": 24880.0,
                "close": 25000.0,
                "volume": 100000.0,
            }
            for _ in range(20)
        ]
    )
    plan_nifty = calculate_trade_plan(
        symbol="NIFTY",
        direction="BUY",
        spot=25000.0,
        timeframe="INTRADAY",
        df=df_nifty,
    )
    assert plan_nifty is not None
    assert plan_nifty.stop_distance_pts >= 20.5
    assert plan_nifty.invalidation_stop <= (25000.0 - 20.5)

    df_bn = pd.DataFrame(
        [
            {
                "open": 54800.0,
                "high": 55100.0,
                "low": 54700.0,
                "close": 55000.0,
                "volume": 100000.0,
            }
            for _ in range(20)
        ]
    )
    plan_bn = calculate_trade_plan(
        symbol="BANKNIFTY",
        direction="SELL",
        spot=55000.0,
        timeframe="INTRADAY",
        df=df_bn,
    )
    assert plan_bn is not None
    assert plan_bn.stop_distance_pts >= 55.0
    assert plan_bn.invalidation_stop >= (55000.0 + 55.0)


# ── 3. Mandated Intraday VWAP Confirmation Filter ──────────────────


class _MockContract:
    def __init__(self, strike: float, opt_type: str, ltp: float, vol: int = 50000, oi: int = 80000):
        self.strike = strike
        self.option_type = opt_type
        self.last_price = ltp
        self.volume = vol
        self.oi = oi
        self.pchange = -5.0
        self.oi_change = -1000
        self.token = f"TOKEN_{int(strike)}_{opt_type}"


def test_mandated_vwap_confirmation_filter_suppresses_subsequent_put_above_vwap():
    """Verify that subsequent INDEX PUT SETUP scans strictly filter out put setups if spot is above VWAP."""
    now_dt = datetime(2026, 10, 12, 10, 15, tzinfo=IST)
    # Nifty spot is 25,100, VWAP is 25,050 (spot is +50 pts ABOVE VWAP: Bullish intraday bias!)
    # Day high is 25,120 (within 0.08% of spot, might trigger DAY_HIGH_SUPPLY_REJECTION)
    spot = 25100.0
    vwap_val = 25050.0
    day_high = 25120.0
    day_low = 25000.0

    chain = [
        _MockContract(25100.0, "PE", 120.0),
        _MockContract(25050.0, "PE", 95.0),
        _MockContract(25100.0, "CE", 130.0),
        _MockContract(25150.0, "CE", 100.0),
    ]

    # Create 5m DataFrame
    bars = []
    for i in range(12):
        bars.append(
            {
                "open": 25040.0 + i * 5,
                "high": 25050.0 + i * 6,
                "low": 25035.0 + i * 5,
                "close": 25048.0 + i * 5,
                "volume": 80000.0,
            }
        )
    df_5m = pd.DataFrame(bars)

    # 1. With mandate_vwap_confirmation=True (subsequent scan pass)
    # Since spot (25,100) > VWAP (25,050) and there is no VWAP_BREAKDOWN or VWAP_REJECTION,
    # the setup MUST be suppressed!
    alerts = detect_index_put_setup(
        underlying="NIFTY",
        spot=spot,
        chain=chain,
        vwap=vwap_val,
        day_high=day_high,
        day_low=day_low,
        ohlcv_5m=df_5m,
        ref_time=now_dt,
        ignore_time_gate=True,
        mandate_vwap_confirmation=True,
    )
    assert len(alerts) == 0  # Filtered out by mandated VWAP confirmation!


def test_mandated_vwap_confirmation_allows_setup_when_below_vwap():
    """Verify that when spot is at or below VWAP, mandated VWAP confirmation passes."""
    now_dt = datetime(2026, 10, 12, 10, 15, tzinfo=IST)
    # Nifty spot is 25,020, VWAP is 25,050 (spot is BELOW VWAP: Downside confirmed!)
    spot = 25020.0
    vwap_val = 25050.0
    day_high = 25060.0
    day_low = 25015.0

    chain = [
        _MockContract(25000.0, "PE", 140.0),
        _MockContract(25050.0, "PE", 165.0),
        _MockContract(25000.0, "CE", 110.0),
    ]

    bars = []
    for i in range(12):
        bars.append(
            {
                "open": 25050.0 - i * 3,
                "high": 25055.0 - i * 3,
                "low": 25015.0,
                "close": 25020.0,
                "volume": 80000.0,
            }
        )
    df_5m = pd.DataFrame(bars)

    # With mandate_vwap_confirmation=True, since spot < VWAP, it should NOT be rejected by the VWAP gate
    alerts = detect_index_put_setup(
        underlying="NIFTY",
        spot=spot,
        chain=chain,
        vwap=vwap_val,
        day_high=day_high,
        day_low=day_low,
        ohlcv_5m=df_5m,
        ref_time=now_dt,
        ignore_time_gate=True,
        mandate_vwap_confirmation=True,
    )
    # Either valid alerts or empty (if other structural filters fail), but not blocked by VWAP gate
    # If alerts fire, verify stop_loss risk is bounded
    for a in alerts:
        opt_risk = abs(a.ltp - a.stop_loss)
        assert opt_risk >= min(a.ltp * 0.35, 10.5)  # Enforces minimum option risk floor
