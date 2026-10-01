import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.universe import THEMATIC_PRESETS
from engine.position_sizer import _F_AND_O_LOT_SIZES

backend_fno = set(THEMATIC_PRESETS.get("fno_universe", {}).get("symbols", []))

print(f"Backend F&O count: {len(backend_fno)}")
print(f"Position sizer lot sizes count: {len(_F_AND_O_LOT_SIZES)}")

with open("macos-app/src/renderer/src/data/universeData.js", "r", encoding="utf-8") as f:
    text = f.read()

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

print(f"Parsed frontend universeData.js entries: {len(frontend_entries)}")

# 1. Stocks in frontend marked isFO: false, but are in backend F&O or have lotSize > 1
gaps = []
for sym, data in frontend_entries.items():
    if sym in backend_fno and not data["isFO"]:
        gaps.append((sym, "In backend F&O list but isFO: false", data))
    elif (data["lotSize"] or 0) > 1 and not data["isFO"]:
        gaps.append((sym, "Has lotSize > 1 in frontend but isFO: false", data))
    elif sym in _F_AND_O_LOT_SIZES and not data["isFO"]:
        gaps.append((sym, "In _F_AND_O_LOT_SIZES but isFO: false", data))

print(f"\n=== AUDIT GAPS (isFO: False when should be True): {len(gaps)} ===")
for g in gaps:
    print(g)

# 2. Stocks in backend_fno that are missing entirely from universeData.js
missing_from_frontend = [s for s in sorted(backend_fno) if s not in frontend_entries]
print(f"\n=== Backend F&O stocks missing from universeData.js: {len(missing_from_frontend)} ===")
if missing_from_frontend:
    print(missing_from_frontend)

# 3. Stocks in _F_AND_O_LOT_SIZES missing from frontend
missing_from_lot_sizes = [
    s
    for s in sorted(_F_AND_O_LOT_SIZES.keys())
    if s not in frontend_entries
    and s not in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX")
]
print(
    f"\n=== _F_AND_O_LOT_SIZES stocks missing from universeData.js: {len(missing_from_lot_sizes)} ==="
)
if missing_from_lot_sizes:
    print(missing_from_lot_sizes)

# 4. Check if any frontend entry is marked isFO: true, but missing lotSize or has lotSize == 1
invalid_fo = []
for sym, data in frontend_entries.items():
    if data["isFO"]:
        if not data["lotSize"] or data["lotSize"] <= 1:
            invalid_fo.append((sym, "isFO is True but lotSize <= 1 or missing", data))

print(f"\n=== Frontend entries with isFO: true but invalid lotSize: {len(invalid_fo)} ===")
for item in invalid_fo:
    print(item)
