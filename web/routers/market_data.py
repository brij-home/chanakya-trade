"""
web/routers/market_data.py
──────────────────────────
Dedicated router for Market Intelligence, Depth, Order Book Imbalance,
Regime Gate, Precursors, Asymmetric Opportunities, and Ticker Feeds.
All synchronous network and quant calculations are offloaded via asyncio.to_thread.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

logger = logging.getLogger("chanakya.web.routers.market_data")
router = APIRouter(tags=["Market Intelligence", "Market Data"])


@router.get("/api/market/participant-oi")
async def get_participant_oi_endpoint():
    """Returns the latest official NSE Participant-wise Open Interest metrics."""
    from market.participant_oi import get_latest_participant_oi

    data = await asyncio.to_thread(get_latest_participant_oi)
    return {"status": "ok", "data": data.to_dict()}


@router.get("/api/market/order-book/{symbol}")
async def get_order_book_endpoint(symbol: str):
    """Returns real-time Order Book Imbalance (OBI) and depth analytics."""
    from market.order_book import analyze_symbol_order_book

    snapshot = await asyncio.to_thread(analyze_symbol_order_book, symbol)
    return {"status": "ok", "data": snapshot.to_dict()}


@router.get("/api/market/whale-deals")
async def get_whale_deals_endpoint(min_deal_cr: float = 0.0, investor: Optional[str] = None):
    """Returns marquee superstar investor and institutional bulk/block deals."""
    from analysis.whale_tracker import get_whale_flows

    flows = await asyncio.to_thread(get_whale_flows, investor_filter=investor, min_deal_cr=min_deal_cr)
    return {"status": "ok", "data": flows}


@router.get("/api/market/regime")
async def get_market_regime():
    """
    Institutional Market Regime Gate.
    Returns the current EDGELESS CHOP / LOW VIX state for UI banner display.
    """
    try:
        from engine.market_regime_gate import evaluate_market_regime

        snap = await asyncio.to_thread(evaluate_market_regime)
        return {
            "status": "ok",
            "is_edgeless": snap.is_edgeless,
            "prefer_spreads": snap.prefer_spreads,
            "banner": snap.banner,
            "vix": snap.vix,
            "ad_ratio": snap.ad_ratio,
            "vix_status": snap.vix_status,
            "ad_status": snap.ad_status,
            "data_quality": snap.data_quality,
            "reason": snap.reason,
            "is_locomotive_polarized": getattr(snap, "is_locomotive_polarized", False),
            "locomotive_detail": getattr(snap, "locomotive_detail", ""),
        }
    except Exception as exc:
        return {
            "status": "UNAVAILABLE",
            "is_edgeless": False,
            "prefer_spreads": False,
            "banner": "",
            "data_quality": "UNAVAILABLE",
            "reason": f"Regime gate unavailable: {exc}",
        }


@router.get("/api/market/council-sotd")
async def get_council_sotd():
    """
    Multi-Agent Council Setup of the Day (SOTD) winners.
    Returns the Top 2-3 setups selected by the 10-minute council arbitration cycle.
    """
    try:
        from engine.council_arbitrator import get_last_winners
        from engine.auto_alert_engine import auto_alert_engine

        winner_ids = await asyncio.to_thread(get_last_winners)
        all_alerts = await asyncio.to_thread(auto_alert_engine.get_alerts)
        winners = []
        for a in all_alerts:
            if getattr(a, "alert_id", "") in winner_ids:
                d = a.to_dict()
                d["_is_council_winner"] = True
                winners.append(d)

        winners.sort(key=lambda x: (x.get("actionable_plan") or {}).get("council_rank", 99))
        return {"status": "ok", "count": len(winners), "data": winners}
    except Exception as exc:
        return {"status": "UNAVAILABLE", "count": 0, "data": [], "error": str(exc)}


@router.get("/api/movers/autopsy", tags=["Movers & Autopsy"])
async def get_mover_autopsy(date: Optional[str] = None, segment: Optional[str] = None):
    """
    Get daily top gainers & losers forensic autopsy dossier.
    Includes 5-dimensional causal factor decomposition and control cohort contrast.
    """
    from engine.mover_autopsy import mover_autopsy_engine

    if date:
        autopsy = await asyncio.to_thread(mover_autopsy_engine.get_autopsy_by_date, date)
    else:
        autopsy = await asyncio.to_thread(mover_autopsy_engine.get_latest_autopsy)

    if not autopsy:
        autopsy = await asyncio.to_thread(mover_autopsy_engine.run_daily_autopsy, segment=segment)

    if autopsy and segment and segment.upper() not in ("ALL", ""):
        seg_upper = segment.upper().replace("CASH", "NON_FNO")
        autopsy_dict = autopsy.to_dict()
        autopsy_dict["gainers"] = [
            g
            for g in autopsy_dict.get("gainers", [])
            if g.get("segment") == seg_upper or (seg_upper == "FNO" and g.get("is_fo"))
        ]
        autopsy_dict["losers"] = [
            l
            for l in autopsy_dict.get("losers", [])
            if l.get("segment") == seg_upper or (seg_upper == "FNO" and l.get("is_fo"))
        ]
        return {"status": "ok", "data": autopsy_dict}

    return {"status": "ok", "data": autopsy.to_dict() if autopsy else None}


@router.post("/api/movers/autopsy/run", tags=["Movers & Autopsy"])
async def run_mover_autopsy(payload: Optional[dict] = None):
    """Trigger an on-demand forensic autopsy across top movers and control cohort."""
    from engine.mover_autopsy import mover_autopsy_engine

    top_n = payload.get("top_n", 10) if payload else 10
    target_date = payload.get("date") if payload else None
    segment = payload.get("segment") if payload else None

    autopsy = await asyncio.to_thread(
        mover_autopsy_engine.run_daily_autopsy,
        target_date=target_date,
        segment=segment,
        top_n=top_n,
    )

    try:
        from web.sse import event_bus

        event_bus.publish_sync(
            "system",
            {
                "type": "mover_autopsy_completed",
                "date": autopsy.date,
                "segment": segment or "ALL",
                "market_regime": autopsy.market_regime,
                "gainers_count": len(autopsy.gainers),
                "losers_count": len(autopsy.losers),
                "traps_filtered": autopsy.traps_filtered,
            },
        )
    except Exception:
        pass

    return {"status": "ok", "data": autopsy.to_dict()}


@router.get("/api/movers/precursors", tags=["Movers & Autopsy"])
async def get_mover_precursors(limit: int = 5, segment: Optional[str] = None):
    """Scan liquid universe and return high-conviction pre-ignition candidates."""
    from engine.precursor_radar import precursor_radar

    candidates = await asyncio.to_thread(
        precursor_radar.scan_precursors, segment=segment, top_n=limit
    )
    return {"status": "ok", "data": [c.to_dict() for c in candidates]}


@router.get("/api/opportunities/asymmetric", tags=["Asymmetric Opportunities"])
async def get_asymmetric_opportunities(
    limit: int = 8,
    segment: Optional[str] = None,
    setup_type: Optional[str] = None,
):
    """Returns active high-asymmetry (low risk : high reward) trade setups."""
    from engine.asymmetric_radar import asymmetric_radar

    opps = await asyncio.to_thread(
        asymmetric_radar.scan_asymmetric_opportunities,
        segment=segment,
        top_n=limit,
    )
    if setup_type and setup_type.upper() not in ("ALL", ""):
        st_upper = setup_type.upper()
        opps = [o for o in opps if o.setup_type == st_upper]

    return {"status": "ok", "data": [o.to_dict() for o in opps]}


@router.post("/api/opportunities/asymmetric/scan", tags=["Asymmetric Opportunities"])
async def run_asymmetric_opportunities_scan(payload: Optional[dict] = None):
    """Trigger on-demand sweep across market universes for low-risk, high-reward setups."""
    from engine.asymmetric_radar import asymmetric_radar

    top_n = payload.get("top_n", 8) if payload else 8
    segment = payload.get("segment") if payload else None
    setup_type = payload.get("setup_type") if payload else None

    opps = await asyncio.to_thread(
        asymmetric_radar.scan_asymmetric_opportunities,
        segment=segment,
        top_n=top_n,
    )
    if setup_type and setup_type.upper() not in ("ALL", ""):
        st_upper = setup_type.upper()
        opps = [o for o in opps if o.setup_type == st_upper]

    try:
        from web.sse import event_bus

        event_bus.publish_sync(
            "system",
            {
                "type": "asymmetric_scan_completed",
                "segment": segment or "ALL",
                "count": len(opps),
                "top_opportunity": opps[0].symbol if opps else None,
            },
        )
    except Exception:
        pass

    return {"status": "ok", "data": [o.to_dict() for o in opps]}


@router.post("/api/quotes/batch", tags=["Market Data"])
async def api_quotes_batch(req: dict):
    """Sidecar batch quote query endpoint."""
    from web.skills import BatchQuotesRequest, skill_quotes_batch

    symbols = req.get("symbols", []) if isinstance(req, dict) else []
    exchange = req.get("exchange", "NSE") if isinstance(req, dict) else "NSE"
    return await skill_quotes_batch(BatchQuotesRequest(symbols=symbols, exchange=exchange))


@router.get("/api/ticker/snapshot", tags=["Market Data"])
async def get_ticker_snapshot():
    """Get current snapshot of major Indian and Global indices."""
    from market.ticker_stream import ticker_stream, compute_ribbon_tickers

    snap = ticker_stream.get_snapshot()
    if not snap.get("tickers"):
        tickers = await asyncio.to_thread(compute_ribbon_tickers)
        ticker_stream._cached_ribbon_tickers = tickers
        snap["tickers"] = tickers
    return snap
