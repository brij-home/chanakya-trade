---
name: multi-agent-system
description: >-
  Orchestrate, tune, and extend the multi-agent AI pipeline in chanakya-trade,
  including Smart Funnel (Stage 1-4), Bull vs Bear debates, persona agents,
  DAG orchestrator, tool definitions, and Dual-LLM routing.
---

# Multi-Agent System & Smart Funnel Runbook

## Core Architecture

The AI layer uses a multi-tier pipeline designed to maximize accuracy and minimize token consumption:

### Stage 1 — 0-Token Quant Pre-Filter
[`agent/smart_funnel.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/smart_funnel.py)

Runs deterministic, pure-Python checks on technical indicators (RSI, EMAs, Supertrend, 200-DMA), valuation (PE/PB, ROE, D/E), Sector RRG momentum tailwinds, and Forensic accounting/governance red flags. Discards unqualified stocks with explicit rejection reasons before invoking any LLMs.

### Stage 2 — Shared Macro Context
Injects India VIX, NIFTY 50 breadth, FII/DII institutional flows, USD/INR, Crude oil, Gold, and Sector RRG rotation matrix into a shared context object.

### Stage 3 — Adversarial Multi-Agent Debate & Persona Roster
[`agent/multi_agent.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/multi_agent.py), [`agent/personas.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/personas.py), [`agent/persona_agent.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/persona_agent.py)

- **Bull Analyst**: Argues long thesis, catalysts, and support levels.
- **Bear Analyst**: Argues short/risk thesis, overhead resistance, and tail risks.
- **13 Named Specialist Personas**:

| Persona | Style | Key Metrics |
| :--- | :--- | :--- |
| `buffett` | Value & Durable Moats | ROE >15%, Free Cash Flow, Margin of Safety |
| `jhunjhunwala` | India Macro Mega-trends | Domestic Scale, Operating Leverage |
| `lynch` | GARP | PEG <1.0, Ground-level Demand Insights |
| `soros` | Global Macro | Reflexivity, Currency/FII Flows |
| `munger` | Quality & Inversion | Multi-Disciplinary Mental Models |
| `forensic` | Forensic Auditor | Beneish M-Score, Altman Z''-Score, Pledging |
| `minervini` | SEPA/VCP | 8-Point Trend Template, Stage 2 Markup |
| `wyckoff` | VSA | Accumulation Spring, Sign of Strength |
| `oneil` | CAN SLIM | Institutional Sponsorship, Base Breakouts |
| `taleb` | Antifragile Convexity | Tail Risk, Defined-Risk Spreads |
| `kedia` | SMILE Framework | Indian Multibagger Discovery |
| `simons` | Statistical Arbitrage | Volatility Regimes, Mathematical EV |
| `smc` | Smart Money / ICT | Liquidity Sweeps, Order Blocks, FVGs |

- **Council Ensembles** ([`agent/persona_agent.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/persona_agent.py)):

| Council | Members | Focus |
| :--- | :--- | :--- |
| `breakout` | minervini, wyckoff, oneil, forensic | Momentum breakout validation |
| `options_sniper` | smc, taleb, simons | Options timing & risk |
| `multibagger` | kedia, buffett, munger, jhunjhunwala, forensic | Long-term compounders |
| `macro_regime` | soros, jhunjhunwala, simons, forensic | Macro-driven positioning |
| `core_value` | buffett, munger, lynch, forensic | Intrinsic value plays |

### Stage 4 — Fund Manager Synthesis
- **Debate Facilitator**: Mediates points of contention across rounds.
- **Fund Manager / Risk Gate**: Final verdict (`BUY`, `STRONG_BUY`, `HOLD`, `SELL`, `STRONG_SELL`, `AVOID`), confidence score, entry, stop-loss, target, and position size.
- **DAG Orchestration** ([`agent/dag_orchestrator.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/dag_orchestrator.py)): Parallel execution with dependency graphs.

---

## Dual-LLM Routing & Model Selection

Configured in `.env` and loaded via [`agent/core.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/core.py):

### Fast Extraction Layer (`AI_FAST_PROVIDER`, `AI_FAST_MODEL`)

Used for parallel Bull & Bear opening/rebuttal arguments, news sentiment classification, and risk debates.

| Provider | Recommended Models | Notes |
| :--- | :--- | :--- |
| **Groq** | `qwen/qwen3.8-27b` (✅ tool-calling) | **Primary choice** — ~389ms latency, supports function calling |
| **Groq** | `openai/gpt-oss-120b` | Deep reasoning fallback — ~446ms, no tool-calling |
| **Gemini** | `gemini-3.7-flash`, `gemini-3.6-flash` | Google's fast models with tool-calling |

> ⚠️ **Deprecated**: `llama-3.3-70b-versatile` is no longer available on Groq Cloud (returns `404`). Use `qwen/qwen3.8-27b` instead.

### Deep Reasoning Layer (`AI_DEEP_PROVIDER`, `AI_DEEP_MODEL`)

Used for Facilitator debate synthesis and Fund Manager final verdict.

| Provider | Recommended Models |
| :--- | :--- |
| **Groq** | `openai/gpt-oss-120b` (120B parameters, high quality) |
| **NVIDIA NIM** | `meta/llama-3.3-70b-instruct` |
| **Anthropic** | `claude-sonnet-4` |
| **OpenAI** | `gpt-4o`, `o3-mini` |

### Failover & Latency Safeguards

1. **Thread Execution Safety**: All debate futures wrapped in `try/except` with quantitative fallback defaults. 18.0s timeout per thread.
2. **Fast-Fail Auth**: Provider key errors (`api_key_invalid`, `401`) fail immediately — no retry storms.
3. **Multi-Key Pooling**: Comma-separated `GROQ_API_KEY=key1,key2` doubles throughput and provides automatic cooldown rotation.
4. **Instant SSE Progress**: Dispatch `type="debate_step", step="starting"` as Phase 2 begins to eliminate perceived UI freezes.

---

## Registered Agent Tools

All tools in [`agent/tools.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/tools.py):

| Tool | Purpose |
| :--- | :--- |
| `get_sector_rotation_matrix` | NSE sector RRG quadrants |
| `get_stock_sector_alignment` | Stock-to-sector tailwind scoring (0-100) |
| `audit_forensics` | Beneish M-Score, Altman Z-Score, Piotroski F-Score, pledging |
| `get_macro_snapshot` | Global macro metrics & sensitivities |
| `calculate_position_size` | ATR volatility risk-parity, Half-Kelly, F&O lot sizing |
| `get_quote` | Real-time stock quote (WebSocket → REST → yfinance) |
| `get_options_chain` | Full option chain with Greeks |
| `scan_multibagger_template` | Minervini 8-point, Weinstein Stage 2, VCP |
| `magic_trend_3axis` | 3-Axis Super-Investor scoring + ATR trade tickets |
| `scan_thematic_baskets` | 6 Institutional Baskets (100-Baggers, GARP, CAN SLIM, etc.) |
| `audit_portfolio_health` | Portfolio Doctor: Stage 4 dead-money, HHI, tax-loss harvesting |
| `search_web` | Web search for news & catalysts |

---

## Testing

```powershell
# Multi-agent & persona test suites
.venv\Scripts\pytest.exe tests/test_personas.py tests/test_persona_debate.py tests/test_smart_funnel.py -v

# Complete fast test suite (Windows, 4 workers)
.venv\Scripts\pytest.exe -n 4
```
