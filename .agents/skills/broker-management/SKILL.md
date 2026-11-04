---
name: broker-management
description: >-
  Add, test, and maintain Indian broker integrations (Zerodha Kite, Fyers,
  Angel One SmartAPI, Groww, Upstox, Dhan, Stoxkart, and Mock Broker),
  handling OAuth2 redirects, TOTP authentication, and unified order/quote mapping.
---

# Broker Integration & Session Management Runbook

> **Current safety contract (1 November 2026):** Read `docs/SAFETY_CONTRACTS.md` before changes. Its execution qualification, provenance and instrument-authority rules supersede older fallback examples below. Never route actionable real-market alerts to synthetic Mock data when feeds fail. Depth queues are not traded volume; rolling tick VWAP is not exchange session ATP; unknown OHLC/OI fields stay unavailable. TBT liveness requires recent local packet evidence and an importable transport dependency profile.

## Architecture

`chanakya-trade` uses a unified broker abstraction under [`brokers/`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/brokers/):

- **Base Class**: [`brokers.base.BrokerBase`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/brokers/base.py) — contract for auth, quotes, history, orders, margins, positions.
- **Session Registry**: [`brokers.session`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/brokers/session.py) — multi-broker sessions, role separation (Data vs Execution), credential persistence.

---

## Supported Brokers

| Broker | Auth | Market Data | Execution | Callback URL | Notes |
| :--- | :--- | :---: | :---: | :--- | :--- |
| **Fyers** | OAuth2 Redirect | ✅ Free v3 API | ✅ | `/fyers/callback` | **Primary data broker** — live quotes & options chain |
| **Zerodha Kite** | OAuth2 (Request Token) | ✅ Paid API | ✅ | `/zerodha/callback` | Industry standard execution broker |
| **Angel One** | TOTP Auto-Login | ✅ SmartAPI Free | ✅ | — (no redirect) | Uses `ANGEL_TOTP_SECRET` for auto-auth |
| **Upstox** | OAuth2 Redirect | ✅ Free API v3 | ✅ | `/upstox/callback` | Good options data via WebSocket |
| **Groww** | OAuth2 Partner | ✅ Internal | ✅ | `/groww/callback` | Partner API integration |
| **Dhan** | Access Token | ✅ Free API v2 | ✅ | — (direct token) | Simple token-based auth |
| **Stoxkart** | OAuth2 | ✅ Free REST + WS | ✅ | `/stoxkart/callback` | Free API for algo trading |
| **m.Stock** | TOTP Auto / OAuth2 | ✅ Free Type B API | ✅ | `/mstock/callback` | Mirae Asset Capital Markets official API & WS |
| **Kotak Neo** | TOTP Auto-Login | ✅ Neo Trade API | ✅ | — (no redirect) | Kotak Securities Neo API — TOTP, quotes, history & WS |
| **Mock** | In-Memory | ✅ Synthetic | ✅ Paper | — | Explicit demo scenarios and isolated tests only; never a production fallback for actionable market data |

### Broker Routing Priority
```
Fyers (data) → explicitly configured, source-qualified data provider; execution routes only to the selected authenticated execution broker. Mock is isolated to explicit demo and test paths.
```

---

## Adding a New Broker

1. **Subclass `BrokerBase`**: Create `brokers/<broker_name>.py` implementing `authenticate()`, `get_quote()`, `get_history()`, `place_order()`, `get_positions()`, `get_holdings()`.
2. **Register in Session**: Update [`brokers/session.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/brokers/session.py) — add initialization in `login()` and `get_broker()`.
3. **Add OAuth Endpoints** (if OAuth2): In [`web/api.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/web/api.py), add `/<broker>/login` and `/<broker>/callback`.
4. **Update Credentials**: Add env keys to [`.env.example`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/.env.example) and keychain loader in [`config/credentials.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/config/credentials.py).

---

## Critical Rules

1. **Default Paper Mode**: All tests and automated scripts MUST use `TRADING_MODE=PAPER` or Mock broker. Never execute real orders without explicit user confirmation.
2. **Live Execution Gate (`ALLOW_LIVE_TRADING=1`, owner qualification, fail closed)**:
   - Live order submission via `execute_order_intent()` MUST pass `assert_live_execution_allowed()` before claiming `SUBMITTING`, then pass the supported-order-shape guard, pilot safety gate, and `validate_pretrade()` before contacting the execution broker.
   - Only `CONFIRMED → SUBMITTING` is permitted, atomically, after the exact server-generated preview hash is confirmed. A denied gate or unsupported shape remains `CONFIRMED` and must not claim a broker request was made.
   - `TRADING_MODE=EXECUTE` additionally requires `ALLOW_LIVE_TRADING=1` and owner-controlled `LIVE_EXECUTION_QUALIFIED=1`. Do not set qualification until the account-scoped execution ledger, unknown-attempt recovery, fill-driven protection and broker acceptance criteria are complete.
   - Ambiguous broker responses, TCP timeouts, or transport exceptions transition fail-closed to `UNKNOWN_FREEZE` with `broker_order_id=None` — never fabricate live order IDs.
   - Paper broker exceptions transition to `REJECTED` with the underlying reason rather than fabricating `FILLED_PAPER`.
3. **Honest Broker Reconciliation (`/api/reconciliation`)**:
   - Must query `get_execution_broker().get_positions()` and `get_execution_broker().get_funds()` directly.
   - The internal side comes from persisted local fills and an explicit opening-cash baseline. If the broker or independent ledger baseline is unavailable, return `status="UNAVAILABLE"` — never compare the internal ledger against itself.
   - Always includes `broker_account_id`, `broker_snapshot_at`, and `correlation_id` in valid reports.
4. **Authoritative Symbol Master Validation**:
   - Symbols must be verified against official daily exchange masters via [`market.symbol_master.validate_symbol()`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/market/symbol_master.py) before dispatch.
   - Prevents `-300 Invalid Symbol` rejections and guarantees canonical lot sizes and tick sizes.
5. **Decimal Tick-Size Quantization & 1-Paisa NSE/BSE Equity Rule**:
   - Limit and stop prices must be rounded via [`brokers.fyers.round_price_to_tick()`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/brokers/fyers.py) using `Decimal` arithmetic.
   - Cash equity symbols trading under ₹250 trade in 1-paisa ticks (`eff_tick = 0.01`), while stocks $\ge ₹250$ and all F&O derivatives trade in 5-paise ticks (`eff_tick = 0.05`). Resolve dynamically via [`engine.dynamic_risk.resolve_price_tier(ltp).tick_size`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/dynamic_risk.py).
   - Eliminates IEEE 754 floating point drift (e.g. `805.0500000000001`) that causes broker `-50 Invalid Parameter` rejections.
6. **Broker Rate-Limit Defense (plan-aware and fail closed)**:
   - FYERS announced revised, plan-specific limits effective **16 October 2026**. Standard data APIs: 5 req/s, 50 req/min, 5,000 req/day; Prime data APIs: 10 req/s, 500 req/min, 500,000 req/day. Prime also documents up to 1,000 symbols per quotes request and 5,000 real-time Data WebSocket symbols. Do not apply an old, plan-agnostic 10/200/100k limit or infer account entitlement from a sample config.
   - Transaction and user-information APIs have separate category limits in the FYERS schedule. Keep the client limiter at or below the configured plan/category budget with safety headroom; verify endpoint category, plan entitlement and current provider documentation before changing caps. Provider limits can change independently of this runbook.
   - The current FYERS gate uses conservative aggregate plan presets. Invalid `FYERS_PLAN` values raise instead of silently selecting Prime. The owner has confirmed an active Prime subscription; retain `FYERS_PLAN=PRIME` unless the account entitlement changes. Do not raise quotas beyond documented limits.
   - Primary source: [FYERS API rate-limit changes](https://fyers.in/notice-board/changes-to-fyers-api-rate-limits-and-usage), effective 16 October 2026; [FYERS Standard and Prime limits](https://support.fyers.in/portal/en/kb/articles/what-are-the-fyers-api-rate-limits-for-standard-and-prime-plans).
7. **Historical Candle Range Chunking**:
   - Minute resolutions are capped by Fyers at **100 days** per request; daily resolutions at **366 days**.
   - Queries spanning larger windows must use the automatic sequential chunking in `get_historical_data()`.
8. **SEBI IPv4 Binding**: Indian broker APIs enforce whitelisted static IPv4 addresses. Keep the `socket.getaddrinfo` override in `app/main.py`.
9. **Credential Safety**: Never commit API keys, TOTP secrets, or tokens. Use OS keychain via `config.credentials`.
10. **Honest Data Degradation**: When the selected live data source is unavailable, mark data `DEGRADED` or `UNAVAILABLE` and suppress actionable alerts that require it. A secondary source is eligible only when explicitly configured, licensed/authorized, instrument-mapped, freshness-checked and provenance-preserving. Never fall back to synthetic Mock or unverified `yfinance` data for production alerts.
11. **Connection Lifecycle**: Wrap `httpx.Client` in `with` context managers to prevent TCP socket leaks.
12. **October 2026 Instrument Master & Zero Hardcoding Invariant**:
   - Resolve active contract metadata, lot sizes, ticks and quantities from the fresh canonical exchange master. Do not use `STANDARD_LOT_SIZES` for current contracts when an exact listed row is required.
   - Quantity-freeze checks use `market.symbol_master.get_quantity_freeze_info()`; unavailable or ambiguous `qtyFreeze` blocks the plan. Never infer a per-order limit from lot size or an underlying-specific constant.
   - Hardcoding broker security tokens, legacy pre-2024 lot sizes, or arbitrary market-rule fallbacks in broker adapters is strictly prohibited.
13. **FYERS Prime Expired Options Data Semantics**:
   - `get_expired_fno_history()` uses the dedicated expired-contract endpoint. Optional OI and Greeks are read by the response `columns` names, not fixed offsets; null values remain null and carry explicit field status.
   - This API does not cover active contracts. A collection of expired-contract IV values is not a comparable historical IV rank; constant-tenor/moneyness construction, as-of validation and held-out evidence are required before any live alert can consume it.
   - The FYERS endpoint limits seconds history to recent sessions, has per-request range caps, and may omit individual Greek values. Unsupported or unavailable data remains explicitly unavailable.

---

## Testing

```powershell
# Live OMS, pre-trade gates & execution safety
.venv\Scripts\pytest.exe tests/test_live_oms_p3b.py tests/test_mode_banner_mapping.py tests/test_reconciliation_unavailable.py -v

# Broker routing and roles
.venv\Scripts\pytest.exe tests/test_broker_roles.py -v

# Quote fallback mechanisms
.venv\Scripts\pytest.exe tests/test_broker_quote_change.py -v

# OAuth callback endpoints (synthetic/mocked)
.venv\Scripts\pytest.exe tests/test_oauth_callback.py -v
```
