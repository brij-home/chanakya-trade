"""
engine/modes.py
───────────────
Strict 3-Tier Operating Mode Enforcement for ChanakyaTrade.

Defines the three non-negotiable execution boundaries:
  1. OBSERVE : Read-only market data, watchlists, quotes, and research.
               All mutating order placement endpoints are strictly blocked.
  2. SIMULATE: Paper trading, what-if modeling, strategy sandbox, and backtesting.
               Safe default. Operates on synthetic / virtual accounts.
  3. EXECUTE : Live broker order routing.
               Requires explicit server-side feature flags, account allowlisting,
               pre-trade confirmation tickets, and fail-closed deterministic risk gates.
"""

from __future__ import annotations

import os
from enum import Enum


class TradingMode(str, Enum):
    """Authoritative operational mode."""

    OBSERVE = "OBSERVE"
    SIMULATE = "SIMULATE"
    EXECUTE = "EXECUTE"

    @classmethod
    def from_str(cls, value: str | None) -> TradingMode:
        """Parse a known mode; only an unset value defaults to SIMULATE."""
        if not value:
            return cls.SIMULATE
        v = value.strip().upper()
        if v in ("OBSERVE", "DEMO", "READONLY", "READ_ONLY"):
            return cls.OBSERVE
        if v in ("SIMULATE", "PAPER"):
            return cls.SIMULATE
        if v in ("EXECUTE", "LIVE"):
            return cls.EXECUTE
        raise ValueError(
            f"Unknown TRADING_MODE {value!r}; expected OBSERVE, SIMULATE/PAPER, or EXECUTE/LIVE."
        )


from dataclasses import dataclass


@dataclass
class ModeInfo:
    mode: TradingMode
    is_observe: bool
    is_simulate: bool
    is_execute: bool
    description: str


def get_current_mode() -> TradingMode:
    """Resolve current operating mode from environment variables."""
    raw = os.environ.get("TRADING_MODE", "PAPER")
    return TradingMode.from_str(raw)


def get_trading_mode() -> ModeInfo:
    """Return structured ModeInfo for current operational mode."""
    m = get_current_mode()
    desc_map = {
        TradingMode.OBSERVE: "Read-only market observation mode. All order mutations blocked.",
        TradingMode.SIMULATE: "Paper trading and backtest sandbox. Zero live capital risk.",
        TradingMode.EXECUTE: "LIVE BROKER EXECUTION. Real capital order placement enabled.",
    }
    return ModeInfo(
        mode=m,
        is_observe=(m == TradingMode.OBSERVE),
        is_simulate=(m == TradingMode.SIMULATE),
        is_execute=(m == TradingMode.EXECUTE),
        description=desc_map.get(m, "Operational mode"),
    )


def is_observe_mode() -> bool:
    """Return True if currently in read-only Observe mode."""
    return get_current_mode() == TradingMode.OBSERVE


def is_simulate_mode() -> bool:
    """Return True if currently in Paper / Simulate mode."""
    return get_current_mode() == TradingMode.SIMULATE


def is_execute_mode() -> bool:
    """Return True if currently in Live Execute mode."""
    return get_current_mode() == TradingMode.EXECUTE


def assert_can_mutate(action_name: str = "order execution") -> None:
    """
    Guard mutating endpoints.

    Raises PermissionError if called while operating in OBSERVE mode.
    """
    mode = get_current_mode()
    if mode == TradingMode.OBSERVE:
        raise PermissionError(
            f"Cannot perform '{action_name}' in OBSERVE mode. "
            "Switch to SIMULATE (Paper) or EXECUTE mode to place orders."
        )


def assert_live_execution_allowed(account_id: str | None = None) -> None:
    """
    Strict safety gate before live broker order submission.

    Requires:
      1. TRADING_MODE=EXECUTE or TRADING_MODE=LIVE
      2. Server flag ALLOW_LIVE_TRADING=1
      3. LIVE_EXECUTION_QUALIFIED=1 after account, fill-ledger, recovery and
         broker acceptance criteria have passed owner-controlled qualification.
    """
    mode = get_current_mode()
    if mode != TradingMode.EXECUTE:
        raise PermissionError(
            f"Live broker order blocked: current mode is '{mode.value}', not 'EXECUTE'."
        )

    # Server safety flag check
    live_flag = os.environ.get("ALLOW_LIVE_TRADING", "0").strip()
    if live_flag not in ("1", "true", "TRUE", "yes"):
        raise PermissionError(
            "Live broker order blocked: ALLOW_LIVE_TRADING server feature flag is not enabled."
        )

    if os.environ.get("LIVE_EXECUTION_QUALIFIED", "0").strip() != "1":
        raise PermissionError(
            "Live broker order blocked: the deployment has not passed live-execution qualification. "
            "Set LIVE_EXECUTION_QUALIFIED=1 only after owner acceptance of the required controls. "
            "Account-scoped execution facts, unknown-attempt recovery, protective-fill lifecycle, "
            "and broker acceptance criteria are still required."
        )

    # Account allowlist verification (SEC-14)
    allowed_accounts_str = os.environ.get("LIVE_EXECUTION_ALLOWED_ACCOUNTS", "").strip()
    if allowed_accounts_str:
        allowed_accounts = {acc.strip() for acc in allowed_accounts_str.split(",") if acc.strip()}
        if not account_id or account_id not in allowed_accounts:
            raise PermissionError(
                f"Live broker order blocked: account '{account_id}' is not in LIVE_EXECUTION_ALLOWED_ACCOUNTS."
            )
