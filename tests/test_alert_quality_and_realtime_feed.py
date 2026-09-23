"""
tests/test_alert_quality_and_realtime_feed.py
─────────────────────────────────────────────
Comprehensive institutional test suite verifying:
1. Opening Range (ORB) Stabilization Filter (prevents opening drive whipsaws).
2. VWAP Extension / Exhaustion Guard (prevents chasing stretched setups).
3. Live Options Pricing Fallback (rejects 0.0 priced dummy contracts, engages live fallback).
4. Intraday Option Target Bound Sanctity (T1 capped at +35%, T2 at +55%).
5. Provenance Transparency (live broker feed badge and milestone action clarity).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import pandas as pd

from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine
from engine.trade_plan import calculate_trade_plan

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class DummyQuote:
    symbol: str
    last_price: float
    change_pct: float
    volume: int
    vwap: float
    ltp: float = 0.0

    def __post_init__(self):
        if not self.ltp:
            self.ltp = self.last_price


@dataclass
class DummyOptionContract:
    symbol: str
    underlying: str
    strike: float
    option_type: str
    last_price: float
    oi: int = 10000
    oi_change: int = -500
    volume: int = 50000
    iv: float = 18.0
    exchange: str = "NFO"


def test_orb_stabilization_suppresses_early_morning_whipsaw(tmp_path, monkeypatch):
    """Stocks dipping before 09:30 IST during price discovery must be suppressed to avoid whipsaws."""
    data_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)
    eng = AutoAlertEngine()
    eng.clear_alerts()
    monkeypatch.setattr(eng, "watched_equities", ["MAZDOCK"])

    quotes = {
        "NSE:MAZDOCK": DummyQuote(
            symbol="NSE:MAZDOCK",
            last_price=3950.0,
            change_pct=-2.3,
            volume=200000,
            vwap=3980.0,
        )
    }
    df_hist = pd.DataFrame(
        {
            "open": [4000.0] * 25,
            "high": [4050.0] * 25,
            "low": [3900.0] * 25,
            "close": [4000.0] * 25,
            "volume": [100000] * 25,
        },
        index=pd.date_range("2026-08-01", periods=25, freq="D"),
    )

    monkeypatch.setattr("market.quotes.get_quote", lambda *args, **kwargs: quotes)
    monkeypatch.setattr("market.history.get_ohlcv", lambda *args, **kwargs: df_hist)

    # Simulate 09:25 IST (during opening discovery window)
    mock_0925 = datetime(2026, 9, 16, 9, 25, 0, tzinfo=IST)
    monkeypatch.setattr(
        "engine.auto_alert_engine.datetime",
        type(
            "MockDT",
            (),
            {
                "now": staticmethod(lambda tz=None: mock_0925),
                "fromtimestamp": datetime.fromtimestamp,
                "strptime": datetime.strptime,
                "date": datetime.date,
                "time": datetime.time,
            },
        ),
    )

    # Disable test override flag so the real time gate is active
    monkeypatch.delenv("CHANAKYA_TESTING", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    sparks = eng.scan_intraday_mover_sparks()
    mazdock_spark = next((s for s in sparks if "MAZDOCK" in s.symbol), None)

    assert mazdock_spark is None, (
        "MAZDOCK opening breakdown spark must be suppressed before 09:30 IST"
    )


def test_orb_stabilization_requires_institutional_volume_0930_to_0945(tmp_path, monkeypatch):
    """Between 09:30 and 09:45 IST, single-stock moves require RVOL >= 2.0x and |chg| >= 1.2%."""
    data_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)
    eng = AutoAlertEngine()
    eng.clear_alerts()
    monkeypatch.setattr(eng, "watched_equities", ["MAZDOCK"])

    # Simulate 09:36 IST (where MAZDOCK originally gave a false breakdown)
    mock_0936 = datetime(2026, 9, 16, 9, 36, 0, tzinfo=IST)
    monkeypatch.setattr(
        "engine.auto_alert_engine.datetime",
        type(
            "MockDT",
            (),
            {
                "now": staticmethod(lambda tz=None: mock_0936),
                "fromtimestamp": datetime.fromtimestamp,
                "strptime": datetime.strptime,
                "date": datetime.date,
                "time": datetime.time,
            },
        ),
    )
    monkeypatch.delenv("CHANAKYA_TESTING", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    # 1. Weak volume (RVOL ~ 1.2x) -> Suppressed
    quotes_weak = {
        "NSE:MAZDOCK": DummyQuote(
            symbol="NSE:MAZDOCK",
            last_price=3960.0,
            change_pct=-1.5,
            volume=50000,
            vwap=3980.0,
        )
    }
    df_hist = pd.DataFrame(
        {
            "open": [4000.0] * 25,
            "high": [4050.0] * 25,
            "low": [3900.0] * 25,
            "close": [4000.0] * 25,
            "volume": [200000] * 25,
        },
        index=pd.date_range("2026-08-01", periods=25, freq="D"),
    )
    monkeypatch.setattr("market.quotes.get_quote", lambda *args, **kwargs: quotes_weak)
    monkeypatch.setattr("market.history.get_ohlcv", lambda *args, **kwargs: df_hist)
    monkeypatch.setattr("engine.auto_alert_engine.compute_time_of_day_rvol", lambda *a, **kw: 1.2)

    sparks = eng.scan_intraday_mover_sparks()
    assert next((s for s in sparks if "MAZDOCK" in s.symbol), None) is None

    # 2. Strong institutional surge (RVOL = 2.4x, change = -2.2%) -> Ignites
    eng.clear_alerts()
    monkeypatch.setattr("engine.auto_alert_engine.compute_time_of_day_rvol", lambda *a, **kw: 2.4)
    quotes_strong = {
        "NSE:MAZDOCK": DummyQuote(
            symbol="NSE:MAZDOCK",
            last_price=3930.0,
            change_pct=-2.2,
            volume=300000,
            vwap=3980.0,
        )
    }
    monkeypatch.setattr("market.quotes.get_quote", lambda *args, **kwargs: quotes_strong)
    monkeypatch.setattr("analysis.sector_rotation.get_stock_tailwind", lambda *a, **kw: None)
    sparks_strong = eng.scan_intraday_mover_sparks()
    spark_strong = next((s for s in sparks_strong if "MAZDOCK" in s.symbol), None)
    assert spark_strong is not None
    assert spark_strong.direction == "BEARISH"
    assert spark_strong.stage == "IGNITED"


def test_vwap_extension_exhaustion_guard(tmp_path, monkeypatch):
    """Setups stretched > 2.5% from VWAP are rejected to prevent chasing exhaustion moves."""
    data_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)
    eng = AutoAlertEngine()
    eng.clear_alerts()
    monkeypatch.setattr(eng, "watched_equities", ["LALPATHLAB"])

    # Price = 2500, VWAP = 2580 (distance = 3.1% > 2.5% limit)
    quotes = {
        "NSE:LALPATHLAB": DummyQuote(
            symbol="NSE:LALPATHLAB",
            last_price=2500.0,
            change_pct=-2.8,
            volume=500000,
            vwap=2580.0,
        )
    }
    df_hist = pd.DataFrame(
        {
            "open": [2600.0] * 25,
            "high": [2650.0] * 25,
            "low": [2450.0] * 25,
            "close": [2600.0] * 25,
            "volume": [100000] * 25,
        },
        index=pd.date_range("2026-08-01", periods=25, freq="D"),
    )
    monkeypatch.setattr("market.quotes.get_quote", lambda *args, **kwargs: quotes)
    monkeypatch.setattr("market.history.get_ohlcv", lambda *args, **kwargs: df_hist)
    monkeypatch.setattr("engine.auto_alert_engine.compute_time_of_day_rvol", lambda *a, **kw: 2.5)

    sparks = eng.scan_intraday_mover_sparks()
    assert next((s for s in sparks if "LALPATHLAB" in s.symbol), None) is None, (
        "Exhausted setup > 2.5% from VWAP must be rejected"
    )


def test_options_fallback_on_zero_price_broker_chain(monkeypatch):
    """When broker returns dummy contracts with 0.0 prices, engine must cleanly fallback to live scraper."""
    from market.options import get_options_chain

    # Clear cache to ensure clean test
    from market.options import _CHAIN_CACHE

    _CHAIN_CACHE.clear()

    # Simulate broker returning 0-priced dummy objects
    dummy_chain = [
        DummyOptionContract("MUTHOOTFIN26SEP2000CE", "MUTHOOTFIN", 2000.0, "CE", 0.0),
        DummyOptionContract("MUTHOOTFIN26SEP2000PE", "MUTHOOTFIN", 2000.0, "PE", 0.0),
    ]

    class FakeBroker:
        def get_options_chain(self, *args, **kwargs):
            return dummy_chain

    monkeypatch.setattr("market.options.get_data_broker", lambda: FakeBroker())
    monkeypatch.setattr("brokers.session.get_data_broker", lambda: FakeBroker())
    monkeypatch.setattr("brokers.session.get_broker", lambda: FakeBroker())
    monkeypatch.setattr("brokers.session.is_multi_broker", lambda: False)

    # Scraper Tier-3 fallback returning real quotes
    scraper_chain = [
        DummyOptionContract("MUTHOOTFIN26SEP2000CE", "MUTHOOTFIN", 2000.0, "CE", 42.5),
        DummyOptionContract("MUTHOOTFIN26SEP2000PE", "MUTHOOTFIN", 2000.0, "PE", 38.0),
    ]
    monkeypatch.setattr("market.options.nse_get_options_chain", lambda *a, **kw: scraper_chain)

    chain = get_options_chain("MUTHOOTFIN")
    assert chain is not None
    assert len(chain) == 2
    assert any(c.last_price > 0 for c in chain), "Must receive positive live prices from fallback"
    assert chain[0].last_price == 42.5


def test_intraday_option_target_capping():
    """Intraday option targets must be bounded realistically: T1 <= +35%, T2 <= +55%."""
    plan = calculate_trade_plan(
        symbol="NIFTY",
        direction="LONG",
        spot=25000.0,
        timeframe="INTRADAY",
        has_active_blast=True,
    )
    assert plan is not None
    if plan.option_plan and plan.option_plan.entry_price > 0:
        opt = plan.option_plan
        t1_gain_pct = ((opt.target_1 - opt.entry_price) / opt.entry_price) * 100.0
        t2_gain_pct = ((opt.target_2 - opt.entry_price) / opt.entry_price) * 100.0
        assert t1_gain_pct <= 36.0, f"Intraday option T1 gain ({t1_gain_pct:.1f}%) exceeds +35% cap"
        assert t2_gain_pct <= 56.0, f"Intraday option T2 gain ({t2_gain_pct:.1f}%) exceeds +55% cap"


def test_alert_provenance_and_milestone_rendering():
    """Verify live broker feed badge and milestone rendering without BUY copy."""
    from bot.alert_templates import render_auto_alert

    # 1. Ignited alert with live broker connection
    alert_live = AutoAlert(
        alert_id="test-live-prov-1",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="KOTAKBANK",
        exchange="NFO",
        direction="BULLISH",
        headline="KOTAKBANK 1860 CE Momentum",
        summary="Volume surge",
        ltp=1850.0,
        trigger_level=1850.0,
        target_level=1890.0,
        stop_loss=1830.0,
        contract_symbol="KOTAKBANK26SEP1860CE",
        strike=1860.0,
        option_type="CE",
        option_premium=45.0,
        order_flow_signals={
            "live_broker_connected": True,
            "provenance": "LIVE_BROKER_FEED",
            "broker_depth_status": "LIVE_L2",
        },
    )
    rendered_live = render_auto_alert(alert_live, in_market=True)
    assert "LIVE BROKER FEED" in rendered_live
    assert "SYNTHETIC L1" not in rendered_live

    # 2. Milestone Target 1 Hit alert must NEVER render Action: BUY
    alert_t1 = AutoAlert(
        alert_id="test-t1-prov-1",
        alert_type="OPTIONS_MOMENTUM",
        stage="T1_ACHIEVED",
        symbol="KOTAKBANK",
        exchange="NFO",
        direction="BULLISH",
        headline="KOTAKBANK Target 1 Achieved",
        summary="T1 Hit",
        ltp=1880.0,
        trigger_level=1850.0,
        target_level=1880.0,
        stop_loss=1830.0,
        target_status="T1_ACHIEVED",
        contract_symbol="KOTAKBANK26SEP1860CE",
        strike=1860.0,
        option_type="CE",
        option_premium=58.0,
    )
    rendered_t1 = render_auto_alert(alert_t1, in_market=True)
    assert "TARGET 1 ACHIEVED" in rendered_t1 or "TARGET 1 HIT" in rendered_t1
    assert "DECISIVE ACTION:" in rendered_t1
    assert "BOOK 50% PROFIT" in rendered_t1
    assert "Action: BUY" not in rendered_t1
