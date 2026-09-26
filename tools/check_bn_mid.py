import json, pathlib, sys
sys.stdout.reconfigure(encoding="utf-8")
p = pathlib.Path.home() / ".trading_platform" / "auto_alerts.json"
alerts = json.loads(p.read_text("utf-8"))
for a in alerts:
    if a.get("symbol") in ("BANKNIFTY", "MIDCPNIFTY"):
        print(f"Symbol: {a.get('symbol')} | Created: {a.get('created_at')} | Stage: {a.get('stage')} | LTP: {a.get('ltp')} | PnL: {a.get('pnl_pct')}% | Inv: {a.get('is_invalidated')} | Reason: {a.get('invalidation_reason')}")
