---
name: broker-management
description: >-
  Add, test, and maintain Indian broker integrations (Zerodha Kite, Fyers,
  Angel One SmartAPI, Groww, Upstox, Dhan, Stoxkart, and Mock Broker),
  handling OAuth2 redirects, TOTP authentication, and unified order/quote mapping.
---

# Broker Integration & Session Management Runbook

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
| **Mock** | In-Memory | ✅ Synthetic | ✅ Paper | — | **Default fallback** — offline & tests |

### Broker Routing Priority
```
Fyers (data) → Zerodha/Angel One (execution) → yfinance (fallback) → Mock (offline)
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
2. **SEBI IPv4 Binding**: Indian broker APIs enforce whitelisted static IPv4 addresses. Keep the `socket.getaddrinfo` override in `app/main.py`.
3. **Credential Safety**: Never commit API keys, TOTP secrets, or tokens. Use OS keychain via `config.credentials`.
4. **Graceful Degradation**: Always fall back through the broker chain → `yfinance` → Mock when live brokers are disconnected.
5. **Connection Lifecycle**: Wrap `httpx.Client` in `with` context managers to prevent TCP socket leaks.

---

## Testing

```powershell
# Broker routing and roles
.venv\Scripts\pytest.exe tests/test_broker_roles.py -v

# Quote fallback mechanisms
.venv\Scripts\pytest.exe tests/test_broker_quote_change.py -v

# OAuth callback endpoints (synthetic/mocked)
.venv\Scripts\pytest.exe tests/test_oauth_callback.py -v
```
