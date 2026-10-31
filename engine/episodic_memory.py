# -*- coding: utf-8 -*-
"""
engine/episodic_memory.py
─────────────────────────
Episodic Trade Memory & Reflective Experience Replay (Reflective RAG).

Indexes completed trades and postmortems into a persistent SQLite store
(`data/memory/trade_episodes.db`), capturing full market regime fingerprints
(VIX regime, Dalton day archetype, VPIN toxicity, initial balance status, MFE/MAE).

Before trade execution, queries the most analogous historical market setups
to surface empirical probabilities, expected drawdowns, and actionable trade lessons.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from config.paths import app_data_path
import numpy as np

logger = logging.getLogger("chanakya.engine.episodic_memory")
IST = ZoneInfo("Asia/Kolkata")


@dataclass
class TradeEpisode:
    """Immutable record of an executed trade lifecycle episode."""

    episode_id: str
    session_date: str
    symbol: str
    direction: str  # "LONG" | "SHORT" | "BULLISH" | "BEARISH"
    entry_price: float
    exit_price: float
    stop_loss: float
    target_1: float
    pnl_pts: float
    pnl_pct: float
    r_multiple: float
    mfe_r: float
    mae_r: float
    execution_efficiency: float
    vix_regime: str  # "ULTRA_LOW_IV" | "NORMAL_IV" | "INFLATED_IV" | "TAIL_RISK"
    day_archetype: str  # "TREND_DAY" | "NORMAL_DAY" | "NORMAL_VARIATION_DAY"
    vpin_regime: str  # "LOW_TOXICITY" | "MODERATE_TOXICITY" | "HIGH_TOXICITY" | "EXTREME_TOXICITY"
    holding_duration_mins: float
    exit_reason: str  # "T1_HIT" | "T2_HIT" | "RUNNER_TRAILED" | "STOPPED_OUT" | "BREAKEVEN_EXIT"
    win_loss: str  # "WIN" | "LOSS" | "BREAKEVEN"
    narrative: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AnalogyQueryResult:
    """Statistical summary of top analogous historical setups."""

    symbol: str
    direction: str
    sample_size: int
    win_rate_pct: float
    avg_mfe_r: float
    avg_mae_r: float
    avg_eer: float
    analogous_episodes: list[dict[str, Any]]
    confidence_calibration: str  # "HIGH_CONFIDENCE_SETUP" | "HIGH_MAE_DRAWDOWN_PRONE" | "CHOPPY_REGIME_CAUTION" | "INSUFFICIENT_HISTORY"
    heuristic_recommendation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EpisodicTradeMemoryStore:
    """Thread-safe persistent store for trade episodes and regime analogy queries."""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path:
            self._db_path = Path(db_path)
        else:
            base_dir = app_data_path("memory")
            base_dir.mkdir(parents=True, exist_ok=True)
            self._db_path = base_dir / "trade_episodes.db"

        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS trade_episodes (
                        episode_id TEXT PRIMARY KEY,
                        session_date TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        direction TEXT NOT NULL,
                        entry_price REAL NOT NULL,
                        exit_price REAL NOT NULL,
                        stop_loss REAL NOT NULL,
                        target_1 REAL NOT NULL,
                        pnl_pts REAL NOT NULL,
                        pnl_pct REAL NOT NULL,
                        r_multiple REAL NOT NULL,
                        mfe_r REAL NOT NULL,
                        mae_r REAL NOT NULL,
                        execution_efficiency REAL NOT NULL,
                        vix_regime TEXT NOT NULL,
                        day_archetype TEXT NOT NULL,
                        vpin_regime TEXT NOT NULL,
                        holding_duration_mins REAL NOT NULL,
                        exit_reason TEXT NOT NULL,
                        win_loss TEXT NOT NULL,
                        narrative TEXT,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_episodes_sym ON trade_episodes(symbol)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_episodes_regime ON trade_episodes(vix_regime, day_archetype)"
                )
                conn.commit()
        except Exception as e:
            logger.error(f"[EpisodicMemory] DB init error: {e}", exc_info=True)
        finally:
            conn.close()

    def record_episode(self, ep: TradeEpisode) -> bool:
        """Stores a trade episode into the memory bank."""
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO trade_episodes (
                        episode_id, session_date, symbol, direction, entry_price, exit_price,
                        stop_loss, target_1, pnl_pts, pnl_pct, r_multiple, mfe_r, mae_r,
                        execution_efficiency, vix_regime, day_archetype, vpin_regime,
                        holding_duration_mins, exit_reason, win_loss, narrative, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ep.episode_id,
                        ep.session_date,
                        ep.symbol.upper(),
                        ep.direction.upper(),
                        ep.entry_price,
                        ep.exit_price,
                        ep.stop_loss,
                        ep.target_1,
                        ep.pnl_pts,
                        ep.pnl_pct,
                        ep.r_multiple,
                        ep.mfe_r,
                        ep.mae_r,
                        ep.execution_efficiency,
                        ep.vix_regime,
                        ep.day_archetype,
                        ep.vpin_regime,
                        ep.holding_duration_mins,
                        ep.exit_reason,
                        ep.win_loss,
                        ep.narrative,
                        ep.created_at,
                    ),
                )
                conn.commit()
            return True
        except Exception as e:
            logger.error(
                f"[EpisodicMemory] Failed recording episode {ep.episode_id}: {e}", exc_info=True
            )
            return False
        finally:
            conn.close()

    def query_analogous_episodes(
        self,
        symbol: str,
        direction: str,
        vix_regime: str = "NORMAL_IV",
        day_archetype: str = "NORMAL_DAY",
        vpin_regime: str = "MODERATE_TOXICITY",
        top_k: int = 5,
    ) -> AnalogyQueryResult:
        """
        Retrieves top K most analogous historical setups and computes statistical expectations.
        """
        clean_sym = symbol.upper().replace("NSE:", "").replace(".NS", "").strip()
        norm_dir = "LONG" if direction.upper() in ("LONG", "BULLISH", "BUY", "CE") else "SHORT"

        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM trade_episodes ORDER BY rowid DESC LIMIT 200"
            ).fetchall()
        except Exception as e:
            logger.warning(f"[EpisodicMemory] Query failed: {e}")
            rows = []
        finally:
            conn.close()

        if not rows:
            return AnalogyQueryResult(
                symbol=clean_sym,
                direction=norm_dir,
                sample_size=0,
                win_rate_pct=0.0,
                avg_mfe_r=0.0,
                avg_mae_r=0.0,
                avg_eer=0.0,
                analogous_episodes=[],
                confidence_calibration="INSUFFICIENT_HISTORY",
                heuristic_recommendation="No prior trade episodes recorded under this regime.",
            )

        scored: list[tuple[float, dict[str, Any]]] = []
        for r in rows:
            d = dict(r)
            score = 0.0

            # 1. Exact symbol match (35 pts)
            if d.get("symbol") == clean_sym:
                score += 35.0
            elif clean_sym in ("NIFTY", "BANKNIFTY") and d.get("symbol") in ("NIFTY", "BANKNIFTY"):
                score += 25.0

            # 2. Direction match (20 pts)
            ep_dir = (
                "LONG"
                if str(d.get("direction", "")).upper() in ("LONG", "BULLISH", "BUY", "CE")
                else "SHORT"
            )
            if ep_dir == norm_dir:
                score += 20.0

            # 3. Day archetype match (20 pts)
            if d.get("day_archetype") == day_archetype:
                score += 20.0

            # 4. VIX regime match (15 pts)
            if d.get("vix_regime") == vix_regime:
                score += 15.0

            # 5. VPIN toxicity match (10 pts)
            if d.get("vpin_regime") == vpin_regime:
                score += 10.0

            scored.append((score, d))

        scored.sort(key=lambda x: x[0], reverse=True)
        top_matches = [ep for _, ep in scored[:top_k]]

        wins = sum(1 for ep in top_matches if ep.get("win_loss") == "WIN")
        win_rate = (wins / len(top_matches)) * 100.0 if top_matches else 0.0
        avg_mfe = (
            float(np.mean([ep.get("mfe_r", 0.0) for ep in top_matches])) if top_matches else 0.0
        )
        avg_mae = (
            float(np.mean([ep.get("mae_r", 0.0) for ep in top_matches])) if top_matches else 0.0
        )
        avg_eer = (
            float(np.mean([ep.get("execution_efficiency", 0.0) for ep in top_matches]))
            if top_matches
            else 0.0
        )

        if avg_mae >= 0.70:
            calibration = "HIGH_MAE_DRAWDOWN_PRONE"
            heuristic = (
                f"Historical Analogy Warning: In analogous setups under {day_archetype} / {vix_regime}, "
                f"trades suffered high adverse excursion (avg MAE {avg_mae:.1f}R). Strongly favor limit pullback entry over market chase."
            )
        elif win_rate >= 75.0 and avg_mfe >= 2.0:
            calibration = "HIGH_CONFIDENCE_SETUP"
            heuristic = (
                f"High-Conviction Historical Analogy: {win_rate:.0f}% win rate across {len(top_matches)} similar episodes "
                f"(avg peak MFE +{avg_mfe:.1f}R). Follow runner scaling plan."
            )
        else:
            calibration = "CHOPPY_REGIME_CAUTION"
            heuristic = (
                f"Balanced Analogy: Win rate {win_rate:.0f}%, avg MFE +{avg_mfe:.1f}R, avg MAE {avg_mae:.1f}R. "
                f"Strict adherence to 1.8R breakeven lock is mandatory."
            )

        return AnalogyQueryResult(
            symbol=clean_sym,
            direction=norm_dir,
            sample_size=len(top_matches),
            win_rate_pct=round(win_rate, 1),
            avg_mfe_r=round(avg_mfe, 2),
            avg_mae_r=round(avg_mae, 2),
            avg_eer=round(avg_eer, 3),
            analogous_episodes=top_matches,
            confidence_calibration=calibration,
            heuristic_recommendation=heuristic,
        )


_global_memory_store: Optional[EpisodicTradeMemoryStore] = None


def get_episodic_memory_store() -> EpisodicTradeMemoryStore:
    """Returns singleton instance of EpisodicTradeMemoryStore."""
    global _global_memory_store
    if _global_memory_store is None:
        _global_memory_store = EpisodicTradeMemoryStore()
    return _global_memory_store
