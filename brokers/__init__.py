"""
brokers
───────
Unified broker abstractions and adapters for ChanakyaTrade.
"""

from brokers.base import (
    BrokerAPI,
    Funds,
    Holding,
    OptionsContract,
    Order,
    OrderRequest,
    OrderResponse,
    Position,
    Quote,
    UserProfile,
)
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

__all__ = [
    "BrokerAPI",
    "UserProfile",
    "Funds",
    "Holding",
    "Position",
    "Quote",
    "OptionsContract",
    "OrderRequest",
    "OrderResponse",
    "Order",
    "BrokerError",
    "BrokerAuthError",
    "BrokerNetworkError",
    "BrokerRateLimitError",
    "BrokerMarginError",
    "BrokerOrderRejectedError",
    "BrokerOrderNotFoundError",
    "BrokerDataUnavailableError",
    "BrokerFreezeError",
]
