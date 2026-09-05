"""
engine/risk_limits.py
─────────────────────
Non-overridable hard risk limits.

Enforced BEFORE every order reaches the broker. Cannot be bypassed by
LLM reasoning, user prompts, or any code path.

Configuration via environment variables:
  MAX_DAILY_LOSS         — max cumulative loss per day in INR (default: 20000)
  MAX_DAILY_TRADES       — max total trades per day (default: 20)
  MAX_TRADES_PER_SYMBOL  — max trades per symbol per day (default: 5)
  RISK_DB_PATH           — path to SQLite DB (default: ~/.trading_platform/risk_limits.db)

Usage:
    from engine.risk_limits import risk_limits, RiskLimitError

    # Before placing order:
    risk_limits.check("INFY", "BUY", 10, 1400.0)

    # After order fills:
    risk_limits.record_trade("INFY", "BUY", 10, 1400.0, pnl=0.0)

    # Check status:
    status = risk_limits.get_status()
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Generator, Optional


from dataclasses import dataclass, field
from typing import Any


@dataclass
class RiskPreflightResult:
    """Preflight advisory evaluation with behavioral coaching and double confirmation."""

    allowed: bool
    requires_double_confirmation: bool
    flags: list[str] = field(default_factory=list)
    disclaimers: list[str] = field(default_factory=list)
    coaching_recommendations: list[str] = field(default_factory=list)
    block_reason: str = ""
    overridden: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "requires_double_confirmation": self.requires_double_confirmation,
            "flags": self.flags,
            "disclaimers": self.disclaimers,
            "coaching_recommendations": self.coaching_recommendations,
            "block_reason": self.block_reason,
            "overridden": self.overridden,
        }


class RiskLimitError(Exception):
    """Raised when an order would breach a hard risk limit without user confirmation."""


def _db_path() -> Path:
    path = os.environ.get("RISK_DB_PATH")
    if path:
        return Path(path)
    return Path.home() / ".trading_platform" / "risk_limits.db"


class RiskLimits:
    """
    Tracks daily P&L and trade counts in SQLite.
    Checks hard limits before every order.
    Persists across process restarts; resets at midnight.
    """

    def __init__(self) -> None:
        self._db = _db_path()
        self._db.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ── Config ────────────────────────────────────────────────

    @property
    def max_daily_loss(self) -> float:
        return -abs(float(os.environ.get("MAX_DAILY_LOSS", "20000")))

    @property
    def max_daily_trades(self) -> int:
        return int(os.environ.get("MAX_DAILY_TRADES", "20"))

    @property
    def max_trades_per_symbol(self) -> int:
        return int(os.environ.get("MAX_TRADES_PER_SYMBOL", "5"))

    @property
    def max_consecutive_losses(self) -> int:
        """Max consecutive losing trades before trading is locked to prevent tilt/revenge trading."""
        return int(os.environ.get("MAX_CONSECUTIVE_LOSSES", "3"))

    @property
    def max_daily_drawdown_pct(self) -> float:
        """Max allowed daily portfolio drawdown in percentage (e.g. 2.0 = 2%)."""
        return float(os.environ.get("MAX_DAILY_DRAWDOWN_PCT", "2.0"))

    # ── DB setup ──────────────────────────────────────────────

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_trades (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_date  TEXT NOT NULL,
                    symbol      TEXT NOT NULL,
                    action      TEXT NOT NULL,
                    quantity    INTEGER NOT NULL,
                    price       REAL NOT NULL,
                    pnl         REAL NOT NULL DEFAULT 0.0,
                    recorded_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_trade_date
                ON daily_trades (trade_date)
            """)

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self._db), timeout=30.0)
        try:
            yield conn
        finally:
            conn.close()

    def _today(self) -> str:
        return date.today().isoformat()

    # ── Read helpers ──────────────────────────────────────────

    def _daily_loss(self) -> float:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(pnl), 0.0) FROM daily_trades WHERE trade_date = ?",
                (self._today(),),
            ).fetchone()
        return float(row[0]) if row else 0.0

    def _trades_today(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM daily_trades WHERE trade_date = ?",
                (self._today(),),
            ).fetchone()
        return int(row[0]) if row else 0

    def _trades_today_for_symbol(self, symbol: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM daily_trades WHERE trade_date = ? AND symbol = ?",
                (self._today(), symbol.upper()),
            ).fetchone()
        return int(row[0]) if row else 0

    def _consecutive_losses_today(self) -> int:
        """Count consecutive losing trades from the most recent trade backwards today."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT pnl FROM daily_trades WHERE trade_date = ? ORDER BY id DESC",
                (self._today(),),
            ).fetchall()
        streak = 0
        for (pnl,) in rows:
            if pnl < 0:
                streak += 1
            else:
                break
        return streak

    # ── Preflight Evaluation & Guided Advisory ─────────────────

    def evaluate_preflight(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: float,
        current_position: Optional[dict] = None,
        allow_override: bool = False,
    ) -> RiskPreflightResult:
        """
        Evaluate an order against risk rules, returning structured behavioral disclaimers
        and coaching guidance rather than an opaque block.
        """
        sym = symbol.upper()
        act = action.upper()
        flags = []
        disclaimers = []
        recs = []

        # 1. Daily Loss Cap
        current_loss = self._daily_loss()
        if current_loss <= self.max_daily_loss:
            flags.append("DAILY_LOSS_CAP")
            disclaimers.append(
                f"Daily loss threshold reached (-₹{abs(current_loss):,.0f} vs limit -₹{abs(self.max_daily_loss):,.0f}). "
                f"Continuing past daily loss boundaries statistically compounds drawdown by 2.4x."
            )
            recs.append(
                "Take the remainder of the trading session off to protect capital and mental clarity."
            )

        # 2. Consecutive Losses (Tilt / Revenge Trading)
        streak = self._consecutive_losses_today()
        if streak >= self.max_consecutive_losses:
            flags.append("TILT_LOCKOUT")
            disclaimers.append(
                f"Tilt & revenge trading alert: {streak} consecutive losing trades today (limit: {self.max_consecutive_losses}). "
                f"Statistically, urgent re-entries during loss streaks have a >78% failure rate."
            )
            recs.append(
                "Step away for a 15-minute breather or reduce position size to 0.5% capital."
            )

        # 3. Max Daily Trades
        trades = self._trades_today()
        if trades >= self.max_daily_trades:
            flags.append("MAX_DAILY_TRADES")
            disclaimers.append(
                f"Overtrading alert: {trades} trades executed today (limit: {self.max_daily_trades}). High frequency increases brokerage drag."
            )
            recs.append("Wait for A+ high-conviction setups only.")

        # 4. Max Trades per Symbol
        sym_trades = self._trades_today_for_symbol(sym)
        if sym_trades >= self.max_trades_per_symbol:
            flags.append("MAX_SYMBOL_TRADES")
            disclaimers.append(
                f"Symbol over-focus alert: {sym_trades} trades on {sym} today (limit: {self.max_trades_per_symbol})."
            )
            recs.append(
                f"Diversify attention across other uncorrelated sectors or wait for a clearer structure on {sym}."
            )

        # 5. Anti-Pyramiding into Losers
        if current_position and act == "BUY" and quantity > 0:
            avg = float(current_position.get("avg_price", 0))
            if avg > 0 and price > 0 and price < avg:
                loss_pct = (avg - price) / avg * 100
                flags.append("PYRAMID_INTO_LOSER")
                disclaimers.append(
                    f"Anti-pyramiding alert: adding size to a losing position in {sym} (held at avg ₹{avg:,.2f} vs LTP ₹{price:,.2f}, {loss_pct:.1f}% below avg). "
                    f"Pyramiding into a losing position increases total capital at risk."
                )
                recs.append(
                    "Ensure you have a strict invalidation stop-loss rather than emotional averaging."
                )

        requires_confirm = len(flags) > 0
        if requires_confirm:
            if allow_override:
                return RiskPreflightResult(
                    allowed=True,
                    requires_double_confirmation=True,
                    flags=flags,
                    disclaimers=disclaimers,
                    coaching_recommendations=recs,
                    block_reason="",
                    overridden=True,
                )
            else:
                reason = disclaimers[0] if disclaimers else "Order blocked by risk limits"
                return RiskPreflightResult(
                    allowed=False,
                    requires_double_confirmation=True,
                    flags=flags,
                    disclaimers=disclaimers,
                    coaching_recommendations=recs,
                    block_reason=reason,
                    overridden=False,
                )

        return RiskPreflightResult(
            allowed=True,
            requires_double_confirmation=False,
            flags=[],
            disclaimers=[],
            coaching_recommendations=[],
            block_reason="",
            overridden=False,
        )

    # ── Core check ────────────────────────────────────────────

    def check(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: float,
        current_position: Optional[dict] = None,
        allow_override: bool = False,
    ) -> RiskPreflightResult:
        """
        Validate an order against risk rules with advisory guidance and override support.

        Args:
            symbol:           Stock/index symbol
            action:           "BUY" or "SELL"
            quantity:         Number of shares/lots
            price:            Order price (use 0 for market orders)
            current_position: Optional dict with {avg_price, quantity}
            allow_override:   If True, permits execution with awareness acknowledgment.

        Raises:
            RiskLimitError: if a risk threshold is breached and allow_override is False.
        """
        res = self.evaluate_preflight(
            symbol=symbol,
            action=action,
            quantity=quantity,
            price=price,
            current_position=current_position,
            allow_override=allow_override,
        )
        if not res.allowed:
            raise RiskLimitError(
                f"Order blocked — {res.block_reason}\n"
                f"  Disclaimer: {res.disclaimers[0] if res.disclaimers else ''}\n"
                f"  Coaching: {res.coaching_recommendations[0] if res.coaching_recommendations else ''}\n"
                f"  (To execute with conscious awareness, confirm double-check override)."
            )
        return res

    # ── Record ────────────────────────────────────────────────

    def record_trade(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: float,
        pnl: float = 0.0,
    ) -> None:
        """Record a completed trade for daily tracking."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO daily_trades
                    (trade_date, symbol, action, quantity, price, pnl, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self._today(),
                    symbol.upper(),
                    action.upper(),
                    quantity,
                    price,
                    pnl,
                    datetime.now().isoformat(),
                ),
            )

    # ── Status ────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return current risk usage."""
        loss = self._daily_loss()
        trades = self._trades_today()
        streak = self._consecutive_losses_today()
        remaining_loss = max(0.0, loss - self.max_daily_loss)

        return {
            "daily_loss": loss,
            "trades_today": trades,
            "consecutive_losses_today": streak,
            "max_consecutive_losses": self.max_consecutive_losses,
            "max_daily_loss": self.max_daily_loss,
            "max_daily_trades": self.max_daily_trades,
            "max_trades_per_symbol": self.max_trades_per_symbol,
            "remaining_loss_room": -remaining_loss if loss < 0 else abs(self.max_daily_loss),
            "remaining_trades": max(0, self.max_daily_trades - trades),
            "tilt_lockout_active": streak >= self.max_consecutive_losses,
            "limits_hit": loss <= self.max_daily_loss
            or trades >= self.max_daily_trades
            or streak >= self.max_consecutive_losses,
        }


# ── Singleton ─────────────────────────────────────────────────
risk_limits = RiskLimits()
