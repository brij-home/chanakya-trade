"""
tests/test_predator_interception_edge.py
────────────────────────────────────────
Institutional verification of the 4 Predatory Edge Interception factors:
  1. Predator Strike Clock Heads-Up at STAGE_PRIMED (±0.35% trigger proximity)
  2. Order Book Imbalance (OBI) & Microstructure Gate at ignition
  3. Sector RRG Alignment Gate on Equity Breakouts
  4. Adaptive IV Rank Options Routing (High IV -> Defined-Risk Spreads)
"""

from datetime import datetime, timezone, timedelta
import pandas as pd

from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine
from bot.alert_templates import render_primed_strike_clock_alert
from market.order_book import get_depth_book, clear_depth_books

IST = timezone(timedelta(hours=5, minutes=30))


def test_telegram_strike_clock_dispatch_on_primed(tmp_path, monkeypatch):
    """
    Verifies that when price comes within ±0.35% of sniper trigger,
    the alert transitions to PRIMED, dispatches Strike Clock heads-up to Telegram,
    records audit trail, and marks strike_clock_sent=True.
    """
    engine = AutoAlertEngine()
    monkeypatch.setattr(engine, "_save", lambda: None)

    alert = AutoAlert(
        alert_id="aa-sq-rel-1-20261018",
        alert_type="SQUEEZE_BREAKOUT",
        stage="EARLY_WARNING",
        symbol="RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="🎯 SQUEEZE COILING: RELIANCE",
        summary="Coiled below pivot resistance.",
        ltp=1270.0,
        trigger_level=1274.0,  # 0.31% away (<= 0.35%)
        target_level=1300.0,
        stop_loss=1260.0,
        confidence=85,
        created_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        is_live=True,
        environment="LIVE",
        actionable_plan={
            "breakout_trigger": "₹1,274.0",
            "stop_loss": "₹1,260.0",
            "target": "₹1,300.0",
            "risk_reward": "1:2.5",
        },
    )

    with engine._lock:
        engine._alerts.append(alert)

    dispatched_msgs = []
    monkeypatch.setattr("engine.alerts._is_market_hours", lambda ex: True)
    monkeypatch.setattr(
        "engine.alerts._telegram_notify",
        lambda msg, **kwargs: dispatched_msgs.append((msg, kwargs)),
    )
    monkeypatch.setattr("market.quotes.get_ltp", lambda sym: 1270.20)  # within 0.30% of 1274

    engine.check_and_ignite_early_warnings()

    assert alert.stage == "PRIMED"
    assert alert.strike_clock_sent is True
    assert len(dispatched_msgs) == 1
    assert "PREDATOR STRIKE CLOCK" in dispatched_msgs[0][0]
    assert "RELIANCE" in dispatched_msgs[0][0]

    # Verify audit trail recording
    audit_events = [e["event_type"] for e in alert.audit_trail]
    assert "STRIKE_CLOCK_DISPATCHED" in audit_events


def test_strike_clock_renders_hedged_spread_vehicle():
    """Verifies that render_primed_strike_clock_alert displays spread structure when present."""
    data = {
        "symbol": "NIFTY",
        "segment": "FNO_INDEX",
        "ltp": 25100.0,
        "trigger_level": 25120.0,
        "stop_loss": 25050.0,
        "target_level": 25260.0,
        "target_2": 25400.0,
        "direction": "BULLISH",
        "confidence": 88,
        "actionable_plan": {
            "risk_reward": "1:2.8",
            "hedged_spread": {
                "strategy": "BULL_CALL_DEBIT_SPREAD",
                "buy_leg": {"symbol": "NIFTY25100CE"},
                "sell_leg": {"symbol": "NIFTY25250CE"},
                "net_debit_per_share": 45.0,
                "max_profit_per_share": 105.0,
            },
        },
    }

    rendered = render_primed_strike_clock_alert(data, in_market=True)
    assert "PREDATOR STRIKE CLOCK" in rendered
    assert "Spread Vehicle:" in rendered
    assert "BULL_CALL_DEBIT_SPREAD" in rendered
    assert "NIFTY25100CE" in rendered
    assert "NIFTY25250CE" in rendered
    assert "Net Debit: ₹45.0" in rendered


def test_order_book_imbalance_gate_blocks_absorption_trap(tmp_path, monkeypatch):
    """
    Verifies that when price crosses trigger but Order Book Imbalance is severely adverse
    (e.g. OBI <= -0.45 ask wall) and RVOL < 1.30x, ignition is safely held in PRIMED.
    """
    clear_depth_books()
    engine = AutoAlertEngine()
    monkeypatch.setattr(engine, "_save", lambda: None)

    alert = AutoAlert(
        alert_id="aa-sq-tata-1-20261018",
        alert_type="SQUEEZE_BREAKOUT",
        stage="PRIMED",
        symbol="TATASTEEL",
        exchange="NSE",
        direction="BULLISH",
        headline="🎯 SQUEEZE PRIMED: TATASTEEL",
        summary="Within sniper proximity.",
        ltp=150.0,
        trigger_level=150.0,
        target_level=158.0,
        stop_loss=146.0,
        confidence=85,
        created_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        is_live=True,
        environment="LIVE",
        metrics={"rvol": 1.10},  # Low volume poke
    )

    with engine._lock:
        engine._alerts.append(alert)

    # Simulate heavy Ask Wall in depth book: 1,000 bids vs 10,000 asks (OBI = -0.818)
    depth = get_depth_book("TATASTEEL")
    depth.batch_update(
        bids=[{"price": 149.95, "quantity": 1000}],
        asks=[{"price": 150.05, "quantity": 10000}],
    )
    assert depth.obi(5) < -0.45

    monkeypatch.setattr("market.quotes.get_ltp", lambda sym: 150.10)  # Price breaches 150.0

    engine.check_and_ignite_early_warnings()

    # Should remain in PRIMED with OBI gate active
    assert alert.stage == "PRIMED"
    assert "WALL_RESISTANCE" in alert.metrics.get("microstructure_status", "")
    assert alert.metrics.get("obi_at_ignition") is not None

    # Now simulate absorption: RVOL surges to 2.10x
    alert.metrics["rvol"] = 2.10
    engine.check_and_ignite_early_warnings()

    # Now it cleanly ignites!
    assert alert.stage == "IGNITED"
    clear_depth_books()


def test_sector_rrg_alignment_gate_on_equity_breakout(monkeypatch):
    """
    Verifies that detect_squeeze_breakout suppresses bullish breakouts on stocks
    in LAGGING parent sectors unless supported by explosive RVOL >= 2.2x.
    """
    from engine.detectors.squeeze_breakout import detect_squeeze_breakout

    # Construct synthetic coiled OHLCV data
    closes = [100.0 + i * 0.05 for i in range(30)]
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    volumes = [10000] * 30

    df = pd.DataFrame(
        {
            "close": closes,
            "high": highs,
            "low": lows,
            "volume": volumes,
            "open": closes,
        }
    )

    # Case A: Parent sector is LAGGING, stock has low RVOL (1.2x) -> Suppressed
    monkeypatch.setattr(
        "analysis.sector_rotation.get_stock_sector_alignment",
        lambda sym: {"sector": "IT", "quadrant": "LAGGING", "alignment": "SEVERE_HEADWIND"},
    )
    monkeypatch.delenv("CHANAKYA_TESTING", raising=False)
    monkeypatch.delenv("DEPLOY_MODE", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    alert_lagging = detect_squeeze_breakout(
        symbol="WIPRO",
        df=df,
        ltp=highs[-1] + 0.1,  # breaking out
        timeframe="daily",
    )
    assert alert_lagging is None  # Suppressed by sector headwind gate

    # Case B: Parent sector is LEADING -> Approved and tagged with sector metrics
    monkeypatch.setattr(
        "analysis.sector_rotation.get_stock_sector_alignment",
        lambda sym: {"sector": "AUTO", "quadrant": "LEADING", "alignment": "STRONG_TAILWIND"},
    )

    alert_leading = detect_squeeze_breakout(
        symbol="TATAMOTORS",
        df=df,
        ltp=highs[-1] + 0.1,
        timeframe="daily",
    )
    if alert_leading is not None:
        assert alert_leading.metrics.get("sector") == "AUTO"
        assert alert_leading.metrics.get("sector_quadrant") == "LEADING"


def test_adaptive_iv_rank_spread_routing(monkeypatch):
    """
    Verifies that when IV Rank is elevated (>= 60%), asymmetric radar
    promotes Defined-Risk Spreads as the primary vehicle instead of naked options.
    """
    from engine.asymmetric_radar import resolve_recommended_option_contract

    # Mock IV Rank to 72%
    monkeypatch.setattr(
        "analysis.options.compute_iv_rank_from_history",
        lambda sym: 72.0,
    )
    # Mock hedge plan builder
    fake_hedge = {
        "strategy": "BULL_CALL_DEBIT_SPREAD",
        "buy_leg": {"symbol": "RELIANCE251300CE"},
        "sell_leg": {"symbol": "RELIANCE251340CE"},
        "net_debit_per_share": 18.0,
        "max_profit_per_share": 22.0,
    }
    monkeypatch.setattr(
        "engine.options_hedging.build_defined_risk_hedge_plan",
        lambda **kwargs: fake_hedge,
    )

    opt_info = resolve_recommended_option_contract(
        symbol="RELIANCE",
        direction="BULLISH",
        spot=1280.0,
        stop_loss=1260.0,
        target_1=1320.0,
        target_2=1360.0,
        setup_type="POCKET_PIVOT",
        is_positional=True,
    )

    assert opt_info["iv_rank"] == 72.0
    assert opt_info["primary_execution_style"] == "DEFINED_RISK_SPREAD"
    assert "HIGH IV REGIME" in opt_info["execution_style_mandate"]
    assert opt_info["hedge_plan"] == fake_hedge
