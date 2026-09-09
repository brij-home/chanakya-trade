import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")
p = pathlib.Path.home() / ".trading_platform" / "auto_alerts.json"
if not p.exists():
    print("No auto_alerts.json file found")
    sys.exit(0)

data = json.loads(p.read_text("utf-8"))
print(f"Total alerts in storage: {len(data)}")
for i, a in enumerate(data):
    plan = a.get("actionable_plan", {})
    trade_plan = plan.get("trade_plan", {}) if isinstance(plan, dict) else {}
    print(
        f"[{i}] {a.get('symbol')} ({a.get('alert_type')}) - Stage: {a.get('stage')} - Expired: {a.get('is_expired')} - Archived: {a.get('is_archived')}"
    )
    print(
        f"    Contract: {a.get('contract_symbol')} | Expiry: {a.get('expiry_date')} ({a.get('expiry_type')}) | Strike: {a.get('strike')} {a.get('option_type')}"
    )
    print(
        f"    Levels -> Trigger: {a.get('trigger_level')} | Target: {a.get('target_level')} | SL: {a.get('stop_loss')}"
    )
    if trade_plan:
        print(
            f"    TradePlan -> Entry: {trade_plan.get('entry_zone') or trade_plan.get('entry')} | T1: {trade_plan.get('t1_target') or trade_plan.get('t1')} | T2: {trade_plan.get('t2_target') or trade_plan.get('t2')} | T3: {trade_plan.get('t3_target') or trade_plan.get('t3')} | SL: {trade_plan.get('sl')}"
        )
        print(f"    StructureAdvice: {trade_plan.get('structure_advice')}")
        print(
            f"    NextExpiryAdvice: {trade_plan.get('next_expiry_advice') or plan.get('next_expiry_advice')}"
        )
