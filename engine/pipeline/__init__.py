"""
engine/pipeline/__init__.py
───────────────────────────
Pipeline modules for ChanakyaTrade alert processing.
"""

from engine.pipeline.alert_dispatcher import DispatchClassification, classify_alert_dispatch
from engine.pipeline.coherence_gate import CoherenceGate, coherence_gate
from engine.pipeline.gate_evaluator import UnifiedGateDecision, evaluate_unified_candidate_gates
from engine.pipeline.hierarchical_engine import (
    HierarchicalPipelineVerdict,
    HierarchicalSignalPipeline,
    Level1ContextResult,
    Level2SetupResult,
    Level3ExecutionResult,
    hierarchical_pipeline,
)
from engine.pipeline.universe_scheduler import (
    BoundedBackgroundRunner,
    background_task_runner,
    prioritize_equities_by_velocity,
    schedule_cycle_targets,
)

__all__ = [
    "BoundedBackgroundRunner",
    "background_task_runner",
    "CoherenceGate",
    "coherence_gate",
    "DispatchClassification",
    "classify_alert_dispatch",
    "HierarchicalSignalPipeline",
    "hierarchical_pipeline",
    "HierarchicalPipelineVerdict",
    "Level1ContextResult",
    "Level2SetupResult",
    "Level3ExecutionResult",
    "UnifiedGateDecision",
    "evaluate_unified_candidate_gates",
    "prioritize_equities_by_velocity",
    "schedule_cycle_targets",
]
