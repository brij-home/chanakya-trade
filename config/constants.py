"""
config/constants.py
───────────────────
Centralized constants for ChanakyaTrade.

Import from here instead of defining locally in each module.
Prevents duplication of IST timezone, market hours, and path constants
across the codebase (historically defined in 8+ separate files).
"""

from __future__ import annotations

from datetime import timezone, timedelta

# ── Timezone ─────────────────────────────────────────────────────────────────

#: Indian Standard Time (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

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

# ── F&O Lot Sizes (canonical as of Aug 2026 — check SEBI circular on changes) ─

NIFTY_LOT_SIZE: int = 65
BANKNIFTY_LOT_SIZE: int = 15
FINNIFTY_LOT_SIZE: int = 25
MIDCPNIFTY_LOT_SIZE: int = 50
SENSEX_LOT_SIZE: int = 10
BANKEX_LOT_SIZE: int = 15

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
