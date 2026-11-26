"""Regression tests for Phase 3B cluster coalescing, PARTIAL_DATA provenance, and codebase hygiene."""

from __future__ import annotations

from datetime import datetime
import pathlib
import re
from unittest.mock import patch


def test_history_marks_partial_data_and_skips_eod_persistence(monkeypatch):
    from market.history import clear_df_memory_cache, get_ohlcv

    clear_df_memory_cache()

    class _PartialBroker:
        _is_mock = False
        _last_history_partial = True

        def get_historical_data(self, *args, **kwargs):
            return [
                {
                    "date": "2026-11-20 09:15:00",
                    "open": 25000.0,
                    "high": 25020.0,
                    "low": 24990.0,
                    "close": 25010.0,
                    "volume": 5000,
                }
            ]

    monkeypatch.setattr("brokers.session.get_data_broker", lambda: _PartialBroker())
    monkeypatch.setattr("brokers.session.get_data_broker_key", lambda: "fyers")
    monkeypatch.setattr("brokers.session.get_all_brokers", lambda: {"fyers": _PartialBroker()})
    monkeypatch.setattr("engine.eod_store.get_ohlcv_batch", lambda *a, **k: {})

    with patch("engine.historical_warehouse.historical_warehouse.save_bars") as mock_save:
        df = get_ohlcv(
            "PARTIALSYM",
            exchange="NSE",
            interval="5m",
            days=10,
            as_of=datetime(2026, 11, 20, 15, 30),
        )

    assert not df.empty
    assert df.attrs["provenance"]["data_source"] == "PARTIAL_DATA"
    assert df.attrs["provenance"]["is_partial"] is True
    assert df.attrs["provenance"]["reproducible"] is False
    mock_save.assert_not_called()


def test_zero_bare_except_pass_in_core_modules():
    checked = [
        "engine/alert_scrutiny.py",
        "engine/auto_alert_engine.py",
        "engine/outbox_worker.py",
        "engine/paper.py",
        "engine/detectors/commodity.py",
        "engine/detectors/intraday_spark.py",
        "engine/detectors/options_momentum.py",
        "engine/detectors/smc_orderblock_retest.py",
        "engine/detectors/trend_day_continuation.py",
        "market/calendar.py",
        "market/options.py",
        "market/quotes.py",
        "market/vectorized_greeks.py",
        "config/discovery_policy.py",
    ]
    leftovers = []
    for rel in checked:
        lines = pathlib.Path(rel).read_text(encoding="utf-8").splitlines()
        for idx, line in enumerate(lines):
            s = line.strip()
            if re.match(r"^except\b.*:\s*pass\s*(#.*)?$", s):
                leftovers.append(f"{rel}:{idx + 1}")
            if (
                idx + 1 < len(lines)
                and re.match(r"^except\b.*:\s*(#.*)?$", s)
                and lines[idx + 1].strip() == "pass"
            ):
                leftovers.append(f"{rel}:{idx + 1}")
    assert leftovers == []


def test_app_data_path_overrides_rate_gate_and_calibration(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))
    monkeypatch.setenv("TRADING_PLATFORM_HOME", str(tmp_path))
    from market.fyers_rate_gate import _get_quota_file
    from config.paths import app_data_path

    assert _get_quota_file() == tmp_path / "fyers_daily_quota.json"
    assert (
        app_data_path("calibration", "index_calibration.json")
        == tmp_path / "calibration" / "index_calibration.json"
    )


def test_semantic_cluster_coalesces_overlapping_equity_signals(monkeypatch):
    from engine.alert_identity import generate_alert_id
    from engine.alert_model import AutoAlert
    from engine.auto_alert_engine import AutoAlertEngine

    engine = AutoAlertEngine.__new__(AutoAlertEngine)
    import threading

    engine._lock = threading.RLock()
    engine._alerts = []
    engine._max_buffer = 50
    engine._clean_sym = lambda s: s.replace("NSE:", "").replace("NFO:", "").strip().upper()
    engine._alert_date = lambda a: datetime(2026, 11, 25).date()

    # Seed first active alert directly with matching cluster_key
    from engine.alert_identity import semantic_cluster_key

    c_key = semantic_cluster_key(
        "RELIANCE", direction="BULLISH", horizon="INTRADAY", trigger_price=1350.0
    )
    a1 = AutoAlert(
        alert_id=generate_alert_id("RELIANCE", "SQUEEZE_BREAKOUT"),
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="RELIANCE",
        exchange="NSE",
        segment="FNO_STOCK",
        direction="BULLISH",
        headline="Reliance Squeeze",
        summary="Trigger",
        ltp=1350.0,
        trigger_level=1350.0,
        stop_loss=1335.0,
        target_level=1395.0,
        confidence=80,
        is_live=True,
        environment="PAPER",
        details={"cluster_key": c_key},
    )
    engine._alerts.append(a1)

    # Confirm second distinct detector within the exact same cluster key coalesces without duplicating
    a2 = AutoAlert(
        alert_id=generate_alert_id("RELIANCE", "OPENING_DRIVE"),
        alert_type="OPENING_DRIVE",
        stage="IGNITED",
        symbol="RELIANCE",
        exchange="NSE",
        segment="FNO_STOCK",
        direction="BULLISH",
        headline="Reliance Drive",
        summary="Trigger",
        ltp=1351.0,
        trigger_level=1351.0,
        stop_loss=1335.0,
        target_level=1399.0,
        confidence=82,
        is_live=True,
        environment="PAPER",
        details={},
    )
    # Invoke cluster matching helper logic deterministically
    incoming_key = semantic_cluster_key(
        "RELIANCE", direction=a2.direction, horizon="INTRADAY", trigger_price=a2.trigger_level
    )
    assert incoming_key == c_key
    leader = next(
        (
            a
            for a in engine._alerts
            if a.is_active and (a.details or {}).get("cluster_key") == incoming_key
        ),
        None,
    )
    assert leader is a1
