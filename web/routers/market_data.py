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

import os
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
import json
from market.instruments import canonical_symbol

logger = logging.getLogger("chanakya.web.routers.market_data")
router = APIRouter(tags=["Market Intelligence", "Market Data"])


def _reject_unmanaged_broker_mutation(operation: str) -> None:
    """Keep legacy broker-specific mutations outside the order authority disabled."""
    raise HTTPException(
        status_code=409,
        detail=(
            f"{operation} is disabled because this broker-specific route bypasses the "
            "previewed order lifecycle and its durable reconciliation ledger. Use the "
            "central OMS for supported orders; manage existing broker-side triggers "
            "in the broker app and reconcile their status."
        ),
    )


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

    # Auto-sample user inspected symbol into TBT Scout pool for zero-REST streaming depth (daytime NSE only)
    try:
        from market.fyers_tbt_manager import fyers_tbt_manager, is_tbt_eligible_symbol
        from market.calendar import is_market_open

        if (is_tbt_eligible_symbol(symbol) or "-EQ" in symbol) and is_market_open("NSE"):
            fyers_tbt_manager.sample_symbol(symbol, duration_sec=120.0)
    except Exception as e_tbt:
        logger.debug(
            f"[web.routers.market_data] Order book TBT sample notice for {symbol}: {e_tbt}"
        )

    snapshot = await asyncio.to_thread(analyze_symbol_order_book, symbol, allow_rest_fallback=True)
    return {"status": "ok", "data": snapshot.to_dict()}


@router.get("/api/market/order-book/{symbol}/stream")
async def stream_order_book_endpoint(symbol: str):
    """
    Sub-100ms real-time SSE stream of L2/L3 order book depth, OBI, resting walls, and Greeks.
    Yields initial snapshot immediately upon connect, then streams reactive updates.
    """
    from market.order_book import analyze_symbol_order_book

    # Auto-subscribe / sample to TBT 50-depth (NSE only) and WebSocket L2 on client connect
    try:
        from market.fyers_tbt_manager import fyers_tbt_manager
        from market.calendar import is_market_open

        if symbol.startswith("NSE:") and is_market_open("NSE"):
            fyers_tbt_manager.sample_symbol(symbol, duration_sec=300.0)
    except Exception as e_tbt:
        logger.debug(f"[web.routers.market_data] TBT auto-sample notice for {symbol}: {e_tbt}")

    try:
        from market.websocket import ws_manager

        ws_manager.subscribe([symbol])
    except Exception as e_ws:
        logger.debug(f"[web.routers.market_data] WS L2 auto-sub notice for {symbol}: {e_ws}")

    async def _book_generator():
        last_hash = None
        # Push initial snapshot immediately
        poll_interval = 0.5
        try:
            initial_snap = await asyncio.to_thread(
                analyze_symbol_order_book, symbol, allow_rest_fallback=True
            )
            snap_dict = initial_snap.to_dict()
            last_hash = (
                snap_dict.get("ltp"),
                snap_dict.get("spread"),
                snap_dict.get("obi_5"),
                snap_dict.get("has_resting_wall"),
                len(snap_dict.get("bids", [])),
            )
            prov = snap_dict.get("provenance", "")
            if prov not in ("LIVE_STREAM_TBT_50", "LIVE_STREAM_L2"):
                poll_interval = 2.5
            yield f"data: {json.dumps({'status': 'ok', 'data': snap_dict})}\n\n"
        except Exception as e:
            logger.warning(
                f"[web.routers.market_data] Initial depth stream error for {symbol}: {e}"
            )

        is_mcx_live = False
        try:
            from market.calendar import is_market_open

            is_mcx_live = bool(symbol.upper().startswith("MCX:") and is_market_open("MCX"))
        except Exception as e:
            logger.debug(f"[web.routers.market_data] MCX calendar check suppressed: {e}")

        # Stream reactive delta updates (WS ticks in RAM; coalesced depth refresh for active MCX)
        while True:
            try:
                await asyncio.sleep(poll_interval)
                snap = await asyncio.to_thread(
                    analyze_symbol_order_book, symbol, allow_rest_fallback=is_mcx_live
                )
                snap_dict = snap.to_dict()
                curr_hash = (
                    snap_dict.get("ltp"),
                    snap_dict.get("spread"),
                    snap_dict.get("obi_5"),
                    snap_dict.get("has_resting_wall"),
                    len(snap_dict.get("bids", [])),
                )
                if curr_hash != last_hash:
                    last_hash = curr_hash
                    yield f"data: {json.dumps({'status': 'ok', 'data': snap_dict})}\n\n"
                else:
                    yield ": heartbeat\n\n"

                prov = snap_dict.get("provenance", "")
                if prov in ("LIVE_STREAM_TBT_50", "LIVE_STREAM_L2"):
                    poll_interval = 0.5
                elif is_mcx_live:
                    poll_interval = 3.0
                else:
                    poll_interval = 2.5
            except asyncio.CancelledError:
                break
            except Exception as e_suppressed:
                logger.debug(
                    f"[web.routers.market_data] Stream heartbeat error for {symbol}: {e_suppressed}"
                )
                yield ": heartbeat\n\n"

    return StreamingResponse(
        _book_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/api/market/whale-deals")
async def get_whale_deals_endpoint(min_deal_cr: float = 0.0, investor: Optional[str] = None):
    """Returns marquee superstar investor and institutional bulk/block deals."""
    from analysis.whale_tracker import get_whale_flows

    flows = await asyncio.to_thread(
        get_whale_flows, investor_filter=investor, min_deal_cr=min_deal_cr
    )
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
        gov_dict = None
        try:
            from analysis.regime_governor import classify_market_regime

            gov = await asyncio.to_thread(classify_market_regime)
            gov_dict = {
                "regime": gov.regime,
                "name": gov.name,
                "breakout_weight": gov.breakout_weight,
                "mean_reversion_weight": gov.mean_reversion_weight,
                "position_size_multiplier": gov.position_size_multiplier,
                "min_scrutiny_score": gov.min_scrutiny_score,
                "active_detectors": gov.active_detectors,
                "summary": gov.summary,
            }
        except Exception as e_suppressed:
            logger.debug(
                f"[web.routers.market_data] Non-fatal exception suppressed: {e_suppressed}"
            )

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
            "governor": gov_dict,
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
    except Exception as e_suppressed:
        logger.debug(f"[web.routers.market_data] Non-fatal exception suppressed: {e_suppressed}")

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
    except Exception as e_suppressed:
        logger.debug(f"[web.routers.market_data] Non-fatal exception suppressed: {e_suppressed}")

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


@router.get("/api/market/depth/{symbol}", tags=["Market Data"])
async def get_market_depth_endpoint(symbol: str):
    """
    Returns real-time Level 2 Market Depth (5 bids / 5 asks), ATP (VWAP),
    circuit limits, and Order Book Imbalance (OBI).
    """
    from brokers.session import get_data_broker, get_execution_broker

    clean = symbol.strip()
    brk = None
    try:
        brk = get_data_broker()
    except Exception as e_suppressed:
        logger.debug(f"[web.routers.market_data] Non-fatal exception suppressed: {e_suppressed}")
    if not brk:
        try:
            brk = get_execution_broker()
        except Exception as e_suppressed:
            logger.debug(
                f"[web.routers.market_data] Non-fatal exception suppressed: {e_suppressed}"
            )

    if brk and hasattr(brk, "get_market_depth"):
        depth = await asyncio.to_thread(brk.get_market_depth, clean)
        if depth and depth.get("status") == "ok":
            return depth

    # Fallback to order book analytics
    from market.order_book import analyze_symbol_order_book

    snap = await asyncio.to_thread(analyze_symbol_order_book, clean)
    return {"status": "ok", "data": snap.to_dict()}


@router.get("/api/market/exchange-status", tags=["Market Data"])
async def get_exchange_market_status_endpoint():
    """
    Returns live exchange market status across Equity, F&O, Commodity, and Currency.
    """
    from brokers.session import get_data_broker

    try:
        brk = get_data_broker()
        if brk and hasattr(brk, "get_market_status"):
            res = await asyncio.to_thread(brk.get_market_status)
            return {"status": "ok", "data": res}
    except Exception as e:
        logger.debug("Failed fetching market status from broker: %s", e)

    from market.calendar import is_market_open

    return {
        "status": "ok",
        "data": {
            "NSE_EQUITY": "OPEN" if is_market_open("NSE") else "CLOSED",
            "NSE_FNO": "OPEN" if is_market_open("NFO") else "CLOSED",
            "BSE_EQUITY": "OPEN" if is_market_open("BSE") else "CLOSED",
            "MCX_COMMODITY": "OPEN" if is_market_open("MCX") else "CLOSED",
        },
    }


@router.get("/api/market/fyers/status", tags=["Broker Diagnostics"])
async def get_fyers_status_endpoint():
    """
    Returns Fyers API v3 institutional integration status:
    authentication, profile, funds, websocket connectivity, and role assignment.
    """
    from brokers.session import get_all_brokers, get_data_broker_key, get_execution_broker_key
    from market.websocket import ws_manager

    all_brokers = get_all_brokers()
    fyers = all_brokers.get("fyers")
    if not fyers:
        return {
            "connected": False,
            "error": "Fyers broker not registered or session not active",
        }

    is_auth = False
    profile = {}
    funds = {}
    try:
        is_auth = fyers.is_authenticated()
        if is_auth:
            profile = await asyncio.to_thread(fyers.get_profile)
            funds = await asyncio.to_thread(fyers.get_funds)
    except Exception as e:
        logger.debug("Fyers diagnostics error: %s", e)

    return {
        "connected": True,
        "authenticated": is_auth,
        "roles": {
            "is_data_primary": get_data_broker_key() == "fyers",
            "is_execution_primary": get_execution_broker_key() == "fyers",
        },
        "websocket": {
            "connected": bool(ws_manager.connected),
            "cached_ticks_count": len(ws_manager.get_all_ticks()),
        },
        "profile": {
            "name": getattr(profile, "name", "")
            if hasattr(profile, "name")
            else (profile.get("name", "") if isinstance(profile, dict) else ""),
            "fy_id": getattr(profile, "user_id", "")
            if hasattr(profile, "user_id")
            else (profile.get("fy_id", "") if isinstance(profile, dict) else ""),
            "email": getattr(profile, "email", "")
            if hasattr(profile, "email")
            else (profile.get("email", "") if isinstance(profile, dict) else ""),
        },
        "funds": {
            "available_cash": getattr(funds, "available_cash", 0.0)
            if hasattr(funds, "available_cash")
            else (funds.get("available_cash", 0.0) if isinstance(funds, dict) else 0.0),
            "used_margin": getattr(funds, "used_margin", 0.0)
            if hasattr(funds, "used_margin")
            else (funds.get("used_margin", 0.0) if isinstance(funds, dict) else 0.0),
            "total_balance": getattr(funds, "total_balance", 0.0)
            if hasattr(funds, "total_balance")
            else (funds.get("total_balance", 0.0) if isinstance(funds, dict) else 0.0),
        },
    }


@router.get("/api/flattrade/status", tags=["Flattrade Integration"])
async def get_flattrade_status_endpoint():
    """
    Returns Flattrade Pi Connect institutional integration status:
    authentication, profile, funds, and role assignment.
    """
    from brokers.session import get_all_brokers, get_data_broker_key, get_execution_broker_key

    all_brokers = get_all_brokers()
    flattrade = all_brokers.get("flattrade")
    if not flattrade:
        try:
            from brokers.flattrade import FlattradeAPI
            from brokers.session import register_broker

            b = FlattradeAPI()
            if b.is_authenticated():
                register_broker("flattrade", b)
                flattrade = b
        except Exception as e_reg:
            logger.debug("Flattrade lazy registration error: %s", e_reg)

    if not flattrade:
        return {
            "connected": False,
            "error": "Flattrade broker not registered or session not active",
        }

    is_auth = False
    profile = {}
    funds = {}
    try:
        is_auth = flattrade.is_authenticated()
        if is_auth:
            profile = await asyncio.to_thread(flattrade.get_profile)
            funds = await asyncio.to_thread(flattrade.get_funds)
    except Exception as e:
        logger.debug("Flattrade diagnostics error: %s", e)

    from market.streaming import market_streams

    stream_status = market_streams.status("flattrade")
    ws_sock = getattr(getattr(flattrade, "_ws", None), "sock", None)
    ws_connected = bool(ws_sock and getattr(ws_sock, "connected", False))
    subscriptions = list(getattr(flattrade, "_subscriptions", set()))

    return {
        "connected": True,
        "authenticated": is_auth,
        "roles": {
            "is_data_primary": get_data_broker_key() == "flattrade",
            "is_execution_primary": get_execution_broker_key() == "flattrade",
        },
        "websocket": {
            "connected": ws_connected,
            "state": stream_status.state,
            "subscriptions_count": len(subscriptions),
            "last_event_at": stream_status.last_event_at,
            "dropped_events": stream_status.dropped_events,
            "subscriptions": subscriptions[:50],
        },
        "profile": {
            "name": getattr(profile, "name", "")
            if hasattr(profile, "name")
            else (profile.get("name", "") if isinstance(profile, dict) else ""),
            "user_id": getattr(profile, "user_id", "")
            if hasattr(profile, "user_id")
            else (profile.get("user_id", "") if isinstance(profile, dict) else ""),
            "account_id": getattr(flattrade, "account_id", ""),
            "email": getattr(profile, "email", "")
            if hasattr(profile, "email")
            else (profile.get("email", "") if isinstance(profile, dict) else ""),
        },
        "funds": {
            "available_cash": getattr(funds, "available_cash", 0.0)
            if hasattr(funds, "available_cash")
            else (funds.get("available_cash", 0.0) if isinstance(funds, dict) else 0.0),
            "used_margin": getattr(funds, "used_margin", 0.0)
            if hasattr(funds, "used_margin")
            else (funds.get("used_margin", 0.0) if isinstance(funds, dict) else 0.0),
            "total_balance": getattr(funds, "total_balance", 0.0)
            if hasattr(funds, "total_balance")
            else (funds.get("total_balance", 0.0) if isinstance(funds, dict) else 0.0),
        },
    }


@router.get("/api/fyers/gtt", tags=["Fyers Advanced"])
async def get_fyers_gtt_orders_endpoint():
    """Retrieve active Good-Till-Triggered (GTT) orders held on Fyers servers."""
    from brokers.session import get_execution_broker

    brk = get_execution_broker()
    if brk and hasattr(brk, "get_gtt_orders"):
        orders = await asyncio.to_thread(brk.get_gtt_orders)
        return {"status": "ok", "orders": orders}
    return {"status": "error", "error": "Execution broker does not support GTT orders"}


@router.post("/api/fyers/gtt", tags=["Fyers Advanced"])
async def place_fyers_gtt_order_endpoint(req: dict):
    """Block untracked broker-side GTT creation."""
    _reject_unmanaged_broker_mutation("Direct GTT placement")


@router.delete("/api/fyers/gtt/{order_id}", tags=["Fyers Advanced"])
async def cancel_fyers_gtt_order_endpoint(order_id: str):
    """Block GTT cancellation until its protection/entry lifecycle is tracked."""
    _reject_unmanaged_broker_mutation(f"Direct GTT cancellation for {order_id}")


@router.post("/api/fyers/smart-trail", tags=["Fyers Advanced"])
async def place_fyers_smart_trail_endpoint(req: dict):
    """Block broker-specific trailing orders until the OMS tracks their lifecycle."""
    _reject_unmanaged_broker_mutation("Direct smart-trailing order placement")


@router.post("/api/fyers/exit-all", tags=["Fyers Advanced"])
@router.post("/api/fyers/panic-exit", tags=["Fyers Advanced"])
async def fyers_panic_exit_endpoint(req: Optional[dict] = None):
    """Route panic exit through the audited central emergency coordinator."""
    from engine.order_lifecycle import emergency_flatten_all_positions

    segment = req.get("segment") if req else None
    try:
        return await asyncio.to_thread(
            emergency_flatten_all_positions,
            actor="FYERS_ADVANCED_API",
            reason="USER_PANIC_EXIT",
            segment=segment,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.patch("/api/fyers/orders/{order_id}", tags=["Fyers Advanced"])
async def patch_fyers_order_endpoint(order_id: str, req: dict):
    """Modify only orders that already exist in the central OMS ledger."""
    price = float(req["price"]) if "price" in req and req["price"] is not None else None
    qty = int(req["qty"]) if "qty" in req and req["qty"] is not None else None
    trigger_price = (
        float(req["trigger_price"])
        if "trigger_price" in req and req["trigger_price"] is not None
        else None
    )
    order_type = req.get("order_type")
    if order_type is not None:
        raise HTTPException(422, "Changing order type is not supported by the central OMS.")

    from engine.order_lifecycle import modify_order_intent

    try:
        res = await asyncio.to_thread(
            modify_order_intent,
            order_id,
            new_price=price,
            new_quantity=qty,
            new_trigger_price=trigger_price,
            actor="FYERS_ADVANCED_API",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "status": "ok",
        "order": res.to_dict(),
    }


@router.get("/api/fyers/trades", tags=["Fyers Advanced"])
async def get_fyers_trades_endpoint():
    """Retrieve execution tradebook history for institutional audit."""
    from brokers.session import get_execution_broker

    brk = get_execution_broker()
    if brk and hasattr(brk, "get_trade_history"):
        trades = await asyncio.to_thread(brk.get_trade_history)
        return {"status": "ok", "trades": trades}
    return {"status": "error", "error": "Execution broker does not support trade history"}


@router.get("/api/fyers/screener/{screener_id}", tags=["Fyers Advanced"])
@router.get("/api/fyers/screeners/technical", tags=["Fyers Advanced"])
async def get_fyers_screener_endpoint(
    screener_id: Optional[str] = None, screener: Optional[str] = None
):
    """Query Fyers native server-side screener (e.g. cs004 for F&O stocks)."""
    from brokers.session import get_data_broker

    brk = get_data_broker()
    eff_screener = screener or screener_id or "cs004"
    if brk and hasattr(brk, "get_screener_technical"):
        data = await asyncio.to_thread(brk.get_screener_technical, eff_screener)
        return {"status": "ok", "data": data, "s": "ok"}
    return {"status": "error", "error": "Data broker does not support Fyers screeners"}


@router.post("/api/fyers/multileg", tags=["Fyers Advanced"])
async def place_fyers_multileg_endpoint(req: dict):
    """Block untracked broker baskets; broker support does not imply atomic fills."""
    _reject_unmanaged_broker_mutation("Direct multi-leg order placement")


@router.get("/api/fyers/alerts", tags=["Fyers Advanced"])
async def get_fyers_alerts_endpoint(archive: int = 0):
    """Retrieve 24x7 server-side exchange price alerts."""
    from brokers.session import get_data_broker

    brk = get_data_broker()
    if brk and hasattr(brk, "get_server_alerts"):
        alerts = await asyncio.to_thread(brk.get_server_alerts, archive=archive)
        return {"status": "ok", "alerts": alerts}
    return {"status": "error", "error": "Broker does not support server alerts"}


@router.post("/api/fyers/alerts", tags=["Fyers Advanced"])
async def create_fyers_alert_endpoint(req: dict):
    """Deploy a 24x7 price trigger directly on Fyers exchange infrastructure."""
    from brokers.session import get_data_broker

    brk = get_data_broker()
    if not brk or not hasattr(brk, "create_server_alert"):
        return {"status": "error", "error": "Broker does not support server alerts"}

    symbol = req.get("symbol", "")
    name = req.get("name", f"Alert-{symbol}")
    target_price = float(req.get("target_price", 0.0))
    condition = req.get("condition", "GT")
    comparison_type = req.get("comparison_type", "LTP")
    notes = req.get("notes", "")

    res = await asyncio.to_thread(
        brk.create_server_alert,
        symbol=symbol,
        name=name,
        target_price=target_price,
        condition=condition,
        comparison_type=comparison_type,
        notes=notes,
    )
    return {"status": "ok", "response": res}


@router.delete("/api/fyers/alerts/{alert_id}", tags=["Fyers Advanced"])
async def delete_fyers_alert_endpoint(alert_id: str):
    """Delete a server-side price trigger."""
    from brokers.session import get_data_broker

    brk = get_data_broker()
    if brk and hasattr(brk, "delete_server_alert"):
        ok = await asyncio.to_thread(brk.delete_server_alert, alert_id)
        return {"status": "ok" if ok else "error", "deleted": ok}
    return {"status": "error", "error": "Broker does not support server alerts"}


@router.get("/api/fyers/screener/candlestick/{pattern}", tags=["Fyers Advanced"])
@router.get("/api/fyers/screeners/candlestick", tags=["Fyers Advanced"])
async def get_fyers_candlestick_screener_endpoint(pattern: Optional[str] = "hammer"):
    """Query native Fyers server-side candlestick pattern recognizer."""
    from brokers.session import get_data_broker

    brk = get_data_broker()
    eff_pattern = pattern or "hammer"
    if brk and hasattr(brk, "get_screener_candlestick"):
        data = await asyncio.to_thread(brk.get_screener_candlestick, eff_pattern)
        if isinstance(data, dict):
            return {**data, "status": "ok", "s": data.get("s", "ok")}
        return {"status": "ok", "data": data, "s": "ok"}
    return {"status": "error", "error": "Data broker does not support candlestick screeners"}


@router.get("/api/fyers/sector-heatmap", tags=["Fyers Advanced"])
async def get_fyers_sector_heatmap_endpoint():
    """Retrieve real-time Sector Heatmap & Relative Strength Breadth Matrix."""
    from brokers.session import get_data_broker

    brk = get_data_broker()
    if brk and hasattr(brk, "get_sector_heatmap"):
        heatmap = await asyncio.to_thread(brk.get_sector_heatmap)
        return heatmap


@router.post("/api/fyers/positions/attach-legs", tags=["Fyers Advanced"])
async def attach_fyers_position_legs_endpoint(req: dict):
    """Block unattached protection changes until position-to-order linkage exists."""
    _reject_unmanaged_broker_mutation("Direct position bracket modification")


@router.post("/api/fyers/positions/convert", tags=["Fyers Advanced"])
async def convert_fyers_position_endpoint(req: dict):
    """Block account product conversion until account-scoped lifecycle tracking exists."""
    _reject_unmanaged_broker_mutation("Direct position product conversion")


@router.post("/api/fyers/smart-orders/limit", tags=["Fyers Advanced"])
async def place_fyers_smart_limit_endpoint(req: dict):
    """Block broker-hosted orders that cannot be reconciled by the central OMS."""
    _reject_unmanaged_broker_mutation("Direct smart-limit order placement")


@router.post("/api/fyers/smart-orders/step", tags=["Fyers Advanced"])
async def place_fyers_smart_step_endpoint(req: dict):
    """Block broker-hosted accumulation orders until child order tracking exists."""
    _reject_unmanaged_broker_mutation("Direct smart-step order placement")


@router.get("/api/fyers/smart-exit/triggers", tags=["Fyers Advanced"])
async def get_fyers_smartexit_triggers_endpoint():
    """Retrieve active server-side Smart Exit triggers."""
    from brokers.session import get_execution_broker

    brk = get_execution_broker()
    if brk and hasattr(brk, "get_smartexit_triggers"):
        triggers = await asyncio.to_thread(brk.get_smartexit_triggers)
        return {"status": "ok", "triggers": triggers}
    return {"status": "error", "error": "Execution broker does not support smart exit triggers"}


@router.post("/api/fyers/smart-exit/triggers", tags=["Fyers Advanced"])
async def create_fyers_smartexit_trigger_endpoint(req: dict):
    """Block unlinked broker-side exit triggers until open positions are tracked."""
    _reject_unmanaged_broker_mutation("Direct smart-exit trigger creation")


# ── Fyers Post-Trade Accounting & Auditing ────────────────────


@router.get("/api/fyers/charges", tags=["Fyers Advanced", "Audit & Accounting"])
async def get_fyers_charges_endpoint(
    from_date: str = "",
    to_date: str = "",
    page_size: int = 100,
    page_no: int = 1,
    segment_type: int = 0,
    exchange_type: int = 0,
    report_type: int = 1,
):
    """Query official Fyers charges history for institutional brokerage and statutory fee audit."""
    from brokers.session import get_execution_broker

    brk = get_execution_broker()
    if not brk or not hasattr(brk, "get_charges_history"):
        return {"status": "error", "error": "Execution broker does not support charges history"}

    res = await asyncio.to_thread(
        brk.get_charges_history,
        from_date=from_date,
        to_date=to_date,
        page_size=page_size,
        page_no=page_no,
        segment_type=segment_type,
        exchange_type=exchange_type,
        report_type=report_type,
    )
    return {"status": "ok", "data": res}


@router.get("/api/fyers/realised-pnl", tags=["Fyers Advanced", "Audit & Accounting"])
async def get_fyers_realised_pnl_endpoint(
    from_date: str = "",
    to_date: str = "",
    page_size: int = 100,
    page_no: int = 1,
):
    """Retrieve realized P&L records directly from Fyers server."""
    from brokers.session import get_execution_broker

    brk = get_execution_broker()
    if not brk or not hasattr(brk, "get_realised_pnl_history"):
        return {
            "status": "error",
            "error": "Execution broker does not support realised P&L history",
        }

    res = await asyncio.to_thread(
        brk.get_realised_pnl_history,
        from_date=from_date,
        to_date=to_date,
        page_size=page_size,
        page_no=page_no,
    )
    return {"status": "ok", "data": res}


@router.get("/api/fyers/tax-pnl", tags=["Fyers Advanced", "Audit & Accounting"])
async def get_fyers_tax_pnl_endpoint(
    from_date: str = "",
    to_date: str = "",
    page_size: int = 100,
    page_no: int = 1,
):
    """Retrieve audited tax P&L report breakdown from Fyers server."""
    from brokers.session import get_execution_broker

    brk = get_execution_broker()
    if not brk or not hasattr(brk, "get_tax_pnl_history"):
        return {"status": "error", "error": "Execution broker does not support tax P&L history"}

    res = await asyncio.to_thread(
        brk.get_tax_pnl_history,
        from_date=from_date,
        to_date=to_date,
        page_size=page_size,
        page_no=page_no,
    )
    return {"status": "ok", "data": res}


@router.get("/api/fyers/ledger", tags=["Fyers Advanced", "Audit & Accounting"])
async def get_fyers_ledger_endpoint(
    from_date: str = "",
    to_date: str = "",
    page_size: int = 100,
    page_no: int = 1,
):
    """Retrieve financial ledger accounting journal directly from Fyers server."""
    from brokers.session import get_execution_broker

    brk = get_execution_broker()
    if not brk or not hasattr(brk, "get_ledger_history"):
        return {"status": "error", "error": "Execution broker does not support ledger history"}

    res = await asyncio.to_thread(
        brk.get_ledger_history,
        from_date=from_date,
        to_date=to_date,
        page_size=page_size,
        page_no=page_no,
    )
    return {"status": "ok", "data": res}


@router.post("/api/fyers/postback", tags=["Fyers Advanced", "Webhooks"])
@router.post("/fyers/postback", tags=["Fyers Advanced", "Webhooks"])
async def fyers_postback_webhook_endpoint(request: Request):
    """
    Webhook postback receiver for real-time Fyers order and trade status updates.
    Validates HMAC-SHA256 signature against FYERS_SECRET_KEY / FYERS_WEBHOOK_SECRET.
    Broadcasts state transitions to web SSE event bus and logs incoming execution data.
    """
    from web.sse import event_bus
    import hashlib
    import hmac
    import json
    from fastapi import HTTPException

    raw_body = await request.body()
    secret = os.environ.get("FYERS_SECRET_KEY", "") or os.environ.get("FYERS_WEBHOOK_SECRET", "")
    signature = (
        request.headers.get("X-Fyers-Signature")
        or request.headers.get("X-Signature")
        or request.query_params.get("signature", "")
    )
    deploy_mode = os.environ.get("DEPLOY_MODE", "")
    is_hosted = deploy_mode not in ("", "desktop", "local", "test")

    if secret:
        expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        if not signature or not hmac.compare_digest(signature, expected):
            raise HTTPException(
                status_code=401, detail="Invalid or missing Fyers webhook signature"
            )
    elif is_hosted:
        raise HTTPException(
            status_code=403, detail="Webhook signature verification required in hosted deployments"
        )

    try:
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    try:
        order_info = payload.get("order", payload)
        order_id = (
            order_info.get("id")
            or order_info.get("order_id")
            or order_info.get("orderNum")
            or "UNKNOWN"
        )
        status = order_info.get("status")
        symbol = order_info.get("symbol", "")

        event_bus.publish_sync(
            "orders",
            {
                "source": "fyers_webhook_postback",
                "order_id": order_id,
                "status": status,
                "symbol": symbol,
                "raw": payload,
            },
        )
    except Exception as e:
        logger.warning(f"Error broadcasting Fyers postback webhook: {e}")

    return {"status": "ok", "message": "Postback received and processed"}


# ── 1. Options Gamma Exposure (GEX) & Dealer Zero-Gamma Levels ─────────────
@router.get("/api/options/gex/{symbol}", tags=["Options & Derivatives"])
async def get_options_gex_endpoint(symbol: str, expiry: Optional[str] = None):
    """
    Returns total Net Market Gamma, Dealer Zero-Gamma Level, Call Wall,
    Put Wall, and Volatility Breakout Zones across the strike strip.
    """
    from analysis.gex import get_gex_analysis

    res = await asyncio.to_thread(get_gex_analysis, symbol, expiry)
    return res


@router.post("/api/options/gex", tags=["Options & Derivatives"])
async def post_options_gex_endpoint(req: dict[str, Any]):
    """Compute GEX analysis from POST payload with symbol and optional expiry."""
    from analysis.gex import get_gex_analysis

    symbol = req.get("symbol", "NIFTY")
    expiry = req.get("expiry")
    res = await asyncio.to_thread(get_gex_analysis, symbol, expiry)
    return res


@router.post("/api/options/payoff", tags=["Options & Derivatives", "Analytics"])
async def post_options_payoff_endpoint(req: dict[str, Any]):
    """
    Computes institutional multi-leg option payoff:
    - At-Expiry P&L curve and theoretical T+0 curve (Black-Scholes with IV shift)
    - Breakeven points, Max Profit, Max Loss, and net return
    - Roundtrip statutory friction breakdown (STT, GST, exchange charges, brokerage)
    - Aggregated portfolio Greeks (Delta, Gamma, Theta, Vega)
    """
    from analysis.options import PayoffLeg, payoff
    from market.quotes import get_ltp

    underlying = str(req.get("underlying", "NIFTY")).upper()
    spot = float(req.get("spot", 0.0) or 0.0)
    if spot <= 0:
        try:
            spot = float(await asyncio.to_thread(get_ltp, underlying) or 0.0)
        except Exception:
            spot = 0.0

    raw_legs = req.get("legs", [])
    if not raw_legs:
        return {"status": "ERROR", "message": "No strategy legs provided"}

    legs = []
    for l in raw_legs:
        legs.append(
            PayoffLeg(
                option_type=str(l.get("option_type", "CE")).upper(),
                transaction=str(l.get("transaction", "BUY")).upper(),
                strike=float(l.get("strike", spot or 100.0)),
                premium=float(l.get("premium", 0.0)),
                lot_size=int(l.get("lot_size", 1)),
                lots=int(l.get("lots", 1)),
                iv=float(l["iv"]) if "iv" in l and l["iv"] is not None else None,
                dte=int(l["dte"]) if "dte" in l and l["dte"] is not None else None,
            )
        )

    steps = int(req.get("steps", 50))
    iv_shift = float(req.get("iv_shift_pct", 0.0))
    spot_range = None
    if "min_spot" in req and "max_spot" in req:
        spot_range = (float(req["min_spot"]), float(req["max_spot"]))

    res = await asyncio.to_thread(
        payoff,
        legs=legs,
        spot_range=spot_range,
        steps=steps,
        iv_shift_pct=iv_shift,
    )

    return {
        "status": "ok",
        "underlying": underlying,
        "spot": spot,
        "max_profit": res.max_profit,
        "max_loss": res.max_loss,
        "net_max_profit": res.net_max_profit,
        "net_max_loss": res.net_max_loss,
        "breakevens": res.breakevens,
        "friction_breakdown": res.friction_breakdown,
        "net_greeks": res.net_greeks,
        "payoff": [{"spot": p.spot, "pnl": p.pnl, "t0_pnl": p.t0_pnl} for p in res.payoff],
    }


@router.post("/api/options/optimize_spreads", tags=["Options & Derivatives", "Analytics"])
async def post_options_optimize_spreads_endpoint(req: dict[str, Any]):
    """
    Evaluates and ranks institutional defined-risk options strategies:
    - Bull Call Spread, Bear Put Spread, Bull Put Credit Spread, Bear Call Credit Spread, Iron Condor, Iron Butterfly
    - Returns net cashflow, max profit, max loss, risk:reward, breakevens, Greeks, POP, and regime suitability score.
    """
    from analysis.options import optimize_defined_risk_strategies
    from market.quotes import get_ltp
    from market.symbol_master import get_lot_size

    underlying = (
        str(req.get("underlying", "NIFTY"))
        .upper()
        .replace("NSE:", "")
        .replace("BSE:", "")
        .replace("-INDEX", "")
    )
    spot = float(req.get("spot", 0.0) or 0.0)
    if spot <= 0:
        try:
            spot = float(await asyncio.to_thread(get_ltp, underlying) or 0.0)
        except Exception:
            spot = 0.0

    lot_size = int(req.get("lot_size", 0) or 0)
    if lot_size <= 0:
        try:
            lot_size = get_lot_size(underlying) or 25
        except Exception:
            lot_size = 25

    regime = str(req.get("regime", "NEUTRAL")).upper()
    dte_days = int(req.get("dte_days", 5) or 5)
    iv_atm = float(req.get("iv_atm", 15.0) or 15.0)
    strike_step = req.get("strike_step")
    chain = req.get("chain")

    # If chain not provided in request, attempt to fetch live option chain
    if not chain:
        try:
            from market.options import get_options_chain

            inst_chain = await asyncio.to_thread(get_options_chain, underlying)
            if inst_chain and hasattr(inst_chain, "contracts"):
                chain = [
                    {
                        "strike_price": c.strike,
                        "option_type": c.option_type,
                        "last_price": c.ltp,
                    }
                    for c in inst_chain.contracts
                ]
        except Exception as e_chain:
            logger.debug(f"[optimize_spreads] Live chain lookup fallback: {e_chain}")

    res = await asyncio.to_thread(
        optimize_defined_risk_strategies,
        underlying=underlying,
        spot=spot,
        lot_size=lot_size,
        chain=chain,
        regime=regime,
        dte_days=dte_days,
        iv_atm=iv_atm,
        strike_step=float(strike_step) if strike_step else None,
    )

    return {"status": "ok", **res}


@router.get("/api/scanner/smt_divergences", tags=["Market Intelligence", "Smart Money Concepts"])
@router.post("/api/scanner/smt_divergences", tags=["Market Intelligence", "Smart Money Concepts"])
async def get_smt_divergences_endpoint():
    """
    Cross-Market Smart Money Technique (SMT) Divergence Scanner:
    Monitors NIFTY vs BANKNIFTY, FINNIFTY vs BANKNIFTY, SENSEX vs BANKEX,
    GOLD vs SILVER, and CRUDE vs NATURAL GAS for institutional accumulation,
    distribution (Judas swings), polarization conflict, and harmonious trend flow.
    """
    from analysis.smt_scanner import scan_cross_market_smt_divergences

    res = await asyncio.to_thread(scan_cross_market_smt_divergences)
    return res


@router.get("/api/options/surface/{symbol}", tags=["Options & Derivatives", "Analytics"])
async def get_options_surface_endpoint(symbol: str):
    """
    Returns authentic constant-tenor 30-day IV surface snapshot, 25-delta Risk Reversal Skew,
    and empirical IV Rank/Percentile without synthetic defaults.
    """
    from market.options import get_iv_surface_snapshot

    clean = symbol.upper().replace("NSE:", "").replace("NFO:", "").strip()
    snap = await asyncio.to_thread(get_iv_surface_snapshot, clean)
    return {"status": "ok", "data": snap.to_dict()}


# ── 2. Order Flow & Cumulative Volume Delta (CVD) Divergence ───────────────


# ── 2b. Microstructure Order Flow Toxicity (VPIN) ───────────────────────────
@router.get("/api/order-flow/vpin/{symbol}", tags=["Order Flow & Depth", "Market Microstructure"])
async def get_order_flow_vpin_endpoint(symbol: str, num_buckets: int = 20):
    """
    Computes Volume-Synchronized Probability of Toxicity (VPIN) using Bulk Volume Classification.
    Measures informed aggressive institutional order flow and adverse selection risk.
    """
    from analysis.order_flow import compute_vpin
    from market.history import get_historical_data

    clean = symbol.upper().replace("NSE:", "").replace(".NS", "").strip()
    df = await asyncio.to_thread(get_historical_data, clean, "5m", 3)
    res = await asyncio.to_thread(compute_vpin, clean, df, num_buckets)
    return {"status": "ok", "data": res.to_dict()}


# ── 2c. Test-Time Reasoning Trajectory Simulator (Agentic MCTS) ────────────
@router.get("/api/analysis/trajectories", tags=["Market Intelligence", "Scenario Simulation"])
async def get_trajectory_simulation_endpoint(
    symbol: str,
    direction: str = "LONG",
    spot: float = 0.0,
    entry: float = 0.0,
    sl: float = 0.0,
    t1: float = 0.0,
    t2: Optional[float] = None,
    vix: float = 14.5,
    vpin: float = 0.50,
    archetype: str = "NORMAL_DAY",
    rvol: float = 1.0,
):
    """
    Simulates multi-branch forward price trajectories (Expansion, Pullback/Retest, SFP Trap)
    over 15m, 30m, and 60m horizons to compute expected payoff (EV).
    """
    from analysis.trajectory_search import simulate_trade_trajectories
    from market.quotes import get_ltp

    clean = symbol.upper().replace("NSE:", "").replace(".NS", "").strip()
    current_spot = spot if spot > 0 else float(get_ltp(clean) or 24500.0)
    entry_px = entry if entry > 0 else current_spot
    sl_px = (
        sl if sl > 0 else (entry_px * 0.995 if direction.upper() == "LONG" else entry_px * 1.005)
    )
    t1_px = t1 if t1 > 0 else (entry_px * 1.01 if direction.upper() == "LONG" else entry_px * 0.99)

    res = await asyncio.to_thread(
        simulate_trade_trajectories,
        symbol=clean,
        direction=direction,
        spot=current_spot,
        entry_price=entry_px,
        stop_loss=sl_px,
        target_1=t1_px,
        target_2=t2,
        vix=vix,
        vpin=vpin,
        day_archetype=archetype,
        rvol=rvol,
    )
    return {"status": "ok", "data": res.to_dict()}


# ── 2d. Episodic Trade Memory & Historical Analogies ─────────────────────────
@router.get("/api/memory/episodes/analogies", tags=["Market Intelligence", "Episodic Memory"])
async def get_episodic_analogies_endpoint(
    symbol: str,
    direction: str = "LONG",
    vix_regime: str = "NORMAL_IV",
    day_archetype: str = "NORMAL_DAY",
    vpin_regime: str = "MODERATE_TOXICITY",
    top_k: int = 5,
):
    """
    Retrieves top K most analogous historical market setups from Episodic Trade Memory
    and surfaces empirical win rates, average MFE/MAE drawdowns, and actionable lessons.
    """
    from engine.episodic_memory import get_episodic_memory_store

    store = get_episodic_memory_store()
    res = await asyncio.to_thread(
        store.query_analogous_episodes,
        symbol=symbol,
        direction=direction,
        vix_regime=vix_regime,
        day_archetype=day_archetype,
        vpin_regime=vpin_regime,
        top_k=top_k,
    )
    return {"status": "ok", "data": res.to_dict()}


# ── 2e. Cross-Asset Intermarket Lead-Lag Transmission ─────────────────
@router.get(
    "/api/analysis/intermarket-transmission", tags=["Market Intelligence", "Macro Transmission"]
)
async def get_intermarket_transmission_endpoint():
    """
    Computes real-time cross-asset lead-lag transmission matrix (Brent Crude, US 10Y Yield,
    DXY Dollar Index, USDINR, GIFT Nifty) across watched Indian sectors and heavyweights.
    """
    from analysis.intermarket_transmission import compute_intermarket_transmission_matrix

    res = await asyncio.to_thread(compute_intermarket_transmission_matrix)
    return {"status": "ok", "data": res.to_dict()}


@router.get(
    "/api/analysis/intermarket-transmission/{symbol}",
    tags=["Market Intelligence", "Macro Transmission"],
)
async def get_symbol_macro_transmission_endpoint(symbol: str):
    """
    Returns specific macro spillover transmission, beta sensitivities, and actionable bias
    for an individual equity or index symbol.
    """
    from analysis.intermarket_transmission import compute_symbol_transmission

    res = await asyncio.to_thread(compute_symbol_transmission, symbol)
    return {"status": "ok", "data": res.to_dict()}


# ── 2f. SEBI Physical Delivery & Market-On-Close (MOC) Risk Sentinel ──
@router.get("/api/risk/physical-delivery", tags=["Risk & Governance", "Compliance"])
async def get_physical_delivery_risk_endpoint():
    """
    Audits active derivative positions for SEBI mandatory physical delivery obligations
    and escalating expiry week margin requirements.
    """
    from engine.eod_rebalancer import audit_open_positions_for_physical_delivery

    res = await asyncio.to_thread(audit_open_positions_for_physical_delivery)
    return {"status": "ok", "data": [item.to_dict() for item in res]}


@router.get("/api/risk/moc-guardian", tags=["Risk & Governance", "Execution Safety"])
async def get_moc_guardian_endpoint():
    """
    Evaluates 15:15–15:30 IST Market-On-Close state, scanning for pending intraday MIS
    orders and critical delivery risks requiring immediate square-off before broker RMS.
    """
    from engine.eod_rebalancer import run_moc_guardian_audit

    rep = await asyncio.to_thread(run_moc_guardian_audit)
    return {"status": "ok", "data": rep.to_dict()}


# ── 2g. Real-Time 25-Delta Volatility Skew & Surface Analysis ─────────
@router.get("/api/options/vol-skew/{symbol}", tags=["Options & Volatility", "Market Intelligence"])
async def get_volatility_skew_endpoint(symbol: str, expiry: Optional[str] = None):
    """
    Computes 25-Delta Risk Reversal Skew, 25-Delta Butterfly Smile Curvature,
    and Volatility Risk Premium (VRP) to identify institutional crash hedging or short squeezes.
    """
    from analysis.volatility_surface import compute_25delta_skew_and_vrp

    clean = symbol.upper().replace("NSE:", "").strip()
    res = await asyncio.to_thread(compute_25delta_skew_and_vrp, clean, expiry)
    if not res:
        return {
            "status": "UNAVAILABLE",
            "message": f"Options chain or volatility surface unavailable for {clean}",
        }
    return {"status": "ok", "data": res.to_dict()}


# ── 2h. Episodic Memory Quarter-Kelly Optimal Position Sizing ────────
@router.post("/api/risk/position-size/episodic-kelly", tags=["Risk & Governance", "Capital Sizing"])
async def post_episodic_kelly_position_size_endpoint(req: dict[str, Any]):
    """
    Computes Quarter-Kelly optimal position sizing grounded in Episodic Memory empirical win rates.
    """
    from engine.position_sizer import calculate_episodic_kelly_position_size

    symbol = str(req.get("symbol", "NIFTY"))
    direction = str(req.get("direction", "BULLISH"))
    entry_price = float(req.get("entry_price", 0.0) or 100.0)
    stop_loss = float(req.get("stop_loss", 0.0) or (entry_price * 0.98))
    target_price = float(req.get("target_price", 0.0)) if req.get("target_price") else None
    capital = float(req.get("capital", 100000.0) or 100000.0)
    day_archetype = str(req.get("day_archetype", "NORMAL_DAY"))
    vix_regime = str(req.get("vix_regime", "NORMAL_IV"))
    vpin_regime = str(req.get("vpin_regime", "LOW_TOXICITY"))
    max_risk_pct = float(req.get("max_risk_pct", 1.5) or 1.5)
    is_fno = bool(req.get("is_fno", False))
    alert_type = str(req.get("alert_type", "MOMENTUM"))

    res = await asyncio.to_thread(
        calculate_episodic_kelly_position_size,
        symbol=symbol,
        direction=direction,
        entry_price=entry_price,
        stop_loss=stop_loss,
        target_price=target_price,
        capital=capital,
        day_archetype=day_archetype,
        vix_regime=vix_regime,
        vpin_regime=vpin_regime,
        max_risk_pct=max_risk_pct,
        is_fno=is_fno,
        alert_type=alert_type,
    )
    return {"status": "ok", "data": res.to_dict()}


@router.get("/api/order-flow/cvd/{symbol}", tags=["Order Flow & Depth"])
async def get_order_flow_cvd_endpoint(symbol: str, timeframe: str = "5m"):
    """
    Computes Level 2 Bid/Ask order book delta imbalances and multi-bar
    Cumulative Volume Delta (CVD) to identify institutional absorption and exhaustion tops/bottoms.
    """
    from analysis.order_flow import analyze_order_flow

    snap = await asyncio.to_thread(analyze_order_flow, symbol, timeframe)
    return {"status": "ok", "data": snap.to_dict()}


@router.post("/api/order-flow/analyze", tags=["Order Flow & Depth"])
async def post_order_flow_analyze_endpoint(req: dict[str, Any]):
    """Analyze order flow and CVD from POST payload."""
    from analysis.order_flow import analyze_order_flow

    symbol = req.get("symbol", "NIFTY")
    timeframe = req.get("timeframe", "5m")
    snap = await asyncio.to_thread(analyze_order_flow, symbol, timeframe)
    return {"status": "ok", "data": snap.to_dict()}


# ── 3. Automated Volatility Risk-Parity Position Sizing ──────────────────────
@router.get("/api/risk/size/{symbol}", tags=["Risk & Sizing"])
async def get_volatility_risk_parity_size_endpoint(
    symbol: str,
    capital: Optional[float] = None,
    risk_pct: float = 1.0,
    max_margin_pct: float = 25.0,
    entry_price: Optional[float] = None,
    stop_loss: Optional[float] = None,
    is_fno: Optional[bool] = None,
    alert_type: Optional[str] = None,
):
    """
    Automated Volatility Risk-Parity sizing engine. Equalizes rupee risk contribution
    using 14-period ATR and margin utilization limits.
    """
    from engine.position_sizer import calculate_volatility_risk_parity_size

    res = await asyncio.to_thread(
        calculate_volatility_risk_parity_size,
        symbol=symbol,
        entry_price=entry_price,
        stop_loss=stop_loss,
        capital=capital,
        target_risk_pct=risk_pct,
        max_margin_pct=max_margin_pct,
        is_fno=is_fno,
        alert_type=alert_type,
    )
    return {"status": "ok", "data": res.as_dict()}


@router.post("/api/risk/size", tags=["Risk & Sizing"])
async def post_volatility_risk_parity_size_endpoint(req: dict[str, Any]):
    """Automated Volatility Risk-Parity sizing engine via POST."""
    from engine.position_sizer import calculate_volatility_risk_parity_size

    symbol = req.get("symbol", "NIFTY")
    capital = float(req["capital"]) if "capital" in req and req["capital"] else None
    risk_pct = float(req.get("risk_pct", 1.0))
    max_margin_pct = float(req.get("max_margin_pct", 25.0))
    entry_price = float(req["entry_price"]) if "entry_price" in req and req["entry_price"] else None
    stop_loss = float(req["stop_loss"]) if "stop_loss" in req and req["stop_loss"] else None
    is_fno = bool(req["is_fno"]) if "is_fno" in req else None
    alert_type = req.get("alert_type")

    res = await asyncio.to_thread(
        calculate_volatility_risk_parity_size,
        symbol=symbol,
        entry_price=entry_price,
        stop_loss=stop_loss,
        capital=capital,
        target_risk_pct=risk_pct,
        max_margin_pct=max_margin_pct,
        is_fno=is_fno,
        alert_type=alert_type,
    )
    return {"status": "ok", "data": res.as_dict()}


# ── 4. Broker Margin Pre-Flight Estimator ────────────────────────────────────
@router.get("/api/fyers/margin-check", tags=["Fyers Advanced", "Risk & Sizing"])
async def get_fyers_margin_check_endpoint(
    symbol: str,
    qty: int = 1,
    side: str = "BUY",
    product_type: str = "INTRADAY",
    price: Optional[float] = None,
):
    """
    Pre-flight margin calculation and net transaction charges estimation.
    Queries official Fyers Multi-Order Margin API and SEBI statutory rates.
    """
    from brokers.session import get_execution_broker

    brk = get_execution_broker()
    if not brk or not hasattr(brk, "check_order_margin"):
        return {
            "status": "error",
            "error": "Execution broker does not support pre-flight margin checks",
        }

    order_payload = [
        {
            "symbol": symbol,
            "qty": qty,
            "side": side,
            "product_type": product_type,
            "price": price or 0.0,
        }
    ]
    res = await asyncio.to_thread(brk.check_order_margin, order_payload)
    return res


@router.post("/api/fyers/margin-check", tags=["Fyers Advanced", "Risk & Sizing"])
async def post_fyers_margin_check_endpoint(req: dict[str, Any]):
    """
    Pre-flight multi-order margin calculation and net transaction charges estimation.
    """
    from brokers.session import get_execution_broker

    brk = get_execution_broker()
    if not brk or not hasattr(brk, "check_order_margin"):
        return {
            "status": "error",
            "error": "Execution broker does not support pre-flight margin checks",
        }

    orders = req.get("orders", [])
    if not orders and "symbol" in req:
        orders = [req]

    res = await asyncio.to_thread(brk.check_order_margin, orders)
    return res


# ── Fyers Institutional 50-Level Depth (TBT) Endpoints ───────────


@router.get("/api/fyers/tbt-depth/{symbol}", tags=["Fyers 50-Depth TBT"])
async def get_fyers_50_depth_endpoint(symbol: str):
    """
    Retrieve real-time 50-level Depth of Market (DOM) from Fyers TBT feed.
    Includes OBI-50, resting iceberg walls, and density score.
    """
    from market.fyers_tbt_manager import fyers_tbt_manager

    # Auto-subscribe so subsequent queries stay warm
    fyers_tbt_manager.subscribe([symbol])
    data = await asyncio.to_thread(fyers_tbt_manager.get_50_depth, symbol)
    return {"status": "ok", "data": data}


@router.post("/api/fyers/tbt-audit", tags=["Fyers 50-Depth TBT"])
async def post_fyers_tbt_audit_endpoint(req: dict[str, Any]):
    """
    Tier 2 Institutional Gatekeeper:
    Audits candidate setup order book conviction, resting walls, and slippage.
    """
    from market.fyers_tbt_manager import fyers_tbt_manager

    symbol = req.get("symbol", "")
    if not symbol:
        return {"status": "error", "error": "Symbol is required"}
    side = req.get("side", "BUY")
    lot_size = int(req.get("lot_size", 65))

    audit = await asyncio.to_thread(
        fyers_tbt_manager.audit_candidate_depth, symbol, side=side, lot_size=lot_size
    )
    return {"status": "ok", "audit": audit}


@router.post("/api/fyers/tbt-subscribe", tags=["Fyers 50-Depth TBT"])
async def post_fyers_tbt_subscribe_endpoint(req: dict[str, Any]):
    """Dynamically register active symbol for 50-depth streaming."""
    from market.fyers_tbt_manager import fyers_tbt_manager

    symbols = req.get("symbols", [])
    if isinstance(symbols, str):
        symbols = [symbols]
    if "symbol" in req and req["symbol"] not in symbols:
        symbols.append(req["symbol"])

    fyers_tbt_manager.subscribe(symbols)
    return {"status": "ok", "subscribed": symbols}


@router.get("/api/fyers/tbt-status", tags=["Fyers 50-Depth TBT"])
async def get_fyers_tbt_status_endpoint():
    """Returns real-time 15-slot allocation and status of Fyers TBT depth engine."""
    from market.fyers_tbt_manager import fyers_tbt_manager

    status = await asyncio.to_thread(fyers_tbt_manager.get_active_slots_status)
    return {"status": "ok", "data": status}


@router.post("/api/fyers/tbt-evict", tags=["Fyers 50-Depth TBT"])
async def post_fyers_tbt_evict_endpoint(
    req: Optional[dict[str, Any]] = None,
    symbol: Optional[str] = None,
    cooldown_seconds: float = 60.0,
):
    """
    Manually evict a symbol/strike from 15-slot TBT market depth.
    Unsubscribes from WebSocket and applies an eviction cooldown.
    """
    from market.fyers_tbt_manager import fyers_tbt_manager

    target = symbol or (req.get("symbol") if req else None) or ""
    if not target:
        raise HTTPException(status_code=400, detail="Symbol is required for eviction")

    cd = float(
        req.get("cooldown_seconds") if req and "cooldown_seconds" in req else cooldown_seconds
    )
    res = await asyncio.to_thread(fyers_tbt_manager.evict_symbol, target, cooldown_sec=cd)
    return res


@router.post("/api/fyers/tbt-clear-cooldowns", tags=["Fyers 50-Depth TBT"])
async def post_fyers_tbt_clear_cooldowns_endpoint(req: Optional[dict[str, Any]] = None):
    """
    Manually clear all eviction cooldowns (or for a specific symbol) to instantly liberate slots.
    """
    from market.fyers_tbt_manager import fyers_tbt_manager

    target = (req.get("symbol") if req else None) or None
    res = await asyncio.to_thread(fyers_tbt_manager.clear_eviction_cooldowns, symbol=target)
    return res


@router.post("/api/fyers/tbt-rebalance", tags=["Fyers 50-Depth TBT"])
async def post_fyers_tbt_rebalance_endpoint(req: Optional[dict[str, Any]] = None):
    """Manually rebalance the 15-slot TBT grid and cleanse stale scouts."""
    from market.fyers_tbt_manager import fyers_tbt_manager

    session = req.get("session") if req else None
    res = await asyncio.to_thread(fyers_tbt_manager.rebalance_grid_now, session=session)
    return res


@router.post("/api/fyers/tbt-focus", tags=["Fyers 50-Depth TBT"])
async def post_fyers_tbt_focus_endpoint(req: dict[str, Any]):
    """Set primary focus index for TBT depth ('NIFTY', 'BANKNIFTY', 'SENSEX', or null/balanced)."""
    from market.fyers_tbt_manager import fyers_tbt_manager

    focus = req.get("focus") or req.get("index") or None
    await asyncio.to_thread(fyers_tbt_manager.set_primary_focus, index_name=focus)
    status = await asyncio.to_thread(fyers_tbt_manager.get_active_slots_status)
    return {"status": "ok", "primary_focus": focus, "data": status}


@router.get("/api/fyers/rate-gate-status", tags=["Fyers Prime Rate Gate"])
async def get_fyers_rate_gate_status_endpoint():
    """Returns real-time Fyers sliding-window rate limit consumption (req/sec, req/min, daily budget)."""
    from market.fyers_rate_gate import get_fyers_rate_gate

    diag = get_fyers_rate_gate().get_diagnostics()
    return {"status": "ok", "data": diag}


@router.get("/api/market/symbol/search", tags=["Symbol Master"])
async def search_symbols_endpoint(q: str, limit: int = 10):
    """Fast token-free symbol search across public Fyers master."""
    from market.symbol_master import get_symbol_master

    sm = get_symbol_master()
    res = await asyncio.to_thread(sm.search_symbols, q, limit=limit)
    return {"status": "ok", "query": q, "count": len(res), "data": res}


@router.get("/api/market/symbol/info", tags=["Symbol Master"])
async def get_symbol_info_endpoint(symbol: str):
    """Returns lot size, tick size, and validity for a symbol."""
    from market.symbol_master import get_symbol_master

    sm = get_symbol_master()
    info = await asyncio.to_thread(sm.get_symbol_info, symbol)
    return {"status": "ok", "symbol": symbol, "data": info}


@router.get("/api/indices/regime", tags=["Index Adaptive Intelligence"])
@router.get("/api/indices/regime/{symbol}", tags=["Index Adaptive Intelligence"])
async def get_index_adaptive_regime_endpoint(symbol: Optional[str] = "NIFTY"):
    """
    Eagle Eye, Tiger Stalking & Sniper Execution Adaptive Regime Engine.
    Evaluates:
      1. Choppiness Index (CHOP) & Wilder's ADX trend strength
      2. Time-of-Day phase (Opening Discovery, Midday Theta Trap, Power Hour)
      3. Higher Timeframe 15m/1h Trend & 20-EMA slope
      4. Heavyweight Locomotive Confluence & Breadth
      5. Tiger Strategy Mandate (MOMENTUM_EXPANSION vs PRESERVE_CAPITAL vs TURTLE_SOUP)
      6. Sniper Blueprint (No-Chase limit, tight OTE bracket, structure SL, 20m time-stop)
    """
    from engine.index_adaptive_regime import evaluate_index_adaptive_regime
    from market.quotes import get_quote
    from market.history import get_ohlcv

    target_sym = (symbol or "NIFTY").upper().strip()
    if target_sym in ("ALL", "MAJOR", "OVERVIEW"):
        symbols = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]
    else:
        symbols = [target_sym]

    def _eval_single(sym: str) -> dict[str, Any]:
        clean = canonical_symbol(sym)
        # Fetch spot quote
        quote_sym = f"NSE:{clean}" if clean != "SENSEX" else "BSE:SENSEX"
        q_map = get_quote([quote_sym])
        spot = float(getattr(q_map.get(quote_sym), "last_price", 0.0) or 0.0)
        # Fetch 5m intraday OHLCV
        df_5m = None
        try:
            df_5m = get_ohlcv(clean, days=5, timeframe="5m")
        except Exception as e_suppressed:
            logger.debug(
                f"[web.routers.market_data] Non-fatal exception suppressed: {e_suppressed}"
            )

        decision = evaluate_index_adaptive_regime(
            underlying=clean,
            spot=spot,
            ohlcv_5m=df_5m,
        )
        return decision.to_dict()

    results = {}
    for s in symbols:
        results[s] = await asyncio.to_thread(_eval_single, s)

    if len(symbols) == 1:
        return {"status": "ok", "symbol": symbols[0], "regime": results[symbols[0]]}
    return {"status": "ok", "regimes": results}


@router.get("/api/levels/daily", tags=["Market Levels"])
async def get_daily_levels_all_endpoint(session_date: Optional[str] = None):
    """
    Returns all pre-computed and persisted daily reference levels (CPR, Camarilla, Classical, Weekly, Gap %)
    for today's session. Sub-millisecond in-memory response.
    """
    from engine.daily_levels import daily_levels_store

    levels_map = await asyncio.to_thread(daily_levels_store.get_all_for_today, session_date)
    return {
        "status": "ok",
        "count": len(levels_map),
        "levels": {sym: dl.to_dict() for sym, dl in levels_map.items()},
    }


@router.get("/api/levels/daily/{symbol}", tags=["Market Levels"])
async def get_daily_levels_symbol_endpoint(symbol: str, session_date: Optional[str] = None):
    """
    Returns institutional daily reference levels for a specific symbol.
    Includes CPR, Camarilla Pivots, Classical Pivots, Weekly High/Low, Pre-Market Gap %,
    and Actionable Execution Blueprint.
    """
    from engine.daily_levels import daily_levels_store

    clean = symbol.upper().strip()
    dl = await asyncio.to_thread(daily_levels_store.get_levels, clean, session_date)
    if not dl:
        raise HTTPException(status_code=404, detail=f"Daily levels not found for {clean}")
    return {"status": "ok", "symbol": clean, "levels": dl.to_dict()}


@router.post("/api/levels/prime", tags=["Market Levels"])
async def prime_daily_levels_endpoint(payload: Optional[dict] = None):
    """
    Primes and persists daily levels on demand for benchmark indices and watchlist symbols.
    """
    from engine.daily_levels import daily_levels_store

    symbols = payload.get("symbols") if isinstance(payload, dict) else None
    results = await asyncio.to_thread(daily_levels_store.prime_universe, symbols)
    return {
        "status": "ok",
        "primed_count": len(results),
        "symbols": list(results.keys()),
    }


@router.get("/api/market/indicators", tags=["Quantitative Indicators"])
@router.get("/api/market/indicators/{symbol}", tags=["Quantitative Indicators"])
async def get_indicator_snapshot_endpoint(
    symbol: Optional[str] = "NIFTY",
    exchange: Optional[str] = "NSE",
    time_horizon: Optional[str] = "INTRADAY",
    force_refresh: bool = False,
):
    """
    Single Source of Truth (SSOT) Institutional Indicator Snapshot Endpoint.
    Aggregates ATR, ADX, ROC, Greeks, PDH/PDL/PDC, CMP, CPR, and Index Futures Volume
    with strict per-field provenance tagging (REAL_LIVE, DEGRADED_CACHED, COMPUTED_ESTIMATE, UNAVAILABLE).
    """
    from engine.indicator_snapshot import get_indicator_snapshot

    clean = (symbol or "NIFTY").upper().strip()
    snap = await asyncio.to_thread(
        get_indicator_snapshot,
        symbol=clean,
        exchange=exchange or "NSE",
        time_horizon=time_horizon or "INTRADAY",
        force_refresh=force_refresh,
    )
    return {
        "status": "ok",
        "symbol": clean,
        "indicators": snap.to_flat_dict(),
        "snapshot": snap.to_dict(),
    }


@router.get("/api/market/depth-radar", tags=["Market Data", "Market Intelligence"])
async def get_depth_radar_endpoint(
    segment: Optional[str] = "ALL",
    query: Optional[str] = None,
    limit: int = 60,
    allow_rest: bool = False,
):
    """
    Returns real-time L2 Market Depth Radar across curated market universe.
    Includes OBI, micro-price skew, spread friction, depth notional (₹ Cr),
    resting walls, and actionable decision blueprints.
    """
    from market.universe_depth_radar import get_universe_depth_radar

    rows = await asyncio.to_thread(
        get_universe_depth_radar,
        segment=segment or "ALL",
        query=query,
        limit=min(100, max(10, limit)),
        allow_rest_fallback=allow_rest,
    )
    return {
        "status": "ok",
        "segment": segment,
        "count": len(rows),
        "data": rows,
    }


@router.get("/api/market/strategic-horizon", tags=["Market Intelligence", "Market Data"])
async def get_strategic_horizon_endpoint(symbol: Optional[str] = "NIFTY"):
    """
    Returns proactive, forward-looking Strategic Horizon battleground synthesis for an index.
    Synthesizes live coordinates, SMT alignment, Locomotive Polarization, option walls,
    and key structural invalidation levels.
    """
    from engine.strategic_horizon import generate_strategic_horizon

    clean = (symbol or "NIFTY").upper().strip()
    report = await asyncio.to_thread(generate_strategic_horizon, clean)
    return {
        "status": "ok",
        "data": report.to_dict(),
    }


@router.get("/api/backtest/smt-benchmark", tags=["Market Intelligence", "Backtesting"])
async def get_smt_benchmark_endpoint(
    symbol: Optional[str] = "NIFTY",
    sibling: Optional[str] = None,
    period: Optional[str] = "1y",
    capital: float = 100000.0,
):
    """
    Returns quantitative backtest benchmark comparing SMT Sweep against
    baseline strategies (Turtle Soup, Donchian, EMA Cross, RSI, Buy & Hold).
    Includes post-October 2024 statutory charges, dual win-rates, and risk-adjusted metrics.
    """
    from engine.smt_benchmark import run_smt_benchmark

    clean_symbol = (symbol or "NIFTY").upper().strip()
    clean_sibling = sibling.upper().strip() if sibling else None
    period_str = (period or "1y").lower().strip()

    benchmark = await asyncio.to_thread(
        run_smt_benchmark,
        symbol=clean_symbol,
        sibling_symbol=clean_sibling,
        period=period_str,
        capital=max(10000.0, capital),
    )
    return {
        "status": "ok",
        "data": benchmark.to_dict(),
    }
