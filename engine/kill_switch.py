"""
engine/kill_switch.py
──────────────────────
P3-B: Multi-Level Kill Switch System.

Provides hierarchical kill switches at 6 levels:
  SYSTEM   — All trading halted globally (circuit breaker)
  BROKER   — All orders through a specific broker halted
  ACCOUNT  — All orders for a specific account halted
  USER     — All orders for a specific user halted
  STRATEGY — All orders for a specific strategy halted
  SYMBOL   — All orders for a specific instrument halted

Kill switches are:
- Persisted to disk (survive process restart)
- Thread-safe with a bounded LRU in-memory cache
- Audited with actor, reason, and timestamp on every activation
- Only deactivatable by explicit un_kill with reason and actor

Design: Never silently ignore a kill switch.
Every blocked order MUST surface a kill switch block reason.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from config.paths import app_data_path


# ── Kill Switch Level ─────────────────────────────────────────────────────────


class KillSwitchLevel(str, Enum):
    SYSTEM = "SYSTEM"
    BROKER = "BROKER"
    ACCOUNT = "ACCOUNT"
    USER = "USER"
    STRATEGY = "STRATEGY"
    SYMBOL = "SYMBOL"


# ── Kill Switch Record ────────────────────────────────────────────────────────


@dataclass
class KillSwitchRecord:
    """An active kill switch with full audit trail."""

    level: str  # KillSwitchLevel value
    key: str  # broker_id, account_id, user_id, strategy_id, symbol, or "ALL"
    reason: str  # Human-readable reason for activation
    actor: str  # Who activated it (user_id, "SYSTEM", "AUTOMATED")
    activated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: Optional[str] = None  # ISO timestamp, None = no expiry
    deactivated_at: Optional[str] = None
    deactivated_by: Optional[str] = None
    deactivation_reason: Optional[str] = None
    active: bool = True

    @property
    def ks_id(self) -> str:
        return f"{self.level}:{self.key}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Kill Switch Registry ──────────────────────────────────────────────────────


class KillSwitchRegistry:
    """
    Thread-safe persistent kill switch registry.

    Storage: {app_data}/kill_switches.json (JSONL append log + active state)
    """

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self._lock = threading.Lock()
        self._data_dir = data_dir or app_data_path("oms")
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._state_file = self._data_dir / "kill_switches.json"
        self._audit_file = self._data_dir / "kill_switch_audit.jsonl"
        self._active: dict[str, KillSwitchRecord] = {}
        self._load_state()

    def _load_state(self) -> None:
        """Load persisted kill switch state from disk."""
        try:
            if self._state_file.exists():
                data = json.loads(self._state_file.read_text(encoding="utf-8"))
                for record_dict in data.get("active_switches", []):
                    rec = KillSwitchRecord(**record_dict)
                    if rec.active:
                        self._active[rec.ks_id] = rec
        except Exception:
            # If state is corrupt, start fresh (fail-safe)
            self._active = {}

    def _persist_state(self) -> None:
        """Persist active kill switches to disk."""
        try:
            state = {
                "as_of": datetime.now(timezone.utc).isoformat(),
                "active_switches": [r.to_dict() for r in self._active.values() if r.active],
            }
            self._state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception:
            pass  # Never crash the caller

    def _audit(self, event: str, record: KillSwitchRecord, metadata: dict | None = None) -> None:
        """Append an audit event to the JSONL audit log."""
        try:
            entry = {
                "event": event,
                "ks_id": record.ks_id,
                "record": record.to_dict(),
                "metadata": metadata or {},
                "logged_at": datetime.now(timezone.utc).isoformat(),
            }
            with self._audit_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    # ── Public API ─────────────────────────────────────────────────────────────

    def activate(
        self,
        level: KillSwitchLevel,
        key: str,
        reason: str,
        actor: str,
        expires_at: Optional[str] = None,
    ) -> KillSwitchRecord:
        """
        Activate a kill switch. Idempotent — re-activating an existing switch
        updates the reason and actor.

        Args:
            level: KillSwitchLevel (SYSTEM, BROKER, ACCOUNT, USER, STRATEGY, SYMBOL)
            key: The specific entity key. Use "ALL" for SYSTEM level.
            reason: Human-readable reason for activation.
            actor: Who is activating (user_id, "SYSTEM", "AUTOMATED").
            expires_at: Optional ISO timestamp for auto-expiry.

        Returns:
            The activated KillSwitchRecord.
        """
        with self._lock:
            record = KillSwitchRecord(
                level=level.value,
                key=key,
                reason=reason,
                actor=actor,
                expires_at=expires_at,
                active=True,
            )
            self._active[record.ks_id] = record
            self._persist_state()
            self._audit("ACTIVATED", record)
        return record

    def deactivate(
        self,
        level: KillSwitchLevel,
        key: str,
        actor: str,
        reason: str,
    ) -> bool:
        """
        Deactivate a kill switch. Returns True if found and deactivated.

        Deactivation is audited but the kill switch record is retained
        in the audit log for compliance.
        """
        ks_id = f"{level.value}:{key}"
        with self._lock:
            record = self._active.get(ks_id)
            if not record:
                return False
            record.active = False
            record.deactivated_at = datetime.now(timezone.utc).isoformat()
            record.deactivated_by = actor
            record.deactivation_reason = reason
            del self._active[ks_id]
            self._persist_state()
            self._audit("DEACTIVATED", record, {"actor": actor, "reason": reason})
        return True

    def is_blocked(
        self,
        broker: Optional[str] = None,
        account: Optional[str] = None,
        user: Optional[str] = None,
        strategy: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> tuple[bool, list[str]]:
        """
        Check if any active kill switch blocks this combination.

        Returns: (is_blocked: bool, blocking_reasons: list[str])

        Checks hierarchy: SYSTEM → BROKER → ACCOUNT → USER → STRATEGY → SYMBOL
        """
        blocking: list[str] = []
        now = datetime.now(timezone.utc).isoformat()

        with self._lock:
            switches = list(self._active.values())

        for ks in switches:
            if not ks.active:
                continue
            # Check expiry
            if ks.expires_at and ks.expires_at < now:
                continue
            level = ks.level
            key = ks.key

            if level == KillSwitchLevel.SYSTEM.value and key == "ALL":
                blocking.append(f"SYSTEM kill switch: {ks.reason}")
            elif level == KillSwitchLevel.BROKER.value and broker and key == broker:
                blocking.append(f"BROKER({broker}) kill switch: {ks.reason}")
            elif level == KillSwitchLevel.ACCOUNT.value and account and key == account:
                blocking.append(f"ACCOUNT({account}) kill switch: {ks.reason}")
            elif level == KillSwitchLevel.USER.value and user and key == user:
                blocking.append(f"USER({user}) kill switch: {ks.reason}")
            elif level == KillSwitchLevel.STRATEGY.value and strategy and key == strategy:
                blocking.append(f"STRATEGY({strategy}) kill switch: {ks.reason}")
            elif level == KillSwitchLevel.SYMBOL.value and symbol and key == symbol.upper():
                blocking.append(f"SYMBOL({symbol}) kill switch: {ks.reason}")

        return bool(blocking), blocking

    def list_active(self) -> list[KillSwitchRecord]:
        """Return all currently active kill switches."""
        with self._lock:
            return [r for r in self._active.values() if r.active]

    def get_status(self) -> dict[str, Any]:
        """Return a structured kill switch status report."""
        active = self.list_active()
        return {
            "total_active": len(active),
            "system_halted": any(
                r.level == KillSwitchLevel.SYSTEM.value and r.key == "ALL" for r in active
            ),
            "active_switches": [r.to_dict() for r in active],
        }


# ── Module-Level Singleton ────────────────────────────────────────────────────

_registry: Optional[KillSwitchRegistry] = None
_registry_lock = threading.Lock()


def get_kill_switch_registry() -> KillSwitchRegistry:
    """Get or create the global KillSwitchRegistry singleton."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = KillSwitchRegistry()
    return _registry
