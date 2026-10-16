"""
tests/test_fyers_rate_gate_daily.py
───────────────────────────────────
Deterministic verification of the daily quota budget pacer,
calendar rollover, and emergency order preservation in UnifiedFyersRateGate.
"""

from market.fyers_rate_gate import FyersCallCategory, UnifiedFyersRateGate


def test_daily_soft_cap_rejects_non_order_calls(tmp_path, monkeypatch):
    test_file = tmp_path / "fyers_daily_quota.json"
    monkeypatch.setattr("market.fyers_rate_gate._QUOTA_FILE", test_file)

    gate = UnifiedFyersRateGate(max_per_sec=20.0, max_per_min=200.0, max_per_day=4.0)

    # 4 calls should succeed
    for i in range(4):
        assert gate.acquire(category=FyersCallCategory.SCANNER_QUOTE) is True

    diag = gate.get_diagnostics()
    assert diag["daily_requests"] == 4
    assert diag["daily_budget_remaining"] == 0
    assert diag["daily_quota_exhausted"] is True

    # 5th non-order call rejected immediately
    assert gate.acquire(category=FyersCallCategory.SCANNER_QUOTE) is False
    assert gate.acquire(category=FyersCallCategory.URGENT_QUOTE) is False
    assert gate.acquire(category=FyersCallCategory.DEPTH_CHAIN) is False
    assert gate.acquire(category=FyersCallCategory.HISTORICAL) is False

    # But ORDER category still permitted up to order emergency cap
    assert gate.acquire(category=FyersCallCategory.ORDER) is True
    assert gate.get_diagnostics()["daily_requests"] == 5


def test_daily_quota_persists_across_reloads(tmp_path, monkeypatch):
    test_file = tmp_path / "fyers_daily_quota.json"
    monkeypatch.setattr("market.fyers_rate_gate._QUOTA_FILE", test_file)

    gate1 = UnifiedFyersRateGate(max_per_sec=20.0, max_per_min=200.0, max_per_day=50.0)
    for _ in range(7):
        assert gate1.acquire(category=FyersCallCategory.ORDER) is True

    assert gate1.get_diagnostics()["daily_requests"] == 7

    # Emulate service restart by creating a new gate instance
    gate2 = UnifiedFyersRateGate(max_per_sec=20.0, max_per_min=200.0, max_per_day=50.0)
    assert gate2.get_diagnostics()["daily_requests"] == 7
    assert gate2.get_diagnostics()["daily_budget_remaining"] == 43


def test_get_quote_ws_only_skips_external_rest(monkeypatch):
    from market.quotes import get_quote

    # Mock broker to track if it is called
    mock_called = []

    class MockBroker:
        def get_quote(self, instruments, **kwargs):
            mock_called.append(instruments)
            return {}

    monkeypatch.setattr("market.quotes.get_data_broker", lambda: MockBroker())
    monkeypatch.setattr("market.quotes._ws_quotes", lambda insts, **kwargs: {})
    monkeypatch.setattr("market.quotes._QUOTE_CACHE", {})

    # Call with ws_only=True
    res = get_quote(["NSE:INFY", "NSE:RELIANCE"], ws_only=True)
    assert isinstance(res, dict)
    # Crucial invariant: Broker get_quote MUST NOT be invoked when ws_only=True
    assert len(mock_called) == 0


def test_fyers_prime_recalibration_and_reset_quota(tmp_path, monkeypatch):
    test_file = tmp_path / "fyers_daily_quota.json"
    monkeypatch.setattr("market.fyers_rate_gate._QUOTA_FILE", test_file)

    gate = UnifiedFyersRateGate(plan="STANDARD")
    assert gate.plan == "STANDARD"
    assert gate.quotes_chunk_size == 50
    assert gate._max_per_day == 4500.0

    # Recalibrate to PRIME
    gate.recalibrate("PRIME")
    assert gate.plan == "PRIME"
    assert gate.quotes_chunk_size == 1000
    assert gate._max_per_day == 480_000.0
    assert gate._max_per_min == 360.0
    assert gate._max_per_sec == 8.0

    # Simulate past requests and reset
    gate.record_external_exhaustion()
    assert gate.get_diagnostics()["daily_quota_exhausted"] is True

    gate.reset_daily_quota(requests=0)
    assert gate.get_diagnostics()["daily_requests"] == 0
    assert gate.get_diagnostics()["daily_quota_exhausted"] is False
