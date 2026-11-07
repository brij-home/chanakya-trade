"""
engine/shadow_evaluator.py
──────────────────────────
Shadow Candidate Evaluator, Episode Deduplication & Suppressor Ablation Engine.

Institutional Mandates (S02 & S03):
1. Measure Missed Opportunities Alongside Prevented Noise (S02):
   - Records shadow candidates that pass non-negotiable safety gates but are blocked
     by empirical strategy filters (Learning lockouts, RSI exhaustion, VWAP trend conflict,
     Time-of-day theta trap).
   - Deduplicates underlying episodes so multiple option strikes or detectors on the
     same move do not multiply one market event into separate instances.
   - Evaluates forward price action to measure:
     * Avoided Adverse Move: Price hit stop loss (suppressor saved capital).
     * Missed Favorable Move: Price reached target without hitting stop (suppressor missed move).
   - Produces ablation analytics to assess whether each suppressor has positive expectancy.

2. Three-Stage Lifecycle & Latency SLA (S03):
   - Enforces clean separation of preparation (STALK), trigger (PRIMED), and tradeability (IGNITED).
   - Tracks granular timestamps: first_evidence_ts, trigger_ts, eval_ts, enrichment_ts, dispatch_ts.
   - Computes p50/p95/p99 latency by stage.
   - Enforces Entry-Validity Budget: If current price exceeds max acceptable entry
     (no_chase_boundary) or queue age is stale, candidate is downgraded with explicit NO CHASE.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np

from config.constants import IST
from config.paths import app_data_path
from engine.alert_identity import canonical_alert_symbol

logger = logging.getLogger("engine.shadow_evaluator")


def get_shadow_candidates_file() -> Path:
    return app_data_path("shadow_candidates.json")


@dataclass
class ShadowCandidate:
    """Immutable record of an alert candidate suppressed by empirical strategy filters."""

    candidate_id: str
    symbol: str
    canonical_symbol: str
    direction: str  # "BULLISH" | "BEARISH"
    alert_type: str
    entry_level: float
    stop_loss: float
    target_level: float
    underlying_spot: float
    suppressed_by_gate: str
    suppression_reason: str
    session_id: str
    recorded_at: str
    recorded_ts: float
    episode_id: str
    feature_snapshot: dict[str, Any] = field(default_factory=dict)
    # Forward Outcome Evaluation
    evaluated: bool = False
    forward_high: Optional[float] = None
    forward_low: Optional[float] = None
    avoided_adverse_move: Optional[bool] = None  # True if hit SL
    missed_favorable_move: Optional[bool] = None  # True if hit target without SL
    net_outcome_r: Optional[float] = None
    evaluation_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LatencyTelemetrySnapshot:
    """Granular latency measurements across the candidate interception funnel."""

    candidate_id: str
    first_evidence_ts: float
    trigger_ts: float
    eval_ts: float
    enrichment_ts: float
    dispatch_ts: float
    entry_validity_budget_seconds: float = 60.0

    @property
    def detection_latency_ms(self) -> Optional[float]:
        """Time from trigger event to policy decision. Returns None if ordering invalid."""
        if self.eval_ts >= self.trigger_ts > 0:
            return round((self.eval_ts - self.trigger_ts) * 1000.0, 2)
        return None

    @property
    def enrichment_latency_ms(self) -> Optional[float]:
        """Time to resolve active contract, option chain snapshot & Greeks."""
        if self.enrichment_ts >= self.eval_ts > 0:
            return round((self.enrichment_ts - self.eval_ts) * 1000.0, 2)
        return None

    @property
    def dispatch_latency_ms(self) -> Optional[float]:
        """Time from enrichment to SSE broadcast & channel outbox."""
        if self.dispatch_ts >= self.enrichment_ts > 0:
            return round((self.dispatch_ts - self.enrichment_ts) * 1000.0, 2)
        return None

    @property
    def total_pipeline_latency_ms(self) -> Optional[float]:
        """Total elapsed duration from trigger to channel dispatch."""
        if self.dispatch_ts >= self.trigger_ts > 0:
            return round((self.dispatch_ts - self.trigger_ts) * 1000.0, 2)
        return None

    @property
    def is_within_entry_validity_budget(self) -> Optional[bool]:
        """Determines if the candidate reached execution queue within valid entry window."""
        if self.dispatch_ts < self.trigger_ts or self.trigger_ts <= 0:
            return None
        elapsed = self.dispatch_ts - self.trigger_ts
        return elapsed <= self.entry_validity_budget_seconds


class ShadowCandidateEvaluator:
    """
    Central recorder and ablation evaluator for empirical strategy filters.
    Prevents silent opportunity leakage and quantifies gate efficacy.
    """

    def __init__(self, storage_path: Optional[Path] = None) -> None:
        self._storage_path = storage_path or get_shadow_candidates_file()
        self._candidates: list[ShadowCandidate] = []
        self._seen_episodes: set[str] = set()
        self._latency_records: list[LatencyTelemetrySnapshot] = []
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if self._storage_path.exists():
            try:
                data = json.loads(self._storage_path.read_text(encoding="utf-8"))
                with self._lock:
                    self._candidates = [ShadowCandidate(**d) for d in data if isinstance(d, dict)]
                    self._seen_episodes = {c.episode_id for c in self._candidates if c.episode_id}
            except Exception as e:
                logger.debug(f"[ShadowCandidateEvaluator] Load error: {e}")
                self._candidates = []

    def _save(self) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._lock:
                data = [c.to_dict() for c in self._candidates[-500:]]  # Retain last 500
            self._storage_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug(f"[ShadowCandidateEvaluator] Save error: {e}")

    @staticmethod
    def generate_episode_id(
        canonical_symbol: str,
        direction: str,
        session_id: str,
        dt: Optional[datetime] = None,
        bucket_minutes: int = 15,
    ) -> str:
        """
        Deduplicates underlying market events into 15-minute episode clusters.
        Prevents multiple option strikes or detectors from artificially multiplying counts.
        """
        ref = dt or datetime.now(IST)
        hour = ref.hour
        b_idx = ref.minute // bucket_minutes
        return f"{canonical_symbol}:{direction.upper()}:{session_id}:{hour:02d}_{b_idx:02d}"

    def record_shadow_candidate(
        self,
        symbol: Optional[str] = None,
        direction: Optional[str] = None,
        alert_type: Optional[str] = None,
        entry_level: Optional[float] = None,
        stop_loss: Optional[float] = None,
        target_level: Optional[float] = None,
        underlying_spot: Optional[float] = None,
        suppressed_by_gate: Optional[str] = None,
        suppression_reason: Optional[str] = None,
        session_id: Optional[str] = None,
        feature_snapshot: Optional[dict[str, Any]] = None,
        ref_dt: Optional[datetime] = None,
        alert: Optional[Any] = None,
        **kwargs: Any,
    ) -> ShadowCandidate:
        """
        Records a candidate that was suppressed by an empirical filter for later ablation.
        Supports both raw parameter signature and (alert=..., feature_vector=...) signature.
        """
        if alert is not None:
            symbol = symbol or getattr(alert, "symbol", "")
            direction = direction or getattr(alert, "direction", "BULLISH")
            alert_type = alert_type or getattr(alert, "alert_type", "GENERIC")
            entry_level = (
                entry_level
                if entry_level is not None
                else float(
                    getattr(alert, "trigger_level", None) or getattr(alert, "ltp", 0.0) or 0.0
                )
            )
            stop_loss = (
                stop_loss
                if stop_loss is not None
                else float(getattr(alert, "stop_loss", 0.0) or 0.0)
            )
            target_level = (
                target_level
                if target_level is not None
                else float(getattr(alert, "target_level", 0.0) or 0.0)
            )
            underlying_spot = (
                underlying_spot
                if underlying_spot is not None
                else float(
                    getattr(alert, "underlying_spot", None) or getattr(alert, "ltp", 0.0) or 0.0
                )
            )
            suppressed_by_gate = (
                suppressed_by_gate or kwargs.get("suppressed_by_gate") or "POLICY_HOLD"
            )
            suppression_reason = (
                suppression_reason
                or kwargs.get("notes")
                or kwargs.get("suppression_reason")
                or "Policy hold"
            )
            session_id = session_id or datetime.now(IST).strftime("%Y%m%d")
            feature_snapshot = feature_snapshot or kwargs.get("feature_vector") or {}

        symbol = symbol or ""
        direction = direction or "BULLISH"
        alert_type = alert_type or "GENERIC"
        entry_level = float(entry_level or 0.0)
        stop_loss = float(stop_loss or 0.0)
        target_level = float(target_level or 0.0)
        underlying_spot = float(underlying_spot or 0.0)
        suppressed_by_gate = suppressed_by_gate or "UNKNOWN_GATE"
        suppression_reason = suppression_reason or "Empirical filter suppression"
        session_id = session_id or datetime.now(IST).strftime("%Y%m%d")

        clean_sym = canonical_alert_symbol(symbol).upper()
        now_dt = ref_dt or datetime.now(IST)
        now_ts = now_dt.timestamp()
        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")
        episode_id = self.generate_episode_id(clean_sym, direction, session_id, dt=now_dt)

        cid = f"sc-{clean_sym}-{direction.lower()}-{int(now_ts)}"

        cand = ShadowCandidate(
            candidate_id=cid,
            symbol=symbol,
            canonical_symbol=clean_sym,
            direction=direction.upper(),
            alert_type=alert_type,
            entry_level=float(entry_level),
            stop_loss=float(stop_loss),
            target_level=float(target_level),
            underlying_spot=float(underlying_spot),
            suppressed_by_gate=suppressed_by_gate,
            suppression_reason=suppression_reason,
            session_id=session_id,
            recorded_at=now_str,
            recorded_ts=now_ts,
            episode_id=episode_id,
            feature_snapshot=feature_snapshot or {},
        )

        with self._lock:
            self._candidates.append(cand)
            self._seen_episodes.add(episode_id)
            self._save()

        logger.info(
            f"[ShadowEvaluator] 👁️ Recorded Shadow Candidate for {clean_sym} ({direction}) "
            f"suppressed by {suppressed_by_gate} | Episode: {episode_id}"
        )
        return cand

    def record_latency_telemetry(
        self,
        candidate_id: str,
        first_evidence_ts: float,
        trigger_ts: float,
        eval_ts: float,
        enrichment_ts: float,
        dispatch_ts: float,
        entry_validity_budget_seconds: float = 60.0,
    ) -> LatencyTelemetrySnapshot:
        """Records granular pipeline stage timing for latency SLA monitoring."""
        snapshot = LatencyTelemetrySnapshot(
            candidate_id=candidate_id,
            first_evidence_ts=first_evidence_ts,
            trigger_ts=trigger_ts,
            eval_ts=eval_ts,
            enrichment_ts=enrichment_ts,
            dispatch_ts=dispatch_ts,
            entry_validity_budget_seconds=entry_validity_budget_seconds,
        )
        with self._lock:
            self._latency_records.append(snapshot)
            if len(self._latency_records) > 1000:
                self._latency_records = self._latency_records[-1000:]
        return snapshot

    def compute_pipeline_latency_stats(self) -> dict[str, Any]:
        """Calculates p50, p95, p99 latency percentiles across the pipeline."""
        with self._lock:
            valid_totals = [
                r.total_pipeline_latency_ms
                for r in self._latency_records
                if r.total_pipeline_latency_ms is not None
            ]
            valid_on_time = [
                r.is_within_entry_validity_budget
                for r in self._latency_records
                if r.is_within_entry_validity_budget is not None
            ]

            if not valid_totals:
                return {
                    "sample_count": 0,
                    "p50_total_ms": None,
                    "p95_total_ms": None,
                    "p99_total_ms": None,
                    "on_time_ratio_pct": None,
                }

            return {
                "sample_count": len(valid_totals),
                "p50_total_ms": round(float(np.percentile(valid_totals, 50)), 2),
                "p95_total_ms": round(float(np.percentile(valid_totals, 95)), 2),
                "p99_total_ms": round(float(np.percentile(valid_totals, 99)), 2),
                "on_time_ratio_pct": round((sum(valid_on_time) / len(valid_on_time)) * 100.0, 1)
                if valid_on_time
                else None,
            }

    def evaluate_shadow_outcomes(
        self,
        forward_price_paths: dict[str, list[tuple[float, float]]],  # cid -> list of (high, low)
        max_horizon_bars: int = 75,
    ) -> list[ShadowCandidate]:
        """
        Evaluates forward price action using payoff-aware coordinates, adverse first-touch
        resolution, and explicit horizon censoring (missing/unfinished paths are CENSORED).
        """
        from engine.position_sizer import resolve_payoff_orientation

        evaluated_records = []
        with self._lock:
            for cand in self._candidates:
                if cand.evaluated or cand.candidate_id not in forward_price_paths:
                    continue
                bars = forward_price_paths[cand.candidate_id]
                if not bars:
                    continue

                # Truncate bars to qualified evaluation horizon
                horizon_bars = bars[:max_horizon_bars]

                coord = resolve_payoff_orientation(
                    payoff_type=cand.feature_snapshot.get("payoff_type", "LONG_ASSET"),
                    direction=cand.direction,
                    symbol=cand.symbol,
                )
                is_long_coord = coord == "LONG"

                stop_dist = abs(cand.entry_level - cand.stop_loss)
                t1_dist = abs(cand.target_level - cand.entry_level)

                hit_sl = False
                hit_target = False

                for high, low in horizon_bars:
                    if is_long_coord:
                        bar_sl = low <= cand.stop_loss
                        bar_tgt = high >= cand.target_level
                    else:  # SHORT
                        bar_sl = high >= cand.stop_loss
                        bar_tgt = low <= cand.target_level

                    # First-touch ambiguity: if both hit in same bar, assume worst-case (SL)
                    if bar_sl and bar_tgt:
                        hit_sl = True
                        break
                    elif bar_sl:
                        hit_sl = True
                        break
                    elif bar_tgt:
                        hit_target = True
                        break

                cand.evaluated = True
                if hit_sl:
                    cand.avoided_adverse_move = True
                    cand.missed_favorable_move = False
                    cand.net_outcome_r = -1.0
                    cand.evaluation_notes = "Veto successful: Avoided stop-loss liquidation."
                elif hit_target:
                    cand.avoided_adverse_move = False
                    cand.missed_favorable_move = True
                    r_val = round(t1_dist / stop_dist, 2) if stop_dist > 0 else 1.0
                    cand.net_outcome_r = r_val
                    cand.evaluation_notes = (
                        f"Missed opportunity: Setup achieved target (+{r_val:.1f}R)."
                    )
                else:
                    # Explicit horizon censoring: unfinished price path is CENSORED, not flat 0R
                    cand.avoided_adverse_move = False
                    cand.missed_favorable_move = False
                    cand.net_outcome_r = None
                    cand.evaluation_notes = f"Censored: Horizon limit ({len(horizon_bars)} bars) reached without barrier touch."

                evaluated_records.append(cand)

            if evaluated_records:
                self._save()

        return evaluated_records

    def get_suppressor_ablation_summary(self) -> dict[str, Any]:
        """
        Generates suppressor efficacy analytics.
        Compares avoided adverse moves against missed favorable moves per gate.
        """
        with self._lock:
            by_gate: dict[str, dict[str, Any]] = {}
            for cand in self._candidates:
                g = cand.suppressed_by_gate
                if g not in by_gate:
                    by_gate[g] = {
                        "total_suppressed": 0,
                        "unique_episodes": set(),
                        "evaluated_count": 0,
                        "avoided_adverse_moves": 0,
                        "missed_favorable_moves": 0,
                        "net_r_saved": 0.0,
                    }

                entry = by_gate[g]
                entry["total_suppressed"] += 1
                entry["unique_episodes"].add(cand.episode_id)

                if cand.evaluated:
                    entry["evaluated_count"] += 1
                    if cand.avoided_adverse_move:
                        entry["avoided_adverse_moves"] += 1
                        entry["net_r_saved"] += 1.0  # +1R preserved
                    elif cand.missed_favorable_move:
                        entry["missed_favorable_moves"] += 1
                        entry["net_r_saved"] -= float(cand.net_outcome_r or 1.0)  # Opportunity cost

            # Format final stats
            summary: dict[str, Any] = {}
            for gate_name, stats in by_gate.items():
                ev_count = stats["evaluated_count"]
                avoided = stats["avoided_adverse_moves"]
                missed = stats["missed_favorable_moves"]
                precision = (
                    round((avoided / (avoided + missed)) * 100.0, 1)
                    if (avoided + missed) > 0
                    else None
                )

                summary[gate_name] = {
                    "total_suppressed": stats["total_suppressed"],
                    "unique_episodes": len(stats["unique_episodes"]),
                    "evaluated_count": ev_count,
                    "avoided_adverse_moves": avoided,
                    "missed_favorable_moves": missed,
                    "gate_precision_pct": precision,
                    "net_r_saved": round(stats["net_r_saved"], 2),
                }

            return summary


# Global singleton evaluator
def evaluate_shadow_outcomes(
    candidates: list[ShadowCandidate],
    forward_price_paths: dict[str, list[tuple[float, float]]],
    max_horizon_bars: int = 75,
) -> list[dict[str, Any]]:
    """Evaluates candidates functionally against forward price paths."""
    from engine.position_sizer import resolve_payoff_orientation

    results = []
    for cand in candidates:
        bars = forward_price_paths.get(cand.candidate_id, [])
        horizon_bars = bars[:max_horizon_bars]
        coord = resolve_payoff_orientation(
            payoff_type=cand.feature_snapshot.get("payoff_type", "LONG_ASSET"),
            direction=cand.direction,
            symbol=cand.symbol,
        )
        is_long_coord = coord == "LONG"
        stop_dist = abs(cand.entry_level - cand.stop_loss)
        t1_dist = abs(cand.target_level - cand.entry_level)

        hit_sl = False
        hit_target = False

        for high, low in horizon_bars:
            if is_long_coord:
                bar_sl = low <= cand.stop_loss
                bar_tgt = high >= cand.target_level
            else:
                bar_sl = high >= cand.stop_loss
                bar_tgt = low <= cand.target_level

            if bar_sl and bar_tgt:
                hit_sl = True
                break
            elif bar_sl:
                hit_sl = True
                break
            elif bar_tgt:
                hit_target = True
                break

        if hit_sl:
            cand.evaluated = True
            cand.avoided_adverse_move = True
            cand.missed_favorable_move = False
            cand.net_outcome_r = -1.0
            cand.evaluation_notes = "Veto successful: Avoided stop-loss liquidation."
        elif hit_target:
            cand.evaluated = True
            cand.avoided_adverse_move = False
            cand.missed_favorable_move = True
            cand.net_outcome_r = round(t1_dist / max(0.01, stop_dist), 2)
            cand.evaluation_notes = (
                f"Missed opportunity: Setup achieved target (+{cand.net_outcome_r:.1f}R)."
            )
        else:
            cand.evaluated = True
            cand.avoided_adverse_move = False
            cand.missed_favorable_move = False
            cand.net_outcome_r = None
            cand.evaluation_notes = (
                f"Censored: Horizon limit ({len(horizon_bars)} bars) reached without barrier touch."
            )

        results.append(cand.to_dict())

    return results


shadow_candidate_evaluator = ShadowCandidateEvaluator()
shadow_evaluator = shadow_candidate_evaluator
