"""
scripts/remediate_corrupted_alerts.py
──────────────────────────────────────
Invalidates corrupted MCX commodity option alerts in auto_alerts.json
and purges false win records from pattern_outcomes.json with institutionally
honest invalidation reasons so that they are never counted as trading wins.
"""

import json
import os
import shutil
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
now_str = datetime.now(IST).strftime("%Y%m%d_%H%M%S")
now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

base_dir = os.path.expanduser("~/.trading_platform")
auto_alerts_path = os.path.join(base_dir, "auto_alerts.json")
pattern_outcomes_path = os.path.join(base_dir, "pattern_outcomes.json")

print("=== REMEDIATING CORRUPTED ALERTS & PURGING FALSE WINS ===")

# 1. Remediate auto_alerts.json
if os.path.exists(auto_alerts_path):
    # Create timestamped backup
    backup_path = f"{auto_alerts_path}.pre_invalidation_{now_str}.bak"
    shutil.copy2(auto_alerts_path, backup_path)
    print(f"Created backup of auto_alerts.json at: {backup_path}")

    with open(auto_alerts_path, "r", encoding="utf-8") as f:
        alerts = json.load(f)

    invalidated_count = 0
    for a in alerts:
        aid = a.get("alert_id", "")
        sym = a.get("symbol", "")
        ex = a.get("exchange", "")
        rm = a.get("r_multiple") or 0
        pnl = a.get("pnl_pct") or 0

        # Target criteria: MCX base metal option alerts, or alerts with corrupted >500% PnL / >20R from units confusion
        is_corrupted = False
        reasons = []

        if ex == "MCX" and sym in ("COPPER", "ZINC", "ALUMINIUM", "LEAD", "SILVER"):
            # Check if it was generated as an option trade
            plan = a.get("actionable_plan") or {}
            if (
                a.get("strike")
                or plan.get("instrument_type") == "OPTION"
                or plan.get("preferred_vehicle") == "DEFINED_RISK_OPTION"
            ):
                is_corrupted = True
                reasons.append(
                    f"Illiquid MCX option contract for base metal {sym} with zero institutional open interest"
                )

        if rm > 20 or pnl > 500:
            is_corrupted = True
            reasons.append(
                f"Unit scale mismatch between spot price and option premium levels (R: {rm}, PnL: {pnl}%)"
            )

        if is_corrupted and not a.get("is_invalidated"):
            full_reason = (
                "Corrupted alert: MCX option vehicle evaluated against spot price with uncalibrated COMEX basis "
                f"and illiquid contract ({'; '.join(reasons)})."
            )
            a["is_invalidated"] = True
            a["invalidation_reason"] = full_reason
            a["invalidated_at"] = now_iso
            a["stage"] = "INVALIDATED"
            a["target_status"] = "INVALIDATED"
            a["achieved_milestones"] = []
            a["should_trail"] = False
            a["trailing_decision"] = "INVALIDATED"
            a["trailing_stop"] = None
            a["r_multiple"] = 0.0
            a["pnl_pct"] = 0.0
            a["locked_profit_pts"] = 0.0
            a["locked_profit_pct"] = 0.0
            a["is_archived"] = True
            a["archived_at"] = now_iso
            a["archive_reason"] = full_reason
            is_test = (a.get("environment") == "TEST") or (not a.get("is_live", True))
            tag = "[TEST]" if is_test else "[REAL/LIVE]"
            a["headline"] = (
                f"⚠️ {tag} VIEW INVALIDATED: {sym} {a.get('alert_type', '').replace('_', ' ')}"
            )
            a["summary"] = full_reason
            invalidated_count += 1
            print(f"-> Invalidated alert {aid} ({sym}): {full_reason}")

    with open(auto_alerts_path, "w", encoding="utf-8") as f:
        json.dump(alerts, f, indent=2, ensure_ascii=False)
    print(f"Successfully remediated {invalidated_count} alert(s) in auto_alerts.json.")

# 2. Remediate pattern_outcomes.json
if os.path.exists(pattern_outcomes_path):
    backup_po = f"{pattern_outcomes_path}.pre_invalidation_{now_str}.bak"
    shutil.copy2(pattern_outcomes_path, backup_po)
    print(f"Created backup of pattern_outcomes.json at: {backup_po}")

    with open(pattern_outcomes_path, "r", encoding="utf-8") as f:
        outcomes = json.load(f)

    purged_count = 0
    cleaned_outcomes = []
    for item in outcomes:
        aid = str(item.get("alert_id") or "")
        sym = str(item.get("symbol") or "")
        out = item.get("outcome")
        en = float(item.get("entry_price") or 0)
        ex = float(item.get("exit_price") or 0)

        # Flag false wins from unit mismatches
        is_false_win = False
        if out in ("WIN_T1", "WIN_T2", "WIN_TARGET"):
            if "comm-copper" in aid or sym.upper() == "COPPER":
                is_false_win = True
            elif en > 0 and (ex / en > 5.0 or ex / en < 0.2):
                is_false_win = True

        if is_false_win:
            purged_count += 1
            print(
                f"-> Purged false win outcome: alert={aid}, sym={sym}, outcome={out}, entry={en}, exit={ex}"
            )
            # Mark as INVALIDATED and set realized_rr to 0.0 so it is excluded from win analytics
            item["outcome"] = "INVALIDATED"
            item["realized_rr"] = 0.0
            cleaned_outcomes.append(item)
        else:
            cleaned_outcomes.append(item)

    with open(pattern_outcomes_path, "w", encoding="utf-8") as f:
        json.dump(cleaned_outcomes, f, indent=2, ensure_ascii=False)
    print(f"Successfully cleaned {purged_count} false win outcome(s) in pattern_outcomes.json.")

print("=== REMEDIATION COMPLETED ===")
