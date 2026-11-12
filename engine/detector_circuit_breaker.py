"""
engine/detector_circuit_breaker.py
───────────────────────────────────
Institutional Detector Degradation Circuit Breaker & Rolling Kelly Governor.

Continuously tracks the realized empirical performance of each signal detector
(e.g., GAMMA_BLAST, ORB, SQUEEZE_BREAKOUT, PRE_INFLECTION_DRYUP) across forward outcomes.

Mathematical Foundation:
  1. Win Rate: W = wins / total
  2. Payoff Ratio: R = avg_win_R / avg_loss_R
  3. Mathematical Expectancy: E = (W * R) - (1 - W)
  4. Full Kelly: K = W - (1 - W) / R
  5. Half Kelly: HK = max(0.0, 0.5 * K)

Degradation State Machine:
  - HEALTHY (E >= 0.20): Full confidence, optional +5% conviction bonus.
  - NORMAL (0.0 <= E < 0.20): Standard baseline confidence.
  - PROBATION (E < 0.0 or K <= 0.0): Adverse regime detected. 25% confidence discount,
    flagged in actionable plan, auto-ticket execution disabled.
  - HALTED (E < -0.35 or consecutive_losses >= 5): Detector tripped circuit breaker.
    Suppressed from generating noisy or negative-edge alerts until manual reset or regime shift.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import threading
import time
from typing import Any, Literal, Optional

logger = logging.getLogger("engine.detector_circuit_breaker")

from config.constants import IST
from config.paths import app_data_path

DetectorStatus = Literal["UNCALIBRATED", "HEALTHY", "NORMAL", "PROBATION", "HALTED"]
OutcomeProvenance = Literal[
    "ALERT_FORWARD_PATH_TERMINAL",
    "VERIFIED_BROKER_FILL",
    "TEST",
    "LEGACY_UNVERIFIED",
]
CALIBRATABLE_OUTCOME_PROVENANCE = frozenset({"ALERT_FORWARD_PATH_TERMINAL", "TEST"})


def _is_test_runtime() -> bool:
    """Keep synthetic calibration provenance unavailable to normal app runs."""
    return "PYTEST_CURRENT_TEST" in os.environ


def _is_calibratable_record(record: "TradeOutcome") -> bool:
    if record.provenance == "ALERT_FORWARD_PATH_TERMINAL":
        return True
    return record.provenance == "TEST" and _is_test_runtime()


def get_performance_ledger_file() -> Path:
    """Canonical path to detector performance outcome ledger."""
    p = app_data_path("detector_performance.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@dataclass
class TradeOutcome:
    """Single terminal forward-path observation or explicitly tagged test record."""

    alert_id: str
    symbol: str
    alert_type: str
    outcome: Literal["WIN", "LOSS", "FLAT"]
    realized_r: float
    # Historical rows without provenance are deliberately retained for audit but
    # excluded from calibration because older code could write assumed milestone R.
    provenance: OutcomeProvenance = "LEGACY_UNVERIFIED"
    timestamp: str = field(
        default_factory=lambda: datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    )


@dataclass
class DetectorMetrics:
    """Rolling statistical edge metrics for a single detector."""

    alert_type: str
    sample_count: int
    win_rate: float
    avg_win_r: float
    avg_loss_r: float
    payoff_ratio: float
    expectancy: float
    kelly_fraction: float
    half_kelly: float
    consecutive_losses: int
    status: DetectorStatus
    confidence_multiplier: float
    last_updated: str
    today_consecutive_losses: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DetectorCircuitBreaker:
    """
    Thread-safe governor evaluating detector health and applying Kelly circuit breakers.
    """

    def __init__(
        self,
        ledger_file: Optional[Path] = None,
        rolling_window: int = 20,
        min_samples: int = 5,
    ) -> None:
        self.ledger_file = Path(ledger_file) if ledger_file else get_performance_ledger_file()
        self.rolling_window = rolling_window
        self.min_samples = min_samples
        self._lock = threading.Lock()
        self._history: dict[str, deque[TradeOutcome]] = {}
        self._seen_outcomes: dict[str, str] = {}
        self._load()

    def record_outcome(
        self,
        alert_id: str,
        symbol: str,
        alert_type: str,
        outcome: Literal["WIN", "LOSS", "FLAT"],
        realized_r: float,
        *,
        provenance: Literal["ALERT_FORWARD_PATH_TERMINAL", "VERIFIED_BROKER_FILL", "TEST"],
    ) -> DetectorMetrics:
        """
        Records a completed trade outcome and returns recalibrated detector metrics.
        """
        clean_type = alert_type.upper().strip()
        if not alert_id or not clean_type or not symbol or not math.isfinite(float(realized_r)):
            raise ValueError(
                "Outcome requires alert_id, symbol, detector type and finite realized_r."
            )
        if provenance == "VERIFIED_BROKER_FILL":
            raise ValueError(
                "Verified broker outcomes require an account-scoped reconciled fill-ledger "
                "writer; a caller-supplied provenance label is insufficient."
            )
        if provenance == "TEST" and not _is_test_runtime():
            raise ValueError("TEST outcome provenance is only accepted while running pytest.")
        if provenance not in CALIBRATABLE_OUTCOME_PROVENANCE:
            raise ValueError("Outcome provenance is not eligible for detector calibration.")
        normalized_r = float(realized_r)
        if normalized_r > 0 and outcome != "WIN":
            raise ValueError("Positive realized_r must be recorded as WIN.")
        if normalized_r < 0 and outcome != "LOSS":
            raise ValueError("Negative realized_r must be recorded as LOSS.")
        if normalized_r == 0:
            outcome = "FLAT"
        record = TradeOutcome(
            alert_id=alert_id,
            symbol=symbol.upper().strip(),
            alert_type=clean_type,
            outcome=outcome,
            realized_r=normalized_r,
            provenance=provenance,
        )
        dedup_key = f"{clean_type}:{record.alert_id}"
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "symbol": record.symbol,
                    "outcome": record.outcome,
                    "realized_r": record.realized_r,
                    "provenance": record.provenance,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        with self._lock:
            existing_fingerprint = self._seen_outcomes.get(dedup_key)
            if existing_fingerprint:
                if existing_fingerprint != fingerprint:
                    raise ValueError(
                        f"Conflicting outcome replay for alert {record.alert_id} / {clean_type}."
                    )
                duplicate = True
            else:
                duplicate = False
                self._seen_outcomes[dedup_key] = fingerprint
            if clean_type not in self._history:
                self._history[clean_type] = deque(maxlen=self.rolling_window)
            if not duplicate:
                self._history[clean_type].append(record)
                self._save_unlocked()

        return self.get_metrics(clean_type)

    def get_metrics(self, alert_type: str) -> DetectorMetrics:
        """
        Calculates rolling mathematical edge metrics for a detector.
        """
        clean_type = alert_type.upper().strip()
        with self._lock:
            records = [
                record
                for record in self._history.get(clean_type, [])
                if _is_calibratable_record(record)
            ]

        count = len(records)
        now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

        wins = [r for r in records if r.outcome == "WIN"]
        losses = [r for r in records if r.outcome == "LOSS"]
        if count < self.min_samples:
            return DetectorMetrics(
                alert_type=clean_type,
                sample_count=count,
                win_rate=0.0,
                avg_win_r=0.0,
                avg_loss_r=0.0,
                payoff_ratio=0.0,
                expectancy=0.0,
                kelly_fraction=0.0,
                half_kelly=0.0,
                consecutive_losses=0,
                status="UNCALIBRATED",
                confidence_multiplier=1.0,
                last_updated=now_str,
            )

        if not wins and not losses:
            # A sample of flat outcomes contains no directional or risk evidence.
            return DetectorMetrics(
                alert_type=clean_type,
                sample_count=count,
                win_rate=0.0,
                avg_win_r=0.0,
                avg_loss_r=0.0,
                payoff_ratio=0.0,
                expectancy=0.0,
                kelly_fraction=0.0,
                half_kelly=0.0,
                consecutive_losses=0,
                status="UNCALIBRATED",
                confidence_multiplier=1.0,
                last_updated=now_str,
            )

        if not wins:
            avg_loss_r = float(sum(abs(r.realized_r) for r in losses) / len(losses))
            expectancy = float(sum(r.realized_r for r in records) / count)
            # A run with only losses can justify degradation, but cannot imply a
            # payoff ratio or positive Kelly allocation.
            win_rate = 0.0
            avg_win_r = 0.0
            payoff_ratio = 0.0
            kelly = 0.0
            half_kelly = 0.0
        elif not losses:
            # Wins without any observed losses do not estimate downside or a
            # payoff ratio. Do not convert a one-sided sample into alpha.
            return DetectorMetrics(
                alert_type=clean_type,
                sample_count=count,
                win_rate=0.0,
                avg_win_r=0.0,
                avg_loss_r=0.0,
                payoff_ratio=0.0,
                expectancy=0.0,
                kelly_fraction=0.0,
                half_kelly=0.0,
                consecutive_losses=0,
                status="UNCALIBRATED",
                confidence_multiplier=1.0,
                last_updated=now_str,
            )
        else:
            win_rate = len(wins) / count
            avg_win_r = float(sum(r.realized_r for r in wins) / len(wins))
            avg_loss_r = float(sum(abs(r.realized_r) for r in losses) / len(losses))
            if avg_loss_r <= 0.01:
                return DetectorMetrics(
                    alert_type=clean_type,
                    sample_count=count,
                    win_rate=0.0,
                    avg_win_r=0.0,
                    avg_loss_r=0.0,
                    payoff_ratio=0.0,
                    expectancy=0.0,
                    kelly_fraction=0.0,
                    half_kelly=0.0,
                    consecutive_losses=0,
                    status="UNCALIBRATED",
                    confidence_multiplier=1.0,
                    last_updated=now_str,
                )
            payoff_ratio = avg_win_r / avg_loss_r
            # Use observed average R per outcome rather than an assumed payoff
            # floor; the formula is equivalent when wins/losses are directional.
            expectancy = float(sum(r.realized_r for r in records) / count)
            kelly = win_rate - ((1.0 - win_rate) / payoff_ratio) if payoff_ratio > 0 else 0.0
            half_kelly = max(0.0, 0.5 * kelly)

        # Consecutive losses from tail in CURRENT session vs historical
        today_str = datetime.now(IST).strftime("%Y-%m-%d")
        consecutive_losses = 0
        today_consecutive_losses = 0
        for r in reversed(records):
            if r.outcome == "LOSS":
                consecutive_losses += 1
                r_day = (r.timestamp or "")[:10]
                if r_day == today_str:
                    today_consecutive_losses += 1
            else:
                break

        # Kelly and positive-edge status require account-bound fill provenance.
        # Alert market paths may conservatively degrade a detector, but cannot
        # claim a tradable edge or produce a Kelly allocation.
        # Until the account-scoped, independently reconciled fill writer exists,
        # production cannot claim verified performance. TEST samples exercise
        # the math in pytest but are never trusted by normal application runs.
        has_verified_performance_provenance = (
            _is_test_runtime()
            and bool(records)
            and all(record.provenance == "TEST" for record in records)
        )
        if not has_verified_performance_provenance:
            kelly = 0.0
            half_kelly = 0.0

        # State Machine Evaluation
        # If 5 consecutive losses occurred in TODAY's session, or deeply negative expectancy with >=3 losses today:
        if today_consecutive_losses >= 5 or (expectancy < -0.60 and today_consecutive_losses >= 3):
            status: DetectorStatus = "HALTED"
            multiplier = 0.0
        elif (
            consecutive_losses >= 3
            or today_consecutive_losses >= 2
            or expectancy < 0.0
            or (has_verified_performance_provenance and kelly <= 0.0)
            or (expectancy < -0.60 and today_consecutive_losses < 3)
        ):
            status = "PROBATION"
            multiplier = 0.75
        elif has_verified_performance_provenance and expectancy >= 0.20 and win_rate >= 0.40:
            status = "HEALTHY"
            multiplier = 1.05
        else:
            status = "NORMAL"
            multiplier = 1.0

        return DetectorMetrics(
            alert_type=clean_type,
            sample_count=count,
            win_rate=round(win_rate, 3),
            avg_win_r=round(avg_win_r, 2),
            avg_loss_r=round(avg_loss_r, 2),
            payoff_ratio=round(payoff_ratio, 2),
            expectancy=round(expectancy, 3),
            kelly_fraction=round(kelly, 3),
            half_kelly=round(half_kelly, 3),
            consecutive_losses=consecutive_losses,
            status=status,
            confidence_multiplier=round(multiplier, 2),
            last_updated=now_str,
            today_consecutive_losses=today_consecutive_losses,
        )

    def evaluate_alert_allowed(self, alert_type: str) -> tuple[bool, float, str]:
        """
        Checks if an alert is allowed to fire based on detector degradation.
        Returns: (is_allowed, confidence_multiplier, status_message)
        """
        self._maybe_reload()
        metrics = self.get_metrics(alert_type)
        if metrics.status == "HALTED":
            return (
                False,
                0.0,
                f"Detector '{alert_type}' circuit tripped (E={metrics.expectancy:.2f}, {metrics.consecutive_losses} consecutive losses). Generation halted.",
            )
        if metrics.status == "PROBATION":
            reason_detail = (
                f"{metrics.today_consecutive_losses} intraday consecutive losses today"
                if metrics.today_consecutive_losses >= 2
                else f"E={metrics.expectancy:.2f}"
            )
            return (
                True,
                0.75,
                f"Detector '{alert_type}' in probation ({reason_detail}). 25% confidence discount applied.",
            )
        if metrics.status == "HEALTHY":
            return (
                True,
                1.05,
                f"Detector '{alert_type}' institutional alpha confirmed (E={metrics.expectancy:.2f}, W={metrics.win_rate * 100:.1f}%).",
            )
        if metrics.status == "UNCALIBRATED":
            return (
                True,
                1.0,
                f"Detector '{alert_type}' is UNCALIBRATED ({metrics.sample_count}/{self.min_samples} "
                "eligible outcomes or missing both wins and losses); no empirical alpha bonus is applied.",
            )
        return (True, 1.0, f"Detector '{alert_type}' operating within normal tolerances.")

    def get_all_metrics(self) -> dict[str, dict[str, Any]]:
        """Returns metrics for all known detectors."""
        self._maybe_reload()
        with self._lock:
            keys = sorted(self._history.keys())
        return {k: self.get_metrics(k).to_dict() for k in keys}

    def reset_detector(self, alert_type: str) -> None:
        """Manually clears history for a detector (e.g. after parameter tuning or regime reset)."""
        clean_type = alert_type.upper().strip()
        with self._lock:
            self._history.pop(clean_type, None)
            self._save_unlocked()

    def reset_all(self) -> None:
        """Manually clears history for all detectors and resets ledger file."""
        with self._lock:
            self._history.clear()
            self._seen_outcomes.clear()
            self._save_unlocked()

    def _maybe_reload(self) -> None:
        """Reloads ledger if external processes updated the file on disk."""
        if not self.ledger_file.exists():
            return
        try:
            mtime = self.ledger_file.stat().st_mtime
            if mtime > getattr(self, "_last_mtime", 0.0):
                self._load()
        except Exception as e_suppressed:
            logger.debug(
                f"[engine.detector_circuit_breaker] Non-fatal exception suppressed: {e_suppressed}"
            )

    def _save_unlocked(self) -> None:
        """Persists trade history to JSON file atomically."""
        temp_path = None
        try:
            data = {"__schema_version__": 3, "__seen_outcomes__": self._seen_outcomes}
            for k, deq in self._history.items():
                data[k] = [asdict(r) for r in deq]
            self.ledger_file.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.ledger_file.with_suffix(f".tmp.{os.getpid()}")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, self.ledger_file)
            if self.ledger_file.exists():
                self._last_mtime = self.ledger_file.stat().st_mtime
        except Exception as e:
            logger.error(f"[DetectorCircuitBreaker] Failed to save ledger: {e}")
        finally:
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception as e_unlink:
                    logger.debug(
                        "[DetectorCircuitBreaker] Failed to unlink temp_path %s: %s",
                        temp_path,
                        e_unlink,
                    )

    def _load(self) -> None:
        """Loads trade history from JSON file with self-healing recovery on corruption."""
        self._history.clear()
        self._seen_outcomes.clear()
        if not self.ledger_file.exists():
            return
        try:
            self._last_mtime = self.ledger_file.stat().st_mtime
            with open(self.ledger_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._seen_outcomes = dict(data.get("__seen_outcomes__", {}))
            detector_data = {
                key: records for key, records in data.items() if not key.startswith("__")
            }
            for k, records in detector_data.items():
                self._history[k] = deque(
                    [TradeOutcome(**r) for r in records], maxlen=self.rolling_window
                )
                for record in self._history[k]:
                    dedup_key = f"{k}:{record.alert_id}"
                    self._seen_outcomes.setdefault(
                        dedup_key,
                        hashlib.sha256(
                            json.dumps(
                                {
                                    "symbol": record.symbol,
                                    "outcome": record.outcome,
                                    "realized_r": record.realized_r,
                                    **(
                                        {}
                                        if record.provenance == "LEGACY_UNVERIFIED"
                                        else {"provenance": record.provenance}
                                    ),
                                },
                                sort_keys=True,
                                separators=(",", ":"),
                            ).encode("utf-8")
                        ).hexdigest(),
                    )
        except json.JSONDecodeError as jde:
            # Self-healing: quarantine corrupted file and reinitialize clean ledger
            corrupted_backup = self.ledger_file.with_suffix(f".corrupted.{int(time.time())}.json")
            try:
                os.replace(self.ledger_file, corrupted_backup)
                logger.warning(
                    f"[DetectorCircuitBreaker] Self-healed corrupted ledger: quarantined {self.ledger_file} to {corrupted_backup} ({jde})"
                )
            except Exception as e_mv:
                logger.error(
                    f"[DetectorCircuitBreaker] Failed quarantining corrupted ledger: {e_mv}"
                )
            self._history.clear()
            self._save_unlocked()
        except Exception as e:
            logger.error(f"[DetectorCircuitBreaker] Failed to load ledger: {e}")


# Singleton instance
detector_circuit_breaker = DetectorCircuitBreaker()
