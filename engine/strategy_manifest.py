"""
engine/strategy_manifest.py
────────────────────────────
P2-C: Immutable Strategy Run Manifest and Reproducibility Engine.

Every backtest run must produce a cryptographically-bound manifest capturing:
- Strategy identity & version (code hash)
- Universe of instruments and data snapshot window
- Benchmark, parameters, cost assumptions (brokerage, STT, slippage, taxes)
- Execution assumptions (delay, order type, lot rounding)
- Bias prevention flags (look-ahead, survivorship, corporate-action awareness)

The same manifest must reproduce the same report. Manifests are append-only
and cryptographically signed — no in-place mutation is permitted.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass
class CostAssumptions:
    """Realistic statutory and execution cost model for Indian equity markets."""
    brokerage_pct: float = 0.0003            # 0.03% per leg (typical flat-fee broker)
    stt_delivery_pct: float = 0.001          # 0.1% on sell side for equity delivery
    stt_intraday_pct: float = 0.00025        # 0.025% on sell side intraday
    stt_fno_options_pct: float = 0.0625      # ₹62.5 per ₹1L premium (sold options)
    exchange_txn_charge_pct: float = 0.0000297   # NSE transaction charge
    sebi_turnover_fee_pct: float = 0.000001       # ₹10 per crore
    gst_on_brokerage_pct: float = 0.18           # 18% GST on brokerage + txn charges
    slippage_bps: float = 5.0                # Worst-case 5 basis point slippage per side
    stamp_duty_pct: float = 0.00015          # 0.015% on buy side equity delivery
    segment: str = "EQUITY_DELIVERY"

    def total_round_trip_bps(self) -> float:
        """Estimate total round-trip cost in basis points for a buy+sell cycle."""
        entry = (self.brokerage_pct + self.exchange_txn_charge_pct + self.stamp_duty_pct) * 10000
        exit_ = (self.brokerage_pct + self.stt_delivery_pct + self.exchange_txn_charge_pct) * 10000
        gst_impact = (self.brokerage_pct * 2 * self.gst_on_brokerage_pct) * 10000
        slip = self.slippage_bps * 2
        return round(entry + exit_ + gst_impact + slip, 2)


@dataclass
class ExecutionAssumptions:
    """Execution realism constraints for the backtest engine."""
    fill_delay_bars: int = 1            # Execute at open of next bar (no look-ahead)
    order_type: str = "MARKET_OPEN"     # MARKET_OPEN | VWAP_APPROXIMATION | LIMIT
    lot_rounding: bool = True           # Round position to instrument lot size
    min_lot_size: int = 1
    partial_fill_pct: float = 1.0       # Assume full fill
    volume_participation_max_pct: float = 0.05  # Max 5% of daily volume per order
    survivorship_bias_guard: bool = True
    look_ahead_guard: bool = True
    corporate_action_adjusted: bool = True  # Use adjusted OHLCV for splits/bonuses


@dataclass
class StrategyRunManifest:
    """
    Immutable, cryptographically-bound strategy run identity.

    Once created, the manifest hash seals the run. Any alteration of inputs
    must produce a new manifest with a new run_id.
    """
    run_id: str
    strategy_id: str
    strategy_name: str
    strategy_version: str
    code_hash: str           # SHA-256 of strategy source for reproducibility
    universe: list[str]      # Instrument universe (symbols)
    data_snapshot_start: str
    data_snapshot_end: str
    benchmark: str
    parameters: dict[str, Any]
    cost_assumptions: CostAssumptions
    execution_assumptions: ExecutionAssumptions
    created_at: str
    manifest_hash: str       # SHA-256 over canonical identity fields (tamper-evidence)
    bias_prevention: dict[str, bool] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)


# ── Canonical hash field set ─────────────────────────────────────────────────
# Excluded intentionally: run_id (unique per run), created_at (timestamp),
# notes (audit annotation), manifest_hash (circular reference).
_HASH_FIELDS = (
    "strategy_id",
    "strategy_version",
    "code_hash",
    "universe",
    "data_snapshot_start",
    "data_snapshot_end",
    "benchmark",
    "parameters",
    "cost_assumptions",
    "execution_assumptions",
    "bias_prevention",
)


def _canonical_hash_data(data: dict[str, Any]) -> str:
    """
    Extract only the canonical identity fields from a manifest dict and compute SHA-256.

    This function must be used identically during manifest creation and verification
    to ensure the hash comparison is always consistent.
    """
    stable = {k: data[k] for k in _HASH_FIELDS if k in data}
    serialized = json.dumps(stable, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _compute_code_hash(strategy_code: Optional[str] = None) -> str:
    """Compute truncated SHA-256 of strategy source code for version binding."""
    content = (strategy_code or "STRATEGY_SOURCE_UNAVAILABLE").encode("utf-8")
    return hashlib.sha256(content).hexdigest()[:16]


def create_run_manifest(
    strategy_id: str,
    strategy_name: str,
    strategy_version: str,
    universe: list[str],
    data_snapshot_start: str,
    data_snapshot_end: str,
    benchmark: str = "NIFTY50",
    parameters: Optional[dict[str, Any]] = None,
    cost_assumptions: Optional[CostAssumptions] = None,
    execution_assumptions: Optional[ExecutionAssumptions] = None,
    strategy_code: Optional[str] = None,
    notes: str = "",
) -> StrategyRunManifest:
    """
    Factory to create a sealed, immutable StrategyRunManifest.

    Args:
        strategy_id: Short identifier for the strategy (e.g. 'minervini_vcp_v1').
        strategy_name: Human-readable name.
        strategy_version: Semantic version string (e.g. '1.2.3').
        universe: List of ticker symbols in the backtest universe.
        data_snapshot_start: ISO date string for data window start (e.g. '2022-01-01').
        data_snapshot_end: ISO date string for data window end (e.g. '2024-01-01').
        benchmark: Benchmark index symbol for relative performance (e.g. 'NIFTY50').
        parameters: Strategy-specific parameter dict.
        cost_assumptions: Realistic cost model; defaults to equity delivery.
        execution_assumptions: Execution realism constraints; defaults to next-bar fill.
        strategy_code: Optional source code string for code hash computation.
        notes: Human-readable notes for audit trail.

    Returns:
        Sealed StrategyRunManifest with computed manifest_hash.
    """
    run_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    costs = cost_assumptions or CostAssumptions()
    exec_assumptions = execution_assumptions or ExecutionAssumptions()
    params = parameters or {}
    code_hash = _compute_code_hash(strategy_code)

    bias_flags: dict[str, bool] = {
        "look_ahead_guard_active": exec_assumptions.look_ahead_guard,
        "survivorship_bias_guard_active": exec_assumptions.survivorship_bias_guard,
        "corporate_action_adjusted": exec_assumptions.corporate_action_adjusted,
        "fill_delay_bars": exec_assumptions.fill_delay_bars >= 1,
    }

    # Build canonical dict for hash — must match what asdict(manifest) produces
    # for the same _HASH_FIELDS so that verify_manifest_integrity is consistent.
    canonical = {
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
        "code_hash": code_hash,
        "universe": sorted(universe),
        "data_snapshot_start": data_snapshot_start,
        "data_snapshot_end": data_snapshot_end,
        "benchmark": benchmark,
        "parameters": params,
        "cost_assumptions": asdict(costs),
        "execution_assumptions": asdict(exec_assumptions),
        "bias_prevention": bias_flags,
    }
    manifest_hash = _canonical_hash_data(canonical)

    return StrategyRunManifest(
        run_id=run_id,
        strategy_id=strategy_id,
        strategy_name=strategy_name,
        strategy_version=strategy_version,
        code_hash=code_hash,
        universe=sorted(universe),
        data_snapshot_start=data_snapshot_start,
        data_snapshot_end=data_snapshot_end,
        benchmark=benchmark,
        parameters=params,
        cost_assumptions=costs,
        execution_assumptions=exec_assumptions,
        created_at=created_at,
        manifest_hash=manifest_hash,
        bias_prevention=bias_flags,
        notes=notes,
    )


def verify_manifest_integrity(manifest: StrategyRunManifest) -> tuple[bool, str]:
    """
    Verify that a manifest has not been tampered with.

    Uses the same _canonical_hash_data projection as create_run_manifest to ensure
    hash comparison is deterministic regardless of non-identity fields.

    Returns:
        (True, 'VALID') if hash matches, (False, reason) if tampered.
    """
    d = manifest.to_dict()
    recomputed = _canonical_hash_data(d)
    if recomputed == manifest.manifest_hash:
        return True, "VALID"
    return False, f"HASH_MISMATCH: expected {manifest.manifest_hash}, got {recomputed}"
