import json
from pathlib import Path

fno_data = json.loads(Path("tools/fno_master_sep26.json").read_text("utf-8"))
# Filter to equity/index F&O symbols (exclude commodities and currencies)
non_eq = {
    "ALUMINIUM", "COPPER", "COTTON", "CRUDEOIL", "CRUDEOILM", "GOLD", "GOLDM",
    "GOLDPETAL", "LEAD", "NATGASMINI", "NATURALGAS", "SILVER", "SILVERM", "SILVERMIC",
    "ZINC", "EURINR", "GBPINR", "JPYINR", "USDINR", "NIFTY50"
}
fno_symbols = sorted([k for k in fno_data.keys() if k not in non_eq])

univ_path = Path("analysis/universe.py")
content = univ_path.read_text("utf-8")

start_marker = '    "fno_universe": {\n'
end_marker = '    },\n}\n\n# ── Multi-Asset Taxonomies'

start_idx = content.find(start_marker)
end_idx = content.find(end_marker)

if start_idx == -1 or end_idx == -1:
    raise ValueError("Markers not found in analysis/universe.py")

symbols_block = '    "fno_universe": {\n'
symbols_block += '        "name": "⚡ Complete Liquid F&O Universe",\n'
symbols_block += f'        "description": "All {len(fno_symbols)} official NSE derivatives contracts (Sep-2026 Master).",\n'
symbols_block += '        "symbols": [\n'
for s in fno_symbols:
    symbols_block += f'            "{s}",\n'
symbols_block += '        ],\n'

new_content = content[:start_idx] + symbols_block + content[end_idx:]
univ_path.write_text(new_content, encoding="utf-8")
print(f"Successfully updated analysis/universe.py with {len(fno_symbols)} F&O symbols")
