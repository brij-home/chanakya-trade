"""
tests/test_dual_blueprints_and_episodic_kelly.py

Unit tests verifying:
  1. Dual Execution Blueprints (Predatory Limit Retest vs Momentum Market Ignition)
  2. Episodic Memory Quarter-Kelly Optimal Position Sizing Engine
"""

from engine.alert_model import AutoAlert
from engine.position_sizer import (
    calculate_episodic_kelly_position_size,
    EpisodicKellySizingResult,
)
from engine.episodic_memory import EpisodicTradeMemoryStore, TradeEpisode


def test_auto_alert_dual_execution_blueprints():
    """AutoAlert automatically generates dual execution blueprints (Predatory Limit vs Momentum Market)."""
    alert = AutoAlert(
        alert_id="aa-spark-nifty-20261031",
        alert_type="INTRADAY_BREAKOUT_SPARK",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="NIFTY Breakout Ignition",
        summary="NIFTY surging on 2.2x volume",
        ltp=25000.0,
        trigger_level=25000.0,
        target_level=25150.0,
        stop_loss=24950.0,
    )

    blueprints = alert.generate_dual_blueprints()
    assert "predatory_limit" in blueprints
    assert "momentum_market" in blueprints

    pred = blueprints["predatory_limit"]
    mkt = blueprints["momentum_market"]

    # Predatory Limit Blueprint: pullback discount with tight risk and superior R:R
    assert pred["order_type"] == "LIMIT"
    assert pred["entry_price"] < 25000.0  # Discounted entry on pullback
    assert pred["stop_loss"] == 24950.0
    assert pred["execution_tag"] == "RECOMMENDED_PREDATORY"

    # Momentum Market Blueprint: enters immediately at current trigger level
    assert mkt["order_type"] == "MARKET"
    assert mkt["entry_price"] == 25000.0
    assert mkt["stop_loss"] == 24950.0
    assert mkt["execution_tag"] == "ALTERNATIVE_MOMENTUM"

    # Serialization in to_dict()
    d = alert.to_dict()
    assert "dual_blueprints" in d
    assert d["dual_blueprints"]["predatory_limit"]["order_type"] == "LIMIT"


def test_episodic_kelly_sizing_scaling_up(tmp_path, monkeypatch):
    """When analogous historical win rate is high (>=75%), Quarter-Kelly scales up capital allocation."""
    db_file = tmp_path / "test_kelly_up.db"
    store = EpisodicTradeMemoryStore(db_path=db_file)
    monkeypatch.setattr("engine.episodic_memory.get_episodic_memory_store", lambda: store)

    # Ingest 4 winning episodes
    for i in range(4):
        store.record_episode(
            TradeEpisode(
                episode_id=f"ep-win-{i}",
                session_date="2026-10-31",
                symbol="RELIANCE",
                direction="BULLISH",
                entry_price=3000.0,
                exit_price=3100.0,
                stop_loss=2970.0,
                target_1=3060.0,
                pnl_pts=100.0,
                pnl_pct=3.33,
                r_multiple=3.33,
                mfe_r=3.5,
                mae_r=0.2,
                execution_efficiency=0.95,
                vix_regime="NORMAL_IV",
                day_archetype="NORMAL_DAY",
                vpin_regime="LOW_TOXICITY",
                holding_duration_mins=45.0,
                exit_reason="T2_HIT",
                win_loss="WIN",
            )
        )

    res = calculate_episodic_kelly_position_size(
        symbol="RELIANCE",
        direction="BULLISH",
        entry_price=3000.0,
        stop_loss=2970.0,
        target_price=3060.0,
        capital=200000.0,
        day_archetype="NORMAL_DAY",
        vix_regime="NORMAL_IV",
        vpin_regime="LOW_TOXICITY",
    )

    assert isinstance(res, EpisodicKellySizingResult)
    assert res.sample_size >= 4
    assert res.empirical_win_rate_pct == 100.0
    assert res.quarter_kelly_multiplier >= 1.20  # High conviction scale-up
    assert res.allocated_shares > 0


def test_episodic_kelly_sizing_defensive_throttle(tmp_path, monkeypatch):
    """When analogous historical drawdowns are high or win rate is low, Quarter-Kelly throttles down."""
    db_file = tmp_path / "test_kelly_down.db"
    store = EpisodicTradeMemoryStore(db_path=db_file)
    monkeypatch.setattr("engine.episodic_memory.get_episodic_memory_store", lambda: store)

    # Ingest 4 losing/high MAE episodes
    for i in range(4):
        store.record_episode(
            TradeEpisode(
                episode_id=f"ep-loss-{i}",
                session_date="2026-10-31",
                symbol="TATAMOTORS",
                direction="BULLISH",
                entry_price=1000.0,
                exit_price=980.0,
                stop_loss=980.0,
                target_1=1040.0,
                pnl_pts=-20.0,
                pnl_pct=-2.0,
                r_multiple=-1.0,
                mfe_r=0.3,
                mae_r=1.2,
                execution_efficiency=0.0,
                vix_regime="INFLATED_IV",
                day_archetype="NORMAL_DAY",
                vpin_regime="HIGH_TOXICITY",
                holding_duration_mins=30.0,
                exit_reason="STOPPED_OUT",
                win_loss="LOSS",
            )
        )

    res = calculate_episodic_kelly_position_size(
        symbol="TATAMOTORS",
        direction="BULLISH",
        entry_price=1000.0,
        stop_loss=980.0,
        target_price=1040.0,
        capital=200000.0,
        day_archetype="NORMAL_DAY",
        vix_regime="INFLATED_IV",
        vpin_regime="HIGH_TOXICITY",
    )

    assert isinstance(res, EpisodicKellySizingResult)
    assert res.sample_size >= 4
    assert res.empirical_win_rate_pct == 0.0
    assert res.quarter_kelly_multiplier <= 0.50  # Defensive capital preservation
    assert res.confidence_calibration == "HIGH_MAE_DRAWDOWN_PRONE"


def test_episodic_kelly_sizing_neutral_fallback(tmp_path, monkeypatch):
    """When sample size is small (< 3), Quarter-Kelly defaults to neutral 1.0x baseline."""
    db_file = tmp_path / "test_kelly_empty.db"
    store = EpisodicTradeMemoryStore(db_path=db_file)
    monkeypatch.setattr("engine.episodic_memory.get_episodic_memory_store", lambda: store)

    res = calculate_episodic_kelly_position_size(
        symbol="INFY",
        direction="BULLISH",
        entry_price=1900.0,
        stop_loss=1870.0,
        target_price=1950.0,
        capital=100000.0,
    )

    assert res.sample_size == 0
    assert res.quarter_kelly_multiplier == 1.0  # Neutral baseline
