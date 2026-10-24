"""
scripts/remediate_corrupted_alerts.py — Offline Alert Data Remediation

Remediates corrupted alert records in ~/.trading_platform/auto_alerts.json that were
falsely flagged with IN_FLIGHT_WARNING / DANGER ZONE due to scale contamination
(comparing equity spot prices against derivative option premium stop-losses).

Follows Invariant 18 (Zero In-Line Startup Migrations) & Invariant 20 (SSOT & Auditability).
"""

import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

IST = ZoneInfo("Asia/Kolkata")


def remediate_auto_alerts(dry_run: bool = False) -> int:
    path = os.path.expanduser("~/.trading_platform/auto_alerts.json")
    if not os.path.exists(path):
        print(f"File not found: {path}")
        return 0

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    remediated_count = 0
    now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    for a in data:
        warn_sent = a.get("in_flight_warning_sent", False)
        warn_reason = str(a.get("in_flight_warning_reason") or "")
        stage = a.get("stage", "")

        # Detect scale contamination signatures
        is_corrupted = False
        if warn_sent and ("99% risk budget consumed" in warn_reason or "near SL" in warn_reason):
            act_plan = a.get("actionable_plan") or {}
            opt_plan = act_plan.get("option_plan") if isinstance(act_plan, dict) else {}
            has_opt = bool(opt_plan or a.get("strike") or a.get("option_type"))
            ltp = float(a.get("ltp") or 0.0)
            if has_opt and ltp > 50.0:
                is_corrupted = True

        if not is_corrupted:
            continue

        remediated_count += 1
        aid = a.get("alert_id")
        sym = a.get("symbol")
        prev_stage = stage

        # Determine recovered stage
        achieved = a.get("achieved_milestones") or []
        tgt_status = str(a.get("target_status") or "").upper()
        if stage in ("COMPLETED", "INVALIDATED", "RUNNER_EXIT"):
            new_stage = stage
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
        elif "TRAILING_UPDATE" in achieved or a.get("trailing_stop"):
            new_stage = "TRAILING_UPDATE"
        elif a.get("triggered_at") or a.get("is_ignited"):
            new_stage = "IGNITED"
        else:
            new_stage = "PRIMED"

        print(f"[{sym}] {aid}: {prev_stage} -> {new_stage} (Reason was: {warn_reason[:50]}...)")

        if not dry_run:
            a["in_flight_warning_sent"] = False
            a["in_flight_warning_reason"] = None
            if stage == "IN_FLIGHT_WARNING":
                a["stage"] = new_stage

            if "audit_trail" not in a or not isinstance(a["audit_trail"], list):
                a["audit_trail"] = []
            a["audit_trail"].append(
                {
                    "timestamp": now_iso,
                    "event_type": "DATA_REMEDIATION",
                    "action": "DATA_REMEDIATION",
                    "message": f"Offline remediation: cleared false IN_FLIGHT_WARNING caused by legacy scale contamination. Restored stage {prev_stage} -> {new_stage}.",
                    "actor": "OFFLINE_REMEDIATION",
                    "details": {
                        "previous_reason": warn_reason,
                        "previous_stage": prev_stage,
                        "restored_stage": new_stage,
                    },
                }
            )

    if not dry_run and remediated_count > 0:
        # Atomic file write
        temp_path = f"{path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(temp_path, path)
        print(f"\nSuccessfully remediated {remediated_count} alerts in {path}.")
    else:
        print(f"\nDry run complete. {remediated_count} alerts identified for remediation.")

    return remediated_count


if __name__ == "__main__":
    is_dry = "--dry-run" in sys.argv
    remediate_auto_alerts(dry_run=is_dry)
