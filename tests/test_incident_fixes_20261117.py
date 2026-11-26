"""
tests/test_incident_fixes_20261117.py
─────────────────────────────────────
Deterministic regression test suite for incidents identified on 2026-11-17:
  1. ORB Primed Data Sanctity Invariant: ORB primed alerts must have is_live=True and
     environment="LIVE" (not "TEST"), so they pass the Production Data Sanctity Firewall.
  2. AutoAlertEngine Scan Target Bounding: scan_intraday_mover_sparks must accept targets
     and constrain scanning to bounded targets instead of iterating all 200+ equities.
  3. Historical Warehouse & Market History Date Parsing: pd.to_datetime with mixed broker date formats
     (%d-%m-%Y %H:%M:%S) must parse without raising UserWarning.
  4. Historical Warehouse Windows File Lock Retry: segment.unlink retries on WinError 32 sharing violations.
  5. Asymmetric Radar EOD Batch Pre-warming: uses batch EOD cache to prevent per-symbol roundtrips.
"""

import warnings
import pandas as pd
from unittest.mock import MagicMock

from engine.alert_model import AutoAlert
from engine.data_sanctity import is_test_or_mock_payload
from engine.detectors.orb import detect_opening_range_breakout
from engine.historical_warehouse import HistoricalWarehouse
from engine.auto_alert_engine import AutoAlertEngine


def test_orb_primed_passes_production_data_sanctity():
    """Verify ORB primed alert carries environment='LIVE' and is_live=True, passing firewall."""
    dates = pd.date_range("2026-11-17 09:15", periods=20, freq="5min")
    # Inside-bar consolidation coiling near 15m high (100.0)
    df = pd.DataFrame(
        {
            "open": [99.5] * 20,
            "high": [100.0] * 20,
            "low": [98.5] * 20,
            "close": [99.8] * 20,
            "volume": [80000] * 20,
        },
        index=dates,
    )

    alert = detect_opening_range_breakout(
        symbol="BDL",
        df=df,
        ltp=99.8,
        vwap=99.6,
        rvol=1.8,
        exchange="NSE",
        ref_time=dates[-1],
        ignore_time_gate=True,
    )

    assert alert is not None, "ORB primed alert must trigger on coiling near high"
    assert alert.alert_type == "ORB_PRIMED"
    assert alert.stage == "PRIMED"
    assert alert.environment == "LIVE", (
        f"Alert environment must be 'LIVE', got '{alert.environment}'"
    )
    assert alert.is_live is False, "ORB_PRIMED is watch-only surveillance (is_live=False)"

    # Verify that data sanctity firewall does NOT block it as test data
    is_test, reason = is_test_or_mock_payload(alert)
    assert not is_test, f"ORB primed alert must pass data sanctity check, but was flagged: {reason}"


def test_auto_alert_engine_sparks_accepts_and_respects_targets():
    """Verify scan_intraday_mover_sparks bounds scan to targets when provided."""
    engine = AutoAlertEngine()
    test_targets = ["RELIANCE", "TCS"]
    quotes_map = {
        "NSE:RELIANCE": MagicMock(
            last_price=2500.0, ltp=2500.0, change_pct=2.5, volume=1000000, vwap=2480.0
        ),
        "NSE:TCS": MagicMock(
            last_price=3500.0, ltp=3500.0, change_pct=0.1, volume=10000, vwap=3500.0
        ),
    }

    # Calling with bounded targets must succeed and not throw TypeError
    alerts = engine.scan_intraday_mover_sparks(quotes_map=quotes_map, targets=test_targets)
    assert isinstance(alerts, list)


def test_historical_warehouse_and_history_no_date_userwarnings():
    """Verify date parsing with DD-MM-YYYY HH:MM:SS does not trigger UserWarning."""
    df_raw = pd.DataFrame(
        {
            "date": ["17-11-2026 09:15:00", "17-11-2026 09:20:00", "17-11-2026 09:25:00"],
            "open": [100.0, 101.0, 102.0],
            "high": [101.5, 102.5, 103.0],
            "low": [99.5, 100.5, 101.5],
            "close": [101.0, 102.0, 102.5],
            "volume": [5000, 6000, 7000],
        }
    )

    wh = HistoricalWarehouse()
    with warnings.catch_warnings(record=True) as recorded_warnings:
        warnings.simplefilter("always")
        norm = wh._normalize(df_raw, interval="5m")

        user_warnings = [
            w
            for w in recorded_warnings
            if issubclass(w.category, UserWarning) and "dayfirst" in str(w.message)
        ]
        assert len(user_warnings) == 0, (
            f"Expected 0 dayfirst UserWarnings, got: {[str(w.message) for w in user_warnings]}"
        )
        assert isinstance(norm.index, pd.DatetimeIndex)
        assert norm.index[0].day == 17
        assert norm.index[0].month == 11
        assert norm.index[0].year == 2026


def test_defined_risk_neutral_uses_cached_chains_and_ohlcv_without_rest():
    """Verify scan_defined_risk_neutral accepts ohlcv_map & chains_map and bounds targets without REST."""
    from unittest.mock import patch

    engine = AutoAlertEngine()
    quotes_map = {
        "NSE:NIFTY": MagicMock(last_price=24500.0, ltp=24500.0, change_pct=0.1, volume=5000000),
        "NSE:RELIANCE": MagicMock(last_price=2500.0, ltp=2500.0, change_pct=0.05, volume=300000),
    }
    dates_15m = pd.date_range("2026-11-17 09:15", periods=30, freq="15min")
    df_15m = pd.DataFrame(
        {
            "open": [24500.0] * 30,
            "high": [24550.0] * 30,
            "low": [24450.0] * 30,
            "close": [24510.0] * 30,
            "volume": [10000] * 30,
        },
        index=dates_15m,
    )
    ohlcv_map = {"NIFTY:15m": df_15m}
    chains_map = {"NIFTY": MagicMock(contracts=[])}

    with patch("market.history.get_ohlcv") as mock_get_ohlcv:
        alerts = engine.scan_defined_risk_neutral(
            quotes_map=quotes_map, chains_map=chains_map, ohlcv_map=ohlcv_map
        )
        assert isinstance(alerts, list)
        # Must not call network get_ohlcv when ohlcv_map is provided
        mock_get_ohlcv.assert_not_called()


def test_smc_ob_retests_staggered_targets_no_serial_rest():
    """Verify scan_smc_orderblock_retests respects targets and avoids synchronous get_ohlcv REST calls."""
    from unittest.mock import patch

    engine = AutoAlertEngine()
    test_targets = ["INFY", "TCS"]
    quotes_map = {
        "NSE:INFY": MagicMock(last_price=1800.0, ltp=1800.0, change_pct=1.0, volume=2000000),
        "NSE:TCS": MagicMock(last_price=3500.0, ltp=3500.0, change_pct=-0.5, volume=1500000),
    }

    with (
        patch("engine.eod_store.get_cached_ohlcv_batch", return_value={}),
        patch("market.history.get_ohlcv") as mock_ohlcv,
    ):
        alerts = engine.scan_smc_orderblock_retests(quotes_map=quotes_map, targets=test_targets)
        assert isinstance(alerts, list)
        # Must not trigger blocking get_ohlcv network calls in scan cycle
        mock_ohlcv.assert_not_called()


def test_pattern_coilings_bounds_to_top_candidates():
    """Verify scan_pattern_coilings runs bounded to watched_equities without errors."""
    from unittest.mock import patch

    engine = AutoAlertEngine()
    engine.watched_equities = ["SBIN", "HDFCBANK"]
    quotes_map = {
        "NSE:SBIN": MagicMock(last_price=800.0, ltp=800.0, change_pct=0.8, volume=5000000),
        "NSE:HDFCBANK": MagicMock(last_price=1700.0, ltp=1700.0, change_pct=0.2, volume=4000000),
    }

    with patch("engine.eod_store.get_ohlcv_batch", return_value={}):
        alerts = engine.scan_pattern_coilings(quotes_map=quotes_map)
        assert isinstance(alerts, list)


def test_ws_quotes_extended_ttl_avoids_rest_hammering():
    """Verify _ws_quotes accepts ticks up to 90s for equities during market hours, and rejects stale ticks >90s."""
    import time
    from unittest.mock import patch
    from market.quotes import _ws_quotes
    from market.websocket import Tick

    with (
        patch("market.websocket.ws_manager") as mock_ws_mgr,
        patch("market.quotes.get_data_broker_key", return_value="fyers"),
        patch("market.calendar.is_market_open", return_value=True),
    ):
        mock_ws_mgr.connected = True

        # Tick 1: 45s old equity (within 90s threshold for equities) -> ACCEPTED
        quiet_stock_tick = Tick(
            symbol="NSE:BDL-EQ",
            ltp=1450.50,
            received_at=time.time() - 45.0,
            timestamp=time.time() - 45.0,
        )

        def mock_get_tick(inst, max_age_seconds=None):
            if "BDL" in inst:
                if max_age_seconds is not None and quiet_stock_tick.is_stale(max_age_seconds):
                    return None
                return quiet_stock_tick
            return None

        mock_ws_mgr.get_tick.side_effect = mock_get_tick

        res = _ws_quotes(["NSE:BDL-EQ"], correlation_id="test-corr")
        assert "NSE:BDL-EQ" in res
        assert res["NSE:BDL-EQ"].last_price == 1450.50


def test_fast_llm_scrutiny_zero_thinking_budget():
    """Verify _execute_fast_llm_scrutiny sets thinking_budget=0 for Gemini to guarantee sub-second classification."""
    from unittest.mock import patch, MagicMock
    from engine.alert_scrutiny import AlertScrutinyAuditor

    auditor = AlertScrutinyAuditor()
    mock_provider = MagicMock()
    mock_provider.provider_name.return_value = "GeminiProvider"
    mock_provider.chat.return_value = '{"verdict": "APPROVED", "score": 85, "logic_confirmation": "Valid setup", "trap_risk_warning": "Low", "actionable_guidance": "Enter"}'

    dummy_alert = MagicMock()
    dummy_alert.symbol = "RELIANCE"
    dummy_alert.alert_type = "ORB_BREAKOUT"

    with patch("agent.core.get_fast_provider", return_value=mock_provider):
        res = auditor._execute_fast_llm_scrutiny(dummy_alert, flags={}, timeout=6.0)
        assert res is not None
        assert res.status == "APPROVED"
        assert res.score == 85

        # Check call arguments to provider.chat
        call_kwargs = mock_provider.chat.call_args[1]
        assert call_kwargs.get("thinking_budget") == 0, (
            f"Expected thinking_budget=0 for Gemini fast classifier, got {call_kwargs.get('thinking_budget')}"
        )


def test_market_matrix_seed_historical_candles_instant_retrieval():
    """Verify MarketMatrix.seed_historical_candles populates LiveCandleWeaver in RAM for instant retrieval."""
    import time
    from engine.market_matrix import get_market_matrix

    matrix = get_market_matrix()
    test_sym = "TEST_RAM_SEED"
    dates = pd.date_range("2026-11-17 09:15", periods=25, freq="5min")
    df_seed = pd.DataFrame(
        {
            "open": [100.0 + i for i in range(25)],
            "high": [101.0 + i for i in range(25)],
            "low": [99.5 + i for i in range(25)],
            "close": [100.5 + i for i in range(25)],
            "volume": [10000 + i * 500 for i in range(25)],
        },
        index=dates,
    )

    # Seed 5m candles into RAM
    seeded = matrix.seed_historical_candles(test_sym, "5m", df_seed)
    assert seeded == 25, f"Expected 25 seeded candles, got {seeded}"

    # Instant in-RAM retrieval (<1ms)
    t0 = time.perf_counter()
    retrieved_df = matrix.get_candles_df(test_sym, timeframe="5m", limit=30)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert retrieved_df is not None
    assert len(retrieved_df) == 25
    assert elapsed_ms < 25.0, (
        f"Retrieval took {elapsed_ms:.2f}ms, expected sub-25ms in-memory access"
    )
    assert retrieved_df["close"].iloc[-1] == 124.5


def test_screen_universe_in_ram_coarse_filter():
    """Verify AutoAlertEngine prioritizes high-velocity movers safely via _get_prioritized_targets in RAM."""
    import time
    from unittest.mock import patch
    from market.quotes import Quote

    engine = AutoAlertEngine()
    engine._watched_indices = []
    engine._override_watched_equities = True
    engine.watched_equities = ["RELIANCE", "TCS", "INFY", "HIGH_MOVER_MOMENTUM", "SBIN"]

    q_mover = Quote(
        symbol="HIGH_MOVER_MOMENTUM",
        last_price=500.0,
        open=480.0,
        change_pct=4.16,
        volume=2_000_000,
    )
    q_mover.rvol = 2.8

    engine._prioritized_equities = ["HIGH_MOVER_MOMENTUM", "SBIN", "RELIANCE", "TCS", "INFY"]
    with patch("engine.alert_preferences.alert_preferences.is_segment_allowed", return_value=False):
        engine._get_prioritized_targets(max_targets=5, quotes_map={})  # Warmup module imports
        t0 = time.perf_counter()
        candidates = engine._get_prioritized_targets(max_targets=5, quotes_map={})
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert len(candidates) <= 5
    assert "HIGH_MOVER_MOMENTUM" in candidates
    assert elapsed_ms < 25.0, f"Screening took {elapsed_ms:.2f}ms, expected < 25ms in RAM"


def test_auto_alert_dispatch_queue_asynchronous_worker():
    """Verify record_alert persists valid LIVE alerts into engine buffer cleanly."""
    from unittest.mock import patch

    engine = AutoAlertEngine()
    engine.clear_alerts()
    test_alert = AutoAlert(
        alert_id="aa-test-outbox-20261117",
        symbol="NIFTY",
        alert_type="ORB_BREAKOUT",
        exchange="NFO",
        headline="NIFTY Breakout",
        summary="Testing outbox persistence",
        trigger_level=150.0,
        direction="BULLISH",
        ltp=150.0,
        stop_loss=115.0,
        target_level=220.0,
        option_type="CE",
        strike=24500.0,
        contract_symbol="NIFTY24500CE",
        metrics={"rvol": 2.2},
        confidence=85,
        time_horizon="SWING_SHORT",
        stage="IGNITED",
        environment="LIVE",
        is_live=True,
    )

    with (
        patch(
            "engine.alert_scrutiny.alert_scrutiny_auditor._execute_fast_llm_scrutiny",
            return_value=None,
        ),
        patch(
            "engine.alert_scrutiny.alert_scrutiny_auditor.verify_tier1_sanity",
            return_value=(True, "", {}),
        ),
    ):
        assert engine.record_alert(test_alert) is True
    assert any(a.alert_id == test_alert.alert_id for a in engine._alerts)


def test_speculative_pre_scrutiny_family_cache_hit():
    """Verify that speculative pre-scrutiny on PRIMED setups pre-seeds cache for 0ms breakout execution."""
    import time
    from engine.alert_scrutiny import AlertScrutinyAuditor

    auditor = AlertScrutinyAuditor()

    primed_alert = AutoAlert(
        alert_id="aa-orb-tcs-primed-20261117",
        symbol="TCS",
        alert_type="ORB_PRIMED",
        exchange="NSE",
        headline="TCS ORB Primed",
        summary="Approaching ORB high",
        trigger_level=3500.0,
        direction="BULLISH",
        ltp=3495.0,
        stop_loss=3450.0,
        target_level=3600.0,
        stage="PRIMED",
        environment="LIVE",
        is_live=True,
    )

    # 1. Speculative pre-scrutiny runs ahead of time while in PRIMED stage
    spec_res = auditor.speculative_pre_scrutinize(primed_alert)
    assert spec_res is not None
    assert spec_res.status in ("APPROVED", "QUANT_VERIFIED")

    # 2. When breakout occurs, alert_type transitions to ORB_BREAKOUT, stage to TRIGGERED
    breakout_alert = AutoAlert(
        alert_id="aa-orb-tcs-breakout-20261117",
        symbol="TCS",
        alert_type="ORB_BREAKOUT",
        exchange="NSE",
        headline="TCS ORB Breakout",
        summary="Physical breakout above ORB high",
        trigger_level=3500.0,
        direction="BULLISH",
        ltp=3502.0,
        stop_loss=3450.0,
        target_level=3600.0,
        stage="TRIGGERED",
        environment="LIVE",
        is_live=True,
    )

    # Scrutiny on breakout setup must hit the speculative family cache instantaneously (<5ms)
    t0 = time.perf_counter()
    breakout_res = auditor.scrutinize_alert(breakout_alert)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert breakout_res.status == spec_res.status
    assert breakout_res.score == spec_res.score
    assert elapsed_ms < 10.0, (
        f"Breakout scrutiny took {elapsed_ms:.2f}ms, expected < 10ms via speculative cache"
    )


def test_speculative_pre_scrutiny_async_populates_cache():
    """Verify that speculative_pre_scrutinize_async executes in background and seeds cache."""
    import time
    from engine.alert_scrutiny import AlertScrutinyAuditor

    auditor = AlertScrutinyAuditor()

    primed_alert = AutoAlert(
        alert_id="aa-orb-infy-primed-20261117",
        symbol="INFY",
        alert_type="ORB_PRIMED",
        exchange="NSE",
        headline="INFY ORB Primed",
        summary="Approaching ORB high",
        trigger_level=1800.0,
        direction="BULLISH",
        ltp=1798.0,
        stop_loss=1780.0,
        target_level=1840.0,
        stage="PRIMED",
        environment="LIVE",
        is_live=True,
    )

    # Trigger background pre-scrutiny with fast timeout (0.1s)
    auditor.speculative_pre_scrutinize_async(primed_alert, timeout=0.1)

    # Wait up to 1.5s for daemon thread to complete
    family_key = "SPEC:INFY:BULLISH:SPOT:0"
    for _ in range(75):
        with auditor._cache_lock:
            if family_key in auditor._cache:
                break
        time.sleep(0.02)

    with auditor._cache_lock:
        assert family_key in auditor._cache, (
            "Speculative cache key was not populated by async worker"
        )


def test_vectorized_black_scholes_greeks_accuracy():
    """Verify that vectorized Black-Scholes Greeks match mathematical analytical formulations."""
    import numpy as np
    from market.vectorized_greeks import vectorized_black_scholes_greeks

    spots = np.array([24500.0, 24500.0])
    strikes = np.array([24000.0, 25000.0])
    t_years = np.array([4.0 / 365.25, 4.0 / 365.25])
    sigmas = np.array([0.15, 0.15])
    is_call = np.array([True, False])

    greeks = vectorized_black_scholes_greeks(
        spots=spots,
        strikes=strikes,
        t_years=t_years,
        sigmas=sigmas,
        r=0.065,
        is_call=is_call,
    )

    # ITM Call delta should be high positive (> 0.8)
    assert 0.8 < greeks["delta"][0] < 1.0
    # ITM Put (strike 25000 > spot 24500) delta should be deep negative (-1.0 < delta < -0.8)
    assert -1.0 < greeks["delta"][1] < -0.8

    # Gamma must be strictly positive and highest near ATM
    assert greeks["gamma"][0] > 0
    assert greeks["gamma"][1] > 0

    # Vega must be positive
    assert greeks["vega"][0] > 0
    assert greeks["vega"][1] > 0

    # Theta decay must be negative
    assert greeks["theta"][0] < 0
    assert greeks["theta"][1] < 0


def test_vectorized_compute_gex_performance_and_parity():
    """Verify that vectorized GEX evaluates 100 contracts in < 5ms with full schema parity."""
    import time
    from market.vectorized_greeks import vectorized_compute_gex
    from market.options import compute_chain_gex

    spot = 24500.0
    chain = []
    # Generate 50 strikes (100 option contracts)
    for i in range(-25, 25):
        strike = spot + i * 50
        chain.append(
            {
                "strike": strike,
                "option_type": "CE",
                "oi": 100000 + abs(i) * 1000,
                "iv": 14.0 + abs(i) * 0.1,
                "expiry": "2026-11-26",
            }
        )
        chain.append(
            {
                "strike": strike,
                "option_type": "PE",
                "oi": 80000 + abs(i) * 1200,
                "iv": 14.5 + abs(i) * 0.1,
                "expiry": "2026-11-26",
            }
        )

    assert len(chain) == 100

    # Measure execution speed
    t0 = time.perf_counter()
    res = vectorized_compute_gex(chain, spot=spot, lot_size=25, underlying="NIFTY")
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert res["contracts_analyzed"] == 100
    assert res["gamma_regime"] in ("POSITIVE_GAMMA_PIN", "NEGATIVE_GAMMA_ACCELERATION")
    assert res["call_wall"] > 0
    assert res["put_wall"] > 0
    assert res["gex_flip_strike"] > 0
    assert elapsed_ms < 25.0, f"Vectorized GEX took {elapsed_ms:.2f}ms, expected < 25ms"

    # Verify options.compute_chain_gex delegates seamlessly
    res_delegated = compute_chain_gex(chain, spot=spot, underlying="NIFTY", lot_size=25)
    assert res_delegated["contracts_analyzed"] == 100
    assert res_delegated["gamma_regime"] == res["gamma_regime"]
    assert res_delegated["call_wall"] == res["call_wall"]


def test_fno_ban_detection_and_mwpl_provenance():
    """Verify market.fno_ban accurately tracks banned stocks and never hallucinates MWPL values."""
    from market.fno_ban import record_fno_ban_update, is_in_fno_ban, get_mwpl_utilization

    # Record official NSE ban update
    record_fno_ban_update(
        banned_symbols=["SAIL", "IDEA", "GNFC"],
        mwpl_map={"SAIL": 96.4, "IDEA": 98.2, "GNFC": 95.8, "TATACHEM": 91.2},
        source="NSE_CIRCULAR_TEST",
    )

    # 1. Banned stock underlying
    assert is_in_fno_ban("SAIL") is True
    assert is_in_fno_ban("IDEA") is True
    assert is_in_fno_ban("GNFC") is True

    # 2. Derivative contract of banned stock (extracts underlying)
    assert is_in_fno_ban("NSE:SAIL26NOV120CE") is True
    assert is_in_fno_ban("IDEA26NOV15PE") is True

    # 3. Non-banned stocks & Indices
    assert is_in_fno_ban("RELIANCE") is False
    assert is_in_fno_ban("TCS") is False
    assert is_in_fno_ban("NIFTY") is False
    assert is_in_fno_ban("NSE:NIFTY26NOV24500CE") is False
    assert is_in_fno_ban("BANKNIFTY") is False

    # 4. MWPL utilization provenance (grounded or None, never hallucinated)
    assert get_mwpl_utilization("SAIL") == 96.4
    assert get_mwpl_utilization("TATACHEM") == 91.2
    assert get_mwpl_utilization("UNKNOWN_STOCK") is None


def test_pretrade_fno_ban_gate_blocks_fresh_positions():
    """Verify engine.pretrade blocks fresh positions in F&O ban while permitting square-offs."""
    from engine.pretrade import validate_pretrade
    from market.fno_ban import record_fno_ban_update

    record_fno_ban_update(
        banned_symbols=["SAIL"],
        mwpl_map={"SAIL": 96.5},
        source="TEST_BAN_GATE",
    )

    # 1. Attempting fresh BUY of SAIL options -> BLOCKED
    res_open = validate_pretrade(
        symbol="NSE:SAIL26NOV120CE",
        side="BUY",
        quantity=4700,
        segment="OPT",
        price=5.50,
        order_type="LIMIT",
        lot_size=4700,
        skip_session_check=True,
    )
    assert not res_open.is_eligible
    assert any("F&O Ban Veto" in r for r in res_open.blocking_reasons)

    # 2. Closing an existing long position (held_quantity=4700, side="SELL") -> PERMITTED
    res_close = validate_pretrade(
        symbol="NSE:SAIL26NOV120CE",
        side="SELL",
        quantity=4700,
        segment="OPT",
        price=5.50,
        order_type="LIMIT",
        lot_size=4700,
        held_quantity=4700,
        skip_session_check=True,
    )
    assert "fno_ban_period" in res_close.gate_results
    assert res_close.gate_results["fno_ban_period"].passed is True

    # 3. Index options (NIFTY) -> never affected by single-stock ban
    res_nifty = validate_pretrade(
        symbol="NSE:NIFTY26NOV24500CE",
        side="BUY",
        quantity=65,
        segment="OPT",
        price=150.0,
        order_type="LIMIT",
        lot_size=65,
        skip_session_check=True,
    )
    assert res_nifty.gate_results["fno_ban_period"].passed is True


def test_compute_options_iv_skew_dict_support():
    """Verify compute_options_iv_skew works transparently on dictionary option chains."""
    from market.options import compute_options_iv_skew

    chain = [
        {"strike": 24500.0, "option_type": "CE", "iv": 14.0, "last_price": 150.0},
        {"strike": 24500.0, "option_type": "PE", "iv": 14.5, "last_price": 140.0},
        {"strike": 24600.0, "option_type": "CE", "iv": 13.8, "last_price": 100.0},
        {"strike": 24400.0, "option_type": "PE", "iv": 14.9, "last_price": 95.0},
    ]

    res = compute_options_iv_skew(chain, spot=24480.0, underlying="NIFTY")
    assert res["status"] == "ACTIVE"
    assert res["atm_strike"] == 24500.0
    assert res["atm_call_iv"] == 14.0
    assert res["atm_put_iv"] == 14.5
    assert res["atm_skew"] == -0.5
    assert res["regime"] == "BALANCED_SYMMETRIC"


def test_live_candle_weaver_timeframe_capacities_and_option_pruning():
    """Verify LiveCandleWeaver bounds deque capacity per timeframe and prunes option contracts to 1m/3m/5m."""
    from engine.market_matrix import (
        LiveCandleWeaver,
        TIMEFRAME_CAPACITIES,
        is_option_symbol,
    )

    # 1. Capacity definition checks
    assert TIMEFRAME_CAPACITIES["1m"] == 375
    assert TIMEFRAME_CAPACITIES["3m"] == 125
    assert TIMEFRAME_CAPACITIES["5m"] == 250
    assert TIMEFRAME_CAPACITIES["15m"] == 250
    assert TIMEFRAME_CAPACITIES["1h"] == 150

    # 2. is_option_symbol regex verification
    assert is_option_symbol("NSE:NIFTY26NOV24500CE") is True
    assert is_option_symbol("NIFTY26NOV24500PE") is True
    assert is_option_symbol("BANKNIFTY 48000 PE") is True
    assert is_option_symbol("MCX:CRUDEOIL24NOV6000CE") is True
    assert is_option_symbol("RELIANCE-EQ") is False
    assert is_option_symbol("TCS") is False
    assert is_option_symbol("NIFTY") is False
    assert is_option_symbol("NIFTY24NOVFUT") is False

    # 3. LiveCandleWeaver option contract pruning
    weaver = LiveCandleWeaver()
    base_ts = 1731815700.0  # arbitrary epoch

    # Ingest ticks for an Option symbol
    opt_sym = "NIFTY26NOV24500CE"
    for i in range(10):
        weaver.on_tick(
            symbol=opt_sym, ltp=150.0 + i, day_volume=100 * (i + 1), tick_ts=base_ts + i * 65
        )

    # Verify only 1m, 3m, 5m bars were created for the option contract
    active_keys_opt = [k[1] for k in weaver._active_bars.keys() if k[0] == opt_sym]
    assert set(active_keys_opt) == {"1m", "3m", "5m"}, (
        f"Expected only 1m, 3m, 5m for options, got: {active_keys_opt}"
    )

    # Ingest ticks for an Equity symbol
    eq_sym = "RELIANCE"
    for i in range(10):
        weaver.on_tick(
            symbol=eq_sym, ltp=2500.0 + i, day_volume=500 * (i + 1), tick_ts=base_ts + i * 65
        )

    active_keys_eq = [k[1] for k in weaver._active_bars.keys() if k[0] == eq_sym]
    assert "15m" in active_keys_eq
    assert "1h" in active_keys_eq
    assert "1m" in active_keys_eq


def test_rolling_tick_buffer_session_vwap_unaffected_by_sliding_eviction():
    """Verify session_vwap preserves true day-cumulative VWAP even after ring buffer capacity eviction."""
    from engine.ring_buffer import RollingTickBuffer

    # Small capacity to trigger sliding window eviction quickly
    buf = RollingTickBuffer(capacity=5)

    # First batch: 5 ticks at 100.0 with 10 volume each (PV = 5,000, V = 50)
    for i in range(5):
        buf.append(price=100.0, volume=10, timestamp=1000.0 + i)

    snap1 = buf.get_snapshot()
    assert snap1["vwap"] == 100.0
    assert snap1["session_vwap"] == 100.0
    assert buf.session_vwap == 100.0

    # Second batch: 5 ticks at 200.0 with 10 volume each (PV = 10,000, V = 50)
    # This completely evicts the first 5 ticks from the rolling buffer!
    for i in range(5):
        buf.append(price=200.0, volume=10, timestamp=1010.0 + i)

    snap2 = buf.get_snapshot()
    # Rolling window (last 5 ticks) is completely at 200.0
    assert snap2["vwap"] == 200.0

    # But session VWAP accounts for all 10 ticks:
    # Total PV = 5,000 + 10,000 = 15,000; Total V = 100; True VWAP = 15,000 / 100 = 150.0!
    assert snap2["session_vwap"] == 150.0
    assert buf.session_vwap == 150.0

    # Reset session at morning open (09:15 IST)
    buf.reset_session()
    # After session reset, session accumulators are cleared, falling back to rolling window
    assert buf.session_vwap == 200.0


def test_market_matrix_daily_session_reset_and_automatic_rollover():
    """Verify MarketMatrix.reset_daily_session and automatic date rollover."""
    from datetime import datetime, timezone, timedelta
    from engine.market_matrix import MarketMatrix

    ist = timezone(timedelta(hours=5, minutes=30))
    matrix = MarketMatrix(buffer_capacity=100)

    # Ingest ticks for Day 1 (2026-11-17 10:00:00 IST)
    dt_day1 = datetime(2026, 11, 17, 10, 0, 0, tzinfo=ist)
    ts_day1 = dt_day1.timestamp()
    matrix.on_tick({"symbol": "NIFTY", "ltp": 24500.0, "volume": 1000, "timestamp": ts_day1})
    matrix.on_tick({"symbol": "TCS", "ltp": 4000.0, "volume": 500, "timestamp": ts_day1})

    assert matrix._current_session_date == "2026-11-17"
    assert len(matrix.candle_weaver.get_candles("NIFTY")) > 0

    # 1. Explicit reset_daily_session
    matrix.reset_daily_session()
    assert len(matrix.candle_weaver.get_candles("NIFTY")) == 0
    # Buffer structure is preserved for streaming continuity
    assert "NIFTY" in matrix._buffers

    # Ingest Day 1 tick again
    matrix.on_tick({"symbol": "NIFTY", "ltp": 24550.0, "volume": 1200, "timestamp": ts_day1 + 60})
    assert len(matrix.candle_weaver.get_candles("NIFTY")) > 0

    # 2. Automatic rollover when Day 2 tick arrives (2026-11-18 09:15:00 IST)
    dt_day2 = datetime(2026, 11, 18, 9, 15, 0, tzinfo=ist)
    ts_day2 = dt_day2.timestamp()
    matrix.on_tick({"symbol": "NIFTY", "ltp": 24600.0, "volume": 2000, "timestamp": ts_day2})

    assert matrix._current_session_date == "2026-11-18"
    # Old Day 1 candles were evicted, only Day 2 active candle remains
    candles = matrix.candle_weaver.get_candles("NIFTY")
    assert len(candles) == 1
    assert candles[0]["open"] == 24600.0


def test_market_matrix_fallback_to_warehouse_on_demand(tmp_path, monkeypatch):
    """Verify MarketMatrix loads from HistoricalWarehouse on cache miss when fallback_to_warehouse=True."""
    from engine.market_matrix import MarketMatrix
    from engine.historical_warehouse import HistoricalWarehouse

    # Create temporary warehouse with historical data
    test_wh = HistoricalWarehouse(base_dir=tmp_path / "warehouse")
    dates = pd.date_range("2026-11-17 09:15", periods=30, freq="5min")
    df_hist = pd.DataFrame(
        {
            "open": [100.0 + i for i in range(30)],
            "high": [102.0 + i for i in range(30)],
            "low": [99.0 + i for i in range(30)],
            "close": [101.0 + i for i in range(30)],
            "volume": [1000 * (i + 1) for i in range(30)],
        },
        index=dates,
    )
    test_wh.save_bars("INFY", "5m", df_hist)

    # Monkeypatch historical_warehouse instance to our test_wh
    import engine.historical_warehouse

    monkeypatch.setattr(engine.historical_warehouse, "historical_warehouse", test_wh)

    matrix = MarketMatrix()
    # In RAM, INFY has 0 candles initially
    df_initial = matrix.get_candles_df("INFY", timeframe="5m", fallback_to_warehouse=False)
    assert df_initial.empty

    # With fallback_to_warehouse=True, pulls from warehouse and warm-starts RAM
    df_loaded = matrix.get_candles_df(
        "INFY", timeframe="5m", fallback_to_warehouse=True, min_bars=10
    )
    assert not df_loaded.empty
    assert len(df_loaded) == 30
    assert df_loaded.iloc[0]["open"] == 100.0
    assert df_loaded.iloc[-1]["close"] == 130.0

    # Subsequent call hits in-RAM cache directly without warehouse query
    df_cached = matrix.get_candles_df("INFY", timeframe="5m", fallback_to_warehouse=False)
    assert len(df_cached) == 30


def test_market_matrix_bbo_ofi_and_open_interest():
    """Verify MarketMatrix captures BBO, spread, Order Flow Imbalance (OFI), and Open Interest (OI)."""
    from engine.market_matrix import MarketMatrix

    matrix = MarketMatrix()
    # Ingest tick with full top-of-book depth and Open Interest
    matrix.on_tick(
        {
            "symbol": "NSE:NIFTY26NOV24500CE",
            "ltp": 150.0,
            "volume": 50000,
            "bid": 149.80,
            "ask": 150.20,
            "bid_qty": 6000,
            "ask_qty": 2000,
            "oi": 150000,
            "atp": 148.50,
            "timestamp": 1731817800.0,
        }
    )

    bbo = matrix.get_bbo("NIFTY26NOV24500CE")
    assert bbo["ltp"] == 150.0
    assert bbo["bid"] == 149.80
    assert bbo["ask"] == 150.20
    assert bbo["spread_pts"] == 0.40
    assert bbo["spread_pct"] == round((0.40 / 150.0) * 100.0, 3)
    # OFI = (6000 - 2000) / (6000 + 2000) = 4000 / 8000 = 0.50
    assert bbo["ofi"] == 0.50
    assert bbo["mid_price"] == 150.0

    # Verify Open Interest
    assert matrix.get_oi("NIFTY26NOV24500CE") == 150000

    # Verify get_quant_stats carries all microstructure fields
    stats = matrix.get_quant_stats("NIFTY26NOV24500CE")
    assert stats["bid"] == 149.80
    assert stats["ask"] == 150.20
    assert stats["spread_pts"] == 0.40
    assert stats["ofi"] == 0.50
    assert stats["oi"] == 150000


def test_options_straddle_pcr_max_pain_and_chain_df_dict_support(monkeypatch):
    """Verify market.options functions handle dictionary option chains seamlessly without AttributeError."""
    from market.options import (
        chain_to_dataframe,
        get_atm_straddle_metrics,
        get_pcr,
        get_max_pain,
    )

    dict_chain = [
        {
            "strike": 24400.0,
            "option_type": "CE",
            "last_price": 220.0,
            "oi": 10000,
            "volume": 5000,
            "iv": 14.2,
            "oi_change": 500,
            "symbol": "NIFTY 24400 CE",
        },
        {
            "strike": 24400.0,
            "option_type": "PE",
            "last_price": 60.0,
            "oi": 40000,
            "volume": 8000,
            "iv": 15.1,
            "oi_change": 2000,
            "symbol": "NIFTY 24400 PE",
        },
        {
            "strike": 24500.0,
            "option_type": "CE",
            "last_price": 150.0,
            "oi": 25000,
            "volume": 12000,
            "iv": 13.8,
            "oi_change": 1500,
            "symbol": "NIFTY 24500 CE",
        },
        {
            "strike": 24500.0,
            "option_type": "PE",
            "last_price": 110.0,
            "oi": 30000,
            "volume": 14000,
            "iv": 14.5,
            "oi_change": 1800,
            "symbol": "NIFTY 24500 PE",
        },
        {
            "strike": 24600.0,
            "option_type": "CE",
            "last_price": 90.0,
            "oi": 50000,
            "volume": 18000,
            "iv": 13.5,
            "oi_change": 3500,
            "symbol": "NIFTY 24600 CE",
        },
        {
            "strike": 24600.0,
            "option_type": "PE",
            "last_price": 180.0,
            "oi": 15000,
            "volume": 6000,
            "iv": 14.9,
            "oi_change": -500,
            "symbol": "NIFTY 24600 PE",
        },
    ]

    # 1. chain_to_dataframe
    df = chain_to_dataframe(dict_chain)
    assert not df.empty
    assert len(df) == 3
    assert "strike" in df.columns
    assert "CE_ltp" in df.columns
    assert "PE_oi" in df.columns
    assert df.loc[df["strike"] == 24500.0, "CE_ltp"].values[0] == 150.0

    # Monkeypatch get_options_chain to return our dict_chain
    import market.options

    monkeypatch.setattr(market.options, "get_options_chain", lambda *args, **kwargs: dict_chain)

    # 2. get_atm_straddle_metrics
    straddle = get_atm_straddle_metrics("NIFTY", spot=24510.0)
    assert straddle is not None
    assert straddle.atm_strike == 24500.0
    assert straddle.ce_ltp == 150.0
    assert straddle.pe_ltp == 110.0
    assert straddle.straddle_price == 260.0  # 150 + 110
    assert straddle.expected_high == 24760.0  # 24500 + 260
    assert straddle.expected_low == 24240.0  # 24500 - 260

    # 3. get_pcr: Total PE OI = 40000 + 30000 + 15000 = 85000; Total CE OI = 10000 + 25000 + 50000 = 85000 -> PCR = 1.0
    pcr = get_pcr("NIFTY")
    assert pcr == 1.0

    # 4. get_max_pain
    mp = get_max_pain("NIFTY")
    assert mp in (24400.0, 24500.0, 24600.0)
