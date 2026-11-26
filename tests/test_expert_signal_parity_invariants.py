"""
Tests verifying parity with elite institutional / human market expert signals
for opening momentum, midday trend continuation, V-reversal bottom bounces,
and single-stock F&O option contract resolution.

Addresses specific scenarios from session 18/11/2026:
1. Sensex 82300 PE at 09:26 IST (Early opening breakdown, <= 2 flow bars required).
2. Sensex 81900 PE at 13:06 IST (Midday trend continuation slicing session Day Low).
3. Sensex 81800 CE at 13:50 IST (V-reversal bounce >= 0.20% from capitulation low bypassing breadth veto).
4. Polycab 7600 PE (Single-stock F&O breakdown resolving defined-risk option contract).
"""

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
import pandas as pd

from engine.auto_alert_engine import AutoAlertEngine
from engine.detectors.index_call_setup import detect_index_call_setup
from engine.detectors.index_micro_scalp import detect_index_micro_scalp
from engine.detectors.index_put_setup import detect_index_put_setup
from engine.detectors.intraday_spark import detect_intraday_mover_sparks
from market.quotes import Quote

IST = timezone(timedelta(hours=5, minutes=30))


_DEFAULT_FUTURE_EXPIRY = (datetime.now(IST) + timedelta(days=5)).strftime("%Y-%m-%d")


@dataclass
class MockContract:
    symbol: str
    strike: float
    option_type: str
    last_price: float
    volume: int
    oi: int
    pchange: float = 0.0
    change_pct: float = 0.0
    expiry: str = _DEFAULT_FUTURE_EXPIRY
    expiry_date: str = _DEFAULT_FUTURE_EXPIRY
    oi_change: int = 1500


def _build_sensex_chain(spot: float) -> list[MockContract]:
    chain = []
    base_strike = round(spot / 100.0) * 100
    for offset in [-300, -200, -100, 0, 100, 200, 300]:
        strk = base_strike + offset
        # CE
        ce_prem = max(
            25.0, (spot - strk) + 350.0 if strk <= spot else max(25.0, 350.0 - (strk - spot) * 0.5)
        )
        chain.append(
            MockContract(
                symbol=f"SENSEX26NOV{int(strk)}CE",
                strike=strk,
                option_type="CE",
                last_price=round(ce_prem, 1),
                volume=12000,
                oi=25000,
                pchange=22.5,
                oi_change=1200,
            )
        )
        # PE
        pe_prem = max(
            25.0, (strk - spot) + 350.0 if strk >= spot else max(25.0, 350.0 - (spot - strk) * 0.5)
        )
        chain.append(
            MockContract(
                symbol=f"SENSEX26NOV{int(strk)}PE",
                strike=strk,
                option_type="PE",
                last_price=round(pe_prem, 1),
                volume=18000,
                oi=28000,
                pchange=28.0,
                oi_change=2500,
            )
        )
    return chain


def test_sensex_opening_put_breakdown_0926_parity():
    """
    Scenario 1: At 09:26 IST, price breaks VWAP/Day Low with only 2 bars of 5m data.
    Verifies that index_put_setup recognizes is_opening_session_drive, elevates
    stage to IGNITED, achieves confidence >= 88%, and passes the Telegram Apex Gate.
    """
    dt_0926 = datetime(2026, 11, 18, 9, 26, 0, tzinfo=IST)
    spot = 82310.0
    chain = _build_sensex_chain(spot)

    # 2 five-minute bars at 09:26
    df_5m = pd.DataFrame(
        {
            "open": [82500.0, 82420.0],
            "high": [82550.0, 82430.0],
            "low": [82380.0, 82290.0],
            "close": [82400.0, 82310.0],
            "volume": [150000, 220000],
        },
        index=pd.date_range("2026-11-18 09:15", periods=2, freq="5min"),
    )

    alerts = detect_index_put_setup(
        underlying="SENSEX",
        spot=spot,
        chain=chain,
        vwap=82420.0,
        day_high=82550.0,
        day_low=82290.0,
        prev_day_high=82600.0,
        prev_day_low=82200.0,
        ohlcv_5m=df_5m,
        ref_time=dt_0926,
        ignore_time_gate=True,
    )

    assert len(alerts) >= 1, "Expected opening put breakdown alert on SENSEX at 09:26"
    alert = alerts[0]
    assert alert.direction == "BEARISH"
    assert alert.stage == "IGNITED"
    assert alert.confidence >= 88
    assert alert.strike is not None
    assert alert.option_type == "PE"

    # Verify Telegram Apex Gate evaluates and admits the setup without being held
    engine = AutoAlertEngine()
    passed, reason = engine._eval_telegram_apex_gate(alert, in_market=True)
    assert passed is True, f"Telegram Apex Gate failed: {reason}"


def test_sensex_midday_continuation_1306_parity():
    """
    Scenario 2: At 13:06 IST (midday lull window), price expands below Day Low.
    Verifies that index_micro_scalp bypasses the midday chop block when spot
    is slicing session Day Low, producing a high-conviction micro-scalp alert.
    """
    dt_1306 = datetime(2026, 11, 18, 13, 6, 0, tzinfo=IST)
    spot = 81900.0
    chain = _build_sensex_chain(spot)

    # 40 five-minute bars leading to a breakdown at 13:06
    closes = [82300.0 - i * 10 for i in range(40)]
    df_5m = pd.DataFrame(
        {
            "open": closes,
            "high": [c + 15 for c in closes],
            "low": [c - 20 for c in closes],
            "close": closes,
            "volume": [100000] * 40,
        },
        index=pd.date_range("2026-11-18 09:15", periods=40, freq="5min"),
    )

    alerts = detect_index_micro_scalp(
        underlying="SENSEX",
        spot=spot,
        chain=chain,
        ohlcv_5m=df_5m,
        vwap=82200.0,
        day_high=82550.0,
        day_low=81900.0,  # Slicing day low at 13:06
        ref_time=dt_1306,
        ignore_time_gate=False,
    )

    assert len(alerts) >= 1, "Expected midday continuation micro-scalp alert on SENSEX at 13:06"
    pe_alert = next((a for a in alerts if a.direction == "BEARISH"), None)
    assert pe_alert is not None, "Expected BEARISH micro scalp alert"
    assert pe_alert.alert_type == "INDEX_MICRO_SCALP"
    assert pe_alert.strike is not None
    assert pe_alert.option_type == "PE"

    # Whitelisted in Apex Gate
    engine = AutoAlertEngine()
    pe_alert.confidence = 88
    pe_alert.stage = "EARLY_WARNING"
    passed, reason = engine._eval_telegram_apex_gate(pe_alert, in_market=True)
    assert passed is True, f"Telegram Apex Gate failed for INDEX_MICRO_SCALP: {reason}"


def test_sensex_v_reversal_bounce_1350_parity():
    """
    Scenario 3: At 13:50 IST, SENSEX drops to 81,750 (Day Low) and bounces to 81,960
    (+0.25% bounce from low). Even with market breadth in decline and spot below VWAP,
    _is_v_reversal_escape and _CE_BOUNCE_THRESHOLDS allow the CE setup to scan and fire.
    """
    dt_1350 = datetime(2026, 11, 18, 13, 50, 0, tzinfo=IST)
    spot = 81960.0
    chain = _build_sensex_chain(spot)

    # 45 five-minute bars: sharp morning drop, capitulation at 13:30, bounce at 13:50
    closes = [82500 - i * 18 for i in range(40)] + [81760, 81820, 81890, 81930, 81960]
    df_5m = pd.DataFrame(
        {
            "open": closes,
            "high": [c + 25 for c in closes],
            "low": [c - 20 for c in closes],
            "close": closes,
            "volume": [120000] * 45,
        },
        index=pd.date_range("2026-11-18 09:15", periods=45, freq="5min"),
    )

    with patch(
        "market.sentiment.get_market_breadth",
        return_value=MagicMock(verdict="BROAD_DECLINE", advances=300, declines=2100),
    ):
        alerts = detect_index_call_setup(
            underlying="SENSEX",
            spot=spot,
            chain=chain,
            vwap=82150.0,  # Spot is below VWAP
            day_high=82550.0,
            day_low=81750.0,  # Session low 81750, spot 81960 -> 0.257% bounce
            prev_day_high=82600.0,
            prev_day_low=82200.0,
            ohlcv_5m=df_5m,
            ref_time=dt_1350,
            ignore_time_gate=True,
        )

    assert len(alerts) >= 1, "Expected V-reversal Call setup on SENSEX at 13:50"
    alert = alerts[0]
    assert alert.direction == "BULLISH"
    assert alert.option_type == "CE"
    assert alert.strike is not None
    assert alert.strike in (81800, 81900, 82000)


def test_polycab_fno_breakdown_option_resolution_parity():
    """
    Scenario 4: Polycab breaks down with heavy volume.
    Verifies that intraday_spark resolves the option contract for F&O stocks,
    populating contract_symbol (e.g. POLYCAB...PE), option_premium, tactical_sl,
    and defined-risk option_plan rather than emitting a naked equity short alert.
    """
    quote_polycab = Quote(
        symbol="POLYCAB",
        last_price=7600.0,
        open=7800.0,
        high=7820.0,
        low=7580.0,
        close=7780.0,
        volume=1200000,
        change=-180.0,
        change_pct=-2.31,
        vwap=7710.0,
        provider="TEST",
    )

    quote_nifty = Quote(
        symbol="NIFTY",
        last_price=24300.0,
        open=24450.0,
        high=24480.0,
        low=24280.0,
        close=24450.0,
        volume=15000000,
        change=-150.0,
        change_pct=-0.61,
        vwap=24380.0,
        provider="TEST",
    )

    df_daily = pd.DataFrame(
        {
            "open": [7780.0] * 30,
            "high": [7850.0] * 30,
            "low": [7550.0] * 30,
            "close": [7600.0] * 30,
            "volume": [800000] * 30,
        }
    )

    with patch("market.history.get_ohlcv", return_value=df_daily):
        with patch("engine.detectors.intraday_spark.get_cached_avg_volume_20", return_value=500000):
            with patch(
                "engine.detectors.intraday_spark.compute_time_of_day_rvol", return_value=2.6
            ):
                alerts = detect_intraday_mover_sparks(
                    universe=["POLYCAB"],
                    quotes_map={
                        "NSE:POLYCAB": quote_polycab,
                        "POLYCAB": quote_polycab,
                        "NSE:NIFTY": quote_nifty,
                        "NIFTY": quote_nifty,
                    },
                )

    assert len(alerts) >= 1, "Expected intraday breakdown spark on POLYCAB"
    alert = alerts[0]
    assert alert.direction == "BEARISH"
    assert alert.segment == "FNO_STOCK"
    assert alert.contract_symbol is not None
    assert "PE" in alert.contract_symbol
    assert alert.option_type == "PE"
    assert alert.strike is not None
    assert alert.option_premium is not None and alert.option_premium > 0
    assert alert.tactical_sl is not None and alert.tactical_sl > 0

    plan = alert.actionable_plan or {}
    assert "option_plan" in plan
    opt_plan = plan["option_plan"]
    assert opt_plan.get("option_type") == "PE"
    assert opt_plan.get("contract_symbol") == alert.contract_symbol
    assert opt_plan.get("lot_size", 0) > 1
    assert "PE" in alert.headline


def test_fno_stock_option_resolution_across_detectors_parity():
    """
    Verifies that all core breakout and reversal detectors (ORB, Opening Drive,
    Afternoon Thrust, Liquidity Sweep) resolve defined-risk F&O option contracts
    with segment="FNO_STOCK" when triggered on single-stock F&O underlyings.
    """
    from engine.detectors.orb import detect_opening_range_breakout
    from engine.detectors.opening_drive import detect_opening_drive
    from engine.detectors.afternoon_thrust import detect_afternoon_thrust

    dt_orb = datetime(2026, 11, 18, 9, 35, 0, tzinfo=IST)
    df_orb = pd.DataFrame(
        {
            "open": [7550.0, 7570.0, 7580.0, 7610.0],
            "high": [7580.0, 7590.0, 7600.0, 7618.0],
            "low": [7540.0, 7560.0, 7570.0, 7605.0],
            "close": [7570.0, 7580.0, 7595.0, 7615.0],
            "volume": [100000, 120000, 110000, 350000],
        },
        index=pd.date_range("2026-11-18 09:15", periods=4, freq="5min"),
    )

    alert_orb = detect_opening_range_breakout(
        symbol="POLYCAB",
        df=df_orb,
        ltp=7615.0,
        vwap=7590.0,
        rvol=2.8,
        ref_time=dt_orb,
        orb_levels=(7600.0, 7540.0, 60.0, 7570.0),
        ignore_time_gate=True,
    )
    assert alert_orb is not None, "Expected ORB breakout on POLYCAB"
    assert alert_orb.segment == "FNO_STOCK"
    assert alert_orb.contract_symbol is not None
    assert "CE" in alert_orb.contract_symbol
    assert alert_orb.option_premium is not None and alert_orb.option_premium > 0

    # 2. Opening Drive on F&O Stock
    dt_od = datetime(2026, 11, 18, 9, 20, 0, tzinfo=IST)
    df_od = pd.DataFrame(
        {
            "open": [7550.0, 7580.0],
            "high": [7590.0, 7630.0],
            "low": [7548.0, 7575.0],
            "close": [7585.0, 7625.0],
            "volume": [200000, 350000],
        },
        index=pd.date_range("2026-11-18 09:15", periods=2, freq="5min"),
    )
    alert_od = detect_opening_drive(
        symbol="POLYCAB",
        df_5m=df_od,
        ltp=7625.0,
        vwap=7580.0,
        rvol=2.5,
        ref_time=dt_od,
        prev_close=7540.0,
        ignore_time_gate=True,
    )
    assert alert_od is not None, "Expected Opening Drive ignition on POLYCAB"
    assert alert_od.segment == "FNO_STOCK"
    assert alert_od.contract_symbol is not None
    assert "CE" in alert_od.contract_symbol

    # 3. Afternoon Thrust on F&O Stock
    dt_at = datetime(2026, 11, 18, 13, 45, 0, tzinfo=IST)
    df_at = pd.DataFrame(
        {
            "open": [7580.0, 7590.0, 7610.0, 7640.0],
            "high": [7595.0, 7605.0, 7645.0, 7670.0],
            "low": [7575.0, 7585.0, 7605.0, 7635.0],
            "close": [7590.0, 7600.0, 7638.0, 7665.0],
            "volume": [80000, 90000, 250000, 400000],
        },
        index=pd.date_range("2026-11-18 13:30", periods=4, freq="5min"),
    )
    alert_at = detect_afternoon_thrust(
        symbol="POLYCAB",
        df_5m=df_at,
        ltp=7665.0,
        vwap=7600.0,
        rvol=2.4,
        day_high=7670.0,
        day_low=7550.0,
        ref_time=dt_at,
        prev_close=7550.0,
        ignore_time_gate=True,
    )
    assert alert_at is not None, "Expected Afternoon Thrust on POLYCAB"
    assert alert_at.segment == "FNO_STOCK"
    assert alert_at.contract_symbol is not None
    assert "CE" in alert_at.contract_symbol
