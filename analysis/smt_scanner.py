"""
analysis/smt_scanner.py
───────────────────────
Cross-Market Smart Money Technique (SMT) Divergence Scanner.

Analyzes institutional inter-market correlations across Indian markets:
  1. Benchmark Indices (NSE): NIFTY 50 vs BANK NIFTY (Banking ~34% of NIFTY weight)
  2. Financial Services (NSE): FINNIFTY vs BANK NIFTY
  3. BSE Benchmarks: SENSEX vs BANKEX
  4. Precious Metals (MCX): GOLD vs SILVER (Bullion Safe-Haven ratio)
  5. Energy Complex (MCX): CRUDE OIL vs NATURAL GAS

Divergence Patterns Detected:
  - Bullish SMT Accumulation (Bear Trap): Primary breaks Day Low, Sibling prints Higher Low / holds VWAP.
  - Bearish SMT Distribution (Judas Swing Bull Trap): Primary breaks Day High, Sibling prints Lower High / stays below VWAP.
  - Locomotive Polarization: One asset above VWAP (+ momentum), Sibling trapped below VWAP (Chop/whipsaw hazard).
  - Harmonious Flow: Correlated assets expanding synchronously in same direction (Institutional trend confirmation).
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Optional

logger = logging.getLogger("analysis.smt_scanner")

DEFAULT_SMT_PAIRS = [
    {
        "pair_id": "NIFTY_BANKNIFTY",
        "asset_a": "NIFTY",
        "asset_b": "BANKNIFTY",
        "exchange_a": "NSE",
        "exchange_b": "NSE",
        "category": "BENCHMARK_INDEX",
        "description": "NSE Flagship Benchmark vs Banking Engine (~34% Nifty weight)",
    },
    {
        "pair_id": "FINNIFTY_BANKNIFTY",
        "asset_a": "FINNIFTY",
        "asset_b": "BANKNIFTY",
        "exchange_a": "NSE",
        "exchange_b": "NSE",
        "category": "FINANCIAL_SERVICES",
        "description": "Financial Services vs Banking Core Sync",
    },
    {
        "pair_id": "SENSEX_BANKEX",
        "asset_a": "SENSEX",
        "asset_b": "BANKEX",
        "exchange_a": "BSE",
        "exchange_b": "BSE",
        "category": "BSE_BENCHMARK",
        "description": "BSE 30-Pack vs BSE Banking Sector",
    },
    {
        "pair_id": "GOLD_SILVER",
        "asset_a": "GOLD",
        "asset_b": "SILVER",
        "exchange_a": "MCX",
        "exchange_b": "MCX",
        "category": "PRECIOUS_METALS",
        "description": "MCX Bullion Complex — Global Safe-Haven & Currency Hedge",
    },
    {
        "pair_id": "CRUDE_NATGAS",
        "asset_a": "CRUDEOIL",
        "asset_b": "NATURALGAS",
        "exchange_a": "MCX",
        "exchange_b": "MCX",
        "category": "ENERGY_COMPLEX",
        "description": "MCX Hydrocarbon Energy Complex",
    },
]


@dataclass
class AssetMetrics:
    symbol: str
    exchange: str
    ltp: float
    day_high: float
    day_low: float
    prev_close: float
    change_pct: float
    vwap: float = 0.0
    obi: float = 0.0


@dataclass
class SMTScanItem:
    pair_id: str
    category: str
    asset_a: str
    asset_b: str
    status: str  # "BULLISH_SMT_ACCUMULATION" | "BEARISH_SMT_DISTRIBUTION" | "POLARIZED_CONFLICT" | "HARMONIOUS_FLOW" | "NEUTRAL"
    conviction_score: int  # 0 to 100
    actionable_directive: str  # "VETO_SHORTS_LOOK_FOR_LONGS" | "VETO_LONGS_LOOK_FOR_SHORTS" | "STAND_ASIDE_CHOP" | "FOLLOW_TREND" | "MONITOR"
    rationale: str
    asset_a_metrics: dict[str, Any]
    asset_b_metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _fetch_metrics(
    symbol: str, exchange: str, quotes_cache: Optional[dict[str, Any]] = None
) -> AssetMetrics:
    """Fetch live or cached metrics for an asset."""
    sym_clean = (
        symbol.upper()
        .replace("NSE:", "")
        .replace("BSE:", "")
        .replace("MCX:", "")
        .replace("-INDEX", "")
    )
    full_sym = f"{exchange}:{sym_clean}" if not symbol.startswith(f"{exchange}:") else symbol

    ltp = 0.0
    day_high = 0.0
    day_low = 0.0
    prev_close = 0.0
    vwap = 0.0
    obi = 0.0

    if quotes_cache:
        q = (
            quotes_cache.get(full_sym)
            or quotes_cache.get(sym_clean)
            or quotes_cache.get(f"{full_sym}-INDEX")
        )
        if q:
            ltp = _safe_float(
                getattr(q, "last_price", None)
                or getattr(q, "ltp", None)
                or (q.get("ltp") if isinstance(q, dict) else None)
            )
            day_high = _safe_float(
                getattr(q, "high", None) or (q.get("high") if isinstance(q, dict) else None)
            )
            day_low = _safe_float(
                getattr(q, "low", None) or (q.get("low") if isinstance(q, dict) else None)
            )
            prev_close = _safe_float(
                getattr(q, "prev_close", None)
                or getattr(q, "close", None)
                or (q.get("prev_close") if isinstance(q, dict) else None)
            )
            vwap = _safe_float(
                getattr(q, "vwap", None) or (q.get("vwap") if isinstance(q, dict) else None)
            )

    if ltp <= 0.0:
        try:
            from market.quotes import get_ltp, get_quote, get_computed_vwap

            inst = (
                f"{exchange}:{sym_clean}-INDEX"
                if exchange in ("NSE", "BSE")
                and sym_clean in ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "BANKEX")
                else full_sym
            )
            ltp = _safe_float(get_ltp(inst) or get_ltp(full_sym) or get_ltp(sym_clean))
            q_res = get_quote([inst, full_sym])
            q_obj = q_res.get(inst) or q_res.get(full_sym)
            if q_obj:
                day_high = _safe_float(getattr(q_obj, "high", 0.0))
                day_low = _safe_float(getattr(q_obj, "low", 0.0))
                prev_close = _safe_float(getattr(q_obj, "prev_close", getattr(q_obj, "close", 0.0)))
                vwap = _safe_float(getattr(q_obj, "vwap", 0.0))
            if vwap <= 0.0 and ltp > 0.0:
                vwap = _safe_float(get_computed_vwap(sym_clean, exchange=exchange))
        except Exception as e_q:
            logger.debug(f"[smt_scanner] Quote lookup fallback for {symbol}: {e_q}")

    change_pct = ((ltp - prev_close) / prev_close * 100.0) if prev_close > 0 and ltp > 0 else 0.0

    return AssetMetrics(
        symbol=sym_clean,
        exchange=exchange,
        ltp=round(ltp, 2),
        day_high=round(day_high, 2),
        day_low=round(day_low, 2),
        prev_close=round(prev_close, 2),
        change_pct=round(change_pct, 2),
        vwap=round(vwap, 2),
        obi=round(obi, 2),
    )


def evaluate_pair_smt(
    m_a: AssetMetrics,
    m_b: AssetMetrics,
    pair_meta: dict[str, Any],
) -> SMTScanItem:
    """Evaluates cross-market SMT divergence between asset A and asset B."""
    pair_id = pair_meta.get("pair_id", f"{m_a.symbol}_{m_b.symbol}")
    cat = pair_meta.get("category", "MARKET_CORRELATION")

    if m_a.ltp <= 0 or m_b.ltp <= 0:
        return SMTScanItem(
            pair_id=pair_id,
            category=cat,
            asset_a=m_a.symbol,
            asset_b=m_b.symbol,
            status="NEUTRAL",
            conviction_score=0,
            actionable_directive="MONITOR",
            rationale=f"Insufficient telemetry data for {m_a.symbol} or {m_b.symbol}",
            asset_a_metrics=asdict(m_a),
            asset_b_metrics=asdict(m_b),
        )

    # 1. Day Extreme Proximity
    # Is asset A testing / breaking day high (within 0.25% or above)?
    a_at_high = m_a.day_high > 0 and (m_a.ltp >= m_a.day_high * 0.9975)
    # Is asset A testing / breaking day low (within 0.25% or below)?
    a_at_low = m_a.day_low > 0 and (m_a.ltp <= m_a.day_low * 1.0025)

    # Same for asset B
    b_at_high = m_b.day_high > 0 and (m_b.ltp >= m_b.day_high * 0.9975)
    b_at_low = m_b.day_low > 0 and (m_b.ltp <= m_b.day_low * 1.0025)

    # VWAP relationship
    a_above_vwap = m_a.vwap > 0 and (m_a.ltp > m_a.vwap)
    a_below_vwap = m_a.vwap > 0 and (m_a.ltp < m_a.vwap)
    b_above_vwap = m_b.vwap > 0 and (m_b.ltp > m_b.vwap)
    b_below_vwap = m_b.vwap > 0 and (m_b.ltp < m_b.vwap)

    # ── CASE 0: EXTREME POLARIZATION (One at Day High, sibling at Day Low) ──
    if (a_at_high and b_at_low) or (b_at_high and a_at_low):
        high_asset = m_a.symbol if a_at_high else m_b.symbol
        low_asset = m_b.symbol if a_at_high else m_a.symbol
        rationale = (
            f"Extreme Locomotive Polarization: {high_asset} is pressing Day High while {low_asset} is breaking Day Low. "
            f"Severe inter-market divergence and conflicting institutional capital flows mandate standing aside."
        )
        return SMTScanItem(
            pair_id=pair_id,
            category=cat,
            asset_a=m_a.symbol,
            asset_b=m_b.symbol,
            status="POLARIZED_CONFLICT",
            conviction_score=85,
            actionable_directive="STAND_ASIDE_CHOP",
            rationale=rationale,
            asset_a_metrics=asdict(m_a),
            asset_b_metrics=asdict(m_b),
        )

    # ── CASE 1: BEARISH SMT DISTRIBUTION (Judas Swing / Bull Trap) ──
    # One asset makes / tests new high, sibling fails to confirm (stays lower, not at day low, trapped below VWAP)
    if (
        a_at_high
        and not b_at_high
        and not b_at_low
        and (b_below_vwap or m_b.change_pct < m_a.change_pct - 0.3)
    ) or (
        b_at_high
        and not a_at_high
        and not a_at_low
        and (a_below_vwap or m_a.change_pct < m_b.change_pct - 0.3)
    ):
        leader = m_a.symbol if a_at_high else m_b.symbol
        laggard = m_b.symbol if a_at_high else m_a.symbol
        laggard_m = m_b if a_at_high else m_a
        rationale = (
            f"Bearish SMT Divergence: {leader} tested Day High, but correlated sibling {laggard} "
            f"failed to confirm ({laggard_m.change_pct:+.2f}%, {'below VWAP' if (b_below_vwap if a_at_high else a_below_vwap) else 'lagging'}). "
            f"Classic institutional distribution & Judas swing bull trap."
        )
        return SMTScanItem(
            pair_id=pair_id,
            category=cat,
            asset_a=m_a.symbol,
            asset_b=m_b.symbol,
            status="BEARISH_SMT_DISTRIBUTION",
            conviction_score=88,
            actionable_directive="VETO_LONGS_LOOK_FOR_SHORTS",
            rationale=rationale,
            asset_a_metrics=asdict(m_a),
            asset_b_metrics=asdict(m_b),
        )

    # ── CASE 2: BULLISH SMT ACCUMULATION (Bear Trap / Liquidity Sweep) ──
    # One asset makes / tests new low, sibling refuses to break low (holds higher, not at day high, holds above VWAP)
    if (
        a_at_low
        and not b_at_low
        and not b_at_high
        and (b_above_vwap or m_b.change_pct > m_a.change_pct + 0.3)
    ) or (
        b_at_low
        and not a_at_low
        and not a_at_high
        and (a_above_vwap or m_a.change_pct > m_b.change_pct + 0.3)
    ):
        leader = m_a.symbol if a_at_low else m_b.symbol
        absorber = m_b.symbol if a_at_low else m_a
        absorber_m = m_b if a_at_low else m_a
        rationale = (
            f"Bullish SMT Divergence: {leader} broke/tested Day Low, but correlated sibling {absorber} "
            f"refused to make a new low ({absorber_m.change_pct:+.2f}%, {'above VWAP' if (b_above_vwap if a_at_low else a_above_vwap) else 'holding'}). "
            f"Smart money absorption & bear trap accumulation."
        )
        return SMTScanItem(
            pair_id=pair_id,
            category=cat,
            asset_a=m_a.symbol,
            asset_b=m_b.symbol,
            status="BULLISH_SMT_ACCUMULATION",
            conviction_score=90,
            actionable_directive="VETO_SHORTS_LOOK_FOR_LONGS",
            rationale=rationale,
            asset_a_metrics=asdict(m_a),
            asset_b_metrics=asdict(m_b),
        )

    # ── CASE 3: LOCOMOTIVE CONFLICT / POLARIZATION ──
    # One asset significantly green above VWAP, sibling significantly red below VWAP
    if (a_above_vwap and b_below_vwap and m_a.change_pct > 0.2 and m_b.change_pct < -0.2) or (
        b_above_vwap and a_below_vwap and m_b.change_pct > 0.2 and m_a.change_pct < -0.2
    ):
        rationale = (
            f"Locomotive Polarization Conflict: {m_a.symbol} ({m_a.change_pct:+.2f}%) and "
            f"{m_b.symbol} ({m_b.change_pct:+.2f}%) are pulling in opposite directions across VWAP. "
            f"Lack of institutional market harmony indicates high risk of rotational chop."
        )
        return SMTScanItem(
            pair_id=pair_id,
            category=cat,
            asset_a=m_a.symbol,
            asset_b=m_b.symbol,
            status="POLARIZED_CONFLICT",
            conviction_score=75,
            actionable_directive="STAND_ASIDE_CHOP",
            rationale=rationale,
            asset_a_metrics=asdict(m_a),
            asset_b_metrics=asdict(m_b),
        )

    # ── CASE 4: HARMONIOUS TREND FLOW ──
    # Both assets moving strongly in the same direction
    if (
        m_a.change_pct > 0.35
        and m_b.change_pct > 0.35
        and (a_above_vwap or not m_a.vwap)
        and (b_above_vwap or not m_b.vwap)
    ):
        rationale = (
            f"Harmonious Bullish Flow: Both {m_a.symbol} ({m_a.change_pct:+.2f}%) and {m_b.symbol} ({m_b.change_pct:+.2f}%) "
            f"are expanding synchronously above VWAP. Multi-asset institutional trend confirmed."
        )
        return SMTScanItem(
            pair_id=pair_id,
            category=cat,
            asset_a=m_a.symbol,
            asset_b=m_b.symbol,
            status="HARMONIOUS_FLOW",
            conviction_score=85,
            actionable_directive="FOLLOW_TREND",
            rationale=rationale,
            asset_a_metrics=asdict(m_a),
            asset_b_metrics=asdict(m_b),
        )
    elif (
        m_a.change_pct < -0.35
        and m_b.change_pct < -0.35
        and (a_below_vwap or not m_a.vwap)
        and (b_below_vwap or not m_b.vwap)
    ):
        rationale = (
            f"Harmonious Bearish Flow: Both {m_a.symbol} ({m_a.change_pct:+.2f}%) and {m_b.symbol} ({m_b.change_pct:+.2f}%) "
            f"are declining synchronously below VWAP. Institutional liquidation confirmed."
        )
        return SMTScanItem(
            pair_id=pair_id,
            category=cat,
            asset_a=m_a.symbol,
            asset_b=m_b.symbol,
            status="HARMONIOUS_FLOW",
            conviction_score=85,
            actionable_directive="FOLLOW_TREND",
            rationale=rationale,
            asset_a_metrics=asdict(m_a),
            asset_b_metrics=asdict(m_b),
        )

    # Default: Neutral Rangebound
    return SMTScanItem(
        pair_id=pair_id,
        category=cat,
        asset_a=m_a.symbol,
        asset_b=m_b.symbol,
        status="NEUTRAL",
        conviction_score=40,
        actionable_directive="MONITOR",
        rationale=f"Balanced rangebound trading across {m_a.symbol} and {m_b.symbol} without significant divergence.",
        asset_a_metrics=asdict(m_a),
        asset_b_metrics=asdict(m_b),
    )


def scan_cross_market_smt_divergences(
    pairs: Optional[list[dict[str, Any]]] = None,
    quotes_cache: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Executes a comprehensive scan across all institutional cross-market pairs.
    Returns aggregated counts and detailed scan items.
    """
    target_pairs = pairs or DEFAULT_SMT_PAIRS
    items: list[SMTScanItem] = []

    for p in target_pairs:
        m_a = _fetch_metrics(p["asset_a"], p.get("exchange_a", "NSE"), quotes_cache=quotes_cache)
        m_b = _fetch_metrics(p["asset_b"], p.get("exchange_b", "NSE"), quotes_cache=quotes_cache)
        res = evaluate_pair_smt(m_a, m_b, p)
        items.append(res)

    bullish_count = sum(1 for i in items if i.status == "BULLISH_SMT_ACCUMULATION")
    bearish_count = sum(1 for i in items if i.status == "BEARISH_SMT_DISTRIBUTION")
    conflict_count = sum(1 for i in items if i.status == "POLARIZED_CONFLICT")
    harmony_count = sum(1 for i in items if i.status == "HARMONIOUS_FLOW")

    return {
        "status": "ok",
        "summary": {
            "total_pairs_scanned": len(items),
            "bullish_divergences": bullish_count,
            "bearish_divergences": bearish_count,
            "polarized_conflicts": conflict_count,
            "harmonious_flows": harmony_count,
        },
        "pairs": [i.to_dict() for i in items],
    }
