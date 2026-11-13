# Quantitative Metric Hierarchy & Anti-Oversimplification Invariants

> **CRITICAL INVARIANT**: Never collapse nuanced multi-dimensional quantitative market metrics into crude, primitive scalar checks (e.g. blindly checking `if rvol > 1.5:`). Real trading capital depends on exact mathematical definitions, localized timeframe context, and contract-level liquidity.

---

## 1. The Metric Taxonomy & Mandatory Use Cases

### A. Volume Metrics: Which RVOL to Use Where?

| Metric | Mathematical Formula | Intended Scope & Use Case | Anti-Pattern (What is BANNED) |
| :--- | :--- | :--- | :--- |
| **TOD-RVOL** *(Time-of-Day)* | $\frac{\text{Current Cumulative Volume}}{\text{Avg Daily Vol} \times \text{ExpectedFraction}(t)}$ | **Session-Level Momentum Gates** (e.g., Morning Reversal Zone 10:15–11:00, Midday Lull 11:30–13:15, and Radar Screening). | **NEVER** use raw unadjusted daily RVOL ($\frac{\text{Vol}}{\text{Avg20}}$) before 14:00. At 09:30 AM, volume is naturally only ~15% of daily volume; using raw RVOL guarantees false negative rejections. |
| **Bar Impulse RVOL** *(5-Bar / 20-Bar)* | $\max\left(\frac{V_{\text{candle}}}{\text{SMA}_5(V)}, \frac{V_{\text{candle}}}{\text{SMA}_{20}(V)}\right)$ | **Breakout Thrusts, Liquidity Sweeps, SFP Reversals, Orderblock Retests**. | **NEVER** veto an explosive breakout candle showing $3.0\text{x}$ 5-bar impulse surge simply because total session cumulative volume hasn't caught up yet. |
| **Hybrid RVOL** | $0.60 \times \text{Bar-RVOL} + 0.40 \times \text{TOD-RVOL}$ | **Institutional Volume Profile & Setup Conviction Scoring** in [`engine/daily_levels.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/daily_levels.py). | **NEVER** ignore localized candle volume when evaluating session pace. |
| **Option Contract Turnover & Vol/OI** | $\text{Premium} \times \text{Volume}$ and $\frac{\text{Contract Volume}}{\max(1, \text{Contract OI})}$ | **All Option Buying Strategies** (`OPTIONS_MOMENTUM`, `GAMMA_BLAST`, `INDEX_CALL_SETUP`, `INDEX_PUT_SETUP`). | **NEVER** use underlying equity/index volume as a proxy for option liquidity. An option buying setup requires contract turnover $\ge ₹2\text{ Cr}$ (stocks) or $\ge ₹10\text{ Cr}$ (indices) and $\text{Vol/OI} \ge 1.0\text{x}$. |

---

## 2. Order Flow & Microstructure Invariants

### B. Cumulative Volume Delta (CVD)
- Computed via [`calculate_intraday_cvd(df_5m)`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/daily_levels.py).
- **Absorption Protection**:
  - If a Bullish Breakout triggers but 5m CVD shows `BEARISH_EXHAUSTION`: **VETO OR DEGRADE**. Institutional passive limit sellers are absorbing aggressive retail buyers at the highs.
  - If a Bearish Breakdown triggers but 5m CVD shows `BULLISH_EXHAUSTION`: **VETO OR DEGRADE**. Institutional passive limit buyers are absorbing aggressive market sellers at the lows.

### C. Intraday VWAP & Boundary Harmony
- **SSOT**: In-RAM [`MarketMatrix`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/market_matrix.py) or Flattrade `ap` tick.
- **Directional Alignment Invariants**:
  - **No Knife-Catching**: A Bullish Call bounce (e.g. `IB_BOUNCE_LOW`) is strictly prohibited when spot is trading below session VWAP with declining momentum.
  - **No Top-Fading**: A Bearish Put fade (e.g. `IB_FADE_HIGH`) is strictly prohibited when spot is surging above session VWAP with expanding momentum.
  - **Breakdown Acceptance**: When price reaches or slips below Initial Balance Low under VWAP liquidation, the system must prioritize `INITIAL_BALANCE_BREAKDOWN_PRESSURE` (Put setups) rather than buying counter-trend calls.

---

## 3. Structural Level & Range Invariants

### D. Average Daily Range (ADR) Exhaustion
- Computed from 14-period daily ADR ($\text{High} - \text{Low}$).
- **The 85% Exhaustion Rule**:
  - If intraday move ($\text{Spot} - \text{Day Low}$ for longs, or $\text{Day High} - \text{Spot}$ for shorts) exceeds **85% of ADR**:
    - Disallow chasing breakout highs/lows.
    - Require a minimum $38.2\%$ Fibonacci pullback or 20-EMA base consolidation before permitting late-session continuation.

### E. Central Pivot Range (CPR) Width
- **Wide CPR Core Rule**:
  - When $TC - BC \ge 0.40\%$ of spot, price is structurally prone to rotational chop inside the CPR core.
  - Directional breakout alerts initiated inside a Wide CPR core are **strictly vetoed** unless supported by $RVOL \ge 2.50\text{x}$ and a clear structural close outside the pivot band.

---

## 4. Coding Standard for Future Updates

Whenever authoring, refactoring, or reviewing detectors, filters, or scrutiny rules:
1. **Explicit Naming**: Never name a variable just `rvol`. Always use `tod_rvol`, `bar_rvol`, `hybrid_rvol`, or `option_turnover_cr`.
2. **Context-Aware Gates**: When gating an alert on volume, check the time of day:
   ```python
   # Correct Institutional Pattern:
   if is_intraday_breakout:
       # Check 5-bar candle impulse surge OR time-of-day normalized volume
       if bar_rvol < 2.0 and tod_rvol < 1.5:
           continue
   ```
3. **Preserve Valid Domain Distinctions**: Never simplify or replace multi-bar impulse metrics or contract-level option checks with a blunt scalar check.

---

## 5. Active Canonical Lot Sizes & Instrument Master Authority

All lot sizes, tick sizes, freeze limits, and multipliers **MUST** resolve strictly from [`market.instruments.STANDARD_LOT_SIZES`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/market/instruments.py) and `get_fno_lot_size(symbol)`.

### Official Exchange Lot Sizes (Active Contract Master):
- **`NIFTY`**: **65** (NSE circular NSE/FAOP/70616; strictly 65. BANNED: legacy 75, 50, 25).
- **`BANKNIFTY`**: **30** (strictly 30. BANNED: legacy 35, 25, 15).
- **`FINNIFTY`**: **60** (strictly 60. BANNED: legacy 65, 40, 25).
- **`MIDCPNIFTY`**: **120** (strictly 120. BANNED: legacy 140, 75, 50).
- **`SENSEX`**: **20** (for active Nov/Dec 2026 expiries) / **25** (for Jan 2027+ expiries per BSE Notice 20260930-58; BANNED: legacy 10 or hedging with "10/20").
- **`BANKEX`**: **30** (strictly 30. BANNED: legacy 15).

### Mandatory Rule for AI Agents & Developers:
- **Zero Obsolete Citing**: Never cite, calculate with, or use legacy numbers in prose, chat explanations, test fixtures, docstrings, or mathematical examples (e.g. NEVER say "NIFTY 1 lot (75 qty)" or "SENSEX 10").
- Every calculation of contract turnover, premium risk, portfolio exposure, margin, or position size MUST strictly utilize the active canonical lot size.
