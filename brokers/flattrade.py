"""Flattrade Pi Connect API adapter for ChanakyaTrade.

Provides automated headless authentication (TOTP + REST API) and unified
order routing, quote feeds, options chains, and portfolio tracking over Flattrade's
Noren-based Pi Connect OMS backend.
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
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import httpx

from brokers.base import (
    save_secure_token,
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

logger = logging.getLogger("brokers.flattrade")
log = logger

TOKEN_FILE = Path.home() / ".trading_platform" / "flattrade.json"
DEFAULT_API_URL = "https://piconnect.flattrade.in/PiConnectAPI/"
DEFAULT_WS_URL = "wss://piconnect.flattrade.in/PiConnectWSAPI/"
AUTH_API_BASE = "https://authapi.flattrade.in"

_EXCHANGE_MAP = {
    "NSE": "NSE",
    "BSE": "BSE",
    "NFO": "NFO",
    "BFO": "BFO",
    "MCX": "MCX",
    "CDS": "CDS",
}
_PRODUCT_MAP = {"CNC": "C", "MIS": "I", "NRML": "M", "CO": "H", "BO": "B"}
_REV_PRODUCT_MAP = {v: k for k, v in _PRODUCT_MAP.items()}
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


class FlattradeAPI(BrokerAPI):
    """Flattrade Pi Connect REST adapter with headless TOTP auto-login."""

    def __init__(
        self,
        user_id: str = "",
        password: str = "",
        totp_secret: str = "",
        api_key: str = "",
        api_secret: str = "",
        api_url: str = "",
        ws_url: str = "",
    ) -> None:
        self.user_id = (user_id or os.environ.get("FLATTRADE_USER_ID", "")).strip().upper()
        self._password = (password or os.environ.get("FLATTRADE_PASSWORD", "")).strip()
        self._totp_secret = (totp_secret or os.environ.get("FLATTRADE_TOTP_SECRET", "")).strip()
        self._api_key = (api_key or os.environ.get("FLATTRADE_API_KEY", "")).strip()
        self._api_secret = (api_secret or os.environ.get("FLATTRADE_API_SECRET", "")).strip()

        self.api_url = (api_url or os.environ.get("FLATTRADE_API_URL", DEFAULT_API_URL)).rstrip(
            "/"
        ) + "/"
        self.ws_url = ws_url or os.environ.get("FLATTRADE_WS_URL", DEFAULT_WS_URL)
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

    # ── Session persistence ──────────────────────────────────────────────

    def _load_token(self) -> bool:
        try:
            if not TOKEN_FILE.exists():
                return False
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
                    broker="FLATTRADE",
                )
                return True
        except (OSError, ValueError, TypeError) as e_suppressed:
            logger.debug(f"[brokers.flattrade] Non-fatal token read error: {e_suppressed}")
        return False

    def _save_token(
        self, token: str, user_id: str, account_id: str = "", name: str = "", email: str = ""
    ) -> None:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._token = token
        self._token_date = _today_ist()
        self.user_id = user_id
        self._account_id = account_id or user_id
        self._user_profile = UserProfile(
            user_id=self.user_id,
            name=name or self.user_id,
            email=email or "",
            broker="FLATTRADE",
        )
        save_secure_token(
            TOKEN_FILE,
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
        api_key = self._api_key or os.environ.get("FLATTRADE_API_KEY", "")
        return (
            f"https://auth.flattrade.in/?app_key={api_key}"
            if api_key
            else "https://wall.flattrade.in/"
        )

    # ── Headless Auto-Login (TOTP + REST Handshake) ──────────────────────

    def complete_login(self, **kwargs) -> UserProfile:
        """
        Executes a 100% headless automated login using User ID, Password, TOTP,
        API Key, and API Secret via Flattrade's auth API.
        """
        user_id = (kwargs.get("user_id") or self.user_id).strip().upper()
        password = kwargs.get("password") or self._password
        totp_secret = kwargs.get("totp_secret") or self._totp_secret
        api_key = kwargs.get("api_key") or self._api_key
        api_secret = kwargs.get("api_secret") or self._api_secret

        if not all((user_id, password, api_key, api_secret)):
            raise RuntimeError(
                "Flattrade credentials incomplete. Required in .env: "
                "FLATTRADE_USER_ID, FLATTRADE_PASSWORD, FLATTRADE_API_KEY, FLATTRADE_API_SECRET."
            )

        factor2 = kwargs.get("two_fa", "")
        if not factor2 and totp_secret:
            try:
                import pyotp

                factor2 = pyotp.TOTP(totp_secret.strip()).now()
            except ImportError as exc:
                raise RuntimeError(
                    "pyotp is required for Flattrade TOTP login. Run: pip install pyotp"
                ) from exc
        if not factor2:
            raise RuntimeError(
                "Flattrade requires FLATTRADE_TOTP_SECRET to generate automated 2FA code."
            )

        auth_headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": "https://auth.flattrade.in",
            "Referer": f"https://auth.flattrade.in/?app_key={api_key}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }

        # Step 1: Request Session ID (SID)
        try:
            r_sid = httpx.post(f"{AUTH_API_BASE}/auth/session", headers=auth_headers, timeout=10.0)
            r_sid.raise_for_status()
            sid = r_sid.text.strip()
        except Exception as e:
            raise RuntimeError(f"Flattrade session initialization failed: {e}") from e

        # Step 2: Authenticate User & TOTP
        pwd_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        auth_payload = {
            "UserName": user_id,
            "Password": pwd_hash,
            "PAN_DOB": factor2,
            "App": "",
            "ClientID": "",
            "Key": "",
            "APIKey": api_key,
            "Sid": sid,
            "Rd": "",
            "Override": "Y",
            "Source": "AUTHPAGE",
        }

        try:
            r_auth = httpx.post(
                f"{AUTH_API_BASE}/ftauth", json=auth_payload, headers=auth_headers, timeout=12.0
            )
            r_auth.raise_for_status()
            auth_data = r_auth.json()
        except Exception as e:
            raise RuntimeError(f"Flattrade ftauth request failed: {e}") from e

        emsg = auth_data.get("emsg", "")
        redirect_url = auth_data.get("RedirectURL", "")
        if emsg:
            raise RuntimeError(f"Flattrade authentication rejected: {emsg}")
        if not redirect_url:
            raise RuntimeError(f"Flattrade returned empty redirect URL: {auth_data}")

        # Step 3: Extract authorization request_code from redirect URL
        parsed = urlparse(redirect_url)
        params = parse_qs(parsed.query)
        code = params.get("code", [None])[0] or params.get("request_code", [None])[0]
        if not code:
            raise RuntimeError(f"Flattrade auth code not found in redirect URL: {redirect_url}")

        # Step 4: Exchange request_code for session token
        token_hash = hashlib.sha256(f"{api_key}{code}{api_secret}".encode("utf-8")).hexdigest()
        token_payload = {
            "api_key": api_key,
            "request_code": code,
            "api_secret": token_hash,
        }

        try:
            r_token = httpx.post(
                f"{AUTH_API_BASE}/trade/apitoken",
                json=token_payload,
                headers=auth_headers,
                timeout=12.0,
            )
            r_token.raise_for_status()
            token_data = r_token.json()
        except Exception as e:
            raise RuntimeError(f"Flattrade token exchange failed: {e}") from e

        if token_data.get("stat") != "Ok" or not token_data.get("token"):
            err = token_data.get("emsg", token_data.get("error", "Unknown token error"))
            raise RuntimeError(f"Flattrade token exchange rejected: {err}")

        session_token = str(token_data["token"])
        self._token = session_token
        self._token_date = _today_ist()
        self.user_id = user_id
        self._user_profile = None
        profile = self.get_profile()
        self._save_token(
            token=session_token,
            user_id=user_id,
            account_id=self._account_id,
            name=profile.name,
            email=profile.email,
        )
        log.info(f"[Flattrade] Automated TOTP login successful for user {user_id}")
        return profile

    def logout(self) -> None:
        self.stop_websocket()
        if self._token:
            try:
                self._post("Logout", {"uid": self.user_id})
            except Exception as e_suppressed:
                logger.debug(f"[brokers.flattrade] Non-fatal logout error: {e_suppressed}")
        self._token = ""
        self._token_date = ""
        self._account_id = ""
        self._user_profile = None
        try:
            if TOKEN_FILE.exists():
                TOKEN_FILE.unlink()
        except OSError as e_suppressed:
            logger.debug(f"[brokers.flattrade] Non-fatal token file unlink error: {e_suppressed}")
        if hasattr(self, "_client") and self._client is not None:
            try:
                self._client.close()
            except Exception as e_suppressed:
                logger.debug(f"[brokers.flattrade] Non-fatal client close error: {e_suppressed}")

    def close(self) -> None:
        self.logout()

    # ── Wire Protocol ────────────────────────────────────────────────────

    def _post(self, endpoint: str, payload: dict[str, Any], *, authenticated: bool = True) -> Any:
        if authenticated and not self.is_authenticated():
            # Try headless re-authentication if credentials are present
            if self._password and self._totp_secret and self._api_key and self._api_secret:
                try:
                    self.complete_login()
                except Exception as e:
                    raise RuntimeError(
                        f"Flattrade session expired and auto-login failed: {e}"
                    ) from e
            else:
                raise RuntimeError(
                    "Flattrade session is missing or expired; please configure credentials in .env"
                )

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
            raise RuntimeError(f"Flattrade returned invalid JSON for {endpoint}") from exc

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
            raise RuntimeError(f"Flattrade returned unexpected response type for {endpoint}")

        if str(result.get("stat", "")).lower() not in ("ok", "success"):
            message = result.get("emsg") or result.get("error") or "unknown broker error"
            if "session" in str(message).lower() or "invalid session" in str(message).lower():
                self._token = ""
            raise RuntimeError(f"Flattrade {endpoint} failed: {message}")
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
            raise RuntimeError("Flattrade broker not authenticated")
        try:
            res = self._post("UserDetails", {})
            self._account_id = str(res.get("actid") or self.user_id)
            self._user_profile = UserProfile(
                user_id=self.user_id,
                name=str(res.get("uname") or self.user_id),
                email=str(res.get("email") or ""),
                broker="FLATTRADE",
            )
            return self._user_profile
        except Exception:
            self._user_profile = UserProfile(self.user_id, self.user_id, "", "FLATTRADE")
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
                    product=_REV_PRODUCT_MAP.get(
                        str(row.get("prd") or ""), str(row.get("prd") or "")
                    ),
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

    # ── Instruments & Quotes ─────────────────────────────────────────────

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
            raise RuntimeError(f"Flattrade could not resolve instrument {instrument}")

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
            raise RuntimeError(f"Flattrade instrument lookup omitted token for {instrument}")

        lot_size = _int(exact.get("ls"), 0)
        tick_size = _num(exact.get("ti"), 0.0)
        if resolved["exch"] in {"NFO", "BFO"} and lot_size > 0 and tick_size > 0:
            try:
                from market.instrument_master import upsert_verified_contract

                upsert_verified_contract(
                    lookup_symbol=instrument,
                    provider="flattrade",
                    provider_symbol=resolved["tsym"],
                    provider_token=resolved["token"],
                    exchange=resolved["exch"],
                    segment="FNO",
                    lot_size=lot_size,
                    tick_size=tick_size,
                    expiry_date=str(exact.get("exd") or "") or None,
                )
            except Exception:
                log.warning("Could not persist verified Flattrade contract metadata", exc_info=True)
        self._instrument_cache[key] = resolved
        return resolved

    def get_quote(self, instruments: list[str] | str) -> dict[str, Quote]:
        if isinstance(instruments, str):
            instruments = [instruments]
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

    def get_market_depth(self, symbol: str) -> dict[str, Any]:
        """Level 2 Market Depth (5-level Order Book) from Flattrade GetQuotes API."""
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
        try:
            resolved = self._resolve_instrument(clean_sym)
            result = self._post("GetQuotes", {"exch": resolved["exch"], "token": resolved["token"]})
            bids = []
            asks = []
            tot_b = 0
            tot_s = 0

            for i in range(1, 6):
                bp = _num(result.get(f"bp{i}"))
                bq = _int(result.get(f"bq{i}"))
                bno = _int(result.get(f"bno{i}")) or 1
                if bp > 0 and bq > 0:
                    bids.append({"level": i, "price": bp, "quantity": bq, "orders": bno})
                    tot_b += bq

                sp = _num(result.get(f"sp{i}"))
                sq = _int(result.get(f"sq{i}"))
                sno = _int(result.get(f"sno{i}")) or 1
                if sp > 0 and sq > 0:
                    asks.append({"level": i, "price": sp, "quantity": sq, "orders": sno})
                    tot_s += sq

            spread = round(asks[0]["price"] - bids[0]["price"], 2) if (bids and asks) else 0.0

            try:
                from market.order_book import get_depth_book

                get_depth_book(symbol).batch_update(bids, asks)
                get_depth_book(clean_sym.split(":")[-1]).batch_update(bids, asks)
            except Exception as e_bridge:
                log.debug(f"[Flattrade] BisectDepthBook bridge notice: {e_bridge}")

            return {
                "symbol": symbol,
                "bids": bids,
                "asks": asks,
                "spread": spread,
                "total_buy_qty": tot_b,
                "total_sell_qty": tot_s,
                "status": "LIVE_L2",
            }
        except Exception as e:
            log.warning(f"[Flattrade] get_market_depth failed for {symbol}: {e}")
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
        prefix = f"{exch}:" if is_commodity or is_currency else ("BSE:" if is_bse else "NSE:")
        resolved = self._resolve_instrument(f"{prefix}{clean_sym}")
        payload: dict[str, Any] = {
            "exch": exch,
            "tsym": resolved.get("tsym", clean_sym),
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
                    underlying=clean_sym,
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
                    exchange=exch,
                )
            )
        return contracts

    # ── Orders & Execution ───────────────────────────────────────────────

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
            raise RuntimeError("Flattrade accepted the request without returning an order ID")
        return OrderResponse(
            order_id=order_id, status="OPEN", message="Order submitted to Flattrade"
        )

    def modify_order(
        self,
        order_id: str,
        quantity: Optional[int] = None,
        price: Optional[float] = None,
        trigger_price: Optional[float] = None,
        order_type: Optional[str] = None,
    ) -> OrderResponse:
        payload: dict[str, Any] = {"norenordno": order_id}
        if quantity is not None:
            payload["qty"] = str(quantity)
        if price is not None:
            payload["prc"] = str(price)
        if trigger_price is not None:
            payload["trgprc"] = str(trigger_price)
        if order_type is not None:
            payload["prctyp"] = _ORDER_TYPE_MAP.get(order_type.upper(), order_type)
        result = self._post("ModifyOrder", payload)
        res_id = str(result.get("norenordno") or result.get("result") or order_id)
        return OrderResponse(order_id=res_id, status="OPEN", message="Order modified on Flattrade")

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
                    status=status_map.get(status, status or "UNKNOWN"),
                    price=_num(row.get("prc")) or None,
                    average_price=_num(row.get("avgprc")) or None,
                    filled_quantity=_int(row.get("fillshares")),
                    placed_at=str(row.get("norentm") or row.get("ordenttm") or "") or None,
                    tag=row.get("remarks"),
                )
            )
        return orders

    # ── WebSocket Streaming ──────────────────────────────────────────────

    def start_websocket(
        self,
        on_tick: Optional[Callable[[dict[str, Any]], None]] = None,
        on_order: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> None:
        """Start background WebSocket streaming if websocket-client is installed."""
        if not self.is_authenticated():
            log.warning("Flattrade WebSocket requested without active authentication.")
            return

        try:
            import websocket
        except ImportError:
            log.info("websocket-client not installed; Flattrade WebSocket streaming disabled.")
            return

        def _on_message(ws, raw_message):
            try:
                msg = json.loads(raw_message)
                if msg.get("t") == "tk" and on_tick:
                    on_tick(msg)
                elif msg.get("t") == "om" and on_order:
                    on_order(msg)
            except Exception as e_suppressed:
                logger.debug(f"[brokers.flattrade] WebSocket message error: {e_suppressed}")

        def _on_open(ws):
            auth_msg = {
                "t": "c",
                "uid": self.user_id,
                "actid": self.account_id,
                "susertoken": self._token,
                "source": "API",
            }
            ws.send(json.dumps(auth_msg))
            log.info("[Flattrade] WebSocket connection opened and authenticated.")

        def _run():
            self._ws = websocket.WebSocketApp(
                self.ws_url,
                on_open=_on_open,
                on_message=_on_message,
            )
            self._ws.run_forever()

        self._ws_stop.clear()
        self._ws_thread = threading.Thread(target=_run, daemon=True)
        self._ws_thread.start()

    def stop_websocket(self) -> None:
        self._ws_stop.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception as e_suppressed:
                logger.debug(f"[brokers.flattrade] WebSocket close error: {e_suppressed}")
            self._ws = None
