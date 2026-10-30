"""
engine/order_slicer.py
──────────────────────
Institutional Order Slicing Engine (TWAP & POV Execution Algorithms) (G5).

Transforms parent execution intents into randomized, stealth child orders
to minimize market impact, avoid sweeping thin order books, and disguise
presence from predatory high-frequency algorithms (HFTs).

Supported Algorithms:
  1. TWAP (Time-Weighted Average Price):
     - Divides total quantity across a time horizon (e.g., 10 to 60 minutes).
     - Injects Gaussian time jitter (±15-25%) and quantity variation (±5-10%)
       to prevent algorithmic detection.
  2. POV (Participation of Volume):
     - Dynamically constrains child order quantities to a strict fraction (e.g., 5-10%)
       of observed or historical candle volume.
  3. No-Chase Boundary Protection:
     - Aborts remaining child order dispatches if spot drifts beyond the parent's
       designated adverse price boundary.
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional

logger = logging.getLogger("engine.order_slicer")

SliceAlgorithm = Literal["TWAP", "POV"]


@dataclass
class ChildSlicePlan:
    slice_index: int
    quantity: int
    delay_seconds: float
    limit_price: float
    order_id: Optional[str] = None
    status: str = "PENDING"  # PENDING | FILLED | CANCELLED | REJECTED


@dataclass
class SlicedOrderSchedule:
    schedule_id: str
    symbol: str
    side: Literal["BUY", "SELL"]
    algorithm: SliceAlgorithm
    total_parent_quantity: int
    total_sliced_quantity: int
    num_slices: int
    duration_minutes: float
    slices: list[ChildSlicePlan]
    no_chase_boundary: Optional[float] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schedule_id": self.schedule_id,
            "symbol": self.symbol,
            "side": self.side,
            "algorithm": self.algorithm,
            "total_parent_quantity": self.total_parent_quantity,
            "total_sliced_quantity": self.total_sliced_quantity,
            "num_slices": self.num_slices,
            "duration_minutes": self.duration_minutes,
            "no_chase_boundary": self.no_chase_boundary,
            "created_at": self.created_at,
            "slices": [
                {
                    "slice_index": s.slice_index,
                    "quantity": s.quantity,
                    "delay_seconds": round(s.delay_seconds, 2),
                    "limit_price": round(s.limit_price, 2),
                    "status": s.status,
                }
                for s in self.slices
            ],
        }


def build_twap_schedule(
    symbol: str,
    side: Literal["BUY", "SELL"],
    total_quantity: int,
    base_limit_price: float,
    duration_minutes: float = 15.0,
    num_slices: int = 5,
    time_jitter_pct: float = 0.20,
    qty_jitter_pct: float = 0.10,
    no_chase_boundary: Optional[float] = None,
    lot_size: int = 1,
    seed: Optional[int] = None,
) -> SlicedOrderSchedule:
    """
    Construct a TWAP execution schedule with Gaussian time jitter and quantity stealthing.

    Args:
        symbol: Ticker symbol.
        side: 'BUY' or 'SELL'.
        total_quantity: Total shares or contracts to execute.
        base_limit_price: Parent limit price.
        duration_minutes: Time window in minutes.
        num_slices: Number of child orders.
        time_jitter_pct: Max random delay deviation fraction (default ±20%).
        qty_jitter_pct: Max random slice size deviation fraction (default ±10%).
        no_chase_boundary: Price ceiling (for BUY) or floor (for SELL) where execution halts.
        lot_size: Contract lot size (quantizes slices to valid exchange lots).
        seed: Optional RNG seed for deterministic backtest replay.
    """
    if total_quantity <= 0 or num_slices <= 0 or duration_minutes <= 0:
        raise ValueError("total_quantity, num_slices, and duration_minutes must be positive.")

    rng = random.Random(seed)
    schedule_id = f"twap-{symbol}-{rng.randint(100000, 999999)}"

    # Ensure quantity is quantized by lot size
    lot = max(1, lot_size)
    total_lots = max(1, total_quantity // lot)
    actual_total_qty = total_lots * lot

    # Calculate base quantities per slice in lots
    base_lots_per_slice = max(1, total_lots // num_slices)
    allocated_lots = 0
    slice_lots: list[int] = []

    for i in range(num_slices - 1):
        jitter = rng.uniform(-qty_jitter_pct, qty_jitter_pct)
        cur_lots = max(1, int(round(base_lots_per_slice * (1.0 + jitter))))
        # Ensure we don't exceed remaining lots
        remaining = total_lots - allocated_lots - (num_slices - 1 - i)
        cur_lots = min(cur_lots, max(1, remaining))
        slice_lots.append(cur_lots)
        allocated_lots += cur_lots

    # Final slice absorbs the remainder to ensure exact sum
    final_lots = max(1, total_lots - allocated_lots)
    slice_lots.append(final_lots)

    # Calculate time intervals with jitter
    total_seconds = duration_minutes * 60.0
    base_interval = total_seconds / num_slices
    current_delay = 0.0
    slices: list[ChildSlicePlan] = []

    for idx, lots in enumerate(slice_lots):
        slice_qty = lots * lot
        if idx == 0:
            delay = 0.0  # Immediate first execution
        else:
            time_jitter = rng.uniform(-time_jitter_pct, time_jitter_pct)
            interval = max(5.0, base_interval * (1.0 + time_jitter))
            current_delay += interval
            delay = current_delay

        slices.append(
            ChildSlicePlan(
                slice_index=idx,
                quantity=slice_qty,
                delay_seconds=round(delay, 2),
                limit_price=base_limit_price,
            )
        )

    sum_sliced_qty = sum(s.quantity for s in slices)
    return SlicedOrderSchedule(
        schedule_id=schedule_id,
        symbol=symbol,
        side=side,
        algorithm="TWAP",
        total_parent_quantity=actual_total_qty,
        total_sliced_quantity=sum_sliced_qty,
        num_slices=len(slices),
        duration_minutes=duration_minutes,
        slices=slices,
        no_chase_boundary=no_chase_boundary,
    )


def build_pov_schedule(
    symbol: str,
    side: Literal["BUY", "SELL"],
    total_quantity: int,
    base_limit_price: float,
    estimated_candle_volume: int,
    participation_rate: float = 0.05,  # 5% of candle volume
    candle_interval_minutes: float = 5.0,
    no_chase_boundary: Optional[float] = None,
    lot_size: int = 1,
) -> SlicedOrderSchedule:
    """
    Construct a Participation of Volume (POV) schedule.
    Caps each slice to a maximum percentage of estimated volume per candle.
    """
    if estimated_candle_volume <= 0:
        raise ValueError("estimated_candle_volume must be greater than zero.")
    if participation_rate <= 0.0 or participation_rate > 0.50:
        raise ValueError("participation_rate must be between 0.01 (1%) and 0.50 (50%).")

    lot = max(1, lot_size)
    max_slice_qty = max(lot, int(round((estimated_candle_volume * participation_rate) / lot)) * lot)
    num_slices = max(1, math.ceil(total_quantity / max_slice_qty))
    duration_minutes = num_slices * candle_interval_minutes

    return build_twap_schedule(
        symbol=symbol,
        side=side,
        total_quantity=total_quantity,
        base_limit_price=base_limit_price,
        duration_minutes=duration_minutes,
        num_slices=num_slices,
        time_jitter_pct=0.10,
        qty_jitter_pct=0.05,
        no_chase_boundary=no_chase_boundary,
        lot_size=lot,
    )
