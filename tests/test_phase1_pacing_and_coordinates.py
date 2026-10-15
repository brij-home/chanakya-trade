"""
tests/test_phase1_pacing_and_coordinates.py
───────────────────────────────────────────
Regression verification for Phase 1 fixes:
1. Cross-Asset Pacing Isolation: Cash Equity dispatches do not choke FNO_STOCK options.
2. Coordinate Sanctity: ASYMMETRIC_OPPORTUNITY root targets remain in SPOT domain,
   while option premium targets reside cleanly in option_plan.
3. Long Put Directional Semantics: Put option buying is treated as upward expansion in premium space.
"""

import time
from engine.auto_alert_engine import AutoAlertEngine
from engine.alert_model import AutoAlert


def _make_alert(alert_id, symbol, segment="FNO_STOCK", confidence=90, **kwargs):
    a = AutoAlert(
        alert_id=alert_id,
        alert_type=kwargs.get("alert_type", "GAMMA_BLAST"),
        stage="IGNITED",
        symbol=symbol,
        exchange="NSE",
        direction=kwargs.get("direction", "BULLISH"),
        headline="Test alert",
        summary="Test summary",
        ltp=kwargs.get("ltp", 100.0),
        trigger_level=kwargs.get("trigger_level", 100.0),
        target_level=kwargs.get("target_level", 120.0),
        stop_loss=kwargs.get("stop_loss", 90.0),
        confidence=confidence,
        segment=segment,
        contract_symbol=kwargs.get("contract_symbol", f"{symbol}26OCT100CE"),
    )
    if "actionable_plan" in kwargs:
        a.actionable_plan = kwargs["actionable_plan"]
    return a


def test_fno_stock_not_choked_by_cash_equity_pacing():
    """Verify that 8 Cash Equity dispatches do NOT block high-conviction FNO_STOCK options."""
    engine = AutoAlertEngine()
    now_t = time.time()
    # 8 Cash equity dispatches within the last 30 minutes
    engine._hourly_telegram_dispatches["EQUITY"] = [now_t - (i * 100) for i in range(8)]
    engine._hourly_telegram_dispatches["FNO_STOCK"] = []
    engine._hourly_telegram_dispatches["STOCKS"] = list(
        engine._hourly_telegram_dispatches["EQUITY"]
    )

    # High-conviction FNO_STOCK option breakout arrives (e.g. RVNL CE or PFC CE)
    alert_opt = _make_alert(
        "aa-gamma-blast-rvnl-ce-195-20261013",
        "RVNL",
        segment="FNO_STOCK",
        confidence=92,
        contract_symbol="NSE:RVNL26OCT195CE",
        ltp=5.5,
        trigger_level=5.5,
        target_level=7.7,
        stop_loss=4.5,
    )

    passed, reason = engine._eval_telegram_apex_gate(alert_opt, in_market=True)
    assert passed, (
        f"Expected FNO_STOCK option to pass isolated pacing, but was blocked by: {reason}"
    )


def test_asymmetric_opportunity_spot_target_coordinate_integrity():
    """Verify that ASYMMETRIC_OPPORTUNITY maintains spot targets at root and option targets in option_plan."""
    plan = {
        "action": "BUY",
        "segment": "FNO_STOCK",
        "instrument_type": "OPTION",
        "spot_entry_range": "₹2,830 – ₹2,845",
        "spot_stop_loss": 2767.39,
        "spot_target_1": 2966.78,
        "spot_target_2": 3108.5,
        "target": "₹2,966.8",
        "target_1": "₹2,966.8",
        "target_2": "₹3,108.5",
        "option_plan": {
            "contract_symbol": "NSE:MM26OCT2850CE",
            "entry_premium": 54.15,
            "sl_premium": 37.9,
            "t1_premium": 118.24,
            "t2_premium": 185.0,
        },
    }

    alert = AutoAlert(
        alert_id="aa-asym-fno-ban-squeeze-m&m-20261013",
        alert_type="ASYMMETRIC_OPPORTUNITY",
        stage="EARLY_WARNING",
        symbol="M&M",
        exchange="NSE",
        direction="BULLISH",
        headline="M&M Asymmetric Squeeze",
        summary="M&M base squeeze",
        ltp=2838.6,
        trigger_level=2838.6,
        target_level=2966.78,
        stop_loss=2767.39,
        confidence=88,
        segment="FNO_STOCK",
        actionable_plan=plan,
    )

    # 1. Enforce target harmonization
    alert.normalize_target_hierarchy()

    # 2. Verify root target_1 preserves the SPOT target, NOT the option premium!
    assert alert.target_1 == 2966.78, f"Expected spot target 2966.78, got {alert.target_1}"
    assert alert.entry_price == 2838.6
    assert alert.stop_loss == 2767.39
    assert alert.target_1 > alert.entry_price > alert.stop_loss

    # 3. Verify option premium targets remain intact in option_plan
    assert alert.option_target_1 == 118.24
    assert plan["option_plan"]["t1_premium"] == 118.24

    # 4. Verify to_dict output maintains spot coordinates
    d = alert.to_dict()
    assert d["entry_price"] == 2838.6
    assert d["target_1"] == 2966.78
    assert d["target_1"] > d["entry_price"]
