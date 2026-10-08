"""
engine/data_sanctity.py
───────────────────────
Institutional Production Data Firewall & Sanctity Guard for ChanakyaTrade.

Enforces zero-tolerance invariants:
1. No test, mock, dummy, or synthetic records are ever permitted in production databases,
   SQLite tables, JSON ledgers, or runtime caches.
2. In non-test environments, any payload tagged with environment='TEST' or bearing test/mock
   identifiers is fail-closed blocked at the persistence boundary.
3. Tests and unit-test harnesses must be explicitly flagged with CHANAKYA_TESTING=1 or
   PYTEST_CURRENT_TEST to bypass the firewall into sandboxed directories.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Tuple

logger = logging.getLogger("engine.data_sanctity")

FORBIDDEN_SYMBOL_PREFIXES = ("TEST", "MOCK", "DUMMY", "SAMPLE", "FAKE")
FORBIDDEN_ID_PREFIXES = ("test-", "mock-", "dummy-", "vm-", "aa-degenerate")


def is_test_environment() -> bool:
    """Return True if execution is running under an isolated test harness."""
    return bool(
        os.environ.get("CHANAKYA_TESTING") == "1"
        or "PYTEST_CURRENT_TEST" in os.environ
        or os.environ.get("DEPLOY_MODE") == "test"
    )


def is_test_or_mock_payload(item: Any) -> Tuple[bool, str]:
    """
    Inspect a data record (dict, dataclass, or model instance) for test/mock provenance.
    Returns (is_test, reason).
    """
    if item is None:
        return False, ""

    # Convert dataclass/model to dict if needed
    if hasattr(item, "to_dict") and callable(item.to_dict):
        d = item.to_dict()
    elif hasattr(item, "__dict__"):
        d = item.__dict__
    elif isinstance(item, dict):
        d = item
    else:
        return False, ""

    env = str(d.get("environment", "")).upper()
    if env in ("TEST", "MOCK", "SYNTHETIC"):
        return True, f"Explicit test environment tag: environment='{env}'"

    if d.get("is_mock") is True:
        return True, "is_mock flag set to True"

    # Check symbol
    raw_sym = str(d.get("symbol") or d.get("canonical_symbol") or "").upper().strip()
    # Strip common exchange prefixes for checking
    clean_sym = raw_sym
    for pfx in ("NSE:", "BSE:", "MCX:", "NFO:", "BFO:", "CDS:", "CRYPTO:"):
        if clean_sym.startswith(pfx):
            clean_sym = clean_sym[len(pfx) :]
            break

    for pfx in FORBIDDEN_SYMBOL_PREFIXES:
        if clean_sym.startswith(pfx) or clean_sym == pfx:
            return True, f"Forbidden test symbol prefix: '{clean_sym}'"

    # Check alert ID / record ID
    alert_id = str(d.get("alert_id") or d.get("id") or "").lower().strip()
    for pfx in FORBIDDEN_ID_PREFIXES:
        if alert_id.startswith(pfx):
            return True, f"Forbidden test ID prefix: '{alert_id}'"

    return False, ""


def assert_production_data_sanctity(item: Any, source_module: str = "") -> bool:
    """
    Validate that an item is permissible for persistence in production stores.
    Returns True if allowed. Returns False if blocked.
    """
    if is_test_environment():
        return True  # Tests write to their own sandboxed directories

    is_test, reason = is_test_or_mock_payload(item)
    if is_test:
        logger.critical(
            f"[DATA_SANCTITY_FIREWALL] Blocked test/mock data from persisting to production "
            f"(Source: {source_module or 'Unknown'}): {reason}"
        )
        return False

    return True
