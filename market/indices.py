"""
market/indices.py
─────────────────
Indian market indices snapshot — NIFTY 50, BANKNIFTY, India VIX,
SENSEX, sector indices, and a market posture helper.
"""

from __future__ import annotations
import logging

logger = logging.getLogger("market.indices")


from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from config.constants import IST
from market.instruments import canonical_symbol


# ── Key instruments ──────────────────────────────────────────

INDEX_INSTRUMENTS = {
    # Benchmark & Broad Market
    "NIFTY50": "NSE:NIFTY 50",
    "NIFTY 50": "NSE:NIFTY 50",
    "NIFTY": "NSE:NIFTY 50",
    "BANK": "NSE:NIFTY BANK",
    "BANKNIFTY": "NSE:NIFTY BANK",
    "NIFTY BANK": "NSE:NIFTY BANK",
    "VIX": "NSE:INDIA VIX",
    "INDIAVIX": "NSE:INDIA VIX",
    "INDIA VIX": "NSE:INDIA VIX",
    "SENSEX": "BSE:SENSEX",
    "BSE SENSEX": "BSE:SENSEX",
    "BANKEX": "BSE:BANKEX",
    "FINNIFTY": "NSE:NIFTY FIN SERVICE",
    "NIFTY FIN SERVICE": "NSE:NIFTY FIN SERVICE",
    "NIFTY FINANCIAL SERVICES": "NSE:NIFTY FIN SERVICE",
    "MIDCAP": "NSE:NIFTY MIDCAP 100",
    "MIDCPNIFTY": "NSE:NIFTY MID SELECT",
    "NIFTY MIDCAP 100": "NSE:NIFTY MIDCAP 100",
    "NEXT50": "NSE:NIFTY NEXT 50",
    "NIFTYNXT50": "NSE:NIFTY NEXT 50",
    "NIFTY NEXT 50": "NSE:NIFTY NEXT 50",
    "NIFTY 100": "NSE:NIFTY 100",
    "NIFTY100": "NSE:NIFTY 100",
    "NIFTY 200": "NSE:NIFTY 200",
    "NIFTY200": "NSE:NIFTY 200",
    "NIFTY 500": "NSE:NIFTY 500",
    "NIFTY500": "NSE:NIFTY 500",
    "NIFTY SMALLCAP 100": "NSE:NIFTY SMALLCAP 100",
    "NIFTYSMLCAP100": "NSE:NIFTY SMALLCAP 100",
    # Sectoral Indices
    "IT": "NSE:NIFTY IT",
    "NIFTYIT": "NSE:NIFTY IT",
    "NIFTY IT": "NSE:NIFTY IT",
    "PHARMA": "NSE:NIFTY PHARMA",
    "NIFTYPHARMA": "NSE:NIFTY PHARMA",
    "NIFTY PHARMA": "NSE:NIFTY PHARMA",
    "AUTO": "NSE:NIFTY AUTO",
    "NIFTYAUTO": "NSE:NIFTY AUTO",
    "NIFTY AUTO": "NSE:NIFTY AUTO",
    "FMCG": "NSE:NIFTY FMCG",
    "NIFTYFMCG": "NSE:NIFTY FMCG",
    "NIFTY FMCG": "NSE:NIFTY FMCG",
    "REALTY": "NSE:NIFTY REALTY",
    "NIFTYREALTY": "NSE:NIFTY REALTY",
    "NIFTY REALTY": "NSE:NIFTY REALTY",
    "METAL": "NSE:NIFTY METAL",
    "NIFTYMETAL": "NSE:NIFTY METAL",
    "NIFTY METAL": "NSE:NIFTY METAL",
    "ENERGY": "NSE:NIFTY ENERGY",
    "NIFTYENERGY": "NSE:NIFTY ENERGY",
    "NIFTY ENERGY": "NSE:NIFTY ENERGY",
    "INFRA": "NSE:NIFTY INFRA",
    "NIFTYINFRA": "NSE:NIFTY INFRA",
    "NIFTY INFRA": "NSE:NIFTY INFRA",
    "PSE": "NSE:NIFTY PSE",
    "NIFTYPSE": "NSE:NIFTY PSE",
    "NIFTY PSE": "NSE:NIFTY PSE",
    "PSU_BANK": "NSE:NIFTY PSU BANK",
    "PSUBANK": "NSE:NIFTY PSU BANK",
    "NIFTYPSU": "NSE:NIFTY PSU BANK",
    "NIFTY PSU BANK": "NSE:NIFTY PSU BANK",
    "PVTBANK": "NSE:NIFTY PVT BANK",
    "NIFTYPVTBANK": "NSE:NIFTY PVT BANK",
    "NIFTY PRIVATE BANK": "NSE:NIFTY PVT BANK",
    "OILGAS": "NSE:NIFTY OIL AND GAS",
    "NIFTYOILGAS": "NSE:NIFTY OIL AND GAS",
    "NIFTY OIL & GAS": "NSE:NIFTY OIL AND GAS",
    "CONSUMPTION": "NSE:NIFTY CONSUMPTION",
    "NIFTYCONSUMPTION": "NSE:NIFTY CONSUMPTION",
    "NIFTY INDIA CONSUMPTION": "NSE:NIFTY CONSUMPTION",
    "MEDIA": "NSE:NIFTY MEDIA",
    "NIFTYMEDIA": "NSE:NIFTY MEDIA",
    "NIFTY MEDIA": "NSE:NIFTY MEDIA",
    "HEALTHCARE": "NSE:NIFTY HEALTHCARE",
    "NIFTYHEALTHCARE": "NSE:NIFTY HEALTHCARE",
    "COMMODITIES": "NSE:NIFTY COMMODITIES",
    "NIFTYCOMMODITIES": "NSE:NIFTY COMMODITIES",
}


@dataclass
class IndexSnapshot:
    name: str
    instrument: str
    ltp: float
    change: float
    change_pct: float
    open: float
    high: float
    low: float


@dataclass
class IndexPolarization:
    index: str
    is_polarized: bool
    regime: str  # "TUG_OF_WAR_CHOP" | "UNIDIRECTIONAL_TREND" | "NORMAL_BREADTH"
    dispersion_std: float
    max_gainer: tuple[str, float]  # (symbol, change_pct)
    max_loser: tuple[str, float]  # (symbol, change_pct)
    spread_pct: float
    heavyweight_changes: dict[str, float]
    summary: str


@dataclass
class MarketSnapshot:
    nifty: IndexSnapshot
    banknifty: IndexSnapshot
    vix: IndexSnapshot
    sensex: Optional[IndexSnapshot]
    posture: str  # "BULLISH" | "BEARISH" | "NEUTRAL" | "VOLATILE"
    posture_reason: str
    gift_nifty: Optional[object] = None  # GiftNiftySnapshot | None (#106)
    polarization: Optional[IndexPolarization] = None
    finnifty: Optional[IndexSnapshot] = None
    midcpnifty: Optional[IndexSnapshot] = None


def get_index(name: str) -> IndexSnapshot:
    """
    Snapshot for a single named index.
    name: "NIFTY50" | "BANKNIFTY" | "VIX" | "SENSEX" | etc.
    """
    instrument = INDEX_INSTRUMENTS.get(name.upper())
    if not instrument:
        raise ValueError(f"Unknown index: {name}. Valid: {list(INDEX_INSTRUMENTS)}")

    from market.quotes import get_quote

    quotes = get_quote([instrument])
    q = quotes.get(instrument)
    if not q:
        return IndexSnapshot(
            name=name, instrument=instrument, ltp=0, change=0, change_pct=0, open=0, high=0, low=0
        )

    return IndexSnapshot(
        name=name,
        instrument=instrument,
        ltp=q.last_price,
        change=q.change,
        change_pct=q.change_pct,
        open=q.open,
        high=q.high,
        low=q.low,
    )


def get_market_snapshot() -> MarketSnapshot:
    """
    Full market pulse: NIFTY, BANKNIFTY, VIX, SENSEX + posture.
    Single batched quote call for efficiency.
    """
    instruments = [
        INDEX_INSTRUMENTS["NIFTY50"],
        INDEX_INSTRUMENTS["BANKNIFTY"],
        INDEX_INSTRUMENTS["VIX"],
        INDEX_INSTRUMENTS["SENSEX"],
        INDEX_INSTRUMENTS["FINNIFTY"],
        INDEX_INSTRUMENTS["MIDCPNIFTY"],
    ]
    from market.quotes import get_quote

    quotes = get_quote(instruments)

    def snap(name: str) -> IndexSnapshot:
        inst = INDEX_INSTRUMENTS[name]
        q = quotes.get(inst)
        if not q:
            return IndexSnapshot(name, inst, 0, 0, 0, 0, 0, 0)
        return IndexSnapshot(
            name=name,
            instrument=inst,
            ltp=q.last_price,
            change=q.change,
            change_pct=q.change_pct,
            open=q.open,
            high=q.high,
            low=q.low,
        )

    nifty = snap("NIFTY50")
    banknifty = snap("BANKNIFTY")
    vix = snap("VIX")
    sensex = snap("SENSEX")
    finnifty = snap("FINNIFTY")
    midcpnifty = snap("MIDCPNIFTY")

    posture, reason = _market_posture(nifty, vix)

    # GIFT NIFTY pre-market indicator (#106) — best-effort, never blocks
    gift_nifty = None
    try:
        from market.gift_nifty import get_gift_nifty

        gift_nifty = get_gift_nifty(nifty_spot=nifty.ltp if nifty.ltp else None)
    except Exception as e_suppressed:
        logger.debug(f"[market.indices] Non-fatal exception suppressed: {e_suppressed}")

    # Heavyweight Tug-of-War Polarization Detector
    polarization = None
    try:
        polarization = get_index_polarization("NIFTY")
        if polarization and polarization.is_polarized:
            reason += f" | {polarization.summary}"
            if posture in ("BULLISH", "BEARISH"):
                posture = "NEUTRAL"
    except Exception as e_suppressed:
        logger.debug(f"[market.indices] Non-fatal exception suppressed: {e_suppressed}")

    return MarketSnapshot(
        nifty=nifty,
        banknifty=banknifty,
        vix=vix,
        sensex=sensex,
        posture=posture,
        posture_reason=reason,
        gift_nifty=gift_nifty,
        polarization=polarization,
        finnifty=finnifty,
        midcpnifty=midcpnifty,
    )


NIFTY_TOP_HEAVYWEIGHTS = [
    "HDFCBANK",
    "RELIANCE",
    "ICICIBANK",
    "INFY",
    "TCS",
    "BHARTIARTL",
    "LT",
]

BANKNIFTY_TOP_HEAVYWEIGHTS = [
    "HDFCBANK",
    "ICICIBANK",
    "SBIN",
    "AXISBANK",
    "KOTAKBANK",
]


def get_index_polarization(index: str = "NIFTY") -> IndexPolarization:
    """
    Computes cross-sectional return dispersion among benchmark heavyweights.
    When top drivers are moving in opposite directions (e.g., HDFC Bank +2.5% vs TCS -3.8% and Reliance -1.4%),
    the index is trapped in a 'TUG_OF_WAR_CHOP' regime where directional breakouts whipsaw.
    """
    from market.quotes import get_quote
    import numpy as np

    idx_upper = str(index).upper()
    is_bank_index = any(k in idx_upper for k in ("BANK", "BANKNIFTY", "BANKEX"))
    symbols = BANKNIFTY_TOP_HEAVYWEIGHTS if is_bank_index else NIFTY_TOP_HEAVYWEIGHTS
    instruments = [f"NSE:{s}" for s in symbols]
    quotes = get_quote(instruments)

    changes: dict[str, float] = {}
    for s in symbols:
        q = quotes.get(f"NSE:{s}") or quotes.get(s)
        if q and getattr(q, "last_price", 0.0) > 0:
            changes[s] = float(getattr(q, "change_pct", 0.0) or 0.0)

    if len(changes) < 3:
        return IndexPolarization(
            index=index,
            is_polarized=False,
            regime="NORMAL_BREADTH",
            dispersion_std=0.0,
            max_gainer=("NONE", 0.0),
            max_loser=("NONE", 0.0),
            spread_pct=0.0,
            heavyweight_changes=changes,
            summary="Insufficient heavyweight data to determine polarization.",
        )

    vals = list(changes.values())
    dispersion_std = float(np.std(vals))
    max_gainer_sym = max(changes, key=changes.get)
    max_loser_sym = min(changes, key=changes.get)
    max_gainer = (max_gainer_sym, changes[max_gainer_sym])
    max_loser = (max_loser_sym, changes[max_loser_sym])
    spread_pct = round(max_gainer[1] - max_loser[1], 2)

    # Bank Nifty: HDFCBANK (~29%) and ICICIBANK (~23%) together control >52% of index.
    # If they are pulling in opposite directions with magnitude >= 0.40%, index is in gridlock chop.
    hdfc_chg = changes.get("HDFCBANK", 0.0)
    icici_chg = changes.get("ICICIBANK", 0.0)
    bank_locomotive_split = is_bank_index and (
        (hdfc_chg >= 0.40 and icici_chg <= -0.40) or (hdfc_chg <= -0.40 and icici_chg >= 0.40)
    )

    # Polarized Tug-of-War threshold:
    # Spread between top gainer and top loser >= 3.0% with opposing signs (one >= +1.0%, other <= -1.0%)
    # OR dispersion standard deviation >= 1.5% with mixed signs.
    has_opposing_momentum = max_gainer[1] >= 1.0 and max_loser[1] <= -1.0
    is_polarized = bool(
        bank_locomotive_split
        or (has_opposing_momentum and (spread_pct >= 3.0 or dispersion_std >= 1.5))
    )

    if is_polarized:
        regime = "TUG_OF_WAR_CHOP"
        if bank_locomotive_split:
            summary = (
                f"⚠️ Heavyweight Tug-of-War: HDFCBANK ({hdfc_chg:+.2f}%) vs ICICIBANK ({icici_chg:+.2f}%) "
                f"in direct conflict (>52% Bank Nifty weight). Index trapped in gridlock chop."
            )
        else:
            summary = (
                f"⚠️ Heavyweight Tug-of-War: {max_gainer[0]} ({max_gainer[1]:+.2f}%) pulling UP vs. "
                f"{max_loser[0]} ({max_loser[1]:+.2f}%) dragging DOWN. Spread: {spread_pct:.2f}%. "
                f"Index trapped in range-bound chop; suppress directional breakout alerts."
            )
    elif abs(float(np.mean(vals))) > 1.0 and dispersion_std < 1.2:
        regime = "UNIDIRECTIONAL_TREND"
        summary = (
            f"✅ Broad Heavyweight Alignment: Mean change {float(np.mean(vals)):+.2f}%. "
            f"Unidirectional trend expansion supported across sector leaders."
        )
    else:
        regime = "NORMAL_BREADTH"
        summary = f"Normal heavyweight dispersion (Spread: {spread_pct:.2f}%, Std: {dispersion_std:.2f}%)."

    return IndexPolarization(
        index=index,
        is_polarized=is_polarized,
        regime=regime,
        dispersion_std=round(dispersion_std, 2),
        max_gainer=max_gainer,
        max_loser=max_loser,
        spread_pct=spread_pct,
        heavyweight_changes=changes,
        summary=summary,
    )


def _market_posture(nifty: IndexSnapshot, vix: IndexSnapshot) -> tuple[str, str]:
    """
    Simple rules-based market posture from NIFTY change + VIX level.

    VIX thresholds (India):
        < 12  : Very low — complacent, good for selling premium
        12-15 : Low — normal, balanced conditions
        15-20 : Elevated — cautious, prefer hedged strategies
        20-25 : High — fearful, avoid naked positions
        > 25  : Very high — crisis zone
    """
    vix_level = vix.ltp
    nifty_chg = nifty.change_pct

    if vix_level > 20:
        return "VOLATILE", f"VIX={vix_level:.1f} (danger zone >20). Hedge everything."

    if vix_level < 12:
        vix_note = f"VIX={vix_level:.1f} (very low — sell premium)"
    elif vix_level < 15:
        vix_note = f"VIX={vix_level:.1f} (normal)"
    else:
        vix_note = f"VIX={vix_level:.1f} (elevated — prefer spreads)"

    if nifty_chg > 0.5:
        return "BULLISH", f"NIFTY {nifty_chg:+.2f}%, {vix_note}"
    elif nifty_chg < -0.5:
        return "BEARISH", f"NIFTY {nifty_chg:+.2f}%, {vix_note}"
    else:
        return "NEUTRAL", f"NIFTY {nifty_chg:+.2f}% (range-bound), {vix_note}"


def get_vix() -> float:
    """Quick India VIX level."""
    from market.quotes import get_quote

    q = get_quote([INDEX_INSTRUMENTS["VIX"]])
    vix_quote = q.get(INDEX_INSTRUMENTS["VIX"])
    return vix_quote.last_price if vix_quote else 0.0


def get_sector_snapshot() -> list[IndexSnapshot]:
    """Return snapshots for all sector indices.

    Primary: broker/NSE quotes. Fallback: yfinance sector indices
    when primary returns zeros (common with NSE API).
    """
    sector_keys = [
        "BANK",
        "IT",
        "PHARMA",
        "AUTO",
        "FMCG",
        "REALTY",
        "METAL",
        "ENERGY",
        "INFRA",
        "PSU_BANK",
        "MEDIA",
    ]
    instruments = [INDEX_INSTRUMENTS[k] for k in sector_keys]
    from market.quotes import get_quote

    quotes = get_quote(instruments)

    snaps = []
    zero_sectors = []
    for key in sector_keys:
        inst = INDEX_INSTRUMENTS[key]
        q = quotes.get(inst)
        if q and q.last_price > 0:
            snaps.append(
                IndexSnapshot(
                    name=key,
                    instrument=inst,
                    ltp=q.last_price,
                    change=q.change,
                    change_pct=q.change_pct,
                    open=q.open,
                    high=q.high,
                    low=q.low,
                )
            )
        else:
            zero_sectors.append(key)

    # Fallback to yfinance for sectors that returned zero
    if zero_sectors:
        snaps.extend(_yf_sector_fallback(zero_sectors))

    return snaps


# yfinance tickers for sector indices
_YF_SECTOR_MAP = {
    "BANK": "^NSEBANK",
    "IT": "^CNXIT",
    "PHARMA": "^CNXPHARMA",
    "AUTO": "^CNXAUTO",
    "FMCG": "^CNXFMCG",
    "REALTY": "^CNXREALTY",
    "METAL": "^CNXMETAL",
    "ENERGY": "^CNXENERGY",
    "INFRA": "^CNXINFRA",
    "PSU_BANK": "^CNXPSUBANK",
    "MEDIA": "^CNXMEDIA",
}


def _yf_sector_fallback(sector_keys: list[str]) -> list[IndexSnapshot]:
    """Fetch sector data from yfinance when NSE returns zeros."""
    import os

    if os.environ.get("CHANAKYA_TESTING") == "1":
        return []
    try:
        import yfinance as yf

        snaps = []
        for key in sector_keys:
            yf_ticker = _YF_SECTOR_MAP.get(key)
            if not yf_ticker:
                continue
            try:
                t = yf.Ticker(yf_ticker)
                hist = t.history(period="2d")
                if hist.empty or len(hist) < 2:
                    continue
                curr = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2])
                change = curr - prev
                change_pct = (change / prev) * 100 if prev else 0
                snaps.append(
                    IndexSnapshot(
                        name=key,
                        instrument=f"YF:{yf_ticker}",
                        ltp=round(curr, 2),
                        change=round(change, 2),
                        change_pct=round(change_pct, 2),
                        open=float(hist["Open"].iloc[-1]),
                        high=float(hist["High"].iloc[-1]),
                        low=float(hist["Low"].iloc[-1]),
                    )
                )
            except Exception:
                continue
        return snaps
    except ImportError:
        return []


# ── Index Heavyweight Locomotives Mapping ──────────────────────

INDEX_HEAVYWEIGHTS: dict[str, list[str]] = {
    "NIFTY": ["RELIANCE", "HDFCBANK", "ICICIBANK", "INFOSYS", "TCS"],
    "NIFTY 50": ["RELIANCE", "HDFCBANK", "ICICIBANK", "INFOSYS", "TCS"],
    "BANKNIFTY": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK"],
    "NIFTY BANK": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK"],
    "FINNIFTY": ["HDFCBANK", "ICICIBANK", "BAJFINANCE", "KOTAKBANK", "AXISBANK"],
    "SENSEX": ["RELIANCE", "HDFCBANK", "ICICIBANK", "INFOSYS", "TCS"],
    "BANKEX": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK"],
    "MIDCPNIFTY": ["PERSISTENT", "FEDERALBNK", "COFORGE", "DIXON", "MAXHEALTH"],
}


def get_heavyweights_posture(underlying: str) -> dict[str, Any]:
    """
    Checks the real-time posture (change_pct and ltp vs vwap) of key heavyweight
    locomotives that drive the given index.
    Uses in-memory quote cache (0ms, no network I/O).
    """
    clean_und = canonical_symbol(underlying)
    heavyweights = INDEX_HEAVYWEIGHTS.get(clean_und, [])
    if not heavyweights:
        return {
            "underlying": clean_und,
            "heavyweights": [],
            "all_bullish": False,
            "all_bearish": False,
            "bull_count": 0,
            "bear_count": 0,
            "total_heavyweights": 0,
            "summary": "NO_HEAVYWEIGHTS",
        }

    try:
        from market.quotes import _QUOTE_CACHE, _quote_cache_lock

        details = []
        bull_count = 0
        bear_count = 0

        with _quote_cache_lock:
            for sym in heavyweights:
                q = None
                for k in (f"NSE:{sym}", f"BSE:{sym}", sym, f"{sym}.NS"):
                    if k in _QUOTE_CACHE:
                        _, q = _QUOTE_CACHE[k]
                        break
                if q:
                    ltp = float(getattr(q, "last_price", 0.0) or getattr(q, "ltp", 0.0) or 0.0)
                    chg = float(getattr(q, "change_pct", 0.0) or 0.0)
                    vwap = float(getattr(q, "vwap", 0.0) or 0.0)
                    is_bull = (chg > 0.20) and (ltp >= vwap if vwap > 0 else True)
                    is_bear = (chg < -0.20) and (ltp <= vwap if vwap > 0 else True)
                    if is_bull:
                        bull_count += 1
                    elif is_bear:
                        bear_count += 1
                    details.append(
                        {
                            "symbol": sym,
                            "ltp": ltp,
                            "change_pct": chg,
                            "vwap": vwap,
                            "is_bullish": is_bull,
                            "is_bearish": is_bear,
                        }
                    )

        n = len(details)
        if n == 0:
            return {
                "underlying": clean_und,
                "heavyweights": [],
                "all_bullish": False,
                "all_bearish": False,
                "bull_count": 0,
                "bear_count": 0,
                "total_heavyweights": 0,
                "summary": "UNAVAILABLE",
            }

        target_n = len(heavyweights)
        all_bull = bull_count == target_n and target_n > 0 and n == target_n
        all_bear = bear_count == target_n and target_n > 0 and n == target_n

        return {
            "underlying": clean_und,
            "heavyweights": details,
            "all_bullish": all_bull,
            "all_bearish": all_bear,
            "bull_count": bull_count,
            "bear_count": bear_count,
            "total_heavyweights": n,
            "summary": "ALL_BULLISH" if all_bull else "ALL_BEARISH" if all_bear else "MIXED",
        }
    except Exception:
        return {
            "underlying": clean_und,
            "heavyweights": [],
            "all_bullish": False,
            "all_bearish": False,
            "bull_count": 0,
            "bear_count": 0,
            "total_heavyweights": 0,
            "summary": "UNAVAILABLE",
        }


def get_premarket_battle_plan(
    indices: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Computes institutional Pre-Market Battle Plan for benchmark and major indices.
    Calculates Virgin CPR (Pivot, BC, TC, width %), Camarilla Pivots (H4, H3, L3, L4),
    and Previous Day Levels (PDH, PDL, PDC) with actionable trade blueprints.
    Leverages centralized DailyLevelsStore for sub-millisecond in-memory retrieval and daily persistence.
    """
    from engine.daily_levels import get_daily_levels
    from market.quotes import get_quote

    target_indices = indices or ["NIFTY", "BANKNIFTY", "MIDCPNIFTY", "SENSEX"]
    results: dict[str, Any] = {}

    for name in target_indices:
        clean_name = canonical_symbol(name)
        inst = INDEX_INSTRUMENTS.get(clean_name, f"NSE:{clean_name}")
        dl = get_daily_levels(clean_name)

        if dl:
            quotes = get_quote([inst])
            q = quotes.get(inst)
            ltp = (
                float(getattr(q, "last_price", 0.0) or getattr(q, "ltp", 0.0) or dl.spot)
                if q
                else dl.spot
            )

            bp = dict(dl.blueprint or {})
            if "bull_contract" not in bp:
                cam = dl.camarilla or {}
                h4 = cam.get("h4", round(dl.spot * 1.004, 1))
                l4 = cam.get("l4", round(dl.spot * 0.996, 1))
                from market.symbol_master import get_strike_step

                step = get_strike_step(clean_name, spot=dl.spot) or 50.0
                bull_stk = int(round(h4 / step) * step)
                bear_stk = int(round(l4 / step) * step)
                bp["bull_strike"] = bull_stk
                bp["bear_strike"] = bear_stk
                bp["bull_contract"] = f"{clean_name} {bull_stk} CE"
                bp["bear_contract"] = f"{clean_name} {bear_stk} PE"
                bp["h4_trigger"] = round(h4, 1)
                bp["l4_trigger"] = round(l4, 1)

            results[clean_name] = {
                "symbol": clean_name,
                "instrument": inst,
                "spot": round(ltp, 1),
                "pdh": dl.pdh,
                "pdl": dl.pdl,
                "pdc": dl.pdc,
                "pdo": dl.pdo,
                "atr_14": dl.atr_14,
                "cpr": dl.cpr,
                "camarilla": dl.camarilla,
                "classic_pivots": dl.classic_pivots,
                "weekly": dl.weekly,
                "pre_open": dl.pre_open,
                "blueprint": bp,
            }
            continue

        # Fallback if daily levels engine could not resolve
        quotes = get_quote([inst])
        q = quotes.get(inst)
        ltp = float(getattr(q, "last_price", 0.0) or getattr(q, "ltp", 0.0) or 0.0) if q else 0.0
        prev_close = float(getattr(q, "close", 0.0) or 0.0) if q else 0.0
        if ltp <= 0 and prev_close <= 0:
            continue

        pdh = round((getattr(q, "high", None) or ltp * 1.006), 1)
        pdl = round((getattr(q, "low", None) or ltp * 0.994), 1)
        pdc = round(prev_close or ltp, 1)

        cpr_pivot = (pdh + pdl + pdc) / 3.0
        cpr_bc = (pdh + pdl) / 2.0
        cpr_tc = (cpr_pivot - cpr_bc) + cpr_pivot
        cpr_top = max(cpr_tc, cpr_bc)
        cpr_bottom = min(cpr_tc, cpr_bc)
        cpr_width_pct = abs(cpr_tc - cpr_bc) / max(1.0, cpr_pivot) * 100.0

        is_narrow = cpr_width_pct <= (
            0.22 if clean_name in ("BANKNIFTY", "SENSEX", "BANKEX") else 0.15
        )
        is_wide = cpr_width_pct >= 0.35
        regime = (
            "NARROW_CPR (Trend Day Expected)"
            if is_narrow
            else ("WIDE_CPR (Range/Chop Expected)" if is_wide else "AVERAGE_CPR")
        )

        cam_range = pdh - pdl
        cam_h4 = pdc + (cam_range * 1.1 / 2.0)
        cam_h3 = pdc + (cam_range * 1.1 / 4.0)
        cam_l3 = pdc - (cam_range * 1.1 / 4.0)
        cam_l4 = pdc - (cam_range * 1.1 / 2.0)

        results[clean_name] = {
            "symbol": clean_name,
            "instrument": inst,
            "spot": round(ltp, 1),
            "pdh": round(pdh, 1),
            "pdl": round(pdl, 1),
            "pdc": round(pdc, 1),
            "cpr": {
                "tc": round(cpr_tc, 1),
                "pivot": round(cpr_pivot, 1),
                "bc": round(cpr_bc, 1),
                "cpr_top": round(cpr_top, 1),
                "cpr_bottom": round(cpr_bottom, 1),
                "cpr_width_pct": round(cpr_width_pct, 3),
                "regime": regime,
                "is_narrow": is_narrow,
                "is_wide": is_wide,
            },
            "camarilla": {
                "h4": round(cam_h4, 1),
                "h3": round(cam_h3, 1),
                "l3": round(cam_l3, 1),
                "l4": round(cam_l4, 1),
            },
            "blueprint": {
                "trend_long": f"Buy CE on 5m close above H4 (₹{cam_h4:,.1f})",
                "trend_short": f"Buy PE on 5m close below L4 (₹{cam_l4:,.1f})",
                "reversal_long": f"Buy CE on bullish rejection wick at L3/PDL (₹{cam_l3:,.1f} - ₹{pdl:,.1f}) with tight SL",
                "reversal_short": f"Buy PE on bearish rejection wick at H3/PDH (₹{cam_h3:,.1f} - ₹{pdh:,.1f}) with tight SL",
                "bull_strike": int(round(cam_h4 / 50.0) * 50),
                "bear_strike": int(round(cam_l4 / 50.0) * 50),
                "bull_contract": f"{clean_name} {int(round(cam_h4 / 50.0) * 50)} CE",
                "bear_contract": f"{clean_name} {int(round(cam_l4 / 50.0) * 50)} PE",
                "h4_trigger": round(cam_h4, 1),
                "l4_trigger": round(cam_l4, 1),
                "action_guidance": "Wait for spot to reach key boundary. Never chase in the middle between L3 and H3.",
            },
        }

    return results


def format_premarket_strike_radar(plan: Optional[dict[str, Any]] = None) -> str:
    """
    Formats the 09:10 IST Pre-Market Strike Radar into an institutional,
    two-sided battle plan for Telegram and Terminal display.
    Provides the exact CE and PE strikes to pre-populate in watchlists BEFORE 09:15.
    """
    if plan is None:
        plan = get_premarket_battle_plan(["NIFTY", "BANKNIFTY", "SENSEX"])

    now_str = datetime.now(IST).strftime("%d-%b-%Y %H:%M IST")
    lines = [
        "🎯 <b>PRE-MARKET INDEX STRIKE RADAR</b>",
        f"📅 <i>{now_str} · Watchlist Pre-Flight Preparation</i>",
        "──────────────────────────────",
        "⚡ <b>Action Required:</b> Add both ready-to-execute strikes to your broker watchlist NOW before the 09:15 bell.",
        "",
    ]

    for sym in ("NIFTY", "BANKNIFTY", "MIDCPNIFTY", "SENSEX"):
        data = plan.get(sym)
        if not data:
            continue
        spot = data.get("spot", 0.0)
        cpr_info = data.get("cpr", {})
        regime = cpr_info.get("regime", "AVERAGE_CPR")
        bp = data.get("blueprint", {})
        cam = data.get("camarilla", {})

        h4 = bp.get("h4_trigger") or cam.get("h4", round(spot * 1.004, 1))
        l4 = bp.get("l4_trigger") or cam.get("l4", round(spot * 0.996, 1))
        h5 = bp.get("h5_target") or round(h4 + (h4 - spot), 1)
        l5 = bp.get("l5_target") or round(l4 - (spot - l4), 1)

        bull_contract = bp.get("bull_contract") or f"{sym} {int(round(h4 / 50.0) * 50)} CE"
        bear_contract = bp.get("bear_contract") or f"{sym} {int(round(l4 / 50.0) * 50)} PE"

        regime_badge = (
            "🟢 Narrow (Trend Day Expected)"
            if "NARROW" in regime
            else ("🔴 Wide (Chop/Range Expected)" if "WIDE" in regime else "⚪ Average")
        )

        lines.append(f"<b>📊 {sym}</b> (Spot Anchor: ₹{spot:,.1f} | CPR: {regime_badge})")
        lines.append(f"  🟢 <b>BULL TRIGGER:</b> Above ₹{h4:,.1f} (H4 Breakout)")
        lines.append(
            f"     👉 <b>Strike:</b> <code>{bull_contract}</code> (T1: ₹{h5:,.1f} | SL: ₹{spot:,.1f})"
        )
        lines.append(f"  🔴 <b>BEAR TRIGGER:</b> Below ₹{l4:,.1f} (L4 Breakdown)")
        lines.append(
            f"     👉 <b>Strike:</b> <code>{bear_contract}</code> (T1: ₹{l5:,.1f} | SL: ₹{spot:,.1f})"
        )
        lines.append(f"  ⚠️ <b>Chop Trap Zone:</b> ₹{l4:,.1f} – ₹{h4:,.1f} (Do not chase)")
        lines.append("")

    lines.append("──────────────────────────────")
    lines.append(
        "💡 <i>Execution Discipline: Once spot breaches a trigger level with 1-min volume expansion, enter the pre-staged strike instantly without manual searching.</i>"
    )
    return "\n".join(lines)


def get_opening_range_battle_plan(symbols: Optional[list[str]] = None) -> dict[str, Any]:
    """
    Computes the 09:18 IST Opening Range Breakout (ORB) Battle Plan using the
    first 3-minute candle range (09:15 - 09:18 IST).
    Resolves:
      - Opening High (ORH) & Opening Low (ORL)
      - Bullish Trigger (Above ORH) with pre-staged CE strike & SL-Limit order guidance
      - Bearish Trigger (Below ORL) with pre-staged PE strike & SL-Limit order guidance
      - Invalidation stops anchored to opposite side of ORB or midpoint
    """
    if symbols is None:
        symbols = ["NIFTY", "BANKNIFTY", "MIDCPNIFTY", "SENSEX"]

    try:
        from market.quotes import get_quote

        index_inst_map = {
            "NIFTY": "NSE:NIFTY 50",
            "BANKNIFTY": "NSE:NIFTY BANK",
            "FINNIFTY": "NSE:NIFTY FIN SERVICE",
            "SENSEX": "BSE:SENSEX",
            "MIDCPNIFTY": "NSE:NIFTY MID SELECT",
        }
        inst_list = [index_inst_map.get(s, s) for s in symbols]
        raw_quotes = get_quote(inst_list)
        quotes: dict[str, Any] = {}
        for s in symbols:
            inst = index_inst_map.get(s, s)
            if inst in raw_quotes:
                quotes[s] = raw_quotes[inst]
            elif s in raw_quotes:
                quotes[s] = raw_quotes[s]
    except Exception as e:
        logger.warning(f"[Indices] Opening range battle plan quotes error: {e}")
        quotes = {}

    results: dict[str, Any] = {}
    for sym in symbols:
        clean_name = canonical_symbol(sym)
        q = quotes.get(clean_name) or quotes.get(sym) or quotes.get(f"{clean_name}.NS")
        spot = getattr(q, "ltp", 0.0) or getattr(q, "close", 0.0) or 0.0
        if spot <= 0:
            continue

        day_high = getattr(q, "high", 0.0) or 0.0
        day_low = getattr(q, "low", 0.0) or 0.0
        if day_high <= 0 or day_high < spot:
            day_high = round(spot * 1.002, 1)
        if day_low <= 0 or day_low > spot:
            day_low = round(spot * 0.998, 1)

        orb_range = round(day_high - day_low, 1)
        midpoint = round((day_high + day_low) / 2.0, 1)

        from market.symbol_master import get_strike_step

        step = get_strike_step(clean_name, spot=spot) or 50.0
        bull_strike = int(round(day_high / step) * step)
        bear_strike = int(round(day_low / step) * step)

        bull_trigger = round(day_high, 1)
        bear_trigger = round(day_low, 1)

        bull_t1 = round(day_high + orb_range, 1)
        bear_t1 = round(day_low - orb_range, 1)

        results[clean_name] = {
            "symbol": clean_name,
            "spot": round(spot, 1),
            "orh": day_high,
            "orl": day_low,
            "orb_range": orb_range,
            "midpoint": midpoint,
            "bull_strike": bull_strike,
            "bear_strike": bear_strike,
            "bull_contract": f"{clean_name} {bull_strike} CE",
            "bear_contract": f"{clean_name} {bear_strike} PE",
            "bull_trigger": bull_trigger,
            "bear_trigger": bear_trigger,
            "bull_t1": bull_t1,
            "bear_t1": bear_t1,
            "sl": midpoint,
        }

    return results


def format_opening_range_radar(plan: Optional[dict[str, Any]] = None) -> str:
    """
    Formats the 09:18 IST Opening Range Radar into an institutional,
    two-sided battle plan for Telegram and Terminal display.
    """
    if plan is None:
        plan = get_opening_range_battle_plan(["NIFTY", "BANKNIFTY", "MIDCPNIFTY", "SENSEX"])

    now_str = datetime.now(IST).strftime("%d-%b-%Y %H:%M IST")
    lines = [
        "⚡ <b>OPENING RANGE RADAR (09:18 IST)</b>",
        f"📅 <i>{now_str} · First 3-Min Opening Bracket Defined</i>",
        "──────────────────────────────",
        "🎯 <b>Pre-Staged Action:</b> Opening High/Low brackets are locked. Set your SL-Limit trigger orders now for instant breakout execution with zero lag!",
        "",
    ]

    for sym in ("NIFTY", "BANKNIFTY", "MIDCPNIFTY", "SENSEX"):
        data = plan.get(sym)
        if not data:
            continue
        spot = data.get("spot", 0.0)
        orh = data.get("orh", 0.0)
        orl = data.get("orl", 0.0)
        rng = data.get("orb_range", 0.0)
        mid = data.get("midpoint", 0.0)
        b_c = data.get("bull_contract", "")
        p_c = data.get("bear_contract", "")
        b_t1 = data.get("bull_t1", 0.0)
        p_t1 = data.get("bear_t1", 0.0)

        lines.append(
            f"<b>📊 {sym}</b> (Spot: ₹{spot:,.1f} | 3m Range: ₹{orl:,.1f} – ₹{orh:,.1f} [{rng:,.0f} pts])"
        )
        lines.append(f"  🟢 <b>BULL TRIGGER:</b> Above ₹{orh:,.1f} (ORH Breach)")
        lines.append(
            f"     👉 <b>Strike:</b> <code>{b_c}</code> (T1: ₹{b_t1:,.1f} | SL: ₹{mid:,.1f})"
        )
        lines.append(f"  🔴 <b>BEAR TRIGGER:</b> Below ₹{orl:,.1f} (ORL Breakdown)")
        lines.append(
            f"     👉 <b>Strike:</b> <code>{p_c}</code> (T1: ₹{p_t1:,.1f} | SL: ₹{mid:,.1f})"
        )
        lines.append(
            f"  ⚠️ <b>Chop Zone:</b> Inside ₹{orl:,.1f} – ₹{orh:,.1f} (Do not chase inside bracket)"
        )
        lines.append("")

    lines.append("──────────────────────────────")
    lines.append(
        "💡 <i>Zero-Latency Execution: Place pending SL-Limit orders in broker now. Order auto-fills on candle breach without manual searching.</i>"
    )
    return "\n".join(lines)
