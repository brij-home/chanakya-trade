"""
engine/market_internals.py
──────────────────────────
Index Market Internal Breadth Matrix & Heavyweight Point Contribution Engine.

Institutional Capabilities:
  1. Advance / Decline (A/D) Market Breadth:
     Real-time constituent breadth ratio and net advances across benchmark indices
     (NIFTY 50 and BANKNIFTY).
  2. Percent Above Session VWAP (% > VWAP):
     Percentage of index constituents trading above their intraday volume-weighted
     average price, establishing institutional participation vs distribution.
  3. Weighted Heavyweight Point Contribution:
     Calculates exact index points driven by each heavyweight (e.g. HDFC Bank, Reliance,
     ICICI Bank) based on exchange market-cap weighting.
  4. Institutional Edge & Divergence Classification:
     - BROAD_BASED_BULLISH: High A/D (>= 2.5) + high % > VWAP (>= 70%) -> High-conviction Call buys.
     - BROAD_BASED_BEARISH: Low A/D (<= 0.4) + low % > VWAP (<= 30%) -> High-conviction Put buys.
     - HEAD_FAKE_DIVERGENCE: Index up on mega-cap prop, but majority of constituents down.
     - CHOPPY_EQUILIBRIUM: Mixed dispersion; breakouts fail, spread structures mandated.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any

from engine.feature_bus import INDEX_CONSTITUENT_WEIGHTS
from market.instruments import canonical_symbol

logger = logging.getLogger("engine.market_internals")


# ── Authoritative Benchmark Weights (Synchronized with feature_bus SSOT) ──

NIFTY_WEIGHTS: dict[str, float] = {
    **INDEX_CONSTITUENT_WEIGHTS["NIFTY"],
    "KOTAKBANK": 0.028,
    "HINDUNILVR": 0.024,
    "BAJFINANCE": 0.020,
    "M&M": 0.019,
    "MARUTI": 0.016,
    "SUNPHARMA": 0.015,
    "TMPV": 0.014,
    "HCLTECH": 0.014,
    "NTPC": 0.013,
    "POWERGRID": 0.012,
    "TITAN": 0.012,
    "ASIANPAINT": 0.011,
    "ONGC": 0.010,
    "COALINDIA": 0.009,
    "TATASTEEL": 0.009,
    "JSWSTEEL": 0.008,
    "BAJAJFINSV": 0.008,
    "ADANIENT": 0.008,
    "ADANIPORTS": 0.008,
    "ULTRACEMCO": 0.007,
}

BANKNIFTY_WEIGHTS: dict[str, float] = {
    **INDEX_CONSTITUENT_WEIGHTS["BANKNIFTY"],
    "PNB": 0.030,
    "BANKBARODA": 0.025,
    "FEDERALBNK": 0.025,
    "AUBANK": 0.015,
    "IDFCFIRSTB": 0.010,
    "BANDHANBNK": 0.010,
}

SENSEX_WEIGHTS: dict[str, float] = dict(INDEX_CONSTITUENT_WEIGHTS["SENSEX"])
MIDCPNIFTY_WEIGHTS: dict[str, float] = dict(INDEX_CONSTITUENT_WEIGHTS["MIDCPNIFTY"])
FINNIFTY_WEIGHTS: dict[str, float] = dict(INDEX_CONSTITUENT_WEIGHTS["FINNIFTY"])


@dataclass
class ConstituentContribution:
    """Individual constituent posture and point contribution to index."""

    symbol: str
    weight: float
    ltp: float
    vwap: float
    change_pct: float
    is_above_vwap: bool
    point_contribution: float


@dataclass
class IndexInternalsReport:
    """Complete institutional index market internals report."""

    index: str
    spot: float
    change_pct: float
    total_constituents: int
    advances: int
    declines: int
    unchanged: int
    ad_ratio: float
    pct_above_vwap: float
    net_point_contribution: float
    regime: str  # "BROAD_BASED_BULLISH" | "BROAD_BASED_BEARISH" | "HEAD_FAKE_DIVERGENCE" | "CHOPPY_EQUILIBRIUM"
    regime_summary: str
    actionable_option_guidance: str
    top_positive_drivers: list[dict[str, Any]]
    top_negative_drivers: list[dict[str, Any]]
    as_of: str
    status: str = "AVAILABLE"  # "AVAILABLE" | "UNAVAILABLE"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_INTERNALS_CACHE: dict[str, tuple[float, IndexInternalsReport]] = {}
_INTERNALS_LOCK = threading.Lock()
_CACHE_TTL_SECS = 15.0


def compute_index_internals(index: str = "NIFTY") -> IndexInternalsReport:
    """
    Computes real-time market internals (A/D ratio, % > VWAP, and weighted point contributions)
    for NIFTY 50, BANKNIFTY, SENSEX, MIDCPNIFTY, or FINNIFTY.
    Fails closed with status='UNAVAILABLE' when live index spot or constituent quotes are absent.
    """
    clean_idx = canonical_symbol(index).upper()
    if "SENSEX" in clean_idx:
        target_idx = "SENSEX"
        index_sym = "BSE:SENSEX-INDEX"
        weights_map = SENSEX_WEIGHTS
        constituents = list(SENSEX_WEIGHTS.keys())
    elif any(k in clean_idx for k in ("BANK", "BANKNIFTY", "BANKEX")):
        target_idx = "BANKNIFTY"
        index_sym = "NSE:NIFTY BANK"
        weights_map = BANKNIFTY_WEIGHTS
        constituents = list(BANKNIFTY_WEIGHTS.keys())
    elif "MID" in clean_idx:
        target_idx = "MIDCPNIFTY"
        index_sym = "NSE:MIDCPNIFTY-INDEX"
        weights_map = MIDCPNIFTY_WEIGHTS
        constituents = list(MIDCPNIFTY_WEIGHTS.keys())
    elif "FIN" in clean_idx:
        target_idx = "FINNIFTY"
        index_sym = "NSE:FINNIFTY-INDEX"
        weights_map = FINNIFTY_WEIGHTS
        constituents = list(FINNIFTY_WEIGHTS.keys())
    else:
        target_idx = "NIFTY"
        index_sym = "NSE:NIFTY 50"
        weights_map = NIFTY_WEIGHTS
        from analysis.universe import THEMATIC_PRESETS

        n50_list = THEMATIC_PRESETS.get("nifty50", {}).get("symbols", [])
        constituents = n50_list if len(n50_list) >= 40 else list(NIFTY_WEIGHTS.keys())

    now = time.time()
    with _INTERNALS_LOCK:
        if target_idx in _INTERNALS_CACHE:
            cached_time, cached_rep = _INTERNALS_CACHE[target_idx]
            if now - cached_time < _CACHE_TTL_SECS:
                return cached_rep

    # Fetch Index Spot and Constituent Quotes (never fabricate default spot prices)
    spot = 0.0
    quotes_map: dict[str, Any] = {}
    official_idx_chg = 0.0
    try:
        from market.quotes import get_ltp, get_quote

        spot = float(get_ltp(index_sym) or 0.0)
        formatted_symbols = [f"NSE:{s}" for s in constituents]
        quotes_map = get_quote(formatted_symbols + [index_sym]) or {}
        idx_q = quotes_map.get(index_sym) or quotes_map.get(target_idx)
        if spot <= 0 and idx_q is not None:
            spot = float(getattr(idx_q, "last_price", 0.0) or getattr(idx_q, "ltp", 0.0) or 0.0)
        official_idx_chg = float(getattr(idx_q, "change_pct", 0.0) or 0.0)
    except Exception as exc:
        logger.warning(f"[compute_index_internals] Quote resolution note for {target_idx}: {exc}")

    now_iso = time.strftime("%Y-%m-%d %H:%M:%S IST", time.localtime())

    # Analyze reporting constituents
    contributions: list[ConstituentContribution] = []
    advances = 0
    declines = 0
    unchanged = 0
    above_vwap_count = 0
    reporting = 0

    assigned_weight = sum(weights_map.get(s, 0.0) for s in constituents)
    unassigned_count = sum(1 for s in constituents if s not in weights_map)
    rem_per_stock = (
        ((1.0 - assigned_weight) / max(1, unassigned_count)) if unassigned_count > 0 else 0.005
    )

    for s in constituents:
        q = quotes_map.get(f"NSE:{s}") or quotes_map.get(s)
        ltp = float(getattr(q, "last_price", 0.0) or getattr(q, "ltp", 0.0) or 0.0)
        if ltp <= 0:
            continue
        reporting += 1
        vwap = float(getattr(q, "vwap", 0.0) or ltp)
        chg = float(getattr(q, "change_pct", 0.0) or 0.0)

        weight = weights_map.get(s, rem_per_stock)

        is_above = ltp >= vwap if (ltp > 0 and vwap > 0) else (chg >= 0)
        if is_above:
            above_vwap_count += 1

        if chg > 0.05:
            advances += 1
        elif chg < -0.05:
            declines += 1
        else:
            unchanged += 1

        pt_contrib = round(weight * (chg / 100.0) * spot, 2) if spot > 0 else 0.0

        contributions.append(
            ConstituentContribution(
                symbol=s,
                weight=weight,
                ltp=ltp,
                vwap=vwap,
                change_pct=chg,
                is_above_vwap=is_above,
                point_contribution=pt_contrib,
            )
        )

    if spot <= 0 or reporting == 0:
        return IndexInternalsReport(
            index=target_idx,
            spot=0.0,
            change_pct=0.0,
            total_constituents=0,
            advances=0,
            declines=0,
            unchanged=0,
            ad_ratio=0.0,
            pct_above_vwap=0.0,
            net_point_contribution=0.0,
            regime="UNAVAILABLE",
            regime_summary=f"Live {target_idx} spot or constituent quotes unavailable.",
            actionable_option_guidance="Feed unavailable; withhold directional index internals inference.",
            top_positive_drivers=[],
            top_negative_drivers=[],
            as_of=now_iso,
            status="UNAVAILABLE",
        )

    total_count = reporting
    ad_ratio = round(advances / max(1, declines), 2)
    pct_above_vwap = round((above_vwap_count / max(1, total_count)) * 100.0, 1)
    net_pts = round(sum(c.point_contribution for c in contributions), 2)
    calculated_chg = round((net_pts / spot) * 100.0, 2) if spot > 0 else 0.0
    idx_chg_pct = official_idx_chg if official_idx_chg != 0.0 else calculated_chg

    # Sort drivers
    sorted_by_pts = sorted(contributions, key=lambda c: c.point_contribution, reverse=True)
    top_pos = [
        {
            "symbol": c.symbol,
            "points": c.point_contribution,
            "change_pct": c.change_pct,
            "weight_pct": round(c.weight * 100, 1),
        }
        for c in sorted_by_pts
        if c.point_contribution > 0
    ][:5]
    top_neg = [
        {
            "symbol": c.symbol,
            "points": c.point_contribution,
            "change_pct": c.change_pct,
            "weight_pct": round(c.weight * 100, 1),
        }
        for c in reversed(sorted_by_pts)
        if c.point_contribution < 0
    ][:5]

    # 4. Regime & Guidance Synthesis (Head-Fake Divergence evaluated before Broad-Based regimes)
    if idx_chg_pct >= 0.20 and (ad_ratio < 1.0 or pct_above_vwap < 45.0):
        regime = "HEAD_FAKE_DIVERGENCE"
        top_driver = top_pos[0]["symbol"] if top_pos else "Mega-caps"
        summary = (
            f"Head-Fake Index Divergence detected: {target_idx} is green (+{idx_chg_pct:.2f}%), "
            f"but market breadth is negative (A/D: {ad_ratio:.1f}, only {pct_above_vwap:.0f}% > VWAP). "
            f"Move is concentrated in {top_driver} while broader constituents bleed."
        )
        guidance = (
            "VETO naked index call breakouts. High probability of bull trap or late-day reversal. "
            "Wait for pullback to major value support or trade stock-specific alpha."
        )
    elif idx_chg_pct <= -0.20 and (ad_ratio > 1.0 or pct_above_vwap > 55.0):
        regime = "HEAD_FAKE_DIVERGENCE"
        top_drag = top_neg[0]["symbol"] if top_neg else "Mega-caps"
        summary = (
            f"Bear Trap Divergence detected: {target_idx} spot is red, but majority of constituents "
            f"({pct_above_vwap:.0f}% > VWAP) are positive. Drag is isolated in {top_drag}."
        )
        guidance = (
            "VETO aggressive breakdown shorts. High probability of bear trap bounce. "
            "Look for pullback-to-value longs in strong outperforming constituents."
        )
    elif ad_ratio >= 2.2 and pct_above_vwap >= 65.0:
        regime = "BROAD_BASED_BULLISH"
        summary = (
            f"Strong broad institutional buying across {target_idx}. "
            f"A/D ratio is {ad_ratio:.1f} ({advances} advances vs {declines} declines), "
            f"and {pct_above_vwap:.0f}% of constituents are holding above session VWAP."
        )
        guidance = (
            "Apex high-conviction Call buying regime. Trend breakouts have institutional tailwinds. "
            "Favor ATM/ITM Call options (Delta >= 0.50) or Momentum Breakout spreads."
        )
    elif ad_ratio <= 0.45 and pct_above_vwap <= 35.0:
        regime = "BROAD_BASED_BEARISH"
        summary = (
            f"Broad institutional liquidation across {target_idx}. "
            f"A/D ratio is {ad_ratio:.1f} ({advances} advances vs {declines} declines), "
            f"and only {pct_above_vwap:.0f}% of constituents are above VWAP."
        )
        guidance = (
            "High-conviction Put buying regime. Breakdown moves have broad institutional participation. "
            "Favor ATM Put options or Bear Put Spreads."
        )
    else:
        regime = "CHOPPY_EQUILIBRIUM"
        summary = (
            f"Tug-of-war equilibrium in {target_idx}. A/D is balanced ({advances}:{declines}), "
            f"{pct_above_vwap:.0f}% of stocks near VWAP, and net point contribution is muted."
        )
        guidance = (
            "Avoid chasing directional breakouts. Range-bound regime. Mandate defined-risk "
            "credit spreads or wait for 15-minute Initial Balance boundary tests."
        )

    now_iso = time.strftime("%Y-%m-%d %H:%M:%S IST", time.localtime())
    report = IndexInternalsReport(
        index=target_idx,
        spot=spot,
        change_pct=idx_chg_pct,
        total_constituents=total_count,
        advances=advances,
        declines=declines,
        unchanged=unchanged,
        ad_ratio=ad_ratio,
        pct_above_vwap=pct_above_vwap,
        net_point_contribution=net_pts,
        regime=regime,
        regime_summary=summary,
        actionable_option_guidance=guidance,
        top_positive_drivers=top_pos,
        top_negative_drivers=top_neg,
        as_of=now_iso,
    )

    with _INTERNALS_LOCK:
        _INTERNALS_CACHE[target_idx] = (now, report)

    return report


def clear_index_internals_cache() -> None:
    """Clears the in-memory internals cache (for testing or session reset)."""
    with _INTERNALS_LOCK:
        _INTERNALS_CACHE.clear()
