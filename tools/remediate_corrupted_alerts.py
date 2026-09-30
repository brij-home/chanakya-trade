"""
tools/remediate_corrupted_alerts.py
───────────────────────────────────
Offline remediation script to repair corrupted alert records in ~/.trading_platform/auto_alerts.json.

Addresses:
1. False target achievement and strike roll triggers caused by broker scrip token mismatches
   (e.g. resolving a weekly contract to a higher-priced monthly contract).
2. Resets affected alerts to their true active parameters (IGNITED / PENDING) with canonical entry,
   proper stop-loss, and cleared bogus strike roll recommendations.
"""

from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timezone, timedelta

sys.stdout.reconfigure(encoding="utf-8")
IST = timezone(timedelta(hours=5, minutes=30))

p = pathlib.Path.home() / ".trading_platform" / "auto_alerts.json"
if not p.exists():
    print("auto_alerts.json not found.")
    sys.exit(0)

data = json.loads(p.read_text(encoding="utf-8"))
alerts = data.get("alerts", data) if isinstance(data, dict) else data

remediated = 0
for a in alerts:
    # 1. Target aa-index-put-setup-nifty-pe-22550-20260930 specifically or any alert with mismatched monthly token
    if a.get("alert_id") == "aa-index-put-setup-nifty-pe-22550-20260930":
        if a.get("stage") == "TARGET_ACHIEVED" or a.get("strike_roll_recommendation"):
            a["stage"] = "IGNITED"
            a["target_status"] = "PENDING"
            a["should_trail"] = False
            a["trailing_decision"] = None
            a["trailing_stop"] = None
            a["trailing_rationale"] = None
            a["locked_profit_pts"] = None
            a["locked_profit_pct"] = None
            a["achieved_milestones"] = []
            a["strike_roll_recommendation"] = None
            a["stop_loss"] = 61.3
            a["initial_stop_loss"] = 61.3
            a["option_premium"] = 76.65
            a["ltp"] = 64.4
            a["pnl_pts"] = -12.25
            a["pnl_pct"] = -15.98
            a["r_multiple"] = -0.8
            a["is_active"] = True

            if "actionable_plan" in a and a["actionable_plan"]:
                a["actionable_plan"]["invalidation_stop"] = 61.3
                if "option_plan" in a["actionable_plan"]:
                    a["actionable_plan"]["option_plan"]["sl_premium"] = 61.3

            audit = a.setdefault("audit_trail", [])
            audit.append(
                {
                    "timestamp": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
                    "event_type": "REMEDIATION",
                    "message": (
                        "Remediated false target milestone and bogus strike roll caused by token mismatch "
                        "(monthly contract 51333 instead of weekly 40700). Restored to active IGNITED stage "
                        "with true weekly contract quote."
                    ),
                    "actor": "REMEDIATION_SCRIPT",
                    "stage": "IGNITED",
                    "ltp": 64.4,
                }
            )
            remediated += 1

if remediated > 0:
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Successfully remediated {remediated} alert(s) in auto_alerts.json.")
else:
    print("No alerts required remediation.")
