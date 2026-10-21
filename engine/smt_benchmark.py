"""
engine/smt_benchmark.py
───────────────────────
Quantitative Backtest Benchmark Engine for Smart Money Technique (SMT) Liquidity Sweep.

Compares the institutional SMT Sweep strategy (inter-market divergence liquidity sweep)
against standard industry baseline strategies over identical historical datasets:
  1. SMT Sweep Strategy: Inter-market liquidity sweep fading with sibling divergence non-confirmation.
  2. Turtle Soup Strategy: Classical single-instrument liquidity sweep baseline (Linda Raschke / ICT).
  3. Donchian Breakout: 20-period swing breakout (Turtle Trading).
  4. EMA Crossover: 20/50 Exponential Moving Average trend following.
  5. RSI Mean Reversion: 14-period RSI 30/70 oversold/overbought mean reversion.
  6. Buy & Hold Benchmark: Passive index buy-and-hold baseline.

Institutional Evaluation Invariants (AGENTS.md):
  - Statutory Friction Accounting: Deducts post-October 2024 SEBI, STT, GST, exchange turnover,
    and stamp duty fees via engine.charges / NSECharges to calculate realistic Net Returns.
  - Two Win Rates Disambiguation: Explicitly reports Trade Win Rate (winning_trades / total_trades)
    and Positive Period % (daily positive return days / total trading days).
  - Absolute Data Provenance: Real historical feeds tagged 'REAL/HISTORICAL'; deterministic
    synthetic test data tagged 'SYNTHETIC/TEST'.
  - Edge Quantification: Measures SMT Alpha, Win Rate delta, and Drawdown attenuation vs Turtle Soup.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from engine.backtest import (
    BacktestResult,
    Backtester,
    DonchianStrategy,
    MACrossStrategy,
    RSIStrategy,
    SMTSweepStrategy,
    TurtleSoupStrategy,
)
from engine.charges import calculate_transaction_charges
from engine.smt_divergence import get_sibling_index

logger = logging.getLogger("chanakya.engine.smt_benchmark")
console = Console()


@dataclass
class StrategyBenchmarkScorecard:
    """Detailed quantitative performance scorecard for a single strategy."""

    strategy_id: str
    strategy_name: str
    category: str
    total_return: float  # Gross return %
    cagr: float  # %
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown: float  # %
    total_trades: int
    winning_trades: int
    losing_trades: int
    trade_win_rate: float  # % of winning trades
    positive_period_pct: float  # % of positive daily return days
    profit_factor: float
    avg_win: float  # %
    avg_loss: float  # %
    realized_rr: float  # avg_win / abs(avg_loss)
    avg_hold_days: float
    statutory_charges: float  # Total ₹ statutory costs deducted
    net_return: float  # Net return % after statutory friction
    alpha_vs_buy_hold: float  # Net return % minus Buy & Hold return %
    alpha_vs_single_sweep: float  # Net return % minus Turtle Soup net return %
    equity_curve: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "strategy_name": self.strategy_name,
            "category": self.category,
            "total_return": self.total_return,
            "cagr": self.cagr,
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "calmar_ratio": self.calmar_ratio,
            "max_drawdown": self.max_drawdown,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "trade_win_rate": self.trade_win_rate,
            "positive_period_pct": self.positive_period_pct,
            "profit_factor": self.profit_factor,
            "avg_win": self.avg_win,
            "avg_loss": self.avg_loss,
            "realized_rr": self.realized_rr,
            "avg_hold_days": self.avg_hold_days,
            "statutory_charges": self.statutory_charges,
            "net_return": self.net_return,
            "alpha_vs_buy_hold": self.alpha_vs_buy_hold,
            "alpha_vs_single_sweep": self.alpha_vs_single_sweep,
            "equity_points": len(self.equity_curve),
        }


@dataclass
class SMTBenchmarkResult:
    """Complete comparative benchmark report across SMT Sweep and baseline strategies."""

    symbol: str
    sibling_symbol: str
    period: str
    start_date: str
    end_date: str
    initial_capital: float
    scorecards: list[StrategyBenchmarkScorecard]
    smt_edge_summary: dict[str, Any]
    provenance: str = "REAL/HISTORICAL"

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "sibling_symbol": self.sibling_symbol,
            "period": self.period,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "initial_capital": self.initial_capital,
            "provenance": self.provenance,
            "smt_edge_summary": self.smt_edge_summary,
            "scorecards": [s.to_dict() for s in self.scorecards],
        }

    def print_summary(self) -> None:
        """Display comparative benchmark results as a Rich institutional table."""
        header_text = (
            f"[bold cyan]SMT SWEEP STRATEGIC BENCHMARK[/bold cyan]\n"
            f"[dim]Primary:[/dim] [bold white]{self.symbol}[/bold white]  "
            f"[dim]Sibling:[/dim] [bold white]{self.sibling_symbol}[/bold white]  "
            f"[dim]Period:[/dim] {self.start_date} → {self.end_date} ({self.period})  "
            f"[dim]Provenance:[/dim] [yellow]{self.provenance}[/yellow]"
        )
        console.print(Panel(header_text, border_style="cyan"))

        table = Table(title="Strategy Comparison Leaderboard", show_lines=True)
        table.add_column("Strategy", style="bold white", width=22)
        table.add_column("Category", style="dim", width=16)
        table.add_column("Net Ret %", justify="right", width=11)
        table.add_column("CAGR %", justify="right", width=9)
        table.add_column("Sharpe", justify="right", width=8)
        table.add_column("Sortino", justify="right", width=8)
        table.add_column("Max DD %", justify="right", width=10)
        table.add_column("Trades", justify="right", width=8)
        table.add_column("Win Rate", justify="right", width=10)
        table.add_column("Pos Days", justify="right", width=10)
        table.add_column("Profit Fac", justify="right", width=10)
        table.add_column("Stat Costs", justify="right", width=11)

        for card in self.scorecards:
            ret_style = "green" if card.net_return >= 0 else "red"
            cagr_style = "green" if card.cagr >= 0 else "red"
            dd_style = "red" if card.max_drawdown < -15 else "yellow"

            table.add_row(
                card.strategy_name,
                card.category,
                f"[{ret_style}]{card.net_return:+.2f}%[/{ret_style}]",
                f"[{cagr_style}]{card.cagr:+.2f}%[/{cagr_style}]",
                f"{card.sharpe_ratio:.2f}",
                f"{card.sortino_ratio:.2f}",
                f"[{dd_style}]{card.max_drawdown:.2f}%[/{dd_style}]",
                str(card.total_trades),
                f"{card.trade_win_rate:.1f}%",
                f"{card.positive_period_pct:.1f}%",
                f"{card.profit_factor:.2f}",
                f"₹{card.statutory_charges:,.0f}",
            )

        console.print(table)

        # SMT Edge Insight Box
        edge = self.smt_edge_summary
        edge_lines = [
            "  [bold]SMT Inter-Market Edge vs Single-Asset Turtle Soup:[/bold]",
            f"    • Net Alpha Generation  : [green]{edge.get('alpha_over_single_sweep', 0):+.2f}%[/green]",
            f"    • Trade Win Rate Delta  : [green]{edge.get('win_rate_boost_pct', 0):+.1f}%[/green]",
            f"    • Sharpe Ratio Delta    : [green]{edge.get('sharpe_delta', 0):+.2f}[/green]",
            f"    • Max Drawdown Delta    : [green]{edge.get('drawdown_attenuation_pct', 0):+.2f}%[/green] (DD reduction)",
            f"    • False Fades Avoided   : [bold cyan]{edge.get('harmonious_breakouts_filtered', 0)}[/bold cyan] harmonious breakouts",
            f"    • Statutory Cost Impact : ₹{edge.get('statutory_friction_inr', 0):,.2f} post-Oct 2024 tax & fee drag",
        ]
        console.print(
            Panel(
                "\n".join(edge_lines),
                title="[bold green]Institutional Quantitative Edge Summary[/bold green]",
                border_style="green",
            )
        )


def _compute_statutory_costs(trades: list[Any]) -> float:
    """
    Computes total statutory charges across all completed trades using
    effective post-October 2024 SEBI & exchange rates via engine.charges.
    """
    total_charges = 0.0
    for t in trades:
        entry_price = getattr(t, "entry_price", 0.0)
        exit_price = getattr(t, "exit_price", 0.0)
        qty = getattr(t, "quantity", 0)
        hold_days = getattr(t, "hold_days", 0)

        if qty <= 0 or entry_price <= 0:
            continue

        seg = "EQUITY_INTRADAY" if hold_days == 0 else "EQUITY_DELIVERY"

        try:
            # Buy side charges
            buy_breakdown = calculate_transaction_charges(
                price=entry_price,
                quantity=qty,
                segment=seg,
                side="BUY",
            )
            # Sell side charges
            sell_breakdown = calculate_transaction_charges(
                price=exit_price if exit_price > 0 else entry_price,
                quantity=qty,
                segment=seg,
                side="SELL",
            )
            total_charges += float(buy_breakdown.total_charges + sell_breakdown.total_charges)
        except Exception as e_chg:
            logger.debug(f"[smt_benchmark] Cost calculation fallback note: {e_chg}")
            # Approximate fallback if charges calculation encounters edge case
            turnover = (entry_price + exit_price) * qty
            total_charges += turnover * 0.0015 + 40.0  # Approx 0.15% + ₹40 brokerage

    return round(total_charges, 2)


def run_smt_benchmark(
    symbol: str = "NIFTY",
    sibling_symbol: Optional[str] = None,
    period: str = "1y",
    capital: float = 100000.0,
    df: Optional[pd.DataFrame] = None,
    sibling_df: Optional[pd.DataFrame] = None,
    provenance: str = "REAL/HISTORICAL",
) -> SMTBenchmarkResult:
    """
    Runs multi-strategy backtest benchmark comparing SMT Sweep against
    Turtle Soup, Donchian, EMA Cross, RSI, and Buy & Hold.

    Args:
        symbol: Primary ticker or index (e.g. "NIFTY").
        sibling_symbol: Correlated sibling index (e.g. "BANKNIFTY").
        period: Historical period ("6m", "1y", "2y", etc.).
        capital: Initial trading capital (₹).
        df: Preloaded OHLCV DataFrame for primary symbol (optional).
        sibling_df: Preloaded OHLCV DataFrame for sibling symbol (optional).
        provenance: Data origin tag.

    Returns:
        SMTBenchmarkResult with complete comparative leaderboard and edge analysis.
    """
    clean_symbol = symbol.upper().strip()
    clean_sibling = (
        sibling_symbol.upper().strip() if sibling_symbol else get_sibling_index(clean_symbol)
    )

    # 1. Load Primary Data if not provided
    primary_df = df
    if primary_df is None:
        from market.history import get_ohlcv

        period_days = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "3y": 1095}
        days = period_days.get(period.lower(), 365)
        primary_df = get_ohlcv(symbol=clean_symbol, interval="day", days=days)

    if primary_df is None or primary_df.empty:
        raise RuntimeError(f"No historical price data available for {clean_symbol}")

    primary_df = primary_df.dropna(subset=["close"]).copy()
    if hasattr(primary_df.index, "tz") and primary_df.index.tz is not None:
        primary_df.index = primary_df.index.tz_localize(None)

    # 2. Load Sibling Data if not provided
    sib_df = sibling_df
    if sib_df is None:
        from market.history import get_ohlcv

        try:
            start_dt = primary_df.index[0]
            end_dt = primary_df.index[-1]
            days = (
                max(30, (end_dt - start_dt).days + 15)
                if hasattr(start_dt, "days") or isinstance(start_dt, pd.Timestamp)
                else 365
            )
            sib_df = get_ohlcv(symbol=clean_sibling, interval="day", days=int(days))
            if sib_df is not None and not sib_df.empty:
                sib_df = sib_df.dropna(subset=["close"]).copy()
                if hasattr(sib_df.index, "tz") and sib_df.index.tz is not None:
                    sib_df.index = sib_df.index.tz_localize(None)
        except Exception as e_sib:
            logger.warning(
                f"[smt_benchmark] Failed to fetch sibling data for {clean_sibling}: {e_sib}"
            )
            sib_df = None

    start_date = str(primary_df.index[0])[:10]
    end_date = str(primary_df.index[-1])[:10]

    # 3. Define Strategies to Benchmark
    strategies = [
        (
            "smt_sweep",
            SMTSweepStrategy(
                lookback=20,
                sibling_symbol=clean_sibling,
                sibling_df=sib_df,
                primary_symbol=clean_symbol,
            ),
            "Liquidity Sweep (SMT)",
        ),
        (
            "turtle_soup",
            TurtleSoupStrategy(period=20),
            "Single-Asset Sweep",
        ),
        (
            "donchian",
            DonchianStrategy(period=20),
            "Trend Breakout",
        ),
        (
            "ema_cross",
            MACrossStrategy(fast=20, slow=50),
            "Trend Following",
        ),
        (
            "rsi",
            RSIStrategy(period=14, buy_level=30, sell_level=70),
            "Mean Reversion",
        ),
    ]

    # 4. Compute Buy & Hold Baseline Metrics
    first_c = float(primary_df["close"].iloc[0])
    last_c = float(primary_df["close"].iloc[-1])
    bh_gross_return = (last_c - first_c) / first_c * 100 if first_c > 0 else 0.0

    days_total = max(1, (primary_df.index[-1] - primary_df.index[0]).days)
    years = days_total / 365.25 if days_total > 0 else 1.0
    bh_cagr = ((last_c / first_c) ** (1 / years) - 1) * 100 if (years > 0 and first_c > 0) else 0.0

    bh_daily_ret = primary_df["close"].pct_change().dropna()
    bh_sharpe = (
        (bh_daily_ret.mean() / bh_daily_ret.std()) * math.sqrt(252)
        if (len(bh_daily_ret) > 1 and bh_daily_ret.std() > 0)
        else 0.0
    )
    bh_downside = bh_daily_ret[bh_daily_ret < 0]
    bh_sortino = (
        (bh_daily_ret.mean() / bh_downside.std()) * math.sqrt(252)
        if (len(bh_downside) > 1 and bh_downside.std() > 0)
        else 0.0
    )
    bh_equity = (primary_df["close"] / first_c) * capital
    bh_peak = bh_equity.expanding().max()
    bh_dd_series = (bh_equity - bh_peak) / bh_peak * 100
    bh_max_dd = float(bh_dd_series.min())
    bh_calmar = abs(bh_cagr / bh_max_dd) if abs(bh_max_dd) > 0.01 else 0.0
    bh_pos_period = float((bh_daily_ret > 0).mean() * 100.0) if not bh_daily_ret.empty else 0.0

    # Buy & Hold statutory delivery charges (1 buy at start, 1 sell at end)
    bh_qty = int(capital / first_c) if first_c > 0 else 0
    bh_stat_cost = 0.0
    if bh_qty > 0:
        try:
            b_chg = calculate_transaction_charges(
                first_c, bh_qty, segment="EQUITY_DELIVERY", side="BUY"
            )
            s_chg = calculate_transaction_charges(
                last_c, bh_qty, segment="EQUITY_DELIVERY", side="SELL"
            )
            bh_stat_cost = float(b_chg.total_charges + s_chg.total_charges)
        except Exception:
            bh_stat_cost = (first_c + last_c) * bh_qty * 0.0012 + 40.0

    bh_net_pnl = (last_c - first_c) * bh_qty - bh_stat_cost
    bh_net_return = (bh_net_pnl / capital) * 100 if capital > 0 else 0.0

    bh_scorecard = StrategyBenchmarkScorecard(
        strategy_id="buy_and_hold",
        strategy_name="Buy & Hold Benchmark",
        category="Passive Benchmark",
        total_return=round(bh_gross_return, 2),
        cagr=round(bh_cagr, 2),
        sharpe_ratio=round(bh_sharpe, 2),
        sortino_ratio=round(bh_sortino, 2),
        calmar_ratio=round(bh_calmar, 2),
        max_drawdown=round(bh_max_dd, 2),
        total_trades=1,
        winning_trades=1 if bh_net_pnl > 0 else 0,
        losing_trades=1 if bh_net_pnl <= 0 else 0,
        trade_win_rate=100.0 if bh_net_pnl > 0 else 0.0,
        positive_period_pct=round(bh_pos_period, 1),
        profit_factor=99.99 if bh_net_pnl > 0 else 0.0,
        avg_win=round(bh_gross_return, 2) if bh_gross_return > 0 else 0.0,
        avg_loss=round(abs(bh_gross_return), 2) if bh_gross_return < 0 else 0.0,
        realized_rr=1.0,
        avg_hold_days=days_total,
        statutory_charges=round(bh_stat_cost, 2),
        net_return=round(bh_net_return, 2),
        alpha_vs_buy_hold=0.0,
        alpha_vs_single_sweep=0.0,
        equity_curve=bh_equity.tolist(),
    )

    # 5. Run Each Strategy
    scorecards: list[StrategyBenchmarkScorecard] = []
    turtle_net_ret = 0.0

    for strat_id, strat_obj, cat in strategies:
        bt = Backtester(symbol=clean_symbol, period=period, capital=capital)
        bt._df = primary_df.copy()

        try:
            res: BacktestResult = bt.run(strat_obj)  # type: ignore
        except Exception as e_run:
            logger.error(f"[smt_benchmark] Strategy {strat_id} failed: {e_run}", exc_info=True)
            continue

        stat_cost = _compute_statutory_costs(res.trades)
        gross_pnl = (res.total_return / 100.0) * capital
        net_pnl = gross_pnl - stat_cost
        net_ret = (net_pnl / capital) * 100.0

        if strat_id == "turtle_soup":
            turtle_net_ret = net_ret

        realized_rr = (
            round(res.avg_win / abs(res.avg_loss), 2)
            if abs(res.avg_loss) > 0.001
            else (round(res.avg_win, 2) if res.avg_win > 0 else 0.0)
        )

        card = StrategyBenchmarkScorecard(
            strategy_id=strat_id,
            strategy_name=strat_obj.name,
            category=cat,
            total_return=float(round(res.total_return, 2)),
            cagr=float(round(res.cagr, 2)),
            sharpe_ratio=float(round(res.sharpe_ratio, 2)),
            sortino_ratio=float(round(res.sortino_ratio, 2)),
            calmar_ratio=float(round(res.calmar_ratio, 2)),
            max_drawdown=float(round(res.max_drawdown, 2)),
            total_trades=int(res.total_trades),
            winning_trades=int(res.winning_trades),
            losing_trades=int(res.losing_trades),
            trade_win_rate=float(round(res.trade_win_rate, 1)),
            positive_period_pct=float(round(res.positive_period_pct, 1)),
            profit_factor=float(round(res.profit_factor, 2)),
            avg_win=float(round(res.avg_win, 2)),
            avg_loss=float(round(res.avg_loss, 2)),
            realized_rr=float(realized_rr),
            avg_hold_days=float(round(res.avg_hold_days, 1)),
            statutory_charges=float(round(stat_cost, 2)),
            net_return=float(round(net_ret, 2)),
            alpha_vs_buy_hold=float(round(net_ret - bh_net_return, 2)),
            alpha_vs_single_sweep=0.0,  # Computed below
            equity_curve=res.equity_curve,
        )
        scorecards.append(card)

    # 6. Calculate Relative Alpha vs Single-Asset Turtle Soup
    for sc in scorecards:
        sc.alpha_vs_single_sweep = round(sc.net_return - turtle_net_ret, 2)
    bh_scorecard.alpha_vs_single_sweep = round(bh_scorecard.net_return - turtle_net_ret, 2)

    # Append Buy & Hold to scorecards
    scorecards.append(bh_scorecard)

    # 7. Extract SMT Edge Metrics vs Turtle Soup
    smt_card = next((s for s in scorecards if s.strategy_id == "smt_sweep"), None)
    turtle_card = next((s for s in scorecards if s.strategy_id == "turtle_soup"), None)

    edge_summary: dict[str, Any] = {}
    if smt_card and turtle_card:
        # Harmonious breakouts filtered out = turtle trade count - smt trade count (where turtle got chopped)
        breakouts_filtered = max(0, turtle_card.total_trades - smt_card.total_trades)
        edge_summary = {
            "alpha_over_single_sweep": round(smt_card.net_return - turtle_card.net_return, 2),
            "alpha_over_buy_and_hold": round(smt_card.net_return - bh_scorecard.net_return, 2),
            "win_rate_boost_pct": round(smt_card.trade_win_rate - turtle_card.trade_win_rate, 1),
            "sharpe_delta": round(smt_card.sharpe_ratio - turtle_card.sharpe_ratio, 2),
            "sortino_delta": round(smt_card.sortino_ratio - turtle_card.sortino_ratio, 2),
            "drawdown_attenuation_pct": round(
                abs(turtle_card.max_drawdown) - abs(smt_card.max_drawdown), 2
            ),
            "harmonious_breakouts_filtered": breakouts_filtered,
            "statutory_friction_inr": smt_card.statutory_charges,
        }

    return SMTBenchmarkResult(
        symbol=clean_symbol,
        sibling_symbol=clean_sibling,
        period=period,
        start_date=start_date,
        end_date=end_date,
        initial_capital=capital,
        scorecards=scorecards,
        smt_edge_summary=edge_summary,
        provenance=provenance,
    )
