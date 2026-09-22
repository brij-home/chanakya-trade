"""
scripts/inspect_today_alerts.py
Inspects today's alerts (2026-09-22) and assesses market data for the session.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from engine.auto_alert_engine import AUTO_ALERTS_FILE, auto_alert_engine

def main():
    print(f"AUTO_ALERTS_FILE: {AUTO_ALERTS_FILE}")
    if not AUTO_ALERTS_FILE.exists():
        print("Alerts file does not exist!")
        return

    with open(AUTO_ALERTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"Total alerts in file: {len(data)}")

    today_str = "2026-09-22"
    today_alerts = []
    other_dates = {}

    for a in data:
        ts = a.get("timestamp", "")
        date_prefix = ts[:10]
        other_dates[date_prefix] = other_dates.get(date_prefix, 0) + 1
        if ts.startswith(today_str):
            today_alerts.append(a)

    print("\nDate distribution of alerts:")
    for d, c in sorted(other_dates.items()):
        print(f"  {d}: {c} alerts")

    print(f"\nTotal alerts for today ({today_str}): {len(today_alerts)}")
    
    # If today_alerts is empty, let's also check the most recent date
    target_alerts = today_alerts
    if not target_alerts and data:
        most_recent_date = sorted(other_dates.keys())[-1]
        print(f"No alerts for {today_str}, inspecting most recent date: {most_recent_date}")
        target_alerts = [a for a in data if a.get("timestamp", "").startswith(most_recent_date)]

    print(f"\nDetailed Breakdown of Alerts ({len(target_alerts)}):")
    print("-" * 120)
    for idx, a in enumerate(target_alerts):
        sym = a.get("symbol", "")
        atype = a.get("alert_type", "")
        action = a.get("action", "")
        ts = a.get("timestamp", "")
        entry = a.get("entry_price")
        sl = a.get("stop_loss")
        t1 = a.get("target_1")
        t2 = a.get("target_2")
        conf = a.get("confidence")
        status = a.get("target_status")
        is_inv = a.get("is_invalidated")
        inv_reason = a.get("invalidation_reason")
        achieved = a.get("achieved_milestones", [])
        horizon = a.get("horizon")
        notes = a.get("notes", "")[:120] if a.get("notes") else ""
        
        # Calculate R:R if available
        rr_str = "N/A"
        try:
            if entry and sl and t1 and float(entry) != float(sl):
                risk = abs(float(entry) - float(sl))
                reward = abs(float(t1) - float(entry))
                rr_str = f"1:{reward/risk:.2f}"
        except Exception:
            pass

        print(f"[{idx+1}] {ts} | {sym} | {atype} | {action} | Entry: {entry} | SL: {sl} | T1: {t1} | RR: {rr_str} | Conf: {conf}%")
        print(f"    Status: {status} | Invalidated: {is_inv} ({inv_reason}) | Milestones: {achieved} | Horizon: {horizon}")
        if notes:
            print(f"    Notes: {notes}")
        scrutiny = a.get("scrutiny_details")
        if scrutiny:
            print(f"    Scrutiny: {scrutiny.get('verdict')} | Score: {scrutiny.get('composite_score')} | Reason: {scrutiny.get('reason')}")
        print("-" * 120)

if __name__ == "__main__":
    main()
