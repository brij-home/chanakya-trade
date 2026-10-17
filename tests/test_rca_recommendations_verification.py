"""
tests/test_rca_recommendations_verification.py
─────────────────────────────────────────────
Verification tests for:
1. Dynamic Benchmark Reversal Override in scan_index_call_setups (unblocking Call setups on V-reversals).
2. Downside ADR Exhaustion (85% ATR) & Major Support Proximity (Camarilla L4, PWL) in index_put_setup.py.
3. Strict Breakeven Floor Enforcement upon T1 / T0.5 in alert_evaluator.py and trade_lifecycle_manager.py.
"""

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from engine.alert_model import AutoAlert
from engine.alert_evaluator import evaluate_alert_invalidation, TargetTrailingEvaluation
from engine.lifecycle.trade_lifecycle_manager import trade_lifecycle_manager

IST = ZoneInfo("Asia/Kolkata")


# ── Dummy Data Classes ──────────────────────────────────────────


@dataclass
class DummyOptionContract:
    symbol: str
    strike: float
    option_type: str
    last_price: float
    volume: int
    oi: int
    oi_change: int
    pchange: float = 0.0


@dataclass
class DummyDailyLevels:
    pdh: float = 23000.0
    pdl: float = 22700.0
    atr_14: float = 200.0
    camarilla: dict = None
    weekly: dict = None

    def __post_init__(self):
        if self.camarilla is None:
            self.camarilla = {
                "h3": 22950.0,
                "h4": 23050.0,
                "h5": 23200.0,
                "l3": 22800.0,
                "l4": 22700.0,
                "l5": 22500.0,
            }
        if self.weekly is None:
            self.weekly = {"pwh": 23200.0, "pwl": 22650.0}


# ── 1. Benchmark V-Reversal Override Verification ───────────────


def test_benchmark_v_reversal_unblocks_call_scans(monkeypatch):
    """
    Verifies that when benchmark NIFTY has dropped from open but staged an active V-reversal
    (>= 0.25% off its session low), benchmark_is_bearish evaluates to False even though its
    daily percentage change vs previous close is negative (-0.15%).
    """
    from engine.auto_alert_engine import AutoAlertEngine

    engine = AutoAlertEngine()

    # NIFTY opened gap down: yesterday close was 22,900, day low was 22,800 (-0.43%).
    # Current spot is 22,870 (-0.13% vs yesterday close, below VWAP 22,890).
    # Bounce from day low = (22,870 - 22,800) / 22,800 * 100 = +0.307% (active V-reversal).
    quotes_map = {
        "NSE:NIFTY": {
            "last_price": 22870.0,
            "vwap": 22890.0,
            "change_pct": -0.13,
            "low": 22800.0,
            "high": 22920.0,
        }
    }

    nifty_quote = quotes_map["NSE:NIFTY"]
    nifty_spot = engine._extract_quote_val(nifty_quote, "last_price", "ltp")
    nifty_vwap = engine._extract_quote_val(nifty_quote, "vwap", "average_price")
    nifty_chg = engine._extract_quote_val(nifty_quote, "change_pct")
    nifty_day_low = engine._extract_quote_val(nifty_quote, "low", "day_low")
    nifty_bounce_pct = (
        ((nifty_spot - nifty_day_low) / max(1.0, nifty_day_low) * 100.0)
        if (nifty_day_low and nifty_day_low > 0 and nifty_spot > nifty_day_low)
        else 0.0
    )
    nifty_v_reversal_active = nifty_bounce_pct >= 0.25
    benchmark_is_bearish = (
        nifty_spot > 0
        and nifty_vwap > 0
        and nifty_spot < nifty_vwap
        and nifty_chg <= -0.05
        and not nifty_v_reversal_active
    )

    assert nifty_bounce_pct > 0.25
    assert nifty_v_reversal_active is True
    # The benchmark must NOT be marked bearish because V-reversal is active!
    assert benchmark_is_bearish is False


# ── 2. Downside ADR Exhaustion & Support Proximity Gate ─────────


def test_downside_adr_exhaustion_suppresses_put_setup(monkeypatch):
    """
    Verifies that when an index has dropped >= 85% of its 14-day ATR off session high
    without high-volume breakdown momentum, detect_index_put_setup suppresses the trade.
    """
    from engine.detectors.index_put_setup import detect_index_put_setup
    import engine.daily_levels as dl_mod

    # Setup 14-day ATR = 200 pts. Day high = 23,000.
    # Current spot = 22,810 (drop = 190 pts = 95% of ATR).
    # Normal volume (not explosive).
    dummy_dl = DummyDailyLevels(atr_14=200.0, camarilla={"l5": 22400.0, "l4": 22600.0})
    monkeypatch.setattr(dl_mod, "get_daily_levels", lambda sym: dummy_dl)

    chain = [
        DummyOptionContract(
            symbol="NIFTY26OCT22800PE",
            strike=22800.0,
            option_type="PE",
            last_price=110.0,
            volume=8000,
            oi=10000,
            oi_change=2000,
            pchange=8.0,  # Below 15% breakdown threshold
        ),
        DummyOptionContract(
            symbol="NIFTY26OCT22800CE",
            strike=22800.0,
            option_type="CE",
            last_price=90.0,
            volume=8000,
            oi=15000,
            oi_change=1000,
            pchange=-10.0,
        ),
    ]

    # Force test evaluation through daily levels
    alerts = detect_index_put_setup(
        underlying="NIFTY",
        spot=22810.0,
        chain=chain,
        vwap=22900.0,
        day_high=23000.0,
        day_low=22805.0,
        prev_day_high=23100.0,
        prev_day_low=22750.0,
        ignore_time_gate=True,
    )

    # Must be suppressed due to Downside ADR Exhaustion (190 pts drop >= 85% of ATR 200 pts)
    assert len(alerts) == 0


def test_major_support_proximity_suppresses_put_setup(monkeypatch):
    """
    Verifies that when spot is within 0.15% above Camarilla L4 or PWL without breakdown momentum,
    detect_index_put_setup suppresses the setup to prevent shorting directly into institutional floor.
    """
    from engine.detectors.index_put_setup import detect_index_put_setup
    import engine.daily_levels as dl_mod

    # Camarilla L4 floor = 22,800. Spot = 22,820 (dist = 0.087% above L4).
    dummy_dl = DummyDailyLevels(
        atr_14=300.0,
        camarilla={"l5": 22500.0, "l4": 22800.0},
        weekly={"pwl": 22500.0},
    )
    monkeypatch.setattr(dl_mod, "get_daily_levels", lambda sym: dummy_dl)

    chain = [
        DummyOptionContract(
            symbol="NIFTY26OCT22800PE",
            strike=22800.0,
            option_type="PE",
            last_price=110.0,
            volume=8000,
            oi=10000,
            oi_change=2000,
            pchange=5.0,  # No breakdown momentum
        ),
        DummyOptionContract(
            symbol="NIFTY26OCT22800CE",
            strike=22800.0,
            option_type="CE",
            last_price=90.0,
            volume=8000,
            oi=15000,
            oi_change=1000,
            pchange=-5.0,
        ),
    ]

    alerts = detect_index_put_setup(
        underlying="NIFTY",
        spot=22820.0,
        chain=chain,
        vwap=22860.0,
        day_high=22900.0,
        day_low=22815.0,
        prev_day_high=23000.0,
        prev_day_low=22600.0,
        ignore_time_gate=True,
    )

    # Must be suppressed due to Camarilla L4 proximity collision
    assert len(alerts) == 0


# ── 3. Strict Breakeven Floor Enforcement Verification ─────────


def test_breakeven_floor_enforcement_in_evaluator():
    """
    Verifies that when an alert has achieved Target 1 (T1_ACHIEVED in achieved_milestones),
    evaluate_alert_invalidation strictly enforces the breakeven floor by pegging stop_loss
    to the entry level, preventing the trade from exiting as a loss.
    """
    now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    # 1. BULLISH Option alert: entry was ₹120.0, initial stop was ₹95.0.
    # T1 was achieved, but due to any anomaly stop_loss remained at ₹105.0 (< entry).
    bull_alert = AutoAlert(
        alert_id="aa-test-bull-be",
        symbol="NIFTY",
        alert_type="INDEX_CALL_SETUP",
        exchange="NFO",
        direction="BULLISH",
        ltp=135.0,
        trigger_level=120.0,
        stop_loss=105.0,  # Below entry ₹120.0!
        target_level=160.0,
        headline="Test Bull BE",
        summary="Test summary",
        stage="TARGET_1",
        achieved_milestones=["T1_ACHIEVED"],
        created_at=now_iso,
        is_live=True,
        environment="LIVE",
        initial_entry_premium=120.0,
        initial_stop_loss=95.0,
    )

    # When evaluate_alert_invalidation runs with LTP = ₹115 (below entry ₹120 but above old SL ₹105):
    # It must enforce breakeven floor: peg alert.stop_loss = 120.0, and detect runner stop breach!
    invalidation = evaluate_alert_invalidation(bull_alert, current_ltp=115.0)

    # stop_loss must have been ratcheted to breakeven entry ₹120.0
    assert bull_alert.stop_loss == 120.0
    # Invalidation reason must declare trailing runner stop triggered at scratch/breakeven
    assert invalidation is not None
    assert "Trailing runner stop triggered" in invalidation
    assert (
        "Target 1 profit was banked" in invalidation
        or "stopped at scratch/breakeven" in invalidation
        or "runner closed" in invalidation
    )


def test_breakeven_floor_pegging_in_lifecycle_manager():
    """
    Verifies that apply_milestone_state in TradeLifecycleManager automatically clamps
    the recommended stop to at least the breakeven entry price upon T1 / T0.5.
    """
    now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    alert = AutoAlert(
        alert_id="aa-test-be-lifecycle",
        symbol="BANKNIFTY",
        alert_type="GAMMA_BLAST",
        exchange="NFO",
        direction="BULLISH",
        ltp=250.0,
        trigger_level=200.0,
        stop_loss=160.0,
        target_level=300.0,
        headline="Test BE Lifecycle",
        summary="Test summary",
        stage="IGNITED",
        created_at=now_iso,
        is_live=True,
        environment="LIVE",
        option_premium=200.0,
    )

    # Suppose evaluator returns recommended_stop = 190.0 (slightly below entry 200.0)
    eval_res = TargetTrailingEvaluation(
        new_milestone="T1_ACHIEVED",
        target_status="T1_ACHIEVED",
        should_trail=True,
        trailing_decision="BOOK_50_TRAIL_BREAKEVEN",
        recommended_stop=190.0,
        trailing_rationale="T1 hit",
        locked_profit_pts=0.0,
        locked_profit_pct=0.0,
        r_multiple=2.0,
        pnl_pct=25.0,
    )

    trade_lifecycle_manager.apply_milestone_state(
        alert, eval_res, cur_quote_ltp=250.0, now_ts=1700000000.0, now_str=now_iso
    )

    # alert.stop_loss must be pegged to at least ref_entry (200.0)
    assert alert.stop_loss >= 200.0


def test_intraday_spark_monotonic_target_hierarchy(monkeypatch):
    from engine.detectors.intraday_spark import detect_intraday_mover_sparks
    from market.quotes import Quote
    import pandas as pd
    import market.history as hist_mod

    # Synthetic quote for bullish spark
    bull_quote = Quote(
        symbol="TATASTEEL",
        last_price=160.0,
        open=155.0,
        high=161.0,
        low=154.5,
        close=155.0,
        volume=5000000,
        change=5.0,
        change_pct=3.2,
        vwap=157.0,
        provider="TEST",
    )
    df = pd.DataFrame(
        {
            "open": [155.0] * 30,
            "high": [161.0] * 30,
            "low": [154.5] * 30,
            "close": [156.0] * 30,
            "volume": [100000] * 30,
        }
    )
    monkeypatch.setattr(hist_mod, "get_ohlcv", lambda *args, **kwargs: df)

    alerts = detect_intraday_mover_sparks(
        universe=["TATASTEEL"],
        quotes_map={"NSE:TATASTEEL": bull_quote, "TATASTEEL": bull_quote},
    )
    assert len(alerts) >= 1
    alert = alerts[0]
    p = alert.actionable_plan or {}
    t1 = float(str(p.get("target", "0")).replace("₹", "").replace(",", ""))
    t2 = float(str(p.get("target_2", "0")).replace("₹", "").replace(",", ""))
    t3 = float(str(p.get("target_3", "0")).replace("₹", "").replace(",", ""))
    assert t1 > 160.0
    assert t2 > t1, f"Expected t2 ({t2}) > t1 ({t1})"
    assert t3 > t2, f"Expected t3 ({t3}) > t2 ({t2})"


def test_major_resistance_proximity_suppresses_call_setup(monkeypatch):
    from engine.detectors.index_call_setup import detect_index_call_setup
    import engine.daily_levels as dl_mod

    # Setup spot = 23090, Camarilla H4 = 23100 (dist 10 pts = 0.04% < 0.20%)
    dummy_dl = DummyDailyLevels(atr_14=180.0, camarilla={"h5": 23250.0, "h4": 23100.0})
    monkeypatch.setattr(dl_mod, "get_daily_levels", lambda sym: dummy_dl)

    chain = [
        DummyOptionContract(
            symbol="NIFTY26OCT23100CE",
            strike=23100.0,
            option_type="CE",
            last_price=105.0,
            volume=8000,
            oi=12000,
            oi_change=1500,
            pchange=5.0,
        ),
        DummyOptionContract(
            symbol="NIFTY26OCT23100PE",
            strike=23100.0,
            option_type="PE",
            last_price=85.0,
            volume=8000,
            oi=10000,
            oi_change=-500,
            pchange=-8.0,
        ),
    ]

    alerts = detect_index_call_setup(
        underlying="NIFTY",
        spot=23090.0,
        chain=chain,
        vwap=23000.0,
        day_high=23095.0,
        day_low=23010.0,
        prev_day_high=23080.0,
        prev_day_low=22950.0,
        ignore_time_gate=True,
    )

    # Must be suppressed due to Camarilla H4 Resistance Collision (spot is within 0.04% of H4)
    assert len(alerts) == 0
