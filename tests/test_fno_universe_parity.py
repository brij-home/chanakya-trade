"""
tests/test_fno_universe_parity.py
──────────────────────────────────
Verifies that all F&O universe assets have 100% metadata parity between
backend canonical definitions (THEMATIC_PRESETS, _F_AND_O_LOT_SIZES)
and frontend universeData.js.
Ensures no stock with a valid lotSize > 1 is erroneously marked isFO: false.
"""

import re
from pathlib import Path
from analysis.universe import THEMATIC_PRESETS


def test_fno_universe_frontend_parity():
    backend_fno = set(THEMATIC_PRESETS.get("fno_universe", {}).get("symbols", []))
    assert len(backend_fno) >= 200, f"Backend F&O universe expected >= 200, got {len(backend_fno)}"

    universe_js_path = Path("macos-app/src/renderer/src/data/universeData.js")
    assert universe_js_path.exists(), "universeData.js must exist"

    text = universe_js_path.read_text(encoding="utf-8")

    # Match each object { ... }
    pattern = re.compile(r"\{\s*symbol:\s*['\"](?P<symbol>[^'\"]+)['\"](?P<body>.*?)\}", re.DOTALL)
    frontend_entries = {}
    for m in pattern.finditer(text):
        sym = m.group("symbol")
        body = m.group("body")
        is_fo_match = re.search(r"isFO:\s*(true|false)", body)
        lot_size_match = re.search(r"lotSize:\s*(\d+)", body)
        is_fo = (is_fo_match.group(1) == "true") if is_fo_match else False
        lot_size = int(lot_size_match.group(1)) if lot_size_match else None
        frontend_entries[sym] = {"isFO": is_fo, "lotSize": lot_size}

    # 1. Verify zero gaps: no stock with lotSize > 1 or in backend_fno should have isFO: false
    gaps = []
    for sym, data in frontend_entries.items():
        if sym in backend_fno and not data["isFO"]:
            gaps.append((sym, "In backend F&O but isFO: false", data))
        elif (data["lotSize"] or 0) > 1 and not data["isFO"]:
            gaps.append((sym, "Has lotSize > 1 but isFO: false", data))

    assert not gaps, f"Found {len(gaps)} F&O universe gaps in universeData.js: {gaps}"

    # 2. Verify all single-stock F&O equities exist in frontend
    missing = [
        s for s in backend_fno if s not in frontend_entries and s not in ("NIFTY", "NIFTY50")
    ]
    assert not missing, f"Missing F&O stocks in frontend: {missing}"

    # 3. Verify key stocks mentioned by user
    for critical_sym in (
        "SONACOMS",
        "MCX",
        "TATAMOTORS",
        "DMART",
        "SWIGGY",
        "HINDZINC",
        "INOXWIND",
    ):
        assert critical_sym in frontend_entries, f"{critical_sym} must be present in frontend"
        assert frontend_entries[critical_sym]["isFO"] is True, (
            f"{critical_sym} must have isFO: true"
        )
        assert frontend_entries[critical_sym]["lotSize"] > 1, (
            f"{critical_sym} must have valid lotSize"
        )
