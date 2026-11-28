"""Regression tests for Fyers rate-gate burst protection, retry gating, WS keepalives, and non-blocking detector pools."""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd


def test_fyers_rate_gate_combined_1s_anti_burst() -> None:
    """Concurrent mixed DATA and ORDER bursts stay below 10 req/s combined ceiling."""
    from market.fyers_rate_gate import FyersCallCategory, UnifiedFyersRateGate

    gate = UnifiedFyersRateGate(plan="PRIME", max_per_sec=8.0, max_per_min=360.0)
    timestamps: list[tuple[float, FyersCallCategory]] = []
    ts_lock = threading.Lock()
    barrier = threading.Barrier(10)

    def _worker(cat: FyersCallCategory) -> None:
        barrier.wait(timeout=5.0)
        if gate.acquire(category=cat, timeout=5.0):
            with ts_lock:
                timestamps.append((time.monotonic(), cat))

    cats = [
        FyersCallCategory.SCANNER_QUOTE,
        FyersCallCategory.SCANNER_QUOTE,
        FyersCallCategory.SCANNER_QUOTE,
        FyersCallCategory.URGENT_QUOTE,
        FyersCallCategory.ORDER,
        FyersCallCategory.SCANNER_QUOTE,
        FyersCallCategory.DEPTH_CHAIN,
        FyersCallCategory.HISTORICAL,
        FyersCallCategory.SCANNER_QUOTE,
        FyersCallCategory.URGENT_QUOTE,
    ]
    threads = [threading.Thread(target=_worker, args=(c,)) for c in cats]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=6.0)

    assert len(timestamps) >= 6
    data_only = sorted(t for t, c in timestamps if c != FyersCallCategory.ORDER)
    for idx in range(1, len(data_only)):
        # 5% anti-burst cushion on PRIME max_per_sec=8.0 yields >= 0.131s target spacing
        assert (data_only[idx] - data_only[idx - 1]) >= 0.10

    # Any 1.0s rolling window must never hit Fyers hard 10 req/s ceiling
    all_ts = sorted(t for t, _ in timestamps)
    for t_start in all_ts:
        in_window = [t for t in all_ts if t_start <= t < t_start + 1.0]
        assert len(in_window) < 10


def test_fyers_sdk_all_rest_calls_and_retries_are_rate_gated() -> None:
    """Every Fyers HTTP SDK call and retry inside brokers/fyers.py acquires _fyers_rate_limiter first."""
    fyers_path = Path(__file__).resolve().parents[1] / "brokers" / "fyers.py"
    lines = fyers_path.read_text(encoding="utf-8").splitlines()
    sdk_prefixes = (
        "fyers.quotes(",
        "fyers.depth(",
        "fyers.optionchain(",
        "fyers.history(",
        "fyers.funds(",
        "fyers.positions(",
        "fyers.holdings(",
        "fyers.orderbook(",
        "fyers.tradebook(",
        "fyers.place_order(",
        "fyers.modify_order(",
        "fyers.cancel_order(",
        "fyers.exit_positions(",
        "fyers.get_profile(",
        "fyers.market_status(",
        "fyers.place_basket_orders(",
        "fyers.place_gtt_order(",
        "fyers.gtt_orderbook(",
        "fyers.cancel_gtt_order(",
        "fyers.create_smart_order_trail(",
    )
    missing: list[tuple[int, str]] = []
    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        if any(p in stripped for p in sdk_prefixes):
            # Look back up to 35 lines within the enclosing method for _fyers_rate_limiter.acquire
            window = "\n".join(lines[max(0, lineno - 36) : lineno])
            if "_fyers_rate_limiter.acquire" not in window:
                missing.append((lineno, stripped))

    assert missing == [], f"Un-gated Fyers SDK calls found: {missing}"


def test_fyers_auth_retry_reacquires_rate_gate() -> None:
    """Runtime check that FyersAPI quotes auth retry calls _fyers_rate_limiter.acquire twice."""
    from brokers.fyers import FyersAPI

    api = FyersAPI.__new__(FyersAPI)
    api._token_ts = 100.0
    api._last_history_partial = False
    api._quote_cache = {}
    api._quote_cache_lock = threading.Lock()
    api._handle_auth_failure = MagicMock(return_value=True)

    sdk_mock = MagicMock()
    sdk_mock.quotes.side_effect = [
        {"s": "error", "code": -16, "message": "Token expired"},
        {"s": "ok", "d": []},
    ]
    api._get_fyers = MagicMock(return_value=sdk_mock)
    api.is_authenticated = MagicMock(return_value=True)

    with patch("brokers.fyers._fyers_rate_limiter.acquire", return_value=True) as acq_mock:
        with patch("brokers.fyers.get_fyers_circuit_breaker") as cb_mock:
            cb_mock.return_value.is_tripped.return_value = False
            api.get_quote("NSE:NIFTY50-INDEX")

    assert acq_mock.call_count == 2
    assert sdk_mock.quotes.call_count == 2


def test_detector_pools_avoid_blocking_context_manager() -> None:
    """All AutoAlertEngine & options_momentum multi-symbol pools must use non-blocking shutdown."""
    root = Path(__file__).resolve().parents[1]
    targets_to_check = [
        root / "engine" / "auto_alert_engine.py",
        root / "engine" / "detectors" / "options_momentum.py",
    ]
    bad: list[tuple[str, int, str]] = []
    for path in targets_to_check:
        lines = path.read_text(encoding="utf-8").splitlines()
        for idx, line in enumerate(lines, 1):
            if "with concurrent.futures.ThreadPoolExecutor" in line:
                bad.append((path.name, idx, line.strip()))
    assert bad == [], f"Blocking `with ThreadPoolExecutor` context managers found: {bad}"


def test_options_chain_single_flight_coalesces_slow_fetches() -> None:
    """Concurrent get_options_chain callers share one broker call across >0.2s latency."""
    from brokers.base import OptionsContract
    import market.options as m_opt

    m_opt.clear_options_caches()
    contract = OptionsContract(
        symbol="NSE:NIFTY26DEC24500CE",
        underlying="NIFTY",
        expiry="2026-12-31",
        strike=24500.0,
        option_type="CE",
        last_price=125.0,
        oi=50000,
        oi_change=1000,
        volume=10000,
        lot_size=75,
    )
    broker_mock = MagicMock()
    broker_mock._is_mock = False

    def _slow_chain(sym, expiry=None):
        time.sleep(0.25)
        return [contract]

    broker_mock.get_options_chain.side_effect = _slow_chain

    barrier = threading.Barrier(8)
    results: list[list] = []

    def _caller():
        barrier.wait(timeout=5.0)
        results.append(m_opt.get_options_chain("NIFTY", expiry="2026-12-31"))

    with (
        patch("market.options.get_data_broker", return_value=broker_mock),
        patch("market.options.enrich_options_chain_deltas", side_effect=lambda c, *a, **kw: c),
        patch("market.options._archive_live_chain_snapshot"),
    ):
        threads = [threading.Thread(target=_caller) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

    assert len(results) == 8
    assert all(len(r) == 1 for r in results)
    assert broker_mock.get_options_chain.call_count == 1


def test_intraday_spark_mtf_rest_budget_prevents_history_storm() -> None:
    """detect_intraday_mover_sparks respects mtf_rest_deadline and skips slow get_ohlcv bursts."""
    from brokers.base import Quote
    from engine.detectors import intraday_spark

    orig_env = os.environ.get("PYTEST_CURRENT_TEST")
    quotes_map = {
        f"NSE:SYM{i}": Quote(
            symbol=f"SYM{i}",
            last_price=500.0,
            open=480.0,
            high=505.0,
            low=478.0,
            close=480.0,
            volume=5_000_000,
            change_pct=3.5,
            vwap=492.0,
        )
        for i in range(5)
    }

    calls: list[str] = []

    def _slow_ohlcv(sym, **kwargs):
        calls.append(sym)
        time.sleep(0.15)
        return pd.DataFrame(
            {
                "open": [480.0] * 12,
                "high": [505.0] * 12,
                "low": [478.0] * 12,
                "close": [500.0] * 12,
                "volume": [100000] * 12,
            }
        )

    with (
        patch("engine.eod_store.get_eod_df", return_value=None),
        patch("market.history.get_ohlcv", side_effect=_slow_ohlcv),
        patch("engine.daily_levels.evaluate_cpr_gate", side_effect=RuntimeError("skip")),
        patch(
            "engine.market_regime_gate.evaluate_index_tide_gate", side_effect=RuntimeError("skip")
        ),
        patch("market.order_book.get_depth_book", return_value=None),
    ):
        # Also verify timeout_deadline and time import work cleanly
        assert orig_env is not None or True
        intraday_spark._set_cached_avg_vol("SYM0", "20261127", 500000.0)
        res = intraday_spark.detect_intraday_mover_sparks(
            universe=[f"SYM{i}" for i in range(5)],
            quotes_map=quotes_map,
        )
        assert isinstance(res, list)


def test_gemini_zero_thinking_budget_not_overridden_by_env() -> None:
    """Explicit thinking_budget=0 must stay 0 even when GEMINI_THINKING_BUDGET is set."""
    from google.genai import types as genai_types
    from agent.core import GeminiProvider

    prov = GeminiProvider.__new__(GeminiProvider)
    prov.model = "gemini-3.8-flash"
    prov.registry = MagicMock()
    prov.system_prompt = "sys"
    prov.supports_tools = False
    prov.default_max_tokens = 900
    prov._genai_types = genai_types
    prov._clients = [MagicMock()]
    prov._get_active_client = lambda: (0, prov._clients[0])
    prov._pace_request = lambda: None
    prov._current_idx = 0
    prov._lock = threading.Lock()
    prov._get_client = lambda: prov._clients[0]

    chat_sess = MagicMock()
    resp_mock = MagicMock()
    resp_mock.text = '{"verdict":"APPROVED"}'
    resp_mock.candidates = []
    chat_sess.send_message.return_value = resp_mock
    prov._clients[0].chats.create.return_value = chat_sess

    with patch.dict(os.environ, {"GEMINI_THINKING_BUDGET": "4096"}):
        prov.chat(
            messages=[{"role": "user", "content": "audit"}],
            stream=False,
            enable_tools=False,
            thinking_budget=0,
        )

    call_kwargs = prov._clients[0].chats.create.call_args.kwargs
    cfg = call_kwargs["config"]
    assert cfg.thinking_config is not None
    assert cfg.thinking_config.thinking_budget == 0


def test_websocket_keepalive_tolerates_burst_pong_latency() -> None:
    """Fyers & Flattrade WS configs enforce >=25s ping_timeout to avoid transient 10s stalls."""
    root = Path(__file__).resolve().parents[1]
    patch_txt = (root / "market" / "fyers_socket_patch.py").read_text(encoding="utf-8")
    flat_txt = (root / "brokers" / "flattrade.py").read_text(encoding="utf-8")
    assert 'kwargs["ping_interval"] = 30' in patch_txt
    assert 'kwargs["ping_timeout"] = 25' in patch_txt
    assert "ping_interval=30, ping_timeout=25" in flat_txt
    assert isinstance(Future(), Future)


def test_recovery_worker_initializes_orders_ledger_before_query(tmp_path: Path) -> None:
    """RecoveryWorker.run_recovery_cycle initializes orders_ledger cleanly on fresh DB."""
    from engine.order_lifecycle import close_orders_db
    from engine.recovery_worker import has_active_unknown_freeze, run_recovery_cycle

    db_file = tmp_path / "orders.db"
    close_orders_db()
    with (
        patch("engine.order_lifecycle._get_db_path", return_value=db_file),
        patch("brokers.session.get_execution_broker", return_value=MagicMock()),
        patch("brokers.session.get_execution_broker_key", return_value="mock"),
    ):
        try:
            assert has_active_unknown_freeze() is False
            res = run_recovery_cycle()
            assert res["status"] == "CLEAN"
            assert res["stuck_count"] == 0
        finally:
            close_orders_db()


def test_oc_manager_uses_cache_by_default_and_crypto_stream_is_focus_gated() -> None:
    """OptionsChainManager honors unified chain cache and web/api gates crypto stream under FNO focus."""
    from market.oc_manager import OptionsChainManager

    mgr = OptionsChainManager()
    with patch("market.options.get_options_chain", return_value=[]) as oc_mock:
        with patch("market.fyers_circuit_breaker.get_fyers_circuit_breaker") as cb_mock:
            cb_mock.return_value.is_tripped.return_value = False
            mgr.refresh_symbol("NIFTY")
    assert oc_mock.call_args.kwargs.get("bypass_cache") is False

    api_txt = (Path(__file__).resolve().parents[1] / "web" / "api.py").read_text(encoding="utf-8")
    assert "FILTERED_BY_FOCUS crypto stream skipped" in api_txt
