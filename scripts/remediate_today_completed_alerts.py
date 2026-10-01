"""
scripts/remediate_today_completed_alerts.py
─────────────────────────────────────────────
Institutional offline remediation script (Invariant 18):
1. Reverses false invalidations on winning/profitable session-closed alerts from 2026-09-29.
   Transfers them to stage="COMPLETED", is_invalidated=False, archive_reason="Trading session ended at 15:15 IST. Profit secured."
2. Remediates inverted targets on precursor alerts (e.g. BAJFINANCE) anchoring targets to trigger_level.
3. Preserves full auditability with timestamped JSON backup and immutable audit_trail entries.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone, timedelta

# Fix Windows console UTF-8 encoding
if sys.platform == "win32":
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

IST = timezone(timedelta(hours=5, minutes=30))
now = datetime.now(IST)
now_str = now.strftime("%Y%m%d_%H%M%S")
now_iso = now.strftime("%Y-%m-%d %H:%M:%S IST")

base_dir = os.path.expanduser("~/.trading_platform")
auto_alerts_path = os.path.join(base_dir, "auto_alerts.json")

print("=== REMEDIATING TODAY'S AUTO ALERTS (2026-09-29) ===")

if not os.path.exists(auto_alerts_path):
    print(f"Error: {auto_alerts_path} does not exist.")
    sys.exit(1)

# 1. Create timestamped backup
backup_path = f"{auto_alerts_path}.pre_remediation_{now_str}.bak"
shutil.copy2(auto_alerts_path, backup_path)
print(f"Backup created at: {backup_path}")

with open(auto_alerts_path, "r", encoding="utf-8") as f:
    alerts = json.load(f)

remediated_winners = 0
remediated_precursors = 0

for a in alerts:
    aid = a.get("alert_id", "")
    created = a.get("created_at", "")
    is_today = "20260929" in aid or str(created).startswith("2026-09-29")
    if not is_today:
        continue

    # 1. Fix winning alerts marked as invalidated
    is_inv = a.get("is_invalidated", False)
    tgt_status = a.get("target_status", "")
    pnl = float(a.get("pnl_pct") or 0.0)
    has_won = tgt_status in ("TARGET_ACHIEVED", "T1_ACHIEVED") or pnl > 0.0

    if is_inv and has_won:
        prev_inv_reason = a.get("invalidation_reason", "")
        a["is_invalidated"] = False
        a["invalidation_reason"] = None
        a["stage"] = "COMPLETED"
        a["is_archived"] = True
        a["archive_reason"] = (
            "Trading session ended at 15:15 IST. Profit secured / target achieved."
        )

        # Audit trail
        trail = a.setdefault("audit_trail", [])
        if isinstance(trail, list):
            trail.append(
                {
                    "timestamp": now_iso,
                    "event": "REMEDIATION_INVALIDATION_REVERSAL",
                    "notes": f"Reversed false invalidation ('{prev_inv_reason}') on profitable trade (PnL: +{pnl:.1f}%). Set stage=COMPLETED.",
                }
            )
        remediated_winners += 1
        print(
            f"  [WINNER REMEDIATED] {aid} ({a.get('symbol')}): PnL +{pnl:.1f}%, TargetStatus: {tgt_status}"
        )

    # 2. Fix precursor radar inverted targets (trigger > target_1 on bullish)
    atype = a.get("alert_type", "")
    direction = str(a.get("direction", "")).upper()
    trigger = float(a.get("trigger_level") or 0.0)
    target_1 = float(a.get("target_level") or 0.0)
    sl = float(a.get("stop_loss") or 0.0)

    if "PRECURSOR" in atype.upper() or "precursor" in aid.lower():
        if direction == "BULLISH" and trigger > 0 and target_1 > 0 and target_1 <= trigger:
            risk_pts = (
                max(1.0, round(trigger - sl, 2))
                if sl > 0 and sl < trigger
                else round(trigger * 0.015, 2)
            )
            new_t1 = round(trigger + 1.5 * risk_pts, 2)
            new_t2 = round(trigger + 2.5 * risk_pts, 2)

            a["target_level"] = new_t1
            plan = a.setdefault("actionable_plan", {})
            if isinstance(plan, dict):
                plan["target_1"] = new_t1
                plan["target_2"] = new_t2
                plan["trigger_level"] = trigger
                plan["stop_loss"] = sl
                plan["risk_reward_ratio"] = "1:1.5"
                plan["no_chase_boundary"] = round(trigger * 1.008, 2)
                plan["strategy"] = "Institutional Precursor Breakout Radar"

            trail = a.setdefault("audit_trail", [])
            if isinstance(trail, list):
                trail.append(
                    {
                        "timestamp": now_iso,
                        "event": "REMEDIATION_TARGET_REANCHORING",
                        "notes": f"Corrected inverted targets: Old T1={target_1}, New T1={new_t1}, New T2={new_t2} anchored above trigger {trigger}.",
                    }
                )
            remediated_precursors += 1
            print(
                f"  [PRECURSOR REMEDIATED] {aid} ({a.get('symbol')}): Trigger {trigger} -> New T1 {new_t1}, New T2 {new_t2} (Old T1 was {target_1})"
            )

# Write back updated alerts atomically
tmp_file = f"{auto_alerts_path}.tmp"
with open(tmp_file, "w", encoding="utf-8") as f:
    json.dump(alerts, f, indent=2, ensure_ascii=False)

os.replace(tmp_file, auto_alerts_path)
print(
    f"Remediation complete: {remediated_winners} winning alerts restored to COMPLETED, {remediated_precursors} precursor targets re-anchored."
)
