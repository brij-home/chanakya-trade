"""
web/routers/crypto_api.py
─────────────────────────
FastAPI router for 24x7 crypto market feeds, SMC analysis, options chain,
order flow (CVD), liquidation cascades, basis arbitrage, and SSE streaming.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException
from starlette.responses import StreamingResponse

logger = logging.getLogger("chanakya.web.routers.crypto")

router = APIRouter()


@router.get("/api/crypto/snapshot", tags=["Crypto 24x7"])
async def get_crypto_snapshot():
    """
    Current 24x7 snapshot of major crypto assets (BTC, ETH, SOL, BNB)
    from Binance public stream with 24h change, high/low, volume, and BBO.
    """
    from market.crypto_stream import crypto_stream

    return crypto_stream.get_snapshot()


@router.get("/api/crypto/smc", tags=["Crypto 24x7"])
async def get_crypto_smc(
    symbol: str = "BTCUSDT",
    timeframe: str = "15m",
    limit: int = 150,
):
    """
    24x7 Real-Time Smart Money Concepts (SMC) & Market Structure Analysis.
    Computes Order Blocks, FVGs, Liquidity Sweeps, CHoCH, and +2R/+4R invalidation targets.
    """
    from market.crypto_stream import crypto_stream
    from analysis.market_structure import analyze_market_structure

    df = await asyncio.to_thread(
        crypto_stream.get_klines,
        symbol=symbol,
        interval=timeframe,
        limit=limit,
    )
    if df.empty:
        raise HTTPException(status_code=404, detail=f"No kline data available for {symbol}")

    report = await asyncio.to_thread(
        analyze_market_structure,
        symbol=symbol,
        df=df,
        exchange="CRYPTO",
        timeframe=timeframe,
    )
    return report.to_dict()


@router.get("/api/crypto/options", tags=["Crypto 24x7"])
async def get_crypto_options(currency: str = "BTC", force_refresh: bool = False):
    """
    24x7 Real-Time Crypto Options Chain & Volatility Surface via Deribit.
    Computes Max Pain strike, Put-Call Ratio (OI & Volume), ATM IV, and dealer positioning.
    Zero auth/API key required.
    """
    from market.crypto_options import get_crypto_options_summary

    return await asyncio.to_thread(
        get_crypto_options_summary,
        currency=currency,
        force_refresh=force_refresh,
    )


@router.get("/api/crypto/squeeze", tags=["Crypto 24x7"])
async def get_crypto_squeeze(symbol: str = "BTCUSDT"):
    """
    Leading Indicator Squeeze & Leverage Positioning Analysis via Binance Futures.
    Computes Open Interest, 8h Funding Rate skew, and Long/Short Squeeze warnings.
    Zero auth/API key required.
    """
    from market.crypto_stream import crypto_stream

    return await asyncio.to_thread(
        crypto_stream.get_squeeze_metrics,
        symbol=symbol,
    )


@router.get("/api/crypto/orderflow", tags=["Crypto 24x7"])
async def get_crypto_orderflow(
    symbol: str = "BTCUSDT",
    timeframe: str = "15m",
    limit: int = 60,
):
    """
    Institutional Cumulative Volume Delta (CVD) & Order Flow Absorption Analysis.
    Computes aggressive buyer vs seller volume delta, cumulative delta slope,
    and institutional absorption divergence alerts.
    """
    from market.crypto_stream import crypto_stream

    return await asyncio.to_thread(
        crypto_stream.get_order_flow_metrics,
        symbol=symbol,
        interval=timeframe,
        limit=limit,
    )


@router.get("/api/crypto/liquidations", tags=["Crypto 24x7"])
async def get_crypto_liquidations(symbol: str = "BTCUSDT"):
    """
    Institutional Liquidation Cascade & Flush Exhaustion Reversal Detector.
    Scans for extreme volume anomalies accompanied by long/short rejection wicks
    and Open Interest drain to identify high R:R counter-trend reversal entries.
    """
    from market.crypto_stream import crypto_stream

    return await asyncio.to_thread(
        crypto_stream.get_liquidation_cascade_metrics,
        symbol=symbol,
    )


@router.get("/api/crypto/basis", tags=["Crypto 24x7"])
async def get_crypto_basis():
    """
    Institutional Delta-Neutral Basis & Funding Rate Arbitrage Engine.
    Scans all major crypto benchmarks (BTC, ETH, SOL, BNB, XRP, DOGE)
    for Cash-and-Carry (Long Spot + Short Perp) delta-neutral yield opportunities.
    """
    from market.crypto_stream import crypto_stream

    return await asyncio.to_thread(
        crypto_stream.get_basis_arbitrage_matrix,
    )


@router.get("/api/crypto/volatility-surface", tags=["Crypto 24x7"])
async def get_crypto_volatility_surface(currency: str = "BTC", force_refresh: bool = False):
    """
    Institutional 24x7 Deribit Options Surface, ATM IV vs 30d Realized Volatility Spread,
    Dealer GEX (Gamma Exposure) inflection zones, and Max Pain Magnet.
    """
    from market.crypto_options import get_crypto_options_summary

    return await asyncio.to_thread(
        get_crypto_options_summary,
        currency=currency,
        force_refresh=force_refresh,
    )


@router.get("/api/crypto/stream", tags=["SSE"])
async def stream_crypto():
    """
    SSE stream of 24x7 real-time crypto ticks, BBO, and candle updates.
    """
    from market.crypto_stream import crypto_stream

    async def _crypto_generator():
        snap = crypto_stream.get_snapshot()
        yield f"data: {json.dumps({'type': 'crypto_snapshot', 'data': snap})}\n\n"

        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=100)
        loop = asyncio.get_running_loop()

        def _on_tick(tick: dict):
            try:
                loop.call_soon_threadsafe(
                    lambda: queue.put_nowait(tick) if not queue.full() else None
                )
            except Exception as e_suppressed:
                logger.debug(f"[web.routers.crypto] Non-fatal exception suppressed: {e_suppressed}")

        crypto_stream.on_tick(_on_tick)

        try:
            while True:
                try:
                    tick = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps({'type': 'crypto_tick', 'data': tick})}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError as e_suppressed:
            logger.debug(f"[web.routers.crypto] Non-fatal exception suppressed: {e_suppressed}")

    return StreamingResponse(
        _crypto_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
