"""
brokers/mstock.py
─────────────────
m.Stock (Mirae Asset Capital Markets) BrokerAPI implementation.

m.Stock provides a free trading API for Indian equity & F&O markets,
supporting OAuth2 browser redirects, TOTP session generation, live quotes,
portfolio holdings, intraday positions, and order execution.

Credentials needed:
    MSTOCK_API_KEY      — API Key / Platform Key from m.Stock developer portal
    MSTOCK_API_SECRET   — API Secret / Secret Key
    MSTOCK_CLIENT_CODE  — Your m.Stock trading login ID / Client Code
    MSTOCK_PASSWORD     — Your m.Stock trading password (optional for direct login)
    MSTOCK_TOTP_SECRET  — (Optional) Base32 TOTP secret for automated 2FA login
    MSTOCK_REDIRECT_URL — Redirect URL (default: http://103.149.127.88:8765/mstock/callback)

Session token is persisted to ~/.trading_platform/mstock.json and auto-restored.
"""

from __future__ import annotations

import base64
import json
import os
import time
from datetime import datetime
from typing import Optional

try:
    import dotenv

    dotenv.load_dotenv()
except ImportError:
    pass

import httpx

from brokers.base import (
    BrokerAPI,
    UserProfile,
    Funds,
    Holding,
    Position,
    Quote,
    OptionsContract,
    OrderRequest,
    OrderResponse,
    Order,
)
from config.paths import app_data_path

TOKEN_FILE = app_data_path("mstock.json")

MSTOCK_BASE_URL = os.environ.get("MSTOCK_BASE_URL", "https://api.mstock.trade")
MSTOCK_AUTH_URL = os.environ.get("MSTOCK_AUTH_URL", "https://api.mstock.trade")

# Exchange mapping
_EXCHANGE_MAP = {
    "NSE": "NSE",
    "BSE": "BSE",
    "NFO": "NFO",
    "BFO": "BFO",
    "MCX": "MCX",
    "CDS": "CDS",
}

# Reverse exchange mapping
_REV_EXCHANGE_MAP = {v: k for k, v in _EXCHANGE_MAP.items()}

# Order Type mapping
_ORDER_TYPE_MAP = {
    "MARKET": "MARKET",
    "LIMIT": "LIMIT",
    "SL": "SL",
    "SL-M": "SL-M",
}

# Product Type mapping
_PRODUCT_MAP = {
    "CNC": "CNC",
    "MIS": "MIS",
    "NRML": "NRML",
}

# Common NSE segment security tokens
_KNOWN_NSE_TOKENS = {
    "NIFTY": "26000",
    "NIFTY50": "26000",
    "NIFTY 50": "26000",
    "BANKNIFTY": "26009",
    "NIFTY BANK": "26009",
    "RELIANCE": "2885",
    "TCS": "11536",
    "INFY": "1594",
    "HDFCBANK": "1333",
    "ICICIBANK": "4963",
    "SBIN": "3045",
    "KOTAKBANK": "1922",
    "AXISBANK": "5900",
    "LT": "11483",
    "ITC": "1660",
    "BAJFINANCE": "317",
    "BHARTIARTL": "10604",
    "MARUTI": "10999",
    "TATAMOTORS": "3456",
    "WIPRO": "3787",
    "COFORGE": "11540",
    "TRENT": "1964",
    "HCLTECH": "7229",
    "DIVISLAB": "10940",
    "TECHM": "13538",
    "GOLD": "GOLD",
    "SILVER": "SILVER",
    "CRUDEOIL": "CRUDEOIL",
}


class MStockAPI(BrokerAPI):
    """
    m.Stock (Mirae Asset Capital Markets) Broker implementation for live data and order execution.
    Supports official Type B User APIs with TOTP automated session handshake.
    """

    name = "mstock"

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        client_code: str = "",
        password: str = "",
        totp_secret: str = "",
        redirect_uri: str = "",
    ) -> None:
        self._api_key = api_key or os.environ.get("MSTOCK_API_KEY", "")
        self._api_secret = api_secret or os.environ.get("MSTOCK_API_SECRET", "")
        self._client_code = client_code or os.environ.get("MSTOCK_CLIENT_CODE", "")
        self._password = password or os.environ.get("MSTOCK_PASSWORD", "")
        self._totp_secret = totp_secret or os.environ.get("MSTOCK_TOTP_SECRET", "")
        self._redirect_uri = (
            redirect_uri
            or os.environ.get("MSTOCK_REDIRECT_URL", "")
            or "http://103.149.127.88:8765/mstock/callback"
        )

        self._token: str = ""
        self._refresh_token: str = ""
        self._token_expiry: float = 0.0
        self._user_profile: Optional[UserProfile] = None
        self._client = httpx.Client(timeout=10.0)

        # Restore saved token session if valid
        self._load_token()

    # ── Token persistence ─────────────────────────────────────

    def _load_token(self) -> bool:
        if not TOKEN_FILE.exists():
            return False
        try:
            data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
            token = data.get("token", "")
            expiry = data.get("expiry", 0)
            client_code = data.get("client_code", "")

            if token and (client_code == self._client_code or not self._client_code):
                if expiry > time.time():
                    self._token = token
                    self._refresh_token = data.get("refresh_token", "")
                    self._token_expiry = expiry
                    self._client_code = client_code or self._client_code
                    if not self._api_key and data.get("api_key"):
                        self._api_key = data.get("api_key")
                    c_name = data.get("client_name")
                    if c_name:
                        self._user_profile = UserProfile(
                            user_id=self._client_code or "MSTOCK_USER",
                            name=c_name,
                            email="",
                            broker="MSTOCK",
                        )
                    return True
        except Exception:
            pass
        return False

    def _save_token(
        self, token: str, expiry_seconds: int = 28800, refresh_token: str = ""
    ) -> None:
        try:
            TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
            # Parse real JWT exp claim if present
            try:
                parts = token.split(".")
                if len(parts) >= 2:
                    padded = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
                    jwt_payload = json.loads(
                        base64.urlsafe_b64decode(padded.encode()).decode("utf-8")
                    )
                    jwt_exp = jwt_payload.get("exp")
                    if jwt_exp:
                        expiry_seconds = max(60, int(jwt_exp - time.time() - 120))
            except Exception:
                pass

            client_name = self._user_profile.name if self._user_profile else "m.Stock Trader"
            payload = {
                "token": token,
                "refresh_token": refresh_token,
                "client_code": self._client_code,
                "client_name": client_name,
                "api_key": self._api_key,
                "expiry": time.time() + expiry_seconds,
                "updated_at": datetime.now().isoformat(),
            }
            TOKEN_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            pass

    # ── Authentication ────────────────────────────────────────

    def is_authenticated(self) -> bool:
        """True if a valid session token is present and not expired."""
        if not self._token:
            return False
        if self._token_expiry > 0 and self._token_expiry < time.time():
            return False
        return True

    def authenticate(
        self,
        api_key: str = "",
        api_secret: str = "",
        client_code: str = "",
        password: str = "",
        totp_secret: str = "",
        force: bool = False,
    ) -> bool:
        """
        Authenticate with m.Stock Type B REST API.
        If already authenticated via active token and not forced, returns True.
        Performs official 2-step TOTP handshake:
          Step 1: POST /openapi/typeb/connect/login
          Step 2: POST /openapi/typeb/session/verifytotp
        Also gracefully supports single-step direct token mock responses for unit tests.
        """
        if not force and self.is_authenticated():
            return True
        if force:
            self._token = ""
            self._token_expiry = 0

        ak = api_key or self._api_key
        cc = client_code or self._client_code
        pwd = password or self._password
        totp_s = totp_secret or self._totp_secret

        if not cc:
            return False

        try:
            # Step 1: Login
            url = f"{MSTOCK_BASE_URL}/openapi/typeb/connect/login"
            headers = {
                "X-Mirae-Version": "1",
                "Content-Type": "application/json",
            }
            if ak:
                headers["X-PrivateKey"] = ak
            payload = {
                "clientcode": cc,
                "password": pwd,
                "totp": "",
                "state": "",
            }
            resp = self._client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                res_data = data.get("data") or data.get("result") or data
                refresh_token = (
                    res_data.get("refreshToken")
                    or res_data.get("jwtToken")
                    or data.get("token", "")
                )

                # Step 2: Verify TOTP if totp_secret is present
                totp_code = ""
                if totp_s:
                    try:
                        import pyotp

                        totp_code = pyotp.TOTP(totp_s.strip()).now()
                    except ImportError:
                        pass

                if totp_code and refresh_token and ak:
                    v_url = f"{MSTOCK_BASE_URL}/openapi/typeb/session/verifytotp"
                    v_headers = {
                        "X-Mirae-Version": "1",
                        "X-PrivateKey": ak,
                        "Content-Type": "application/json",
                    }
                    v_body = {
                        "refreshToken": refresh_token,
                        "totp": totp_code,
                    }
                    v_resp = self._client.post(v_url, json=v_body, headers=v_headers)
                    if v_resp.status_code == 200:
                        v_data = v_resp.json()
                        v_res = v_data.get("data") or v_data.get("result") or v_data
                        jwt_token = (
                            v_res.get("jwtToken") or v_res.get("token") or v_res.get("accessToken")
                        )
                        if jwt_token:
                            self._token = jwt_token
                            self._client_code = cc
                            self._token_expiry = time.time() + 86400
                            client_name = (
                                v_res.get("ClientName")
                                or v_res.get("CLIENTNAME")
                                or "m.Stock Trader"
                            )
                            self._user_profile = UserProfile(
                                user_id=cc,
                                name=client_name,
                                email="",
                                broker="MSTOCK",
                            )
                            self._save_token(jwt_token, refresh_token=refresh_token)
                            return True

                # Direct token fallback (for test mocks or single-step responses)
                direct_token = (
                    res_data.get("jwtToken") or res_data.get("token") or res_data.get("accessToken")
                )
                if direct_token:
                    self._token = direct_token
                    self._client_code = cc
                    self._token_expiry = time.time() + 86400
                    self._save_token(direct_token, refresh_token=refresh_token)
                    return True
        except Exception:
            pass
        return False

    def get_login_url(self) -> str:
        """Returns the m.Stock OAuth authorization URL."""
        return f"{MSTOCK_AUTH_URL}/login/?platform_key={self._api_key}&redirect_url={self._redirect_uri}"

    def complete_login(
        self,
        token: str = "",
        auth_code: str = "",
        request_token: str = "",
        code: str = "",
        jwt: str = "",
        **kwargs,
    ) -> UserProfile:
        """
        Exchange or accept redirected token from m.Stock callback.
        Supports query parameters 'token', 'auth_token', 'jwt', 'request_token', 'code'.
        """
        candidate_token = (
            token or jwt or auth_code or request_token or code or kwargs.get("auth_token", "")
        )

        if not candidate_token:
            if not self.authenticate():
                raise RuntimeError(
                    "m.Stock authentication failed; no active session or authorization token found. "
                    "Verify your MSTOCK_API_KEY and credentials, or log in via the m.Stock OAuth portal."
                )
        else:
            self._token = candidate_token
            self._token_expiry = time.time() + 86400
            self._save_token(self._token)

        return self.get_profile()

    def logout(self) -> None:
        """Clear active token and unlink saved session file."""
        self._token = ""
        self._user_profile = None
        if TOKEN_FILE.exists():
            try:
                TOKEN_FILE.unlink()
            except Exception:
                pass

    # ── Headers Helper ────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Mirae-Version": "1",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if self._api_key:
            headers["X-PrivateKey"] = self._api_key
        return headers

    def _fetch_authed(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Execute request with automatic transparent re-auth retry on 401/403."""
        headers = self._headers()
        if "headers" in kwargs:
            headers.update(kwargs.pop("headers"))

        m = method.upper()
        if m == "GET":
            resp = self._client.get(url, headers=headers, **kwargs)
        elif m == "POST":
            resp = self._client.post(url, headers=headers, **kwargs)
        else:
            resp = self._client.request(method, url, headers=headers, **kwargs)

        if resp.status_code in (401, 403) and self._client_code and self._password and self._totp_secret:
            if self.authenticate(force=True):
                headers = self._headers()
                if m == "GET":
                    resp = self._client.get(url, headers=headers, **kwargs)
                elif m == "POST":
                    resp = self._client.post(url, headers=headers, **kwargs)
                else:
                    resp = self._client.request(method, url, headers=headers, **kwargs)
        return resp

    # ── User Profile & Funds ──────────────────────────────────

    def get_profile(self) -> UserProfile:
        """Fetch user profile details from m.Stock."""
        if self._user_profile:
            return self._user_profile

        name = "m.Stock Trader"
        email = ""
        uid = self._client_code or "MSTOCK_USER"

        self._user_profile = UserProfile(
            user_id=uid,
            name=name,
            email=email,
            broker="MSTOCK",
        )
        return self._user_profile

    def get_funds(self) -> Funds:
        """Fetch available funds and margin utilization."""
        if not self._token:
            return Funds(available_cash=0.0, used_margin=0.0, total_balance=0.0)

        try:
            url = f"{MSTOCK_BASE_URL}/openapi/typeb/user/fundsummary"
            resp = self._fetch_authed("GET", url)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data") or data.get("result") or data
                item = (
                    items[0]
                    if isinstance(items, list) and items
                    else (items if isinstance(items, dict) else {})
                )
                avail = float(
                    item.get("AVAILABLE_BALANCE")
                    or item.get("CLEAR_BALANCE")
                    or item.get("availableMargin")
                    or item.get("netMargin")
                    or item.get("available_cash")
                    or 0.0
                )
                used = float(
                    item.get("AMOUNT_UTILIZED")
                    or item.get("usedMargin")
                    or item.get("marginUsed")
                    or 0.0
                )
                total = float(item.get("LIMIT_SOD") or item.get("totalMargin") or (avail + used))
                return Funds(available_cash=avail, used_margin=used, total_balance=total)
        except Exception:
            pass

        return Funds(available_cash=0.0, used_margin=0.0, total_balance=0.0)

    # ── Portfolio & Positions ─────────────────────────────────

    def get_holdings(self) -> list[Holding]:
        """Fetch long-term delivery (CNC) holdings."""
        if not self._token:
            return []

        try:
            url = f"{MSTOCK_BASE_URL}/openapi/typeb/portfolio/holdings"
            resp = self._fetch_authed("GET", url)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data") or data.get("result") or data
                if isinstance(items, dict):
                    items = items.get("holdings", [])
                if not isinstance(items, list):
                    items = []
                holdings = []
                for item in items:
                    qty = int(item.get("quantity") or item.get("totalQty") or 0)
                    avg = float(
                        item.get("averageprice")
                        or item.get("avgPrice")
                        or item.get("averagePrice")
                        or 0.0
                    )
                    ltp = float(item.get("ltp") or item.get("lastPrice") or avg)
                    pnl = float(item.get("pnl") or ((ltp - avg) * qty))
                    pnl_pct = (pnl / (avg * qty) * 100.0) if avg and qty else 0.0
                    sym = (
                        item.get("tradingsymbol")
                        or item.get("symbol")
                        or item.get("tradingSymbol")
                        or ""
                    )
                    holdings.append(
                        Holding(
                            symbol=sym,
                            exchange=item.get("exchange") or "NSE",
                            quantity=qty,
                            avg_price=avg,
                            last_price=ltp,
                            pnl=pnl,
                            pnl_pct=pnl_pct,
                            day_change=float(item.get("dayChange") or 0.0),
                            day_change_pct=float(item.get("dayChangePct") or 0.0),
                        )
                    )
                return holdings
        except Exception:
            pass

        return []

    def get_positions(self) -> list[Position]:
        """Fetch open intraday and F&O positions."""
        if not self._token:
            return []

        try:
            url = f"{MSTOCK_BASE_URL}/openapi/typeb/portfolio/positions"
            resp = self._fetch_authed("GET", url)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data") or data.get("result") or data
                if isinstance(items, dict):
                    items = items.get("positions", [])
                if not isinstance(items, list):
                    items = []
                positions = []
                for item in items:
                    qty = int(item.get("netqty") or item.get("netQty") or item.get("quantity") or 0)
                    avg = float(
                        item.get("buyavgprice")
                        or item.get("avgPrice")
                        or item.get("buyAvgPrice")
                        or 0.0
                    )
                    ltp = float(item.get("ltp") or item.get("lastPrice") or avg)
                    unrealised = float(
                        item.get("unrealisedPnl")
                        or item.get("unrealizedPnl")
                        or ((ltp - avg) * qty)
                    )
                    realised = float(item.get("realisedPnl") or item.get("realizedPnl") or 0.0)
                    sym = (
                        item.get("symbolname")
                        or item.get("tradingsymbol")
                        or item.get("symbol")
                        or item.get("tradingSymbol")
                        or ""
                    )
                    positions.append(
                        Position(
                            symbol=sym,
                            exchange=item.get("exchange") or "NSE",
                            product=item.get("producttype") or item.get("product") or "MIS",
                            quantity=qty,
                            avg_price=avg,
                            last_price=ltp,
                            pnl=unrealised + realised,
                        )
                    )
                return positions
        except Exception:
            pass
        return []

    # ── Market Data & Quotes ──────────────────────────────────

    def get_quote(self, instruments: list[str] | str) -> dict[str, Quote] | Quote:
        """
        Fetch live quote(s). Accepts either a single symbol string or a list of instruments.
        Utilizes m.Stock Type B quote API when symbol token is mapped, falling back to market quote engine.
        """
        is_single = isinstance(instruments, str)
        inst_list = [instruments] if is_single else list(instruments)

        quotes: dict[str, Quote] = {}
        for inst in inst_list:
            clean_sym = inst.replace("NSE:", "").replace("BSE:", "")
            exchange = "BSE" if inst.startswith("BSE:") else "NSE"
            quote_obj = None

            token = _KNOWN_NSE_TOKENS.get(clean_sym, "")
            if self._token:
                try:
                    url = f"{MSTOCK_BASE_URL}/openapi/typeb/instruments/quote"
                    resp = None
                    if token:
                        q_payload = json.dumps(
                            {"mode": "OHLC", "exchangeTokens": {exchange: [token]}}
                        )
                        try:
                            resp = self._client.request(
                                "GET", url, content=q_payload, headers=self._headers()
                            )
                        except Exception:
                            resp = None
                    if resp is None or resp.status_code != 200:
                        resp = self._client.get(
                            url,
                            params={"symbol": clean_sym, "exchange": exchange},
                            headers=self._headers(),
                        )

                    if resp is not None and resp.status_code == 200:
                        data = resp.json()
                        fetched = (
                            data.get("data", {}).get("fetched", [])
                            if isinstance(data.get("data"), dict)
                            else []
                        )
                        if fetched:
                            item = fetched[0]
                            ltp = float(item.get("ltp") or 0.0)
                            close = float(item.get("close") or ltp)
                            change = ltp - close
                            change_pct = (change / close * 100.0) if close else 0.0
                            quote_obj = Quote(
                                symbol=clean_sym,
                                last_price=ltp,
                                open=float(item.get("open") or ltp),
                                high=float(item.get("high") or ltp),
                                low=float(item.get("low") or ltp),
                                close=close,
                                volume=int(item.get("volume") or 0),
                                change=round(change, 2),
                                change_pct=round(change_pct, 2),
                            )
                        else:
                            res = data.get("result") or data.get("data") or data
                            if isinstance(res, dict) and (res.get("ltp") or res.get("lastPrice")):
                                ltp = float(res.get("ltp") or res.get("lastPrice") or 0.0)
                                close = float(res.get("close") or res.get("prevClose") or ltp)
                                change = ltp - close
                                change_pct = (change / close * 100.0) if close else 0.0
                                quote_obj = Quote(
                                    symbol=clean_sym,
                                    last_price=ltp,
                                    open=float(res.get("open") or ltp),
                                    high=float(res.get("high") or ltp),
                                    low=float(res.get("low") or ltp),
                                    close=close,
                                    volume=int(res.get("volume") or 0),
                                    change=round(change, 2),
                                    change_pct=round(change_pct, 2),
                                )
                except Exception:
                    pass

            if quote_obj is None:
                from market.quotes import get_quote as _mkt_quote

                raw_q = _mkt_quote(f"{exchange}:{clean_sym}")
                if isinstance(raw_q, dict):
                    quote_obj = raw_q.get(f"{exchange}:{clean_sym}") or (
                        next(iter(raw_q.values())) if raw_q else None
                    )
                elif isinstance(raw_q, Quote):
                    quote_obj = raw_q

            if quote_obj is None:
                quote_obj = Quote(symbol=clean_sym, last_price=0.0)

            quotes[inst] = quote_obj

        if is_single:
            return quotes[instruments]
        return quotes

    def get_options_chain(
        self,
        underlying: str,
        expiry: Optional[str] = None,
    ) -> list[OptionsContract]:
        """m.Stock Type B does not have a dedicated options chain endpoint; fall back to market engine."""
        raise NotImplementedError("m.Stock Type B does not provide options chain API; use market scraper")

    def get_history(
        self,
        symbol: str,
        resolution: str = "D",
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ):
        """
        Fetch historical OHLCV data.
        Maps resolution to m.Stock Type B intervals (ONE_DAY, ONE_MINUTE, etc.)
        when token is mapped, or smoothly falls back to Chanakya's historical engine.
        """
        import pandas as pd

        clean_sym = symbol.replace("NSE:", "").replace("BSE:", "")
        exchange = "BSE" if symbol.startswith("BSE:") else "NSE"
        token = _KNOWN_NSE_TOKENS.get(clean_sym, "")

        interval_map = {
            "D": "ONE_DAY",
            "1D": "ONE_DAY",
            "1": "ONE_MINUTE",
            "1m": "ONE_MINUTE",
            "5": "FIVE_MINUTE",
            "5m": "FIVE_MINUTE",
            "15": "FIFTEEN_MINUTE",
            "15m": "FIFTEEN_MINUTE",
            "60": "ONE_HOUR",
            "1h": "ONE_HOUR",
        }
        interval = interval_map.get(str(resolution).upper(), "ONE_DAY")

        if self._token and token:
            try:
                url = f"{MSTOCK_BASE_URL}/openapi/typeb/instruments/historical"
                f_date = from_date.strftime("%Y-%m-%d %H:%M") if from_date else "2024-01-01 09:15"
                t_date = (
                    to_date.strftime("%Y-%m-%d %H:%M")
                    if to_date
                    else datetime.now().strftime("%Y-%m-%d %H:%M")
                )
                h_payload = json.dumps(
                    {
                        "exchange": exchange,
                        "symboltoken": token,
                        "interval": interval,
                        "fromdate": f_date,
                        "todate": t_date,
                    }
                )
                resp = self._client.request("GET", url, content=h_payload, headers=self._headers())
                if resp.status_code == 200:
                    data = resp.json()
                    candles = (
                        data.get("data", {}).get("candles", [])
                        if isinstance(data.get("data"), dict)
                        else []
                    )
                    if candles:
                        df = pd.DataFrame(
                            candles,
                            columns=["timestamp", "open", "high", "low", "close", "volume"],
                        )
                        df["timestamp"] = pd.to_datetime(df["timestamp"])
                        df.set_index("timestamp", inplace=True)
                        df.index = df.index.tz_localize(None)
                        return df
            except Exception:
                pass

        from market.quotes import get_historical_data

        return get_historical_data(
            symbol, resolution=resolution, from_date=from_date, to_date=to_date
        )

    # ── Order Execution ───────────────────────────────────────

    def place_order(self, order: OrderRequest) -> OrderResponse:
        """
        Place an order through m.Stock.
        Strictly enforces the live trading gate ALLOW_LIVE_TRADING=1.
        """
        if os.environ.get("ALLOW_LIVE_TRADING", "0") != "1":
            raise PermissionError(
                "Live trading disabled. Set ALLOW_LIVE_TRADING=1 to execute live orders with m.Stock."
            )

        if not self._token:
            raise RuntimeError(
                "m.Stock session not authenticated. Please log in before placing orders."
            )

        try:
            url = f"{MSTOCK_BASE_URL}/openapi/typeb/orders/regular"
            payload = {
                "symbol": order.symbol,
                "exchange": _EXCHANGE_MAP.get(order.exchange, "NSE"),
                "transactionType": order.transaction_type,
                "orderType": _ORDER_TYPE_MAP.get(order.order_type, "MARKET"),
                "product": _PRODUCT_MAP.get(order.product, "CNC"),
                "quantity": order.quantity,
                "price": order.price,
                "triggerPrice": order.trigger_price or 0.0,
            }
            resp = self._client.post(url, json=payload, headers=self._headers())
            if resp.status_code == 200:
                data = resp.json()
                res = data.get("data") or data.get("result") or data
                order_id = str(res.get("orderId") or res.get("order_id") or "")
                if order_id:
                    return OrderResponse(
                        order_id=order_id,
                        status="PLACED",
                        message="Order placed successfully with m.Stock",
                        average_price=order.price,
                        filled_quantity=order.quantity,
                    )
            raise RuntimeError(f"m.Stock order placement failed: {resp.text}")
        except Exception as e:
            if isinstance(e, PermissionError):
                raise
            raise RuntimeError(f"Failed to place order with m.Stock: {e}")

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        if os.environ.get("ALLOW_LIVE_TRADING", "0") != "1":
            raise PermissionError("Live trading disabled. Set ALLOW_LIVE_TRADING=1.")

        if not self._token:
            return False

        try:
            url = f"{MSTOCK_BASE_URL}/openapi/typeb/orders/regular/{order_id}"
            resp = self._client.delete(url, headers=self._headers())
            return resp.status_code in (200, 204)
        except Exception:
            return False

    def get_orders(self) -> list[Order]:
        """Return orders placed today."""
        if not self._token:
            return []
        try:
            url = f"{MSTOCK_BASE_URL}/openapi/typeb/orders"
            resp = self._client.get(url, headers=self._headers())
            if resp.status_code == 200:
                raw = resp.json().get("data") or resp.json().get("result", resp.json())
                if isinstance(raw, dict):
                    raw = raw.get("orders", [])
                if not isinstance(raw, list):
                    raw = []
                orders = []
                for o in raw:
                    orders.append(
                        Order(
                            order_id=str(o.get("orderId") or o.get("order_id")),
                            symbol=o.get("symbol", ""),
                            exchange=o.get("exchange", "NSE"),
                            transaction_type=o.get("transactionType", "BUY"),
                            order_type=o.get("orderType", "LIMIT"),
                            product=o.get("product", "CNC"),
                            quantity=int(o.get("quantity", 0)),
                            price=float(o.get("price", 0.0)),
                            status=o.get("status", "OPEN"),
                            filled_quantity=int(o.get("filledQuantity", 0)),
                        )
                    )
                return orders
        except Exception:
            pass
        return []
