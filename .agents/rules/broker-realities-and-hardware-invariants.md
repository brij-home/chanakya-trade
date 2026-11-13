# Broker Realities, Data Stream Invariants & Zero-Hallucination Contracts

> **CRITICAL INVARIANT**: Real capital is at stake. Trading decisions, alert generation, stop losses, and market breadth must NEVER be predicated on unverified broker capabilities, aspirational docstrings, or imaginary APIs.

---

## 1. Verified Broker Capabilities & Hard Limits

### FYERS API v3 (Active Subscription: FYERS PRIME)
- **Data Socket (`FYERS_PLAN=PRIME`)**:
  - Maximum **5,000 concurrent symbols** subscription limit across all user data socket connections (standard tier is capped at 100 symbols).
  - Streaming modes: Lite (`mode 1`) and Full (`mode 2` - includes 5-depth DOM).
  - Enables streaming the entire 180+ NSE F&O stock universe, benchmark indices, and hundreds of active option strikes simultaneously into `MarketMatrix`.
- **Bulk Quotes API (`FYERS_PLAN=PRIME`)**:
  - Up to **1,000 symbols per REST request** (standard tier is capped at 50 symbols).
  - **500,000 requests/day** limit (10 req/s, 500 req/min), providing massive headroom for multi-timeframe candle scans, option chains, and Greeks discovery.
- **Fyers TBT 50-Depth WebSocket (`FYERS_PLAN=PRIME`)**:
  - Maximum **15 symbols** total (structured across 3 physical connections/workers with a cap of 5 symbols each). Standard tier is limited to 1 symbol.
  - Strictly supports **NSE Equity (CM) and NFO (Futures & Options)** only.
  - Does **NOT** support BSE (SENSEX, BANKEX) or MCX (Commodities) under any circumstances.
  - Uses binary Protobuf decoding (`versova`) with manual channel-resume handshakes.
  - **Invariant**: TBT is reserved for the top 15 anchor futures and in-flight ATM contracts. General universe scanning and stop-loss execution must not mandate 50-depth DOM.
- **What Fyers Prime Does NOT Provide**:
  - Does **NOT** provide a pre-aggregated Market Breadth API.
  - Does **NOT** provide a real-time Sector Heatmap or Market Map endpoint.
  - Does **NOT** provide pre-computed session VWAP in standard quote packets.

### FLATTRADE (Pi / WebSocket API)
- **Execution & Tick Feed**:
  - Zero brokerage on Equity Intraday, F&O, and Commodities.
  - WebSocket tick payload provides:
    - `lp` — Last Traded Price
    - `ap` — Average Traded Price (= Official Exchange Intraday VWAP)
    - `v` — Cumulative Traded Volume
    - `tbq` — Total Buy Quantity
    - `tsq` — Total Sell Quantity
  - Does **NOT** provide server-side market breadth, heatmaps, or advance/decline metrics.

---

## 2. Single Source of Truth (SSOT) Invariants

1. **Market Breadth & Heatmaps via Fyers Prime 5,000 Stream Capacity**:
   - Because Fyers Prime supports **5,000 streaming symbols**, `market.ws_subscription_manager` subscribes to the complete **180+ NSE F&O universe**.
   - **`engine.market_matrix.MarketMatrix` computes all analytics in-RAM**:
     - Rolling `% Above VWAP` vs `% Below VWAP` (`vwap_ratio`)
     - `% Above Open` (`open_ratio`)
     - Advance/Decline ratio
     - Sub-millisecond ($<0.05\text{ ms}$) in-RAM calculation without external HTTP latency or 3rd-party scraping risks.

2. **Negative Invariants (Strictly Prohibited Assumptions)**:
   - NEVER claim or assume Fyers TBT provides universe-wide 50-depth order books across all 180+ stocks. It is capped at 15 symbols on Prime and strictly excludes BSE/MCX.
   - NEVER gate alert generation or stop-loss logic on the presence of Level-3 50-depth data for non-NSE symbols.
   - NEVER assume brokers provide server-side breadth or sentiment APIs.
