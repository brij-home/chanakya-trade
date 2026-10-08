"""
tests/test_vwap_session_cache.py
────────────────────────────────
Unit tests for VwapSessionCache disk persistence, reload, and single-flight execution.
"""

import tempfile
import time
import threading
from pathlib import Path
from unittest.mock import patch

from market.vwap_session_cache import VwapSessionCache


def test_vwap_cache_memory_and_disk_roundtrip():
    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch("market.vwap_session_cache._get_cache_dir", return_value=Path(tmp_dir)):
            cache = VwapSessionCache(ttl_seconds=60.0)
            assert cache.get("NIFTY") is None

            # Put VWAP
            cache.put("NIFTY", 24850.50)
            assert cache.get("NIFTY") == 24850.50

            # Simulate service restart: instantiate fresh cache pointing to same directory
            restarted_cache = VwapSessionCache(ttl_seconds=60.0)
            # Must restore instantly from disk
            assert restarted_cache.get("NIFTY") == 24850.50


def test_vwap_single_flight_deduplication():
    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch("market.vwap_session_cache._get_cache_dir", return_value=Path(tmp_dir)):
            cache = VwapSessionCache(ttl_seconds=60.0)
            call_count = 0
            compute_lock = threading.Lock()

            def slow_compute(sym, exchange="NSE"):
                nonlocal call_count
                with compute_lock:
                    call_count += 1
                time.sleep(0.1)  # Simulate network latency
                return 52300.0

            results = []

            def worker():
                val = cache.get_or_compute("BANKNIFTY", slow_compute)
                results.append(val)

            threads = [threading.Thread(target=worker) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=2.0)

            # All 5 threads must obtain the exact same calculated VWAP
            assert len(results) == 5
            assert all(r == 52300.0 for r in results)
            # Single-flight deduplication must ensure compute was only executed ONCE!
            assert call_count == 1
