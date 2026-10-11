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
        except Exception:
            pass

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
    except Exception:
        pass
    if not brk:
        try:
            brk = get_execution_broker()
        except Exception:
            pass

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
    """Place a 1-year valid GTT trigger order on Fyers servers."""
    from brokers.session import get_execution_broker

    brk = get_execution_broker()
    if not brk or not hasattr(brk, "place_gtt_order"):
        return {"status": "error", "error": "Execution broker does not support GTT orders"}

    symbol = req.get("symbol", "")
    qty = int(req.get("qty", req.get("quantity", 1)))
    raw_side = str(req.get("side", 1)).upper()
    side = 1 if raw_side in ("1", "BUY") else -1
    trigger_price = float(req.get("trigger_price", req.get("triggerPrice", 0.0)))
    limit_price = float(req.get("limit_price", req.get("limitPrice", trigger_price)))
    product = req.get("product", req.get("productType", "CNC"))

    res = await asyncio.to_thread(
        brk.place_gtt_order,
        symbol=symbol,
        qty=qty,
        side=side,
        trigger_price=trigger_price,
        limit_price=limit_price,
        product=product,
    )
    resp_dict = res if isinstance(res, dict) else {}
    return {
        **resp_dict,
        "status": "ok" if (not isinstance(res, dict) or res.get("s", "ok") == "ok") else "error",
        "response": res,
    }


@router.delete("/api/fyers/gtt/{order_id}", tags=["Fyers Advanced"])
async def cancel_fyers_gtt_order_endpoint(order_id: str):
    """Cancel a server-held GTT order."""
    from brokers.session import get_execution_broker

    brk = get_execution_broker()
    if brk and hasattr(brk, "cancel_gtt_order"):
        ok = await asyncio.to_thread(brk.cancel_gtt_order, order_id)
        return {"status": "ok" if ok else "error", "cancelled": ok}
    return {"status": "error", "error": "Execution broker does not support GTT orders"}


@router.post("/api/fyers/smart-trail", tags=["Fyers Advanced"])
async def place_fyers_smart_trail_endpoint(req: dict):
    """Place an exchange-managed Smart Trailing Stop Loss order."""
    from brokers.session import get_execution_broker

    brk = get_execution_broker()
    if not brk or not hasattr(brk, "create_smart_trailing_order"):
        return {
            "status": "error",
            "error": "Execution broker does not support smart trailing orders",
        }

    symbol = req.get("symbol", "")
    qty = int(req.get("qty", 1))
    raw_side = str(req.get("side", -1)).upper()
    side = 1 if raw_side in ("1", "BUY") else -1
    stop_price = float(req.get("stop_price", 0.0))
    trail_amount = float(req.get("trail_amount", 1.0))
    limit_price = float(req.get("limit_price")) if req.get("limit_price") else None
    product = req.get("product", "INTRADAY")

    res = await asyncio.to_thread(
        brk.create_smart_trailing_order,
        symbol=symbol,
        qty=qty,
        side=side,
        stop_price=stop_price,
        trail_amount=trail_amount,
        limit_price=limit_price,
        product=product,
    )
    return {
        "status": "ok" if (isinstance(res, dict) and res.get("s") == "ok") else "error",
        "response": res,
    }


@router.post("/api/fyers/exit-all", tags=["Fyers Advanced"])
@router.post("/api/fyers/panic-exit", tags=["Fyers Advanced"])
async def fyers_panic_exit_endpoint(req: Optional[dict] = None):
    """1-Click Emergency Position Square-Off across all segments or specific segment."""
    from brokers.session import get_execution_broker

    brk = get_execution_broker()
    if not brk or not hasattr(brk, "exit_all_positions"):
        return {"status": "error", "error": "Execution broker does not support bulk emergency exit"}

    segment = req.get("segment") if req else None
    res = await asyncio.to_thread(brk.exit_all_positions, segment=segment)
    resp_dict = res if isinstance(res, dict) else {}
    return {
        **resp_dict,
        "status": "ok" if (isinstance(res, dict) and res.get("s", "ok") == "ok") else "error",
        "response": res,
    }


@router.patch("/api/fyers/orders/{order_id}", tags=["Fyers Advanced"])
async def patch_fyers_order_endpoint(order_id: str, req: dict):
    """Modify an active pending order without losing queue priority."""
    from brokers.session import get_execution_broker

    brk = get_execution_broker()
    if not brk or not hasattr(brk, "modify_order"):
        return {"status": "error", "error": "Broker does not support order modification"}

    price = float(req["price"]) if "price" in req and req["price"] is not None else None
    qty = int(req["qty"]) if "qty" in req and req["qty"] is not None else None
    trigger_price = (
        float(req["trigger_price"])
        if "trigger_price" in req and req["trigger_price"] is not None
        else None
    )
    order_type = req.get("order_type")

    res = await asyncio.to_thread(
        brk.modify_order,
        order_id=order_id,
        price=price,
        qty=qty,
        trigger_price=trigger_price,
        order_type=order_type,
    )
    return {
        "status": "ok" if res.status == "OPEN" else "error",
        "order_id": res.order_id,
        "broker_status": res.status,
        "message": res.message,
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
    """Place atomic multi-leg option strategy (2L or 3L) with zero legging risk."""
    from brokers.session import get_execution_broker

    brk = get_execution_broker()
    if not brk or not hasattr(brk, "place_multileg_order"):
        return {"status": "error", "error": "Execution broker does not support multileg orders"}

    order_type = req.get("order_type", "2L")
    legs = req.get("legs", [])
    product = req.get("product", "INTRADAY")

    if not legs or len(legs) < 2:
        return {"status": "error", "error": "At least 2 legs required for multileg order"}

    res = await asyncio.to_thread(
        brk.place_multileg_order,
        order_type=order_type,
        legs=legs,
        product=product,
    )
    return {"status": "ok", "response": res}


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
    """Attach or update server-managed TP/SL bracket legs directly to an open position."""
    from brokers.session import get_execution_broker

    brk = get_execution_broker()
    if not brk or not hasattr(brk, "attach_position_legs"):
        return {
            "status": "error",
            "error": "Execution broker does not support attaching position legs",
        }

    pos_id = req.get("position_id") or req.get("positionId")
    if not pos_id:
        return {"status": "error", "error": "position_id is required"}

    res = await asyncio.to_thread(
        brk.attach_position_legs,
        position_id=pos_id,
        take_profit=req.get("take_profit") or req.get("takeProfit"),
        stop_loss=req.get("stop_loss") or req.get("stopLoss"),
        leg_type=int(req.get("leg_type", req.get("legType", 1))),
        qty=req.get("qty"),
    )
    return {
        "status": "ok" if (isinstance(res, dict) and res.get("s", "ok") == "ok") else "error",
        "response": res,
    }


@router.post("/api/fyers/positions/convert", tags=["Fyers Advanced"])
async def convert_fyers_position_endpoint(req: dict):
    """Convert an open position product type (e.g. INTRADAY to MARGIN or CNC)."""
    from brokers.session import get_execution_broker

    brk = get_execution_broker()
    if not brk or not hasattr(brk, "convert_position"):
        return {"status": "error", "error": "Execution broker does not support position conversion"}

    symbol = req.get("symbol", "")
    position_side = int(req.get("position_side", req.get("positionSide", 1)))
    convert_qty = int(req.get("convert_qty", req.get("convertQty", 1)))
    convert_from = req.get("convert_from", req.get("convertFrom", "INTRADAY"))
    convert_to = req.get("convert_to", req.get("convertTo", "MARGIN"))

    res = await asyncio.to_thread(
        brk.convert_position,
        symbol=symbol,
        position_side=position_side,
        convert_qty=convert_qty,
        convert_from=convert_from,
        convert_to=convert_to,
    )
    return {
        "status": "ok" if (isinstance(res, dict) and res.get("s", "ok") == "ok") else "error",
        "response": res,
    }


@router.post("/api/fyers/smart-orders/limit", tags=["Fyers Advanced"])
async def place_fyers_smart_limit_endpoint(req: dict):
    """Place a timed Smart Limit Order managed on Fyers servers."""
    from brokers.session import get_execution_broker

    brk = get_execution_broker()
    if not brk or not hasattr(brk, "create_smart_order_limit"):
        return {"status": "error", "error": "Execution broker does not support smart limit orders"}

    res = await asyncio.to_thread(
        brk.create_smart_order_limit,
        symbol=req.get("symbol", ""),
        qty=int(req.get("qty", 1)),
        side=int(req.get("side", 1)),
        limit_price=float(req.get("limit_price", req.get("limitPrice", 0.0))),
        product=req.get("product", "INTRADAY"),
    )
    return {
        "status": "ok" if (isinstance(res, dict) and res.get("s", "ok") == "ok") else "error",
        "response": res,
    }


@router.post("/api/fyers/smart-orders/step", tags=["Fyers Advanced"])
async def place_fyers_smart_step_endpoint(req: dict):
    """Place a ladder step accumulation order managed on Fyers servers."""
    from brokers.session import get_execution_broker

    brk = get_execution_broker()
    if not brk or not hasattr(brk, "create_smart_order_step"):
        return {"status": "error", "error": "Execution broker does not support smart step orders"}

    res = await asyncio.to_thread(
        brk.create_smart_order_step,
        symbol=req.get("symbol", ""),
        qty=int(req.get("qty", 1)),
        side=int(req.get("side", 1)),
        avg_qty=int(req.get("avg_qty", req.get("avgqty", 1))),
        avg_diff=float(req.get("avg_diff", req.get("avgdiff", 1.0))),
        direction=int(req.get("direction", 1)),
        order_type=int(req.get("order_type", req.get("orderType", 1))),
        product=req.get("product", "INTRADAY"),
    )
    return {
        "status": "ok" if (isinstance(res, dict) and res.get("s", "ok") == "ok") else "error",
        "response": res,
    }


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
    """Create a server-side Smart Exit trigger (profit protection or trailing exit)."""
    from brokers.session import get_execution_broker

    brk = get_execution_broker()
    if not brk or not hasattr(brk, "create_smartexit_trigger"):
        return {"status": "error", "error": "Execution broker does not support smart exit triggers"}

    res = await asyncio.to_thread(
        brk.create_smartexit_trigger,
        name=req.get("name", "SmartExit"),
        strategy_type=int(req.get("strategy_type", req.get("type", 2))),
        profit_rate=req.get("profit_rate", req.get("profitRate")),
        loss_rate=req.get("loss_rate", req.get("lossRate")),
    )
    return {
        "status": "ok" if (isinstance(res, dict) and res.get("s", "ok") == "ok") else "error",
        "response": res,
    }


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
async def fyers_postback_webhook_endpoint(payload: dict[str, Any]):
    """
    Webhook postback receiver for real-time Fyers order and trade status updates.
    Broadcasts state transitions to web SSE event bus and logs incoming execution data.
    """
    from web.sse import event_bus

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


# ── 2. Order Flow & Cumulative Volume Delta (CVD) Divergence ───────────────
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
        clean = sym.replace("NSE:", "").replace("BSE:", "").strip().upper()
        # Fetch spot quote
        quote_sym = f"NSE:{clean}" if clean != "SENSEX" else "BSE:SENSEX"
        q_map = get_quote([quote_sym])
        spot = float(getattr(q_map.get(quote_sym), "last_price", 0.0) or 0.0)
        # Fetch 5m intraday OHLCV
        df_5m = None
        try:
            df_5m = get_ohlcv(clean, days=5, timeframe="5m")
        except Exception:
            pass

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
