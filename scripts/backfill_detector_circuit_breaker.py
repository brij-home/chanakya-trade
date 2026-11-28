"""Offline administrative backfill for detector_circuit_breaker (never runs at server startup).

Reads persisted LIVE alerts, validates conservative unscaled terminal paths via
`engine.alert_outcomes.calculate_terminal_forward_outcome`, and replays eligible outcomes
idempotently into `detector_circuit_breaker` with provenance="ALERT_FORWARD_PATH_TERMINAL".
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.alert_outcomes import calculate_terminal_forward_outcome
from engine.detector_circuit_breaker import DetectorCircuitBreaker, detector_circuit_breaker
from engine.signal_expectancy import (
    _DictAlertAdapter,
    load_persisted_alerts,
    resolve_exit_price_from_alert,
)


def backfill_detector_circuit_breaker(
    *,
    breaker: DetectorCircuitBreaker | None = None,
    alerts: list[dict] | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Replay eligible terminal forward outcomes idempotently into DetectorCircuitBreaker."""
    cb = breaker or detector_circuit_breaker
    raw_alerts = alerts if alerts is not None else load_persisted_alerts()

    recorded = 0
    already_seen = 0
    ineligible = 0
    conflicts = 0

    for item in raw_alerts:
        if (
            not bool(item.get("is_live", False))
            or str(item.get("environment", "")).upper() != "LIVE"
        ):
            ineligible += 1
            continue

        exit_p = resolve_exit_price_from_alert(item)
        if not exit_p:
            ineligible += 1
            continue

        adapter = _DictAlertAdapter(item)
        outcome = calculate_terminal_forward_outcome(adapter, exit_p)
        if outcome is None:
            ineligible += 1
            continue

        alert_id = str(item.get("alert_id") or "")
        symbol = str(item.get("symbol") or "").upper().strip()
        alert_type = str(item.get("alert_type") or "").upper().strip()
        dedup_key = f"{alert_type}:{alert_id}"

        with cb._lock:
            if dedup_key in cb._seen_outcomes:
                already_seen += 1
                continue

        result = "WIN" if outcome.realized_r > 0 else ("LOSS" if outcome.realized_r < 0 else "FLAT")
        if dry_run:
            recorded += 1
            continue

        try:
            cb.record_outcome(
                alert_id=alert_id,
                symbol=symbol,
                alert_type=alert_type,
                outcome=result,
                realized_r=outcome.realized_r,
                provenance="ALERT_FORWARD_PATH_TERMINAL",
            )
            recorded += 1
        except ValueError:
            conflicts += 1

    return {
        "scanned": len(raw_alerts),
        "recorded": recorded,
        "already_seen": already_seen,
        "ineligible": ineligible,
        "conflicts": conflicts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Offline backfill of eligible terminal outcomes into detector_circuit_breaker."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect counts without mutating detector_performance.json",
    )
    args = parser.parse_args()

    summary = backfill_detector_circuit_breaker(dry_run=args.dry_run)
    print(f"Backfill summary (dry_run={args.dry_run}): {summary}")
    for det, metrics in detector_circuit_breaker.get_all_metrics().items():
        if metrics.get("sample_count", 0) > 0:
            print(
                f"  {det:24s} n={metrics['sample_count']:3d} "
                f"W={metrics['win_rate'] * 100:5.1f}% E={metrics['expectancy']:+.3f}R "
                f"status={metrics['status']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
