"""
market/options_scanner.py
─────────────────────────
Scan F&O stocks for actionable options setups:
  - High IV Rank (sell premium candidates)
  - Unusual OI buildup (support/resistance walls forming)
  - High put writing (bullish signal)
  - IV crush candidates (near earnings)

Usage:
    scan                      # Scan top F&O stocks
    scan --quick              # Quick scan (NIFTY + BANKNIFTY only)
"""

from __future__ import annotations

from typing import Optional

from rich.console import Console
from rich.table import Table

console = Console()

# F&O universe — top liquid stocks
SCAN_UNIVERSE = [
    "NIFTY",
    "BANKNIFTY",
    "RELIANCE",
    "HDFCBANK",
    "INFY",
    "TCS",
    "ICICIBANK",
    "SBIN",
    "TATAMOTORS",
    "BHARTIARTL",
    "BAJFINANCE",
    "LT",
    "MARUTI",
    "AXISBANK",
    "KOTAKBANK",
    "HINDUNILVR",
]

QUICK_UNIVERSE = ["NIFTY", "BANKNIFTY"]


# ── Filters ──────────────────────────────────────────────────


def filter_high_iv(stocks: list[dict], threshold: float = 60) -> list[dict]:
    """Filter stocks with IV rank above threshold, sorted descending."""
    filtered = [s for s in stocks if s.get("iv_rank") is not None and s["iv_rank"] >= threshold]
    return sorted(filtered, key=lambda x: x["iv_rank"], reverse=True)


def filter_unusual_oi(
    strikes: list[dict],
    threshold: float = 100,
    min_oi: int = 0,
    min_oi_change: int = 0,
    dedup_by_symbol: bool = False,
) -> list[dict]:
    """
    Filter strikes with OI change % above threshold.

    Args:
        strikes: list of strike dicts (with 'oi_change_pct', and optionally 'oi', 'oi_change', 'symbol')
        threshold: minimum percentage OI increase (default 100%)
        min_oi: minimum total contracts to avoid ghost strikes (default 0)
        min_oi_change: minimum absolute OI increase (default 0)
        dedup_by_symbol: if True, returns at most 1 peak spike per symbol
    """
    filtered = []
    for s in strikes:
        pct = s.get("oi_change_pct", 0)
        if pct < threshold:
            continue
        if min_oi > 0 and s.get("oi") is not None and s["oi"] < min_oi:
            continue
        if min_oi_change > 0 and s.get("oi_change") is not None and s["oi_change"] < min_oi_change:
            continue
        filtered.append(s)

    if not dedup_by_symbol:
        return sorted(filtered, key=lambda x: x.get("oi_change_pct", 0), reverse=True)

    # Group by symbol and keep the highest-conviction strike per underlying
    by_symbol: dict[str, list[dict]] = {}
    for s in filtered:
        sym = s.get("symbol")
        if not sym:
            # Item without symbol: treat as distinct
            by_symbol.setdefault(f"_anonymous_{len(by_symbol)}", []).append(s)
        else:
            by_symbol.setdefault(sym, []).append(s)

    deduped = []
    for sym, group in by_symbol.items():
        # Sort group by oi_change_pct descending, then by absolute oi_change
        sorted_group = sorted(
            group,
            key=lambda x: (x.get("oi_change_pct", 0), x.get("oi_change", 0)),
            reverse=True,
        )
        peak = dict(sorted_group[0])
        peak["spikes_count"] = len(sorted_group)
        deduped.append(peak)

    return sorted(deduped, key=lambda x: x.get("oi_change_pct", 0), reverse=True)


# ── Scanner ──────────────────────────────────────────────────


def scan_options(
    symbols: Optional[list[str]] = None,
    quick: bool = False,
) -> dict:
    """
    Scan F&O universe for actionable setups.

    Returns dict with keys:
      high_iv: stocks with IV rank > 60
      unusual_oi: unique symbols with peak OI change > 100% (deduplicated by symbol)
      unusual_oi_contracts: top individual contract strikes
      high_put_writing: stocks with PCR > 1.0
      summary: text summary
    """
    universe = symbols or (QUICK_UNIVERSE if quick else SCAN_UNIVERSE)

    high_iv = []
    unusual_oi = []
    high_put_writing = []

    for sym in universe:
        try:
            # IV Rank
            from analysis.options import compute_iv_rank_from_history

            iv_rank = compute_iv_rank_from_history(sym)

            if iv_rank is not None:
                entry = {"symbol": sym, "iv_rank": round(iv_rank, 1)}

                # PCR
                try:
                    from market.options import get_pcr

                    pcr = get_pcr(sym)
                    entry["pcr"] = round(pcr, 2) if pcr else None
                except Exception:
                    entry["pcr"] = None

                high_iv.append(entry)

                if entry.get("pcr") and entry["pcr"] > 1.0:
                    high_put_writing.append(entry)

            # Unusual OI (check chain)
            try:
                from market.options import get_options_chain

                chain = get_options_chain(sym)
                if chain:
                    is_idx = sym.upper() in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
                    min_oi = 250 if is_idx else 100
                    min_oi_change = 100 if is_idx else 50

                    for c in chain:
                        # Apply institutional liquidity filter to prevent illiquid ghost strikes
                        if c.oi >= min_oi and c.oi_change >= min_oi_change:
                            oi_chg_pct = (c.oi_change / max(c.oi - c.oi_change, 1)) * 100
                            if oi_chg_pct >= 100:
                                contract_sym = getattr(
                                    c, "symbol", f"{sym}{int(c.strike)}{c.option_type}"
                                )
                                unusual_oi.append(
                                    {
                                        "symbol": sym,
                                        "strike": c.strike,
                                        "option_type": c.option_type,
                                        "contract": f"{sym} {int(c.strike)} {c.option_type}",
                                        "tradingsymbol": contract_sym,
                                        "expiry": getattr(c, "expiry", ""),
                                        "oi": c.oi,
                                        "oi_change": c.oi_change,
                                        "oi_change_pct": round(oi_chg_pct, 1),
                                    }
                                )
            except Exception:
                pass

        except Exception:
            continue

    # Deduplicate unusual_oi by symbol so each stock appears at most once with its peak spike
    unique_unusual_oi = filter_unusual_oi(unusual_oi, threshold=100, dedup_by_symbol=True)
    raw_contract_spikes = filter_unusual_oi(unusual_oi, threshold=100, dedup_by_symbol=False)

    return {
        "high_iv": filter_high_iv(high_iv),
        "unusual_oi": unique_unusual_oi[:10],
        "unusual_oi_contracts": raw_contract_spikes[:15],
        "high_put_writing": high_put_writing,
        "summary": f"Scanned {len(universe)} symbols. "
        f"High IV: {len(filter_high_iv(high_iv))} | "
        f"Unusual OI: {len(unique_unusual_oi)} symbols ({len(unusual_oi)} strikes) | "
        f"Put writing: {len(high_put_writing)}",
    }


def print_scan_results(symbols: Optional[list[str]] = None, quick: bool = False) -> None:
    """Display scan results as Rich tables."""
    console.print("[dim]Scanning F&O universe...[/dim]")
    results = scan_options(symbols, quick)

    # High IV table
    if results["high_iv"]:
        table = Table(title="High IV Rank (Sell Premium Candidates)")
        table.add_column("Symbol", style="cyan bold")
        table.add_column("IV Rank", justify="right")
        table.add_column("PCR", justify="right")
        table.add_column("Signal")

        for s in results["high_iv"][:10]:
            signal = ""
            if s["iv_rank"] > 80:
                signal = "[red]Very High — sell straddle/strangle[/red]"
            elif s["iv_rank"] > 60:
                signal = "[yellow]Elevated — sell spreads[/yellow]"
            table.add_row(
                s["symbol"],
                f"{s['iv_rank']:.0f}",
                f"{s['pcr']:.2f}" if s.get("pcr") else "—",
                signal,
            )
        console.print(table)

    # Unusual OI table
    if results["unusual_oi"]:
        console.print()
        table2 = Table(title="Unusual OI Buildup (Peak Spike per Symbol)")
        table2.add_column("Symbol", style="cyan bold")
        table2.add_column("Strike", justify="right")
        table2.add_column("Type", width=4)
        table2.add_column("OI", justify="right")
        table2.add_column("OI Change", justify="right")
        table2.add_column("Change %", justify="right")
        table2.add_column("Active Spikes", justify="right", style="dim")

        for s in results["unusual_oi"][:10]:
            spikes_str = f"{s['spikes_count']} strikes" if s.get("spikes_count") else "1 strike"
            table2.add_row(
                s["symbol"],
                f"{s['strike']:,.0f}",
                s["option_type"],
                f"{s['oi']:,}",
                f"+{s['oi_change']:,}",
                f"[yellow]+{s['oi_change_pct']:.0f}%[/yellow]",
                spikes_str,
            )
        console.print(table2)

    console.print(f"\n[dim]{results['summary']}[/dim]")
