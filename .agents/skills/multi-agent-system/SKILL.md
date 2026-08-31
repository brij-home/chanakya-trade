---
name: multi-agent-system
description: >-
  Orchestrate, tune, and extend the multi-agent AI pipeline in chanakya-trade,
  including Smart Funnel (Stage 1-4), Bull vs Bear debates, persona agents,
  DAG orchestrator, tool definitions, and Dual-LLM routing.
---

# Multi-Agent System & Smart Funnel Runbook

## Core Architecture

The AI layer in `chanakya-trade` uses a multi-tier pipeline designed to maximize accuracy and minimize token consumption:

1. **Stage 1 — 0-Token Quant Pre-Filter** ([`agent/smart_funnel.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/smart_funnel.py)):
   - Runs deterministic, pure-Python checks on technical indicators (RSI, EMAs, Supertrend, 200-DMA), valuation (PE/PB, ROE, D/E), Sector RRG momentum tailwinds, and Forensic accounting/governance red flags.
   - Discards unqualified stocks with explicit rejection reasons before invoking any LLMs.
2. **Stage 2 — Shared Macro Context**:
   - Injects India VIX, NIFTY 50 breadth, FII/DII institutional flows, USD/INR, Crude oil, Gold, and Sector RRG rotation matrix into a shared context object.
3. **Stage 3 — Adversarial Multi-Agent Debate & Persona Roster** ([`agent/multi_agent.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/multi_agent.py), [`agent/personas.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/personas.py), [`agent/persona_agent.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/persona_agent.py)):
   - **Bull Analyst**: Argues long thesis, catalysts, and support levels.
   - **Bear Analyst**: Argues short/risk thesis, overhead resistance, and tail risks.
   - **13 Named Specialist Personas**:
     - `buffett` (Value, Durable Moats, Free Cash Flow, ROE > 15%)
     - `jhunjhunwala` (Growth-Value, India Macro Mega-trends, Domestic Scale)
     - `lynch` (GARP, PEG Ratio < 1.0, Ground-level Demand Insights)
     - `soros` (Global Macro, Reflexivity, Currency/Commodity/FII Flows)
     - `munger` (Quality, Inversion, Multi-Disciplinary Mental Models)
     - `forensic` (Forensic Auditor: Beneish M-Score, Altman Z''-Score, Piotroski F-Score, Promoter Pledge)
     - `minervini` (Mark Minervini: SEPA, 8-Point Trend Template, Stage 2 Markup, VCP Patterns)
     - `wyckoff` (Richard Wyckoff: VSA, Accumulation Phase C Spring, Sign of Strength, Absorption)
     - `oneil` (William O'Neil: CAN SLIM, Institutional Sponsorship Surge, Base Breakouts)
     - `taleb` (Nassim Nicholas Taleb: Antifragile Convexity, Tail Risk, Defined-Risk Spreads)
     - `kedia` (Vijay Kedia: SMILE Framework for Indian Multibagger Discovery)
     - `simons` (Jim Simons: Statistical Arbitrage, Volatility Regimes, Mathematical EV)
     - `smc` (Smart Money Concepts / ICT: Liquidity Sweeps, Order Blocks, FVGs, Optimal Trade Entry)
   - **Specialist Council Ensembles** ([`agent/persona_agent.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/persona_agent.py)):
     - `breakout`: `[minervini, wyckoff, oneil, forensic]`
     - `options_sniper`: `[smc, taleb, simons]`
     - `multibagger`: `[kedia, buffett, munger, jhunjhunwala, forensic]`
     - `macro_regime`: `[soros, jhunjhunwala, simons, forensic]`
     - `core_value`: `[buffett, munger, lynch, forensic]`
   - **Debate Facilitator**: Mediates points of contention across rounds.
   - **Fund Manager / Risk Gate**: Synthesizes the final verdict (`BUY`, `STRONG_BUY`, `HOLD`, `SELL`, `STRONG_SELL`, `AVOID`), confidence score, entry, stop-loss, target, and volatility risk-parity position size.
4. **DAG Orchestration** ([`agent/dag_orchestrator.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/dag_orchestrator.py)):
   - Executes parallel analyst tasks with dependency graphs and structured outputs.

---

## Dual-LLM Routing & Debate Allocation

Configured in `.env` and loaded via [`agent/core.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/core.py):

- **Fast Extraction Layer** (`AI_FAST_PROVIDER`, `AI_FAST_MODEL`):
  - Used for: Parallel Bull & Bear researcher opening and rebuttal arguments, news sentiment classification, preliminary scanning, and Aggressive/Conservative risk debates.
  - Recommended: `groq` (`qwen/qwen3.8-27b`, `llama-3.3-70b-versatile`), `gemini` (`gemini-3.7-flash`, `gemini-3.5-flash-lite`).
  - Timeout: Strict 18.0s timeout per thread with deterministic quantitative fallback.
- **Deep Reasoning Layer** (`AI_DEEP_PROVIDER`, `AI_DEEP_MODEL`):
  - Used for: Facilitator debate synthesis, Neutral calibrated risk view, and Fund Manager final verdict synthesis.
  - Recommended: `nvidia` (`meta/llama-3.3-70b-instruct`), `anthropic` (`claude-3-7-sonnet`), `openai` (`gpt-4o` / `o3-mini`).

### Phase 2 Latency & Failure Safeguards
1. **Thread Execution Safety**: All debate futures (`f_bull`, `f_bear`, `f_bull_reb`, `f_bear_reb`) must be wrapped in `try/except` fallback blocks with quantitative thesis defaults so timeouts never crash the pipeline.
2. **Fast-Fail Authentication**: Provider key errors (`api_key_invalid`, `401`, `unauthorized`) must fail immediately without cycling through fallback model candidate loops.
3. **Instant SSE Progress**: Dispatch `type="debate_step", step="starting"` as soon as Phase 2 starts to eliminate perceived UI freezes.

---

## Registered Agent Tools

All tools exposed to LLM agents are defined in [`agent/tools.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/tools.py):
- `get_sector_rotation_matrix`: NSE sector RRG quadrants (Leading/Weakening/Lagging/Improving).
- `get_stock_sector_alignment`: Stock-to-sector tailwind scoring (0-100).
- `audit_forensics`: Beneish M-Score, Altman Z-Score, Piotroski F-Score, promoter pledging.
- `get_macro_snapshot` & `get_stock_macro_linkages`: Global macro metrics & sensitivities.
- `calculate_position_size`: Volatility risk-parity, Half-Kelly, and F&O lot sizing.
- `get_quote`, `get_options_chain`, `get_pcr`, `get_dcf_valuation`, `search_web`.
- `scan_multibagger_template`: Mark Minervini 8-point Trend Template, Stan Weinstein Stage 2 Markup & VCP.
- `magic_trend_3axis`: 3-Axis (X: Moat/Forensics, Y: Growth/Value Migration, Z: Timing/Weinstein Stage 2) Super-Investor scoring and ATR trade tickets.
- `scan_thematic_baskets`: 6 Institutional Baskets (100-Baggers, Lynch GARP, Capex Surge, CAN SLIM, Order Books, Value Migration).
- `audit_portfolio_health`: Broker Portfolio Doctor for Stage 4 dead-money detection, HHI concentration, and STCG tax-loss harvesting.

---

## Verification & Testing

```powershell
# Run all multi-agent & persona test suites
.venv\Scripts\pytest.exe tests/test_personas.py tests/test_persona_debate.py tests/test_smart_funnel.py -v

# Run complete test suite (Windows safe with 4 workers)
.venv\Scripts\pytest.exe -n 4
```
