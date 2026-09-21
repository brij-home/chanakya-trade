import yfinance as yf
import pandas as pd

symbols = ['PNB.NS', 'WAAREEENER.NS', 'TRENT.NS', '^NSEI', '^NSEBANK']

for sym in symbols:
    df = yf.download(sym, period='3mo', interval='1d', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
    
    c = df['Close'].iloc[-1]
    ret_5d = ((c - df['Close'].iloc[-5]) / df['Close'].iloc[-5]) * 100
    ret_1m = ((c - df['Close'].iloc[-21]) / df['Close'].iloc[-21]) * 100
    
    # 50 SMA vs 200 SMA
    df_long = yf.download(sym, period='1y', interval='1d', progress=False)
    if isinstance(df_long.columns, pd.MultiIndex):
        df_long.columns = [col[0] for col in df_long.columns]
    sma50 = df_long['Close'].rolling(50).mean().iloc[-1]
    sma200 = df_long['Close'].rolling(200).mean().iloc[-1] if len(df_long) >= 200 else 0
    
    print(f"{sym:15s} | Close: {c:8.2f} | 5D: {ret_5d:+6.2f}% | 1M: {ret_1m:+6.2f}% | SMA50: {sma50:8.2f} | SMA200: {sma200:8.2f}")
