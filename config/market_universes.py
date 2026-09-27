"""
config/market_universes.py
──────────────────────────
Authoritative centralized instrument universes and asset class taxonomy for ChanakyaTrade.

Institutional Invariants:
1. Single Authority: All modules (quotes, precursor radar, asymmetric radar, alert engines)
   MUST import canonical asset universes from here rather than maintaining private sets.
2. Immutability: All sets are frozenset to prevent accidental runtime mutation.
3. Provenance: Every symbol group maps to a verified exchange segment (NSE, BSE, MCX, CDS, CRYPTO).
"""

from __future__ import annotations

# ── 1. 24x7 Crypto Universes (Binance / Spot / Perpetuals) ─────────────────────
CRYPTO_BASE_ASSETS: frozenset[str] = frozenset(
    {
        "BTC",
        "ETH",
        "SOL",
        "BNB",
        "XRP",
        "DOGE",
    }
)

CRYPTO_SYMBOLS: frozenset[str] = frozenset(
    {
        # Base Tickers
        "BTC",
        "BITCOIN",
        "BTCUSD",
        "BTC-USD",
        "BTCUSDT",
        "BTCINR",
        "ETH",
        "ETHEREUM",
        "ETHUSD",
        "ETH-USD",
        "ETHUSDT",
        "SOL",
        "SOLANA",
        "SOLUSD",
        "SOL-USD",
        "SOLUSDT",
        "BNB",
        "BINANCECOIN",
        "BNBUSD",
        "BNB-USD",
        "BNBUSDT",
        "XRP",
        "RIPPLE",
        "XRPUSD",
        "XRP-USD",
        "XRPUSDT",
        "DOGE",
        "DOGECOIN",
        "DOGEUSD",
        "DOGE-USD",
        "DOGEUSDT",
    }
)

# ── 2. MCX Commodity Universes ────────────────────────────────────────────────
MCX_COMMODITY_SYMBOLS: frozenset[str] = frozenset(
    {
        "GOLD",
        "GOLDM",
        "GOLDPETAL",
        "SILVER",
        "SILVERM",
        "SILVERMIC",
        "CRUDEOIL",
        "CRUDEOILM",
        "CRUDE",
        "BRENT",
        "NATURALGAS",
        "NATGASMINI",
        "NATGAS",
        "COPPER",
        "ZINC",
        "ALUMINIUM",
        "ALUMINUM",
        "LEAD",
        "COTTON",
    }
)

# ── 3. CDS Currency Derivatives Universes ─────────────────────────────────────
CDS_CURRENCY_SYMBOLS: frozenset[str] = frozenset(
    {
        "USDINR",
        "USD/INR",
        "EURINR",
        "EUR/INR",
        "GBPINR",
        "GBP/INR",
        "JPYINR",
        "JPY/INR",
    }
)

# ── 4. BSE Equity Benchmarks ──────────────────────────────────────────────────
BSE_EQUITY_SYMBOLS: frozenset[str] = frozenset(
    {
        "SENSEX",
        "BANKEX",
        "BSE SENSEX",
        "BSE BANKEX",
    }
)

# ── 5. Index Benchmarks & Broad Market ────────────────────────────────────────
INDEX_BENCHMARKS: frozenset[str] = frozenset(
    {
        "NIFTY",
        "NIFTY50",
        "NIFTY 50",
        "BANKNIFTY",
        "BANK NIFTY",
        "NIFTYBANK",
        "FINNIFTY",
        "FIN NIFTY",
        "MIDCPNIFTY",
        "MIDCAP",
        "NEXT50",
        "NIFTYNXT50",
        "NIFTY NEXT 50",
        "NIFTY 100",
        "NIFTY100",
        "NIFTY 200",
        "NIFTY200",
        "NIFTY 500",
        "NIFTY500",
        "NIFTYIT",
        "NIFTY IT",
        "CNXIT",
        "NIFTYAUTO",
        "NIFTY AUTO",
        "CNXAUTO",
        "NIFTYPHARMA",
        "NIFTY PHARMA",
        "NIFTYMETAL",
        "NIFTY METAL",
        "NIFTYENERGY",
        "NIFTY ENERGY",
        "NIFTYFMCG",
        "NIFTY FMCG",
        "NIFTYREALTY",
        "NIFTY REALTY",
        "NIFTYINFRA",
        "NIFTY INFRA",
        "NIFTYPSE",
        "NIFTY PSE",
        "NIFTYPSU",
        "NIFTY PSU BANK",
        "NIFTYPVTBANK",
        "NIFTY PVT BANK",
        "SENSEX",
        "BANKEX",
        "NSEI",
        "NSEBANK",
    }
)
