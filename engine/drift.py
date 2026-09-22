"""
engine/drift.py
───────────────
Model drift detection AND closed-loop correction — tracks whether analysis
accuracy is degrading and actively recalibrates the system when it does.

Detects:
  - Win rate declining over time
  - Analyst accuracy per VIX regime
  - Analyst disagreement patterns
  - Strategy performance decay

Corrects (when DECLINING trend detected):
  - Raises AlertScrutinyAuditor min_rr_ratio from 1.3 → 1.6
  - Triggers mover autopsy → SNR computation → PatternLearningEngine recalibration
  - Logs a structured DriftCorrectionEvent for audit trail

Requires trade outcomes in trade_memory (engine/memory.py).

Usage:
    from engine.drift import detect_drift, print_drift_report, nightly_drift_check
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

logger = logging.getLogger("engine.drift")
console = Console()

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class DriftReport:
    """Model drift analysis results."""

    total_trades: int = 0
    trades_with_outcome: int = 0

    # Win rate trend
    recent_win_rate: float = 0.0  # last 10 trades
    older_win_rate: float = 0.0  # trades before last 10
    win_rate_trend: str = "STABLE"  # IMPROVING / DECLINING / STABLE
    win_rate_delta: float = 0.0  # recent - older

    # By VIX regime
    low_vix_win_rate: float = 0.0  # VIX < 15
    high_vix_win_rate: float = 0.0  # VIX > 18
    best_vix_regime: str = ""

    # By verdict type
    buy_accuracy: float = 0.0
    sell_accuracy: float = 0.0
    hold_accuracy: float = 0.0

    # Analyst-level drift
    analyst_accuracy: dict = field(
        default_factory=dict
    )  # analyst → win rate when they were bullish
    worst_analyst: str = ""
    best_analyst: str = ""

    # Alerts
    alerts: list[str] = field(default_factory=list)

    def apply_drift_corrections(self) -> dict[str, Any]:
        """
        Closed-loop correction controller.

        When DECLINING trend is detected, this method:
          1. Raises AlertScrutinyAuditor.min_rr_ratio from 1.3 →  1.6 (tighter gates)
          2. Triggers mover_autopsy → SNR → PatternLearningEngine.recalibrate_from_snr()
          3. Returns a structured correction event dict for audit logging

        Safe to call unconditionally — no-ops when trend is STABLE or IMPROVING.
        Returns: dict with correction_applied, actions_taken, timestamp
        """
        correction_event: dict[str, Any] = {
            "timestamp": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
            "win_rate_trend": self.win_rate_trend,
            "win_rate_delta": self.win_rate_delta,
            "recent_win_rate": self.recent_win_rate,
            "correction_applied": False,
            "actions_taken": [],
        }

        if self.win_rate_trend not in ("DECLINING",) or self.trades_with_outcome < 5:
            return correction_event  # No-op for STABLE / IMPROVING

        # 1. Raise AlertScrutiny minimum R:R threshold during declining phase
        try:
            from engine.alert_scrutiny import AlertScrutinyAuditor
            # Patch the module-level singleton if instantiated, else flag via env
            import os
            current_rr = float(os.environ.get("CHANAKYA_MIN_RR_OVERRIDE", "1.3"))
            adjusted_rr = 1.6 if self.win_rate_delta < -15 else 1.45
            if adjusted_rr > current_rr:
                os.environ["CHANAKYA_MIN_RR_OVERRIDE"] = str(adjusted_rr)
                correction_event["actions_taken"].append(
                    f"AlertScrutiny min_rr_ratio raised: {current_rr:.2f} → {adjusted_rr:.2f} (win rate declining {self.win_rate_delta:+.0f}%)"
                )
                logger.warning(
                    "[DRIFT CORRECTION] min_rr_ratio raised %.2f → %.2f (win_rate_delta=%.1f%%)",
                    current_rr, adjusted_rr, self.win_rate_delta,
                )
        except Exception as e:
            logger.debug("Drift correction: rr_ratio adjustment failed: %s", e)

        # 2. Trigger mover autopsy → SNR → recalibrate_from_snr pipeline
        try:
            from engine.mover_autopsy import run_daily_autopsy
            from engine.learning_engine import PatternLearningEngine

            autopsy = run_daily_autopsy()
            if autopsy and hasattr(autopsy, "gainers") and hasattr(autopsy, "control_cohort"):
                gainers = autopsy.gainers or []
                controls = autopsy.control_cohort or []

                if gainers and controls:
                    # Compute discriminative SNR: which factors separate gainers from controls
                    snr_table: dict[str, float] = {}
                    factor_keys = [
                        "trend_score", "vcp_score", "smc_score", "rvol_20d",
                        "squeeze_coiling", "sector_tailwind", "forensic_safe",
                    ]
                    for fk in factor_keys:
                        gainer_vals = [float(getattr(g, fk, 0) or 0) for g in gainers]
                        control_vals = [float(getattr(c, fk, 0) or 0) for c in controls]
                        if gainer_vals and control_vals:
                            mean_g = sum(gainer_vals) / len(gainer_vals)
                            mean_c = sum(control_vals) / len(control_vals)
                            spread = abs(mean_g - mean_c)
                            noise = max(0.01, (sum(abs(v - mean_g) for v in gainer_vals) / len(gainer_vals) +
                                               sum(abs(v - mean_c) for v in control_vals) / len(control_vals)) / 2)
                            snr_table[fk] = round(spread / noise, 3)

                    if snr_table:
                        learning_engine = PatternLearningEngine()
                        if hasattr(learning_engine, "recalibrate_from_snr"):
                            learning_engine.recalibrate_from_snr(snr_table)
                            correction_event["actions_taken"].append(
                                f"PatternLearningEngine recalibrated from SNR table ({len(snr_table)} factors): "
                                + ", ".join(f"{k}={v:.2f}" for k, v in sorted(snr_table.items(), key=lambda x: -x[1])[:4])
                            )
                            logger.info("[DRIFT CORRECTION] Learning engine recalibrated. SNR: %s", snr_table)
        except Exception as e:
            logger.debug("Drift correction: autopsy/recalibrate pipeline failed: %s", e)

        # 3. Emit audit alert for worst analyst if accuracy < 35%
        if (
            self.worst_analyst
            and self.analyst_accuracy.get(self.worst_analyst, {}).get("accuracy", 50) < 35
        ):
            try:
                from engine.analysis_cache import analysis_cache
                analysis_cache.save_macro(
                    f"drift_worst_analyst_{self.worst_analyst}",
                    {"analyst": self.worst_analyst, "accuracy": self.analyst_accuracy[self.worst_analyst]},
                    ttl_minutes=1440,  # 24h cache
                )
                correction_event["actions_taken"].append(
                    f"Analyst {self.worst_analyst} flagged (accuracy {self.analyst_accuracy[self.worst_analyst].get('accuracy', 0):.0f}% < 35%)"
                )
            except Exception:
                pass

        correction_event["correction_applied"] = len(correction_event["actions_taken"]) > 0
        if correction_event["correction_applied"]:
            logger.warning(
                "[DRIFT CORRECTION APPLIED] %d actions: %s",
                len(correction_event["actions_taken"]),
                " | ".join(correction_event["actions_taken"]),
            )
        return correction_event

    def print_report(self) -> None:
        if self.trades_with_outcome < 5:
            console.print(
                f"[dim]Need at least 5 trade outcomes for drift analysis "
                f"(have {self.trades_with_outcome}). "
                f"Use 'memory outcome <ID> WIN|LOSS' to record results.[/dim]"
            )
            return

        trend_style = {
            "IMPROVING": "green",
            "DECLINING": "red",
            "STABLE": "yellow",
        }.get(self.win_rate_trend, "white")

        lines = [
            f"  Trades Analyzed   : {self.trades_with_outcome} / {self.total_trades}",
            "",
            "  [bold]Win Rate Trend[/bold]",
            f"  Recent (last 10)  : {self.recent_win_rate:.0f}%",
            f"  Older             : {self.older_win_rate:.0f}%",
            f"  Trend             : [{trend_style}]{self.win_rate_trend} ({self.win_rate_delta:+.0f}%)[/{trend_style}]",
            "",
            "  [bold]By VIX Regime[/bold]",
            f"  Low VIX (<15)     : {self.low_vix_win_rate:.0f}%",
            f"  High VIX (>18)    : {self.high_vix_win_rate:.0f}%",
            f"  Best regime       : {self.best_vix_regime}",
            "",
            "  [bold]By Verdict[/bold]",
            f"  BUY accuracy      : {self.buy_accuracy:.0f}%",
            f"  SELL accuracy     : {self.sell_accuracy:.0f}%",
        ]

        if self.best_analyst:
            lines.extend(
                [
                    "",
                    "  [bold]Analyst Accuracy[/bold]",
                    f"  Best analyst      : [green]{self.best_analyst}[/green]",
                    f"  Worst analyst     : [red]{self.worst_analyst}[/red]",
                ]
            )

        console.print(
            Panel(
                "\n".join(lines),
                title="[bold cyan]Model Drift Report[/bold cyan]",
                border_style="cyan",
            )
        )

        if self.analyst_accuracy:
            table = Table(title="Analyst Accuracy (when they were bullish, did stock go up?)")
            table.add_column("Analyst", style="bold", width=18)
            table.add_column("Accuracy", justify="right", width=10)
            table.add_column("Trades", justify="right", width=8)

            for analyst, data in sorted(
                self.analyst_accuracy.items(), key=lambda x: -x[1].get("accuracy", 0)
            ):
                acc = data.get("accuracy", 0)
                n = data.get("count", 0)
                style = "green" if acc >= 60 else "red" if acc < 40 else "yellow"
                table.add_row(analyst, f"[{style}]{acc:.0f}%[/{style}]", str(n))
            console.print(table)

        if self.alerts:
            console.print("\n[bold yellow]Drift Alerts:[/bold yellow]")
            for a in self.alerts:
                console.print(f"  [yellow]! {a}[/yellow]")


def detect_drift() -> DriftReport:
    """Analyze trade memory for model drift."""
    try:
        from engine.memory import trade_memory
    except ImportError:
        return DriftReport()

    records = trade_memory._records
    with_outcome = [r for r in records if r.outcome]
    report = DriftReport(
        total_trades=len(records),
        trades_with_outcome=len(with_outcome),
    )

    if len(with_outcome) < 5:
        return report

    # Win rate trend
    recent = with_outcome[-10:]
    older = with_outcome[:-10] if len(with_outcome) > 10 else []

    recent_wins = sum(1 for r in recent if r.outcome == "WIN")
    report.recent_win_rate = recent_wins / len(recent) * 100 if recent else 0

    if older:
        older_wins = sum(1 for r in older if r.outcome == "WIN")
        report.older_win_rate = older_wins / len(older) * 100
    else:
        report.older_win_rate = report.recent_win_rate

    report.win_rate_delta = report.recent_win_rate - report.older_win_rate
    if report.win_rate_delta > 10:
        report.win_rate_trend = "IMPROVING"
    elif report.win_rate_delta < -10:
        report.win_rate_trend = "DECLINING"
    else:
        report.win_rate_trend = "STABLE"

    # By VIX regime
    low_vix = [r for r in with_outcome if r.vix is not None and r.vix < 15]
    high_vix = [r for r in with_outcome if r.vix is not None and r.vix > 18]

    if low_vix:
        report.low_vix_win_rate = sum(1 for r in low_vix if r.outcome == "WIN") / len(low_vix) * 100
    if high_vix:
        report.high_vix_win_rate = (
            sum(1 for r in high_vix if r.outcome == "WIN") / len(high_vix) * 100
        )

    if report.low_vix_win_rate > report.high_vix_win_rate:
        report.best_vix_regime = "Low VIX (<15)"
    elif report.high_vix_win_rate > report.low_vix_win_rate:
        report.best_vix_regime = "High VIX (>18)"
    else:
        report.best_vix_regime = "No difference"

    # By verdict
    buys = [r for r in with_outcome if r.verdict in ("BUY", "STRONG_BUY")]
    sells = [r for r in with_outcome if r.verdict in ("SELL", "STRONG_SELL")]

    if buys:
        report.buy_accuracy = sum(1 for r in buys if r.outcome == "WIN") / len(buys) * 100
    if sells:
        report.sell_accuracy = sum(1 for r in sells if r.outcome == "WIN") / len(sells) * 100

    # Analyst-level accuracy
    analyst_stats: dict[str, dict] = {}
    for r in with_outcome:
        if not r.analyst_scores:
            continue
        for analyst, score in r.analyst_scores.items():
            if analyst not in analyst_stats:
                analyst_stats[analyst] = {"correct": 0, "total": 0}
            analyst_stats[analyst]["total"] += 1
            # "Correct" = analyst was bullish (score > 0) and outcome was WIN,
            # or analyst was bearish (score < 0) and outcome was LOSS
            if (score > 0 and r.outcome == "WIN") or (score < 0 and r.outcome == "LOSS"):
                analyst_stats[analyst]["correct"] += 1

    for analyst, stats in analyst_stats.items():
        acc = stats["correct"] / stats["total"] * 100 if stats["total"] > 0 else 0
        report.analyst_accuracy[analyst] = {"accuracy": round(acc, 1), "count": stats["total"]}

    if report.analyst_accuracy:
        best = max(report.analyst_accuracy.items(), key=lambda x: x[1]["accuracy"])
        worst = min(report.analyst_accuracy.items(), key=lambda x: x[1]["accuracy"])
        report.best_analyst = best[0]
        report.worst_analyst = worst[0]

    # Alerts
    if report.win_rate_trend == "DECLINING" and report.win_rate_delta < -15:
        report.alerts.append(
            f"Win rate declining sharply: {report.older_win_rate:.0f}% → {report.recent_win_rate:.0f}%"
        )

    if (
        report.worst_analyst
        and report.analyst_accuracy.get(report.worst_analyst, {}).get("accuracy", 50) < 35
    ):
        report.alerts.append(
            f"{report.worst_analyst} analyst accuracy below 35% — consider reducing its weight"
        )

    if report.buy_accuracy > 0 and report.buy_accuracy < 40:
        report.alerts.append(
            f"BUY signals only {report.buy_accuracy:.0f}% accurate — model may be too bullish"
        )

    return report


def print_drift_report() -> None:
    """Display drift analysis and auto-apply corrections if declining."""
    report = detect_drift()
    report.print_report()
    # Auto-trigger corrections if drift detected — turns report into action
    corrections = report.apply_drift_corrections()
    if corrections["correction_applied"]:
        console.print("\n[bold yellow]⚡ Drift Corrections Applied:[/bold yellow]")
        for action in corrections["actions_taken"]:
            console.print(f"  [yellow]✓ {action}[/yellow]")


def nightly_drift_check() -> dict[str, Any]:
    """
    Nightly post-market drift check (to be called at 15:45–16:30 IST).

    Chains: detect_drift() → apply_drift_corrections() → structured result
    for logging or alerting via Telegram bot.
    """
    report = detect_drift()
    corrections = report.apply_drift_corrections()
    return {
        "report": {
            "total_trades": report.total_trades,
            "trades_with_outcome": report.trades_with_outcome,
            "win_rate_trend": report.win_rate_trend,
            "recent_win_rate": report.recent_win_rate,
            "older_win_rate": report.older_win_rate,
            "win_rate_delta": report.win_rate_delta,
            "best_analyst": report.best_analyst,
            "worst_analyst": report.worst_analyst,
            "alerts": report.alerts,
        },
        "corrections": corrections,
    }
