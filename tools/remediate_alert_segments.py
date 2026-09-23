import sys
import json
import shutil
from datetime import datetime
from pathlib import Path

p = Path.home() / ".trading_platform" / "auto_alerts.json"
if not p.exists():
    print("No auto_alerts.json found.")
    sys.exit(0)

# 1. Backup
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
bak = p.parent / f"auto_alerts.json.bak_seg_{ts}"
shutil.copyfile(p, bak)
print(f"Backed up to {bak}")

data = json.loads(p.read_text(encoding="utf-8"))
remediated_count = 0

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from engine.alert_preferences import classify_alert_segment

for a in data:
    old_seg = a.get("segment")
    new_seg = classify_alert_segment(a)
    if old_seg != new_seg:
        print(f"Fixing {a.get('symbol')} ({a.get('alert_type')}): {old_seg} -> {new_seg}")
        a["segment"] = new_seg
        if "actionable_plan" in a and isinstance(a["actionable_plan"], dict):
            a["actionable_plan"]["segment"] = new_seg
        remediated_count += 1

p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Remediation complete. Updated {remediated_count} records.")
