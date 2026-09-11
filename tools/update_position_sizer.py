from pathlib import Path

fno_code = Path("tools/fno_code_block.py").read_text("utf-8").strip()

ps_path = Path("engine/position_sizer.py")
content = ps_path.read_text("utf-8")

start_marker = "# Standard F&O Lot Sizes for Indian Instruments"
end_marker = "def is_fno_symbol(symbol: str) -> bool:"

start_idx = content.find(start_marker)
end_idx = content.find(end_marker)

if start_idx == -1 or end_idx == -1:
    raise ValueError("Markers not found in engine/position_sizer.py")

new_content = (
    content[:start_idx]
    + "# Standard F&O Lot Sizes for Indian Instruments (Official NSE September 2026 Master: 216 Equity F&O + Commodities + Currencies)\n"
    + fno_code
    + "\n\n\n"
    + content[end_idx:]
)

ps_path.write_text(new_content, encoding="utf-8")
print("Successfully updated engine/position_sizer.py")
