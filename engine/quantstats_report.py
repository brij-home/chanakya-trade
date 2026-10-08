"""
engine/quantstats_report.py
────────────────────────────
Institutional QuantStats & Risk Analytics Reporting Engine for ChanakyaTrade.
Inspired by FyersDev/fyers-skills performance tear sheets.

Features:
  - Generates institutional HTML tear sheets with monthly return heatmaps,
    rolling Sharpe, drawdown/underwater plots, and risk-return statistics.
  - Resamples intraday returns (1m, 5m, 15m, 60m) into daily compounded returns with
    proper timezone normalization.
  - Disambiguates the 'Two Win Rates':
      * trade_win_rate      : % winning trades / total closed trades (trade-level)
      * positive_period_pct : % profitable days / total periods (period-level)
  - Calculates Out-of-Sample (OOS) Robustness Score to detect curve-fitting & overfitting:
      Robustness = min(1.0, max(0.0, Sharpe_OOS / max(0.01, Sharpe_IS)))
  - Lazy-imported QuantStats with headless matplotlib ('Agg' backend) and pure-Python fallback.
"""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd


def _quantstats():
    """Lazily import quantstats with graceful fallback."""
    try:
        import quantstats as qs

        return qs
    except Exception:
        return None


def _use_headless_backend() -> None:
    """Ensure non-interactive Agg backend is used for matplotlib."""
    try:
        import matplotlib

        matplotlib.use("Agg", force=True)
    except Exception:
        pass


def daily_returns(data: Any, freq: str = "auto") -> pd.Series:
    """
    Coerce a returns Series, DataFrame, or array into a clean daily returns pd.Series.
    Compounds intraday bars within each calendar day: (1 + r).prod() - 1.
    """
    if isinstance(data, pd.Series):
        s = data.copy().astype(float)
    elif isinstance(data, pd.DataFrame):
        s = data.iloc[:, 0].copy().astype(float)
    else:
        s = pd.Series(np.asarray(data, dtype=float))

    s = s.dropna()
    if s.empty:
        return s

    # Ensure tz-naive or normalized DatetimeIndex
    if isinstance(s.index, pd.DatetimeIndex):
        if s.index.tz is not None:
            s.index = s.index.tz_localize(None)
    else:
        # Stamp a synthetic daily index ending today if non-datetime
        s.index = pd.date_range(end=datetime.now(), periods=len(s), freq="D")

    if freq == "auto":
        # Check if intraday (multiple timestamps on the same calendar day)
        days = s.index.normalize()
        if len(days.unique()) < len(s):
            # Intraday returns -> compound by day: prod(1 + r) - 1
            daily = (1.0 + s).groupby(days).prod() - 1.0
            return daily

    return s


def calculate_robustness_score(returns: Any, oos_fraction: float = 0.3) -> float:
    """
    Compute Walk-Forward In-Sample vs Out-of-Sample stability score:
      Robustness = min(1.0, max(0.0, Sharpe_OOS / max(0.01, Sharpe_IS)))
    Score near 1.0 indicates strong out-of-sample edge persistence.
    Score near 0.0 indicates severe curve-fitting or vanishing edge out-of-sample.
    """
    s = daily_returns(returns)
    if len(s) < 20:
        return 0.5  # Insufficient data to penalize

    split_idx = int(len(s) * (1.0 - oos_fraction))
    is_rets = s.iloc[:split_idx]
    oos_rets = s.iloc[split_idx:]

    def _calc_sharpe(r: pd.Series) -> float:
        std = float(r.std(ddof=1))
        if std <= 1e-9:
            return 0.0
        return float((r.mean() / std) * math.sqrt(252))

    sharpe_is = _calc_sharpe(is_rets)
    sharpe_oos = _calc_sharpe(oos_rets)

    if sharpe_is <= 0.0:
        return 0.0 if sharpe_oos <= 0.0 else 0.5

    ratio = sharpe_oos / max(0.01, sharpe_is)
    return round(min(1.0, max(0.0, ratio)), 3)


def key_metrics(
    returns: Any, trades: Optional[list[dict[str, Any]]] = None, rf: float = 0.0
) -> dict[str, Any]:
    """
    Compute hedge-fund grade risk & return metrics from a returns series and closed trades.
    Strictly disambiguates Period Win Rate vs Trade Win Rate.
    """
    s = daily_returns(returns)
    if s.empty:
        return {}

    qs = _quantstats()
    if qs is not None:
        try:
            sharpe = float(qs.stats.sharpe(s, rf=rf))
            sortino = float(qs.stats.sortino(s, rf=rf))
            cagr = float(qs.stats.cagr(s, rf=rf) * 100.0)
            max_dd = float(qs.stats.max_drawdown(s) * 100.0)
            calmar = float(qs.stats.calmar(s))
            vol_ann = float(qs.stats.volatility(s) * 100.0)
        except Exception:
            qs = None

    if qs is None:
        # Pure-Python fallback
        mean_ret = float(s.mean())
        std_ret = float(s.std(ddof=1)) if len(s) > 1 else 0.0
        downside = s[s < 0.0]
        downside_std = float(downside.std(ddof=1)) if len(downside) > 1 else 0.0

        sharpe = (mean_ret / std_ret * math.sqrt(252)) if std_ret > 1e-9 else 0.0
        sortino = (mean_ret / downside_std * math.sqrt(252)) if downside_std > 1e-9 else 0.0
        vol_ann = std_ret * math.sqrt(252) * 100.0

        cum = (1.0 + s).cumprod()
        peak = cum.cummax()
        dd = (cum - peak) / peak
        max_dd = float(dd.min() * 100.0)
        total_ret = float(cum.iloc[-1] - 1.0) if not cum.empty else 0.0
        years = max(1.0 / 252.0, len(s) / 252.0)
        cagr = (
            (float((1.0 + total_ret) ** (1.0 / years) - 1.0) * 100.0)
            if total_ret > -1.0
            else -100.0
        )
        calmar = abs(cagr / max_dd) if abs(max_dd) > 1e-9 else 0.0

    # Period Win Rate (% profitable days)
    pos_periods = (s > 0.0).sum()
    total_periods = len(s)
    positive_period_pct = (
        round((pos_periods / total_periods * 100.0), 2) if total_periods > 0 else 0.0
    )

    # Cumulative total return
    cum = (1.0 + s).cumprod()
    total_return_pct = round(float((cum.iloc[-1] - 1.0) * 100.0), 2) if not cum.empty else 0.0

    # Trade-level statistics if trade list provided
    trade_count = len(trades) if trades else 0
    trade_win_rate = None
    profit_factor = None
    avg_profit = None
    avg_loss = None
    largest_loss = None
    longest_losing_streak = None

    if trades:
        pnls = [float(t.get("pnl", 0.0)) for t in trades]
        wins = [p for p in pnls if p > 0.0]
        losses = [p for p in pnls if p < 0.0]
        trade_win_rate = round((len(wins) / len(pnls) * 100.0), 2) if pnls else 0.0
        sum_wins = sum(wins)
        sum_losses = abs(sum(losses))
        profit_factor = (
            round(sum_wins / sum_losses, 2)
            if sum_losses > 1e-9
            else (float("inf") if sum_wins > 0 else 0.0)
        )
        avg_profit = round(sum_wins / len(wins), 2) if wins else 0.0
        avg_loss = round(sum_losses / len(losses), 2) if losses else 0.0
        largest_loss = round(min(pnls), 2) if pnls else 0.0

        # Longest losing streak
        max_streak = 0
        curr_streak = 0
        for p in pnls:
            if p <= 0.0:
                curr_streak += 1
                max_streak = max(max_streak, curr_streak)
            else:
                curr_streak = 0
        longest_losing_streak = max_streak

    return {
        "total_return_pct": total_return_pct,
        "cagr": round(cagr, 2),
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "calmar": round(calmar, 2),
        "max_drawdown": round(max_dd, 2),
        "volatility_ann": round(vol_ann, 2),
        "positive_period_pct": positive_period_pct,
        "trade_count": trade_count,
        "trade_win_rate": trade_win_rate,
        "profit_factor": profit_factor,
        "avg_profit": avg_profit,
        "avg_loss": avg_loss,
        "largest_loss": largest_loss,
        "longest_losing_streak": longest_losing_streak,
        "robustness_score": calculate_robustness_score(s),
    }


def generate_html_tear_sheet(
    returns: Any,
    output_path: Optional[str] = None,
    title: str = "ChanakyaTrade Strategy Tear Sheet",
    benchmark: Optional[Any] = None,
    trades: Optional[list[dict[str, Any]]] = None,
) -> str:
    """
    Generate full HTML tear sheet with monthly returns heatmap and institutional metrics.
    Falls back to a standalone institutional HTML report if QuantStats is not installed.
    """
    s = daily_returns(returns)
    b = daily_returns(benchmark) if benchmark is not None else None
    metrics = key_metrics(s, trades=trades)

    if output_path:
        out_file = Path(output_path)
    else:
        out_file = (
            Path.home()
            / ".trading_platform"
            / "reports"
            / f"tear_sheet_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        )

    out_file.parent.mkdir(parents=True, exist_ok=True)

    _use_headless_backend()
    qs = _quantstats()

    if qs is not None:
        try:
            qs.reports.html(
                s,
                benchmark=b,
                output=str(out_file),
                title=title,
                download_filename=out_file.name,
            )
            return str(out_file)
        except Exception:
            pass

    # High-quality standalone fallback tear sheet
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0B0F17; color: #E2E8F0; margin: 0; padding: 24px; }}
    .container {{ max-width: 1100px; margin: 0 auto; }}
    .header {{ border-bottom: 1px solid #1E293B; padding-bottom: 16px; margin-bottom: 24px; }}
    h1 {{ color: #F8FAFC; margin: 0 0 8px 0; font-size: 24px; }}
    .badge {{ background: #10B98120; color: #10B981; border: 1px solid #10B98140; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}
    .card {{ background: #111827; border: 1px solid #1E293B; border-radius: 8px; padding: 16px; }}
    .card-title {{ font-size: 11px; text-transform: uppercase; color: #94A3B8; letter-spacing: 0.05em; margin-bottom: 8px; }}
    .card-value {{ font-size: 22px; font-weight: 700; color: #F8FAFC; font-variant-numeric: tabular-nums; }}
    .positive {{ color: #10B981; }}
    .negative {{ color: #F43F5E; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 16px; background: #111827; border-radius: 8px; overflow: hidden; }}
    th, td {{ padding: 12px 16px; text-align: left; border-bottom: 1px solid #1E293B; }}
    th {{ background: #0F172A; color: #94A3B8; font-size: 12px; text-transform: uppercase; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>{title}</h1>
      <span class="badge">PROVENANCE: REAL/QUANT</span> &bull; <span style="color:#64748B;font-size:12px">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")}</span>
    </div>

    <div class="grid">
      <div class="card">
        <div class="card-title">Total Return</div>
        <div class="card-value {"positive" if metrics.get("total_return_pct", 0) >= 0 else "negative"}">{metrics.get("total_return_pct", 0.0):+.2f}%</div>
      </div>
      <div class="card">
        <div class="card-title">CAGR</div>
        <div class="card-value">{metrics.get("cagr", 0.0):.2f}%</div>
      </div>
      <div class="card">
        <div class="card-title">Sharpe Ratio</div>
        <div class="card-value">{metrics.get("sharpe", 0.0):.2f}</div>
      </div>
      <div class="card">
        <div class="card-title">Max Drawdown</div>
        <div class="card-value negative">{metrics.get("max_drawdown", 0.0):.2f}%</div>
      </div>
      <div class="card">
        <div class="card-title">Robustness Score (OOS)</div>
        <div class="card-value {"positive" if metrics.get("robustness_score", 0) >= 0.7 else "negative"}">{metrics.get("robustness_score", 0.0):.2f} / 1.0</div>
      </div>
      <div class="card">
        <div class="card-title">Trade Win Rate</div>
        <div class="card-value">{metrics.get("trade_win_rate", "N/A")}{"%" if metrics.get("trade_win_rate") is not None else ""}</div>
      </div>
      <div class="card">
        <div class="card-title">Period Win Rate (% Days)</div>
        <div class="card-value">{metrics.get("positive_period_pct", 0.0):.2f}%</div>
      </div>
      <div class="card">
        <div class="card-title">Profit Factor</div>
        <div class="card-value">{metrics.get("profit_factor", "N/A")}</div>
      </div>
    </div>
  </div>
</body>
</html>"""

    out_file.write_text(html, encoding="utf-8")
    return str(out_file)
