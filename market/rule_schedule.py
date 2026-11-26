"""Effective-dated exchange rules. Sources and regression fixtures are release contracts.

NSE FAOP/68685 (2025-06-23); BSE 20250617-11;
NSE CAS modalities (2026-08-12); SEBI 23843/2026 (effective 2026-12-07).
"""

from calendar import monthrange
from datetime import date, datetime, time, timedelta
from typing import Optional


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


def intraday_entry_cutoff(
    as_of: date,
    *,
    is_derivative: bool = True,
    expiring_index: bool = False,
) -> time:
    """
    Canonical intraday entry cutoff (15m runway before active segment close).
    Before Dec 7, 2026 (or for cash / expiring-index 0DTE), closes at 15:30 -> 15:15 cutoff.
    From Dec 7, 2026 onwards on non-expiring derivatives (15:45 close) -> 15:30 cutoff.
    """
    if not is_derivative:
        close_t = cash_continuous_close(as_of, cas_eligible=False)
    else:
        close_t = derivative_close(as_of, expiring_index=expiring_index)
    if close_t >= time(15, 45):
        return time(15, 30)
    return time(15, 15)


def intraday_squareoff_cutoff(
    as_of: date,
    *,
    is_derivative: bool = True,
    expiring_index: bool = False,
) -> time:
    """Canonical intraday MIS / EOD sweep square-off cutoff (15m prior to close)."""
    return intraday_entry_cutoff(
        as_of,
        is_derivative=is_derivative,
        expiring_index=expiring_index,
    )


def is_cas_window(ref_dt: datetime) -> bool:
    """True when ref_dt falls inside NSE/BSE Closing Auction Session (15:30-15:40 IST from 2026-12-07)."""
    d = ref_dt.date()
    t = ref_dt.time()
    if d >= date(2026, 12, 7):
        return time(15, 30) <= t < time(15, 40)
    return time(15, 15) <= t < time(15, 25)


def is_cas_derivative_dispersion_window(ref_dt: datetime) -> bool:
    """
    True during post-Dec 7, 2026 CAS overlap/post-cash derivative tail (15:25-15:45 IST),
    when cash equities enter CAS close (15:30-15:40) while non-expiring derivatives continue trading until 15:45.
    """
    d = ref_dt.date()
    t = ref_dt.time()
    if d >= date(2026, 12, 7):
        return time(15, 25) <= t <= time(15, 45)
    return False


def closing_vwap_window(ref_dt: datetime, *, is_expiry: bool = False) -> bool:
    """True during expiry closing 30-min VWAP determination window (15:00-15:30 IST)."""
    if not is_expiry:
        return False
    t = ref_dt.time()
    return time(15, 0) <= t <= time(15, 30)


def effective_lot_size(
    symbol: str,
    expiry_date: Optional[date] = None,
    default_lot: int = 1,
) -> int:
    """Effective-dated contract lot size transitions (e.g. BSE Notice 20260930-58: SENSEX 20 -> 25)."""
    clean = (symbol or "").upper().split(":", 1)[-1].strip()
    if clean in ("SENSEX", "BSESN", "^BSESN", "BSE SENSEX"):
        if expiry_date is not None and expiry_date >= date(2027, 1, 25):
            return 25
        return 20
    return int(default_lot or 1)


def is_cas_order_transition_active(as_of: date) -> bool:
    """SEBI Oct 15, 2026 Phase 2 CAS Limit/Iceberg CTS-to-CAS carry-over rules go live 2027-02-08."""
    return as_of >= date(2027, 2, 8)
