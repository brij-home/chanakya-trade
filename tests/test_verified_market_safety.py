"""Behavioral release contracts sourced from exchange rules, not implementation constants."""

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from config.constants import IST
from engine.charges import calculate_transaction_charges
from market.rule_schedule import expiry_weekday, derivative_close, monthly_expiry


@pytest.mark.parametrize("venue,expected", [("NSE", 1), ("NFO", 1), ("BSE", 3), ("BFO", 3)])
def test_current_expiry_rule(venue, expected):
    assert expiry_weekday(venue, date(2026, 10, 30)) == expected


def test_effective_dates_and_holiday_roll():
    from market.calendar import get_nearest_weekly_expiry

    assert monthly_expiry(2026, 10, "NSE") == date(2026, 10, 27)
    assert monthly_expiry(2026, 10, "BSE") == date(2026, 10, 29)
    assert expiry_weekday("NSE", date(2025, 8, 1)) == 3
    assert get_nearest_weekly_expiry("NIFTY", ref_date=date(2026, 10, 19)) == date(2026, 10, 19)
    assert derivative_close(date(2026, 10, 30)).hour == 15
    assert derivative_close(date(2026, 10, 30)).minute == 40
    assert derivative_close(date(2026, 12, 7)).minute == 45
    assert derivative_close(date(2026, 12, 7), expiring_index=True).minute == 30


@pytest.mark.parametrize("segment,old,new", [("FUTURES", 20, 50), ("OPTIONS", 100, 150)])
def test_stt_effective_boundary(segment, old, new):
    for day, expected in [(date(2026, 3, 31), old), (date(2026, 4, 1), new)]:
        result = calculate_transaction_charges(100, 1000, segment, "SELL", trade_date=day)
        assert result.stt == Decimal(expected)


def test_exercise_tax_uses_intrinsic_not_premium():
    assert calculate_transaction_charges(
        100,
        1000,
        "OPTIONS",
        "BUY",
        trade_date=date(2026, 10, 30),
        option_exercised=True,
        intrinsic_value=10,
    ).stt == Decimal("15")
    with pytest.raises(ValueError):
        calculate_transaction_charges(100, 1000, "OPTIONS", "BUY", option_exercised=True)


def test_zero_dte_is_not_defaulted():
    from engine.eod_rebalancer import audit_open_positions_for_physical_delivery

    result = audit_open_positions_for_physical_delivery(
        positions=[
            dict(
                symbol="RELIANCE",
                net_quantity=250,
                strike=100,
                option_type="CE",
                lot_size=250,
                days_to_expiry=0,
                spot_price=110,
            )
        ]
    )
    assert result[0].days_to_expiry == 0
    assert result[0].risk_level == "CRITICAL_DELIVERY_RISK"


def test_write_transaction_rollback(tmp_path):
    from engine.db_pool import SQLiteConnectionPool

    pool = SQLiteConnectionPool(str(tmp_path / "transaction.db"))
    try:
        with pool.acquire() as conn:
            conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        with pytest.raises(RuntimeError):
            with pool.transaction() as conn:
                conn.execute("INSERT INTO t VALUES (1)")
                raise RuntimeError("simulated second-leg claim failure")
        with pool.acquire() as conn:
            assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0
    finally:
        pool.close()


def test_emergency_paper_cannot_touch_real_broker(monkeypatch):
    from engine import order_lifecycle as ol

    real = Mock()
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setattr("brokers.session.get_execution_broker", Mock(return_value=real))
    fake = SimpleNamespace(get_orders=lambda: [], get_positions=lambda: [])
    monkeypatch.setattr("engine.paper.PaperBroker", lambda: fake)
    monkeypatch.setattr(ol, "set_emergency_lockout", lambda duration: 0)
    result = ol.emergency_flatten_all_positions()
    assert not real.mock_calls
    assert result["status"] != "SUCCESS"


def test_unknown_segment_fails_closed(monkeypatch):
    from engine import pretrade

    clock = Mock()
    clock.now.return_value = datetime(2026, 10, 30, 18, 0, tzinfo=IST)
    monkeypatch.setattr(pretrade, "datetime", clock)
    for segment in ("OPTIONS", "FUTURES", "EQUITY_DELIVERY", "NOT_A_SEGMENT"):
        assert not pretrade._gate_market_session(segment).passed


def test_cas_cash_continuous_trading_is_not_assumed_open(monkeypatch):
    from engine import pretrade

    clock = Mock()
    clock.now.return_value = datetime(2026, 10, 30, 15, 20, tzinfo=IST)
    monkeypatch.setattr(pretrade, "datetime", clock)
    assert not pretrade._gate_market_session("EQUITY_DELIVERY", symbol="TCS").passed
    assert pretrade._gate_market_session("OPTIONS", symbol="TCS26NOV3000CE").passed


def test_december_derivative_close_is_contract_and_expiry_aware(monkeypatch):
    from engine import pretrade
    from datetime import datetime as dt_datetime

    clock = Mock()
    clock.now.return_value = datetime(2026, 12, 7, 15, 35, tzinfo=IST)
    monkeypatch.setattr(pretrade, "datetime", clock)

    expiry_epoch = int(dt_datetime(2026, 12, 7, 15, 30, tzinfo=IST).timestamp())

    def master_row(symbol, **kwargs):
        if symbol == "NSE:NIFTY26D0725000CE":
            return {"expiryDate": expiry_epoch, "underSym": "NIFTY"}
        if symbol == "NSE:TCS26D074000CE":
            return {"expiryDate": expiry_epoch, "underSym": "TCS"}
        return None

    monkeypatch.setattr("market.symbol_master.get_symbol_info", master_row)
    assert not pretrade._gate_market_session("OPTIONS", "NSE:NIFTY26D0725000CE").passed
    assert pretrade._gate_market_session("OPTIONS", "NSE:TCS26D074000CE").passed


def test_december_derivative_cutoff_fails_closed_without_master(monkeypatch):
    from engine import pretrade

    clock = Mock()
    clock.now.return_value = datetime(2026, 12, 7, 15, 35, tzinfo=IST)
    monkeypatch.setattr(pretrade, "datetime", clock)
    monkeypatch.setattr("market.symbol_master.get_symbol_info", lambda symbol, **kwargs: None)

    result = pretrade._gate_market_session("OPTIONS", "NSE:UNKNOWN26D0725000CE")
    assert not result.passed
    assert "Current derivative master data" in result.reason


def test_administrative_routes_require_auth(monkeypatch):
    from fastapi.testclient import TestClient
    import web.api as api

    monkeypatch.setenv("DEPLOY_MODE", "self-hosted")
    monkeypatch.setattr(api, "user_count", lambda: 1)
    client = TestClient(api.app)
    for path in (
        "/api/maintenance/circuit-breaker/reset",
        "/api/maintenance/purge",
        "/api/maintenance/incidents/clear",
    ):
        assert client.post(path).status_code == 401


def test_smc_reachable_and_causal():
    import pandas as pd
    from engine.backtest import SMCStrategy

    close = [100.0] * 25 + [110.0, 115.0, 80.0, 75.0]
    df = pd.DataFrame(
        {"close": close, "high": [p + 1 for p in close], "low": [p - 1 for p in close]}
    )
    strategy = SMCStrategy()
    result = strategy.generate_signals(df)
    assert 1 in result.values and -1 in result.values
    assert result.iloc[:27].equals(strategy.generate_signals(df.iloc[:27]))


def test_no_synthetic_chain_permission_from_paper_mode():
    import ast
    from pathlib import Path

    tree = ast.parse(Path("market/options.py").read_text(encoding="utf-8"))
    assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "allow_synthetic" for t in node.targets)
    ]
    assert len(assignments) == 1
    expression = ast.Expression(assignments[0].value)
    for broker, mode, expected in [
        ("fyers", "PAPER", False),
        ("", "", False),
        ("mock", "SIMULATE", False),
        ("mock", "DEMO", True),
    ]:
        assert (
            eval(
                compile(expression, "<provenance contract>", "eval"),
                {},
                dict(broker_key=broker, trading_mode=mode),
            )
            is expected
        )


def test_index_contagion_holds_without_live_broker_option_snapshot(monkeypatch):
    from engine.index_contagion import IndexContagionEngine

    plan = SimpleNamespace(
        invalidation_stop=24900.0,
        target_1=25200.0,
        target_2=25300.0,
        target_3=25400.0,
        rr_t1=2.0,
        is_asymmetry_viable=True,
        asymmetry_verdict="ACCEPTABLE",
        asymmetry_note="test plan",
        as_dict=lambda: {},
    )
    monkeypatch.setattr("engine.trade_plan.calculate_trade_plan", lambda **kwargs: plan)
    monkeypatch.setattr(
        "market.options.get_options_snapshot",
        lambda *args, **kwargs: (
            [],
            None,
            [],
            {
                "source": "SCRAPER_FALLBACK",
                "data_state": "DELAYED",
                "is_realtime": False,
                "is_market_open": True,
                "as_of": "2026-11-02T05:00:00+00:00",
            },
        ),
    )

    result = IndexContagionEngine()._create_contagion_alert(
        index_name="NIFTY",
        direction="BULLISH",
        spot=25000.0,
        vwap=24980.0,
        change_pct=0.3,
        sync_pct=80.0,
        leading=["HDFCBANK (+1.0%, RVOL 2.0x)"],
        now_iso="2026-11-02 10:00:00 IST",
    )
    assert result is None


@pytest.mark.parametrize(
    "environment,source,is_live",
    [("TEST", "REAL", True), ("LIVE", "SYNTHETIC", True), ("LIVE", "REAL", False)],
)
def test_production_telegram_rejects_unverified_evidence(monkeypatch, environment, source, is_live):
    from engine.auto_alert_engine import AutoAlertEngine

    monkeypatch.delenv("CHANAKYA_TESTING", raising=False)
    monkeypatch.setenv("DEPLOY_MODE", "desktop")
    alert = SimpleNamespace(
        environment=environment,
        metrics={"source": source},
        details={},
        is_live=is_live,
        alert_id="aa-review-20261031",
    )
    permitted, reason = AutoAlertEngine._eval_telegram_apex_gate(None, alert)
    assert not permitted
    assert "Unverified" in reason
