# -*- coding: utf-8 -*-
"""
tests/test_fractal_entry_coordinator.py
───────────────────────────────────────
Deterministic unit test suite for the Dual-Timeframe Fractal Inception Engine.
"""

from __future__ import annotations

import pandas as pd

from engine.fractal_entry_coordinator import coordinate_fractal_entry


def _create_ltf_candles(
    sweep_type: str = "BULLISH_SWEEP",
    has_choch: bool = True,
    high_volume: bool = False,
) -> pd.DataFrame:
    """Creates deterministic lower-timeframe bars testing sweeps and displacements."""
    if sweep_type == "BEARISH_SWEEP":
        bars = [
            {"open": 24060.0, "high": 24075.0, "low": 24055.0, "close": 24070.0, "volume": 1000.0},
            {"open": 24070.0, "high": 24085.0, "low": 24065.0, "close": 24080.0, "volume": 1000.0},
            # Sweeps high to 24110 (above 24100 zone), closes at 24085 with long upper wick
            {"open": 24080.0, "high": 24110.0, "low": 24075.0, "close": 24085.0, "volume": 1200.0},
            # Prior bar before displacement
            {"open": 24085.0, "high": 24095.0, "low": 24075.0, "close": 24080.0, "volume": 1000.0},
        ]
        vol = 2500.0 if high_volume else 1000.0
        if has_choch:
            # Bear bar closing below prior low (24075) at 24050
            bars.append(
                {"open": 24080.0, "high": 24082.0, "low": 24045.0, "close": 24050.0, "volume": vol}
            )
        else:
            bars.append(
                {"open": 24080.0, "high": 24088.0, "low": 24072.0, "close": 24078.0, "volume": vol}
            )
        return pd.DataFrame(bars)

    # Bullish scenario
    bars = [
        {"open": 24050.0, "high": 24060.0, "low": 24035.0, "close": 24040.0, "volume": 1000.0},
        {"open": 24040.0, "high": 24045.0, "low": 24020.0, "close": 24025.0, "volume": 1000.0},
        # Sweeps low to 23990 (below 24000 zone), closes at 24015 with long lower wick
        {"open": 24020.0, "high": 24025.0, "low": 23990.0, "close": 24015.0, "volume": 1200.0},
        # Prior bar before trigger
        {"open": 24015.0, "high": 24030.0, "low": 24010.0, "close": 24025.0, "volume": 1000.0},
    ]

    vol = 2500.0 if high_volume else 1000.0
    if has_choch:
        # Strong bull bar closing above prior high (24030) at 24055
        bars.append(
            {"open": 24020.0, "high": 24060.0, "low": 24018.0, "close": 24055.0, "volume": vol}
        )
    else:
        bars.append(
            {"open": 24025.0, "high": 24035.0, "low": 24020.0, "close": 24028.0, "volume": vol}
        )

    return pd.DataFrame(bars)


def test_fractal_entry_bullish_sweep_and_choch():
    df_ltf = _create_ltf_candles(sweep_type="BULLISH_SWEEP", has_choch=True, high_volume=False)

    blueprint = coordinate_fractal_entry(
        symbol="NIFTY",
        direction="BULLISH",
        htf_zone=(24040.0, 24000.0),  # Zone 24000 - 24040
        htf_target=24300.0,  # Target 24300
        df_ltf=df_ltf,
        ltp=24055.0,
    )

    assert blueprint.is_confirmed is True
    assert blueprint.has_micro_sweep is True
    assert blueprint.has_micro_choch is True
    assert blueprint.entry_type == "LIMIT_OTE"
    # Stop loss must be below the micro sweep level (23990)
    assert blueprint.stop_loss < 23990.0
    # Entry price must be inside the impulse leg
    assert blueprint.entry_price > blueprint.stop_loss
    # Structural R:R must be high (> 4.0) because target is 24300
    assert blueprint.risk_reward_ratio >= 4.0
    assert "Target_1 (+2.0R)" in blueprint.scale_out_plan


def test_fractal_entry_fast_impulse_fvg():
    # When volume is high (RVOL >= 2.0x), entry switches to LIMIT_FVG_50 (Consequent Encroachment)
    df_ltf = _create_ltf_candles(sweep_type="BULLISH_SWEEP", has_choch=True, high_volume=True)

    blueprint = coordinate_fractal_entry(
        symbol="NIFTY",
        direction="BULLISH",
        htf_zone=(24040.0, 24000.0),
        htf_target=24300.0,
        df_ltf=df_ltf,
        ltp=24055.0,
    )

    assert blueprint.is_confirmed is True
    assert blueprint.entry_type == "LIMIT_FVG_50"
    assert blueprint.risk_reward_ratio >= 4.0


def test_fractal_entry_bearish_sweep_and_choch():
    df_ltf = _create_ltf_candles(sweep_type="BEARISH_SWEEP", has_choch=True, high_volume=False)

    blueprint = coordinate_fractal_entry(
        symbol="NIFTY",
        direction="BEARISH",
        htf_zone=(24100.0, 24060.0),
        htf_target=23800.0,
        df_ltf=df_ltf,
        ltp=24055.0,
    )

    assert blueprint.is_confirmed is True
    assert blueprint.has_micro_sweep is True
    assert blueprint.has_micro_choch is True
    assert blueprint.entry_type == "LIMIT_OTE"
    # Stop loss must be above the micro sweep high (24110)
    assert blueprint.stop_loss > 24110.0
    assert blueprint.entry_price < blueprint.stop_loss
    assert blueprint.risk_reward_ratio >= 4.0


def test_fractal_entry_fallback_when_ltf_missing():
    blueprint = coordinate_fractal_entry(
        symbol="NIFTY",
        direction="BULLISH",
        htf_zone=(24040.0, 24000.0),
        htf_target=24300.0,
        df_ltf=None,
        ltp=24020.0,
    )

    assert blueprint.is_confirmed is False
    assert blueprint.entry_type == "UNCONFIRMED_STALK"
    assert blueprint.entry_price == 24020.0  # Zone midpoint
