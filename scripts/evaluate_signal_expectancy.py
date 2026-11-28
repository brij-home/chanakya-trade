"""CLI report for held-out post-cost walk-forward signal expectancy evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.signal_expectancy import compute_signal_expectancy_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate post-cost signal expectancy.")
    parser.add_argument("--json", action="store_true", help="Emit full JSON report.")
    parser.add_argument("--include-test", action="store_true", help="Include TEST/SIMULATION rows.")
    args = parser.parse_args()

    report = compute_signal_expectancy_report(include_test=args.include_test)
    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    ov = report["overall"]
    print(
        f"Evaluated {report['evaluated_trades']}/{report['total_alerts_scanned']} alerts "
        f"| Net E={ov['net_expectancy_r']:+.3f}R | Gross E={ov['gross_expectancy_r']:+.3f}R "
        f"| Win%={ov['win_rate_pct']}% | TimeStop%={ov['time_stop_rate_pct']}% "
        f"| Qualification={ov['qualification']}"
    )
    for section in (
        "by_detector",
        "by_segment",
        "by_session_bucket",
        "by_rvol_bucket",
        "by_confluence_bucket",
    ):
        print(f"\n[{section}]")
        for key, stats in report[section].items():
            print(
                f"  {key:24s} n={stats['sample_count']:3d} cal={stats['calibratable_count']:3d} "
                f"net={stats['net_expectancy_r']:+.3f}R gross={stats['gross_expectancy_r']:+.3f}R "
                f"W={stats['win_rate_pct']:5.1f}% TS={stats['time_stop_rate_pct']:5.1f}% "
                f"[{stats['qualification']}]"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
