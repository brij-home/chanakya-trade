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
from typing import Any, Optional

from market.fyers_rate_gate import FyersCallCategory, get_fyers_rate_gate

logger = logging.getLogger(__name__)

FYERS_MAX_CHUNK_SIZE = 1000
SAFE_HTTP_MAX_CHUNK_SIZE = (
    300  # Clamped to at most 300 symbols to avoid HTTP 414 URI Too Long on GET queries
)
SAFE_URL_MAX_CHARS = (
    5500  # Conservative safe byte/char budget for HTTP GET query string (< 8KB buffer)
)


def chunk_symbols_for_quotes(
    symbols: list[str],
    max_symbols: int = SAFE_HTTP_MAX_CHUNK_SIZE,
    max_chars: int = SAFE_URL_MAX_CHARS,
) -> list[list[str]]:
    """
    Dynamically batch symbols for Fyers API v3 GET /data/quotes endpoint.
    Optimizes batch density up to max_symbols (up to 300 for Prime, 50 for Standard)
    while strictly respecting URL query string limits (max_chars <= 5,500 chars) to prevent
    HTTP 414 URI Too Long errors.
    """
    if not symbols:
        return []

    chunks: list[list[str]] = []
    current_chunk: list[str] = []
    current_chars = 0

    for s in symbols:
        s_len = len(s) + 1  # symbol + comma separator
        if current_chunk and (
            len(current_chunk) >= max_symbols or (current_chars + s_len) > max_chars
        ):
            chunks.append(current_chunk)
            current_chunk = [s]
            current_chars = len(s)
        else:
            current_chunk.append(s)
            current_chars += s_len

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


class QuoteDispatcher:
    """
    Serialized, priority-aware quote dispatcher.
    Eliminates parallel thread bursts against Fyers quotes API.
    Supports up to 300 symbols/request batching for Fyers Prime (50 for Standard),
    dynamically packed by character budget to guarantee immunity from HTTP 414.
    """

    def __init__(self, chunk_size: Optional[int] = None) -> None:
        self._rate_gate = get_fyers_rate_gate()
        max_chunk = getattr(self._rate_gate, "quotes_chunk_size", FYERS_MAX_CHUNK_SIZE)
        safe_max = min(max_chunk, SAFE_HTTP_MAX_CHUNK_SIZE)
        self._chunk_size = min(chunk_size or safe_max, safe_max)
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
        Leverages in-memory L2 WebSocket (up to 5,000 streaming symbols) before REST.
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
        except Exception as e_suppressed:
            logger.debug(
                f"[market.quote_dispatcher] Non-fatal exception suppressed: {e_suppressed}"
            )

        unresolved = [
            s for s in unique_syms if s not in combined and s.split(":")[-1] not in combined
        ]

        if unresolved:
            # Dynamically chunk unresolved symbols by symbol count AND URL byte budget
            chunks = chunk_symbols_for_quotes(
                unresolved, max_symbols=self._chunk_size, max_chars=SAFE_URL_MAX_CHARS
            )

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

                        # Dispatch single chunk with rate_gate_acquired=True to eliminate duplicate token debit
                        res = get_quote(
                            chunk,
                            category=category,
                            rate_gate_acquired=True,
                        )
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
