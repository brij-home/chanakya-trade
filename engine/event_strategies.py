"""
engine/event_strategies.py
──────────────────────────
Event-calendar context for Indian markets. Earnings option ideas are omitted
until verified option-IV history and historical move inputs are available.

Auto-detects upcoming events and recommends pre/post-event strategies:
  - RBI policy: hedge rate-sensitives, straddle BANKNIFTY
  - Earnings: no premium strategy without verified option-IV and move evidence
  - Expiry: max pain convergence, gamma scalping
  - Budget: sector-specific positioning

Usage:
    from engine.event_strategies import get_event_strategies, print_event_strategies

    strategies = get_event_strategies()
    for s in strategies:
        print(f"{s.event} → {s.strategy} ({s.timing})")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from rich.console import Console
from rich.table import Table

console = Console()


@dataclass
class EventStrategy:
    """A recommended strategy for an upcoming event."""

    event: str  # "Weekly Expiry", "RBI Policy", "RELIANCE Earnings"
    event_date: str  # YYYY-MM-DD
    days_away: int  # days until event
    timing: str  # "PRE" or "POST"
    strategy: str  # "Sell NIFTY Straddle", "Buy BANKNIFTY Puts"
    rationale: str
    risk_level: str  # "LOW" / "MEDIUM" / "HIGH"
    instruments: list[str] = field(default_factory=list)  # suggested instruments


def get_event_strategies(
    symbols: Optional[list[str]] = None,
    days_ahead: int = 7,
) -> list[EventStrategy]:
    """
    Scan upcoming events and generate strategy recommendations.
    """
    today = date.today()
    strategies: list[EventStrategy] = []

    # ── Expiry strategies ────────────────────────────────────
    strategies.extend(_expiry_strategies(today, days_ahead))

    # ── RBI policy strategies ────────────────────────────────
    strategies.extend(_rbi_strategies(today, days_ahead))

    # ── Earnings strategies ──────────────────────────────────
    strategies.extend(_earnings_strategies(today, days_ahead, symbols))

    # ── Budget strategies ────────────────────────────────────
    strategies.extend(_budget_strategies(today))

    # Sort by days_away
    strategies.sort(key=lambda s: s.days_away)
    return strategies


def _expiry_strategies(today: date, days_ahead: int) -> list[EventStrategy]:
    """Calendar context for verified upcoming index expiries."""
    strategies = []
    from market.calendar import get_nearest_weekly_expiry, get_nearest_monthly_expiry

    upcoming = (
        ("NIFTY weekly expiry", "NIFTY", get_nearest_weekly_expiry("NIFTY", ref_date=today)),
        (
            "BANKNIFTY monthly expiry",
            "BANKNIFTY",
            get_nearest_monthly_expiry("BANKNIFTY", ref_date=today),
        ),
    )
    for label, symbol, expiry in upcoming:
        days_away = (expiry - today).days
        if 0 <= days_away <= days_ahead:
            strategies.append(
                EventStrategy(
                    event=label,
                    event_date=expiry.isoformat(),
                    days_away=days_away,
                    timing="PRE",
                    strategy="Review open exposure, listed contract expiry and defined risk; no directional edge is implied.",
                    rationale="Expiry may change liquidity, gamma and settlement risk. Use current listed contracts and live quotes.",
                    risk_level="HIGH",
                    instruments=[symbol],
                )
            )

    return strategies


def _rbi_strategies(today: date, days_ahead: int) -> list[EventStrategy]:
    """Strategies around RBI MPC meetings."""
    # RBI MPC meetings in 2026 (approximate dates — typically bi-monthly)
    rbi_dates = [
        date(2026, 2, 5),
        date(2026, 4, 8),
        date(2026, 6, 4),
        date(2026, 8, 5),
        date(2026, 10, 7),
        date(2026, 12, 3),
    ]

    strategies = []
    for rbi_date in rbi_dates:
        days_away = (rbi_date - today).days
        if 0 <= days_away <= days_ahead:
            if days_away >= 2:
                strategies.append(
                    EventStrategy(
                        event="RBI MPC Policy",
                        event_date=rbi_date.isoformat(),
                        days_away=days_away,
                        timing="PRE",
                        strategy="Buy BANKNIFTY straddle or hedge bank positions.",
                        rationale="Rate-sensitive sectors (banks, NBFCs, realty) swing 2-4% on RBI day. "
                        "Buy straddle 2-3 days before to capture IV expansion.",
                        risk_level="MEDIUM",
                        instruments=["BANKNIFTY", "HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK"],
                    )
                )
            elif days_away == 0:
                strategies.append(
                    EventStrategy(
                        event="RBI MPC Decision Day",
                        event_date=rbi_date.isoformat(),
                        days_away=0,
                        timing="PRE",
                        strategy="Do NOT enter new positions before 10 AM announcement. "
                        "After announcement: sell straddle to capture IV crush.",
                        rationale="Decision at ~10 AM. IV crush after announcement is significant. "
                        "If you have pre-event straddles, exit immediately after announcement.",
                        risk_level="HIGH",
                        instruments=["BANKNIFTY", "NIFTY BANK"],
                    )
                )

    return strategies


def _earnings_strategies(
    today: date, days_ahead: int, symbols: Optional[list[str]] = None
) -> list[EventStrategy]:
    """Strategies around earnings announcements."""
    try:
        from market.earnings import get_earnings_calendar, get_pre_earnings_iv

        calendar = get_earnings_calendar(symbols, days_ahead=days_ahead)

        strategies = []
        for entry in calendar[:5]:
            if entry.result_date and entry.result_date != "TBD":
                try:
                    result_date = date.fromisoformat(entry.result_date)
                    days_away = (result_date - today).days
                except ValueError:
                    continue

                if 1 <= days_away <= 5:
                    iv_data = get_pre_earnings_iv(entry.symbol)
                    iv_rank = iv_data.get("iv_rank")
                    avg_move = entry.avg_move

                    # Do not manufacture an event-volatility trade idea when
                    # actual option-IV history and a comparable move estimate
                    # are unavailable.
                    if iv_rank is None:
                        continue
                    if avg_move is None:
                        continue

                    if iv_rank > 60:
                        strategy = (
                            f"Sell {entry.symbol} straddle/strangle — IV elevated (rank: {iv_rank})"
                        )
                        risk = "MEDIUM"
                    elif iv_rank < 30:
                        strategy = f"Buy {entry.symbol} straddle — IV cheap (rank: {iv_rank}), avg move ±{avg_move:.1f}%"
                        risk = "MEDIUM"
                    else:
                        strategy = f"Iron condor on {entry.symbol} — neutral IV, expected move ±{avg_move:.1f}%"
                        risk = "LOW"

                    strategies.append(
                        EventStrategy(
                            event=f"{entry.symbol} Earnings ({entry.quarter})",
                            event_date=entry.result_date,
                            days_away=days_away,
                            timing="PRE",
                            strategy=strategy,
                            rationale=f"IV rank: {iv_rank}, historical avg move: ±{avg_move:.1f}%",
                            risk_level=risk,
                            instruments=[entry.symbol],
                        )
                    )

        return strategies
    except Exception:
        return []


def _budget_strategies(today: date) -> list[EventStrategy]:
    """Strategies around Union Budget (Feb 1)."""
    strategies = []
    budget_date = date(today.year, 2, 1)

    # If budget is in the past this year, check next year
    if budget_date < today:
        budget_date = date(today.year + 1, 2, 1)

    days_away = (budget_date - today).days

    if days_away <= 14 and days_away > 0:
        strategies.append(
            EventStrategy(
                event="Union Budget",
                event_date=budget_date.isoformat(),
                days_away=days_away,
                timing="PRE",
                strategy="Buy NIFTY straddle for budget day volatility. "
                "Position in infra/defence/PSU for potential allocation boosts.",
                rationale="Budget day: 2-3% NIFTY swing. Infra/defence stocks rally on capex announcements. "
                "Don't trade the first reaction — let it settle for 30 minutes.",
                risk_level="HIGH",
                instruments=["NIFTY", "LT", "NTPC", "POWERGRID", "BEL"],
            )
        )

    return strategies


def get_event_strategy_context() -> str:
    """Generate text for LLM prompts."""
    strategies = get_event_strategies(days_ahead=7)
    if not strategies:
        return "No event-driven opportunities in the next 7 days."

    parts = [f"Event-driven strategies ({len(strategies)} active):"]
    for s in strategies:
        parts.append(
            f"  [{s.risk_level}] {s.event} (in {s.days_away}d)\n"
            f"    Strategy: {s.strategy}\n"
            f"    Rationale: {s.rationale}"
        )
    return "\n\n".join(parts)


def print_event_strategies(days_ahead: int = 7) -> None:
    """Display event strategies as a Rich table."""
    strategies = get_event_strategies(days_ahead=days_ahead)
    if not strategies:
        console.print("[dim]No event-driven opportunities in the next {days_ahead} days.[/dim]")
        return

    table = Table(title=f"Event-Driven Strategies (next {days_ahead} days)")
    table.add_column("Event", style="bold", width=25)
    table.add_column("Date", width=12)
    table.add_column("Days", justify="right", width=6)
    table.add_column("Strategy", ratio=1)
    table.add_column("Risk", width=8)

    for s in strategies:
        risk_style = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red"}.get(s.risk_level, "white")
        table.add_row(
            s.event,
            s.event_date,
            str(s.days_away),
            s.strategy[:60],
            f"[{risk_style}]{s.risk_level}[/{risk_style}]",
        )

    console.print(table)
