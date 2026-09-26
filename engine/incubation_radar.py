"""
engine/incubation_radar.py
──────────────────────────
Institutional Persistent Cycle Incubation Pipeline & ETA Retention Radar.

Solves the core institutional trader requirement:
  "Find, mark, highlight, and retain candidates as per their ETA or cycle
   so we can execute at the exact right moment without missing the breakout."

Lifecyle Cycle States:
  - "STAGE_1_ACCUMULATION": Stealth base-building, float exhaustion. ETA: 2–6 Weeks.
  - "COILING_PIVOT": Volatility compressed inside Keltner/BB or VCP contraction (<3.5%). ETA: 1–5 Sessions. Stalk closely.
  - "TRIGGER_READY": Breakout underway today (RVOL >= 1.8x, pivot breached). Immediate execution.
  - "PULLBACK_RETEST": Low-volume retest of 20/50 EMA or Order Block. High-asymmetry re-entry.
  - "STAGE_2_MARKUP": Positional trend compounding mode. Trailing stop active.
  - "TARGET_1_ACHIEVED": Risk de-risked at +2R. SL moved to Breakeven (+0.2% costs).
  - "CYCLE_INVALIDATED": Breached invalidation stop. Auto-culled from active radar.

Provides:
  - add_to_incubation(...)
  - get_incubated_candidates(...)
  - remove_from_incubation(...)
  - evaluate_incubated_pipeline(...)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
import sqlite3
import threading
from typing import Any, Optional

logger = logging.getLogger("engine.incubation_radar")

_DB_LOCK = threading.RLock()
_DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "incubation_pipeline.db",
)


@dataclass
class IncubatedCandidate:
    symbol: str
    name: str
    sector: str
    horizon: str  # "SHORT_TERM" | "MID_TERM" | "LONG_TERM"
    cycle_state: str  # "STAGE_1_ACCUMULATION" | "COILING_PIVOT" | "TRIGGER_READY" | "PULLBACK_RETEST" | "STAGE_2_MARKUP" | "TARGET_1_ACHIEVED" | "CYCLE_INVALIDATED"
    eta_days: int
    eta_label: str  # e.g. "TODAY (Trigger Ready)", "2–5 Sessions", "2–4 Weeks"
    entry_pivot: float
    current_price: float
    stop_loss: float
    target_1: float
    target_2: float
    target_moonshot: float
    risk_reward_ratio: float
    conviction_score: int
    primary_archetype: str
    catalyst_badges: list[str] = field(default_factory=list)
    catalyst_summary: str = ""
    added_at: str = ""
    last_evaluated_at: str = ""
    days_in_incubation: int = 0
    user_notes: str = ""
    is_archived: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or _DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS incubation_pipeline (
            symbol TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            sector TEXT NOT NULL,
            horizon TEXT NOT NULL,
            cycle_state TEXT NOT NULL,
            eta_days INTEGER NOT NULL,
            eta_label TEXT NOT NULL,
            entry_pivot REAL NOT NULL,
            current_price REAL NOT NULL,
            stop_loss REAL NOT NULL,
            target_1 REAL NOT NULL,
            target_2 REAL NOT NULL,
            target_moonshot REAL NOT NULL,
            risk_reward_ratio REAL NOT NULL,
            conviction_score INTEGER NOT NULL,
            primary_archetype TEXT NOT NULL,
            catalyst_badges_json TEXT NOT NULL,
            catalyst_summary TEXT,
            added_at TEXT NOT NULL,
            last_evaluated_at TEXT NOT NULL,
            days_in_incubation INTEGER DEFAULT 0,
            user_notes TEXT DEFAULT '',
            is_archived INTEGER DEFAULT 0
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_incubation_state ON incubation_pipeline (cycle_state, horizon)"
    )
    conn.commit()
    return conn


def init_incubation_db(db_path: Optional[str] = None) -> None:
    """Initializes SQLite incubation schema."""
    with _DB_LOCK:
        conn = _get_connection(db_path)
        conn.close()


# Auto-init schema on module load
init_incubation_db()


def add_to_incubation(
    candidate: dict[str, Any] | IncubatedCandidate,
    db_path: Optional[str] = None,
) -> IncubatedCandidate:
    """
    Retains a setup in the persistent cycle incubation pipeline.
    If already existing, updates current metrics while preserving user notes and original added_at.
    """
    if isinstance(candidate, IncubatedCandidate):
        data = candidate.to_dict()
    else:
        data = dict(candidate)

    clean_sym = data["symbol"].upper().replace(".NS", "").replace("NSE:", "").strip()
    now_iso = datetime.now(timezone.utc).isoformat()

    badges = data.get("catalyst_badges") or []
    badges_json = json.dumps(badges if isinstance(badges, list) else [])

    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            # Check existing row
            cur = conn.execute(
                "SELECT added_at, user_notes FROM incubation_pipeline WHERE symbol = ?",
                (clean_sym,),
            )
            row = cur.fetchone()
            added_at = row["added_at"] if row else now_iso
            user_notes = data.get("user_notes") or (row["user_notes"] if row else "")

            conn.execute(
                """
                INSERT INTO incubation_pipeline (
                    symbol, name, sector, horizon, cycle_state, eta_days, eta_label,
                    entry_pivot, current_price, stop_loss, target_1, target_2, target_moonshot,
                    risk_reward_ratio, conviction_score, primary_archetype, catalyst_badges_json,
                    catalyst_summary, added_at, last_evaluated_at, days_in_incubation, user_notes, is_archived
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    name = excluded.name,
                    sector = excluded.sector,
                    horizon = excluded.horizon,
                    cycle_state = excluded.cycle_state,
                    eta_days = excluded.eta_days,
                    eta_label = excluded.eta_label,
                    entry_pivot = excluded.entry_pivot,
                    current_price = excluded.current_price,
                    stop_loss = excluded.stop_loss,
                    target_1 = excluded.target_1,
                    target_2 = excluded.target_2,
                    target_moonshot = excluded.target_moonshot,
                    risk_reward_ratio = excluded.risk_reward_ratio,
                    conviction_score = excluded.conviction_score,
                    primary_archetype = excluded.primary_archetype,
                    catalyst_badges_json = excluded.catalyst_badges_json,
                    catalyst_summary = excluded.catalyst_summary,
                    last_evaluated_at = excluded.last_evaluated_at,
                    user_notes = excluded.user_notes,
                    is_archived = 0
                """,
                (
                    clean_sym,
                    data.get("name", clean_sym),
                    data.get("sector", "Broad Market"),
                    data.get("horizon", "MID_TERM"),
                    data.get("cycle_state", "COILING_PIVOT"),
                    int(data.get("eta_days", 3)),
                    data.get("eta_label", "2–5 Sessions"),
                    float(data.get("entry_pivot", data.get("entry_price", 0.0))),
                    float(data.get("current_price", data.get("ltp", 0.0))),
                    float(data.get("stop_loss", 0.0)),
                    float(data.get("target_1", 0.0)),
                    float(data.get("target_2", 0.0)),
                    float(data.get("target_moonshot", 0.0)),
                    float(data.get("risk_reward_ratio", 2.5)),
                    int(data.get("conviction_score", data.get("inflection_score", 75))),
                    data.get("primary_archetype", "VCP_PIVOT_BREAKOUT"),
                    badges_json,
                    data.get("catalyst_summary", ""),
                    added_at,
                    now_iso,
                    0,
                    user_notes,
                    0,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    return get_incubated_candidate(clean_sym, db_path=db_path)  # type: ignore


def get_incubated_candidate(
    symbol: str, db_path: Optional[str] = None
) -> Optional[IncubatedCandidate]:
    """Retrieves a single candidate from incubation."""
    clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").strip()
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            cur = conn.execute(
                "SELECT * FROM incubation_pipeline WHERE symbol = ?",
                (clean_sym,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return _row_to_candidate(row)
        finally:
            conn.close()


def get_incubated_candidates(
    horizon_filter: Optional[str] = None,
    cycle_state_filter: Optional[str] = None,
    include_archived: bool = False,
    db_path: Optional[str] = None,
) -> list[IncubatedCandidate]:
    """
    Returns list of retained candidates with optional filtering by Horizon or Cycle State.
    """
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            clauses = []
            params: list[Any] = []

            if not include_archived:
                clauses.append("is_archived = 0")

            if horizon_filter and horizon_filter.upper() != "ALL":
                clauses.append("horizon = ?")
                params.append(horizon_filter.upper().strip())

            if cycle_state_filter and cycle_state_filter.upper() != "ALL":
                clauses.append("cycle_state = ?")
                params.append(cycle_state_filter.upper().strip())

            where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            query = f"SELECT * FROM incubation_pipeline {where_sql} ORDER BY conviction_score DESC, eta_days ASC"

            cur = conn.execute(query, tuple(params))
            rows = cur.fetchall()
            return [_row_to_candidate(r) for r in rows]
        finally:
            conn.close()


def remove_from_incubation(
    symbol: str, hard_delete: bool = True, db_path: Optional[str] = None
) -> bool:
    """Removes or archives a candidate from incubation."""
    clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").strip()
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            if hard_delete:
                cur = conn.execute(
                    "DELETE FROM incubation_pipeline WHERE symbol = ?", (clean_sym,)
                )
            else:
                cur = conn.execute(
                    "UPDATE incubation_pipeline SET is_archived = 1 WHERE symbol = ?",
                    (clean_sym,),
                )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def evaluate_incubated_pipeline(
    db_path: Optional[str] = None,
    live_quotes: Optional[dict[str, float]] = None,
) -> dict[str, Any]:
    """
    Evaluates all active candidates in incubation:
      - Calculates days in incubation.
      - Checks trigger condition: if price >= entry_pivot -> promotes to TRIGGER_READY!
      - Checks invalidation: if price < stop_loss -> marks CYCLE_INVALIDATED.
      - Checks target 1: if price >= target_1 -> marks TARGET_1_ACHIEVED.
    Returns audit statistics and newly triggered breakouts.
    """
    candidates = get_incubated_candidates(include_archived=False, db_path=db_path)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    triggered_breakouts: list[str] = []
    invalidated: list[str] = []
    updated_count = 0

    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            for c in candidates:
                # 1. Update days in incubation
                try:
                    added_dt = datetime.fromisoformat(c.added_at)
                    days = max(0, (now - added_dt).days)
                except Exception:
                    days = c.days_in_incubation

                # 2. Get current price
                curr_price = c.current_price
                if live_quotes and c.symbol in live_quotes:
                    curr_price = float(live_quotes[c.symbol])

                new_state = c.cycle_state
                new_eta_days = c.eta_days
                new_eta_label = c.eta_label

                # 3. Check Lifecycle Milestones
                # Case A: Breakout Trigger
                if (
                    curr_price >= c.entry_pivot
                    and c.entry_pivot > 0
                    and c.cycle_state in ("COILING_PIVOT", "STAGE_1_ACCUMULATION")
                ):
                    new_state = "TRIGGER_READY"
                    new_eta_days = 0
                    new_eta_label = "🔥 TODAY (Trigger Ready)"
                    triggered_breakouts.append(c.symbol)

                # Case B: Invalidation Stop
                elif curr_price < c.stop_loss and c.stop_loss > 0:
                    new_state = "CYCLE_INVALIDATED"
                    new_eta_days = 99
                    new_eta_label = "❌ Invalidation Breached"
                    invalidated.append(c.symbol)

                # Case C: Target 1 Reached
                elif curr_price >= c.target_1 and c.target_1 > 0 and c.cycle_state != "TARGET_1_ACHIEVED":
                    new_state = "TARGET_1_ACHIEVED"
                    new_eta_label = "🎯 +2R De-Risked"

                conn.execute(
                    """
                    UPDATE incubation_pipeline SET
                        current_price = ?,
                        cycle_state = ?,
                        eta_days = ?,
                        eta_label = ?,
                        days_in_incubation = ?,
                        last_evaluated_at = ?
                    WHERE symbol = ?
                    """,
                    (
                        curr_price,
                        new_state,
                        new_eta_days,
                        new_eta_label,
                        days,
                        now_iso,
                        c.symbol,
                    ),
                )
                updated_count += 1

            conn.commit()
        finally:
            conn.close()

    return {
        "total_evaluated": len(candidates),
        "updated_count": updated_count,
        "triggered_breakouts": triggered_breakouts,
        "invalidated": invalidated,
        "evaluated_at": now_iso,
    }


def _row_to_candidate(row: sqlite3.Row) -> IncubatedCandidate:
    try:
        badges = json.loads(row["catalyst_badges_json"])
    except Exception:
        badges = []

    return IncubatedCandidate(
        symbol=row["symbol"],
        name=row["name"],
        sector=row["sector"],
        horizon=row["horizon"],
        cycle_state=row["cycle_state"],
        eta_days=row["eta_days"],
        eta_label=row["eta_label"],
        entry_pivot=row["entry_pivot"],
        current_price=row["current_price"],
        stop_loss=row["stop_loss"],
        target_1=row["target_1"],
        target_2=row["target_2"],
        target_moonshot=row["target_moonshot"],
        risk_reward_ratio=row["risk_reward_ratio"],
        conviction_score=row["conviction_score"],
        primary_archetype=row["primary_archetype"],
        catalyst_badges=badges,
        catalyst_summary=row["catalyst_summary"] or "",
        added_at=row["added_at"],
        last_evaluated_at=row["last_evaluated_at"],
        days_in_incubation=row["days_in_incubation"],
        user_notes=row["user_notes"] or "",
        is_archived=bool(row["is_archived"]),
    )
