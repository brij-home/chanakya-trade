import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

p = pathlib.Path.home() / ".trading_platform" / "auto_alerts.json"
alerts = json.loads(p.read_text("utf-8"))
today = [
    a
    for a in alerts
    if "2026-09-29" in a.get("created_at", "") or "20260929" in a.get("alert_id", "")
]
index_alerts = [
    a
    for a in today
    if a.get("symbol") in ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]
    or a.get("segment") == "FNO_INDEX"
]

print(f"Total Index Alerts Today: {len(index_alerts)}\n")

for i, a in enumerate(index_alerts):
    aid = a.get("alert_id")
    atype = a.get("alert_type")
    sym = a.get("symbol")
    adir = a.get("direction")
    stage = a.get("stage")
    ltp = a.get("ltp")
    trg = a.get("trigger_level")
    sl = a.get("stop_loss")
    t1 = a.get("target_level")
    opt = a.get("option_type")
    stk = a.get("strike")
    csym = a.get("contract_symbol")
    exp = a.get("expiry_date")
    pnl = a.get("pnl_pct")
    rmult = a.get("r_multiple")
    inv = a.get("is_invalidated")
    invr = a.get("invalidation_reason")
    hl = a.get("headline")
    summ = a.get("summary")
    created = a.get("created_at")

    print(f"[{i + 1:02d}] {created} | {aid}")
    print(
        f"     Type: {atype} | Sym: {sym} | Dir: {adir} | Stage: {stage} | PnL: {pnl}% | R: {rmult}"
    )
    print(f"     Option: {opt} {stk} | Contract: {csym} | Expiry: {exp}")
    print(f"     Levels -> LTP: {ltp} | Trg: {trg} | SL: {sl} | T1: {t1}")
    if inv:
        print(f"     ⚠️ INVALIDATED: {invr}")
    print(f"     Headline: {hl}")
    print(f"     Summary:  {summ}")
    print("-" * 75)
