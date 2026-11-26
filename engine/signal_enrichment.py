"""
engine/signal_enrichment.py
───────────────────────────
Lightweight enrichment helpers integrating SharedFeatureBus, constituent lead-lag,
and rate-gated Fyers Multi-Order SPAN margin preflight onto F&O setups without
bloating AutoAlertEngine.
"""

from __future__ import annotations

from datetime import date, datetime
import logging
from typing import Any, Optional

logger = logging.getLogger("engine.signal_enrichment")


def _extract_expiry_date(alert: Any) -> Optional[date]:
    raw_exp = getattr(alert, "expiry", None) or getattr(alert, "expiry_date", None)
    if not raw_exp and isinstance(getattr(alert, "details", None), dict):
        raw_exp = alert.details.get("expiry") or alert.details.get("expiry_date")
    if isinstance(raw_exp, date) and not isinstance(raw_exp, datetime):
        return raw_exp
    if isinstance(raw_exp, datetime):
        return raw_exp.date()
    if isinstance(raw_exp, str) and raw_exp.strip():
        try:
            return date.fromisoformat(raw_exp.strip()[:10])
        except ValueError:
            return None
    return None


def enrich_alert_with_feature_bus(
    alert: Any,
    *,
    df_5m: Any = None,
    quotes_map: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Attach single-pass SharedFeatureBus metrics and read-only index constituent lead-lag."""
    if not isinstance(getattr(alert, "details", None), dict):
        alert.details = {}

    enriched: dict[str, Any] = {}
    sym = str(getattr(alert, "symbol", "") or "")
    if not sym:
        return enriched

    if df_5m is not None:
        try:
            from engine.feature_bus import compute_shared_features

            feats = compute_shared_features(sym, df_5m)
            if isinstance(feats, dict) and feats.get("status") == "AVAILABLE":
                alert.details["feature_bus"] = feats
                enriched["feature_bus"] = feats
        except Exception as exc_fb:
            logger.debug("[SignalEnrichment] SharedFeatureBus enrichment skipped: %s", exc_fb)

    try:
        from engine.alert_identity import canonical_alert_symbol
        from engine.feature_bus import INDEX_CONSTITUENT_WEIGHTS, compute_constituent_lead_lag

        clean = canonical_alert_symbol(sym).upper()
        if clean in INDEX_CONSTITUENT_WEIGHTS:
            lead = compute_constituent_lead_lag(clean, quotes_map=quotes_map)
            if isinstance(lead, dict) and lead.get("status") == "AVAILABLE":
                alert.details["constituent_lead_lag"] = lead
                enriched["constituent_lead_lag"] = lead
    except Exception as exc_lead:
        logger.debug("[SignalEnrichment] Constituent lead-lag skipped: %s", exc_lead)

    return enriched


def preflight_fno_setup_margin(alert: Any, *, broker: Any = None) -> dict[str, Any]:
    """Run live rate-gated multi-order margin preflight when F&O contract + auth session exist.

    Never fabricates margin estimates offline: reports UNAVAILABLE if unauthenticated.
    """
    if not isinstance(getattr(alert, "details", None), dict):
        alert.details = {}

    stage = str(getattr(alert, "stage", "") or "").upper()
    contract = str(getattr(alert, "contract_symbol", "") or "").strip()
    if stage not in ("PRIMED", "IGNITED") or not contract:
        return {"status": "SKIPPED", "reason": "NOT_STAGED_FNO_CONTRACT"}

    entry_px = float(getattr(alert, "trigger_level", 0.0) or getattr(alert, "ltp", 0.0) or 0.0)
    if entry_px <= 0:
        return {"status": "SKIPPED", "reason": "MISSING_PRICE"}

    brk = broker
    if brk is None:
        try:
            from brokers.session import get_execution_broker

            brk = get_execution_broker()
        except Exception as exc_brk:
            logger.debug("[SignalEnrichment] Execution broker lookup error: %s", exc_brk)
            brk = None

    if (
        brk is None
        or not hasattr(brk, "check_order_margin")
        or not getattr(brk, "_access_token", None)
    ):
        res = {"status": "UNAVAILABLE", "reason": "NO_AUTHENTICATED_MARGIN_BROKER"}
        alert.details["margin_preflight"] = res
        return res

    from market.instruments import get_fno_lot_size

    exp_date = _extract_expiry_date(alert)
    lot = max(
        1, int(get_fno_lot_size(str(getattr(alert, "symbol", "")), expiry_date=exp_date) or 1)
    )
    side = "SELL" if "SELL" in str(getattr(alert, "action", "") or "").upper() else "BUY"

    orders_payload: list[dict[str, Any]] = []
    plan = getattr(alert, "actionable_plan", None)
    spread_legs = plan.get("spread_legs") if isinstance(plan, dict) else None
    if isinstance(spread_legs, list) and spread_legs:
        for leg in spread_legs:
            if not isinstance(leg, dict) or not leg.get("contract_symbol"):
                continue
            orders_payload.append(
                {
                    "symbol": str(leg["contract_symbol"]),
                    "qty": int(leg.get("qty") or lot),
                    "side": str(leg.get("side") or "BUY").upper(),
                    "product_type": str(leg.get("product_type") or "MARGIN"),
                    "price": float(leg.get("price") or 0.0),
                }
            )

    if not orders_payload:
        orders_payload = [
            {
                "symbol": contract,
                "qty": lot,
                "side": side,
                "product_type": "INTRADAY",
                "price": entry_px,
            }
        ]

    try:
        res = brk.check_order_margin(orders_payload)
        if not isinstance(res, dict):
            res = {"status": "UNAVAILABLE", "reason": "INVALID_MARGIN_RESPONSE"}
    except Exception as exc_m:
        logger.debug("[SignalEnrichment] Multi-order margin check error: %s", exc_m)
        res = {"status": "DEGRADED", "reason": str(exc_m)}

    alert.details["margin_preflight"] = res
    return res
