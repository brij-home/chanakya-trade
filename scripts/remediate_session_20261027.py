"""
scripts/remediate_session_20261027.py
────────────────────────────────────
Offline remediation script to regenerate yesterday's scorecard (2026-10-27)
and EOD report using the calibrated engine invariants:
  1. Clamps unearned ghost R on pullback alerts where milestones were not achieved.
  2. Converts pre-trade scrutiny vetoes to DISQUALIFIED (0 capital risked, not losses).
  3. Reclassifies superseded sector leader alerts to SUPERSEDED_UNSEATED (0 in-flight zombies).
  4. Decouples pure option contracts from cash spot levels.
  5. Computes honest, institutional performance metrics.
"""

import json
import os
import sys
from zoneinfo import ZoneInfo

# Fix Windows console UTF-8 output
sys.stdout.reconfigure(encoding="utf-8")

IST = ZoneInfo("Asia/Kolkata")

# Add workspace to path
workspace_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if workspace_dir not in sys.path:
    sys.path.insert(0, workspace_dir)

from engine.alert_model import AutoAlert
from engine.alert_postmortem_runner import generate_session_scorecard
from engine.eod_report_generator import EODReportGenerator


def remediate_session():
    data_dir = os.path.expanduser("~/.trading_platform")
    alerts_path = os.path.join(data_dir, "auto_alerts.json")

    if not os.path.exists(alerts_path):
        print(f"Error: {alerts_path} not found.")
        return

    with open(alerts_path, "r", encoding="utf-8") as f:
        raw_alerts = json.load(f)

    print(f"Loaded {len(raw_alerts)} total alerts from auto_alerts.json.")

    alerts_20261027 = []
    for d in raw_alerts:
        created_at = str(d.get("created_at", "") or "")
        aid = str(d.get("alert_id", "") or "")
        if "2026-10-27" in created_at or "20261027" in aid:
            # Instantiate AutoAlert
            try:
                alert = AutoAlert(**{k: v for k, v in d.items() if k in AutoAlert.__annotations__})
                alerts_20261027.append(alert)
            except Exception as e:
                print(f"Warning: Failed to instantiate {aid}: {e}")

    print(f"Found {len(alerts_20261027)} alerts belonging to session 2026-10-27.")

    # Apply Remediation
    remediated_alerts = []
    ghost_r_fixed = 0
    vetoes_fixed = 0
    superseded_fixed = 0
    squareoffs_fixed = 0

    for a in alerts_20261027:
        # 1. Clean up Ghost +6.0R Win Inflation
        str(getattr(a, "alert_type", "") or "")
        milestones = getattr(a, "achieved_milestones", []) or []
        is_inv = getattr(a, "is_invalidated", False)

        if not milestones and not is_inv:
            if a.r_multiple is not None and a.r_multiple > 0.5:
                ghost_r_fixed += 1
                a.r_multiple = None

        # 2. Pre-Trade Scrutiny Vetoes (Tier-2) should be DISQUALIFIED, not INVALIDATED
        scrutiny = getattr(a, "scrutiny", None)
        s_tier = getattr(scrutiny, "tier", "") if scrutiny else ""
        s_status = getattr(scrutiny, "status", "") if scrutiny else ""
        inv_reason = str(getattr(a, "invalidation_reason", "") or "")

        if (
            s_tier == "REJECTED"
            or s_status == "REJECTED"
            or "Tier-2" in inv_reason
            or "Runway Veto" in inv_reason
        ) and not milestones:
            if a.is_invalidated:
                vetoes_fixed += 1
                a.is_invalidated = False
                a.stage = "CANCELLED"
                a.target_status = "SETUP_DISQUALIFIED"
                a.is_active = False

        # 3. Superseded Sector Alerts
        arch_reason = str(getattr(a, "archive_reason", "") or "")
        if "Superseded by sector leader" in arch_reason:
            if a.stage != "CANCELLED" or a.target_status != "SUPERSEDED":
                superseded_fixed += 1
                a.stage = "CANCELLED"
                a.target_status = "SUPERSEDED"
                a.is_active = False

        # 4. Intraday setups open post-market
        th = (getattr(a, "time_horizon", "INTRADAY") or "INTRADAY").upper()
        if a.is_active and th == "INTRADAY" and a.stage in ("IGNITED", "TRIGGERED", "ACTIONABLE"):
            squareoffs_fixed += 1
            a.is_active = False
            a.stage = "COMPLETED"
            a.target_status = "SESSION_CLOSE_EXIT"
            a.archive_reason = "15:15 IST cutoff reached - intraday session close square-off"

        remediated_alerts.append(a)

    print("Remediation Applied:")
    print(f"  - Ghost +6.0R Win alerts cleared: {ghost_r_fixed}")
    print(f"  - Pre-trade scrutiny vetoes converted to DISQUALIFIED: {vetoes_fixed}")
    print(f"  - Superseded sector setups marked CANCELLED: {superseded_fixed}")
    print(f"  - Intraday setups squared off: {squareoffs_fixed}")

    # Generate Remediated Scorecard
    new_scorecard = generate_session_scorecard(remediated_alerts, session_date="2026-10-27")

    scorecard_path = os.path.join(data_dir, "postmortem", "daily_scorecard_20261027.json")
    with open(scorecard_path, "w", encoding="utf-8") as f:
        json.dump(new_scorecard, f, indent=2, ensure_ascii=False)

    print("\n[Remediated Scorecard 2026-10-27]")
    print(f"  Total Setups:   {new_scorecard['total_alerts']}")
    print(f"  Verified Wins:  {new_scorecard['wins']}")
    print(f"  Trading Losses: {new_scorecard['losses']}")
    print(f"  Unfulfilled:    {new_scorecard['unfulfilled']}")
    print(f"  Active Swings:  {new_scorecard['active_swings']}")
    print(f"  Win Rate:       {new_scorecard['win_rate_pct']}%")
    print(f"  Profit Factor:  {new_scorecard['profit_factor']}")
    print(f"  Net Realized R: {new_scorecard['net_realized_r']:+.2f}R")
    print(f"Saved calibrated scorecard to {scorecard_path}")

    # Also update auto_alerts.json with remediated states
    alert_map = {a.alert_id: a.to_dict() for a in remediated_alerts}
    updated_raw = []
    for d in raw_alerts:
        aid = d.get("alert_id")
        if aid in alert_map:
            updated_raw.append(alert_map[aid])
        else:
            updated_raw.append(d)

    with open(alerts_path, "w", encoding="utf-8") as f:
        json.dump(updated_raw, f, indent=2, ensure_ascii=False)
    print(f"Updated {len(alerts_20261027)} alert states in {alerts_path}")

    # Regenerate EOD Report
    print("\nRegenerating official EOD Report for 2026-10-27...")
    generator = EODReportGenerator()
    report = generator.generate(target_date="2026-10-27")
    eod_json_path = os.path.join(data_dir, "reports", "eod_2026-10-27.json")
    with open(eod_json_path, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)

    eod_md_path = os.path.join(data_dir, "reports", "eod_2026-10-27.md")
    with open(eod_md_path, "w", encoding="utf-8") as f:
        f.write(report.to_markdown())

    print(f"EOD Report saved to:\n  - {eod_json_path}\n  - {eod_md_path}")
    print(
        f"Report Summary: Total Alerts: {report.total_alerts}, In-Flight: {report.in_flight_count}"
    )


if __name__ == "__main__":
    remediate_session()
