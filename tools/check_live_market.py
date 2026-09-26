import sys, os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.abspath("."))

from market.quotes import get_quote
from market.indices import get_market_snapshot, get_heavyweights_posture, get_index

print("--- FETCHING MARKET SNAPSHOT ---")
try:
    snap = get_market_snapshot()
    print(f"NIFTY: LTP={snap.nifty.ltp}, Chg={snap.nifty.change}, Chg%={snap.nifty.change_pct}%")
    print(f"BANKNIFTY: LTP={snap.banknifty.ltp}, Chg={snap.banknifty.change}, Chg%={snap.banknifty.change_pct}%")
    print(f"INDIA VIX: LTP={snap.vix.ltp}, Chg={snap.vix.change}")
    print(f"POSTURE: {snap.posture} ({snap.posture_reason})")
    if snap.polarization:
        print(f"POLARIZATION: Regime={snap.polarization.regime}, Spread={snap.polarization.spread_pct}%, Summary={snap.polarization.summary}")
except Exception as e:
    print("Market snapshot error:", e)

print("\n--- FETCHING DIRECT QUOTES ---")
symbols = ["NSE:NIFTY 50", "NSE:NIFTY BANK", "NSE:NIFTY FIN SERVICE", "NSE:NIFTY MID SELECT", "NSE:INDIA VIX", "NSE:RELIANCE", "NSE:HDFCBANK", "NSE:ICICIBANK"]
quotes = get_quote(symbols)
for s, q in quotes.items():
    print(f"{s:<25}: LTP={q.last_price:<10} Chg={q.change:<8} Chg%={q.change_pct:<6}% O={q.open} H={q.high} L={q.low} V={q.volume} Src={q.source} Prov={q.provider}")

print("\n--- HEAVYWEIGHT POSTURES ---")
for idx in ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]:
    hw = get_heavyweights_posture(idx)
    print(f"{idx}: {hw}")
