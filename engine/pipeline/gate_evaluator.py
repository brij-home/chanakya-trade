"""
engine/pipeline/gate_evaluator.py
─────────────────────────────────
Unified Gate Evaluator consolidating SignalPolicy, ConfidenceCalibrator,
Meta-Labeler Half-Kelly 0-lot cost gate, and CoherenceGate.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from engine.confidence_calibrator import (
    CalibratedConfidenceReport,
    calibrate_alert_confidence,
)
from engine.meta_labeler import MetaLabelPrediction, score_meta_label_and_kelly
from engine.signal_policy import (
    CandidatePolicyResult,
    build_policy_context_from_alert,
    evaluate_candidate_policy,
)

logger = logging.getLogger("engine.pipeline.gate_evaluator")


@dataclass
class UnifiedGateDecision:
    policy_result: CandidatePolicyResult
    calibration_report: CalibratedConfidenceReport
    meta_prediction: MetaLabelPrediction
    accepted: bool
    recommended_lots: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "recommended_lots": self.recommended_lots,
            "reason": self.reason,
            "policy_decision": self.policy_result.decision,
            "calibration": self.calibration_report.to_dict(),
            "meta_label": self.meta_prediction.to_dict(),
        }


def evaluate_unified_candidate_gates(
    alert: Any,
    *,
    meta_features: Optional[dict[str, Any]] = None,
    budget_lots: int = 1,
    sl_r_distance: float = 1.0,
    enforce_calibrated_meta_gate: bool = False,
) -> UnifiedGateDecision:
    """Run SignalPolicy -> ConfidenceCalibrator -> MetaLabeler Half-Kelly 0-lot check."""
    ctx = build_policy_context_from_alert(alert)
    pol_res = evaluate_candidate_policy(ctx, alert)
    cal_res = calibrate_alert_confidence(alert)

    feats = dict(meta_features or {})
    metrics = getattr(alert, "metrics", None)
    if not feats and isinstance(metrics, dict):
        feats = dict(metrics)

    meta_res = score_meta_label_and_kelly(
        feats,
        budget_lots=budget_lots,
        sl_r_distance=sl_r_distance,
    )

    accepted = pol_res.decision == "ACCEPT"
    lots = budget_lots
    reason = "Policy ACCEPTED"

    if not accepted:
        lots = 0
        reason = (
            pol_res.blocking_gate.reason if pol_res.blocking_gate else "Rejected by SignalPolicy"
        )
    elif (
        enforce_calibrated_meta_gate
        and meta_res.status == "CALIBRATED"
        and not meta_res.cost_gate_passed
    ):
        accepted = False
        lots = 0
        reason = meta_res.reason
    elif meta_res.status == "CALIBRATED":
        lots = meta_res.recommended_lots

    return UnifiedGateDecision(
        policy_result=pol_res,
        calibration_report=cal_res,
        meta_prediction=meta_res,
        accepted=accepted,
        recommended_lots=lots,
        reason=reason,
    )
