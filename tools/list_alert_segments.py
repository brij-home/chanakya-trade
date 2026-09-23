import sys
import json
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
p = Path.home() / ".trading_platform" / "auto_alerts.json"
if not p.exists():
    print("No auto_alerts.json found")
    sys.exit(0)

data = json.loads(p.read_text(encoding="utf-8"))
print(f"Total alerts: {len(data)}")
for a in data:
    sym = a.get("symbol", "")
    atype = a.get("alert_type", "")
    seg = a.get("segment", "")
    contract = a.get("contract_symbol")
    op_type = a.get("option_type")
    strike = a.get("strike")
    headline = a.get("headline", "")
    print(
        f"{sym:<12} | type={atype:<24} | seg={str(seg):<12} | contract={str(contract):<16} | op={str(op_type):<4} | strike={str(strike):<6} | {headline[:40]}"
    )
