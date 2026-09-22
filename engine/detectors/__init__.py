"""
Detector modules for ChanakyaTrade automated alert engine.
"""

from __future__ import annotations

from engine.detectors.circuit import detect_circuit_proximity
from engine.detectors.commodity import detect_commodity_breakouts
from engine.detectors.crypto import detect_crypto_signals, detect_single_crypto_symbol
from engine.detectors.currency import detect_currency_breakouts
from engine.detectors.gamma_blast import detect_gamma_blast
from engine.detectors.index_call_setup import detect_index_call_setup
from engine.detectors.index_put_setup import detect_index_put_setup
from engine.detectors.intraday_spark import detect_intraday_mover_sparks
from engine.detectors.opening_drive import detect_opening_drive
from engine.detectors.options_momentum import detect_options_momentum_breakouts
from engine.detectors.orb import detect_opening_range_breakout
from engine.detectors.pattern_coiling import detect_learned_pattern_coiling
from engine.detectors.preopen_bias import detect_preopen_bias
from engine.detectors.squeeze_breakout import detect_squeeze_breakout

__all__ = [
    "detect_gamma_blast",
    "detect_index_call_setup",
    "detect_index_put_setup",
    "detect_opening_drive",
    "detect_preopen_bias",
    "detect_squeeze_breakout",
    "detect_circuit_proximity",
    "detect_learned_pattern_coiling",
    "detect_opening_range_breakout",
    "detect_options_momentum_breakouts",
    "detect_commodity_breakouts",
    "detect_currency_breakouts",
    "detect_crypto_signals",
    "detect_single_crypto_symbol",
    "detect_intraday_mover_sparks",
]
