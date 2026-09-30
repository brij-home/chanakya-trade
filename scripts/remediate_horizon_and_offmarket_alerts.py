"""
scripts/remediate_horizon_and_offmarket_alerts.py
─────────────────────────────────────────────────
Remediates historical alerts in auto_alerts.json:
1. Re-tags daily/weekly SQUEEZE_BREAKDOWN setups from INTRADAY to SWING_MID.
2. Re-tags PRECURSOR_RADAR setups from INTRADAY to SWING_SHORT.
3. Re-tags 24x7 Crypto setups to ROLLING_24H.
4. Marks stale domestic intraday setups from past calendar days as EXPIRED / inactive.
5. Re-activates valid swing setups so they show as Active trades.
"""

import json
import os
import shutil
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
now = datetime.now(IST)
now_str = now.strftime("%Y%m%d_%H%M%S")
now_iso = now.strftime("%Y-%m-%d %H:%M:%S IST")

base_dir = os.path.expanduser("~/.trading_platform")
auto_alerts_path = os.path.join(base_dir, "auto_alerts.json")

print("=== REMEDIATING ALERT HORIZONS & OFF-MARKET ALERTS ===")

if not os.path.exists(auto_alerts_path):
    print("No auto_alerts.json found. Nothing to remediate.")
    exit(0)

# Create timestamped backup
backup_path = f"{auto_alerts_path}.pre_horizon_fix_{now_str}.bak"
shutil.copy2(auto_alerts_path, backup_path)
print(f"Created backup at: {backup_path}")

with open(auto_alerts_path, "r", encoding="utf-8") as f:
    alerts = json.load(f)

print(f"Loaded {len(alerts)} alerts.")

updated_count = 0
active_swings = 0
expired_intradays = 0

for a in alerts:
    aid = a.get("alert_id", "")
    atype = a.get("alert_type", "")
    sym = a.get("symbol", "")
    exch = (a.get("exchange") or "").upper()
    created_at_raw = a.get("created_at") or a.get("timestamp") or ""

    # Parse creation date
    created_dt = None
    if created_at_raw:
        try:
            clean_ts = created_at_raw.replace(" IST", "").strip()
            created_dt = datetime.fromisoformat(clean_ts).replace(tzinfo=IST)
        except Exception:
            try:
                created_dt = datetime.strptime(clean_ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
            except Exception:
                pass

    age_hours = (now - created_dt).total_seconds() / 3600.0 if created_dt else 999.0
    is_today = created_dt and (created_dt.date() == now.date())
    is_crypto = (
        exch in ("CRYPTO", "BINANCE", "DERIBIT")
        or sym.upper().endswith("USDT")
        or sym.upper().endswith("USDC")
        or atype.startswith("CRYPTO_")
    )

    modified = False

    # 1. Squeeze Breakdown -> SWING_MID
    if atype in ("SQUEEZE_BREAKDOWN", "SQUEEZE_BREAKOUT"):
        if a.get("time_horizon") != "SWING_MID":
            a["time_horizon"] = "SWING_MID"
            a["eta_label"] = a.get("eta_label") or "1–4w"
            modified = True

        # If created within last 5 calendar days and not SL/target hit, mark active!
        if age_hours <= 120.0 and a.get("stage") not in (
            "SL_HIT",
            "TARGET_ACHIEVED",
            "COMPLETED",
            "INVALIDATED",
        ):
            if not a.get("is_active"):
                a["is_active"] = True
                a["is_invalidated"] = False
                a["stage"] = "ACTIVE" if a.get("stage") in ("EXPIRED", None) else a.get("stage")
                active_swings += 1
                modified = True

    # 2. Precursor Radar -> SWING_SHORT
    elif atype == "PRECURSOR_RADAR":
        if a.get("time_horizon") != "SWING_SHORT":
            a["time_horizon"] = "SWING_SHORT"
            a["eta_label"] = "2–5d"
            modified = True
        if age_hours <= 72.0 and a.get("stage") not in (
            "SL_HIT",
            "TARGET_ACHIEVED",
            "COMPLETED",
            "INVALIDATED",
        ):
            if not a.get("is_active"):
                a["is_active"] = True
                a["is_invalidated"] = False
                a["stage"] = "ACTIVE"
                active_swings += 1
                modified = True

    # 3. Crypto -> ROLLING_24H
    elif is_crypto:
        if a.get("time_horizon") != "ROLLING_24H":
            a["time_horizon"] = "ROLLING_24H"
            a["eta_label"] = "24h"
            modified = True
        if age_hours > 24.0:
            if a.get("is_active"):
                a["is_active"] = False
                a["stage"] = "EXPIRED"
                a["is_invalidated"] = True
                a["archive_reason"] = (
                    "24x7 Crypto session expired (24h rolling limit reached). Trade closed."
                )
                modified = True
        else:
            if not a.get("is_active") and a.get("stage") not in (
                "SL_HIT",
                "TARGET_ACHIEVED",
                "COMPLETED",
                "INVALIDATED",
            ):
                a["is_active"] = True
                a["is_invalidated"] = False
                modified = True

    # 4. Multibagger -> Ensure MULTIBAGGER horizon and active
    elif atype == "MULTIBAGGER":
        a["time_horizon"] = "MULTIBAGGER"
        a["eta_label"] = a.get("eta_label") or "6–24m"
        if not a.get("is_active") and a.get("stage") not in (
            "SL_HIT",
            "TARGET_ACHIEVED",
            "COMPLETED",
            "INVALIDATED",
        ):
            a["is_active"] = True
            a["is_invalidated"] = False
            a["stage"] = "ACTIVE"
            active_swings += 1
            modified = True

    # 5. Domestic Intraday Setups (past calendar days) -> EXPIRED
    elif a.get("time_horizon") == "INTRADAY" or atype in (
        "ORB_BREAKDOWN",
        "GAMMA_BLAST",
        "OPTIONS_MOMENTUM",
        "INDEX_CONTAGION",
        "INTRADAY_BREAKDOWN_SPARK",
        "OPENING_DRIVE_IGNITION",
    ):
        if not is_today:
            if a.get("is_active"):
                a["is_active"] = False
                a["stage"] = "EXPIRED"
                a["is_invalidated"] = True
                a["archive_reason"] = (
                    "Intraday session expired (15:15 IST cutoff reached). Trade closed."
                )
                expired_intradays += 1
                modified = True

    if modified:
        updated_count += 1

with open(auto_alerts_path, "w", encoding="utf-8") as f:
    json.dump(alerts, f, indent=2, ensure_ascii=False)

print("Remediation complete!")
print(f"Total alerts updated: {updated_count}")
print(f"Active swing/multibagger setups enabled: {active_swings}")
print(f"Stale domestic intraday setups retired: {expired_intradays}")
