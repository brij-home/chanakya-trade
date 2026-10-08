"""
Remediation script for false T1_ACHIEVED milestones in auto_alerts.json.
Audits all alerts and demotes any alert where T1 was marked achieved without LTP physically reaching T1.
"""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def remediate_alerts():
    db_path = Path.home() / ".trading_platform" / "auto_alerts.json"
    if not db_path.exists():
        print(f"File not found: {db_path}")
        return

    # Create backup
    backup_path = db_path.with_suffix(".json.bak_t1_fix")
    shutil.copyfile(db_path, backup_path)
    print(f"Created backup at {backup_path}")

    with open(db_path, "r", encoding="utf-8") as f:
        alerts = json.load(f)

    remediated = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    for a in alerts:
        milestones = a.get("achieved_milestones") or []
        stage = a.get("stage")
        target_status = a.get("target_status")

        has_t1 = "T1_ACHIEVED" in milestones or stage == "T1_ACHIEVED" or target_status == "T1_HIT"
        if not has_t1:
            continue

        direction = (a.get("direction") or "BULLISH").upper()
        is_long = direction in ("BULLISH", "LONG", "BUY")
        ltp = float(a.get("ltp") or a.get("current_ltp") or 0.0)
        t1 = float(a.get("target_1") or (a.get("actionable_plan") or {}).get("target_1") or 0.0)
        entry_p = float(a.get("entry_price") or 0.0)

        # Check physical reach
        is_downward = (t1 < entry_p) if (entry_p > 0 and t1 > 0) else False
        if not entry_p and not is_long:
            is_opt = bool(
                a.get("option_type")
                or "PE" in str(a.get("contract_symbol") or "")
                or "CE" in str(a.get("contract_symbol") or "")
            )
            is_downward = not is_opt

        hit_t1 = False
        if t1 > 0 and ltp > 0:
            if not is_downward and ltp >= t1 * 0.998:
                hit_t1 = True
            elif is_downward and ltp <= t1 * 1.002:
                hit_t1 = True

        if hit_t1:
            print(f"Valid T1 for {a.get('symbol')}: LTP {ltp} crossed T1 {t1}")
            continue

        # Remediate false T1
        print(f"Remediating false T1 for {a.get('symbol')}: LTP={ltp}, T1={t1}")
        new_milestones = [m for m in milestones if m != "T1_ACHIEVED"]
        a["achieved_milestones"] = new_milestones

        if "BREAKEVEN_LOCKED" in new_milestones:
            new_stage = "BREAKEVEN_LOCKED"
        elif "DE_RISK_0_5R" in new_milestones:
            new_stage = "DE_RISK_0_5R"
        elif "T0_5_ACHIEVED" in new_milestones:
            new_stage = "T0_5_ACHIEVED"
        else:
            new_stage = "ACTIVE"

        a["stage"] = new_stage
        a["target_status"] = "ACTIVE"

        is_crypto = (
            (a.get("exchange") or "").upper() in ("BINANCE", "CRYPTO", "DERIBIT")
            or "CRYPTO" in (a.get("alert_type") or "").upper()
            or (a.get("symbol") or "").upper().endswith("USDT")
        )
        cs = "$" if is_crypto else "₹"
        sym = a.get("symbol")
        sl = float(a.get("trailing_stop") or a.get("stop_loss") or 0.0)

        if new_stage == "BREAKEVEN_LOCKED":
            a["headline"] = (
                f"🛡️ [REAL/LIVE] BREAKEVEN LOCKED (+0.8R FREE ROLL): {sym} SL → {cs}{sl:,.2f} (Downside Eliminated)"
            )
        elif new_stage == "DE_RISK_0_5R":
            a["headline"] = (
                f"🛡️ [REAL/LIVE] RISK COMPRESSED (+0.5R DE-RISK): {sym} SL → {cs}{sl:,.2f}"
            )
        else:
            a["headline"] = f"⚡ [REAL/LIVE] ACTIVE: {sym}"

        if "audit_trail" not in a or not isinstance(a["audit_trail"], list):
            a["audit_trail"] = []

        a["audit_trail"].append(
            {
                "timestamp": now_iso,
                "action": "INTEGRITY_REMEDIATION",
                "details": f"Rectified false T1_ACHIEVED to {new_stage}. LTP ({cs}{ltp:,.2f}) did not reach physical Target 1 ({cs}{t1:,.2f}).",
            }
        )

        remediated += 1

    with open(db_path, "w", encoding="utf-8") as f:
        json.dump(alerts, f, indent=2, ensure_ascii=False)

    print(f"Successfully remediated {remediated} alerts in {db_path}")


if __name__ == "__main__":
    remediate_alerts()
