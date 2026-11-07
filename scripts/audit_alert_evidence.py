"""Read-only alert provenance inventory. Never rewrites historical trading evidence."""

import json
from pathlib import Path
from config.paths import app_data_path


def audit(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw if isinstance(raw, list) else raw.get("alerts", [])
    result = {"records": len(rows), "active": 0, "explicitly_unverified": 0, "active_unverified": 0}
    for row in rows:
        active = bool(row.get("is_active", False))
        evidence = [row.get("environment", "")]
        for payload in (row.get("metrics", {}), row.get("details", {})):
            if isinstance(payload, dict):
                evidence.extend(
                    payload.get(k, "")
                    for k in ("source", "data_source", "provenance", "data_state")
                )
        invalid = row.get("is_live") is False or any(
            any(tag in str(v).upper() for tag in ("SYNTHETIC", "MOCK", "TEST", "SIMULATION"))
            for v in evidence
        )
        result["active"] += active
        result["explicitly_unverified"] += invalid
        result["active_unverified"] += active and invalid
    result["limitation"] = (
        "Unmarked records are not certified authentic by this inventory. No history was modified."
    )
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=app_data_path("auto_alerts.json"))
    args = parser.parse_args()
    print(json.dumps(audit(args.path), indent=2))
