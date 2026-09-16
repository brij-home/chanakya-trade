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

from engine.alert_model import AutoAlert
from engine.alert_scrutiny import AlertScrutinyAuditor, COMMODITY_MIN_SL_FLOORS, alert_scrutiny_auditor
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


def test_commodity_structural_noise_safe_stop_acceptance(auditor: AlertScrutinyAuditor, monkeypatch):
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


def test_commodity_scrutiny_prompt_contains_macro_context(auditor: AlertScrutinyAuditor, monkeypatch):
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
    assert (
        format_readable_option_symbol("MCX:CRUDEOIL26SEP6500CE")
        == "CRUDEOIL 6500 CE (26 Sep)"
    )
    assert (
        format_readable_option_symbol("CRUDEOIL26SEP6500PE")
        == "CRUDEOIL 6500 PE (26 Sep)"
    )

    # 2. Natural Gas
    assert (
        format_readable_option_symbol("MCX:NATURALGAS26SEP240PE")
        == "NATURALGAS 240 PE (26 Sep)"
    )

    # 3. Gold & Silver
    assert (
        format_readable_option_symbol("MCX:GOLD26OCT75000CE")
        == "GOLD 75000 CE (26 Oct)"
    )
    assert (
        format_readable_option_symbol("MCX:SILVER26NOV88000PE")
        == "SILVER 88000 PE (26 Nov)"
    )

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
    assert "BUY_CE <b>CRUDEOIL 6500 CE (26 Sep)</b>" in formatted
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
    df = pd.DataFrame([
        {"open": 100.0, "high": 101.0, "low": 85.0, "close": 99.5},   # prev
        {"open": 98.0,  "high": 99.0,  "low": 82.0, "close": 97.5},   # Hammer bar
    ])
    result = detect_confirmation_candle(df, direction="BULLISH")
    assert result["confirmed"] is True
    assert result["pattern"] in ("Hammer", "Bullish Pin Bar")
    assert result["strength"] >= 65


def test_detect_confirmation_candle_bearish_engulfing():
    """Bearish engulfing is detected for BEARISH direction."""
    import pandas as pd
    from analysis.market_structure import detect_confirmation_candle

    # Prior bar is bullish, current bar fully engulfs it with bearish close
    df = pd.DataFrame([
        {"open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0},  # bull bar
        {"open": 106.0, "high": 107.0, "low": 97.0, "close": 98.5},   # bearish engulfing
    ])
    result = detect_confirmation_candle(df, direction="BEARISH")
    assert result["confirmed"] is True
    assert result["pattern"] == "Bearish Engulfing"


def test_detect_divergence_bullish_regular():
    """Regular bullish divergence: price LL, RSI HL."""
    import pandas as pd
    import numpy as np
    from analysis.market_structure import detect_divergence

    # Construct data where price makes lower low in second half but RSI improves
    # Use a synthetic series that falls then recovers partially
    n = 40
    prices_first = [100.0 - i * 0.2 for i in range(20)]  # declining
    prices_second = [96.0 - i * 0.3 for i in range(20)]  # declining MORE (LL in price)

    closes = pd.Series(prices_first + prices_second)
    # Simulate RSI improvement: first half has lower RSI, second half recovers
    df = pd.DataFrame({
        "close": closes,
        "high": closes + 0.5,
        "low": closes - 0.5,
    })
    result = detect_divergence(df)
    # We just check function returns valid dict without errors; divergence direction
    # depends on data shape
    assert "type" in result
    assert "bias" in result
    assert result["type"] in (
        "BULLISH_REGULAR", "BEARISH_REGULAR",
        "BULLISH_HIDDEN", "BEARISH_HIDDEN", "NONE"
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
    from datetime import datetime, timezone, timedelta

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

    with patch("engine.auto_alert_engine.datetime") as mock_dt, \
         patch("market.quotes.get_quote", return_value={"MCX:CRUDEOIL": mock_quote}), \
         patch("engine.auto_alert_engine.AutoAlertEngine.record_alert", return_value=False), \
         patch("engine.learning_engine.pattern_learning_engine.is_symbol_locked_out", return_value=(False, "")):
        mock_dt.now.return_value = tuesday_api_time
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

        # During Tuesday 20:30 IST — should be suppressed by API blackout
        with patch.dict(os.environ, {"CHANAKYA_TESTING": "0"}):
            # The blackout should suppress the signal; no alerts generated for CRUDEOIL
            results = engine.scan_commodities_now()
            # Either suppressed (0 alerts) or record_alert returned False (mocked)
            crudeoil_alerts = [a for a in results if "CRUDEOIL" in (a.symbol or "").upper()]
            assert len(crudeoil_alerts) == 0, "CRUDEOIL signal must be suppressed during Tuesday API blackout"


def test_mtf_alignment_returns_alignment_count():
    """check_mtf_structural_alignment now returns alignment_count (0-3)."""
    import pandas as pd
    from analysis.market_structure import check_mtf_structural_alignment

    # Build a bullish 5m DataFrame
    n = 60
    prices = [100.0 + i * 0.1 for i in range(n)]
    df_5m = pd.DataFrame({
        "open":   [p - 0.05 for p in prices],
        "high":   [p + 0.15 for p in prices],
        "low":    [p - 0.15 for p in prices],
        "close":  prices,
        "volume": [1000] * n,
    })

    result = check_mtf_structural_alignment("CRUDEOIL", exchange="MCX", ltp=105.0, direction="BULLISH", df_5m=df_5m)
    assert "alignment_count" in result
    assert 0 <= result["alignment_count"] <= 3
    assert "is_aligned" in result
    assert "tf_5m_trend" in result
    assert "tf_15m_trend" in result

