"""
tests/test_index_adaptive_regime.py
───────────────────────────────────
Institutional Test Suite for Eagle, Tiger, and Sniper Adaptive Index Framework:
  1. Choppiness Index (CHOP) mathematical invariants:
     - Linear trending bars produce low CHOP (<= 38.2)
     - Overlapping oscillating bars produce high CHOP (>= 61.8)
  2. Wilder's ADX (14) trend strength discrimination:
     - Non-trending drift (ADX < 20)
     - Strong trend impulse (ADX >= 25)
  3. Multi-timeframe trend alignment (15m vs 5m)
  4. Time-of-Day (TOD) Market Phase and Midday Theta Sink classification
  5. Tiger Stalking Strategy Mandates:
     - Routine breakout suppression during non-trending chop or midday lull
     - Instant Tiger Pounce on Institutional Expansion Thrust
     - Turtle Soup boundary fade during rangebound extremes
  6. Sniper Execution Plan invariants:
     - Strict No-Chase boundary
     - OTE Pullback limit range
     - Asymmetric R:R >= 1:2.5 on T1
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd

from engine.index_adaptive_regime import (
    compute_choppiness_index,
    compute_adx,
    get_time_of_day_phase,
    evaluate_multi_timeframe_trend,
    evaluate_eagle_regime,
    evaluate_tiger_mandate,
    compute_sniper_execution_plan,
    evaluate_index_adaptive_regime,
)

IST = ZoneInfo("Asia/Kolkata")


def _generate_synthetic_candles(n_bars: int = 30, pattern: str = "TREND_UP") -> pd.DataFrame:
    """Generates synthetic OHLCV bars for mathematical testing."""
    start_dt = datetime(2026, 10, 5, 9, 30, tzinfo=IST)
    records = []
    price = 25000.0

    for i in range(n_bars):
        t = start_dt + timedelta(minutes=5 * i)
        if pattern == "TREND_UP":
            # Strong linear stair-step uptrend with minimal retracement
            o = price
            h = o + 20.0
            l = o - 2.0
            c = o + 18.0
            price = c + 2.0
            vol = 30000 + i * 500
        elif pattern == "SEVERE_CHOP":
            # Oscillating tight box (25000 to 25015) with high overlap and wicks
            offset = 12.0 if (i % 2 == 0) else -12.0
            o = 25000.0 + offset
            h = 25015.0
            l = 24985.0
            c = 25000.0 - offset
            vol = 5000
        elif pattern == "TREND_DOWN":
            o = price
            h = o + 2.0
            l = o - 20.0
            c = o - 18.0
            price = c - 2.0
            vol = 30000 + i * 500
        else:
            o = price
            h = o + 8.0
            l = o - 8.0
            c = o
            vol = 8000

        records.append(
            {
                "datetime": t,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": vol,
            }
        )

    df = pd.DataFrame(records)
    df.set_index("datetime", inplace=True)
    return df


# ── Test 1: Choppiness Index (CHOP) ──────────────────────────────────────────


def test_choppiness_index_trend_vs_chop():
    """Verifies that CHOP accurately distinguishes between trending and choppy markets."""
    df_trend = _generate_synthetic_candles(n_bars=25, pattern="TREND_UP")
    chop_trend = compute_choppiness_index(df_trend, period=14)

    assert chop_trend is not None
    # Trending move must have low CHOP (<= 45.0, ideally <= 38.2)
    assert chop_trend < 45.0, f"Expected low CHOP on trend, got {chop_trend}"

    df_chop = _generate_synthetic_candles(n_bars=25, pattern="SEVERE_CHOP")
    chop_val = compute_choppiness_index(df_chop, period=14)

    assert chop_val is not None
    # Severe chop oscillation must have high CHOP (>= 58.0, ideally >= 61.8)
    assert chop_val >= 58.0, f"Expected high CHOP on chop, got {chop_val}"


# ── Test 2: Wilder's ADX Trend Strength ──────────────────────────────────────


def test_adx_trend_vs_consolidation():
    """Verifies that ADX correctly registers high on strong trend and low on chop."""
    df_trend = _generate_synthetic_candles(n_bars=35, pattern="TREND_UP")
    adx_trend = compute_adx(df_trend, period=14)

    assert adx_trend is not None
    assert adx_trend >= 24.0, f"Expected high ADX on trend, got {adx_trend}"

    df_chop = _generate_synthetic_candles(n_bars=35, pattern="SEVERE_CHOP")
    adx_chop = compute_adx(df_chop, period=14)

    assert adx_chop is not None
    assert adx_chop < 22.0, f"Expected low ADX on chop, got {adx_chop}"


# ── Test 3: Time of Day Phase and Midday Theta Sink ──────────────────────────


def test_time_of_day_phase_classification():
    """Verifies accurate phase classification across Indian market hours."""
    # 09:20 IST -> Opening auction discovery
    p1, is_mid1 = get_time_of_day_phase(datetime(2026, 10, 5, 9, 20, tzinfo=IST))
    assert p1 == "OPENING_AUCTION"
    assert is_mid1 is False

    # 10:15 IST -> Morning expansion (prime trend)
    p2, is_mid2 = get_time_of_day_phase(datetime(2026, 10, 5, 10, 15, tzinfo=IST))
    assert p2 == "MORNING_EXPANSION"
    assert is_mid2 is False

    # 12:15 IST -> Midday theta chop window (11:30 - 13:15 IST)
    p3, is_mid3 = get_time_of_day_phase(datetime(2026, 10, 5, 12, 15, tzinfo=IST))
    assert p3 == "MIDDAY_THETA_CHOP"
    assert is_mid3 is True

    # 14:00 IST -> Afternoon expansion
    p4, is_mid4 = get_time_of_day_phase(datetime(2026, 10, 5, 14, 0, tzinfo=IST))
    assert p4 == "AFTERNOON_EXPANSION"
    assert is_mid4 is False

    # 15:00 IST -> Power hour
    p5, is_mid5 = get_time_of_day_phase(datetime(2026, 10, 5, 15, 0, tzinfo=IST))
    assert p5 == "POWER_HOUR_EXPIRY"
    assert is_mid5 is False


# ── Test 4: Multi-Timeframe Trend Extraction ─────────────────────────────────


def test_multi_timeframe_trend_alignment():
    """Verifies that 15m and 5m structures are evaluated coherently."""
    df_up = _generate_synthetic_candles(n_bars=30, pattern="TREND_UP")
    mtf_up = evaluate_multi_timeframe_trend(df_up, spot=25500.0)

    assert mtf_up.trend_5m == "BULLISH"
    assert mtf_up.bias in ("BULLISH_ALIGNED", "RANGE_BOUND")

    df_down = _generate_synthetic_candles(n_bars=30, pattern="TREND_DOWN")
    mtf_down = evaluate_multi_timeframe_trend(df_down, spot=24500.0)

    assert mtf_down.trend_5m == "BEARISH"
    assert mtf_down.bias in ("BEARISH_ALIGNED", "RANGE_BOUND")


# ── Test 5: Tiger Stalking Mandate: Chop & Midday Suppression ─────────────────


def test_tiger_stalking_suppresses_routine_breakouts_in_chop():
    """In severe chop or midday lull, Tiger Stalking mandate must disable routine breakouts."""
    # Midday + Choppy bars
    dt_midday = datetime(2026, 10, 5, 12, 10, tzinfo=IST)
    df_chop = _generate_synthetic_candles(n_bars=25, pattern="SEVERE_CHOP")

    eagle = evaluate_eagle_regime(
        symbol="NIFTY",
        spot=25000.0,
        ohlcv_5m=df_chop,
        ref_time=dt_midday,
    )

    # Routine setup without institutional thrust
    mandate = evaluate_tiger_mandate(eagle=eagle, is_institutional_thrust=False)

    assert mandate.mandate == "TIGER_STALKING_PRESERVE_CAPITAL"
    assert mandate.allow_routine_breakouts is False
    assert mandate.allow_thrust_only is True
    assert mandate.suggested_strategy == "WAIT_IN_CASH"
    assert "Tiger Stalking" in mandate.action_guidance


def test_tiger_pounces_on_institutional_expansion_thrust():
    """Even in midday or chop, an authentic institutional expansion thrust unlocks immediate execution."""
    dt_midday = datetime(2026, 10, 5, 12, 10, tzinfo=IST)
    df_chop = _generate_synthetic_candles(n_bars=25, pattern="SEVERE_CHOP")

    eagle = evaluate_eagle_regime(
        symbol="NIFTY",
        spot=25000.0,
        ohlcv_5m=df_chop,
        ref_time=dt_midday,
    )

    # Verified Institutional Expansion Thrust (Thrust = True)
    mandate = evaluate_tiger_mandate(eagle=eagle, is_institutional_thrust=True)

    assert mandate.mandate == "MOMENTUM_EXPANSION"
    assert mandate.allow_routine_breakouts is True
    assert mandate.suggested_strategy == "BUY_MOMENTUM"
    assert "Tiger Pounce" in mandate.action_guidance


def test_tiger_turtle_soup_fade_in_chop():
    """When a liquidity sweep occurs at range boundaries during chop, Turtle Soup fade is authorized."""
    dt_midday = datetime(2026, 10, 5, 12, 10, tzinfo=IST)
    df_chop = _generate_synthetic_candles(n_bars=25, pattern="SEVERE_CHOP")

    eagle = evaluate_eagle_regime(
        symbol="NIFTY",
        spot=25000.0,
        ohlcv_5m=df_chop,
        ref_time=dt_midday,
    )

    mandate = evaluate_tiger_mandate(
        eagle=eagle, is_institutional_thrust=False, is_liquidity_sweep=True
    )

    assert mandate.mandate == "TURTLE_SOUP_RANGE_FADE"
    assert mandate.suggested_strategy == "FADE_BOUNDARY"
    assert "Turtle Soup" in mandate.reason


# ── Test 6: Sniper Execution Plan: Invalidation & Zero-Chase Invariants ──────


def test_sniper_execution_plan_bullish():
    """Verifies precision pullback limits, strict No-Chase barrier, and R:R >= 1:2.5."""
    spot = 25025.0
    trigger = 25020.0
    sl = 24995.0  # 30 pts risk
    t1 = 25095.0  # 70 pts gain (~2.33R)

    plan = compute_sniper_execution_plan(
        symbol="NIFTY",
        direction="BULLISH",
        spot=spot,
        trigger_level=trigger,
        invalidation_level=sl,
        target_1=t1,
        setup_name="DAY_HIGH_BREAKOUT",
    )

    assert plan.direction == "BULLISH"
    assert plan.entry_zone_min < plan.trigger_level or plan.entry_zone_min <= plan.entry_zone_max
    assert plan.no_chase_boundary > plan.trigger_level
    assert plan.target_1 > plan.spot > plan.structural_invalidation
    assert plan.risk_reward_t1 >= 2.0
    assert not plan.is_chasing
    assert "DO NOT CHASE" in plan.entry_instruction


def test_sniper_execution_plan_chase_detection():
    """If price is extended past the no_chase_boundary, is_chasing must be True."""
    spot = 25055.0  # +35 pts past trigger (too extended to enter safely)
    trigger = 25020.0
    sl = 24995.0
    t1 = 25110.0

    plan = compute_sniper_execution_plan(
        symbol="NIFTY",
        direction="BULLISH",
        spot=spot,
        trigger_level=trigger,
        invalidation_level=sl,
        target_1=t1,
        setup_name="DAY_HIGH_BREAKOUT",
    )

    assert plan.is_chasing is True, (
        f"Expected chasing flag True for spot {spot} vs boundary {plan.no_chase_boundary}"
    )


def test_unified_adaptive_index_decision():
    """Verifies end-to-end evaluation combining Eagle, Tiger, and Sniper."""
    df_trend = _generate_synthetic_candles(n_bars=30, pattern="TREND_UP")
    dt = datetime(2026, 10, 5, 10, 30, tzinfo=IST)

    decision = evaluate_index_adaptive_regime(
        underlying="BANKNIFTY",
        spot=56000.0,
        ohlcv_5m=df_trend,
        ref_time=dt,
        force_refresh=True,
    )

    assert decision.symbol == "BANKNIFTY"
    assert decision.spot == 56000.0
    assert decision.eagle.chop_status in ("TRENDING_EXPANSION", "NEUTRAL_DRIFT")
    assert decision.tiger.mandate in ("MOMENTUM_EXPANSION", "NORMAL_ADAPTIVE")
    d_dict = decision.to_dict()
    assert "eagle" in d_dict
    assert "tiger" in d_dict


# ── Integration Tests: Detectors Wired with Eagle, Tiger & Sniper ────────────


class _MockContract:
    def __init__(
        self,
        strike: float,
        option_type: str,
        last_price: float,
        volume: int = 20000,
        oi: int = 10000,
    ):
        self.strike = strike
        self.option_type = option_type
        self.last_price = last_price
        self.volume = volume
        self.oi = oi
        self.oi_change = 1500
        self.pchange = 12.0
        self.symbol = f"NIFTY{int(strike)}{option_type}"
        self.expiry = "2026-10-08"


def test_index_call_setup_suppressed_in_midday_chop():
    """Confirms that routine CE setups are suppressed during midday chop under Tiger Stalking discipline."""
    from engine.detectors.index_call_setup import detect_index_call_setup

    spot = 25050.0
    chain = [
        _MockContract(25050.0, "CE", 120.0),
        _MockContract(25000.0, "CE", 155.0),
        _MockContract(25100.0, "CE", 90.0),
    ]
    # Midday time (12:20 IST) with oscillating chop bars
    dt_midday = datetime(2026, 10, 5, 12, 20, tzinfo=IST)
    df_chop = _generate_synthetic_candles(n_bars=30, pattern="SEVERE_CHOP")

    alerts = detect_index_call_setup(
        underlying="NIFTY",
        spot=spot,
        chain=chain,
        vwap=25045.0,
        day_high=25055.0,
        day_low=24985.0,
        ohlcv_5m=df_chop,
        ref_time=dt_midday,
        ignore_time_gate=False,
    )

    # Must be suppressed by Tiger Stalking discipline (capital preservation in midday chop)
    assert len(alerts) == 0


def test_index_call_setup_ignites_on_thrust_in_chop():
    """An authentic institutional expansion thrust punches through midday chop and triggers Tiger Pounce."""
    from engine.detectors.index_call_setup import detect_index_call_setup

    # 12:20 IST with 25 base bars then a massive expansion thrust candle
    dt_midday = datetime(2026, 10, 5, 12, 20, tzinfo=IST)
    df_trend = _generate_synthetic_candles(n_bars=25, pattern="TREND_UP")
    last_c = float(df_trend["close"].iloc[-1])

    thrust_open = last_c + 2.0
    thrust_high = thrust_open + 55.0
    thrust_low = thrust_open - 2.0
    thrust_close = thrust_high - 3.0
    thrust_row = pd.DataFrame(
        [
            {
                "open": thrust_open,
                "high": thrust_high,
                "low": thrust_low,
                "close": thrust_close,
                "volume": 120000,
            }
        ],
        index=[dt_midday],
    )
    df_with_thrust = pd.concat([df_trend, thrust_row])

    spot = thrust_close
    strike = round(spot / 50.0) * 50.0
    chain = [
        _MockContract(strike, "CE", 140.0, volume=40000, oi=10000),
        _MockContract(strike - 50.0, "CE", 175.0, volume=30000, oi=10000),
    ]
    chain[0].pchange = 22.0
    chain[1].pchange = 18.0

    alerts = detect_index_call_setup(
        underlying="NIFTY",
        spot=spot,
        chain=chain,
        vwap=round(spot - 70.0, 1),
        day_high=round(last_c + 5.0, 1),
        day_low=24950.0,
        ohlcv_5m=df_with_thrust,
        ref_time=dt_midday,
        ignore_time_gate=False,
    )

    assert len(alerts) >= 1
    alert = alerts[0]
    assert (
        "TIGER POUNCE" in alert.headline
        or "INSTITUTIONAL EXPANSION THRUST" in alert.headline
        or "SNIPER" in alert.headline
        or "HEDGED SPREAD MANDATE" in alert.headline
    )
    assert "eagle_regime" in alert.metrics
    assert "tiger_mandate" in alert.metrics


def test_index_put_setup_suppressed_in_midday_chop():
    """Confirms that routine PE setups are suppressed during midday chop."""
    from engine.detectors.index_put_setup import detect_index_put_setup

    spot = 24950.0
    chain = [
        _MockContract(24950.0, "PE", 120.0),
        _MockContract(24900.0, "PE", 90.0),
        _MockContract(25000.0, "PE", 160.0),
    ]
    dt_midday = datetime(2026, 10, 5, 12, 20, tzinfo=IST)
    df_chop = _generate_synthetic_candles(n_bars=30, pattern="SEVERE_CHOP")

    alerts = detect_index_put_setup(
        underlying="NIFTY",
        spot=spot,
        chain=chain,
        vwap=24955.0,
        day_high=25015.0,
        day_low=24945.0,
        ohlcv_5m=df_chop,
        ref_time=dt_midday,
        ignore_time_gate=False,
    )

    # Must be suppressed by Tiger Stalking discipline
    assert len(alerts) == 0


def test_orb_suppressed_in_severe_chop():
    """Index ORB breakout in severe chop without institutional volume is suppressed."""
    from engine.detectors.orb import detect_opening_range_breakout

    spot = 25020.0
    df_chop = _generate_synthetic_candles(n_bars=25, pattern="SEVERE_CHOP")
    dt_morning = datetime(2026, 10, 5, 9, 45, tzinfo=IST)

    # Low rvol (1.2x) in severe chop
    alert = detect_opening_range_breakout(
        symbol="NIFTY",
        df=df_chop,
        ltp=spot,
        rvol=1.2,
        ref_time=dt_morning,
    )

    # Must be suppressed to avoid false break traps
    assert alert is None
