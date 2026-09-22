"""
scripts/market_moves_today.py
Examines market movements on 2026-09-22 across indices, F&O, and broader equities.
"""

import sys
from datetime import datetime
import pandas as pd

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from market.quotes import get_quote
from analysis.universe import THEMATIC_PRESETS

def check_market():
    # 1. Major Indices
    indices = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]
    print("=== MAJOR INDICES PERFORMANCE TODAY ===")
    for idx in indices:
        try:
            res = get_quote(idx)
            q = next(iter(res.values())) if res else None
            if not q:
                continue
            chg = getattr(q, 'change_pct', 0.0) or 0.0
            lp = getattr(q, 'last_price', 0.0) or 0.0
            o = getattr(q, 'open', 0.0) or 0.0
            h = getattr(q, 'high', 0.0) or 0.0
            l = getattr(q, 'low', 0.0) or 0.0
            print(f"{idx:12}: LTP={lp:10.2f} | Chg={chg:+6.2f}% | Open={o:10.2f} | High={h:10.2f} | Low={l:10.2f}")
        except Exception as e:
            print(f"{idx:12}: Error: {e}")

    # 2. Check F&O Universe Movers in bulk
    fno_syms = THEMATIC_PRESETS.get("fno_universe", {}).get("symbols", [])
    # Remove invalid index tickers if any
    fno_syms = [s for s in fno_syms if s not in ("NIFTYFPI", "NIFTYNXT50")]
    print(f"\nFetching {len(fno_syms)} F&O symbols in batch...")
    # Fetch in batches of 40
    all_quotes = {}
    for i in range(0, len(fno_syms), 40):
        batch = fno_syms[i:i+40]
        try:
            b_res = get_quote(batch)
            all_quotes.update(b_res)
        except Exception as e:
            print(f"Batch {i} error: {e}")

    movers = []
    for s in fno_syms:
        # Check canonical keys
        q = all_quotes.get(f"NSE:{s}") or all_quotes.get(s)
        if not q:
            continue
        chg = getattr(q, 'change_pct', 0.0) or 0.0
        lp = getattr(q, 'last_price', 0.0) or 0.0
        vol = getattr(q, 'volume', 0) or 0
        o = getattr(q, 'open', 0.0) or 0.0
        h = getattr(q, 'high', 0.0) or 0.0
        l = getattr(q, 'low', 0.0) or 0.0
        if lp > 0:
            rng = (h - l) / o * 100 if o > 0 else 0
            movers.append({
                "symbol": s,
                "ltp": lp,
                "chg": chg,
                "volume": vol,
                "open": o,
                "high": h,
                "low": l,
                "range_pct": rng
            })


    if not movers:
        print("No quotes returned for F&O universe. Check broker or data source.")
        return

    # Sort by absolute change
    movers.sort(key=lambda x: x["chg"], reverse=True)

    print("\n=== TOP 15 GAINERS (F&O) ===")
    for m in movers[:15]:
        print(f"{m['symbol']:12}: LTP={m['ltp']:8.2f} | Chg={m['chg']:+6.2f}% | Range={m['range_pct']:5.2f}% | Vol={m['volume']:,}")

    print("\n=== TOP 15 LOSERS (F&O) ===")
    for m in movers[-15:][::-1]:
        print(f"{m['symbol']:12}: LTP={m['ltp']:8.2f} | Chg={m['chg']:+6.2f}% | Range={m['range_pct']:5.2f}% | Vol={m['volume']:,}")

    # Sort by intraday range (large moves/volatility)
    movers.sort(key=lambda x: x["range_pct"], reverse=True)
    print("\n=== TOP 15 HIGHEST INTRADAY EXPANSION / RANGE (F&O) ===")
    for m in movers[:15]:
        print(f"{m['symbol']:12}: Range={m['range_pct']:5.2f}% | Chg={m['chg']:+6.2f}% | LTP={m['ltp']:8.2f} | High={m['high']:8.2f} | Low={m['low']:8.2f}")

if __name__ == "__main__":
    check_market()
