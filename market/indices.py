"""
market/indices.py
─────────────────
Indian market indices snapshot — NIFTY 50, BANKNIFTY, India VIX,
SENSEX, sector indices, and a market posture helper.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


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

    posture, reason = _market_posture(nifty, vix)

    # GIFT NIFTY pre-market indicator (#106) — best-effort, never blocks
    gift_nifty = None
    try:
        from market.gift_nifty import get_gift_nifty

        gift_nifty = get_gift_nifty(nifty_spot=nifty.ltp if nifty.ltp else None)
    except Exception:
        pass

    # Heavyweight Tug-of-War Polarization Detector
    polarization = None
    try:
        polarization = get_index_polarization("NIFTY")
        if polarization and polarization.is_polarized:
            reason += f" | {polarization.summary}"
            if posture in ("BULLISH", "BEARISH"):
                posture = "NEUTRAL"
    except Exception:
        pass

    return MarketSnapshot(
        nifty=nifty,
        banknifty=banknifty,
        vix=vix,
        sensex=sensex,
        posture=posture,
        posture_reason=reason,
        gift_nifty=gift_nifty,
        polarization=polarization,
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


def get_index_polarization(index: str = "NIFTY") -> IndexPolarization:
    """
    Computes cross-sectional return dispersion among benchmark heavyweights.
    When top drivers are moving in opposite directions (e.g., HDFC Bank +2.5% vs TCS -3.8% and Reliance -1.4%),
    the index is trapped in a 'TUG_OF_WAR_CHOP' regime where directional breakouts whipsaw.
    """
    from market.quotes import get_quote
    import numpy as np

    symbols = NIFTY_TOP_HEAVYWEIGHTS
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

    # Polarized Tug-of-War threshold:
    # Spread between top gainer and top loser >= 3.0% with opposing signs (one >= +1.0%, other <= -1.0%)
    # OR dispersion standard deviation >= 1.5% with mixed signs.
    has_opposing_momentum = max_gainer[1] >= 1.0 and max_loser[1] <= -1.0
    is_polarized = has_opposing_momentum and (spread_pct >= 3.0 or dispersion_std >= 1.5)

    if is_polarized:
        regime = "TUG_OF_WAR_CHOP"
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
