"""
brokers/exceptions.py
─────────────────────
Canonical Broker Exception Hierarchy for ChanakyaTrade.

Enforces institutional error handling across all brokers (Zerodha, Fyers,
Angel One, Shoonya, mStock, Stoxkart, Upstox, Groww, Mock):
- Zero unhandled proprietary broker SDK exceptions leaking into engine layers.
- Strict mapping into typed domains: Auth, Margin, Rate Limit, Network, Rejection, Order State.
- Every exception preserves root cause, broker name, and optional error code.
"""

from __future__ import annotations

from typing import Any, Optional


class BrokerError(Exception):
    """Root base class for all broker-related errors."""

    def __init__(
        self,
        message: str,
        broker: str = "UNKNOWN",
        error_code: Optional[str] = None,
        raw_response: Optional[Any] = None,
    ):
        super().__init__(message)
        self.message = message
        self.broker = broker
        self.error_code = error_code
        self.raw_response = raw_response

    def __str__(self) -> str:
        code_str = f" [{self.error_code}]" if self.error_code else ""
        return f"[{self.broker}]{code_str} {self.message}"


class BrokerAuthError(BrokerError, RuntimeError):
    """Raised when authentication fails, session token expires, or TOTP is invalid."""

    pass


class BrokerNetworkError(BrokerError):
    """Raised when broker API connection times out or fails at transport layer."""

    pass


class BrokerRateLimitError(BrokerError):
    """Raised when broker returns HTTP 429 or hits request throttling limits."""

    def __init__(
        self,
        message: str,
        broker: str = "UNKNOWN",
        retry_after_seconds: Optional[float] = None,
        error_code: Optional[str] = None,
        raw_response: Optional[Any] = None,
    ):
        super().__init__(message, broker, error_code, raw_response)
        self.retry_after_seconds = retry_after_seconds


class BrokerMarginError(BrokerError):
    """Raised when account balance is insufficient or margin requirements fail."""

    pass


class BrokerOrderRejectedError(BrokerError):
    """Raised when broker rejects order placement or modification (RMS, circuit limits, invalid strike)."""

    pass


class BrokerOrderNotFoundError(BrokerError):
    """Raised when querying or cancelling an order ID that does not exist at broker."""

    pass


class BrokerDataUnavailableError(BrokerError):
    """Raised when live quotes, options chain, or depth cannot be fetched."""

    pass


class BrokerFreezeError(BrokerError):
    """Raised when broker order enters an ambiguous, timeout, or frozen state."""

    pass
