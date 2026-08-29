---
name: broker-management
description: >-
  Add, test, and maintain Indian broker integrations (Zerodha Kite, Fyers,
  Angel One SmartAPI, Groww, Upstox, Dhan, and Mock Broker), handling OAuth2
  redirects, TOTP authentication, and unified order/quote mapping.
---

# Broker Integration & Session Management Runbook

## Broker Architecture & Roles

`chanakya-trade` uses a unified broker abstraction layer under [`brokers/`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/brokers/):

- **Base Class**: [`brokers.base.BrokerBase`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/brokers/base.py) defines the contract for authentication, quotes, historical data, order execution, margins, and portfolio positions.
- **Session Registry**: [`brokers.session`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/brokers/session.py) manages multi-broker sessions, role separation (Data Broker vs Execution Broker), and credential persistence.

### Supported Brokers Matrix

| Broker | Auth Method | Market Data | Order Execution | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Fyers** | OAuth2 Redirect | Excellent (Free v3 API) | Yes | Ideal primary broker for live quotes & options chain |
| **Zerodha Kite** | OAuth2 (Request Token) | Paid API subscription | Yes (KiteConnect) | Industry standard execution broker |
| **Angel One** | TOTP Auto-Login | SmartAPI Free | Yes | Zero redirect needed — uses `ANGEL_TOTP_SECRET` |
| **Upstox** | OAuth2 Redirect | Free API v3 | Yes | Redirect via `http://127.0.0.1:8765/upstox/callback` |
| **Groww** | OAuth2 Partner API | Internal | Yes | Redirect via `http://localhost:8765/groww/callback` |
| **Dhan** | Access Token | Free API v2 | Yes | Direct token authentication |
| **Mock** | In-Memory | Synthetic fallback | Paper simulation | Default fallback when offline or in tests |

---

## Adding a New Broker

1. **Subclass `BrokerBase`**:
   - Create `brokers/<broker_name>.py`.
   - Implement `authenticate()`, `get_quote()`, `get_history()`, `place_order()`, `get_positions()`, `get_holdings()`.
2. **Register in Session Manager**:
   - Update [`brokers/session.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/brokers/session.py) to add broker initialization in `login()` and `get_broker()`.
3. **Add Web OAuth Endpoints (if OAuth2)**:
   - In [`web/api.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/web/api.py), add `/<broker>/login` and `/<broker>/callback`.
4. **Update Credentials & Config**:
   - Add environment keys to [`.env.example`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/.env.example) and keychain loader in [`config/credentials.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/config/credentials.py).

---

## Testing Broker Modules

```powershell
# Test broker routing and roles
.venv\Scripts\pytest.exe tests/test_broker_roles.py -v

# Test broker quote fallback mechanisms
.venv\Scripts\pytest.exe tests/test_broker_quote_change.py -v

# Test OAuth callback endpoints (synthetic/mocked)
.venv\Scripts\pytest.exe tests/test_oauth_callback.py -v
```
