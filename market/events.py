"""
market/events.py
────────────────
Market calendar: F&O expiry dates, earnings, RBI policy, corporate actions.
All data sourced from public endpoints (NSE, RBI websites).
"""

from __future__ import annotations
import logging

logger = logging.getLogger("market.events")


from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Optional


from market.http_pool import get_nse_client

try:
    import feedparser

    _FEEDPARSER_AVAILABLE = True
except ImportError:
    _FEEDPARSER_AVAILABLE = False


# ── Result types ─────────────────────────────────────────────


@dataclass
class ExpiryDates:
    weekly: date  # nearest weekly expiry from the effective-dated exchange calendar
    monthly: date  # nearest monthly expiry from the effective-dated exchange calendar
    next_monthly: date  # following month's expiry


@dataclass
class EarningsEvent:
    symbol: str
    company: str
    date: str  # "YYYY-MM-DD"
    purpose: str  # "Quarterly Results", "Board Meeting" etc.
    published_at: Optional[str] = None
    first_seen_at: Optional[str] = None
    revision_id: Optional[str] = None
    source_entity: str = "NSE"


@dataclass
class RBIEvent:
    date: str
    event: str
    rate: Optional[float] = None  # repo rate after decision
    published_at: Optional[str] = None
    first_seen_at: Optional[str] = None
    revision_id: Optional[str] = None
    source_entity: str = "RBI"


@dataclass
class CorporateAction:
    symbol: str
    action: str  # "Dividend", "Bonus", "Split", "Rights"
    ex_date: str
    details: str
    published_at: Optional[str] = None
    first_seen_at: Optional[str] = None
    revision_id: Optional[str] = None
    source_entity: str = "NSE"


def filter_events_as_of(
    events: list[Any],
    as_of: datetime | str,
) -> list[Any]:
    """
    Filter events to prevent lookahead bias in backtest/replay.
    Only includes events whose first_seen_at (or published_at / date) is <= as_of.
    """
    if not events:
        return []

    from datetime import timezone

    if isinstance(as_of, str):
        try:
            as_of_dt = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        except ValueError:
            as_of_dt = datetime.strptime(as_of[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        as_of_dt = as_of

    if as_of_dt.tzinfo is None:
        as_of_dt = as_of_dt.replace(tzinfo=timezone.utc)

    valid_events = []
    for ev in events:
        ts_str = getattr(ev, "first_seen_at", None) or getattr(ev, "published_at", None)
        if ts_str:
            try:
                ev_dt = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
                if ev_dt.tzinfo is None:
                    ev_dt = ev_dt.replace(tzinfo=timezone.utc)
                if ev_dt <= as_of_dt:
                    valid_events.append(ev)
                continue
            except Exception as e_ts:
                logger.debug(f"[market.events] Failed parsing ISO timestamp '{ts_str}': {e_ts}")

        d_str = getattr(ev, "date", None) or getattr(ev, "ex_date", None)
        if d_str:
            try:
                ev_d = datetime.strptime(str(d_str)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if ev_d <= as_of_dt:
                    valid_events.append(ev)
            except Exception as e_d:
                logger.debug(f"[market.events] Failed parsing date '{d_str}': {e_d}")
    return valid_events


# ── F&O Expiry Dates ─────────────────────────────────────────


def _last_thursday(year: int, month: int) -> date:
    """Compatibility name returning the effective-dated NSE monthly expiry."""
    from market.rule_schedule import monthly_expiry
    from market.calendar import get_adjusted_expiry_date

    return get_adjusted_expiry_date(monthly_expiry(year, month, "NSE"), "NFO")


def _next_thursday(from_date: date = None) -> date:
    """Compatibility name returning the next canonical NIFTY weekly expiry."""
    from market.calendar import get_nearest_weekly_expiry

    return get_nearest_weekly_expiry("NIFTY", ref_date=from_date or date.today())


def get_expiry_dates() -> ExpiryDates:
    """
    Calculate current week/month/next-month F&O expiry dates through the
    effective-dated exchange calendar.
    """
    today = date.today()
    year, month = today.year, today.month

    # Weekly NIFTY expiry; calendar resolver applies holidays and dated rules.
    from market.calendar import get_nearest_weekly_expiry

    weekly = get_nearest_weekly_expiry("NIFTY", ref_date=today)

    # Monthly NSE expiry from the same rule schedule.
    monthly = _monthly_contract_expiry(year, month)
    if monthly < today:
        # Current month already expired — move to next month
        nm = month + 1 if month < 12 else 1
        ny = year if month < 12 else year + 1
        monthly = _monthly_contract_expiry(ny, nm)

    # Next monthly
    if monthly.month == 12:
        nm2, ny2 = 1, monthly.year + 1
    else:
        nm2, ny2 = monthly.month + 1, monthly.year
    next_monthly = _monthly_contract_expiry(ny2, nm2)

    from market.calendar import get_adjusted_expiry_date

    return ExpiryDates(
        weekly=get_adjusted_expiry_date(weekly, "NFO"),
        monthly=get_adjusted_expiry_date(monthly, "NFO"),
        next_monthly=get_adjusted_expiry_date(next_monthly, "NFO"),
    )


# ── Earnings Calendar ─────────────────────────────────────────

NSE_CORP_CALENDAR_URL = "https://www.nseindia.com/api/event-calendar"


def get_earnings_calendar(
    symbols: Optional[list[str]] = None,
    days: int = 14,
) -> list[EarningsEvent]:
    """
    Upcoming earnings / board meetings for watchlist symbols.

    Args:
        symbols: Filter to these symbols. None = all upcoming.
        days:    Look ahead this many days.
    """
    try:
        session = get_nse_client()
        r = session.get(NSE_CORP_CALENDAR_URL, timeout=8)
        r.raise_for_status()
        data = r.json()

        today = date.today()
        cutoff = today + timedelta(days=days)
        events = []
        for item in data:
            sym = item.get("symbol", "")
            ev_date = item.get("date", "")
            purpose = item.get("purpose", "")
            if symbols and sym.upper() not in [s.upper() for s in symbols]:
                continue
            try:
                ev_dt = datetime.strptime(ev_date, "%d-%b-%Y").date()
                if today <= ev_dt <= cutoff:
                    events.append(
                        EarningsEvent(
                            symbol=sym,
                            company=item.get("company", sym),
                            date=ev_dt.isoformat(),
                            purpose=purpose,
                        )
                    )
            except (ValueError, TypeError):
                continue
        return sorted(events, key=lambda e: e.date)

    except Exception:
        return []  # No mock data — return empty when NSE API fails


# ── RBI Calendar ─────────────────────────────────────────────

RBI_RSS = "https://rbi.org.in/scripts/RSSFeedMonetary.aspx"


def get_rbi_calendar() -> list[RBIEvent]:
    """
    RBI Monetary Policy Committee upcoming dates.
    Fetches from RBI RSS feed. Returns empty list if unavailable.
    """
    if not _FEEDPARSER_AVAILABLE:
        return []
    try:
        feed = feedparser.parse(RBI_RSS)
        events = []
        for entry in feed.entries[:10]:
            title = entry.get("title", "")
            if "monetary" in title.lower() or "policy" in title.lower() or "repo" in title.lower():
                published = entry.get("published", "")
                events.append(
                    RBIEvent(
                        date=published[:10] if published else "",
                        event=title,
                    )
                )
        if events:
            return events
    except Exception as e_suppressed:
        logger.debug(f"[market.events] Non-fatal exception suppressed: {e_suppressed}")

    return []  # No mock data — return empty when RBI RSS fails


# ── Corporate Actions ─────────────────────────────────────────

NSE_CORP_ACTIONS_URL = (
    "https://www.nseindia.com/api/corporates-corporateActions?index=equities&symbol={symbol}"
)


def get_corporate_actions(symbol: str, n: int = 5) -> list[CorporateAction]:
    """
    Recent dividends, splits, bonuses from NSE for a given symbol.
    """
    try:
        session = get_nse_client()
        r = session.get(
            NSE_CORP_ACTIONS_URL.format(symbol=symbol.upper()),
            timeout=8,
        )
        r.raise_for_status()
        data = r.json()
        actions = []
        for item in data[:n]:
            actions.append(
                CorporateAction(
                    symbol=symbol.upper(),
                    action=item.get("subject", item.get("purpose", "Action")),
                    ex_date=item.get("exDate", item.get("ex_date", "")),
                    details=item.get("remarks", ""),
                )
            )
        return actions
    except Exception:
        return []


# ── Upcoming market events summary ────────────────────────────


def get_upcoming_events(days: int = 7) -> dict:
    """
    Combined summary of all upcoming market events.
    Used by morning brief.
    """
    expiries = get_expiry_dates()
    earnings = get_earnings_calendar(days=days)
    rbi = get_rbi_calendar()
    today = date.today()

    return {
        "expiries": {
            "weekly": expiries.weekly.isoformat(),
            "monthly": expiries.monthly.isoformat(),
            "days_to_weekly": (expiries.weekly - today).days,
            "days_to_monthly": (expiries.monthly - today).days,
        },
        "earnings": [
            {"symbol": e.symbol, "date": e.date, "purpose": e.purpose} for e in earnings[:5]
        ],
        "rbi": [{"date": r.date, "event": r.event} for r in rbi[:2]],
    }


def _monthly_contract_expiry(year, month):
    from market.rule_schedule import monthly_expiry
    from market.calendar import get_adjusted_expiry_date

    return get_adjusted_expiry_date(monthly_expiry(year, month), "NFO")
