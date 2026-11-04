# Human-Readable, Crisp & Decisive Communication Standard

This rule governs all agent communication, terminal outputs, UI tooltips, card commentary, and explanations.

## 1. Zero Raw LaTeX & Cryptic Math
- **Prohibited**: Never use raw LaTeX math formatting (e.g. `$\text{OI} \ge 35{,}000$`, `$\times$`, `$\le$`, `$\approx$`, `$\Delta$`).
- **Required**: Express all quantitative thresholds in natural, human-readable English:
  - Instead of `$\text{OI} \ge 35{,}000$ and $\text{Volume} \ge 40{,}000$`, write: **"At least 35,000 Open Interest and 40,000 Volume"**.
  - Instead of `$k \ge \text{spot} \times 0.992$`, write: **"Strikes at or above current price (within 1.2%)"**.
  - Instead of `$\Delta \text{OI} \le -12\%$`, write: **"Open Interest drop of 12% or more"**.

## 2. Crisp, Articulate & Decisive
- Avoid essays, long introductory preamble, apologies, and conversational filler.
- Be decisive: state conclusions, signals, price zones, stop-losses, and risk/reward targets immediately.
- Only provide extensive long-form content when the user explicitly requests deep architectural write-ups or exhaustive background analysis.

## 3. High Scannability & Institutional Density
- Use clean bullet points, bold key terms, and compact structured tables.
- Use visual state badges where appropriate: `🟢 BUY / LONG`, `🔴 SELL / SHORT`, `⚡ TRIGGER NOW`, `🟡 STALK`, `🎯 TARGET`.
- Group information logically with clear headers so the user can scan in 3 seconds.

## 4. Trader Intuition First
- Translate mathematical mechanics into intuitive market dynamics:
  - *"Call writers in retreat / covering short positions"*
  - *"Put support collapsing under selling pressure"*
  - *"Aggressive buyer demand absorbing available supply"*

---

## 5. Emoji Density & Non-TTY Compatibility

- **Max 2 emoji per output line** in terminal context. Do not stack emoji on every bullet point — one clear status badge per section is sufficient. Overuse of emoji breaks non-TTY log parsers and looks unprofessional in structured reports.
- **Non-TTY Contexts**: File output, CI logs, and Telegram bot messages must suppress or replace emoji with plain-text equivalents. Check `sys.stdout.isatty()` before emoji-heavy outputs in scripts. API JSON responses must never contain emoji in machine-readable fields (status codes, signal types) — only in `display_text` or `commentary` fields.
- **Permitted Status Badges** (max 1 per output block):
  - `[BUY]` / `[SELL]` / `[HOLD]` for signal verdicts
  - `[LIVE]` / `[PAPER]` / `[DEMO]` for mode display
  - `[TRIGGER]` / `[STALK]` / `[STANDDOWN]` for alert status

---

## 6. Mermaid Diagram Formatting & Invariants

- **Strictly Supported Diagram Headers**: When generating visual architectures, workflows, or lifecycles in Markdown artifacts, chat responses, or documentation, use ONLY the supported Mermaid headers:
  - `flowchart TD` / `flowchart LR` / `graph TD` / `graph LR`
  - `sequenceDiagram`
  - `stateDiagram-v2` or `stateDiagram`
  - `classDiagram`
  - `erDiagram`
  - `xychart-beta`
  - `pie`
- **Strictly Prohibited Headers**: `gantt`, `gitGraph`, `journey`, `quadrantChart`, `mindmap`, `timeline`, and other unsupported Mermaid headers fail client-side rendering with `Invalid mermaid header: "<type>"`.
- **Roadmaps & Timelines**: For phase-wise roadmaps, schedules, and release plans, always use structured directed flowcharts (`flowchart TD` / `flowchart LR` with subgraphs) or Markdown tables instead of `gantt`.

