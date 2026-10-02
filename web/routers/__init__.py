"""
web/routers/__init__.py
───────────────────────
Package export for modular FastAPI route handlers in ChanakyaTrade.
"""

from __future__ import annotations

from web.routers.alerts_api import router as alerts_router
from web.routers.market_data import router as market_router

__all__ = [
    "alerts_router",
    "market_router",
]
