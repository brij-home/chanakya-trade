"""
tools/remediate_weekend_false_alerts.py
──────────────────────────────────────
Offline remediation script to identify and invalidate false intraday setups generated on weekends
or exchange trading holidays when the domestic market was closed.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from config.constants import IST_ZONE as IST
from market.calendar import is_trading_day


def remediate_weekend_false_alerts():
    db_path = Path.home() / ".trading_platform" / "auto_alerts.json"
    if not db_path.exists():
        print(f"File not found: {db_path}")
        return

    ts_slug = datetime.now(IST).strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.with_suffix(f".json.bak_weekend_{ts_slug}")
    shutil.copyfile(db_path, backup_path)
    print(f"Created safety backup at {backup_path}")

    with open(db_path, "r", encoding="utf-8") as f:
        alerts = json.load(f)

    remediated = 0
    now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    for a in alerts:
        ca = a.get("created_at") or ""
        if not ca:
            continue
        try:
            created_date = datetime.strptime(ca[:10], "%Y-%m-%d").date()
        except Exception:
            continue

        exch = (a.get("exchange") or "NSE").upper()
        # Crypto markets trade 24x7 legitimately
        if exch in ("CRYPTO", "BINANCE", "DERIBIT") or (a.get("alert_type") or "").startswith(
            "CRYPTO_"
        ):
            continue

        # Check if the exchange was open on created_date
        if is_trading_day(created_date, exchange=exch):
            continue

        # If it was a weekend or holiday, only verified off-market EOD research scans (e.g. at 00:01) are permissible.
        # Daytime index loop breakouts (e.g. SQUEEZE_BREAKOUT at 13:15) are false weekend triggers.
        time_horizon = (a.get("time_horizon") or "").upper()
        alert_type = a.get("alert_type") or ""
        is_intraday = time_horizon in (
            "INTRADAY",
            "SCALP",
            "INTRADAY_SCALP_ONLY",
        ) or alert_type in (
            "AFTERNOON_THRUST",
            "OPENING_DRIVE",
            "OPENING_DRIVE_IGNITION",
            "INDEX_MICRO_SCALP",
            "INDEX_CALL_SETUP",
            "INDEX_PUT_SETUP",
            "GAMMA_BLAST",
            "FAST_SCALP",
        )
        is_daytime_false_loop = alert_type == "SQUEEZE_BREAKOUT" and "-1315-" in a.get(
            "alert_id", ""
        )

        # Invalidate any intraday alert or daytime loop trigger created on a weekend/holiday
        if (is_intraday or is_daytime_false_loop) and not a.get("is_invalidated"):
            a["is_invalidated"] = True
            a["stage"] = "INVALIDATED"
            a["target_status"] = "INVALIDATED"
            a["is_archived"] = True
            a["invalidation_reason"] = (
                f"WEEKEND_CLOSED_MARKET_FALSE_TRIGGER: Created on non-trading day ({created_date})"
            )
            audit = a.get("audit_trail") or []
            audit.append(
                {
                    "timestamp": now_iso,
                    "event_type": "REMEDIATED_WEEKEND_TRIGGER",
                    "message": f"Invalidated false weekend trigger created on closed market date {created_date}",
                    "actor": "REMEDIATION_SCRIPT",
                    "stage": "INVALIDATED",
                }
            )
            a["audit_trail"] = audit
            remediated += 1
            print(
                f"Remediated false weekend alert: {a.get('alert_id')} ({a.get('symbol')} - {alert_type})"
            )

    if remediated > 0:
        with open(db_path, "w", encoding="utf-8") as f:
            json.dump(alerts, f, indent=2, ensure_ascii=False)
        print(f"\nSuccessfully remediated {remediated} false weekend alert(s) in {db_path}.")
    else:
        print("\nNo false weekend alerts found needing remediation.")


if __name__ == "__main__":
    remediate_weekend_false_alerts()
