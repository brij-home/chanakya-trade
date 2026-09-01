"""
engine/journal.py
─────────────────
Authoritative Trade Journal & Performance Analytics Engine for Indian Markets.

Features:
  1. Immutable capture of trade thesis, technical setup, intended risk (R), and realized outcomes.
  2. Calculation of institutional trading statistics (Win Rate, Profit Factor, Expectancy R).
  3. Persistent local storage in ~/.trading_platform/trade_journal.json.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

from config.paths import app_data_path
from market.instruments import get_current_ist_time

logger = logging.getLogger("chanakya.journal")

TradeOutcome = Literal["WIN", "LOSS", "BREAKEVEN", "OPEN"]
TradeDirection = Literal["BUY", "SELL"]


@dataclass
class JournalEntry:
    """A single trade record in the authoritative trade journal."""

    id: str
    symbol: str
    direction: TradeDirection
    entry_price: float
    qty: int
    stop_loss: float
    target: float
    setup_type: str = "SYSTEMATIC_BREAKOUT"
    thesis: str = ""
    status: TradeOutcome = "OPEN"
    exit_price: Optional[float] = None
    realized_pnl: float = 0.0
    realized_r: float = 0.0
    initial_risk_amount: float = 0.0
    fees_and_taxes: float = 0.0
    entry_time_ist: str = field(
        default_factory=lambda: get_current_ist_time().strftime("%d %b %Y, %H:%M:%S IST")
    )
    exit_time_ist: Optional[str] = None
    order_id: Optional[str] = None
    notes: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.initial_risk_amount == 0.0 and self.stop_loss > 0 and self.entry_price > 0:
            risk_per_share = abs(self.entry_price - self.stop_loss)
            self.initial_risk_amount = round(risk_per_share * self.qty, 2)

    def close_trade(
        self,
        exit_price: float,
        fees_and_taxes: float = 0.0,
        exit_notes: Optional[str] = None,
    ) -> None:
        """Close the trade, computing final realized P&L, fees, and realized R-multiple."""
        self.exit_price = float(exit_price)
        self.fees_and_taxes = float(fees_and_taxes)
        self.exit_time_ist = get_current_ist_time().strftime("%d %b %Y, %H:%M:%S IST")

        # P&L Calculation
        gross_pnl = (
            (self.exit_price - self.entry_price) * self.qty
            if self.direction == "BUY"
            else (self.entry_price - self.exit_price) * self.qty
        )
        self.realized_pnl = round(gross_pnl - self.fees_and_taxes, 2)

        # R-Multiple Calculation
        if self.initial_risk_amount > 0:
            self.realized_r = round(self.realized_pnl / self.initial_risk_amount, 2)
        else:
            self.realized_r = 0.0

        # Assign outcome category
        if self.realized_pnl > 50.0:
            self.status = "WIN"
        elif self.realized_pnl < -50.0:
            self.status = "LOSS"
        else:
            self.status = "BREAKEVEN"

        if exit_notes:
            self.notes.append(exit_notes)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class JournalStatistics:
    """Aggregate statistics derived from closed journal entries."""

    total_trades: int
    open_trades: int
    closed_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    win_rate_pct: float
    profit_factor: float
    expectancy_r: float
    total_realized_pnl: float
    total_fees_and_taxes: float
    avg_win_r: float
    avg_loss_r: float
    largest_win_r: float
    largest_loss_r: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TradeJournalManager:
    """Manages persistent trade journal records and analytical calculations."""

    def __init__(self, storage_path: Optional[Path] = None) -> None:
        self._path = storage_path or (app_data_path() / "trade_journal.json")
        self._entries: list[JournalEntry] = []
        self._load()

    def _load(self) -> None:
        """Load journal entries from persistent storage."""
        if not self._path.exists():
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._entries = [JournalEntry(**item) for item in data if isinstance(item, dict)]
        except Exception as e:
            logger.warning(f"Failed to load trade journal from {self._path}: {e}")
            self._entries = []

    def _save(self) -> None:
        """Save journal entries to disk."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump([e.to_dict() for e in self._entries], f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save trade journal to {self._path}: {e}")

    def add_entry(
        self,
        symbol: str,
        direction: TradeDirection,
        entry_price: float,
        qty: int,
        stop_loss: float,
        target: float,
        setup_type: str = "SYSTEMATIC_BREAKOUT",
        thesis: str = "",
        order_id: Optional[str] = None,
    ) -> JournalEntry:
        """Record a new trade entry in the journal."""
        entry = JournalEntry(
            id=f"JRN-{uuid.uuid4().hex[:8].upper()}",
            symbol=symbol.upper(),
            direction=direction,
            entry_price=float(entry_price),
            qty=int(qty),
            stop_loss=float(stop_loss),
            target=float(target),
            setup_type=setup_type,
            thesis=thesis,
            order_id=order_id,
        )
        self._entries.insert(0, entry)
        self._save()
        return entry

    def close_entry(
        self,
        entry_id: str,
        exit_price: float,
        fees_and_taxes: float = 0.0,
        exit_notes: Optional[str] = None,
    ) -> Optional[JournalEntry]:
        """Close an open journal entry by ID."""
        for entry in self._entries:
            if entry.id == entry_id:
                entry.close_trade(
                    exit_price=exit_price, fees_and_taxes=fees_and_taxes, exit_notes=exit_notes
                )
                self._save()
                return entry
        return None

    def list_entries(self, status: Optional[str] = None) -> list[dict[str, Any]]:
        """Return list of journal entries, optionally filtered by status."""
        if status:
            return [e.to_dict() for e in self._entries if e.status == status.upper()]
        return [e.to_dict() for e in self._entries]

    def compute_statistics(self) -> JournalStatistics:
        """Compute institutional trading performance metrics from closed trades."""
        closed = [e for e in self._entries if e.status != "OPEN"]
        open_trades = len(self._entries) - len(closed)

        if not closed:
            return JournalStatistics(
                total_trades=len(self._entries),
                open_trades=open_trades,
                closed_trades=0,
                winning_trades=0,
                losing_trades=0,
                breakeven_trades=0,
                win_rate_pct=0.0,
                profit_factor=0.0,
                expectancy_r=0.0,
                total_realized_pnl=0.0,
                total_fees_and_taxes=0.0,
                avg_win_r=0.0,
                avg_loss_r=0.0,
                largest_win_r=0.0,
                largest_loss_r=0.0,
            )

        wins = [e for e in closed if e.status == "WIN"]
        losses = [e for e in closed if e.status == "LOSS"]
        breakevens = [e for e in closed if e.status == "BREAKEVEN"]

        win_rate = round((len(wins) / len(closed)) * 100.0, 2)
        total_gains = sum(e.realized_pnl for e in wins)
        total_losses = abs(sum(e.realized_pnl for e in losses))
        profit_factor = (
            round(total_gains / total_losses, 2)
            if total_losses > 0
            else (99.0 if total_gains > 0 else 0.0)
        )

        r_wins = [e.realized_r for e in wins]
        r_losses = [e.realized_r for e in losses]

        avg_win_r = round(sum(r_wins) / len(r_wins), 2) if r_wins else 0.0
        avg_loss_r = round(sum(r_losses) / len(r_losses), 2) if r_losses else 0.0
        largest_win_r = max(r_wins) if r_wins else 0.0
        largest_loss_r = min(r_losses) if r_losses else 0.0

        # Mathematical Expectancy: (Win Rate * Avg Win R) - (Loss Rate * Avg Loss R)
        loss_rate = len(losses) / len(closed)
        win_rate_dec = len(wins) / len(closed)
        expectancy = round((win_rate_dec * avg_win_r) + (loss_rate * avg_loss_r), 2)

        return JournalStatistics(
            total_trades=len(self._entries),
            open_trades=open_trades,
            closed_trades=len(closed),
            winning_trades=len(wins),
            losing_trades=len(losses),
            breakeven_trades=len(breakevens),
            win_rate_pct=win_rate,
            profit_factor=profit_factor,
            expectancy_r=expectancy,
            total_realized_pnl=round(sum(e.realized_pnl for e in closed), 2),
            total_fees_and_taxes=round(sum(e.fees_and_taxes for e in closed), 2),
            avg_win_r=avg_win_r,
            avg_loss_r=avg_loss_r,
            largest_win_r=largest_win_r,
            largest_loss_r=largest_loss_r,
        )


# Singleton instance
_journal_manager: Optional[TradeJournalManager] = None


def get_trade_journal() -> TradeJournalManager:
    """Access singleton TradeJournalManager."""
    global _journal_manager
    if _journal_manager is None:
        _journal_manager = TradeJournalManager()
    return _journal_manager
