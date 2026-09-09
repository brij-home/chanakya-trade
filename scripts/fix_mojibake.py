"""
scripts/fix_mojibake.py
───────────────────────
Repairs all known Mojibake (UTF-8 bytes misread as Windows-1252 / ISO-8859-1)
across the repository to ensure all text rendered for humans is authentic UTF-8.
"""

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

REPLACEMENTS = [
    # Emojis corrupted by UTF-8 bytes -> Windows-1252
    ("ðŸ’Ž", "💎"),
    ("ðŸš€", "🚀"),
    ("ðŸ —ï¸ ", "🏗️"),
    ("ðŸ —", "🏗️"),
    ("ðŸ›¡ï¸ ", "🛡️"),
    ("ðŸ›¡", "🛡️"),
    ("ðŸ“ˆ", "📈"),
    ("ðŸ ¢", "🏢"),
    ("ðŸ§®", "🧮"),
    ("ðŸŽ¯", "🎯"),
    ("ðŸ ‚", "🐂"),
    ("ðŸ °", "🏰"),
    ("ðŸ” ", "🔍"),
    ("ðŸŒŠ", "🌊"),
    ("ðŸ›’", "🛒"),
    ("ðŸ ›ï¸ ", "🏛️"),
    ("ðŸ ›", "🏛️"),
    ("ðŸŒ ", "🌐"),
    ("âš¡", "⚡"),
    ("â€”", "—"),
    ("â”€", "─"),
]


def fix_file(file_path: Path):
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Skipping {file_path}: {e}")
        return 0

    lines = content.splitlines(keepends=True)
    new_lines = []
    total_changes = 0
    for i, line in enumerate(lines):
        prev_chunk = "".join(lines[max(0, i - 6) : i])
        if "icon" in line and ("ð" in line or "â" in line):
            if "jhunjhunwala" in prev_chunk:
                line = '                "icon": "🐂",\n'
                total_changes += 1
            elif "buffett" in prev_chunk:
                line = '                "icon": "🏰",\n'
                total_changes += 1
            elif "forensic" in prev_chunk:
                line = '                "icon": "🔍",\n'
                total_changes += 1
            elif "munger" in prev_chunk:
                line = '                "icon": "🏛️",\n'
                total_changes += 1
            elif "macro_regime" in prev_chunk:
                line = '                "icon": "🌐",\n'
                total_changes += 1
            elif "core_value" in prev_chunk:
                line = '                "icon": "🏛️",\n'
                total_changes += 1
        new_lines.append(line)
    content = "".join(new_lines)

    total_changes = 0
    for old, new in REPLACEMENTS:
        if old in content:
            c = content.count(old)
            content = content.replace(old, new)
            total_changes += c
            print(f"  [{file_path.name}] {c}x {repr(old)} -> {repr(new)}")

    if total_changes > 0 or content != file_path.read_text(encoding="utf-8"):
        file_path.write_text(content, encoding="utf-8")
        print(f"Fixed mojibake occurrences in {file_path}")

    return total_changes


def main():
    total = 0
    target_dirs = ["web", "agent", "analysis", "engine", "market", "macos-app/src", "app", "config"]
    for td in target_dirs:
        p = REPO_ROOT / td
        if not p.exists():
            continue
        for ext in ["*.py", "*.js", "*.jsx", "*.json", "*.md"]:
            for f in p.rglob(ext):
                total += fix_file(f)

    print(f"\nCompleted: Fixed {total} total mojibake instances.")


if __name__ == "__main__":
    main()
