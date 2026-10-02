"""
web/routers/common.py
─────────────────────
Shared utilities and guards for FastAPI routers.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from fastapi import HTTPException, Request

logger = logging.getLogger("chanakya.web.routers.common")


def require_localhost(request: Request) -> None:
    """Raise 403 if the request does not originate from localhost / loopback."""
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise HTTPException(
            status_code=403,
            detail="This endpoint is only accessible from localhost.",
        )
