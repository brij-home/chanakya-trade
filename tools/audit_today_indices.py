import sys, os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.abspath("."))

from engine.auto_alert_engine import auto_alert_engine
from engine.alert_scrutiny import alert_scrutiny_auditor

alerts = auto_alert_engine.get_alerts(limit=500)
today = [a for a in alerts if getattr(a, "created_at", "").startswith("2026-09-25")]
print(f"Total alerts loaded from engine: {len(alerts)}, today: {len(today)}")

for a in today:
    sym = getattr(a, "symbol", "")
    print(f"Checking today alert: {sym} | {a.alert_type} | {a.alert_id}")
    if any(idx in sym for idx in ["NIFTY", "SENSEX", "BANKEX"]):
        print("=" * 80)
        print(f"Auditing {a.symbol} | {a.alert_type} | {a.headline}")
        print(f"Recorded levels: LTP={a.ltp}, Trigger={a.trigger_level}, SL={a.stop_loss}, T1={a.target_level}")
        passed, reason, flags = alert_scrutiny_auditor.verify_tier1_sanity(a)
        print(f"Tier-1 Sanity: passed={passed}, reason={reason}")
        
        scrutiny = alert_scrutiny_auditor.scrutinize_alert(a, timeout=3.0)
        print(f"Scrutiny Result: Status={scrutiny.status}, Score={scrutiny.score}, Model={scrutiny.auditor_model}")
        print(f"Rejection Reason: {scrutiny.rejection_reason}")
        print(f"Trap Warning: {scrutiny.trap_risk_warning}")
