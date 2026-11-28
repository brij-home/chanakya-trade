"""
engine/confidence_calibrator.py
───────────────────────────────
Hierarchical Confidence Calibration & Net-Cost Expectancy Governor.

Replaces ungrounded static detector scores (82–95) with an explicit, auditable
3-layer calibration assessment:
  1. Structural Strength: multi-pillar confluence count, R:R asymmetry, flow depth.
  2. Empirical Calibration: rolling detector metrics from detector_circuit_breaker
     with strict UNCALIBRATED zero-alpha invariant (never inflates uncalibrated scores).
  3. Statutory + Spread Friction Ratio: real NSE/BSE charges (via engine.charges)
     plus bid-ask spread relative to Target-1 distance.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional

from config.constants import IST_ZONE as IST

logger = logging.getLogger("engine.confidence_calibrator")


@dataclass
class CalibratedConfidenceReport:
    raw_confidence: int
    calibrated_confidence: int
    calibration_status: str  # "UNCALIBRATED" | "HEALTHY" | "NORMAL" | "PROBATION" | "HALTED"
    empirical_sample_count: int
    empirical_expectancy: float
    structural_pillars_count: int
    cost_friction_pct: Optional[float]
    high_friction_risk: bool
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _alert_field(alert: Any, name: str, default: Any = None) -> Any:
    """Read field uniformly from either an AutoAlert dataclass/object or dict payload."""
    if isinstance(alert, dict):
        return alert.get(name, default)
    return getattr(alert, name, default)


def calibrate_alert_confidence(
    alert: Any,
    *,
    pillars: Optional[list[str]] = None,
    as_of: Optional[datetime] = None,
) -> CalibratedConfidenceReport:
    """Evaluate honest, cost-aware calibrated confidence for an AutoAlert candidate or dict."""
    raw_val = _alert_field(alert, "confidence", None)
    raw_conf = int(raw_val) if raw_val is not None else 0
    raw_conf = max(0, min(100, raw_conf))
    notes: list[str] = []

    metrics = _alert_field(alert, "metrics", None)
    metrics = metrics if isinstance(metrics, dict) else {}
    pillar_list = (
        list(pillars) if pillars is not None else list(metrics.get("confluence_pillars") or [])
    )
    pillar_cnt = len(pillar_list)

    # 1. Empirical detector edge check (strict UNCALIBRATED zero-bonus guarantee)
    cal_status = "UNCALIBRATED"
    sample_count = 0
    expectancy = 0.0
    empirical_adj = 0
    max_cap = 100

    try:
        from engine.detector_circuit_breaker import detector_circuit_breaker

        atype = str(_alert_field(alert, "alert_type", "") or "").upper().strip()
        if atype:
            dm = detector_circuit_breaker.get_metrics(atype)
            cal_status = str(dm.status)
            sample_count = int(dm.sample_count)
            expectancy = float(dm.expectancy)
            if cal_status == "HALTED":
                max_cap = 40
                empirical_adj = -30
                notes.append(f"Detector HALTED (E={expectancy:.2f}R, n={sample_count})")
            elif cal_status == "PROBATION":
                max_cap = 74
                empirical_adj = -15
                notes.append(f"Detector PROBATION (E={expectancy:.2f}R, n={sample_count})")
            elif cal_status == "HEALTHY" and expectancy >= 0.25 and sample_count >= 10:
                empirical_adj = min(5, int(round(expectancy * 4.0)))
                notes.append(f"Calibrated HEALTHY (E=+{expectancy:.2f}R, n={sample_count})")
            else:
                notes.append(f"Empirical state={cal_status} (n={sample_count}) — zero alpha boost")
    except Exception as e_cb:
        logger.debug(f"[ConfidenceCalibrator] Empirical lookup skipped: {e_cb}")

    # Prevent uncalibrated setups with < 3 pillars from clearing high-confidence alert tiers blindly
    if cal_status == "UNCALIBRATED" and pillar_cnt < 3:
        max_cap = min(max_cap, 84)
        notes.append("Uncalibrated setup (<3 full pillars) capped at 84")

    # 2. Statutory + spread friction relative to planned Target-1 distance
    ltp_entry = float(
        _alert_field(alert, "ltp", 0.0) or _alert_field(alert, "trigger_level", 0.0) or 0.0
    )
    trig_entry = float(_alert_field(alert, "trigger_level", 0.0) or 0.0)
    t1 = float(_alert_field(alert, "target_level", 0.0) or 0.0)
    lot_sz = max(1, int(_alert_field(alert, "lot_size", 1) or 1))
    is_opt = bool(_alert_field(alert, "option_type", None) in ("CE", "PE"))
    exch_u = str(_alert_field(alert, "exchange", "NSE") or "NSE").upper()

    # For fast option breakouts where live premium accelerated close to or past initial T1,
    # measure setup friction against planned setup target distance (trigger -> T1) so winners
    # aren't misclassified as narrow micro-targets.
    entry = ltp_entry
    reward_per_unit = abs(t1 - entry) if (entry > 0 and t1 > 0) else 0.0
    if is_opt and trig_entry > 0 and t1 > trig_entry and abs(t1 - trig_entry) > reward_per_unit:
        entry = trig_entry
        reward_per_unit = abs(t1 - trig_entry)

    cost_friction_pct: Optional[float] = None
    high_friction_risk = False
    if entry > 0 and t1 > 0 and reward_per_unit > 0:
        try:
            from engine.charges import calculate_transaction_charges

            ref_d = (as_of or datetime.now(IST)).date()
            seg: Any = (
                "OPTIONS"
                if is_opt
                else (
                    "COMMODITY"
                    if exch_u == "MCX"
                    else ("CURRENCY" if exch_u == "CDS" else "EQUITY_INTRADAY")
                )
            )
            buy_c = calculate_transaction_charges(
                entry, lot_sz, segment=seg, side="BUY", trade_date=ref_d
            )
            sell_c = calculate_transaction_charges(
                t1, lot_sz, segment=seg, side="SELL", trade_date=ref_d
            )
            stat_per_unit = float(buy_c.total_charges + sell_c.total_charges) / lot_sz
            bas_pct = float(
                _alert_field(alert, "bid_ask_spread_pct", None)
                or (metrics.get("liquidity") or {}).get("bid_ask_spread_pct")
                or 0.0
            )
            spread_per_unit = entry * (bas_pct / 100.0) if bas_pct > 0 else 0.0
            cost_friction_pct = round(
                ((stat_per_unit + spread_per_unit) / reward_per_unit) * 100.0, 2
            )
            if cost_friction_pct >= 25.0:
                high_friction_risk = True
                max_cap = min(max_cap, 72)
                notes.append(
                    f"High cost+spread friction ({cost_friction_pct:.1f}% of Target-1 distance)"
                )
        except Exception as e_cost:
            logger.debug(f"[ConfidenceCalibrator] Friction estimate skipped: {e_cost}")

    cal_conf = max(10, min(max_cap, raw_conf + empirical_adj)) if raw_conf > 0 else 0
    return CalibratedConfidenceReport(
        raw_confidence=raw_conf,
        calibrated_confidence=cal_conf,
        calibration_status=cal_status,
        empirical_sample_count=sample_count,
        empirical_expectancy=round(expectancy, 3),
        structural_pillars_count=pillar_cnt,
        cost_friction_pct=cost_friction_pct,
        high_friction_risk=high_friction_risk,
        notes=notes,
    )


def evaluate_telegram_confidence_calibration(
    alert: Any,
    min_conf: int,
    *,
    is_lifecycle_update: bool = False,
) -> tuple[bool, CalibratedConfidenceReport, str]:
    """
    Shared Telegram confidence & cost-friction gate called by both AlertPreferences
    and AutoAlertEngine._dispatch(). Prevents uncalibrated single-pillar or high-friction
    setups from bypassing Telegram min_confidence thresholds on arbitrary raw scores.
    """
    raw_conf = int(_alert_field(alert, "confidence", 0) or 0)
    pillars: Optional[list[str]] = None
    three_ok = True
    metrics = _alert_field(alert, "metrics", None)
    if not is_lifecycle_update:
        try:
            from types import SimpleNamespace
            from engine.signal_policy import (
                build_policy_context_from_alert,
                evaluate_three_pillar_confluence,
            )

            alert_obj = SimpleNamespace(**alert) if isinstance(alert, dict) else alert
            ctx = build_policy_context_from_alert(alert_obj)
            three_ok, pillars, _ = evaluate_three_pillar_confluence(alert_obj, ctx)
        except Exception as e_p:
            logger.debug(f"[ConfidenceCalibrator] Pillar inference skipped: {e_p}")

    report = calibrate_alert_confidence(alert, pillars=pillars)
    if isinstance(metrics, dict):
        metrics["calibrated_confidence"] = report.calibrated_confidence
        metrics["calibration_status"] = report.calibration_status
        if report.cost_friction_pct is not None:
            metrics["cost_friction_pct"] = report.cost_friction_pct

    if is_lifecycle_update:
        return True, report, "Lifecycle milestone exempt"

    if report.calibration_status == "HALTED":
        return (
            False,
            report,
            f"Detector HALTED by circuit breaker (E={report.empirical_expectancy:.2f}R, n={report.empirical_sample_count})",
        )
    if report.high_friction_risk and report.calibrated_confidence < min_conf:
        return (
            False,
            report,
            f"High statutory+spread friction ({report.cost_friction_pct:.1f}% of T1) caps calibrated confidence to {report.calibrated_confidence}% (< {min_conf}%)",
        )
    if report.calibration_status == "PROBATION" and report.calibrated_confidence < min_conf:
        return (
            False,
            report,
            f"Detector in PROBATION: calibrated confidence {report.calibrated_confidence}% below bar {min_conf}%",
        )
    if raw_conf < min_conf:
        return False, report, f"Confidence {raw_conf}% below threshold {min_conf}%"

    # Prevent uncalibrated single-pillar (< 2) alerts with indicator telemetry from clearing high-confidence Telegram bars on raw score alone
    if (
        report.calibration_status == "UNCALIBRATED"
        and min_conf >= 85
        and not three_ok
        and pillars is not None
        and report.structural_pillars_count < 2
        and report.calibrated_confidence < min_conf
    ):
        return (
            False,
            report,
            f"Uncalibrated single-pillar setup ({report.structural_pillars_count}/3 pillars) capped at {report.calibrated_confidence}% (< {min_conf}%)",
        )

    return True, report, "Calibrated confidence passed"
