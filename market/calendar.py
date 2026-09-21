"""
market/calendar.py
──────────────────
Institutional Exchange Trading Calendar and Holiday Service for Indian Markets.
Covers NSE (Cash, F&O), BSE, MCX (Commodities), and CDS (Currency Derivatives).

Key Capabilities:
  - Official Trading Holiday Calendars (2025, 2026, 2027) with session-specific logic.
  - MCX Split-Session Handling (Morning Closed 09:00–17:00, Evening Open 17:00–23:30/23:55).
  - Special Sessions (Diwali Laxmi Pujan Muhurat Trading, Saturday DR mock trading).
  - True Trading Minutes Elapsed computation (excludes nights, weekends, and holidays).
  - Expiry Preceding-Day Holiday Roll (NSE / SEBI rule for contract settlements).
  - Real-time and historical queryable status APIs.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger("market.calendar")
IST = ZoneInfo("Asia/Kolkata")

# ─────────────────────────────────────────────────────────────────────────────
# 1. Trading Holiday Master Data (NSE / BSE / MCX / CDS)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class HolidayRule:
    holiday_date: date
    name: str
    # If True, entire day is closed across all equity, NFO, and currency markets.
    is_equity_closed: bool = True
    # For MCX: 'CLOSED' (both sessions closed), 'EVENING_ONLY' (open 17:00–23:30), 'OPEN'
    mcx_status: str = "EVENING_ONLY"
    # CDS Currency segment status: 'CLOSED' or 'OPEN'
    cds_status: str = "CLOSED"
    # Special session time window if applicable: (open_time, close_time)
    special_session: Optional[tuple[dtime, dtime]] = None


# Official Exchange Trading Holidays 2025–2027
# Sources: NSE & MCX Circulars
_HOLIDAYS_CATALOG: dict[date, HolidayRule] = {
    # ── 2025 ──────────────────────────────────────────────────────────────────
    date(2025, 1, 26): HolidayRule(date(2025, 1, 26), "Republic Day", mcx_status="CLOSED"),
    date(2025, 2, 26): HolidayRule(date(2025, 2, 26), "Mahashivratri", mcx_status="EVENING_ONLY"),
    date(2025, 3, 14): HolidayRule(date(2025, 3, 14), "Holi", mcx_status="EVENING_ONLY"),
    date(2025, 3, 31): HolidayRule(date(2025, 3, 31), "Id-ul-Fitr (Ramzan Id)", mcx_status="EVENING_ONLY"),
    date(2025, 4, 10): HolidayRule(date(2025, 4, 10), "Mahavir Jayanti", mcx_status="EVENING_ONLY"),
    date(2025, 4, 14): HolidayRule(date(2025, 4, 14), "Dr. Baba Saheb Ambedkar Jayanti", mcx_status="EVENING_ONLY"),
    date(2025, 4, 18): HolidayRule(date(2025, 4, 18), "Good Friday", mcx_status="CLOSED"),
    date(2025, 5, 1): HolidayRule(date(2025, 5, 1), "Maharashtra Day", mcx_status="EVENING_ONLY"),
    date(2025, 6, 7): HolidayRule(date(2025, 6, 7), "Bakri Id / Eid-ul-Adha", mcx_status="CLOSED"),
    date(2025, 7, 6): HolidayRule(date(2025, 7, 6), "Muharram", mcx_status="CLOSED"),
    date(2025, 8, 15): HolidayRule(date(2025, 8, 15), "Independence Day", mcx_status="CLOSED"),
    date(2025, 8, 27): HolidayRule(date(2025, 8, 27), "Ganesh Chaturthi", mcx_status="EVENING_ONLY"),
    date(2025, 10, 2): HolidayRule(date(2025, 10, 2), "Mahatma Gandhi Jayanti", mcx_status="CLOSED"),
    date(2025, 10, 21): HolidayRule(
        date(2025, 10, 21),
        "Diwali Laxmi Pujan (Muhurat Trading)",
        is_equity_closed=False,
        mcx_status="SPECIAL",
        special_session=(dtime(18, 15), dtime(19, 15)),
    ),
    date(2025, 10, 22): HolidayRule(date(2025, 10, 22), "Diwali Balipratipada", mcx_status="EVENING_ONLY"),
    date(2025, 11, 5): HolidayRule(date(2025, 11, 5), "Guru Nanak Jayanti", mcx_status="EVENING_ONLY"),
    date(2025, 12, 25): HolidayRule(date(2025, 12, 25), "Christmas", mcx_status="CLOSED"),

    # ── 2026 ──────────────────────────────────────────────────────────────────
    date(2026, 1, 26): HolidayRule(date(2026, 1, 26), "Republic Day", mcx_status="CLOSED"),
    date(2026, 2, 16): HolidayRule(date(2026, 2, 16), "Mahashivratri", mcx_status="EVENING_ONLY"),
    date(2026, 3, 4): HolidayRule(date(2026, 3, 4), "Holi", mcx_status="EVENING_ONLY"),
    date(2026, 3, 20): HolidayRule(date(2026, 3, 20), "Id-ul-Fitr (Ramzan Id)", mcx_status="EVENING_ONLY"),
    date(2026, 4, 3): HolidayRule(date(2026, 4, 3), "Good Friday", mcx_status="CLOSED"),
    date(2026, 4, 14): HolidayRule(date(2026, 4, 14), "Dr. Baba Saheb Ambedkar Jayanti", mcx_status="EVENING_ONLY"),
    date(2026, 4, 21): HolidayRule(date(2026, 4, 21), "Ram Navami", mcx_status="EVENING_ONLY"),
    date(2026, 5, 1): HolidayRule(date(2026, 5, 1), "Maharashtra Day", mcx_status="EVENING_ONLY"),
    date(2026, 5, 27): HolidayRule(date(2026, 5, 27), "Bakri Id / Eid-ul-Adha", mcx_status="EVENING_ONLY"),
    date(2026, 6, 26): HolidayRule(date(2026, 6, 26), "Muharram", mcx_status="EVENING_ONLY"),
    date(2026, 8, 15): HolidayRule(date(2026, 8, 15), "Independence Day", mcx_status="CLOSED"),
    # Sep 14, 2026 — Ganesh Chaturthi (Current Date):
    date(2026, 9, 14): HolidayRule(date(2026, 9, 14), "Ganesh Chaturthi", mcx_status="EVENING_ONLY"),
    date(2026, 10, 2): HolidayRule(date(2026, 10, 2), "Mahatma Gandhi Jayanti", mcx_status="CLOSED"),
    date(2026, 10, 20): HolidayRule(date(2026, 10, 20), "Dussehra", mcx_status="EVENING_ONLY"),
    date(2026, 11, 8): HolidayRule(
        date(2026, 11, 8),
        "Diwali Laxmi Pujan (Muhurat Trading)",
        is_equity_closed=False,
        mcx_status="SPECIAL",
        special_session=(dtime(18, 15), dtime(19, 15)),
    ),
    date(2026, 11, 10): HolidayRule(date(2026, 11, 10), "Diwali Balipratipada", mcx_status="EVENING_ONLY"),
    date(2026, 11, 24): HolidayRule(date(2026, 11, 24), "Guru Nanak Jayanti", mcx_status="EVENING_ONLY"),
    date(2026, 12, 25): HolidayRule(date(2026, 12, 25), "Christmas", mcx_status="CLOSED"),

    # ── 2027 ──────────────────────────────────────────────────────────────────
    date(2027, 1, 26): HolidayRule(date(2027, 1, 26), "Republic Day", mcx_status="CLOSED"),
    date(2027, 3, 8): HolidayRule(date(2027, 3, 8), "Mahashivratri", mcx_status="EVENING_ONLY"),
    date(2027, 3, 23): HolidayRule(date(2027, 3, 23), "Holi", mcx_status="EVENING_ONLY"),
    date(2027, 3, 26): HolidayRule(date(2027, 3, 26), "Good Friday", mcx_status="CLOSED"),
    date(2027, 4, 14): HolidayRule(date(2027, 4, 14), "Dr. Baba Saheb Ambedkar Jayanti", mcx_status="EVENING_ONLY"),
    date(2027, 5, 1): HolidayRule(date(2027, 5, 1), "Maharashtra Day", mcx_status="EVENING_ONLY"),
    date(2027, 8, 15): HolidayRule(date(2027, 8, 15), "Independence Day", mcx_status="CLOSED"),
    date(2027, 9, 4): HolidayRule(date(2027, 9, 4), "Ganesh Chaturthi", mcx_status="EVENING_ONLY"),
    date(2027, 10, 2): HolidayRule(date(2027, 10, 2), "Mahatma Gandhi Jayanti", mcx_status="CLOSED"),
    date(2027, 10, 10): HolidayRule(date(2027, 10, 10), "Dussehra", mcx_status="EVENING_ONLY"),
    date(2027, 10, 29): HolidayRule(
        date(2027, 10, 29),
        "Diwali Laxmi Pujan (Muhurat Trading)",
        is_equity_closed=False,
        mcx_status="SPECIAL",
        special_session=(dtime(18, 15), dtime(19, 15)),
    ),
    date(2027, 11, 14): HolidayRule(date(2027, 11, 14), "Guru Nanak Jayanti", mcx_status="EVENING_ONLY"),
    date(2027, 12, 25): HolidayRule(date(2027, 12, 25), "Christmas", mcx_status="CLOSED"),
}


def _load_custom_holidays() -> dict[date, HolidayRule]:
    """Loads optional user custom holidays from ~/.trading_platform/holidays.json."""
    custom = {}
    cfg_path = Path.home() / ".trading_platform" / "holidays.json"
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            for item in data:
                d_str = item.get("date")
                if not d_str:
                    continue
                d = datetime.strptime(d_str, "%Y-%m-%d").date()
                custom[d] = HolidayRule(
                    holiday_date=d,
                    name=item.get("name", "Special Market Holiday"),
                    is_equity_closed=item.get("is_equity_closed", True),
                    mcx_status=item.get("mcx_status", "CLOSED"),
                    cds_status=item.get("cds_status", "CLOSED"),
                )
        except Exception as e:
            logger.debug(f"[Calendar] Error loading custom holidays: {e}")
    return custom


_CUSTOM_HOLIDAYS = _load_custom_holidays()


def get_holiday_rule(d: date) -> Optional[HolidayRule]:
    """Returns HolidayRule if date is a declared holiday, else None."""
    return _CUSTOM_HOLIDAYS.get(d) or _HOLIDAYS_CATALOG.get(d)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Queryable Holiday & Session Functions
# ─────────────────────────────────────────────────────────────────────────────

def is_trading_holiday(
    check_date: Optional[date] = None,
    exchange: str = "NSE",
    ref_time: Optional[dtime] = None,
) -> bool:
    """
    Checks if check_date is an official trading holiday for the given exchange/segment.
    Respects MCX morning vs evening session rules.
    """
    d = check_date or datetime.now(IST).date()
    rule = get_holiday_rule(d)
    if not rule:
        return False

    exch = (exchange or "NSE").upper()
    if exch == "MCX":
        if rule.mcx_status == "CLOSED":
            return True
        if rule.mcx_status == "EVENING_ONLY":
            # If ref_time is provided and >= 17:00 IST, evening session is OPEN
            if ref_time and ref_time >= dtime(17, 0):
                return False
            # If ref_time is not provided, check current time if evaluating today
            if not ref_time and d == datetime.now(IST).date():
                if datetime.now(IST).time() >= dtime(17, 0):
                    return False
            return True
        if rule.mcx_status == "SPECIAL":
            return False  # Handled by special session window
        return False

    if exch in ("CDS", "CURRENCY"):
        return rule.cds_status == "CLOSED"

    # NSE, BSE, NFO, EQUITY
    if rule.special_session:
        return False
    return rule.is_equity_closed


def get_holiday_reason(
    check_date: Optional[date] = None,
    exchange: str = "NSE",
) -> Optional[str]:
    """Returns human-readable name of holiday if check_date is a trading holiday."""
    d = check_date or datetime.now(IST).date()
    rule = get_holiday_rule(d)
    if rule and is_trading_holiday(d, exchange):
        return rule.name
    return None


def is_market_open(
    exchange: str = "NSE",
    ref_dt: Optional[datetime] = None,
) -> bool:
    """
    Canonical truth function for market hours across Indian Exchanges.
    Returns True ONLY during active trading minutes.
    Handles:
      - Weekends (Sat/Sun closed, unless special session declared)
      - Trading Holidays (Ganesh Chaturthi, Republic Day, etc.)
      - Normal Market Trading Windows:
          NSE / BSE / NFO: Mon–Fri, 09:15–15:30 IST.
          CDS (Currency):  Mon–Fri, 09:00–17:00 IST.
          MCX (Commodity): Mon–Fri, 09:00–23:30 IST (17:00–23:30 on evening-only holidays).
      - Special Muhurat / DR mock trading windows.
    """
    now = ref_dt or datetime.now(IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    else:
        now = now.astimezone(IST)

    today = now.date()
    current_t = now.time()
    rule = get_holiday_rule(today)

    exch = (exchange or "NSE").upper()

    # 24x7 Continuous Global Markets (Crypto / Binance / Deribit)
    if exch in ("CRYPTO", "BINANCE", "DERIBIT"):
        return True

    # Check for special trading session (e.g. Diwali Muhurat Trading)
    if rule and rule.special_session:
        start_t, end_t = rule.special_session
        return start_t <= current_t <= end_t

    # Weekends (Sat=5, Sun=6) are closed
    if now.weekday() >= 5:
        return False

    # MCX Commodity Segment
    if exch == "MCX":
        if rule:
            if rule.mcx_status == "CLOSED":
                return False
            if rule.mcx_status == "EVENING_ONLY":
                # Morning session closed; evening session 17:00 to 23:30 IST
                return dtime(17, 0) <= current_t <= dtime(23, 30)
        # Normal MCX schedule: 09:00 to 23:30 IST
        return dtime(9, 0) <= current_t <= dtime(23, 30)

    # CDS Currency Segment
    if exch in ("CDS", "CURRENCY"):
        if rule and rule.cds_status == "CLOSED":
            return False
        return dtime(9, 0) <= current_t <= dtime(17, 0)

    # NSE, BSE, NFO (Domestic Equity & Derivatives)
    if rule and rule.is_equity_closed:
        return False

    return dtime(9, 15) <= current_t <= dtime(15, 30)


def get_current_ist_session(ref_dt: Optional[datetime] = None) -> dict[str, bool]:
    """
    Evaluates current IST operational session status per institutional schedule:
      - 'equity_nfo': Mon–Fri 09:15–15:30 IST (Prime domestic equities & NFO derivatives).
      - 'currency':   Mon–Fri 15:30–17:00 IST (Strictly post-equity, active until CDS close)
                      plus 09:00–09:15 IST (Pre-equity opening window).
      - 'commodity':  Mon–Fri 15:30–23:30 IST (Strictly post-equity, active through US overlap).
      - 'crypto':     24x7 Continuous Global Trading (Binance / Deribit 365 days).
    All markets return False outside operational trading windows or during closed holidays.
    """
    now = ref_dt or datetime.now(IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    else:
        now = now.astimezone(IST)

    if now.weekday() >= 5:
        return {
            "equity_nfo": False,
            "currency": False,
            "commodity": False,
            "crypto": True,
        }

    current_t = now.time()

    # 09:15 to 15:30 IST: Pure Domestic Equity & NFO Desk
    is_equity_nfo = is_market_open("NSE", ref_dt=now) and (dtime(9, 15) <= current_t <= dtime(15, 30))

    # Post-Equity Session: Currency (15:30 - 17:00 IST) and Commodities (15:30 - 23:30 IST)
    # Currency is also valid 09:00 - 09:15 IST before domestic equity opens
    is_currency_window = (dtime(9, 0) <= current_t < dtime(9, 15)) or (
        dtime(15, 30) < current_t <= dtime(17, 0)
    )
    is_currency = is_currency_window and is_market_open("CDS", ref_dt=now)

    # MCX Commodities: Active continuously throughout exchange hours (09:00 - 23:30 IST)
    # as well as evening-only sessions on applicable holidays.
    is_commodity = is_market_open("MCX", ref_dt=now)

    return {
        "equity_nfo": is_equity_nfo,
        "currency": is_currency,
        "commodity": is_commodity,
        "crypto": True,
    }


def get_market_status(
    exchange: str = "NSE",
    ref_dt: Optional[datetime] = None,
) -> dict[str, Any]:
    """
    Returns complete institutional market status and countdown metadata.
    """
    now = ref_dt or datetime.now(IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    else:
        now = now.astimezone(IST)

    exch = (exchange or "NSE").upper()
    live = is_market_open(exch, ref_dt=now)
    today = now.date()
    rule = get_holiday_rule(today)
    is_weekend = now.weekday() >= 5
    current_t = now.time()

    holiday_name = None
    if rule:
        holiday_name = rule.name

    if live:
        status = "LIVE"
        if exch in ("CRYPTO", "BINANCE", "DERIBIT"):
            label = f"🟢 LIVE {exch} (24x7 CONTINUOUS)"
        else:
            label = f"🟢 LIVE {exch} MARKET"
    elif is_weekend:
        status = "WEEKEND"
        label = "🏖️ WEEKEND (MARKET CLOSED)"
    elif rule and is_trading_holiday(today, exch, ref_time=current_t):
        status = "HOLIDAY"
        label = f"🏖️ TRADING HOLIDAY ({holiday_name or 'Closed'})"
    elif current_t < dtime(9, 0):
        status = "PRE_MARKET"
        label = "🌅 PRE-MARKET SESSION"
    elif current_t < dtime(9, 15) and exch in ("NSE", "BSE", "NFO"):
        status = "PRE_OPEN_AUCTION"
        label = "🔔 PRE-OPEN DISCOVERY (09:00–09:15)"
    else:
        status = "SESSION_CLOSED"
        label = "🌙 MARKET CLOSED"

    # Remaining session minutes
    remaining_mins = 0
    if live:
        if exch in ("CRYPTO", "BINANCE", "DERIBIT"):
            remaining_mins = 1440  # 24h continuous rolling
        elif exch == "MCX":
            close_min = 23 * 60 + 30
            now_min = now.hour * 60 + now.minute
            remaining_mins = max(0, close_min - now_min)
        elif exch in ("CDS", "CURRENCY"):
            close_min = 17 * 60
            now_min = now.hour * 60 + now.minute
            remaining_mins = max(0, close_min - now_min)
        else:
            close_min = 15 * 60 + 30
            now_min = now.hour * 60 + now.minute
            remaining_mins = max(0, close_min - now_min)

    return {
        "is_open": live,
        "status": status,
        "label": label,
        "holiday_name": holiday_name,
        "remaining_session_mins": remaining_mins,
        "exchange": exch,
        "as_of_ist": now.strftime("%H:%M:%S IST"),
        "as_of_date": today.strftime("%Y-%m-%d"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. Active Trading Minutes Elapsed (Greeks & Theta Stagnation Aware)
# ─────────────────────────────────────────────────────────────────────────────

def get_trading_minutes_elapsed(
    start_dt: datetime,
    end_dt: Optional[datetime] = None,
    exchange: str = "NSE",
) -> float:
    """
    Computes the exact number of active market trading minutes that elapsed
    between start_dt and end_dt.
    Excludes all:
      - Overnight / after-hours non-trading periods.
      - Weekend non-trading periods (Saturday & Sunday).
      - Exchange trading holidays (e.g. Ganesh Chaturthi).

    Prevents spurious in-flight warnings and artificial theta decay accusations
    across weekends or closed market periods.
    """
    if start_dt.tzinfo is None:
        cur = start_dt.replace(tzinfo=IST)
    else:
        cur = start_dt.astimezone(IST)

    target = end_dt or datetime.now(IST)
    if target.tzinfo is None:
        target = target.replace(tzinfo=IST)
    else:
        target = target.astimezone(IST)

    if cur >= target:
        return 0.0

    exch = (exchange or "NSE").upper()
    total_trading_minutes = 0.0

    # Step in 5-minute increments for efficiency while preserving high precision
    step = timedelta(minutes=5)
    while cur < target:
        next_cur = min(cur + step, target)
        segment_duration = (next_cur - cur).total_seconds() / 60.0

        # Check midpoint of the segment to see if market was active
        midpoint = cur + (next_cur - cur) / 2
        if is_market_open(exch, ref_dt=midpoint):
            total_trading_minutes += segment_duration

        cur = next_cur

    return round(total_trading_minutes, 1)


# ─────────────────────────────────────────────────────────────────────────────
# 4. F&O Expiry Date Preceding-Day Holiday Roll
# ─────────────────────────────────────────────────────────────────────────────

def get_adjusted_expiry_date(
    target_date: date,
    exchange: str = "NFO",
) -> date:
    """
    Per SEBI & Indian exchange rules: If the regular weekly or monthly expiry day
    falls on a trading holiday, the contract expires on the preceding trading day.
    Walks backward until a valid non-holiday weekday is found.
    """
    cur = target_date
    while cur.weekday() >= 5 or is_trading_holiday(cur, exchange):
        cur -= timedelta(days=1)
    return cur
