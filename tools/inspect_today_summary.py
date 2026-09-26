import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")
p = pathlib.Path.home() / ".trading_platform" / "auto_alerts.json"
alerts = json.loads(p.read_text("utf-8"))
today = [a for a in alerts if a.get("created_at", "").startswith("2026-09-25")]
print(f"Total alerts today (2026-09-25): {len(today)}")

for i, a in enumerate(today):
    sym = a.get("symbol", "")
    atype = a.get("alert_type", "")
    adir = a.get("direction", "")
    ltp = a.get("ltp")
    trg = a.get("trigger_level")
    sl = a.get("stop_loss")
    tgt = a.get("target_level")
    conf = a.get("confidence")
    stage = a.get("stage")
    pnl = a.get("pnl_pct")
    inv = a.get("is_invalidated")
    time_str = a.get("created_at")
    print(f"[{i+1:02d}] {time_str} | {sym:<12} | {atype:<24} | {adir:<7} | LTP: {str(ltp):<7} | Trg: {str(trg):<7} | SL: {str(sl):<7} | Tgt: {str(tgt):<7} | Conf: {str(conf):<3} | Stage: {str(stage):<18} | PnL: {str(pnl):<6} | Inv: {inv}")
