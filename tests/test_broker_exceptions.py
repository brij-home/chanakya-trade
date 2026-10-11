"""
tests/test_broker_exceptions.py
───────────────────────────────
Unit tests for the canonical broker exception hierarchy in brokers/exceptions.py.
"""

from __future__ import annotations


from brokers.exceptions import (
    BrokerAuthError,
    BrokerDataUnavailableError,
    BrokerError,
    BrokerFreezeError,
    BrokerMarginError,
    BrokerNetworkError,
    BrokerOrderNotFoundError,
    BrokerOrderRejectedError,
    BrokerRateLimitError,
)


def test_broker_error_hierarchy():
    """Verify all broker exceptions inherit from BrokerError."""
    assert issubclass(BrokerAuthError, BrokerError)
    assert issubclass(BrokerNetworkError, BrokerError)
    assert issubclass(BrokerRateLimitError, BrokerError)
    assert issubclass(BrokerMarginError, BrokerError)
    assert issubclass(BrokerOrderRejectedError, BrokerError)
    assert issubclass(BrokerOrderNotFoundError, BrokerError)
    assert issubclass(BrokerDataUnavailableError, BrokerError)
    assert issubclass(BrokerFreezeError, BrokerError)


def test_broker_auth_error_backward_compatibility():
    """Verify BrokerAuthError also subclasses RuntimeError for backwards compatibility."""
    assert issubclass(BrokerAuthError, RuntimeError)
    err = BrokerAuthError("Session expired", broker="ZERODHA", error_code="TOKEN_EXPIRED")
    assert isinstance(err, RuntimeError)
    assert isinstance(err, BrokerError)
    assert str(err) == "[ZERODHA] [TOKEN_EXPIRED] Session expired"


def test_broker_rate_limit_retry_after():
    """Verify BrokerRateLimitError captures retry_after_seconds."""
    err = BrokerRateLimitError(
        "Too many requests",
        broker="FYERS",
        retry_after_seconds=30.0,
        error_code="RATE_LIMIT_429",
    )
    assert err.retry_after_seconds == 30.0
    assert err.error_code == "RATE_LIMIT_429"
    assert "[FYERS]" in str(err)


def test_broker_margin_error():
    """Verify BrokerMarginError representation."""
    err = BrokerMarginError(
        "Insufficient funds for MIS order", broker="MSTOCK", error_code="RMS_MARGIN"
    )
    assert err.broker == "MSTOCK"
    assert err.error_code == "RMS_MARGIN"
    assert "Insufficient funds" in str(err)


def test_unified_imports_from_brokers_package():
    """Verify canonical exceptions are cleanly exported from the top-level brokers package."""
    import brokers

    assert hasattr(brokers, "BrokerError")
    assert hasattr(brokers, "BrokerAuthError")
    assert hasattr(brokers, "BrokerMarginError")
    assert hasattr(brokers, "BrokerNetworkError")
    assert hasattr(brokers, "BrokerRateLimitError")
