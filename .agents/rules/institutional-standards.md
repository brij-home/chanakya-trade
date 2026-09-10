# Institutional Engineering, Data Quality & UI Aesthetics Standard

> **MANDATORY INVARIANT**: This rule governs all development, architectural decisions, analytical logic, data pipelines, and UI implementations across ChanakyaTrade. Real money and real financial risk depend on this system.

---

## 1. Zero AI Hallucinations & Deterministic Grounding
- **Grounded Facts Only**: Every signal, conviction score, price level, target, and recommendation MUST be derived from real-time broker feeds, historical OHLCV data, or verified quantitative models (SMC, Minervini, VPA, Beneish, Altman, RRG).
- **Zero Fabrications**: Never fabricate or guess order IDs, fill prices, P&L amounts, execution confirmations, or forensic results.
- **Deterministic Quant Fallbacks**: All LLM interactions must be defensive with 18s timeouts. If an LLM is throttled or fails, the system MUST seamlessly fall back to pure quantitative analysis (VIX + FII/DII + Minervini + SMC). Never output raw error messages, blank cards, or hallucinated numbers.
- **Honest Feed State**: If market data is unreachable or disconnected, explicitly return `UNAVAILABLE` or `DEGRADED`. Never invent synthetic dummy prices to conceal disconnected infrastructure.

---

## 2. Zero Hardcoding & Zero False Data Representation
- **No Dummy Prices in Production**: Hardcoding static stock prices, artificial DCF multiples (e.g., `price * 1.15`), or dummy forensic statuses (e.g., hardcoded `"CLEAN"`) in production code paths is strictly prohibited.
- **Transparent Provenance**: Every event, quote, and chart snapshot must be explicitly tagged with its true provenance:
  - `REAL/LIVE` — Verified live broker WebSocket or REST feed during market hours.
  - `OFF-MARKET/EOD` — Post-market settlement / EOD candle.
  - `TEST` — Explicit synthetic test data.
  - `DEGRADED` / `UNAVAILABLE` — Stale or disconnected feed.
- **Exchange & Instrument Authority**: Instrument specifications (lot size, tick size, token, segment) must resolve from canonical exchange masters, never from client assumptions.

---

## 3. Strong, Decisive & Logically Valid Outputs
- **No Indecisive Filler**: Eliminate wishy-washy language (*"This stock could go up or it could go down"*). Be crisp, quantitative, and decisive.
- **Complete Actionable Blueprints**: Every trade recommendation, radar candidate, or alert must specify:
  1. **Exact Entry Zone**: Specific price band anchored to structural support/VWAP.
  2. **Invalidation Stop-Loss**: Structurally placed level (below 10-EMA, 200-EMA, base low, or VWAP) with exact point risk.
  3. **Target 1 (+2R)**: 50% scale-out level with immediate stop-loss adjustment to breakeven.
  4. **Target 2 (+4R)**: Extended swing target with 20-EMA / 3.0×ATR trailing stop.
  5. **Moonshot Runner (+6R+)**: High-convexity runner level for generational trends.
  6. **Strict "NO CHASE" Boundary**: Exact price limit beyond which entry is disqualified without a retest.
  7. **Risk:Reward Standard**: Enforce strict minimum $1:3.0$ R:R for asymmetric opportunities; reject unfavorable setups.

---

## 4. Elimination of Architectural Anti-Patterns
- **Fail-Closed Execution**:
  - Live orders require pilot safety gate check $\to$ pre-trade validation $\to$ execution broker call in strict sequence.
  - Broker errors must yield `status=REJECTED` with the genuine error message.
  - Ambiguous/timed-out live orders must yield `status=UNKNOWN_FREEZE` with `broker_order_id=None`. Never fabricate `LIVE-XXXXXX` IDs or assume an order was filled.
- **Hygiene & Concurrency**:
  - All HTTP requests must use `httpx` within `with` or `async with` context managers. No dangling TCP sockets.
  - All shared memory caches and state dictionaries must have thread locks (`threading.Lock()`) and LRU/TTL bounds to prevent memory leaks.
  - Enforce timezone-naive DatetimeIndex (`df.index.tz_localize(None)`) across all pandas computations.
  - Never silently swallow exceptions (`except: pass`) without structured logging or telemetry emission.
  - Frontend components must never leave unhandled Promise rejections.

---

## 5. Niche Institutional UI Aesthetics & Density
- **Bloomberg / TradingView Standard**: Institutional density, compact padding (`p-2.5`, `gap-2`, `py-1 px-2` table cells), dark theme default with crisp typography (Google Inter for body, monospace for tabular numbers).
- **Curated Color Tokens**:
  - 🟢 **Emerald (`#10B981`)**: Profit, Bullish, Verified Live, T1/T2 Targets.
  - 🔴 **Rose / Crimson (`#F43F5E`)**: Invalidation Stop-Loss, Bearish, Traps Quarantined.
  - 🟡 **Amber / Gold (`#F59E0B`)**: High Conviction Score, Precursors, Asymmetric Setups.
  - 🟣 **Indigo (`#6366F1`)**: F&O Derivatives, Greeks, Open Interest.
  - 🔵 **Sky (`#0EA5E9`)**: Benchmark Indices, Macro Contagion, Sector RRG.
- **Rich Micro-Interactions**:
  - Smooth transitions (`transition: transform 0.15s ease, opacity 0.2s`).
  - Glassmorphism overlays (`backdrop-filter: blur(12px); background: rgba(0,0,0,0.45)`).
  - 1-Click frictionless execution: all action buttons must immediately dispatch orders or ticket drafts (`autoSubmit: true`), never leaving the user stranded.
- **Zero Placeholders**: Never render broken, blank, or generic toy mockups. Every card, table, and modal must be production-grade.
