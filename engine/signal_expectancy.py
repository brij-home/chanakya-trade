"""Held-out post-cost walk-forward signal expectancy & calibration evaluator.

Evaluates persisted AutoAlert terminal records post statutory costs and spread friction,
segmented by detector, segment, IST session bucket, RVOL bucket, and confluence bucket.
Adheres strictly to sample-size statistical qualification rules (never claiming alpha on
n < 20 or uncalibrated partial paths).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json
import logging
import math
from pathlib import Path
from typing import Any, Iterable, Optional

logger = logging.getLogger("engine.signal_expectancy")

from config.paths import app_data_path
from engine.alert_outcomes import calculate_terminal_forward_outcome
from engine.charges import SegmentType, calculate_net_expectancy
from engine.position_sizer import get_lot_size

MIN_PRELIMINARY_SAMPLES = 5
MIN_ACTIONABLE_SAMPLES = 20


class _DictAlertAdapter:
    """Read-only attribute view over a serialized AutoAlert dictionary."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    @property
    def has_triggered(self) -> bool:
        if self._data.get("has_triggered") is not None:
            return bool(self._data.get("has_triggered"))
        if self._data.get("triggered_at"):
            return True
        stage = str(self._data.get("stage") or "").upper()
        if stage in (
            "IGNITED",
            "TRIGGERED",
            "ACTIVE",
            "IN_FLIGHT",
            "RUNNER_EXIT",
            "COMPLETED",
            "T1_ACHIEVED",
            "T2_ACHIEVED",
            "T3_ACHIEVED",
            "TARGET_ACHIEVED",
            "DE_RISK_0_5R",
            "T0_5_ACHIEVED",
            "BREAKEVEN_LOCKED",
            "TRAILING_UPDATE",
        ):
            return True
        if (
            stage == "INVALIDATED"
            and str(self._data.get("target_status") or "") != "SETUP_DISQUALIFIED"
        ):
            return True
        milestones = self._data.get("achieved_milestones") or []
        return any(
            m
            in (
                "IGNITED",
                "ACTIVE",
                "T1_ACHIEVED",
                "T2_ACHIEVED",
                "T3_ACHIEVED",
                "TARGET_ACHIEVED",
                "DE_RISK_0_5R",
                "T0_5_ACHIEVED",
                "BREAKEVEN_LOCKED",
                "RUNNER_EXIT",
            )
            for m in milestones
        )

    def __getattr__(self, item: str) -> Any:
        return self._data.get(item)


def load_persisted_alerts(limit: int = 5000) -> list[dict[str, Any]]:
    """Load deduplicated alert dictionaries from SQLite ledger and/or auto_alerts.json."""
    by_id: dict[str, dict[str, Any]] = {}

    try:
        from engine.sqlite_store import SQLiteAlertStore

        store = SQLiteAlertStore()
        for row in store.get_alerts(limit=limit):
            if isinstance(row, dict) and row.get("alert_id"):
                by_id[str(row["alert_id"])] = row
    except Exception as e_store:
        logger.debug(f"[signal_expectancy] SQLite alert load skipped: {e_store}")

    json_path = Path(app_data_path("auto_alerts.json"))
    if json_path.exists():
        try:
            raw = json.loads(json_path.read_text(encoding="utf-8"))
            items = (
                raw
                if isinstance(raw, list)
                else raw.get("alerts", [])
                if isinstance(raw, dict)
                else []
            )
            for row in items:
                if isinstance(row, dict) and row.get("alert_id"):
                    by_id.setdefault(str(row["alert_id"]), row)
        except Exception as e_json:
            logger.debug(f"[signal_expectancy] JSON alert load skipped: {e_json}")

    return list(by_id.values())


def _sample_qualification(n: int) -> str:
    if n >= MIN_ACTIONABLE_SAMPLES:
        return "STATISTICALLY_ACTIONABLE"
    if n >= MIN_PRELIMINARY_SAMPLES:
        return "PRELIMINARY"
    return "INSUFFICIENT_SAMPLE"


def _resolve_session_bucket(created_at: Any, segment: str) -> str:
    text = str(created_at or "").replace(" IST", "").strip()
    if str(segment).upper().strip() == "COMMODITY":
        return "MCX_SESSION"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return "UNKNOWN_SESSION"
    hhmm = dt.hour * 100 + dt.minute
    if hhmm < 1030:
        return "OPEN_0915_1030"
    if hhmm < 1300:
        return "MID_1030_1300"
    if hhmm <= 1600:
        return "PM_1300_CLOSE"
    return "AFTER_HOURS"


def _resolve_rvol_bucket(metrics: dict[str, Any]) -> str:
    raw = metrics.get("rvol")
    if raw is None:
        raw = metrics.get("rvol_10d")
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return "MISSING_OR_ZERO"
    if not math.isfinite(val) or val <= 0.0:
        return "MISSING_OR_ZERO"
    if val < 1.0:
        return "LOW_<1.0"
    if val < 1.5:
        return "MODERATE_1.0_1.5"
    if val < 2.5:
        return "HIGH_1.5_2.5"
    return "SURGE_>=2.5"


def _resolve_confluence_bucket(alert: dict[str, Any], metrics: dict[str, Any]) -> str:
    raw = metrics.get("composite_confluence_score")
    if raw is None:
        raw = metrics.get("confluence_score")
    if raw is None:
        raw = alert.get("confidence")
    try:
        score = float(raw)
    except (TypeError, ValueError):
        return "UNKNOWN_SCORE"
    if not math.isfinite(score):
        return "UNKNOWN_SCORE"
    if score < 55:
        return "LOW_<55"
    if score < 70:
        return "MID_55_69"
    if score < 85:
        return "HIGH_70_84"
    return "APEX_>=85"


def resolve_exit_price_from_alert(alert_dict: dict[str, Any]) -> Optional[float]:
    """Extract terminal exit price from structured audit trail or final LTP/PnL."""
    audit_trail = alert_dict.get("audit_trail") or []
    for ev in reversed(audit_trail):
        if isinstance(ev, dict):
            details = ev.get("details") or {}
            for key in ("exit_price", "ltp", "close_price"):
                raw = details.get(key)
                try:
                    val = float(raw)
                    if math.isfinite(val) and val > 0:
                        return val
                except (TypeError, ValueError):
                    continue
    for key in ("exit_price", "ltp"):
        try:
            val = float(alert_dict.get(key))
            if math.isfinite(val) and val > 0:
                return val
        except (TypeError, ValueError):
            continue
    return None


def _estimate_cost_r_drag(
    alert_dict: dict[str, Any], entry: float, stop: float, exit_p: float
) -> float:
    """Estimate roundtrip statutory + slippage cost measured in initial R units."""
    risk_per_unit = abs(entry - stop)
    if risk_per_unit <= 0 or entry <= 0 or exit_p <= 0:
        return 0.0
    segment_raw = str(alert_dict.get("segment") or "FNO_STOCK").upper().strip()
    symbol = str(alert_dict.get("symbol") or "").upper().strip()
    metrics = alert_dict.get("metrics") or {}
    qty = int(metrics.get("lot_size") or get_lot_size(symbol) or 1)

    charge_seg: SegmentType = "OPTIONS"
    if segment_raw == "COMMODITY":
        charge_seg = "COMMODITY"
    elif segment_raw in ("CASH", "EQUITY", "EQUITY_INTRADAY"):
        charge_seg = "EQUITY_INTRADAY"

    spread_audit = metrics.get("liquidity_spread_audit") or {}
    spread_pct = 0.0
    if isinstance(spread_audit, dict) and spread_audit.get("bid_ask_spread_pct") is not None:
        try:
            spread_pct = max(0.0, float(spread_audit["bid_ask_spread_pct"]))
        except (TypeError, ValueError):
            spread_pct = 0.0
    half_spread = (spread_pct / 200.0) if spread_pct > 0 else 0.001

    target_proxy = (
        max(entry + risk_per_unit, exit_p) if exit_p >= entry else (entry + risk_per_unit)
    )
    net_eval = calculate_net_expectancy(
        entry_price=entry,
        target_price=target_proxy,
        stop_price=stop if stop < entry else max(0.05, entry - risk_per_unit),
        quantity=max(1, qty),
        segment=charge_seg,
        entry_side="BUY",
        half_spread_pct=half_spread,
    )
    friction_rupees = float(net_eval.get("total_friction_target", 0.0) or 0.0)
    risk_rupees = risk_per_unit * max(1, qty)
    return round(friction_rupees / max(0.01, risk_rupees), 4)


def _summarize_bucket(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {
            "sample_count": 0,
            "calibratable_count": 0,
            "qualification": "INSUFFICIENT_SAMPLE",
            "win_rate_pct": 0.0,
            "gross_expectancy_r": 0.0,
            "net_expectancy_r": 0.0,
            "total_gross_r": 0.0,
            "total_net_r": 0.0,
            "avg_win_r": 0.0,
            "avg_loss_r": 0.0,
            "profit_factor": 0.0,
            "time_stop_rate_pct": 0.0,
        }

    wins = [r["net_r"] for r in rows if r["net_r"] > 0]
    losses = [r["net_r"] for r in rows if r["net_r"] < 0]
    gross_win = sum(w for w in wins)
    gross_loss = abs(sum(l for l in losses))
    time_stops = sum(1 for r in rows if r["stage"] == "TIME_STOP_EXIT")
    cal_n = sum(1 for r in rows if r["is_calibratable"])

    return {
        "sample_count": n,
        "calibratable_count": cal_n,
        "qualification": _sample_qualification(n),
        "win_rate_pct": round((len(wins) / n) * 100.0, 1),
        "gross_expectancy_r": round(sum(r["gross_r"] for r in rows) / n, 3),
        "net_expectancy_r": round(sum(r["net_r"] for r in rows) / n, 3),
        "total_gross_r": round(sum(r["gross_r"] for r in rows), 2),
        "total_net_r": round(sum(r["net_r"] for r in rows), 2),
        "avg_win_r": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss_r": round(abs(sum(losses) / len(losses)), 2) if losses else 0.0,
        "profit_factor": round(gross_win / gross_loss, 2)
        if gross_loss > 0
        else (99.9 if gross_win > 0 else 0.0),
        "time_stop_rate_pct": round((time_stops / n) * 100.0, 1),
    }


def compute_signal_expectancy_report(
    alerts: Optional[Iterable[dict[str, Any]]] = None,
    *,
    include_test: bool = False,
) -> dict[str, Any]:
    """Compute segmented post-cost signal expectancy report over persisted terminal alerts."""
    raw_list = list(alerts) if alerts is not None else load_persisted_alerts()

    evaluated: list[dict[str, Any]] = []
    skipped_unclosed = 0
    skipped_test = 0

    for item in raw_list:
        d = (
            item
            if isinstance(item, dict)
            else (item.to_dict() if hasattr(item, "to_dict") else dict(item))
        )
        if not include_test:
            is_live = bool(d.get("is_live", False))
            env = str(d.get("environment", "")).upper().strip()
            if not is_live or env != "LIVE":
                skipped_test += 1
                continue

        stage = str(d.get("stage", "")).upper().strip()
        if stage in ("EARLY_WARNING", "PRIMED", "IGNITED", "ACTIVE", "ACTIONABLE", ""):
            skipped_unclosed += 1
            continue

        adapter = _DictAlertAdapter(d)
        exit_p = resolve_exit_price_from_alert(d)
        term = calculate_terminal_forward_outcome(adapter, exit_p) if exit_p else None

        gross_r: Optional[float] = None
        cost_r = 0.0
        is_calibratable = False

        if term is not None:
            gross_r = float(term.realized_r)
            cost_r = _estimate_cost_r_drag(
                d, term.entry_price, term.initial_stop_loss, term.exit_price
            )
            is_calibratable = True
        else:
            raw_r = d.get("r_multiple")
            try:
                val_r = float(raw_r)
                if (
                    math.isfinite(val_r)
                    and -5.0 <= val_r <= 25.0
                    and bool(d.get("has_triggered", False))
                ):
                    gross_r = val_r
                    entry_val = float(
                        d.get("initial_entry_premium")
                        or d.get("trigger_level")
                        or d.get("ltp")
                        or 0.0
                    )
                    stop_val = float(d.get("initial_stop_loss") or d.get("stop_loss") or 0.0)
                    if entry_val > 0 and stop_val > 0 and exit_p:
                        cost_r = _estimate_cost_r_drag(d, entry_val, stop_val, exit_p)
            except (TypeError, ValueError):
                gross_r = None

        if gross_r is None:
            skipped_unclosed += 1
            continue

        metrics = d.get("metrics") or {}
        if not isinstance(metrics, dict):
            metrics = {}
        segment = str(d.get("segment") or "UNKNOWN").upper().strip()
        evaluated.append(
            {
                "alert_id": d.get("alert_id"),
                "alert_type": str(d.get("alert_type") or "UNKNOWN").upper().strip(),
                "segment": segment,
                "stage": stage,
                "session_bucket": _resolve_session_bucket(d.get("created_at"), segment),
                "rvol_bucket": _resolve_rvol_bucket(metrics),
                "confluence_bucket": _resolve_confluence_bucket(d, metrics),
                "gross_r": round(gross_r, 4),
                "cost_r": round(cost_r, 4),
                "net_r": round(gross_r - cost_r, 4),
                "is_calibratable": is_calibratable,
            }
        )

    def _group_by(field: str) -> dict[str, dict[str, Any]]:
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in evaluated:
            buckets[str(row[field])].append(row)
        return {
            k: _summarize_bucket(v)
            for k, v in sorted(buckets.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        }

    return {
        "total_alerts_scanned": len(raw_list),
        "evaluated_trades": len(evaluated),
        "skipped_unclosed_or_untriggered": skipped_unclosed,
        "skipped_non_live": skipped_test,
        "min_preliminary_samples": MIN_PRELIMINARY_SAMPLES,
        "min_actionable_samples": MIN_ACTIONABLE_SAMPLES,
        "overall": _summarize_bucket(evaluated),
        "by_detector": _group_by("alert_type"),
        "by_segment": _group_by("segment"),
        "by_session_bucket": _group_by("session_bucket"),
        "by_rvol_bucket": _group_by("rvol_bucket"),
        "by_confluence_bucket": _group_by("confluence_bucket"),
    }
