---
name: strategy-supercharge
description: >-
  Iterative multi-agent quantitative strategy optimization loop ("Supercharge Mode").
  A 12-seat specialist strategist council (Risk, Return, Entry, Exit, Regime,
  Integrity, Execution, Options, Capital Efficiency, Simplicity, Variant Generation,
  Performance Ranking) analyzes backtests, debates improvements, generates controlled
  variants, and enforces 4 binding vetoes against overfitting and ruin risk.
---

# Strategy Supercharge Mode — Multi-Agent Optimization Runbook

Turn a single backtested strategy into an evolving research project. A central **orchestrator** convenes a **council of 12 specialist strategists** that study the strategy, debate improvements, generate optimized variants, backtest them, and keep searching for measurably better versions — in iterative cycles with user checkpoints every 3 rounds.

Implemented in [`engine/supercharge.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/supercharge.py) and scored via [`engine/quantstats_report.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/quantstats_report.py).

---

## 1. Core Invariants & Philosophy

1. **The Baseline is Sacred**: The original strategy is captured once as an immutable baseline and never overwritten. Every variant is benchmarked against it.
2. **Improve, Not Just Validate**: The goal is to discover measurably better parameter and structural variants without introducing curve-fitting or parameter bloat.
3. **Controlled Variance**: Each variant modifies **at most 1–2 variables** (e.g. ATR trailing stop multiplier or regime volatility filter) so causal attribution remains clean.
4. **Binding Vetoes**: Four seats possess absolute veto power. No variant can be accepted if an active veto remains unresolved.

---

## 2. The 12-Seat Council Roster & Veto Powers

| Seat | Domain | Mandate | Owned Metrics | Veto Power |
| :--- | :--- | :--- | :--- | :---: |
| **Risk** | Drawdown, tail risk, position sizing | Cap ruin risk without killing edge | `max_drawdown`, `volatility_ann`, `largest_loss` | 🛑 **VETO**: Ruin risk (>35% DD surge) |
| **Return** | Profitability, CAGR, profit factor | Maximize profit, reject cosmetic changes | `total_return_pct`, `cagr`, `profit_factor` | — (Advisory) |
| **Entry Precision** | Signal timing, confirmation, filters | Sharpen entries and eliminate whipsaws | `trade_win_rate`, `avg_profit` | — (Advisory) |
| **Exit Intelligence** | Stops, targets, trailing rules, time exits | Cut losers quickly and let winners run | `avg_loss`, `profit_factor`, `largest_loss` | — (Advisory) |
| **Market Regime** | Trend vs range, high vs low volatility | Expose regime dependence, add macro filters | `robustness_score`, `positive_period_pct` | — (Advisory) |
| **Backtest Integrity** | Look-ahead, data-snooping, curve-fitting | Guarantee improvements survive out-of-sample | `robustness_score` | 🛑 **VETO**: Overfit (OOS score < 0.35) |
| **Execution** | Broker limits, slippage, liquidity | Keep strategy executable under broker limits | `trade_count` | 🛑 **VETO**: Rate-limit breach (>1000 orders) |
| **Options** | Strike/expiry selection, Greeks, IV | Optimize delta/theta posture and spreads | `total_return_pct`, `max_drawdown` | — (Advisory) |
| **Capital Efficiency** | Margin utilization, idle cash drag | Maximize return per rupee of margin | `cagr` | — (Advisory) |
| **Simplicity** | Parsimony, parameter penalty | Guard against 'one more parameter' overfit | `robustness_score` | 🛑 **VETO**: Complexity without $\ge10\%$ Sharpe gain |
| **Variant Generation** | Authoring controlled variant mutations | Turn debate consensus into candidate code | — | — (Authoring) |
| **Performance Ranking** | Apples-to-apples scorecard ranking | Order variants by objective on standard metrics | All metrics | — (Ranking) |

---

## 3. The 6-Phase Optimization Cycle

Each round proceeds through six distinct stages:

```
[Phase 1: Understand]      Study rules, sizing, capital, timeframe, and baseline scorecard.
        ↓
[Phase 2: Diagnose]        Identify bottlenecks, hidden tail risks, and missed opportunities.
        ↓
[Phase 3: Debate]          Seats challenge each other; consensus rule resolves clashes.
        ↓
[Phase 4: Generate]        Variant Generation Strategist authors candidate (≤2 variables changed).
        ↓
[Phase 5: Backtest]        Run identical backtest assumptions via engine.backtest; score via quantstats.
        ↓
[Phase 6: Learn]           Log decisions and variants to evolution_log.jsonl; feed next round.
```

---

## 4. Human Oversight: 3-Round Checkpoints

**Never continue indefinitely in autonomous loops.** After every 3 rounds:
1. Render the **Comparison Dashboard** (`render_comparison_dashboard()`).
2. Present the current leading variant vs baseline.
3. Summarize accepted improvements, discarded variants, and major dissents.
4. Solicit user direction:
   - *Continue general search*
   - *Focus on Drawdown reduction*
   - *Focus on Win Rate & Consistency*
   - *Finalize and generate QuantStats HTML report*

---

## 5. Standard Workflow Example

```python
from engine.supercharge import evaluate_variant_vetoes, render_comparison_dashboard, EvolutionLog, StrategyVariant
from engine.quantstats_report import key_metrics, generate_html_tear_sheet

# 1. Capture baseline
base_metrics = key_metrics(base_returns, trades=base_trades)

# 2. Evaluate candidate variant
var_metrics = key_metrics(var_returns, trades=var_trades)
passed, vetoes, reason = evaluate_variant_vetoes(base_metrics, var_metrics, params={"added_rules": ["ATR_trail"]})

# 3. Log to journal
log = EvolutionLog()
log.log_entry("variant_evaluated", {
    "variant_id": "v1_atr_trailing",
    "accepted": passed,
    "vetoes": vetoes,
    "metrics": var_metrics,
})

# 4. Generate comparison dashboard
dashboard_md = render_comparison_dashboard("EMA_Trend", base_metrics, [
    StrategyVariant(
        variant_id="v1_atr_trailing",
        round_no=1,
        objective="sharpe",
        params={},
        scorecard=var_metrics,
        rules_changed=["ATR Trailing Stop 2.5x"],
        is_accepted=passed,
        rejection_reason=reason,
    )
], objective="sharpe")
```

---

## 6. Testing

```powershell
.venv\Scripts\pytest.exe tests/test_supercharge.py -v
.venv\Scripts\pytest.exe tests/test_quantstats_report.py -v
```
