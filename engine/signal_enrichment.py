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

    # Ensure prev_close telemetry is populated from quotes_map or df_5m when absent
    metrics = getattr(alert, "metrics", None)
    if not isinstance(metrics, dict):
        metrics = {}
        alert.metrics = metrics

    if not metrics.get("prev_close"):
        resolved_pc = 0.0
        if isinstance(quotes_map, dict):
            from engine.alert_identity import canonical_alert_symbol

            c_sym = canonical_alert_symbol(sym).upper()
            q_candidates = (
                quotes_map.get(sym),
                quotes_map.get(c_sym),
                quotes_map.get(f"NSE:{c_sym}"),
                quotes_map.get(f"BSE:{c_sym}"),
                quotes_map.get(f"NSE:{c_sym}-INDEX"),
                quotes_map.get(f"BSE:{c_sym}-INDEX"),
            )
            for q_obj in q_candidates:
                if q_obj is None:
                    continue
                pc_raw = (
                    q_obj.get("prev_close") or q_obj.get("previous_close")
                    if isinstance(q_obj, dict)
                    else getattr(q_obj, "prev_close", None)
                )
                if pc_raw and float(pc_raw) > 0:
                    resolved_pc = float(pc_raw)
                    break
        if resolved_pc <= 0 and df_5m is not None and len(df_5m) >= 2 and "Close" in df_5m.columns:
            try:
                dates = df_5m.index.normalize() if hasattr(df_5m.index, "normalize") else None
                if dates is not None and len(dates.unique()) >= 2:
                    prev_day = dates.unique()[-2]
                    prev_closes = df_5m.loc[dates == prev_day, "Close"].dropna()
                    if len(prev_closes) > 0 and float(prev_closes.iloc[-1]) > 0:
                        resolved_pc = float(prev_closes.iloc[-1])
            except Exception as e_pc:
                logger.debug(
                    f"[engine.signal_enrichment] Prev close fallback lookup failed: {e_pc}"
                )
        if resolved_pc > 0:
            metrics["prev_close"] = round(resolved_pc, 2)
            enriched["prev_close"] = metrics["prev_close"]

    # Zero-REST 6-Factor Confluence Score enrichment from already-resolved alert metrics
    try:
        direction = str(getattr(alert, "direction", "") or "").upper()
        if direction in ("BULLISH", "BEARISH", "BUY", "SELL", "LONG", "SHORT"):
            from engine.confluence_engine import evaluate_confluence

            is_opt_enr = bool(
                getattr(alert, "contract_symbol", None)
                or getattr(alert, "strike", None)
                or getattr(alert, "option_type", None)
            )
            spot_cand = (
                getattr(alert, "underlying_spot", None)
                or metrics.get("underlying_spot")
                or metrics.get("spot")
                or (None if is_opt_enr else getattr(alert, "ltp", None))
            )
            spot_val = float(spot_cand or 0.0)
            if spot_val > 0:
                fb_dict = enriched.get("feature_bus") or {}
                vwap_val = (
                    getattr(alert, "vwap", None)
                    or metrics.get("vwap")
                    or metrics.get("underlying_vwap")
                    or (fb_dict.get("vwap") if isinstance(fb_dict, dict) else None)
                )
                rvol_val = (
                    getattr(alert, "effective_rvol", None)
                    or metrics.get("rvol")
                    or metrics.get("spot_rvol")
                    or metrics.get("rvol_ratio")
                    or metrics.get("volume_surge")
                    or (fb_dict.get("tod_rvol") if isinstance(fb_dict, dict) else None)
                    or (fb_dict.get("vol_ratio") if isinstance(fb_dict, dict) else None)
                )
                prev_close = metrics.get("prev_close")
                chg_pct = metrics.get("spot_change_pct") or metrics.get("change_pct")
                if chg_pct is None and prev_close and float(prev_close) > 0:
                    chg_pct = (spot_val - float(prev_close)) / float(prev_close) * 100.0
                    metrics["spot_change_pct"] = round(chg_pct, 2)

                # Backfill structural_spot_sl on option setups if missing at enrichment time
                if (
                    is_opt_enr
                    and getattr(alert, "structural_spot_sl", None) is None
                    and str(getattr(alert, "alert_type", "") or "").upper()
                    != "DEFINED_RISK_NEUTRAL"
                ):
                    atr_fb = float(
                        metrics.get("atr_5m") or metrics.get("atr_15m") or metrics.get("atr") or 0.0
                    )
                    fb_features = enriched.get("feature_bus") or {}
                    if atr_fb <= 0 and isinstance(fb_features, dict):
                        atr_fb = float(fb_features.get("atr_14") or 0.0)
                    spot_dist = (
                        max(spot_val * 0.0035, min(spot_val * 0.012, atr_fb * 1.5))
                        if 0 < atr_fb < spot_val * 0.03
                        else spot_val * 0.0055
                    )
                    op_e = str(getattr(alert, "option_type", "") or "").upper()
                    is_bear_s = (op_e == "PE") or (
                        op_e != "CE" and direction in ("BEARISH", "SHORT", "SELL")
                    )
                    s_sl = (
                        round(spot_val + spot_dist, 2)
                        if is_bear_s
                        else round(spot_val - spot_dist, 2)
                    )
                    alert.structural_spot_sl = s_sl
                    if getattr(alert, "underlying_sl", None) is None:
                        alert.underlying_sl = s_sl
                    enriched["structural_spot_sl"] = s_sl
                oi_sig = getattr(alert, "order_flow_signals", None)
                oi_sig = oi_sig if isinstance(oi_sig, dict) else {}
                pre_open_gap = (
                    metrics.get("pre_open_gap_pct")
                    or alert.details.get("pre_open_gap_pct")
                    or getattr(alert, "gap_pct", None)
                )
                call_oi_chg = (
                    metrics.get("call_oi_change_pct")
                    or alert.details.get("call_oi_change_pct")
                    or oi_sig.get("call_oi_change_pct")
                )
                put_oi_chg = (
                    metrics.get("put_oi_change_pct")
                    or alert.details.get("put_oi_change_pct")
                    or oi_sig.get("put_oi_change_pct")
                )
                ms_sig = (
                    metrics.get("market_structure_signal")
                    or alert.details.get("market_structure_signal")
                    or getattr(alert, "setup_archetype", None)
                )
                if not ms_sig:
                    _atype_u = str(getattr(alert, "alert_type", "") or "").upper()
                    _archetype_ms = {
                        "LIQUIDITY_INVERSION": "LIQUIDITY_INVERSION",
                        "SMT_SWEEP": "LIQUIDITY_INVERSION",
                        "TURTLE_SOUP": "LIQUIDITY_INVERSION",
                        "SMC_ORDERBLOCK_RETEST": "ORDER_BLOCK_RETEST",
                        "BREAKOUT_RETEST": "BOS",
                        "OPTIONS_MOMENTUM": "BOS",
                        "GAMMA_BLAST": "BOS",
                        "INTRADAY_BREAKOUT_SPARK": "BOS",
                        "INTRADAY_BREAKDOWN_SPARK": "BOS",
                        "STRAT_2_1_2_BULLISH": "BOS",
                        "STRAT_2_1_2_BEARISH": "BOS",
                        "INDEX_MICRO_SCALP": "BOS",
                    }
                    ms_sig = _archetype_ms.get(_atype_u)

                sec_quad = metrics.get("rrg_quadrant") or metrics.get("sector_quadrant")
                if not sec_quad:
                    try:
                        from analysis.sector_rotation import get_stock_tailwind

                        tw_sec = get_stock_tailwind(sym)
                        sec_quad = getattr(tw_sec, "quadrant", None) if tw_sec else None
                    except Exception:
                        sec_quad = None

                c_rep = evaluate_confluence(
                    symbol=sym,
                    direction=direction,
                    ltp=spot_val,
                    vwap=float(vwap_val) if vwap_val else None,
                    rvol=float(rvol_val) if rvol_val else None,
                    change_pct=float(chg_pct) if chg_pct is not None else None,
                    pre_open_gap_pct=float(pre_open_gap) if pre_open_gap is not None else None,
                    sector_quadrant=sec_quad,
                    call_oi_change_pct=float(call_oi_chg) if call_oi_chg is not None else None,
                    put_oi_change_pct=float(put_oi_chg) if put_oi_chg is not None else None,
                    market_structure_signal=str(ms_sig) if ms_sig else None,
                    day_high=float(metrics["day_high"]) if metrics.get("day_high") else None,
                    day_low=float(metrics["day_low"]) if metrics.get("day_low") else None,
                    atr_5m=float(metrics["atr_5m"]) if metrics.get("atr_5m") else None,
                )
                metrics["confluence_score"] = round(c_rep.total_score, 1)
                metrics["confluence_qualified"] = c_rep.is_qualified
                alert.details["confluence_report"] = {
                    "score": round(c_rep.total_score, 1),
                    "qualified": c_rep.is_qualified,
                    "factors": [
                        {"name": f.name, "score": f.score, "status": f.status}
                        for f in c_rep.factors
                    ],
                }
                if not getattr(alert, "confluence_alignment", None):
                    alert.confluence_alignment = (
                        "HIGH_CONFLUENCE" if c_rep.is_qualified else "PARTIAL_CONFLUENCE"
                    )
                enriched["confluence_score"] = round(c_rep.total_score, 1)
    except Exception as exc_conf:
        logger.debug("[SignalEnrichment] Confluence enrichment skipped: %s", exc_conf)

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
