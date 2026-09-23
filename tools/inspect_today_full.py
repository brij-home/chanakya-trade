import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")
p = pathlib.Path.home() / ".trading_platform" / "auto_alerts.json"
data = json.loads(p.read_text("utf-8"))

today = "2026-09-15"
today_alerts = [a for a in data if a.get("created_at", "").startswith(today)]

start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
end = int(sys.argv[2]) if len(sys.argv) > 2 else len(today_alerts)

print(f"=== TODAY'S ALERTS ({len(today_alerts)} total, showing {start} to {end}) ===")
for i in range(start, min(end, len(today_alerts))):
    a = today_alerts[i]

    print("=" * 80)
    print(
        f"[{i}] Alert ID: {a.get('alert_id')} | Sym: {a.get('symbol')} | Type: {a.get('alert_type')} | Stage: {a.get('stage')}"
    )
    print(
        f"    Created: {a.get('created_at')} | Updated: {a.get('updated_at')} | TriggeredAt: {a.get('triggered_at')}"
    )
    print(
        f"    Direction: {a.get('direction')} | Segment: {a.get('segment')} | Exchange: {a.get('exchange')}"
    )
    print(
        f"    LTP: {a.get('ltp')} | Trigger: {a.get('trigger_level')} | Target: {a.get('target_level')} | SL: {a.get('stop_loss')}"
    )
    print(
        f"    Trailing Stop: {a.get('trailing_stop')} | Should Trail: {a.get('should_trail')} | Trailing Decision: {a.get('trailing_decision')}"
    )
    print(
        f"    Milestones: {a.get('achieved_milestones')} | Target Status: {a.get('target_status')} | R-Multiple: {a.get('r_multiple')} | PnL %: {a.get('pnl_pct')}"
    )
    print(
        f"    Invalidated: {a.get('is_invalidated')} | Reason: {a.get('invalidation_reason')} | At: {a.get('invalidated_at')}"
    )
    print(
        f"    In-Flight Warning: Sent={a.get('in_flight_warning_sent')}, Reason={a.get('in_flight_warning_reason')}, At={a.get('in_flight_warning_at')}"
    )
    print(
        f"    Contract: {a.get('contract_symbol')} | Strike: {a.get('strike')} | OptionType: {a.get('option_type')} | Expiry: {a.get('expiry_date')}"
    )
    print(f"    ActionablePlan: {json.dumps(a.get('actionable_plan'), indent=2)}")
