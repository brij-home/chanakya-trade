import yfinance as yf
import pandas as pd

symbols = ["PNB.NS", "WAAREEENER.NS", "TRENT.NS"]

for sym in symbols:
    df = yf.download(sym, period="2y", interval="1d", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]

    print(f"\n=================== {sym} DETAILED STRUCTURE ===================")
    print(
        f"52-Week High: {df['High'].tail(252).max():.2f}, 52-Week Low: {df['Low'].tail(252).min():.2f}"
    )

    # Recent 10 daily candles
    print("\nRecent 10 trading sessions:")
    for idx, row in df.tail(10).iterrows():
        print(
            f"{idx.strftime('%Y-%m-%d')} | O: {row['Open']:8.2f} | H: {row['High']:8.2f} | L: {row['Low']:8.2f} | C: {row['Close']:8.2f} | Vol: {int(row['Volume']):10d}"
        )

    # SMC / Swing Pivots in last 60 days
    recent = df.tail(60)
    swing_highs = []
    swing_lows = []
    for i in range(2, len(recent) - 2):
        if (
            recent["High"].iloc[i] > recent["High"].iloc[i - 1]
            and recent["High"].iloc[i] > recent["High"].iloc[i - 2]
            and recent["High"].iloc[i] > recent["High"].iloc[i + 1]
            and recent["High"].iloc[i] > recent["High"].iloc[i + 2]
        ):
            swing_highs.append((recent.index[i].strftime("%Y-%m-%d"), recent["High"].iloc[i]))
        if (
            recent["Low"].iloc[i] < recent["Low"].iloc[i - 1]
            and recent["Low"].iloc[i] < recent["Low"].iloc[i - 2]
            and recent["Low"].iloc[i] < recent["Low"].iloc[i + 1]
            and recent["Low"].iloc[i] < recent["Low"].iloc[i + 2]
        ):
            swing_lows.append((recent.index[i].strftime("%Y-%m-%d"), recent["Low"].iloc[i]))

    print("\nRecent Significant Swing Highs (Resistance/Liquidity):")
    for d, p in swing_highs[-3:]:
        print(f"  {d}: {p:.2f}")
    print("Recent Significant Swing Lows (Support/Demand):")
    for d, p in swing_lows[-3:]:
        print(f"  {d}: {p:.2f}")

    # Fundamental highlights from Ticker.info
    t = yf.Ticker(sym)
    inf = t.info
    print("\nFundamentals:")
    print(f"  Sector: {inf.get('sector', 'N/A')}, Industry: {inf.get('industry', 'N/A')}")
    print(f"  Market Cap: INR {inf.get('marketCap', 0) / 1e7:,.2f} Cr")
    print(
        f"  Trailing P/E: {inf.get('trailingPE', 'N/A')}, Forward P/E: {inf.get('forwardPE', 'N/A')}"
    )
    print(f"  Price/Book: {inf.get('priceToBook', 'N/A')}, ROE: {inf.get('returnOnEquity', 'N/A')}")
