"""
engine/learning_engine.py
─────────────────────────
Autonomous Pattern Learning & Deciding Factor Adaptation Engine.

Learns from historical and newly occurring explosive market movements
(e.g., ADANIENT +5% surge, DIXON, TRENT, HAL) by extracting pre-blast
factor fingerprints and dynamically recalibrating decisive entry signals.

Key Capabilities:
  1. Backwards Attribution & Factor Extraction:
     - Prior-day Volume Dry-Up ratio (Minervini VCP / Wyckoff "No Supply" test).
     - Options Open Interest capitulation (negative Call ΔOI + turnover).
     - TTM Squeeze compression duration & Keltner band coiling.
     - Proximity to institutional Bullish Order Blocks & Swing Lows.
     - JdK Sector Relative Rotation Graph (RRG) momentum quadrant.
     - Breakout coiling pivot high level.
  2. Autonomous Market Mover Scanning & Ingestion:
     - Continuously scans active market universe for large breakouts (>= 3.8% with RVOL >= 1.6x).
     - Automatically reconstructs pre-blast state, extracts fingerprints, and updates memory.
  3. Pattern Memory & Closed-Loop Outcome Ledger:
     - Persists archetypes in ~/.trading_platform/pattern_memory.json.
     - Persists forward trade outcomes (T1, T2, SL) in ~/.trading_platform/pattern_outcomes.json.
  4. Real-Time Fingerprint Similarity Matcher:
     - Evaluates live candidates against learned archetypes to detect explosive setups
       *before* the breakout candle runs away.
     - Emits Match Score (0–100%) and Deciding Factor Attribution for actionable alerts.
  5. Adaptive Factor Weight Recalibration:
     - Computes empirical factor importance based on historical hit rate and R:R payoff.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional
import time
import threading

import numpy as np
import pandas as pd

logger = logging.getLogger("engine.learning_engine")

from config.constants import IST
from config.paths import app_data_path


def get_pattern_memory_file() -> Path:
    return app_data_path("pattern_memory.json")


def get_pattern_outcomes_file() -> Path:
    return app_data_path("pattern_outcomes.json")


def get_pattern_post_mortems_file() -> Path:
    return app_data_path("invalidation_post_mortems.json")


def get_pattern_lockouts_file() -> Path:
    return app_data_path("symbol_lockouts.json")


@dataclass
class InvalidationPostMortem:
    """Forensic retrospective post-mortem on an invalidated alert or stopped-out trade."""

    alert_id: str
    symbol: str
    direction: str
    alert_type: str
    entry_price: float
    stop_loss: float
    exit_price: float
    loss_pts: float
    loss_pct: float
    realized_r: float
    primary_failure_reason: str
    missed_signals: list[str] = field(default_factory=list)
    root_cause_analysis: str = ""
    corrective_actions: list[str] = field(default_factory=list)
    metrics_snapshot: dict[str, Any] = field(default_factory=dict)
    invalidated_at: str = ""

    def __post_init__(self) -> None:
        if not self.invalidated_at:
            self.invalidated_at = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExplosiveMoveFingerprint:
    """Quantitative footprint of a stock right before giving an explosive move."""

    symbol: str
    date: str
    move_pct: float
    rvol_surge: float
    prior_vol_ratio: Optional[float]  # None means unavailable, not neutral
    squeeze_bars: Optional[int]
    ce_unwind_pct: Optional[float]
    ob_distance_pct: Optional[float]  # None means no verified structural level
    rrg_quadrant: Optional[str]  # "LEADING" | "IMPROVING" | "WEAKENING" | "LAGGING"
    structural_rr: Optional[float]
    key_catalyst: str
    fingerprint_score: Optional[int] = None
    coiling_pivot_high: Optional[float] = None
    sepa_qualified: Optional[bool] = None
    provenance: str = "LEGACY_UNVERIFIED"
    source_data_source: Optional[str] = None
    source_provider: Optional[str] = None
    source_snapshot_id: Optional[str] = None
    source_reproducible: bool = False
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PatternTradeOutcome:
    """Alert-path event; it is not account P&L or a verified broker fill."""

    alert_id: str
    symbol: str
    archetype: str
    entry_price: Optional[float]
    exit_price: Optional[float]
    outcome: str  # "WIN_T1" | "WIN_T2" | "STOPPED_OUT" | "EXPIRED"
    realized_rr: Optional[float]
    factors_present: list[str] = field(default_factory=list)
    provenance: str = "LEGACY_UNVERIFIED"
    recorded_at: str = ""

    def __post_init__(self) -> None:
        if not self.recorded_at:
            self.recorded_at = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PatternMatchResult:
    symbol: str
    similarity_score: int  # 0 to 100
    closest_archetype: Optional[str]  # e.g. "ADANIENT (2026-09-09)"
    matched_factors: list[str]
    is_explosive_candidate: bool
    recommended_entry_action: str
    expected_asymmetry_rr: Optional[float]
    coiling_pivot_high: Optional[float] = None


class PatternLearningEngine:
    """
    Continuous self-learning engine that logs explosive moves,
    extracts deciding factors, and recalibrates pre-breakout detection.
    """

    def __init__(
        self,
        clock: Optional[Callable[[], float]] = None,
        refractory_seconds: float = 900.0,
    ) -> None:
        self._clock: Callable[[], float] = clock or time.time
        self.refractory_seconds: float = refractory_seconds
        self._fingerprints: list[ExplosiveMoveFingerprint] = []
        self._outcomes: list[PatternTradeOutcome] = []
        self._post_mortems: list[InvalidationPostMortem] = []
        self._lockouts: dict[str, dict[str, Any]] = {}  # "SYMBOL:DIRECTION" -> lockout
        self._symbol_lockouts: dict[str, dict[str, Any]] = {}  # legacy alias
        self._session_trap_pivots: dict[str, list[dict[str, Any]]] = {}
        self._invalidation_counts: dict[str, int] = {}  # symbol:direction -> count today
        self._processed_invalidation_events: set[str] = set()
        self._lock = threading.RLock()
        self._factor_weights: dict[str, int] = {
            "volume_dry_up": 25,
            "squeeze_coiling": 20,
            "ce_unwind": 20,
            "order_block_anchor": 15,
            "sector_tailwind": 10,
        }
        self._outcome_calibration_status = "UNAVAILABLE_NO_VERIFIED_EXECUTION_LEDGER"
        self._factor_weight_source = "STATIC_BASELINE"
        self._load()
        self._load_outcomes()
        self._load_post_mortems()
        self._load_lockouts()
        self._recalculate_factor_weights()

    # ── Persistence ──────────────────────────────────────────

    def _load(self) -> None:
        p = get_pattern_memory_file()
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                self._fingerprints = [
                    ExplosiveMoveFingerprint(**d) for d in data if isinstance(d, dict)
                ]
            except Exception as e:
                logger.debug(f"[PatternLearningEngine] Failed to load memory: {e}")
                self._fingerprints = []

    def _save(self) -> None:
        p = get_pattern_memory_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = [f.to_dict() for f in self._fingerprints]
            p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug(f"[PatternLearningEngine] Failed to save memory: {e}")

    def _load_outcomes(self) -> None:
        p = get_pattern_outcomes_file()
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                loaded: list[PatternTradeOutcome] = []
                seen_ids: set[str] = set()
                for d in data:
                    if isinstance(d, dict):
                        # Canonicalize legacy INVALIDATED_ prefixes
                        if "archetype" in d and str(d["archetype"]).startswith("INVALIDATED_"):
                            d["archetype"] = str(d["archetype"]).replace("INVALIDATED_", "")
                        aid = d.get("alert_id")
                        if aid:
                            if aid in seen_ids:
                                continue
                            seen_ids.add(aid)
                        loaded.append(PatternTradeOutcome(**d))
                self._outcomes = loaded
            except Exception as e:
                logger.debug(f"[PatternLearningEngine] Failed to load outcomes: {e}")
                self._outcomes = []

    def _save_outcomes(self) -> None:
        p = get_pattern_outcomes_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = [o.to_dict() for o in self._outcomes]
            p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug(f"[PatternLearningEngine] Failed to save outcomes: {e}")

    def _load_post_mortems(self) -> None:
        p = get_pattern_post_mortems_file()
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                self._post_mortems = [
                    InvalidationPostMortem(**d) for d in data if isinstance(d, dict)
                ]
            except Exception as e:
                logger.debug(f"[PatternLearningEngine] Failed to load post mortems: {e}")
                self._post_mortems = []

    def _save_post_mortems(self) -> None:
        p = get_pattern_post_mortems_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = [pm.to_dict() for pm in self._post_mortems[:100]]
            p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug(f"[PatternLearningEngine] Failed to save post mortems: {e}")

    def _load_lockouts(self) -> None:
        p = get_pattern_lockouts_file()
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                now = self._clock()
                now_dt = datetime.fromtimestamp(now, tz=IST)
                curr_session = now_dt.strftime("%Y%m%d")
                with self._lock:
                    self._lockouts = {}
                    self._symbol_lockouts = {}
                    for k, item in data.items():
                        if not isinstance(item, dict):
                            continue
                        if item.get("expires_at", 0) <= now:
                            continue
                        if item.get("session_id") and item.get("session_id") != curr_session:
                            continue
                        self._lockouts[k] = item
                        sym = item.get("symbol")
                        if sym:
                            self._symbol_lockouts[sym] = item
            except Exception as e:
                logger.debug(f"[PatternLearningEngine] Failed to load lockouts: {e}")

    def _save_lockouts(self) -> None:
        p = get_pattern_lockouts_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._lock:
                data = dict(self._lockouts)
            p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug(f"[PatternLearningEngine] Failed to save lockouts: {e}")

    # ── Closed-Loop Feedback & Dynamic Factor Recalibration ───

    def record_trade_outcome(
        self,
        alert_id: str,
        symbol: str,
        archetype: str,
        entry_price: float,
        exit_price: float,
        outcome: str,
        realized_rr: float,
        factors_present: Optional[list[str]] = None,
        provenance: str = "ALERT_MILESTONE_OBSERVATION",
    ) -> PatternTradeOutcome:
        """
        Records an alert-path milestone for audit and controlled research.
        It is not an account fill or realized P&L observation.
        Deduplicates in-place by alert_id to prevent inflated outcomes (Rule 16 & Rule 17).
        """
        if not alert_id or not symbol or not archetype:
            raise ValueError("Alert outcome requires alert_id, symbol and archetype.")
        numeric_values = (float(entry_price), float(exit_price), float(realized_rr))
        if not all(math.isfinite(value) for value in numeric_values):
            raise ValueError("Alert outcome values must be finite.")
        if numeric_values[0] <= 0 or numeric_values[1] <= 0:
            raise ValueError("Alert outcome requires positive entry and exit price observations.")
        if provenance not in (
            "ALERT_MILESTONE_OBSERVATION",
            "ALERT_FORWARD_PATH_INVALIDATION",
            "TEST",
        ):
            raise ValueError("Unsupported alert outcome provenance.")
        clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").strip()
        canonical_archetype = archetype.replace("INVALIDATED_", "").strip()
        rec = PatternTradeOutcome(
            alert_id=alert_id,
            symbol=clean_sym,
            archetype=canonical_archetype,
            entry_price=round(numeric_values[0], 2),
            exit_price=round(numeric_values[1], 2),
            outcome=outcome,
            realized_rr=round(numeric_values[2], 2),
            factors_present=factors_present or [],
            provenance=provenance,
        )

        # Deduplication Guard (Rule 16 & Rule 17):
        # Update existing outcome in-place if alert_id is already recorded
        existing_idx = next(
            (i for i, o in enumerate(self._outcomes) if o.alert_id == alert_id),
            None,
        )
        if existing_idx is not None:
            self._outcomes[existing_idx] = rec
        else:
            self._outcomes.append(rec)

        self._save_outcomes()
        self._recalculate_factor_weights()
        logger.info(
            "[PatternLearningEngine] Recorded alert-path event for %s (%s): %s "
            "(observed R=%s, provenance=%s)",
            clean_sym,
            canonical_archetype,
            outcome,
            f"{numeric_values[2]:.2f}",
            provenance,
        )
        return rec

    def invalidate_alert_outcomes(self, alert_id: str, reason: str = "") -> int:
        """
        Invalidates alert-path events and clears any terminal R claim for the alert.
        """
        updated_count = 0
        with self._lock:
            for out in self._outcomes:
                if out.alert_id == alert_id and out.outcome != "INVALIDATED":
                    out.outcome = "INVALIDATED"
                    out.realized_rr = None
                    updated_count += 1
            if updated_count > 0:
                self._save_outcomes()
                self._recalculate_factor_weights()
                logger.info(
                    f"[PatternLearningEngine] Invalidated {updated_count} outcome(s) for alert {alert_id}: {reason}"
                )
        return updated_count

    def _recalculate_factor_weights(self) -> None:
        """Keep prior milestone observations out of empirical performance weights.

        The current alert ledger does not contain actual executions or blended
        partial-exit quantities. Its milestones are path events, so using them as
        win/loss samples would bias factor weights. Market mover SNR may adjust
        weights through ``recalibrate_from_snr``; trade performance calibration
        remains unavailable until an independently reconciled fill ledger exists.
        """
        self._outcome_calibration_status = "UNAVAILABLE_NO_VERIFIED_EXECUTION_LEDGER"

    def recalibrate_from_snr(self, snr_table: dict[str, float]) -> None:
        """
        Dynamically adjusts factor weights based on Discriminative Signal-to-Noise Ratio (SNR)
        from daily mover autopsies.

        Factors with high discriminative SNR (separating gainers from control) receive proportional
        weight boosts. Low-SNR factors (noise) receive gradual reductions.
        Weights are normalized to sum to 100 after each update to maintain scoring coherence.

        SNR table keys (from mover_autopsy.py):
          volume_dry_up, squeeze_compression, gamma_short_squeeze, sector_tailwind,
          trend_score, smc_score, rvol_20d, forensic_safe
        """
        if not snr_table:
            return

        # Full factor mapping: autopsy SNR key -> internal weight key
        mapping = {
            "volume_dry_up": "volume_dry_up",
            "squeeze_compression": "squeeze_coiling",
            "gamma_short_squeeze": "ce_unwind",
            "sector_tailwind": "sector_tailwind",
            "trend_score": "trend_alignment",
            "smc_score": "ob_distance",
            "rvol_20d": "volume_dry_up",  # maps to same — RVOL surge boosts volume weight
            "forensic_safe": "sector_tailwind",  # governance quality → sector quality proxy
        }

        weights_before = dict(self._factor_weights)

        for snr_key, weight_key in mapping.items():
            if snr_key not in snr_table:
                continue
            if weight_key not in self._factor_weights:
                continue

            snr_val = snr_table[snr_key]
            current = self._factor_weights[weight_key]

            if snr_val >= 0.50:
                # Very high discrimination — significant boost (proportional)
                boost = min(8, max(4, int(snr_val * 6)))
                self._factor_weights[weight_key] = min(40, current + boost)
            elif snr_val >= 0.25:
                # Moderate discrimination — small boost
                self._factor_weights[weight_key] = min(35, current + 3)
            elif snr_val <= 0.05:
                # Near-noise — gentle reduction
                self._factor_weights[weight_key] = max(8, current - 2)
            # 0.05 < snr_val < 0.25: no change (stable zone)

        # Normalize so all weights sum to 100 (maintains scoring invariant)
        total = sum(self._factor_weights.values())
        if total > 0 and abs(total - 100) > 5:
            scale = 100.0 / total
            self._factor_weights = {
                k: max(5, round(v * scale)) for k, v in self._factor_weights.items()
            }
        self._factor_weight_source = "MARKET_DATA_SNR"

        logger.info(
            "[PatternLearningEngine] SNR recalibration complete. Δweights: %s → %s",
            {
                k: f"{weights_before.get(k, 0)}→{v}"
                for k, v in self._factor_weights.items()
                if weights_before.get(k) != v
            },
            {k: v for k, v in sorted(self._factor_weights.items(), key=lambda x: -x[1])[:5]},
        )

    def recalibrate_factor_weights(self) -> dict[str, int]:
        """Public entrypoint for manual or nightly factor weight recalculation."""
        with self._lock:
            self._recalculate_factor_weights()
            return dict(self._factor_weights)

    # ── Invalidation Post-Mortem & Retrospective Learning ───

    def set_symbol_lockout(
        self,
        symbol: str,
        direction: str = "BULLISH",
        duration_seconds: float = 5400.0,  # 90 minutes adaptive cooldown
        reason: str = "Stop-loss breach / thesis invalidation",
        reclaim_level: float = 0.0,
        event_id: Optional[str] = None,
        session_id: Optional[str] = None,
        current_time: Optional[float] = None,
    ) -> dict[str, Any]:
        """
        Places a symbol on negative feedback lockout following an invalidation.
        Prevents knife-catching and duplicate re-alerts in the same direction.
        Implements the Institutional Two-Strike Rule:
        - 1st failure: 90m adaptive lockout with structural reclaim escape.
        - 2nd failure today: Hard Session Lockout (8h) with NO premature unlock.
        """
        clean_sym = (
            symbol.upper()
            .replace(".NS", "")
            .replace(".BO", "")
            .replace("NSE:", "")
            .replace("BSE:", "")
            .replace("MCX:", "")
            .replace("NFO:", "")
            .strip()
        )
        dir_clean = direction.upper()
        composite_key = f"{clean_sym}:{dir_clean}"

        with self._lock:
            if event_id:
                if event_id in self._processed_invalidation_events:
                    if composite_key in self._lockouts:
                        return self._lockouts[composite_key]
                self._processed_invalidation_events.add(event_id)

            count_key = composite_key
            inv_count = self._invalidation_counts.get(count_key, 0) + 1
            self._invalidation_counts[count_key] = inv_count

            is_hard_session_lockout = inv_count >= 2
            if is_hard_session_lockout:
                duration_seconds = max(duration_seconds, 28800.0)  # 8 hours (rest of session)
                reason = f"Two-Strike Rule: Repeated invalidation ({inv_count}x today in {dir_clean} direction). Hard session lockout enforced to protect capital."

            now_ts = current_time if current_time is not None else self._clock()
            now_dt = datetime.fromtimestamp(now_ts, tz=IST)
            curr_session = session_id or now_dt.strftime("%Y%m%d")
            expires_at = now_ts + duration_seconds
            expiry_dt_str = datetime.fromtimestamp(expires_at, tz=IST).strftime("%H:%M:%S IST")

            lockout = {
                "symbol": clean_sym,
                "direction": dir_clean,
                "locked_at": now_dt.strftime("%Y-%m-%d %H:%M:%S IST"),
                "locked_at_ts": now_ts,
                "expires_at": expires_at,
                "expires_at_str": expiry_dt_str,
                "duration_minutes": round(duration_seconds / 60, 1),
                "reason": reason,
                "reclaim_level": float(reclaim_level or 0.0),
                "invalidation_count": inv_count,
                "is_hard_session_lockout": is_hard_session_lockout,
                "session_id": curr_session,
                "event_id": event_id,
            }
            self._lockouts[composite_key] = lockout
            self._symbol_lockouts[clean_sym] = lockout
            self._save_lockouts()

        reclaim_str = (
            f" | Reclaim Level: ₹{reclaim_level:,.1f}"
            if (reclaim_level > 0 and not is_hard_session_lockout)
            else " | HARD SESSION LOCKOUT (No reclaim)"
        )
        logger.info(
            f"[PatternLearningEngine] Symbol lockout activated for {clean_sym} ({direction}) [Strike {inv_count}] "
            f"until {expiry_dt_str}{reclaim_str} ({reason})"
        )
        return lockout

    @staticmethod
    def resolve_derivative_underlying(clean_sym: str) -> Optional[str]:
        """
        Extracts the canonical underlying index or equity from a derivative contract symbol.
        Consults canonical INDEX_SYMBOLS and exchange _OPTION_PATTERN to prevent ad-hoc hardcoding.
        """
        if not clean_sym:
            return None
        from engine.option_resolver import INDEX_SYMBOLS

        for idx in sorted(INDEX_SYMBOLS, key=len, reverse=True):
            if clean_sym.startswith(idx) and len(clean_sym) > len(idx):
                return idx

        try:
            from market.quotes import _OPTION_PATTERN

            m = _OPTION_PATTERN.match(clean_sym)
            if m:
                und = m.group("underlying")
                if und and und != clean_sym:
                    return und
        except Exception as e_opt:
            logger.debug(
                f"[engine.learning_engine] Option regex extraction error for {clean_sym}: {e_opt}"
            )

        m_std = re.match(r"^([A-Za-z0-9&_-]+?)(?:\d{2}[A-Z]{3}|\d{5})", clean_sym)
        if m_std:
            und = m_std.group(1)
            if und and und != clean_sym:
                return und

        return None

    def is_symbol_locked_out(
        self,
        symbol: str,
        direction: str = "BULLISH",
        ltp: Optional[float] = None,
        vwap: Optional[float] = None,
        current_time: Optional[float] = None,
        ref_dt: Optional[datetime] = None,
        session_id: Optional[str] = None,
        refractory_seconds: Optional[float] = None,
    ) -> tuple[bool, str]:
        """
        Returns (True, reason) if symbol is currently locked out from same-direction alerts.
        Automatically purges expired lockouts.

        Two-Strike Invariant:
        If symbol has failed twice in the current session (is_hard_session_lockout = True),
        structural reclaim is disabled to prevent whipsawing on false bounces.
        Otherwise, adaptive structural reclaim can lift the lockout early, subject to a
        mandatory 15-minute refractory window to eliminate immediate post-stop churn.
        """
        clean_sym = (
            symbol.upper()
            .replace(".NS", "")
            .replace(".BO", "")
            .replace("NSE:", "")
            .replace("BSE:", "")
            .replace("MCX:", "")
            .replace("NFO:", "")
            .strip()
        )
        dir_clean = direction.upper() if direction else "ALL"
        now = (
            current_time
            if current_time is not None
            else (ref_dt.timestamp() if ref_dt is not None else self._clock())
        )
        now_dt = ref_dt or datetime.fromtimestamp(now, tz=IST)
        curr_session = session_id or now_dt.strftime("%Y%m%d")

        with self._lock:
            candidates_to_check: list[tuple[str, dict[str, Any]]] = []
            if dir_clean in ("BULLISH", "BEARISH"):
                k = f"{clean_sym}:{dir_clean}"
                if k in self._lockouts:
                    candidates_to_check.append((k, self._lockouts[k]))
                k_all = f"{clean_sym}:ALL"
                if k_all in self._lockouts:
                    candidates_to_check.append((k_all, self._lockouts[k_all]))
            else:
                for k, v in list(self._lockouts.items()):
                    if k.startswith(f"{clean_sym}:"):
                        candidates_to_check.append((k, v))

            if not candidates_to_check:
                legacy = self._symbol_lockouts.get(clean_sym)
                if legacy:
                    leg_dir = legacy.get("direction", "BULLISH")
                    if dir_clean == "ALL" or leg_dir == dir_clean or leg_dir == "ALL":
                        candidates_to_check.append((clean_sym, legacy))

            if not candidates_to_check:
                underlying = self.resolve_derivative_underlying(clean_sym)
                if underlying:
                    return self.is_symbol_locked_out(
                        underlying,
                        direction=direction,
                        ltp=ltp,
                        vwap=vwap,
                        current_time=current_time,
                        ref_dt=ref_dt,
                        session_id=session_id,
                        refractory_seconds=refractory_seconds,
                    )
                return False, ""

            for key, lockout in candidates_to_check:
                # 1. Session expiry
                lock_session = lockout.get("session_id")
                if lock_session and lock_session != curr_session:
                    self._lockouts.pop(key, None)
                    self._symbol_lockouts.pop(clean_sym, None)
                    self._save_lockouts()
                    continue

                # 2. Time expiry
                if now >= lockout.get("expires_at", 0.0):
                    self._lockouts.pop(key, None)
                    self._symbol_lockouts.pop(clean_sym, None)
                    self._save_lockouts()
                    continue

                # 3. Two-Strike Hard Session Lockout
                if lockout.get("is_hard_session_lockout", False):
                    mins_left = max(1, int((lockout["expires_at"] - now) / 60))
                    reason = f"{lockout.get('reason', 'Two-strike session lockout')} (Active for next {mins_left}m until {lockout.get('expires_at_str', '')})"
                    return True, reason

                # 4. Adaptive Structural Reclaim
                locked_at_ts = float(lockout.get("locked_at_ts") or 0.0)
                min_refractory = (
                    refractory_seconds
                    if refractory_seconds is not None
                    else self.refractory_seconds
                )
                elapsed_since_lock = now - locked_at_ts
                reclaim_lvl = float(lockout.get("reclaim_level") or 0.0)
                lock_dir = lockout.get("direction", "BULLISH")

                if elapsed_since_lock >= min_refractory and ltp and ltp > 0 and reclaim_lvl > 0:
                    if lock_dir == "BULLISH" and ltp >= reclaim_lvl:
                        if vwap is None or ltp >= vwap:
                            logger.info(
                                f"[PatternLearningEngine] ⚡ Structural Reclaim detected for {clean_sym}! "
                                f"LTP ₹{ltp:,.2f} >= Reclaim Level ₹{reclaim_lvl:,.2f} & VWAP. "
                                f"Lockout automatically cleared to capture genuine explosive reversal."
                            )
                            self._lockouts.pop(key, None)
                            self._symbol_lockouts.pop(clean_sym, None)
                            self._save_lockouts()
                            return False, ""
                    elif lock_dir == "BEARISH" and ltp <= reclaim_lvl:
                        if vwap is None or ltp <= vwap:
                            logger.info(
                                f"[PatternLearningEngine] ⚡ Bearish Structural Reclaim detected for {clean_sym}! "
                                f"LTP ₹{ltp:,.2f} <= Reclaim Level ₹{reclaim_lvl:,.2f}. "
                                f"Lockout automatically cleared."
                            )
                            self._lockouts.pop(key, None)
                            self._symbol_lockouts.pop(clean_sym, None)
                            self._save_lockouts()
                            return False, ""

                mins_left = max(1, int((lockout["expires_at"] - now) / 60))
                reason = f"{lockout.get('reason', 'Recent invalidation')} (cooldown active for next {mins_left}m until {lockout.get('expires_at_str', '')})"
                return True, reason

            return False, ""

    def clear_symbol_lockout(
        self, symbol: Optional[str] = None, direction: Optional[str] = None
    ) -> None:
        """Clears lockout for a specific symbol or all symbols."""
        with self._lock:
            if symbol:
                clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").strip()
                if direction:
                    dir_clean = direction.upper()
                    self._lockouts.pop(f"{clean_sym}:{dir_clean}", None)
                else:
                    self._lockouts.pop(f"{clean_sym}:BULLISH", None)
                    self._lockouts.pop(f"{clean_sym}:BEARISH", None)
                    self._lockouts.pop(f"{clean_sym}:ALL", None)
                self._symbol_lockouts.pop(clean_sym, None)
            else:
                self._lockouts.clear()
                self._symbol_lockouts.clear()
            self._save_lockouts()

    def get_locked_out_symbols(self) -> list[dict[str, Any]]:
        """Returns currently active lockouts with remaining time."""
        now = self._clock()
        active = []
        with self._lock:
            to_purge = []
            for k, data in self._lockouts.items():
                if now < data.get("expires_at", 0.0):
                    d = dict(data)
                    d["remaining_minutes"] = max(0, int((data["expires_at"] - now) / 60))
                    active.append(d)
                else:
                    to_purge.append(k)
            for k in to_purge:
                self._lockouts.pop(k, None)
                sym = k.split(":")[0] if ":" in k else k
                self._symbol_lockouts.pop(sym, None)
            if to_purge:
                self._save_lockouts()
        return active

    # ── Session Breakout Trap Memory ────────────────────────

    def record_session_trap_pivot(
        self,
        symbol: str,
        pivot_price: float,
        direction: str = "BULLISH",
        trap_type: str = "BREAKOUT_TRAP",
        note: str = "",
    ) -> dict[str, Any]:
        """
        Records an intraday breakout failure / trap level for a symbol.
        Enforces memory across the session to prevent repeating duplicate entries
        into confirmed fakeout/distribution price zones.
        """
        if not symbol or pivot_price <= 0:
            return {}
        clean_sym = (
            symbol.upper()
            .replace(".NS", "")
            .replace(".BO", "")
            .replace("NSE:", "")
            .replace("BSE:", "")
            .replace("MCX:", "")
            .replace("NFO:", "")
            .strip()
        )
        now_dt = datetime.now(IST)
        today_str = now_dt.strftime("%Y-%m-%d")
        record = {
            "symbol": clean_sym,
            "pivot_price": round(float(pivot_price), 2),
            "direction": direction.upper(),
            "trap_type": trap_type.upper(),
            "recorded_at": now_dt.strftime("%Y-%m-%d %H:%M:%S IST"),
            "session_date": today_str,
            "note": note or f"Failed {direction} breakout pivot at ₹{pivot_price:,.1f}",
        }
        with self._lock:
            if clean_sym not in self._session_trap_pivots:
                self._session_trap_pivots[clean_sym] = []
            # Keep only today's session traps
            self._session_trap_pivots[clean_sym] = [
                p
                for p in self._session_trap_pivots[clean_sym]
                if p.get("session_date") == today_str
            ]
            self._session_trap_pivots[clean_sym].append(record)
            logger.info(
                f"[PatternLearningEngine] 🛑 Session Trap Pivot recorded: {clean_sym} at ₹{pivot_price:,.2f} ({trap_type})"
            )
        return record

    def is_near_session_trap_pivot(
        self,
        symbol: str,
        current_price: float,
        threshold_pct: float = 0.6,
    ) -> tuple[bool, Optional[dict[str, Any]]]:
        """
        Checks if current_price is within threshold_pct of any recorded failed breakout pivot today.
        Returns (is_near, trap_record).
        """
        if not symbol or current_price <= 0:
            return False, None
        clean_sym = (
            symbol.upper()
            .replace(".NS", "")
            .replace(".BO", "")
            .replace("NSE:", "")
            .replace("BSE:", "")
            .replace("MCX:", "")
            .replace("NFO:", "")
            .strip()
        )
        today_str = datetime.now(IST).strftime("%Y-%m-%d")
        with self._lock:
            traps = self._session_trap_pivots.get(clean_sym, [])
            for trap in traps:
                if trap.get("session_date") != today_str:
                    continue
                p_level = trap.get("pivot_price", 0.0)
                if p_level > 0:
                    diff_pct = abs(current_price - p_level) / p_level * 100.0
                    if diff_pct <= threshold_pct:
                        return True, trap
        return False, None

    def conduct_invalidation_post_mortem(
        self,
        alert: Any,
        exit_price: float,
        df: Optional[pd.DataFrame] = None,
        exchange: str = "NSE",
    ) -> InvalidationPostMortem:
        """
        Conducts forensic post-mortem when an alert is invalidated or stopped out.
        Identifies what signals were missed, logs root causes, applies corrective guardrails,
        and records the outcome into memory to improve subsequent decision quality.
        """
        now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        sym = getattr(alert, "symbol", "") if hasattr(alert, "symbol") else alert.get("symbol", "")
        clean_sym = sym.upper().replace(".NS", "").replace("NSE:", "").strip()
        alert_id = (
            getattr(alert, "alert_id", "")
            if hasattr(alert, "alert_id")
            else alert.get("alert_id", f"inv-{clean_sym}")
        )
        direction = (
            getattr(alert, "direction", "BULLISH")
            if hasattr(alert, "direction")
            else alert.get("direction", "BULLISH")
        )
        alert_type = (
            getattr(alert, "alert_type", "SETUP")
            if hasattr(alert, "alert_type")
            else alert.get("alert_type", "SETUP")
        )

        is_opt = bool(
            getattr(alert, "option_type", None)
            or (
                getattr(alert, "contract_symbol", None)
                and any(x in str(getattr(alert, "contract_symbol")).upper() for x in ("CE", "PE"))
            )
            or (
                getattr(alert, "alert_type", "") == "GAMMA_BLAST"
                and getattr(alert, "option_type", None)
            )
        )

        if is_opt:
            act_plan = getattr(alert, "actionable_plan", {}) or (
                alert.get("actionable_plan", {}) if isinstance(alert, dict) else {}
            )
            # 1. Resolve true entry price in option premium coordinates
            entry_price = float(
                getattr(alert, "option_premium", 0.0)
                or (act_plan.get("trade_plan", {}).get("entry_price") if act_plan else 0.0)
                or 0.0
            )
            if entry_price <= 0 and act_plan:
                rec_str = str(
                    act_plan.get("recommended_entry", "") or act_plan.get("entry_range", "")
                )
                m = re.search(r"[\d.]+", rec_str)
                if m:
                    try:
                        entry_price = float(m.group(0))
                    except ValueError as e_suppressed:
                        logger.debug(
                            f"[engine.learning_engine] Non-fatal exception suppressed: {e_suppressed}"
                        )
            if entry_price <= 0:
                entry_price = float(getattr(alert, "ltp", 0.0) or exit_price or 1.0)

            # 2. Resolve option stop-loss in premium coordinates (never inherit underlying spot/futures level)
            stop_loss = 0.0
            if act_plan:
                opt_sl_str = str(act_plan.get("stop_loss", ""))
                m_sl = re.findall(r"[\d,]+(?:\.\d+)?", opt_sl_str)
                if m_sl:
                    stop_loss = float(m_sl[0].replace(",", ""))
                elif act_plan.get("trade_plan", {}).get("invalidation_stop"):
                    stop_loss = float(act_plan["trade_plan"]["invalidation_stop"])

            raw_sl = float(getattr(alert, "stop_loss", 0.0) or 0.0)
            if stop_loss <= 0 and 0 < raw_sl <= 3.0 * entry_price:
                stop_loss = raw_sl
            elif stop_loss <= 0 or stop_loss > 3.0 * entry_price:
                # If stop_loss was missing or in underlying spot coordinates, use 28% Greek risk floor
                stop_loss = round(max(0.05, entry_price * 0.72), 2)

            # 3. Resolve option exit_price in premium coordinates
            # If exit_price was passed as underlying spot price (e.g. 56444 vs entry 799), clamp to stop_loss
            if exit_price > 3.0 * entry_price or exit_price <= 0:
                exit_price = stop_loss
            else:
                exit_price = float(exit_price)
        else:
            entry_price = float(
                getattr(alert, "trigger_level", 0.0) or getattr(alert, "ltp", 0.0) or exit_price
            )
            stop_loss = float(getattr(alert, "stop_loss", 0.0) or 0.0)
            exit_price = float(exit_price or entry_price)

        is_opt_sell = False
        if is_opt:
            act_plan = getattr(alert, "actionable_plan", {}) or (
                alert.get("actionable_plan", {}) if isinstance(alert, dict) else {}
            )
            act = str(act_plan.get("action", "")).upper() if act_plan else ""
            is_opt_sell = act in ("SELL", "WRITE", "SHORT")
            if not is_opt_sell and stop_loss > 0 and getattr(alert, "target_level", 0):
                t_lvl = float(getattr(alert, "target_level", 0) or 0)
                if entry_price > 0 and stop_loss > entry_price and t_lvl < entry_price:
                    is_opt_sell = True

            if is_opt_sell:
                loss_pts = max(0.0, round(exit_price - entry_price, 2))
            else:
                loss_pts = max(0.0, round(entry_price - exit_price, 2))
        elif direction == "BEARISH":
            loss_pts = max(0.0, round(exit_price - entry_price, 2))
        else:
            loss_pts = max(0.0, round(entry_price - exit_price, 2))

        loss_pct = round((loss_pts / max(0.1, entry_price)) * 100.0, 2)
        initial_risk_pts = abs(entry_price - stop_loss) if stop_loss > 0 else (entry_price * 0.015)
        realized_r = round(-1.0 * (loss_pts / max(0.1, initial_risk_pts)), 2)

        missed_signals: list[str] = []
        metrics_snapshot: dict[str, Any] = {
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "exit_price": exit_price,
            "loss_pts": loss_pts,
            "loss_pct": loss_pct,
            "realized_r": realized_r,
        }

        # 1. Forensic Check: Intraday VWAP & Knife-Catching Analysis
        intraday_vwap = None
        try:
            from market.quotes import get_quote

            lookup_sym = f"{exchange}:{clean_sym}" if ":" not in clean_sym else clean_sym
            q = get_quote(lookup_sym)
            if q and getattr(q, "vwap", None) and q.vwap > 0:
                intraday_vwap = float(q.vwap)
                metrics_snapshot["intraday_vwap"] = intraday_vwap
        except Exception as e_suppressed:
            logger.debug(f"[engine.learning_engine] Non-fatal exception suppressed: {e_suppressed}")

        if intraday_vwap and intraday_vwap > 0:
            if direction == "BULLISH" and exit_price < intraday_vwap:
                missed_signals.append(
                    f"Price broke below intraday VWAP (₹{intraday_vwap:,.1f}) — long entered into intraday institutional distribution"
                )
            elif direction == "BEARISH" and exit_price > intraday_vwap:
                missed_signals.append(
                    f"Price reclaimed above intraday VWAP (₹{intraday_vwap:,.1f}) — short caught in intraday short squeeze"
                )

        # 2. Forensic Check: Stop-Loss Volatility Noise Floor vs ATR
        atr = None
        if df is None or len(df) < 15:
            try:
                from market.history import get_ohlcv

                df = get_ohlcv(clean_sym, exchange=exchange, interval="day", days=30)
            except Exception as exc:
                logger.warning(
                    "[PatternLearningEngine] Local history unavailable for %s: %s", clean_sym, exc
                )
                df = None

        if df is not None and len(df) >= 15:
            try:
                highs = df["high"].values if "high" in df.columns else df["close"].values
                lows = df["low"].values if "low" in df.columns else df["close"].values
                closes = df["close"].values
                tr = np.maximum(
                    highs[1:] - lows[1:],
                    np.maximum(abs(highs[1:] - closes[:-1]), abs(lows[1:] - closes[:-1])),
                )
                atr = round(float(np.mean(tr[-14:])), 2)
                metrics_snapshot["atr_14d"] = atr
            except Exception:
                atr = None

        # Check alert timeframe & metrics
        th = (getattr(alert, "time_horizon", "") or "").upper()
        metrics = getattr(alert, "metrics", {}) or {}
        is_swing = th in (
            "SWING",
            "SWING_SHORT",
            "SWING_MID",
            "LONG_TERM",
            "POSITIONAL",
            "MULTIBAGGER",
        ) or getattr(alert, "setup_style", "") in ("SWING", "POSITIONAL")

        atr_5m = float(metrics.get("atr_5m") or metrics.get("atr_15m") or 0.0)

        if is_opt:
            # Option noise floor:
            # Indices: check institutional index floors (15 pts Nifty, 35 pts BankNifty, 45 pts Sensex)
            # Stocks: 10% - 15% of option premium or 1.10x option 5m ATR
            opt_atr_5m = float(metrics.get("opt_atr_5m") or atr_5m or 0.0)
            is_index_sym = any(
                idx in clean_sym
                for idx in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX")
            )

            if is_index_sym:
                min_idx_floor = (
                    45.0
                    if ("SENSEX" in clean_sym or "BANKEX" in clean_sym)
                    else (35.0 if "BANKNIFTY" in clean_sym else 15.0)
                )
                if entry_price >= 80.0:
                    min_noise_sl_pts = min_idx_floor
                else:
                    min_noise_sl_pts = max(3.0, round(entry_price * 0.12, 1))
            else:
                base_pct = round(entry_price * 0.12, 1)
                min_noise_sl_pts = (
                    max(base_pct, round(1.10 * opt_atr_5m, 1))
                    if opt_atr_5m > 0
                    else max(1.5, base_pct)
                )
        else:
            # Equities, Commodities, Crypto, Spot:
            try:
                from engine.alert_scrutiny import COMMODITY_MIN_SL_FLOORS, INDEX_MIN_SL_FLOORS

                if clean_sym in COMMODITY_MIN_SL_FLOORS:
                    min_noise_sl_pts = COMMODITY_MIN_SL_FLOORS[clean_sym]
                elif clean_sym in INDEX_MIN_SL_FLOORS and not is_opt:
                    min_noise_sl_pts = INDEX_MIN_SL_FLOORS[clean_sym]
                else:
                    if is_swing:
                        # Swing setups need 1.2x Daily ATR
                        min_noise_sl_pts = (
                            round(1.20 * atr, 1) if atr else round(entry_price * 0.020, 1)
                        )
                    else:
                        # Intraday setups: 1.20x 5m ATR, or if only daily ATR available, 0.25x Daily ATR (~1.2x 5m range)
                        if atr_5m > 0:
                            min_noise_sl_pts = round(1.20 * atr_5m, 1)
                        elif atr:
                            min_noise_sl_pts = round(max(0.25 * atr, entry_price * 0.007), 1)
                        else:
                            min_noise_sl_pts = round(entry_price * 0.008, 1)
            except Exception:
                min_noise_sl_pts = round(entry_price * 0.008, 1)

        actual_sl_pts = round(abs(entry_price - stop_loss), 2) if stop_loss > 0 else 0.0
        metrics_snapshot["stop_distance_pts"] = actual_sl_pts
        metrics_snapshot["min_noise_sl_pts"] = min_noise_sl_pts

        if actual_sl_pts > 0 and actual_sl_pts < min_noise_sl_pts:
            missed_signals.append(
                f"Stop-loss buffer ({actual_sl_pts:.1f} pts / {loss_pct:.2f}%) was narrower than volatility noise floor "
                f"({min_noise_sl_pts:.1f} pts) — vulnerable to ordinary intraday chop"
            )

        # 3. Forensic Check: Sector RRG Alignment & Institutional Flow
        sector_name = "Broad Market"
        rrg_quadrant = "NEUTRAL"
        try:
            from analysis.sector_rotation import get_stock_sector_alignment

            align = get_stock_sector_alignment(clean_sym)
            if isinstance(align, dict):
                sector_name = align.get("sector", "Sector")
                rrg_quadrant = align.get("quadrant", "NEUTRAL")
                metrics_snapshot["sector"] = sector_name
                metrics_snapshot["rrg_quadrant"] = rrg_quadrant
        except Exception as e_suppressed:
            logger.debug(f"[engine.learning_engine] Non-fatal exception suppressed: {e_suppressed}")

        if rrg_quadrant in ("LAGGING", "WEAKENING"):
            missed_signals.append(
                f"Parent sector ({sector_name}) in '{rrg_quadrant}' RRG quadrant — persistent sector outflow created headwind"
            )

        # 4. Forensic Check: Broad Market Beta Headwind
        try:
            from market.quotes import get_ltp

            nifty_ltp = get_ltp("NSE:NIFTY") or get_ltp("NIFTY")
            metrics_snapshot["nifty_ref"] = nifty_ltp
        except Exception as e_suppressed:
            logger.debug(f"[engine.learning_engine] Non-fatal exception suppressed: {e_suppressed}")

        # 4b. Forensic Check: Session Time Windows (Opening Bell Auction Chop vs Late Session)
        alert_time_str = str(
            getattr(alert, "created_at", "") or getattr(alert, "triggered_at", "") or ""
        )
        is_opening_bell = False
        is_late_session = False
        if " " in alert_time_str:
            try:
                t_part = alert_time_str.split(" ")[1][:5]
                hh, mm = map(int, t_part.split(":"))
                if (hh == 9 and mm < 25) or (hh < 9):
                    is_opening_bell = True
                elif (hh == 15 and 10 <= mm <= 30) and getattr(alert, "exchange", "NSE") in (
                    "NSE",
                    "BSE",
                    "NFO",
                ):
                    is_late_session = True
            except Exception as e_suppressed:
                logger.debug(
                    f"[engine.learning_engine] Non-fatal exception suppressed: {e_suppressed}"
                )

        if is_opening_bell:
            missed_signals.append(
                "Alert triggered during opening auction discovery window (09:15–09:25 IST) — vulnerable to opening spread noise and unanchored VWAP"
            )
        if is_late_session:
            missed_signals.append(
                "Alert triggered post-15:10 IST — market MIS square-off active and terminal overnight theta decay accelerated"
            )

        # 4c. Forensic Check: Repeated Churn Count
        count_key = f"{clean_sym}:{direction.upper()}"
        inv_count = self._invalidation_counts.get(count_key, 0)
        if inv_count >= 2:
            missed_signals.append(
                f"Repeated failure ({inv_count}x today): Symbol in choppy sideways range without directional follow-through"
            )

        # 4d. Forensic Check: L2/L3 Order Book Microstructure Attribution
        exit_micro = (
            getattr(alert, "exit_microstructure", None)
            or (alert.get("exit_microstructure") if isinstance(alert, dict) else None)
            or (
                alert.metrics.get("exit_microstructure")
                if hasattr(alert, "metrics") and isinstance(alert.metrics, dict)
                else None
            )
        )
        if exit_micro is None:
            try:
                from market.order_book import get_depth_book

                lookup_sym = getattr(alert, "contract_symbol", None) or clean_sym
                depth = get_depth_book(lookup_sym)
                if depth and (depth.best_bid > 0 or depth.best_ask > 0):
                    spread_bps = (
                        round(
                            ((depth.best_ask - depth.best_bid) / max(0.01, depth.mid_price))
                            * 10000,
                            1,
                        )
                        if depth.mid_price > 0
                        else 0.0
                    )
                    bids = getattr(depth, "bids", []) or []
                    asks = getattr(depth, "asks", []) or []
                    is_bull = (
                        direction in ("BULLISH", "LONG", "BUY")
                        or getattr(alert, "option_type", "") == "CE"
                    )
                    target_levels = asks if is_bull else bids
                    wall_detected = False
                    wall_side = None
                    wall_qty = 0
                    wall_price = 0.0
                    wall_ratio = 1.0
                    if target_levels:
                        qtys = [float(lvl.qty) for lvl in target_levels[:5]]
                        avg_q = sum(qtys) / max(1, len(qtys))
                        max_q = max(qtys)
                        if avg_q > 0 and (max_q / avg_q >= 2.8) and max_q >= 100:
                            wall_detected = True
                            wall_side = "ASK" if is_bull else "BID"
                            wall_qty = int(max_q)
                            wall_ratio = round(max_q / avg_q, 2)
                            wall_lvl = next(
                                (lvl for lvl in target_levels[:5] if lvl.qty == max_q), None
                            )
                            if wall_lvl:
                                wall_price = float(wall_lvl.price)
                    exit_micro = {
                        "symbol": lookup_sym,
                        "best_bid": float(depth.best_bid),
                        "best_ask": float(depth.best_ask),
                        "mid_price": float(depth.mid_price),
                        "spread_bps": spread_bps,
                        "obi_5": float(depth.obi(5)),
                        "obi_50": float(depth.obi(50)),
                        "has_resting_wall": wall_detected,
                        "wall_side": wall_side,
                        "wall_qty": wall_qty,
                        "wall_price": wall_price,
                        "wall_ratio": wall_ratio,
                    }
            except Exception as e_depth:
                logger.debug(
                    f"[LearningEngine] Microstructure snapshot retrieval failed: {e_depth}"
                )

        if exit_micro:
            metrics_snapshot["exit_microstructure"] = exit_micro
            obi_50 = float(exit_micro.get("obi_50", 0.0) or 0.0)
            spread_bps = float(exit_micro.get("spread_bps", 0.0) or 0.0)
            wall_detected = bool(exit_micro.get("has_resting_wall", False))
            wall_side = exit_micro.get("wall_side") or (
                "ASK" if direction in ("BULLISH", "LONG", "BUY") else "BID"
            )
            wall_qty = int(exit_micro.get("wall_qty", 0) or 0)
            wall_price = float(exit_micro.get("wall_price", 0.0) or 0.0)
            wall_ratio = float(exit_micro.get("wall_ratio", 1.0) or 1.0)

            if wall_detected:
                missed_signals.append(
                    f"Resting fortress {wall_side} wall ({wall_qty:,} contracts @ ₹{wall_price:,.2f}, {wall_ratio:.1f}x depth) absorbed order flow and rejected trade"
                )
            if direction in ("BULLISH", "LONG", "BUY") and obi_50 <= -0.35:
                missed_signals.append(
                    f"Severe ask book imbalance (OBI50={obi_50:+.2f}) overwhelmed buyers at stop-loss level"
                )
            elif direction in ("BEARISH", "SHORT", "SELL") and obi_50 >= 0.35:
                missed_signals.append(
                    f"Severe bid book imbalance (OBI50={obi_50:+.2f}) squeezed short setup into stop-loss"
                )
            if is_opt and spread_bps >= 450.0:
                missed_signals.append(
                    f"Elevated option spread friction ({spread_bps / 100:.1f}%) magnified adverse slippage on exit"
                )
            elif not is_opt and spread_bps >= 35.0:
                missed_signals.append(
                    f"Elevated equity spread friction ({spread_bps:.1f} bps) amplified adverse slippage on exit"
                )

        # 5. Determine Primary Failure Reason
        if is_opening_bell:
            primary_reason = "OPENING_BELL_AUCTION_CHOP"
        elif is_late_session:
            primary_reason = "LATE_SESSION_EXHAUSTION_THETA_DRAG"
        elif inv_count >= 2:
            primary_reason = "CHOPPY_SIDEWAYS_RANGE_TRAP"
        elif exit_micro and exit_micro.get("has_resting_wall"):
            primary_reason = "ORDER_BOOK_ABSORPTION_WALL_TRAP"
        elif exit_micro and (
            (
                direction in ("BULLISH", "LONG", "BUY")
                and float(exit_micro.get("obi_50", 0.0) or 0.0) <= -0.40
            )
            or (
                direction in ("BEARISH", "SHORT", "SELL")
                and float(exit_micro.get("obi_50", 0.0) or 0.0) >= 0.40
            )
        ):
            primary_reason = "HEAVY_OBI_LIQUIDITY_RUN_IMBALANCE"
        elif exit_micro and (
            (is_opt and float(exit_micro.get("spread_bps", 0.0) or 0.0) >= 500.0)
            or (not is_opt and float(exit_micro.get("spread_bps", 0.0) or 0.0) >= 45.0)
        ):
            primary_reason = "EXCESSIVE_SPREAD_FRICTION_DRAG"
        elif intraday_vwap and exit_price < intraday_vwap and actual_sl_pts < min_noise_sl_pts:
            primary_reason = "PREMATURE_ENTRY_BELOW_VWAP_AND_SUB_ATR_STOP"
        elif intraday_vwap and exit_price < intraday_vwap:
            primary_reason = "PREMATURE_ENTRY_BELOW_VWAP"
        elif actual_sl_pts > 0 and actual_sl_pts < min_noise_sl_pts:
            primary_reason = "SUB_ATR_NOISE_WHIPSAW"
        elif rrg_quadrant in ("LAGGING", "WEAKENING"):
            primary_reason = "SECTOR_ROTATION_DRAG"
        else:
            primary_reason = "STRUCTURAL_ORDERFLOW_FAILURE"

        # 6. Formulate Institutional Root Cause & Corrective Actions
        first_cues = (
            "; ".join(missed_signals[:2])
            if missed_signals
            else "Structural breakdown of invalidation anchor"
        )
        root_cause = (
            f"Quantitative attribution indicates {clean_sym} thesis failed due to {primary_reason.replace('_', ' ').lower()}. "
            f"Key factors: {first_cues}."
        )

        # Determine structural reclaim level (price needed to disprove invalidation thesis)
        if is_opt:
            reclaim_level = (
                min(entry_price, exit_price) if is_opt_sell else max(entry_price, exit_price)
            )
        else:
            alert_trig = float(
                getattr(alert, "trigger_level", 0.0) or getattr(alert, "ltp", 0.0) or entry_price
            )
            reclaim_level = (
                max(entry_price, alert_trig, exit_price)
                if direction == "BULLISH"
                else (min(entry_price, alert_trig, exit_price) if entry_price > 0 else exit_price)
            )
        reclaim_str = f" above ₹{reclaim_level:,.1f}" if reclaim_level > 0 else ""

        corrective_actions = [
            f"Symbol {clean_sym} placed on 90m lockout (automatically lifts early on structural reclaim{reclaim_str} & VWAP).",
            f"Enforcing minimum stop-loss distance floor of 1.2x ATR ({min_noise_sl_pts:.1f} pts).",
            f"Mandated intraday VWAP confirmation filter on subsequent {alert_type.replace('_', ' ')} scans.",
        ]
        if primary_reason == "ORDER_BOOK_ABSORPTION_WALL_TRAP":
            corrective_actions.append(
                "Resting wall avoidance: enforce minimum 2.8x fortress wall clearance before triggering breakout alerts."
            )
        elif primary_reason == "HEAVY_OBI_LIQUIDITY_RUN_IMBALANCE":
            corrective_actions.append(
                "Regime-aware OBI filter: require OBI50 confirmation > -0.20 for long setups and < +0.20 for short setups."
            )
        elif primary_reason == "EXCESSIVE_SPREAD_FRICTION_DRAG":
            corrective_actions.append(
                "Spread friction gate: require tighter bid-ask spread (< 30 bps equity / < 4.5% options) to prevent friction loss."
            )
        metrics_snapshot["reclaim_level"] = round(reclaim_level, 2) if reclaim_level > 0 else None

        pm = InvalidationPostMortem(
            alert_id=alert_id,
            symbol=clean_sym,
            direction=direction,
            alert_type=alert_type,
            entry_price=entry_price,
            stop_loss=stop_loss,
            exit_price=exit_price,
            loss_pts=loss_pts,
            loss_pct=loss_pct,
            realized_r=realized_r,
            primary_failure_reason=primary_reason,
            missed_signals=missed_signals
            or ["Intraday orderflow reversed through structural pivot"],
            root_cause_analysis=root_cause,
            corrective_actions=corrective_actions,
            metrics_snapshot=metrics_snapshot,
            invalidated_at=now_iso,
        )

        # 7. Apply closed-loop adaptation
        # Automatically lock out symbol with adaptive structural reclaim
        self.set_symbol_lockout(
            clean_sym,
            direction=direction,
            duration_seconds=5400.0,  # 90 minutes adaptive cooldown
            reason=f"{primary_reason.replace('_', ' ').title()}",
            reclaim_level=reclaim_level,
        )

        underlying_clean = self.resolve_derivative_underlying(clean_sym)
        if underlying_clean and underlying_clean != clean_sym:
            self.set_symbol_lockout(
                underlying_clean,
                direction=direction,
                duration_seconds=5400.0,
                reason=f"{primary_reason.replace('_', ' ').title()} (Option Derivative Trap)",
                reclaim_level=0.0,
            )

        # Record session trap pivot level to prevent repeat fakeout entries today
        trap_pivot = entry_price if entry_price > 0 else (alert_trig if not is_opt else 0.0)
        if trap_pivot > 0:
            self.record_session_trap_pivot(
                symbol=clean_sym,
                pivot_price=trap_pivot,
                direction=direction,
                trap_type="BULL_TRAP" if direction == "BULLISH" else "BEAR_TRAP",
                note=f"Invalidated {alert_type}: {primary_reason}",
            )

        # Record outcome into learning memory with -1.0R payoff
        self.record_trade_outcome(
            alert_id=alert_id,
            symbol=clean_sym,
            archetype=alert_type,
            entry_price=entry_price,
            exit_price=exit_price,
            outcome="STOPPED_OUT",
            realized_rr=realized_r,
            factors_present=missed_signals,
            provenance="ALERT_FORWARD_PATH_INVALIDATION",
        )

        # Save post-mortem to memory
        self._post_mortems = [p for p in self._post_mortems if p.alert_id != alert_id]
        self._post_mortems.insert(0, pm)
        self._save_post_mortems()

        logger.info(
            f"[PatternLearningEngine] Conducted post-mortem for {clean_sym}: "
            f"Reason: {primary_reason} | Missed signals: {len(missed_signals)} | Lockout: 4h"
        )
        return pm

    def get_recent_post_mortems(self, limit: int = 15) -> list[dict[str, Any]]:
        """Returns recent invalidation post-mortems."""
        return [pm.to_dict() for pm in self._post_mortems[:limit]]

    # ── Feature Extraction ────────────────────────────────────

    def extract_pre_blast_features(
        self,
        symbol: str,
        df: Optional[pd.DataFrame] = None,
        chain: Optional[list[Any]] = None,
        exchange: str = "NSE",
        is_historical_blast: bool = False,
        allow_network: bool = False,
    ) -> dict[str, Any]:
        """
        Extracts pre-blast quantitative features from market history and options chain.
        If is_historical_blast=True, slices df up to the pre-blast day to analyze what
        preceded the explosive candle.
        """
        clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").strip()

        if df is None or len(df) < 15:
            try:
                from engine.eod_store import get_eod_df

                df = get_eod_df(clean_sym, days=60)
            except Exception:
                df = None
            if (df is None or len(df) < 15) and allow_network:
                try:
                    from market.history import get_ohlcv

                    df = get_ohlcv(clean_sym, exchange=exchange, interval="day", days=60)
                except Exception as exc:
                    logger.warning(
                        "[PatternLearningEngine] Remote history unavailable for %s: %s",
                        clean_sym,
                        exc,
                    )
                    df = None

        if df is None or len(df) < 15:
            return {}

        # If analyzing a completed blast candle, evaluate the pre-blast window
        if is_historical_blast and len(df) >= 3:
            analysis_df = df.iloc[:-1]
        else:
            analysis_df = df

        closes = analysis_df["close"].values
        highs = analysis_df["high"].values if "high" in analysis_df.columns else closes
        volumes = analysis_df["volume"].values if "volume" in analysis_df.columns else None

        # 1. Prior-day volume dry-up ratio vs 20-day average
        prior_vol_ratio: Optional[float] = None
        if volumes is not None and len(volumes) >= 21:
            avg_vol_20d = float(np.mean(volumes[-21:-1]))
            # Prior day volume (penultimate bar before blast, or current bar for live candidate)
            prior_vol = (
                float(volumes[-1])
                if is_historical_blast
                else (float(volumes[-2]) if len(volumes) >= 2 else avg_vol_20d)
            )
            if math.isfinite(avg_vol_20d) and avg_vol_20d > 0 and math.isfinite(prior_vol):
                prior_vol_ratio = round(prior_vol / avg_vol_20d, 3)

        # 2. TTM Squeeze coiling duration
        squeeze_bars: Optional[int] = None
        try:
            from analysis.big_move import compute_ttm_squeeze

            sq = compute_ttm_squeeze(analysis_df)
            squeeze_bars = (
                int(sq.squeeze_duration_bars) if (sq.is_squeeze_on or sq.squeeze_fired) else 0
            )
        except Exception as e_suppressed:
            logger.debug(f"[engine.learning_engine] Non-fatal exception suppressed: {e_suppressed}")

        # 3. Call OI Unwinding in options chain (only query for F&O instruments with active coiling or volume dry-up)
        ce_unwind_pct: Optional[float] = None
        # Historical OHLCV does not establish an as-of option chain. Suppress
        # current chain inputs until an explicit timestamped historical contract exists.
        if is_historical_blast:
            chain = None
        if (
            chain is None
            and not is_historical_blast
            and allow_network
            and (
                (prior_vol_ratio is not None and prior_vol_ratio <= 0.45)
                or (squeeze_bars is not None and squeeze_bars >= 2)
            )
        ):
            try:
                from engine.position_sizer import get_lot_size

                if get_lot_size(clean_sym) > 1:
                    from market.options import get_options_chain

                    chain = get_options_chain(clean_sym)
            except Exception as exc:
                logger.warning(
                    "[PatternLearningEngine] Option chain unavailable for %s: %s", clean_sym, exc
                )
                chain = None

        if chain:
            ce_shedding = []
            observed_ce_contracts = 0
            for c in chain:
                if getattr(c, "option_type", "") == "CE":
                    oi = getattr(c, "oi", 0)
                    doi = getattr(c, "oi_change", 0)
                    if oi > 0:
                        observed_ce_contracts += 1
                    if doi < 0 and oi > 0:
                        pct = (doi / max(1, oi - doi)) * 100.0
                        ce_shedding.append(pct)
            if observed_ce_contracts:
                ce_unwind_pct = round(min(ce_shedding), 1) if ce_shedding else 0.0

        # 4. Proximity to Bullish Order Block
        ob_dist_pct: Optional[float] = None
        try:
            from analysis.market_structure import analyze_market_structure

            ms = analyze_market_structure(clean_sym, df=analysis_df, exchange=exchange)
            ltp = float(closes[-1])
            if hasattr(ms, "order_blocks") and ms.order_blocks:
                bull_obs = [ob for ob in ms.order_blocks if getattr(ob, "ob_type", "") == "BULLISH"]
                if bull_obs and ltp > 0:
                    nearest_top = bull_obs[0].top
                    ob_dist_pct = round(abs(ltp - nearest_top) / ltp * 100, 2)
        except Exception as e_suppressed:
            logger.debug(f"[engine.learning_engine] Non-fatal exception suppressed: {e_suppressed}")

        # 5. Sector RRG alignment
        rrg_quad: Optional[str] = None
        if not is_historical_blast:
            try:
                from analysis.sector_rotation import get_stock_sector_alignment

                align = get_stock_sector_alignment(clean_sym)
                if isinstance(align, dict):
                    raw_quadrant = str(align.get("quadrant", "")).upper().strip()
                    if raw_quadrant in ("LEADING", "IMPROVING", "WEAKENING", "LAGGING"):
                        rrg_quad = raw_quadrant
                elif isinstance(align, str):
                    raw_quadrant = align.upper()
                    rrg_quad = next(
                        (
                            quadrant
                            for quadrant in ("LEADING", "IMPROVING", "WEAKENING", "LAGGING")
                            if quadrant in raw_quadrant
                        ),
                        None,
                    )
            except Exception as e_suppressed:
                logger.debug(
                    f"[engine.learning_engine] Non-fatal exception suppressed: {e_suppressed}"
                )

        # 6. Breakout Trigger Pivot (highest high of the last 5 coiling bars)
        pivot_high = (
            round(float(np.max(highs[-5:])), 2)
            if len(highs) >= 5 and np.isfinite(highs[-5:]).all()
            else None
        )

        # 7. Minervini SEPA Fundamentals (fast local check, zero network blocking in scanner loops)
        sepa_qual: Optional[bool] = None
        if not is_historical_blast:
            try:
                from analysis.fundamental import _fund_cache, _fund_cache_lock

                with _fund_cache_lock:
                    cached_snap = _fund_cache.get(clean_sym)
                if cached_snap is not None:
                    cached_sepa = getattr(cached_snap[1], "sepa_qualified", None)
                    sepa_qual = bool(cached_sepa) if cached_sepa is not None else None
                else:
                    from engine.eod_store import get_cached_fundamentals

                    cached_fund = get_cached_fundamentals(clean_sym, max_age_days=30)
                    if cached_fund and "sepa_qualified" in cached_fund:
                        sepa_qual = bool(cached_fund["sepa_qualified"])
                    elif allow_network:
                        from analysis.fundamental import analyse

                        snap = analyse(clean_sym, fast=True)
                        sepa_value = getattr(snap, "sepa_qualified", None)
                        sepa_qual = bool(sepa_value) if sepa_value is not None else None
            except Exception as e_suppressed:
                logger.debug(
                    f"[engine.learning_engine] Non-fatal exception suppressed: {e_suppressed}"
                )

        source_meta = (df.attrs.get("provenance") or {}) if df is not None else {}
        if not isinstance(source_meta, dict):
            source_meta = {}
        return {
            "symbol": clean_sym,
            "prior_vol_ratio": prior_vol_ratio,
            "squeeze_bars": squeeze_bars,
            "ce_unwind_pct": ce_unwind_pct,
            "ob_distance_pct": ob_dist_pct,
            "rrg_quadrant": rrg_quad,
            "coiling_pivot_high": pivot_high,
            "sepa_qualified": sepa_qual,
            "data_source": source_meta.get("data_source"),
            "data_provider": source_meta.get("provider"),
            "data_snapshot_id": source_meta.get("snapshot_id"),
            "data_reproducible": bool(source_meta.get("reproducible", False)),
        }

    # ── Learning from a Validated Move ───────────────────────

    def register_explosive_move(
        self,
        symbol: str,
        move_pct: float,
        rvol_surge: float,
        catalyst: str = "",
        df: Optional[pd.DataFrame] = None,
        chain: Optional[list[Any]] = None,
        date_str: Optional[str] = None,
        is_historical_blast: bool = True,
        provenance: str = "USER_SUBMITTED_UNVERIFIED",
    ) -> ExplosiveMoveFingerprint:
        """
        Learns and persists an explosive move case study, locking in its pre-blast factors.
        """
        clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").strip()
        features = self.extract_pre_blast_features(
            clean_sym, df=df, chain=chain, is_historical_blast=is_historical_blast
        )

        if not math.isfinite(float(move_pct)) or not math.isfinite(float(rvol_surge)):
            raise ValueError("Explosive-move inputs must be finite market observations.")
        if provenance == "SOURCE_TAGGED_HISTORICAL_DATA":
            approved_sources = {
                "HISTORICAL_EOD",
                "LOCAL_SQLITE_EOD",
                "LOCAL_PARQUET_WAREHOUSE",
            }
            if (
                features.get("data_source") not in approved_sources
                or features.get("data_source") == "LIVE_ENRICHED"
            ):
                raise ValueError(
                    "Historical archetype requires source-tagged, non-live market data."
                )
        else:
            provenance = "USER_SUBMITTED_UNVERIFIED"

        target_date = date_str or datetime.now(IST).strftime("%Y-%m-%d")

        fp = ExplosiveMoveFingerprint(
            symbol=clean_sym,
            date=target_date,
            move_pct=round(move_pct, 2),
            rvol_surge=round(rvol_surge, 2),
            prior_vol_ratio=features.get("prior_vol_ratio"),
            squeeze_bars=features.get("squeeze_bars"),
            ce_unwind_pct=features.get("ce_unwind_pct"),
            ob_distance_pct=features.get("ob_distance_pct"),
            rrg_quadrant=features.get("rrg_quadrant"),
            structural_rr=None,
            key_catalyst=catalyst.strip(),
            fingerprint_score=None,
            coiling_pivot_high=features.get("coiling_pivot_high"),
            sepa_qualified=features.get("sepa_qualified"),
            provenance=provenance,
            source_data_source=features.get("data_source"),
            source_provider=features.get("data_provider"),
            source_snapshot_id=features.get("data_snapshot_id"),
            source_reproducible=bool(features.get("data_reproducible", False)),
        )

        # Avoid duplicates on same symbol and date
        self._fingerprints = [
            f for f in self._fingerprints if not (f.symbol == fp.symbol and f.date == fp.date)
        ]
        self._fingerprints.insert(0, fp)
        self._save()
        logger.info(
            f"[PatternLearningEngine] Registered new learning archetype: {clean_sym} ({target_date})"
        )
        return fp

    # ── Autonomous Market Mover Scanner ───────────────────────

    def scan_and_learn_from_market_movers(
        self,
        universe: Optional[list[str]] = None,
        min_move_pct: float = 3.8,
        min_rvol: float = 1.6,
    ) -> list[ExplosiveMoveFingerprint]:
        """
        Autonomous sweeper that checks for newly exploded market movers,
        analyzes their pre-blast footprint, and commits them to memory.
        """
        from market.history import get_ohlcv

        if universe is None:
            from analysis.universe import resolve_dynamic_universe

            symbols_to_scan, universe_reason = resolve_dynamic_universe("nifty50", max_stocks=50)
            if not symbols_to_scan:
                logger.warning(
                    "[PatternLearningEngine] Market mover scan skipped: canonical NIFTY 50 "
                    "universe unavailable (%s)",
                    universe_reason,
                )
                return []
        else:
            symbols_to_scan = list(universe)

        learned: list[ExplosiveMoveFingerprint] = []

        for sym in symbols_to_scan:
            try:
                df = get_ohlcv(sym, exchange="NSE", interval="day", days=40)
                if df is None or len(df) < 22:
                    continue

                closes = df["close"].values
                volumes = df["volume"].values if "volume" in df.columns else None
                if volumes is None:
                    continue

                avg_vol = float(np.mean(volumes[-21:-1]))
                evidence_values = (closes[-1], closes[-2], volumes[-1], avg_vol)
                if not all(
                    math.isfinite(float(value)) and float(value) > 0 for value in evidence_values
                ):
                    logger.warning(
                        "[PatternLearningEngine] Skipping %s: invalid price/volume evidence", sym
                    )
                    continue
                day_move_pct = ((closes[-1] - closes[-2]) / closes[-2]) * 100.0
                rvol = float(volumes[-1] / avg_vol)

                if day_move_pct >= min_move_pct and rvol >= min_rvol:
                    if not isinstance(df.index, pd.DatetimeIndex) or pd.isna(df.index[-1]):
                        logger.warning(
                            "[PatternLearningEngine] Skipping %s: event bar has no verifiable date",
                            sym,
                        )
                        continue
                    event_date = df.index[-1].date().isoformat()
                    # Deduplicate by the observed event bar, including on weekends
                    # and delayed feeds, rather than the day this scan was run.
                    already_learned = any(
                        f.symbol == sym and f.date == event_date for f in self._fingerprints
                    )
                    if not already_learned:
                        fp = self.register_explosive_move(
                            symbol=sym,
                            move_pct=day_move_pct,
                            rvol_surge=rvol,
                            catalyst=f"Autonomous Mover Detection (+{day_move_pct:.1f}%, {rvol:.1f}x Vol)",
                            df=df,
                            date_str=event_date,
                            is_historical_blast=True,
                            provenance="SOURCE_TAGGED_HISTORICAL_DATA",
                        )
                        learned.append(fp)
                        logger.info(
                            f"[PatternLearningEngine] Auto-learned explosive mover {sym}: "
                            f"+{day_move_pct:.1f}% surge (Pre-blast vol dry-up: {fp.prior_vol_ratio}x)"
                        )
            except Exception as e:
                logger.debug(f"[PatternLearningEngine] Error scanning {sym}: {e}")

        return learned

    # ── Candidate Matching & Early Warning ───────────────────

    def evaluate_candidate(
        self,
        symbol: str,
        df: Optional[pd.DataFrame] = None,
        chain: Optional[list[Any]] = None,
        ltp: Optional[float] = None,
        vwap: Optional[float] = None,
        allow_network: bool = False,
    ) -> PatternMatchResult:
        """
        Evaluates an active watchlist candidate against learned archetypes using dynamic factor weights.
        Returns match score (0–100), deciding factors met, and early-warning recommendation.
        """
        clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").strip()

        # Check Symbol Invalidation Lockout (prevents knife-catching after stop-loss breach)
        # Adaptively checks if current price has structurally reclaimed above failed level and VWAP
        ltp_val = float(ltp) if ltp is not None and float(ltp) > 0 else None
        vwap_val = float(vwap) if vwap is not None and float(vwap) > 0 else None
        if (ltp_val is None or vwap_val is None) and allow_network:
            try:
                from market.quotes import get_quote

                q = get_quote(f"NSE:{clean_sym}")
                if q:
                    if ltp_val is None:
                        ltp_val = float(q.ltp or 0.0)
                    if vwap_val is None:
                        vwap_val = float(getattr(q, "vwap", 0.0) or 0.0)
            except Exception as e_suppressed:
                logger.debug(
                    f"[engine.learning_engine] Non-fatal exception suppressed: {e_suppressed}"
                )

        if (ltp_val is None or ltp_val <= 0) and df is not None and len(df) > 0:
            try:
                ltp_val = float(df["close"].iloc[-1])
            except Exception as e_suppressed:
                logger.debug(
                    f"[engine.learning_engine] Non-fatal exception suppressed: {e_suppressed}"
                )

        is_locked, lock_reason = self.is_symbol_locked_out(
            clean_sym, direction="BULLISH", ltp=ltp_val, vwap=vwap_val
        )
        if is_locked:
            return PatternMatchResult(
                symbol=clean_sym,
                similarity_score=15,
                closest_archetype=None,
                matched_factors=[
                    f"🛑 Symbol locked out following recent invalidation: {lock_reason}"
                ],
                is_explosive_candidate=False,
                recommended_entry_action="LOCKED_OUT_POST_MORTEM",
                expected_asymmetry_rr=None,
                coiling_pivot_high=0.0,
            )

        features = self.extract_pre_blast_features(
            clean_sym, df=df, chain=chain, is_historical_blast=False, allow_network=allow_network
        )

        if not features:
            return PatternMatchResult(
                symbol=clean_sym,
                similarity_score=0,
                closest_archetype=None,
                matched_factors=[],
                is_explosive_candidate=False,
                recommended_entry_action="INSUFFICIENT_DATA",
                expected_asymmetry_rr=None,
                coiling_pivot_high=0.0,
            )

        required_features = (
            "prior_vol_ratio",
            "squeeze_bars",
            "ce_unwind_pct",
            "ob_distance_pct",
            "rrg_quadrant",
            "sepa_qualified",
        )
        available_features = sum(features.get(key) is not None for key in required_features)
        if available_features < 3:
            return PatternMatchResult(
                symbol=clean_sym,
                similarity_score=0,
                closest_archetype=None,
                matched_factors=[
                    f"Only {available_features} of {len(required_features)} required "
                    "pattern inputs are available; at least 3 are required."
                ],
                is_explosive_candidate=False,
                recommended_entry_action="INSUFFICIENT_VERIFIED_FEATURES",
                expected_asymmetry_rr=None,
                coiling_pivot_high=features.get("coiling_pivot_high"),
            )

        matched_factors: list[str] = []
        score = 20  # baseline anchor

        # Check Intraday VWAP alignment (Knife-catching prevention)
        # If stock is trading below intraday VWAP, apply a penalty
        if ltp_val and vwap_val and vwap_val > 0 and ltp_val < vwap_val:
            score -= 25
            matched_factors.append(
                f"⚠️ Intraday price (₹{ltp_val:,.1f}) is below VWAP (₹{vwap_val:,.1f}) — Knife-catching risk penalty applied"
            )

        # Weights from calibrated dictionary
        w_vol = self._factor_weights.get("volume_dry_up", 25)
        w_sq = self._factor_weights.get("squeeze_coiling", 20)
        w_ce = self._factor_weights.get("ce_unwind", 20)
        w_ob = self._factor_weights.get("order_block_anchor", 15)
        w_rrg = self._factor_weights.get("sector_tailwind", 10)

        # Factor A: Volume Dry-Up (Minervini "No Supply" test)
        p_ratio = features.get("prior_vol_ratio")
        if p_ratio is not None and p_ratio <= 0.20:
            score += w_vol
            matched_factors.append(
                f"Extreme Volume Dry-Up ({p_ratio * 100:.0f}% of 20D SMA — Complete Seller Exhaustion)"
            )
        elif p_ratio is not None and p_ratio <= 0.45:
            score += int(w_vol * 0.65)
            matched_factors.append(f"Healthy Volume Contraction ({p_ratio * 100:.0f}% of 20D SMA)")

        # Factor B: Squeeze Coiling (John Carter TTM Squeeze)
        sq_bars = features.get("squeeze_bars")
        if sq_bars is not None and sq_bars >= 4:
            score += w_sq
            matched_factors.append(
                f"Bollinger Bands tightly compressed in Keltner Squeeze ({sq_bars} bars coiled)"
            )
        elif sq_bars is not None and sq_bars >= 2:
            score += int(w_sq * 0.55)
            matched_factors.append(f"Active Squeeze compression coiling ({sq_bars} bars)")

        # Factor C: Call Options Shedding (Gamma Trap)
        ce_unwind = features.get("ce_unwind_pct")
        if ce_unwind is not None and ce_unwind <= -20.0:
            score += w_ce
            matched_factors.append(
                f"Call writers capitulating ({ce_unwind:.1f}% OI unwound — Gamma Trap primed)"
            )
        elif ce_unwind is not None and ce_unwind <= -10.0:
            score += int(w_ce * 0.55)
            matched_factors.append(f"Call OI liquidation detected ({ce_unwind:.1f}%)")

        # Factor D: Proximity to Order Block / Swing Low
        ob_dist = features.get("ob_distance_pct")
        if ob_dist is not None and ob_dist <= 0.8:
            score += w_ob
            matched_factors.append(
                f"Priced within {ob_dist:.1f}% of Bullish Order Block base (Asymmetric low-SL anchor)"
            )

        # Factor E: Leading Sector Tailwind
        rrg_q = features.get("rrg_quadrant")
        if rrg_q == "LEADING":
            score += w_rrg
            matched_factors.append(
                "Parent sector in Leading RRG quadrant (Institutional inflow tailwind)"
            )
        elif rrg_q == "IMPROVING":
            score += int(w_rrg * 0.6)
            matched_factors.append("Parent sector in Improving RRG quadrant (Emerging rotation)")

        # Factor F: Minervini SEPA Fundamentals
        if features.get("sepa_qualified") is True:
            score += 10
            matched_factors.append(
                "Minervini SEPA Qualified: ≥25% YoY EPS acceleration (Institutional leadership growth)"
            )

        score = max(5, min(98, score))
        is_candidate = score >= 70

        # Find closest archetype from memory with feature similarity
        best_match = None
        trusted_fingerprints = [
            fp for fp in self._fingerprints if fp.provenance == "SOURCE_TAGGED_HISTORICAL_DATA"
        ]
        if trusted_fingerprints:
            best_sim = -1
            cand_sepa = features.get("sepa_qualified", False)
            cand_rrg = features.get("rrg_quadrant", "")
            for fp in trusted_fingerprints:
                sim = 0
                compared = 0
                if cand_sepa is not None and fp.sepa_qualified is not None:
                    compared += 1
                if cand_sepa is True and fp.sepa_qualified is True:
                    sim += 20
                if cand_rrg is not None and fp.rrg_quadrant is not None:
                    compared += 1
                if cand_rrg is not None and cand_rrg == fp.rrg_quadrant:
                    sim += 15
                cand_vol = features.get("prior_vol_ratio")
                if cand_vol is not None and fp.prior_vol_ratio is not None:
                    compared += 1
                    if abs(cand_vol - fp.prior_vol_ratio) < 0.2:
                        sim += 15
                if sq_bars is not None and fp.squeeze_bars is not None:
                    compared += 1
                if (
                    sq_bars is not None
                    and fp.squeeze_bars is not None
                    and abs(sq_bars - fp.squeeze_bars) <= 1
                ):
                    sim += 10
                if compared and sim > best_sim:
                    best_sim = sim
                    best_match = f"{fp.symbol} ({fp.date})"

        if is_candidate:
            if sq_bars is None:
                rec_action = "MONITOR_FOR_CONFIRMATION"
            else:
                rec_action = "BUY_COILING_ZONE" if sq_bars >= 2 else "BUY_EARLY_BREAKOUT"
        else:
            rec_action = "MONITOR_FOR_DRY_UP"

        return PatternMatchResult(
            symbol=clean_sym,
            similarity_score=score,
            closest_archetype=best_match,
            matched_factors=matched_factors,
            is_explosive_candidate=is_candidate,
            recommended_entry_action=rec_action,
            # No execution-fill sample supports a realized expectancy estimate.
            expected_asymmetry_rr=None,
            coiling_pivot_high=features.get("coiling_pivot_high"),
        )

    # ── Learning Analytics ───────────────────────────────────

    def get_learned_archetypes(self) -> list[dict[str, Any]]:
        return [f.to_dict() for f in self._fingerprints]

    def get_active_session_traps(self) -> list[dict[str, Any]]:
        """Returns all breakout trap pivot levels recorded during today's session."""
        today_str = datetime.now(IST).strftime("%Y-%m-%d")
        all_traps = []
        with self._lock:
            for sym, traps in self._session_trap_pivots.items():
                for t in traps:
                    if t.get("session_date") == today_str:
                        all_traps.append(dict(t))
        return all_traps

    def get_learning_analytics(self) -> dict[str, Any]:
        """Returns comprehensive self-learning intelligence and factor attribution."""
        source_tagged_archetypes = [
            fp for fp in self._fingerprints if fp.provenance == "SOURCE_TAGGED_HISTORICAL_DATA"
        ]
        event_counts: dict[str, int] = {}
        for outcome in self._outcomes:
            event_counts[outcome.outcome] = event_counts.get(outcome.outcome, 0) + 1

        return {
            "total_archetypes_learned": len(source_tagged_archetypes),
            "total_archetypes_recorded": len(self._fingerprints),
            "unverified_archetypes_count": len(self._fingerprints) - len(source_tagged_archetypes),
            "total_tracked_outcomes": len(self._outcomes),
            "total_invalidations_analyzed": len(self._post_mortems),
            "performance_metrics_status": self._outcome_calibration_status,
            "win_rate_pct": None,
            "average_realized_rr": None,
            "outcome_event_counts": event_counts,
            "active_factor_weights": self._factor_weights,
            "factor_weight_source": self._factor_weight_source,
            "active_lockouts": self.get_locked_out_symbols(),
            "active_session_traps": self.get_active_session_traps(),
            "archetypes": [f.to_dict() for f in source_tagged_archetypes[:5]],
            "recent_outcomes": [o.to_dict() for o in self._outcomes[-10:]],
            "recent_post_mortems": [pm.to_dict() for pm in self._post_mortems[:10]],
        }


# Global singleton instance
pattern_learning_engine = PatternLearningEngine()
