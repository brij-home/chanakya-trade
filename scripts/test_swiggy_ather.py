"""
scripts/test_swiggy_ather.py
Step by step debugging of scan_options_momentum_breakouts for SWIGGY and ATHERENERG.
"""

import sys
import logging
from engine.auto_alert_engine import auto_alert_engine

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Setup root logger to print debug
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("engine.auto_alert_engine")
logger.setLevel(logging.DEBUG)


def test_symbol(sym):
    print(f"\n--- TESTING {sym} IN scan_options_momentum_breakouts ---")
    auto_alert_engine._override_watched_equities = True
    auto_alert_engine._watched_equities = [sym]
    auto_alert_engine._watched_indices = []

    alerts = auto_alert_engine.scan_options_momentum_breakouts()
    print(f"Resulting alerts for {sym}: {len(alerts)}")
    for a in alerts:
        print(f"  Alert: {a.headline}")


if __name__ == "__main__":
    test_symbol("SWIGGY")
    test_symbol("ATHERENERG")
