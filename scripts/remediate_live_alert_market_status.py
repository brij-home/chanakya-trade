"""
scripts/remediate_live_alert_market_status.py
─────────────────────────────────────────────
Offline remediation script to correct historical/active LIVE alerts
whose market_status was inadvertently saved as 'SESSION_CLOSED' due to
the legacy dataclass default.

Rule 18 compliance: Offline maintenance, never run on hot startup loops.
"""

import logging

logger = logging.getLogger("scripts.remediate_live_alert_market_status")


import json
import os
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))
now = datetime.now(IST)
now_str = now.strftime("%Y%m%d_%H%M%S")

base_dir = Path.home() / ".trading_platform"
auto_alerts_path = base_dir / "auto_alerts.json"

print("=== REMEDIATING LIVE ALERT MARKET_STATUS ===")

if not auto_alerts_path.exists():
    print(f"No auto_alerts.json found at {auto_alerts_path}. Exiting.")
    exit(0)

# 1. Create timestamped backup
backup_path = base_dir / f"auto_alerts.pre_mkt_status_fix_{now_str}.bak"
shutil.copy2(auto_alerts_path, backup_path)
print(f"Created backup at: {backup_path}")

with open(auto_alerts_path, "r", encoding="utf-8") as f:
    alerts = json.load(f)

print(f"Loaded {len(alerts)} alerts.")

updated_count = 0

for a in alerts:
    env = (a.get("environment") or "").upper()
    is_live = a.get("is_live", True)
    is_test = (
        a.get("is_test", False)
        or env in ("TEST", "SIMULATION", "DEMO")
        or (a.get("alert_id") or "").startswith(("test-", "sim-", "mock-"))
    )
    current_mkt_st = a.get("market_status")

    # If it was generated in a LIVE environment and not test:
    # and has market_status "SESSION_CLOSED", check if it's an intraday/live setup
    if env == "LIVE" and not is_test and current_mkt_st == "SESSION_CLOSED":
        created_at_raw = a.get("created_at") or a.get("timestamp") or ""
        created_dt = None
        if created_at_raw:
            try:
                clean_ts = created_at_raw.replace(" IST", "").strip()
                created_dt = datetime.strptime(clean_ts[:19], "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=IST
                )
            except Exception as e_suppressed:
                logger.debug(
                    f"[scripts.remediate_live_alert_market_status] Non-fatal exception suppressed: {e_suppressed}"
                )

        # If created during trading window or created today
        should_fix = False
        if created_dt:
            # Weekday and 09:15 <= time <= 15:30 IST
            if created_dt.weekday() < 5 and (9 * 60 + 15) <= (
                created_dt.hour * 60 + created_dt.minute
            ) <= (15 * 60 + 30):
                should_fix = True
            elif created_dt.date() == now.date():
                should_fix = True
        else:
            should_fix = True

        if should_fix:
            a["market_status"] = "LIVE"
            updated_count += 1

print(f"Remediated {updated_count} alerts from SESSION_CLOSED -> LIVE.")

# 2. Write atomically
temp_path = auto_alerts_path.with_name(f"auto_alerts.json.tmp.{os.getpid()}")
with open(temp_path, "w", encoding="utf-8") as f:
    json.dump(alerts, f, indent=2)

shutil.move(str(temp_path), str(auto_alerts_path))
print(f"Successfully saved updated auto_alerts.json to {auto_alerts_path}.")

# 3. Also update SQLite WAL store if active
try:
    from engine.sqlite_store import alert_sqlite_store
    from engine.alert_model import AutoAlert

    alert_objs = [
        AutoAlert.from_dict(a) for a in alerts if isinstance(a, dict) and a.get("alert_id")
    ]
    alert_sqlite_store.save_alerts_batch(alert_objs)
    print(f"Synced {len(alert_objs)} remediated alerts to SQLite WAL store.")
except Exception as e_sql:
    print(f"SQLite sync notice: {e_sql}")

print("=== REMEDIATION COMPLETE ===")
