#!/usr/bin/env python3
"""
scripts/remediate_crypto_alerts.py
───────────────────────────────────
Administrative remediation script to recover active 24x7 Crypto alerts that were
erroneously marked EXPIRED by Dalal Street's 15:15 IST equity session cutoff.

Enforces AGENTS.md Invariant 18 (Zero In-Line Startup Migrations).
"""

import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Ensure root dir is in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from engine.auto_alert_engine import get_auto_alerts_file

IST = timezone(timedelta(hours=5, minutes=30))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("remediate_crypto")


def remediate_crypto_alerts() -> int:
    target_file = get_auto_alerts_file()
    if not target_file.exists():
        logger.warning(f"Auto-alerts file not found at {target_file}")
        return 0

    try:
        data = json.loads(target_file.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Failed to read {target_file}: {e}")
        return 0

    repaired = 0
    now = datetime.now(IST)

    for a in data:
        sym = str(a.get("symbol") or "").upper()
        exch = str(a.get("exchange") or "").upper()
        seg = str(a.get("segment") or "").upper()
        is_crypto = (
            exch in ("CRYPTO", "BINANCE", "DERIBIT", "COINBASE")
            or seg == "CRYPTO"
            or sym.startswith("CRYPTO:")
            or sym.endswith("USDT")
        )

        if not is_crypto:
            continue

        arch_reason = str(a.get("archive_reason") or "")
        inval_reason = str(a.get("invalidation_reason") or "")

        # Check if corrupted by 15:15 IST equity session cutoff
        if "15:15" in arch_reason or "15:15" in inval_reason:
            created_ts = (
                str(a.get("created_at") or a.get("timestamp") or "")
                .replace(" IST", "")
                .strip()[:19]
            )
            created_dt = None
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    created_dt = datetime.strptime(created_ts, fmt).replace(tzinfo=IST)
                    break
                except ValueError:
                    pass

            # Only reactivate if within the 24-hour rolling window
            if created_dt and (now - created_dt).total_seconds() < 86400:
                logger.info(
                    f"Reactivating falsely expired crypto alert: {a.get('alert_id')} ({sym})"
                )
                a["stage"] = "IGNITED"
                a["is_active"] = True
                a["is_archived"] = False
                a["is_invalidated"] = False
                a["is_expired"] = False
                a["archive_reason"] = None
                a["invalidation_reason"] = None
                a["archived_at"] = None
                a["segment"] = "CRYPTO"
                a["time_horizon"] = "INTRADAY"
                a["eta_label"] = "24h Rolling"
                repaired += 1

    if repaired > 0:
        target_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(
            f"Successfully remediated and restored {repaired} crypto alerts in {target_file}"
        )
    else:
        logger.info("No crypto alerts required remediation.")

    return repaired


if __name__ == "__main__":
    remediate_crypto_alerts()
