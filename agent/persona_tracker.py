"""
agent/persona_tracker.py
─────────────────────────
Self-Evolving Persona Track Record & Dynamic Conviction Weighting Engine.

Tracks empirical performance metrics (Win Rate, Brier Score, Realized R-Multiple,
Sector/Regime Affinity) for all 13 Specialist Personas. Dynamically calibrates
council ensemble consensus weights based on empirical accuracy.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

from config.paths import app_data_path

MINIMUM_RESOLVED_CALLS_FOR_WEIGHTING = 30
MINIMUM_RESOLVED_CALLS_FOR_CONTEXT = 10


@dataclass
class PersonaTrackRecord:
    persona_id: str
    name: str
    win_rate: float | None
    total_calls: int
    winning_calls: int
    losing_calls: int
    brier_score: float | None
    avg_r_multiple: float | None
    compound_r: float | None
    dynamic_weight_multiplier: float = 1.0
    sector_affinity: dict[str, float] = field(default_factory=dict)
    regime_affinity: dict[str, float] = field(default_factory=dict)
    last_updated: str = ""
    data_status: str = "COLD_START"
    minimum_sample_size: int = MINIMUM_RESOLVED_CALLS_FOR_WEIGHTING


class PersonaTrackerEngine:
    """Manages persistent track records and calculates dynamic weighting multipliers."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            self.db_path = app_data_path("persona_track_records.db")
        else:
            self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS persona_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    persona_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    conviction_score REAL NOT NULL,
                    verdict TEXT NOT NULL,
                    entry_price REAL,
                    target_1 REAL,
                    stop_loss REAL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    exit_price REAL,
                    realized_r REAL,
                    sector TEXT,
                    regime TEXT,
                    notes TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS persona_metrics (
                    persona_id TEXT PRIMARY KEY,
                    win_rate REAL NOT NULL,
                    total_calls INTEGER NOT NULL,
                    winning_calls INTEGER NOT NULL,
                    losing_calls INTEGER NOT NULL,
                    brier_score REAL NOT NULL,
                    avg_r_multiple REAL NOT NULL,
                    compound_r REAL NOT NULL,
                    sector_affinity TEXT,
                    regime_affinity TEXT,
                    last_updated TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def record_recommendation(
        self,
        persona_id: str,
        symbol: str,
        conviction_score: float,
        verdict: str,
        entry_price: float | None = None,
        target_1: float | None = None,
        stop_loss: float | None = None,
        sector: str | None = None,
        regime: str | None = None,
    ) -> int:
        """Store a live persona recommendation."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO persona_calls (
                    persona_id, symbol, timestamp, conviction_score, verdict,
                    entry_price, target_1, stop_loss, sector, regime
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    persona_id.lower(),
                    symbol.upper(),
                    now_iso,
                    conviction_score,
                    verdict.upper(),
                    entry_price,
                    target_1,
                    stop_loss,
                    sector,
                    regime,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0

    def record_trade_outcome(
        self,
        call_id: int,
        status: str,  # 'TARGET_HIT', 'SL_HIT', 'CLOSED'
        exit_price: float,
        realized_r: float,
        notes: str = "",
    ) -> None:
        """Update a recommendation outcome and recompute metrics."""
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE persona_calls
                SET status = ?, exit_price = ?, realized_r = ?, notes = ?
                WHERE id = ?
                """,
                (status.upper(), exit_price, realized_r, notes, call_id),
            )
            conn.commit()

    def get_track_record(
        self,
        persona_id: str,
        sector: str | None = None,
        regime: str | None = None,
    ) -> PersonaTrackRecord:
        """Return metrics calculated solely from recorded, resolved recommendations.

        Until enough outcomes exist, the record deliberately remains in COLD_START
        with a neutral weight.  A named persona is not evidence of historical
        accuracy, and unverified priors must never influence a council vote.
        """
        pid = persona_id.lower()
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT conviction_score, realized_r, sector, regime, timestamp
                FROM persona_calls
                WHERE persona_id = ? AND status != 'PENDING' AND realized_r IS NOT NULL
                """,
                (pid,),
            ).fetchall()

        total_calls = len(rows)
        winning_calls = sum(1 for row in rows if float(row["realized_r"]) > 0)
        losing_calls = total_calls - winning_calls
        if not total_calls:
            return PersonaTrackRecord(
                persona_id=pid,
                name=pid.replace("_", " ").title(),
                win_rate=None,
                total_calls=0,
                winning_calls=0,
                losing_calls=0,
                brier_score=None,
                avg_r_multiple=None,
                compound_r=None,
                last_updated="No resolved outcomes recorded",
            )

        realized_rs = [float(row["realized_r"]) for row in rows]
        win_rate = 100.0 * winning_calls / total_calls
        avg_r = sum(realized_rs) / total_calls
        compound_r = sum(realized_rs)
        # Brier score compares the recorded conviction with the observed binary outcome.
        brier_score = (
            sum(
                (
                    (max(0.0, min(100.0, float(row["conviction_score"]))) / 100.0)
                    - (1.0 if float(row["realized_r"]) > 0 else 0.0)
                )
                ** 2
                for row in rows
            )
            / total_calls
        )

        sector_affinity = self._context_affinity(rows, "sector")
        regime_affinity = self._context_affinity(rows, "regime")
        data_status = (
            "ESTABLISHED"
            if total_calls >= MINIMUM_RESOLVED_CALLS_FOR_WEIGHTING
            else "INSUFFICIENT_SAMPLE"
        )
        final_multiplier = 1.0
        if data_status == "ESTABLISHED":
            # Accuracy and calibration are empirical, clipped to avoid one model
            # dominating a diversified council. Context boosts require their own
            # minimum sample size and are only applied when requested.
            base_multiplier = (win_rate / 50.0) * (1.0 - min(0.5, brier_score))
            context_multiplier = 1.0
            if sector and sector in sector_affinity:
                context_multiplier *= 0.9 + (sector_affinity[sector] * 0.2)
            if regime and regime in regime_affinity:
                context_multiplier *= 0.9 + (regime_affinity[regime] * 0.2)
            final_multiplier = round(max(0.75, min(1.25, base_multiplier * context_multiplier)), 2)

        return PersonaTrackRecord(
            persona_id=pid,
            name=pid.replace("_", " ").title(),
            win_rate=round(win_rate, 1),
            total_calls=total_calls,
            winning_calls=winning_calls,
            losing_calls=losing_calls,
            brier_score=round(brier_score, 3),
            avg_r_multiple=round(avg_r, 2),
            compound_r=round(compound_r, 2),
            dynamic_weight_multiplier=final_multiplier,
            sector_affinity=sector_affinity,
            regime_affinity=regime_affinity,
            last_updated=max(row["timestamp"] for row in rows),
            data_status=data_status,
        )

    @staticmethod
    def _context_affinity(rows: list[sqlite3.Row], field_name: str) -> dict[str, float]:
        """Return empirical win rates only for contexts with adequate outcomes."""
        grouped: dict[str, list[float]] = {}
        for row in rows:
            context = row[field_name]
            if context:
                grouped.setdefault(str(context), []).append(float(row["realized_r"]))
        return {
            context: round(sum(1 for result in outcomes if result > 0) / len(outcomes), 2)
            for context, outcomes in grouped.items()
            if len(outcomes) >= MINIMUM_RESOLVED_CALLS_FOR_CONTEXT
        }

    def get_all_track_records(
        self,
        sector: str | None = None,
        regime: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return track records for all 13 personas."""
        order = [
            "buffett",
            "jhunjhunwala",
            "lynch",
            "soros",
            "munger",
            "forensic",
            "minervini",
            "wyckoff",
            "oneil",
            "taleb",
            "kedia",
            "simons",
            "smc",
        ]
        results = []
        for pid in order:
            rec = self.get_track_record(pid, sector=sector, regime=regime)
            results.append(asdict(rec))
        return results

    def generate_post_mortem(
        self,
        persona_id: str,
        symbol: str,
        outcome_status: str,
        realized_r: float,
        entry_price: float,
        exit_price: float,
        sector: str = "Broad Market",
    ) -> dict[str, Any]:
        """Generate structured trade post-mortem retrospective analysis."""
        pid = persona_id.lower()
        is_win = outcome_status.upper() in ["TARGET_HIT", "WIN", "PROFIT"] or realized_r > 0

        if is_win:
            retrospective_thesis = (
                f"✅ Successful {pid.capitalize()} thesis on {symbol}. Setup captured {realized_r:.1f}R payoff. "
                f"Volume spread confluence and structural momentum in {sector} confirmed institutional sponsorship."
            )
            key_learning = (
                "Trail stop aggressively to breakeven + buffer once 2R milestone is printed."
            )
            rule_reinforcement = "Maintain disciplined position sizing and let winners expand into multi-session markups."
        else:
            retrospective_thesis = (
                f"⚠️ Setup on {symbol} reached invalidation threshold ({realized_r:.1f}R). "
                f"Market structure shifted against thesis or liquidity absorption failed in {sector}."
            )
            key_learning = "Exited cleanly at pre-defined stop loss without emotional hesitation."
            rule_reinforcement = (
                "Never widen invalidation stops or average into underwater positions."
            )

        return {
            "persona_id": pid,
            "symbol": symbol.upper(),
            "outcome_status": outcome_status.upper(),
            "realized_r": realized_r,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "sector": sector,
            "retrospective_thesis": retrospective_thesis,
            "key_learning": key_learning,
            "rule_reinforcement": rule_reinforcement,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# Global singleton instance
_tracker_instance: PersonaTrackerEngine | None = None


def get_persona_tracker() -> PersonaTrackerEngine:
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = PersonaTrackerEngine()
    return _tracker_instance
