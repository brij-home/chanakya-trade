"""
tests/test_broker_order_type_translation.py
───────────────────────────────────────────
Regression tests for BRK-01, BRK-06, BRK-14:
  - Protective stop loss orders (SL_LIMIT, SL_MARKET) must produce native stop codes and never default to MARKET/LIMIT.
  - Unknown order types must fail closed (raise ValueError).
  - Status normalization must correctly handle numeric and textual codes (Fyers, mStock PLACED).
"""

import pytest
from brokers.order_types import (
    normalize_order_type,
    normalize_order_status,
)
from brokers.angelone import _map_order_type as angel_map_order_type
from brokers.fyers import FyersAPI


def test_canonical_order_type_normalization():
    """Verify standard aliases normalize to canonical order types."""
    assert normalize_order_type("MARKET") == "MARKET"
    assert normalize_order_type("MKT") == "MARKET"
    assert normalize_order_type("LIMIT") == "LIMIT"
    assert normalize_order_type("LMT") == "LIMIT"
    assert normalize_order_type("SL") == "SL_LIMIT"
    assert normalize_order_type("SL_LIMIT") == "SL_LIMIT"
    assert normalize_order_type("SL-L") == "SL_LIMIT"
    assert normalize_order_type("STOPLOSS_LIMIT") == "SL_LIMIT"
    assert normalize_order_type("SL_MARKET") == "SL_MARKET"
    assert normalize_order_type("SL-M") == "SL_MARKET"
    assert normalize_order_type("STOPLOSS_MARKET") == "SL_MARKET"

    with pytest.raises(ValueError, match="Unknown or unsupported order type"):
        normalize_order_type("UNKNOWN_TYPE_XYZ")


def test_angelone_order_type_mapping():
    """Angel One adapter must map SL_LIMIT to STOPLOSS_LIMIT and SL_MARKET to STOPLOSS_MARKET, never MARKET."""
    assert angel_map_order_type("MARKET") == "MARKET"
    assert angel_map_order_type("LIMIT") == "LIMIT"
    assert angel_map_order_type("SL_LIMIT") == "STOPLOSS_LIMIT"
    assert angel_map_order_type("SL_MARKET") == "STOPLOSS_MARKET"
    assert angel_map_order_type("SL") == "STOPLOSS_LIMIT"
    assert angel_map_order_type("SL-M") == "STOPLOSS_MARKET"

    with pytest.raises(ValueError):
        angel_map_order_type("INVALID_TYPE")


def test_fyers_order_type_mapping():
    """Fyers adapter must map order types to API v3 codes (1: LIMIT, 2: MARKET, 3: SL-M, 4: SL-L)."""
    assert FyersAPI._to_fyers_order_type("LIMIT") == 1
    assert FyersAPI._to_fyers_order_type("MARKET") == 2
    assert FyersAPI._to_fyers_order_type("SL_MARKET") == 3
    assert FyersAPI._to_fyers_order_type("SL_LIMIT") == 4
    assert FyersAPI._to_fyers_order_type("SL") == 4
    assert FyersAPI._to_fyers_order_type("SL-M") == 3

    with pytest.raises(ValueError):
        FyersAPI._to_fyers_order_type("INVALID_TYPE")


def test_status_normalization():
    """Status normalizer must handle Fyers numeric statuses and textual codes accurately."""
    # Fyers numeric codes
    assert normalize_order_status(2) == "COMPLETE"
    assert normalize_order_status(6) == "OPEN"
    assert normalize_order_status(1) == "CANCELLED"
    assert normalize_order_status(5) == "REJECTED"
    assert normalize_order_status(7) == "EXPIRED"

    # Textual broker statuses
    assert normalize_order_status("PLACED") == "SUBMITTED"
    assert normalize_order_status("SUBMITTED") == "SUBMITTED"
    assert normalize_order_status("COMPLETE") == "COMPLETE"
    assert normalize_order_status("FILLED") == "COMPLETE"
    assert normalize_order_status("PARTIALLY_FILLED") == "PARTIALLY_FILLED"
    assert normalize_order_status("CANCELLED") == "CANCELLED"
    assert normalize_order_status("REJECTED") == "REJECTED"

    # Unknown must fail closed to UNKNOWN, never OPEN
    assert normalize_order_status("RANDOM_UNRECOGNIZED_STATUS") == "UNKNOWN"
    assert normalize_order_status(None) == "UNKNOWN"
