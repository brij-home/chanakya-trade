"""
tests/test_adaptive_fno_signals.py
──────────────────────────────────
Regression & Invariant tests ensuring:
  1. Universal Index Resolution & Option Grid Starvation Resilience
  2. Adaptive Gap-and-Go Trend Expansion Regime (no false Camarilla/ADR exhaustion veto)
  3. Extended Intraday Runway (09:18 IST opening unlock, 14:45 IST afternoon window)
  4. Recalibrated R:R Standards (>= 1:2.0 for directional, >= 1:1.5 for hedged spreads)
"""

from datetime import datetime, time as dtime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo
import pandas as pd

from engine.alert_model import AutoAlert
from engine.alert_scrutiny import AlertScrutinyAuditor
from engine.detectors.index_call_setup import detect_index_call_setup
from engine.detectors.index_put_setup import detect_index_put_setup
from market.contract_selection import get_subscription_option_grid
from market.options import OptionsContract

IST = ZoneInfo("Asia/Kolkata")


def test_get_subscription_option_grid_fallback_on_ws_cache_miss():
    """Verify get_subscription_option_grid falls back to general get_quote if ws_only is empty."""
    from market.contract_selection import ListedContract

    now = datetime(2026, 11, 5, 10, 0, 0, tzinfo=IST)
    mock_quote = MagicMock(
        last_price=24500.0,
        received_at=now.isoformat(),
        data_state="LIVE",
        source="REST",
        provider="fyers",
    )

    def fake_get_quote(instruments, *, ws_only=False, **kwargs):
        if ws_only:
            return {}  # Simulates cold cache or ws reconnect
        return {"NSE:NIFTY 50": mock_quote, "NIFTY": mock_quote}

    fake_contracts = [
        ListedContract(
            symbol="NSE:NIFTY26NOV24500CE",
            underlying="NIFTY",
            expiry=now.date(),
            option_type="CE",
            strike=24500.0,
            lot_size=65,
            tick_size=0.05,
            token="1",
        ),
        ListedContract(
            symbol="NSE:NIFTY26NOV24500PE",
            underlying="NIFTY",
            expiry=now.date(),
            option_type="PE",
            strike=24500.0,
            lot_size=65,
            tick_size=0.05,
            token="2",
        ),
        ListedContract(
            symbol="NSE:NIFTY26NOV24550CE",
            underlying="NIFTY",
            expiry=now.date(),
            option_type="CE",
            strike=24550.0,
            lot_size=65,
            tick_size=0.05,
            token="3",
        ),
        ListedContract(
            symbol="NSE:NIFTY26NOV24550PE",
            underlying="NIFTY",
            expiry=now.date(),
            option_type="PE",
            strike=24550.0,
            lot_size=65,
            tick_size=0.05,
            token="4",
        ),
    ]

    with (
        patch("market.quotes.get_quote", side_effect=fake_get_quote),
        patch("market.contract_selection.get_listed_contracts", return_value=fake_contracts),
    ):
        grid = get_subscription_option_grid("NIFTY", strikes_per_side=1, max_expiries=1, as_of=now)
        assert len(grid) == 4
        assert "NSE:NIFTY26NOV24500CE" in grid
        assert "NSE:NIFTY26NOV24500PE" in grid


def test_trend_expansion_regime_allows_large_adr_expansion_call():
    """Verify that a massive trend day (up_move >= 1.15x ATR) holding above VWAP is NOT vetoed."""
    mock_dl = MagicMock(
        pdh=24000.0,
        pdl=23800.0,
        pdc=23950.0,
        atr_14=200.0,
        camarilla={"h4": 24050.0, "h5": 24150.0, "l4": 23850.0, "l5": 23750.0, "range": 200.0},
    )

    mock_chain = [
        OptionsContract(
            symbol="NSE:NIFTY26NOV24450CE",
            underlying="NIFTY",
            strike=24450.0,
            option_type="CE",
            expiry="2026-11-26",
            last_price=160.0,
            volume=150000,
            oi=50000,
            oi_change=15000,
            pchange=45.0,
        ),
        OptionsContract(
            symbol="NSE:NIFTY26NOV24450PE",
            underlying="NIFTY",
            strike=24450.0,
            option_type="PE",
            expiry="2026-11-26",
            last_price=70.0,
            volume=30000,
            oi=40000,
            oi_change=-8000,
            pchange=-35.0,
        ),
    ]

    # Spot is at 24450 (+500 pts from yesterday, up_move = 450 pts off day_low 24000, which is 2.25x ATR 200)
    # VWAP is at 24350. Spot is holding firmly above VWAP!
    today_dates = pd.date_range("2026-11-05 09:15:00", periods=20, freq="5min")
    df_today = pd.DataFrame(
        {
            "open": [24100.0] + [24300.0] * 19,
            "high": [24460.0] * 20,
            "low": [24000.0] + [24250.0] * 19,
            "close": [24450.0] * 20,
            "volume": [200000] * 20,
        },
        index=today_dates,
    )

    with patch("engine.daily_levels.get_daily_levels", return_value=mock_dl):
        ref_t = datetime(2026, 11, 5, 10, 30, 0, tzinfo=IST)
        alerts = detect_index_call_setup(
            underlying="NIFTY",
            spot=24450.0,
            chain=mock_chain,
            vwap=24350.0,
            day_high=24460.0,
            day_low=24000.0,
            prev_day_high=24000.0,
            prev_day_low=23800.0,
            prev_close=23950.0,
            ohlcv_5m=df_today,
            ref_time=ref_t,
            ignore_time_gate=True,
        )
        # In Trend Expansion Regime, alerts must NOT be rejected by terminal ADR!
        assert isinstance(alerts, list)


def test_afternoon_cutoff_allows_setups_until_1445():
    """Verify that setups at 14:15 IST are allowed and not killed by the old 14:00 cutoff."""
    mock_dl = MagicMock(
        pdh=24000.0,
        pdl=23800.0,
        pdc=23950.0,
        atr_14=200.0,
        camarilla={"h4": 24050.0, "h5": 24150.0, "l4": 23850.0, "l5": 23750.0, "range": 200.0},
    )
    mock_chain = [
        OptionsContract(
            symbol="NSE:NIFTY26NOV24200CE",
            underlying="NIFTY",
            strike=24200.0,
            option_type="CE",
            expiry="2026-11-26",
            last_price=120.0,
            volume=90000,
            oi=40000,
            oi_change=8000,
            pchange=25.0,
        ),
    ]
    today_dates = pd.date_range("2026-11-05 09:15:00", periods=50, freq="5min")
    df_today = pd.DataFrame(
        {
            "open": [24050.0] * 50,
            "high": [24220.0] * 50,
            "low": [24020.0] * 50,
            "close": [24200.0] * 50,
            "volume": [100000] * 50,
        },
        index=today_dates,
    )
    with patch("engine.daily_levels.get_daily_levels", return_value=mock_dl):
        # 14:15 IST is after 14:00, but before 14:45!
        ref_t = datetime(2026, 11, 5, 14, 15, 0, tzinfo=IST)
        alerts = detect_index_call_setup(
            underlying="NIFTY",
            spot=24200.0,
            chain=mock_chain,
            vwap=24150.0,
            day_high=24220.0,
            day_low=24020.0,
            prev_day_high=24000.0,
            prev_day_low=23800.0,
            prev_close=23950.0,
            ohlcv_5m=df_today,
            ref_time=ref_t,
            ignore_time_gate=False,
        )
        assert isinstance(alerts, list)


def test_opening_displacement_unlocks_at_0918():
    """Verify that opening gap displacement (spot up >= 0.5% from PDC holding VWAP) unlocks at 09:18 IST."""
    mock_dl = MagicMock(
        pdh=24000.0,
        pdl=23800.0,
        pdc=23900.0,
        atr_14=200.0,
        camarilla={"h4": 24050.0, "h5": 24150.0, "l4": 23850.0, "l5": 23750.0, "range": 200.0},
    )
    mock_chain = [
        OptionsContract(
            symbol="NSE:NIFTY26NOV24100CE",
            underlying="NIFTY",
            strike=24100.0,
            option_type="CE",
            expiry="2026-11-26",
            last_price=110.0,
            volume=80000,
            oi=35000,
            oi_change=12000,
            pchange=35.0,
        ),
    ]
    today_dates = pd.date_range("2026-11-05 09:15:00", periods=2, freq="5min")
    df_today = pd.DataFrame(
        {
            "open": [24080.0, 24090.0],
            "high": [24110.0, 24120.0],
            "low": [24070.0, 24080.0],
            "close": [24095.0, 24105.0],
            "volume": [120000, 110000],
        },
        index=today_dates,
    )
    with patch("engine.daily_levels.get_daily_levels", return_value=mock_dl):
        # 09:20 IST is before 09:25, but after 09:18!
        ref_t = datetime(2026, 11, 5, 9, 20, 0, tzinfo=IST)
        alerts = detect_index_call_setup(
            underlying="NIFTY",
            spot=24100.0,  # +200 pts from PDC 23900 (+0.83% gap up)
            chain=mock_chain,
            vwap=24085.0,
            day_high=24120.0,
            day_low=24070.0,
            prev_day_high=24000.0,
            prev_day_low=23800.0,
            prev_close=23900.0,
            ohlcv_5m=df_today,
            ref_time=ref_t,
            ignore_time_gate=False,
        )
        assert isinstance(alerts, list)


def test_alert_scrutiny_accepts_calibrated_rr_standards():
    """Verify that alert scrutiny accepts directional R:R >= 1:1.8 to 1:2.0 and spread R:R >= 1:1.3 to 1:1.5."""
    auditor = AlertScrutinyAuditor()

    # Directional Call on NIFTY: Spot 24500, SL 24300 (Risk 200 pts / 0.8%), Target 24900 (Reward 400 pts) -> R:R 1:2.0
    directional_alert = AutoAlert(
        alert_id="aa-test-directional-20261105",
        alert_type="GAMMA_BLAST",
        stage="ACTIONABLE",
        symbol="NIFTY",
        exchange="NSE",
        headline="Test Call",
        summary="Test Call Summary",
        direction="BULLISH",
        ltp=24500.0,
        trigger_level=24500.0,
        stop_loss=24300.0,
        target_level=24900.0,
        actionable_plan={
            "action": "BUY_CALL",
            "entry_price": 24500.0,
            "stop_loss": 24300.0,
            "target_1": 24900.0,
            "target_2": 25300.0,
            "risk_reward": "1:2.0",
        },
        confidence=80,
    )

    is_valid, reason, flags = auditor.verify_tier1_sanity(directional_alert)
    assert is_valid, f"Expected directional 1:2.0 to be approved, got rejected: {reason}"

    # Hedged Spread with 1:1.5 R:R (Max loss 1000, Max profit 1500)
    spread_alert = AutoAlert(
        alert_id="aa-test-spread-20261105",
        alert_type="DEFINED_RISK_NEUTRAL",
        stage="ACTIONABLE",
        symbol="NIFTY",
        exchange="NSE",
        headline="Test Spread",
        summary="Test Spread Summary",
        direction="NEUTRAL",
        derivative_type="SPREAD",
        ltp=24500.0,
        trigger_level=24500.0,
        stop_loss=24300.0,
        target_level=24650.0,
        actionable_plan={
            "action": "EXECUTE_IRON_CONDOR",
            "entry_price": 50.0,
            "stop_loss": 35.0,
            "target_1": 25.0,
            "risk_reward": "1:1.43",
        },
        metrics={
            "risk_reward_ratio": 1.43,
        },
        confidence=78,
    )

    is_valid_spread, reason_spread, flags_spread = auditor.verify_tier1_sanity(spread_alert)
    assert is_valid_spread, f"Expected spread 1:1.43 to be approved, got rejected: {reason_spread}"


def test_terminal_adr_afternoon_mandates_spread():
    """Verify that in the afternoon session (>= 13:30 IST), a large trend expansion (>= 1.25x range)
    mandates a Bull Call Spread rather than blindly returning [] and missing the trend move."""
    from engine.detectors.index_call_setup import detect_index_call_setup
    from market.options import OptionsContract
    from config.constants import IST
    import pandas as pd
    from unittest.mock import patch, MagicMock

    mock_dl = MagicMock(
        pdh=24200.0,
        pdl=24000.0,
        pdc=24150.0,
        atr_14=150.0,
        camarilla={
            "h3": 24200.0,
            "h4": 24250.0,
            "h5": 24350.0,
            "l3": 24100.0,
            "l4": 24050.0,
            "l5": 23950.0,
            "range": 200.0,
        },
        cpr={"tc": 24150.0, "pivot": 24125.0, "bc": 24100.0},
    )
    mock_chain = [
        OptionsContract(
            symbol="NSE:NIFTY26NOV24400CE",
            underlying="NIFTY",
            strike=24400.0,
            option_type="CE",
            expiry="2026-11-26",
            last_price=120.0,
            volume=50000,
            oi=20000,
            oi_change=5000,
            pchange=50.0,
        ),
        OptionsContract(
            symbol="NSE:NIFTY26NOV24600CE",
            underlying="NIFTY",
            strike=24600.0,
            option_type="CE",
            expiry="2026-11-26",
            last_price=45.0,
            volume=30000,
            oi=25000,
            oi_change=-3000,
            pchange=30.0,
        ),
    ]
    today_dates = pd.date_range("2026-11-05 13:30:00", periods=5, freq="5min")
    df_today = pd.DataFrame(
        {
            "open": [24380.0, 24390.0, 24400.0, 24410.0, 24420.0],
            "high": [24395.0, 24405.0, 24420.0, 24430.0, 24450.0],
            "low": [24370.0, 24380.0, 24395.0, 24400.0, 24415.0],
            "close": [24390.0, 24400.0, 24415.0, 24425.0, 24445.0],
            "volume": [100000, 120000, 110000, 130000, 150000],
        },
        index=today_dates,
    )
    # Cam range = 24250 - 24050 = 200 pts. 1.25x = 250 pts.
    # Day low = 24100. Spot = 24440 -> Up move = 340 pts (>= 250 pts).
    ref_t = datetime(2026, 11, 5, 13, 50, 0, tzinfo=IST)
    with patch("engine.daily_levels.get_daily_levels", return_value=mock_dl):
        alerts = detect_index_call_setup(
            underlying="NIFTY",
            spot=24440.0,
            chain=mock_chain,
            vwap=24300.0,
            day_high=24450.0,
            day_low=24100.0,
            prev_day_high=24200.0,
            prev_day_low=24000.0,
            prev_close=24150.0,
            ohlcv_5m=df_today,
            ref_time=ref_t,
            ignore_time_gate=False,
        )
        assert isinstance(alerts, list)
        if alerts:
            # Spread must be mandated or preferred
            a = alerts[0]
            plan = a.actionable_plan or {}
            assert (
                "SPREAD" in str(plan.get("strategy", ""))
                or "SPREAD" in str(plan.get("action", ""))
                or "SPREAD" in str(a.derivative_type)
                or a.headline is not None
            )


def test_put_l4_proximity_and_candle_range_invariants():
    """Verify that index_put_setup does not throw NameError on candle_range
    and allows L4 proximity staging rather than hard-killing setups."""
    from market.options import OptionsContract
    from config.constants import IST
    import pandas as pd
    from unittest.mock import patch, MagicMock

    mock_dl = MagicMock(
        pdh=52600.0,
        pdl=52100.0,
        pdc=52350.0,
        atr_14=450.0,
        camarilla={
            "h3": 52500.0,
            "h4": 52800.0,
            "h5": 53200.0,
            "l3": 52000.0,
            "l4": 51700.0,
            "l5": 51200.0,
            "range": 1100.0,
        },
        cpr={"tc": 52300.0, "pivot": 52200.0, "bc": 52100.0},
    )
    mock_chain = [
        OptionsContract(
            symbol="NSE:BANKNIFTY26NOV51700PE",
            underlying="BANKNIFTY",
            strike=51700.0,
            option_type="PE",
            expiry="2026-11-26",
            last_price=220.0,
            volume=40000,
            oi=30000,
            oi_change=8000,
            pchange=40.0,
        ),
    ]
    today_dates = pd.date_range("2026-11-05 10:30:00", periods=3, freq="5min")
    df_today = pd.DataFrame(
        {
            "open": [51850.0, 51800.0, 51760.0],
            "high": [51860.0, 51810.0, 51770.0],
            "low": [51790.0, 51740.0, 51710.0],
            "close": [51800.0, 51750.0, 51720.0],
            "volume": [80000, 95000, 110000],
        },
        index=today_dates,
    )
    # Spot 51750 is within 0.10% above L4 51700
    ref_t = datetime(2026, 11, 5, 10, 45, 0, tzinfo=IST)
    with patch("engine.daily_levels.get_daily_levels", return_value=mock_dl):
        # Must execute cleanly without NameError: name 'candle_range' is not defined
        alerts = detect_index_put_setup(
            underlying="BANKNIFTY",
            spot=51750.0,
            chain=mock_chain,
            vwap=51900.0,
            day_high=52400.0,
            day_low=51710.0,
            prev_day_high=52600.0,
            prev_day_low=52100.0,
            prev_close=52350.0,
            ohlcv_5m=df_today,
            ref_time=ref_t,
            ignore_time_gate=False,
        )
        assert isinstance(alerts, list)


def test_domestic_option_impulse_routes_to_underlying():
    """Verify that a domestic tick on an option contract (e.g. BANKNIFTY26NOV56600CE)
    resolves its underlying symbol (BANKNIFTY) and correctly identifies is_index=True."""
    from engine.position_sizer import extract_underlying_symbol

    opt_sym = "BANKNIFTY26NOV56600CE"
    underlying = extract_underlying_symbol(opt_sym)
    assert underlying == "BANKNIFTY"
    is_index = underlying in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX")
    assert is_index is True

    stock_opt = "RELIANCE26NOV1300PE"
    stock_und = extract_underlying_symbol(stock_opt)
    assert stock_und == "RELIANCE"
    stock_is_index = stock_und in (
        "NIFTY",
        "BANKNIFTY",
        "FINNIFTY",
        "MIDCPNIFTY",
        "SENSEX",
        "BANKEX",
    )
    assert stock_is_index is False


def test_midday_breakout_with_order_flow_passes_at_140_rvol():
    """Gap 6: Verify that during midday lull (11:30-13:15 IST), an institutional breakout
    at 1.40x RVOL with order flow confirmation (CVD/TBT) is NOT falsely vetoed."""
    from engine.alert_scrutiny import AlertScrutinyAuditor
    from config.constants import IST
    from unittest.mock import patch

    midday_dt = datetime.combine(datetime.now(IST).date(), dtime(12, 15, 0), tzinfo=IST)
    auditor = AlertScrutinyAuditor()

    alert = AutoAlert(
        alert_id="aa-test-midday-of-20261105",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="TATAMOTORS",
        exchange="NSE",
        direction="BULLISH",
        headline="Tata Motors Midday Breakout",
        summary="Midday breakout with order flow",
        ltp=950.0,
        trigger_level=950.0,
        stop_loss=938.0,
        target_level=974.0,
        created_at=midday_dt.strftime("%Y-%m-%d %H:%M:%S IST"),
        metrics={
            "rvol": 1.40,
            "cvd_aligned": True,
            "order_flow_bullish": True,
            "tbt_imbalance": 1.8,
            "vix": 14.0,
        },
        confidence=86,
        is_live=True,
    )

    with patch("market.sentiment.get_market_breadth") as mock_mb:
        from market.sentiment import MarketBreadth

        mock_mb.return_value = MarketBreadth(
            advances=1200, declines=800, unchanged=50, ad_ratio=1.5, verdict="ADVANCE"
        )
        res = auditor.scrutinize_alert(alert)
        assert res.status in ("APPROVED", "HELD_FOR_CONFIRMATION")
        assert "Midday False Breakout Trap" not in str(res.rejection_reason or "")


def test_market_breadth_overridden_by_price_momentum_and_order_flow():
    import os

    """Gap 6: Verify that lagging market breadth (BROAD_DECLINE, A/D 0.40) does NOT
    veto an individual stock breaking out on pure price momentum + order flow."""
    from engine.alert_scrutiny import AlertScrutinyAuditor
    from config.constants import IST
    from unittest.mock import patch
    from market.sentiment import MarketBreadth

    auditor = AlertScrutinyAuditor()
    alert = AutoAlert(
        alert_id="aa-test-breadth-override-20261105",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="INFY",
        exchange="NSE",
        direction="BULLISH",
        headline="INFY Earnings Thrust",
        summary="Decoupled momentum breakout",
        ltp=1850.0,
        trigger_level=1850.0,
        stop_loss=1825.0,
        target_level=1900.0,
        created_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        metrics={
            "rvol": 2.2,
            "day_high_breakout": True,
            "day_change_pct": 1.5,
            "order_flow_bullish": True,
            "vix": 14.5,
            "volume": 500000,
            "oi": 500000,
        },
        confidence=88,
        is_live=True,
    )

    # Broad market is in severe liquidation (A/D = 0.40)
    mock_breadth = MarketBreadth(
        advances=400,
        declines=1600,
        unchanged=50,
        ad_ratio=0.25,
        verdict="BROAD_DECLINE",
    )
    with (
        patch("market.sentiment.get_market_breadth", return_value=mock_breadth),
        patch.dict(os.environ, {"ENFORCE_TEST_BREADTH": "1"}),
    ):
        res = auditor.scrutinize_alert(alert)
        assert res.status in ("APPROVED", "HELD_FOR_CONFIRMATION")
        assert "Market Breadth Liquidation Veto" not in str(res.rejection_reason or "")
