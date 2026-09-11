"""
Detector modules for ChanakyaTrade automated alert engine.
"""

from __future__ import annotations

from engine.detectors.circuit import detect_circuit_proximity
from engine.detectors.gamma_blast import detect_gamma_blast
from engine.detectors.pattern_coiling import detect_learned_pattern_coiling
from engine.detectors.squeeze_breakout import detect_squeeze_breakout

__all__ = [
    "detect_gamma_blast",
    "detect_squeeze_breakout",
    "detect_circuit_proximity",
    "detect_learned_pattern_coiling",
]
