"""
web/routers/common.py
─────────────────────
Shared utilities and guards for FastAPI routers.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException, Request

logger = logging.getLogger("chanakya.web.routers.common")

VALID_EXCHANGES = frozenset({"NSE", "BSE", "NFO", "BFO", "MCX", "CDS"})


def skill_ok(data) -> dict:
    """Wrap payload in canonical ChanakyaTrade skill envelope."""
    from agent.tools import _serialise

    return {"status": "ok", "data": _serialise(data)}


def skill_err(msg: str, code: int = 500) -> HTTPException:
    """Build standard JSON error HTTPException for skill routes."""
    return HTTPException(status_code=code, detail={"status": "error", "message": msg})


def normalize_symbol_and_exchange(symbol: str, exchange: Optional[str] = "NSE") -> tuple[str, str]:
    """Normalize symbol and resolve canonical NSE/BSE/MCX/CDS exchange."""
    from market.instruments import canonical_symbol
    from market.quotes import _BSE_SYMBOLS, _CDS_SYMBOLS, _MCX_SYMBOLS

    raw_s = str(symbol or "").strip().upper()
    exch = (exchange or "NSE").upper().strip()
    if ":" in raw_s:
        parts = raw_s.split(":", 1)
        exch_candidate = parts[0].strip().upper()
        if exch_candidate in VALID_EXCHANGES:
            exch = exch_candidate
    if exch not in VALID_EXCHANGES:
        exch = "NSE"
    sym = canonical_symbol(raw_s)
    if exch == "NSE":
        if sym in _MCX_SYMBOLS:
            exch = "MCX"
        elif sym in _CDS_SYMBOLS:
            exch = "CDS"
        elif sym in _BSE_SYMBOLS:
            exch = "BSE"
    return sym, exch


def require_localhost(request: Request) -> None:
    """Raise 403 if the request does not originate from localhost / loopback."""
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise HTTPException(
            status_code=403,
            detail="This endpoint is only accessible from localhost.",
        )
