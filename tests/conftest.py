"""
Shared fixtures for the test suite.

All fixtures produce deterministic, synthetic data — no network calls.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

worker_id = os.environ.get("PYTEST_XDIST_WORKER", "")
if worker_id:
    _TEST_DATA_DIR = Path(__file__).parent.parent / f".pytest_trading_platform_{worker_id}"
else:
    _TEST_DATA_DIR = Path(__file__).parent.parent / ".pytest_trading_platform"

_TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)
(_TEST_DATA_DIR / "pdf").mkdir(parents=True, exist_ok=True)
os.environ["TRADING_PLATFORM_HOME"] = str(_TEST_DATA_DIR)
os.environ["TRADING_PLATFORM_DATA"] = str(_TEST_DATA_DIR)
os.environ["TRADING_PLATFORM_PDF_DIR"] = str(_TEST_DATA_DIR / "pdf")
os.environ["CHANAKYA_EOD_DB_PATH"] = str(_TEST_DATA_DIR / "test_eod_bars.db")
os.environ["CHANAKYA_TESTING"] = "1"
os.environ["ALLOW_MANUAL_TELEGRAM_DISPATCH"] = "1"
os.environ["TRADING_MODE"] = "PAPER"
# Test runs must not inherit deployment authentication policy from a developer's
# local .env file. Individual auth tests explicitly opt into self-hosted mode
# with monkeypatch, while the rest of the suite exercises endpoints without a
# real user setup.
os.environ["DEPLOY_MODE"] = "test"
os.environ.setdefault("CSRF_SECRET", "test-strong-csrf-secret-1234567890-32chars")
os.environ.setdefault("KEYRING_DISABLE", "1")
os.environ.setdefault("PYTHONKEYRING_BACKEND", "keyring.backends.null.Keyring")

# Institutional thread safety & leak prevention:
# 1. Patch fyers_apiv3 WebSocket SDK so all its internal ping/worker threads are daemon threads.
try:
    from market.fyers_socket_patch import patch_fyers_websocket_daemon_threads

    patch_fyers_websocket_daemon_threads()
except Exception:
    pass

# 2. Defensively ensure ANY thread instantiated during pytest sessions is a daemon thread,
# preventing non-daemon threads from hanging Python process shutdown (threading._shutdown).
import socket
import threading

_orig_thread_init = threading.Thread.__init__


def _test_safe_thread_init(self, *args, **kwargs):
    if not kwargs.get("daemon"):
        kwargs["daemon"] = True
    _orig_thread_init(self, *args, **kwargs)


threading.Thread.__init__ = _test_safe_thread_init


@pytest.fixture(autouse=True)
def _isolate_fyers_rate_gate_and_circuit_breaker():
    """Defensively reset rate gate, circuit breaker, and regime cache before and after each test."""

    def _do_reset():
        try:
            from market.fyers_circuit_breaker import get_fyers_circuit_breaker

            get_fyers_circuit_breaker().reset()
        except Exception:
            pass
        try:
            from market.fyers_rate_gate import get_fyers_rate_gate

            gate = get_fyers_rate_gate()
            gate.reset_state()
            gate.reset_daily_quota(requests=0)
        except Exception:
            pass
        try:
            from engine.equity_adaptive_regime import (
                _EQUITY_REGIME_CACHE,
                _EQUITY_REGIME_CACHE_LOCK,
            )

            with _EQUITY_REGIME_CACHE_LOCK:
                _EQUITY_REGIME_CACHE.clear()
        except Exception:
            pass

    _do_reset()
    yield
    _do_reset()


# 3. Institutional zero-network quarantine:
# Defensively isolate test sessions from unmocked external network connections.
# Any attempt to connect to a non-loopback host raises RuntimeError unless marked with @pytest.mark.network.
_orig_socket_connect = socket.socket.connect
_PROCESS_ALLOW_NETWORK = False
_ALLOWED_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


def _test_guarded_socket_connect(self, address):
    if os.environ.get("CHANAKYA_TESTING") == "1" and not _PROCESS_ALLOW_NETWORK:
        if isinstance(address, (tuple, list)) and len(address) >= 1:
            host = address[0]
            if isinstance(host, str) and host not in _ALLOWED_LOCAL_HOSTS:
                raise RuntimeError(
                    f"Outbound network connection blocked during test: socket.connect to {host}. "
                    "Mock this external API call or mark the test with @pytest.mark.network."
                )
    return _orig_socket_connect(self, address)


socket.socket.connect = _test_guarded_socket_connect


def pytest_configure(config: pytest.Config) -> None:
    """Keep pytest's temporary files inside the checkout by default.

    Some managed Windows workspaces deny access to the user's global
    ``%TEMP%\\pytest-of-*`` directory and to a pre-existing ``.pytest_cache``.
    A local, worker-specific directory makes direct ``pytest`` invocations as
    reliable as the CI command while still respecting explicit CLI overrides.
    """
    if config.option.basetemp is None:
        session_tmp = _TEST_DATA_DIR / f"pytest-tmp-{os.getpid()}"
        config.option.basetemp = str(session_tmp)


def pytest_unconfigure(config: pytest.Config) -> None:
    """Safely cleans up session temp directory if created for this process."""
    try:
        import shutil

        basetemp = getattr(config.option, "basetemp", None)
        if basetemp and Path(basetemp).name.startswith("pytest-tmp-") and Path(basetemp).exists():
            shutil.rmtree(basetemp, ignore_errors=True)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def sanitize_test_env(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    """Ensure no unit test accidentally inherits live AI credentials or makes live LLM calls."""
    global _PROCESS_ALLOW_NETWORK
    _PROCESS_ALLOW_NETWORK = "network" in request.keywords
    # Several legacy module-scoped clients mutate DEPLOY_MODE directly. Reset
    # the default for every test so a self-hosted test cannot leak its auth
    # policy into unrelated endpoint tests. Auth tests opt in explicitly.
    monkeypatch.setenv("DEPLOY_MODE", "test")
    if "network" not in request.keywords:
        monkeypatch.setenv("CHANAKYA_TESTING", "1")
        monkeypatch.setenv("AI_FAST_PROVIDER", "")
        monkeypatch.setenv("AI_FAST_MODEL", "")
        monkeypatch.setenv("AI_DEEP_PROVIDER", "")
        monkeypatch.setenv("GROQ_API_KEY", "")
        monkeypatch.setenv("GEMINI_API_KEY", "")
        monkeypatch.setenv("OPENAI_API_KEY", "")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        monkeypatch.setenv("NVIDIA_API_KEY", "")
        monkeypatch.setenv("OPENROUTER_API_KEY", "")

    try:
        from collections import OrderedDict
        import market.quotes as mq

        if not isinstance(mq._QUOTE_CACHE, OrderedDict):
            mq._QUOTE_CACHE = OrderedDict()
        with mq._quote_cache_lock:
            mq._QUOTE_CACHE.clear()
        with mq._in_flight_quote_lock:
            mq._in_flight_quote_events.clear()
    except Exception:
        pass

    try:
        from market.fyers_tbt_manager import FyersTbtManager

        tbt_mgr = FyersTbtManager()
        tbt_mgr.reset_for_testing()
    except Exception:
        pass

    try:
        from market.universe_depth_radar import clear_radar_cache

        clear_radar_cache()
    except Exception:
        pass

    try:
        from engine.market_regime_gate import clear_cached_regime

        clear_cached_regime()
    except Exception:
        pass

    try:
        from engine.index_velocity import clear_velocity_cache

        clear_velocity_cache()
    except Exception:
        pass

    try:
        from market.websocket import FyersWebSocket

        ws = FyersWebSocket._instance
        if ws:
            with ws._lock:
                ws._ticks.clear()
    except Exception:
        pass

    try:
        from market.options import _CHAIN_CACHE, _EXPIRIES_CACHE, _SNAPSHOT_CACHE

        _CHAIN_CACHE.clear()
        _EXPIRIES_CACHE.clear()
        _SNAPSHOT_CACHE.clear()
    except Exception:
        pass

    try:
        from market.history import _df_memory_cache, _df_memory_cache_lock

        with _df_memory_cache_lock:
            _df_memory_cache.clear()
    except Exception:
        pass

    try:
        from engine.detector_circuit_breaker import detector_circuit_breaker

        detector_circuit_breaker.reset_all()
    except Exception:
        pass

    try:
        from engine.risk_limits import risk_limits

        risk_limits.reset_all()
    except Exception:
        pass

    try:
        yield
    finally:
        _PROCESS_ALLOW_NETWORK = False
        try:
            from engine.market_regime_gate import clear_cached_regime

            clear_cached_regime()
        except Exception:
            pass
        try:
            from market.universe_depth_radar import clear_radar_cache

            clear_radar_cache()
        except Exception:
            pass
        try:
            from market.fyers_tbt_manager import FyersTbtManager

            FyersTbtManager().reset_for_testing()
        except Exception:
            pass
        try:
            from engine.index_velocity import clear_velocity_cache

            clear_velocity_cache()
        except Exception:
            pass


@pytest.fixture(autouse=True)
def isolate_test_notifications(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    """Ensure tests never emit real-world Telegram pushes or desktop popups."""
    if "live_telegram" not in request.keywords:
        try:
            monkeypatch.setattr("engine.alerts._telegram_notify", lambda *args, **kwargs: None)
        except Exception:
            pass
        try:
            monkeypatch.setattr("engine.alerts._desktop_notify", lambda **kwargs: None)
        except Exception:
            pass
        try:
            monkeypatch.setattr("bot.telegram_bot.send_push", lambda *args, **kwargs: None)
        except Exception:
            pass


@pytest.fixture(autouse=True)
def isolate_market_websockets(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    """Ensure unit tests never establish real broker WebSockets or background streams."""
    if "live_websocket" not in request.keywords and "network" not in request.keywords:
        try:
            monkeypatch.setattr("brokers.session._start_websocket", lambda *args, **kwargs: None)
        except Exception:
            pass
        try:
            from market.websocket import ws_manager

            monkeypatch.setattr(ws_manager, "start", lambda *args, **kwargs: None)
        except Exception:
            pass
        try:
            from market.fyers_order_stream import fyers_order_stream

            monkeypatch.setattr(fyers_order_stream, "start", lambda *args, **kwargs: None)
        except Exception:
            pass
        try:
            from market.fyers_tbt_manager import fyers_tbt_manager

            monkeypatch.setattr(fyers_tbt_manager, "start", lambda *args, **kwargs: None)
        except Exception:
            pass
        try:
            from market.mstock_websocket import mstock_ws

            monkeypatch.setattr(mstock_ws, "start", lambda *args, **kwargs: None)
        except Exception:
            pass
        try:
            from market.kotak_websocket import kotak_ws

            monkeypatch.setattr(kotak_ws, "start", lambda *args, **kwargs: None)
        except Exception:
            pass


@pytest.fixture(autouse=True)
def isolate_alert_preferences(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Ensure alert preferences start from clean defaults and disk writes are isolated."""
    try:
        from engine.alert_preferences import AlertPreferences, alert_preferences

        test_file = tmp_path / "alert_preferences.json"
        monkeypatch.setattr(alert_preferences, "_pref_file", test_file)
        with alert_preferences._lock:
            alert_preferences._preferences = AlertPreferences()
        yield
        with alert_preferences._lock:
            alert_preferences._preferences = AlertPreferences()
    except ImportError:
        yield


@pytest.fixture(autouse=True)
def isolate_learning_engine(monkeypatch: pytest.MonkeyPatch):
    """Ensure learning engine symbol lockouts and temporary states do not leak between tests."""
    try:
        from engine.learning_engine import pattern_learning_engine

        pattern_learning_engine.clear_symbol_lockout()
        yield
        pattern_learning_engine.clear_symbol_lockout()
    except Exception:
        yield


@pytest.fixture(autouse=True)
def seed_test_rrg_cache():
    """Ensure analysis cache has deterministic RRG sector matrix for zero-network testing."""
    try:
        from engine.analysis_cache import analysis_cache
        from analysis.sector_rotation import (
            NSE_SECTORS,
            SECTOR_PROXY_STOCKS,
            SECTOR_CONSTITUENTS,
            SECTOR_DRIVERS,
        )

        cached = analysis_cache.get_macro("sector_rrg_matrix")
        if not cached:
            quadrants = ["LEADING", "IMPROVING", "WEAKENING", "LAGGING"]
            fake_matrix = []
            for i, (sec, sym) in enumerate(NSE_SECTORS.items()):
                quad = quadrants[i % len(quadrants)]
                rs_r = 102.5 if quad in ("LEADING", "WEAKENING") else 98.0
                rs_m = 101.5 if quad in ("LEADING", "IMPROVING") else 98.5
                proxy = SECTOR_PROXY_STOCKS.get(sec, "INFY")
                fake_matrix.append(
                    {
                        "sector": sec,
                        "symbol": sym,
                        "rs_ratio": rs_r,
                        "rs_momentum": rs_m,
                        "quadrant": quad,
                        "day_change_pct": 1.2,
                        "benchmark_change_pct": 0.5,
                        "relative_strength": 103.5,
                        "trail": [{"rs_ratio": rs_r, "rs_momentum": rs_m}],
                        "top_stocks": SECTOR_CONSTITUENTS.get(sec, [proxy]),
                        "factor_drivers": SECTOR_DRIVERS.get(sec, ["Institutional Flow"]),
                    }
                )
            analysis_cache.save_macro("sector_rrg_matrix", fake_matrix, ttl_minutes=180)
    except Exception:
        pass
    yield


_BASE_OHLCV_DF: pd.DataFrame | None = None


def _get_base_ohlcv_df() -> pd.DataFrame:
    global _BASE_OHLCV_DF
    if _BASE_OHLCV_DF is None:
        np.random.seed(42)
        n = 200
        dates = pd.date_range("2025-01-01", periods=n, freq="B")
        trend = np.concatenate(
            [
                np.linspace(100, 150, 100),
                np.linspace(150, 110, 100),
            ]
        )
        noise = np.random.randn(n) * 2
        close = trend + noise
        high = close + np.abs(np.random.randn(n)) * 1.5
        low = close - np.abs(np.random.randn(n)) * 1.5
        opn = close + np.random.randn(n) * 0.5
        volume = np.random.randint(500_000, 5_000_000, n)
        _BASE_OHLCV_DF = pd.DataFrame(
            {
                "open": opn,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            },
            index=dates,
        )
    return _BASE_OHLCV_DF


@pytest.fixture
def ohlcv_df() -> pd.DataFrame:
    """200-row OHLCV DataFrame with deterministic prices (fast cached copy)."""
    return _get_base_ohlcv_df().copy()


@pytest.fixture
def strong_fundamentals() -> dict:
    """High-quality company fundamentals — should score STRONG."""
    return {
        "name": "Test Corp",
        "pe": 18.0,
        "pb": 3.0,
        "roe": 22.0,
        "roce": 25.0,
        "npm": 15.0,
        "sales_growth": 15.0,
        "profit_growth": 20.0,
        "debt_equity": 0.3,
        "current_ratio": 2.0,
        "promoter_holding": 55.0,
        "pledged_pct": 0.0,
        "dividend_yield": 2.0,
    }


@pytest.fixture
def weak_fundamentals() -> dict:
    """Weak company fundamentals — should score WEAK or AVOID."""
    return {
        "name": "Bad Corp",
        "pe": 80.0,
        "pb": 0.5,
        "roe": 5.0,
        "roce": 6.0,
        "npm": 2.0,
        "sales_growth": -5.0,
        "profit_growth": -10.0,
        "debt_equity": 2.5,
        "current_ratio": 0.6,
        "promoter_holding": 20.0,
        "pledged_pct": 30.0,
        "dividend_yield": 0.0,
    }


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Clean up any singleton background services when pytest finishes."""
    try:
        from market.websocket import ws_manager

        ws_manager.stop(timeout=0.2)
    except Exception:
        pass
    try:
        from market.fyers_order_stream import fyers_order_stream

        fyers_order_stream.stop(timeout=0.2)
    except Exception:
        pass
    try:
        from market.fyers_tbt_manager import fyers_tbt_manager

        fyers_tbt_manager.stop(timeout=0.2)
    except Exception:
        pass
    try:
        from market.mstock_websocket import mstock_ws

        mstock_ws.stop(timeout=0.2)
    except Exception:
        pass
    try:
        from market.kotak_websocket import kotak_ws

        kotak_ws.stop()
    except Exception:
        pass
    try:
        from market.tick_store import tick_store

        tick_store.stop(timeout=0.2)
    except Exception:
        pass
    try:
        from market.ticker_stream import ticker_stream

        ticker_stream.stop(timeout=0.2)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def reset_auto_alert_engine_pacing():
    """Ensure hermetic test isolation for AutoAlertEngine pacing & dispatch tables."""
    yield
    try:
        from engine.auto_alert_engine import auto_alert_engine

        if auto_alert_engine is not None:
            auto_alert_engine._sector_daily_telegram.clear()
            auto_alert_engine._daily_index_telegram.clear()
            auto_alert_engine._index_half_telegram.clear()
            auto_alert_engine._sector_hourly_telegram.clear()
            for k in auto_alert_engine._hourly_telegram_dispatches:
                auto_alert_engine._hourly_telegram_dispatches[k].clear()
            auto_alert_engine._hourly_index_directional.clear()
            auto_alert_engine._hourly_fno_stock_directional.clear()
    except Exception:
        pass
