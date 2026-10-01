import json
import pathlib
import sys
from collections import Counter

# Ensure UTF-8 output
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

p = pathlib.Path.home() / ".trading_platform" / "auto_alerts.json"
if not p.exists():
    print("auto_alerts.json not found!")
    sys.exit(1)

alerts = json.loads(p.read_text("utf-8"))
today = [
    a
    for a in alerts
    if "2026-09-29" in a.get("created_at", "") or "20260929" in a.get("alert_id", "")
]

print("================================================================================")
print(f"  CHANAKYA-TRADE DEEP AUDIT: TODAY'S ALERTS (2026-09-29) - TOTAL: {len(today)}")
print("================================================================================")

# 1. Headline, Summary, Details Quality
empty_headlines = sum(1 for a in today if not a.get("headline"))
empty_summaries = sum(1 for a in today if not a.get("summary"))
empty_plans = sum(1 for a in today if not a.get("actionable_plan"))
empty_details = sum(1 for a in today if not a.get("details"))

print("\n--- 1. TEXT CONTENT QUALITY ---")
print(f"Empty Headlines: {empty_headlines}/{len(today)}")
print(f"Empty Summaries: {empty_summaries}/{len(today)}")
print(f"Empty Actionable Plans: {empty_plans}/{len(today)}")
print(f"Empty Details: {empty_details}/{len(today)}")

# 2. Telegram Dispatch & Suppression Reasons
print("\n--- 2. TELEGRAM DISPATCH & SUPPRESSION AUDIT ---")
tg_dispatched = sum(1 for a in today if a.get("telegram_dispatched"))
print(f"Telegram Dispatched: {tg_dispatched}/{len(today)}")

suppression_reasons = Counter(
    a.get("telegram_suppression_reason") or "NONE_RECORDED" for a in today
)
print("Suppression Reasons breakdown:")
for reason, count in suppression_reasons.most_common():
    print(f"  - {reason}: {count}")

# 3. Actionable Plan inspection
print("\n--- 3. ACTIONABLE PLAN INSPECTION ---")
plan_samples = []
for a in today:
    plan = a.get("actionable_plan")
    if plan and len(plan_samples) < 5:
        plan_samples.append((a.get("alert_id"), a.get("alert_type"), plan))

for aid, atype, plan in plan_samples:
    print(f"\nAlert ID: {aid} ({atype})")
    print(f"  Plan keys: {list(plan.keys()) if isinstance(plan, dict) else type(plan)}")
    print(f"  Plan content: {str(plan)[:200]}")

# 4. Levels & Direction Consistency Check
print("\n--- 4. DIRECTION VS LEVELS CONSISTENCY ---")
level_inconsistencies = []
for a in today:
    aid = a.get("alert_id")
    sym = a.get("symbol")
    atype = a.get("alert_type")
    adir = a.get("direction", "")
    trg = a.get("trigger_level")
    sl = a.get("stop_loss")
    t1 = a.get("target_level")
    opt_type = a.get("option_type")
    strike = a.get("strike")

    # Is it an option contract alert?
    is_option = opt_type is not None or strike is not None or "CE" in aid or "PE" in aid

    if trg is not None and sl is not None and t1 is not None:
        if is_option:
            # For options, whether CE or PE, buyer pays premium: SL < Trg < T1
            if sl >= trg:
                level_inconsistencies.append(
                    (aid, atype, adir, is_option, f"OPTION SL ({sl}) >= Trg ({trg})")
                )
            if t1 <= trg:
                level_inconsistencies.append(
                    (aid, atype, adir, is_option, f"OPTION T1 ({t1}) <= Trg ({trg})")
                )
        else:
            if adir == "BULLISH" or adir == "LONG":
                if sl >= trg:
                    level_inconsistencies.append(
                        (aid, atype, adir, is_option, f"BULLISH SL ({sl}) >= Trg ({trg})")
                    )
                if t1 <= trg:
                    level_inconsistencies.append(
                        (aid, atype, adir, is_option, f"BULLISH T1 ({t1}) <= Trg ({trg})")
                    )
            elif adir == "BEARISH" or adir == "SHORT":
                if sl <= trg:
                    level_inconsistencies.append(
                        (aid, atype, adir, is_option, f"BEARISH SL ({sl}) <= Trg ({trg})")
                    )
                if t1 >= trg:
                    level_inconsistencies.append(
                        (aid, atype, adir, is_option, f"BEARISH T1 ({t1}) >= Trg ({trg})")
                    )

print(f"Total level/direction inconsistencies found: {len(level_inconsistencies)}")
for aid, atype, adir, is_opt, issue in level_inconsistencies[:10]:
    print(f"  ❌ [{aid}] ({atype} | {adir} | Opt:{is_opt}): {issue}")

# 5. Options Expiry & Contract Symbol Quality
print("\n--- 5. OPTIONS METADATA QUALITY ---")
option_alerts = [
    a
    for a in today
    if a.get("option_type")
    or a.get("strike")
    or "CE" in a.get("alert_id", "")
    or "PE" in a.get("alert_id", "")
]
print(f"Total Option Alerts: {len(option_alerts)}")
missing_expiry_date = sum(1 for a in option_alerts if not a.get("expiry_date"))
missing_contract_symbol = sum(1 for a in option_alerts if not a.get("contract_symbol"))
missing_lot_size = sum(1 for a in option_alerts if not a.get("lot_size"))
print(f"Missing expiry_date: {missing_expiry_date}/{len(option_alerts)}")
print(f"Missing contract_symbol: {missing_contract_symbol}/{len(option_alerts)}")
print(f"Missing lot_size: {missing_lot_size}/{len(option_alerts)}")

# Sample option alerts
for a in option_alerts[:5]:
    print(f"\nAlert ID: {a.get('alert_id')}")
    print(
        f"  Symbol: {a.get('symbol')} | Strike: {a.get('strike')} | OptType: {a.get('option_type')}"
    )
    print(
        f"  Contract: {a.get('contract_symbol')} | Expiry: {a.get('expiry_date')} | LotSize: {a.get('lot_size')}"
    )
    print(
        f"  LTP: {a.get('ltp')} | Trg: {a.get('trigger_level')} | SL: {a.get('stop_loss')} | T1: {a.get('target_level')}"
    )
    print(f"  Headline: {a.get('headline')}")
    print(f"  Summary: {a.get('summary')}")

# 6. Headline & Summary samples across different detectors
print("\n--- 6. HEADLINE & SUMMARY SAMPLES ACROSS ALL DETECTORS ---")
seen_types = set()
for a in today:
    t = a.get("alert_type")
    if t not in seen_types:
        seen_types.add(t)
        print(f"\n>>> TYPE: {t} | Symbol: {a.get('symbol')} | Stage: {a.get('stage')}")
        print(f"    Headline: {a.get('headline')}")
        print(f"    Summary: {a.get('summary')}")
        print(
            f"    Time Horizon: {a.get('time_horizon')} | Setup Style: {a.get('setup_style')} | Entry Type: {a.get('entry_type')}"
        )
        print(f"    No Chase: {a.get('no_chase_boundary')} | R-Multiple: {a.get('r_multiple')}")
