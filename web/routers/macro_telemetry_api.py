"""
web/routers/macro_telemetry_api.py
──────────────────────────────────
Modular Macro, Dashboard, FII Flow, Telemetry, Portfolio Health, and Tax routes
extracted from web/skills.py via Strangler pattern.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import logging
import sys
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from market.ticker_stream import compute_ribbon_tickers as _compute_live_tickers_sync
from web.routers.common import skill_err as _err, skill_ok as _ok
from web.schemas import (
    DashboardSnapshotRequest,
    PortfolioHealthRequest,
    TaxEstimateRequest,
)

logger = logging.getLogger("chanakya.web.routers.macro_telemetry")
router = APIRouter(tags=["OpenClaw Skills"])

_in_flight_snapshots: dict[str, asyncio.Task] = {}
_in_flight_snapshots_lock = asyncio.Lock()


@router.get("/dashboard_snapshot")
@router.post("/dashboard_snapshot")
async def skill_dashboard_snapshot(req: Optional[DashboardSnapshotRequest] = None):
    """
    Comprehensive snapshot for the Strategic Quant Terminal:
    Includes real-time watchlist quotes, AI personas, automated SMC setup with Order Block,
    Volume Profile (POC/VAH/VAL), daily FII/DII net flows, and 1D sector rotation matrix.
    """
    try:
        sym = (req.symbol if req and req.symbol else "NIFTY").upper().strip()
        exch = (req.exchange if req and req.exchange else "NSE").upper().strip()
        tf = req.timeframe if req and req.timeframe else "15m"

        from analysis.universe import normalize_symbol_exchange

        sym, exch = normalize_symbol_exchange(sym, exch)

        cache_key = f"dashboard_snapshot_v10_{sym}_{exch}_{tf}"
        force = bool(req and getattr(req, "force_refresh", False))
        if not force:
            try:
                from engine.analysis_cache import analysis_cache

                cached = analysis_cache.get_macro(cache_key)
                if (
                    cached
                    and isinstance(cached, dict)
                    and cached.get("symbol") == sym
                    and len(cached.get("watchlist", [])) >= 20
                    and cached.get("terminal_contract_version") == 2
                    and "automated_setup" in cached
                    and cached.get("councils") is not None
                    and len(cached.get("personas", [])) >= 13
                    and (cached.get("ltp") or 0) > 0
                    and "portfolio_heat" in cached
                ):
                    return _ok(cached)
            except Exception as e_suppressed:
                logger.debug(f"[web.skills] Non-fatal exception suppressed: {e_suppressed}")

        skills_mod = sys.modules.get("web.skills")
        compute_fn = getattr(skills_mod, "_compute_dashboard_snapshot_sync", None)
        if compute_fn is None:
            from web.skills import _compute_dashboard_snapshot_sync

            compute_fn = _compute_dashboard_snapshot_sync

        async with _in_flight_snapshots_lock:
            existing_task = _in_flight_snapshots.get(cache_key)
            if existing_task is None or existing_task.done():
                existing_task = asyncio.create_task(asyncio.to_thread(compute_fn, req))
                _in_flight_snapshots[cache_key] = existing_task

        try:
            payload = await existing_task
        finally:
            async with _in_flight_snapshots_lock:
                if _in_flight_snapshots.get(cache_key) is existing_task:
                    _in_flight_snapshots.pop(cache_key, None)

        if isinstance(payload, dict) and "status" in payload and "data" in payload:
            return payload
        return _ok(payload)
    except Exception as e:
        raise _err(str(e))


@router.get("/live_tickers")
@router.post("/live_tickers")
async def skill_live_tickers():
    """Ultra-fast real-time ticker strip for Major Indian Indices, Commodities & Crypto."""
    try:
        from engine.analysis_cache import analysis_cache

        cached = analysis_cache.get_macro("live_tickers_ribbon_v1", max_age_seconds=20)
        if cached and isinstance(cached, list) and len(cached) >= 8:
            return _ok({"tickers": cached})

        skills_mod = sys.modules.get("web.skills")
        ribbon_fn = getattr(skills_mod, "_compute_live_tickers_sync", _compute_live_tickers_sync)
        tickers = await asyncio.to_thread(ribbon_fn)
        if tickers and len(tickers) >= 8:
            try:
                analysis_cache.save_macro("live_tickers_ribbon_v1", tickers, ttl_minutes=1)
            except Exception as e_suppressed:
                logger.debug(f"[web.skills] Non-fatal exception suppressed: {e_suppressed}")
        return _ok({"tickers": tickers})
    except Exception as e:
        raise _err(str(e))


class GlobalMacroRequest(BaseModel):
    nifty_spot: Optional[float] = None
    use_cache: Optional[bool] = True


def _compute_global_macro_sync(spot: Optional[float], use_cache: bool) -> dict:
    from market.global_macro import fetch_global_macro_report

    report = fetch_global_macro_report(nifty_spot=spot, use_cache=use_cache)
    return report.to_dict()


@router.get("/global_macro")
@router.post("/global_macro")
async def skill_global_macro(req: Optional[GlobalMacroRequest] = None):
    """Evaluates institutional Global Macro Correlation & Transmission Channels."""
    try:
        spot = req.nifty_spot if req else None
        use_cache = req.use_cache if req is not None and req.use_cache is not None else True
        report_dict = await asyncio.to_thread(_compute_global_macro_sync, spot, use_cache)
        return _ok(report_dict)
    except Exception as e:
        raise _err(str(e))


def _compute_market_overview_sync() -> dict:
    try:
        from engine.analysis_cache import analysis_cache

        cached = analysis_cache.get_macro("market_overview_snapshot_v2")
        if cached and isinstance(cached, dict) and cached.get("_status") == "cached_fresh":
            return cached
    except Exception as e_suppressed:
        logger.debug(f"[web.skills] Non-fatal exception suppressed: {e_suppressed}")

    result = {
        "_status": "unavailable",
        "_source_name": None,
        "_as_of": None,
        "vix": None,
        "fii_net": None,
        "dii_net": None,
        "advancers": None,
        "decliners": None,
        "unchanged": None,
        "sectors": [],
        "index_internals": None,
    }

    fetched_any = False

    try:
        from market.quotes import get_quote

        vix_quote = get_quote(["NSE:INDIA VIX"])
        if vix_quote:
            raw = list(vix_quote.values())[0]
            ltp = getattr(raw, "last_price", None) or getattr(raw, "ltp", None)
            if ltp is None and isinstance(raw, dict):
                ltp = raw.get("last_price") or raw.get("ltp")
            if ltp and float(ltp) > 0:
                result["vix"] = round(float(ltp), 2)
                fetched_any = True
    except Exception as e_suppressed:
        logger.debug(f"[web.skills] Non-fatal exception suppressed: {e_suppressed}")

    try:
        from market.sentiment import get_fii_dii_data

        flows = get_fii_dii_data(3)
        if flows and len(flows) > 0:
            latest = flows[0]
            result["fii_net"] = (
                round(float(latest.fii_net), 2)
                if hasattr(latest, "fii_net")
                else round(float(latest.get("fii_net", 0)), 2)
            )
            result["dii_net"] = (
                round(float(latest.dii_net), 2)
                if hasattr(latest, "dii_net")
                else round(float(latest.get("dii_net", 0)), 2)
            )
            fetched_any = True
    except Exception as e_suppressed:
        logger.debug(f"[web.skills] Non-fatal exception suppressed: {e_suppressed}")

    try:
        from market.sentiment import get_market_breadth

        breadth = get_market_breadth()
        if breadth:
            result["advancers"] = (
                getattr(breadth, "advances", None)
                if hasattr(breadth, "advances")
                else breadth.get("advances")
            )
            result["decliners"] = (
                getattr(breadth, "declines", None)
                if hasattr(breadth, "declines")
                else breadth.get("declines")
            )
            result["unchanged"] = (
                getattr(breadth, "unchanged", None)
                if hasattr(breadth, "unchanged")
                else breadth.get("unchanged")
            )
            fetched_any = True
    except Exception as e_suppressed:
        logger.debug(f"[web.skills] Non-fatal exception suppressed: {e_suppressed}")

    try:
        from engine.market_internals import compute_index_internals

        internals = compute_index_internals("NIFTY")
        if internals and internals.total_constituents > 0:
            if result.get("advancers") is None:
                result["advancers"] = internals.advances
                result["decliners"] = internals.declines
                result["unchanged"] = internals.unchanged
            result["index_internals"] = internals.to_dict()
            fetched_any = True
    except Exception as e_internals:
        logger.debug(f"[web.skills] Market internals enrichment note: {e_internals}")

    try:
        import concurrent.futures as _cf

        _ex = _cf.ThreadPoolExecutor(max_workers=1)
        from analysis.sector_rotation import get_sector_rrg_matrix

        try:
            _fut = _ex.submit(get_sector_rrg_matrix, use_cache=True)
            try:
                rrg = _fut.result(timeout=3.5)
            except Exception:
                rrg = []
        finally:
            _ex.shutdown(wait=False, cancel_futures=True)

        if rrg and len(rrg) > 0:
            sectors = []
            for entry in rrg:
                if isinstance(entry, dict):
                    name = entry.get("sector", "")
                    phase = entry.get("quadrant")
                    chg = entry.get("change_pct") or entry.get("momentum")
                else:
                    name = getattr(entry, "sector", "") or ""
                    phase = getattr(entry, "quadrant", None)
                    chg = getattr(entry, "change_pct", None) or getattr(entry, "momentum", None)
                if name:
                    sectors.append(
                        {
                            "name": str(name),
                            "phase": str(phase) if phase else None,
                            "change_pct": round(float(chg), 2) if chg is not None else None,
                        }
                    )
            result["sectors"] = sectors
            fetched_any = True
    except Exception as e_suppressed:
        logger.debug(f"[web.skills] Non-fatal exception suppressed: {e_suppressed}")

    if fetched_any:
        result["_status"] = "cached_fresh"
        result["_source_name"] = "NSE / SEBI Data Feed"
        result["_as_of"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
        try:
            from engine.analysis_cache import analysis_cache

            analysis_cache.save_macro("market_overview_snapshot_v2", result, ttl_minutes=15)
        except Exception as e_suppressed:
            logger.debug(f"[web.skills] Non-fatal exception suppressed: {e_suppressed}")

    return result


@router.get("/market_overview")
@router.post("/market_overview")
async def skill_market_overview():
    """P0-A: Market overview snapshot — India VIX, FII/DII flows, sector RRG."""
    try:
        data = await asyncio.to_thread(_compute_market_overview_sync)
        return _ok(data)
    except Exception as e:
        raise _err(str(e))


@router.post("/tax/calculate")
async def skill_tax_calculate(req: TaxEstimateRequest):
    """P0-A Alias: /skills/tax/calculate -> /skills/tax/estimate."""
    try:
        from engine.charges import calculate_capital_gains_tax

        estimate = calculate_capital_gains_tax(
            gross_pnl=req.gross_pnl,
            holding_period_days=req.holding_period_days,
            segment=req.segment,
            prior_accumulated_ltcg=req.prior_accumulated_ltcg,
        )
        return _ok(estimate)
    except Exception as e:
        raise _err(str(e))


@router.get("/fii_flow")
@router.post("/fii_flow")
async def skill_fii_flow():
    """FII/DII institutional flow intelligence."""
    try:
        from market.flow_intel import get_flow_analysis
        from market.sentiment import get_fii_dii_data

        flow = get_flow_analysis()
        raw = get_fii_dii_data(days=5)

        recent_days = [
            {
                "date": d.date,
                "fii_net": round(d.fii_net, 2),
                "dii_net": round(d.dii_net, 2),
                "verdict": d.verdict,
            }
            for d in raw[:5]
        ]

        return _ok(
            {
                "fii_net_today": round(flow.fii_net_today, 2),
                "dii_net_today": round(flow.dii_net_today, 2),
                "fii_streak": flow.fii_streak,
                "dii_streak": flow.dii_streak,
                "fii_5d_net": round(flow.fii_5d_net, 2),
                "dii_5d_net": round(flow.dii_5d_net, 2),
                "fii_streak_total": round(flow.fii_streak_total, 2),
                "divergence": flow.divergence,
                "divergence_type": flow.divergence_type,
                "fii_momentum": flow.fii_momentum,
                "signal": flow.signal,
                "signal_reason": flow.signal_reason,
                "confidence": flow.confidence,
                "recent_days": recent_days,
            }
        )
    except Exception as e:
        raise _err(str(e))


@router.get("/telemetry/summary")
@router.post("/telemetry/summary")
async def skill_telemetry_summary():
    """Return institutional telemetry summary with failure patterns & self-learning recommendations."""
    try:
        from engine.telemetry import get_telemetry_summary

        return _ok(get_telemetry_summary())
    except Exception as e:
        raise _err(str(e))


class TelemetryEventsRequest(BaseModel):
    limit: int = 50
    event_type: Optional[str] = None
    severity: Optional[str] = None


@router.get("/telemetry/events")
@router.post("/telemetry/events")
async def skill_telemetry_events(req: Optional[TelemetryEventsRequest] = None):
    """Return filtered telemetry events (failovers, fallbacks, exceptions)."""
    try:
        from engine.telemetry import get_recent_events

        limit = req.limit if req else 50
        event_type = req.event_type if req else None
        severity = req.severity if req else None
        return _ok(
            {"events": get_recent_events(limit=limit, event_type=event_type, severity=severity)}
        )
    except Exception as e:
        raise _err(str(e))


@router.post("/telemetry/clear")
async def skill_telemetry_clear():
    """Clear telemetry logs."""
    try:
        from engine.telemetry import clear_telemetry

        clear_telemetry()
        return _ok({"cleared": True})
    except Exception as e:
        raise _err(str(e))


@router.post("/portfolio/health")
@router.get("/portfolio/health")
async def skill_portfolio_health(req: Optional[PortfolioHealthRequest] = None):
    """Audit retail portfolio health, concentration risk (HHI), and wealth allocation pyramid."""
    try:
        from engine.portfolio import audit_portfolio_health

        audit = audit_portfolio_health()
        return _ok(audit.to_dict())
    except RuntimeError as e:
        return _ok({"_status": "UNAVAILABLE", "reason": str(e), "actionable": False})
    except Exception as e:
        raise _err(str(e))


@router.post("/tax/estimate")
async def skill_tax_estimate(req: TaxEstimateRequest):
    """Estimate post-budget capital gains tax, STCG 20%, LTCG 12.5% u/s 112A, or F&O business income."""
    try:
        from engine.charges import calculate_capital_gains_tax

        estimate = calculate_capital_gains_tax(
            gross_pnl=req.gross_pnl,
            holding_period_days=req.holding_period_days,
            segment=req.segment,  # type: ignore
            prior_accumulated_ltcg=req.prior_accumulated_ltcg,
        )
        return _ok(estimate.to_dict())
    except Exception as e:
        raise _err(str(e))


@router.post("/tax/harvesting")
@router.get("/tax/harvesting")
async def skill_tax_harvesting():
    """Identify tax-loss harvesting candidates across retail holdings to offset STCG."""
    try:
        from engine.charges import suggest_tax_loss_harvesting
        from engine.portfolio import get_portfolio_summary

        summary = get_portfolio_summary()
        holdings_dicts = [
            {"symbol": h.symbol, "qty": h.qty, "ltp": h.ltp, "pnl": h.pnl, "days_held": 90}
            for h in summary.holdings
        ]
        suggestions = suggest_tax_loss_harvesting(holdings_dicts)
        return _ok({"tax_loss_harvest_opportunities": suggestions})
    except RuntimeError as e:
        return _ok({"_status": "UNAVAILABLE", "reason": str(e), "actionable": False})
    except Exception as e:
        raise _err(str(e))
