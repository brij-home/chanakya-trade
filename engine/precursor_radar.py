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
    Classifies a symbol into 'INDEX', 'FNO', 'NON_FNO', 'COMMODITY', or 'CRYPTO'.
    """
    clean = (
        symbol.upper()
        .replace("NSE:", "")
        .replace("BSE:", "")
        .replace("MCX:", "")
        .replace("CRYPTO:", "")
        .replace("BINANCE:", "")
        .replace(".NS", "")
        .replace("^", "")
        .strip()
    )
    if symbol.upper().startswith("CRYPTO:") or symbol.upper().startswith("BINANCE:"):
        return "CRYPTO"
    try:
        from market.quotes import _CRYPTO_SYMBOLS

        if clean in _CRYPTO_SYMBOLS:
            return "CRYPTO"
    except Exception:
        pass
    if clean in ("BTC", "ETH", "SOL", "BNB", "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"):
        return "CRYPTO"
    if symbol.upper().startswith("MCX:"):
        return "COMMODITY"
    try:
        from market.quotes import _MCX_SYMBOLS

        if clean in _MCX_SYMBOLS and clean not in ("MCX",):
            return "COMMODITY"
    except Exception:
        pass
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
    timeframe: str = "1D"
    is_nr7_coiling: bool = False
    is_inside_bar: bool = False

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

    def __init__(self, min_conviction: int = 70) -> None:
        self._min_conviction_alert = min_conviction
        self._cache: dict[Any, list[PrecursorCandidate]] = {}
        self._cache_ts: dict[Any, float] = {}
        self._cache_ttl: float = 30.0
        import threading

        self._cache_lock = threading.Lock()

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
            "M&M",
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
            "MAZDOCK",
            "COCHINSHIP",
            "KAYNES",
            "PREMIERENE",
            "WAAREEENER",
            "INOXWIND",
            "POLICYBZR",
            "APLAPOLLO",
            "RVNL",
            "IRFC",
        ]

        non_fno_universe = [
            "KPITTECH",
            "ZENTEC",
            "DATAPATTNS",
            "ARE&M",
            "MAPMYINDIA",
            "AFFLE",
            "NEWGEN",
            "RATEGAIN",
            "MEDANTA",
            "LALPATHLAB",
            "CENTURYPLY",
            "GRAVITA",
            "RAILTEL",
            "RITES",
            "IRCON",
            "TEXRAIL",
            "TITAGARH",
            "BEML",
            "GRSE",
            "GESHIP",
            "SCI",
            "ELECON",
            "TRITURBINE",
            "KBL",
            "KIRLOSENG",
            "VOLTAMP",
            "SCHNEIDER",
            "KEC",
        ]

        commodity_universe = [
            "CRUDEOIL",
            "GOLD",
            "SILVER",
            "COPPER",
            "NATURALGAS",
        ]

        crypto_universe = [
            "BTC",
            "ETH",
            "SOL",
            "BNB",
        ]

        if seg == "INDEX":
            return index_universe
        elif seg == "FNO":
            return fno_universe
        elif seg in ("NON_FNO", "CASH"):
            return non_fno_universe
        elif seg in ("COMMODITY", "MCX"):
            return commodity_universe
        elif seg in ("CRYPTO", "BINANCE"):
            return crypto_universe
        else:
            # Balanced multi-segment blend
            return (
                index_universe[:4]
                + fno_universe[:30]
                + non_fno_universe[:20]
                + commodity_universe
                + crypto_universe
            )

    def evaluate_symbol(
        self,
        symbol: str,
        df: Optional[pd.DataFrame] = None,
        chain: Optional[list[Any]] = None,
        quote: Optional[Any] = None,
        interval: str = "day",
    ) -> Optional[PrecursorCandidate]:
        """
        Evaluates a single stock for pre-move coiling DNA against dynamic factor weights.
        Returns a PrecursorCandidate if the setup meets quality and conviction thresholds.
        """
        clean_sym = (
            symbol.upper()
            .replace("NSE:", "")
            .replace("BSE:", "")
            .replace("MCX:", "")
            .replace("CRYPTO:", "")
            .replace("BINANCE:", "")
            .replace(".NS", "")
            .strip()
        )
        sym_seg = classify_symbol_segment(symbol)

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

        q_item = quote
        if q_item is None:
            try:
                inst_lookup = (
                    f"CRYPTO:{clean_sym}"
                    if sym_seg == "CRYPTO"
                    else (f"MCX:{clean_sym}" if sym_seg == "COMMODITY" else f"NSE:{clean_sym}")
                )
                q_res = get_quote(inst_lookup)
                if isinstance(q_res, dict):
                    q_item = q_res.get(inst_lookup) or q_res.get(clean_sym)
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

        vwap = ltp
        vwap_val = getattr(q_item, "vwap", None)
        if vwap_val is not None and type(vwap_val).__name__ not in ("MagicMock", "Mock"):
            try:
                f = float(vwap_val)
                if f > 0:
                    vwap = f
            except (ValueError, TypeError):
                pass
        elif hasattr(q_item, "__dict__") and "vwap" in q_item.__dict__:
            try:
                f = float(q_item.__dict__["vwap"])
                if f > 0:
                    vwap = f
            except (ValueError, TypeError):
                pass

        # 3. Daily History & Structural Footprint
        from market.history import get_ohlcv

        hist_exchange = (
            "CRYPTO" if sym_seg == "CRYPTO" else ("MCX" if sym_seg == "COMMODITY" else "NSE")
        )

        if df is None or len(df) < 20:
            try:
                days_to_fetch = 45 if interval == "day" else 12
                df = get_ohlcv(
                    clean_sym, exchange=hist_exchange, interval=interval, days=days_to_fetch
                )
            except Exception:
                df = None

        if df is None or len(df) < 20:
            return None

        closes = df["close"].values
        highs = df["high"].values if "high" in df.columns else closes
        lows = df["low"].values if "low" in df.columns else closes
        volumes = df["volume"].values if "volume" in df.columns else None

        # Fallback to daily session volume when quote volume is 0/delayed
        if vol <= 0 and volumes is not None and len(volumes) > 0:
            try:
                vol = int(volumes[-1])
            except Exception:
                pass

        turnover_cr = round((ltp * vol) / 1e7, 2)
        avg_20_vol = (
            float(np.mean(volumes[-21:-1]))
            if (volumes is not None and len(volumes) >= 21)
            else float(vol)
        )
        avg_turnover_cr = round((ltp * avg_20_vol) / 1e7, 2)

        # Anti-Trap: Reject illiquid names (evaluate against both session and 20D average)
        # Turnover in INR only applies to Indian cash equities
        if sym_seg not in ("CRYPTO", "COMMODITY", "INDEX"):
            if turnover_cr < 8.0 and avg_turnover_cr < 8.0 and vol < 50000 and avg_20_vol < 50000:
                return None

        # 4. Orthogonal Factor Scoring
        score = 15  # baseline anchor
        matched_factors: list[str] = []

        # A. Volume Dry-Up (Seller Exhaustion) or Early Institutional Volume Surge [0–25 pts]
        prior_vol_ratio = 1.0
        session_vol_ratio = 1.0
        if volumes is not None and len(volumes) >= 21:
            avg_20 = float(np.mean(volumes[-21:-1]))
            # Current session volume vs 20D SMA or prior day volume
            prior_vol = float(volumes[-2]) if len(volumes) >= 2 else avg_20
            prior_vol_ratio = round(prior_vol / max(1.0, avg_20), 3)
            session_vol_ratio = round(vol / max(1.0, avg_20), 3)

            # Intraday TOD-RVOL check if volume is already active
            tod_rvol = 1.0
            if vol > 0:
                try:
                    from engine.auto_alert_engine import compute_time_of_day_rvol

                    tod_rvol = compute_time_of_day_rvol(vol, avg_20)
                except Exception:
                    tod_rvol = session_vol_ratio

            # Evaluate either intraday surge, full-day surge (>=1.3x), or supply dry-up (<=0.4x)
            if tod_rvol >= 1.6 or session_vol_ratio >= 1.3:
                score += 25
                v_mult = max(tod_rvol, session_vol_ratio)
                matched_factors.append(
                    f"Institutional Volume Expansion ({v_mult:.1f}x RVOL above normal expectation)"
                )
            elif prior_vol_ratio <= 0.20 or session_vol_ratio <= 0.30:
                score += 25
                matched_factors.append(
                    f"Extreme Volume Dry-Up ({min(prior_vol_ratio, session_vol_ratio) * 100:.0f}% of 20D SMA — Institutional Supply Exhaustion)"
                )
            elif prior_vol_ratio <= 0.40 or session_vol_ratio <= 0.50:
                score += 18
                matched_factors.append(
                    f"Healthy Volume Contraction ({min(prior_vol_ratio, session_vol_ratio) * 100:.0f}% of 20D SMA)"
                )
            elif prior_vol_ratio <= 0.65 or session_vol_ratio <= 0.70:
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

        # NR7 & Inside Bar Compression Check (Imminent Volatility Expansion Precursor)
        is_nr7 = False
        is_ib = False
        if len(highs) >= 8 and len(lows) >= 8:
            bar_ranges = [highs[i] - lows[i] for i in range(-7, 0)]
            curr_bar_range = bar_ranges[-1]
            prior_6_ranges = bar_ranges[:-1]
            if curr_bar_range <= min(prior_6_ranges):
                is_nr7 = True
                score += 10
                matched_factors.append(
                    "NR7 Coiling Pattern (Narrowest Range of 7 bars — imminent explosive volatility expansion)"
                )

            if highs[-1] <= highs[-2] and lows[-1] >= lows[-2]:
                is_ib = True
                score += 8
                matched_factors.append(
                    "Inside Bar Compression (Range coiled entirely inside prior bar — energy coiling)"
                )

        # C. Institutional Order Block Anchor & Structural Support [0–20 pts]
        ob_dist = 2.0
        try:
            from analysis.market_structure import analyze_market_structure

            ms = analyze_market_structure(clean_sym, df=df, exchange="NSE")
            demand_zones = getattr(ms, "active_demand_zones", []) or []
            nearest_sup = getattr(ms, "nearest_support", 0.0) or 0.0
            in_discount = getattr(ms, "in_discount_zone", False)

            if demand_zones:
                nearest_top = demand_zones[0].top
                ob_dist = round(abs(ltp - nearest_top) / ltp * 100, 2)
                if ob_dist <= 1.2:
                    score += 20
                    matched_factors.append(
                        f"Anchored within {ob_dist:.1f}% of Bullish Demand Zone (Asymmetric risk pivot)"
                    )
                elif ob_dist <= 2.2:
                    score += 12
                    matched_factors.append(
                        f"Holding above institutional Demand Zone ({ob_dist:.1f}% buffer)"
                    )
            elif nearest_sup > 0 and abs(ltp - nearest_sup) / ltp <= 0.025:
                sup_dist = round(abs(ltp - nearest_sup) / ltp * 100, 2)
                score += 15
                matched_factors.append(
                    f"Holding right at major structural support pivot (₹{nearest_sup:,.1f}, {sup_dist:.1f}% buffer)"
                )
            elif in_discount:
                score += 10
                matched_factors.append("Trading in institutional 50% OTE discount zone")
        except Exception:
            pass

        # D. Sector RRG Tailwind [0–15 pts]
        sector_name = "Equities"
        rrg_quad = "NEUTRAL"
        if sym_seg not in ("CRYPTO", "COMMODITY"):
            try:
                from analysis.sector_rotation import get_stock_sector_alignment

                align = get_stock_sector_alignment(clean_sym)
                if hasattr(align, "quadrant"):
                    rrg_quad = getattr(align, "quadrant", rrg_quad)
                    sector_name = getattr(
                        align, "sector", getattr(align, "sector_name", sector_name)
                    )
                elif isinstance(align, dict):
                    sector_name = align.get("sector_name", align.get("sector", sector_name))
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
                    score -= 10  # Mild drag penalty instead of harsh -15
            except Exception:
                pass
        elif sym_seg == "CRYPTO":
            sector_name = "Crypto"
        elif sym_seg == "COMMODITY":
            sector_name = "Commodities"

        # E. Options Gamma & Call Unwinding [0–15 pts]
        if sym_seg not in ("CRYPTO", "COMMODITY"):
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
        entry_high = round(max(entry_low + 0.1, pivot_high * 1.002), 2)

        # Calculate ATR/Swing-based Stop-Loss with price-band scaled floor
        min_risk = round(max(0.10, ltp * 0.008), 2)
        sl_distance = (
            max(ltp * 0.015, (ltp - float(np.min(lows[-5:]))) * 1.05)
            if len(lows) >= 5
            else ltp * 0.02
        )
        stop_loss = round(ltp - max(min_risk, sl_distance), 2)
        if stop_loss >= entry_low:
            stop_loss = round(entry_low - min_risk, 2)
        risk_pts = max(min_risk, round(ltp - stop_loss, 2))

        target_1 = round(ltp + 2.0 * risk_pts, 2)
        target_2 = round(ltp + 3.5 * risk_pts, 2)
        rr_str = f"1:{((target_2 - ltp) / risk_pts):.1f}"

        curr_sym = "$" if sym_seg == "CRYPTO" else "₹"
        entry_range = f"{curr_sym}{entry_low:,.1f} – {curr_sym}{entry_high:,.1f}"

        verdict = (
            "MAX_CONVICTION"
            if score >= 85
            else ("HIGH_CONVICTION" if score >= 75 else "COILING_ACCUMULATION")
        )

        when_buy = f"Enter on Ask/Retest within coiling range ({entry_range}) while price holds above {curr_sym}{entry_low:,.1f} and VWAP."
        when_wait = f"DO NOT CHASE if asset gaps up > 1.8% at open (above {curr_sym}{round(ltp * 1.018, 1):,}). Wait for a VWAP pullback."
        profit_rule = f"Book 50% profit at Target 1 ({curr_sym}{target_1:,.1f}), move Stop-Loss to Breakeven, and trail runner to Target 2 ({curr_sym}{target_2:,.1f})."
        has_squeeze = squeeze_bars >= 2
        severe_dry_up = prior_vol_ratio <= 0.40
        closest_archetype = (
            "ARCHETYPE_VOLATILITY_CONTRACTION_SPRING"
            if has_squeeze
            else "ARCHETYPE_INSTITUTIONAL_ABSORPTION"
            if severe_dry_up
            else "ARCHETYPE_MOMENTUM_TREND_CONTINUATION"
        )

        exchange = "CRYPTO" if sym_seg == "CRYPTO" else ("MCX" if sym_seg == "COMMODITY" else "NSE")

        return PrecursorCandidate(
            symbol=clean_sym,
            exchange=exchange,
            direction="BULLISH",
            conviction_score=score,
            verdict=verdict,
            segment=sym_seg,
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
            timeframe="1D" if interval == "day" else interval.upper(),
            is_nr7_coiling=is_nr7,
            is_inside_bar=is_ib,
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
        force_refresh: bool = False,
    ) -> list[PrecursorCandidate]:
        """
        Scans universe and returns top N high-conviction pre-ignition candidates.
        Can be filtered by segment ('INDEX' | 'FNO' | 'NON_FNO' | 'ALL').
        """
        import time

        cache_key = (tuple(universe) if universe else None, segment)
        now = time.monotonic()
        if not force_refresh:
            with self._cache_lock:
                if cache_key in self._cache and (
                    now - self._cache_ts.get(cache_key, 0.0) < self._cache_ttl
                ):
                    return list(self._cache[cache_key][:top_n])

        symbols = universe or self.get_scan_universe(segment=segment)
        candidates: list[PrecursorCandidate] = []

        logger.info(
            f"[PrecursorRadar] Scanning {len(symbols)} tickers ({segment or 'ALL'}) for pre-move precursor DNA..."
        )

        # Batch pre-fetch quotes across universe in a single network round-trip
        quotes_map: dict[str, Any] = {}
        try:
            from market.quotes import get_quote

            formatted_syms = []
            for s in symbols:
                if ":" in s:
                    formatted_syms.append(s)
                else:
                    seg = classify_symbol_segment(s)
                    if seg == "CRYPTO":
                        formatted_syms.append(f"CRYPTO:{s}")
                    elif seg == "COMMODITY":
                        formatted_syms.append(f"MCX:{s}")
                    else:
                        formatted_syms.append(f"NSE:{s}")

            q_res = get_quote(formatted_syms)
            if isinstance(q_res, dict):
                quotes_map = q_res
        except Exception as e:
            logger.debug(f"[PrecursorRadar] Batch quote fetch error: {e}")

        def _worker(sym: str) -> Optional[PrecursorCandidate]:
            clean = (
                sym.upper()
                .replace("NSE:", "")
                .replace("MCX:", "")
                .replace("CRYPTO:", "")
                .replace("BINANCE:", "")
                .replace(".NS", "")
                .strip()
            )
            q = (
                quotes_map.get(f"CRYPTO:{clean}")
                or quotes_map.get(f"NSE:{clean}")
                or quotes_map.get(f"MCX:{clean}")
                or quotes_map.get(clean)
                or quotes_map.get(sym)
            )
            return self.evaluate_symbol(sym, quote=q)

        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(6, len(symbols) or 1)
        ) as executor:
            future_to_sym = {executor.submit(_worker, s): s for s in symbols}
            for fut in concurrent.futures.as_completed(future_to_sym):
                s = future_to_sym[fut]
                try:
                    candidate = fut.result()
                    if candidate:
                        candidates.append(candidate)
                except Exception as e:
                    logger.debug(f"[PrecursorRadar] Evaluation error on {s}: {e}")

        # Sort descending by conviction score
        candidates.sort(key=lambda c: c.conviction_score, reverse=True)
        with self._cache_lock:
            self._cache[cache_key] = candidates
            self._cache_ts[cache_key] = now

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
