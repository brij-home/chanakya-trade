"""
scripts/remediate_today_scale_contamination.py — Offline Scale Contamination Remediation

Remediates scale contamination in ~/.trading_platform/auto_alerts.json for alerts where
derivative option premiums contaminated primary underlying spot targets and stop-losses.

Invariants Respected:
  - Invariant 14: Tri-directional symmetry (Bullish, Bearish, Neutral)
  - Invariant 18: Zero in-line startup migrations (offline administrative script)
  - Invariant 20: SSOT & End-to-end audit traceability
  - Invariant 21: Zero silent swallowing
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

# Ensure workspace root is in sys.path
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from engine.alert_expiry import is_alert_option_premium_level

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("remediate_scale")
IST = ZoneInfo("Asia/Kolkata")


def parse_float_val(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"[\d,]+(?:\.\d+)?", str(v))
    if m:
        try:
            return float(m.group(0).replace(",", ""))
        except ValueError:
            return None
    return None


def remediate_scale_contamination(dry_run: bool = False, target_date: str = "20261023") -> int:
    path = os.path.expanduser("~/.trading_platform/auto_alerts.json")
    if not os.path.exists(path):
        logger.error(f"Alert file not found: {path}")
        return 0

    backup_path = f"{path}.bak.{datetime.now(IST).strftime('%Y%m%d_%H%M%S')}"
    if not dry_run:
        shutil.copyfile(path, backup_path)
        logger.info(f"Created pre-remediation backup: {backup_path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    remediated_count = 0
    now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    for a in data:
        aid = a.get("alert_id", "")
        created_at = str(a.get("created_at", ""))
        if target_date and (
            target_date not in aid
            and not created_at.startswith(f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:]}")
        ):
            continue

        # If this alert is legitimately an option-level contract (e.g. GAMMA_BLAST, INDEX_PUT_SETUP, OPTIONS_MOMENTUM), skip!
        if is_alert_option_premium_level(a):
            continue

        ltp = float(a.get("ltp") or 0.0)
        entry_p = float(a.get("entry_price") or a.get("trigger_level") or ltp)
        if ltp <= 50.0 and entry_p <= 50.0:
            # Micro-penny or penny stock, skip
            continue

        plan = a.get("actionable_plan") or {}
        if not isinstance(plan, dict):
            continue

        opt_p = plan.get("option_plan") or {}
        has_option_plan = isinstance(opt_p, dict) and bool(
            opt_p.get("contract_symbol") or opt_p.get("sl_premium")
        )
        if not has_option_plan and not a.get("strike") and not a.get("option_type"):
            continue

        # Check for scale contamination in plan stop_loss, target_2, target_3
        raw_plan_sl = parse_float_val(plan.get("stop_loss"))
        raw_plan_t2 = parse_float_val(plan.get("target_2"))
        raw_plan_t3 = parse_float_val(plan.get("target_3"))
        raw_alert_t2 = parse_float_val(a.get("target_2"))
        raw_alert_sl = parse_float_val(a.get("stop_loss"))

        is_sl_contaminated = (
            raw_plan_sl is not None and raw_plan_sl > 0 and raw_plan_sl < ltp * 0.40
        )
        is_t2_contaminated = (
            raw_plan_t2 is not None and raw_plan_t2 > 0 and raw_plan_t2 < ltp * 0.40
        )
        is_alert_t2_contaminated = (
            raw_alert_t2 is not None and raw_alert_t2 > 0 and raw_alert_t2 < ltp * 0.40
        )
        is_t3_contaminated = (
            raw_plan_t3 is not None and raw_plan_t3 > 0 and raw_plan_t3 < ltp * 0.40
        )

        warn_sent = a.get("in_flight_warning_sent", False)
        warn_reason = str(a.get("in_flight_warning_reason") or "")
        is_false_warning = warn_sent and (
            "risk budget consumed" in warn_reason or "near SL" in warn_reason
        )

        if not (
            is_sl_contaminated
            or is_t2_contaminated
            or is_alert_t2_contaminated
            or is_t3_contaminated
            or is_false_warning
        ):
            continue

        remediated_count += 1
        sym = a.get("symbol", "")
        direction = str(a.get("direction", "BULLISH")).upper()
        is_bull = direction in ("BULLISH", "BUY", "LONG")

        trade_plan = plan.get("trade_plan") or {}

        # 1. Recover Spot Stop Loss
        spot_sl = None
        if raw_alert_sl and raw_alert_sl >= ltp * 0.50 and raw_alert_sl <= ltp * 1.60:
            spot_sl = raw_alert_sl
        elif trade_plan.get("invalidation_stop"):
            spot_sl = float(trade_plan["invalidation_stop"])
        elif trade_plan.get("stop_loss"):
            spot_sl = float(trade_plan["stop_loss"])
        elif plan.get("underlying_sl"):
            spot_sl = parse_float_val(plan["underlying_sl"])

        if not spot_sl or spot_sl <= 0:
            # Fallback to standard 1.5% structural risk
            spot_sl = round(ltp * 0.985, 2) if is_bull else round(ltp * 1.015, 2)

        # 2. Recover Spot Targets
        spot_t1 = None
        raw_alert_t1 = parse_float_val(a.get("target_1"))
        if raw_alert_t1 and raw_alert_t1 >= ltp * 0.50:
            spot_t1 = raw_alert_t1
        elif trade_plan.get("target_1"):
            spot_t1 = float(trade_plan["target_1"])
        elif plan.get("underlying_target"):
            spot_t1 = parse_float_val(plan["underlying_target"])

        if not spot_t1 or spot_t1 <= 0:
            risk_dist = abs(entry_p - spot_sl)
            spot_t1 = (
                round(entry_p + 1.5 * risk_dist, 2)
                if is_bull
                else round(entry_p - 1.5 * risk_dist, 2)
            )

        spot_t2 = None
        if trade_plan.get("target_2"):
            spot_t2 = float(trade_plan["target_2"])
        else:
            risk_dist = abs(entry_p - spot_sl)
            spot_t2 = (
                round(entry_p + 3.0 * risk_dist, 2)
                if is_bull
                else round(entry_p - 3.0 * risk_dist, 2)
            )

        spot_t3 = None
        if trade_plan.get("runner_target"):
            spot_t3 = float(trade_plan["runner_target"])
        elif trade_plan.get("target_3"):
            spot_t3 = float(trade_plan["target_3"])
        else:
            risk_dist = abs(entry_p - spot_sl)
            spot_t3 = (
                round(entry_p + 5.0 * risk_dist, 2)
                if is_bull
                else round(entry_p - 5.0 * risk_dist, 2)
            )

        # 3. Preserve Option Premiums into option_plan
        if "option_plan" not in plan or not isinstance(plan["option_plan"], dict):
            plan["option_plan"] = {}

        if is_sl_contaminated:
            plan["option_plan"]["sl_premium"] = raw_plan_sl
            plan["option_sl"] = f"₹{raw_plan_sl:,.2f}"
        if is_t2_contaminated or is_alert_t2_contaminated:
            opt_t2_val = raw_plan_t2 or raw_alert_t2
            plan["option_plan"]["t2_premium"] = opt_t2_val
            plan["option_target_2"] = f"₹{opt_t2_val:,.2f}"
        if is_t3_contaminated:
            plan["option_plan"]["t3_premium"] = raw_plan_t3
            plan["option_target_3"] = f"₹{raw_plan_t3:,.2f}"

        # 4. Restore Spot Coordinates on Primary Fields
        plan["stop_loss"] = f"₹{spot_sl:,.2f}"
        plan["target_1"] = f"₹{spot_t1:,.2f}"
        plan["target_2"] = f"₹{spot_t2:,.2f}"
        plan["target_3"] = f"₹{spot_t3:,.2f}"
        a["stop_loss"] = spot_sl
        a["target_1"] = spot_t1
        a["target_2"] = spot_t2

        # 5. Fix In-Flight Warning & False Danger Zone
        prev_stage = a.get("stage", "")
        if is_false_warning:
            a["in_flight_warning_sent"] = False
            a["in_flight_warning_reason"] = None

            achieved = a.get("achieved_milestones") or []
            tgt_status = str(a.get("target_status") or "").upper()
            if prev_stage in ("COMPLETED", "INVALIDATED", "RUNNER_EXIT"):
                new_stage = prev_stage
            elif a.get("is_invalidated") or tgt_status in ("INVALIDATED", "STOPPED_OUT"):
                new_stage = "INVALIDATED"
            elif "RUNNER_EXIT" in achieved or "RUNNER_CLOSED" in tgt_status:
                new_stage = "RUNNER_EXIT"
            elif "T2_ACHIEVED" in achieved:
                new_stage = "T2_ACHIEVED"
            elif "T1_ACHIEVED" in achieved:
                new_stage = "T1_ACHIEVED"
            elif "T0_5_ACHIEVED" in achieved or "DE_RISK" in tgt_status:
                new_stage = "DE_RISK_0_5R"
            elif a.get("triggered_at") or a.get("is_ignited"):
                new_stage = "IGNITED"
            else:
                new_stage = "PRIMED"

            if prev_stage == "IN_FLIGHT_WARNING":
                a["stage"] = new_stage

        logger.info(
            f"[{sym}] {aid}: Restored Spot SL={spot_sl}, T1={spot_t1}, T2={spot_t2} "
            f"(was SL={raw_plan_sl}, T2={raw_plan_t2}, alert_T2={raw_alert_t2})"
        )

        if not dry_run:
            if "audit_trail" not in a or not isinstance(a["audit_trail"], list):
                a["audit_trail"] = []
            a["audit_trail"].append(
                {
                    "timestamp": now_iso,
                    "event_type": "SCALE_REMEDIATION",
                    "action": "SCALE_CONTAMINATION_REPAIR",
                    "message": (
                        f"Offline remediation: restored spot coordinates (SL ₹{spot_sl:,.2f}, T1 ₹{spot_t1:,.2f}, T2 ₹{spot_t2:,.2f}). "
                        f"Option premiums isolated into option_plan."
                    ),
                    "actor": "OFFLINE_SCALE_REMEDIATOR",
                    "details": {
                        "restored_spot_sl": spot_sl,
                        "restored_spot_t1": spot_t1,
                        "restored_spot_t2": spot_t2,
                        "previous_plan_sl": raw_plan_sl,
                        "previous_plan_t2": raw_plan_t2,
                    },
                }
            )

    if not dry_run and remediated_count > 0:
        temp_path = f"{path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(temp_path, path)
        logger.info(f"Successfully remediated {remediated_count} alerts in {path}.")
    else:
        logger.info(f"Dry run complete. {remediated_count} alerts identified for remediation.")

    return remediated_count


if __name__ == "__main__":
    is_dry = "--dry-run" in sys.argv
    remediate_scale_contamination(dry_run=is_dry)
