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
