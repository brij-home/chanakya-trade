"""
tests/test_single_flight_cache.py
─────────────────────────────────
Tests for SingleFlightCache: thundering-herd single-flight coalescing,
Stale-While-Revalidate (SWR) background refreshes, and LRU eviction.
"""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor


from market.single_flight_cache import SingleFlightCache


def test_single_flight_cache_basic_hits():
    cache = SingleFlightCache[int](soft_ttl=2.0, hard_ttl=5.0)
    calls = 0

    def fetcher() -> int:
        nonlocal calls
        calls += 1
        return 42

    # First call: miss
    res1 = cache.get_or_fetch_sync("k1", fetcher)
    assert res1 == 42
    assert calls == 1

    # Second call within soft_ttl: hit
    res2 = cache.get_or_fetch_sync("k1", fetcher)
    assert res2 == 42
    assert calls == 1

    st = cache.stats()
    assert st["hits"] == 1
    assert st["misses"] == 1


def test_single_flight_coalescing_sync_threads():
    cache = SingleFlightCache[str](soft_ttl=10.0, hard_ttl=20.0)
    fetch_count = 0

    def slow_fetcher() -> str:
        nonlocal fetch_count
        fetch_count += 1
        time.sleep(0.1)  # Simulate network latency
        return "expensive_result"

    # Launch 10 threads simultaneously for the same key
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [
            executor.submit(cache.get_or_fetch_sync, "stock_quote", slow_fetcher) for _ in range(10)
        ]
        results = [f.result() for f in futures]

    assert len(results) == 10
    assert all(r == "expensive_result" for r in results)
    # The expensive fetcher must only be executed ONCE despite 10 concurrent callers
    assert fetch_count == 1
    st = cache.stats()
    assert st["coalesced_waits"] == 9
    assert st["misses"] == 1


def test_single_flight_coalescing_async():
    async def _test():
        cache = SingleFlightCache[str](soft_ttl=10.0, hard_ttl=20.0)
        fetch_count = 0

        async def slow_coro() -> str:
            nonlocal fetch_count
            fetch_count += 1
            await asyncio.sleep(0.08)
            return "async_result"

        tasks = [cache.get_or_fetch_async("async_key", slow_coro) for _ in range(8)]
        results = await asyncio.gather(*tasks)

        assert len(results) == 8
        assert all(r == "async_result" for r in results)
        assert fetch_count == 1
        st = cache.stats()
        assert st["coalesced_waits"] == 7
        assert st["misses"] == 1

    asyncio.run(_test())


def test_stale_while_revalidate_sync():
    cache = SingleFlightCache[int](soft_ttl=0.05, hard_ttl=1.0)
    counter = 100

    def fetcher() -> int:
        nonlocal counter
        val = counter
        counter += 1
        return val

    # 1. Initial fetch -> 100
    v1 = cache.get_or_fetch_sync("item", fetcher)
    assert v1 == 100

    # 2. Wait 0.08s: past soft_ttl (0.05s) but within hard_ttl (1.0s)
    time.sleep(0.08)

    # Calling get_or_fetch_sync returns stale 100 instantly, but kicks off background refresh to fetch 101
    v2 = cache.get_or_fetch_sync("item", fetcher)
    assert v2 == 100
    st = cache.stats()
    assert st["swr_hits"] == 1

    # Give background thread a moment to finish revalidation
    time.sleep(0.05)

    # Next call returns updated revalidated value 101
    v3 = cache.get_or_fetch_sync("item", fetcher)
    assert v3 == 101


def test_lru_eviction():
    cache = SingleFlightCache[int](soft_ttl=10.0, hard_ttl=20.0, max_size=3)
    for i in range(5):
        cache.put(f"key_{i}", i)

    # Max size is 3 -> key_0 and key_1 should have been evicted
    assert cache.get("key_0") is None
    assert cache.get("key_1") is None
    assert cache.get("key_2") == 2
    assert cache.get("key_3") == 3
    assert cache.get("key_4") == 4
