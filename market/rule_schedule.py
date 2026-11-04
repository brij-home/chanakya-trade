"""Effective-dated exchange rules. Sources and regression fixtures are release contracts.

NSE FAOP/68685 (2025-06-23); BSE 20250617-11;
NSE CAS modalities (2026-08-12); SEBI 23843/2026 (effective 2026-12-07).
"""

from calendar import monthrange
from datetime import date, time, timedelta


def expiry_weekday(exchange: str, as_of: date) -> int:
    bse = exchange.upper() in ("BSE", "BFO")
    if as_of >= date(2025, 9, 1):
        return 3 if bse else 1
    if bse and as_of >= date(2025, 1, 4):
        return 1
    return 4 if bse else 3


def monthly_expiry(year: int, month: int, exchange: str = "NSE") -> date:
    """Calendar candidate only; callers apply exchange holidays or listed master."""
    last = date(year, month, monthrange(year, month)[1])
    return last - timedelta(days=(last.weekday() - expiry_weekday(exchange, last)) % 7)


def derivative_close(as_of: date, *, expiring_index: bool = False) -> time:
    if as_of >= date(2026, 12, 7):
        return time(15, 30) if expiring_index else time(15, 45)
    return time(15, 40) if as_of >= date(2026, 8, 3) else time(15, 30)


def cash_continuous_close(as_of: date, *, cas_eligible: bool) -> time:
    if cas_eligible and date(2026, 8, 3) <= as_of < date(2026, 12, 7):
        return time(15, 15)
    return time(15, 30)
