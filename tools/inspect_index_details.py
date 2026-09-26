import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")
p = pathlib.Path.home() / ".trading_platform" / "auto_alerts.json"
alerts = json.loads(p.read_text("utf-8"))
today = [a for a in alerts if a.get("created_at", "").startswith("2026-09-25")]

index_symbols = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"}
index_alerts = [a for a in today if a.get("symbol") in index_symbols]

print(f"Total index alerts: {len(index_alerts)}")
for a in index_alerts:
    print("=" * 80)
    print(f"SYMBOL: {a.get('symbol')} | ALERT_TYPE: {a.get('alert_type')} | DIR: {a.get('direction')}")
    print(f"ID: {a.get('alert_id')} | CREATED: {a.get('created_at')} | STAGE: {a.get('stage')}")
    print(f"HEADLINE: {a.get('headline')}")
    print(f"SUMMARY: {a.get('summary')}")
    print(f"LTP: {a.get('ltp')} | TRIGGER: {a.get('trigger_level')} | SL: {a.get('stop_loss')} | T1: {a.get('target_level')}")
    print(f"CONTRACT: {a.get('contract_symbol')} | STRIKE: {a.get('strike')} | EXPIRY: {a.get('expiry_date')}")
    print(f"CONFIDENCE: {a.get('confidence')} | R_MULTIPLE: {a.get('r_multiple')} | PNL_PCT: {a.get('pnl_pct')}")
    print(f"IN_FLIGHT_WARNING: sent={a.get('in_flight_warning_sent')} reason={a.get('in_flight_warning_reason')}")
    print(f"IS_INVALIDATED: {a.get('is_invalidated')} | REASON: {a.get('invalidation_reason')}")
    print("ACTIONABLE PLAN:")
    print(json.dumps(a.get("actionable_plan"), indent=2))
