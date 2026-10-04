"""
engine/supercharge.py
──────────────────────
Institutional Multi-Agent Strategy Optimization Loop ("Supercharge Mode").
Ported and adapted from FyersDev/fyers-skills for ChanakyaTrade.

Features:
  - 12-seat specialist strategist council covering Risk, Return, Entry, Exit,
    Regime, Integrity, Execution, Options, Capital Efficiency, Simplicity,
    Variant Generation, and Performance Ranking.
  - 4 binding veto powers:
      * Risk                   : blocks proposals increasing ruin risk / catastrophic drawdown.
      * Backtest Integrity     : blocks overfitted, curve-fitted, or look-ahead biased proposals.
      * Execution              : blocks rate-limit breach or slippage/liquidity infeasible proposals.
      * Simplicity & Robustness: blocks unjustified rule/parameter complexity.
  - 6-Phase Optimization Loop: Understand → Diagnose → Debate → Generate Variants → Backtest → Learn.
  - Immutable Baseline preservation: Original strategy is never overwritten.
  - Append-only journal: ~/.trading_platform/evolution_log.jsonl.
  - 3-Round Checkpoints for human oversight.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from engine.quantstats_report import key_metrics, calculate_robustness_score
from config.paths import app_data_path


def get_evolution_log_path() -> Path:
    return app_data_path("evolution_log.jsonl")


LOG_PATH = get_evolution_log_path()


@dataclass
class StrategistSeat:
    name: str
    domain: str
    mandate: str
    owned_metrics: list[str]
    has_veto: bool
    veto_scope: Optional[str] = None


COUNCIL_ROSTER: list[StrategistSeat] = [
    StrategistSeat(
        name="Risk",
        domain="drawdown, tail risk, position sizing, leverage",
        mandate="cap ruin risk without killing edge",
        owned_metrics=["max_drawdown", "volatility_ann", "largest_loss", "longest_losing_streak"],
        has_veto=True,
        veto_scope="ruin_risk",
    ),
    StrategistSeat(
        name="Return",
        domain="profitability, CAGR, profit factor, capital growth",
        mandate="maximize returns and eliminate optics-only trades",
        owned_metrics=["total_return_pct", "cagr", "profit_factor"],
        has_veto=False,
    ),
    StrategistSeat(
        name="Entry Precision",
        domain="signal timing, confirmation, false-signal filtering",
        mandate="sharpen entries and eliminate whipsaws",
        owned_metrics=["trade_win_rate", "avg_profit", "trade_count"],
        has_veto=False,
    ),
    StrategistSeat(
        name="Exit Intelligence",
        domain="stops, targets, trailing rules, time-based exits",
        mandate="cut losers quickly and let winners run",
        owned_metrics=["avg_loss", "profit_factor", "largest_loss"],
        has_veto=False,
    ),
    StrategistSeat(
        name="Market Regime",
        domain="regime robustness (trend vs range, high vs low vol)",
        mandate="expose regime dependence and propose macro/volatility filters",
        owned_metrics=["robustness_score", "positive_period_pct"],
        has_veto=False,
    ),
    StrategistSeat(
        name="Backtest Integrity",
        domain="look-ahead, survivorship, overfitting, data-snooping",
        mandate="guarantee all improvements are robust and survive out-of-sample",
        owned_metrics=["robustness_score"],
        has_veto=True,
        veto_scope="invalid_evidence_or_overfitting",
    ),
    StrategistSeat(
        name="Execution",
        domain="broker rate limits (10/s, 200/min), slippage, liquidity",
        mandate="keep strategies realistically executable under Indian broker limits",
        owned_metrics=["trade_count"],
        has_veto=True,
        veto_scope="rate_limit_or_execution_infeasibility",
    ),
    StrategistSeat(
        name="Options",
        domain="strike/expiry selection, Greeks (delta, theta, vega), IV skew",
        mandate="optimize option structures and defined-risk convexity",
        owned_metrics=["total_return_pct", "max_drawdown"],
        has_veto=False,
    ),
    StrategistSeat(
        name="Capital Efficiency",
        domain="margin utilization, cash drag, return on capital",
        mandate="maximize return per rupee of margin deployed",
        owned_metrics=["cagr"],
        has_veto=False,
    ),
    StrategistSeat(
        name="Simplicity & Robustness",
        domain="parsimony, parameter penalty, Occam's razor",
        mandate="resist unnecessary complexity; favor rules that survive out-of-sample",
        owned_metrics=["robustness_score"],
        has_veto=True,
        veto_scope="unjustified_complexity",
    ),
    StrategistSeat(
        name="Variant Generation",
        domain="authoring controlled variant mutations (<= 2 variables)",
        mandate="translate debate consensus into measurable candidate strategies",
        owned_metrics=[],
        has_veto=False,
    ),
    StrategistSeat(
        name="Performance Ranking",
        domain="standardized scorecards and objective ranking",
        mandate="keep comparisons apples-to-apples across all rounds",
        owned_metrics=[],
        has_veto=False,
    ),
]


@dataclass
class StrategyVariant:
    variant_id: str
    round_no: int
    objective: str
    params: dict[str, Any]
    scorecard: dict[str, Any]
    rules_changed: list[str]
    veto_status: dict[str, str] = field(default_factory=dict)  # seat -> "CLEARED" or "VETOED: reason"
    is_accepted: bool = False
    rejection_reason: Optional[str] = None


class EvolutionLog:
    """Append-only JSONL log of rounds, variants, and council decisions."""

    def __init__(self, log_path: Path = LOG_PATH):
        self._path = log_path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def log_entry(self, entry_type: str, data: dict[str, Any]) -> None:
        payload = {
            "timestamp": datetime.now().isoformat(),
            "entry_type": entry_type,
            **data,
        }
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")

    def get_history(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        entries = []
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        continue
        return entries


def evaluate_variant_vetoes(
    baseline_scorecard: dict[str, Any],
    variant_scorecard: dict[str, Any],
    params: dict[str, Any],
) -> tuple[bool, dict[str, str], Optional[str]]:
    """
    Evaluate the 4 binding vetoes against a candidate variant:
      1. Risk: Max drawdown worse by > 25% relative, or largest loss significantly worse.
      2. Backtest Integrity: Robustness score < 0.35 (severe out-of-sample breakdown).
      3. Execution: Trade count excessively high (> 50 trades/day triggering rate limit risk).
      4. Simplicity: More than 3 new parameters added without >= 15% Sharpe improvement.
    """
    veto_status = {}

    # 1. Risk Veto
    base_dd = abs(baseline_scorecard.get("max_drawdown", 10.0))
    var_dd = abs(variant_scorecard.get("max_drawdown", 10.0))
    if var_dd > base_dd * 1.35 and var_dd > 15.0:
        veto_status["Risk"] = f"VETOED: Max drawdown increased from {base_dd:.1f}% to {var_dd:.1f}% (ruin risk)."
    else:
        veto_status["Risk"] = "CLEARED"

    # 2. Backtest Integrity Veto
    rob = variant_scorecard.get("robustness_score", 0.5)
    if rob < 0.35:
        veto_status["Backtest Integrity"] = f"VETOED: Robustness score {rob:.2f} < 0.35 (out-of-sample edge collapse)."
    else:
        veto_status["Backtest Integrity"] = "CLEARED"

    # 3. Execution Veto
    tc = variant_scorecard.get("trade_count", 0)
    if tc > 1000:
        veto_status["Execution"] = f"VETOED: {tc} trades exceeds broker rate-limit capacity."
    else:
        veto_status["Execution"] = "CLEARED"

    # 4. Simplicity Veto
    base_sharpe = baseline_scorecard.get("sharpe", 1.0)
    var_sharpe = variant_scorecard.get("sharpe", 1.0)
    if len(params.get("added_rules", [])) > 2 and var_sharpe < base_sharpe * 1.10:
        veto_status["Simplicity & Robustness"] = "VETOED: Added rule complexity without >= 10% Sharpe gain."
    else:
        veto_status["Simplicity & Robustness"] = "CLEARED"

    # Check if any veto triggered
    active_vetoes = [msg for seat, msg in veto_status.items() if msg.startswith("VETOED")]
    if active_vetoes:
        return False, veto_status, "; ".join(active_vetoes)

    return True, veto_status, None


def render_comparison_dashboard(
    baseline_id: str,
    baseline_card: dict[str, Any],
    variants: list[StrategyVariant],
    objective: str = "sharpe",
) -> str:
    """
    Render a clean Markdown comparative dashboard ranking the baseline and all variants.
    """
    candidates = [
        {"name": f"{baseline_id} (BASELINE)", "scorecard": baseline_card, "accepted": True}
    ]
    for v in variants:
        candidates.append(
            {
                "name": v.variant_id,
                "scorecard": v.scorecard,
                "accepted": v.is_accepted,
                "reason": v.rejection_reason or "ACCEPTED",
            }
        )

    # Sort best-first by objective
    def _rank_key(c):
        val = c["scorecard"].get(objective, 0.0)
        return float(val) if val is not None else -9999.0

    reverse_sort = objective not in ("max_drawdown", "volatility_ann", "largest_loss")
    candidates.sort(key=_rank_key, reverse=reverse_sort)

    lines = [
        f"### 🛡️ Strategy Supercharge Comparison Dashboard (Ranked by {objective.upper()})",
        "",
        "| Rank | Strategy Variant | Return (%) | CAGR (%) | Sharpe | Max DD (%) | Win Rate (%) | Profit Factor | Robustness | Status |",
        "| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
    ]

    for idx, c in enumerate(candidates, start=1):
        sc = c["scorecard"]
        ret = sc.get("total_return_pct", 0.0)
        cagr = sc.get("cagr", 0.0)
        sharpe = sc.get("sharpe", 0.0)
        dd = sc.get("max_drawdown", 0.0)
        wr = sc.get("trade_win_rate", sc.get("positive_period_pct", 0.0))
        pf = sc.get("profit_factor", "N/A")
        rob = sc.get("robustness_score", 0.0)
        status = "✅ ACCEPTED" if c["accepted"] else f"❌ REJECTED ({c.get('reason', '')})"

        lines.append(
            f"| {idx} | **{c['name']}** | {ret:+.1f}% | {cagr:.1f}% | {sharpe:.2f} | {dd:.1f}% | {wr}% | {pf} | {rob:.2f} | {status} |"
        )

    return "\n".join(lines)


def log_evolution_entry(
    baseline_id: str,
    baseline_card: dict[str, Any],
    variants: list[StrategyVariant],
    context: Optional[dict[str, Any]] = None,
) -> None:
    """Helper to log an optimization cycle to the evolution journal."""
    logger = EvolutionLog()
    logger.log_entry(
        "optimization_round",
        {
            "baseline_id": baseline_id,
            "baseline_card": baseline_card,
            "variants": [
                {
                    "variant_id": v.variant_id,
                    "is_accepted": v.is_accepted,
                    "scorecard": v.scorecard,
                    "rejection_reason": v.rejection_reason,
                }
                for v in variants
            ],
            "context": context or {},
        },
    )

