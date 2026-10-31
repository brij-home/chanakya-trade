# chanakya-trade

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/brij-home/chanakya-trade)

Personal data analysis workspace and backtesting scripts for Indian market feeds.

## Requirements

- Python 3.11+
- Node.js 20+ (for local UI)

## Setup

1. Set up virtual environment and install dependencies:

```bash
python -m venv .venv
# Windows:
.venv\Scripts\Activate.ps1
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

2. Environment configuration:

```bash
cp .env.example .env
```

3. Run API:

```bash
python -m web.api
```

## Testing

```bash
python scripts/validate_all.py --fast
```

## Agent & IDE Guides

- [AGENTS.md](AGENTS.md) — Operational handbook, architectural invariants, and safety guidelines for AI agents.
- [CODEX.md](CODEX.md) — Local development, execution runbook, and guardrails for OpenAI / ChatGPT Codex IDE.

## Note

Personal research repository. Not financial advice or an investment recommendation.
