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
- [12. Data Reliability & Honest Provenance](#12-data-reliability-honest-provenance--zero-silent-swallowing-standard)
- [13. Detector Degradation Circuit Breakers](#13-detector-degradation-circuit-breakers--scrutiny-conviction-integrity)
- [14. Tri-Directional Holistic Calibration & Universal Options Symmetry](#14-tri-directional-holistic-calibration--universal-options-symmetry-standard)
<!-- /TOC -->

---

## 1. Alert Lifecycle & Predatory Interception Pipeline

```
[STALK] (Radar Tracking) ──> [PRIMED] (Within ±0.35% Proximity) ──> [IGNITED] (Sniper Trigger)
                              ──> [INVALIDATED / TARGET_ACHIEVED / EXPIRED]
```

| State | Meaning |
|-------|---------|
| `STALK` | Candidate qualified (coiling base / VCP / Order block anchor identified) |
| `PRIMED` | Spot entered high-frequency micro-proximity surveillance ($\pm 0.35\%$ of trigger) |
| `EARLY_WARNING` | Precursor alert awaiting trigger breach (backward compatible) |
| `IGNITED` | Trigger level crossed with micro-confirmation — immediate 1-click execution draft |
| `T1_ACHIEVED` | Target 1 (+2R) hit: 50% profit booked, stop-loss shifted to Breakeven (+0.2%) |
| `T2_ACHIEVED` | Target 2 (+4R) hit: 25% profit booked, trailing via Chandelier / structure |
| `INVALIDATED` | Invalidation stop-loss breached or setup structure broken |
| `EXPIRED` | TTL exceeded or session ended |
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

## 8. Multi-Channel Dispatch & Single-Authority Ingestion

When an alert is approved and dispatched:

1. **SSE Bus** (`web.sse.event_bus`): Pushes to all connected browser / desktop clients in real time
   ```python
   from web.sse import event_bus
   event_bus.publish_sync("alert", alert.to_dict())
   ```
2. **In-Memory Circular Buffer**: Appended to `self._alerts` (deque, maxlen=500)
3. **Persistent Storage**: Written atomically to `auto_alerts.json`
4. **Telegram Gate**: Evaluated against institutional conviction, R:R >= 1.4, macro regime, sector daily caps, and Zero-Ghost lifecycle invariant
5. **Desktop Notification** (macOS/Electron): Local system notification & chime

### Single-Authority Ingestion Protocol (Zero Shadow Dispatches)
- **Zero Shadow Alerts**: Modules outside the alert engine (`analysis/execution_gate.py`, etc.) MUST NEVER call `send_push()` or `push_execution_alert()` directly for new trade setups.
- **Canonical Method**: Ingest via `auto_alert_engine.ingest_execution_gate_report(report)`.
- **Guarantees**:
  1. Generates deterministic alert ID via `generate_alert_id()`.
  2. Persists record into `auto_alerts.json`.
  3. Emits real-time SSE event to UI.
  4. Applies centralized Telegram filters with explicit `TG SENT` vs `TG HELD` provenance logging.

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
6. **Channel Parity & Query Transparency**:
   - Telegram bot `/alerts` (`cmd_alerts`) must query both `auto_alert_engine.get_alerts(view_mode="ACTIVE")` and `alert_manager._alerts`, displaying live delivery status (`📱 TG SENT` vs `🔒 TG HELD`).
7. **Dynamic Price-Tier Risk Clamping (Zero Hardcoded `max(1.0, ...)` Floors)**:
   - Detectors MUST NEVER apply arbitrary static risk floors like `max(1.0, ...)` which distort low-ticket (sub-₹100) or high-ticket (>₹2,500) stocks.
   - All risk boundaries MUST resolve from `engine.dynamic_risk.resolve_price_tier(ltp).abs_min_risk_pts` or `clamp_dynamic_risk(...)`.
8. **SEBI Expiry Architecture & Zero Stale Weekly Expiries**:
   - Detectors MUST resolve expiry metadata through `engine.alert_expiry.classify_expiry_type(...)`.
   - Strictly NIFTY (Thursday) and SENSEX (Friday) have weekly contracts. All other indices (Bank Nifty, FinNifty, MidcpNifty) and stock derivatives are strictly monthly contracts.

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

---

## 12. Data Reliability, Honest Provenance & Zero Silent Swallowing Standard

1. **Zero Silent Swallowing (`except: pass` Banned)**:
   - Every exception in detectors or evaluation loops MUST be logged with `logger.warning` or `logger.error` including `symbol`, `detector_name`, and exception details.
   - Never use empty `pass` in `except` blocks. If an indicator calculation fails for an illiquid instrument, log the skip reason at `warning` or `debug` level with full context.
2. **Signals ONLY on Real, Reliable Data**:
   - Detectors MUST NEVER trigger on synthetic, placeholder, or zero quotes.
   - If market data feed is unreachable, stale, or zero, return `None` or emit explicit `DATA_UNAVAILABLE` / `DATA_DEGRADED` status codes.
   - Every alert carries unambiguous provenance metadata: `source` (`REAL/LIVE`, `EOD_VERIFIED`, `OFF_MARKET`, `DEGRADED`).
3. **Zero Hardcoded Symbols or Multiples**:
   - Never inject arbitrary hardcoded stock lists inside detector evaluation loops. Symbols must originate from canonical universe resolvers (`analysis.universe.resolve_dynamic_universe`).
   - Sizing, targets, and invalidations must be derived dynamically from market structure (ATR, Swing Pivots, Order Blocks), never arbitrary multipliers.

---

## 13. Detector Degradation Circuit Breakers & Scrutiny Conviction Integrity

1. **Rolling Kelly Degradation State Machine**:
   - Every detector is continuously governed by `engine/detector_circuit_breaker.py`.
   - `HALTED` ($E < -0.60$ or $\ge 5$ consecutive losses): Suppressed immediately from emitting alerts.
   - `PROBATION` ($E < 0.0$ or Kelly $\le 0$): 25% confidence discount (`0.75x`) applied to incoming setups.
   - `NORMAL`: Standard baseline confidence.
   - `HEALTHY` ($E \ge 0.20$ & Win Rate $\ge 40\%$): Confirmed edge with optional +5% conviction bonus.
2. **Conviction Integrity Across Scrutiny Layers**:
   - Downstream AI Scrutiny (Tier-2 LLM or quantitative fallback) and `_async_enrich_scrutiny` MUST NEVER wipe out a probation discount.
   - When updating alert confidence after scrutiny, the discount multiplier must be preserved: `target.confidence = max(target.confidence, int(round(scrutiny.score * cb_multiplier)))`.
3. **Continuous Realized Outcome Feedback Loop**:
   - Target milestone hits (T1, T2) and runner trail exits feed `outcome="WIN"` into `detector_circuit_breaker.record_outcome(...)`.
   - Thesis stop-loss invalidations feed `outcome="LOSS"` into `detector_circuit_breaker.record_outcome(...)`.
4. **Hermetic Test Isolation**:
   - `detector_circuit_breaker.reset_all()` must be invoked in test cleanup (configured autouse in `tests/conftest.py::sanitize_test_env`) so that failed test setups never bleed degraded states into unrelated test suites.

---

## 14. Tri-Directional Holistic Calibration & Universal Options Symmetry Standard

1. **Universal Options Applicability (Index & Single-Stock Options)**:
   - Structural and directional guards apply symmetrically to **all options** (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX, BANKEX, and Single-Stock F&O like RELIANCE, HDFCBANK, INFOSYS):
     - **VWAP Regime Discipline**: Call buyers must be aligned with spot holding at/above VWAP; Put buyers must be aligned with spot holding at/below VWAP.
     - **Scale Separation Invariant**: Option premium ticks must never be contaminated with spot index/equity prices ($\ge 1000\text{ pts}$ on sub-500 options) or stray outside a $0.15\times - 3.50\times$ ratio against entry.
     - **Time & Theta Exhaustion**: 0DTE afternoon theta exhaustion guards (e.g. 14:15+ IST) apply across weekly index expirations and monthly stock options during expiry week.

2. **Tri-Directional Cross-Regime Auditing (Zero Unilateral Patches)**:
   - Whenever an issue, anomaly, or edge-case is investigated or modified on one directional bias, developers and agents MUST audit the opposing direction and the neutral regime before committing:
     - **BEAR Patch (Put)**: If adding a Short-Squeeze Guard, Bear-Trap Filter, or Ascending Bounce Guard, immediately verify and update the **BULL** counterpart (Dead-Cat Bounce Guard, Bull-Trap Filter, Descending Flush Guard).
     - **BULL Patch (Call)**: If adding a Momentum Reclaim or Gap-Up Filter, immediately verify the **BEAR** counterpart (Breakdown Rejection, Gap-Down Filter).
     - **NEUTRAL Impact (Iron Condors / Spreads)**: Verify whether suppressing false directional breakouts cleanly transitions capital to defined-risk neutral strategies (`engine/detectors/defined_risk_neutral.py`) during consolidating regimes (ADX $<25$, VIX $\le 15$).

3. **Temporal Momentum vs. Static Morning Extremes**:
   - Never compute directional flush/rally solely against a static morning extreme (`day_high` or `day_low` from hours earlier).
   - Invariants must evaluate **recent dynamic momentum** (last 2–3 candles, slope, green vs. red close, and relative distance between swing low and swing high) to prevent suppressing genuine structural V-bottoms or V-top reversals.

4. **Tri-Directional Regression Test Mandate**:
   - Every directional detector modification must be verified by automated tests covering:
     - Case 1: Valid trending entry (passed).
     - Case 2: Opposing counter-trend surge / flush (strictly suppressed).
     - Case 3: Structural V-reversal with heavyweights or volume confirmation (allowed without false suppression).
     - Case 4: Scale sanity and non-contamination under corrupted tick conditions.

5. **Immutable Entry Anchoring & Persistence Quarantine**:
   - **Entry Anchor Sanctity**: In `engine/alert_model.py` and `engine/alert_scrutiny.py`, stop-loss and target validity checks must anchor against immutable entry definitions (`trigger_level` or `entry_price`), never fluctuating live market ticks (`ltp`). Adverse live price drift before an exit transition must not cause false data sanctity rejections.
   - **Defensive Serialization Quarantine**: `engine/storage/alert_repository.py` must isolate per-alert serialization errors via defensive `try / except` quarantine so that an isolated formatting bug never aborts atomic JSON persistence or SQLite ledger sync for the rest of the alerts.
   - **Milestone Decoupling**: Target scaling milestones (e.g. `DE_RISK_0_5R` at +0.5R) must remain distinct from full breakeven locking (`T1_ACHIEVED` / `BREAKEVEN_LOCKED` at +2.0R) in `engine/alert_evaluator.py`, avoiding false breakeven gate warnings.




