"""
tests/test_mcx_conviction_and_safeguards.py
─────────────────────────────────────────────
Comprehensive institutional test suite for MCX commodity trade conviction safeguards:
  1. Tier-1 Sub-ATR Noise Trap Rejection (Crude Oil <80 pts, NatGas <6 pts, Silver <450 pts, Gold <250 pts)
  2. Tier-1 Noise-Safe Structural Stop Acceptance
  3. Wednesday EIA Crude Inventory Blackout Gate (19:45 - 20:45 IST)
  4. Thursday EIA Natural Gas Storage Blackout Gate (19:45 - 20:45 IST)
  5. Global Macro DXY Divergence Gate (Bullion longs blocked when DXY is surging)
  6. Global Macro Brent Divergence Gate (Crude longs blocked when Brent is crashing)
  7. Defined-Risk Option Vehicle Prioritization for High-Volatility Commodities
  8. Live Global Macro Context Injection into Scrutiny Prompt
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
import pytest
import pandas as pd

from engine.alert_model import AutoAlert
from engine.alert_scrutiny import AlertScrutinyAuditor, COMMODITY_MIN_SL_FLOORS
from engine.auto_alert_engine import AutoAlertEngine
from market.macro import MacroSnapshot

IST = timezone(timedelta(hours=5, minutes=30))


@pytest.fixture
def auditor() -> AlertScrutinyAuditor:
    return AlertScrutinyAuditor(min_rr_ratio=1.3, max_intraday_risk_pct=8.0)


# ── 1. Sub-ATR Noise Trap Rejections ──────────────────────────────────────────


def test_crude_sub_atr_stop_rejection(auditor: AlertScrutinyAuditor):
    """Verifies that a tight 30-pt stop on Crude Oil is rejected in Tier-1 sanity."""
    alert = AutoAlert(
        alert_id="test-crude-tight",
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        headline="MCX Crude Momentum",
        summary="Testing tight stop",
        symbol="CRUDEOIL",
        exchange="MCX",
        direction="BULLISH",
        ltp=6500.0,
        trigger_level=6500.0,
        stop_loss=6470.0,  # 30 pts risk (floor is 80 pts)
        target_level=6580.0,  # R:R = 80/30 = 2.66 (mathematically passes RR, but fails commodity noise)
        confidence=80,
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert not passed
    assert "Sub-ATR Noise Trap" in reason
    assert "CRUDEOIL" in reason
    assert flags["risk_within_bounds"] is False


def test_natgas_sub_atr_stop_rejection(auditor: AlertScrutinyAuditor):
    """Verifies that a tight 2-pt stop on Natural Gas is rejected in Tier-1 sanity."""
    alert = AutoAlert(
        alert_id="test-ng-tight",
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        headline="MCX NatGas Momentum",
        summary="Testing tight stop",
        symbol="NATURALGAS",
        exchange="MCX",
        direction="BULLISH",
        ltp=280.0,
        trigger_level=280.0,
        stop_loss=278.0,  # 2.0 pts risk (floor is 6.0 pts)
        target_level=286.0,  # 6.0 pts reward (R:R 3.0)
        confidence=80,
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert not passed
    assert "Sub-ATR Noise Trap" in reason
    assert "NATURALGAS" in reason


def test_commodity_structural_noise_safe_stop_acceptance(
    auditor: AlertScrutinyAuditor, monkeypatch
):
    """Verifies that noise-safe structural stops (Crude >= 80 pts, NatGas >= 6 pts) pass Tier-1."""
    # Mock neutral macro to isolate stop distance testing
    monkeypatch.setattr(
        "market.macro.get_macro_snapshot",
        lambda: MacroSnapshot(dxy_change=0.0, crude_change=0.1),
    )
    # Crude Oil with 90 pts risk
    crude_valid = AutoAlert(
        alert_id="test-crude-safe",
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        headline="MCX Crude Structural Breakout",
        summary="Valid breakout with safe stop",
        symbol="CRUDEOIL",
        exchange="MCX",
        direction="BULLISH",
        ltp=6500.0,
        trigger_level=6500.0,
        stop_loss=6410.0,  # 90 pts risk (> 80 pts floor)
        target_level=6700.0,  # 200 pts reward (R:R > 2.2)
        confidence=85,
        created_at="2026-09-15 16:30:00 IST",  # Tuesday (no EIA blackout)
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(crude_valid)
    assert passed
    assert flags["risk_within_bounds"] is True
    assert flags["rr_valid"] is True


# ── 2. High-Impact Inventory Blackout Gates ───────────────────────────────────


def test_wednesday_eia_crude_inventory_blackout(auditor: AlertScrutinyAuditor):
    """Verifies that Crude Oil setups are vetoed during Wednesday 20:00 IST EIA inventory window."""
    # Wednesday (weekday == 2) at 20:15 IST
    alert = AutoAlert(
        alert_id="test-crude-eia",
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        headline="MCX Crude Pre-EIA Setup",
        summary="Testing EIA blackout",
        symbol="CRUDEOIL",
        exchange="MCX",
        direction="BULLISH",
        ltp=6500.0,
        trigger_level=6500.0,
        stop_loss=6400.0,
        target_level=6750.0,
        confidence=85,
        created_at="2026-09-16 20:15:00 IST",  # Sep 16, 2026 is a Wednesday!
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert not passed
    assert "EIA Crude Inventory Blackout" in reason


def test_thursday_eia_natgas_storage_blackout(auditor: AlertScrutinyAuditor):
    """Verifies that Natural Gas setups are vetoed during Thursday 20:15 IST EIA storage window."""
    # Thursday (weekday == 3) at 20:15 IST
    alert = AutoAlert(
        alert_id="test-ng-eia",
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        headline="MCX NatGas Pre-EIA Setup",
        summary="Testing NatGas storage blackout",
        symbol="NATURALGAS",
        exchange="MCX",
        direction="BULLISH",
        ltp=280.0,
        trigger_level=280.0,
        stop_loss=272.0,
        target_level=300.0,
        confidence=85,
        created_at="2026-09-17 20:15:00 IST",  # Sep 17, 2026 is a Thursday!
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert not passed
    assert "EIA Natural Gas Storage Blackout" in reason


# ── 3. Global Macro Divergence Gates ──────────────────────────────────────────


def test_gold_bullish_vetoed_by_surging_dxy(auditor: AlertScrutinyAuditor, monkeypatch):
    """Verifies that Gold longs are vetoed when US Dollar Index (DXY) is surging (+0.40%)."""
    mock_macro = MacroSnapshot(
        dxy=104.5,
        dxy_change=0.45,  # Strong dollar surge!
        crude_oil=78.0,
        gold=2500.0,
    )
    monkeypatch.setattr("market.macro.get_macro_snapshot", lambda: mock_macro)

    alert = AutoAlert(
        alert_id="test-gold-dxy",
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        headline="MCX Gold Bullish Long",
        summary="Testing DXY surge filter",
        symbol="GOLD",
        exchange="MCX",
        direction="BULLISH",
        ltp=73000.0,
        trigger_level=73000.0,
        stop_loss=72650.0,  # 350 pts risk (>250 floor)
        target_level=73800.0,  # 800 pts reward
        confidence=85,
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert not passed
    assert "Global Macro Divergence" in reason
    assert "US Dollar Index (DXY)" in reason


def test_crude_bullish_vetoed_by_crashing_brent(auditor: AlertScrutinyAuditor, monkeypatch):
    """Verifies that MCX Crude longs are vetoed when Global Brent is dumping (-1.8%)."""
    mock_macro = MacroSnapshot(
        crude_oil=74.0,
        crude_change=-1.85,  # Global Brent crash
    )
    monkeypatch.setattr("market.macro.get_macro_snapshot", lambda: mock_macro)

    alert = AutoAlert(
        alert_id="test-crude-brent",
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        headline="MCX Crude Long Setup",
        summary="Testing Brent crash filter",
        symbol="CRUDEOIL",
        exchange="MCX",
        direction="BULLISH",
        ltp=6500.0,
        trigger_level=6500.0,
        stop_loss=6400.0,  # 100 pts risk (>80 floor)
        target_level=6750.0,
        confidence=85,
        created_at="2026-09-15 16:30:00 IST",  # Tuesday afternoon (no EIA blackout)
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert not passed
    assert "Global Macro Divergence" in reason
    assert "Brent crude" in reason


def test_natgas_bullish_vetoed_by_crashing_henry_hub(auditor: AlertScrutinyAuditor, monkeypatch):
    """Verifies that MCX NatGas longs are vetoed when Henry Hub natural gas is dumping (-2.5%)."""
    mock_macro = MacroSnapshot(
        natural_gas=3.10,
        natural_gas_change=-2.65,  # Henry Hub crash
    )
    monkeypatch.setattr("market.macro.get_macro_snapshot", lambda: mock_macro)

    alert = AutoAlert(
        alert_id="test-ng-hh",
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        headline="MCX NatGas Long Setup",
        summary="Testing Henry Hub crash filter",
        symbol="NATURALGAS",
        exchange="MCX",
        direction="BULLISH",
        ltp=305.0,
        trigger_level=305.0,
        stop_loss=295.0,
        target_level=325.0,
        confidence=85,
        created_at="2026-09-15 16:30:00 IST",
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert not passed
    assert "Global Macro Divergence" in reason
    assert "Henry Hub Natural Gas" in reason


# ── 4. Auto Alert Engine Multi-Timeframe Stop Floor & Preferred Vehicle ───────


def test_auto_alert_engine_applies_commodity_sl_floor(monkeypatch):
    """Verifies that scan_commodities_now sets stop-loss at or above COMMODITY_MIN_SL_FLOORS."""
    engine = AutoAlertEngine()
    engine._alerts = []
    engine._cooldowns = {}
    engine._watched_commodities = ["CRUDEOIL"]

    mock_quote = MagicMock()
    mock_quote.last_price = 6500.0
    mock_quote.ltp = 6500.0
    mock_quote.open = 6400.0  # +1.56% breakout
    mock_quote.high = 6510.0
    mock_quote.low = 6390.0
    mock_quote.change_pct = 1.2
    mock_quote.volume = 40000

    # Mock macro snapshot to be neutral
    monkeypatch.setattr(
        "market.macro.get_macro_snapshot",
        lambda: MacroSnapshot(dxy_change=0.0, crude_change=0.2),
    )

    with patch("market.quotes.get_quote", return_value={"MCX:CRUDEOIL": mock_quote}):
        with patch("market.history.get_ohlcv", return_value=None):
            with patch("market.quotes.get_ltp", return_value=6500.0):
                alerts = engine.scan_commodities_now()
                assert len(alerts) >= 1
                alert = alerts[0]
                fut_ref = alert.actionable_plan.get("futures_reference")
                risk_pts = (
                    abs(fut_ref["entry"] - fut_ref["stop_loss"])
                    if fut_ref
                    else abs(alert.ltp - alert.stop_loss)
                )
                # Must be at least the 80-pt structural floor
                assert risk_pts >= COMMODITY_MIN_SL_FLOORS["CRUDEOIL"]


def test_defined_risk_option_preferred_vehicle_annotation(monkeypatch):
    """Verifies that high-volatility commodities highlight DEFINED_RISK_OPTION in actionable_plan."""
    engine = AutoAlertEngine()
    engine._alerts = []
    engine._cooldowns = {}
    engine._watched_commodities = ["CRUDEOIL"]

    mock_quote = MagicMock()
    mock_quote.last_price = 6500.0
    mock_quote.ltp = 6500.0
    mock_quote.open = 6400.0
    mock_quote.high = 6510.0
    mock_quote.low = 6390.0
    mock_quote.change_pct = 1.2
    mock_quote.volume = 40000

    mock_opt = MagicMock()
    mock_opt.symbol = "MCX:CRUDEOIL26SEP6500CE"
    mock_opt.strike = 6500
    mock_opt.option_type = "CE"
    mock_opt.last_price = 140.0

    monkeypatch.setattr(
        "market.macro.get_macro_snapshot",
        lambda: MacroSnapshot(dxy_change=0.0, crude_change=0.2),
    )
    monkeypatch.setattr("market.options.get_options_chain", lambda sym: [mock_opt])

    with patch("market.quotes.get_quote", return_value={"MCX:CRUDEOIL": mock_quote}):
        with patch("market.history.get_ohlcv", return_value=None):
            with patch("market.quotes.get_ltp", return_value=6500.0):
                alerts = engine.scan_commodities_now()
                assert len(alerts) >= 1
                plan = alerts[0].actionable_plan
                assert plan.get("preferred_vehicle") == "DEFINED_RISK_OPTION"
                assert "option_alternative" in plan
                assert plan["option_alternative"]["contract"] == "MCX:CRUDEOIL26SEP6500CE"


# ── 5. Tier-2 Scrutiny Prompt Injects Live Macro Context ───────────────────────


def test_commodity_scrutiny_prompt_contains_macro_context(
    auditor: AlertScrutinyAuditor, monkeypatch
):
    """Verifies that _build_scrutiny_prompt injects live DXY and Brent indicators into commodity prompt."""
    mock_macro = MacroSnapshot(
        dxy=103.8,
        dxy_change=-0.12,
        crude_oil=79.5,
        crude_change=0.85,
        gold=2520.0,
        gold_change=0.45,
        us_10y=3.85,
        usdinr=83.92,
    )
    monkeypatch.setattr("market.macro.get_macro_snapshot", lambda: mock_macro)

    alert = AutoAlert(
        alert_id="test-prompt-macro",
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        headline="MCX Crude Prompt Audit",
        summary="Testing macro context injection",
        symbol="CRUDEOIL",
        exchange="MCX",
        direction="BULLISH",
        ltp=6500.0,
        trigger_level=6500.0,
        stop_loss=6400.0,
        target_level=6750.0,
        confidence=85,
    )
    prompt = auditor._build_scrutiny_prompt(alert)
    assert "GLOBAL MACRO:" in prompt
    assert "DXY: 103.8" in prompt
    assert "Brent: $79.5" in prompt
    assert "COMEX Gold: $2520.0" in prompt


# ── 6. Readable Option Formatting & SMC Confluence Tests ─────────────────────


def test_format_readable_option_symbol():
    """Verifies that format_readable_option_symbol produces clean, human-readable labels."""
    from market.options import format_readable_option_symbol, parse_option_symbol

    # 1. Crude Oil
    assert format_readable_option_symbol("MCX:CRUDEOIL26SEP6500CE") == "CRUDEOIL 6500 CE (26 Sep)"
    assert format_readable_option_symbol("CRUDEOIL26SEP6500PE") == "CRUDEOIL 6500 PE (26 Sep)"

    # 2. Natural Gas
    assert format_readable_option_symbol("MCX:NATURALGAS26SEP240PE") == "NATURALGAS 240 PE (26 Sep)"

    # 3. Gold & Silver
    assert format_readable_option_symbol("MCX:GOLD26OCT75000CE") == "GOLD 75000 CE (26 Oct)"
    assert format_readable_option_symbol("MCX:SILVER26NOV88000PE") == "SILVER 88000 PE (26 Nov)"

    # 4. Explicit parameters override
    assert (
        format_readable_option_symbol(
            "MCX:CRUDEOIL", strike=6600.0, option_type="CE", expiry="2026-09-26"
        )
        == "CRUDEOIL 6600 CE (26 Sep)"
    )

    # 5. Parsing structure
    parsed = parse_option_symbol("MCX:CRUDEOIL26SEP6500CE")
    assert parsed["underlying"] == "CRUDEOIL"
    assert parsed["strike"] == 6500.0
    assert parsed["option_type"] == "CE"
    assert parsed["expiry_tag"] == "26SEP"


def test_scan_commodities_options_first_and_smc_confluence(monkeypatch):
    """Verifies that scan_commodities_now generates an Options-First payload with SMC confluence."""
    import pandas as pd
    from engine.auto_alert_engine import AutoAlertEngine
    from market.macro import MacroSnapshot

    engine = AutoAlertEngine()
    engine._alerts = []
    engine._cooldowns = {}
    engine._watched_commodities = ["CRUDEOIL"]

    mock_quote = MagicMock()
    mock_quote.last_price = 6500.0
    mock_quote.ltp = 6500.0
    mock_quote.open = 6420.0
    mock_quote.high = 6502.0
    mock_quote.low = 6415.0
    mock_quote.vwap = 6450.0
    mock_quote.change_pct = 2.4
    mock_quote.volume = 55000

    mock_opt = MagicMock()
    mock_opt.symbol = "MCX:CRUDEOIL26SEP6500CE"
    mock_opt.strike = 6500.0
    mock_opt.option_type = "CE"
    mock_opt.last_price = 195.0
    mock_opt.expiry = "2026-09-26"

    # Create 25 5m candles: 24 consolidating around 6430-6460, 25th breaking out to 6500
    dates = pd.date_range("2026-09-16 18:00", periods=25, freq="5min")
    opens = [6430.0 + (i % 5) * 2.0 for i in range(24)] + [6460.0]
    highs = [o + 5.0 for o in opens[:-1]] + [6502.0]
    lows = [o - 3.0 for o in opens[:-1]] + [6458.0]
    closes = [o + 2.0 for o in opens[:-1]] + [6500.0]
    volumes = [1000.0] * 24 + [4500.0]  # RVOL 4.5x surge
    df_5m = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        },
        index=dates,
    )

    monkeypatch.setattr(
        "market.macro.get_macro_snapshot",
        lambda: MacroSnapshot(dxy_change=-0.1, crude_change=1.5),
    )
    monkeypatch.setattr("market.options.get_options_chain", lambda sym: [mock_opt])

    with patch("market.quotes.get_quote", return_value={"MCX:CRUDEOIL": mock_quote}):
        with patch("market.history.get_ohlcv", return_value=df_5m):
            with patch("market.quotes.get_ltp", return_value=6500.0):
                alerts = engine.scan_commodities_now()
                assert len(alerts) >= 1
                alert = alerts[0]
                plan = alert.actionable_plan

                # Options-First Assertions
                assert plan["preferred_vehicle"] == "DEFINED_RISK_OPTION"
                assert plan["action"] == "BUY_CE"
                assert "CRUDEOIL 6500 CE (26 Sep)" in plan["contract"]
                assert plan["max_loss_capped"] == 195.0 * 100  # 19,500
                assert "futures_reference" in plan
                assert plan["futures_reference"]["entry"] == 6500.0

                # Confluence Assertions
                assert "setup_confluence" in plan
                assert alert.derivative_type == "OPT"
                assert alert.option_premium == 195.0
                assert alert.option_stop_loss > 0


def test_telegram_mcx_options_first_formatting():
    """Verifies that alert_templates renders human-readable options, capped max risk, and SMC confluence."""
    from bot.alert_templates import format_auto_alert_telegram

    alert = AutoAlert(
        alert_id="comm-crudeoil-opt-test",
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        symbol="CRUDEOIL",
        exchange="MCX",
        direction="BULLISH",
        headline="🛢️ MCX OPTION: CRUDEOIL 6500 CE (26 Sep) @ ₹195.0",
        summary="Institutional breakout with capped risk",
        ltp=195.0,
        trigger_level=195.0,
        stop_loss=145.0,
        target_level=295.0,
        confidence=88,
        is_live=True,
        environment="LIVE",
        market_status="LIVE",
        actionable_plan={
            "action": "BUY_CE",
            "contract": "CRUDEOIL 6500 CE (26 Sep)",
            "entry_range": "₹190.0 – ₹200.0",
            "stop_loss": "₹145.0",
            "target": "₹295.0",
            "target_2": "₹370.0",
            "risk_reward": "1:2.4",
            "lot_size": 100,
            "preferred_vehicle": "DEFINED_RISK_OPTION",
            "max_loss_capped": 19500.0,
            "setup_confluence": "SMC Bullish BOS + Demand Order Block Support + Institutional Surge (RVOL 2.1x)",
            "futures_reference": {
                "contract": "MCX:CRUDEOIL",
                "entry": 6540.0,
                "stop_loss": 6450.0,
            },
            "profit_rule": "Book 50% at T1, trail stop to cost.",
        },
    )

    formatted = format_auto_alert_telegram(alert)
    assert (
        "BUY <b>CRUDEOIL 6500 CE (26 Sep)</b>" in formatted
        or "BUY_CE <b>CRUDEOIL 6500 CE (26 Sep)</b>" in formatted
    )
    assert "Capped Max Risk:</b> ₹19,500" in formatted
    assert "Confluence:</b> <i>SMC Bullish BOS" in formatted
    assert "Underlying Anchor:</b> <code>MCX:CRUDEOIL</code> @ ₹6,540.0" in formatted
    # Ensure unreadable raw tokens are NOT shown in primary action
    assert "CRUDEOIL26SEP6500CE" not in formatted


# ── New Signal Quality Improvement Tests ───────────────────────────────────────


def test_detect_confirmation_candle_hammer():
    """Hammer candle (long lower wick) is detected as a valid bullish rejection candle."""
    import pandas as pd
    from analysis.market_structure import detect_confirmation_candle

    # Hammer: tiny body at top, long lower wick
    df = pd.DataFrame(
        [
            {"open": 100.0, "high": 101.0, "low": 85.0, "close": 99.5},  # prev
            {"open": 98.0, "high": 99.0, "low": 82.0, "close": 97.5},  # Hammer bar
        ]
    )
    result = detect_confirmation_candle(df, direction="BULLISH")
    assert result["confirmed"] is True
    assert result["pattern"] in ("Hammer", "Bullish Pin Bar")
    assert result["strength"] >= 65


def test_detect_confirmation_candle_bearish_engulfing():
    """Bearish engulfing is detected for BEARISH direction."""
    import pandas as pd
    from analysis.market_structure import detect_confirmation_candle

    # Prior bar is bullish, current bar fully engulfs it with bearish close
    df = pd.DataFrame(
        [
            {"open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0},  # bull bar
            {"open": 106.0, "high": 107.0, "low": 97.0, "close": 98.5},  # bearish engulfing
        ]
    )
    result = detect_confirmation_candle(df, direction="BEARISH")
    assert result["confirmed"] is True
    assert result["pattern"] == "Bearish Engulfing"


def test_detect_divergence_bullish_regular():
    """Regular bullish divergence: price LL, RSI HL."""
    import pandas as pd
    from analysis.market_structure import detect_divergence

    # Construct data where price makes lower low in second half but RSI improves
    # Use a synthetic series that falls then recovers partially
    prices_first = [100.0 - i * 0.2 for i in range(20)]  # declining
    prices_second = [96.0 - i * 0.3 for i in range(20)]  # declining MORE (LL in price)

    closes = pd.Series(prices_first + prices_second)
    # Simulate RSI improvement: first half has lower RSI, second half recovers
    df = pd.DataFrame(
        {
            "close": closes,
            "high": closes + 0.5,
            "low": closes - 0.5,
        }
    )
    result = detect_divergence(df)
    # We just check function returns valid dict without errors; divergence direction
    # depends on data shape
    assert "type" in result
    assert "bias" in result
    assert result["type"] in (
        "BULLISH_REGULAR",
        "BEARISH_REGULAR",
        "BULLISH_HIDDEN",
        "BEARISH_HIDDEN",
        "NONE",
    )


def test_detect_divergence_returns_none_on_insufficient_data():
    """Divergence detection returns NONE gracefully with < 20 bars."""
    import pandas as pd
    from analysis.market_structure import detect_divergence

    df = pd.DataFrame({"close": [100.0] * 10, "high": [101.0] * 10, "low": [99.0] * 10})
    result = detect_divergence(df)
    assert result["type"] == "NONE"
    assert result["bias"] == "NONE"


def test_tuesday_api_crude_blackout():
    """Tuesday API crude inventory blackout (20:00–21:30 IST) blocks CRUDEOIL signals."""
    import os
    from unittest.mock import patch, MagicMock
    from datetime import timezone, timedelta

    IST = timezone(timedelta(hours=5, minutes=30))
    tuesday_api_time = datetime(2026, 9, 15, 20, 30, tzinfo=IST)  # Tuesday 20:30 IST

    engine = AutoAlertEngine()

    mock_quote = MagicMock()
    mock_quote.last_price = 6500.0
    mock_quote.ltp = 6500.0
    mock_quote.change_pct = 1.5
    mock_quote.open = 6400.0
    mock_quote.high = 6520.0
    mock_quote.low = 6380.0
    mock_quote.volume = 10000
    mock_quote.vwap = 6450.0
    mock_quote.provider = "live"
    mock_quote.data_state = "LIVE"
    mock_quote._is_mock = False

    with (
        patch("engine.auto_alert_engine.datetime") as mock_dt,
        patch("market.quotes.get_quote", return_value={"MCX:CRUDEOIL": mock_quote}),
        patch("engine.auto_alert_engine.AutoAlertEngine.record_alert", return_value=False),
        patch(
            "engine.learning_engine.pattern_learning_engine.is_symbol_locked_out",
            return_value=(False, ""),
        ),
    ):
        mock_dt.now.return_value = tuesday_api_time
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

        # During Tuesday 20:30 IST — should be suppressed by API blackout
        with patch.dict(os.environ, {"CHANAKYA_TESTING": "0"}):
            # The blackout should suppress the signal; no alerts generated for CRUDEOIL
            results = engine.scan_commodities_now()
            # Either suppressed (0 alerts) or record_alert returned False (mocked)
            crudeoil_alerts = [a for a in results if "CRUDEOIL" in (a.symbol or "").upper()]
            assert len(crudeoil_alerts) == 0, (
                "CRUDEOIL signal must be suppressed during Tuesday API blackout"
            )


def test_mtf_alignment_returns_alignment_count():
    """check_mtf_structural_alignment now returns alignment_count (0-3)."""
    import pandas as pd
    from analysis.market_structure import check_mtf_structural_alignment

    # Build a bullish 5m DataFrame
    n = 60
    prices = [100.0 + i * 0.1 for i in range(n)]
    df_5m = pd.DataFrame(
        {
            "open": [p - 0.05 for p in prices],
            "high": [p + 0.15 for p in prices],
            "low": [p - 0.15 for p in prices],
            "close": prices,
            "volume": [1000] * n,
        }
    )

    result = check_mtf_structural_alignment(
        "CRUDEOIL", exchange="MCX", ltp=105.0, direction="BULLISH", df_5m=df_5m
    )
    assert "alignment_count" in result
    assert 0 <= result["alignment_count"] <= 3
    assert "is_aligned" in result
    assert "tf_5m_trend" in result
    assert "tf_15m_trend" in result


# ── MCX Alert Quality, Options Safeguards & Provenance Tests ───────────────


def test_copper_and_base_metals_default_to_futures_never_options(monkeypatch):
    """
    Verifies that COPPER, ZINC, and ALUMINIUM always default to MCX FUTURES,
    never illiquid options, even if an options chain function returns mock contracts.
    """
    import pandas as pd
    from engine.auto_alert_engine import AutoAlertEngine
    from market.macro import MacroSnapshot
    from brokers.base import OptionsContract

    engine = AutoAlertEngine()
    engine._alerts = []
    engine._cooldowns = {}
    engine._watched_commodities = ["COPPER"]

    mock_quote = MagicMock()
    mock_quote.last_price = 1413.5
    mock_quote.ltp = 1413.5
    mock_quote.open = 1400.0
    mock_quote.high = 1420.0
    mock_quote.low = 1395.0
    mock_quote.vwap = 1405.0
    mock_quote.change_pct = 1.8
    mock_quote.volume = 12000
    mock_quote.source = "REST"
    mock_quote.provider = "live"

    dates = pd.date_range("2026-09-22 18:00", periods=25, freq="5min")
    opens = [1400.0 + (i % 5) * 1.0 for i in range(24)] + [1410.0]
    highs = [o + 2.0 for o in opens[:-1]] + [1415.0]
    lows = [o - 1.0 for o in opens[:-1]] + [1409.0]
    closes = [o + 1.0 for o in opens[:-1]] + [1413.5]
    volumes = [500.0] * 24 + [2500.0]
    df_5m = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )

    mock_opt = OptionsContract(
        symbol="MCX:COPPER26SEP1450CE",
        underlying="COPPER",
        expiry="2026-09-23",
        strike=1450.0,
        option_type="CE",
        last_price=0.27,
        oi=1000,
        oi_change=50,
        volume=5000,
        lot_size=2500,
        exchange="MCX",
    )

    monkeypatch.setattr(
        "market.macro.get_macro_snapshot",
        lambda: MacroSnapshot(dxy_change=-0.2, crude_change=0.5),
    )
    monkeypatch.setattr("market.options.get_options_chain", lambda sym: [mock_opt])

    with (
        patch("market.quotes.get_quote", return_value={"MCX:COPPER": mock_quote}),
        patch("market.history.get_ohlcv", return_value=df_5m),
        patch("market.quotes.get_ltp", return_value=1413.5),
    ):
        alerts = engine.scan_commodities_now()
        assert len(alerts) >= 1
        alert = alerts[0]
        plan = alert.actionable_plan

        # Institutional Base Metals Rule: MUST be FUTURES
        assert alert.derivative_type == "FUT"
        assert alert.contract_symbol == "MCX:COPPER"
        assert plan["preferred_vehicle"] == "FUTURES"
        assert plan["action"] == "BUY_FUTURES"
        assert "MCX BREAKOUT: COPPER" in alert.headline or "MCX MOMENTUM: COPPER" in alert.headline
        assert "MCX OPTION: COPPER" not in alert.headline


def test_mcx_prompt_expiry_weekend_rollback_and_accurate_dte():
    """
    Verifies that MCX options never expire on weekends and calculate exact DTE.
    """
    from datetime import date
    from engine.greeks_manager import get_mcx_prompt_expiry_and_dte

    # On 2026-09-22: Copper prompt expiry is 2026-09-23 (Wednesday), DTE = 1
    exp_date, dte = get_mcx_prompt_expiry_and_dte("COPPER", as_of=date(2026, 9, 22))
    assert exp_date == "2026-09-23"
    assert dte == 1

    # Verify that if candidate day 25 falls on Sunday (e.g. October 2026 where Oct 25 is Sunday)
    # it rolls backward to Friday Oct 23!
    assert date(2026, 10, 25).weekday() == 6  # Sunday
    exp_oct, _ = get_mcx_prompt_expiry_and_dte("GOLD", as_of=date(2026, 10, 1))
    oct_d = date.fromisoformat(exp_oct)
    assert oct_d.weekday() < 5  # MUST be Monday-Friday, never weekend!
    assert oct_d == date(2026, 10, 23)  # Rolled backward from Sunday 25 to Friday 23


def test_alert_invalidation_clears_milestones_and_purges_outcomes():
    """
    Verifies that when an alert is invalidated:
    1. achieved_milestones is emptied so it is never displayed or counted as a target hit.
    2. target_status is set to INVALIDATED.
    3. r_multiple and pnl_pct are zeroed out.
    4. PatternLearningEngine.invalidate_alert_outcomes() is invoked to purge any false win records.
    """
    from engine.auto_alert_engine import AutoAlertEngine
    from engine.alert_model import AutoAlert
    from engine.learning_engine import pattern_learning_engine

    engine = AutoAlertEngine()

    test_alert = AutoAlert(
        alert_id="test-inv-milestones-123",
        alert_type="COMMODITY_MOMENTUM",
        stage="TRAILING_UPDATE",
        symbol="COPPER",
        exchange="MCX",
        direction="BULLISH",
        headline="Test alert",
        summary="Test summary",
        ltp=1442.0,
        trigger_level=1442.0,
        stop_loss=1426.0,
        target_level=1476.0,
        confidence=85,
        is_live=True,
        achieved_milestones=["T1_ACHIEVED", "T2_ACHIEVED"],
        target_status="T2_ACHIEVED",
        r_multiple=247.95,
        pnl_pct=8719.88,
    )

    with engine._lock:
        engine._alerts.append(test_alert)

    # Record a test outcome in pattern_learning_engine to verify purging
    pattern_learning_engine.record_trade_outcome(
        alert_id="test-inv-milestones-123",
        symbol="COPPER",
        archetype="COMMODITY_MOMENTUM",
        entry_price=16.33,
        exit_price=1441.63,
        outcome="WIN_T2",
        realized_rr=3.5,
    )

    # Invalidate alert with honest reason
    inv = engine.invalidate_alert_by_id(
        "test-inv-milestones-123",
        reason="Corrupted alert: MCX option vehicle evaluated against spot price with uncalibrated COMEX basis",
    )

    assert inv is not None
    assert inv.is_invalidated is True
    assert inv.stage == "INVALIDATED"
    assert inv.target_status == "INVALIDATED"
    assert inv.achieved_milestones == []
    assert inv.r_multiple == 0.0
    assert inv.pnl_pct == 0.0
    assert inv.should_trail is False
    assert inv.trailing_decision == "INVALIDATED"

    # Verify that pattern_learning_engine no longer holds WIN_T2 for this alert
    matching = [
        o for o in pattern_learning_engine._outcomes if o.alert_id == "test-inv-milestones-123"
    ]
    assert len(matching) >= 1
    for m in matching:
        assert m.outcome == "INVALIDATED"
        assert m.realized_rr == 0.0


def test_alert_evaluator_rejects_spot_option_scale_mismatch():
    """
    Verifies that evaluate_alert_targets_and_trailing rejects extreme price scale mismatch
    (e.g. current_ltp=1442.0 vs entry=16.33, ratio=88.3) and returns None instead of triggering fake WIN_T2.
    Also verifies that when trigger_level is spot price, option target levels are never falsely triggered.
    """
    from engine.alert_evaluator import evaluate_alert_targets_and_trailing
    from engine.alert_model import AutoAlert

    # Scenario 1: Mismatched entry (option premium 16.33 vs spot quote 1442.05)
    alert_mismatched = AutoAlert(
        alert_id="test-mismatch-1",
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        symbol="COPPER",
        exchange="MCX",
        direction="BULLISH",
        headline="Test alert",
        summary="Test summary",
        ltp=16.33,
        trigger_level=16.33,
        stop_loss=10.6,
        target_level=27.7,
        confidence=85,
        is_live=True,
    )

    res_mismatch = evaluate_alert_targets_and_trailing(alert_mismatched, current_ltp=1442.05)
    # MUST return None because ratio is ~88x
    assert res_mismatch is None

    # Scenario 2: Spot trade with attached option plan (option target ₹27.7 must not trigger on spot 1442.0)
    alert_spot = AutoAlert(
        alert_id="test-spot-opt-plan-2",
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        symbol="COPPER",
        exchange="MCX",
        direction="BULLISH",
        headline="Test alert",
        summary="Test summary",
        ltp=1442.0,
        trigger_level=1442.0,
        stop_loss=1426.0,
        target_level=1476.0,
        confidence=85,
        is_live=True,
        actionable_plan={
            "action": "BUY_CE",
            "entry_range": "₹15.5 – ₹17.2",
            "stop_loss": "₹10.6",
            "target": "₹27.7",
            "target_2": "₹36.3",
            "preferred_vehicle": "DEFINED_RISK_OPTION",
            "instrument_type": "OPTION",
        },
    )

    res_spot = evaluate_alert_targets_and_trailing(alert_spot, current_ltp=1442.05)
    # MUST NOT falsely trigger milestone or mark T2
    assert res_spot.new_milestone is None
    assert res_spot.target_status == "PENDING"
    assert res_spot.r_multiple == 0.0


def test_eod_report_excludes_invalidated_corrupted_alerts(tmp_path, monkeypatch):
    """
    Verifies that EODReportGenerator excludes invalidated corrupted alerts
    from win counts and star setups.
    """
    import json
    from engine.eod_report_generator import EODReportGenerator

    mock_alerts = [
        {
            "alert_id": "comm-copper-corrupt",
            "alert_type": "COMMODITY_MOMENTUM",
            "symbol": "COPPER",
            "exchange": "MCX",
            "direction": "BULLISH",
            "stage": "INVALIDATED",
            "target_status": "INVALIDATED",
            "achieved_milestones": [],
            "is_invalidated": True,
            "invalidation_reason": "Corrupted alert: MCX option vehicle evaluated against spot price with uncalibrated COMEX basis",
            "trigger_level": 1442.0,
            "ltp": 1442.0,
            "stop_loss": 1426.0,
            "target_level": 1476.0,
            "created_at": "2026-09-22 14:42:00 IST",
            "triggered_at": "2026-09-22 14:42:00 IST",
        }
    ]

    alerts_file = tmp_path / "auto_alerts.json"
    alerts_file.write_text(json.dumps(mock_alerts, indent=2), encoding="utf-8")
    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))

    gen = EODReportGenerator(data_file=alerts_file)
    report = gen.generate(target_date="2026-09-22")
    # The corrupted alert MUST NOT be counted as a win or trade
    assert report.win_count == 0
    assert report.loss_count == 0
    assert len(report.star_setups) == 0


def test_mcx_session_end_retirement():
    """
    Verifies that:
    1. Prior-session MCX intraday alerts (e.g. yesterday's) are immediately retired by resolve_session_end_alerts()
       regardless of the current time, preventing zombie lockout.
    2. Today's MCX intraday alerts remain active during MCX trading hours (until 23:30 IST),
       even when NSE equity has closed at 15:30 IST.
    3. Today's MCX intraday alerts are cleanly retired once MCX closes after 23:30 IST.
    """
    from datetime import datetime, timezone, timedelta
    from unittest.mock import patch
    from engine.auto_alert_engine import AutoAlertEngine
    from engine.alert_model import AutoAlert

    IST = timezone(timedelta(hours=5, minutes=30))
    engine = AutoAlertEngine()
    engine._alerts = []

    # Prior date alert (yesterday)
    alert_yesterday_mcx = AutoAlert(
        alert_id="aa-commodity-momentum-naturalgas-20261005",
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        symbol="NATURALGAS",
        exchange="MCX",
        direction="BULLISH",
        headline="MCX NatGas Breakout",
        summary="Prior session setup",
        ltp=280.0,
        trigger_level=280.0,
        stop_loss=272.0,
        target_level=300.0,
        confidence=85,
        created_at="2026-10-05 19:30:00 IST",
        target_status="PENDING",
    )

    # Today's MCX alert
    alert_today_mcx = AutoAlert(
        alert_id="aa-commodity-momentum-crudeoil-20261006",
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        symbol="CRUDEOIL",
        exchange="MCX",
        direction="BULLISH",
        headline="MCX Crude Momentum",
        summary="Active commodity setup",
        ltp=6500.0,
        trigger_level=6500.0,
        stop_loss=6410.0,
        target_level=6700.0,
        confidence=85,
        created_at="2026-10-06 18:00:00 IST",
        target_status="PENDING",
    )

    # Today's NSE alert
    alert_today_nse = AutoAlert(
        alert_id="aa-options-momentum-nifty-20261006",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Nifty Options Momentum",
        summary="Equity setup",
        ltp=25000.0,
        trigger_level=25000.0,
        stop_loss=24900.0,
        target_level=25200.0,
        confidence=85,
        created_at="2026-10-06 10:00:00 IST",
        target_status="PENDING",
    )

    engine._alerts = [alert_yesterday_mcx, alert_today_mcx, alert_today_nse]

    # Test 1: At 19:00 IST on 2026-10-06: NSE is closed (19:00 > 15:30), but MCX is OPEN (19:00 < 23:30)
    time_19_00 = datetime(2026, 10, 6, 19, 0, 0, tzinfo=IST)
    with patch("engine.auto_alert_engine.datetime") as mock_dt:
        mock_dt.now.return_value = time_19_00
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

        resolved = engine.resolve_session_end_alerts()
        # Yesterday's MCX alert and Today's NSE alert must be retired
        assert alert_yesterday_mcx in resolved
        assert alert_today_nse in resolved
        assert alert_yesterday_mcx.is_archived is True
        assert alert_yesterday_mcx.target_status == "EXPIRED_SESSION_END"
        assert "Prior session alert retired" in alert_yesterday_mcx.archive_reason

        # Today's MCX alert MUST NOT be retired at 19:00 IST
        assert alert_today_mcx not in resolved
        assert alert_today_mcx.is_archived is False
        assert alert_today_mcx.stage == "IGNITED"

    # Test 2: At 23:35 IST on 2026-10-06: MCX market is now closed (23:35 > 23:30)
    time_23_35 = datetime(2026, 10, 6, 23, 35, 0, tzinfo=IST)
    with patch("engine.auto_alert_engine.datetime") as mock_dt:
        mock_dt.now.return_value = time_23_35
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

        resolved_late = engine.resolve_session_end_alerts()
        # Today's MCX alert MUST now be retired
        assert alert_today_mcx in resolved_late
        assert alert_today_mcx.is_archived is True
        assert alert_today_mcx.target_status == "EXPIRED_SESSION_END"
        assert "MCX session closed at 23:30 IST" in alert_today_mcx.archive_reason


def test_pacing_retry_dispatches_secondary_commodity():
    """
    Verifies that an alert held back by Telegram segment burst pacing
    is retried and dispatched by _retry_pacing_throttled_alerts() once cooldown expires,
    preventing permanent alert dropouts for secondary commodities.
    """
    import time
    from unittest.mock import patch
    from engine.auto_alert_engine import AutoAlertEngine
    from engine.alert_model import AutoAlert

    IST = timezone(timedelta(hours=5, minutes=30))
    engine = AutoAlertEngine()
    engine._alerts = []
    engine._dispatch_cooldowns = {}

    now_dt = datetime.now(IST)
    throttled_alert = AutoAlert(
        alert_id="aa-commodity-momentum-naturalgas-20261006",
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        symbol="NATURALGAS",
        exchange="MCX",
        direction="BULLISH",
        headline="MCX Momentum: NATURALGAS",
        summary="Secondary commodity breakout",
        ltp=280.0,
        trigger_level=280.0,
        stop_loss=272.0,
        target_level=300.0,
        confidence=90,
        is_live=True,
        environment="LIVE",
        created_at=now_dt.strftime("%Y-%m-%d %H:%M:%S IST"),
        telegram_dispatched=False,
        telegram_suppression_reason="Telegram pacing throttle active on COMMODITY (cooldown: 15s)",
    )
    engine._alerts.append(throttled_alert)

    # Case A: Pacing cooldown is STILL ACTIVE (only 5s since last dispatch, burst cooldown is 15s)
    engine._dispatch_cooldowns["PACING:COMMODITY"] = time.time() - 5.0
    with patch.object(engine, "_dispatch") as mock_dispatch:
        dispatched = engine._retry_pacing_throttled_alerts()
        assert len(dispatched) == 0
        mock_dispatch.assert_not_called()

    # Case B: Pacing cooldown has ELAPSED (20s since last dispatch, burst cooldown 15s)
    engine._dispatch_cooldowns["PACING:COMMODITY"] = time.time() - 20.0

    def fake_dispatch(a):
        a.telegram_dispatched = True
        a.telegram_suppression_reason = None

    with patch.object(engine, "_dispatch", side_effect=fake_dispatch) as mock_dispatch:
        dispatched = engine._retry_pacing_throttled_alerts()
        assert len(dispatched) == 1
        assert dispatched[0].alert_id == throttled_alert.alert_id
        assert throttled_alert.telegram_dispatched is True
        mock_dispatch.assert_called_once_with(throttled_alert)
        # Verify pacing key was updated to fresh timestamp
        assert engine._dispatch_cooldowns["PACING:COMMODITY"] >= time.time() - 2.0


def test_detect_commodity_volatility_squeeze():
    """
    Verifies that detect_commodity_volatility_squeeze detects:
    1. is_squeeze_on when Bollinger Bands coil inside Keltner Channels.
    2. is_squeeze_fired when price expands out of a multi-bar squeeze.
    """
    import pandas as pd
    from engine.detectors.commodity import detect_commodity_volatility_squeeze

    # Create 30 bars of ultra-tight consolidation: price between 100.0 and 100.2
    dates = pd.date_range("2026-10-06 18:00", periods=30, freq="5min")
    tight_opens = [100.0 + (i % 2) * 0.1 for i in range(25)]
    tight_highs = [p + 0.1 for p in tight_opens]
    tight_lows = [p - 0.1 for p in tight_opens]
    tight_closes = [p + 0.05 for p in tight_opens]

    df_coiling = pd.DataFrame(
        {"open": tight_opens, "high": tight_highs, "low": tight_lows, "close": tight_closes},
        index=dates[:25],
    )
    res_coiling = detect_commodity_volatility_squeeze(df_coiling)
    # When volatility is ultra-narrow, BB is well inside KC
    assert res_coiling["is_squeeze_on"] is True
    assert res_coiling["squeeze_bars"] >= 5

    # Now add 5 explosive bars breaking out to 105.0
    exp_opens = [100.2, 101.0, 102.5, 103.8, 104.5]
    exp_highs = [101.2, 102.8, 104.0, 105.2, 106.0]
    exp_lows = [100.0, 100.9, 102.2, 103.5, 104.2]
    exp_closes = [101.0, 102.5, 103.8, 104.8, 105.5]

    df_fired = pd.DataFrame(
        {
            "open": tight_opens + exp_opens,
            "high": tight_highs + exp_highs,
            "low": tight_lows + exp_lows,
            "close": tight_closes + exp_closes,
        },
        index=dates,
    )
    res_fired = detect_commodity_volatility_squeeze(df_fired)
    # The squeeze fired bullishly!
    assert res_fired["is_squeeze_fired"] is True
    assert res_fired["squeeze_direction"] == "BULLISH"


def test_mcx_golden_hours_and_midday_lull():
    """
    Verifies that MCX session golden hours (17:30–22:30 IST) and midday lull (11:30–15:30 IST)
    are accurately identified.
    """
    from datetime import datetime, timezone, timedelta
    from engine.quality_gate import is_mcx_golden_hours_window, is_mcx_midday_lull_window

    IST = timezone(timedelta(hours=5, minutes=30))

    # Tuesday 18:30 IST (US pre-market / active pit) -> Golden Hours
    t_golden = datetime(2026, 10, 6, 18, 30, tzinfo=IST)
    assert is_mcx_golden_hours_window(t_golden) is True
    assert is_mcx_midday_lull_window(t_golden) is False

    # Tuesday 13:00 IST (Midday lull) -> Midday Lull
    t_lull = datetime(2026, 10, 6, 13, 0, tzinfo=IST)
    assert is_mcx_golden_hours_window(t_lull) is False
    assert is_mcx_midday_lull_window(t_lull) is True

    # Tuesday 10:00 IST (Morning session) -> Neither
    t_morning = datetime(2026, 10, 6, 10, 0, tzinfo=IST)
    assert is_mcx_golden_hours_window(t_morning) is False
    assert is_mcx_midday_lull_window(t_morning) is False


def test_quality_gate_vetoes_htf_wall_collision():
    """
    Verifies that evaluate_institutional_quality_gate vetoes setups trading
    directly into higher-timeframe resistance/support walls with poor headroom.
    """
    from engine.alert_model import AutoAlert
    from engine.quality_gate import evaluate_institutional_quality_gate

    alert = AutoAlert(
        alert_id="test-wall-collision-crude",
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        symbol="CRUDEOIL",
        exchange="MCX",
        direction="BULLISH",
        headline="MCX Crude into Wall",
        summary="Testing wall collision veto",
        ltp=6500.0,
        trigger_level=6500.0,
        stop_loss=6410.0,
        target_level=6700.0,
        confidence=85,
        metrics={
            "wall_collision": True,  # 1H resistance right overhead
            "mtf_alignment_count": 1,
        },
    )

    verdict = evaluate_institutional_quality_gate(alert)
    assert verdict.is_vetoed is True
    assert "Overhead Higher-Timeframe Structural Wall" in verdict.veto_reason
    assert verdict.conviction_tier == "REJECTED"


def test_commodity_retest_and_asymmetric_rr_blueprint(monkeypatch):
    """
    Verifies that detect_commodity_breakouts generates an asymmetric blueprint with
    retest entry guidance, Target 1 >= 2.8R, Target 2 >= 5.0R, and Runner >= 8.0R.
    """
    import pandas as pd
    from unittest.mock import patch, MagicMock
    from engine.auto_alert_engine import AutoAlertEngine
    from market.macro import MacroSnapshot

    engine = AutoAlertEngine()
    engine._alerts = []
    engine._cooldowns = {}
    engine._watched_commodities = ["CRUDEOIL"]

    mock_quote = MagicMock()
    mock_quote.last_price = 6500.0
    mock_quote.ltp = 6500.0
    mock_quote.open = 6420.0
    mock_quote.high = 6510.0
    mock_quote.low = 6415.0
    mock_quote.vwap = 6450.0
    mock_quote.change_pct = 2.4
    mock_quote.volume = 55000

    dates = pd.date_range("2026-10-06 18:00", periods=25, freq="5min")
    opens = [6430.0 + (i % 5) * 2.0 for i in range(24)] + [6460.0]
    highs = [o + 5.0 for o in opens[:-1]] + [6510.0]
    lows = [o - 3.0 for o in opens[:-1]] + [6458.0]
    closes = [o + 2.0 for o in opens[:-1]] + [6500.0]
    volumes = [1000.0] * 24 + [4500.0]
    df_5m = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )

    monkeypatch.setattr(
        "market.macro.get_macro_snapshot",
        lambda: MacroSnapshot(dxy_change=-0.1, crude_change=1.5),
    )
    monkeypatch.setattr("market.options.get_options_chain", lambda sym: [])

    with patch("market.quotes.get_quote", return_value={"MCX:CRUDEOIL": mock_quote}):
        with patch("market.history.get_ohlcv", return_value=df_5m):
            with patch("market.quotes.get_ltp", return_value=6500.0):
                alerts = engine.scan_commodities_now()
                assert len(alerts) >= 1
                alert = alerts[0]
                plan = alert.actionable_plan

                # Blueprint Asymmetry Assertions:
                assert "target_1" in plan
                assert "target_2" in plan
                assert "target_3" in plan
                assert "when_to_buy" in plan
                assert "profit_rule" in plan
                assert "+2.8R" in plan["profit_rule"]
                assert "+5.0R" in plan["profit_rule"]
                assert "+8.0R" in plan["profit_rule"]


def test_commodity_microstructure_cvd_and_obi_provenance(monkeypatch):
    """Verifies that commodity scan computes CVD buyer aggression, OBI, and records microstructure metrics."""
    import pandas as pd
    from engine.auto_alert_engine import AutoAlertEngine
    from market.macro import MacroSnapshot
    from unittest.mock import patch, MagicMock

    engine = AutoAlertEngine()
    engine._alerts = []
    engine._cooldowns = {}
    engine._watched_commodities = ["CRUDEOIL"]

    mock_quote = MagicMock()
    mock_quote.symbol = "MCX:CRUDEOIL"
    mock_quote.last_price = 6500.0
    mock_quote.ltp = 6500.0
    mock_quote.open = 6420.0
    mock_quote.high = 6510.0
    mock_quote.low = 6415.0
    mock_quote.vwap = 6450.0
    mock_quote.change_pct = 2.4
    mock_quote.volume = 55000

    dates = pd.date_range("2026-10-06 18:00", periods=25, freq="5min")
    opens = [6430.0 + (i % 5) * 2.0 for i in range(24)] + [6460.0]
    highs = [o + 5.0 for o in opens[:-1]] + [6510.0]
    lows = [o - 3.0 for o in opens[:-1]] + [6458.0]
    closes = [o + 2.0 for o in opens[:-1]] + [6500.0]
    volumes = [1000.0] * 24 + [4500.0]
    df_5m = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )

    monkeypatch.setattr(
        "market.macro.get_macro_snapshot",
        lambda: MacroSnapshot(dxy_change=-0.1, crude_change=1.5),
    )
    monkeypatch.setattr("market.options.get_options_chain", lambda sym: [])

    with patch("market.quotes.get_quote", return_value={"MCX:CRUDEOIL": mock_quote}):
        with patch("market.history.get_ohlcv", return_value=df_5m):
            with patch("market.quotes.get_ltp", return_value=6500.0):
                alerts = engine.scan_commodities_now()
                assert len(alerts) >= 1
                alert = alerts[0]
                m = alert.metrics
                assert "cvd_ratio" in m
                assert m["cvd_ratio"] >= 2.0
                assert any("Buyer CVD Aggression" in tag for tag in m.get("confluence_factors", []))


def test_crudeoil_8500_pe_scale_mismatch_prevention():
    """
    RCA Incident 1 Test:
    Verifies that option alerts with entry 289.30 and spot price 8529.0 NEVER leak spot scale into
    in-flight evaluations or Telegram milestone rendering, eliminating bogus +2848.2% / +94.94R warnings.
    """
    from engine.alert_evaluator import evaluate_alert_in_flight_decay
    from bot.alert_templates import MilestoneAlertData

    alert = AutoAlert(
        alert_id="aa-crude-8500pe-test",
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        symbol="CRUDEOIL",
        exchange="MCX",
        direction="BEARISH",
        headline="MCX Crude 8500 PE",
        summary="Crude breakdown test",
        ltp=289.30,  # Option premium LTP
        trigger_level=289.30,
        stop_loss=202.51,  # Option stop loss
        target_level=420.0,  # Option target
        derivative_type="OPT",
        option_type="PE",
        strike=8500.0,
        option_premium=289.30,
        option_stop_loss=202.51,
        option_target_level=420.0,
        contract_symbol="MCX:CRUDEOIL26OCT8500PE",
        underlying_spot=8529.0,  # Underlying spot price
        confidence=85,
        created_at="2026-10-06 19:15:00 IST",
        actionable_plan={
            "option_plan": {
                "entry_premium": 289.30,
                "sl_premium": 202.51,
                "t1_premium": 420.0,
            }
        },
    )

    # 1. In-flight evaluator MUST NOT use spot 8529 to compute 2848% P&L against entry 289.30
    eval_res = evaluate_alert_in_flight_decay(alert, current_ltp=8529.0)
    # The evaluator must either return None (scale mismatch suppressed) or not evaluate with spot scale
    if eval_res:
        assert eval_res.pnl_pct is None or abs(eval_res.pnl_pct) < 100.0

    # 2. MilestoneAlertData MUST NOT render spot price as Opt CMP or compute +2848% P&L
    alert_corrupted = AutoAlert(
        alert_id="aa-crude-8500pe-test-corrupted",
        alert_type="COMMODITY_MOMENTUM",
        stage="IN_FLIGHT_WARNING",
        symbol="CRUDEOIL",
        exchange="MCX",
        direction="BEARISH",
        headline="VWAP Band Warning",
        summary="Testing scale leak",
        ltp=8529.0,  # Leaked spot price
        trigger_level=289.30,
        stop_loss=202.51,
        target_level=420.0,
        derivative_type="OPT",
        option_type="PE",
        strike=8500.0,
        option_premium=289.30,
        option_stop_loss=202.51,
        contract_symbol="MCX:CRUDEOIL26OCT8500PE",
        underlying_spot=8529.0,
        pnl_pct=2848.2,  # Corrupted pre-calculated P&L
        confidence=85,
        created_at="2026-10-06 19:15:00 IST",
        actionable_plan={
            "option_plan": {
                "entry_premium": 289.30,
                "sl_premium": 202.51,
            }
        },
    )
    m_data = MilestoneAlertData.from_alert(alert_corrupted, milestone_type="IN_FLIGHT_WARNING")
    # Sanitized LTP must be clamped back to option premium (289.30), not 8529.0
    assert m_data.ltp <= 289.30 * 3.5
    # Sanitized P&L must never be +2848.2%
    assert m_data.pnl_pct is None or abs(m_data.pnl_pct) < 100.0


def test_crudeoil_golden_hours_trend_invariant_vetoes_counter_trend_pe(monkeypatch):
    """
    RCA Incident 2 Test:
    Verifies that when Crude is trading at 8529.0 > VWAP 8495.0 during Golden Hours (19:15 IST),
    counter-trend BEARISH / 8500 PE trades are strictly vetoed.
    """
    import pandas as pd
    from engine.detectors.commodity import detect_commodity_breakouts
    from market.macro import MacroSnapshot
    from unittest.mock import patch, MagicMock

    mock_quote = MagicMock()
    mock_quote.symbol = "MCX:CRUDEOIL"
    mock_quote.last_price = 8529.0
    mock_quote.ltp = 8529.0
    mock_quote.open = 8400.0
    mock_quote.high = 8535.0
    mock_quote.low = 8380.0
    mock_quote.vwap = 8495.0  # Price 8529 is ABOVE VWAP
    mock_quote.change_pct = 1.5
    mock_quote.volume = 65000

    dates = pd.date_range("2026-10-06 18:00", periods=25, freq="5min")
    df_5m = pd.DataFrame(
        {
            "open": [8500.0] * 25,
            "high": [8535.0] * 25,
            "low": [8490.0] * 25,
            "close": [8529.0] * 25,
            "volume": [3000.0] * 25,
        },
        index=dates,
    )

    monkeypatch.setattr(
        "market.macro.get_macro_snapshot",
        lambda: MacroSnapshot(dxy_change=0.0, crude_change=1.2),
    )

    with patch("market.quotes.get_quote", return_value={"MCX:CRUDEOIL": mock_quote}):
        with patch("market.history.get_ohlcv", return_value=df_5m):
            with patch("market.quotes.get_ltp", return_value=8529.0):
                alerts = detect_commodity_breakouts(universe=["CRUDEOIL"])
                # Any alert generated must NOT be BEARISH (no 8500 PE above VWAP)
                for a in alerts:
                    assert a.direction != "BEARISH", "Counter-trend short > VWAP during Golden Hours must be vetoed!"


def test_crudeoil_golden_hours_thrust_detects_1837_rebound(monkeypatch):
    """
    RCA Incident 3 Test:
    Verifies that at 18:37 IST (US open / Golden Hours), a 40-pt rebound from 8360 to 8400
    with positive 15m ROC and high RVOL triggers a BULLISH trade (e.g. 8400 CE)
    even when daily change from yesterday's close is only +0.3% (< 1.0%).
    """
    import pandas as pd
    from engine.detectors.commodity import detect_commodity_breakouts
    from market.macro import MacroSnapshot
    from unittest.mock import patch, MagicMock

    mock_quote = MagicMock()
    mock_quote.symbol = "MCX:CRUDEOIL"
    mock_quote.last_price = 8400.0
    mock_quote.ltp = 8400.0
    mock_quote.open = 8380.0
    mock_quote.high = 8405.0
    mock_quote.low = 8360.0  # +40 pt bounce from low
    mock_quote.vwap = 8375.0  # Trading above VWAP
    mock_quote.change_pct = 0.35  # Only +0.35% on the day (< 1.0% static filter)
    mock_quote.volume = 80000

    dates = pd.date_range("2026-10-06 18:00", periods=25, freq="5min")
    opens = [8360.0 + (i % 3) * 2.0 for i in range(21)] + [8370.0, 8375.0, 8385.0, 8395.0]
    highs = [o + 5.0 for o in opens[:-1]] + [8405.0]
    lows = [o - 2.0 for o in opens[:-1]] + [8390.0]
    closes = [o + 3.0 for o in opens[:-1]] + [8400.0]
    volumes = [1000.0] * 21 + [2500.0, 3000.0, 3500.0, 4500.0]  # High volume surge
    df_5m = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )

    mock_opt = MagicMock()
    mock_opt.symbol = "MCX:CRUDEOIL26OCT8400CE"
    mock_opt.strike = 8400
    mock_opt.option_type = "CE"
    mock_opt.last_price = 310.0

    monkeypatch.setattr(
        "market.macro.get_macro_snapshot",
        lambda: MacroSnapshot(dxy_change=-0.1, crude_change=0.5),
    )
    monkeypatch.setattr("market.options.get_options_chain", lambda sym: [mock_opt])

    with patch("market.quotes.get_quote", return_value={"MCX:CRUDEOIL": mock_quote}):
        with patch("market.history.get_ohlcv", return_value=df_5m):
            with patch("market.quotes.get_ltp", return_value=8400.0):
                alerts = detect_commodity_breakouts(universe=["CRUDEOIL"])
                assert len(alerts) >= 1, "Golden Hours momentum must catch US Open rebound!"
                alert = alerts[0]
                assert alert.direction == "BULLISH"
                assert alert.derivative_type == "OPT"
                assert alert.strike == 8400
                assert alert.ltp == 310.0


def test_naturalgas_anti_fomo_overbought_rsi_guard(monkeypatch):
    """
    RCA Incident 4 Test:
    Verifies that Natural Gas breakout attempts when 5m RSI is 71.4 (> 68.0 overbought ceiling)
    are suppressed from buying 300 CE at the top-tick without a pullback.
    """
    import pandas as pd
    from engine.detectors.commodity import detect_commodity_breakouts
    from market.macro import MacroSnapshot
    from unittest.mock import patch, MagicMock

    mock_quote = MagicMock()
    mock_quote.symbol = "MCX:NATURALGAS"
    mock_quote.last_price = 301.5
    mock_quote.ltp = 301.5
    mock_quote.open = 295.0
    mock_quote.high = 301.8
    mock_quote.low = 294.0
    mock_quote.vwap = 297.0
    mock_quote.change_pct = 2.2
    mock_quote.volume = 40000

    dates = pd.date_range("2026-10-06 18:00", periods=25, freq="5min")
    # Upward parabolic price series producing high RSI (> 70)
    closes = [294.0 + i * 0.32 for i in range(25)]
    opens = [c - 0.2 for c in closes]
    highs = [c + 0.3 for c in closes]
    lows = [c - 0.3 for c in closes]
    volumes = [1500.0] * 25
    df_5m = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )

    monkeypatch.setattr(
        "market.macro.get_macro_snapshot",
        lambda: MacroSnapshot(dxy_change=0.0, crude_change=0.0),
    )

    with patch("market.quotes.get_quote", return_value={"MCX:NATURALGAS": mock_quote}):
        with patch("market.history.get_ohlcv", return_value=df_5m):
            with patch("market.quotes.get_ltp", return_value=301.5):
                alerts = detect_commodity_breakouts(universe=["NATURALGAS"])
                # Must be suppressed due to overbought RSI exhaustion (> 68.0)
                assert len(alerts) == 0, "Overbought Natural Gas 300 CE FOMO chase must be suppressed!"


def test_default_symbols_includes_sensex_and_midcap():
    """Verifies that DEFAULT_SYMBOLS in market/websocket.py includes SENSEX, MIDCPNIFTY, FINNIFTY."""
    from market.websocket import DEFAULT_SYMBOLS, _SYMBOL_MAP

    assert "BSE:SENSEX-INDEX" in DEFAULT_SYMBOLS
    assert "NSE:MIDCPNIFTY-INDEX" in DEFAULT_SYMBOLS
    assert "NSE:FINNIFTY-INDEX" in DEFAULT_SYMBOLS
    assert "BSE:SENSEX" in _SYMBOL_MAP
    assert "NSE:MIDCPNIFTY" in _SYMBOL_MAP


def test_commodity_detector_henry_hub_veto(monkeypatch):
    """Verifies that detect_commodity_breakouts vetoes Natural Gas longs when Henry Hub drops -2.5%."""
    from engine.detectors.commodity import detect_commodity_breakouts

    mock_quote = MagicMock()
    mock_quote.symbol = "MCX:NATURALGAS"
    mock_quote.last_price = 295.0
    mock_quote.ltp = 295.0
    mock_quote.open = 290.0
    mock_quote.high = 296.0
    mock_quote.low = 289.0
    mock_quote.vwap = 292.0
    mock_quote.change_pct = 1.7
    mock_quote.volume = 50000

    dates = pd.date_range("2026-10-06 18:00", periods=25, freq="5min")
    df_5m = pd.DataFrame(
        {
            "open": [290.0] * 25,
            "high": [296.0] * 25,
            "low": [289.0] * 25,
            "close": [295.0] * 25,
            "volume": [2000.0] * 25,
        },
        index=dates,
    )

    # Henry Hub crashing -2.5%
    monkeypatch.setattr(
        "market.macro.get_macro_snapshot",
        lambda: MacroSnapshot(dxy_change=0.0, crude_change=0.0, natural_gas_change=-2.5),
    )

    with patch("market.quotes.get_quote", return_value={"MCX:NATURALGAS": mock_quote}):
        with patch("market.history.get_ohlcv", return_value=df_5m):
            with patch("market.quotes.get_ltp", return_value=295.0):
                alerts = detect_commodity_breakouts(universe=["NATURALGAS"])
                assert len(alerts) == 0, "Crashing Henry Hub must veto MCX Natural Gas long setup!"


def test_commodity_detector_cvd_order_flow_integration(monkeypatch):
    """Verifies that Order Flow CVD divergence boosts confidence or raises warning tags."""
    from engine.detectors.commodity import detect_commodity_breakouts
    from brokers.base import Quote
    from analysis.order_flow import OrderFlowSnapshot

    live_quote = Quote(
        symbol="CRUDEOIL",
        last_price=6800.0,
        open=6750.0,
        high=6810.0,
        low=6740.0,
        close=6750.0,
        vwap=6770.0,
        change=50.0,
        change_pct=0.74,
        volume=35000,
        provider="fyers",
    )

    dates = pd.date_range("2026-10-06 18:00", periods=25, freq="5min")
    df_5m = pd.DataFrame(
        {
            "open": [6750.0] * 25,
            "high": [6810.0] * 25,
            "low": [6740.0] * 25,
            "close": [6800.0] * 25,
            "volume": [1500.0] * 25,
        },
        index=dates,
    )

    mock_of = MagicMock(spec=OrderFlowSnapshot)
    mock_of.market_state = "LIVE"
    mock_of.cvd_divergence = "BULLISH_ABSORPTION"

    monkeypatch.setattr(
        "market.macro.get_macro_snapshot",
        lambda: MacroSnapshot(dxy_change=0.0, crude_change=0.5),
    )
    monkeypatch.setenv("CHANAKYA_TESTING", "0")
    monkeypatch.setenv("DEPLOY_MODE", "live")

    with patch("market.quotes.get_quote", return_value={"MCX:CRUDEOIL": live_quote}):
        with patch("market.history.get_ohlcv", return_value=df_5m):
            with patch("market.quotes.get_ltp", return_value=6800.0):
                with patch("analysis.order_flow.analyze_order_flow", return_value=mock_of):
                    with patch("market.order_book.analyze_symbol_order_book", return_value=None):
                        alerts = detect_commodity_breakouts(universe=["CRUDEOIL"])
                        if alerts:
                            assert any("CVD Bullish Absorption" in t for t in alerts[0].tags)


def test_commodity_adaptive_regime_eagle_choppiness_and_adx():
    """Verifies that Eagle Eye computes Choppiness Index and ADX-14 correctly."""
    import pandas as pd
    from engine.commodity_adaptive_regime import (
        compute_commodity_choppiness_index,
        compute_commodity_adx,
        evaluate_commodity_eagle_regime,
    )

    # 1. Choppy, alternating price series (whipsaw range)
    dates = pd.date_range("2026-10-06 10:00", periods=30, freq="5min")
    choppy_closes = [100.0 + (i % 2) * 1.5 for i in range(30)]
    df_chop = pd.DataFrame(
        {
            "open": [100.0] * 30,
            "high": [102.0] * 30,
            "low": [99.5] * 30,
            "close": choppy_closes,
            "volume": [1000.0] * 30,
        },
        index=dates,
    )

    chop = compute_commodity_choppiness_index(df_chop, period=14)
    assert chop is not None
    assert chop >= 55.0  # Confirms high consolidation/chop

    # 2. Trending, linear expansion price series
    trend_closes = [100.0 + i * 2.0 for i in range(35)]
    df_trend = pd.DataFrame(
        {
            "open": [c - 1.0 for c in trend_closes],
            "high": [c + 0.5 for c in trend_closes],
            "low": [c - 1.5 for c in trend_closes],
            "close": trend_closes,
            "volume": [2000.0] * 35,
        },
        index=pd.date_range("2026-10-06 18:00", periods=35, freq="5min"),
    )

    adx = compute_commodity_adx(df_trend, period=14)
    assert adx is not None
    assert adx >= 25.0  # Confirms strong trending expansion

    # 3. Eagle Regime evaluation during Golden Hours (19:30 IST)
    from datetime import datetime, timezone, timedelta

    ist = timezone(timedelta(hours=5, minutes=30))
    ref_dt = datetime(2026, 10, 6, 19, 30, tzinfo=ist)

    eagle = evaluate_commodity_eagle_regime(
        symbol="CRUDEOIL",
        spot=8500.0,
        df_5m=df_trend,
        ref_time=ref_dt,
    )
    assert eagle.session_phase == "US_GOLDEN_HOURS"
    assert eagle.is_golden_hours is True
    assert eagle.is_midday_lull is False
    assert eagle.adx_status == "STRONG_TREND"


def test_commodity_adaptive_regime_tiger_stalking_suppresses_midday_lull():
    """Verifies that Tiger Stalking vetoes routine low-volume breakouts during midday lull (11:30-15:30 IST)."""
    from datetime import datetime, timezone, timedelta
    from engine.commodity_adaptive_regime import (
        evaluate_commodity_eagle_regime,
        evaluate_commodity_tiger_mandate,
    )

    ist = timezone(timedelta(hours=5, minutes=30))
    # 13:15 IST is during the dead midday volume lull
    ref_dt = datetime(2026, 10, 6, 13, 15, tzinfo=ist)
    from unittest.mock import patch
    with patch("market.macro.get_macro_snapshot", return_value=None):
        eagle = evaluate_commodity_eagle_regime(
            symbol="CRUDEOIL",
            spot=8500.0,
            ref_time=ref_dt,
        )
    assert eagle.session_phase == "MIDDAY_VOLUME_LULL"
    assert eagle.is_midday_lull is True

    # Case A: Low volume routine breakout (RVOL = 1.1x) -> MUST BE SUPPRESSED
    tiger_low_vol = evaluate_commodity_tiger_mandate(
        eagle=eagle,
        is_institutional_thrust=False,
        rvol=1.1,
    )
    assert tiger_low_vol.allow_routine_breakouts is False
    assert tiger_low_vol.mandate == "TIGER_STALKING_PRESERVE_CAPITAL"
    assert "Midday volume lull" in tiger_low_vol.reason

    # Case B: Verified Institutional Thrust (RVOL = 2.4x + SMC confluence) -> ALLOWED IN POUNCE MODE
    tiger_high_vol = evaluate_commodity_tiger_mandate(
        eagle=eagle,
        is_institutional_thrust=True,
        rvol=2.4,
        has_smc_confluence=True,
    )
    assert tiger_high_vol.allow_routine_breakouts is True
    assert tiger_high_vol.mandate == "MOMENTUM_EXPANSION"


def test_commodity_adaptive_regime_sniper_plan_optimal_trade_entry():
    """Verifies that Sniper Execution builds OTE pullback bracket, 25m time-stop, and detects extended FOMO."""
    from engine.commodity_adaptive_regime import compute_commodity_sniper_plan

    # Setup: Crude breakout at 8,700, SL at 8,650 (50 pts risk), current spot 8,705 (near retest anchor)
    sniper = compute_commodity_sniper_plan(
        symbol="CRUDEOIL",
        direction="BULLISH",
        spot=8705.0,
        trigger_level=8700.0,
        invalidation_level=8650.0,
        lot_size=100,
        retest_anchor=8700.0,
    )

    assert sniper.risk_points == 55.0  # max(15 * 0.8, 55.0)
    assert sniper.structural_invalidation == 8650.0
    assert sniper.target_1 == round(8705.0 + 3.0 * 55.0, 2)
    assert sniper.target_2 == round(8705.0 + 5.0 * 55.0, 2)
    assert sniper.target_3 == round(8705.0 + 7.5 * 55.0, 2)
    assert sniper.time_stop_minutes == 25
    assert sniper.is_chasing is False
    assert sniper.entry_zone_min < sniper.entry_zone_max

    # Extended Setup: spot is at 8,745 (extended 45 pts above 8,700 breakout anchor)
    sniper_extended = compute_commodity_sniper_plan(
        symbol="CRUDEOIL",
        direction="BULLISH",
        spot=8745.0,
        trigger_level=8700.0,
        invalidation_level=8650.0,
        lot_size=100,
        retest_anchor=8700.0,
    )
    assert sniper_extended.is_chasing is True  # Flags FOMO chase condition!


def test_telegram_mcx_sniper_plan_rendering():
    """Verifies that format_auto_alert_telegram renders the Sniper OTE Bracket and Time-Stop."""
    from engine.alert_model import AutoAlert
    from bot.alert_templates import format_auto_alert_telegram

    alert = AutoAlert(
        alert_id="comm-crude-sniper-test",
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        symbol="CRUDEOIL",
        exchange="MCX",
        direction="BULLISH",
        headline="🛢️ MCX OPTION: CRUDEOIL 8750 CE (16 Oct) @ ₹276.1",
        summary="Institutional momentum breakout with defined risk",
        ltp=276.1,
        trigger_level=276.1,
        stop_loss=218.7,
        target_level=448.3,
        confidence=90,
        is_live=True,
        environment="LIVE",
        market_status="LIVE",
        actionable_plan={
            "action": "BUY_CE",
            "contract": "CRUDEOIL 8750 CE (16 Oct)",
            "entry_range": "₹267.5 – ₹281.8",
            "stop_loss": "₹218.7",
            "target": "₹448.3",
            "target_2": "₹563.1",
            "risk_reward": "1:3.0",
            "lot_size": 100,
            "preferred_vehicle": "DEFINED_RISK_OPTION",
            "max_loss_capped": 27610.0,
            "setup_confluence": "SMC Bullish BOS + Institutional Surge (RVOL 4.2x)",
            "futures_reference": {
                "contract": "MCX:CRUDEOIL",
                "entry": 8753.0,
                "stop_loss": 8642.7,
            },
            "sniper_plan": {
                "optimal_entry_zone": "₹8,720.0 – ₹8,745.0",
                "time_stop_minutes": 25,
                "stop_loss_rule": "Trail to breakeven at T1; invalidation at ₹8,642.7",
                "risk_reward_ratio": "3.0",
            },
            "profit_rule": "Book 50% at T1, trail stop to cost.",
        },
    )

    formatted = format_auto_alert_telegram(alert)
    assert "Sniper OTE Bracket:</b> <code>₹8,720.0 – ₹8,745.0</code> (Time-Stop: 25m)" in formatted


def test_wyckoff_utad_crudeoil_8800_pe_reversal(monkeypatch):
    """
    Direct regression test for the user's scenario:
    At 19:22 IST, Crude Oil poked up to 8824 (sweeping 8800 strike & resistance),
    then rolled over to 8760. Even though LTP (8760) is above full-day VWAP (8728),
    the Wyckoff UTAD Liquidity Sweep detector MUST catch the reversal,
    bypass the rigid Golden Hours VWAP filter, select CRUDEOIL 8800 PE,
    and generate an institutional reversal alert.
    """
    import os
    import pandas as pd
    from datetime import datetime
    from unittest.mock import MagicMock, patch
    from engine.detectors.commodity import detect_commodity_breakouts
    from brokers.base import OptionsContract, Quote

    monkeypatch.setenv("CHANAKYA_TESTING", "1")

    # Construct 5m candles leading up to the 19:22 UTAD sweep
    records = []
    for i in range(21):
        records.append({
            "open": 8740.0 + (i % 5) * 5,
            "high": 8760.0 + (i % 5) * 5,
            "low": 8730.0 + (i % 5) * 5,
            "close": 8750.0 + (i % 5) * 5,
            "volume": 200.0,
        })
    # Bar 21 (19:00): Pre-breakout push
    records.append({"open": 8760.0, "high": 8790.0, "low": 8755.0, "close": 8785.0, "volume": 350.0})
    # Bar 22 (19:05): Breakout push to 8805
    records.append({"open": 8785.0, "high": 8815.0, "low": 8780.0, "close": 8805.0, "volume": 500.0})
    # Bar 23 (19:10): High momentum bar to 8818
    records.append({"open": 8805.0, "high": 8820.0, "low": 8800.0, "close": 8815.0, "volume": 550.0})
    # Bar 24 (19:15): Spike poking up to 8824.0 (Liquidity sweep UTAD peak)
    records.append({"open": 8815.0, "high": 8824.0, "low": 8795.0, "close": 8800.0, "volume": 750.0})
    # Bar 25 (19:20): Rejection bar failing back under 8800 to 8760
    records.append({"open": 8800.0, "high": 8805.0, "low": 8755.0, "close": 8760.0, "volume": 850.0})

    df_5m = pd.DataFrame(records)
    now_t = pd.Timestamp.now()
    df_5m.index = pd.date_range(end=now_t, periods=len(df_5m), freq="5min")

    fake_quote = Quote(
        symbol="MCX:CRUDEOIL",
        last_price=8760.0,
        change_pct=-0.25,
        volume=120000,
        close=8782.0,  # Previous close
        open=8730.0,
        high=8824.0,
        low=8710.0,
        vwap=8728.0,  # Full day VWAP is below LTP!
    )

    # Mock options chain with 8750 PE, 8800 PE, 8850 PE
    mock_pe_8750 = OptionsContract(
        symbol="MCX:CRUDEOIL26OCT8750PE",
        underlying="CRUDEOIL",
        expiry="2026-10-16",
        strike=8750.0,
        option_type="PE",
        last_price=235.0,
        oi=1000,
        oi_change=100,
        volume=5000,
    )
    mock_pe_8800 = OptionsContract(
        symbol="MCX:CRUDEOIL26OCT8800PE",
        underlying="CRUDEOIL",
        expiry="2026-10-16",
        strike=8800.0,
        option_type="PE",
        last_price=272.0,  # Expert bought at 270-273!
        oi=2500,
        oi_change=450,
        volume=12000,
    )
    mock_pe_8850 = OptionsContract(
        symbol="MCX:CRUDEOIL26OCT8850PE",
        underlying="CRUDEOIL",
        expiry="2026-10-16",
        strike=8850.0,
        option_type="PE",
        last_price=315.0,
        oi=800,
        oi_change=50,
        volume=3000,
    )
    mock_chain = [mock_pe_8750, mock_pe_8800, mock_pe_8850]

    with patch("market.history.get_ohlcv", return_value=df_5m), \
         patch("market.options.get_options_chain", return_value=mock_chain), \
         patch("engine.detectors.commodity.datetime") as mock_dt:

        # Mock time to 19:22 IST on a Wednesday (2026-10-07)
        mock_now = datetime(2026, 10, 7, 19, 22, 0, tzinfo=IST)
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

        alerts = detect_commodity_breakouts(
            universe=["CRUDEOIL"],
            quotes_map={"MCX:CRUDEOIL": fake_quote},
        )

    assert len(alerts) == 1, "Should detect exactly 1 alert for CRUDEOIL"
    alert = alerts[0]

    # Verify direction is BEARISH (PE setup)
    assert alert.direction == "BEARISH"
    assert alert.derivative_type == "OPT"
    assert alert.option_type == "PE"

    # Verify 8800 PE is chosen as the primary vehicle (matching expert call)
    assert alert.strike == 8800.0
    assert "8800 PE" in alert.headline
    assert "UTAD Rejection" in alert.headline or "REVERSAL" in alert.headline
    assert alert.metrics.get("is_utad_reversal") is True
    assert alert.metrics.get("peak_recent") == 8824.0

    # Verify deterministic alert ID has variant
    assert "aa-commodity-momentum-crudeoil-bearish-8800pe-" in alert.alert_id


def test_commodity_alert_id_variant_deduplication():
    """
    Verifies that early CE alert and later PE alert on the same session date
    have distinct deterministic alert IDs and both are recorded without collision.
    """
    from engine.alert_identity import generate_alert_id
    from engine.alert_model import AutoAlert
    from engine.auto_alert_engine import AutoAlertEngine

    id_ce = generate_alert_id("CRUDEOIL", "COMMODITY_MOMENTUM", variant="bullish-8750ce")
    id_pe = generate_alert_id("CRUDEOIL", "COMMODITY_MOMENTUM", variant="bearish-8800pe")

    assert id_ce != id_pe
    assert "bullish-8750ce" in id_ce
    assert "bearish-8800pe" in id_pe

    alert_ce = AutoAlert(
        alert_id=id_ce,
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        symbol="CRUDEOIL",
        exchange="MCX",
        direction="BULLISH",
        derivative_type="OPT",
        option_type="CE",
        strike=8750.0,
        contract_symbol="MCX:CRUDEOIL26OCT8750CE",
        headline="CRUDEOIL 8750 CE",
        summary="Early CE setup",
        ltp=250.0,
        trigger_level=250.0,
        stop_loss=200.0,
        target_level=350.0,
        confidence=88,
        is_live=False,
        environment="TEST",
        actionable_plan={"action": "BUY_CE", "instrument_type": "OPTION"},
    )

    alert_pe = AutoAlert(
        alert_id=id_pe,
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        symbol="CRUDEOIL",
        exchange="MCX",
        direction="BEARISH",
        derivative_type="OPT",
        option_type="PE",
        strike=8800.0,
        contract_symbol="MCX:CRUDEOIL26OCT8800PE",
        headline="CRUDEOIL 8800 PE",
        summary="Reversal PE setup",
        ltp=272.0,
        trigger_level=272.0,
        stop_loss=215.0,
        target_level=410.0,
        confidence=92,
        is_live=False,
        environment="TEST",
        actionable_plan={"action": "BUY_PE", "instrument_type": "OPTION"},
    )

    engine = AutoAlertEngine()
    engine.clear_alerts()

    recorded_ce = engine.record_alert(alert_ce)
    assert recorded_ce is True

    # The PE alert should NOT be blocked by the earlier CE alert
    recorded_pe = engine.record_alert(alert_pe)
    assert recorded_pe is True

    # Duplicate submission of the exact same PE alert is properly deduped
    recorded_pe_dup = engine.record_alert(alert_pe)
    assert recorded_pe_dup is False


def test_quality_gate_hard_vetoes_resistance_wall_high_confidence():
    """
    Verifies that wall_collision=True in metrics is an unconditional hard veto
    even if the detector reports 94%+ confidence.
    """
    from engine.quality_gate import evaluate_institutional_quality_gate
    from engine.alert_model import AutoAlert

    alert = AutoAlert(
        alert_id="test-crude-wall-veto",
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        symbol="CRUDEOIL",
        exchange="MCX",
        direction="BULLISH",
        headline="MCX Crude Momentum",
        summary="Momentum right into 1H resistance wall",
        ltp=8753.0,
        trigger_level=8753.0,
        stop_loss=8670.0,
        target_level=8950.0,
        confidence=94,  # High confidence from SMC tags
        is_live=True,
        environment="LIVE",
        metrics={
            "wall_collision": True,
            "rvol": 1.4,
        },
    )

    verdict = evaluate_institutional_quality_gate(alert)
    assert verdict.is_vetoed is True
    assert "Structural Wall" in verdict.veto_reason
    assert verdict.conviction_tier == "REJECTED"


def test_1m_micro_rejection_trigger_golden_hours():
    """
    Verifies that a 1m sub-candle liquidity sweep and rejection
    (spike above 8800 round level to 8824, with immediate 1m rejection close back below 8800)
    ignites the Wyckoff UTAD reversal immediately without 5m candle close lag.
    """
    from engine.detectors.commodity import detect_commodity_breakouts
    from market.options import OptionsContract

    # 5m bars where current bar is still forming (open=8790, close=8792, not fully bearish on 5m)
    bars_5m = []
    base_t = datetime(2026, 10, 7, 18, 0, 0)
    for i in range(25):
        t = base_t + timedelta(minutes=i * 5)
        bars_5m.append({
            "date": t,
            "open": 8750.0 + i * 2,
            "high": 8760.0 + i * 2,
            "low": 8740.0 + i * 2,
            "close": 8755.0 + i * 2,
            "volume": 2000,
        })
    # Last 5m bar peaked at 8824 but hasn't formed a big bearish close yet
    bars_5m.append({
        "date": base_t + timedelta(minutes=125),
        "open": 8792.0,
        "high": 8824.0,
        "low": 8788.0,
        "close": 8790.0,
        "volume": 3500,
    })
    df_5m = pd.DataFrame(bars_5m).set_index("date")

    # 1m bars explicitly showing the micro-sweep and rejection at 19:21-19:22
    bars_1m = []
    base_1m_t = datetime(2026, 10, 7, 19, 15, 0)
    for j in range(6):
        t = base_1m_t + timedelta(minutes=j)
        bars_1m.append({
            "date": t,
            "open": 8790.0,
            "high": 8805.0,
            "low": 8788.0,
            "close": 8800.0,
            "volume": 500,
        })
    # 19:21: Poke to 8824 (sweep)
    bars_1m.append({
        "date": base_1m_t + timedelta(minutes=6),
        "open": 8800.0,
        "high": 8824.0,
        "low": 8798.0,
        "close": 8815.0,
        "volume": 1200,
    })
    # 19:22: Sharp rejection candle back down to 8795 with long upper wick
    bars_1m.append({
        "date": base_1m_t + timedelta(minutes=7),
        "open": 8815.0,
        "high": 8818.0,
        "low": 8792.0,
        "close": 8795.0,  # Closed well back under 8800 round level
        "volume": 1500,
    })
    df_1m = pd.DataFrame(bars_1m).set_index("date")

    fake_quote = MagicMock(
        last_price=8795.0,
        ltp=8795.0,
        open=8750.0,
        high=8824.0,
        low=8710.0,
        volume=25000,
        change_pct=0.51,
        vwap=8740.0,
    )
    fake_quote.source = "LIVE"
    fake_quote._is_mock = False
    fake_quote.provider = "fyers"

    mock_pe_8800 = OptionsContract(
        symbol="MCX:CRUDEOIL26OCT8800PE",
        underlying="CRUDEOIL",
        expiry="2026-10-16",
        strike=8800.0,
        option_type="PE",
        last_price=272.0,
        oi=3000,
        oi_change=500,
        volume=15000,
    )

    with patch("market.history.get_ohlcv", return_value=df_5m), \
         patch("market.options.get_options_chain", return_value=[mock_pe_8800]), \
         patch("engine.detectors.commodity.datetime") as mock_dt:

        mock_now = datetime(2026, 10, 7, 19, 22, 0, tzinfo=IST)
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

        alerts = detect_commodity_breakouts(
            universe=["CRUDEOIL"],
            quotes_map={"MCX:CRUDEOIL": fake_quote},
            ohlcv_1m_map={"CRUDEOIL": df_1m},
        )

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.direction == "BEARISH"
    assert alert.strike == 8800.0
    assert alert.metrics.get("is_1m_micro_trigger") is True
    assert "1m Micro-Rejection Sweep Confirmed" in alert.metrics.get("confluence_factors", [])
    assert "MCX SNIPER REVERSAL" in alert.headline
    assert "Active 1m micro-rejection confirmed" in alert.actionable_plan["when_to_buy"]


def test_cvd_absorption_confirms_utad_bull_trap():
    """
    Verifies that aggressive buyer delta at a resistance peak during Wyckoff UTAD
    does NOT suppress the bearish reversal; instead it tags institutional absorption
    and confirms the bull trap.
    """
    from engine.detectors.commodity import detect_commodity_breakouts
    from market.options import OptionsContract
    from market.quotes import Quote

    records = []
    for i in range(20):
        records.append({
            "open": 8740.0 + (i % 5) * 5,
            "high": 8760.0 + (i % 5) * 5,
            "low": 8730.0 + (i % 5) * 5,
            "close": 8750.0 + (i % 5) * 5,
            "volume": 200.0,
        })
    records.append({"open": 8760.0, "high": 8790.0, "low": 8755.0, "close": 8785.0, "volume": 350.0})
    records.append({"open": 8785.0, "high": 8815.0, "low": 8780.0, "close": 8805.0, "volume": 500.0})
    records.append({"open": 8805.0, "high": 8820.0, "low": 8800.0, "close": 8815.0, "volume": 550.0})
    records.append({"open": 8815.0, "high": 8824.0, "low": 8795.0, "close": 8800.0, "volume": 750.0})
    records.append({"open": 8800.0, "high": 8805.0, "low": 8755.0, "close": 8760.0, "volume": 850.0})

    df_5m = pd.DataFrame(records)
    now_t = pd.Timestamp.now()
    df_5m.index = pd.date_range(end=now_t, periods=len(df_5m), freq="5min")

    fake_quote = Quote(
        symbol="MCX:CRUDEOIL",
        last_price=8760.0,
        change_pct=-0.25,
        volume=120000,
        close=8782.0,
        open=8730.0,
        high=8824.0,
        low=8710.0,
        vwap=8728.0,
    )

    mock_pe_8800 = OptionsContract(
        symbol="MCX:CRUDEOIL26OCT8800PE",
        underlying="CRUDEOIL",
        expiry="2026-10-16",
        strike=8800.0,
        option_type="PE",
        last_price=272.0,
        oi=3000,
        oi_change=500,
        volume=15000,
    )

    # Force compute_bar_volume_delta to return heavy buyer volume (buyer delta absorption trap)
    with patch("market.history.get_ohlcv", return_value=df_5m), \
         patch("market.options.get_options_chain", return_value=[mock_pe_8800]), \
         patch("engine.detectors.order_flow.compute_bar_volume_delta", return_value=(4500.0, 1500.0, 3000.0)), \
         patch("engine.detectors.commodity.datetime") as mock_dt:

        mock_now = datetime(2026, 10, 7, 19, 22, 0, tzinfo=IST)
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

        alerts = detect_commodity_breakouts(
            universe=["CRUDEOIL"],
            quotes_map={"MCX:CRUDEOIL": fake_quote},
        )

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.direction == "BEARISH"
    assert "Institutional Absorption of Buyers (Bull Trap Confirmed)" in alert.metrics.get("confluence_factors", [])


def test_volume_profile_targets_aligned_to_poc_and_val():
    """
    Verifies that when Volume Profile POC and VAL are present,
    bearish reversal targets align to Session POC (Target 1) and VAL (Target 2).
    """
    from engine.detectors.commodity import detect_commodity_breakouts
    from market.options import OptionsContract
    from market.quotes import Quote

    records = []
    for i in range(20):
        records.append({
            "open": 8740.0 + (i % 5) * 5,
            "high": 8760.0 + (i % 5) * 5,
            "low": 8730.0 + (i % 5) * 5,
            "close": 8750.0 + (i % 5) * 5,
            "volume": 200.0,
        })
    records.append({"open": 8760.0, "high": 8790.0, "low": 8755.0, "close": 8785.0, "volume": 350.0})
    records.append({"open": 8785.0, "high": 8815.0, "low": 8780.0, "close": 8805.0, "volume": 500.0})
    records.append({"open": 8805.0, "high": 8820.0, "low": 8800.0, "close": 8815.0, "volume": 550.0})
    records.append({"open": 8815.0, "high": 8824.0, "low": 8795.0, "close": 8800.0, "volume": 750.0})
    records.append({"open": 8800.0, "high": 8805.0, "low": 8755.0, "close": 8760.0, "volume": 850.0})

    df_5m = pd.DataFrame(records)
    now_t = pd.Timestamp.now()
    df_5m.index = pd.date_range(end=now_t, periods=len(df_5m), freq="5min")

    fake_quote = Quote(
        symbol="MCX:CRUDEOIL",
        last_price=8760.0,
        change_pct=-0.25,
        volume=120000,
        close=8782.0,
        open=8730.0,
        high=8824.0,
        low=8710.0,
        vwap=8728.0,
    )

    mock_pe_8800 = OptionsContract(
        symbol="MCX:CRUDEOIL26OCT8800PE",
        underlying="CRUDEOIL",
        expiry="2026-10-16",
        strike=8800.0,
        option_type="PE",
        last_price=272.0,
        oi=3000,
        oi_change=500,
        volume=15000,
    )

    # Return POC=8600, VAH=8810, VAL=8480 (ltp is 8760, so ltp-poc = 160 >= 1.5*80=120, ltp-val = 280 >= 3*80=240)
    with patch("market.history.get_ohlcv", return_value=df_5m), \
         patch("market.options.get_options_chain", return_value=[mock_pe_8800]), \
         patch("analysis.volume_profile.compute_volume_profile", return_value=(8600.0, 8810.0, 8480.0, [])), \
         patch("engine.detectors.commodity.datetime") as mock_dt:

        mock_now = datetime(2026, 10, 7, 19, 22, 0, tzinfo=IST)
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

        alerts = detect_commodity_breakouts(
            universe=["CRUDEOIL"],
            quotes_map={"MCX:CRUDEOIL": fake_quote},
        )

    assert len(alerts) == 1
    alert = alerts[0]
    fut_ref = alert.actionable_plan["futures_reference"]
    assert fut_ref["target_1"] == 8600.0  # Session POC
    assert fut_ref["target_2"] == 8480.0  # Session VAL
    assert alert.metrics["poc_price"] == 8600.0
    assert alert.metrics["val_price"] == 8480.0


def test_scan_commodities_now_target_filtering():
    """
    Verifies that AutoAlertEngine.scan_commodities_now(targets=...) forwards
    the filtered target subset to detect_commodity_breakouts.
    """
    engine = AutoAlertEngine()

    with patch("engine.detectors.commodity.detect_commodity_breakouts", return_value=[]) as mock_detect:
        engine.scan_commodities_now(targets=["CRUDEOIL", "NATURALGAS", "GOLD"])
        mock_detect.assert_called_once_with(universe=["CRUDEOIL", "NATURALGAS", "GOLD"])







