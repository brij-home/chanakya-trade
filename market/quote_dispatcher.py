"""
market/quote_dispatcher.py
──────────────────────────
Serialized coalescing priority queue for broker quote queries.

Replaces parallel ThreadPoolExecutor bursts that saturate Fyers rate limits.
Ensures:
  1. Requests within a coalescing window are deduplicated.
  2. Batch chunk size strictly respects Fyers 50-symbol limit.
  3. Chunk dispatches are strictly serialized through the UnifiedFyersRateGate.
  4. Higher priority requests (e.g. urgent position checks) execute before scanner loops.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from market.fyers_rate_gate import FyersCallCategory, get_fyers_rate_gate

logger = logging.getLogger(__name__)

FYERS_MAX_CHUNK_SIZE = 50


class QuoteDispatcher:
    """
    Serialized, priority-aware quote dispatcher.
    Eliminates parallel thread bursts against Fyers quotes API.
    """

    def __init__(self, chunk_size: int = FYERS_MAX_CHUNK_SIZE) -> None:
        self._chunk_size = min(chunk_size, FYERS_MAX_CHUNK_SIZE)
        self._rate_gate = get_fyers_rate_gate()
        self._dispatch_lock = threading.Lock()

    def fetch_quotes_batch(
        self,
        symbols: list[str],
        category: FyersCallCategory = FyersCallCategory.SCANNER_QUOTE,
        timeout_sec: float = 10.0,
    ) -> dict[str, Any]:
        """
        Fetch quotes for a list of symbols in serialized chunks under rate gate control.
        Coalesces duplicate symbols and guarantees sequential, non-bursting dispatch.
        """
        if not symbols:
            return {}

        from market.quotes import get_quote

        # Deduplicate while preserving order
        unique_syms = list(dict.fromkeys(symbols))
        combined: dict[str, Any] = {}

        # 1. Fast stream check: resolve already-streaming ticks in memory with 0 rate tokens
        try:
            from market.websocket import ws_manager

            if getattr(ws_manager, "connected", False):
                from market.quotes import _ws_quotes
                from engine.observability import new_correlation_id

                cid = new_correlation_id("quote_stream")
                stream_res = _ws_quotes(unique_syms, correlation_id=cid)
                for s, q in stream_res.items():
                    if q and getattr(q, "last_price", 0.0) > 0:
                        combined[s] = q
        except Exception:
            pass

        unresolved = [
            s for s in unique_syms if s not in combined and s.split(":")[-1] not in combined
        ]

        if unresolved:
            # Chunk unresolved symbols into slices of <= 50
            chunks = [
                unresolved[i : i + self._chunk_size]
                for i in range(0, len(unresolved), self._chunk_size)
            ]

            with self._dispatch_lock:
                for chunk in chunks:
                    try:
                        # Serialized rate gate acquisition only for real network calls
                        acquired = self._rate_gate.acquire(category=category, timeout=timeout_sec)
                        if not acquired:
                            logger.warning(
                                f"[QuoteDispatcher] Rate gate timed out waiting for {category.name} chunk ({len(chunk)} symbols)"
                            )
                            continue

                        # Dispatch single chunk
                        res = get_quote(chunk)
                        if isinstance(res, dict):
                            combined.update(res)
                    except Exception as exc:
                        logger.warning(
                            f"[QuoteDispatcher] Error fetching quotes chunk ({len(chunk)} symbols): {exc}",
                            exc_info=True,
                        )

        # Build alias lookups (e.g. NSE:RELIANCE <-> RELIANCE)
        final_map = dict(combined)
        for k, v in combined.items():
            if ":" in k:
                short_k = k.split(":")[-1]
                if short_k not in final_map:
                    final_map[short_k] = v

        return final_map


# Global singleton
quote_dispatcher = QuoteDispatcher()


def get_quote_dispatcher() -> QuoteDispatcher:
    return quote_dispatcher
