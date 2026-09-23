"""
scripts/cross_reference_alerts.py
Deep dive into:
1. Hit rate / outcomes of today's 112 alerts (Target reached vs Invalidated vs Stagnated).
2. For top gainers/losers: did we alert them? If so, when and what type? If not, why?
3. Why did 44 alerts fire at 09:21:11 IST? What triggered them?
"""

import json
import sys
from collections import Counter, defaultdict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from engine.auto_alert_engine import AUTO_ALERTS_FILE


def main():
    with open(AUTO_ALERTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    today = "2026-09-22"
    today_alerts = [a for a in data if a.get("timestamp", "").startswith(today)]

    print(f"Total alerts on {today}: {len(today_alerts)}")

    # 1. Outcomes breakdown
    outcomes = Counter()
    status_by_type = defaultdict(lambda: Counter())

    for a in today_alerts:
        status = a.get("target_status", "UNKNOWN")
        is_inv = a.get("is_invalidated", False)
        milestones = a.get("achieved_milestones", [])
        atype = a.get("alert_type", "UNKNOWN")

        outcome_key = status
        if is_inv:
            outcome_key = f"INVALIDATED ({a.get('invalidation_reason', 'unknown')})"
        elif "FINAL_ACHIEVED" in milestones or "T3_ACHIEVED" in milestones:
            outcome_key = "RUNNER_MAX_TARGET_HIT"
        elif "T2_ACHIEVED" in milestones:
            outcome_key = "T2_HIT"
        elif "T1_ACHIEVED" in milestones:
            outcome_key = "T1_HIT"
        elif status == "PENDING":
            outcome_key = "PENDING / STAGNATED"

        outcomes[outcome_key] += 1
        status_by_type[atype][outcome_key] += 1

    print("\n=== OVERALL OUTCOMES OF TODAY'S ALERTS ===")
    for k, cnt in outcomes.most_common():
        print(f"  {k:45}: {cnt} ({cnt / len(today_alerts) * 100:.1f}%)")

    print("\n=== OUTCOMES BY ALERT TYPE ===")
    for atype, counts in status_by_type.items():
        print(f"\n--- {atype} (Total: {sum(counts.values())}) ---")
        for st, c in counts.most_common():
            print(f"    {st:40}: {c}")

    # 2. Check top gainers & losers
    top_movers = [
        ("RBLBANK", "+5.17%"),
        ("SWIGGY", "+4.16%"),
        ("PIIND", "+3.80%"),
        ("PAGEIND", "+3.34%"),
        ("SOLARINDS", "+3.24%"),
        ("COALINDIA", "+3.21%"),
        ("BANDHANBNK", "+3.18%"),
        ("IDEA", "+3.11%"),
        ("BSE", "+2.34%"),
        ("KAYNES", "-5.34%"),
        ("CONCOR", "-4.12%"),
        ("VOLTAS", "-3.62%"),
        ("ATHERENERG", "-3.09%"),
        ("PGEL", "-3.05%"),
        ("BLUESTARCO", "-2.56%"),
        ("OIL", "-2.37%"),
        ("ABB", "-2.07%"),
        ("CUMMINSIND", "-2.06%"),
        ("DIXON", "-1.99%"),
    ]

    print("\n=== CHECKING IF TOP MOVERS WERE ALERTED TODAY ===")
    for sym, move in top_movers:
        alerts = [a for a in today_alerts if a.get("symbol") == sym]
        if alerts:
            print(f"✓ {sym:12} ({move:7}): {len(alerts)} alerts fired:")
            for al in alerts:
                ts = al.get("timestamp", "")[11:19]
                print(
                    f"    [{ts}] {al.get('alert_type')} | {al.get('direction')} | LTP={al.get('ltp')} | SL={al.get('stop_loss')} | Status={al.get('target_status')} | Achieved={al.get('achieved_milestones')}"
                )
        else:
            print(f"✗ {sym:12} ({move:7}): MISSED (0 alerts)")

    # 3. Analyze 09:21:11 burst
    burst_0921 = [a for a in today_alerts if a.get("timestamp", "").startswith("2026-09-22 09:21")]
    print(f"\n=== 09:21:11 BURST ANALYSIS ({len(burst_0921)} alerts) ===")
    burst_types = Counter(a.get("alert_type") for a in burst_0921)
    print("Types in 09:21 burst:", burst_types)
    sample_burst = burst_0921[0]
    print("Sample 09:21 alert headline:", sample_burst.get("headline"))
    print("Sample 09:21 alert summary:", sample_burst.get("summary"))
    print("Sample 09:21 metrics:", sample_burst.get("metrics"))


if __name__ == "__main__":
    main()
