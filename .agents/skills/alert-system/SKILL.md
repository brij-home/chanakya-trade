---
name: alert-system
description: >-
  Full alert system runbook for ChanakyaTrade: alert lifecycle, 4-stage
  pre-LLM filter, detector registration, scrutiny tier 1/2 flow, and
  how to add new detector types in engine/detectors/.
---

# Alert System Runbook

> The alert system spans 7+ modules and 16 detector files. Read this before
> modifying anything in `engine/alerts.py`, `engine/auto_alert_engine.py`,
> `engine/alert_scrutiny.py`, `engine/alert_model.py`, `engine/alert_evaluator.py`,
> `engine/alert_expiry.py`, or `engine/detectors/`.

<!-- TOC -->
- [1. Alert Lifecycle](#1-alert-lifecycle)
- [2. Module Map](#2-module-map)
- [3. The 4-Stage Pre-LLM Filter](#3-the-4-stage-pre-llm-filter)
- [4. Detector Registration Pattern](#4-detector-registration-pattern)
- [5. Alert Scrutiny: Tier 1 and Tier 2](#5-alert-scrutiny-tier-1-and-tier-2)
- [6. Adding a New Detector](#6-adding-a-new-detector)
- [7. Auto Alert Engine Loop](#7-auto-alert-engine-loop)
- [8. Multi-Channel Dispatch](#8-multi-channel-dispatch)
- [9. Alert Identity & Deduplication Invariants](#9-alert-identity--deduplication-invariants)
- [10. Institutional RCA-First Debugging Protocol](#10-institutional-rca-first-debugging-protocol)
- [11. Testing & Invariant Verification](#11-testing--invariant-verification)
<!-- /TOC -->

---

## 1. Alert Lifecycle

```
CREATED -> PENDING -> ACTIVE -> TRIGGERED -> [INVALIDATED or EXPIRED]
                             -> CANCELLED (user dismiss)
```

| State | Meaning |
|-------|---------|
| `CREATED` | Alert just written to storage |
| `PENDING` | Waiting for trigger condition |
| `ACTIVE` | Trigger condition partially met (precursor) |
| `TRIGGERED` | Full condition met — dispatched to channels |
| `INVALIDATED` | Stop-loss hit or setup structure broken |
| `EXPIRED` | TTL exceeded or expiry date passed |
| `CANCELLED` | User manually dismissed |

### Key Fields in `AutoAlert` (engine/alert_model.py)
```python
alert_id: str          # Deterministic: aa-{alert_type_slug}-{canonical_symbol}[-{variant}]-{YYYYMMDD} from generate_alert_id()
symbol: str            # Clean canonical symbol via canonical_alert_symbol() (no exchange prefix)
alert_type: str        # "GAMMA_BLAST", "SQUEEZE_BREAKOUT", "ORB", etc.
direction: str         # "BULLISH" | "BEARISH"
entry_price: float
stop_loss: float
target_1: float
target_2: float
confidence: int        # 0-100
status: str
scrutiny: ScrutinyResult   # Tier 1 + Tier 2 verdict
created_at: str        # IST timestamp
expires_at: str        # IST timestamp
```

---

## 2. Module Map

| Module | Responsibility |
|--------|---------------|
| `engine/alert_identity.py` | Single authority for alert ID generation (`generate_alert_id`), symbol normalization (`canonical_alert_symbol`), and determinism validation (`validate_alert_id`) |
| `engine/alert_model.py` | `AutoAlert` dataclass, status transitions, defensive invariant setters |
| `engine/alerts.py` | CRUD: save/load/update alerts to JSON storage |
| `engine/alert_evaluator.py` | Evaluate invalidation, target hits, trailing stop updates |
| `engine/alert_expiry.py` | TTL classification, options expiry detection |
| `engine/alert_scrutiny.py` | Tier 1 math sanity + Tier 2 LLM devil's advocate |
| `engine/alert_preferences.py` | User alert preference filters (asset class, type, confidence) |
| `engine/auto_alert_engine.py` | Main engine loop, detector dispatch, circular buffer, SSE |
| `engine/detectors/` | 16 individual detector implementations (ALL use `generate_alert_id`) |
| `engine/multibagger_alerts.py` | Multibagger-specific alert generation |
| `engine/precursor_radar.py` | Precursor signal detection (early warning) |

---

## 3. The 4-Stage Pre-LLM Filter

**MANDATORY** — every alert candidate must pass ALL 4 stages sequentially before any LLM is invoked. Zero tokens spent on rejected candidates.

### Stage 1: Lockout Gate
```python
session = get_current_ist_session()
if not session["is_market_open"] and not session["is_extended"]:
    return None  # Market closed — skip entirely
if alert_on_cooldown(symbol, alert_type):
    return None  # Within 90-120s TTL cooldown
```

### Stage 2: In-Memory Deduplication & TTL Cache
```python
cache_key = f"{symbol}:{alert_type}:{round(price, 1)}"
if cache_key in _DEDUP_CACHE and (time.time() - _DEDUP_CACHE[cache_key]) < 90:
    return None  # Same setup seen within 90s — skip
_DEDUP_CACHE[cache_key] = time.time()
```

### Stage 3: Deterministic Quantitative Conviction Gate
```python
if minervini_stage != 2:
    return None  # Wrong stage — reject without LLM
if technical_confidence < 70:
    return None  # Weak setup
if rr_ratio < 2.0:
    return None  # Unfavorable R:R
```

### Stage 4: LLM Pool Availability Circuit Breaker
```python
from agent.core import get_fast_llm_provider
provider = get_fast_llm_provider()
if hasattr(provider, "is_pool_available") and not provider.is_pool_available():
    # Fast-fail locally in ~0ms — no network request made
    return _quant_fallback_scrutiny(alert)
```

Only candidates that pass all 4 stages proceed to `alert_scrutiny.py` Tier 2.

---

## 4. Detector Registration Pattern

Each detector lives in `engine/detectors/<name>.py` and exports a single function:
```python
# engine/detectors/squeeze_breakout.py
def detect_squeeze_breakout(
    symbol: str,
    quote: dict,
    ohlcv: pd.DataFrame,
    options_data: dict | None = None,
) -> AutoAlert | None:
    """Returns AutoAlert if setup detected, None otherwise."""
    ...
```

Register in `engine/detectors/__init__.py`:
```python
from .squeeze_breakout import detect_squeeze_breakout
from .gamma_blast import detect_gamma_blast
# etc.
```

And call from `engine/auto_alert_engine.py` dispatch loop:
```python
detectors = [
    detect_squeeze_breakout,
    detect_gamma_blast,
    detect_circuit_proximity,
    # new detectors added here
]
for detector in detectors:
    alert = detector(symbol, quote, ohlcv, options_data)
    if alert:
        _process_candidate(alert)
```

---

## 5. Alert Scrutiny: Tier 1 and Tier 2

### Tier 1 — Math Sanity (0 tokens, ~1-2ms)
File: `engine/alert_scrutiny.py::_tier1_sanity_check()`

Validates:
- Direction coherence: `BULLISH` -> entry < target_1 < target_2, entry > stop_loss
- R:R ratio >= 2.0 (target: >= 2.5)
- Entry within 1.2% of pivot (no-chase rule)
- Minimum liquidity: daily turnover threshold
- ATR floor: stop-loss not below commodity/index noise floor

```python
# Commodity minimum SL floors (points)
COMMODITY_MIN_SL_FLOORS = {
    "CRUDEOIL": 80.0, "GOLD": 250.0, "SILVER": 450.0, ...
}
# Index minimum SL floors (points)
INDEX_MIN_SL_FLOORS = {
    "NIFTY": 25.0, "BANKNIFTY": 65.0, "FINNIFTY": 30.0, ...
}
```

If Tier 1 fails -> `ScrutinyResult(status="REJECTED", rejection_reason=...)`

### Tier 2 — LLM Devil's Advocate (<2.5s timeout)
File: `engine/alert_scrutiny.py::_tier2_llm_scrutiny()`

- Calls Fast-LLM with a structured audit prompt
- Asks for: setup confirmation, #1 failure mode, derivative flow analysis
- Returns: `status="APPROVED"`, `score` (0-100), `trap_risk_warning`, `actionable_guidance`
- On LLM timeout/failure -> returns `status="QUANT_VERIFIED"` from quantitative fallback (never blank)

### ScrutinyResult
```python
@dataclass
class ScrutinyResult:
    status: str          # "APPROVED" | "REJECTED" | "QUANT_VERIFIED" | "PENDING_AI"
    score: int           # 0-100
    logic_confirmation: str
    trap_risk_warning: str
    actionable_guidance: str
    rejection_reason: str | None
    auditor_model: str   # "FAST_LLM" | "QUANT_FALLBACK"
```

---

## 6. Adding a New Detector

1. **Create the detector file**: `engine/detectors/my_new_detector.py`
2. **Implement the standard signature**:
   ```python
   from engine.alert_model import AutoAlert
   import pandas as pd

   def detect_my_new_setup(
       symbol: str,
       quote: dict,
       ohlcv: pd.DataFrame,
       options_data: dict | None = None,
   ) -> AutoAlert | None:
       # 1. Pass through 4-stage pre-LLM filter first
       # 2. Compute signals deterministically
       # 3. Build and return AutoAlert if detected
       return None  # if not detected
   ```
3. **Register in `engine/detectors/__init__.py`**:
   ```python
   from .my_new_detector import detect_my_new_setup
   ```
4. **Add to dispatch loop in `engine/auto_alert_engine.py`**:
   ```python
   alert = detect_my_new_setup(symbol, quote, ohlcv, options_data)
   ```
5. **Write tests**: `tests/test_my_new_detector.py` using synthetic OHLCV data
6. **Add alert_type constant**: Add the new type string to `engine/alert_model.py` type list

---

## 7. Auto Alert Engine Loop

`engine/auto_alert_engine.py` runs a background thread that:

1. Every N seconds (configurable via `ALERT_SCAN_INTERVAL`), fetches live quotes for the active universe
2. For each symbol, calls all registered detectors
3. Passes candidates through the 4-stage pre-LLM filter
4. Sends approved candidates to `alert_scrutiny.py`
5. Approved alerts go to multi-channel dispatch

**Market Hours Awareness**:
```python
session = get_current_ist_session()
# Equity: 09:15 - 15:30 IST
# MCX: 09:00 - 23:30/23:55 IST
# Extended: 15:30 - 16:00 IST (post-close monitoring)
```

**Circular Buffer**: Last 500 alerts kept in-memory for fast `/skills/alerts/auto/list` API.

---

## 8. Multi-Channel Dispatch

When an alert is approved and dispatched:

1. **SSE Bus** (`web.sse.event_bus`): Pushes to all connected browser clients
   ```python
   from web.sse import event_bus
   event_bus.push({"type": "alert", "data": alert.to_dict()})
   ```
2. **In-Memory Circular Buffer**: Appended to `_ALERT_BUFFER` (deque, maxlen=500)
3. **Persistent Storage**: Written to `auto_alerts.json` via `engine/alerts.py`
4. **Telegram** (if configured): `bot/telegram_bot.py` high-confidence alerts only (score >= 80)
5. **Desktop Notification** (macOS): Electron IPC notification

---

## 9. Alert Identity & Deduplication Invariants

All alerts in ChanakyaTrade must strictly follow centralized determinism rules:

1. **Single Canonical Authority**:
   - Every detector MUST call `generate_alert_id(symbol, alert_type, session_date, variant)`.
   - Never mint ad-hoc strings in detectors.
2. **Calendar Session Date Determinism**:
   - Alert IDs are bound to calendar session date (`%Y%m%d`), NEVER to minute/second timestamps (`%H%M`, `%S`) or random UUIDs (`uuid.uuid4()`).
   - Format: `aa-{alert_type_slug}-{canonical_symbol}[-{variant}]-{YYYYMMDD}`
   - Example: `aa-gamma-blast-nifty-ce-25000-20260926`, `aa-crypto-squeeze-btcusdt-20260926`.
3. **Symbol Normalization**:
   - Always normalize symbols with `canonical_alert_symbol(sym)`, which strips exchange prefixes (`NSE:`, `BSE:`, `MCX:`, `NFO:`, `BFO:`, `CDS:`, `CRYPTO:`, `BINANCE:`, `DERIBIT:`).
4. **Validation Guard**:
   - `validate_alert_id(alert_id)` rejects IDs with banned minute timestamps (12+ digits) or random UUID hex suffixes.
5. **Static Code Audits**:
   - Statically validated via `tests/test_alert_identity_invariants.py`, which parses all files in `engine/detectors/*.py` to ensure zero banned patterns exist.

---

## 10. Institutional RCA-First Debugging Protocol

When diagnosing alert storms, UI popup bursts, or unexpected state transitions:

1. **Step 1 — Full Pipeline Inspection**:
   - Read backend logs (`.logs/backend_err.log`, `.logs/backend.log`).
   - Inspect SSE event payloads and network traffic to determine if the event stream is flooded.
   - Check `auto_alerts.json` to verify whether IDs are unique per iteration (indicating broken dedup) or identical (indicating duplicate broadcast).
2. **Step 2 — Identify Root Cause (RCA)**:
   - Identify whether the fault is in detector ID generation, cooldown caches, state machine transitions, or model properties.
3. **Step 3 — Remediate at the Source**:
   - NEVER apply cosmetic UI debounces, rate-limiters, or toast hiding to mask an underlying engine bug.
   - Fix the schema, factory, or deduplication logic at the source.
4. **Step 4 — Invariant Prevention**:
   - Add a deterministic unit/invariant test to prevent any future regression.
5. **Step 5 — Zero In-Line Migrations**:
   - Do not inject historical ad-hoc regex repair loops into `_load()` or hot loops. Use offline repair scripts (`scripts/remediate_corrupted_alerts.py`).

---

## 11. Testing & Invariant Verification

```powershell
# Alert identity, symbol normalization, and detector static invariants (< 1s)
& "C:\Users\brije\AppData\Local\Programs\Python\Python312\python.exe" -m pytest tests/test_alert_identity_invariants.py -q

# Full auto-alert engine tests (dedup, cooldown, lifecycle)
& "C:\Users\brije\AppData\Local\Programs\Python\Python312\python.exe" -m pytest tests/test_auto_alerts.py -q

# Crypto alert pipeline tests
& "C:\Users\brije\AppData\Local\Programs\Python\Python312\python.exe" -m pytest tests/test_crypto_alert_pipeline.py -q

# Alert scrutiny tier 1 and tier 2
& "C:\Users\brije\AppData\Local\Programs\Python\Python312\python.exe" -m pytest tests/test_alert_scrutiny.py -q

# Alert lifecycle and expiry
& "C:\Users\brije\AppData\Local\Programs\Python\Python312\python.exe" -m pytest tests/test_alert_revamp.py tests/test_alert_horizon_and_liquidity.py -q
```

