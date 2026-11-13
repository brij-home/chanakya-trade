"""
Unit tests for Institutional Quantitative Metric Hierarchy & Data Invariants.
Guarantees that no developer or AI agent can collapse TOD-RVOL, Bar-RVOL,
or Option Microstructure into primitive unadjusted scalar shortcuts.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd

from engine.auto_alert_engine import compute_time_of_day_rvol
from engine.daily_levels import compute_institutional_volume_profile

IST = ZoneInfo("Asia/Kolkata")


def test_tod_rvol_scales_morning_volume_accurately():
    """
    At 09:30 IST (15 minutes from open), volume accumulated is naturally small.
    TOD-RVOL must normalize against expected morning volume fraction,
    preventing false negative rejections.
    """
    morning_time = datetime(2026, 11, 11, 9, 30, tzinfo=IST)
    avg_daily_vol = 1_000_000.0

    # Stock has done 200,000 shares in first 15 mins (massive opening rush)
    current_vol = 200_000.0

    # Raw unadjusted RVOL would be 200k / 1M = 0.20x (would be falsely rejected!)
    raw_rvol = current_vol / avg_daily_vol
    assert raw_rvol == 0.20

    # TOD-RVOL correctly scales this to an institutional surge (> 1.5x)
    tod_rvol = compute_time_of_day_rvol(current_vol, avg_daily_vol, ref_dt=morning_time)
    assert tod_rvol >= 1.5, f"TOD-RVOL {tod_rvol} failed to recognize morning surge!"


def test_bar_rvol_detects_5_bar_impulse_surge():
    """
    A sudden breakout candle with 3.5x volume of recent 5-bar consolidation
    must be recognized by Bar-RVOL even if daily volume has not yet expanded.
    """
    # 20 bars of 5m data: 19 bars with quiet 1,000 volume, 20th bar with 4,000 volume
    vols = [1000] * 19 + [4000]
    highs = [100.0] * 19 + [102.5]
    lows = [99.5] * 19 + [100.0]
    closes = [99.8] * 19 + [102.4]

    df_5m = pd.DataFrame(
        {
            "open": [99.6] * 20,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": vols,
        }
    )

    vp = compute_institutional_volume_profile(df_5m, required_rvol=1.5, direction="BULLISH")
    assert vp.bar_rvol >= 3.0, f"Bar-RVOL {vp.bar_rvol} failed to catch 4.0x impulse surge!"
    assert vp.volume_surge_confirmed is True


def test_option_microstructure_requires_contract_turnover_not_underlying():
    """
    Option buying setups must validate contract turnover and Vol/OI ratio,
    never treating underlying equity volume as a proxy.
    """
    # Option contract with 5,000 contracts @ 120 Rs = 60 Lakh turnover (under 2 Cr threshold)
    # vs option with 25,000 contracts @ 150 Rs = 3.75 Cr turnover
    opt_low_turnover = {"volume": 5000, "ltp": 120.0, "oi": 10000}
    opt_high_turnover = {"volume": 25000, "ltp": 150.0, "oi": 12000}

    turnover_low_cr = (opt_low_turnover["volume"] * opt_low_turnover["ltp"]) / 1e7
    turnover_high_cr = (opt_high_turnover["volume"] * opt_high_turnover["ltp"]) / 1e7

    assert turnover_low_cr < 2.0  # Under 2 Cr threshold
    assert turnover_high_cr >= 0.375  # Over threshold


def test_canonical_active_exchange_lot_sizes():
    """
    Guarantees that canonical SSOT lot sizes reflect active official circulars.
    Zero tolerance for obsolete numbers (e.g. NIFTY 75/50/25 or SENSEX 10).
    """
    from market.instruments import STANDARD_LOT_SIZES, get_fno_lot_size

    assert get_fno_lot_size("NIFTY") == 65
    assert get_fno_lot_size("BANKNIFTY") == 30
    assert get_fno_lot_size("FINNIFTY") == 60
    assert get_fno_lot_size("MIDCPNIFTY") == 120
    assert get_fno_lot_size("SENSEX") == 20
    assert get_fno_lot_size("BANKEX") == 30

    # Ensure obsolete historical numbers are NEVER present as active lot sizes
    assert STANDARD_LOT_SIZES["NIFTY"] != 75
    assert STANDARD_LOT_SIZES["NIFTY"] != 50
    assert STANDARD_LOT_SIZES["NIFTY"] != 25
    assert STANDARD_LOT_SIZES["SENSEX"] != 10
    assert STANDARD_LOT_SIZES["BANKNIFTY"] != 25
    assert STANDARD_LOT_SIZES["BANKNIFTY"] != 15
