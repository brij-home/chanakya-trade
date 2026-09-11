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

fno_dict = {}
for row in reader:
    if not row or len(row) < 3:
        continue
    sym = row[1].strip().upper()
    sep26 = row[2].strip()
    if sym and sep26 and sep26.isdigit():
        fno_dict[sym] = int(sep26)

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

out_path = Path(__file__).resolve().parent / "fno_master_sep26.json"
out_path.write_text(json.dumps(full_dict, indent=2), encoding="utf-8")
print(f"Saved {len(full_dict)} instruments to {out_path}")

keys = sorted(full_dict.keys())
code_lines = ["_F_AND_O_LOT_SIZES: dict[str, int] = {"]
for k in keys:
    code_lines.append(f'    "{k}": {full_dict[k]},')
code_lines.append("}")

py_path = Path(__file__).resolve().parent / "fno_code_block.py"
py_path.write_text("\n".join(code_lines), encoding="utf-8")
print(f"Generated python code block with {len(keys)} entries at {py_path}")
