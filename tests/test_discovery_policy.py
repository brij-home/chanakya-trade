"""Production discovery scope must not disable care for existing exposure."""

import asyncio
import json
import threading
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from config.discovery_policy import get_discovery_policy, allows_context_symbol
from engine.auto_alert_engine import AutoAlertEngine


@pytest.fixture
def strict_scope(monkeypatch):
    monkeypatch.setenv("SESSION_FOCUS_MODE", "FNO_ONLY")


def test_production_default_is_strict_and_unknown_profiles_do_not_fall_back(monkeypatch):
    monkeypatch.delenv("SESSION_FOCUS_MODE", raising=False)
    assert get_discovery_policy().fno_only
    monkeypatch.setenv("SESSION_FOCUS_MODE", "TYPO")
    with pytest.raises(ValueError, match="Unknown SESSION_FOCUS_MODE"):
        get_discovery_policy()


@pytest.mark.parametrize(
    "method,args",
    [
        ("scan_crypto_now", ()),
        ("_scan_single_crypto_symbol", ("BTC",)),
        ("scan_commodities_now", ()),
        ("scan_currency_now", ()),
        ("scan_multibagger_compounders", ()),
        ("scan_circuits", ()),
        ("scan_incubation_triggers", ()),
        ("scan_pairs_arbitrage", ()),
        ("scan_swing_inflections", ()),
    ],
)
def test_excluded_discovery_stops_before_accessing_engine_or_feeds(strict_scope, method, args):
    # No initialized engine, watchlist or provider is available: any body work fails.
    engine = AutoAlertEngine.__new__(AutoAlertEngine)
    assert getattr(engine, method)(*args) == []


def test_all_scan_keeps_existing_exposure_checks_and_only_discovers_fno(strict_scope, monkeypatch):
    engine = AutoAlertEngine.__new__(AutoAlertEngine)
    monkeypatch.setattr(
        "engine.auto_alert_engine.get_current_ist_session",
        lambda: {"equity_nfo": True, "currency": True, "commodity": True},
    )
    for name in (
        "check_and_alert_invalidations",
        "check_and_alert_in_flight_decay",
        "check_and_alert_targets_and_trailing",
        "scan_equity_nfo_now",
    ):
        setattr(engine, name, Mock(return_value=[]))
    engine.scan_crypto_now = Mock(side_effect=AssertionError("crypto discovery leaked"))
    engine.scan_commodities_now = Mock(side_effect=AssertionError("MCX discovery leaked"))
    engine.scan_currency_now = Mock(side_effect=AssertionError("CDS discovery leaked"))
    assert engine.scan_all_now(segment="ALL") == []
    engine.scan_equity_nfo_now.assert_called_once()
    for name in (
        "check_and_alert_invalidations",
        "check_and_alert_in_flight_decay",
        "check_and_alert_targets_and_trailing",
    ):
        exchanges = getattr(engine, name).call_args.kwargs["exchanges"]
        assert {"MCX", "CDS", "CRYPTO"}.issubset(exchanges)


def test_strict_discovery_sleeps_when_domestic_session_closed(strict_scope, monkeypatch):
    monkeypatch.setattr(
        "engine.auto_alert_engine.get_current_ist_session",
        lambda: {"equity_nfo": False, "commodity": True},
    )
    engine = AutoAlertEngine.__new__(AutoAlertEngine)
    engine.scan_equity_nfo_now = Mock(side_effect=AssertionError("off-session discovery"))
    for segment in ("AUTO", "ALL", "NFO", "MCX", "CRYPTO"):
        assert engine.scan_fresh_signals_now(segment=segment) == []


def test_crypto_tick_keeps_exit_monitoring_without_impulse_discovery(strict_scope, monkeypatch):
    engine = AutoAlertEngine.__new__(AutoAlertEngine)
    engine._lock = threading.Lock()
    alert = SimpleNamespace(
        symbol="BTC", exchange="CRYPTO", stage="IGNITED", is_invalidated=False, is_archived=False
    )
    engine._alerts = [alert]
    engine._handle_alert_exit = Mock()
    monkeypatch.setattr(
        "engine.auto_alert_engine.evaluate_alert_invalidation",
        lambda *args, **kwargs: "stop crossed",
    )
    engine._on_crypto_tick({"symbol": "BTC", "ltp": 100.0, "timestamp": 1.0})
    engine._handle_alert_exit.assert_called_once()
    assert not hasattr(engine, "_crypto_tick_history")


def test_context_scoping_does_not_require_feed_access(strict_scope):
    assert allows_context_symbol("NSE:NIFTY50-INDEX")
    assert allows_context_symbol("BSE:SENSEX-INDEX")
    assert allows_context_symbol("NSE:SBIN-EQ")
    assert not allows_context_symbol("MCX:GOLD")
    assert not allows_context_symbol("CRYPTO:BTC")
    assert not allows_context_symbol("NSE:UNLISTED_CASH_ONLY-EQ")
    assert not allows_context_symbol("NSE:GOLD")
    assert not allows_context_symbol("NSE:USDINR")
    assert not allows_context_symbol("NSE:UNLISTED26NOV100CE")


def test_strict_crypto_transport_start_and_off_hours_tbt_do_no_work(strict_scope):
    from market.crypto_stream import CryptoStreamManager
    from market.fyers_tbt_manager import get_default_core_grid

    transport = object.__new__(CryptoStreamManager)
    transport.start()
    assert not hasattr(transport, "_running")
    assert get_default_core_grid("COMMODITY_CDS") == ([], [])
    assert get_default_core_grid("OFF_MARKET", primary_focus="NIFTY") == ([], [])


def test_ticker_polling_excludes_unrelated_feed_requests(strict_scope, monkeypatch):
    from market.ticker_stream import compute_ribbon_tickers

    requested = []
    monkeypatch.setattr("market.quotes.get_quote", lambda symbols: requested.extend(symbols) or {})
    result = compute_ribbon_tickers()
    assert requested
    assert all(not symbol.startswith(("MCX:", "CRYPTO:", "CDS:")) for symbol in requested)
    assert not any(item["category"] in {"CRYPTO", "COMMODITY"} for item in result)


def test_legacy_wide_radar_cache_cannot_leak_into_strict_profile(strict_scope, monkeypatch):
    import time
    from engine.precursor_radar import PrecursorRadarScanner
    from engine.asymmetric_radar import AsymmetricRadarScanner

    precursor = PrecursorRadarScanner()
    precursor._cache[(None, "CRYPTO")] = ["legacy crypto candidate"]
    precursor._cache_ts[(None, "CRYPTO")] = time.monotonic()
    assert precursor.scan_precursors(segment="CRYPTO") == []
    asymmetric = AsymmetricRadarScanner()
    asymmetric._cache["CRYPTO"] = ["legacy crypto candidate"]
    asymmetric._cache_ts["CRYPTO"] = time.monotonic()
    assert asymmetric.scan_asymmetric_opportunities(segment="CRYPTO") == []


def test_subscription_bootstrap_omits_commodity_discovery_but_retains_legacy_tracking(
    strict_scope, monkeypatch, tmp_path
):
    from market import ws_subscription_manager as module

    path = tmp_path / "subscriptions.json"
    monkeypatch.setattr(module, "_get_cache_path", lambda: path)
    monkeypatch.setattr(
        module, "CORE_BASE_SYMBOLS", ["NSE:NIFTY50-INDEX", "MCX:GOLD", "NSE:SBIN-EQ"]
    )
    manager = module.WsSubscriptionManager()
    assert "MCX:GOLD" not in manager.get_all_desired_subscriptions()
    monkeypatch.setattr(module, "get_active_index_options_grid", lambda: [])
    monkeypatch.setattr(
        module,
        "get_active_commodity_grid",
        Mock(side_effect=AssertionError("commodity grid work leaked")),
    )
    assert manager.seed_active_derivatives() == []
    # Persisted symbols have unknown exposure purpose, so retain them honestly
    # rather than dropping potentially necessary risk data during a scope change.
    path.write_text(json.dumps({"dynamic": ["MCX:GOLD26DECFUT"]}), encoding="utf-8")
    restored = module.WsSubscriptionManager()
    assert "MCX:GOLD26DECFUT" in restored.get_all_desired_subscriptions()
    assert "MCX:GOLD26DECFUT" in restored.get_diagnostics()["retained_out_of_scope_symbols"]


def test_more_than_four_exposures_preempt_tbt_discovery_without_losing_registration(
    strict_scope, monkeypatch
):
    from market import fyers_tbt_manager as module

    manager = object.__new__(module.FyersTbtManager)
    manager._slots_lock = threading.RLock()
    manager._in_flight = []
    manager._evicted_cooldowns = {}
    manager._core_grid = ["NSE:DISCOVERY"]
    manager._todays_expiry = []
    manager._scout = OrderedDict()
    manager.sync_subscriptions = Mock()
    monkeypatch.setattr(module, "resolve_tradable_tbt_symbol", lambda symbol: symbol)
    symbols = [f"NSE:EXPOSURE-{index}" for index in range(16)]
    for symbol in symbols:
        manager.register_in_flight(symbol)
    assert manager._in_flight == symbols
    desired = manager.compute_desired_subscriptions(fill_sector_leaders=False)
    assert desired == symbols[:15]
    assert "NSE:DISCOVERY" not in desired


def test_focused_stock_discovery_cannot_outrank_index_options(strict_scope):
    from market.fyers_tbt_manager import _tbt_symbol_priority

    stock = _tbt_symbol_priority("NSE:TCS26NOV3000CE", session="EQUITY_NFO", primary_focus="TCS")
    index = _tbt_symbol_priority("NSE:NIFTY26NOV25000PE", session="EQUITY_NFO", primary_focus="TCS")
    assert index > stock


def test_mode_reports_scope_without_changing_execution_mode(strict_scope):
    from web.api import api_mode

    payload = json.loads(asyncio.run(api_mode()).body)
    assert payload["mode"] == "PAPER"
    assert payload["discovery_policy"]["profile"] == "FNO_ONLY"
    assert payload["discovery_policy"]["existing_exposure_monitoring"] == "UNRESTRICTED_BY_FOCUS"


def test_direct_registry_and_alert_ingestion_cannot_bypass_scope(strict_scope):
    from engine.detection_context import DetectionContext, DetectorRegistry

    registry = DetectorRegistry()
    detector = SimpleNamespace(
        detector_slug="unexpected", detect=Mock(side_effect=AssertionError("detector ran"))
    )
    registry.register(detector)
    assert (
        registry.evaluate_all(
            DetectionContext(symbol="BTC", canonical_symbol="BTC", exchange="CRYPTO")
        )
        == []
    )
    detector.detect.assert_not_called()


def test_fno_only_ingestion_rejects_cash_desk_and_keeps_derivative_contracts(
    strict_scope, monkeypatch, tmp_path
):
    from engine.alert_model import AutoAlert

    monkeypatch.setattr(
        "engine.auto_alert_engine.get_auto_alerts_file", lambda: tmp_path / "alerts.json"
    )
    engine = AutoAlertEngine(max_buffer=5)
    engine.clear_alerts()

    cash = AutoAlert(
        alert_id="cash-only-discovery",
        alert_type="PRECURSOR_RADAR",
        stage="EARLY_WARNING",
        symbol="SBIN",
        exchange="NSE",
        direction="BULLISH",
        headline="Cash equity candidate",
        summary="Context must not become a separate cash desk",
        ltp=800,
        trigger_level=800,
        stop_loss=780,
        target_level=860,
    )
    assert engine.record_alert(cash) is False
    assert cash.audit_trail[-1]["event_type"] == "FOCUS_FILTERED"

    derivative = AutoAlert(
        alert_id="stock-option-discovery",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="SBIN",
        exchange="NFO",
        direction="BULLISH",
        headline="Stock option candidate",
        summary="Listed derivative contract with evidence",
        ltp=20,
        trigger_level=20,
        stop_loss=18,
        target_level=26,
        option_type="CE",
        contract_symbol="SBIN26NOV800CE",
        metrics={"volume": 100000, "oi": 100000},
        environment="PAPER",
        is_live=False,
    )
    assert engine.record_alert(derivative) is True
    engine = AutoAlertEngine.__new__(AutoAlertEngine)
    engine._lock = threading.Lock()
    engine._alerts = []
    alert = SimpleNamespace(
        alert_id="excluded-discovery", exchange="CRYPTO", symbol="BTC", record_audit=Mock()
    )
    assert engine.record_alert(alert) is False
    alert.record_audit.assert_called_once()
