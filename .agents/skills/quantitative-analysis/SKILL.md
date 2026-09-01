---
name: quantitative-analysis
description: >-
  Quantitative analysis workflows in chanakya-trade, including RRG (Relative Rotation Graph)
  sector momentum, Forensic accounting audits (Beneish M-Score, Altman Z-Score, Piotroski F-Score),
  SMC market structure, volume profile analysis, multibagger screening, position sizing,
  and volatility risk-parity with Indian F&O contract lot quantization.
---

# Quantitative Analysis & Risk Engine Runbook

<!-- TOC -->
- [1. RRG Sector Momentum](#1-rrg-sector-momentum)
- [2. Forensic Accounting](#2-forensic-accounting)
- [3. Position Sizing & Risk-Parity](#3-position-sizing--risk-parity)
- [4. Smart Money Concepts (SMC)](#4-smart-money-concepts-smc)
- [5. Volume Price Analysis (VPA)](#5-volume-price-analysis-vpa)
- [6. Multibagger Engine](#6-multibagger-engine)
- [7. Trade Lifecycle & Trailing Stops](#7-trade-lifecycle--trailing-stops)
- [8. Two-Tier Execution Gate](#8-two-tier-execution-gate)
- [9. 3-Axis Magic Trend Engine](#9-3-axis-magic-trend-engine)
- [10. Dynamic ATR Trade Level Calibration](#10-dynamic-atr-trade-level-calibration)
- [11. Retail Protection & Behavioral Coaching](#11-retail-protection--behavioral-coaching)
- [12. Global Macro Correlation & Sector Transmission](#12-global-macro-correlation--sector-transmission)
- [13. Institutional Security 360 Truthfulness Contract](#13-institutional-security-360-truthfulness-contract)
- [14. Testing](#14-testing)
<!-- /TOC -->

---

## 1. RRG Sector Momentum

[`analysis/sector_rotation.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/sector_rotation.py) — Models rotation across 10 NSE sectors relative to NIFTY 50.

| Metric | Description |
| :--- | :--- |
| **JdK RS-Ratio** | Rolling relative strength (>100 = outperforming) |
| **JdK RS-Momentum** | Rate of change of RS-Ratio (>100 = accelerating) |

| Quadrant | RS-Ratio | RS-Momentum | Meaning |
| :--- | :---: | :---: | :--- |
| `LEADING` | ≥100 | ≥100 | Strong uptrend, high momentum |
| `WEAKENING` | ≥100 | <100 | Positive but decelerating |
| `LAGGING` | <100 | <100 | Underperforming benchmark |
| `IMPROVING` | <100 | ≥100 | Early recovery phase |

```python
from analysis.sector_rotation import get_sector_rrg_matrix, get_stock_tailwind

matrix = get_sector_rrg_matrix()
tailwind = get_stock_tailwind("INFY")
# tailwind.quadrant → "LEADING", tailwind.tailwind_score → 95, tailwind.alignment → "STRONG_TAILWIND"
```

---

## 2. Forensic Accounting

[`analysis/forensic.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/forensic.py) — Screens for balance sheet distress and earnings manipulation.

| Model | Threshold | Interpretation |
| :--- | :--- | :--- |
| **Beneish M-Score** | > −1.78 | High probability of earnings manipulation |
| **Altman Z''-Score** | > 2.60 / 1.10–2.60 / < 1.10 | SAFE / GREY / DISTRESS |
| **Piotroski F-Score** | 8–9 / 4–7 / 0–3 | High / Average / Weak quality |
| **Promoter Pledge** | >10% / >20% | Warning / Critical margin call risk |

```python
from analysis.forensic import audit_company_forensics

report = audit_company_forensics("RELIANCE")
# report.quality_rating → "A+" | "A" | "B" | "C" | "D"
# report.overall_forensic_verdict → "CLEAN_PASS" | "MILD_WARNING" | "RED_FLAG"
# report.beneish_m_score, report.altman_z_score, report.piotroski_f_score
```

---

## 3. Position Sizing & Risk-Parity

[`engine/position_sizer.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/position_sizer.py)

| Model | Description |
| :--- | :--- |
| `atr_volatility` | Equalizes risk based on 1.5×ATR volatility stop |
| `fixed_fractional` | Direct stop distance risk sizing |
| `half_kelly` | Kelly criterion × 0.5 for stability |

**F&O Lot Quantization**: Auto-rounds to standard lots (NIFTY 25, BANKNIFTY 15, FINNIFTY 25, MIDCPNIFTY 50, equity lots).

```python
from engine.position_sizer import calculate_position_size

size = calculate_position_size(
    symbol="INFY", entry_price=1500.0, stop_loss=1470.0,
    capital=200000.0, max_risk_pct=1.5, sizing_model="atr_volatility",
)
# size.shares, size.lots, size.capital_allocated, size.risk_amount
```

---

## 4. Smart Money Concepts (SMC)

[`analysis/market_structure.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/market_structure.py)

- **Fractal Swing Points**: HH, HL, LH, LL classification.
- **Structural Shifts**: `CHoCH` (reversal transition), `BOS` (confirmed continuation).
- **Order Blocks**: Unmitigated institutional accumulation/distribution bases.
- **Fair Value Gaps (FVG)**: 3-bar price imbalances with fill ratios.
- **Liquidity Sweeps**: Stop-hunts piercing support/resistance with immediate reclaim.

```python
from analysis.market_structure import analyze_market_structure

report = analyze_market_structure("RELIANCE")
# report.regime → "BULLISH" | "BEARISH" | "RANGING"
# report.setup_type → "BREAKOUT_EXPANSION" | "BOTTOM_FISHING_SPRING" | "PULLBACK_RETEST"
```

---

## 5. Volume Price Analysis (VPA)

[`analysis/volume_profile.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/volume_profile.py)

| Metric | Threshold | Meaning |
| :--- | :--- | :--- |
| **RVOL** (20D/50D) | >2.0× | Institutional expansion |
| **VSA Absorption** | — | Stopping Volume, Effort vs Result |
| **Volume Profile** | — | POC, VAH, VAL levels |

---

## 6. Multibagger Engine

[`analysis/multibagger.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/multibagger.py)

- **Minervini 8-Point Trend Template**: Strict MA alignment, 52-week boundaries, 200 SMA slope.
- **Weinstein Stage 2 Breakout**: Stage 1 base expansion → Stage 2 markup.
- **VCP Contraction**: Progressive narrowing (20% → 10% → 4%) with dry volume.
- **Multibagger Score (0-100)**: Combines Stage 2 + Minervini + RRG tailwinds + Forensic safety.

---

## 7. Trade Lifecycle & Trailing Stops

[`engine/trade_lifecycle.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/trade_lifecycle.py)

| Event | Action |
| :--- | :--- |
| **+2R Payoff** | Book 33–50% profit, shift stop to Breakeven (+0.2% costs) |
| **Structure Trail** | Trail stop behind verified Higher Low swing supports |
| **Chandelier Trail** | Highest Close − (3.0 × ATR) |
| **Runner Protection** | Hold remaining until structural invalidation |

---

## 8. Two-Tier Execution Gate

[`analysis/execution_gate.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/execution_gate.py)

| Tier | Data Source | Outputs |
| :--- | :--- | :--- |
| **Tier 1 Strategic** (180–365D) | Historical quant: Minervini, Weinstein, SMC, RRG, Forensics | Strategic Conviction Score (0–100) |
| **Tier 2 Tactical** (Live) | Entry zone proximity, RVOL surge (≥1.3×), OI flow, TTM Squeeze | Tactical Score (0–100), Verdict (`🟢 READY` / `🟡 STALK` / `🔴 STAND_DOWN`) |

**Data Efficiency**: Single-source 250D OHLCV fetch, passed in-memory across analyzers (66% network reduction). SQLite cache (15min TTL). Enforced tz-naive DatetimeIndex.

---

## 9. 3-Axis Magic Trend Engine

[`analysis/magic_trend.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/magic_trend.py) — Super-Investor scoring for Indian multibagger discovery.

| Axis | Weight | Criteria |
| :--- | :---: | :--- |
| **X (Moat & Quality)** | 35 pts | ROCE ≥20%, Low D/E, Pristine Forensics (Beneish <−1.78, Altman Z'' >2.60), CFO ≥80% |
| **Y (Growth & Migration)** | 35 pts | Sales/PAT CAGR ≥25%, Small/Mid runway, High reinvestment |
| **Z (Timing & Asymmetry)** | 30 pts | Weinstein Stage 2, Minervini 8/8, VCP pivot, PEG ≤1.0 |

Generates dynamic ATR trade tickets: Entry, Stop-Loss (1.2×ATR), Target 1 (2R), Target 2 (3.5R), and trailing stop rules.

---

## 10. Dynamic ATR Trade Level Calibration

When generating automated trade tickets:
- **ATR Bounds**: Stop-loss bounded by 1.0×–1.2×ATR. Anchored to unmitigated OB boundaries.
- **SMC OTE**: Entry targets 50% Mean Threshold of active Order Block.
- **Directional Integrity**: `LONG` → Entry at Demand OTE, Stop below base. `SHORT` → Entry at Supply OTE, Stop above base.
- **Timeline Horizons**:

| Timeframe | Holding Period |
| :--- | :--- |
| 5m / 15m | 1–3 Trading Sessions (Intraday Swing) |
| 1h | 2–5 Trading Days (Swing Pivot) |
| 1D / Daily | 5–15 Trading Days (Positional Markup) |
| 1W / Weekly | 3–8 Weeks (Trend Continuation) |

---

## 11. Retail Protection & Behavioral Coaching

[`engine/risk_limits.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/risk_limits.py), [`engine/risk_gate.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/risk_gate.py)

- **`evaluate_preflight()`**: Computes risk flags (`TILT_LOCKOUT`, `PYRAMID_INTO_LOSER`, `DAILY_LOSS_CAP`) without hard-blocking.
- **Coaching Advisory**: Prompts with failure probabilities and alternatives (reduce risk to 0.5%, cool off).
- **Double Confirmation**: Allows execution when user consciously confirms (`allow_override=True`).
- **Defined-Risk Spreads** ([`engine/defined_risk_spreads.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/defined_risk_spreads.py)): Bull/Bear Call/Put Spreads, Iron Condors with quantized payoff.
- **Tax Engine** ([`engine/charges.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/charges.py)): STCG 20%, LTCG 12.5%, F&O turnover audit thresholds, tax-loss harvesting.

---

## 12. Global Macro Correlation & Sector Transmission

[`market/global_macro.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/market/global_macro.py) — Evaluates the High-Correlation 6 global drivers that directly move Dalal Street:

| Global Indicator | Correlation | Sector / Market Transmission Channel |
| :--- | :---: | :--- |
| **GIFT NIFTY** (`^NSEIFSC`) | ~0.96 | Pre-market opening gap predictor (`implied_nifty_gap_pct`, `pts`) |
| **NASDAQ 100** (`^IXIC`) | ~0.82 | Overnight sentiment for Indian IT Services (`TCS`, `INFY`, `HCLTECH`, `COFORGE`) |
| **US Dollar Index** (DXY) | -0.74 | FII foreign equity flows; DXY surge triggers EM outflows in Largecap Banks |
| **Brent Crude Oil** (`BZ=F`) | -0.78 / +0.82 | Negative for Paints (`ASIANPAINT`), Aviation (`INDIGO`), OMCs; Positive for Upstream (`ONGC`, `OIL`) |
| **US 10Y Yield** (`^TNX`) | -0.70 | Global hurdle rate & multiple contraction across High-PE growth compounders |
| **US VIX vs India VIX** | ~0.68 | Volatility contagion, options writing risk-parity & ATR band calibration |

```python
from market.global_macro import fetch_global_macro_report

report = fetch_global_macro_report(nifty_spot=24150.0)
# report.composite_score -> -100 to +100
# report.global_posture -> "RISK_ON" | "NEUTRAL" | "RISK_OFF" | "VOLATILE_CAUTION"
# report.implied_nifty_gap_pct, report.sector_impacts
```

---

## 13. Institutional Security 360 Truthfulness Contract

[`engine/security_360.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/security_360.py) — Enforces zero-fabrication standards across all institutional equity dossiers:

- **Live Quote Truthfulness**: If current price is missing or quote fetch fails, returns `_status="UNAVAILABLE"`, `current_price=0.0`, `decision=None`, and `methodology_lenses=[]`. Hardcoded price fallbacks are strictly prohibited.
- **Valuation Integrity**: Returns `valuation_status="UNAVAILABLE"` and `valuation_fair_value=None` until real DCF computation is wired. Never returns static price multiplier approximations (`price × 1.15`).
- **Forensic Status**: Directly calls `analysis.forensic.audit_company_forensics()`. Returns `UNAVAILABLE` on database/network exception; never defaults or hardcodes `"CLEAN"`.
- **Methodology Lenses**: Emits `[]` until real multi-factor quantitative lenses are calculated. Lenses are never pre-populated with synthetic `BULLISH` verdicts.
- **Decision Summary**: `decision` is set to `None` when lenses are empty or quote is unavailable. No trade levels or stop-loss recommendations are generated without verified live data.

```python
from engine.security_360 import build_security_360_dossier

dossier = build_security_360_dossier("RELIANCE")
# If live quote fails: dossier._status -> "UNAVAILABLE", dossier.decision -> None
# If live quote succeeds: dossier._status -> "PARTIAL", dossier.forensic_status -> "CLEAN" | "FLAGGED"
```

---

## 14. Testing

```powershell
# Security 360 truthfulness & unavailable status verification
.venv\Scripts\pytest.exe tests/test_security_360_unavailable.py -v

# Quantitative, global macro, retail protection & structural test suites
.venv\Scripts\pytest.exe tests/test_global_macro.py tests/test_market_structure.py tests/test_volume_profile.py tests/test_multibagger.py tests/test_trade_lifecycle.py tests/test_execution_gate.py tests/test_retail_protection.py -v

# Complete fast suite
.venv\Scripts\pytest.exe -n 4
```
