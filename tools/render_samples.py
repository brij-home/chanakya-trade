import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from bot.alert_templates import render_auto_alert

p = pathlib.Path.home() / ".trading_platform" / "auto_alerts.json"
alerts = json.loads(p.read_text("utf-8"))
today = [
    a
    for a in alerts
    if "2026-09-29" in a.get("created_at", "") or "20260929" in a.get("alert_id", "")
]

stages_to_sample = [
    "IGNITED",
    "T0_5_ACHIEVED",
    "T1_ACHIEVED",
    "RUNNER_EXIT",
    "INVALIDATED",
    "TIME_STOP_EXIT",
    "IN_FLIGHT_WARNING",
]
sampled = {}
for a in today:
    st = a.get("stage")
    if st in stages_to_sample and st not in sampled:
        sampled[st] = a

from dataclasses import fields
from engine.alert_model import AutoAlert

valid_keys = {f.name for f in fields(AutoAlert)}

for st, a in sampled.items():
    sym = a.get("symbol")
    atype = a.get("alert_type")
    print(f"\n=================== STAGE: {st} ({sym} | {atype}) ===================")
    try:
        alert_obj = AutoAlert(**{k: v for k, v in a.items() if k in valid_keys})
        msg = render_auto_alert(alert_obj, in_market=True)
        print(msg)
    except Exception as e:
        print(f"ERROR RENDERING: {e}")
        import traceback

        traceback.print_exc()
