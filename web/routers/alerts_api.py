"""
web/routers/alerts_api.py
─────────────────────────
Dedicated router for Auto-Alerts, Manual Alerts, Audit Trail, and Telegram dispatch.
All synchronous engine and file operations are offloaded via asyncio.to_thread.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

logger = logging.getLogger("chanakya.web.routers.alerts")
router = APIRouter(tags=["Alerts"])


@router.get("/api/alerts/auto")
async def get_auto_alerts(
    limit: int = 300,
    alert_type: Optional[str] = None,
    stage: Optional[str] = None,
    environment: Optional[str] = None,
    is_invalidated: Optional[bool] = None,
    target_status: Optional[str] = None,
    view_mode: str = "ACTIVE",  # "ACTIVE" | "ARCHIVED" | "ALL"
    is_archived: Optional[bool] = None,
    horizon: Optional[str] = None,
    segment: Optional[str] = None,
):
    """
    Get real-time auto-detected alerts with active/archived partitioning and horizon differentiation.
    Offloaded to thread pool to prevent event loop blocking.
    """
    from engine.auto_alert_engine import auto_alert_engine

    alerts = await asyncio.to_thread(
        auto_alert_engine.get_alerts,
        limit=limit,
        alert_type=alert_type,
        stage=stage,
        environment=environment,
        is_invalidated=is_invalidated,
        target_status=target_status,
        view_mode=view_mode,
        is_archived=is_archived,
        horizon=horizon,
        segment=segment,
    )
    return {"status": "ok", "data": [a.to_dict() for a in alerts]}


@router.post("/api/alerts/auto/archive")
async def archive_auto_alert(payload: dict):
    """Archive or restore an alert by ID."""
    from engine.auto_alert_engine import auto_alert_engine

    alert_id = payload.get("alert_id")
    archive = payload.get("archive", True)
    reason = payload.get("reason")
    if not alert_id:
        raise HTTPException(status_code=400, detail="Missing alert_id")

    alert = await asyncio.to_thread(
        auto_alert_engine.archive_alert_by_id, alert_id, archive=archive, reason=reason
    )
    if not alert:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")

    try:
        from web.sse import event_bus

        await event_bus.broadcast(
            {
                "type": "auto_alert_archived",
                "alert_id": alert_id,
                "is_archived": archive,
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
    except Exception:
        pass
    return {"status": "ok", "data": alert.to_dict()}


@router.post("/api/alerts/auto/cleanup")
async def cleanup_auto_alerts(payload: Optional[dict] = None):
    """Cleanup archived alerts older than max_age_days (default 3 days)."""
    from engine.auto_alert_engine import auto_alert_engine

    days = payload.get("max_age_days", 3) if payload else 3
    purged = await asyncio.to_thread(auto_alert_engine.cleanup_archived_records, max_age_days=days)
    surviving = await asyncio.to_thread(auto_alert_engine.get_alerts, limit=500)
    return {
        "status": "ok",
        "data": {
            "purged_count": purged,
            "remaining_count": len(surviving),
            "max_age_days": days,
        },
    }


@router.post("/api/alerts/auto/invalidate")
async def invalidate_auto_alert_endpoint(payload: dict):
    """Explicitly invalidate an auto alert with a specific rationale."""
    from engine.auto_alert_engine import auto_alert_engine

    alert_id = payload.get("alert_id")
    reason = payload.get("reason", "Manually invalidated by user")
    if not alert_id:
        raise HTTPException(status_code=400, detail="Missing alert_id")

    alert = await asyncio.to_thread(auto_alert_engine.invalidate_alert_by_id, alert_id, reason=reason)
    if not alert:
        raise HTTPException(
            status_code=404, detail=f"Alert {alert_id} not found or already invalidated"
        )
    return {"status": "ok", "data": alert.to_dict()}


@router.post("/api/alerts/manual/invalidate")
async def invalidate_manual_alert_endpoint(payload: dict):
    """Explicitly invalidate a manual alert with a specific rationale."""
    from engine.alerts import alert_manager

    alert_id = payload.get("alert_id")
    reason = payload.get("reason", "Manually invalidated by user")
    if not alert_id:
        raise HTTPException(status_code=400, detail="Missing alert_id")

    alert = await asyncio.to_thread(alert_manager.invalidate_alert, alert_id, reason=reason)
    if not alert:
        raise HTTPException(
            status_code=404, detail=f"Manual alert {alert_id} not found or already invalidated"
        )
    return {"status": "ok", "data": alert_manager.public_dict(alert)}


@router.post("/api/alerts/auto/rescrutinize")
async def rescrutinize_auto_alert(payload: dict):
    """Re-scrutinize an active alert on demand with AI Chief Risk Officer Devil's Advocate."""
    from engine.auto_alert_engine import auto_alert_engine
    from engine.alert_scrutiny import alert_scrutiny_auditor

    alert_id = payload.get("alert_id")
    if not alert_id:
        raise HTTPException(status_code=400, detail="Missing alert_id")

    alerts = await asyncio.to_thread(auto_alert_engine.get_alerts, limit=200, view_mode="ALL")
    target = next((a for a in alerts if a.alert_id == alert_id), None)
    if not target:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")

    scrutiny = await asyncio.to_thread(alert_scrutiny_auditor.scrutinize_alert, target, timeout=3.5)
    if not isinstance(target.metrics, dict):
        target.metrics = {}
    target.metrics["scrutiny"] = scrutiny.to_dict()
    target.confidence = max(target.confidence, scrutiny.score)
    await asyncio.to_thread(auto_alert_engine._save)
    return {"status": "ok", "data": target.to_dict(), "scrutiny": scrutiny.to_dict()}


@router.post("/api/alerts/auto/scan-multibaggers")
async def trigger_multibagger_scan_api(top_n: int = 10, min_conviction: int = 65):
    """
    Triggers an institutional compounder & multibagger breakout scan across 40+ growth leaders.
    Evaluates Minervini 8-point Trend Template, Stan Weinstein Stage 2 markup, and float absorption.
    """
    from engine.auto_alert_engine import auto_alert_engine

    fresh = await asyncio.to_thread(
        auto_alert_engine.scan_multibagger_compounders,
        top_n=top_n,
        min_conviction=min_conviction,
    )
    return {
        "status": "ok",
        "count": len(fresh),
        "data": [a.to_dict() for a in fresh],
    }


@router.get("/api/alerts/auto/audit-trail")
async def get_alerts_audit_trail_api(
    alert_id: Optional[str] = None,
    symbol: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 50,
):
    """
    Query chronological audit trail events across one or all active/archived alerts.
    Enables rapid operational troubleshooting and end-to-end delivery traceability.
    """
    from engine.auto_alert_engine import auto_alert_engine

    events = await asyncio.to_thread(
        auto_alert_engine.get_audit_trail,
        alert_id=alert_id,
        symbol=symbol,
        event_type=event_type,
        limit=min(limit, 200),
    )
    return {"status": "ok", "count": len(events), "data": events}


@router.get("/api/alerts/auto/{alert_id}/audit")
async def get_alert_audit_detail_api(alert_id: str):
    """
    Get complete audit lifecycle trail and delivery diagnostics for a specific alert.
    """
    from engine.auto_alert_engine import auto_alert_engine

    alert = await asyncio.to_thread(auto_alert_engine.get_alert_by_id, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")

    return {
        "status": "ok",
        "data": {
            "alert_id": alert.alert_id,
            "trace_id": alert.trace_id,
            "symbol": alert.symbol,
            "exchange": alert.exchange,
            "stage": alert.stage,
            "created_at": alert.created_at,
            "current_status": {
                "ltp": alert.ltp,
                "is_active": alert.is_active,
                "is_invalidated": alert.is_invalidated,
                "is_archived": alert.is_archived,
                "telegram_dispatched": alert.telegram_dispatched,
                "telegram_suppression_reason": alert.telegram_suppression_reason,
                "achieved_milestones": alert.achieved_milestones or [],
            },
            "audit_trail": getattr(alert, "audit_trail", []) or [],
        },
    }


@router.get("/api/alerts/auto/telegram-destinations")
async def get_telegram_destinations_api():
    """
    Get available Telegram destinations (default private chat ID, channel ID if configured).
    """
    from bot.telegram_bot import get_telegram_destinations

    dests = await asyncio.to_thread(get_telegram_destinations)
    return {"status": "ok", "data": dests}


@router.get("/api/alerts/preferences")
async def get_alert_preferences_api():
    """
    Get active alert routing and segment subscription matrix.
    """
    from engine.alert_preferences import alert_preferences

    prefs = await asyncio.to_thread(alert_preferences.get_preferences)
    return {"status": "ok", "data": prefs}


@router.post("/api/alerts/preferences")
async def update_alert_preferences_api(payload: dict):
    """
    Update alert routing and segment subscription matrix. Emits SSE broadcast.
    """
    from engine.alert_preferences import alert_preferences

    updated = await asyncio.to_thread(alert_preferences.update_preferences, payload)

    # Emit SSE broadcast
    try:
        from web.sse import event_bus

        event_bus.publish_sync(
            "system",
            {
                "type": "alert_preferences_updated",
                "preferences": updated,
            },
        )
    except Exception:
        pass

    return {"status": "ok", "data": updated}


@router.post("/api/alerts/auto/send-telegram")
async def send_alert_to_telegram(payload: dict):
    """
    Dispatch a specific alert to the configured Telegram chat, group, or channel.
    Runs the canonical render_auto_alert() template and sends via send_push().
    """
    from engine.auto_alert_engine import auto_alert_engine
    from bot.alert_templates import render_auto_alert
    from market.calendar import is_market_open

    alert_id = payload.get("alert_id")
    chat_id = payload.get("chat_id")
    if chat_id is not None and isinstance(chat_id, str):
        chat_id = chat_id.strip() or None
    if not alert_id:
        raise HTTPException(status_code=400, detail="Missing alert_id")

    alerts = await asyncio.to_thread(auto_alert_engine.get_alerts, limit=500, view_mode="ALL")
    target = next((a for a in alerts if a.alert_id == alert_id), None)
    if not target:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")

    now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    in_market = is_market_open("NSE", ref_dt=now)

    try:
        rendered_msg = render_auto_alert(target, in_market=in_market)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render alert message: {e}")

    is_milestone = bool(
        getattr(target, "is_milestone", False)
        or getattr(target, "is_invalidated", False)
        or getattr(target, "stage", "") in (
            "TARGET_ACHIEVED", "COMPLETED", "T0_5_ACHIEVED", "T1_ACHIEVED", "T2_ACHIEVED",
            "RUNNER_EXIT", "PROFIT_SECURED", "BREAKEVEN_EXIT", "TRAILING_UPDATE", "INVALIDATED"
        )
    )
    reply_to = getattr(target, "telegram_root_message_id", None) if is_milestone else None

    try:
        from bot.telegram_bot import send_push

        try:
            await asyncio.to_thread(
                send_push,
                rendered_msg,
                parse_mode="HTML",
                bypass_dedup=True,
                chat_id=chat_id,
                reply_to_message_id=reply_to,
                signal_id=getattr(target, "signal_ref", None),
                alert_id=getattr(target, "alert_id", None),
                is_update=is_milestone,
            )
        except TypeError:
            await asyncio.to_thread(
                send_push,
                rendered_msg,
                parse_mode="HTML",
                bypass_dedup=True,
                chat_id=chat_id,
            )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Telegram send failed: {e}")

    # Mark alert as dispatched to Telegram and record audit trail
    try:
        target.telegram_dispatched = True
        target.telegram_suppression_reason = None
        if not isinstance(getattr(target, "dispatched_channels", None), list):
            target.dispatched_channels = []
        if "telegram" not in target.dispatched_channels:
            target.dispatched_channels.append("telegram")
        if hasattr(target, "record_audit"):
            target.record_audit(
                "TELEGRAM_SENT",
                f"Manually dispatched to Telegram channel via UI (confidence: {target.confidence}%)",
                actor="MANUAL_UI",
                details={
                    "confidence": target.confidence,
                    "stage": target.stage,
                    "chat_id": chat_id or "DEFAULT_CHAT",
                },
            )
        await asyncio.to_thread(auto_alert_engine._save)
    except Exception as e_audit:
        logger.debug(f"[API] Failed to record manual Telegram dispatch state: {e_audit}")

    preview = rendered_msg[:800] if len(rendered_msg) > 800 else rendered_msg
    return {
        "status": "ok",
        "alert_id": alert_id,
        "chat_id": chat_id or "DEFAULT_CHAT",
        "message_preview": preview,
        "in_market": in_market,
        "sent_at": now.strftime("%Y-%m-%d %H:%M:%S IST"),
    }
