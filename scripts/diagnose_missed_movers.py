"""
scripts/diagnose_missed_movers.py
Diagnoses why SWIGGY, BANDHANBNK, ATHERENERG, and PGEL were missed today.
"""

import sys
from market.quotes import get_quote, get_ltp
from market.options import get_options_chain, get_expiries
from engine.auto_alert_engine import auto_alert_engine

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def diagnose_symbol(sym):
    print(f"\n{'='*30} DIAGNOSING {sym} {'='*30}")
    # 1. Quote
    res = get_quote(f"NSE:{sym}")
    q = res.get(f"NSE:{sym}") or res.get(sym)
    if not q:
        print(f"FAILED: No quote returned for {sym}!")
        return

    ltp = getattr(q, 'last_price', 0.0) or 0.0
    open_p = getattr(q, 'open', 0.0) or 0.0
    high_p = getattr(q, 'high', 0.0) or 0.0
    low_p = getattr(q, 'low', 0.0) or 0.0
    chg = getattr(q, 'change_pct', 0.0) or 0.0
    vol = getattr(q, 'volume', 0) or 0
    vwap = getattr(q, 'vwap', 0.0) or 0.0

    print(f"Quote: LTP={ltp}, Open={open_p}, High={high_p}, Low={low_p}, Chg={chg}%, Vol={vol:,}, VWAP={vwap}")

    # 2. Options chain
    try:
        chain = get_options_chain(sym)
        print(f"Options chain: {len(chain) if chain else 0} contracts returned")
        if not chain:
            print("  REASON: No options chain available or empty!")
            return
        
        # Check ATM contracts
        max_dist = ltp * 0.02
        atm = [c for c in chain if abs(getattr(c, 'strike', 0.0) - ltp) <= max_dist]
        print(f"  ATM contracts within 2%: {len(atm)}")
        for c in atm[:6]:
            c_strk = getattr(c, 'strike', 0.0)
            c_typ = getattr(c, 'option_type', '')
            c_vol = getattr(c, 'volume', 0)
            c_oi = getattr(c, 'oi', 0)
            c_ltp = getattr(c, 'last_price', 0.0)
            c_pch = getattr(c, 'pchange', 0.0)
            vol_oi = round(c_vol / max(1, c_oi), 2)
            print(f"    Strike: {c_strk} {c_typ} | Prem: {c_ltp} ({c_pch}%) | Vol: {c_vol} | OI: {c_oi} | Vol/OI: {vol_oi}")

    except Exception as e:
        print(f"  Options chain error: {e}")

    # 3. Check Squeeze / Technical Setup
    try:
        from market.history import get_ohlcv
        df_daily = get_ohlcv(sym, days=30, interval="1day")
        print(f"Daily bars returned: {len(df_daily) if df_daily is not None else 0}")
    except Exception as e:
        print(f"  OHLCV error: {e}")

if __name__ == "__main__":
    for s in ["SWIGGY", "BANDHANBNK", "ATHERENERG", "PGEL"]:
        diagnose_symbol(s)
