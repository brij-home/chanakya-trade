"""
tests/test_afternoon_thrust.py
──────────────────────────────
Unit and integration tests for the Afternoon Thrust & Power Hour Breakout detector
and second-half derivative movement capture (Indices & F&O Stocks).
All tests are deterministic and use synthetic data.
"""

from __future__ import annotations

import os
from datetime import date, datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd

os.environ.setdefault("CHANAKYA_TESTING", "1")
IST = ZoneInfo("Asia/Kolkata")


def _make_dt(hour: int, minute: int) -> datetime:
    d = date.today()
    return datetime(d.year, d.month, d.day, hour, minute, 0, tzinfo=IST)


def _generate_intraday_5m_bars(
    start_time: dtime = dtime(9, 15),
    end_time: dtime = dtime(13, 30),
    base_price: float = 25000.0,
    regime: str = "BULLISH_PM_BREAKOUT",
) -> pd.DataFrame:
    """Generates synthetic 5m OHLCV bars across morning, midday lull, and PM sessions."""
    today = date.today()
    cur = datetime.combine(today, start_time, tzinfo=IST)
    end_dt = datetime.combine(today, end_time, tzinfo=IST)

    rows = []
    price = base_price

    while cur <= end_dt:
        t = cur.time()
        # Morning session (09:15 - 11:30): trending up to 25050
        if t < dtime(11, 30):
            step = 5.0
            rng = 15.0
            vol = 10000
        # Midday lull (11:30 - 13:00): tight coiling between 25030 and 25060
        elif t < dtime(13, 0):
            step = 0.5
            rng = 8.0
            vol = 3000
        # Afternoon Power Hour (13:00 onwards): explosive thrust
        else:
            if regime == "BULLISH_PM_BREAKOUT":
                step = 10.0
                rng = 25.0
                vol = 18000
            elif regime == "BEARISH_PM_FLUSH":
                step = -15.0
                rng = 25.0
                vol = 18000
            else:
                step = 1.0
                rng = 10.0
                vol = 4000

        price += step
        o = price - 2.0
        c = price + 3.0
        h = max(o, c) + rng / 2.0
        l = min(o, c) - rng / 2.0

        rows.append(
            {
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": vol,
            }
        )
        cur += timedelta(minutes=5)

    index = pd.date_range(
        start=datetime.combine(today, start_time, tzinfo=IST),
        periods=len(rows),
        freq="5min",
    )
    return pd.DataFrame(rows, index=index)


class TestAfternoonThrustTimeGates:
    def test_rejected_before_1300(self):
        from engine.detectors.afternoon_thrust import detect_afternoon_thrust

        df = _generate_intraday_5m_bars(end_time=dtime(10, 30))
        alert = detect_afternoon_thrust(
            symbol="NIFTY",
            df_5m=df,
            ltp=25000.0,
            vwap=24980.0,
            ref_time=_make_dt(10, 30),
            ignore_time_gate=False,
        )
        assert alert is None, "Afternoon thrust must not fire before 13:00 IST"

    def test_rejected_during_midday_lull(self):
        from engine.detectors.afternoon_thrust import detect_afternoon_thrust

        df = _generate_intraday_5m_bars(end_time=dtime(12, 15))
        alert = detect_afternoon_thrust(
            symbol="NIFTY",
            df_5m=df,
            ltp=25040.0,
            vwap=25020.0,
            ref_time=_make_dt(12, 15),
            ignore_time_gate=False,
        )
        assert alert is None, "Afternoon thrust must not fire at 12:15 IST"

    def test_rejected_after_1515(self):
        from engine.detectors.afternoon_thrust import detect_afternoon_thrust

        df = _generate_intraday_5m_bars(end_time=dtime(15, 20))
        alert = detect_afternoon_thrust(
            symbol="NIFTY",
            df_5m=df,
            ltp=25150.0,
            vwap=25050.0,
            ref_time=_make_dt(15, 20),
            ignore_time_gate=False,
        )
        assert alert is None, "Afternoon thrust must not fire after 15:15 IST"

    def test_active_during_power_hour(self):
        from engine.detectors.afternoon_thrust import detect_afternoon_thrust

        df = _generate_intraday_5m_bars(end_time=dtime(13, 35))
        ltp = float(df["close"].iloc[-1])
        alert = detect_afternoon_thrust(
            symbol="NIFTY",
            df_5m=df,
            ltp=ltp,
            vwap=ltp - 30.0,
            ref_time=_make_dt(13, 35),
            ignore_time_gate=False,
        )
        assert alert is not None
        assert alert.alert_type == "AFTERNOON_THRUST"


class TestAfternoonThrustLogic:
    def test_bullish_index_breakout(self):
        from engine.detectors.afternoon_thrust import detect_afternoon_thrust

        df = _generate_intraday_5m_bars(
            end_time=dtime(13, 30),
            base_price=25000.0,
            regime="BULLISH_PM_BREAKOUT",
        )
        ltp = float(df["close"].iloc[-1])
        day_high = float(df["high"].iloc[:-1].max())

        alert = detect_afternoon_thrust(
            symbol="NIFTY",
            df_5m=df,
            ltp=ltp,
            vwap=ltp - 25.0,
            rvol=1.8,
            day_high=day_high,
            day_low=24950.0,
            ref_time=_make_dt(13, 30),
            ignore_time_gate=True,
        )
        assert alert is not None
        assert alert.direction == "BULLISH"
        assert alert.symbol == "NIFTY"
        assert alert.stage == "IGNITED"
        assert alert.alert_type == "AFTERNOON_THRUST"
        assert alert.option_type == "CE"
        assert alert.confidence >= 75

        # Check Actionable Blueprint
        plan = alert.actionable_plan
        assert plan is not None
        assert "target_1" in plan
        assert "stop_loss" in plan
        assert "no_chase_boundary" in plan
        assert plan["action"] == "BUY CE"

        # Check alert identity determinism and 24hr slot
        assert "aa-afternoon-thrust-nifty-bull-1315-" in alert.alert_id

    def test_bearish_index_flush(self):
        from engine.detectors.afternoon_thrust import detect_afternoon_thrust

        df = _generate_intraday_5m_bars(
            end_time=dtime(14, 0),
            base_price=25000.0,
            regime="BEARISH_PM_FLUSH",
        )
        ltp = float(df["close"].iloc[-1])
        day_low = float(df["low"].iloc[:-1].min())

        alert = detect_afternoon_thrust(
            symbol="NIFTY",
            df_5m=df,
            ltp=ltp,
            vwap=ltp + 35.0,
            rvol=1.7,
            day_high=25100.0,
            day_low=day_low,
            ref_time=_make_dt(14, 0),
            ignore_time_gate=True,
        )
        assert alert is not None
        assert alert.direction == "BEARISH"
        assert alert.stage == "IGNITED"
        assert alert.alert_type == "AFTERNOON_THRUST"
        plan = alert.actionable_plan
        assert plan is not None
        assert plan["action"] == "BUY PE"
        assert "aa-afternoon-thrust-nifty-bear-1315-" in alert.alert_id

    def test_stock_option_afternoon_thrust(self):
        from engine.detectors.afternoon_thrust import detect_afternoon_thrust

        df = _generate_intraday_5m_bars(
            end_time=dtime(13, 45),
            base_price=2900.0,
            regime="BULLISH_PM_BREAKOUT",
        )
        ltp = float(df["close"].iloc[-1])

        alert = detect_afternoon_thrust(
            symbol="RELIANCE",
            df_5m=df,
            ltp=ltp,
            vwap=ltp - 5.0,
            rvol=1.6,
            ref_time=_make_dt(13, 45),
            ignore_time_gate=True,
        )
        assert alert is not None
        assert alert.symbol == "RELIANCE"
        assert alert.direction == "BULLISH"
        assert alert.segment in ("FNO_STOCK", "EQUITY")
        assert "aa-afternoon-thrust-reliance-bull-1315-" in alert.alert_id


class TestGammaBlastPMDistinctness:
    def test_gamma_blast_phase_slot_distinct_ids(self):
        """Verifies that AM and PM gamma blasts on the same strike do not deduplicate."""
        from types import SimpleNamespace
        from engine.detectors.gamma_blast import detect_gamma_blast

        # Mock options chain
        chain = [
            SimpleNamespace(
                symbol="NIFTY25000CE",
                strike=25000.0,
                option_type="CE",
                last_price=120.0,
                oi=50000,
                oi_change=-8000,
                volume=25000,
                expiry="2026-10-15",
                pchange=15.0,
                bid=119.5,
                ask=120.5,
            ),
        ]

        # AM detection (10:30 IST -> phase slot 0915)
        am_alerts = detect_gamma_blast(
            underlying="NIFTY",
            spot=25010.0,
            chain=chain,
            vwap=24990.0,
            now_dt=_make_dt(10, 30),
        )

        # PM detection (13:45 IST -> phase slot 1315)
        pm_alerts = detect_gamma_blast(
            underlying="NIFTY",
            spot=25020.0,
            chain=chain,
            vwap=24995.0,
            now_dt=_make_dt(13, 45),
        )

        assert len(am_alerts) > 0
        assert len(pm_alerts) > 0
        assert am_alerts[0].alert_id != pm_alerts[0].alert_id
        assert "-0915-" in am_alerts[0].alert_id
        assert "-1315-" in pm_alerts[0].alert_id

    def test_gamma_blast_pm_day_high_breakout_press_allowed(self):
        """Spot pressing day high in PM session with writer capitulation must not be vetoed."""
        from types import SimpleNamespace
        from engine.detectors.gamma_blast import detect_gamma_blast

        chain = [
            SimpleNamespace(
                symbol="NIFTY25000CE",
                strike=25000.0,
                option_type="CE",
                last_price=135.0,
                oi=60000,
                oi_change=-12000,  # Negative dOI (writer panic)
                volume=30000,
                expiry="2026-10-15",
                pchange=18.0,
                bid=134.5,
                ask=135.5,
            ),
        ]

        # Spot 25048 vs day_high 25050 (distance 0.008% < 0.15%)
        alerts = detect_gamma_blast(
            underlying="NIFTY",
            spot=25048.0,
            chain=chain,
            vwap=25010.0,
            day_high=25050.0,
            day_low=24950.0,
            now_dt=_make_dt(13, 45),
        )
        assert len(alerts) > 0, "PM day high breakout press with writer unwinding must be detected"


class TestAutoAlertEngineAfternoonScan:
    def test_engine_scan_afternoon_thrusts(self, monkeypatch):
        from engine.auto_alert_engine import AutoAlertEngine
        from engine.alert_model import AutoAlert

        engine = AutoAlertEngine()
        engine._alerts.clear()

        def mock_detect(*args, **kwargs):
            sym = kwargs.get("symbol", "NIFTY")
            return AutoAlert(
                alert_id=f"aa-afternoon-thrust-{sym.lower()}-bull-1315-20261013",
                alert_type="AFTERNOON_THRUST",
                stage="IGNITED",
                symbol=sym,
                exchange="NFO",
                direction="BULLISH",
                ltp=25050.0,
                trigger_level=25050.0,
                stop_loss=25000.0,
                target_level=25150.0,
                headline="PM Test",
                summary="PM Test Summary",
                environment="TEST",
            )

        monkeypatch.setattr(
            "engine.auto_alert_engine.detect_afternoon_thrust",
            mock_detect,
        )

        # Mock get_ohlcv to return valid data
        df = _generate_intraday_5m_bars()
        monkeypatch.setattr("market.history.get_ohlcv", lambda *args, **kwargs: df)
        monkeypatch.setattr("market.quotes.get_ltp", lambda *args, **kwargs: 25000.0)

        from types import SimpleNamespace

        q = SimpleNamespace(
            last_price=25050.0,
            high=25060.0,
            low=24950.0,
            vwap=25000.0,
            previous_close=24900.0,
        )
        quotes_map = {"NIFTY": q, "NSE:NIFTY": q}

        results = engine.scan_afternoon_thrusts(indices_only=True, quotes_map=quotes_map)
        assert len(results) >= 1
        assert any(r.alert_type == "AFTERNOON_THRUST" for r in results)
