import yfinance as yf
import pandas as pd
import numpy as np

symbols = ['PNB.NS', 'WAAREEENER.NS', 'TRENT.NS']

for sym in symbols:
    df = yf.download(sym, period='1y', interval='1d', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
    
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    # EMAs
    ema20 = df['Close'].ewm(span=20).mean().iloc[-1]
    ema50 = df['Close'].ewm(span=50).mean().iloc[-1]
    sma200 = df['Close'].rolling(window=200).mean().iloc[-1] if len(df) >= 200 else None
    
    # RSI 14
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    rsi = (100 - (100 / (1 + rs))).iloc[-1]
    
    # ATR 14
    high_low = df['High'] - df['Low']
    high_cp = np.abs(df['High'] - df['Close'].shift())
    low_cp = np.abs(df['Low'] - df['Close'].shift())
    tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().iloc[-1]
    
    # 20D High and Low
    h20 = df['High'].tail(20).max()
    l20 = df['Low'].tail(20).min()
    
    # Volume average
    vol20 = df['Volume'].tail(20).mean()
    vol_ratio = last['Volume'] / vol20 if vol20 > 0 else 1.0

    print("=" * 40)
    print(f"SYMBOL: {sym}")
    print(f"Date: {df.index[-1].strftime('%Y-%m-%d')}")
    print(f"Close: {last['Close']:.2f}, High: {last['High']:.2f}, Low: {last['Low']:.2f}, Open: {last['Open']:.2f}")
    print(f"Prev Close: {prev['Close']:.2f}, Day Chg: {((last['Close'] - prev['Close']) / prev['Close'] * 100):.2f}%")
    print(f"EMA20: {ema20:.2f}, EMA50: {ema50:.2f}, SMA200: {f'{sma200:.2f}' if sma200 else 'N/A'}")
    print(f"RSI(14): {rsi:.1f}, ATR(14): {atr:.2f}")
    print(f"20D High: {h20:.2f}, 20D Low: {l20:.2f}")
    print(f"Volume: {int(last['Volume'])}, 20D Avg Vol: {int(vol20)}, RVOL: {vol_ratio:.2f}x")
