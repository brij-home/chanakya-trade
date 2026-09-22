"""
scripts/inspect_today_alerts_fixed.py
"""

import json
import sys
from collections import Counter, defaultdict
from engine.auto_alert_engine import AUTO_ALERTS_FILE

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


def main():
    with open(AUTO_ALERTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    today = "2026-09-22"
    today_alerts = [a for a in data if a.get("timestamp", "").startswith(today)]
    print(f"Total alerts today ({today}): {len(today_alerts)}\n")

    # Let's inspect alert types and directions
    type_dir_counter = Counter()
    for a in today_alerts:
        atype = a.get("alert_type", "")
        direction = a.get("direction", "")
        stage = a.get("stage", "")
        type_dir_counter[(atype, direction, stage)] += 1

    print("Alerts by (Type, Direction, Stage):")
    for (atype, direction, stage), cnt in type_dir_counter.most_common():
        print(f"  {atype:25} | {direction:10} | {stage:15} : {cnt}")

    # Inspect options alerts specifically
    print("\n" + "="*80)
    print("OPTIONS ALERTS SAMPLE (First 5):")
    opt_alerts = [a for a in today_alerts if "OPTION" in a.get("alert_type", "") or "GAMMA" in a.get("alert_type", "")]
    for a in opt_alerts[:5]:
        print(f"ID: {a.get('alert_id')} | Symbol: {a.get('symbol')} | Type: {a.get('alert_type')} | Dir: {a.get('direction')}")
        print(f"  Strike: {a.get('strike')} | OptType: {a.get('option_type')} | Contract: {a.get('contract_symbol')}")
        print(f"  LTP: {a.get('ltp')} | Trigger: {a.get('trigger_level')} | Target: {a.get('target_level')} | SL: {a.get('stop_loss')}")
        print(f"  Option Prem: {a.get('option_premium')} | Spot: {a.get('underlying_spot')}")
        print(f"  Actionable Plan: {a.get('actionable_plan')}")
        print("-" * 50)

    # Inspect stock equity / precursor alerts
    print("\n" + "="*80)
    print("EQUITY / NON-FNO / PRECURSOR / SQUEEZE ALERTS:")
    eq_alerts = [a for a in today_alerts if "OPTION" not in a.get("alert_type", "") and "GAMMA" not in a.get("alert_type", "")]
    for a in eq_alerts:
        print(f"Time: {a.get('timestamp')} | ID: {a.get('alert_id')} | Symbol: {a.get('symbol')} | Type: {a.get('alert_type')} | Dir: {a.get('direction')}")
        print(f"  LTP: {a.get('ltp')} | Trigger: {a.get('trigger_level')} | Target: {a.get('target_level')} | SL: {a.get('stop_loss')}")
        print(f"  Status: {a.get('target_status')} | Milestones: {a.get('achieved_milestones')} | Invalidated: {a.get('is_invalidated')} ({a.get('invalidation_reason')})")
        print(f"  Plan: {a.get('actionable_plan')}")
        print("-" * 50)

if __name__ == "__main__":
    main()
