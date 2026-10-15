"""
Market data, calendar, feeds, quotes, and intelligence modules.
"""

# Ensure fyers_apiv3 WebSocket background threads are always daemon=True
import market.fyers_socket_patch  # noqa: F401

from market.calendar import (
    is_trading_holiday,
    get_holiday_reason,
    is_market_open,
    get_market_status,
    get_current_ist_session,
    get_trading_minutes_elapsed,
    get_adjusted_expiry_date,
    get_trading_days_elapsed,
)

__all__ = [
    "is_trading_holiday",
    "get_holiday_reason",
    "is_market_open",
    "get_market_status",
    "get_current_ist_session",
    "get_trading_minutes_elapsed",
    "get_adjusted_expiry_date",
    "get_trading_days_elapsed",
]
