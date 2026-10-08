import csv
import io
import json
from pathlib import Path
from curl_cffi import requests

sess = requests.Session(impersonate="chrome124")
headers = {"User-Agent": "Mozilla/5.0"}
r = sess.get("https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv", headers=headers)
r.raise_for_status()

f = io.StringIO(r.text)
reader = csv.reader(f)
rows = list(reader)

if not rows:
    raise ValueError("Empty CSV returned by NSE")

header = rows[0]
col_map = {h.strip().upper(): i for i, h in enumerate(header) if h.strip()}

# Detect active month column (prefer OCT-26, or fallback to first expiry column index 2)
active_col = col_map.get("OCT-26", 2)
active_col_name = header[active_col].strip() if len(header) > active_col else "OCT-26"
print(f"Detected active contract column: {active_col_name} (index {active_col})")

fno_dict = {}
for row in rows[1:]:
    if not row or len(row) <= active_col:
        continue
    sym = row[1].strip().upper()
    val = row[active_col].strip()
    if sym and sym not in ("SYMBOL", "UNDERLYING") and val.isdigit():
        fno_dict[sym] = int(val)

commodities = {
    "ALUMINIUM": 5000,
    "COPPER": 2500,
    "COTTON": 25,
    "CRUDEOIL": 100,
    "CRUDEOILM": 10,
    "GOLD": 100,
    "GOLDM": 10,
    "GOLDPETAL": 1,
    "LEAD": 5000,
    "NATGASMINI": 250,
    "NATURALGAS": 1250,
    "SILVER": 30,
    "SILVERM": 5,
    "SILVERMIC": 1,
    "ZINC": 5000,
}
currencies = {
    "EURINR": 1000,
    "GBPINR": 1000,
    "JPYINR": 1000,
    "USDINR": 1000,
}
bse = {
    "SENSEX": 20,
    "BANKEX": 30,
}

full_dict = {}
full_dict.update(fno_dict)
full_dict.update(commodities)
full_dict.update(currencies)
full_dict.update(bse)
if "NIFTY" in full_dict:
    full_dict["NIFTY50"] = full_dict["NIFTY"]
if "TATAMOTORS" not in full_dict:
    full_dict["TATAMOTORS"] = 575

out_path_oct = Path(__file__).resolve().parent / "fno_master_oct26.json"
out_path_oct.write_text(json.dumps(full_dict, indent=2), encoding="utf-8")
print(f"Saved {len(full_dict)} instruments to {out_path_oct}")

# Backwards compatibility symlink/mirror
out_path_sep = Path(__file__).resolve().parent / "fno_master_sep26.json"
out_path_sep.write_text(json.dumps(full_dict, indent=2), encoding="utf-8")

keys = sorted(full_dict.keys())
code_lines = ["_F_AND_O_LOT_SIZES: dict[str, int] = {"]
for k in keys:
    code_lines.append(f'    "{k}": {full_dict[k]},')
code_lines.append("}")

py_path = Path(__file__).resolve().parent / "fno_code_block.py"
py_path.write_text("\n".join(code_lines), encoding="utf-8")
print(f"Generated python code block with {len(keys)} entries at {py_path}")
