"""
tests/test_gamma_blast_strike_and_sl_calibration.py
──────────────────────────────────────────────────
Regression and institutional invariant tests for:
1. Gamma Blast Index Strike Moneyness & ATM Selection Priority:
   - Deep ITM strikes (e.g. SENSEX 74100 CE @ spot 74476) are strictly blocked.
   - ATM (74500 CE) or Near-ATM (74400 CE) is selected.
2. Structural Spot SL & Safe SL (1m Close) Provenance:
   - AutoAlert always carries structural_spot_sl, underlying_sl, and tactical_sl.
   - Telegram templates render 'Safe SL (Tactical)' and 'Structural SL (Spot)'.
3. Index Sub-ATR Invalidation Stop Protection:
   - calculate_trade_plan enforces calibrated minimum noise floors:
     SENSEX >= 160 pts, BANKNIFTY >= 110 pts, NIFTY >= 50 pts.
4. High-Premium Option SL Volatility Floor:
   - calculate_option_execution_plan prevents narrow sub-ATR stops on SENSEX options.
5. Coiling Stage Execution Discipline:
   - Prohibits blind market entry at CMP in EARLY_WARNING stage.
"""

from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo
import pytest

from engine.detectors.gamma_blast import detect_gamma_blast
from engine.trade_plan import calculate_trade_plan, calculate_option_execution_plan
from bot.alert_templates import render_auto_alert

IST = ZoneInfo("Asia/Kolkata")


class MockOptionItem:
    def __init__(self, strike, opt_type, last_price, oi=25000, oi_change=47900, volume=65000, pchange=15.0):
        self.strike = float(strike)
        self.option_type = opt_type
        self.last_price = float(last_price)
        self.oi = oi
        self.oi_change = oi_change
        self.volume = volume
        self.pchange = pchange
        self.symbol = f"SENSEX26NOV{int(strike)}{opt_type}"
        self.expiry = "2026-11-05"


def test_gamma_blast_blocks_deep_itm_and_prioritizes_atm():
    """
    RCA Guard: SENSEX trading at 74,476.89.
    Chain contains:
    - 74100 CE (376 pts deep ITM, premium 791.60) -> MUST BE BLOCKED
    - 74400 CE (76 pts ITM, premium 540.0) -> ALLOWED (Near-ATM)
    - 74500 CE (23 pts OTM, premium 470.0) -> ALLOWED (ATM, Prioritized)
    - 75200 CE (723 pts far OTM, premium 120.0) -> BLOCKED
    """
    spot = 74476.89
    vwap = 74448.59
    now_dt = datetime(2026, 10, 30, 13, 51, tzinfo=IST)

    chain = [
        MockOptionItem(74100.0, "CE", 791.60, oi=12000, oi_change=47900, volume=70000),  # Deep ITM
        MockOptionItem(74400.0, "CE", 540.0, oi=35000, oi_change=52000, volume=85000),   # 1-strike ITM
        MockOptionItem(74500.0, "CE", 470.0, oi=50000, oi_change=65000, volume=120000),  # ATM
        MockOptionItem(75200.0, "CE", 120.0, oi=10000, oi_change=20000, volume=40000),   # Far OTM
    ]

    alerts = detect_gamma_blast(
        underlying="SENSEX",
        spot=spot,
        chain=chain,
        vwap=vwap,
        now_dt=now_dt,
    )

    assert len(alerts) >= 1, "At least one Gamma Blast alert should be detected"

    # None of the generated alerts should be the 4-strike deep ITM 74100 CE
    alert_strikes = [a.strike for a in alerts]
    assert 74100.0 not in alert_strikes, "74100 CE (deep ITM) must be filtered out by moneyness boundary"
    assert 75200.0 not in alert_strikes, "75200 CE (far OTM) must be filtered out"

    # The highest priority alert must be ATM (74500) or Near-ATM (74400)
    primary_strike = alerts[0].strike
    assert primary_strike in (74500.0, 74400.0), f"Expected ATM (74500) or Near-ATM (74400), got {primary_strike}"


def test_gamma_blast_wires_structural_spot_sl_and_candle_close():
    """
    RCA Guard: Gamma Blast alerts MUST populate structural_spot_sl and underlying_sl,
    and Telegram formatting MUST render 'Safe SL (Tactical)' and 'Structural SL (Spot)'.
    """
    spot = 74476.89
    vwap = 74448.59
    now_dt = datetime(2026, 10, 30, 13, 51, tzinfo=IST)

    chain = [
        MockOptionItem(74500.0, "CE", 470.0, oi=50000, oi_change=65000, volume=120000),
    ]

    alerts = detect_gamma_blast(
        underlying="SENSEX",
        spot=spot,
        chain=chain,
        vwap=vwap,
        now_dt=now_dt,
    )

    assert len(alerts) >= 1
    alert = alerts[0]

    # Invariant: Structural spot SL must be populated
    assert alert.structural_spot_sl is not None, "structural_spot_sl must be set"
    assert alert.underlying_sl is not None, "underlying_sl must be set"
    assert alert.tactical_sl is not None, "tactical_sl must be set"
    assert alert.structural_spot_sl < spot, "Bullish spot SL must be strictly below spot"

    # Format for Telegram and verify two-tier SL lines
    tg_text = render_auto_alert(alert)
    assert "Safe SL (Tactical):" in tg_text, "Must render Safe SL (Tactical) in Telegram template"
    assert "1m close — filters freak wicks" in tg_text, "Must render 1m close filter warning"
    assert "Structural SL (Spot):" in tg_text, "Must render Structural SL (Spot) anchor"


def test_index_minimum_stop_distance_floor_in_trade_plan():
    """
    RCA Guard: calculate_trade_plan MUST enforce calibrated noise floors on indices:
    - SENSEX >= 160.0 pts
    - BANKNIFTY >= 110.0 pts
    - NIFTY >= 50.0 pts
    """
    # 1. SENSEX
    tp_sensex = calculate_trade_plan(
        symbol="SENSEX",
        spot=74500.0,
        direction="BULLISH",
        timeframe="INTRADAY",
    )
    stop_dist_sensex = tp_sensex.entry_price - tp_sensex.invalidation_stop
    assert stop_dist_sensex >= 160.0, (
        f"SENSEX stop distance {stop_dist_sensex} must be >= 160.0 to prevent sub-ATR noise traps"
    )

    # 2. BANKNIFTY
    tp_bn = calculate_trade_plan(
        symbol="BANKNIFTY",
        spot=52000.0,
        direction="BULLISH",
        timeframe="INTRADAY",
    )
    stop_dist_bn = tp_bn.entry_price - tp_bn.invalidation_stop
    assert stop_dist_bn >= 110.0, (
        f"BANKNIFTY stop distance {stop_dist_bn} must be >= 110.0"
    )

    # 3. NIFTY
    tp_nifty = calculate_trade_plan(
        symbol="NIFTY",
        spot=24000.0,
        direction="BULLISH",
        timeframe="INTRADAY",
    )
    stop_dist_nifty = tp_nifty.entry_price - tp_nifty.invalidation_stop
    assert stop_dist_nifty >= 50.0, (
        f"NIFTY stop distance {stop_dist_nifty} must be >= 50.0"
    )


def test_high_premium_index_option_execution_plan_volatility_floor():
    """
    RCA Guard: On SENSEX index options trading at >= 500, calculate_option_execution_plan
    MUST NOT set a fragile sub-ATR stop (e.g. only 92 pts away). It must enforce
    at least 18% option volatility buffer.
    """
    tp = calculate_trade_plan(
        symbol="SENSEX",
        spot=74476.89,
        direction="BULLISH",
        timeframe="INTRADAY",
    )

    opt_res = calculate_option_execution_plan(
        trade_plan=tp,
        option_type="CE",
        strike=74500.0,
        expiry="2026-11-05",
        option_ltp=791.60,
        lot_size=20,
        spot=74476.89,
        contract_symbol="SENSEX26NOV74500CE",
    )

    sl_prem = opt_res["sl_premium"]
    risk_pts = 791.60 - sl_prem

    # Minimum risk pts must be at least 18% of 791.60 = 142.5 pts
    assert risk_pts >= 140.0, (
        f"Expected at least 140.0 pts buffer on ₹791.60 SENSEX option, got {risk_pts:.1f} pts (SL={sl_prem})"
    )


def test_coiling_stage_execution_discipline():
    """
    RCA Guard: In EARLY_WARNING (coiling) stage, execution notes must explicitly
    prohibit market entry at CMP and require OTE pullback or stop-limit breakout.
    """
    spot = 74476.89
    vwap = 74448.59
    now_dt = datetime(2026, 10, 30, 13, 51, tzinfo=IST)

    chain = [
        MockOptionItem(74500.0, "CE", 470.0, oi=50000, oi_change=65000, volume=120000),
    ]

    alerts = detect_gamma_blast(
        underlying="SENSEX",
        spot=spot,
        chain=chain,
        vwap=vwap,
        now_dt=now_dt,
    )

    assert len(alerts) >= 1
    alert = alerts[0]
    if alert.stage == "EARLY_WARNING":
        plan = alert.actionable_plan
        assert "COILING DISCIPLINE" in plan.get("execution_notes", "")
        assert "Do NOT buy market at CMP" in plan.get("execution_notes", "")
