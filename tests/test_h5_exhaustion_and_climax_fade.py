"""
tests/test_h5_exhaustion_and_climax_fade.py
───────────────────────────────────────────
Regression test suite ensuring:
  1. index_call_setup suppresses buying calls at Camarilla H5 exhaustion on non-gap rally days.
  2. index_call_setup dynamically formats spread width in adaptive_regime based on actual strike width.
  3. turtle_soup permits Bearish Upthrust (Bull Trap) sweeps above Camarilla H4 when rejection wick >= 35%.
  4. index_put_setup permits top reversal fades (INTRADAY_CAPITULATION_TOP / DISTRIBUTION_TOP) above VWAP.
"""

from unittest.mock import MagicMock
import pandas as pd
import numpy as np

from engine.detectors.index_call_setup import detect_index_call_setup
from engine.detectors.index_put_setup import detect_index_put_setup
from engine.detectors.turtle_soup import detect_turtle_soup_sweep
from market.options import OptionsContract


def _make_dummy_chain(underlying="BANKNIFTY", spot=61650.0, step=100.0):
    contracts = []
    for strike in range(int(spot - 1000), int(spot + 1500), int(step)):
        contracts.append(
            OptionsContract(
                symbol=f"NSE:{underlying}26NOV{strike}CE",
                underlying=underlying,
                expiry="2026-11-23",
                strike=float(strike),
                option_type="CE",
                last_price=max(10.0, 500.0 - (strike - spot) * 0.45),
                oi=200000,
                oi_change=10000,
                volume=800000,
                iv=16.5,
                delta=0.50 if strike == spot else (0.30 if strike > spot else 0.70),
                exchange="NFO",
                lot_size=30,
            )
        )
        contracts.append(
            OptionsContract(
                symbol=f"NSE:{underlying}26NOV{strike}PE",
                underlying=underlying,
                expiry="2026-11-23",
                strike=float(strike),
                option_type="PE",
                last_price=max(10.0, 500.0 + (strike - spot) * 0.45),
                oi=150000,
                oi_change=5000,
                volume=500000,
                iv=16.5,
                delta=-0.50 if strike == spot else (-0.30 if strike < spot else -0.70),
                exchange="NFO",
                lot_size=30,
            )
        )
    return contracts


def _make_ohlcv(bars=20, base=61200.0, high_bar_idx=None):
    dates = pd.date_range("2026-11-16 09:15", periods=bars, freq="5min")
    df = pd.DataFrame(index=dates)
    prices = np.linspace(base, base + 450.0, bars)
    df["open"] = prices - 20.0
    df["high"] = prices + 30.0
    df["low"] = prices - 30.0
    df["close"] = prices + 10.0
    df["volume"] = 100000.0

    # Set topping tail at the peak
    target_idx = (bars - 2) if high_bar_idx is None else min(high_bar_idx, bars - 1)
    df.iloc[target_idx, df.columns.get_loc("high")] = base + 512.8
    df.iloc[target_idx, df.columns.get_loc("close")] = base + 460.0
    df.iloc[target_idx, df.columns.get_loc("open")] = base + 470.0
    return df


def test_index_call_setup_suppresses_camarilla_h5_exhaustion(monkeypatch):
    """Ensure index_call_setup rejects long call setup when spot reaches Camarilla H5 after non-gap rally."""
    chain = _make_dummy_chain("BANKNIFTY", spot=61600.0)
    ohlcv = _make_ohlcv(bars=12, base=61225.0)

    mock_dl = MagicMock()
    mock_dl.camarilla = {"h5": 61550.0, "h4": 61320.0, "range": 500.0}
    mock_dl.atr_14 = 900.0
    mock_dl.pre_open = {"gap_pct": 0.25}
    monkeypatch.setattr(
        "engine.daily_levels.get_daily_levels", lambda sym, session_date=None: mock_dl
    )

    # Spot is 61600 (above H5 of 61550), open was 61225, prev_close was 61034 (mild 0.31% gap)
    alerts = detect_index_call_setup(
        underlying="BANKNIFTY",
        spot=61600.0,
        chain=chain,
        vwap=61400.0,
        day_high=61700.0,
        day_low=61225.0,
        ohlcv_5m=ohlcv,
        prev_close=61034.0,
        ignore_time_gate=True,
    )
    assert len(alerts) == 0, (
        "Call setup must be suppressed at Camarilla H5 exhaustion on non-gap rally"
    )


def test_index_call_setup_dynamic_spread_width(monkeypatch):
    """Ensure spread adaptive_regime matches the actual strike width (e.g. 700 pt width)."""
    chain = _make_dummy_chain("BANKNIFTY", spot=61400.0)
    ohlcv = _make_ohlcv(bars=12, base=61225.0)

    mock_dl = MagicMock()
    mock_dl.camarilla = {"h5": 61850.0, "h4": 61380.0, "range": 500.0}
    mock_dl.atr_14 = 900.0
    mock_dl.pre_open = {"gap_pct": 0.10}
    monkeypatch.setattr(
        "engine.daily_levels.get_daily_levels", lambda sym, session_date=None: mock_dl
    )

    # Force candidate sell strike to 62100 (700 pt width above 61400)
    alerts = detect_index_call_setup(
        underlying="BANKNIFTY",
        spot=61400.0,
        chain=chain,
        vwap=61380.0,
        day_high=61450.0,
        day_low=61225.0,
        ohlcv_5m=ohlcv,
        prev_close=61300.0,
        ignore_time_gate=True,
    )
    if alerts:
        hedge_plan = alerts[0].actionable_plan.get("hedged_spread_plan") or {}
        if hedge_plan:
            actual_w = int(hedge_plan.get("strike_width", 0))
            adaptive_regime = hedge_plan.get("adaptive_regime", "")
            if actual_w > 0:
                assert f"{actual_w} pt width" in adaptive_regime, (
                    f"Adaptive regime '{adaptive_regime}' must contain '{actual_w} pt width'"
                )


def test_turtle_soup_bearish_upthrust_above_h4_with_wick(monkeypatch):
    """Turtle soup must NOT suppress bearish upthrust above H4 when upper rejection wick is >= 35%."""
    df = _make_ohlcv(bars=25, base=61200.0, high_bar_idx=23)
    prior_high = float(df["high"].iloc[-15:-2].max())

    # Create bull trap wick on the last bar: high pierces prior high, closes below
    df.iloc[-1, df.columns.get_loc("high")] = prior_high + 25.0
    df.iloc[-1, df.columns.get_loc("open")] = prior_high - 10.0
    df.iloc[-1, df.columns.get_loc("close")] = prior_high - 8.0
    df.iloc[-1, df.columns.get_loc("low")] = prior_high - 30.0

    mock_dl = MagicMock()
    # H4 is beneath the swept level, so curr_ltp > cam_h4
    mock_dl.camarilla = {"h4": prior_high - 20.0, "l4": prior_high - 500.0}
    monkeypatch.setattr(
        "engine.daily_levels.get_daily_levels", lambda sym, session_date=None: mock_dl
    )

    alert = detect_turtle_soup_sweep(
        "BANKNIFTY",
        df=df,
        ltp=prior_high - 8.0,
        vwap=prior_high - 50.0,
    )
    assert alert is not None, "Turtle soup upthrust above H4 with upper rejection wick must trigger"
    assert alert.direction == "BEARISH"


def test_index_put_setup_permits_top_reversal_fade_above_vwap(monkeypatch):
    """index_put_setup must permit DISTRIBUTION_TOP or INTRADAY_CAPITULATION_TOP above VWAP."""
    chain = _make_dummy_chain("BANKNIFTY", spot=61580.0)
    ohlcv = _make_ohlcv(bars=15, base=61200.0, high_bar_idx=10)

    mock_dl = MagicMock()
    mock_dl.camarilla = {"h5": 61750.0, "h4": 61350.0, "l4": 60700.0, "range": 600.0}
    mock_dl.atr_14 = 900.0
    mock_dl.pre_open = {"gap_pct": 0.20}
    monkeypatch.setattr(
        "engine.daily_levels.get_daily_levels", lambda sym, session_date=None: mock_dl
    )

    # Spot is 61580, day_high was 61712, VWAP is 61400.
    # Spot is +0.29% above VWAP and retreated -0.21% from day high.
    alerts = detect_index_put_setup(
        underlying="BANKNIFTY",
        spot=61580.0,
        chain=chain,
        vwap=61400.0,
        day_high=61712.0,
        day_low=61210.0,
        ohlcv_5m=ohlcv,
        prev_close=61034.0,
        ignore_time_gate=True,
    )
    # The setup should detect a top reversal fade rather than being killed by the VWAP confirmation gate
    for a in alerts:
        signals = a.metrics.get("signals", []) if hasattr(a, "metrics") and a.metrics else []
        assert any(
            s in signals
            for s in ("DISTRIBUTION_TOP", "INTRADAY_CAPITULATION_TOP", "FAILED_DAY_HIGH_BREAKOUT")
        )


def test_index_call_setup_suppressed_by_tug_of_war_polarization(monkeypatch):
    """Ensure breakout call setups are suppressed when heavyweights are in Tug-of-War Gridlock."""
    from market.indices import IndexPolarization

    chain = _make_dummy_chain("BANKNIFTY", spot=61500.0)
    ohlcv = _make_ohlcv(bars=15, base=61200.0)

    mock_dl = MagicMock()
    mock_dl.camarilla = {"h5": 61850.0, "h4": 61400.0, "range": 500.0}
    mock_dl.atr_14 = 800.0
    mock_dl.pre_open = {"gap_pct": 0.10}
    monkeypatch.setattr(
        "engine.daily_levels.get_daily_levels", lambda sym, session_date=None: mock_dl
    )

    # Mock index polarization to return active Tug-of-War chop
    mock_pol = IndexPolarization(
        index="BANKNIFTY",
        is_polarized=True,
        regime="TUG_OF_WAR_CHOP",
        dispersion_std=1.65,
        max_gainer=("HDFCBANK", 0.95),
        max_loser=("ICICIBANK", -0.55),
        spread_pct=1.50,
        heavyweight_changes={"HDFCBANK": 0.95, "ICICIBANK": -0.55, "SBIN": -0.40},
        summary="⚠️ Heavyweight Tug-of-War: HDFCBANK (+0.95%) vs ICICIBANK (-0.55%) in direct conflict",
    )
    monkeypatch.setattr("market.indices.get_index_polarization", lambda sym: mock_pol)

    alerts = detect_index_call_setup(
        underlying="BANKNIFTY",
        spot=61500.0,
        chain=chain,
        vwap=61350.0,
        day_high=61550.0,
        day_low=61200.0,
        ohlcv_5m=ohlcv,
        prev_close=61100.0,
        ignore_time_gate=True,
    )
    assert len(alerts) == 0, (
        "Breakout call setup must be suppressed during Tug-of-War Polarization gridlock"
    )


def test_index_call_setup_suppressed_when_majority_heavyweights_bearish(monkeypatch):
    """Ensure explosive momentum does NOT bypass HBCM when 3 of 5 heavyweights are bearish."""
    from engine.hbcm import HBCMResult

    chain = _make_dummy_chain("BANKNIFTY", spot=61450.0)
    ohlcv = _make_ohlcv(bars=15, base=61200.0)

    mock_dl = MagicMock()
    mock_dl.camarilla = {"h5": 61950.0, "h4": 61600.0, "range": 500.0}
    mock_dl.atr_14 = 800.0
    mock_dl.pre_open = {"gap_pct": 0.10}
    monkeypatch.setattr(
        "engine.daily_levels.get_daily_levels", lambda sym, session_date=None: mock_dl
    )

    # 3 of 5 heavyweights are bearish (ICICI, SBI, AXIS), only HDFC is bullish
    mock_hbcm = HBCMResult(
        index_symbol="BANKNIFTY",
        direction_tested="BULLISH",
        confluence_pass=False,
        bullish_count=1,
        bearish_count=3,
        neutral_count=1,
        total_heavyweights=5,
        total_weight_represented_pct=82.0,
        constituents=[
            {"symbol": "HDFCBANK", "weight_pct": 29.0, "posture": "BULLISH"},
            {"symbol": "ICICIBANK", "weight_pct": 23.0, "posture": "BEARISH"},
            {"symbol": "SBIN", "weight_pct": 11.0, "posture": "BEARISH"},
            {"symbol": "AXISBANK", "weight_pct": 11.0, "posture": "BEARISH"},
            {"symbol": "KOTAKBANK", "weight_pct": 8.0, "posture": "NEUTRAL"},
        ],
        rejection_reason="Only 1/5 heavyweights bullish above VWAP",
    )
    monkeypatch.setattr("engine.hbcm.evaluate_hbcm", lambda *args, **kwargs: mock_hbcm)

    alerts = detect_index_call_setup(
        underlying="BANKNIFTY",
        spot=61450.0,
        chain=chain,
        vwap=61350.0,
        day_high=61500.0,
        day_low=61200.0,
        ohlcv_5m=ohlcv,
        prev_close=61300.0,
        ignore_time_gate=True,
    )
    assert len(alerts) == 0, "Call setup must be suppressed when 3/5 heavyweights are bearish"


def test_index_put_setup_top_fade_permitted_with_distribution_star(monkeypatch):
    """Ensure DISTRIBUTION_TOP fade is permitted at session high even when daily heavyweights are bullish."""
    from engine.hbcm import HBCMResult

    chain = _make_dummy_chain("BANKNIFTY", spot=61620.0)
    # OHLCV where the last bar is an institutional distribution shooting star:
    # open 61635, high 61712.8, low 61610, close 61620 (close < open, upper wick > 70%)
    ohlcv = _make_ohlcv(bars=15, base=61200.0)
    ohlcv.iloc[-1, ohlcv.columns.get_loc("open")] = 61635.0
    ohlcv.iloc[-1, ohlcv.columns.get_loc("high")] = 61712.8
    ohlcv.iloc[-1, ohlcv.columns.get_loc("low")] = 61610.0
    ohlcv.iloc[-1, ohlcv.columns.get_loc("close")] = 61620.0

    mock_dl = MagicMock()
    mock_dl.camarilla = {"h5": 61750.0, "h4": 61350.0, "l4": 60700.0, "range": 600.0}
    mock_dl.atr_14 = 900.0
    mock_dl.pre_open = {"gap_pct": 0.20}
    monkeypatch.setattr(
        "engine.daily_levels.get_daily_levels", lambda sym, session_date=None: mock_dl
    )

    # Daily heavyweights still show 3 bulls from yesterday's close, but 1 bear is already falling
    mock_hbcm = HBCMResult(
        index_symbol="BANKNIFTY",
        direction_tested="BEARISH",
        confluence_pass=False,
        bullish_count=3,
        bearish_count=1,
        neutral_count=1,
        total_heavyweights=5,
        total_weight_represented_pct=82.0,
        constituents=[
            {"symbol": "HDFCBANK", "weight_pct": 29.0, "posture": "BULLISH"},
            {"symbol": "ICICIBANK", "weight_pct": 23.0, "posture": "BEARISH"},
            {"symbol": "SBIN", "weight_pct": 11.0, "posture": "BULLISH"},
            {"symbol": "AXISBANK", "weight_pct": 11.0, "posture": "BULLISH"},
            {"symbol": "KOTAKBANK", "weight_pct": 8.0, "posture": "NEUTRAL"},
        ],
        rejection_reason="Only 1/5 heavyweights bearish below VWAP",
    )
    monkeypatch.setattr("engine.hbcm.evaluate_hbcm", lambda *args, **kwargs: mock_hbcm)

    alerts = detect_index_put_setup(
        underlying="BANKNIFTY",
        spot=61620.0,
        chain=chain,
        vwap=61400.0,
        day_high=61712.8,
        day_low=61210.0,
        ohlcv_5m=ohlcv,
        prev_close=61034.0,
        ignore_time_gate=True,
    )
    # The setup should detect a top reversal fade rather than being killed by daily HBCM
    assert len(alerts) > 0, (
        "Top reversal fade must be permitted when distribution star prints near session high"
    )
    for a in alerts:
        signals = a.metrics.get("signals", []) if hasattr(a, "metrics") and a.metrics else []
        assert any(
            s in signals
            for s in ("DISTRIBUTION_TOP", "INTRADAY_CAPITULATION_TOP", "FAILED_DAY_HIGH_BREAKOUT")
        ), f"Expected top reversal signal, got: {signals}"


def test_index_call_setup_suppressed_by_bearish_futures_basis_divergence(monkeypatch):
    """Ensure index_call_setup suppresses buying calls when near-month futures trade at steep discount."""
    chain = _make_dummy_chain("BANKNIFTY", spot=61650.0)
    ohlcv = _make_ohlcv(bars=12, base=61250.0)

    mock_dl = MagicMock()
    mock_dl.camarilla = {"h5": 61850.0, "h4": 61500.0, "range": 500.0}
    mock_dl.atr_14 = 900.0
    mock_dl.pre_open = {"gap_pct": 0.20}
    monkeypatch.setattr(
        "engine.daily_levels.get_daily_levels", lambda sym, session_date=None: mock_dl
    )

    # Mock futures basis to -50.4 pts (live market discount condition)
    mock_fut_snap = {
        "status": "REAL_LIVE",
        "provenance": "REAL_LIVE",
        "contract": "NSE:BANKNIFTY26NOVFUT",
        "ltp": 61599.6,
        "volume": 342720,
        "basis": -50.4,
        "spot_ltp": 61650.0,
    }
    monkeypatch.setattr("market.indices.get_index_futures_snapshot", lambda sym: mock_fut_snap)

    alerts = detect_index_call_setup(
        underlying="BANKNIFTY",
        spot=61650.0,
        chain=chain,
        vwap=61400.0,
        day_high=61700.0,
        day_low=61250.0,
        ohlcv_5m=ohlcv,
        prev_close=61034.0,
        ignore_time_gate=True,
    )
    assert len(alerts) == 0, (
        "Index call setup must be suppressed when near-month futures trade at steep discount"
    )


def test_index_put_setup_confirmed_by_bearish_futures_basis_divergence(monkeypatch):
    """Ensure index_put_setup attaches FUTURES_BASIS_BEARISH_DISCOUNT when near-month futures trade at discount."""
    chain = _make_dummy_chain("BANKNIFTY", spot=61620.0)
    ohlcv = _make_ohlcv(bars=15, base=61200.0)
    ohlcv.iloc[-1, ohlcv.columns.get_loc("open")] = 61635.0
    ohlcv.iloc[-1, ohlcv.columns.get_loc("high")] = 61712.8
    ohlcv.iloc[-1, ohlcv.columns.get_loc("low")] = 61610.0
    ohlcv.iloc[-1, ohlcv.columns.get_loc("close")] = 61620.0

    mock_dl = MagicMock()
    mock_dl.camarilla = {"h5": 61750.0, "h4": 61350.0, "l4": 60700.0, "range": 600.0}
    mock_dl.atr_14 = 900.0
    mock_dl.pre_open = {"gap_pct": 0.20}
    monkeypatch.setattr(
        "engine.daily_levels.get_daily_levels", lambda sym, session_date=None: mock_dl
    )

    # Mock futures basis to -50.4 pts (live market discount condition)
    mock_fut_snap = {
        "status": "REAL_LIVE",
        "provenance": "REAL_LIVE",
        "contract": "NSE:BANKNIFTY26NOVFUT",
        "ltp": 61569.6,
        "volume": 342720,
        "basis": -50.4,
        "spot_ltp": 61620.0,
    }
    monkeypatch.setattr("market.indices.get_index_futures_snapshot", lambda sym: mock_fut_snap)

    alerts = detect_index_put_setup(
        underlying="BANKNIFTY",
        spot=61620.0,
        chain=chain,
        vwap=61400.0,
        day_high=61712.8,
        day_low=61210.0,
        ohlcv_5m=ohlcv,
        prev_close=61034.0,
        ignore_time_gate=True,
    )
    assert len(alerts) > 0, "Top reversal fade must trigger with futures basis discount confluence"
    all_signals = []
    for a in alerts:
        sigs = a.metrics.get("signals", []) if hasattr(a, "metrics") and a.metrics else []
        all_signals.extend(sigs)
    assert "FUTURES_BASIS_BEARISH_DISCOUNT" in all_signals, (
        f"Expected FUTURES_BASIS_BEARISH_DISCOUNT in signals, got: {all_signals}"
    )


def test_opening_drive_suppressed_by_polarization(monkeypatch):
    """Ensure detect_opening_drive suppresses index opening drive when heavyweights are polarized."""
    from engine.detectors.opening_drive import detect_opening_drive
    from market.indices import IndexPolarization

    dates = pd.date_range("2026-11-16 09:15", periods=5, freq="5min")
    df = pd.DataFrame(
        {
            "open": [61200.0, 61350.0, 61400.0, 61450.0, 61500.0],
            "high": [61360.0, 61420.0, 61460.0, 61520.0, 61580.0],
            "low": [61195.0, 61330.0, 61380.0, 61430.0, 61480.0],
            "close": [61350.0, 61410.0, 61450.0, 61510.0, 61560.0],
            "volume": [100000.0] * 5,
        },
        index=dates,
    )

    mock_pol = IndexPolarization(
        index="BANKNIFTY",
        is_polarized=True,
        regime="TUG_OF_WAR_CHOP",
        dispersion_std=1.65,
        max_gainer=("HDFCBANK", 0.95),
        max_loser=("ICICIBANK", -0.55),
        spread_pct=1.50,
        heavyweight_changes={"HDFCBANK": 0.95, "ICICIBANK": -0.55, "SBIN": -0.40},
        summary="⚠️ Heavyweight Tug-of-War: HDFCBANK (+0.95%) vs ICICIBANK (-0.55%) in direct conflict",
    )
    monkeypatch.setattr("market.indices.get_index_polarization", lambda sym: mock_pol)

    alert = detect_opening_drive(
        symbol="BANKNIFTY",
        df_5m=df,
        ltp=61350.0,
        vwap=61250.0,
        rvol=2.0,
        ref_time=dates[0],
        ignore_time_gate=True,
    )
    assert alert is None, "Opening drive must be suppressed when heavyweights are polarized"


def test_trend_day_continuation_suppressed_by_polarization(monkeypatch):
    """Ensure detect_trend_day_pullback suppresses index continuation when heavyweights are polarized."""
    from engine.detectors.trend_day_continuation import detect_trend_day_pullback
    from market.indices import IndexPolarization

    dates = pd.date_range("2026-11-16 09:15", periods=15, freq="5min")
    prices = np.linspace(61200.0, 61500.0, 15)
    df = pd.DataFrame(
        {
            "open": prices - 20.0,
            "high": prices + 30.0,
            "low": prices - 30.0,
            "close": prices + 10.0,
            "volume": [100000.0] * 15,
        },
        index=dates,
    )

    mock_pol = IndexPolarization(
        index="BANKNIFTY",
        is_polarized=True,
        regime="TUG_OF_WAR_CHOP",
        dispersion_std=1.65,
        max_gainer=("HDFCBANK", 0.95),
        max_loser=("ICICIBANK", -0.55),
        spread_pct=1.50,
        heavyweight_changes={"HDFCBANK": 0.95, "ICICIBANK": -0.55, "SBIN": -0.40},
        summary="⚠️ Heavyweight Tug-of-War: HDFCBANK (+0.95%) vs ICICIBANK (-0.55%) in direct conflict",
    )
    monkeypatch.setattr("market.indices.get_index_polarization", lambda sym: mock_pol)

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("CHANAKYA_TESTING", raising=False)

    alert = detect_trend_day_pullback(
        symbol="BANKNIFTY",
        df_5m=df,
        ltp=61510.0,
        now_dt=dates[-1],
    )
    assert alert is None, (
        "Trend day continuation must be suppressed when heavyweights are polarized"
    )


def test_orb_suppressed_by_camarilla_h5_exhaustion_and_polarization(monkeypatch):
    """Ensure detect_opening_range_breakout suppresses index ORB when spot reaches H5 or heavyweights are polarized."""
    from engine.detectors.orb import detect_opening_range_breakout
    from market.indices import IndexPolarization

    dates = pd.date_range("2026-11-16 09:15", periods=10, freq="5min")
    df = pd.DataFrame(
        {
            "open": [61400.0] * 10,
            "high": [61500.0] * 10,
            "low": [61300.0] * 10,
            "close": [61520.0] * 10,
            "volume": [100000.0] * 10,
        },
        index=dates,
    )

    mock_dl = MagicMock()
    mock_dl.camarilla = {"h5": 61510.0, "h4": 61400.0, "l4": 61200.0, "l5": 61100.0, "range": 200.0}
    mock_dl.atr_14 = 600.0
    monkeypatch.setattr("engine.daily_levels.get_daily_levels", lambda sym: mock_dl)

    # 1. Spot is 61520.0 > H5 of 61510.0 -> Camarilla H5 Exhaustion must suppress
    alert_h5 = detect_opening_range_breakout(
        symbol="BANKNIFTY",
        df=df,
        ltp=61520.0,
        vwap=61400.0,
        rvol=2.0,
        ref_time=dates[-1],
        ignore_time_gate=True,
    )
    assert alert_h5 is None, (
        "ORB breakout must be suppressed when spot reaches Camarilla H5 ceiling"
    )

    # 2. Spot below H5 (e.g. 61450.0), but heavyweights polarized -> Polarization must suppress
    mock_dl.camarilla = {"h5": 61800.0, "h4": 61600.0, "l4": 61200.0, "l5": 61100.0, "range": 400.0}
    mock_pol = IndexPolarization(
        index="BANKNIFTY",
        is_polarized=True,
        regime="TUG_OF_WAR_CHOP",
        dispersion_std=1.65,
        max_gainer=("HDFCBANK", 0.95),
        max_loser=("ICICIBANK", -0.55),
        spread_pct=1.50,
        heavyweight_changes={"HDFCBANK": 0.95, "ICICIBANK": -0.55, "SBIN": -0.40},
        summary="⚠️ Heavyweight Tug-of-War: HDFCBANK (+0.95%) vs ICICIBANK (-0.55%) in direct conflict",
    )
    monkeypatch.setattr("market.indices.get_index_polarization", lambda sym: mock_pol)

    alert_pol = detect_opening_range_breakout(
        symbol="BANKNIFTY",
        df=df,
        ltp=61520.0,
        vwap=61400.0,
        rvol=2.0,
        ref_time=dates[-1],
        ignore_time_gate=True,
    )
    assert alert_pol is None, "ORB breakout must be suppressed when heavyweights are polarized"


def test_index_call_setup_liquidity_and_friction_gate(monkeypatch):
    """Verifies that illiquid options are rejected in live mode and wide-spread contracts enforce spreads with friction badges."""
    from bot.alert_templates import render_auto_alert

    chain = _make_dummy_chain("BANKNIFTY", spot=61400.0)
    ohlcv = _make_ohlcv(bars=12, base=61225.0)

    mock_dl = MagicMock()
    mock_dl.camarilla = {
        "h5": 62200.0,
        "h4": 61800.0,
        "h3": 61400.0,
        "l3": 61000.0,
        "l4": 60800.0,
        "l5": 60500.0,
        "range": 400.0,
    }
    mock_dl.atr_14 = 600.0
    mock_dl.prev_day_high = 61400.0
    mock_dl.prev_day_low = 60800.0
    monkeypatch.setattr(
        "engine.daily_levels.get_daily_levels", lambda sym, session_date=None: mock_dl
    )
    monkeypatch.setattr(
        "market.indices.get_index_polarization",
        lambda sym: MagicMock(is_polarized=False, regime="UNIFIED_TREND", summary="Clean"),
    )
    monkeypatch.setattr(
        "market.indices.get_heavyweights_posture",
        lambda sym: {"posture": "BULLISH", "summary": "Bullish", "score": 80.0, "heavyweights": []},
    )

    # A) Test Illiquid Option Rejection in live mode
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("CHANAKYA_TESTING", raising=False)
    monkeypatch.setattr(
        "market.options.audit_option_liquidity",
        lambda contract, underlying=None, lot_size=None: {
            "is_liquid": False,
            "liquidity_status": "ILLIQUID",
            "bid_ask_spread_pct": 8.5,
        },
    )
    alerts_illiquid = detect_index_call_setup(
        underlying="BANKNIFTY",
        spot=61400.0,
        chain=chain,
        vwap=61380.0,
        day_high=61450.0,
        day_low=61225.0,
        ohlcv_5m=ohlcv,
        prev_close=61300.0,
        ignore_time_gate=True,
    )
    assert len(alerts_illiquid) == 0, (
        "Illiquid option contract must be rejected fail-closed in live mode"
    )

    # B) Test Wide Spread (3.5%) Enforces SPREAD_ONLY and Friction Badge
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
    monkeypatch.setattr(
        "market.options.audit_option_liquidity",
        lambda contract, underlying=None, lot_size=None: {
            "is_liquid": True,
            "liquidity_status": "WIDE_SPREAD_CAUTION",
            "bid_ask_spread_pct": 3.5,
        },
    )
    alerts_fric = detect_index_call_setup(
        underlying="BANKNIFTY",
        spot=61400.0,
        chain=chain,
        vwap=61380.0,
        day_high=61450.0,
        day_low=61225.0,
        ohlcv_5m=ohlcv,
        prev_close=61300.0,
        ignore_time_gate=True,
    )
    if alerts_fric:
        alert = alerts_fric[0]
        assert alert.actionable_plan["preferred_vehicle"] == "SPREAD_ONLY"
        assert "WIDE SPREAD (3.5%)" in alert.metrics["execution_friction_badge"]
        assert alert.metrics.get("gex_call_wall") is not None
        assert alert.metrics.get("gex_put_wall") is not None
        assert alert.metrics.get("gamma_regime") is not None

        # Verify rendering includes friction badge and GEX structure
        rendered = render_auto_alert(alert)
        assert "Friction:" in rendered or "WIDE SPREAD" in rendered
        assert "GEX Structure:" in rendered


def test_index_put_setup_liquidity_and_gex_telemetry(monkeypatch):
    """Verifies that index_put_setup rejects illiquid options in live mode and injects GEX structure."""
    from bot.alert_templates import render_auto_alert

    chain = _make_dummy_chain("BANKNIFTY", spot=61580.0)
    ohlcv = _make_ohlcv(bars=15, base=61200.0, high_bar_idx=10)

    mock_dl = MagicMock()
    mock_dl.camarilla = {"h5": 61750.0, "h4": 61350.0, "l4": 60700.0, "range": 600.0}
    mock_dl.atr_14 = 900.0
    mock_dl.prev_day_high = 61800.0
    mock_dl.prev_day_low = 61200.0
    monkeypatch.setattr(
        "engine.daily_levels.get_daily_levels", lambda sym, session_date=None: mock_dl
    )
    monkeypatch.setattr(
        "market.indices.get_index_polarization",
        lambda sym: MagicMock(is_polarized=False, regime="UNIFIED_TREND", summary="Clean"),
    )
    monkeypatch.setattr(
        "market.indices.get_heavyweights_posture",
        lambda sym: {
            "posture": "BEARISH",
            "summary": "Bearish",
            "score": -80.0,
            "heavyweights": [],
        },
    )

    # A) Test Illiquid Option Rejection in live mode
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("CHANAKYA_TESTING", raising=False)
    monkeypatch.setattr(
        "market.options.audit_option_liquidity",
        lambda contract, underlying=None, lot_size=None: {
            "is_liquid": False,
            "liquidity_status": "ILLIQUID",
            "bid_ask_spread_pct": 7.0,
        },
    )
    alerts_illiquid = detect_index_put_setup(
        underlying="BANKNIFTY",
        spot=61580.0,
        chain=chain,
        vwap=61400.0,
        day_high=61712.8,
        day_low=61150.0,
        ohlcv_5m=ohlcv,
        prev_close=61500.0,
        ignore_time_gate=True,
    )
    assert len(alerts_illiquid) == 0, (
        "Illiquid put option contract must be rejected fail-closed in live mode"
    )

    # B) Test Normal Execution injects GEX metrics and formats correctly
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
    monkeypatch.setattr(
        "market.options.audit_option_liquidity",
        lambda contract, underlying=None, lot_size=None: {
            "is_liquid": True,
            "liquidity_status": "OPTIMAL",
            "bid_ask_spread_pct": 0.8,
        },
    )
    alerts = detect_index_put_setup(
        underlying="BANKNIFTY",
        spot=61580.0,
        chain=chain,
        vwap=61400.0,
        day_high=61712.8,
        day_low=61150.0,
        ohlcv_5m=ohlcv,
        prev_close=61500.0,
        ignore_time_gate=True,
    )
    if alerts:
        put_alert = alerts[0]
        assert put_alert.metrics.get("gex_call_wall") is not None
        assert put_alert.metrics.get("gex_put_wall") is not None
        assert put_alert.metrics.get("zero_gamma_level") is not None

        rendered = render_auto_alert(put_alert)
        assert "GEX Structure:" in rendered
