---
name: quantitative-analysis
description: >-
  Quantitative analysis workflows in chanakya-trade, including RRG (Relative Rotation Graph)
  sector momentum, Forensic accounting audits (Beneish M-Score, Altman Z-Score, Piotroski F-Score),
  and volatility risk-parity position sizing with Indian F&O contract lot quantization.
---

# Quantitative Analysis & Risk Engine Runbook

## 1. Relative Rotation Graph (RRG) Sector Momentum

The RRG engine ([`analysis/sector_rotation.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/sector_rotation.py)) models sector rotation across 10 major NSE sectors relative to NIFTY 50:

- **JdK RS-Ratio (Trend)**: Rolling relative strength normalized to 100 baseline ($>100$ = outperforming).
- **JdK RS-Momentum (Velocity)**: Rate of change of RS-Ratio ($>100$ = accelerating).
- **Quadrants**:
  - `LEADING`: RS-Ratio $\ge 100$, RS-Momentum $\ge 100$ (Strong uptrend, high momentum).
  - `WEAKENING`: RS-Ratio $\ge 100$, RS-Momentum $< 100$ (Trend positive but decelerating).
  - `LAGGING`: RS-Ratio $< 100$, RS-Momentum $< 100$ (Underperforming benchmark).
  - `IMPROVING`: RS-Ratio $< 100$, RS-Momentum $\ge 100$ (Early recovery phase).
- **Usage**:
  ```python
  from analysis.sector_rotation import get_sector_rrg_matrix, get_stock_sector_alignment

  # Get matrix of all 10 NSE sectors
  matrix = get_sector_rrg_matrix()

  # Check specific stock alignment
  alignment = get_stock_sector_alignment("INFY")
  # Returns: {"symbol": "INFY", "sector": "IT", "quadrant": "LEADING", "tailwind_score": 85, "alignment": "STRONG_TAILWIND"}
  ```

---

## 2. Forensic Accounting & Corporate Governance Audit

The forensic auditor ([`analysis/forensic.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/forensic.py)) screens for balance sheet distress and earnings manipulation:

1. **Beneish M-Score (8-Variable Model)**:
   - $M > -1.78$: High probability of earnings manipulation.
   - Variables: Days Sales in Receivables (DSRI), Gross Margin (GMI), Asset Quality (AQI), Sales Growth (SGI), Depreciation (DEPI), SGA Expenses (SGAI), Leverage (LVGI), Total Accruals to Total Assets (TATA).
2. **Altman Z''-Score (Emerging Market Model)**:
   - $Z'' > 2.60$: **SAFE** credit zone.
   - $1.10 \le Z'' \le 2.60$: **GREY** zone.
   - $Z'' < 1.10$: **DISTRESS** / high bankruptcy probability.
3. **Piotroski 9-Point F-Score**:
   - 8–9: High Quality | 4–7: Average | 0–3: Weak Quality.
4. **Governance Red Flag Checks**:
   - Promoter share pledge $>10\%$ (warning) and $>20\%$ (critical margin call risk).
   - Low interest coverage ($<2.0\text{x}$).
   - High financial leverage ($D/E > 2.2\text{x}$).
   - Accruals divergence (Negative operating cash flow with positive net income).
- **Usage**:
  ```python
  from analysis.forensic import audit_forensics

  report = audit_forensics("RELIANCE")
  # report.quality_rating -> "A+" | "A" | "B" | "C" | "D"
  # report.beneish_m_score, report.altman_z_score, report.piotroski_f_score
  # report.governance_red_flags -> list[str]
  ```

---

## 3. Institutional Position Sizing & Risk-Parity

The sizing engine ([`engine/position_sizer.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/position_sizer.py)) computes risk-calibrated position sizes:

- **Sizing Models**:
  - `atr_volatility`: Equalizes risk based on asset volatility ($1.5 \times \text{ATR}$ volatility stop).
  - `fixed_fractional`: Direct stop distance risk sizing.
  - `half_kelly`: Kelly criterion growth formula scaled by 0.5 for stability.
- **F&O Contract Lot Quantization**: Automatically rounds shares to standard Indian derivative lot sizes (NIFTY 25, BANKNIFTY 15, FINNIFTY 25, MIDCPNIFTY 50, equity lots).
- **Usage**:
  ```python
  from engine.position_sizer import calculate_position_size

  size = calculate_position_size(
      symbol="INFY",
      entry_price=1500.0,
      stop_loss=1470.0,
      capital=200000.0,
      max_risk_pct=1.5,
      sizing_model="atr_volatility",
  )
  # size.shares, size.lots, size.capital_allocated, size.risk_amount
  ```

---

## 4. Smart Money Concepts (SMC) & Market Structure

The market structure engine ([`analysis/market_structure.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/market_structure.py)) identifies structural regimes and institutional footprints:

- **Fractal Swing Points**: Classifies price action into Higher Highs (HH), Higher Lows (HL), Lower Highs (LH), and Lower Lows (LL).
- **Structural Shifts**:
  - `CHoCH` (Change of Character): Early reversal transition (Bottom Fishing / Wyckoff Spring).
  - `BOS` (Break of Structure): Confirmed trend continuation breakout.
- **Order Blocks (OB) & Fair Value Gaps (FVG)**:
  - Demand Order Blocks: Unmitigated institutional accumulation bases.
  - Fair Value Gaps (FVG): 3-bar price imbalances with fill ratios.
  - Liquidity Sweeps: Stop-hunts that pierce key support/resistance and immediately reclaim the range.
- **Usage**:
  ```python
  from analysis.market_structure import analyze_market_structure

  report = analyze_market_structure("RELIANCE")
  # report.regime -> "BULLISH" | "BEARISH" | "RANGING"
  # report.setup_type -> "BREAKOUT_EXPANSION" | "BOTTOM_FISHING_SPRING" | "PULLBACK_RETEST"
  # report.nearest_support, report.invalidation_level, report.target_1
  ```

---

## 5. Volume Price Analysis (VPA) & Volume Profile

The volume engine ([`analysis/volume_profile.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/volume_profile.py)) computes institutional accumulation/distribution:

- **Relative Volume (RVOL)**: Current volume vs 20-day and 50-day moving averages ($>2.0\text{x}$ is institutional expansion).
- **Volume Spread Analysis (VSA)**: Absorption / Stopping Volume, Effort vs Result (Distribution), and Volume Dry-Up on pullbacks.
- **Volume Profile**: Point of Control (POC), Value Area High (VAH), and Value Area Low (VAL).

---

## 6. Multibagger & Positional Opportunity Engine

The multibagger engine ([`analysis/multibagger.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/multibagger.py)) screens for high-growth superperformers:

- **Mark Minervini 8-Point Trend Template**: Strict moving average alignment, 52-week high/low boundaries, and upward 200 SMA slope.
- **Stan Weinstein Stage 2 Breakout**: Identifies Stage 1 base expansion into Stage 2 markup.
- **VCP Contraction**: Detects progressive narrowing of swing depths (e.g. $20\% \rightarrow 10\% \rightarrow 4\%$) with dry volume.
- **Multibagger Score (0-100)**: Combines Stage 2, Minervini criteria, RRG sector tailwinds, and Forensic accounting safety.

---

## 7. Trade Lifecycle & Dynamic Trailing Stop-Loss

The lifecycle engine ([`engine/trade_lifecycle.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/trade_lifecycle.py)) manages live positions:

- **2R Breakeven Pivot**: At $+2R$ payoff, triggers recommendation to book $33\%\text{--}50\%$ profit and auto-shift Stop-Loss to Breakeven (+ costs).
- **Dynamic Trailing Stops**:
  - `STRUCTURE_HL_TRAIL`: Trails stop behind verified Higher Low swing supports.
  - `CHANDELIER_ATR_TRAIL`: $\text{Highest Close} - (3.0 \times \text{ATR})$.
- **Multibagger Runner Protection**: Holds remaining runner until structural invalidation.

---

## 8. Two-Tier Execution Gate & Single-Source OHLCV Efficiency

The execution gate ([`analysis/execution_gate.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/execution_gate.py)) unites historical edge with live order flow:

1. **🏛️ Tier 1: Strategic Edge (180–365D Historical Quant)**:
   - Evaluates Minervini Trend Template, Weinstein Stage 2, SMC unmitigated order blocks, RRG momentum, and Forensic governance.
   - Outputs **Strategic Conviction Score (0–100)**.
2. **⚡ Tier 2: Tactical Microstructure (Live Tick & Order Flow)**:
   - Evaluates live entry zone proximity ($\pm 0.5\%$), intraday RVOL surge ($\ge 1.3\text{x}$), options OI flow (`LONG_BUILDUP` vs `SHORT_BUILDUP`), and TTM Squeeze firing.
   - Outputs **Tactical Execution Score (0–100)** and Verdict (`🟢 READY`, `🟡 STALK`, `🔴 STAND_DOWN`).
3. **Data Reuse & Caching Architecture**:
   - Single-source OHLCV: Fetch 250D Daily OHLCV once and pass the DataFrame in-memory across all analyzers (reduces network overhead by 66%).
   - Fast SQLite Cache: Persist features in `analysis_cache` (15m TTL).
   - Timezone normalization: Enforce tz-naive DatetimeIndex (`df.index.tz_localize(None)`).

---

## 9. Testing & Verification

```powershell
# Run quantitative and structural test suites
.venv\Scripts\pytest.exe tests/test_market_structure.py tests/test_volume_profile.py tests/test_multibagger.py tests/test_trade_lifecycle.py tests/test_execution_gate.py -v
```
