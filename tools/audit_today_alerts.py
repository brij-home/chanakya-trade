import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")
p = pathlib.Path.home() / ".trading_platform" / "auto_alerts.json"
data = json.loads(p.read_text("utf-8"))

today = "2026-09-15"
today_alerts = [a for a in data if a.get("created_at", "").startswith(today)]

print(f"Auditing {len(today_alerts)} alerts from today ({today}):\n")

issues_found = []

for i, a in enumerate(today_alerts):
    sym = a.get("symbol")
    aid = a.get("alert_id")
    atype = a.get("alert_type")
    stage = a.get("stage")
    direction = a.get("direction")
    ltp = a.get("ltp")
    trigger = a.get("trigger_level")
    target = a.get("target_level")
    sl = a.get("stop_loss")
    plan = a.get("actionable_plan") or {}
    opt_plan = plan.get("option_plan") or {}

    alert_issues = []

    # Check 1: In-flight warning on EARLY_WARNING
    if a.get("in_flight_warning_sent") and a.get("triggered_at") is None:
        alert_issues.append(f"IN-FLIGHT WARNING fired on un-ignited setup (triggered_at is None, reason: {a.get('in_flight_warning_reason')})")

    # Check 2: Missing or broken Option Plan
    if opt_plan:
        if opt_plan.get("entry_premium") == 0.0 or opt_plan.get("entry_premium") is None:
            alert_issues.append(f"Option plan has 0.0 or None entry_premium: {opt_plan.get('contract_symbol')}")
        if opt_plan.get("sl_premium") in (0.0, 0.05, 0.1) and (opt_plan.get("entry_premium") or 0) > 1.0:
            alert_issues.append(f"Option stop loss premium is suspiciously low: {opt_plan.get('sl_premium')}")

    # Check 3: Plan option_entry string
    if plan.get("option_contract") and not plan.get("option_entry"):
        alert_issues.append(f"Plan specifies option_contract '{plan.get('option_contract')}' but option_entry is null/empty")

    # Check 4: Direction and level monotonicity
    if direction == "BULLISH":
        if trigger and sl and sl >= trigger:
            alert_issues.append(f"BULLISH stop_loss (₹{sl}) >= trigger (₹{trigger})")
        if trigger and target and target <= trigger:
            alert_issues.append(f"BULLISH target (₹{target}) <= trigger (₹{trigger})")
    elif direction == "BEARISH":
        if trigger and sl and sl <= trigger:
            alert_issues.append(f"BEARISH stop_loss (₹{sl}) <= trigger (₹{trigger})")
        if trigger and target and target >= trigger:
            alert_issues.append(f"BEARISH target (₹{target}) >= trigger (₹{trigger})")

    # Check 5: Trade plan inside actionable_plan
    trade_plan = plan.get("trade_plan")
    if not trade_plan:
        alert_issues.append("actionable_plan has NO trade_plan structured object")

    # Check 6: LTP freshness / None
    if ltp is None or ltp == 0:
        alert_issues.append("LTP is missing or zero")

    # Check 7: R:R ratio quality
    rr = plan.get("risk_reward") or (trade_plan.get("risk_reward") if isinstance(trade_plan, dict) else None)
    if not rr:
        alert_issues.append("No Risk:Reward ratio in plan")

    status_str = "OK" if not alert_issues else f"{len(alert_issues)} ISSUE(S)"
    print(f"[{i:02d}] {sym:<12} | {atype:<23} | {stage:<18} | {status_str}")
    for iss in alert_issues:
        print(f"     ❌ {iss}")
        issues_found.append((sym, atype, iss))

print(f"\nTotal issues across today's alerts: {len(issues_found)}")
