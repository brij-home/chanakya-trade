"""
scripts/remediate_no_chase_boundaries.py
────────────────────────────────────────
Institutional remediation script to normalize no_chase_boundary in auto_alerts.json
and SQLite WAL store for option derivative setups.

When cash equity setups were enriched with option contracts, the no_chase_boundary
often retained the cash equity spot price (e.g. ₹180 vs option entry ₹2.8).
This script:
1. Backs up ~/.trading_platform/auto_alerts.json.
2. Deserializes all alerts through AutoAlert.from_dict() which enforces the invariant scale guard:
   - Stores the underlying cash spot limit in `spot_no_chase_boundary`
   - Sets `no_chase_boundary` to the option premium execution ceiling (+5% tolerance).
3. Synchronizes SQLite alert store and writes back auto_alerts.json atomically.
"""

import json
import logging
import os
import shutil
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engine.alert_model import AutoAlert

IST = timezone(timedelta(hours=5, minutes=30))
now_str = datetime.now(IST).strftime("%Y%m%d_%H%M%S")

base_dir = Path.home() / ".trading_platform"
auto_alerts_path = base_dir / "auto_alerts.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("remediate_no_chase")


def remediate() -> None:
    if not auto_alerts_path.exists():
        logger.warning(f"File {auto_alerts_path} does not exist. Nothing to remediate.")
        return

    # Backup
    backup_path = base_dir / f"auto_alerts.json.pre_nochase_fix_{now_str}.bak"
    shutil.copy2(auto_alerts_path, backup_path)
    logger.info(f"Created backup of auto_alerts.json at {backup_path}")

    raw_data = json.loads(auto_alerts_path.read_text(encoding="utf-8"))
    remediated_count = 0
    updated_alerts = []

    for alert_dict in raw_data:
        old_no_chase = alert_dict.get("no_chase_boundary")
        alert_obj = AutoAlert.from_dict(alert_dict)

        if alert_obj.no_chase_boundary != old_no_chase:
            remediated_count += 1
            logger.info(
                f"Remediated {alert_obj.alert_id} ({alert_obj.symbol}): "
                f"Prem: {alert_obj.option_premium} | NoChase: {old_no_chase} -> {alert_obj.no_chase_boundary} | "
                f"SpotMax: {alert_obj.spot_no_chase_boundary}"
            )

        updated_dict = alert_obj.to_dict()
        updated_alerts.append(updated_dict)

    # Atomic write to auto_alerts.json
    temp_path = auto_alerts_path.with_name(f"auto_alerts.json.tmp.{os.getpid()}")
    temp_path.write_text(json.dumps(updated_alerts, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temp_path, auto_alerts_path)
    logger.info(f"Successfully remediated {remediated_count} alerts in {auto_alerts_path}.")

    # Sync to SQLite store if available
    try:
        from engine.sqlite_store import alert_sqlite_store

        for alert_dict in updated_alerts:
            alert_obj = AutoAlert.from_dict(alert_dict)
            alert_sqlite_store.save_alert(alert_obj)
        logger.info("Successfully updated SQLite store with remediated alerts.")
    except Exception as e:
        logger.warning(f"SQLite sync skipped or encountered error: {e}")


if __name__ == "__main__":
    remediate()
