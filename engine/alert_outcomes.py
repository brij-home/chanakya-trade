"""Evidence-qualified terminal outcomes for alert-path detector calibration.

These records describe a market-price path from an immutable setup anchor. They
are not broker fills, realized account P&L, or evidence of execution quality.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import math
from typing import Any, Optional

from engine.alert_expiry import is_alert_option_premium_level, is_option_seller

logger = logging.getLogger(__name__)

_PARTIAL_EXIT_MILESTONES = frozenset(
    {
        "T0_5_ACHIEVED",
        "DE_RISK_0_5R",
        "T1_ACHIEVED",
        "T2_ACHIEVED",
        "T3_ACHIEVED",
        "BREAKEVEN_LOCKED",
    }
)


@dataclass(frozen=True)
class TerminalForwardOutcome:
    """A terminal mark-to-market observation with immutable entry and stop anchors."""

    entry_price: float
    initial_stop_loss: float
    exit_price: float
    pnl_points: float
    pnl_pct: float
    realized_r: float


def calculate_terminal_forward_outcome(
    alert: Any, exit_price: Any
) -> Optional[TerminalForwardOutcome]:
    """Calculate a conservative terminal R only when the path is reconstructible.

    We exclude alerts with partial-scale milestones because their true blended
    outcome requires durable fills and quantities. A single terminal quote cannot
    reconstruct that P&L. Historical milestone price paths remain useful for audit,
    but are not admitted as completed outcomes to detector calibration.
    """
    if not bool(getattr(alert, "has_triggered", False)):
        return None

    direction = str(getattr(alert, "direction", "")).upper().strip()
    # A neutral or multi-leg payoff cannot be inferred from one quoted price.
    if direction not in {"BULLISH", "BEARISH", "BULL", "BEAR", "LONG", "SHORT", "BUY", "SELL"}:
        return None

    milestones = {
        str(value).upper() for value in (getattr(alert, "achieved_milestones", None) or [])
    }
    stage = str(getattr(alert, "stage", "")).upper()
    target_status = str(getattr(alert, "target_status", "")).upper()
    if "RUNNER" in stage or "RUNNER" in target_status:
        return None
    if milestones.intersection(_PARTIAL_EXIT_MILESTONES) or any(
        marker in stage or marker in target_status for marker in _PARTIAL_EXIT_MILESTONES
    ):
        return None

    is_option = is_alert_option_premium_level(alert)
    if is_option:
        entry_raw = getattr(alert, "initial_entry_premium", None) or getattr(
            alert, "trigger_level", None
        )
    else:
        entry_raw = getattr(alert, "trigger_level", None)

    stop_raw = getattr(alert, "initial_stop_loss", None)
    try:
        entry = float(entry_raw)
        stop = float(stop_raw)
        exit_value = float(exit_price)
    except (TypeError, ValueError):
        return None

    if not all(math.isfinite(value) and value > 0 for value in (entry, stop, exit_value)):
        return None

    short_payoff = (is_option and is_option_seller(alert)) or (
        not is_option and direction in ("BEARISH", "BEAR", "SHORT", "SELL")
    )
    if short_payoff:
        if stop <= entry:
            return None
        pnl_points = entry - exit_value
    else:
        if stop >= entry:
            return None
        pnl_points = exit_value - entry

    initial_risk = abs(entry - stop)
    if initial_risk <= 0:
        return None
    realized_r = pnl_points / initial_risk
    pnl_pct = pnl_points / entry * 100.0
    # Match the evaluator's scale sanity envelope. Extreme moves are treated as
    # suspect data and excluded rather than clipped into a distorted observation.
    if not math.isfinite(realized_r) or realized_r < -5.0 or realized_r > 25.0:
        return None

    return TerminalForwardOutcome(
        entry_price=entry,
        initial_stop_loss=stop,
        exit_price=exit_value,
        pnl_points=pnl_points,
        pnl_pct=pnl_pct,
        realized_r=realized_r,
    )


def record_terminal_forward_outcome(
    alert: Any,
    outcome: Optional[TerminalForwardOutcome],
    *,
    event: str,
) -> None:
    """Persist one explicitly labeled terminal forward-path sample when eligible."""
    if outcome is None:
        logger.info(
            "[AlertOutcomes] Detector calibration skipped for %s at %s: "
            "no complete unscaled terminal path with immutable entry/stop anchors",
            getattr(alert, "alert_id", "unknown"),
            event,
        )
        return

    if (
        not bool(getattr(alert, "is_live", False))
        or str(getattr(alert, "environment", "")).upper() != "LIVE"
    ):
        logger.info(
            "[AlertOutcomes] Detector calibration skipped for non-live alert %s at %s",
            getattr(alert, "alert_id", "unknown"),
            event,
        )
        return

    realized_r = outcome.realized_r
    result = "WIN" if realized_r > 0 else "LOSS" if realized_r < 0 else "FLAT"
    try:
        from engine.detector_circuit_breaker import detector_circuit_breaker

        detector_circuit_breaker.record_outcome(
            alert_id=str(getattr(alert, "alert_id", "")),
            symbol=str(getattr(alert, "symbol", "")),
            alert_type=str(getattr(alert, "alert_type", "")),
            outcome=result,
            realized_r=realized_r,
            provenance="ALERT_FORWARD_PATH_TERMINAL",
        )
    except Exception as exc:
        # Outcome persistence must never fabricate success. The close itself is
        # already persisted; retain a trace if calibration persistence fails.
        logger.error(
            "[AlertOutcomes] Could not persist terminal forward outcome for %s at %s: %s",
            getattr(alert, "alert_id", "unknown"),
            event,
            exc,
            exc_info=True,
        )
