import json
import pathlib
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
IST = timezone(timedelta(hours=5, minutes=30))

p = pathlib.Path.home() / ".trading_platform" / "auto_alerts.json"
alerts = json.loads(p.read_text("utf-8"))
today = [
    a
    for a in alerts
    if "2026-09-29" in a.get("created_at", "") or "20260929" in a.get("alert_id", "")
]

print("================================================================================")
print(f"  QUANTITATIVE PERFORMANCE AUDIT: 2026-09-29 ({len(today)} ALERTS)")
print("================================================================================")

stats = defaultdict(
    lambda: {
        "total": 0,
        "t1_hit": 0,
        "t0_5_hit": 0,
        "t2_hit": 0,
        "runner_exit": 0,
        "time_stop_exit": 0,
        "sl_invalidated": 0,
        "pnl_list": [],
        "r_list": [],
        "durations_min": [],
    }
)


def parse_time(ts_str):
    if not ts_str:
        return None
    ts_str = ts_str.replace(" IST", "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(ts_str, fmt).replace(tzinfo=IST)
        except ValueError:
            pass
    return None


for a in today:
    atype = a.get("alert_type", "UNKNOWN")
    st = stats[atype]
    st["total"] += 1

    stage = a.get("stage")
    tstat = a.get("target_status")
    milestones = a.get("achieved_milestones", [])

    pnl = a.get("pnl_pct", 0.0) or 0.0
    r_mult = a.get("r_multiple", 0.0) or 0.0
    st["pnl_list"].append(pnl)
    st["r_list"].append(r_mult)

    if (
        "T1_ACHIEVED" in milestones
        or stage == "T1_ACHIEVED"
        or tstat == "T1_ACHIEVED"
        or stage == "RUNNER_EXIT"
    ):
        st["t1_hit"] += 1
    if "T0_5_ACHIEVED" in milestones or stage in ("T0_5_ACHIEVED", "DE_RISK_0_5R"):
        st["t0_5_hit"] += 1
    if "T2_ACHIEVED" in milestones or stage == "T2_ACHIEVED" or tstat == "T2_ACHIEVED":
        st["t2_hit"] += 1
    if stage == "RUNNER_EXIT":
        st["runner_exit"] += 1
    if stage == "TIME_STOP_EXIT":
        st["time_stop_exit"] += 1
    if a.get("is_invalidated") or stage == "INVALIDATED":
        # Was it invalidated due to SL or something else?
        st["sl_invalidated"] += 1

    t_start = parse_time(a.get("created_at"))
    t_end = parse_time(a.get("invalidated_at") or a.get("archived_at") or a.get("updated_at"))
    if t_start and t_end:
        dur = (t_end - t_start).total_seconds() / 60.0
        if 0 < dur < 1000:
            st["durations_min"].append(dur)

print(
    f"{'Detector':<26} {'Tot':<4} {'T1%':<6} {'T2':<3} {'Runner':<7} {'TimeStop':<9} {'Inval':<6} {'AvgPnL%':<9} {'Avg R':<7} {'AvgDur(m)'}"
)
print("-" * 88)

tot_alerts = 0
tot_t1 = 0
tot_runner = 0
tot_timestop = 0
tot_inval = 0
all_pnl = []
all_r = []

for atype, st in sorted(stats.items(), key=lambda x: x[1]["total"], reverse=True):
    cnt = st["total"]
    tot_alerts += cnt
    tot_t1 += st["t1_hit"]
    tot_runner += st["runner_exit"]
    tot_timestop += st["time_stop_exit"]
    tot_inval += st["sl_invalidated"]
    all_pnl.extend(st["pnl_list"])
    all_r.extend(st["r_list"])

    t1_pct = (st["t1_hit"] / cnt * 100) if cnt else 0.0
    avg_pnl = (sum(st["pnl_list"]) / cnt) if cnt else 0.0
    avg_r = (sum(st["r_list"]) / cnt) if cnt else 0.0
    avg_dur = (sum(st["durations_min"]) / len(st["durations_min"])) if st["durations_min"] else 0.0

    print(
        f"{atype:<26} {cnt:<4} {t1_pct:>5.1f}% {st['t2_hit']:<3} {st['runner_exit']:<7} {st['time_stop_exit']:<9} {st['sl_invalidated']:<6} {avg_pnl:>7.2f}% {avg_r:>6.2f}R {avg_dur:>7.1f}m"
    )

print("-" * 88)
overall_t1_pct = (tot_t1 / tot_alerts * 100) if tot_alerts else 0.0
overall_pnl = (sum(all_pnl) / len(all_pnl)) if all_pnl else 0.0
overall_r = (sum(all_r) / len(all_r)) if all_r else 0.0
print(
    f"{'OVERALL':<26} {tot_alerts:<4} {overall_t1_pct:>5.1f}% -   {tot_runner:<7} {tot_timestop:<9} {tot_inval:<6} {overall_pnl:>7.2f}% {overall_r:>6.2f}R"
)
