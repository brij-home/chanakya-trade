"""
brokers/order_types.py
──────────────────────
Canonical order types, product types, and order status normalization
for all Indian broker adapters (NSE, BSE, MCX).
"""

from __future__ import annotations
from typing import Any, Literal

CanonicalOrderType = Literal["MARKET", "LIMIT", "SL_LIMIT", "SL_MARKET"]
CanonicalProductType = Literal["CNC", "MIS", "NRML"]
CanonicalSide = Literal["BUY", "SELL"]
CanonicalOrderStatus = Literal[
    "OPEN",
    "SUBMITTED",
    "COMPLETE",
    "PARTIALLY_FILLED",
    "CANCELLED",
    "REJECTED",
    "EXPIRED",
    "UNKNOWN",
]

CANONICAL_ORDER_TYPES: set[str] = {"MARKET", "LIMIT", "SL_LIMIT", "SL_MARKET"}
CANONICAL_PRODUCTS: set[str] = {"CNC", "MIS", "NRML"}
CANONICAL_SIDES: set[str] = {"BUY", "SELL"}


def normalize_order_type(order_type: str) -> str:
    """Normalize user/OMS order type to canonical form; raise ValueError on unknown."""
    raw = str(order_type or "").strip().upper()
    _MAP = {
        "MARKET": "MARKET",
        "MKT": "MARKET",
        "LIMIT": "LIMIT",
        "LMT": "LIMIT",
        "SL": "SL_LIMIT",
        "SL_LIMIT": "SL_LIMIT",
        "SL-L": "SL_LIMIT",
        "SL-LMT": "SL_LIMIT",
        "STOP_LIMIT": "SL_LIMIT",
        "STOPLOSS_LIMIT": "SL_LIMIT",
        "SL_MARKET": "SL_MARKET",
        "SL-M": "SL_MARKET",
        "SL-MKT": "SL_MARKET",
        "STOP": "SL_MARKET",
        "STOP_MARKET": "SL_MARKET",
        "STOPLOSS_MARKET": "SL_MARKET",
    }
    if raw in _MAP:
        return _MAP[raw]
    raise ValueError(
        f"Unknown or unsupported order type '{order_type}'. Allowed: {CANONICAL_ORDER_TYPES}"
    )


def normalize_order_status(status: Any) -> CanonicalOrderStatus:
    """Normalize raw broker order status string or numeric code to canonical status."""
    if status is None:
        return "UNKNOWN"

    # Numeric codes (e.g. Fyers status codes)
    if isinstance(status, int) or (isinstance(status, str) and status.isdigit()):
        code = int(status)
        _NUMERIC_FYERS: dict[int, CanonicalOrderStatus] = {
            1: "CANCELLED",
            2: "COMPLETE",
            4: "SUBMITTED",
            5: "REJECTED",
            6: "OPEN",
            7: "EXPIRED",
        }
        return _NUMERIC_FYERS.get(code, "UNKNOWN")

    raw = str(status).strip().upper()
    _MAP: dict[str, CanonicalOrderStatus] = {
        "OPEN": "OPEN",
        "PENDING": "OPEN",
        "TRIGGER_PENDING": "OPEN",
        "TRIGGER PENDING": "OPEN",
        "PLACED": "SUBMITTED",
        "SUBMITTED": "SUBMITTED",
        "TRANSIT": "SUBMITTED",
        "COMPLETE": "COMPLETE",
        "COMPLETED": "COMPLETE",
        "FILLED": "COMPLETE",
        "TRADED": "COMPLETE",
        "PARTIALLY_FILLED": "PARTIALLY_FILLED",
        "PARTIAL": "PARTIALLY_FILLED",
        "PARTIALLY FILLED": "PARTIALLY_FILLED",
        "CANCELLED": "CANCELLED",
        "CANCELED": "CANCELLED",
        "REJECTED": "REJECTED",
        "EXPIRED": "EXPIRED",
    }
    return _MAP.get(raw, "UNKNOWN")


def normalize_product(product: str) -> str:
    raw = str(product or "").strip().upper()
    _MAP = {
        "CNC": "CNC",
        "DELIVERY": "CNC",
        "MIS": "MIS",
        "INTRADAY": "MIS",
        "NRML": "NRML",
        "MARGIN": "NRML",
        "CARRYFORWARD": "NRML",
    }
    if raw in _MAP:
        return _MAP[raw]
    raise ValueError(f"Unknown product type '{product}'. Allowed: CNC, MIS, NRML")


def normalize_side(side: str) -> str:
    raw = str(side or "").strip().upper()
    if raw in ("BUY", "B", "1"):
        return "BUY"
    if raw in ("SELL", "S", "-1"):
        return "SELL"
    raise ValueError(f"Unknown transaction side '{side}'. Allowed: BUY, SELL")
