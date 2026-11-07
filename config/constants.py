"""
config/constants.py
───────────────────
Centralized constants for ChanakyaTrade.

Import from here instead of defining locally in each module.
Prevents duplication of IST timezone, market hours, and path constants
across the codebase (historically defined in 8+ separate files).
"""

from __future__ import annotations

import os

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

# ── Timezone ─────────────────────────────────────────────────────────────────

#: Indian Standard Time (UTC+5:30) offset
IST = timezone(timedelta(hours=5, minutes=30))

#: Indian Standard Time IANA ZoneInfo instance
IST_ZONE = ZoneInfo("Asia/Kolkata")


def now_ist() -> datetime:
    """Canonical truth timestamp in Indian Standard Time (IST, UTC+05:30)."""
    return datetime.now(IST)


# ── NSE/BSE Market Hours (HHMM integers for fast comparison) ──────────────────

#: Pre-open session start: 9:00 IST
PRE_OPEN_START_HHMM: int = 900

#: Regular session open: 9:15 IST
MARKET_OPEN_HHMM: int = 915

#: Regular session close: 15:30 IST
MARKET_CLOSE_HHMM: int = 1530

#: Post-close / after-market session end: 16:00 IST
AFTER_MARKET_CLOSE_HHMM: int = 1600

# ── MCX Commodity Market Hours ────────────────────────────────────────────────

#: MCX morning open: 9:00 IST
MCX_OPEN_HHMM: int = 900

#: MCX agri / early close: 17:00 IST
MCX_AGRI_CLOSE_HHMM: int = 1700

#: MCX non-agri / evening close: 23:30 IST
MCX_EVENING_CLOSE_HHMM: int = 2330

#: MCX crude oil / extended close: 23:55 IST
MCX_EXTENDED_CLOSE_HHMM: int = 2355

# ── Data Directory ────────────────────────────────────────────────────────────

#: Environment variable name for custom data directory
TRADING_PLATFORM_DATA_ENV: str = "TRADING_PLATFORM_DATA"

#: Default data directory name under user home
DEFAULT_DATA_DIR_NAME: str = ".trading_platform"

# ── F&O Lot Sizes (Official NSE/BSE October 2026 Master — SSOT from market.instruments) ─

NIFTY_LOT_SIZE: int = 65
BANKNIFTY_LOT_SIZE: int = 30
FINNIFTY_LOT_SIZE: int = 60
MIDCPNIFTY_LOT_SIZE: int = 120
SENSEX_LOT_SIZE: int = 20
BANKEX_LOT_SIZE: int = 30


# ── Session Focus & Workload Prioritization ────────────────────────────────────

#: Default operational focus mode during live trading sessions.
#: 'FNO_ONLY': Strict domestic F&O discovery; preserve existing-exposure monitoring.
#: 'FNO_PRIORITY': Legacy session-level prioritization (not a strict scope).
#: 'BALANCED': Standard multi-asset operation across all segments.
SESSION_FOCUS_MODE: str = "FNO_ONLY"

# ── Alert & Analysis TTLs ─────────────────────────────────────────────────────

#: Default analysis cache TTL in seconds (15 minutes)
ANALYSIS_CACHE_TTL_SECONDS: int = 900

#: Alert dedup/cooldown window in seconds
ALERT_DEDUP_TTL_SECONDS: int = 90

#: Delisted symbol blacklist TTL in seconds (6 hours)
DELISTED_SYMBOL_TTL_SECONDS: int = 6 * 3600

#: Chat session TTL in seconds (2 hours)
CHAT_SESSION_TTL_SECONDS: int = 2 * 3600

#: Max chat sessions in LRU store
CHAT_SESSION_MAX_SIZE: int = 50

# ── Broker OAuth Redirect URIs & SEBI Network Binding ─────────────────────────

#: Static IPv4 whitelisted with SEBI brokers (configurable via SEBI_WHITELISTED_IP)
DEFAULT_SEBI_WHITELISTED_IP: str = os.environ.get("SEBI_WHITELISTED_IP", "127.0.0.1")

#: Default FastAPI sidecar port
DEFAULT_SIDECAR_PORT: int = 8765

DEFAULT_BROKER_CALLBACK_URLS: dict[str, str] = {
    "fyers": f"http://127.0.0.1:{DEFAULT_SIDECAR_PORT}/fyers/callback",
    "groww": f"http://127.0.0.1:{DEFAULT_SIDECAR_PORT}/groww/callback",
    "upstox": f"http://127.0.0.1:{DEFAULT_SIDECAR_PORT}/upstox/callback",
    "mstock": f"http://{DEFAULT_SEBI_WHITELISTED_IP}:{DEFAULT_SIDECAR_PORT}/mstock/callback",
    "zerodha": f"http://127.0.0.1:{DEFAULT_SIDECAR_PORT}/zerodha/callback",
}


def validate_callback_url(url: str) -> str:
    """
    Validates that OAuth callback redirect URIs are safe:
    - Loopback hosts (127.0.0.1, localhost, ::1, testserver, testclient) may use HTTP.
    - All non-loopback addresses MUST use HTTPS.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    scheme = (parsed.scheme or "").lower()

    is_loopback = host in ("localhost", "127.0.0.1", "::1", "testserver", "testclient")
    if not is_loopback and host:
        try:
            import ipaddress

            is_loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = False

    if not is_loopback and scheme == "http":
        raise ValueError(
            f"Insecure OAuth callback: Non-loopback redirect URI '{url}' must use HTTPS."
        )
    return url


def get_broker_callback_url(broker_key: str) -> str:
    """
    Returns the authoritative OAuth callback redirect URI for the given broker.
    Resolves environment variable override (e.g. MSTOCK_REDIRECT_URL, OAUTH_CALLBACK_BASE_URL) first,
    falling back to canonical default.
    Enforces HTTPS on non-loopback endpoints.
    """
    k = broker_key.lower().strip()
    env_var = f"{k.upper()}_REDIRECT_URL"
    val = os.environ.get(env_var, "").strip()
    if not val:
        base_url = os.environ.get("OAUTH_CALLBACK_BASE_URL", "").strip().rstrip("/")
        if base_url:
            val = f"{base_url}/{k}/callback"
    if not val:
        val = DEFAULT_BROKER_CALLBACK_URLS.get(
            k, f"http://127.0.0.1:{DEFAULT_SIDECAR_PORT}/{k}/callback"
        )
    return validate_callback_url(val)


# ── Microstructure Risk & Volatility Floors ─────────────────────────────────

#: Minimum option premium stop loss points (tick noise buffer)
MIN_OPTION_PREMIUM_SL_PTS: float = 3.0

#: Minimum option premium stop loss percentage (10% floor)
MIN_OPTION_PREMIUM_SL_PCT: float = 0.10

#: Maximum adverse excursion drawdown percentage for statistical arbitrage / pair trading
DEFAULT_PAIR_MAX_ADVERSE_PCT: float = 5.0

#: Minimum relative volume for thematic sympathy follower qualification (institutional participation floor)
MIN_SYMPATHY_FOLLOWER_RVOL: float = 1.80
