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
- AI-Powered Strategic Quant Terminal & Multi-Agent Intelligence for Indian Markets (`NSE/BSE/NFO/BFO/MCX`), default discovery profile `FNO_ONLY` (`config.discovery_policy`)
- Terminal CLI (`app/`) + Electron/React desktop app (`macos-app/`)
- FastAPI sidecar on configurable port (default `8765` via `DEFAULT_SIDECAR_PORT` / `getBaseUrl()`)
- Brokers: Fyers Prime (primary data + execution), Flattrade Pi (secondary data/execution standby failover), Zerodha, Angel One, Groww, Upstox, Dhan, Stoxkart, Kotak Neo, m.Stock
- AI providers: Groq (`qwen/qwen3.8-27b`, `openai/gpt-oss-120b`), Gemini (`gemini-3.8-flash`), Anthropic (`claude-sonnet-4-7`), OpenAI (`gpt-4o`), NVIDIA NIM, OpenRouter

## Safety & Truthfulness Guardrails
- **Paper Default & Owner Qualification**: Default to `TRADING_MODE=PAPER` (`SIMULATE`). Live broker execution strictly requires `TRADING_MODE=EXECUTE`, `ALLOW_LIVE_TRADING=1`, owner-controlled `LIVE_EXECUTION_QUALIFIED=1`, and pilot qualification passing `assert_live_execution_allowed()` + `validate_pretrade()`.
- **Fail-Closed Execution**: Ambiguous broker responses or timeouts transition to `UNKNOWN_FREEZE` with `broker_order_id=None`. `OrderSocket` updates reconcile atomically via `apply_fyers_stream_order_update()` / `apply_fyers_stream_trade_fill()` with strict account isolation.
- **Truthful Modes & Provenance**: Mode mapping via `/api/mode` is server-authoritative (`OBSERVE -> DEMO`, `SIMULATE -> PAPER`, `EXECUTE -> LIVE`). Missing/stale live feeds fail closed (`UNAVAILABLE`/`DEGRADED`/`PARTIAL_DATA`); never fabricate synthetic quotes or VIX baselines.
- **Validation**: Run targeted `pytest` during active iteration and `python scripts/validate_all.py --fast` / `npm.cmd --prefix macos-app test -- --run` before committing.
