import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")
p = pathlib.Path.home() / ".trading_platform" / "auto_alerts.json"
if not p.exists():
    print("No auto_alerts.json found.")
    sys.exit(0)

alerts = json.loads(p.read_text("utf-8"))
today = [a for a in alerts if a.get("created_at", "").startswith("2026-09-25")]
print(f"Total alerts today (2026-09-25): {len(today)}")

index_symbols = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX", "NIFTY50", "NIFTYBANK"}
index_alerts = [
    a for a in today 
    if a.get("symbol") in index_symbols 
    or any(idx in a.get("symbol", "") for idx in ["NIFTY", "SENSEX", "BANKEX"])
    or a.get("segment") in ("INDEX", "INDEX_OPT", "INDEX_FUT", "INDICES")
]

print(f"Total index alerts today: {len(index_alerts)}")
print("=" * 120)
for i, a in enumerate(index_alerts):
    print(f"[{i+1}] {a.get('created_at')} | {a.get('symbol'):<12} | {a.get('alert_type'):<24} | {a.get('direction'):<7} | LTP: {str(a.get('ltp')):<8} | Trg: {str(a.get('trigger_level')):<8} | SL: {str(a.get('stop_loss')):<8} | Tgt: {str(a.get('target_level')):<8} | Conf: {str(a.get('confidence')):<4} | Stage: {str(a.get('stage')):<18} | PnL: {str(a.get('pnl_pct'))}% | Inv: {a.get('is_invalidated')}")

    print(f"    Confidence: {a.get('confidence')} | R-Multiple: {a.get('r_multiple')} | PnL %: {a.get('pnl_pct')}")
    print(f"    Invalidated: {a.get('is_invalidated')} | Invalidation Reason: {a.get('invalidation_reason')}")
    print(f"    Scrutiny: {a.get('scrutiny')}")
    print(f"    Actionable Plan: {a.get('actionable_plan')}")
    print("-" * 80)
