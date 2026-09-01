# Project Instructions

## Git commits
- Do NOT include "Co-Authored-By: Claude" or any Claude/Anthropic attribution in commit messages
- Keep commit messages concise and focused on what changed
- Follow conventional commits format (feat:, fix:, docs:, style:, etc.)

## Workflow
- Spec -> Tests -> Code (always)
- Create GitHub issues for things not fixed immediately
- Run tests before committing

## Project context
- AI-Powered Strategic Quant Terminal & Multi-Agent Intelligence for Indian Markets (NSE/BSE/NFO/MCX)
- Terminal CLI + macOS Electron app
- FastAPI sidecar on port 8765
- Brokers: Fyers (data, free), Zerodha (execution), Angel One, Groww, Upstox, Dhan
- AI providers: Groq, Gemini, Claude, OpenAI, NVIDIA NIM, OpenRouter

## Safety & Truthfulness Guardrails
- **Paper Default**: Default to `TRADING_MODE=PAPER`. Live execution requires `ALLOW_LIVE_TRADING=1` and `assert_live_execution_allowed()`.
- **Fail-Closed Execution**: Ambiguous broker responses or timeouts must transition to `UNKNOWN_FREEZE` with no fabricated IDs.
- **Truthful Modes**: Mode mapping via `/api/mode` is server-authoritative (`OBSERVE -> DEMO`, `SIMULATE -> PAPER`, `EXECUTE -> LIVE`).
- **Zero Fabrication**: Security 360 dossiers emit explicit `UNAVAILABLE`/`PARTIAL` states on missing live data. Reconciliation requires authenticated broker snapshots.
- **Validation**: Always run `.venv\Scripts\python.exe scripts/validate_all.py --fast` before committing.
