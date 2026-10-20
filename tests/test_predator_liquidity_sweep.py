"""
tests/test_predator_liquidity_sweep.py
──────────────────────────────────────
Unit tests verifying the Predator Liquidity Sweep & Order Book Absorption detector.
"""

from datetime import date, datetime, timedelta
import pandas as pd

from engine.detectors.liquidity_sweep import detect_predator_liquidity_sweep
from engine.alert_model import AutoAlert


def _build_sweep_df(
    sweep_type: str = "SPRING",
    ref_high: float = 25000.0,
    ref_low: float = 24800.0,
) -> pd.DataFrame:
    base = datetime(2024, 10, 10, 9, 15)
    rows = []
    # Build 15 base consolidation bars between 24820 and 24980
    for i in range(15):
        t = base + timedelta(minutes=5 * i)
        rows.append(
            {
                "date": t,
                "open": 24900.0,
                "high": 24950.0,
                "low": 24850.0,
                "close": 24910.0,
                "volume": 20000,
            }
        )

    # Prior structural reference bars
    rows[5]["high"] = ref_high
    rows[6]["low"] = ref_low

    if sweep_type == "SPRING":
        # Sweeps ref_low (24800) by piercing down to 24775, rejects with lower wick, closes at 24825
        t_sweep = base + timedelta(minutes=5 * 15)
        rows.append(
            {
                "date": t_sweep,
                "open": 24810.0,
                "high": 24835.0,
                "low": 24775.0,  # Swept low (24800 - 25 = 0.1% sweep)
                "close": 24825.0,  # Closes back above 24800
                "volume": 65000,
            }
        )
    elif sweep_type == "UPTHRUST":
        # Sweeps ref_high (25000) by piercing up to 25025, rejects with upper wick, closes at 24975
        t_sweep = base + timedelta(minutes=5 * 15)
        rows.append(
            {
                "date": t_sweep,
                "open": 24980.0,
                "high": 25025.0,  # Swept high (25000 + 25 = 0.1% sweep)
                "low": 24965.0,
                "close": 24975.0,  # Closes back below 25000
                "volume": 65000,
            }
        )

    df = pd.DataFrame(rows)
    df.set_index("date", inplace=True)
    return df


def test_predator_bullish_spring():
    """Verify that a false breakdown below support with rejection wick generates a Bullish Predator alert."""
    df = _build_sweep_df("SPRING", ref_high=25000.0, ref_low=24800.0)
    d = date(2024, 10, 10)

    alert = detect_predator_liquidity_sweep(
        symbol="NSE:NIFTY",
        df=df,
        ltp=24825.0,
        session_date=d,
        obi_50=0.18,  # Positive bid absorption
        pdh=25000.0,
        pdl=24800.0,
    )

    assert alert is not None
    assert isinstance(alert, AutoAlert)
    assert alert.direction == "BULLISH"
    assert "PREDATOR_SWEEP" in alert.alert_type
    assert alert.trigger_level == 24825.0
    assert alert.stop_loss < 24775.0  # SL below sweep wick
    assert alert.target_level > 24825.0
    assert alert.alert_id.startswith("aa-predator-sweep-nifty")


def test_predator_bearish_upthrust():
    """Verify that a false breakout above resistance with rejection wick generates a Bearish Predator alert."""
    df = _build_sweep_df("UPTHRUST", ref_high=25000.0, ref_low=24800.0)
    d = date(2024, 10, 10)

    alert = detect_predator_liquidity_sweep(
        symbol="NSE:BANKNIFTY",
        df=df,
        ltp=24975.0,
        session_date=d,
        obi_50=-0.22,  # Negative ask absorption
        pdh=25000.0,
        pdl=24800.0,
    )

    assert alert is not None
    assert isinstance(alert, AutoAlert)
    assert alert.direction == "BEARISH"
    assert alert.trigger_level == 24975.0
    assert alert.stop_loss > 25025.0  # SL above sweep wick
    assert alert.target_level < 24975.0
    assert alert.alert_id.startswith("aa-predator-sweep-banknifty")


def test_predator_opposing_obi_veto():
    """Verify that if order book imbalance heavily opposes the reversal, the alert is suppressed."""
    df = _build_sweep_df("SPRING", ref_high=25000.0, ref_low=24800.0)
    d = date(2024, 10, 10)

    # Spring setup, but order book has heavy sell pressure (OBI = -0.45)
    alert = detect_predator_liquidity_sweep(
        symbol="NSE:NIFTY",
        df=df,
        ltp=24825.0,
        session_date=d,
        obi_50=-0.45,  # Heavy opposing sell wall
        pdh=25000.0,
        pdl=24800.0,
    )

    assert alert is None
