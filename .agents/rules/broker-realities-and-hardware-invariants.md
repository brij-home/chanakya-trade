# Broker Realities, Data Stream Invariants & Zero-Hallucination Contracts

> **CRITICAL INVARIANT**: Real capital is at stake. Trading decisions, alert generation, stop losses, and market breadth must NEVER be predicated on unverified broker capabilities, aspirational docstrings, or imaginary APIs.

---

## 1. Verified Broker Capabilities & Hard Limits

### FYERS API v3 (Active Subscription: FYERS PRIME)
- **Rate Limits (`FYERS_PLAN=PRIME`)**:
  - Separate buckets in [`market/fyers_rate_gate.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/market/fyers_rate_gate.py): **`DATA`** (`10 req/s`, `500 req/min`, `500,000 req/day`) and **`TRANSACTION`/`ORDER`** (`10 req/s`, `500 req/min`, `500,000 req/day`), keeping transaction headroom independent of scanner data bursts.
- **Data Socket (`FYERS_PLAN=PRIME`)**:
  - Maximum **5,000 concurrent symbols** subscription limit across all user data socket connections (standard tier is capped at 100 symbols).
  - Streaming modes: Lite (`mode 1`) and Full (`mode 2` - includes 5-depth DOM).
  - Governed by `config.discovery_policy` (`FNO_ONLY` default): subscribe cleanly to active exposures, F&O options/futures, and read-only index constituent context without exhausting slots on unrelated cash-desk discovery.
- **Bulk Quotes API & Span Margin (`FYERS_PLAN=PRIME`)**:
  - Up to **1,000 symbols per REST request** (standard tier is capped at 50 symbols).
  - `check_order_margin()` (`POST /api/v3/multiorder/margin`) MUST acquire `fyers_rate_gate` and verify `fyers_circuit_breaker` before making external REST calls.
- **Fyers TBT 50-Depth WebSocket (`FYERS_PLAN=PRIME`)**:
  - Maximum **15 symbols** total (3 workers × 5 symbols each); strictly **NSE CM and NFO** only (does **NOT** support BSE `SENSEX`/`BANKEX` or MCX — BSE uses standard 5-depth DataSocket). Exposure registrations preempt discovery slots.
- **OrderSocket & Expired F&O Research**:
  - `OrderSocket` (`market/fyers_order_stream.py`) reconciles into `engine/order_lifecycle.py` with strict `account_id` isolation. Expired F&O endpoint supports research replay only (`RESEARCH_ONLY_EXPIRED_FNO`) without fabricating comparable constant-tenor IV rank.
- **What Fyers Prime Does NOT Provide**:
  - Does **NOT** provide a pre-aggregated Market Breadth API, Sector Heatmap API, or server-computed session VWAP in standard quote packets.

### FLATTRADE (Pi Connect v2 — Secondary Hot Standby)
- **Failover & Tick Feed**:
  - Decoupled from `FyersCircuitBreaker` trips in [`market/options.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/market/options.py) and `market/history.py`: automatically serves secondary quotes/chains when Fyers trips or returns empty chains (`subscribe_websocket()`, token-to-symbol bridge, `TPSeries` interval table, fail-closed `[]` on missing spot).
  - WebSocket tick payload provides: `lp`, `ap` (exchange intraday VWAP), `v`, `tbq`, `tsq`.
  - Does **NOT** provide server-side market breadth, heatmaps, or advance/decline metrics.

---

## 2. Single Source of Truth (SSOT) Invariants

1. **Market Breadth & Index Lead-Lag in RAM**:
   - `engine.market_matrix.MarketMatrix` computes breadth metrics in-RAM; `engine.feature_bus.compute_constituent_lead_lag()` computes read-only heavyweight impulse for `NIFTY` / `BANKNIFTY` without emitting cash setups under `FNO_ONLY`.

2. **Negative Invariants (Strictly Prohibited Assumptions)**:
   - NEVER claim or assume Fyers TBT provides universe-wide 50-depth order books across all 180+ stocks. It is capped at 15 symbols on Prime and strictly excludes BSE/MCX.
   - NEVER gate alert generation or stop-loss logic on the presence of Level-3 50-depth data for non-NSE symbols.
   - NEVER assume brokers provide server-side breadth or sentiment APIs.
