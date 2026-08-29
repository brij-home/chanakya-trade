# ChanakyaTrade

**AI-Powered Strategic Quant Terminal & Multi-Agent Intelligence for Indian Markets** -- 7 AI analyst agents analyze stocks in parallel, debate bull vs bear, and deliver actionable trade plans with precise entries, invalidation stops, and quantitative targets.

> Institutional-grade quantitative research, Smart Money Concepts (SMC), Volume Profile, and multi-agent AI debates for Indian equity and derivatives markets (**NSE, BSE, NFO, MCX**).

[![CI](https://github.com/brij-home/chanakya-trade/actions/workflows/ci.yml/badge.svg)](https://github.com/brij-home/chanakya-trade/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

<p align="center">
  <img src="docs/images/chanakya-dashboard.png" alt="ChanakyaTrade — Institutional AI Trading Dashboard" width="850" />
</p>

<p align="center">
  <em>Live Multi-Agent AI Reasoning, Order Flow Analysis, and Quantitative Execution Panel for Indian Markets.</em>
</p>

---

## 📸 Platform Previews

| Multi-Agent Bull vs Bear Debate | Quantitative Options & GEX Terminal |
|:---:|:---:|
| ![ChanakyaTrade Debate](docs/images/chanakya-debate.png) | ![ChanakyaTrade GEX](docs/images/chanakya-gex.png) |
| *Adversarial Bull/Bear debate with Facilitator consensus* | *Gamma Exposure flip points, 0DTE IV smile & delta hedging* |

---

## ⚡ Key Architectural Capabilities

### 1. 🧠 Multi-Agent AI Reasoning & Smart Funnel
- **Stage 1 (0-Token Deterministic Filter)**: Instant quantitative pre-screening across 500+ NSE stocks (Minervini Stage 2 Markup, VCP, RRG Momentum, Beneish M-score).
- **Stage 2 (Macro & Sector Rotation)**: Real-time India VIX, NIFTY breadth, FII/DII institutional liquidity flows, and JdK RS-Ratio sector graphs.
- **Stage 3 (Adversarial Persona Debate)**: Bull vs Bear analysts with legendary investor personas (`Jhunjhunwala`, `Buffett`, `Lynch`, `Soros`, `Munger`, `Forensic Auditor`) synthesized by an AI Fund Manager.

### 2. 📊 Smart Money Concepts (SMC) & Volume Price Analysis
- **Fractal Swings & Break of Structure (BOS)**: Automatic identification of `CHoCH` / `MSS` structural reversals.
- **Unmitigated Order Blocks (OB) & Fair Value Gaps (FVG)**: Institutional liquidity sweeps, buy-side / sell-side liquidity pools.
- **Volume Profile (VPA)**: Point of Control (`POC`), Value Area High (`VAH`), Value Area Low (`VAL`), and Wyckoff stopping volume detection.

### 3. 🎯 Quantitative Options & Risk Management
- **Gamma Exposure (GEX)**: Real-time Zero Gamma Flip Point calculation, Call Wall resistance, Put Support, and 0DTE/Weekly skew analytics.
- **Volatility Risk-Parity Sizing**: Dynamic position sizing adjusted for $1.5 \times \text{ATR}$ risk budgets and Indian F&O contract lot constraints.
- **Active Trade Lifecycle**: Multi-tier trailing stops (`2R Breakeven`, `Chandelier ATR 3.0x`, and daily 20-EMA trail).

### 4. 🔌 Broker Connectivity & Open Execution
- **Unified Multi-Broker Routing**: Seamless dual-broker separation (free live tick data via Fyers API v3, live execution via Zerodha Kite, Angel One, Groww, Upstox, Dhan).
- **Paper Trading Safety First**: Default `TRADING_MODE=PAPER` guardrail with realistic simulated fills, slippage, and STT/SEBI turnover fee modeling.

---

## 🚀 Quickstart Guide

### Prerequisites
- Python 3.11 or higher
- Git

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/brij-home/chanakya-trade.git
cd chanakya-trade

# 2. Create and activate a virtual environment
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On macOS / Linux:
source .venv/bin/activate

# 3. Install in editable mode with development dependencies
pip install -e ".[dev]"
```

### Configuration

Copy the example environment file and add your broker or AI provider credentials:

```bash
cp .env.example .env
```

*(ChanakyaTrade operates seamlessly out-of-the-box in demo mode even without live broker keys).*

### Launching the Platform

```bash
# 1. Launch Interactive Terminal REPL
python -m app.main --no-broker

# 2. Launch Textual Split-Panel TUI
python -m app.main --tui

# 3. Launch FastAPI Sidecar Backend (Port 8765)
python -m uvicorn web.api:app --host 127.0.0.1 --port 8765 --reload
```

---

## 🧪 Testing & Verification

Run the test suite across unit, schema, and strategy modules:

```bash
# Run fast deterministic test suite
pytest tests/ -v -m "not network and not slow" -n auto
```

---

## 📄 License & Attribution

This project is open-source software licensed under the **[MIT License](LICENSE)**.

Copyright (c) 2025 Brijendra Agarwal.
