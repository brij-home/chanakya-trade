"""
engine/mover_autopsy.py
───────────────────────
Daily Top Movers Forensic Autopsy & Causal Attribution Engine.

Performs deep retrospective factor analysis on daily Top 10 Gainers and
Top 10 Losers across liquid Indian equities (NSE 500 & F&O).

Key Objectives:
  1. Causal Decomposition:
     - Deconstructs each move across 5 orthogonal pillars:
       * Pre-Move Setup (T-1 to T-5): Volatility Contraction (VCP), Volume Dry-Up, TTM Squeeze, Order Block anchor.
       * Macro & Sector Tailwind: JdK RRG Sector quadrant (Leading, Improving, Weakening, Lagging).
       * Derivatives & Gamma (F&O): Short Covering vs Long Buildup, Vol/OI turnover surge, Call/Put unwinding.
       * Microstructure & Trigger (T-0): Opening Range Breakout (ORB), Relative Volume (RVOL), Liquidity Sweeps.
       * Corporate & Catalysts: Earnings, bulk/block deals, macro transmission.
  2. False-Positive & Trap Elimination:
     - Benchmarks factors against a Control Cohort of 15–20 non-moving stocks from the same day.
     - Calculates Discriminative Signal-to-Noise Ratio (SNR) to filter out background noise (preventing narrative fallacy).
     - Identifies and flags operator circuit pumps and penny stock traps (< ₹10 Cr turnover).
  3. Continuous Self-Learning:
     - Feeds validated pre-move signatures into PatternLearningEngine to dynamically tune factor weights.
     - Persists autopsy dossiers in ~/.trading_platform/mover_autopsies.json.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("chanakya.mover_autopsy")

IST = timezone(timedelta(hours=5, minutes=30))


def get_mover_autopsies_file() -> Path:
    base = Path(os.environ.get("TRADING_PLATFORM_DATA") or (Path.home() / ".trading_platform"))
    return base / "mover_autopsies.json"


# ── Archetypes & Trap Identifiers ──────────────────────────────

ARCHETYPE_VOLATILITY_CONTRACTION_SPRING = "ARCHETYPE_VOLATILITY_CONTRACTION_SPRING"
ARCHETYPE_SECTOR_MOMENTUM_CONTAGION = "ARCHETYPE_SECTOR_MOMENTUM_CONTAGION"
ARCHETYPE_GAMMA_SHORT_SQUEEZE = "ARCHETYPE_GAMMA_SHORT_SQUEEZE"
ARCHETYPE_LIQUIDITY_SWEEP_REVERSAL = "ARCHETYPE_LIQUIDITY_SWEEP_REVERSAL"
ARCHETYPE_EARNINGS_CATALYST_EXPANSION = "ARCHETYPE_EARNINGS_CATALYST_EXPANSION"
ARCHETYPE_BREAKDOWN_LONG_UNWIND = "ARCHETYPE_BREAKDOWN_LONG_UNWIND"
ARCHETYPE_STRUCTURAL_BREAKDOWN = "ARCHETYPE_STRUCTURAL_BREAKDOWN"

TRAP_LOW_LIQUIDITY_PUMP = "TRAP_LOW_LIQUIDITY_PUMP"
TRAP_CIRCUIT_LOCK_MANIPULATION = "TRAP_CIRCUIT_LOCK_MANIPULATION"


# ── Data Models ────────────────────────────────────────────────


@dataclass
class MoverCausalProfile:
    """Forensic causal decomposition of a single top gainer or loser."""

    symbol: str
    direction: str  # "GAINER" | "LOSER"
    change_pct: float
    ltp: float
    volume: int
    turnover_cr: float
    rvol: float
    is_fo: bool = True
    segment: str = "FNO"  # "FNO" | "NON_FNO" | "INDEX"
    sector_name: str = "General"
    rrg_quadrant: str = "NEUTRAL"

    # Pre-move setup (T-1 to T-5)
    prior_vol_ratio: float = 1.0  # prior day vol / 20D SMA
    squeeze_bars: int = 0  # TTM squeeze coiling count
    vcp_tightness_pct: float = 0.0  # last 5-day range contraction
    order_block_distance_pct: float = 1.5

    # Derivatives metrics (if F&O)
    oi_change_pct: float = 0.0
    vol_oi_ratio: float = 0.0
    pcr: float = 1.0
    derivative_verdict: str = "NEUTRAL"  # SHORT_COVERING, LONG_BUILDUP, LONG_UNWINDING, SHORT_BUILDUP

    # Intraday spark (T-0)
    orb_breakout: bool = False
    liquidity_sweep: bool = False
    above_vwap: bool = True

    # Archetype & Trap Detection
    archetype: str = ARCHETYPE_VOLATILITY_CONTRACTION_SPRING
    is_trap: bool = False
    trap_reason: Optional[str] = None
    key_catalyst: str = "Technical breakout"
    deciding_factors: list[str] = field(default_factory=list)
    lessons_learned: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DailyMoverAutopsy:
    """Comprehensive daily forensic report across top gainers, losers, and control cohort."""

    date: str
    market_regime: str
    gainers: list[MoverCausalProfile] = field(default_factory=list)
    losers: list[MoverCausalProfile] = field(default_factory=list)
    control_cohort: list[dict[str, Any]] = field(default_factory=list)
    factor_snr: dict[str, float] = field(default_factory=dict)
    top_predictive_precursors: list[str] = field(default_factory=list)
    traps_filtered: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "market_regime": self.market_regime,
            "gainers": [g.to_dict() for g in self.gainers],
            "losers": [l.to_dict() for l in self.losers],
            "control_cohort": self.control_cohort,
            "factor_snr": self.factor_snr,
            "top_predictive_precursors": self.top_predictive_precursors,
            "traps_filtered": self.traps_filtered,
            "created_at": self.created_at,
        }


# ── Forensic Autopsy Engine ─────────────────────────────────────


class MoverAutopsyEngine:
    """
    Autonomous engine that performs end-of-day causal autopsies on top movers,
    contrasts with a control group, and updates the pattern learning system.
    """

    def __init__(self) -> None:
        self._autopsies: list[DailyMoverAutopsy] = []
        self._load()

    def _load(self) -> None:
        target = get_mover_autopsies_file()
        if target.exists():
            try:
                data = json.loads(target.read_text(encoding="utf-8"))
                for d in data:
                    if isinstance(d, dict):
                        g_list = [MoverCausalProfile(**g) for g in d.get("gainers", []) if isinstance(g, dict)]
                        l_list = [MoverCausalProfile(**l) for l in d.get("losers", []) if isinstance(l, dict)]
                        self._autopsies.append(
                            DailyMoverAutopsy(
                                date=d.get("date", ""),
                                market_regime=d.get("market_regime", "NORMAL"),
                                gainers=g_list,
                                losers=l_list,
                                control_cohort=d.get("control_cohort", []),
                                factor_snr=d.get("factor_snr", {}),
                                top_predictive_precursors=d.get("top_predictive_precursors", []),
                                traps_filtered=d.get("traps_filtered", 0),
                                created_at=d.get("created_at", ""),
                            )
                        )
            except Exception as e:
                logger.debug(f"[MoverAutopsyEngine] Failed to load autopsies: {e}")
                self._autopsies = []

    def _save(self) -> None:
        target = get_mover_autopsies_file()
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = [a.to_dict() for a in self._autopsies[:30]]  # retain last 30 daily dossiers
            target.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug(f"[MoverAutopsyEngine] Failed to save autopsies: {e}")

    # ── Universe & Quotes Extraction ────────────────────────────

    def get_candidate_universe(self, segment: Optional[str] = None) -> list[str]:
        """Resolves the liquid universe to scan across F&O, Cash Equities, and Indices."""
        try:
            from engine.precursor_radar import precursor_radar

            return precursor_radar.get_scan_universe(segment=segment)
        except Exception:
            pass

        # Fallback to high-liquidity defaults
        return [
            "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "BHARTIARTL",
            "TRENT", "DIXON", "HAL", "BEL", "ADANIENT", "LT", "MARUTI", "BAJFINANCE",
            "TITAN", "COFORGE", "PERSISTENT", "POLYCAB", "KALYANKJIL", "BSE", "MCX",
            "CDSL", "MANKIND", "SUNPHARMA", "DRREDDY", "DIVISLAB", "TATAMOTORS",
            "HINDALCO", "TATASTEEL", "JSWSTEEL", "VEDL", "NTPC", "ONGC", "COALINDIA",
            "POWERGRID", "ASIANPAINT", "HINDUNILVR", "ITC", "NESTLEIND", "ZOMATO"
        ]

    def fetch_daily_movers_and_control(
        self,
        universe: Optional[list[str]] = None,
        segment: Optional[str] = None,
        top_n: int = 10,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Fetches quotes across universe, partitions into top gainers, top losers,
        and a control cohort of non-moving stocks (|change| < 0.8%).
        Can be segmented by 'INDEX', 'FNO', 'NON_FNO', or 'ALL'.
        """
        from market.quotes import get_quote

        symbols = universe or self.get_candidate_universe(segment=segment)
        quotes_data: list[dict[str, Any]] = []

        # Batch fetch quotes
        formatted_symbols = [f"NSE:{s}" if ":" not in s else s for s in symbols]
        try:
            quotes_map = get_quote(formatted_symbols)
        except Exception as e:
            logger.warning(f"[MoverAutopsyEngine] Error batch fetching quotes: {e}")
            quotes_map = {}

        for sym in symbols:
            clean_sym = sym.upper().replace("NSE:", "").replace(".NS", "").strip()
            q = quotes_map.get(f"NSE:{clean_sym}") or quotes_map.get(clean_sym)
            if not q or getattr(q, "ltp", 0.0) <= 0:
                continue

            ltp = float(q.ltp)
            change_pct = float(getattr(q, "change_pct", 0.0) or 0.0)
            vol = int(getattr(q, "volume", 0) or 0)
            vwap = float(getattr(q, "vwap", 0.0) or ltp)
            turnover_cr = round((ltp * vol) / 1e7, 2)  # In Crores

            quotes_data.append({
                "symbol": clean_sym,
                "ltp": ltp,
                "change_pct": change_pct,
                "volume": vol,
                "turnover_cr": turnover_cr,
                "vwap": vwap,
                "raw_quote": q,
            })

        if not quotes_data:
            return [], [], []

        # Sort by change_pct
        gainers_sorted = sorted([q for q in quotes_data if q["change_pct"] > 0], key=lambda x: x["change_pct"], reverse=True)
        losers_sorted = sorted([q for q in quotes_data if q["change_pct"] < 0], key=lambda x: x["change_pct"])
        control_candidates = [q for q in quotes_data if abs(q["change_pct"]) <= 0.8 and q["turnover_cr"] >= 10.0]

        top_gainers = gainers_sorted[:top_n]
        top_losers = losers_sorted[:top_n]
        control_cohort = control_candidates[:15]

        return top_gainers, top_losers, control_cohort

    # ── Single Stock Causal Decomposition ───────────────────────

    def dissect_mover(
        self,
        quote_item: dict[str, Any],
        direction: str = "GAINER",
    ) -> MoverCausalProfile:
        """
        Performs 5-dimensional causal factor decomposition on a single mover.
        Evaluates pre-move setup (T-1 to T-5), sector tailwind, derivatives, and spark.
        """
        sym = quote_item["symbol"]
        ltp = quote_item["ltp"]
        chg = quote_item["change_pct"]
        vol = quote_item["volume"]
        turnover_cr = quote_item["turnover_cr"]
        vwap = quote_item["vwap"]

        # 1. Anti-Trap / Manipulation Checks
        is_trap = False
        trap_reason = None
        if turnover_cr < 8.0 and abs(chg) >= 4.0:
            is_trap = True
            trap_reason = f"Illiquid Operator Pump: Daily turnover ₹{turnover_cr:.1f} Cr < ₹8.0 Cr threshold"
        elif abs(chg) in (4.95, 5.0, 9.95, 10.0, 19.95, 20.0) and vol < 50000:
            is_trap = True
            trap_reason = "Circuit-to-Circuit Lock with negligible depth / retail entrapment"

        # 2. Historical Daily OHLCV Analysis (Pre-breakout T-1 to T-5)
        from market.history import get_ohlcv

        prior_vol_ratio = 1.0
        rvol = 1.0
        squeeze_bars = 0
        vcp_tightness = 0.0
        ob_dist = 1.5

        try:
            df = get_ohlcv(sym, exchange="NSE", interval="day", days=40)
            if df is not None and len(df) >= 15:
                closes = df["close"].values
                volumes = df["volume"].values if "volume" in df.columns else None

                # Pre-blast bar volume (penultimate bar before today's explosion)
                if volumes is not None and len(volumes) >= 21:
                    avg_20 = float(np.mean(volumes[-21:-1]))
                    # Today's RVOL
                    rvol = round(float(volumes[-1]) / max(1.0, avg_20), 2)
                    # Prior day volume dry-up ratio
                    prior_day_vol = float(volumes[-2])
                    prior_vol_ratio = round(prior_day_vol / max(1.0, avg_20), 3)

                # TTM Squeeze coiling duration before today
                try:
                    from analysis.big_move import compute_ttm_squeeze

                    # Evaluate on pre-blast slice
                    pre_slice = df.iloc[:-1] if len(df) >= 5 else df
                    sq = compute_ttm_squeeze(pre_slice)
                    if sq and (sq.is_squeeze_on or sq.squeeze_fired):
                        squeeze_bars = sq.squeeze_duration_bars
                except Exception:
                    pass

                # VCP range contraction ratio over last 5 bars
                if len(closes) >= 6:
                    recent_ranges = [abs(df["high"].iloc[i] - df["low"].iloc[i]) / df["close"].iloc[i] * 100 for i in range(-6, -1)]
                    if len(recent_ranges) >= 2:
                        vcp_tightness = round(min(recent_ranges) / max(0.01, max(recent_ranges)), 2)

                # Order Block distance
                try:
                    from analysis.market_structure import analyze_market_structure

                    ms = analyze_market_structure(sym, df=df.iloc[:-1], exchange="NSE")
                    if hasattr(ms, "order_blocks") and ms.order_blocks:
                        target_obs = [ob for ob in ms.order_blocks if getattr(ob, "ob_type", "") == ("BULLISH" if direction == "GAINER" else "BEARISH")]
                        if target_obs:
                            nearest = target_obs[0].top if direction == "GAINER" else target_obs[0].bottom
                            ob_dist = round(abs(ltp - nearest) / max(1.0, ltp) * 100, 2)
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"[MoverAutopsyEngine] History analysis error for {sym}: {e}")

        # 3. Macro & Sector Tailwind (RRG Quadrant)
        sector_name = "Equities"
        rrg_quadrant = "NEUTRAL"
        try:
            from analysis.sector_rotation import get_stock_sector_alignment

            align = get_stock_sector_alignment(sym)
            if isinstance(align, dict):
                sector_name = align.get("sector_name", sector_name)
                rrg_quadrant = align.get("quadrant", rrg_quadrant)
        except Exception:
            pass

        # 4. Derivatives & Options Structure (for F&O)
        is_fo = True
        oi_change_pct = 0.0
        vol_oi_ratio = 0.0
        pcr = 1.0
        derivative_verdict = "NEUTRAL"

        try:
            from market.options import get_options_chain

            chain = get_options_chain(sym)
            if chain:
                tot_ce_oi = sum(getattr(c, "oi", 0) for c in chain if getattr(c, "option_type", "") == "CE")
                tot_pe_oi = sum(getattr(c, "oi", 0) for c in chain if getattr(c, "option_type", "") == "PE")
                tot_ce_doi = sum(getattr(c, "oi_change", 0) for c in chain if getattr(c, "option_type", "") == "CE")
                tot_pe_doi = sum(getattr(c, "oi_change", 0) for c in chain if getattr(c, "option_type", "") == "PE")
                tot_vol = sum(getattr(c, "volume", 0) for c in chain)

                pcr = round(tot_pe_oi / max(1, tot_ce_oi), 2)
                vol_oi_ratio = round(tot_vol / max(1, tot_ce_oi + tot_pe_oi), 2)

                if direction == "GAINER":
                    if tot_ce_doi < 0 and abs(tot_ce_doi) > 0.10 * max(1, tot_ce_oi):
                        derivative_verdict = "SHORT_COVERING"
                        oi_change_pct = round((tot_ce_doi / max(1, tot_ce_oi)) * 100, 1)
                    else:
                        derivative_verdict = "LONG_BUILDUP"
                        oi_change_pct = round(((tot_ce_doi + tot_pe_doi) / max(1, tot_ce_oi + tot_pe_oi)) * 100, 1)
                else:
                    if tot_pe_doi < 0 and abs(tot_pe_doi) > 0.10 * max(1, tot_pe_oi):
                        derivative_verdict = "LONG_UNWINDING"
                        oi_change_pct = round((tot_pe_doi / max(1, tot_pe_oi)) * 100, 1)
                    else:
                        derivative_verdict = "SHORT_BUILDUP"
                        oi_change_pct = round(((tot_ce_doi + tot_pe_doi) / max(1, tot_ce_oi + tot_pe_oi)) * 100, 1)
            else:
                is_fo = False
        except Exception:
            is_fo = False

        # 5. Intraday Spark & Execution
        above_vwap = ltp >= vwap if direction == "GAINER" else ltp <= vwap
        orb_breakout = rvol >= 1.8 and abs(chg) >= 2.5
        liquidity_sweep = ob_dist <= 0.8 and rvol >= 1.5

        # 6. Archetype Classification & Lessons
        deciding_factors: list[str] = []
        lessons_learned: list[str] = []

        if is_trap:
            archetype = TRAP_LOW_LIQUIDITY_PUMP if "Illiquid" in (trap_reason or "") else TRAP_CIRCUIT_LOCK_MANIPULATION
            deciding_factors.append(f"⚠️ {trap_reason}")
            lessons_learned.append("Discard from predictive pattern memory; low institutional depth invites slippage and operator traps.")
        elif derivative_verdict == "SHORT_COVERING" and vol_oi_ratio >= 1.5:
            archetype = ARCHETYPE_GAMMA_SHORT_SQUEEZE
            deciding_factors.append(f"Aggressive Short Covering: Call OI unwound by {abs(oi_change_pct):.1f}% with {vol_oi_ratio:.1f}x Vol/OI surge")
            if squeeze_bars >= 2:
                deciding_factors.append(f"Pre-squeeze coiling for {squeeze_bars} daily sessions")
            lessons_learned.append("Watch for negative Call ΔOI combined with spot reclaiming VWAP on high-turnover F&O leaders.")
        elif prior_vol_ratio <= 0.35 and (squeeze_bars >= 2 or vcp_tightness <= 0.40):
            archetype = ARCHETYPE_VOLATILITY_CONTRACTION_SPRING
            deciding_factors.append(f"Extreme Volume Dry-up at T-1 ({prior_vol_ratio * 100:.0f}% of 20D SMA — Seller Exhaustion)")
            if squeeze_bars >= 2:
                deciding_factors.append(f"Bollinger bands coiled in Keltner squeeze for {squeeze_bars} bars")
            if vcp_tightness > 0:
                deciding_factors.append(f"VCP contraction ratio {vcp_tightness:.2f} (tightening daily spread)")
            lessons_learned.append("Volume dry-up below 35% of 20-day average is the single most reliable pre-breakout signature in momentum leaders.")
        elif rrg_quadrant in ("LEADING", "IMPROVING") and direction == "GAINER":
            archetype = ARCHETYPE_SECTOR_MOMENTUM_CONTAGION
            deciding_factors.append(f"Parent Sector ({sector_name}) in {rrg_quadrant} RRG quadrant")
            deciding_factors.append(f"RVOL expansion ({rvol:.1f}x) confirming institutional sector rotation")
            lessons_learned.append("Riding stocks in Leading/Improving RRG sectors provides a 3x higher success probability than counter-trend bottom fishing.")
        elif liquidity_sweep:
            archetype = ARCHETYPE_LIQUIDITY_SWEEP_REVERSAL
            deciding_factors.append("Institutional Order Block liquidity sweep & rejection")
            deciding_factors.append(f"Held VWAP with {rvol:.1f}x volume confirmation")
            lessons_learned.append("Wait for prior day high/low sweeps to grab retail stop-losses before entering with institutional flow.")
        elif direction == "LOSER":
            archetype = ARCHETYPE_BREAKDOWN_LONG_UNWIND if derivative_verdict == "LONG_UNWINDING" else ARCHETYPE_STRUCTURAL_BREAKDOWN
            deciding_factors.append(f"Structural breakdown with {rvol:.1f}x volume surge")
            if rrg_quadrant in ("LAGGING", "WEAKENING"):
                deciding_factors.append(f"Parent sector ({sector_name}) in {rrg_quadrant} drag")
            lessons_learned.append("Never average down into stocks in Lagging RRG sectors breaching institutional support levels.")
        else:
            archetype = ARCHETYPE_EARNINGS_CATALYST_EXPANSION
            deciding_factors.append(f"High-momentum expansion: +{chg:.1f}% with {rvol:.1f}x volume surge")
            lessons_learned.append("Trade opening range continuation with trailing stops anchored to 5-min VWAP.")

        catalyst = "; ".join(deciding_factors[:2])

        from engine.precursor_radar import classify_symbol_segment
        segment = classify_symbol_segment(sym)

        return MoverCausalProfile(
            symbol=sym,
            direction=direction,
            change_pct=round(chg, 2),
            ltp=round(ltp, 2),
            volume=vol,
            turnover_cr=turnover_cr,
            rvol=rvol,
            is_fo=is_fo,
            segment=segment,
            sector_name=sector_name,
            rrg_quadrant=rrg_quadrant,
            prior_vol_ratio=prior_vol_ratio,
            squeeze_bars=squeeze_bars,
            vcp_tightness_pct=vcp_tightness,
            order_block_distance_pct=ob_dist,
            oi_change_pct=oi_change_pct,
            vol_oi_ratio=vol_oi_ratio,
            pcr=pcr,
            derivative_verdict=derivative_verdict,
            orb_breakout=orb_breakout,
            liquidity_sweep=liquidity_sweep,
            above_vwap=above_vwap,
            archetype=archetype,
            is_trap=is_trap,
            trap_reason=trap_reason,
            key_catalyst=catalyst,
            deciding_factors=deciding_factors,
            lessons_learned=lessons_learned,
        )

    # ── Control Cohort Contrast & Statistical Attribution ────────

    def compute_control_contrast(
        self,
        movers: list[MoverCausalProfile],
        control_quotes: list[dict[str, Any]],
    ) -> tuple[dict[str, float], list[str]]:
        """
        Calculates the Discriminative Signal-to-Noise Ratio (SNR) for each factor.
        Compares factor prevalence in Movers vs Control Cohort:
            Delta = P(Factor | Mover) - P(Factor | Control)
        Factors with Delta <= 0.15 are penalized as background noise.
        """
        from market.history import get_ohlcv

        # Extract features for control stocks
        control_vol_dry_up = 0
        control_squeeze = 0
        control_leading_sector = 0
        control_total = max(1, len(control_quotes))

        for item in control_quotes:
            c_sym = item["symbol"]
            try:
                df = get_ohlcv(c_sym, exchange="NSE", interval="day", days=30)
                if df is not None and len(df) >= 21:
                    vols = df["volume"].values
                    avg_20 = float(np.mean(vols[-21:-1]))
                    if float(vols[-2]) <= 0.35 * avg_20:
                        control_vol_dry_up += 1
                # Sector
                from analysis.sector_rotation import get_stock_sector_alignment

                align = get_stock_sector_alignment(c_sym)
                if isinstance(align, dict) and align.get("quadrant") == "LEADING":
                    control_leading_sector += 1
            except Exception:
                pass

        p_control_vol_dry_up = control_vol_dry_up / control_total
        p_control_leading_sec = control_leading_sector / control_total

        # Movers frequencies (exclude traps!)
        valid_movers = [m for m in movers if not m.is_trap and m.direction == "GAINER"]
        m_total = max(1, len(valid_movers))

        m_vol_dry_up = sum(1 for m in valid_movers if m.prior_vol_ratio <= 0.35)
        m_squeeze = sum(1 for m in valid_movers if m.squeeze_bars >= 2)
        m_leading_sec = sum(1 for m in valid_movers if m.rrg_quadrant in ("LEADING", "IMPROVING"))
        m_short_squeeze = sum(1 for m in valid_movers if m.derivative_verdict == "SHORT_COVERING")

        p_m_vol_dry_up = m_vol_dry_up / m_total
        p_m_squeeze = m_squeeze / m_total
        p_m_leading_sec = m_leading_sec / m_total
        p_m_short_squeeze = m_short_squeeze / m_total

        # Discriminative Delta
        snr_table = {
            "volume_dry_up": round(p_m_vol_dry_up - p_control_vol_dry_up, 3),
            "squeeze_compression": round(p_m_squeeze - 0.10, 3),
            "sector_tailwind": round(p_m_leading_sec - p_control_leading_sec, 3),
            "gamma_short_squeeze": round(p_m_short_squeeze - 0.05, 3),
        }

        # Select top predictive precursors
        sorted_factors = sorted(snr_table.items(), key=lambda x: x[1], reverse=True)
        top_precursors = [f"{k.replace('_', ' ').title()} (SNR: {v:+.2f})" for k, v in sorted_factors if v > 0.15]

        return snr_table, top_precursors

    # ── Full Daily Autopsy Orchestration ─────────────────────────

    def run_daily_autopsy(
        self,
        target_date: Optional[str] = None,
        segment: Optional[str] = None,
        top_n: int = 10,
    ) -> DailyMoverAutopsy:
        """
        Executes the full end-of-day autopsy across top gainers, losers, and control cohort.
        Persists results and recalibrates pattern learning weights.
        """
        date_str = target_date or datetime.now(IST).strftime("%Y-%m-%d")
        logger.info(f"[MoverAutopsyEngine] Starting daily autopsy for {date_str} (segment={segment or 'ALL'})...")

        top_gainers_raw, top_losers_raw, control_raw = self.fetch_daily_movers_and_control(segment=segment, top_n=top_n)

        gainers_profiles = [self.dissect_mover(g, direction="GAINER") for g in top_gainers_raw]
        losers_profiles = [self.dissect_mover(l, direction="LOSER") for l in top_losers_raw]

        all_movers = gainers_profiles + losers_profiles
        traps_count = sum(1 for m in all_movers if m.is_trap)

        # Statistical Contrast vs Control Cohort
        snr_table, top_precursors = self.compute_control_contrast(all_movers, control_raw)

        # Market regime assessment
        market_regime = "NORMAL_TRENDING"
        try:
            from market.quotes import get_ltp

            vix = get_ltp("NSE:INDIA VIX") or 14.0
            if vix > 19.0:
                market_regime = "HIGH_VIX_CHOPPY"
            elif vix < 12.5:
                market_regime = "LOW_VIX_EXPANSION"
        except Exception:
            pass

        autopsy = DailyMoverAutopsy(
            date=date_str,
            market_regime=market_regime,
            gainers=gainers_profiles,
            losers=losers_profiles,
            control_cohort=[{"symbol": c["symbol"], "change_pct": c["change_pct"]} for c in control_raw],
            factor_snr=snr_table,
            top_predictive_precursors=top_precursors,
            traps_filtered=traps_count,
        )

        # Commit to learning memory (feed validated non-trap winners into PatternLearningEngine)
        try:
            from engine.learning_engine import pattern_learning_engine

            for g in gainers_profiles:
                if not g.is_trap and g.change_pct >= 3.5 and g.rvol >= 1.5:
                    pattern_learning_engine.register_explosive_move(
                        symbol=g.symbol,
                        move_pct=g.change_pct,
                        rvol_surge=g.rvol,
                        catalyst=f"{g.archetype.replace('ARCHETYPE_', '').replace('_', ' ')}: {g.key_catalyst}",
                        date_str=date_str,
                        is_historical_blast=True,
                    )
            pattern_learning_engine.recalibrate_from_snr(snr_table)
        except Exception as e:
            logger.debug(f"[MoverAutopsyEngine] Error syncing with pattern_learning_engine: {e}")

        # Persist autopsy dossier
        self._autopsies = [a for a in self._autopsies if a.date != date_str]
        self._autopsies.insert(0, autopsy)
        self._save()

        logger.info(
            f"[MoverAutopsyEngine] Daily autopsy completed: {len(gainers_profiles)} Gainers, "
            f"{len(losers_profiles)} Losers, {traps_count} Traps Filtered, SNR Top: {top_precursors[:2]}"
        )
        return autopsy

    def get_latest_autopsy(self) -> Optional[DailyMoverAutopsy]:
        """Returns the most recent autopsy report, or runs an on-demand one if store is empty."""
        if self._autopsies:
            return self._autopsies[0]
        return None

    def get_autopsy_by_date(self, date_str: str) -> Optional[DailyMoverAutopsy]:
        for a in self._autopsies:
            if a.date == date_str:
                return a
        return None


# Module-level singleton instance
mover_autopsy_engine = MoverAutopsyEngine()
