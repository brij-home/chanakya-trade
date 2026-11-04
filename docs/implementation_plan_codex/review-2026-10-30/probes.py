"""Isolated review probes. All broker effects are replaced with fakes."""

import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

with tempfile.TemporaryDirectory(prefix="chanakya-review-") as review_dir:
    for key in ("TRADING_PLATFORM_HOME", "TRADING_PLATFORM_DATA"):
        os.environ[key] = review_dir
    os.environ.update(TRADING_MODE="PAPER", CHANAKYA_TESTING="1", KEYRING_DISABLE="1")
    import socket

    def no_network(*args, **kwargs):
        raise RuntimeError("Review probe blocks all external network connections")

    socket.socket.connect = no_network

    from engine.charges import calculate_transaction_charges
    from engine.alert_expiry import get_last_thursday_of_month
    from market.instruments import resolve_canonical_instrument
    from engine.pretrade import _gate_market_session, _gate_buying_power, _gate_lot_size
    from engine.detector_circuit_breaker import DetectorCircuitBreaker

    evidence = {}
    evidence["charges"] = {
        segment: float(calculate_transaction_charges(100, 1000, segment, "SELL").stt)
        for segment in ("FUTURES", "OPTIONS")
    }
    evidence["charges"]["expected_2026_futures_stt"] = 50.0
    evidence["charges"]["expected_2026_options_stt"] = 150.0
    evidence["october_monthly_calendar_fallback"] = str(get_last_thursday_of_month(2026, 10))
    inst = resolve_canonical_instrument("REVIEW_UNKNOWN_EQUITY_DOES_NOT_EXIST")
    evidence["unknown_equity"] = {"status": inst.status, "tradable": inst.is_tradable}
    from datetime import datetime
    from config.constants import IST

    with patch("engine.pretrade.datetime") as clock:
        clock.now.return_value = datetime(2026, 10, 30, 18, 0, tzinfo=IST)
        session_probes = {s: _gate_market_session(s).__dict__ for s in ("OPTIONS", "FUTURES", "EQ")}
    evidence["pretrade"] = {
        "Friday_1800_IST_session_gates": session_probes,
        "default_option_lot_accepts_one_unit": _gate_lot_size(1, "OPTIONS").passed,
        "OPT_100000_premium_20000_cash": _gate_buying_power(
            "BUY", 1000, 100, None, 20000, "OPT"
        ).__dict__,
    }
    cb = DetectorCircuitBreaker(ledger_file=Path(review_dir) / "probe_cb.json")
    evidence["unobserved_detector"] = cb.get_metrics("REVIEW").to_dict()
    cb.record_outcome("same-alert", "REVIEW", "REVIEW", "WIN", 2)
    cb.record_outcome("same-alert", "REVIEW", "REVIEW", "WIN", 2)
    evidence["duplicate_outcome_sample_count"] = cb.get_metrics("REVIEW").sample_count

    import numpy as np
    import pandas as pd
    from engine.backtest import SMCStrategy

    rng = np.random.default_rng(20261030)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 300)))
    frame = pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 100000,
        },
        index=pd.date_range("2025-01-01", periods=300),
    )
    signals = SMCStrategy().generate_signals(frame)
    evidence["SMC_valid_300_bar_signal_counts"] = {
        str(k): int(v) for k, v in signals.value_counts().items()
    }

    from engine.eod_rebalancer import audit_open_positions_for_physical_delivery

    delivery = audit_open_positions_for_physical_delivery(
        positions=[
            {
                "symbol": "RELIANCE",
                "net_quantity": 250,
                "strike": 100,
                "option_type": "CE",
                "lot_size": 250,
                "days_to_expiry": 0,
                "spot_price": 110,
            }
        ]
    )[0]
    evidence["physical_settlement_zero_DTE"] = {
        "input_days_to_expiry": 0,
        "reported_days_to_expiry": delivery.days_to_expiry,
        "reported_margin_rate_pct": delivery.required_margin_rate_pct,
        "reported_risk_level": delivery.risk_level,
    }

    import time
    from agent.multi_agent import MultiAgentAnalyzer

    class SlowLLM:
        def chat(self, **kwargs):
            time.sleep(0.15)
            return "fake local response"

    started = time.monotonic()
    fallback = MultiAgentAnalyzer._safe_chat(
        SimpleNamespace(llm=SlowLLM(), verbose=False), "local probe", "FALLBACK", timeout=0.005
    )
    evidence["LLM_timeout_fake_only"] = {
        "requested_timeout_seconds": 0.005,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "returned": fallback,
    }

    import sqlite3
    from engine.db_pool import SQLiteConnectionPool

    pool = SQLiteConnectionPool(str(Path(review_dir) / "atomic_probe.db"))
    with pool.acquire() as conn:
        conn.execute("CREATE TABLE probe (id INTEGER PRIMARY KEY)")
        try:
            conn.execute("INSERT INTO probe VALUES (1)")
            conn.execute("INSERT INTO probe VALUES (1)")
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
        evidence["pool_autocommit_first_write_survives_rollback"] = conn.execute(
            "SELECT COUNT(*) FROM probe"
        ).fetchone()[0]
    pool.close()

    import engine.order_lifecycle as lifecycle

    lifecycle._init_orders_db()
    lifecycle.set_ledger_cash_baseline("ACCOUNT_A", 100000)
    lifecycle.set_ledger_cash_baseline("ACCOUNT_B", 100000)
    with lifecycle._get_orders_db() as conn:
        conn.execute("""INSERT INTO orders_ledger
            (order_id,idempotency_key,symbol,side,quantity,price,order_type,product,status,mode,created_at,updated_at)
            VALUES ('REVIEW_ORDER','REVIEW_KEY','REVIEW_SYMBOL','BUY',100,100,'LIMIT','CNC','FILLED','EXECUTE','2026-10-30','2026-10-30')""")
        conn.commit()
    evidence["account_snapshots"] = {
        name: lifecycle.get_internal_ledger_snapshot(name) for name in ("ACCOUNT_A", "ACCOUNT_B")
    }

    class FakeBroker:
        def __init__(self):
            self.calls = []

        def get_orders(self):
            return []

        def get_positions(self):
            return [{"symbol": "REVIEW_FAKE_ONLY", "net_qty": 3}]

        def place_order(self, request):
            self.calls.append(request)
            return SimpleNamespace(status="REJECTED", order_id=None)

    fake = FakeBroker()
    with (
        patch("brokers.session.get_execution_broker", return_value=fake),
        patch("engine.paper.PaperBroker", return_value=SimpleNamespace()),
        patch.object(lifecycle, "set_emergency_lockout", return_value=0),
        patch("engine.security_audit.record_audit_event", return_value=None),
    ):
        result = lifecycle.emergency_flatten_all_positions(reason="ISOLATED REVIEW PROBE")
    evidence["emergency_flatten_mock_only"] = {
        "mode": result["mode"],
        "broker_place_order_calls": len(fake.calls),
        "fake_broker_response": "REJECTED",
        "reported_status": result["status"],
        "reported_flattened_count": result["flattened_positions_count"],
    }
    lifecycle.close_orders_db()
    from engine.security_audit import close_audit_db

    close_audit_db()
    import sys

    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(
            json.dumps(evidence, indent=2, default=str) + "\n", encoding="utf-8"
        )
    print(json.dumps(evidence, indent=2, default=str))
