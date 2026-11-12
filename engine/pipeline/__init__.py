"""
engine/pipeline/__init__.py
───────────────────────────
Pipeline modules for ChanakyaTrade alert processing.
"""

from engine.pipeline.coherence_gate import CoherenceGate, coherence_gate
from engine.pipeline.hierarchical_engine import (
    HierarchicalPipelineVerdict,
    HierarchicalSignalPipeline,
    Level1ContextResult,
    Level2SetupResult,
    Level3ExecutionResult,
    hierarchical_pipeline,
)

__all__ = [
    "CoherenceGate",
    "coherence_gate",
    "HierarchicalSignalPipeline",
    "hierarchical_pipeline",
    "HierarchicalPipelineVerdict",
    "Level1ContextResult",
    "Level2SetupResult",
    "Level3ExecutionResult",
]
