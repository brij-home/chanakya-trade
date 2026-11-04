import pandas as pd
from engine.detection_context import DetectionContext
from engine.detectors.defined_risk_neutral import detect_defined_risk_neutral
from engine.option_resolver import resolve_option_contract


def _make_range_bound_candles(n: int = 50, center: float = 24500.0) -> pd.DataFrame:
    import numpy as np

    np.random.seed(42)
    closes = [center]
    for _ in range(n - 1):
        delta = np.random.uniform(-15.0, 15.0)
        closes.append(closes[-1] + delta)

    opens = [c - np.random.uniform(-5.0, 5.0) for c in closes]
    highs = [max(o, c) + np.random.uniform(2.0, 10.0) for o, c in zip(opens, closes)]
    lows = [min(o, c) - np.random.uniform(2.0, 10.0) for o, c in zip(opens, closes)]
    vols = [int(np.random.uniform(1000, 5000)) for _ in range(n)]

    return pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": vols,
        }
    )


def test_defined_risk_neutral_attaches_hedged_spread_and_four_legs():
    candles = _make_range_bound_candles(50, center=55452.7)
    ctx = DetectionContext(
        symbol="BANKNIFTY",
        canonical_symbol="BANKNIFTY",
        exchange="NSE",
        segment="FNO_INDEX",
        ltp=55452.7,
        prev_close=55400.0,
        vix=13.0,
        candles_15m=candles,
        option_chain=[
            {"option_type": "PE", "strike": 55300, "oi": 500000},
            {"option_type": "PE", "strike": 55100, "oi": 200000},
            {"option_type": "CE", "strike": 55700, "oi": 600000},
            {"option_type": "CE", "strike": 55900, "oi": 250000},
        ],
    )

    alert = detect_defined_risk_neutral(ctx)
    assert alert is not None
    assert alert.alert_type == "DEFINED_RISK_NEUTRAL"
    assert alert.direction == "NEUTRAL"
    assert alert.derivative_type == "SPREAD"

    # Verify hedged_spread attachment
    assert alert.hedged_spread is not None
    assert alert.hedged_spread["strategy_name"] == "IRON_CONDOR"
    assert len(alert.hedged_spread["legs"]) == 4

    # Verify actionable plan fields
    act = alert.actionable_plan
    assert act["preferred_vehicle"] == "DEFINED_RISK_SPREAD"
    assert act["hedged_spread"] is not None
    assert len(act["hedged_spread"]["legs"]) == 4
    assert act["entry_price"] > 0
    assert act["stop_loss"] > 0
    assert act["target_1"] > 0
    assert act["target_2"] > act["target_1"]
    assert act["target_3"] > act["target_2"]

    # Verify to_dict serialization
    d = alert.to_dict()
    assert d.get("hedged_spread") is not None
    assert len(d["hedged_spread"]["legs"]) == 4


def test_option_resolver_t3_ceiling_bounds_explosive_swing_targets():
    # Spot 55535, large underlying target 59830 (+4295 pts swing)
    plan = resolve_option_contract(
        symbol="BANKNIFTY",
        spot=55535.0,
        direction="BULLISH",
        underlying_sl=54068.99,
        underlying_target=59830.67,
        india_vix=15.82,
    )
    assert plan is not None
    # Entry premium should be bounded
    entry = plan.entry_premium
    assert entry > 0

    # T3 should be bounded by ceiling, not exploding to 7x entry
    assert plan.t3_premium <= round(entry * 3.0, 2)
    assert plan.t3_premium > plan.t2_premium > plan.t1_premium
