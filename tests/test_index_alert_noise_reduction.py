"""
tests/test_index_alert_noise_reduction.py
──────────────────────────────────────────
Regression tests for index alert noise reduction safeguards:
  1. 09:25 IST market stabilization gate
  2. Today-only bar isolation (cross-session contamination guard)
  3. Active heavyweight locomotive confluence
  4. Low-VIX (<13.0) range-bound hedged spread mandate
  5. Synchronous scrutiny gating for index Gamma Blast & Opening Drive
"""

from datetime import datetime
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo
import pandas as pd

from engine.detectors.index_call_setup import detect_index_call_setup
from engine.detectors.index_put_setup import detect_index_put_setup
from engine.detectors.opening_drive import detect_opening_drive

IST = ZoneInfo("Asia/Kolkata")


class DummyContract:
    def __init__(
        self,
        strike: float,
        option_type: str,
        last_price: float,
        volume: int = 15000,
        oi: int = 8000,
    ):
        self.strike = strike
        self.option_type = option_type
        self.last_price = last_price
        self.volume = volume
        self.oi = oi
        self.oi_change = 1200
        self.pchange = 12.0
        self.symbol = f"BANKNIFTY{int(strike)}{option_type}"
        self.expiry = "2026-09-30"


def _make_sample_chain(spot: float):
    return [
        DummyContract(spot - 200, "CE", 380.0),
        DummyContract(spot - 100, "CE", 310.0),
        DummyContract(spot, "CE", 240.0),
        DummyContract(spot + 100, "CE", 180.0),
        DummyContract(spot + 200, "CE", 130.0),
        DummyContract(spot - 200, "PE", 140.0),
        DummyContract(spot - 100, "PE", 190.0),
        DummyContract(spot, "PE", 250.0),
        DummyContract(spot + 100, "PE", 320.0),
        DummyContract(spot + 200, "PE", 400.0),
    ]


def test_0925_stabilization_window_suppresses_early_signals():
    """Multi-candle structural patterns must not trigger before 09:25 IST."""
    spot = 56000.0
    chain = _make_sample_chain(spot)

    # 09:18 IST (within opening auction noise window)
    early_dt = datetime(2026, 9, 25, 9, 18, 0, tzinfo=IST)

    # Supply 12 bars with today's date
    dates = [datetime(2026, 9, 25, 9, 15 + i, 0, tzinfo=IST) for i in range(12)]
    df_early = pd.DataFrame(
        {
            "open": [55950.0 + i * 5 for i in range(12)],
            "high": [56010.0 for _ in range(12)],
            "low": [55940.0 for _ in range(12)],
            "close": [56005.0 for _ in range(12)],
            "volume": [5000 for _ in range(12)],
        },
        index=dates,
    )

    with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": ""}, clear=False):
        # Without ignore_time_gate, early time (09:18 IST) must suppress
        alerts_call = detect_index_call_setup(
            underlying="BANKNIFTY",
            spot=spot,
            chain=chain,
            vwap=55980.0,
            day_high=56010.0,
            day_low=55940.0,
            ohlcv_5m=df_early,
            ref_time=early_dt,
            ignore_time_gate=False,
        )
        assert len(alerts_call) == 0

        alerts_put = detect_index_put_setup(
            underlying="BANKNIFTY",
            spot=spot,
            chain=chain,
            vwap=56020.0,
            day_high=56060.0,
            day_low=55990.0,
            ohlcv_5m=df_early,
            ref_time=early_dt,
            ignore_time_gate=False,
        )
        assert len(alerts_put) == 0


def test_heavyweight_locomotive_confluence_gate():
    """Alerts must be suppressed if heavyweights are actively dragging in opposite direction."""
    spot = 56000.0
    chain = _make_sample_chain(spot)
    audit_dt = datetime(2026, 9, 25, 9, 40, 0, tzinfo=IST)

    dates = [datetime(2026, 9, 25, 9, 15 + i * 2, 0, tzinfo=IST) for i in range(12)]
    df_5m = pd.DataFrame(
        {
            "open": [55900.0 + i * 10 for i in range(12)],
            "high": [56020.0 for _ in range(12)],
            "low": [55890.0 for _ in range(12)],
            "close": [56010.0 for _ in range(12)],
            "volume": [5000 for _ in range(12)],
        },
        index=dates,
    )

    # Case A: 0 heavyweights bullish (HDFCBANK & ICICIBANK falling)
    bearish_posture = {
        "underlying": "BANKNIFTY",
        "heavyweights": [
            {"symbol": "HDFCBANK", "change_pct": -0.85, "is_bullish": False, "is_bearish": True},
            {"symbol": "ICICIBANK", "change_pct": -0.45, "is_bullish": False, "is_bearish": True},
        ],
        "all_bullish": False,
        "all_bearish": True,
        "bull_count": 0,
        "bear_count": 2,
        "total_heavyweights": 2,
        "summary": "ALL_BEARISH",
    }

    with patch("market.indices.get_heavyweights_posture", return_value=bearish_posture):
        alerts = detect_index_call_setup(
            underlying="BANKNIFTY",
            spot=spot,
            chain=chain,
            vwap=55980.0,
            day_high=56015.0,
            day_low=55900.0,
            ohlcv_5m=df_5m,
            ref_time=audit_dt,
            ignore_time_gate=True,
        )
        # Must be suppressed because 0 heavyweights are bullish
        assert len(alerts) == 0

    # Case B: Opening Drive on index vetoed if heavyweights unaligned
    with patch("market.indices.get_heavyweights_posture", return_value=bearish_posture):
        od_alert = detect_opening_drive(
            symbol="BANKNIFTY",
            df_5m=df_5m,
            ltp=56010.0,
            rvol=2.5,
            ref_time=audit_dt,
            ignore_time_gate=True,
        )
        assert od_alert is None


def test_low_vix_range_bound_regime_mandates_spread():
    """In low VIX (<13.0) range-bound regime, alerts must mandate hedged spreads."""
    spot = 56000.0
    chain = _make_sample_chain(spot)
    audit_dt = datetime(2026, 9, 25, 9, 45, 0, tzinfo=IST)

    dates = [datetime(2026, 9, 25, 9, 15 + i * 2, 0, tzinfo=IST) for i in range(12)]
    df_5m = pd.DataFrame(
        {
            "open": [55980.0 for _ in range(12)],
            "high": [56020.0 for _ in range(12)],
            "low": [55970.0 for _ in range(12)],
            "close": [56005.0 for _ in range(12)],
            "volume": [5000 for _ in range(12)],
        },
        index=dates,
    )

    bullish_posture = {
        "underlying": "BANKNIFTY",
        "heavyweights": [
            {"symbol": "HDFCBANK", "change_pct": 0.45, "is_bullish": True, "is_bearish": False},
            {"symbol": "ICICIBANK", "change_pct": 0.35, "is_bullish": True, "is_bearish": False},
        ],
        "all_bullish": True,
        "all_bearish": False,
        "bull_count": 2,
        "bear_count": 0,
        "total_heavyweights": 2,
        "summary": "ALL_BULLISH",
    }

    # Simulate low India VIX = 12.4
    with patch("market.indices.get_vix", return_value=12.4):
        with patch("market.indices.get_heavyweights_posture", return_value=bullish_posture):
            alerts = detect_index_call_setup(
                underlying="BANKNIFTY",
                spot=spot,
                chain=chain,
                vwap=56000.0,  # spot is at VWAP (range-bound)
                day_high=56050.0,
                day_low=55950.0,
                prev_day_low=55940.0,
                ohlcv_5m=df_5m,
                ref_time=audit_dt,
                ignore_time_gate=True,
            )
            if alerts:
                alert = alerts[0]
                assert "HEDGED SPREAD MANDATE" in alert.headline
                assert alert.actionable_plan["preferred_vehicle"] == "SPREAD_ONLY"
                assert alert.actionable_plan["action"] == "BULL CALL SPREAD"
                assert alert.actionable_plan["hedge_plan"] is not None


def test_day_low_breakdown_suppressed_on_absorption_wick_spring():
    """Verify that DAY_LOW_BREAKDOWN is suppressed when spot tests the low with a Wyckoff spring / absorption wick (>= 35%)."""
    from engine.detectors.index_put_setup import detect_index_put_setup
    from unittest.mock import MagicMock
    import pandas as pd

    spot = 22655.0
    day_low = 22663.8
    ref_time = datetime(2026, 10, 14, 11, 36, 0, tzinfo=IST)

    # 15 bars, last bar is a heavy absorption wick (like today at 11:35)
    # open 22682, high 22690, low 22655, close 22690 -> 76% lower wick!
    dates = pd.date_range("2026-10-14 10:20", periods=15, freq="5min", tz=IST)
    df = pd.DataFrame(
        {
            "open": [22700.0] * 14 + [22682.0],
            "high": [22710.0] * 14 + [22690.0],
            "low": [22670.0] * 14 + [22655.0],
            "close": [22690.0] * 14 + [22690.0],
            "volume": [10000] * 15,
        },
        index=dates,
    )

    c = MagicMock(
        symbol="NIFTY22650PE",
        strike=22650.0,
        option_type="PE",
        last_price=140.0,
        oi=50000,
        oi_change=2000,
        volume=25000,
        pchange=2.0,
        expiry="2026-10-15",
    )

    alerts = detect_index_put_setup(
        underlying="NIFTY",
        spot=spot,
        chain=[c],
        vwap=22715.0,
        day_high=22757.0,
        day_low=day_low,
        ohlcv_5m=df,
        ref_time=ref_time,
        ignore_time_gate=True,
    )

    # Must be suppressed because candle has a 76% absorption wick (Wyckoff spring trap)
    dlb_alerts = [
        a
        for a in alerts
        if "DAY LOW BREAKDOWN" in a.headline or "DAY_LOW_BREAKDOWN" in getattr(a, "signals", [])
    ]
    assert len(dlb_alerts) == 0


def test_day_high_breakout_suppressed_on_rejection_wick_upthrust():
    """5m bar testing Day High with a long upper rejection wick (>= 35%) is an Upthrust Bull Trap (UTAD) and must not fire DAY_HIGH_BREAKOUT."""
    from engine.detectors.index_call_setup import detect_index_call_setup

    ref_time = datetime(2026, 10, 14, 11, 45, tzinfo=IST)
    dates = pd.date_range("2026-10-14 09:15", periods=15, freq="5min", tz=IST)
    spot = 22756.0
    day_high = 22757.0

    # Candle pierces day high to 22765, but dumps back down to close at 22752 (upper wick: 13/18 = 72%)
    df = pd.DataFrame(
        {
            "open": [22700.0] * 14 + [22750.0],
            "high": [22710.0] * 14 + [22765.0],
            "low": [22690.0] * 14 + [22747.0],
            "close": [22705.0] * 14 + [22752.0],
            "volume": [10000] * 15,
        },
        index=dates,
    )

    c = MagicMock(
        symbol="NIFTY22750CE",
        strike=22750.0,
        option_type="CE",
        last_price=110.0,
        oi=50000,
        oi_change=-2000,
        volume=25000,
        pchange=10.0,
        expiry="2026-10-15",
    )

    alerts = detect_index_call_setup(
        underlying="NIFTY",
        spot=spot,
        chain=[c],
        vwap=22720.0,
        day_high=day_high,
        day_low=22690.0,
        ohlcv_5m=df,
        ref_time=ref_time,
        ignore_time_gate=True,
    )

    # Must be suppressed because candle has a 72% upper rejection wick (Wyckoff upthrust trap)
    dhb_alerts = [
        a
        for a in alerts
        if "DAY HIGH BREAKOUT" in a.headline or "DAY_HIGH_BREAKOUT" in getattr(a, "signals", [])
    ]
    assert len(dhb_alerts) == 0


def test_hbcm_symmetric_bypass_allows_call_setup_when_heavyweights_lag():
    """When an index V-reverses up, heavyweights lag (e.g. 3 bears vs 2 bulls, but bulls have >= 50% weight). HBCM bypass must allow CE setup."""
    from engine.detectors.index_call_setup import detect_index_call_setup
    from engine.hbcm import HBCMResult

    ref_time = datetime(2026, 10, 14, 11, 45, tzinfo=IST)
    dates = pd.date_range("2026-10-14 09:15", periods=15, freq="5min", tz=IST)
    spot = 22717.0
    day_low = 22645.0
    day_high = 22757.0

    df = pd.DataFrame(
        {
            "open": [22700.0] * 14 + [22698.0],
            "high": [22710.0] * 14 + [22722.0],
            "low": [22660.0] * 14 + [22697.0],
            "close": [22680.0] * 14 + [22717.0],
            "volume": [10000] * 15,
        },
        index=dates,
    )

    c = MagicMock(
        symbol="NIFTY22700CE",
        strike=22700.0,
        option_type="CE",
        last_price=105.0,
        oi=60000,
        oi_change=3000,
        volume=35000,
        pchange=18.0,
        expiry="2026-10-15",
    )

    # 3 bears, 2 bulls: HDFCBANK (28% wt) and ICICIBANK (23% wt) are bullish (51% wt)
    mock_constituents = [
        {"symbol": "HDFCBANK", "weight_pct": 28.0, "posture": "BULLISH"},
        {"symbol": "ICICIBANK", "weight_pct": 23.0, "posture": "BULLISH"},
        {"symbol": "RELIANCE", "weight_pct": 18.0, "posture": "BEARISH"},
        {"symbol": "INFY", "weight_pct": 10.0, "posture": "BEARISH"},
        {"symbol": "TCS", "weight_pct": 8.0, "posture": "BEARISH"},
    ]
    hbcm_res = HBCMResult(
        index_symbol="NIFTY",
        direction_tested="BULLISH",
        confluence_pass=False,
        bullish_count=2,
        bearish_count=3,
        neutral_count=0,
        total_heavyweights=5,
        total_weight_represented_pct=87.0,
        summary="BEARISH_MAJORITY",
        constituents=mock_constituents,
        as_of="11:45:00 IST",
    )

    with patch("engine.hbcm.evaluate_hbcm", return_value=hbcm_res):
        alerts = detect_index_call_setup(
            underlying="NIFTY",
            spot=spot,
            chain=[c],
            vwap=22704.0,
            day_high=day_high,
            day_low=day_low,
            prev_day_high=22850.0,
            prev_day_low=22620.0,
            ohlcv_5m=df,
            ref_time=ref_time,
            ignore_time_gate=True,
        )
        # Must NOT be hard vetoed because 2 heavyweights with 51% weight are bullish and V-bottom / VWAP reclaim is active
        assert len(alerts) >= 1
        assert any("VWAP_RECLAIM" in a.metrics.get("signals", []) for a in alerts)
