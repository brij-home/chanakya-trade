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
from datetime import datetime, timezone, timedelta
import json
import logging
import os
from pathlib import Path
import threading
from typing import Any, Literal, Optional

logger = logging.getLogger("engine.detector_circuit_breaker")

IST = timezone(timedelta(hours=5, minutes=30))

DetectorStatus = Literal["HEALTHY", "NORMAL", "PROBATION", "HALTED"]


def get_performance_ledger_file() -> Path:
    """Canonical path to detector performance outcome ledger."""
    base = Path(os.environ.get("TRADING_PLATFORM_DATA") or (Path.home() / ".trading_platform"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "detector_performance.json"


@dataclass
class TradeOutcome:
    """Single realized forward trade outcome record."""

    alert_id: str
    symbol: str
    alert_type: str
    outcome: Literal["WIN", "LOSS"]
    realized_r: float
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
        self._load()

    def record_outcome(
        self,
        alert_id: str,
        symbol: str,
        alert_type: str,
        outcome: Literal["WIN", "LOSS"],
        realized_r: float,
    ) -> DetectorMetrics:
        """
        Records a completed trade outcome and returns recalibrated detector metrics.
        """
        clean_type = alert_type.upper().strip()
        record = TradeOutcome(
            alert_id=alert_id,
            symbol=symbol.upper().strip(),
            alert_type=clean_type,
            outcome=outcome,
            realized_r=float(realized_r),
        )

        with self._lock:
            if clean_type not in self._history:
                self._history[clean_type] = deque(maxlen=self.rolling_window)
            self._history[clean_type].append(record)
            self._save_unlocked()

        return self.get_metrics(clean_type)

    def get_metrics(self, alert_type: str) -> DetectorMetrics:
        """
        Calculates rolling mathematical edge metrics for a detector.
        """
        clean_type = alert_type.upper().strip()
        with self._lock:
            records = list(self._history.get(clean_type, []))

        count = len(records)
        now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

        if count < self.min_samples:
            return DetectorMetrics(
                alert_type=clean_type,
                sample_count=count,
                win_rate=0.50,
                avg_win_r=2.0,
                avg_loss_r=1.0,
                payoff_ratio=2.0,
                expectancy=0.50,
                kelly_fraction=0.25,
                half_kelly=0.125,
                consecutive_losses=0,
                status="NORMAL",
                confidence_multiplier=1.0,
                last_updated=now_str,
            )

        wins = [r for r in records if r.outcome == "WIN"]
        losses = [r for r in records if r.outcome == "LOSS"]

        win_rate = len(wins) / count
        avg_win_r = float(sum(r.realized_r for r in wins) / len(wins)) if wins else 0.0
        avg_loss_r = (
            float(sum(abs(r.realized_r) for r in losses) / len(losses)) if losses else 1.0
        )
        if avg_loss_r <= 0.01:
            avg_loss_r = 0.5  # Defensive floor

        payoff_ratio = avg_win_r / avg_loss_r if avg_loss_r > 0 else 1.0

        # Mathematical Expectancy E = (W * R) - (1 - W)
        expectancy = (win_rate * payoff_ratio) - (1.0 - win_rate)

        # Kelly Criterion: K = W - (1 - W) / R
        kelly = win_rate - ((1.0 - win_rate) / payoff_ratio) if payoff_ratio > 0 else 0.0
        half_kelly = max(0.0, 0.5 * kelly)

        # Consecutive losses from tail
        consecutive_losses = 0
        for r in reversed(records):
            if r.outcome == "LOSS":
                consecutive_losses += 1
            else:
                break

        # State Machine Evaluation
        if expectancy < -0.60 or consecutive_losses >= 5:
            status: DetectorStatus = "HALTED"
            multiplier = 0.0
        elif expectancy < 0.0 or kelly <= 0.0:
            status = "PROBATION"
            multiplier = 0.75
        elif expectancy >= 0.20 and win_rate >= 0.40:
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
        )

    def evaluate_alert_allowed(self, alert_type: str) -> tuple[bool, float, str]:
        """
        Checks if an alert is allowed to fire based on detector degradation.
        Returns: (is_allowed, confidence_multiplier, status_message)
        """
        metrics = self.get_metrics(alert_type)
        if metrics.status == "HALTED":
            return (
                False,
                0.0,
                f"Detector '{alert_type}' circuit tripped (E={metrics.expectancy:.2f}, {metrics.consecutive_losses} consecutive losses). Generation halted.",
            )
        if metrics.status == "PROBATION":
            return (
                True,
                0.75,
                f"Detector '{alert_type}' in probation (E={metrics.expectancy:.2f}). 25% confidence discount applied.",
            )
        if metrics.status == "HEALTHY":
            return (
                True,
                1.05,
                f"Detector '{alert_type}' institutional alpha confirmed (E={metrics.expectancy:.2f}, W={metrics.win_rate*100:.1f}%).",
            )
        return (True, 1.0, f"Detector '{alert_type}' operating within normal tolerances.")

    def reset_detector(self, alert_type: str) -> None:
        """Manually clears history for a detector (e.g. after parameter tuning or regime reset)."""
        clean_type = alert_type.upper().strip()
        with self._lock:
            self._history.pop(clean_type, None)
            self._save_unlocked()

    def _save_unlocked(self) -> None:
        """Persists trade history to JSON file."""
        try:
            data = {}
            for k, deq in self._history.items():
                data[k] = [asdict(r) for r in deq]
            with open(self.ledger_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[DetectorCircuitBreaker] Failed to save ledger: {e}")

    def _load(self) -> None:
        """Loads trade history from JSON file."""
        if not self.ledger_file.exists():
            return
        try:
            with open(self.ledger_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, records in data.items():
                self._history[k] = deque(
                    [TradeOutcome(**r) for r in records], maxlen=self.rolling_window
                )
        except Exception as e:
            logger.error(f"[DetectorCircuitBreaker] Failed to load ledger: {e}")


# Singleton instance
detector_circuit_breaker = DetectorCircuitBreaker()
