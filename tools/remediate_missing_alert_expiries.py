"""
tools/remediate_missing_alert_expiries.py
─────────────────────────────────────────
Offline remediation script to populate missing expiry metadata in ~/.trading_platform/auto_alerts.json.
Conforms strictly to Invariant 18 (Zero In-Line Startup Migrations).
"""

import json
import pathlib
import sys
from datetime import datetime, timezone, timedelta

sys.stdout.reconfigure(encoding="utf-8")
IST = timezone(timedelta(hours=5, minutes=30))

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from engine.alert_expiry import get_expiry_metadata

p = pathlib.Path.home() / ".trading_platform" / "auto_alerts.json"
if not p.exists():
    print("No auto_alerts.json found.")
    sys.exit(0)

alerts = json.loads(p.read_text(encoding="utf-8"))
fixed = 0

for a in alerts:
    if a.get("contract_symbol") and not a.get("expiry_date"):
        meta = get_expiry_metadata(
            None, a.get("expiry_type"), a.get("symbol"), a["contract_symbol"]
        )
        if meta.get("raw_date"):
            a["expiry_date"] = meta["raw_date"]
            a["expiry_type"] = "WEEKLY" if meta.get("is_weekly") else "MONTHLY"
            a["expiry_details"] = meta
            a["expiry_month_name"] = meta.get("month_name")
            a["expiry_formatted"] = meta.get("formatted")
            a["dte"] = meta.get("dte")
            if "actionable_plan" in a and isinstance(a["actionable_plan"], dict):
                op = a["actionable_plan"].get("option_plan")
                if isinstance(op, dict):
                    op["expiry"] = meta["raw_date"]
                    op["expiry_date"] = meta["raw_date"]
            fixed += 1

if fixed > 0:
    # Save backup before writing
    bak = p.parent / f"auto_alerts.json.bak_exp_{datetime.now(IST).strftime('%Y%m%d_%H%M%S')}"
    bak.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    p.write_text(json.dumps(alerts, indent=2), encoding="utf-8")
    print(f"Successfully remediated {fixed} alerts in {p}. Backup created at {bak.name}.")
else:
    print("Zero alerts required remediation.")
