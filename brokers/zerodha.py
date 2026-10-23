"""
brokers/zerodha.py
──────────────────
Zerodha Kite Connect implementation of BrokerAPI.
Docs: https://kite.trade/docs/connect/v3/
"""

from __future__ import annotations
import logging

logger = logging.getLogger("brokers.zerodha")


import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

try:
    from kiteconnect import KiteConnect
    from kiteconnect.exceptions import KiteException
except ImportError:  # pragma: no cover
    KiteConnect = None

    class KiteException(Exception):
        pass


from .base import (
    BrokerAPI,
    Funds,
    Holding,
    Order,
    OptionsContract,
    OrderRequest,
    OrderResponse,
    Position,
    Quote,
    UserProfile,
)

TOKEN_FILE = Path.home() / ".trading_platform" / "zerodha.json"


class ZerodhaAPI(BrokerAPI):
    """
    Full BrokerAPI implementation using Zerodha Kite Connect v3.
    Tokens are persisted in ~/.trading_platform/zerodha.json
    and automatically restored on construction.
    """

    def __init__(self, api_key: str = "", api_secret: str = "") -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.kite = KiteConnect(api_key=api_key) if KiteConnect is not None else None
        self._inst_lock = threading.Lock()
        self._instruments_cache: dict[str, tuple[float, list[dict]]] = {}
        if self.kite is not None:
            self._restore_token()

    # ── Token management ──────────────────────────────────────

    def _save_token(self, access_token: str) -> None:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(
            json.dumps(
                {
                    "access_token": access_token,
                    "saved_at": datetime.now().isoformat(),
                }
            )
        )
        self.kite.set_access_token(access_token)

    def _restore_token(self) -> None:
        if TOKEN_FILE.exists():
            data = json.loads(TOKEN_FILE.read_text())
            self.kite.set_access_token(data["access_token"])

    # ── Authentication ────────────────────────────────────────

    def get_login_url(self) -> str:
        return self.kite.login_url()

    def complete_login(self, request_token: str, **_) -> UserProfile:
        session = self.kite.generate_session(
            request_token,
            api_secret=self.api_secret,
        )
        self._save_token(session["access_token"])
        return UserProfile(
            user_id=session["user_id"],
            name=session.get("user_name", ""),
            email=session.get("email", ""),
            broker="ZERODHA",
        )

    def is_authenticated(self) -> bool:
        if self.kite is None:
            return False
        try:
            self.kite.profile()
            return True
        except KiteException:
            return False

    def logout(self) -> None:
        try:
            self.kite.invalidate_access_token()
        except KiteException as e_suppressed:
            logger.debug(f"[brokers.zerodha] Non-fatal exception suppressed: {e_suppressed}")
        TOKEN_FILE.unlink(missing_ok=True)

    # ── Account ───────────────────────────────────────────────

    def get_profile(self) -> UserProfile:
        p = self.kite.profile()
        return UserProfile(
            user_id=p["user_id"],
            name=p["user_name"],
            email=p["email"],
            broker="ZERODHA",
        )

    def get_funds(self) -> Funds:
        margins = self.kite.margins()
        eq = margins.get("equity", {})
        available = eq.get("available", {})
        utilised = eq.get("utilised", {})
        return Funds(
            available_cash=available.get("live_balance", 0.0),
            used_margin=utilised.get("debits", 0.0),
            total_balance=eq.get("net", 0.0),
        )

    # ── Portfolio ─────────────────────────────────────────────

    def get_holdings(self) -> list[Holding]:
        holdings = []
        for h in self.kite.holdings():
            invested = h["average_price"] * h["quantity"]
            pnl_pct = (h["pnl"] / invested * 100) if invested else 0.0
            holdings.append(
                Holding(
                    symbol=h["tradingsymbol"],
                    exchange=h["exchange"],
                    quantity=h["quantity"],
                    avg_price=h["average_price"],
                    last_price=h["last_price"],
                    pnl=h["pnl"],
                    pnl_pct=round(pnl_pct, 2),
                    day_change=h.get("day_change", 0.0),
                    day_change_pct=h.get("day_change_percentage", 0.0),
                )
            )
        return holdings

    def get_positions(self) -> list[Position]:
        positions = []
        raw = self.kite.positions().get("net", [])
        for p in raw:
            if p["quantity"] == 0:
                continue  # skip squared-off positions
            positions.append(
                Position(
                    symbol=p["tradingsymbol"],
                    exchange=p["exchange"],
                    product=p["product"],
                    quantity=p["quantity"],
                    avg_price=p["average_price"],
                    last_price=p["last_price"],
                    pnl=p["pnl"],
                    instrument_type=p.get("instrument_type", "EQ"),
                    expiry=str(p["expiry"]) if p.get("expiry") else None,
                    strike=p.get("strike_price"),
                    lot_size=p.get("lot_size", 1),
                )
            )
        return positions

    # ── Market Data ───────────────────────────────────────────

    def get_quote(self, instruments: list[str]) -> dict[str, Quote]:
        raw = self.kite.quote(instruments)
        result: dict[str, Quote] = {}
        for sym, q in raw.items():
            ohlc = q.get("ohlc", {})
            change = q["last_price"] - ohlc.get("close", q["last_price"])
            chg_pct = (change / ohlc["close"] * 100) if ohlc.get("close") else 0.0
            result[sym] = Quote(
                symbol=sym,
                last_price=q["last_price"],
                open=ohlc.get("open", 0.0),
                high=ohlc.get("high", 0.0),
                low=ohlc.get("low", 0.0),
                close=ohlc.get("close", 0.0),
                volume=q.get("volume", 0),
                oi=q.get("oi"),
                bid=q.get("depth", {}).get("buy", [{}])[0].get("price"),
                ask=q.get("depth", {}).get("sell", [{}])[0].get("price"),
                change=round(change, 2),
                change_pct=round(chg_pct, 2),
            )
        return result

    def get_market_depth(self, symbol: str) -> dict[str, Any]:
        """
        Level 2 Market Depth (5-level Order Book) from Zerodha Kite quote.
        Bridges into central BisectDepthBook in market.order_book.
        """
        if not symbol:
            return {
                "symbol": "",
                "bids": [],
                "asks": [],
                "spread": 0.0,
                "total_buy_qty": 0,
                "total_sell_qty": 0,
                "status": "UNAVAILABLE",
            }

        clean_sym = symbol.replace(".NS", "").strip()
        kite_sym = clean_sym if ":" in clean_sym else f"NSE:{clean_sym}"

        try:
            raw = self.kite.quote([kite_sym])
            q = raw.get(kite_sym) or raw.get(clean_sym) or {}
            depth = q.get("depth", {})
            buy_levels = depth.get("buy", [])
            sell_levels = depth.get("sell", [])

            bids = []
            asks = []
            tot_b = 0
            tot_s = 0

            for i, b in enumerate(buy_levels):
                p = float(b.get("price") or 0.0)
                qty = int(b.get("quantity") or 0)
                orders = int(b.get("orders") or 1)
                if p > 0 and qty > 0:
                    bids.append({"level": i + 1, "price": p, "quantity": qty, "orders": orders})
                    tot_b += qty

            for i, s in enumerate(sell_levels):
                p = float(s.get("price") or 0.0)
                qty = int(s.get("quantity") or 0)
                orders = int(s.get("orders") or 1)
                if p > 0 and qty > 0:
                    asks.append({"level": i + 1, "price": p, "quantity": qty, "orders": orders})
                    tot_s += qty

            spread = round(asks[0]["price"] - bids[0]["price"], 2) if (bids and asks) else 0.0

            # Bridge into in-memory BisectDepthBook
            try:
                from market.order_book import get_depth_book

                get_depth_book(symbol).batch_update(bids, asks)
                get_depth_book(clean_sym.split(":")[-1]).batch_update(bids, asks)
            except Exception as e_bridge:
                logger.debug(f"[Zerodha] BisectDepthBook bridge error: {e_bridge}")

            return {
                "symbol": symbol,
                "bids": bids,
                "asks": asks,
                "spread": spread,
                "total_buy_qty": tot_b,
                "total_sell_qty": tot_s,
                "status": "LIVE_L2" if (bids or asks) else "UNAVAILABLE",
            }
        except Exception as e:
            logger.warning(f"[Zerodha] get_market_depth failed for {symbol}: {e}")
            return {
                "symbol": symbol,
                "bids": [],
                "asks": [],
                "spread": 0.0,
                "total_buy_qty": 0,
                "total_sell_qty": 0,
                "status": "UNAVAILABLE",
                "message": str(e),
            }

    def _get_instruments(self, exch: str = "NFO") -> list[dict]:
        now = time.time()
        with self._inst_lock:
            if exch in self._instruments_cache:
                cached_time, data = self._instruments_cache[exch]
                if (now - cached_time) < 3600.0:
                    return data
            data = self.kite.instruments(exch)
            self._instruments_cache[exch] = (now, data)
            return data

    def get_options_chain(
        self,
        underlying: str,
        expiry: Optional[str] = None,
    ) -> list[OptionsContract]:
        from market.instruments import COMMODITY_SYMBOLS

        clean_sym = (
            underlying.upper()
            .replace("MCX:", "")
            .replace("CDS:", "")
            .replace("NFO:", "")
            .replace("NSE:", "")
            .replace("BSE:", "")
            .replace("BFO:", "")
            .strip()
        )
        is_commodity = clean_sym in COMMODITY_SYMBOLS or underlying.upper().startswith("MCX:")
        is_currency = clean_sym in (
            "USDINR",
            "EURINR",
            "GBPINR",
            "JPYINR",
        ) or underlying.upper().startswith("CDS:")
        is_bse = (
            clean_sym in ("SENSEX", "BANKEX")
            or underlying.upper().startswith("BSE:")
            or underlying.upper().startswith("BFO:")
        )

        exch = "MCX" if is_commodity else ("CDS" if is_currency else ("BFO" if is_bse else "NFO"))
        all_instruments = self._get_instruments(exch)

        # Filter by underlying and option type
        chain_instruments = [
            i
            for i in all_instruments
            if i.get("name") == clean_sym
            and i.get("instrument_type") in ("CE", "PE")
            and (not expiry or str(i.get("expiry")) == expiry)
        ]

        if not chain_instruments:
            return []

        # Nearest expiry if none specified
        if not expiry:
            expiry = str(min(i["expiry"] for i in chain_instruments))
            chain_instruments = [i for i in chain_instruments if str(i["expiry"]) == expiry]

        # Fetch live quotes for all chain instruments (max 500 at once)
        symbols = [f"{exch}:{i['tradingsymbol']}" for i in chain_instruments]
        quotes: dict = {}
        for i in range(0, len(symbols), 400):
            quotes.update(self.kite.quote(symbols[i : i + 400]))

        contracts = []
        for inst in chain_instruments:
            sym = f"{exch}:{inst['tradingsymbol']}"
            q = quotes.get(sym, {})
            contracts.append(
                OptionsContract(
                    symbol=inst["tradingsymbol"],
                    underlying=clean_sym,
                    expiry=str(inst["expiry"]),
                    strike=float(inst["strike"]),
                    option_type=inst["instrument_type"],
                    last_price=float(q.get("last_price", 0.0)),
                    oi=int(q.get("oi", 0)),
                    oi_change=int(q.get("oi_day_change", 0)),
                    volume=int(q.get("volume", 0)),
                    lot_size=int(inst.get("lot_size", 1)),
                    exchange=exch,
                )
            )

        return sorted(contracts, key=lambda c: (c.expiry, c.strike, c.option_type))

    # ── Orders ────────────────────────────────────────────────

    def place_order(self, order: OrderRequest) -> OrderResponse:
        order_id = self.kite.place_order(
            variety=self.kite.VARIETY_REGULAR,
            tradingsymbol=order.symbol,
            exchange=order.exchange,
            transaction_type=order.transaction_type,
            quantity=order.quantity,
            order_type=order.order_type,
            product=order.product,
            price=order.price,
            trigger_price=order.trigger_price,
            validity=order.validity,
            tag=order.tag,
        )
        return OrderResponse(
            order_id=str(order_id),
            status="OPEN",
            message="Order placed successfully",
        )

    def get_orders(self) -> list[Order]:
        orders = []
        for o in self.kite.orders():
            orders.append(
                Order(
                    order_id=o["order_id"],
                    symbol=o["tradingsymbol"],
                    exchange=o["exchange"],
                    transaction_type=o["transaction_type"],
                    quantity=o["quantity"],
                    order_type=o["order_type"],
                    product=o["product"],
                    status=o["status"],
                    price=o.get("price"),
                    average_price=o.get("average_price"),
                    filled_quantity=o.get("filled_quantity", 0),
                    placed_at=str(o.get("order_timestamp", "")),
                    tag=o.get("tag"),
                )
            )
        return orders

    def cancel_order(self, order_id: str) -> bool:
        self.kite.cancel_order(
            variety=self.kite.VARIETY_REGULAR,
            order_id=order_id,
        )
        return True

    # ── Good-Till-Triggered (GTT) Orders ───────────────────────

    def place_gtt(self, req: Any) -> Any:
        """Standardized BrokerAPI implementation for Zerodha Kite server-side GTT/OCO."""
        from brokers.base import GTTResponse

        try:
            kite = self.kite
            is_oco = str(req.trigger_type).upper() == "OCO" and req.leg2 is not None
            trigger_type = (
                getattr(kite, "GTT_TYPE_OCO", "two-leg")
                if is_oco
                else getattr(kite, "GTT_TYPE_SINGLE", "single")
            )

            orders = [
                {
                    "transaction_type": req.transaction_type.upper(),
                    "quantity": int(req.leg1.quantity),
                    "order_type": getattr(kite, "ORDER_TYPE_LIMIT", "LIMIT"),
                    "product": req.product.upper(),
                    "price": float(req.leg1.price),
                }
            ]
            trigger_values = [float(req.leg1.trigger_price)]

            if is_oco and req.leg2:
                orders.append(
                    {
                        "transaction_type": req.transaction_type.upper(),
                        "quantity": int(req.leg2.quantity),
                        "order_type": getattr(kite, "ORDER_TYPE_LIMIT", "LIMIT"),
                        "product": req.product.upper(),
                        "price": float(req.leg2.price),
                    }
                )
                trigger_values.append(float(req.leg2.trigger_price))

            last_price = float(req.leg1.price)
            res = kite.place_gtt(
                trigger_type=trigger_type,
                tradingsymbol=req.symbol.upper(),
                exchange=req.exchange.upper(),
                trigger_values=trigger_values,
                last_price=last_price,
                orders=orders,
            )
            trigger_id = str(res.get("trigger_id", res) if isinstance(res, dict) else res)
            return GTTResponse(
                gtt_id=trigger_id,
                status="ACTIVE",
                raw=res if isinstance(res, dict) else None,
            )
        except Exception as e:
            return GTTResponse(gtt_id="", status="REJECTED", message=str(e))

    def get_gtts(self) -> list[dict[str, Any]]:
        try:
            data = self.kite.get_gtts()
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def cancel_gtt(self, gtt_id: str) -> bool:
        try:
            self.kite.cancel_gtt(int(gtt_id) if str(gtt_id).isdigit() else gtt_id)
            return True
        except Exception:
            return False

    # ── Historical Data ──────────────────────────────────────

    def get_historical_data(
        self,
        symbol: str,
        exchange: str = "NSE",
        interval: str = "day",
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> list[dict]:
        interval_map = {
            "day": "day",
            "minute": "minute",
            "5minute": "5minute",
            "15minute": "15minute",
            "30minute": "30minute",
            "60minute": "60minute",
        }
        kite_interval = interval_map.get(interval, "day")
        to_date = to_date or datetime.now()
        from_date = from_date or datetime(to_date.year - 1, to_date.month, to_date.day)

        try:
            # Look up instrument token
            instruments = self.kite.instruments(exchange)
            token = None
            for inst in instruments:
                if inst["tradingsymbol"] == symbol:
                    token = inst["instrument_token"]
                    break
            if token is None:
                raise ValueError(f"Instrument {symbol} not found on {exchange}")

            raw = self.kite.historical_data(token, from_date, to_date, kite_interval)
            return [
                {
                    "date": candle["date"],
                    "open": candle["open"],
                    "high": candle["high"],
                    "low": candle["low"],
                    "close": candle["close"],
                    "volume": candle["volume"],
                }
                for candle in raw
            ]
        except Exception as e:
            raise RuntimeError(
                f"Zerodha historical data error: {e}\n"
                "Check that the symbol and date range are valid. If your session expired, try: logout → login"
            ) from e
