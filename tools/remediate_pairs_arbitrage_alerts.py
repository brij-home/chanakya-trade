"""
tools/remediate_pairs_arbitrage_alerts.py
─────────────────────────────────────────
Remediation script to sanitize corrupted pairs arbitrage alerts generated
with hardcoded placeholder LTP (100.0) in ~/.trading_platform/auto_alerts.json.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import sys
from datetime import datetime, timezone, timedelta

sys.stdout.reconfigure(encoding="utf-8")
IST = timezone(timedelta(hours=5, minutes=30))

p = pathlib.Path.home() / ".trading_platform" / "auto_alerts.json"
if not p.exists():
    print("auto_alerts.json not found.")
    sys.exit(0)

try:
    data = json.loads(p.read_text(encoding="utf-8"))
except Exception as exc:
    print(f"Error loading auto_alerts.json: {exc}")
    sys.exit(1)

alerts = data.get("alerts", data) if isinstance(data, dict) else data

remediated = 0
now_str = datetime.now(IST).strftime("%Y%m%d_%H%M%S")
now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

for a in alerts:
    if a.get("alert_type") == "PAIRS_ARBITRAGE" and (
        a.get("entry_price") == 100.0 or a.get("ltp") == 100.0
    ):
        aid = a.get("alert_id")
        sym = a.get("symbol")
        print(f"Remediating corrupted pairs arbitrage alert: {aid} ({sym})")

        a["is_active"] = False
        a["is_invalidated"] = True
        a["stage"] = "INVALIDATED"
        a["status"] = "INVALIDATED"
        a["invalidation_reason"] = (
            "Remediated: Generated with hardcoded placeholder LTP (100.0) instead of live market quote."
        )
        a["invalidated_at"] = now_iso
        a["achieved_milestones"] = []
        a["target_status"] = "INVALIDATED"
        a["should_trail"] = False
        a["trailing_decision"] = None

        audit = a.setdefault("audit_trail", [])
        audit.append(
            {
                "timestamp": now_iso,
                "event_type": "REMEDIATION",
                "action": "INVALIDATED_CORRUPTED_ENTRY",
                "message": (
                    "Remediated corrupted alert: Hardcoded placeholder entry price ₹100.0 eliminated. "
                    "Marked INVALIDATED to prevent false win statistics and ungrounded execution."
                ),
                "actor": "REMEDIATION_SCRIPT",
                "stage": "INVALIDATED",
            }
        )
        remediated += 1

if remediated > 0:
    bak = p.parent / f"auto_alerts.json.bak_pairs_{now_str}"
    shutil.copy2(p, bak)
    print(f"Backup saved to: {bak}")
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Successfully remediated {remediated} alert(s) in auto_alerts.json.")
else:
    print("No corrupted pairs arbitrage alerts found.")
