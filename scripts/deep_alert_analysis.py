"""
scripts/deep_alert_analysis.py
Detailed analysis of all alerts from 2026-09-22:
- Grouping by alert_type, timestamp, symbol, action, entry, targets
- Examining raw JSON fields of alerts
- Checking market movements today
"""

import json
from collections import Counter, defaultdict
from datetime import datetime
from engine.auto_alert_engine import AUTO_ALERTS_FILE

def analyze():
    with open(AUTO_ALERTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    today = "2026-09-22"
    today_alerts = [a for a in data if a.get("timestamp", "").startswith(today)]
    print(f"Total alerts today ({today}): {len(today_alerts)}")

    # Time distribution
    time_bins = defaultdict(int)
    type_counts = Counter()
    action_counts = Counter()
    symbols_alerted = Counter()
    missing_entry = 0
    missing_action = 0
    missing_targets = 0

    for a in today_alerts:
        ts = a.get("timestamp", "")
        # HH:MM
        if len(ts) >= 16:
            hh_mm = ts[11:16]
            time_bins[hh_mm] += 1
        atype = a.get("alert_type", "UNKNOWN")
        type_counts[atype] += 1
        action = a.get("action", "") or "BLANK"
        action_counts[action] += 1
        sym = a.get("symbol", "UNKNOWN")
        symbols_alerted[sym] += 1
        if a.get("entry_price") is None:
            missing_entry += 1
        if not a.get("action"):
            missing_action += 1
        if a.get("target_1") is None:
            missing_targets += 1

    print("\nAlert Types Breakdown:")
    for at, cnt in type_counts.most_common():
        print(f"  {at}: {cnt}")

    print("\nActions Breakdown:")
    for ac, cnt in action_counts.most_common():
        print(f"  {ac}: {cnt}")

    print(f"\nMissing Data Metrics:")
    print(f"  Missing Entry: {missing_entry}/{len(today_alerts)}")
    print(f"  Missing Action: {missing_action}/{len(today_alerts)}")
    print(f"  Missing Target 1: {missing_targets}/{len(today_alerts)}")

    print("\nTime of Alerts (grouped by 1-5 mins):")
    for tm, cnt in sorted(time_bins.items()):
        print(f"  {tm}: {cnt} alerts")

    print("\nSample Alerts Details (first 3 and any non-09:21 alerts):")
    non_morning = [a for a in today_alerts if not a.get("timestamp", "").startswith("2026-09-22 09:21")]
    print(f"Non-09:21 alerts count: {len(non_morning)}")

    for idx, a in enumerate(today_alerts[:3] + non_morning[:10]):
        print(f"\n--- Alert #{idx+1} ---")
        for k in ["alert_id", "timestamp", "symbol", "alert_type", "action", "entry_price", "stop_loss", "target_1", "target_2", "target_3", "target_status", "is_invalidated", "invalidation_reason", "achieved_milestones", "confidence", "horizon", "detector_source", "notes", "scrutiny_details"]:
            if k in a:
                print(f"  {k}: {a[k]}")

if __name__ == "__main__":
    analyze()
