"""
market/http_pool.py
───────────────────
Centralized HTTP Connection Pool & Session Management.

Provides high-performance persistent HTTP connection pooling with keep-alive limits,
cookie-persisting session management for NSE endpoints, and deterministic teardown.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import httpx

logger = logging.getLogger("chanakya.http_pool")

_SHARED_CLIENT: Optional[httpx.Client] = None
_NSE_CLIENT: Optional[httpx.Client] = None
_CLIENT_LOCK = threading.Lock()
_NSE_LAST_INIT: float = 0.0
_NSE_COOKIE_TTL = 300.0  # 5 minutes cookie freshness

_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

_NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com",
}


def get_shared_client() -> httpx.Client:
    """
    Get or create the singleton shared HTTP connection pool.
    
    Reuses TCP/TLS connections with keep-alive, avoiding 150-300ms handshake overhead
    per request and preventing socket exhaustion.
    """
    global _SHARED_CLIENT
    if _SHARED_CLIENT is None or _SHARED_CLIENT.is_closed:
        with _CLIENT_LOCK:
            if _SHARED_CLIENT is None or _SHARED_CLIENT.is_closed:
                _SHARED_CLIENT = httpx.Client(
                    headers=_DEFAULT_HEADERS,
                    follow_redirects=True,
                    timeout=httpx.Timeout(10.0, connect=5.0),
                    limits=httpx.Limits(
                        max_keepalive_connections=20,
                        max_connections=50,
                        keepalive_expiry=30.0,
                    ),
                )
    return _SHARED_CLIENT


def get_nse_client() -> httpx.Client:
    """
    Get or create the singleton NSE client with cookie warming.
    
    Ensures that session cookies from nseindia.com are retained across requests,
    eliminating redundant homepage visits on every API call.
    """
    global _NSE_CLIENT, _NSE_LAST_INIT
    now = time.time()

    if _NSE_CLIENT is None or _NSE_CLIENT.is_closed:
        with _CLIENT_LOCK:
            if _NSE_CLIENT is None or _NSE_CLIENT.is_closed:
                _NSE_CLIENT = httpx.Client(
                    headers=_NSE_HEADERS,
                    follow_redirects=True,
                    timeout=httpx.Timeout(10.0, connect=5.0),
                    limits=httpx.Limits(
                        max_keepalive_connections=10,
                        max_connections=25,
                        keepalive_expiry=60.0,
                    ),
                )
                _NSE_LAST_INIT = 0.0

    # Refresh homepage cookies if older than TTL
    if now - _NSE_LAST_INIT > _NSE_COOKIE_TTL:
        with _CLIENT_LOCK:
            if now - _NSE_LAST_INIT > _NSE_COOKIE_TTL and _NSE_CLIENT and not _NSE_CLIENT.is_closed:
                try:
                    _NSE_CLIENT.get("https://www.nseindia.com", timeout=5.0)
                    _NSE_LAST_INIT = now
                except Exception as exc:
                    logger.debug("NSE cookie warm-up note: %s", exc)

    return _NSE_CLIENT


def close_http_pools() -> None:
    """Deterministically close all pooled HTTP clients and release socket connections."""
    global _SHARED_CLIENT, _NSE_CLIENT, _NSE_LAST_INIT
    with _CLIENT_LOCK:
        if _SHARED_CLIENT is not None:
            try:
                _SHARED_CLIENT.close()
            except Exception:
                pass
            _SHARED_CLIENT = None

        if _NSE_CLIENT is not None:
            try:
                _NSE_CLIENT.close()
            except Exception:
                pass
            _NSE_CLIENT = None
            _NSE_LAST_INIT = 0.0
