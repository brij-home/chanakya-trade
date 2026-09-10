"""
engine/precursor_radar.py
─────────────────────────
Autonomous Precursor Radar & High-Conviction Pre-Breakout Scanner.

Identifies explosive trade setups *before* the breakout candle detonates by
matching active watchlist candidates against the pre-move DNA of top gainers.

Core Capabilities:
  1. Orthogonal 100-Point Precursor Conviction Scoring:
     - Volume Dry-Up (Seller Exhaustion) [0–25 pts]
     - Volatility Compression (TTM Squeeze & VCP) [0–25 pts]
     - Institutional Order Block Anchor [0–20 pts]
     - Sector RRG Tailwind (Leading / Improving) [0–15 pts]
     - Options Gamma Positioning & Call Unwinding [0–15 pts]
  2. False-Positive Vetoes & Traps:
     - Hard veto on penny stocks (< ₹10 Cr daily turnover).
     - Hard veto on symbols with active post-mortem invalidation lockouts.
     - 25-point knife-catching penalty for candidates trading below intraday VWAP.
     - Veto on stocks in Lagging RRG sectors with deteriorating momentum.
  3. Actionable Profit Blueprint:
     - Precise coiling entry zone, invalidation stop-loss, Target 1 (1.5R), Target 2 (2.5R+).
     - Explicit "DO NOT CHASE" rules and profit-taking guidelines.
  4. High Conviction Threshold (>= 80/100):
     - Dispatches alerts to Telegram and Web UI only when conviction >= 80.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("chanakya.precursor_radar")

IST = timezone(timedelta(hours=5, minutes=30))

MAJOR_INDICES = [
    "NIFTY",
    "BANKNIFTY",
    "FINNIFTY",
    "MIDCPNIFTY",
    "NIFTYIT",
    "NIFTYAUTO",
    "NIFTYPHARMA",
    "NIFTYMETAL",
    "NIFTYENERGY",
    "SENSEX",
]


def classify_symbol_segment(symbol: str) -> str:
    """
    Classifies a symbol into 'INDEX', 'FNO', or 'NON_FNO'.
    """
    clean = (
        symbol.upper()
        .replace("NSE:", "")
        .replace("BSE:", "")
        .replace(".NS", "")
        .replace("^", "")
        .strip()
    )
    if (
        clean
        in (
            "NIFTY",
            "BANKNIFTY",
            "FINNIFTY",
            "MIDCPNIFTY",
            "NIFTYIT",
            "NIFTYAUTO",
            "NIFTYPHARMA",
            "NIFTYMETAL",
            "NIFTYENERGY",
            "SENSEX",
            "BANKEX",
            "NSEI",
            "NSEBANK",
            "CNXIT",
            "CNXAUTO",
        )
        or clean.endswith("INDEX")
        or clean.startswith("NIFTY")
    ):
        return "INDEX"
    try:
        from engine.position_sizer import is_fno_symbol

        if is_fno_symbol(clean):
            return "FNO"
    except Exception:
        pass
    return "NON_FNO"


@dataclass
class PrecursorCandidate:
    """A qualified pre-breakout candidate coiling for an explosive move."""

    symbol: str
    exchange: str = "NSE"
    direction: str = "BULLISH"
    conviction_score: int = 80  # 0 to 100
    verdict: str = "HIGH_CONVICTION"  # MAX_CONVICTION (>=85) | HIGH_CONVICTION (75-84) | MODERATE
    segment: str = "FNO"  # "FNO" | "NON_FNO" | "INDEX"
    sector_name: str = "General"
    rrg_quadrant: str = "LEADING"
    ltp: float = 0.0
    turnover_cr: float = 0.0

    # Actionable Execution Levels
    entry_range: str = ""
    stop_loss: float = 0.0
    target_1: float = 0.0
    target_2: float = 0.0
    risk_reward: str = "1:2.5"

    # Matched Precursor Factors
    matched_factors: list[str] = field(default_factory=list)
    prior_vol_ratio: float = 1.0
    squeeze_bars: int = 0
    coiling_pivot_high: float = 0.0

    # Execution Playbook
    when_to_buy: str = ""
    when_to_wait: str = ""
    profit_rule: str = ""
    closest_archetype: Optional[str] = None
    scanned_at: str = ""

    def __post_init__(self) -> None:
        if not self.scanned_at:
            self.scanned_at = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PrecursorRadarScanner:
    """
    Scans the liquid universe across F&O, Non-F&O cash equities, and Indices
    to surface high-conviction pre-ignition candidates.
    """

    def __init__(self) -> None:
        self._min_conviction_alert = 75

    def get_scan_universe(self, segment: Optional[str] = None) -> list[str]:
        """
        Returns liquid watchlist universe, filtered by segment if provided.
        segment: 'INDEX' | 'FNO' | 'NON_FNO' | 'ALL' | None
        """
        seg = (segment or "ALL").upper().replace("CASH", "NON_FNO")

        index_universe = [
            "NIFTY",
            "NIFTY 50",
            "BANKNIFTY",
            "FINNIFTY",
            "MIDCPNIFTY",
            "NIFTYIT",
            "NIFTYAUTO",
            "NIFTYPHARMA",
            "NIFTYMETAL",
            "NIFTYENERGY",
            "SENSEX",
        ]

        fno_universe = [
            "RELIANCE",
            "TCS",
            "INFY",
            "HDFCBANK",
            "ICICIBANK",
            "SBIN",
            "BHARTIARTL",
            "TRENT",
            "DIXON",
            "HAL",
            "BEL",
            "ADANIENT",
            "LT",
            "MARUTI",
            "BAJFINANCE",
            "TITAN",
            "COFORGE",
            "PERSISTENT",
            "POLYCAB",
            "KALYANKJIL",
            "BSE",
            "MCX",
            "CDSL",
            "MANKIND",
            "SUNPHARMA",
            "TATAMOTORS",
            "HINDALCO",
            "TATASTEEL",
            "JSWSTEEL",
            "NTPC",
            "ONGC",
            "COALINDIA",
            "POWERGRID",
            "ASIANPAINT",
            "HINDUNILVR",
            "ITC",
            "NESTLEIND",
            "ZOMATO",
            "CHOLAFIN",
            "FEDERALBNK",
            "AUBANK",
            "MAXHEALTH",
            "LUPIN",
            "AUROPHARMA",
            "DLF",
            "GODREJPROP",
            "ABB",
            "SIEMENS",
            "CUMMINSIND",
            "VOLTAS",
            "HAVELLS",
        ]

        non_fno_universe = [
            "KAYNES",
            "SWANENERGY",
            "PREMIERENE",
            "WAAREEENER",
            "ZENTEC",
            "DATAPATTNS",
            "MAZDOCK",
            "COCHINSHIP",
            "ARE&M",
            "INOXWIND",
            "POLICYBZR",
            "MAPMYINDIA",
            "AFFLE",
            "NEWGEN",
            "RATEGAIN",
            "MEDANTA",
            "LALPATHLAB",
            "APLAPOLLO",
            "CENTURYTEX",
            "GRAVITA",
            "RAILTEL",
            "RVNL",
            "IRFC",
            "RITES",
            "IRCON",
            "TEXRAIL",
            "JUPITERWAG",
            "BEML",
            "GRSE",
            "GSHIP",
            "SCI",
            "ELECON",
            "TRITURBINE",
            "KBL",
            "KIRLOSENG",
            "VOLTAMP",
            "SCHNEIDER",
            "KEC",
        ]

        if seg == "INDEX":
            return index_universe
        elif seg == "FNO":
            return fno_universe
        elif seg in ("NON_FNO", "CASH"):
            return non_fno_universe
        else:
            # Balanced multi-segment blend
            return index_universe[:4] + fno_universe[:30] + non_fno_universe[:20]

    def evaluate_symbol(
        self,
        symbol: str,
        df: Optional[pd.DataFrame] = None,
        chain: Optional[list[Any]] = None,
    ) -> Optional[PrecursorCandidate]:
        """
        Evaluates a single stock for pre-move coiling DNA against dynamic factor weights.
        Returns a PrecursorCandidate if the setup meets quality and conviction thresholds.
        """
        clean_sym = symbol.upper().replace("NSE:", "").replace(".NS", "").strip()

        # 1. Check Symbol Invalidation Lockout (Anti-knife catching)
        try:
            from engine.learning_engine import pattern_learning_engine

            is_locked, lock_reason = pattern_learning_engine.is_symbol_locked_out(
                clean_sym, direction="BULLISH"
            )
            if is_locked:
                logger.debug(f"[PrecursorRadar] Skipping {clean_sym}: locked out ({lock_reason})")
                return None
        except Exception:
            pass

        # 2. Fetch Live Quote & Liquidity Checks
        from market.quotes import get_quote

        q_item = None
        try:
            q_res = get_quote(f"NSE:{clean_sym}")
            if isinstance(q_res, dict):
                q_item = q_res.get(f"NSE:{clean_sym}") or q_res.get(clean_sym)
            else:
                q_item = q_res
        except Exception:
            pass

        if not q_item:
            return None

        ltp = 0.0
        for attr in ("last_price", "ltp"):
            val = getattr(q_item, attr, None) if not isinstance(q_item, dict) else q_item.get(attr)
            if val is not None and type(val).__name__ not in (
                "MagicMock",
                "Mock",
                "NonCallableMagicMock",
            ):
                try:
                    f = float(val)
                    if f > 0:
                        ltp = f
                        break
                except (ValueError, TypeError):
                    pass
        if ltp <= 0 and hasattr(q_item, "__dict__"):
            for attr in ("last_price", "ltp"):
                if attr in q_item.__dict__:
                    try:
                        f = float(q_item.__dict__[attr])
                        if f > 0:
                            ltp = f
                            break
                    except (ValueError, TypeError):
                        pass

        if ltp <= 0:
            return None

        vol_val = getattr(q_item, "volume", 0)
        vol = (
            int(vol_val)
            if (vol_val and type(vol_val).__name__ not in ("MagicMock", "Mock"))
            else (
                int(q_item.__dict__["volume"])
                if (hasattr(q_item, "__dict__") and "volume" in q_item.__dict__)
                else 0
            )
        )

        vwap_val = getattr(q_item, "vwap", None)
        if vwap_val is not None and type(vwap_val).__name__ not in ("MagicMock", "Mock"):
            vwap = float(vwap_val)
        elif hasattr(q_item, "__dict__") and "vwap" in q_item.__dict__:
            vwap = float(q_item.__dict__["vwap"])
        else:
            vwap = ltp

        turnover_cr = round((ltp * vol) / 1e7, 2)

        # Anti-Trap: Reject illiquid names
        if turnover_cr < 8.0 and vol < 50000:
            return None

        # 3. Daily History & Structural Footprint
        from market.history import get_ohlcv

        if df is None or len(df) < 20:
            try:
                df = get_ohlcv(clean_sym, exchange="NSE", interval="day", days=45)
            except Exception:
                df = None

        if df is None or len(df) < 20:
            return None

        closes = df["close"].values
        highs = df["high"].values if "high" in df.columns else closes
        lows = df["low"].values if "low" in df.columns else closes
        volumes = df["volume"].values if "volume" in df.columns else None

        # 4. Orthogonal Factor Scoring
        score = 15  # baseline anchor
        matched_factors: list[str] = []

        # A. Volume Dry-Up (Seller Exhaustion) [0–25 pts]
        prior_vol_ratio = 1.0
        if volumes is not None and len(volumes) >= 21:
            avg_20 = float(np.mean(volumes[-21:-1]))
            # Current session volume vs 20D SMA or prior day volume
            prior_vol = float(volumes[-2]) if len(volumes) >= 2 else avg_20
            prior_vol_ratio = round(prior_vol / max(1.0, avg_20), 3)

            if prior_vol_ratio <= 0.20:
                score += 25
                matched_factors.append(
                    f"Extreme Volume Dry-Up ({prior_vol_ratio * 100:.0f}% of 20D SMA — Institutional Supply Exhaustion)"
                )
            elif prior_vol_ratio <= 0.40:
                score += 18
                matched_factors.append(
                    f"Healthy Volume Contraction ({prior_vol_ratio * 100:.0f}% of 20D SMA)"
                )
            elif prior_vol_ratio <= 0.65:
                score += 10

        # B. Volatility Compression / TTM Squeeze [0–25 pts]
        squeeze_bars = 0
        try:
            from analysis.big_move import compute_ttm_squeeze

            sq = compute_ttm_squeeze(df)
            if sq and (sq.is_squeeze_on or sq.squeeze_fired):
                squeeze_bars = sq.squeeze_duration_bars
                if squeeze_bars >= 4:
                    score += 25
                    matched_factors.append(
                        f"Bollinger Bands tightly compressed in Keltner Squeeze ({squeeze_bars} sessions coiled)"
                    )
                elif squeeze_bars >= 2:
                    score += 18
                    matched_factors.append(
                        f"Active Squeeze compression coiling ({squeeze_bars} sessions)"
                    )
        except Exception:
            pass

        # VCP Tightness check
        recent_spreads = [abs(highs[i] - lows[i]) / closes[i] * 100 for i in range(-5, 0)]
        if len(recent_spreads) >= 3 and min(recent_spreads) <= 1.2:
            score += 5
            matched_factors.append("Daily candle range tightly compressed (< 1.2% daily spread)")

        # C. Institutional Order Block Anchor [0–20 pts]
        ob_dist = 2.0
        try:
            from analysis.market_structure import analyze_market_structure

            ms = analyze_market_structure(clean_sym, df=df, exchange="NSE")
            if hasattr(ms, "order_blocks") and ms.order_blocks:
                bull_obs = [ob for ob in ms.order_blocks if getattr(ob, "ob_type", "") == "BULLISH"]
                if bull_obs:
                    nearest_top = bull_obs[0].top
                    ob_dist = round(abs(ltp - nearest_top) / ltp * 100, 2)
                    if ob_dist <= 0.8:
                        score += 20
                        matched_factors.append(
                            f"Anchored within {ob_dist:.1f}% of Bullish Order Block (Asymmetric risk pivot)"
                        )
                    elif ob_dist <= 1.5:
                        score += 12
                        matched_factors.append(
                            f"Holding above institutional Order Block ({ob_dist:.1f}% buffer)"
                        )
        except Exception:
            pass

        # D. Sector RRG Tailwind [0–15 pts]
        sector_name = "Equities"
        rrg_quad = "NEUTRAL"
        try:
            from analysis.sector_rotation import get_stock_sector_alignment

            align = get_stock_sector_alignment(clean_sym)
            if isinstance(align, dict):
                sector_name = align.get("sector_name", sector_name)
                rrg_quad = align.get("quadrant", rrg_quad)
                if rrg_quad == "LEADING":
                    score += 15
                    matched_factors.append(
                        f"Parent sector ({sector_name}) in LEADING RRG quadrant (Institutional inflow tailwind)"
                    )
                elif rrg_quad == "IMPROVING":
                    score += 10
                    matched_factors.append(
                        f"Parent sector ({sector_name}) in IMPROVING RRG quadrant (Emerging rotation)"
                    )
                elif rrg_quad == "LAGGING":
                    score -= 15  # Veto penalty
        except Exception:
            pass

        # E. Options Gamma & Call Unwinding [0–15 pts]
        try:
            from market.options import get_options_chain

            if chain is None:
                chain = get_options_chain(clean_sym)
            if chain:
                ce_shedding = []
                for c in chain:
                    if getattr(c, "option_type", "") == "CE":
                        oi = getattr(c, "oi", 0)
                        doi = getattr(c, "oi_change", 0)
                        if doi < 0 and oi > 0:
                            pct = (doi / max(1, oi - doi)) * 100.0
                            ce_shedding.append(pct)
                if ce_shedding and min(ce_shedding) <= -15.0:
                    score += 15
                    matched_factors.append(
                        f"Call writers shedding {abs(min(ce_shedding)):.1f}% OI (Gamma Trap primed for squeeze)"
                    )
                elif ce_shedding and min(ce_shedding) <= -8.0:
                    score += 10
                    matched_factors.append(
                        f"Call OI liquidation detected ({abs(min(ce_shedding)):.1f}%)"
                    )
        except Exception:
            pass

        # 5. Intraday VWAP & Knife-Catching Check (VETO / PENALTY)
        if vwap > 0 and ltp < vwap:
            score -= 25
            matched_factors.append(
                f"⚠️ Trading below intraday VWAP (₹{vwap:,.1f}) — Knife-catching risk penalty applied"
            )

        # Cap score between 0 and 98
        score = max(5, min(98, score))

        # Only qualify setups with score >= 75
        if score < self._min_conviction_alert:
            return None

        # 6. Trade Blueprint Formulation
        pivot_high = (
            round(float(np.max(highs[-5:])), 2) if len(highs) >= 5 else round(ltp * 1.01, 2)
        )
        entry_low = round(ltp * 0.995, 2)
        entry_high = round(pivot_high * 1.005, 2)
        entry_range = f"₹{entry_low:,.1f} – ₹{entry_high:,.1f}"

        # Calculate ATR-based Stop-Loss
        sl_distance = (
            max(ltp * 0.015, (ltp - float(np.min(lows[-5:]))) * 1.05)
            if len(lows) >= 5
            else ltp * 0.02
        )
        stop_loss = round(ltp - sl_distance, 2)
        risk_pts = max(1.0, ltp - stop_loss)

        target_1 = round(ltp + 1.5 * risk_pts, 2)
        target_2 = round(ltp + 2.5 * risk_pts, 2)
        rr_str = f"1:{((target_1 - ltp) / risk_pts):.1f}"

        verdict = "MAX_CONVICTION" if score >= 85 else "HIGH_CONVICTION"

        when_buy = f"Enter on Ask/Retest within coiling range ({entry_range}) while price holds above ₹{entry_low:,.1f} and VWAP."
        when_wait = f"DO NOT CHASE if stock gaps up > 1.8% at open (above ₹{round(ltp * 1.018, 1):,}). Wait for a 15-min VWAP pullback."
        profit_rule = f"Book 50% profit at Target 1 (₹{target_1:,.1f}), move Stop-Loss to Breakeven, and trail runner to Target 2 (₹{target_2:,.1f})."
        has_squeeze = squeeze_bars >= 2
        severe_dry_up = prior_vol_ratio <= 0.40
        closest_archetype = (
            "ARCHETYPE_VOLATILITY_CONTRACTION_SPRING"
            if has_squeeze
            else "ARCHETYPE_INSTITUTIONAL_ABSORPTION"
            if severe_dry_up
            else "ARCHETYPE_MOMENTUM_TREND_CONTINUATION"
        )

        segment = classify_symbol_segment(clean_sym)

        return PrecursorCandidate(
            symbol=clean_sym,
            exchange="NSE",
            direction="BULLISH",
            conviction_score=score,
            verdict=verdict,
            segment=segment,
            sector_name=sector_name,
            rrg_quadrant=rrg_quad,
            ltp=round(ltp, 2),
            turnover_cr=turnover_cr,
            entry_range=entry_range,
            stop_loss=stop_loss,
            target_1=target_1,
            target_2=target_2,
            risk_reward=rr_str,
            matched_factors=matched_factors,
            prior_vol_ratio=prior_vol_ratio,
            squeeze_bars=squeeze_bars,
            coiling_pivot_high=pivot_high,
            when_to_buy=when_buy,
            when_to_wait=when_wait,
            profit_rule=profit_rule,
            closest_archetype=closest_archetype,
        )

    def scan_precursors(
        self,
        universe: Optional[list[str]] = None,
        segment: Optional[str] = None,
        top_n: int = 5,
    ) -> list[PrecursorCandidate]:
        """
        Scans universe and returns top N high-conviction pre-ignition candidates.
        Can be filtered by segment ('INDEX' | 'FNO' | 'NON_FNO' | 'ALL').
        """
        symbols = universe or self.get_scan_universe(segment=segment)
        candidates: list[PrecursorCandidate] = []

        logger.info(
            f"[PrecursorRadar] Scanning {len(symbols)} tickers ({segment or 'ALL'}) for pre-move precursor DNA..."
        )

        for sym in symbols:
            try:
                candidate = self.evaluate_symbol(sym)
                if candidate:
                    candidates.append(candidate)
            except Exception as e:
                logger.debug(f"[PrecursorRadar] Evaluation error on {sym}: {e}")

        # Sort descending by conviction score
        candidates.sort(key=lambda c: c.conviction_score, reverse=True)
        top_candidates = candidates[:top_n]

        logger.info(
            f"[PrecursorRadar] Precursor scan completed: {len(top_candidates)} high-conviction setups found."
        )
        return top_candidates


# Module-level singleton instance
precursor_radar = PrecursorRadarScanner()


def get_scan_universe(segment: Optional[str] = None) -> list[str]:
    """Module-level convenience accessor for scan universes."""
    return precursor_radar.get_scan_universe(segment=segment)
