"""Explicit safety profile for a small personal/pilot trading rollout."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class PilotSafetyProfile:
    profile: str
    live_execution_enabled: bool
    allowed_segments: tuple[str, ...]
    allowed_products: tuple[str, ...]
    max_order_notional: float
    require_manual_confirmation: bool
    automatic_broker_failover: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_pilot_safety_profile() -> PilotSafetyProfile:
    """Read conservative, local-only pilot controls from environment variables."""
    allowed_segments = tuple(
        part.strip().upper()
        for part in os.environ.get("PILOT_ALLOWED_SEGMENTS", "EQUITY_DELIVERY").split(",")
        if part.strip()
    )
    allowed_products = tuple(
        part.strip().upper()
        for part in os.environ.get("PILOT_ALLOWED_PRODUCTS", "CNC").split(",")
        if part.strip()
    )
    try:
        max_order_notional = max(0.0, float(os.environ.get("PILOT_MAX_ORDER_NOTIONAL", "5000")))
    except ValueError:
        max_order_notional = 5000.0
    return PilotSafetyProfile(
        profile=os.environ.get("PILOT_PROFILE", "OBSERVE").strip().upper() or "OBSERVE",
        live_execution_enabled=os.environ.get("PILOT_ALLOW_LIVE_EXECUTION", "0") == "1",
        allowed_segments=allowed_segments,
        allowed_products=allowed_products,
        max_order_notional=max_order_notional,
        require_manual_confirmation=True,
        automatic_broker_failover=False,
    )


def assert_pilot_execution_allowed(*, segment: str, product: str, notional: float) -> None:
    """Fail closed unless the account owner deliberately enables pilot execution."""
    profile = get_pilot_safety_profile()
    if not profile.live_execution_enabled:
        raise PermissionError(
            "Pilot live execution is disabled. Set PILOT_ALLOW_LIVE_EXECUTION=1 only after paper validation."
        )
    if segment.upper() not in profile.allowed_segments:
        raise PermissionError(
            f"Pilot safety profile permits {profile.allowed_segments}, not {segment.upper()}."
        )
    if product.upper() not in profile.allowed_products:
        raise PermissionError(
            f"Pilot safety profile permits products {profile.allowed_products}, not {product.upper()}."
        )
    if notional > profile.max_order_notional:
        raise PermissionError(
            f"Order notional ₹{notional:,.2f} exceeds pilot limit ₹{profile.max_order_notional:,.2f}."
        )
