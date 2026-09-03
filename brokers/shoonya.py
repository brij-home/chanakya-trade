"""Shoonya (Finvasia) Noren API adapter.

The adapter intentionally owns all Shoonya/Noren wire-format details.  The
rest of ChanakyaTrade only sees the stable :class:`BrokerAPI` dataclasses.
Credentials are optional at import time; a missing account is reported as an
authentication error rather than creating a simulated session.

The official Shoonya Python SDK is not installed as a mandatory dependency.
This small HTTP adapter keeps the core install deterministic and makes the
broker integration easy to test with mocked HTTP responses.  WebSocket
streaming is exposed through ``start_websocket`` when the optional
``websocket-client`` package is installed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

import httpx

from brokers.base import (
    BrokerAPI,
    Funds,
    Holding,
    OptionsContract,
    Order,
    OrderRequest,
    OrderResponse,
    Position,
    Quote,
    UserProfile,
)

log = logging.getLogger(__name__)

TOKEN_FILE = Path.home() / ".trading_platform" / "shoonya.json"
DEFAULT_API_URL = "https://api.shoonya.com/NorenWClientTP/"
DEFAULT_WS_URL = "wss://api.shoonya.com/NorenWSTP/"

_EXCHANGE_MAP = {"NSE": "NSE", "BSE": "BSE", "NFO": "NFO", "BFO": "BFO", "MCX": "MCX", "CDS": "CDS"}
_PRODUCT_MAP = {"CNC": "C", "MIS": "I", "NRML": "M", "CO": "H", "BO": "B"}
_ORDER_TYPE_MAP = {"MARKET": "MKT", "LIMIT": "LMT", "SL": "SL-LMT", "SL-M": "SL-MKT"}
_IST = ZoneInfo("Asia/Kolkata")


def _today_ist() -> str:
    return datetime.now(_IST).date().isoformat()


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _canonical_symbol(value: Any) -> str:
    """Convert a broker trading symbol to the platform's plain ticker form."""
    symbol = str(value or "").split(":", 1)[-1]
    return symbol[:-3] if symbol.upper().endswith("-EQ") else symbol


class ShoonyaAPI(BrokerAPI):
    """Shoonya REST adapter with daily token persistence and safe parsing."""

    def __init__(
        self,
        user_id: str = "",
        password: str = "",
        api_key: str = "",
        vendor_code: str = "",
        totp_secret: str = "",
        imei: str = "",
        api_url: str = "",
        ws_url: str = "",
    ) -> None:
        self.user_id = user_id or os.environ.get("SHOONYA_USER_ID", "")
        self._password = password or os.environ.get("SHOONYA_PASSWORD", "")
        self._api_key = api_key or os.environ.get("SHOONYA_API_KEY", "")
        self._vendor_code = vendor_code or os.environ.get("SHOONYA_VENDOR_CODE", "")
        self._totp_secret = totp_secret or os.environ.get("SHOONYA_TOTP_SECRET", "")
        self._imei = imei or os.environ.get("SHOONYA_IMEI", "chanakya-trade")
        self.api_url = (api_url or os.environ.get("SHOONYA_API_URL", DEFAULT_API_URL)).rstrip(
            "/"
        ) + "/"
        self.ws_url = ws_url or os.environ.get("SHOONYA_WS_URL", DEFAULT_WS_URL)
        self._token = ""
        self._token_date = ""
        self._account_id = ""
        self._user_profile: Optional[UserProfile] = None
        self._instrument_cache: dict[str, dict[str, str]] = {}
        self._client = httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0))
        self._ws = None
        self._ws_thread: Optional[threading.Thread] = None
        self._ws_stop = threading.Event()
        self._subscriptions: set[str] = set()
        self._load_token()

    @property
    def account_id(self) -> str:
        return self._account_id or self.user_id

    # ── Session management ──────────────────────────────────────────────

    def _load_token(self) -> bool:
        try:
            data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
            token_date = data.get("token_date", "")
            if data.get("token") and token_date == _today_ist():
                self._token = data["token"]
                self._token_date = token_date
                self.user_id = data.get("user_id", self.user_id)
                self._account_id = data.get("account_id", self.user_id)
                self._user_profile = UserProfile(
                    user_id=self.user_id,
                    name=data.get("name", self.user_id),
                    email=data.get("email", ""),
                    broker="SHOONYA",
                )
                return True
        except (OSError, ValueError, TypeError):
            pass
        return False

    def _save_token(self, response: dict[str, Any]) -> None:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._token = str(response["susertoken"])
        self._token_date = _today_ist()
        self._account_id = str(response.get("actid") or self.user_id)
        self._user_profile = UserProfile(
            user_id=self.user_id,
            name=str(response.get("uname") or self.user_id),
            email=str(response.get("email") or ""),
            broker="SHOONYA",
        )
        TOKEN_FILE.write_text(
            json.dumps(
                {
                    "token": self._token,
                    "token_date": self._token_date,
                    "user_id": self.user_id,
                    "account_id": self._account_id,
                    "name": self._user_profile.name,
                    "email": self._user_profile.email,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def is_authenticated(self) -> bool:
        return bool(self._token and self._token_date == _today_ist())

    def get_login_url(self) -> str:
        # Shoonya uses credential/TOTP login; this URL is provided for UI help only.
        return os.environ.get("SHOONYA_LOGIN_URL", "https://prism.shoonya.com/")

    @staticmethod
    def _password_hash(password: str) -> str:
        return hashlib.sha256(password.encode("utf-8")).hexdigest()

    def complete_login(self, **kwargs) -> UserProfile:
        user_id = kwargs.get("user_id", self.user_id)
        password = kwargs.get("password", self._password)
        api_key = kwargs.get("api_key", self._api_key)
        vendor_code = kwargs.get("vendor_code", self._vendor_code)
        imei = kwargs.get("imei", self._imei)
        if not all((user_id, password, api_key, vendor_code)):
            raise RuntimeError(
                "Shoonya credentials are incomplete. Set SHOONYA_USER_ID, "
                "SHOONYA_PASSWORD, SHOONYA_API_KEY, and SHOONYA_VENDOR_CODE."
            )
        factor2 = kwargs.get("two_fa", "")
        if not factor2 and self._totp_secret:
            try:
                import pyotp

                factor2 = pyotp.TOTP(self._totp_secret.strip()).now()
            except ImportError as exc:
                raise RuntimeError("pyotp is required for Shoonya TOTP login") from exc
        if not factor2:
            raise RuntimeError("Shoonya requires a current OTP or SHOONYA_TOTP_SECRET")
        payload = {
            "apkversion": "1.0.0",
            "uid": user_id,
            "pwd": self._password_hash(password),
            "factor2": factor2,
            "vc": vendor_code,
            "appkey": api_key,
            "imei": imei,
            "source": "API",
        }
        response = self._post("QuickAuth", payload, authenticated=False)
        if not response.get("susertoken"):
            raise RuntimeError("Shoonya login response did not include a session token")
        self.user_id = user_id
        self._save_token(response)
        return self.get_profile()

    def logout(self) -> None:
        self.stop_websocket()
        if self._token:
            try:
                self._post("Logout", {"uid": self.user_id})
            except Exception:
                pass
        self._token = ""
        self._token_date = ""
        self._account_id = ""
        self._user_profile = None
        try:
            TOKEN_FILE.unlink()
        except OSError:
            pass

    # ── Wire protocol ────────────────────────────────────────────────────

    def _post(self, endpoint: str, payload: dict[str, Any], *, authenticated: bool = True) -> Any:
        if authenticated and not self.is_authenticated():
            raise RuntimeError("Shoonya session is missing or expired; run login again")
        body = dict(payload)
        body.setdefault("uid", self.user_id)
        data = {"jData": json.dumps(body, separators=(",", ":"))}
        if authenticated:
            data["jKey"] = self._token
        response = self._client.post(f"{self.api_url}{endpoint}", data=data)
        response.raise_for_status()
        try:
            result = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Shoonya returned invalid JSON for {endpoint}") from exc
        if isinstance(result, list):
            error_rows = [
                row
                for row in result
                if isinstance(row, dict)
                and str(row.get("stat", "Ok")).lower() not in ("ok", "success")
            ]
            if error_rows:
                result = error_rows[0]
            else:
                return result
        if not isinstance(result, dict):
            raise RuntimeError(f"Shoonya returned an unexpected response for {endpoint}")
        if str(result.get("stat", "Ok")).lower() not in ("ok", "success"):
            message = result.get("emsg") or result.get("error") or "unknown broker error"
            if "session" in str(message).lower() or "invalid session" in str(message).lower():
                self._token = ""
            raise RuntimeError(f"Shoonya {endpoint} failed: {message}")
        return result

    @staticmethod
    def _rows(result: Any, *keys: str) -> list[dict[str, Any]]:
        """Normalize Noren's endpoint-dependent list/dict response shapes."""
        if isinstance(result, list):
            return [
                row
                for row in result
                if isinstance(row, dict) and str(row.get("stat", "Ok")).lower() in ("ok", "success")
            ]
        if isinstance(result, dict):
            for key in keys:
                rows = result.get(key)
                if isinstance(rows, list):
                    if key == "exch_tsym" and any(
                        result.get(field) is not None for field in ("holdqty", "qty", "upldprc")
                    ):
                        return [result]
                    return [row for row in rows if isinstance(row, dict)]
            return [result] if result.get("tsym") or result.get("token") else []
        return []

    # ── Account ──────────────────────────────────────────────────────────

    def get_profile(self) -> UserProfile:
        if self._user_profile:
            return self._user_profile
        if not self.is_authenticated():
            raise RuntimeError("Shoonya broker not authenticated")
        self._user_profile = UserProfile(self.user_id, self.user_id, "", "SHOONYA")
        return self._user_profile

    def get_funds(self) -> Funds:
        result = self._post("Limits", {"actid": self.account_id})
        available = _num(result.get("cash", result.get("payin", result.get("cashavailable"))))
        used = _num(result.get("marginused", result.get("marginusedamount", 0)))
        return Funds(available_cash=available, used_margin=used, total_balance=available + used)

    def get_holdings(self) -> list[Holding]:
        result = self._post("Holdings", {"prd": "C", "actid": self.account_id})
        rows = self._rows(result, "exch_tsym", "values", "holdings")
        holdings: list[Holding] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            contract = (
                (row.get("exch_tsym") or [{}])[0] if isinstance(row.get("exch_tsym"), list) else row
            )
            qty = _int(row.get("holdqty", row.get("qty", 0)))
            avg = _num(row.get("upldprc", row.get("avgprc", 0)))
            ltp = _num(row.get("lp", row.get("last_price", avg)))
            holdings.append(
                Holding(
                    symbol=_canonical_symbol(contract.get("tsym") or row.get("tsym")),
                    exchange=str(contract.get("exch") or "NSE"),
                    quantity=qty,
                    avg_price=avg,
                    last_price=ltp,
                    pnl=round((ltp - avg) * qty, 2),
                    pnl_pct=round(((ltp / avg) - 1) * 100, 4) if avg else 0.0,
                )
            )
        return holdings

    def get_positions(self) -> list[Position]:
        result = self._post("PositionBook", {"actid": self.account_id})
        rows = self._rows(result, "values", "position", "positions")
        positions: list[Position] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            qty = _int(row.get("netqty", row.get("qty", 0)))
            positions.append(
                Position(
                    symbol=str(row.get("tsym") or ""),
                    exchange=str(row.get("exch") or "NSE"),
                    product=str(row.get("prd") or ""),
                    quantity=qty,
                    avg_price=_num(row.get("netavgprc", row.get("avgprc", 0))),
                    last_price=_num(row.get("lp", row.get("lastprc", 0))),
                    pnl=_num(row.get("urmtom", 0)) + _num(row.get("rpnl", 0)),
                    instrument_type="CE"
                    if str(row.get("optt", "")).upper() == "CE"
                    else ("PE" if str(row.get("optt", "")).upper() == "PE" else "EQ"),
                    expiry=str(row.get("exd") or "") or None,
                    strike=_num(row.get("strprc"), 0) or None,
                    lot_size=_int(row.get("ls"), 1),
                )
            )
        return positions

    # ── Instruments and market data ─────────────────────────────────────

    def _resolve_instrument(self, instrument: str) -> dict[str, str]:
        exchange, symbol = instrument.split(":", 1) if ":" in instrument else ("NSE", instrument)
        key = f"{exchange.upper()}:{symbol.upper()}"
        if key in self._instrument_cache:
            return self._instrument_cache[key]
        result = self._post(
            "SearchScrip",
            {
                "exch": _EXCHANGE_MAP.get(exchange.upper(), exchange.upper()),
                "stext": symbol.upper(),
            },
        )
        values = result.get("values") or []
        if not values:
            raise RuntimeError(f"Shoonya could not resolve instrument {instrument}")
        exact = next(
            (
                v
                for v in values
                if str(v.get("tsym", "")).upper() in {symbol.upper(), f"{symbol.upper()}-EQ"}
            ),
            values[0],
        )
        resolved = {
            "exch": str(exact.get("exch") or exchange.upper()),
            "token": str(exact.get("token") or ""),
            "tsym": str(exact.get("tsym") or symbol.upper()),
        }
        if not resolved["token"]:
            raise RuntimeError(f"Shoonya instrument lookup omitted token for {instrument}")
        # F&O contracts are executable only after actual broker-provided lot and
        # tick metadata is retained locally.  Missing fields remain unverified.
        lot_size = _int(exact.get("ls"), 0)
        tick_size = _num(exact.get("ti"), 0.0)
        if resolved["exch"] in {"NFO", "BFO"} and lot_size > 0 and tick_size > 0:
            try:
                from market.instrument_master import upsert_verified_contract

                upsert_verified_contract(
                    lookup_symbol=instrument,
                    provider="shoonya",
                    provider_symbol=resolved["tsym"],
                    provider_token=resolved["token"],
                    exchange=resolved["exch"],
                    segment="FNO",
                    lot_size=lot_size,
                    tick_size=tick_size,
                    expiry_date=str(exact.get("exd") or "") or None,
                )
            except Exception:
                log.warning("Could not persist verified Shoonya contract metadata", exc_info=True)
        self._instrument_cache[key] = resolved
        return resolved

    def get_quote(self, instruments: list[str]) -> dict[str, Quote]:
        quotes: dict[str, Quote] = {}
        for instrument in instruments:
            resolved = self._resolve_instrument(instrument)
            result = self._post("GetQuotes", {"exch": resolved["exch"], "token": resolved["token"]})
            ltp = _num(result.get("lp"))
            close = _num(result.get("c"))
            change_pct = _num(result.get("pc"))
            change = ltp - close if close else 0.0
            quotes[instrument] = Quote(
                symbol=instrument,
                last_price=ltp,
                open=_num(result.get("o")),
                high=_num(result.get("h")),
                low=_num(result.get("l")),
                close=close,
                volume=_int(result.get("v")),
                oi=_int(result.get("oi")) or None,
                bid=_num(result.get("bp1")) or None,
                ask=_num(result.get("sp1")) or None,
                change=change,
                change_pct=change_pct,
            )
        return quotes

    def get_historical_data(
        self,
        symbol: str,
        exchange: str = "NSE",
        interval: str = "day",
        from_date=None,
        to_date=None,
    ) -> list[dict]:
        resolved = self._resolve_instrument(f"{exchange}:{symbol}")
        end_date = to_date or datetime.now(_IST)
        start_date = from_date or (end_date - timedelta(days=365))
        if interval.lower() in {"day", "1d", "d"}:
            endpoint = "EODChartData"
            payload = {
                "sym": resolved["tsym"],
                "from": str(int(start_date.timestamp())),
                "to": str(int(end_date.timestamp())),
            }
        else:
            endpoint = "TPSeries"
            minutes = interval.lower().replace("min", "")
            payload = {
                "exch": resolved["exch"],
                "token": resolved["token"],
                "st": str(int(start_date.timestamp())),
                "et": str(int(end_date.timestamp())),
                "intrv": minutes,
            }
        result = self._post(endpoint, payload)
        rows = self._rows(result, "values", "data")
        candles = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            candles.append(
                {
                    "date": row.get("time") or row.get("ssboe"),
                    "open": _num(row.get("into")),
                    "high": _num(row.get("inth")),
                    "low": _num(row.get("intl")),
                    "close": _num(row.get("intc")),
                    "volume": _int(row.get("intv")),
                }
            )
        return list(reversed(candles))

    def get_options_chain(
        self, underlying: str, expiry: Optional[str] = None
    ) -> list[OptionsContract]:
        resolved = self._resolve_instrument(f"NSE:{underlying}")
        payload: dict[str, Any] = {
            "exch": "NFO",
            "tsym": resolved["tsym"],
            "strprc": "0",
            "cnt": "50",
        }
        if expiry:
            payload["exd"] = expiry
        result = self._post("GetOptionChain", payload)
        rows = self._rows(result, "values")
        contracts: list[OptionsContract] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            opt = str(row.get("optt") or "").upper()
            if opt not in {"CE", "PE"}:
                continue
            contracts.append(
                OptionsContract(
                    symbol=str(row.get("tsym") or ""),
                    underlying=underlying,
                    expiry=str(row.get("exd") or expiry or ""),
                    strike=_num(row.get("strprc")),
                    option_type=opt,
                    last_price=_num(row.get("lp")),
                    oi=_int(row.get("oi")),
                    oi_change=_int(row.get("oich")),
                    volume=_int(row.get("v")),
                    bid=_num(row.get("bp1")) or None,
                    ask=_num(row.get("sp1")) or None,
                    lot_size=_int(row.get("ls"), 1),
                    exchange="NFO",
                )
            )
        return contracts

    # ── Orders ───────────────────────────────────────────────────────────

    def place_order(self, order: OrderRequest) -> OrderResponse:
        resolved = self._resolve_instrument(f"{order.exchange}:{order.symbol}")
        payload: dict[str, Any] = {
            "actid": self.account_id,
            "exch": resolved["exch"],
            "tsym": resolved["tsym"],
            "qty": str(order.quantity),
            "prd": _PRODUCT_MAP.get(order.product.upper(), order.product),
            "trantype": order.transaction_type[:1].upper(),
            "prctyp": _ORDER_TYPE_MAP.get(order.order_type.upper(), order.order_type),
            "ret": order.validity.upper(),
            "remarks": order.tag or "chanakya-trade",
            "prc": str(order.price or 0),
            "trgprc": str(order.trigger_price or 0),
            "dscqty": "0",
            "ordersource": "API",
        }
        result = self._post("PlaceOrder", payload)
        order_id = str(result.get("norenordno") or result.get("result") or "")
        if not order_id:
            raise RuntimeError("Shoonya accepted the request without returning an order ID")
        return OrderResponse(order_id=order_id, status="OPEN", message="Order submitted to Shoonya")

    def cancel_order(self, order_id: str) -> bool:
        result = self._post("CancelOrder", {"norenordno": order_id})
        return bool(result.get("result") or result.get("norenordno"))

    def get_orders(self) -> list[Order]:
        result = self._post("OrderBook", {"actid": self.account_id})
        rows = self._rows(result, "values", "data")
        orders: list[Order] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            status = str(row.get("status") or "").upper()
            status_map = {
                "COMPLETE": "COMPLETE",
                "FILLED": "COMPLETE",
                "REJECTED": "REJECTED",
                "REJECT": "REJECTED",
                "CANCELLED": "CANCELLED",
                "CANCELED": "CANCELLED",
            }
            orders.append(
                Order(
                    order_id=str(row.get("norenordno") or ""),
                    symbol=str(row.get("tsym") or ""),
                    exchange=str(row.get("exch") or ""),
                    transaction_type="BUY" if str(row.get("trantype")) == "B" else "SELL",
                    quantity=_int(row.get("qty")),
                    order_type=str(row.get("prctyp") or ""),
                    product=str(row.get("prd") or ""),
                    status=status_map.get(status, status or "OPEN"),
                    price=_num(row.get("prc")) or None,
                    average_price=_num(row.get("avgprc")) or None,
                    filled_quantity=_int(row.get("fillshares")),
                    placed_at=str(row.get("norentm") or row.get("ordenttm") or "") or None,
                    tag=row.get("remarks"),
                )
            )
        return orders

    # ── Optional WebSocket ───────────────────────────────────────────────

    def start_websocket(
        self,
        on_quote: Callable[[dict[str, Any]], None],
        on_order: Optional[Callable[[dict[str, Any]], None]] = None,
        on_open: Optional[Callable[[], None]] = None,
        on_close: Optional[Callable[[], None]] = None,
    ) -> None:
        """Start a supervised Noren feed with bounded reconnect backoff."""
        if not self.is_authenticated():
            raise RuntimeError("Shoonya session is missing or expired")
        try:
            import websocket
        except ImportError as exc:
            raise RuntimeError(
                "Install optional dependency 'websocket-client' for Shoonya streaming"
            ) from exc

        def _on_message(_ws, message):
            try:
                data = json.loads(message)
            except (TypeError, ValueError):
                return
            if data.get("t") in {"om", "omsg"} and on_order:
                on_order(data)
            else:
                on_quote(data)

        def _on_open(_ws):
            _ws.send(
                json.dumps(
                    {
                        "t": "c",
                        "actid": self.account_id,
                        "uid": self.user_id,
                        "susertoken": self._token,
                        "source": "API",
                    }
                )
            )
            if self._subscriptions:
                _ws.send(json.dumps({"t": "t", "k": "#".join(sorted(self._subscriptions))}))
            if on_open:
                on_open()

        def _on_close(_ws, *_args):
            if on_close:
                on_close()

        self._ws_stop.clear()

        def _run():
            delay = 1.0
            while not self._ws_stop.is_set() and self.is_authenticated():
                self._ws = websocket.WebSocketApp(
                    self.ws_url, on_open=_on_open, on_message=_on_message, on_close=_on_close
                )
                self._ws.run_forever(ping_interval=20, ping_timeout=10)
                if self._ws_stop.is_set() or not self.is_authenticated():
                    break
                self._ws_stop.wait(delay)
                delay = min(delay * 2, 30.0)

        self._ws_thread = threading.Thread(target=_run, daemon=True, name="shoonya-websocket")
        self._ws_thread.start()

    def subscribe(self, instruments: list[str]) -> None:
        if not self._ws:
            raise RuntimeError("Shoonya WebSocket is not running")
        tokens = []
        for instrument in instruments:
            resolved = self._resolve_instrument(instrument)
            token = f"{resolved['exch']}|{resolved['token']}"
            tokens.append(token)
            self._subscriptions.add(token)
        self._ws.send(json.dumps({"t": "t", "k": "#".join(tokens)}))

    def unsubscribe(self, instruments: list[str]) -> None:
        if self._ws:
            tokens = []
            for instrument in instruments:
                resolved = self._resolve_instrument(instrument)
                token = f"{resolved['exch']}|{resolved['token']}"
                tokens.append(token)
                self._subscriptions.discard(token)
            self._ws.send(json.dumps({"t": "u", "k": "#".join(tokens)}))

    def stop_websocket(self) -> None:
        """Stop the feed and prevent automatic reconnects."""
        self._ws_stop.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        self._ws = None
