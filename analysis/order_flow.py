"""
analysis/order_flow.py
──────────────────────
Institutional Order Flow & Cumulative Volume Delta (CVD) Divergence Engine.

Detects institutional absorption, exhaustion, and aggressive market-order aggression
using Fyers Level 2 5-deep market order book ticks and intraday volume delta streams.

Core Quantitative Concepts:
  1. Bid-Ask Delta Imbalance (OBI):
     OBI = (Total_Buy_Qty - Total_Sell_Qty) / (Total_Buy_Qty + Total_Sell_Qty)
     Ranges from -1.0 (100% Sell Dominated) to +1.0 (100% Buy Dominated).

  2. Micro-Price (Order Book Equilibrium):
     P_micro = (Ask0 * Qty_bid0 + Bid0 * Qty_ask0) / (Qty_bid0 + Qty_ask0)
     Gives the true fair value weighted by top-of-book liquidity pressure.

  3. Cumulative Volume Delta (CVD):
     For each intraday bar, delta is estimated from volume traded at the ask vs bid:
     Delta_t = Volume_t * (2 * ((Close_t - Low_t) / Range_t) - 1)
     CVD_t = Sum(Delta_i, i=1..t)

  4. Order Flow Divergences:
     - Bullish Absorption: Price makes lower lows or retests support, but CVD makes higher lows.
       (Smart money passively absorbing aggressive retail sell orders with institutional limit bids).
     - Bearish Exhaustion: Price makes higher highs or retests resistance, but CVD makes lower highs.
       (Aggressive buyers running into heavy institutional passive limit sell walls).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

import numpy as np

logger = logging.getLogger("chanakya.analysis.order_flow")


@dataclass
class OrderFlowSnapshot:
    """Institutional Order Flow and CVD metrics."""

    symbol: str
    ltp: float
    market_state: str  # LIVE | DEGRADED | SIMULATED
    # Level 2 Depth Metrics
    total_buy_qty: int
    total_sell_qty: int
    order_book_imbalance: float  # -1.0 to +1.0
    bid_ask_ratio: float
    micro_price: float
    spread: float
    spread_pct: float
    top_bids: List[Dict[str, Any]]
    top_asks: List[Dict[str, Any]]
    # CVD & Footprint Metrics
    current_cvd: float
    cvd_slope_5bar: float
    cvd_divergence: str  # BULLISH_ABSORPTION | BEARISH_EXHAUSTION | AGGRESSIVE_BUYING | AGGRESSIVE_SELLING | NEUTRAL
    absorption_detected: bool
    conviction_score: int  # 0 to 100
    recommendation: str
    cvd_series: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "ltp": round(self.ltp, 2),
            "market_state": self.market_state,
            "total_buy_qty": self.total_buy_qty,
            "total_sell_qty": self.total_sell_qty,
            "order_book_imbalance": round(self.order_book_imbalance, 3),
            "bid_ask_ratio": round(self.bid_ask_ratio, 2),
            "micro_price": round(self.micro_price, 2),
            "spread": round(self.spread, 2),
            "spread_pct": round(self.spread_pct, 4),
            "top_bids": self.top_bids,
            "top_asks": self.top_asks,
            "current_cvd": round(self.current_cvd, 1),
            "cvd_slope_5bar": round(self.cvd_slope_5bar, 2),
            "cvd_divergence": self.cvd_divergence,
            "absorption_detected": self.absorption_detected,
            "conviction_score": self.conviction_score,
            "recommendation": self.recommendation,
            "cvd_series": self.cvd_series,
        }


def analyze_order_flow(symbol: str, timeframe: str = "5m") -> OrderFlowSnapshot:
    """
    Compute full order flow and Cumulative Volume Delta (CVD) analysis for any instrument.
    Leverages Fyers Level 2 5-deep market depth and intraday price-action delta.
    """
    from brokers.session import get_data_broker
    from market.history import get_historical_data
    from market.quotes import get_ltp

    clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").replace("BSE:", "").strip()

    # 1. Fetch live LTP
    ltp = float(get_ltp(f"NSE:{clean_sym}") or get_ltp(clean_sym) or 0.0)

    # 2. Fetch L2 Market Depth from Data Broker (Fyers)
    total_buy = 0
    total_sell = 0
    top_bids: List[Dict[str, Any]] = []
    top_asks: List[Dict[str, Any]] = []
    micro_price = ltp
    spread = 0.0
    spread_pct = 0.0
    imbalance = 0.0
    market_state = "DEGRADED"

    broker = None
    try:
        broker = get_data_broker()
    except Exception:
        pass

    if broker and hasattr(broker, "get_market_depth"):
        try:
            depth_data = broker.get_market_depth(clean_sym)
            if depth_data.get("status") == "ok":
                market_state = "LIVE"
                total_buy = int(depth_data.get("total_buy_qty", 0) or 0)
                total_sell = int(depth_data.get("total_sell_qty", 0) or 0)
                top_bids = depth_data.get("bids", [])[:5]
                top_asks = depth_data.get("asks", [])[:5]

                if depth_data.get("ltp") and depth_data["ltp"] > 0:
                    ltp = float(depth_data["ltp"])

                # Calculate Micro-Price & Spread
                if top_bids and top_asks:
                    best_bid = float(top_bids[0].get("price", 0.0) or 0.0)
                    best_ask = float(top_asks[0].get("price", 0.0) or 0.0)
                    bid_vol = float(top_bids[0].get("volume", 1.0) or 1.0)
                    ask_vol = float(top_asks[0].get("volume", 1.0) or 1.0)

                    if best_bid > 0 and best_ask > 0:
                        spread = max(0.0, best_ask - best_bid)
                        spread_pct = (spread / best_bid) * 100.0 if best_bid > 0 else 0.0
                        tot_vol = bid_vol + ask_vol
                        micro_price = (
                            (best_ask * bid_vol + best_bid * ask_vol) / tot_vol
                            if tot_vol > 0
                            else ltp
                        )

                tot_depth = total_buy + total_sell
                if tot_depth > 0:
                    imbalance = (total_buy - total_sell) / tot_depth
        except Exception as e:
            logger.warning(f"Error reading depth for {clean_sym}: {e}")

    bid_ask_ratio = round(total_buy / max(1, total_sell), 2) if total_sell > 0 else 1.0

    # 3. Retrieve Intraday OHLCV for Cumulative Volume Delta (CVD)
    df = None
    try:
        inv = "5m" if "5" in str(timeframe) else ("15m" if "15" in str(timeframe) else "1m")
        df = get_historical_data(clean_sym, interval=inv, days=3)
    except Exception as e:
        logger.warning(f"Error fetching historical bars for CVD: {e}")

    cvd_series: List[Dict[str, Any]] = []
    current_cvd = 0.0
    cvd_slope = 0.0
    cvd_divergence = "NEUTRAL"
    absorption_detected = False
    conviction = 50

    if df is not None and len(df) >= 5:
        # Calculate volume delta per bar
        deltas = []
        n_bars = min(len(df), 30)
        recent_df = df.iloc[-n_bars:]

        for i in range(len(recent_df)):
            row = recent_df.iloc[i]
            h = float(row.get("high", row.get("close", 0.0)))
            l = float(row.get("low", row.get("close", 0.0)))
            c = float(row.get("close", 0.0))
            v = float(row.get("volume", 1.0))

            bar_range = max(0.01, h - l)
            # Intraday bar close location relative to range (-1.0 at low, +1.0 at high)
            pos = (c - l) / bar_range
            delta_est = v * (2.0 * pos - 1.0)
            deltas.append(delta_est)

        cum_deltas = np.cumsum(deltas)
        current_cvd = float(cum_deltas[-1])

        # Generate series for UI charting
        for idx, (dt, row) in enumerate(recent_df.iterrows()):
            time_str = str(dt.strftime("%H:%M") if hasattr(dt, "strftime") else dt)
            cvd_series.append(
                {
                    "time": time_str,
                    "price": round(float(row.get("close", 0.0)), 2),
                    "volume": int(row.get("volume", 0)),
                    "delta": round(float(deltas[idx]), 1),
                    "cvd": round(float(cum_deltas[idx]), 1),
                }
            )

        # 4. Multi-bar CVD divergence analysis
        # Compare last 5 bars vs prior 10 bars
        if len(recent_df) >= 10:
            price_recent_change = float(recent_df["close"].iloc[-1]) - float(
                recent_df["close"].iloc[-6]
            )
            cvd_recent_change = float(cum_deltas[-1]) - float(cum_deltas[-6])
            cvd_slope = cvd_recent_change / 5.0

            # Divergence logic:
            # Case A: Bullish Absorption (Price down/flat, but CVD surging up + limit bids heavy)
            if price_recent_change <= 0 and cvd_recent_change > 0:
                cvd_divergence = "BULLISH_ABSORPTION"
                absorption_detected = True
                conviction = 85 if imbalance > 0.15 else 75

            # Case B: Bearish Exhaustion (Price up/flat, but CVD falling + limit asks heavy)
            elif price_recent_change >= 0 and cvd_recent_change < 0:
                cvd_divergence = "BEARISH_EXHAUSTION"
                absorption_detected = True
                conviction = 85 if imbalance < -0.15 else 75

            # Case C: Aggressive Directional Expansion
            elif price_recent_change > 0 and cvd_recent_change > 0 and imbalance > 0.20:
                cvd_divergence = "AGGRESSIVE_BUYING"
                conviction = 80
            elif price_recent_change < 0 and cvd_recent_change < 0 and imbalance < -0.20:
                cvd_divergence = "AGGRESSIVE_SELLING"
                conviction = 80

    # 5. Formulate actionable recommendation
    if cvd_divergence == "BULLISH_ABSORPTION":
        recommendation = (
            f"BULLISH ABSORPTION DETECTED on {clean_sym}: Aggressive sell market orders are being passively absorbed "
            f"by institutional limit bids (L2 Imbalance: {imbalance:+.2%}). High probability bottom reversal / spring."
        )
    elif cvd_divergence == "BEARISH_EXHAUSTION":
        recommendation = (
            f"BEARISH EXHAUSTION DETECTED on {clean_sym}: Aggressive buyers failing to advance price into heavy institutional "
            f"limit asks (CVD declining while price tests highs). High probability exhaustion top / upthrust."
        )
    elif cvd_divergence == "AGGRESSIVE_BUYING":
        recommendation = (
            f"INSTITUTIONAL AGGRESSIVE BUYING on {clean_sym}: High volume delta expansion ({current_cvd:+,.0f}) "
            f"aligned with rising price and strong bid depth ({bid_ask_ratio:.1f}x). Trend continuation favored."
        )
    elif cvd_divergence == "AGGRESSIVE_SELLING":
        recommendation = (
            f"INSTITUTIONAL AGGRESSIVE SELLING on {clean_sym}: Strong negative delta pressure ({current_cvd:+,.0f}) "
            f"and ask depth dominance. Downside trend continuation favored."
        )
    else:
        recommendation = f"Balanced order flow on {clean_sym}. Bid/Ask depth and Cumulative Volume Delta show equilibrium."

    return OrderFlowSnapshot(
        symbol=clean_sym,
        ltp=ltp,
        market_state=market_state,
        total_buy_qty=total_buy,
        total_sell_qty=total_sell,
        order_book_imbalance=imbalance,
        bid_ask_ratio=bid_ask_ratio,
        micro_price=micro_price,
        spread=spread,
        spread_pct=spread_pct,
        top_bids=top_bids,
        top_asks=top_asks,
        current_cvd=current_cvd,
        cvd_slope_5bar=cvd_slope,
        cvd_divergence=cvd_divergence,
        absorption_detected=absorption_detected,
        conviction_score=conviction,
        recommendation=recommendation,
        cvd_series=cvd_series,
    )
