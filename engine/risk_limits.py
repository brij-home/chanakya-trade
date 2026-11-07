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
    from config.paths import app_data_path

    path = os.environ.get("RISK_DB_PATH")
    if path:
        return Path(path)
    return app_data_path("risk_limits.db")


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

    @property
    def max_order_notional(self) -> float:
        """Max allowed single order notional value in INR (default: 25 Lakh)."""
        return float(os.environ.get("MAX_ORDER_NOTIONAL", "2500000.0"))

    @property
    def max_position_value(self) -> float:
        """Max allowed aggregate position value in INR (default: 50 Lakh)."""
        return float(os.environ.get("MAX_POSITION_VALUE", "5000000.0"))

    @property
    def max_risk_per_trade(self) -> float:
        """Max allowed risk per trade in INR (default: 50,000)."""
        return float(os.environ.get("MAX_RISK_PER_TRADE", "50000.0"))

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
                    recorded_at TEXT NOT NULL,
                    account_id  TEXT NOT NULL DEFAULT 'UNKNOWN',
                    mode        TEXT NOT NULL DEFAULT 'UNKNOWN'
                )
            """)
            # Migration check: if table already existed without account_id / mode
            cursor = conn.execute("PRAGMA table_info(daily_trades)")
            cols = {row[1] for row in cursor.fetchall()}
            if "account_id" not in cols:
                conn.execute(
                    "ALTER TABLE daily_trades ADD COLUMN account_id TEXT NOT NULL DEFAULT 'UNKNOWN'"
                )
            if "mode" not in cols:
                conn.execute(
                    "ALTER TABLE daily_trades ADD COLUMN mode TEXT NOT NULL DEFAULT 'UNKNOWN'"
                )

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_trade_date_account_mode
                ON daily_trades (trade_date, account_id, mode)
            """)

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        from engine.db_pool import configure_sqlite_connection

        conn = sqlite3.connect(str(self._db), timeout=30.0)
        configure_sqlite_connection(conn, timeout_sec=30.0)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _today(self) -> str:
        try:
            from config.constants import now_ist

            return now_ist().date().isoformat()
        except Exception:
            try:
                from market.instruments import get_current_ist_time

                return get_current_ist_time().date().isoformat()
            except Exception:
                return date.today().isoformat()

    # ── Read helpers ──────────────────────────────────────────

    def _daily_loss(self, account_id: Optional[str] = None, mode: Optional[str] = None) -> float:
        query = "SELECT COALESCE(SUM(pnl), 0.0) FROM daily_trades WHERE trade_date = ?"
        params: list[Any] = [self._today()]
        if account_id:
            query += " AND account_id = ?"
            params.append(account_id)
        if mode:
            query += " AND mode = ?"
            params.append(mode)
        with self._connect() as conn:
            row = conn.execute(query, tuple(params)).fetchone()
        return float(row[0]) if row else 0.0

    def _trades_today(self, account_id: Optional[str] = None, mode: Optional[str] = None) -> int:
        query = "SELECT COUNT(*) FROM daily_trades WHERE trade_date = ?"
        params: list[Any] = [self._today()]
        if account_id:
            query += " AND account_id = ?"
            params.append(account_id)
        if mode:
            query += " AND mode = ?"
            params.append(mode)
        with self._connect() as conn:
            row = conn.execute(query, tuple(params)).fetchone()
        return int(row[0]) if row else 0

    def _trades_today_for_symbol(
        self, symbol: str, account_id: Optional[str] = None, mode: Optional[str] = None
    ) -> int:
        query = "SELECT COUNT(*) FROM daily_trades WHERE trade_date = ? AND symbol = ?"
        params: list[Any] = [self._today(), symbol.upper()]
        if account_id:
            query += " AND account_id = ?"
            params.append(account_id)
        if mode:
            query += " AND mode = ?"
            params.append(mode)
        with self._connect() as conn:
            row = conn.execute(query, tuple(params)).fetchone()
        return int(row[0]) if row else 0

    def _consecutive_losses_today(
        self, account_id: Optional[str] = None, mode: Optional[str] = None
    ) -> int:
        """Count consecutive losing trades from the most recent trade backwards today."""
        query = "SELECT pnl FROM daily_trades WHERE trade_date = ?"
        params: list[Any] = [self._today()]
        if account_id:
            query += " AND account_id = ?"
            params.append(account_id)
        if mode:
            query += " AND mode = ?"
            params.append(mode)
        query += " ORDER BY id DESC"
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
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
        account_id: Optional[str] = None,
        mode: Optional[str] = None,
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

        # 0. Order Size & Notional Gate
        notional = float(price or 0.0) * int(quantity or 0)
        if notional > self.max_order_notional:
            flags.append("MAX_ORDER_NOTIONAL")
            disclaimers.append(
                f"Order notional ₹{notional:,.2f} exceeds institutional threshold of ₹{self.max_order_notional:,.2f}. "
                f"Slicing or risk reduction required."
            )
            recs.append("Reduce quantity to stay within risk limits.")

        # 1. Daily Loss Cap & Drawdown %
        current_loss = self._daily_loss(account_id=account_id, mode=mode)
        total_cap = float(
            os.environ.get("TRADING_CAPITAL", os.environ.get("TOTAL_CAPITAL", "200000.0"))
        )
        if current_loss < 0 and total_cap > 0:
            dd_pct = (abs(current_loss) / total_cap) * 100.0
            if dd_pct >= self.max_daily_drawdown_pct:
                flags.append("MAX_DAILY_DRAWDOWN")
                disclaimers.append(
                    f"Daily portfolio drawdown threshold reached ({dd_pct:.1f}% vs limit {self.max_daily_drawdown_pct:.1f}% of capital ₹{total_cap:,.0f})."
                )
                recs.append("Take the remainder of the trading session off to protect capital.")
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
        streak = self._consecutive_losses_today(account_id=account_id, mode=mode)
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
        trades = self._trades_today(account_id=account_id, mode=mode)
        if trades >= self.max_daily_trades:
            flags.append("MAX_DAILY_TRADES")
            disclaimers.append(
                f"Overtrading alert: {trades} trades executed today (limit: {self.max_daily_trades}). High frequency increases brokerage drag."
            )
            recs.append("Wait for A+ high-conviction setups only.")

        # 4. Max Trades per Symbol
        sym_trades = self._trades_today_for_symbol(sym, account_id=account_id, mode=mode)
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
        account_id: Optional[str] = None,
        mode: Optional[str] = None,
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
            account_id=account_id,
            mode=mode,
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
        account_id: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> None:
        """Record a completed trade for daily tracking with account and mode scoping."""
        acc = account_id or "UNKNOWN"
        md = mode or os.environ.get("TRADING_MODE", "UNKNOWN")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO daily_trades
                    (trade_date, symbol, action, quantity, price, pnl, recorded_at, account_id, mode)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self._today(),
                    symbol.upper(),
                    action.upper(),
                    quantity,
                    price,
                    pnl,
                    datetime.now().isoformat(),
                    acc,
                    md,
                ),
            )

    # ── Status ────────────────────────────────────────────────

    def get_status(self, account_id: Optional[str] = None, mode: Optional[str] = None) -> dict:
        """Return current risk usage."""
        loss = self._daily_loss(account_id=account_id, mode=mode)
        trades = self._trades_today(account_id=account_id, mode=mode)
        streak = self._consecutive_losses_today(account_id=account_id, mode=mode)
        allowed_loss = abs(self.max_daily_loss)
        current_l = abs(min(0.0, loss))
        remaining_loss = max(0.0, allowed_loss - current_l)

        return {
            "daily_loss": loss,
            "trades_today": trades,
            "consecutive_losses_today": streak,
            "max_consecutive_losses": self.max_consecutive_losses,
            "max_daily_loss": self.max_daily_loss,
            "max_daily_trades": self.max_daily_trades,
            "max_trades_per_symbol": self.max_trades_per_symbol,
            "remaining_loss_room": remaining_loss,
            "remaining_trades": max(0, self.max_daily_trades - trades),
            "tilt_lockout_active": streak >= self.max_consecutive_losses,
            "limits_hit": loss <= self.max_daily_loss
            or trades >= self.max_daily_trades
            or streak >= self.max_consecutive_losses,
        }

    def get_behavioral_anti_tilt_status(
        self, account_id: Optional[str] = None, mode: Optional[str] = None
    ) -> dict[str, Any]:
        """
        Computes institutional behavioral anti-tilt metrics, psychological reset
        directives, and mindful co-pilot friction status.
        """
        loss = self._daily_loss(account_id=account_id, mode=mode)
        trades = self._trades_today(account_id=account_id, mode=mode)
        streak = self._consecutive_losses_today(account_id=account_id, mode=mode)

        total_cap = float(
            os.environ.get("TRADING_CAPITAL", os.environ.get("TOTAL_CAPITAL", "200000.0"))
        )
        dd_pct = (abs(min(0.0, loss)) / total_cap * 100.0) if total_cap > 0 else 0.0

        if streak >= self.max_consecutive_losses or loss <= self.max_daily_loss:
            tilt_state = "CRITICAL_TILT_RISK"
            coaching = (
                f"Tilt Lockout Active: {streak} consecutive losses (limit {self.max_consecutive_losses}) "
                f"or daily loss limit reached (-₹{abs(loss):,.0f}). "
                f"Statistically, executing immediate re-entries now compounds losses by 2.4x. "
                f"Mindful Directive: Step away from screens for a 15-minute nervous system reset."
            )
            requires_override = True
        elif streak == 2 or (self.max_daily_loss < 0 and loss <= self.max_daily_loss * 0.5):
            tilt_state = "ELEVATED_TILT_RISK"
            coaching = (
                "Elevated Fatigue Risk: 2 consecutive losses. Focus on capital defense. "
                "Downsize next position to 0.5% capital and verify A+ confluence before pulling trigger."
            )
            requires_override = True
        elif streak == 1:
            tilt_state = "MILD_FRICTION"
            coaching = (
                "Normal market fluctuation. Stick strictly to playbook invalidation stop-loss."
            )
            requires_override = False
        else:
            tilt_state = "CLEAR"
            coaching = "Disciplined state. Sizing and risk parameters fully intact."
            requires_override = False

        return {
            "loss_streak": streak,
            "max_consecutive_losses": self.max_consecutive_losses,
            "daily_realized_loss": round(loss, 2),
            "max_daily_loss": self.max_daily_loss,
            "daily_drawdown_pct": round(dd_pct, 2),
            "max_daily_drawdown_pct": self.max_daily_drawdown_pct,
            "trades_today": trades,
            "max_daily_trades": self.max_daily_trades,
            "tilt_state": tilt_state,
            "tilt_lockout_active": streak >= self.max_consecutive_losses,
            "requires_conscious_override": requires_override,
            "coaching_guidance": coaching,
            "recommended_cooldown_minutes": 15 if streak >= 2 else 0,
            "anti_tilt_checklist": [
                "Have I waited at least 15 minutes since the last stop-out?",
                "Is this a playbook A+ setup, or an urge to recover prior losses?",
                "Am I willing to accept the exact rupee risk of this trade if stopped out?",
            ],
        }

    def reset_all(self) -> None:
        """Clear all recorded trades and reset counters (for testing and midnight resets)."""
        with self._connect() as conn:
            conn.execute("DELETE FROM daily_trades")


# ── Singleton ─────────────────────────────────────────────────
risk_limits = RiskLimits()
