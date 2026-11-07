"""
market/fyers_tbt_manager.py
───────────────────────────
Fyers Institutional 50-Level Depth (Tick-By-Tick / TBT) Manager.

Manages high-frequency 50-level Depth of Market (DOM) streams using Fyers
TBT WebSocket (`fyers_apiv3.FyersWebsocket.tbt_ws.FyersTbtSocket`).

Features:
- Dynamic subscription to active Index Options / Target Stock Contracts
- 50-slot Order Book Imbalance (OBI-50) calculation
- Institutional Iceberg / Resting Liquidity Wall detection
- Book Density & Liquidity Quality scoring
- Pre-Trade VWAP Slippage modeling through 50 price levels
- Deep Order Book Audit Gatekeeper for setup conviction
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime, time as dtime, timedelta
from importlib import import_module
import logging
import math
import os
import threading
import time
from typing import Any, Callable, Optional, Set

from engine.ring_buffer import RollingTickBuffer
from config.discovery_policy import get_discovery_policy

logger = logging.getLogger("market.fyers_tbt")

# -- SDK availability sentinel: checked ONCE at process start, never repeated.
# Prevents 80+ repeated 'fyers_apiv3 not installed' P2 incidents per session.
# RCA: INC-001 2026-10-30 -- 81 repetitions masking real P2s in OPS deck.
_FYERS_APIV3_AVAILABLE: bool | None = None
_FYERS_SDK_CHECK_LOCK = threading.Lock()
TBT_LIVE_DEPTH_MAX_AGE_SECONDS = 15.0


def is_fresh_tbt_depth(snapshot: dict[str, Any], *, now: Optional[float] = None) -> bool:
    """Only a recent local packet receipt can qualify a depth snapshot as live."""
    if snapshot.get("status") != "LIVE":
        return False
    try:
        received_at = float(snapshot["received_at"])
        age = (time.time() if now is None else now) - received_at
    except (KeyError, TypeError, ValueError):
        return False
    return math.isfinite(age) and 0 <= age <= TBT_LIVE_DEPTH_MAX_AGE_SECONDS


def _is_fyers_sdk_available() -> bool:
    """Check fyers_apiv3 SDK installation. Result cached after first call."""
    global _FYERS_APIV3_AVAILABLE
    with _FYERS_SDK_CHECK_LOCK:
        if _FYERS_APIV3_AVAILABLE is not None:
            return _FYERS_APIV3_AVAILABLE
        try:
            # A top-level package import does not check WebSocket dependencies.
            module = import_module("fyers_apiv3.FyersWebsocket.tbt_ws")
            if not callable(getattr(module, "FyersTbtSocket", None)):
                raise ImportError("FyersTbtSocket is unavailable")
            _FYERS_APIV3_AVAILABLE = True
        except Exception as exc:
            _FYERS_APIV3_AVAILABLE = False
            logger.warning(
                "[TbtManager] Fyers TBT transport dependencies unavailable (%s) -- "
                "TBT 50-level depth WebSocket PERMANENTLY UNAVAILABLE this session. "
                "Qualify the optional Fyers dependency profile before enabling TBT.",
                exc,
            )
    return _FYERS_APIV3_AVAILABLE


MAX_TBT_SYMBOLS = 15
MAX_SYMBOLS_PER_WORKER = (
    5  # Fyers API physical hard limit: at most 5 active symbols per WebSocket connection
)
RESERVED_ANCHOR_SLOTS = 3  # Slots 0..2: NIFTY, BANKNIFTY, MIDCPNIFTY near-month futures
MAX_DYNAMIC_SLOTS = 12  # Slots 3..14: 100% elastic demand-driven slots
MAX_CORE_GRID_SLOTS = 8  # 3 anchor futures + up to 5 focused asset contracts
MAX_TODAYS_EXPIRY_SLOTS = 4
MAX_SCOUT_SLOTS = 12  # Elastic scout capacity: utilizes all unallocated dynamic slots
MIN_SCOUT_DWELL_SECONDS = 10.0  # Anti-thrashing minimum dwell time before idle eviction


from functools import lru_cache


@lru_cache(maxsize=512)
def _resolve_index_future_memo(
    index_name: str, ref_day: Optional[tuple[int, int, int]] = None
) -> str:
    from market.contract_selection import get_listed_contracts
    from config.constants import IST

    now = datetime.now(IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    if ref_day is not None:
        now = now.replace(year=ref_day[0], month=ref_day[1], day=ref_day[2])
    futures = [
        c
        for c in get_listed_contracts(index_name, as_of=now)
        if c.option_type == "FUT" and c.symbol.startswith("NSE:")
    ]
    return futures[0].symbol if futures else ""


def _resolve_index_future(index_name: str, ref_date: Optional[date] = None) -> str:
    """Resolve spot index name to the active near-month tradable Index Future."""
    ref_day = (ref_date.year, ref_date.month, ref_date.day) if ref_date is not None else None
    return _resolve_index_future_memo(index_name, ref_day)


@lru_cache(maxsize=512)
def _resolve_stock_future_memo(clean: str, ref_day: Optional[tuple[int, int, int]] = None) -> str:
    return _resolve_index_future_memo(clean, ref_day)


def resolve_stock_future(symbol: str, ref_date: Optional[date] = None) -> str:
    """
    Resolve any stock symbol to its active near-month Fyers Stock Future.
    E.g. 'RELIANCE', 'NSE:RELIANCE-EQ', 'BAJFINANCE' -> 'NSE:RELIANCE26NOVFUT'
    Returns empty string if not an eligible F&O stock or resolution fails.
    """
    from config.discovery_policy import allows_context_symbol
    from market.instruments import canonical_symbol

    if not isinstance(symbol, str) or not symbol.strip():
        return ""
    clean = canonical_symbol(symbol)
    if not allows_context_symbol(f"NSE:{clean}"):
        return ""
    ref_day = (ref_date.year, ref_date.month, ref_date.day) if ref_date is not None else None
    return _resolve_stock_future_memo(clean, ref_day)


def _tbt_symbol_priority(
    symbol: str,
    session: Optional[str] = None,
    ref_time: Optional[dtime] = None,
    primary_focus: Optional[str] = None,
) -> int:
    """
    Score symbol priority for 15-slot TBT depth allocation.
    Institutional Hierarchy:
      - Commodity/Evening Session (COMMODITY_CDS: 15:30 - 23:30 IST):
          Active MCX Options (75), MCX Futures (70), Commodities (65), USDINR (62 before 17:00, 5 post 17:00)
          are dynamically elevated above closed equity/index instruments.
      - Primary Focus Dynamic Elevation:
          When a specific stock or index is in primary focus (e.g. RELIANCE, TCS), its options (65)
          and futures (50) are dynamically elevated above generic index options to guarantee depth allocation.
      - Daytime Session (EQUITY_NFO: 09:15 - 15:30 IST) & Default:
          Core 4 Index Options (60..45), Index Futures (45..38), Stock Options (28), Stock Futures (22),
          Commodities (30), Cash Equities (10). Deprecated non-weekly indices (FINNIFTY/BANKEX) demoted to lowest.
    """
    if not symbol:
        return 0
    s = symbol.upper().strip()
    is_option = s.endswith("CE") or s.endswith("PE")
    is_fut = s.endswith("FUT")
    is_mcx = s.startswith("MCX:") or any(
        c in s for c in ("CRUDE", "NATURAL", "GOLD", "SILVER", "COPPER", "ZINC", "ALUMINIUM")
    )
    is_cds = s.startswith("NSE:USDINR") or "USDINR" in s

    sess = session or get_market_session()

    # ── Evening Session (COMMODITY_CDS: 15:30 - 23:30 IST) ─────────────
    # Dynamically elevate active MCX commodities above closed daytime equities.
    if sess == "COMMODITY_CDS":
        if is_option and is_mcx:
            return 75  # Live MCX Commodity Option
        if is_fut and is_mcx:
            return 70  # Live MCX Commodity Future
        if is_mcx:
            return 65  # Live Commodity
        if is_cds:
            if ref_time is not None:
                return 62 if ref_time < dtime(17, 0) else 5
            try:
                from config.constants import IST_ZONE as IST

                now_t = datetime.now(IST).time()
            except Exception:
                now_t = datetime.now().time()
            return 62 if now_t < dtime(17, 0) else 5

    # ── Primary Focus Dynamic Elevation ────────────────────────────────
    if primary_focus and not get_discovery_policy().fno_only:
        pf = (
            primary_focus.upper().replace("NSE:", "").replace("BSE:", "").replace("-EQ", "").strip()
        )
        if pf and pf not in ("NIFTY", "BANKNIFTY", "MIDCPNIFTY", "SENSEX", "FINNIFTY"):
            # Single-Stock F&O Focus (e.g. RELIANCE, TCS, INFY)
            if f":{pf}" in s or s.startswith(f"NSE:{pf}") or s.startswith(pf):
                if is_option:
                    return 65  # Focused Stock Option elevated above generic NIFTY (60)
                if is_fut:
                    return 50  # Focused Stock Future elevated above generic NIFTY Future (45)

    # ── Daytime Session (EQUITY_NFO: 09:15 - 15:30 IST) & Standard Hierarchy ────
    # Core 4 Index Options (NIFTY, BANKNIFTY, MIDCPNIFTY, SENSEX) & High-Conviction Stock Options
    if is_option:
        if "NIFTY" in s and "BANK" not in s and "MID" not in s and "FIN" not in s:
            return 60  # NIFTY Option
        if "BANKNIFTY" in s:
            return 55  # BANKNIFTY Option
        if "MIDCPNIFTY" in s or "MIDCAP" in s:
            return 50  # MIDCPNIFTY Option
        if "SENSEX" in s:
            return 45  # SENSEX Option
        if "FINNIFTY" in s or "BANKEX" in s:
            return 35  # Deprecated non-weekly index options
        if is_mcx:
            return 32  # Commodity Option
        return 28  # High-Conviction Stock Option

    # Futures
    if is_fut:
        if "NIFTY" in s and "BANK" not in s and "MID" not in s and "FIN" not in s:
            return 45  # NIFTY Future
        if "BANKNIFTY" in s:
            return 42  # BANKNIFTY Future
        if "MIDCPNIFTY" in s:
            return 40  # MIDCPNIFTY Future
        if "SENSEX" in s:
            return 38  # SENSEX Future
        if "FINNIFTY" in s or "BANKEX" in s:
            return 25  # Deprecated index futures
        if is_mcx or is_cds:
            return 32  # Commodity / Currency Future
        return 22  # High-Conviction Stock Future

    # Commodities / Currencies
    if is_mcx or is_cds:
        return 30

    # Cash Equities
    return 10


def resolve_tradable_tbt_symbol(symbol: str) -> str:
    """
    Ensure symbol has an order book before sending to Fyers TBT WebSocket.
    Spot indices (-INDEX) lack market depth and trigger INDEX_DEPTH_ERROR_MESSAGE.
    Converts spot indices to their active tradable Index Futures.

    CRITICAL ARCHITECTURAL INVARIANT:
    Fyers API v3 Versova TBT WebSocket (50-depth) strictly supports NSE (Equity CM)
    and NFO (NSE Futures & Options). BSE and MCX are NOT supported on Fyers TBT
    and must be routed through L2 5-depth (FyersDataSocket).
    Any non-NSE or malformed symbol (e.g. spaces) is rejected from TBT.
    """
    if not symbol or not isinstance(symbol, str):
        return ""
    clean = symbol.strip()
    if not clean or " " in clean or "\t" in clean or "\n" in clean:
        return ""

    # Reject crypto
    clean_up = clean.upper()
    if (
        clean_up.startswith("CRYPTO:")
        or clean_up.endswith("USDT")
        or clean_up in ("BTC", "ETH", "SOL", "BNB", "DOGE", "XRP")
    ):
        return ""

    from brokers.fyers import _to_fyers_symbol
    from market.ws_subscription_manager import is_valid_ws_symbol

    fyers_sym = _to_fyers_symbol(clean)
    if not fyers_sym:
        return ""

    if "-INDEX" in fyers_sym:
        clean_idx = fyers_sym.split(":")[-1].replace("-INDEX", "")
        fyers_sym = _resolve_index_future(clean_idx)

    # Validate structural syntax (no unnormalized hyphens, valid option format)
    if not is_valid_ws_symbol(fyers_sym):
        return ""

    return fyers_sym


def is_tbt_eligible_symbol(symbol: str) -> bool:
    """
    Check if a symbol is eligible for Fyers Versova 50-Depth TBT streaming.
    Fyers API v3 Versova TBT WebSocket (50-depth) strictly supports NSE (Equity CM)
    and NFO (NSE Futures & Options). BSE and MCX are NOT supported on Fyers TBT
    and must be routed through L2 5-depth (FyersDataSocket).
    Any non-NSE or malformed symbol (e.g. spaces) is rejected from TBT.
    """
    if not symbol or not isinstance(symbol, str):
        return False
    clean = symbol.strip()
    if not clean or " " in clean or "\t" in clean or "\n" in clean:
        return False
    from market.ws_subscription_manager import is_valid_ws_symbol

    if not is_valid_ws_symbol(clean):
        return False
    return clean.startswith("NSE:")


def get_market_session() -> str:
    """
    Determine the current active market session in IST:
      - 'EQUITY_NFO'   : 09:15 - 15:30 IST (Mon-Fri)
      - 'COMMODITY_CDS': 15:30 - 23:30 IST (Mon-Fri)
      - 'OFF_MARKET'   : Nights / Weekends
    """
    try:
        from config.constants import IST_ZONE as IST

        now = datetime.now(IST)
    except Exception:
        now = datetime.now()

    if now.weekday() >= 5:  # Saturday or Sunday
        return "OFF_MARKET"

    t = now.time()
    if dtime(9, 15) <= t < dtime(15, 30):
        return "EQUITY_NFO"
    elif dtime(15, 30) <= t <= dtime(23, 30):
        return "COMMODITY_CDS"
    return "OFF_MARKET"


def get_default_core_grid(
    session: str = "AUTO",
    primary_focus: Optional[str] = None,
    ref_time: Optional[dtime] = None,
) -> tuple[list[str], list[str]]:
    """
    Build default (core_grid, todays_expiry) for the active session.
    Guarantees that index options or MCX commodities are immediately available on TBT.
    Supports dynamic primary_focus to revolve multi-strike ATM/OTM options for an active index.
    """
    if get_discovery_policy().fno_only:
        if session == "AUTO":
            session = get_market_session()
        if session != "EQUITY_NFO":
            return [], []
    if session == "AUTO":
        from market.instruments import STANDARD_LOT_SIZES

        clean_focus = (
            (primary_focus or "")
            .upper()
            .replace("NSE:", "")
            .replace("BSE:", "")
            .replace("-EQ", "")
            .strip()
        )
        if clean_focus and (
            clean_focus in ("NIFTY", "BANKNIFTY", "MIDCPNIFTY", "SENSEX", "FINNIFTY")
            or clean_focus in STANDARD_LOT_SIZES
        ):
            session = "EQUITY_NFO"
        else:
            session = get_market_session()

    from config.constants import IST

    now = datetime.now(IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    if ref_time is not None:
        now = now.replace(hour=ref_time.hour, minute=ref_time.minute, second=ref_time.second)

    if session in ("EQUITY_NFO", "OFF_MARKET"):
        from market.contract_selection import get_subscription_option_grid
        from market.instruments import canonical_symbol

        core = [
            s
            for s in (
                _resolve_index_future("NIFTY", ref_date=now.date()),
                _resolve_index_future("BANKNIFTY", ref_date=now.date()),
                _resolve_index_future("MIDCPNIFTY", ref_date=now.date()),
            )
            if s
        ]
        focus = canonical_symbol(primary_focus or "")
        if focus:
            focused_future = _resolve_index_future(focus, ref_date=now.date())
            if focused_future and focused_future not in core:
                core.append(focused_future)
            # The Versova TBT transport does not support BSE. BSE contracts stay
            # on the separately managed Data Socket/depth path.
            options = [
                s
                for s in get_subscription_option_grid(
                    focus,
                    strikes_per_side=1,
                    max_expiries=1,
                    as_of=now if ref_time is not None else None,
                )
                if s.startswith("NSE:")
            ]
            core.extend(options)
        return list(dict.fromkeys(core)), []
    else:
        # Evening (15:30 - 23:30 IST): MCX Commodities & Currency CDS
        from brokers.fyers import _resolve_commodity_contract, _resolve_currency_contract

        crude_fut = _resolve_commodity_contract("CRUDEOIL")
        core = [
            crude_fut,
            _resolve_commodity_contract("NATURALGAS"),
            _resolve_commodity_contract("GOLD"),
            _resolve_commodity_contract("SILVER"),
        ]
        try:
            from market.quotes import get_ltp

            c_ltp = get_ltp("MCX:CRUDEOIL") or 6500.0
            c_atm = int(round(c_ltp / 50.0) * 50)
            # Crude Oil options expire ~2 business days before futures; roll on day 15 to guarantee active front-month options.
            c_dt = now if now.day <= 15 else now + timedelta(days=20)
            c_suffix = c_dt.strftime("%y%b").upper()
            core.extend(
                [
                    f"MCX:CRUDEOIL{c_suffix}{c_atm}CE",
                    f"MCX:CRUDEOIL{c_suffix}{c_atm}PE",
                ]
            )
        except Exception:
            core.extend(
                [
                    _resolve_commodity_contract("COPPER"),
                    _resolve_commodity_contract("ZINC"),
                ]
            )

        # Currency derivatives (CDS) trade 09:00 - 17:00 IST.
        # After 17:00 IST, CDS is CLOSED. Never keep reserve for closed currency!
        # Allocate 100% of evening slots to active MCX base metals (COPPER, ZINC, ALUMINIUM).
        try:
            from config.constants import IST_ZONE as IST

            check_t = ref_time or datetime.now(IST).time()
        except Exception:
            check_t = ref_time or now.time()

        if check_t < dtime(17, 0):
            todays_exp = [
                _resolve_currency_contract("USDINR"),
                _resolve_commodity_contract("COPPER"),
                _resolve_commodity_contract("ZINC"),
            ]
        else:
            todays_exp = [
                _resolve_commodity_contract("COPPER"),
                _resolve_commodity_contract("ZINC"),
                _resolve_commodity_contract("ALUMINIUM"),
            ]
        return core[:MAX_CORE_GRID_SLOTS], todays_exp[:MAX_TODAYS_EXPIRY_SLOTS]


class TbtSocketWorker:
    """
    Worker managing a single concurrent Fyers TBT WebSocket connection.
    Fyers Prime allows up to 3 concurrent connections, each holding up to 5 symbols (total 15).
    """

    def __init__(
        self,
        worker_id: int,
        auth_token_getter: Callable[[], str],
        on_depth: Callable[[str, Any], None],
        on_status: Callable[[int, str], None],
    ) -> None:
        self.worker_id = worker_id
        self._auth_token_getter = auth_token_getter
        self._on_depth = on_depth
        self._on_status = on_status
        self.ws: Any = None
        self.connected: bool = False
        self.status: str = "DISCONNECTED"  # DISCONNECTED, CONNECTING, CONNECTED, DEGRADED_429
        self.subscribed: set[str] = set()
        self.desired: list[str] = []
        self._channel_symbols: dict[str, set[str]] = {"1": set()}
        self.last_connected_at: float = 0.0
        self.last_packet_at: float = 0.0
        self.degraded_until: float = 0.0
        self._consecutive_429: int = 0
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def connect(self) -> None:
        with self._lock:
            if self.connected or self.status == "CONNECTING":
                return
            if time.time() < self.degraded_until:
                logger.debug(
                    f"[TbtWorker-{self.worker_id}] In backoff cooldown until {self.degraded_until:.0f}"
                )
                return
            self.status = "CONNECTING"
            self._thread = threading.Thread(
                target=self._do_connect, daemon=True, name=f"tbt-worker-{self.worker_id}"
            )
            self._thread.start()

    def _do_connect(self) -> None:
        try:
            import market.fyers_socket_patch  # noqa: F401 - ensure patches are applied
            from fyers_apiv3.FyersWebsocket.tbt_ws import FyersTbtSocket

            token = self._auth_token_getter()
            if not token:
                with self._lock:
                    self.status = "DISCONNECTED"
                return

            self.ws = FyersTbtSocket(
                access_token=token,
                on_depth_update=self._handle_depth,
                on_error_message=self._on_server_error,
                on_connect=self._on_connect,
                on_open=self._on_connect,
                on_close=self._on_close,
                on_error=self._on_error,
                reconnect=False,  # Autonomous control: prevent Fyers SDK uncontrolled 5s hammer loops
            )
            self.ws.onopen = self._on_connect
            self.ws.background_flag = True
            self.ws.connect()
        except ImportError:
            with self._lock:
                self.status = "UNAVAILABLE"
            # SDK absence logged once per session by _is_fyers_sdk_available().
            # Suppress per-worker repeats -- INC-001 RCA 2026-10-30.
            logger.debug(f"[TbtWorker-{self.worker_id}] fyers_apiv3 unavailable (already logged)")
        except Exception as e:
            logger.warning(f"[TbtWorker-{self.worker_id}] Connect exception: {e}")
            with self._lock:
                self.status = "DISCONNECTED"
                self.connected = False

    def _handle_depth(self, symbol: str, depth_obj: Any) -> None:
        self.last_packet_at = time.time()
        self._on_depth(symbol, depth_obj)

    def _on_connect(self, *args, **kwargs) -> None:
        with self._lock:
            self.connected = True
            self.status = "CONNECTED"
            self.last_connected_at = time.time()
            self._consecutive_429 = 0
        logger.info(
            f"[TbtWorker-{self.worker_id}] Connection confirmed. Synchronizing {len(self.desired)} symbols..."
        )
        self.sync()
        self._on_status(self.worker_id, "CONNECTED")

    def _on_server_error(self, message: str) -> None:
        logger.warning(f"[TbtWorker-{self.worker_id}] Fyers server error: {message}")
        if "symbol count exceeds limit" in str(message).lower():
            logger.info(
                f"[TbtWorker-{self.worker_id}] Server symbol limit exceeded; closing socket to clear server-side channels cleanly..."
            )
            with self._lock:
                ws_to_close = self.ws
                self.ws = None
                self.connected = False
                self._channel_symbols = {"1": set()}
                self.degraded_until = time.time() + 5.0
            if ws_to_close:
                try:
                    setattr(ws_to_close, "restart_flag", False)
                    if hasattr(ws_to_close, "close_connection"):
                        ws_to_close.close_connection()
                    elif hasattr(ws_to_close, "close"):
                        ws_to_close.close()
                except Exception as e_close:
                    logger.debug(f"[TbtWorker-{self.worker_id}] Socket teardown error: {e_close}")

    def _on_close(self, *args, **kwargs) -> None:
        with self._lock:
            self.connected = False
            self._channel_symbols = {"1": set()}
            if self.status != "DEGRADED_429":
                self.status = "DISCONNECTED"
        logger.info(f"[TbtWorker-{self.worker_id}] Disconnected")
        self._on_status(self.worker_id, self.status)

    def _on_error(self, err: Any, *args, **kwargs) -> None:
        err_msg = str(err)
        if "429" in err_msg or "Too Many Requests" in err_msg:
            with self._lock:
                self._consecutive_429 += 1
                # Standard exponential backoff (60s, 120s, 240s, max 300s)
                cooldown = min(60.0 * (2 ** (self._consecutive_429 - 1)), 300.0)
                self.status = "DEGRADED_429"
                self.degraded_until = time.time() + cooldown
                self.connected = False
                ws_to_close = self.ws
                self.ws = None

            if ws_to_close:
                try:
                    setattr(ws_to_close, "restart_flag", False)
                    if hasattr(ws_to_close, "close_connection"):
                        ws_to_close.close_connection()
                    elif hasattr(ws_to_close, "close"):
                        ws_to_close.close()
                except Exception as e_close:
                    logger.debug(
                        f"[TbtWorker-{self.worker_id}] Error socket close suppressed: {e_close}"
                    )

            if self.worker_id > 0:
                logger.info(
                    f"[TbtWorker-{self.worker_id}] Fyers single-user account limit active (429 connection cap). "
                    f"Secondary worker quiescent; primary worker (Worker-0) multiplexes all 15 symbols across channels 1..3."
                )
            elif self._consecutive_429 <= 2:
                logger.warning(
                    f"[TbtWorker-{self.worker_id}] Handshake 429 Too Many Requests (Fyers connection cap/throttle). "
                    f"Backing off for {cooldown:.0f}s (strike {self._consecutive_429})."
                )
            else:
                logger.info(
                    f"[TbtWorker-{self.worker_id}] Connection cap active (429 rate limit). Cooldown: {cooldown:.0f}s (strike {self._consecutive_429})."
                )
            self._on_status(self.worker_id, "DEGRADED_429")
        else:
            logger.debug(f"[TbtWorker-{self.worker_id}] Socket message: {err}")

    def sync(self) -> None:
        with self._lock:
            if not self.connected or not self.ws:
                return
            # Strict per-connection invariant: Never attempt > 5 symbols on a single WebSocket connection!
            desired_list = [
                s for s in self.desired[:MAX_SYMBOLS_PER_WORKER] if is_tbt_eligible_symbol(s)
            ]
            desired_set = set(desired_list)

            try:
                from fyers_apiv3.FyersWebsocket.tbt_ws import SubscriptionModes
            except ImportError:

                class SubscriptionModes:
                    DEPTH = "DEPTH"

            ch = "1"
            target_syms = desired_set
            current_syms = set(self._channel_symbols.get(ch, set()))

            to_unsub = current_syms - target_syms
            if to_unsub:
                try:
                    self.ws.unsubscribe(
                        symbol_tickers=set(to_unsub),
                        channelNo=ch,
                        mode=SubscriptionModes.DEPTH,
                    )
                    logger.info(
                        f"[TbtWorker-{self.worker_id}] Unsubscribed {len(to_unsub)} symbols from ch {ch}: {to_unsub}"
                    )
                except Exception as e:
                    logger.debug(f"[TbtWorker-{self.worker_id}] Unsubscribe failed on ch {ch}: {e}")

            to_sub = target_syms - current_syms
            if to_sub:
                try:
                    self.ws.subscribe(
                        symbol_tickers=set(to_sub),
                        channelNo=ch,
                        mode=SubscriptionModes.DEPTH,
                    )
                    logger.info(
                        f"[TbtWorker-{self.worker_id}] Subscribed {len(to_sub)} symbols to ch {ch}: {to_sub}"
                    )
                except Exception as e:
                    logger.debug(f"[TbtWorker-{self.worker_id}] Subscribe failed on ch {ch}: {e}")

            self._channel_symbols[ch] = target_syms
            self.subscribed = desired_set

            if hasattr(self.ws, "switchChannel") and self.subscribed:
                try:
                    self.ws.switchChannel(resume_channels={"1"}, pause_channels=set())
                except Exception as e:
                    logger.debug(f"[TbtWorker-{self.worker_id}] switchChannel failed: {e}")

    def unsubscribe(self, symbols: set[str] | list[str]) -> None:
        with self._lock:
            sym_set = set(symbols)
            to_remove = self.subscribed.intersection(sym_set)
            if to_remove:
                self.subscribed.difference_update(to_remove)
                self.desired = [s for s in self.desired if s not in to_remove]
                to_remove_tbt = {s for s in to_remove if is_tbt_eligible_symbol(s)}
                if self.connected and self.ws and to_remove_tbt:
                    try:
                        from fyers_apiv3.FyersWebsocket.tbt_ws import SubscriptionModes
                    except ImportError:

                        class SubscriptionModes:
                            DEPTH = "DEPTH"

                    try:
                        ch = "1"
                        in_ch = self._channel_symbols.get(ch, set()).intersection(to_remove_tbt)
                        if in_ch:
                            self._channel_symbols[ch].difference_update(in_ch)
                            self.ws.unsubscribe(
                                symbol_tickers=set(in_ch),
                                channelNo=ch,
                                mode=SubscriptionModes.DEPTH,
                            )
                    except Exception as e:
                        logger.debug(f"[TbtWorker-{self.worker_id}] Unsubscribe error: {e}")

    def close(self) -> None:
        with self._lock:
            self.connected = False
            self.status = "DISCONNECTED"
            self.desired = []
            self.subscribed.clear()
            ws_to_close = self.ws
            self.ws = None

        if ws_to_close:
            try:
                setattr(ws_to_close, "restart_flag", False)
                if hasattr(ws_to_close, "close_connection"):
                    ws_to_close.close_connection()
                elif hasattr(ws_to_close, "close"):
                    ws_to_close.close()
            except Exception as e:
                logger.debug(f"[TbtWorker-{self.worker_id}] Close error: {e}")

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "worker_id": self.worker_id,
                "status": self.status,
                "connected": self.connected,
                "subscribed_count": len(self.subscribed),
                "subscribed_symbols": sorted(self.subscribed),
                "desired_count": len(self.desired),
                "last_connected_at": self.last_connected_at,
                "last_packet_at": self.last_packet_at,
                "degraded_until": self.degraded_until,
            }


def build_sentinel_decision_intel(depth_data: dict[str, Any]) -> dict[str, Any]:
    """
    Translates raw Level-3 market depth signals (Fortress Walls, Spoof Traps, OBI-50)
    into plain, decisive institutional trading intelligence.
    Explains the exact microstructure event and gives concrete trading rules (Bull / Bear / Neutral).
    """
    if not isinstance(depth_data, dict):
        depth_data = {}

    fortress_bid = bool(depth_data.get("fortress_bid_wall_confirmed", False))
    fortress_ask = bool(depth_data.get("fortress_ask_wall_confirmed", False))
    spoof_warning = depth_data.get("spoof_trap_warning")
    bid_spoof = bool(depth_data.get("fleeing_bid_wall_detected", False)) or (
        bool(spoof_warning and "BID_SPOOF" in str(spoof_warning))
    )
    ask_spoof = bool(depth_data.get("fleeing_ask_wall_detected", False)) or (
        bool(spoof_warning and "ASK_SPOOF" in str(spoof_warning))
    )

    strongest_bid = (
        depth_data.get("strongest_bid_wall") or depth_data.get("active_fortress_bid") or {}
    )
    strongest_ask = (
        depth_data.get("strongest_ask_wall") or depth_data.get("active_fortress_ask") or {}
    )
    flee_evt = depth_data.get("recent_fleeing_event") or {}

    obi = float(depth_data.get("obi_50", 0.0) or 0.0)
    density = float(depth_data.get("density_score", 0.0) or 0.0)

    # 1. Bid Spoof Detected (Bull Trap / Rugpull Risk)
    if bid_spoof:
        f_p = flee_evt.get("price") or strongest_bid.get("price")
        f_q = flee_evt.get("qty") or strongest_bid.get("qty")
        price_txt = f" near ₹{float(f_p):,.2f}" if f_p else ""
        qty_txt = f" ({int(f_q):,} lots)" if f_q else ""
        return {
            "bias": "CAUTION_BEAR",
            "badge": "⚠️ BULL TRAP / RUGPULL RISK",
            "tag": "BID SPOOF",
            "color": "rose",
            "headline": f"Fake Bids Pulled{price_txt}",
            "meaning": f"A massive resting buy wall{qty_txt} vanished the moment price approached{price_txt}. This was deceptive liquidity intended to lure retail buyers into long positions.",
            "decision": "DO NOT CHASE LONGS. High probability of a swift downward dump now that fake support is gone. Wait for real absorption or look for put entries.",
            "wall_price": float(f_p) if f_p else None,
            "wall_qty": int(f_q) if f_q else None,
            "book_share_pct": None,
            "duration_seconds": None,
        }

    # 2. Ask Spoof Detected (Bear Trap / Short Squeeze Fuel)
    if ask_spoof:
        f_p = flee_evt.get("price") or strongest_ask.get("price")
        f_q = flee_evt.get("qty") or strongest_ask.get("qty")
        price_txt = f" near ₹{float(f_p):,.2f}" if f_p else ""
        qty_txt = f" ({int(f_q):,} lots)" if f_q else ""
        return {
            "bias": "BULLISH",
            "badge": "🚀 BEAR TRAP / SHORT SQUEEZE",
            "tag": "ASK SPOOF",
            "color": "emerald",
            "headline": f"Fake Asks Pulled{price_txt}",
            "meaning": f"A large resting sell wall{qty_txt} vanished as price approached{price_txt}. Bluffing short sellers cancelled, removing overhead resistance.",
            "decision": "FAVOR LONGS / CALLS. The overhead ceiling was an illusion. Expect accelerated upward breakout as trapped shorts are forced to cover.",
            "wall_price": float(f_p) if f_p else None,
            "wall_qty": int(f_q) if f_q else None,
            "book_share_pct": None,
            "duration_seconds": None,
        }

    # 3. Fortress Bid Wall Confirmed (Institutional Demand Floor)
    if fortress_bid and strongest_bid:
        p = float(strongest_bid.get("price", 0.0))
        q = int(strongest_bid.get("qty", 0))
        sh = float(strongest_bid.get("book_share_pct", 0.0))
        mult = float(strongest_bid.get("multiple_of_avg", 0.0))
        dur = float(strongest_bid.get("duration", 15.0))
        p_txt = f" @ ₹{p:,.2f}" if p > 0 else ""
        return {
            "bias": "BULLISH",
            "badge": "🛡️ BULLISH DEMAND FLOOR",
            "tag": "FORTRESS BID",
            "color": "emerald",
            "headline": f"Buyer Fortress{p_txt} ({q:,} lots)",
            "meaning": f"Institutions have committed a massive resting buy block ({q:,} contracts, {sh:.1f}% of entire book, {mult:.1f}x avg depth) holding stubbornly for {dur:.0f}s+ without cancelling.",
            "decision": f"FAVOR CALLS / LONGS: Dips into ₹{p:,.2f} are high-probability bounce zones. Anchor your Invalidation Stop-Loss just below ₹{p:,.2f}."
            if p > 0
            else "FAVOR CALLS / LONGS: Institutional floor confirmed.",
            "wall_price": p if p > 0 else None,
            "wall_qty": q if q > 0 else None,
            "book_share_pct": sh,
            "duration_seconds": dur,
        }

    # 4. Fortress Ask Wall Confirmed (Institutional Supply Ceiling)
    if fortress_ask and strongest_ask:
        p = float(strongest_ask.get("price", 0.0))
        q = int(strongest_ask.get("qty", 0))
        sh = float(strongest_ask.get("book_share_pct", 0.0))
        mult = float(strongest_ask.get("multiple_of_avg", 0.0))
        dur = float(strongest_ask.get("duration", 15.0))
        p_txt = f" @ ₹{p:,.2f}" if p > 0 else ""
        return {
            "bias": "BEARISH",
            "badge": "🏰 BEARISH SUPPLY CEILING",
            "tag": "FORTRESS ASK",
            "color": "rose",
            "headline": f"Seller Fortress{p_txt} ({q:,} lots)",
            "meaning": f"Institutions have erected an immovable sell wall ({q:,} contracts, {sh:.1f}% of entire book, {mult:.1f}x avg depth) capping the upside for {dur:.0f}s+ without cancelling.",
            "decision": f"FAVOR PUTS / SHORTS: Take profit on calls approaching ₹{p:,.2f}. DO NOT buy breakouts until this wall is completely swept and cleared."
            if p > 0
            else "FAVOR PUTS / SHORTS: Overhead institutional ceiling confirmed.",
            "wall_price": p if p > 0 else None,
            "wall_qty": q if q > 0 else None,
            "book_share_pct": sh,
            "duration_seconds": dur,
        }

    # 5. Strong Order Book Imbalance (> +0.25)
    if obi >= 0.25:
        return {
            "bias": "BULLISH",
            "badge": "📈 NET BUY PRESSURE",
            "tag": f"OBI +{int(obi * 100)}%",
            "color": "emerald",
            "headline": f"Deep Bid Absorption (OBI: +{obi:.2f})",
            "meaning": f"Buyers command {round((1 + obi) / 2 * 100)}% of total 50-level liquidity depth. Consistent bid layering indicates institutional accumulation.",
            "decision": "BULLISH ACCUMULATION: Order flow supports upward drift. Favorable backdrop for trend continuation long trades.",
            "wall_price": None,
            "wall_qty": None,
            "book_share_pct": None,
            "duration_seconds": None,
        }

    # 6. Strong Order Book Imbalance (< -0.25)
    if obi <= -0.25:
        return {
            "bias": "BEARISH",
            "badge": "📉 NET SELL PRESSURE",
            "tag": f"OBI {int(obi * 100)}%",
            "color": "rose",
            "headline": f"Heavy Ask Distribution (OBI: {obi:.2f})",
            "meaning": f"Sellers command {round((1 - obi) / 2 * 100)}% of total 50-level liquidity depth. Persistent ask stacking indicates institutional distribution.",
            "decision": "BEARISH DISTRIBUTION: Heavy overhead supply. Favorable backdrop for put setups; exercise extreme caution on long positions.",
            "wall_price": None,
            "wall_qty": None,
            "book_share_pct": None,
            "duration_seconds": None,
        }

    # 7. Balanced Auction / Neutral
    return {
        "bias": "NEUTRAL",
        "badge": "⚖️ BALANCED AUCTION",
        "tag": f"DENSITY {density:.0f}%",
        "color": "muted",
        "headline": "Symmetric Two-Sided Depth",
        "meaning": "Bids and asks are evenly matched across the 50 depth levels with no predatory resting walls or fleeing orders.",
        "decision": "TRADE PRICE ACTION: No order book distortion detected. Rely on standard VWAP, Camarilla pivots, and candlestick price action.",
        "wall_price": None,
        "wall_qty": None,
        "book_share_pct": None,
        "duration_seconds": None,
    }


class FyersTbtManager:
    """Singleton manager for Fyers 50-level Tick-By-Tick (TBT) market depth."""

    _instance: Optional[FyersTbtManager] = None
    _lock = threading.Lock()

    def __new__(cls) -> FyersTbtManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def _eval_multi_socket_entitled(self) -> bool:
        """
        Evaluate multi-socket entitlement (up to 3 concurrent WebSockets = 15 symbols)
        based on FYERS_TBT_WORKERS and FYERS_PLAN (defaults to True for Prime).
        """
        now = time.time()
        if getattr(self, "_multi_socket_suppressed_until", 0.0) > now:
            return False
        env_val = os.environ.get("FYERS_TBT_WORKERS", "").strip()
        if env_val:
            try:
                num = int(env_val)
                return num > 1
            except ValueError:
                return env_val.lower() not in ("1", "false", "no", "0")
        plan = os.environ.get("FYERS_PLAN", "PRIME").upper()
        return plan == "PRIME"

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._ws: Any = None
        self._workers: list[TbtSocketWorker] = []
        self._multi_socket_suppressed_until: float = 0.0
        self._multi_socket_entitled: bool = self._eval_multi_socket_entitled()
        self._connected: bool = False
        self._access_token: str = ""
        self._app_id: str = ""
        self._thread: Optional[threading.Thread] = None
        self._subscribed: Set[str] = set()
        self._channel_symbols: dict[str, set[str]] = {"1": set()}
        self._depth_cache: dict[str, dict[str, Any]] = {}
        self._depth_lock = threading.Lock()
        self._tick_buffers: dict[str, RollingTickBuffer] = {}
        self._callbacks: list[Callable[[str, dict[str, Any]], None]] = []

        # 15-Slot Dynamic Priority Governor
        self._in_flight: list[str] = []
        self._core_grid: list[str] = []
        self._todays_expiry: list[str] = []
        self._scout: OrderedDict[str, float] = OrderedDict()
        self._scout_ttl: dict[str, float] = {}
        self._current_session: str = "AUTO"
        self._primary_focus_index: Optional[str] = None
        self._last_atm_strikes: dict[str, int] = {}
        self._slots_lock = threading.RLock()

        # Opportunistic Sector Leaders Baseline (Preemptible Elastic Slots)
        self._sector_scouts: list[str] = []
        self._last_sector_scouts_refresh: float = 0.0
        self._sector_scouts_ttl: float = 900.0  # 15 minutes anti-thrashing cadence

        # Autonomous Session Handover & Drift Sentinel
        self._stop_event = threading.Event()
        self._guardian_thread: Optional[threading.Thread] = None

        # Autonomous Packet Silence Watchdog Sentinel
        self._last_packet_time: float = 0.0
        self._silence_watchdog_threshold: float = float(
            os.environ.get("FYERS_TBT_SILENCE_WATCHDOG_THRESHOLD", "30.0")
        )  # seconds
        self._reconnect_count: int = 0

        # Institutional Wall Durability & Spoof History Tracker
        self._wall_history: dict[str, dict[str, Any]] = {}

        # Operator Eviction & Slot Allocation Tracking
        self._slot_allocated_at: dict[str, float] = {}
        self._evicted_cooldowns: dict[str, float] = {}

        self._initialized = True

    def reset_for_testing(self) -> None:
        """Hermetically reset all internal dynamic slots, caches, and cooldowns for clean testing."""
        with self._slots_lock:
            self._in_flight.clear()
            self._core_grid.clear()
            self._todays_expiry.clear()
            self._scout.clear()
            self._sector_scouts.clear()
            self._last_sector_scouts_refresh = 0.0
            self._primary_focus_index = None
            self._last_atm_strikes.clear()
            self._evicted_cooldowns.clear()
            self._slot_allocated_at.clear()
            self._wall_history.clear()
            self._subscribed.clear()
            self._channel_symbols = {"1": set()}
            self._current_session = "AUTO"
            self._workers.clear()
        with self._depth_lock:
            self._depth_cache.clear()
        self._connected = False

    @property
    def is_connected(self) -> bool:
        if self._workers:
            return any(w.connected for w in self._workers)
        return self._connected

    def _get_auth_token(self) -> str:
        if not self._access_token:
            return ""
        return (
            f"{self._app_id}:{self._access_token}"
            if ":" not in self._access_token
            else self._access_token
        )

    def start(self, access_token: str, app_id: str) -> None:
        """Start Fyers TBT WebSocket multi-connection pool in background threads."""
        if os.environ.get("DISABLE_TBT_SOCKET") == "1":
            return
        if self.is_connected and self._access_token == access_token:
            return

        if self.is_connected and self._access_token != access_token:
            logger.info(
                "[TbtManager] Restarting Fyers TBT multi-socket pool with renewed access token"
            )
            self.stop()

        self._access_token = access_token
        self._app_id = app_id

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._connect, daemon=True)
        self._thread.start()

        if self._guardian_thread is None or not self._guardian_thread.is_alive():
            self._guardian_thread = threading.Thread(
                target=self._guardian_loop, daemon=True, name="tbt-session-guardian"
            )
            self._guardian_thread.start()

        logger.info("Fyers 50-Depth TBT Socket background thread started")

    def update_token(self, access_token: str, app_id: Optional[str] = None) -> None:
        """Update access token and reconnect if changed."""
        app = app_id or self._app_id
        if self._access_token != access_token or not self.is_connected:
            self.start(access_token=access_token, app_id=app)

    def stop(self, timeout: float = 1.0) -> None:
        """Gracefully disconnect all TBT WebSocket workers and stop sentinel without blocking."""
        self._stop_event.set()
        self._connected = False
        workers_to_close = list(self._workers)
        self._workers = []

        for w in workers_to_close:
            try:
                w.close()
            except Exception as e_w:
                logger.debug(f"[TbtManager] Worker close error: {e_w}")

        ws_to_close = self._ws
        self._ws = None
        if ws_to_close:
            try:
                setattr(ws_to_close, "restart_flag", False)
                ws_obj = getattr(ws_to_close, "_FyersTbtSocket__ws_object", None)
                if ws_obj and hasattr(ws_obj, "close"):
                    ws_obj.close()
            except Exception as e:
                logger.debug(f"[TbtManager] ws_obj.close suppressed: {e}")

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None

        if self._guardian_thread and self._guardian_thread.is_alive():
            self._guardian_thread.join(timeout=timeout)
        self._guardian_thread = None

    def _guardian_loop(self) -> None:
        """
        Autonomous background sentinel (runs every 15s):
          1. Automated session handover: detects market session transitions (e.g. 15:30 IST
             EQUITY_NFO -> COMMODITY_CDS, or 09:15 morning open) and rotates TBT slots.
          2. Strike revolver: evaluates spot drift and rotates stale ATM option strikes.
          3. In-flight garbage collection: reconciles active open orders/positions to evict closed symbols.
        """
        logger.info("[TbtManager] Autonomous session & strike guardian started")
        while not self._stop_event.is_set():
            try:
                # 1. Automated session handover (09:15 open, 15:30 commodity transition, 23:30 close)
                active_session = get_market_session()
                with self._slots_lock:
                    curr_session = self._current_session

                # Auto-switch whenever market session boundary is crossed (never blocked by stale focus)
                if curr_session != active_session:
                    logger.info(
                        f"[TbtManager] Market session boundary detected: '{curr_session}' -> '{active_session}'. "
                        f"Auto-rotating TBT slots to {'MCX commodities' if active_session == 'COMMODITY_CDS' else 'Index futures & options'}."
                    )
                    self.switch_session(active_session)

                # 1b. Currency CDS Session Retirement Sentinel at 17:00 IST:
                # When in COMMODITY_CDS, check if clock crossed 17:00 IST and retire USDINR immediately
                if self._current_session == "COMMODITY_CDS":
                    try:
                        from config.constants import IST_ZONE as IST

                        now_t = datetime.now(IST).time()
                    except Exception:
                        now_t = datetime.now().time()
                    if now_t >= dtime(17, 0):
                        with self._slots_lock:
                            has_cds = any("USDINR" in s for s in self._todays_expiry) or any(
                                "USDINR" in s for s in self._scout
                            )
                        if has_cds:
                            logger.info(
                                "[TbtManager] 17:00 IST Currency CDS market closed. "
                                "Retiring USDINR slots and rotating 100% capacity to active MCX commodities."
                            )
                            with self._slots_lock:
                                cds_scouts = [s for s in self._scout if "USDINR" in s]
                                for s in cds_scouts:
                                    del self._scout[s]
                            self.refresh_grid("COMMODITY_CDS")

                # 2. Strike revolver for active equity session
                if self._current_session in ("EQUITY_NFO", "OFF_MARKET"):
                    self.revolve_atm_strikes()

                # 2b. Autonomous Scout & Dead-Symbol Sanitation Sentinel (Every cycle)
                self.cleanse_stale_scouts(ttl_sec=120.0)

                # 2c. Opportunistic Sector Scout Capacity Refill
                if self._current_session in ("EQUITY_NFO", "OFF_MARKET"):
                    with self._slots_lock:
                        free_cap = MAX_TBT_SYMBOLS - len(self._subscribed)
                        expired_ttl = (
                            time.time() - self._last_sector_scouts_refresh
                        ) >= self._sector_scouts_ttl
                    if free_cap > 0 or expired_ttl:
                        self.sync_subscriptions()

                # Check if multi-socket temporary suppression has expired
                now_g = time.time()
                if (
                    getattr(self, "_multi_socket_suppressed_until", 0.0) > 0
                    and now_g >= self._multi_socket_suppressed_until
                ):
                    self._multi_socket_suppressed_until = 0.0
                    self._multi_socket_entitled = self._eval_multi_socket_entitled()
                    logger.info(
                        "[TbtManager] Multi-socket 429 suppression probation expired. Re-enabling multi-socket entitlement."
                    )

                # 2d. Reconnect quiescent/disconnected workers if past backoff
                if self._eval_multi_socket_entitled() and self._workers:
                    for w in self._workers:
                        if (
                            not w.connected
                            and w.status in ("DISCONNECTED", "DEGRADED_429")
                            and now_g >= w.degraded_until
                        ):
                            w.connect()

                # 3. In-flight position cleanup
                if self._in_flight:
                    self.sync_in_flight_with_positions()

                # 4. Autonomous Packet Silence Watchdog Sentinel (Self-Healing WebSocket)
                if self.is_connected and self._access_token:
                    try:
                        from market.calendar import is_market_open

                        # Fyers TBT strictly streams NSE Equity (CM) and NFO (Futures & Options).
                        # MCX is not on TBT. Silence watchdog must check NSE trading hours (09:15-15:30 IST)
                        # so pre-market (09:00-09:15 IST) does not trigger false packet freeze alarms.
                        is_active_market = is_market_open("NSE")
                    except Exception:
                        is_active_market = False

                    if (
                        is_active_market
                        and len(self._subscribed) > 0
                        and self._last_packet_time > 0
                    ):
                        silence_duration = time.time() - self._last_packet_time
                        if silence_duration > self._silence_watchdog_threshold:
                            logger.warning(
                                f"[TbtManager] SILENCE WATCHDOG: Packet freeze detected ({silence_duration:.1f}s > {self._silence_watchdog_threshold}s) "
                                f"across {len(self._subscribed)} active subscriptions during market hours. Initiating self-healing reconnect."
                            )
                            self._last_packet_time = time.time()  # Reset to prevent storm
                            self.force_reconnect()

                # 5. Connection Pool Sentinel: recover disconnected or backoff-expired workers during active market sessions
                active_session = get_market_session()
                if active_session != "OFF_MARKET":
                    now_w = time.time()
                    entitled = self._eval_multi_socket_entitled()
                    for w in self._workers:
                        if not entitled and w.worker_id > 0:
                            continue
                        if not w.connected and (
                            w.status == "DISCONNECTED"
                            or (w.status == "DEGRADED_429" and now_w >= w.degraded_until)
                        ):
                            logger.debug(
                                f"[TbtManager] Pool sentinel reconnecting worker {w.worker_id} (status={w.status})"
                            )
                            w.connect()

            except Exception as e:
                logger.debug(f"[TbtManager] Guardian loop pass error: {e}")

            # Sleep 15s or until stop_event is set
            self._stop_event.wait(timeout=15.0)
        logger.info("[TbtManager] Autonomous session & strike guardian stopped")

    def force_reconnect(self) -> None:
        """Forcefully cycles the WebSocket workers to self-heal from silent socket death / packet freezing."""
        logger.warning("[TbtManager] Executing forced multi-socket pool reconnect sequence...")
        self._reconnect_count += 1
        for w in self._workers:
            try:
                w.close()
            except Exception as e:
                logger.debug(f"[TbtManager] worker close suppressed: {e}")
        self._workers = []
        self._connected = False
        self._thread = threading.Thread(target=self._connect, daemon=True)
        self._thread.start()

    def _connect(self) -> None:
        """
        Connect workers in the multi-socket pool with staggered handshakes.
        Staggering handshakes (0s, 5s, 11s) prevents Cloudflare / Fyers 429 Too Many Requests.
        """
        # Fast-path: use cached SDK check; avoids repeated ImportError overhead.
        if not _is_fyers_sdk_available():
            return

        auth_token = self._get_auth_token()
        if not auth_token:
            logger.warning("[TbtManager] Cannot connect: missing auth token")
            return

        # Ensure 3 workers exist
        if not self._workers:
            for wid in range(3):
                worker = TbtSocketWorker(
                    worker_id=wid,
                    auth_token_getter=self._get_auth_token,
                    on_depth=self._handle_depth_update,
                    on_status=self._handle_worker_status,
                )
                self._workers.append(worker)

        session = get_market_session()
        if session == "OFF_MARKET":
            logger.info(
                "[TbtManager] Market session is OFF_MARKET. Worker pool initialized in standby mode; "
                "live socket connection will engage at market open (09:15 IST)."
            )
            return

        # Worker 0 connects immediately
        self._workers[0].connect()
        self._ws = getattr(self._workers[0], "ws", None)

        # Helper thread to connect workers 1 and 2 with staggered delay
        def _staggered_worker_connect():
            self._multi_socket_entitled = self._eval_multi_socket_entitled()
            if not getattr(self, "_multi_socket_entitled", True):
                logger.info(
                    "[TbtManager] Multi-socket disabled by policy/plan. Operating with primary worker (5 slots)."
                )
                return
            if len(self._workers) > 1 and not self._stop_event.is_set():
                time.sleep(6.0)
                if self._workers[0].status == "DEGRADED_429":
                    logger.info(
                        "[TbtManager] Primary worker rate-limited (429). Halting secondary worker connection."
                    )
                    return
                if not self._stop_event.is_set():
                    self._workers[1].connect()
            if len(self._workers) > 2 and not self._stop_event.is_set():
                time.sleep(7.0)
                if (
                    self._workers[0].status == "DEGRADED_429"
                    or self._workers[1].status == "DEGRADED_429"
                ):
                    return
                if not self._stop_event.is_set():
                    self._workers[2].connect()

        threading.Thread(
            target=_staggered_worker_connect, daemon=True, name="tbt-pool-stagger"
        ).start()

    def _handle_worker_status(self, worker_id: int, status: str) -> None:
        try:
            self._connected = any(w.connected for w in self._workers)
            if self._workers and getattr(self._workers[0], "ws", None):
                self._ws = self._workers[0].ws
            if status == "CONNECTED":
                if not self._core_grid:
                    self.refresh_grid()
                else:
                    self.sync_subscriptions()
            elif status in ("DEGRADED_429", "DISCONNECTED"):
                if status == "DEGRADED_429" and worker_id > 0 and self._workers:
                    # Do NOT permanently disable multi-socket on a single transient 429!
                    # Only if consecutive 429s persist (>= 5) do we place secondary workers on temporary probation
                    if (
                        self._workers[worker_id]._consecutive_429 >= 5
                        and self._multi_socket_entitled
                    ):
                        self._multi_socket_suppressed_until = time.time() + 900.0
                        self._multi_socket_entitled = False
                        logger.warning(
                            f"[TbtManager] Secondary worker {worker_id} hit repeated 429s (strike {self._workers[worker_id]._consecutive_429}). "
                            f"Multi-socket placed on temporary probation for 15m; will self-heal automatically."
                        )
                        for w in self._workers[1:]:
                            w.status = "STANDBY_SINGLE_SOCKET"
                            w.desired = []
                    else:
                        logger.info(
                            f"[TbtManager] Secondary worker {worker_id} in backoff cooldown (strike {self._workers[worker_id]._consecutive_429}). "
                            "Pool sentinel will retry connection automatically."
                        )
                # Proactively rebalance top priority slots onto remaining connected workers
                self.sync_subscriptions()
        except Exception as e:
            logger.exception(
                f"[TbtManager] Worker status handling error for worker {worker_id} ({status}): {e}"
            )

    def _handle_connect(self, *args, **kwargs) -> None:
        """Legacy callback maintained for single-socket compatibility."""
        self._connected = True
        logger.info("Fyers TBT Socket: Handshake confirmed. Synchronizing subscriptions...")
        if not self._core_grid:
            self.refresh_grid()
        else:
            self.sync_subscriptions()

    def _handle_close(self, *args, **kwargs) -> None:
        self._connected = any(w.connected for w in self._workers)
        logger.info("Fyers TBT Socket: Disconnected")

    def _handle_error(self, err, *args, **kwargs) -> None:
        logger.debug(f"Fyers TBT Socket error: {err}")

    def _handle_depth_update(self, symbol: str, depth_obj: Any) -> None:
        """Process incoming 50-depth packet from Fyers TBT socket and bridge to central quote cache."""
        try:
            self._last_packet_time = time.time()
            parsed = self._parse_depth_object(symbol, depth_obj)
            with self._depth_lock:
                self._depth_cache[symbol] = parsed
                clean_sym = symbol.split(":")[-1]
                self._depth_cache[clean_sym] = parsed

            # Zero-latency L1 quote bridge: populate market.quotes cache to eliminate REST queries
            try:
                from market.quotes import _QUOTE_CACHE, _quote_cache_lock
                from brokers.base import Quote

                ltp_raw = parsed.get("ltp")
                if ltp_raw is not None and float(ltp_raw) > 0:
                    ltp_val = float(ltp_raw)
                    bids_list = parsed.get("bids", [])
                    asks_list = parsed.get("asks", [])
                    top_b = float(bids_list[0]["price"]) if bids_list else None
                    top_a = float(asks_list[0]["price"]) if asks_list else None
                    q_obj = Quote(
                        symbol=symbol,
                        last_price=ltp_val,
                        open=None,
                        high=None,
                        low=None,
                        close=None,
                        volume=0,
                        bid=top_b,
                        ask=top_a,
                        source="STREAM",
                        data_state="LIVE",
                        provider="fyers_tbt",
                    )
                    now_w = time.time()
                    with _quote_cache_lock:
                        _QUOTE_CACHE[symbol] = (now_w, q_obj)
                        _QUOTE_CACHE[clean_sym] = (now_w, q_obj)
            except Exception as e_suppressed:
                logger.debug(
                    f"[market.fyers_tbt_manager] Non-fatal exception suppressed: {e_suppressed}"
                )

            # High-Frequency L3 Order Book Bridge: populate central BisectDepthBook up to 50 levels
            try:
                from market.order_book import get_depth_book

                b_list = parsed.get("bids", [])
                a_list = parsed.get("asks", [])
                if b_list or a_list:
                    get_depth_book(symbol, max_depth=50).batch_update(b_list, a_list)
                    get_depth_book(clean_sym, max_depth=50).batch_update(b_list, a_list)
            except Exception as e_suppressed:
                logger.debug(
                    f"[market.fyers_tbt_manager] BisectDepthBook bridge suppressed: {e_suppressed}"
                )

            for cb in self._callbacks:
                try:
                    cb(symbol, parsed)
                except Exception as e_suppressed:
                    logger.debug(
                        f"[market.fyers_tbt_manager] Non-fatal exception suppressed: {e_suppressed}"
                    )
        except Exception as e:
            logger.debug(f"Error parsing 50-depth packet for {symbol}: {e}")

    def _parse_depth_object(self, symbol: str, depth: Any) -> dict[str, Any]:
        """Convert SDK Depth protobuf object to structured institutional dict."""
        bid_prices = list(getattr(depth, "bidprice", []))
        ask_prices = list(getattr(depth, "askprice", []))
        bid_qtys = list(getattr(depth, "bidqty", []))
        ask_qtys = list(getattr(depth, "askqty", []))
        bid_orders = list(getattr(depth, "bidordn", []))
        ask_orders = list(getattr(depth, "askordn", []))

        bids = []
        asks = []
        tot_bid_q = 0
        tot_ask_q = 0

        for i in range(min(50, len(bid_prices))):
            bp = float(bid_prices[i] or 0.0)
            bq = int(bid_qtys[i] or 0)
            bo = int(bid_orders[i] or 0)
            if bp > 0 and bq > 0:
                bids.append({"level": i + 1, "price": bp, "qty": bq, "orders": bo})
                tot_bid_q += bq

        for i in range(min(50, len(ask_prices))):
            ap = float(ask_prices[i] or 0.0)
            aq = int(ask_qtys[i] or 0)
            ao = int(ask_orders[i] or 0)
            if ap > 0 and aq > 0:
                asks.append({"level": i + 1, "price": ap, "qty": aq, "orders": ao})
                tot_ask_q += aq

        tbq = int(getattr(depth, "tbq", tot_bid_q) or tot_bid_q)
        tsq = int(getattr(depth, "tsq", tot_ask_q) or tot_ask_q)

        # 50-level Order Book Imbalance ratio [-1.0 to +1.0]
        denom = tbq + tsq
        obi_50 = round((tbq - tsq) / max(1, denom), 4) if denom > 0 else 0.0

        # Book Density Score: active populated levels out of 100 total slots
        active_slots = len(bids) + len(asks)
        density_score = round((active_slots / 100.0) * 100, 1)

        # Institutional Multi-Factor Order Book Wall Classification:
        # Evaluated across 4 orthogonal dimensions:
        #   1. Book Share Dominance (>= 12% of total depth on that side)
        #   2. Multi-Order Clustering (orders >= 2 confirms structural consensus vs 1-order spoof)
        #   3. Capital Commitment (notional turnover & instrument-calibrated minimum volume)
        #   4. Auction Proximity (levels 3 to 25 within actionable execution horizon)
        is_commodity_sym = symbol.startswith("MCX:") or any(
            c in symbol.upper()
            for c in ("CRUDE", "NATURAL", "GOLD", "SILVER", "COPPER", "ZINC", "ALUMINIUM")
        )
        min_wall_qty = 10 if is_commodity_sym else 2500

        avg_bid_q = (tot_bid_q / max(1, len(bids))) if bids else 0
        avg_ask_q = (tot_ask_q / max(1, len(asks))) if asks else 0

        # Read genuine trade price if present; never assume top bid is last-traded price
        explicit_ltp = (
            getattr(depth, "ltp", None)
            or getattr(depth, "last_price", None)
            or getattr(depth, "last_traded_price", None)
        )
        ltp = float(explicit_ltp) if explicit_ltp is not None and float(explicit_ltp) > 0 else None
        ref_px = (
            ltp
            if ltp is not None
            else (bids[0]["price"] if bids else (asks[0]["price"] if asks else 0.0))
        )

        def _classify_wall(
            row: dict[str, Any], tot_q: int, avg_q: float
        ) -> Optional[dict[str, Any]]:
            lvl = row["level"]
            # Exclude level 1-2 spread flicker / top-of-book oscillation
            if lvl <= 2:
                return None
            qty = row["qty"]
            price = row["price"]
            orders = row.get("orders", 1)

            book_share_pct = round((qty / max(1, tot_q)) * 100, 2)
            multiple_of_avg = round(qty / max(1.0, avg_q), 2)
            notional = round(qty * price, 2)
            dist_pct = (
                round(abs(price - ref_px) / max(0.01, ref_px) * 100, 3) if ref_px > 0 else 0.0
            )

            # Must satisfy minimum volume or 2.5x multiple with at least 8% book share
            if (qty < max(min_wall_qty, avg_q * 2.5)) and book_share_pct < 8.0:
                return None
            if multiple_of_avg < 2.5 and qty < min_wall_qty:
                return None

            # Institutional Strength Hierarchy:
            # FORTRESS: Massive book dominance (>= 20% share) or heavy clustered institutional iceberg (orders >= 2 and >= 15% share)
            if (book_share_pct >= 20.0 and multiple_of_avg >= 4.0) or (
                orders >= 2 and book_share_pct >= 15.0 and multiple_of_avg >= 3.5
            ):
                strength = "FORTRESS"
            # STRONG: Dominates book (>= 12% share) and >= 3.0x average
            elif (book_share_pct >= 12.0 and multiple_of_avg >= 3.0) or (
                multiple_of_avg >= 3.0 and qty >= min_wall_qty
            ):
                strength = "STRONG"
            else:
                strength = "MODERATE"

            return {
                "level": lvl,
                "price": price,
                "qty": qty,
                "orders": orders,
                "book_share_pct": book_share_pct,
                "multiple_of_avg": multiple_of_avg,
                "notional_value": notional,
                "strength": strength,
                "distance_pct": dist_pct,
            }

        bid_walls = []
        for b in bids:
            w = _classify_wall(b, tot_bid_q, avg_bid_q)
            if w:
                bid_walls.append(w)

        ask_walls = []
        for a in asks:
            w = _classify_wall(a, tot_ask_q, avg_ask_q)
            if w:
                ask_walls.append(w)

        # Sort walls by structural significance: highest quantity & book share first
        bid_walls.sort(key=lambda x: (x["book_share_pct"], x["qty"]), reverse=True)
        ask_walls.sort(key=lambda x: (x["book_share_pct"], x["qty"]), reverse=True)

        strongest_bid_wall = bid_walls[0] if bid_walls else None
        strongest_ask_wall = ask_walls[0] if ask_walls else None

        spread = round(asks[0]["price"] - bids[0]["price"], 2) if bids and asks else 0.0
        micro_price = (
            round(
                (bids[0]["price"] * asks[0]["qty"] + asks[0]["price"] * bids[0]["qty"])
                / max(1, bids[0]["qty"] + asks[0]["qty"]),
                4,
            )
            if bids and asks
            else (ltp or ref_px)
        )

        # Update O(1) rolling tick buffer for micro-price tracking
        buf = self._tick_buffers.setdefault(symbol, RollingTickBuffer(capacity=1000))
        if micro_price and micro_price > 0:
            buf.append(micro_price, max(1, tbq + tsq))

        rolling_vwap = round(buf.vwap, 4) if buf.count > 0 else (micro_price or 0.0)
        rolling_vol = round(buf.std_dev, 4) if buf.count > 1 else 0.0

        # Micro-Price Skew in Basis Points (bps)
        micro_price_skew_bps = (
            round(((micro_price - ref_px) / max(0.01, ref_px)) * 10000.0, 2)
            if ref_px > 0 and micro_price is not None
            else 0.0
        )
        flow_posture = (
            "BULLISH_PRESSURE"
            if micro_price_skew_bps >= 0.25
            else ("BEARISH_PRESSURE" if micro_price_skew_bps <= -0.25 else "BALANCED")
        )

        # Audit wall durability, resting absorption, and fleeing/spoof behavior
        wall_audit = self._audit_wall_durability(symbol, ref_px, bid_walls, ask_walls)

        return {
            "symbol": symbol,
            "status": "LIVE",
            "timestamp": getattr(depth, "timestamp", int(time.time())),
            "received_at": time.time(),
            "ltp": ltp,
            "micro_price": micro_price,
            "micro_price_skew_bps": micro_price_skew_bps,
            "order_flow_posture": flow_posture,
            "fleeing_bid_wall_detected": wall_audit["fleeing_bid_wall_detected"],
            "fleeing_ask_wall_detected": wall_audit["fleeing_ask_wall_detected"],
            "fortress_bid_wall_confirmed": wall_audit["fortress_bid_wall_confirmed"],
            "fortress_ask_wall_confirmed": wall_audit["fortress_ask_wall_confirmed"],
            "spoof_trap_warning": wall_audit["spoof_trap_warning"],
            "absorption_note": wall_audit["absorption_note"],
            "rolling_tick_vwap": rolling_vwap,
            "rolling_tick_volatility": rolling_vol,
            "spread": spread,
            "tbq": tbq,
            "tsq": tsq,
            "obi_50": obi_50,
            "density_score": density_score,
            "bids_count": len(bids),
            "asks_count": len(asks),
            "bids": bids,
            "asks": asks,
            "bid_walls": bid_walls,
            "ask_walls": ask_walls,
            "strongest_bid_wall": strongest_bid_wall,
            "strongest_ask_wall": strongest_ask_wall,
            "has_bid_wall": len(bid_walls) > 0,
            "has_ask_wall": len(ask_walls) > 0,
        }

    def _audit_wall_durability(
        self,
        symbol: str,
        ltp: float,
        bid_walls: list[dict[str, Any]],
        ask_walls: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Audits wall duration, resting absorption, and fleeing/spoof behavior.
        Detects Phantom Walls (bluffs that cancel as spot approaches) vs Fortress Absorption.
        """
        now = time.time()
        state = self._wall_history.setdefault(
            symbol,
            {
                "active_walls": {},  # key: f"{side}:{price}" -> dict
                "recent_fleeing": [],  # list of recent fleeing events
            },
        )

        active = state["active_walls"]
        current_keys = set()

        for w in bid_walls:
            p = round(float(w["price"]), 2)
            k = f"BID:{p:.2f}"
            current_keys.add(k)
            q = int(w["qty"])
            dist = float(w.get("distance_pct", 0.0))
            st = str(w.get("strength", "MODERATE"))
            if k in active:
                rec = active[k]
                rec["last_seen"] = now
                rec["last_qty"] = q
                if q > rec["peak_qty"]:
                    rec["peak_qty"] = q
                rec["distance_pct"] = dist
                rec["duration"] = round(now - rec["first_seen"], 2)
                rec["strength"] = st
            else:
                active[k] = {
                    "side": "BID",
                    "price": p,
                    "first_seen": now,
                    "last_seen": now,
                    "peak_qty": q,
                    "last_qty": q,
                    "distance_pct": dist,
                    "duration": 0.0,
                    "strength": st,
                }

        for w in ask_walls:
            p = round(float(w["price"]), 2)
            k = f"ASK:{p:.2f}"
            current_keys.add(k)
            q = int(w["qty"])
            dist = float(w.get("distance_pct", 0.0))
            st = str(w.get("strength", "MODERATE"))
            if k in active:
                rec = active[k]
                rec["last_seen"] = now
                rec["last_qty"] = q
                if q > rec["peak_qty"]:
                    rec["peak_qty"] = q
                rec["distance_pct"] = dist
                rec["duration"] = round(now - rec["first_seen"], 2)
                rec["strength"] = st
            else:
                active[k] = {
                    "side": "ASK",
                    "price": p,
                    "first_seen": now,
                    "last_seen": now,
                    "peak_qty": q,
                    "last_qty": q,
                    "distance_pct": dist,
                    "duration": 0.0,
                    "strength": st,
                }

        # Check for walls that just disappeared (potential fleeing / spoof)
        disappeared_keys = [k for k in list(active.keys()) if k not in current_keys]
        for k in disappeared_keys:
            rec = active[k]
            # If the disappeared wall had substantial size and was near spot (<= 0.15%), it's a fleeing wall
            if rec["peak_qty"] >= 2000 and rec.get("distance_pct", 1.0) <= 0.15:
                flee_evt = {
                    "side": rec["side"],
                    "price": rec["price"],
                    "qty": rec["peak_qty"],
                    "timestamp": now,
                    "duration": rec.get("duration", 0.0),
                }
                state["recent_fleeing"].append(flee_evt)
                logger.info(
                    f"[TbtManager] SPOOF DETECTED on {symbol}: {rec['side']} wall of {rec['peak_qty']:,} @ ₹{rec['price']} fled at distance {rec.get('distance_pct', 0):.2f}%"
                )
            del active[k]

        # Prune events older than 45s
        state["recent_fleeing"] = [
            e for e in state["recent_fleeing"] if (now - e["timestamp"]) <= 45.0
        ]

        # Identify confirmed fortress walls (persisting >= 15.0s with fortress/strong conviction)
        top_fortress_bid = next(
            (
                rec
                for rec in active.values()
                if rec["side"] == "BID"
                and rec.get("duration", 0.0) >= 15.0
                and rec.get("strength") in ("FORTRESS", "STRONG")
            ),
            None,
        )
        top_fortress_ask = next(
            (
                rec
                for rec in active.values()
                if rec["side"] == "ASK"
                and rec.get("duration", 0.0) >= 15.0
                and rec.get("strength") in ("FORTRESS", "STRONG")
            ),
            None,
        )
        fortress_bid = top_fortress_bid is not None
        fortress_ask = top_fortress_ask is not None

        # Evaluate fleeing / spoof alerts
        fleeing_bid = any(e["side"] == "BID" for e in state["recent_fleeing"])
        fleeing_ask = any(e["side"] == "ASK" for e in state["recent_fleeing"])
        recent_fleeing_evt = state["recent_fleeing"][-1] if state["recent_fleeing"] else None

        spoof_warning = None
        if fleeing_bid:
            spoof_warning = (
                "BID_SPOOF_RUGPULL_RISK: Substantial resting bid wall fled as price approached"
            )
        elif fleeing_ask:
            spoof_warning = (
                "ASK_SPOOF_BEARTRAP_RISK: Substantial resting ask wall fled as price approached"
            )

        absorption_note = None
        if fortress_bid:
            absorption_note = (
                "FORTRESS_BID_ABSORPTION: Resting institutional bid floor holding >15s"
            )
        elif fortress_ask:
            absorption_note = (
                "FORTRESS_ASK_ABSORPTION: Resting institutional ask ceiling holding >15s"
            )

        return {
            "fleeing_bid_wall_detected": fleeing_bid,
            "fleeing_ask_wall_detected": fleeing_ask,
            "fortress_bid_wall_confirmed": fortress_bid,
            "fortress_ask_wall_confirmed": fortress_ask,
            "recent_fleeing_count": len(state["recent_fleeing"]),
            "spoof_trap_warning": spoof_warning,
            "absorption_note": absorption_note,
            "active_fortress_bid": top_fortress_bid,
            "active_fortress_ask": top_fortress_ask,
            "recent_fleeing_event": recent_fleeing_evt,
        }

    def refresh_grid(self, session: Optional[str] = None) -> None:
        """Populate the core grid and today's expiry symbols based on active market session and primary focus."""
        with self._slots_lock:
            from market.instruments import STANDARD_LOT_SIZES

            if session and session != "AUTO":
                target_session = session
            elif self._primary_focus_index and (
                self._primary_focus_index
                in (
                    "NIFTY",
                    "BANKNIFTY",
                    "MIDCPNIFTY",
                    "SENSEX",
                    "FINNIFTY",
                )
                or self._primary_focus_index in STANDARD_LOT_SIZES
            ):
                target_session = "EQUITY_NFO"
            elif getattr(self, "_current_session", "AUTO") not in ("AUTO", None):
                target_session = self._current_session
            else:
                target_session = get_market_session()

            core, todays = get_default_core_grid(
                target_session, primary_focus=self._primary_focus_index
            )
            self._core_grid = core
            self._todays_expiry = todays
            self._current_session = target_session
            logger.info(
                f"[TbtManager] Refreshed TBT grid for session '{self._current_session}' (Focus={self._primary_focus_index}): "
                f"Core ({len(self._core_grid)})={self._core_grid}, Expiry ({len(self._todays_expiry)})={self._todays_expiry}"
            )
            self.sync_subscriptions()

    def set_primary_focus(
        self, index_name: Optional[str] = None, session: Optional[str] = None
    ) -> None:
        """
        Dynamically designate a primary focus underlying (Index or single-stock F&O like 'RELIANCE', 'TCS').
        Expands core grid with ATM CE/PE and ATM +/- 1 wings by borrowing elastically from the scout pool.
        Pass None to return to balanced multi-index coverage.
        """
        with self._slots_lock:
            self._primary_focus_index = (
                index_name.upper()
                .replace("NSE:", "")
                .replace("BSE:", "")
                .replace("-EQ", "")
                .strip()
                if index_name
                else None
            )
            logger.info(f"[TbtManager] Primary focus set to: {self._primary_focus_index}")
            from market.instruments import STANDARD_LOT_SIZES

            is_equity_focus = bool(
                self._primary_focus_index
                and (
                    self._primary_focus_index
                    in ("NIFTY", "BANKNIFTY", "MIDCPNIFTY", "SENSEX", "FINNIFTY")
                    or self._primary_focus_index in STANDARD_LOT_SIZES
                )
            )
            target_session = session or ("EQUITY_NFO" if is_equity_focus else self._current_session)
            self.refresh_grid(session=target_session)

    def revolve_atm_strikes(self, force: bool = False) -> bool:
        """
        Check underlying spot prices for NIFTY, BANKNIFTY, MIDCPNIFTY, and SENSEX (plus focused stock).
        If spot has drifted by >= 1 strike step, automatically rotate stale ATM contracts
        out of TBT depth and subscribe the newly active ATM strikes.
        Returns True if grid was revolved, False otherwise.
        """
        try:
            from market.quotes import get_ltp
        except Exception:
            return False

        if self._current_session not in ("EQUITY_NFO", "OFF_MARKET"):
            if not (self._primary_focus_index or self._last_atm_strikes):
                return False

        index_configs = {
            "NIFTY": ("NSE:NIFTY50-INDEX", 50),
            "BANKNIFTY": ("NSE:NIFTYBANK-INDEX", 100),
            "MIDCPNIFTY": ("NSE:MIDCPNIFTY-INDEX", 25),
            "SENSEX": ("BSE:SENSEX-INDEX", 100),
        }
        if self._primary_focus_index and self._primary_focus_index not in index_configs:
            from market.instruments import STANDARD_LOT_SIZES
            from engine.strike_revolver import get_strike_step_for_symbol

            if self._primary_focus_index in STANDARD_LOT_SIZES:
                stk_spot_sym = f"NSE:{self._primary_focus_index}-EQ"
                stk_ltp = get_ltp(stk_spot_sym) or get_ltp(self._primary_focus_index) or 1000.0
                stk_step = int(get_strike_step_for_symbol(self._primary_focus_index, spot=stk_ltp))
                index_configs[self._primary_focus_index] = (stk_spot_sym, stk_step)

        revolved = False
        new_atm_map: dict[str, int] = {}

        for idx, (spot_sym, step) in index_configs.items():
            ltp = get_ltp(spot_sym) or get_ltp(idx)
            if ltp and ltp > 0:
                prev_atm = self._last_atm_strikes.get(idx)
                if prev_atm is None:
                    current_atm = int(round(ltp / float(step)) * step)
                    new_atm_map[idx] = current_atm
                    revolved = True
                else:
                    # 15% Strike Deadband (Hysteresis): prevents thrashing when spot oscillates near boundary
                    deadband = 0.15 * step
                    threshold = (0.5 * step) + deadband
                    if abs(ltp - prev_atm) >= threshold:
                        current_atm = int(round(ltp / float(step)) * step)
                        if current_atm != prev_atm:
                            new_atm_map[idx] = current_atm
                            revolved = True
                    else:
                        new_atm_map[idx] = prev_atm

        if force or (revolved and new_atm_map):
            with self._slots_lock:
                self._last_atm_strikes.update(new_atm_map)
                target_session = (
                    self._current_session if self._current_session != "AUTO" else "EQUITY_NFO"
                )
                self.refresh_grid(session=target_session)
                logger.info(
                    f"[TbtManager] Revolved ATM strikes due to spot drift: {self._last_atm_strikes}"
                )
            return True

        return False

    def switch_session(self, session_name: str) -> None:
        """
        Manually or automatically transition market session.
        E.g. 'EQUITY_NFO' at 09:15 IST -> 'COMMODITY_CDS' at 15:30 IST.
        Cleanses stale scouts and resets ATM strike caches for seamless morning switchover.
        """
        logger.info(
            f"[TbtManager] Switching TBT session from '{self._current_session}' to '{session_name}'"
        )
        with self._slots_lock:
            if session_name == "EQUITY_NFO":
                # If workers are in standby (not connected) and we have an auth token, engage connection
                if (
                    self._workers
                    and not any(w.connected for w in self._workers)
                    and self._access_token
                ):
                    self._thread = threading.Thread(target=self._connect, daemon=True)
                    self._thread.start()

                # Morning Handover (09:15 IST): Evict all commodity/currency scouts
                # to liberate all 15 slots for daytime index options & equity scouts.
                to_evict = [
                    s
                    for s in self._scout
                    if s.startswith("MCX:")
                    or "USDINR" in s
                    or any(
                        c in s
                        for c in (
                            "CRUDE",
                            "NATURAL",
                            "GOLD",
                            "SILVER",
                            "COPPER",
                            "ZINC",
                            "ALUMINIUM",
                        )
                    )
                ]
                for s in to_evict:
                    del self._scout[s]
                if to_evict:
                    logger.info(
                        f"[TbtManager] Liberated {len(to_evict)} evening commodity slots for morning equity open: {to_evict}"
                    )
                # Reset ATM strike cache and primary focus for fresh morning index open
                self._last_atm_strikes.clear()
                self._primary_focus_index = None
                try:
                    from market.ws_subscription_manager import get_ws_subscription_manager

                    get_ws_subscription_manager().seed_active_derivatives()
                except Exception as e_seed:
                    logger.debug(f"[TbtManager] Morning seed derivatives notice: {e_seed}")

            elif session_name == "COMMODITY_CDS":
                # Evening Handover (15:30 IST): Flush closed daytime equity/NFO scouts & in-flight positions
                evicted_count = len(self._scout) + len(self._in_flight)
                self._scout.clear()
                self._in_flight.clear()
                self._last_atm_strikes.clear()
                self._primary_focus_index = None
                if evicted_count > 0:
                    logger.info(
                        f"[TbtManager] Evicted {evicted_count} closed daytime equity/NFO slots for evening commodity session"
                    )
                try:
                    from market.ws_subscription_manager import get_ws_subscription_manager

                    get_ws_subscription_manager().cleanse_closed_session_derivatives()
                except Exception as e_cleanse:
                    logger.debug(f"[TbtManager] L1 closed session cleanse notice: {e_cleanse}")

        self.refresh_grid(session=session_name)

    def register_in_flight(self, symbol: str) -> None:
        """
        Register in-flight active position or limit order.
        Existing exposure preempts discovery up to the total provider capacity.
        """
        tradable = resolve_tradable_tbt_symbol(symbol)
        if not tradable:
            return
        with self._slots_lock:
            # In-flight active trade strictly clears any eviction cooldown
            self._evicted_cooldowns.pop(tradable, None)
            self._evicted_cooldowns.pop(symbol, None)
            if tradable not in self._in_flight:
                self._in_flight.append(tradable)
                if len(self._in_flight) > MAX_TBT_SYMBOLS:
                    logger.error(
                        "[TbtManager] TBT exposure capacity exceeded: %s registered / %s slots; excess exposure retains registration and needs alternate market-data monitoring",
                        len(self._in_flight),
                        MAX_TBT_SYMBOLS,
                    )
                logger.info(
                    f"[TbtManager] Registered Tier 1 In-Flight position: {tradable} (Total: {len(self._in_flight)})"
                )
                self.sync_subscriptions()

    def unregister_in_flight(self, symbol: str) -> None:
        """Unregister in-flight symbol once position is closed or order filled/cancelled."""
        tradable = resolve_tradable_tbt_symbol(symbol)
        with self._slots_lock:
            removed = False
            if tradable and tradable in self._in_flight:
                self._in_flight.remove(tradable)
                removed = True
            elif symbol in self._in_flight:
                self._in_flight.remove(symbol)
                removed = True
            if removed:
                logger.info(
                    f"[TbtManager] Unregistered Tier 1 In-Flight position: {tradable or symbol}"
                )
                self.sync_subscriptions()

    def sync_in_flight_with_positions(self) -> None:
        """
        Reconcile Tier 1 In-Flight slots against active live open orders & positions.
        Evicts any closed/cancelled symbols that no longer have an active position or open order.
        """
        with self._slots_lock:
            if not self._in_flight:
                return

        active_symbols: set[str] = set()
        try:
            from engine.order_lifecycle import _get_orders_pool

            pool = _get_orders_pool()
            with pool.connection() as conn:
                rows = conn.execute(
                    "SELECT DISTINCT symbol FROM orders_ledger WHERE status = 'OPEN'"
                ).fetchall()
                for r in rows:
                    if r and r[0]:
                        active_symbols.add(str(r[0]))
        except Exception as e_suppressed:
            logger.debug(
                f"[market.fyers_tbt_manager] Non-fatal exception suppressed: {e_suppressed}"
            )

        try:
            from brokers.session import get_execution_broker

            broker = get_execution_broker()
            if broker and hasattr(broker, "get_positions"):
                for p in broker.get_positions():
                    if getattr(p, "quantity", 0) != 0:
                        active_symbols.add(str(p.symbol))
        except Exception as e_suppressed:
            logger.debug(
                f"[market.fyers_tbt_manager] Non-fatal exception suppressed: {e_suppressed}"
            )

        self.sync_in_flight_with_active_symbols(active_symbols)

    def sync_in_flight_with_active_symbols(self, active_symbols: set[str] | list[str]) -> None:
        """Evict any in-flight symbol that is not in active_symbols."""
        normalized_active = set()
        for s in active_symbols:
            t = resolve_tradable_tbt_symbol(s)
            if t:
                normalized_active.add(t)
            normalized_active.add(s)

        with self._slots_lock:
            to_remove = [s for s in self._in_flight if s not in normalized_active]
            if to_remove:
                for s in to_remove:
                    self._in_flight.remove(s)
                logger.info(
                    f"[TbtManager] Evicted {len(to_remove)} closed/dead in-flight positions: {to_remove}"
                )
                self.sync_subscriptions()

    def _get_cached_sector_scouts(self, force_refresh: bool = False) -> list[str]:
        """
        Opportunistic Sector Momentum Leaders & Heavyweights (Preemptible Elastic Slots).
        Returns up to 12 tradable F&O Stock Futures representing:
          1. Leaders from RRG LEADING & IMPROVING sectors (via analysis.sector_rotation).
          2. Top NIFTY 50 beta heavyweights (RELIANCE, HDFCBANK, ICICIBANK, INFY, TCS, LT, SBIN).
        Refreshes on a 15-minute anti-thrashing cadence (or force_refresh).
        """
        now = time.time()
        if (
            not force_refresh
            and self._sector_scouts
            and (now - self._last_sector_scouts_refresh) < self._sector_scouts_ttl
        ):
            return [s for s in self._sector_scouts if s not in self._evicted_cooldowns]

        # Only populate equity sector leaders during EQUITY_NFO / OFF_MARKET / daytime
        if self._current_session == "COMMODITY_CDS":
            return []

        sector_key_map = {
            "BANK": "banking",
            "IT": "it",
            "AUTO": "auto",
            "PHARMA": "pharma",
            "FMCG": "fmcg",
            "METAL": "metals",
            "REALTY": "infra",
            "ENERGY": "energy",
            "INFRA": "infra",
            "PSU_BANK": "banking",
        }
        # Core Index Mega-Cap Pillars: RELIANCE (~9.5% NIFTY weight) + Top Banking/IT leaders
        # These 5 titans move >40% of the entire index and must be monitored first in spare capacity
        core_market_pillars = [
            "RELIANCE",
            "HDFCBANK",
            "ICICIBANK",
            "INFY",
            "TCS",
        ]
        secondary_heavies = [
            "LT",
            "SBIN",
            "BHARTIARTL",
            "MARUTI",
            "TATASTEEL",
        ]

        candidates: list[str] = list(core_market_pillars)

        # 1. RRG Leading & Improving sector constituents
        try:
            from engine.analysis_cache import analysis_cache
            from analysis.universe import SECTOR_TAXONOMY

            # Never synchronously block under _slots_lock on uncached OHLCV downloads
            cached_rrg = analysis_cache.get_macro("sector_rrg_matrix")
            if cached_rrg and isinstance(cached_rrg, list):
                from analysis.sector_rotation import get_sector_rrg_matrix

                rrg = get_sector_rrg_matrix(use_cache=True)
            else:
                rrg = []
            leading_sectors = [pt.sector for pt in rrg if getattr(pt, "quadrant", "") == "LEADING"]
            improving_sectors = [
                pt.sector for pt in rrg if getattr(pt, "quadrant", "") == "IMPROVING"
            ]

            for sec in leading_sectors + improving_sectors:
                tax_key = sector_key_map.get(sec)
                if tax_key and tax_key in SECTOR_TAXONOMY:
                    symbols = SECTOR_TAXONOMY[tax_key].get("symbols", [])
                    for stk in symbols[:2]:
                        if stk not in candidates:
                            candidates.append(stk)
        except Exception as e_suppressed:
            logger.debug(f"[TbtManager] Sector RRG resolution fallback: {e_suppressed}")

        # 2. Secondary benchmark heavies
        for h in secondary_heavies:
            if h not in candidates:
                candidates.append(h)

        # 3. Resolve to tradable stock futures
        resolved: list[str] = []
        for sym in candidates:
            try:
                fut = resolve_stock_future(sym)
                if fut and is_tbt_eligible_symbol(fut) and fut not in resolved:
                    resolved.append(fut)
            except Exception as e_suppressed:
                logger.debug(
                    f"[TbtManager] Failed resolving stock future for {sym}: {e_suppressed}"
                )

        self._sector_scouts = resolved
        self._last_sector_scouts_refresh = now
        return [s for s in self._sector_scouts if s not in self._evicted_cooldowns]

    def compute_desired_subscriptions(
        self, fill_sector_leaders: Optional[bool] = None
    ) -> list[str]:
        """
        Build exact prioritized list of up to MAX_TBT_SYMBOLS (15) symbols.
        Order of priority:
          1. IN_FLIGHT (active orders/positions, before all discovery)
          2. CORE_GRID (Benchmark Futures & Revolving ATM Options, elastic)
          3. TODAYS_EXPIRY (0DTE priority candidates when active)
          4. SCOUT (Elastic: fills all remaining unallocated slots up to 15)
          5. SECTOR_LEADERS (Opportunistic baseline: fills remaining spare slots with sector heavies)
        """
        now = time.time()
        with self._slots_lock:
            # Purge expired cooldowns
            self._evicted_cooldowns = {k: v for k, v in self._evicted_cooldowns.items() if v > now}
            desired: list[str] = []

            # 1. In-flight open orders / positions (overrides cooldowns if active trade exists)
            for s in self._in_flight[:MAX_TBT_SYMBOLS]:
                if s and s not in desired:
                    desired.append(s)

            # 2. Core Grid (Benchmark Futures & ATM Options - elastic consumption)
            for s in self._core_grid:
                if len(desired) >= MAX_TBT_SYMBOLS:
                    break
                if s and s not in desired and s not in self._evicted_cooldowns:
                    companion = (
                        s[:-2] + ("PE" if s.endswith("CE") else "CE")
                        if s.endswith(("CE", "PE"))
                        else ""
                    )
                    pair = [s, companion] if companion in self._core_grid else [s]
                    missing = [c for c in pair if c not in desired]
                    if any(c in self._evicted_cooldowns for c in missing):
                        continue
                    if len(desired) + len(missing) <= MAX_TBT_SYMBOLS:
                        desired.extend(missing)

            # 3. Today's Expiry Radar
            for s in self._todays_expiry[:MAX_TODAYS_EXPIRY_SLOTS]:
                if len(desired) >= MAX_TBT_SYMBOLS:
                    break
                if s and s not in desired and s not in self._evicted_cooldowns:
                    desired.append(s)

            # 4. Ephemeral Scout slots (Elastic: fills all remaining unallocated slots up to 15)
            remaining_slots = MAX_TBT_SYMBOLS - len(desired)
            if remaining_slots > 0 and self._scout:
                # Prioritize index options and futures ahead of stock options and equities
                sorted_scout = sorted(
                    self._scout.items(),
                    key=lambda item: (
                        _tbt_symbol_priority(item[0], primary_focus=self._primary_focus_index),
                        item[1],
                    ),
                    reverse=True,
                )
                for s, _ in sorted_scout:
                    if len(desired) >= MAX_TBT_SYMBOLS:
                        break
                    if s and s not in desired and s not in self._evicted_cooldowns:
                        desired.append(s)

            # 5. Opportunistic Sector Momentum Leaders (Elastic preemption baseline)
            # Fills any remaining empty slots up to MAX_TBT_SYMBOLS (15) with market-leading sector heavies.
            # These are 100% PREEMPTIBLE: any in-flight order, core grid update, or JIT alert scout
            # will immediately claim slots ahead of these background sector scouts.
            remaining_for_sector = MAX_TBT_SYMBOLS - len(desired)
            fill_sector = (
                getattr(self, "_opportunistic_sector_leaders_enabled", True)
                if fill_sector_leaders is None
                else fill_sector_leaders
            )
            if remaining_for_sector > 0 and fill_sector:
                sector_candidates = self._get_cached_sector_scouts()
                for s in sector_candidates:
                    if len(desired) >= MAX_TBT_SYMBOLS:
                        break
                    if s and s not in desired and s not in self._evicted_cooldowns:
                        desired.append(s)

            return desired[:MAX_TBT_SYMBOLS]

    def sync_subscriptions(self) -> None:
        """
        Synchronize current active Fyers TBT WebSocket subscriptions to desired set.
        Partitions up to 15 desired symbols across the multi-connection pool:
          - Worker 0: slots 0..4 (In-Flight + ATM Index Options)
          - Worker 1: slots 5..9 (Core Grid + Near Wings)
          - Worker 2: slots 10..14 (Scouts / MCX Commodities)
        """
        desired_list = self.compute_desired_subscriptions()[:MAX_TBT_SYMBOLS]
        self._last_desired = list(desired_list)
        desired_set = set(desired_list)

        with self._slots_lock:
            # Update slot allocation timestamps
            now_alloc = time.time()
            for s in desired_set:
                self._slot_allocated_at.setdefault(s, now_alloc)

            # Evict removed symbols from timestamp tracking
            stale_tracked = set(self._slot_allocated_at.keys()) - desired_set
            for s in stale_tracked:
                self._slot_allocated_at.pop(s, None)

            # Partition across up to 3 workers (5 symbols each)
            chunks = [desired_list[i : i + 5] for i in range(0, 15, 5)]

            if self._workers:
                connected_workers = [w for w in self._workers if w.connected]
                disconnected_workers = [w for w in self._workers if not w.connected]

                if connected_workers:
                    # Dynamically prioritize slots onto healthy connected workers
                    for w in disconnected_workers:
                        w.desired = []

                    # Dynamically prioritize top slots onto connected workers:
                    # Each connected worker gets at most MAX_SYMBOLS_PER_WORKER (5),
                    # strictly respecting the physical Fyers WebSocket server limit.
                    for idx, worker in enumerate(connected_workers):
                        start_idx = idx * MAX_SYMBOLS_PER_WORKER
                        end_idx = start_idx + MAX_SYMBOLS_PER_WORKER
                        worker_chunk = desired_list[start_idx:end_idx]
                        worker.desired = worker_chunk
                        worker.sync()

                    self._subscribed = set().union(*(w.subscribed for w in connected_workers))
                else:
                    # All workers disconnected or initializing: stage chunks statically
                    for idx, chunk in enumerate(chunks):
                        if idx < len(self._workers):
                            self._workers[idx].desired = chunk
                    self._subscribed = desired_set
            else:
                self._subscribed = desired_set

    def subscribe(self, symbols: list[str]) -> None:
        """
        Register symbols dynamically under the 15-slot governor.
        Symbols are routed through the Scout ring with prioritized LRU eviction.
        """
        if not symbols:
            return

        with self._slots_lock:
            now_ts = time.time()
            changed = False
            for s in symbols:
                tradable = resolve_tradable_tbt_symbol(s)
                if not tradable:
                    continue
                # Versova TBT WebSocket physically only supports NSE instruments (CM & NFO)
                if not is_tbt_eligible_symbol(tradable) and not (
                    tradable.endswith("-EQ") or tradable.endswith(":EQ")
                ):
                    logger.debug(
                        f"[TbtManager] Skipping non-NSE symbol {tradable} from TBT: Versova TBT strictly supports NSE only."
                    )
                    continue

                # In evening/off-market sessions, NSE markets are closed: reject closed daytime equities/options from TBT slots
                if self._current_session in ("COMMODITY_CDS", "OFF_MARKET"):
                    import os

                    if not os.environ.get("CHANAKYA_TESTING"):
                        logger.debug(
                            f"[TbtManager] NSE closed in session {self._current_session}. Skipping {tradable} from active TBT streaming slots."
                        )
                        continue

                # If a cash equity of an F&O stock is subscribed, upgrade to active Stock Future for 50-depth TBT
                if tradable.endswith("-EQ") or tradable.endswith(":EQ"):
                    stock_fut = resolve_stock_future(tradable)
                    if stock_fut:
                        tradable = stock_fut

                # Intent-driven subscription clears eviction cooldown
                self._evicted_cooldowns.pop(tradable, None)
                self._evicted_cooldowns.pop(s, None)
                if (
                    tradable not in self._subscribed
                    and tradable not in self._core_grid
                    and tradable not in self._todays_expiry
                    and tradable not in self._in_flight
                ):
                    self._scout[tradable] = now_ts
                    changed = True

            # If scout exceeds capacity, evict lowest-priority items first, protecting young scouts from thrashing
            if len(self._scout) > MAX_SCOUT_SLOTS:
                sorted_by_eviction = sorted(
                    self._scout.items(),
                    key=lambda item: (
                        _tbt_symbol_priority(item[0], primary_focus=self._primary_focus_index),
                        0 if (now_ts - item[1]) >= MIN_SCOUT_DWELL_SECONDS else 1,
                        item[1],
                    ),
                )
                excess = len(self._scout) - MAX_SCOUT_SLOTS
                for k, _ in sorted_by_eviction[:excess]:
                    del self._scout[k]
                    changed = True

            if changed:
                self.sync_subscriptions()

    def _do_subscribe(self, symbols: Set[str]) -> None:
        """Legacy helper maintained for backward compatibility."""
        self.sync_subscriptions()

    def unsubscribe(self, symbols: list[str]) -> None:
        """Unsubscribe symbols from Scout or In-Flight tracking across all workers."""
        with self._slots_lock:
            changed = False
            for s in symbols:
                tradable = resolve_tradable_tbt_symbol(s) or s
                if tradable in self._scout:
                    del self._scout[tradable]
                    changed = True
                if tradable in self._in_flight:
                    self._in_flight.remove(tradable)
                    changed = True

            if changed:
                self.sync_subscriptions()
            else:
                formatted = {resolve_tradable_tbt_symbol(s) or s for s in symbols}
                for w in self._workers:
                    w.unsubscribe(formatted)
                self._subscribed.difference_update(formatted)

    def sample_symbol(self, symbol: str, duration_sec: float = 120.0) -> bool:
        """
        Dynamically sample order-book depth for any index (e.g. FINNIFTY, SENSEX) or stock
        on a need basis without blocking core grid.
        Allocates to Elastic Scout pool with an automatic expiration timer.
        """
        tradable = resolve_tradable_tbt_symbol(symbol)
        if not tradable:
            return False
        if self._current_session in ("EQUITY_NFO", "OFF_MARKET") and not is_tbt_eligible_symbol(
            tradable
        ):
            logger.debug(
                f"[TbtManager] Non-NSE symbol {tradable} cannot be sampled on Fyers Versova TBT. "
                f"Routing to L2 WebSocket."
            )
            return False
        with self._slots_lock:
            self._evicted_cooldowns.pop(tradable, None)
            self._evicted_cooldowns.pop(symbol, None)
            self._scout[tradable] = time.time()
            if duration_sec > 0:
                self._scout_ttl[tradable] = duration_sec
            self.sync_subscriptions()
            logger.info(
                f"[TbtManager] Elastic Scout sampling symbol: {tradable} (Duration: {duration_sec}s)"
            )

        return True

    def auto_rotate_dynamic_grid(self, top_fno_movers: Optional[list[str]] = None) -> list[str]:
        """
        Autonomous Priority 15-Slot Grid Rotator:
          - Anchor Slots (3): Near-month futures (NIFTY, BANKNIFTY, MIDCPNIFTY).
          - Option Slots (up to 6): Today's active ATM CE/PE strikes for current index expiry.
          - Mover Slots (up to 6): Dynamically rotated with highest-velocity F&O leaders.
        """
        if top_fno_movers:
            for s in top_fno_movers[:6]:
                try:
                    self.promote_jit_scout(s, duration_sec=180.0, reason="TOP_FNO_MOVER")
                except Exception as _e:
                    logger.debug(f"[TbtManager] Failed to rotate mover {s}: {_e}")
        return list(self._subscribed)

    def promote_jit_scout(
        self,
        symbol: str,
        duration_sec: float = 60.0,
        reason: str = "PRE_INFLECTION",
    ) -> bool:
        """
        Just-In-Time (JIT) 50-Depth TBT Scout Promotion.
        Promotes an L1 radar candidate to the 15-slot TBT DOM stream for high-resolution
        order book audit (OBI-50, Icebergs, Wall Clearance) when entering an inflection kill zone.
        Automatically releases the slot after duration_sec unless refreshed or converted to in-flight.
        """
        tradable = resolve_tradable_tbt_symbol(symbol)
        if not tradable:
            return False
        if self._current_session in ("EQUITY_NFO", "OFF_MARKET") and not is_tbt_eligible_symbol(
            tradable
        ):
            return False

        # If a cash equity of an F&O stock is promoted, upgrade to its active Stock Future for JIT TBT
        if tradable.endswith("-EQ") or tradable.endswith(":EQ"):
            stock_fut = resolve_stock_future(tradable)
            if stock_fut:
                logger.info(
                    f"[TbtManager] Upgraded cash equity {tradable} to active Stock Future {stock_fut} for JIT TBT"
                )
                tradable = stock_fut

        with self._slots_lock:
            # Active JIT scout promotion overrides eviction cooldown
            self._evicted_cooldowns.pop(tradable, None)
            self._evicted_cooldowns.pop(symbol, None)
            if (
                tradable in self._core_grid
                or tradable in self._todays_expiry
                or tradable in self._in_flight
            ):
                return True

            now_t = time.time()
            self._scout[tradable] = now_t
            if duration_sec > 0:
                self._scout_ttl[tradable] = duration_sec

            if len(self._scout) > MAX_SCOUT_SLOTS:
                sorted_by_eviction = sorted(
                    self._scout.items(),
                    key=lambda item: (
                        _tbt_symbol_priority(item[0], primary_focus=self._primary_focus_index),
                        0 if (now_t - item[1]) >= MIN_SCOUT_DWELL_SECONDS else 1,
                        item[1],
                    ),
                )
                excess = len(self._scout) - MAX_SCOUT_SLOTS
                for k, _ in sorted_by_eviction[:excess]:
                    if k != tradable:
                        del self._scout[k]
                        self._scout_ttl.pop(k, None)

            self.sync_subscriptions()
            logger.info(
                f"[TbtManager] JIT Scout promoted: {tradable} (Reason: {reason}, Duration: {duration_sec:.0f}s)"
            )

        return True

    def cleanse_stale_scouts(self, ttl_sec: Optional[float] = None) -> int:
        """
        Cleanses any scout slots that:
          1. Have exceeded their designated retention duration (default 120.0s)
          2. Are dead / unresponsive: held >= 30s with ZERO packets received (depth timestamp is None)
          3. Are non-NSE / invalid for Fyers TBT (e.g. BSE, MCX, or malformed symbols)
        Returns the number of cleansed scout slots.
        """
        now = time.time()
        cleansed = 0
        try:
            from market.calendar import is_market_open

            is_active_market = is_market_open("NSE")
        except Exception:
            is_active_market = self._current_session not in ("OFF_MARKET", "COMMODITY_CDS")

        with self._slots_lock:
            stale_keys = []
            for sym, promoted_at in list(self._scout.items()):
                if sym in self._in_flight:
                    continue

                # Evict immediately if not valid NSE tradable symbol
                if not resolve_tradable_tbt_symbol(sym):
                    stale_keys.append(sym)
                    continue

                duration = now - promoted_at
                depth_data = self._depth_cache.get(sym, {})
                last_pkt_ts = depth_data.get("received_at") or depth_data.get("timestamp")

                # Condition 1: Exceeded normal scout TTL or designated duration
                custom_ttl = self._scout_ttl.get(sym)
                effective_ttl = (
                    custom_ttl
                    if custom_ttl is not None
                    else (ttl_sec if ttl_sec is not None else 120.0)
                )
                if duration >= effective_ttl:
                    stale_keys.append(sym)
                    continue

                # Condition 2: Dead scout fast-eviction (strictly during active market hours)
                # If held for >= 30s during active trading hours and has received ZERO packets,
                # it is dead on exchange/feed. During off-market/weekend, silence is normal.
                # Guard against false eviction when the worker servicing this symbol was offline/degraded.
                assigned_connected = (
                    any(w.connected and sym in w.subscribed for w in self._workers)
                    if self._workers
                    else True
                )
                if is_active_market and duration >= 30.0 and not last_pkt_ts and assigned_connected:
                    logger.info(
                        f"[TbtManager] Revolving idle TBT scout {sym}: zero packets received after {duration:.0f}s"
                    )
                    stale_keys.append(sym)
                    self._evicted_cooldowns[sym] = now + 60.0
                    continue

            for k in stale_keys:
                del self._scout[k]
                self._scout_ttl.pop(k, None)
                self._slot_allocated_at.pop(k, None)
                cleansed += 1

            # Condition 3: Dead sector scout fast-eviction (strictly during active market hours)
            # If an active sector scout has received zero packets for >= 45s during active market,
            # cool it down for 60s and rotate in another sector leader.
            # During off-market/weekend, silence is the normal exchange state.
            if is_active_market:
                for sym in list(self._sector_scouts):
                    if (
                        sym in self._subscribed
                        and sym not in self._in_flight
                        and sym not in self._core_grid
                        and sym not in self._scout
                    ):
                        alloc_t = self._slot_allocated_at.get(sym, now)
                        assigned_connected = (
                            any(w.connected and sym in w.subscribed for w in self._workers)
                            if self._workers
                            else True
                        )
                        if (now - alloc_t) >= 45.0 and assigned_connected:
                            depth_data = self._depth_cache.get(sym, {})
                            if not (depth_data.get("received_at") or depth_data.get("timestamp")):
                                logger.info(
                                    f"[TbtManager] Revolving idle sector scout {sym}: zero packets received after {now - alloc_t:.0f}s"
                                )
                                self._evicted_cooldowns[sym] = now + 60.0
                                if sym in self._sector_scouts:
                                    self._sector_scouts.remove(sym)
                                self._slot_allocated_at.pop(sym, None)
                                cleansed += 1

            # Also scrub any invalid/BSE/MCX from core and todays_expiry if any slipped in
            self._core_grid = [s for s in self._core_grid if resolve_tradable_tbt_symbol(s)]
            self._todays_expiry = [s for s in self._todays_expiry if resolve_tradable_tbt_symbol(s)]

            if cleansed > 0:
                self.sync_subscriptions()
                logger.info(
                    f"[TbtManager] Cleaned up {cleansed} stale/dead scout slots (Scout keys: {stale_keys})"
                )
        return cleansed

    def evict_symbol(self, symbol: str, cooldown_sec: float = 60.0) -> dict[str, Any]:
        """
        Manually evict a symbol from 15-slot TBT market depth.
        Immediately unsubscribes from WebSocket and applies an eviction cooldown
        so automated routines don't immediately re-subscribe it.
        """
        tradable = resolve_tradable_tbt_symbol(symbol) or symbol
        tradable_clean = symbol.strip().upper()
        candidates = {tradable, tradable_clean, symbol}

        with self._slots_lock:
            now = time.time()
            evicted_from = []

            # Check scout
            for c in list(self._scout.keys()):
                if c in candidates:
                    del self._scout[c]
                    self._scout_ttl.pop(c, None)
                    evicted_from.append("SCOUT")

            # Check in-flight
            for c in list(self._in_flight):
                if c in candidates:
                    self._in_flight.remove(c)
                    evicted_from.append("IN_FLIGHT")

            # Check core grid
            for c in list(self._core_grid):
                if c in candidates:
                    self._core_grid.remove(c)
                    evicted_from.append("CORE_GRID")

            # Check today's expiry
            for c in list(self._todays_expiry):
                if c in candidates:
                    self._todays_expiry.remove(c)
                    evicted_from.append("TODAYS_EXPIRY")

            for c in candidates:
                self._slot_allocated_at.pop(c, None)
                if cooldown_sec > 0:
                    self._evicted_cooldowns[c] = now + cooldown_sec

            # Direct WebSocket unsubscribe
            # Remove from workers
            for w in self._workers:
                w.unsubscribe(candidates)
            self._subscribed.difference_update(candidates)

            # Also synchronize remaining subscriptions
            self.sync_subscriptions()

            logger.info(
                f"[TbtManager] Operator evicted {tradable} (roles={evicted_from}, cooldown={cooldown_sec}s). "
                f"Active slots: {len(self._subscribed)}/{MAX_TBT_SYMBOLS}"
            )

            return {
                "status": "ok",
                "evicted_symbol": tradable,
                "evicted_from": evicted_from,
                "cooldown_seconds": cooldown_sec,
                "active_total": len(self._subscribed),
                "free_slots": max(0, MAX_TBT_SYMBOLS - len(self._subscribed)),
                "subscribed": sorted(self._subscribed),
            }

    def clear_eviction_cooldowns(self, symbol: Optional[str] = None) -> dict[str, Any]:
        """
        Instantly clears eviction cooldowns so symbols can be immediately re-subscribed
        without waiting for automated expiration timers.
        """
        now = time.time()
        with self._slots_lock:
            if symbol:
                tradable = resolve_tradable_tbt_symbol(symbol) or symbol
                self._evicted_cooldowns.pop(tradable, None)
                self._evicted_cooldowns.pop(symbol.strip().upper(), None)
                self._evicted_cooldowns.pop(symbol, None)
            else:
                self._evicted_cooldowns.clear()
            self.sync_subscriptions()
            remaining = {
                s: round(exp - now, 1) for s, exp in self._evicted_cooldowns.items() if exp > now
            }
            logger.info(
                f"[TbtManager] Eviction cooldowns cleared (target={symbol or 'ALL'}). Remaining: {len(remaining)}"
            )
            return {
                "status": "ok",
                "cleared": symbol or "ALL",
                "remaining_cooldowns": remaining,
                "active_total": len(self._subscribed),
                "free_slots": max(0, MAX_TBT_SYMBOLS - len(self._subscribed)),
                "subscribed": sorted(self._subscribed),
            }

    def rebalance_grid_now(self, session: Optional[str] = None) -> dict[str, Any]:
        """
        Manually trigger full TBT grid rebalance:
        1. Recovers multi-socket entitlement if probation expired or forced
        2. Reconnects quiescent/disconnected workers
        3. Cleanses stale scouts
        4. Re-evaluates spot prices for ATM strike rotation
        5. Synchronizes desired slots against market hierarchy
        """
        now = time.time()
        if (
            getattr(self, "_multi_socket_suppressed_until", 0.0) > 0
            and now >= self._multi_socket_suppressed_until
        ):
            self._multi_socket_suppressed_until = 0.0
        self._multi_socket_entitled = self._eval_multi_socket_entitled()

        if self._multi_socket_entitled and self._workers:
            for w in self._workers:
                if not w.connected and (
                    w.status == "DISCONNECTED"
                    or (w.status == "DEGRADED_429" and now >= w.degraded_until)
                ):
                    w.connect()

        cleansed = self.cleanse_stale_scouts(ttl_sec=30.0)
        revolved = self.revolve_atm_strikes(force=True)
        self._get_cached_sector_scouts(force_refresh=True)
        self.refresh_grid(session=session)
        logger.info(
            f"[TbtManager] Operator grid rebalance completed (cleansed={cleansed}, revolved={revolved}). "
            f"Active subscriptions: {len(self._subscribed)}/{MAX_TBT_SYMBOLS}"
        )
        return {
            "status": "ok",
            "cleansed_scouts_count": cleansed,
            "revolved": revolved,
            "active_total": len(self._subscribed),
            "free_slots": max(0, MAX_TBT_SYMBOLS - len(self._subscribed)),
            "subscribed": sorted(self._subscribed),
        }

    def get_active_slots_status(self) -> dict[str, Any]:
        """Audit status of all 15 TBT slots and current allocation breakdown with per-slot metrics."""
        now = time.time()
        with self._slots_lock:
            # Purge expired eviction cooldowns
            self._evicted_cooldowns = {
                s: exp for s, exp in self._evicted_cooldowns.items() if exp > now
            }

            slots = []
            desired_list = getattr(self, "_last_desired", None)
            if not desired_list:
                desired_list = list(self._subscribed)
            # Order subscribed symbols strictly by priority: desired_list first, then any remaining
            ordered_syms = [s for s in desired_list if s in self._subscribed]
            remaining = [s for s in self._subscribed if s not in ordered_syms]
            subscribed_list = ordered_syms + sorted(remaining)

            for idx, sym in enumerate(subscribed_list):
                if sym in self._in_flight:
                    role = "IN_FLIGHT_GUARDIAN"
                elif sym in self._core_grid:
                    role = "CORE_GRID"
                elif sym in self._todays_expiry:
                    role = "TODAYS_EXPIRY"
                elif sym in self._scout:
                    role = "DYNAMIC_SCOUT"
                elif sym in getattr(self, "_sector_scouts", []):
                    role = "SECTOR_LEADER_SCOUT"
                else:
                    role = "DYNAMIC_SCOUT"

                allocated_at = self._slot_allocated_at.get(sym, now)
                duration_sec = round(max(0.0, now - allocated_at), 1)

                depth_data = self._depth_cache.get(sym, {})
                if not depth_data or not depth_data.get("ltp"):
                    # Institutional passive RAM resolution (0 REST API calls)
                    try:
                        from market.websocket import ws_manager

                        tick = ws_manager.get_tick(sym)
                        if tick and getattr(tick, "ltp", 0.0) > 0:
                            depth_data = {
                                "ltp": tick.ltp,
                                "status": "WS_L1",
                                "timestamp": getattr(tick, "timestamp", now),
                                "received_at": getattr(
                                    tick, "received_at", getattr(tick, "timestamp", now)
                                ),
                                "obi_50": 0.0,
                                "density_score": 0.0,
                                "spread": 0.0,
                            }
                    except Exception as e:
                        logger.debug(f"[TbtManager] Fallback depth building suppressed: {e}")

                ltp_val = depth_data.get("ltp")
                if ltp_val is None or ltp_val == 0.0:
                    try:
                        from market.quotes import get_quote

                        q = get_quote([sym], ws_only=True).get(sym)
                        if q and getattr(q, "last_price", 0.0) > 0:
                            ltp_val = q.last_price
                    except Exception as e:
                        logger.debug(f"[TbtManager] Fallback get_quote suppressed: {e}")

                # Prefer local packet arrival timestamp to eliminate exchange clock skew
                last_local_ts = depth_data.get("received_at")
                if not last_local_ts:
                    last_pkt_ts = depth_data.get("timestamp")
                    if last_pkt_ts:
                        last_local_ts = (
                            float(last_pkt_ts)
                            if float(last_pkt_ts) < 2e9
                            else float(last_pkt_ts) / 1000.0
                        )

                if last_local_ts and float(last_local_ts) > 0:
                    pkt_age_s = round(max(0.0, now - float(last_local_ts)), 2)
                    threshold = (
                        TBT_LIVE_DEPTH_MAX_AGE_SECONDS
                        if depth_data.get("status") == "LIVE"
                        else 30.0
                    )
                    is_stale = (
                        (pkt_age_s > threshold)
                        if depth_data.get("status") != "L2_FALLBACK"
                        else False
                    )
                else:
                    pkt_age_s = None
                    is_stale = True

                slots.append(
                    {
                        "slot_number": idx + 1,
                        "symbol": sym,
                        "role": role,
                        "duration_seconds": duration_sec,
                        "last_packet_age_seconds": pkt_age_s,
                        "is_stale": is_stale,
                        "ltp": ltp_val,
                        "obi_50": depth_data.get("obi_50", 0.0),
                        "density_score": depth_data.get("density_score", 0.0),
                        "spread": depth_data.get("spread", 0.0),
                        "has_bid_wall": depth_data.get("has_bid_wall", False),
                        "has_ask_wall": depth_data.get("has_ask_wall", False),
                        "fortress_bid_wall_confirmed": depth_data.get(
                            "fortress_bid_wall_confirmed", False
                        ),
                        "fortress_ask_wall_confirmed": depth_data.get(
                            "fortress_ask_wall_confirmed", False
                        ),
                        "spoof_trap_warning": depth_data.get("spoof_trap_warning"),
                        "sentinel_intel": build_sentinel_decision_intel(depth_data),
                    }
                )

            return {
                "max_slots": MAX_TBT_SYMBOLS,
                "active_total": len(self._subscribed),
                "free_slots": max(0, MAX_TBT_SYMBOLS - len(self._subscribed)),
                "pool_status": [w.get_status() for w in self._workers],
                "workers_active": sum(1 for w in self._workers if w.connected),
                "workers_total": len(self._workers),
                "current_session": self._current_session,
                "session_state": (
                    "STANDBY_EOD"
                    if self._current_session in ("COMMODITY_CDS", "OFF_MARKET")
                    else "STREAMING_LIVE"
                ),
                "session_note": (
                    "NSE Equity & NFO closed at 15:30 IST. Versova L3 TBT socket on standby. Live evening depth for MCX Commodities is active on L2 Market Depth Radar."
                    if self._current_session in ("COMMODITY_CDS", "OFF_MARKET")
                    else "L3 50-Depth TBT streaming active on NSE benchmarks and dynamic scouts."
                ),
                "primary_focus": self._primary_focus_index,
                "last_atm_strikes": dict(self._last_atm_strikes),
                "in_flight": list(self._in_flight),
                "in_flight_without_tbt_subscription": [
                    s for s in self._in_flight if s not in self._subscribed
                ],
                "exposure_subscription_coverage": "COMPLETE"
                if all(s in self._subscribed for s in self._in_flight)
                else "INCOMPLETE",
                "core_grid": list(self._core_grid),
                "todays_expiry": list(self._todays_expiry),
                "scout": list(self._scout.keys()),
                "sector_scouts": list(getattr(self, "_sector_scouts", [])),
                "subscribed": subscribed_list,
                "slots": slots,
                "cooldowns": {s: round(exp - now, 1) for s, exp in self._evicted_cooldowns.items()},
            }

    def get_slot_allocation(self) -> dict[str, Any]:
        """Alias for get_active_slots_status."""
        return self.get_active_slots_status()

    def is_fresh_tbt_depth(self, target: Any, *, now: Optional[float] = None) -> bool:
        """Verify freshness of TBT depth snapshot or cached symbol."""
        if isinstance(target, dict):
            return is_fresh_tbt_depth(target, now=now)
        with self._depth_lock:
            snap = self._depth_cache.get(target) or self._depth_cache.get(
                str(target).split(":")[-1]
            )
        if not snap:
            return False
        return is_fresh_tbt_depth(snap, now=now)

    def get_50_depth(self, symbol: str, *, allow_rest_fallback: bool = False) -> dict[str, Any]:
        """
        Retrieve latest cached 50-depth for symbol.
        Defaults to strict in-memory lookup (0 REST calls).
        allow_rest_fallback: If True, falls back to L2 5-depth REST API.
        """
        from brokers.fyers import _to_fyers_symbol

        fyers_sym = _to_fyers_symbol(symbol)
        clean = symbol.split(":")[-1]

        with self._depth_lock:
            if symbol in self._depth_cache:
                return self._depth_cache[symbol]
            if fyers_sym in self._depth_cache:
                return self._depth_cache[fyers_sym]
            if clean in self._depth_cache:
                return self._depth_cache[clean]

        # Optional Fallback to Broker L2 5-depth REST API (only if explicitly allowed)
        if allow_rest_fallback:
            try:
                from brokers.session import get_data_broker

                brk = get_data_broker()
                if brk and hasattr(brk, "get_market_depth"):
                    d = brk.get_market_depth(symbol)
                    if d.get("status") == "ok":
                        return self._convert_l2_to_depth_format(symbol, d)
            except Exception as e_suppressed:
                logger.debug(
                    f"[market.fyers_tbt_manager] Non-fatal exception suppressed: {e_suppressed}"
                )

        return {
            "symbol": symbol,
            "status": "UNAVAILABLE",
            "message": "50-depth data stream awaiting live packets",
            "tbq": 0,
            "tsq": 0,
            "obi_50": 0.0,
            "density_score": 0.0,
            "bids": [],
            "asks": [],
            "bid_walls": [],
            "ask_walls": [],
        }

    def get_depth(self, symbol: str) -> dict[str, Any]:
        """Convenience alias for get_50_depth."""
        return self.get_50_depth(symbol)

    def _convert_l2_to_depth_format(self, symbol: str, l2: dict[str, Any]) -> dict[str, Any]:
        """Convert standard 5-level broker depth into compatible DOM structure."""
        raw_bids = l2.get("bids", []) or []
        raw_asks = l2.get("asks", []) or []

        bids = [
            {
                "level": i + 1,
                "price": float(b.get("price", 0.0)),
                "qty": int(b.get("volume", b.get("qty", 0))),
                "orders": int(b.get("orders", 1)),
            }
            for i, b in enumerate(raw_bids[:5])
            if float(b.get("price", 0.0)) > 0
        ]
        asks = [
            {
                "level": i + 1,
                "price": float(a.get("price", 0.0)),
                "qty": int(a.get("volume", a.get("qty", 0))),
                "orders": int(a.get("orders", 1)),
            }
            for i, a in enumerate(raw_asks[:5])
            if float(a.get("price", 0.0)) > 0
        ]

        tbq = int(l2.get("total_buy_qty", sum(b["qty"] for b in bids)))
        tsq = int(l2.get("total_sell_qty", sum(a["qty"] for a in asks)))
        denom = tbq + tsq
        obi = round((tbq - tsq) / max(1, denom), 4) if denom > 0 else 0.0

        ltp = float(l2.get("ltp", bids[0]["price"] if bids else 0.0))
        spread = round(asks[0]["price"] - bids[0]["price"], 2) if bids and asks else 0.0

        res = {
            "symbol": symbol,
            "status": "L2_FALLBACK",
            "timestamp": int(time.time()),
            "received_at": time.time(),
            "ltp": ltp,
            "spread": spread,
            "tbq": tbq,
            "tsq": tsq,
            "obi_50": obi,
            "density_score": round((len(bids) + len(asks)) / 10.0 * 100, 1),
            "bids_count": len(bids),
            "asks_count": len(asks),
            "bids": bids,
            "asks": asks,
            "bid_walls": [],
            "ask_walls": [],
            "has_bid_wall": False,
            "has_ask_wall": False,
            "fortress_bid_wall_confirmed": False,
            "fortress_ask_wall_confirmed": False,
            "spoof_trap_warning": None,
        }
        res["sentinel_intel"] = build_sentinel_decision_intel(res)
        return res

    def simulate_slippage(
        self,
        symbol: str,
        quantity: int,
        side: str = "BUY",
        max_age_seconds: Optional[float] = 3.0,
    ) -> dict[str, Any]:
        """
        Calculate volume-weighted fill price and slippage through the order book.
        Enforces depth freshness gate (max_age_seconds <= 3.0s) to prevent computing
        slippage against disconnected or stale order books.
        """
        depth = self.get_50_depth(symbol)
        now = time.time()
        if max_age_seconds is not None and "received_at" in depth:
            age = now - float(depth["received_at"])
            if age > max_age_seconds:
                return {
                    "status": "STALE_DEPTH",
                    "error": f"Order book depth is stale ({age:.1f}s > {max_age_seconds}s limit)",
                    "message": f"Order book depth is stale ({age:.1f}s > {max_age_seconds}s limit)",
                    "depth_age_seconds": round(age, 2),
                    "expected_vwap_price": None,
                }

        book = depth.get("asks", []) if side.upper() == "BUY" else depth.get("bids", [])
        if not book:
            return {"status": "UNAVAILABLE", "message": "Order book empty"}

        remaining = int(quantity)
        total_cost = 0.0
        levels_filled = 0
        top_price = book[0]["price"]

        for row in book:
            avail = row["qty"]
            price = row["price"]
            levels_filled += 1
            if remaining <= avail:
                total_cost += remaining * price
                remaining = 0
                break
            else:
                total_cost += avail * price
                remaining -= avail

        if remaining > 0:
            return {
                "status": "PARTIAL_FILL",
                "message": f"Order book exhausted. Remaining unfilled: {remaining} contracts",
                "requested_qty": quantity,
                "unfilled_qty": remaining,
            }

        vwap_fill = round(total_cost / max(1, quantity), 4)
        slippage_pts = round(abs(vwap_fill - top_price), 4)
        slippage_pct = round((slippage_pts / max(0.01, top_price)) * 100, 3)

        return {
            "status": "ok",
            "symbol": symbol,
            "side": side.upper(),
            "requested_qty": quantity,
            "top_of_book_price": top_price,
            "expected_vwap_price": vwap_fill,
            "estimated_slippage_pts": slippage_pts,
            "estimated_slippage_pct": slippage_pct,
            "depth_levels_swept": levels_filled,
        }

    def audit_candidate_depth(
        self,
        symbol: str,
        side: str = "BUY",
        lot_size: int = 65,
    ) -> dict[str, Any]:
        """
        Tier 2 Institutional 50-Depth Gatekeeper.
        Evaluates candidate setup quality, iceberg barriers, OBI-50, and liquidity density.
        """
        # Ensure symbol is registered for depth on order book
        tradable = resolve_tradable_tbt_symbol(symbol) or symbol
        self.subscribe([tradable])
        depth = self.get_50_depth(tradable)

        is_buy = side.upper() in ("BUY", "LONG")
        obi = float(depth.get("obi_50") or 0.0)
        density = float(depth.get("density_score") or 0.0)
        ltp = float(depth.get("ltp") or 0.0)

        findings = []
        penalties = 0
        bonuses = 0

        # 1. Order Book Imbalance (OBI-50)
        if is_buy:
            if obi >= 0.25:
                bonuses += 20
                findings.append(f"Strong bid absorption (OBI-50: +{obi:.2f})")
            elif obi <= -0.30:
                penalties += 35
                findings.append(f"Severe ask pressure overhead (OBI-50: {obi:.2f})")
        else:
            if obi <= -0.25:
                bonuses += 20
                findings.append(f"Strong ask distribution (OBI-50: {obi:.2f})")
            elif obi >= 0.30:
                penalties += 35
                findings.append(f"Strong bid support absorbing sells (OBI-50: +{obi:.2f})")

        # 2. Iceberg / Resting Wall Barrier Check
        ask_walls = depth.get("ask_walls", [])
        bid_walls = depth.get("bid_walls", [])

        if is_buy and ask_walls:
            # Check if wall is within 2.5% of LTP (immediate roadblock)
            near_walls = [w for w in ask_walls if ltp > 0 and w["price"] <= ltp * 1.025]
            if near_walls:
                top_w = near_walls[0]
                str_lbl = top_w.get("strength", "STRONG")
                penalties += 35 if str_lbl == "FORTRESS" else (30 if str_lbl == "STRONG" else 20)
                findings.append(
                    f"[{str_lbl}] Institutional Ask Wall capping upside at ₹{top_w['price']} "
                    f"({top_w['qty']:,} contracts, {top_w.get('book_share_pct', 0)}% book share)"
                )
            else:
                bonuses += 5
                findings.append("No immediate institutional ask walls within +2.5%")
        elif not is_buy and bid_walls:
            near_bid_walls = [w for w in bid_walls if ltp > 0 and w["price"] >= ltp * 0.975]
            if near_bid_walls:
                top_w = near_bid_walls[0]
                str_lbl = top_w.get("strength", "STRONG")
                penalties += 35 if str_lbl == "FORTRESS" else (30 if str_lbl == "STRONG" else 20)
                findings.append(
                    f"[{str_lbl}] Institutional Bid Floor blocking downside at ₹{top_w['price']} "
                    f"({top_w['qty']:,} contracts, {top_w.get('book_share_pct', 0)}% book share)"
                )

        # 3. Density / Liquidity Quality Check
        if density < 15.0 and depth.get("status") != "L2_FALLBACK":
            penalties += 25
            findings.append(f"Thin order book density ({density:.1f}% slots filled)")
        else:
            bonuses += 10
            findings.append(f"Adequate book liquidity density ({density:.1f}%)")

        # 4. Slippage Check for 1 standard lot
        slip = self.simulate_slippage(symbol, quantity=lot_size, side=side)
        if slip.get("status") == "ok":
            slip_pct = slip.get("estimated_slippage_pct", 0.0)
            if slip_pct > 0.45:
                penalties += 20
                findings.append(f"High market order impact slippage ({slip_pct:.2f}%)")
            else:
                bonuses += 10
                findings.append(f"Minimal execution slippage ({slip_pct:.2f}%)")
        elif slip.get("status") == "STALE_DEPTH":
            penalties += 15
            findings.append("Stale depth stream (slippage unverified)")

        raw_score = 50 + bonuses - penalties
        final_conviction = max(0, min(100, raw_score))

        verdict = (
            "PASS"
            if final_conviction >= 65
            else ("CAUTION" if final_conviction >= 45 else "REJECT")
        )

        return {
            "symbol": symbol,
            "side": side.upper(),
            "verdict": verdict,
            "depth_conviction_score": final_conviction,
            "obi_50": obi,
            "density_score": density,
            "findings": findings,
            "audit_timestamp": int(time.time()),
        }

    def get_realtime_orderbook_greeks(
        self,
        symbol: str,
        spot: Optional[float] = None,
        allow_rest_fallback: bool = False,
    ) -> dict[str, Any]:
        """Wrapper method on FyersTbtManager singleton to fuse 50-DOM and GEX/DEX."""
        return get_realtime_orderbook_greeks(
            symbol, spot=spot, allow_rest_fallback=allow_rest_fallback
        )


# Global Singleton Instance
fyers_tbt_manager = FyersTbtManager()


def promote_jit_tbt_scout(
    symbol: str, duration_sec: float = 60.0, reason: str = "PRE_INFLECTION"
) -> bool:
    """Convenience helper to promote a symbol to Fyers TBT 50-depth stream."""
    return fyers_tbt_manager.promote_jit_scout(symbol, duration_sec=duration_sec, reason=reason)


def get_realtime_orderbook_greeks(
    symbol: str,
    spot: Optional[float] = None,
    allow_rest_fallback: bool = False,
) -> dict[str, Any]:
    """
    Fuses real-time Fyers 50-level Level-3 Depth (DOM) with Gamma Exposure (GEX)
    and Dealer Delta Exposure (DEX) to compute Institutional Microstructure Wall Conviction.

    Cross-correlates:
      1. DOM Resting Bid Walls vs GEX Put Walls (Support Confluence).
      2. DOM Resting Ask Walls vs GEX Call Walls (Resistance Confluence).
      3. OBI-50 Order Book Imbalance vs DEX Net Delta Regime (Short-covering / Cascade risk).
    """
    from engine.alert_identity import canonical_alert_symbol

    clean_sym = canonical_alert_symbol(symbol)
    spot_val = float(spot or 0.0)

    # Resolve spot if not supplied
    if spot_val <= 0:
        try:
            from market.quotes import get_quote

            q = get_quote([clean_sym])
            q_obj = q.get(clean_sym) or (list(q.values())[0] if q else None)
            if q_obj:
                spot_val = float(
                    getattr(q_obj, "ltp", 0.0) or getattr(q_obj, "last_price", 0.0) or 0.0
                )
        except Exception as e_spot:
            logger.debug(f"[get_realtime_orderbook_greeks] Spot lookup note: {e_spot}")

    # Step 1: Query DOM 50-Depth
    depth_data = fyers_tbt_manager.get_50_depth(clean_sym, allow_rest_fallback=allow_rest_fallback)
    if (
        not depth_data or depth_data.get("status") == "UNAVAILABLE" or not depth_data.get("bids")
    ) and clean_sym in ("NIFTY", "BANKNIFTY", "SENSEX", "MIDCPNIFTY"):
        fut_sym = resolve_tradable_tbt_symbol(clean_sym)
        if fut_sym:
            depth_data = fyers_tbt_manager.get_50_depth(
                fut_sym, allow_rest_fallback=allow_rest_fallback
            )

    bids = depth_data.get("bids", []) or []
    asks = depth_data.get("asks", []) or []

    # Extract dominant resting walls
    bid_wall = None
    ask_wall = None
    if bids:
        bid_wall = max(bids, key=lambda b: (int(b.get("qty", 0)), int(b.get("orders", 1))))
    if asks:
        ask_wall = max(asks, key=lambda a: (int(a.get("qty", 0)), int(a.get("orders", 1))))

    obi_50 = float(depth_data.get("obi_50", 0.0) or 0.0)
    density_score = float(depth_data.get("density_score", 0.0) or 0.0)
    fortress_bid = bool(depth_data.get("fortress_bid_wall_confirmed", False))
    fortress_ask = bool(depth_data.get("fortress_ask_wall_confirmed", False))

    # Step 2: Query GEX & DEX Analysis
    call_wall = 0.0
    put_wall = 0.0
    gamma_flip = 0.0
    dex_regime = "BALANCED"
    dex_neutral = 0.0
    net_gex_cr = 0.0
    net_dex_cr = 0.0

    try:
        from analysis.gex import get_gex_analysis

        gex_res = get_gex_analysis(clean_sym, spot=spot_val if spot_val > 0 else None)
        if gex_res:
            call_wall = float(gex_res.call_wall or 0.0)
            put_wall = float(gex_res.put_wall or 0.0)
            gamma_flip = float(gex_res.gamma_flip or 0.0)
            dex_regime = str(getattr(gex_res, "dex_regime", "BALANCED"))
            dex_neutral = float(getattr(gex_res, "dex_neutral_level", 0.0) or 0.0)
            net_gex_cr = float(gex_res.total_net_gex_cr or 0.0)
            net_dex_cr = float(getattr(gex_res, "total_net_dex_cr", 0.0) or 0.0)
    except Exception as e_gex:
        logger.debug(f"[get_realtime_orderbook_greeks] GEX lookup note: {e_gex}")

    # Step 3: Compute Confluence between DOM walls and GEX walls
    bid_confluence = False
    ask_confluence = False
    step = 100.0 if clean_sym in ("BANKNIFTY", "SENSEX", "BANKEX") else 50.0

    if bid_wall and put_wall > 0:
        bid_p = float(bid_wall.get("price", 0.0))
        if abs(bid_p - put_wall) <= step * 1.2:
            bid_confluence = True

    if ask_wall and call_wall > 0:
        ask_p = float(ask_wall.get("price", 0.0))
        if abs(ask_p - call_wall) <= step * 1.2:
            ask_confluence = True

    # Step 4: Microstructure Wall Conviction Score (0 to 100)
    conviction = 50
    if bid_confluence:
        conviction += 20
    if ask_confluence:
        conviction += 20
    if fortress_bid or fortress_ask:
        conviction += 10
    if obi_50 > 0.25 and "SHORT_DELTA" in dex_regime:
        conviction += 12
    elif obi_50 < -0.25 and "LONG_DELTA" in dex_regime:
        conviction += 12
    conviction = max(10, min(98, conviction))

    # Step 5: Wall Bias & Actionable plain Synthesis
    if bid_confluence and obi_50 >= 0:
        wall_bias = "STRONG_SUPPORT_CONFIRMED"
        synthesis = (
            f"CONFLUENCE: Resting DOM Bid Wall at ₹{bid_wall.get('price', 0):,.1f} reinforces GEX Put Wall ₹{put_wall:,.0f}. "
            f"Institutional buyers provide solid double-layer cushion against downside."
        )
    elif ask_confluence and obi_50 <= 0:
        wall_bias = "STRONG_RESISTANCE_CONFIRMED"
        synthesis = (
            f"CONFLUENCE: Resting DOM Ask Wall at ₹{ask_wall.get('price', 0):,.1f} reinforces GEX Call Wall ₹{call_wall:,.0f}. "
            f"Heavy institutional sell supply acts as overhead ceiling."
        )
    elif obi_50 > 0.20 and "SHORT_DELTA" in dex_regime:
        wall_bias = "SQUEEZE_ALERT"
        synthesis = (
            f"SQUEEZE FUEL: Order book heavily bid (OBI {obi_50:+.2f}) with Dealer Short Delta ({net_dex_cr:+.1f} Cr). "
            f"Short covering squeeze likely on push above Call Wall ₹{call_wall:,.0f}."
        )
    elif obi_50 < -0.20 and "LONG_DELTA" in dex_regime:
        wall_bias = "CASCADE_ALERT"
        synthesis = (
            f"CASCADE RISK: Order book heavily offered (OBI {obi_50:+.2f}) with Dealer Long Delta ({net_dex_cr:+.1f} Cr). "
            f"Long liquidation cascade likely on breakdown below Put Wall ₹{put_wall:,.0f}."
        )
    else:
        wall_bias = "BALANCED_RANGE"
        synthesis = (
            f"BALANCED MICROSTRUCTURE: OBI {obi_50:+.2f} | Put Wall: ₹{put_wall:,.0f} | "
            f"Call Wall: ₹{call_wall:,.0f} | Gamma Flip: ₹{gamma_flip:,.0f}."
        )

    return {
        "symbol": clean_sym,
        "spot": spot_val,
        "dom_status": depth_data.get("status", "OK"),
        "obi_50": round(obi_50, 4),
        "density_score": round(density_score, 1),
        "dom_bid_wall": bid_wall,
        "dom_ask_wall": ask_wall,
        "fortress_bid_wall": fortress_bid,
        "fortress_ask_wall": fortress_ask,
        "gex_call_wall": call_wall,
        "gex_put_wall": put_wall,
        "gex_gamma_flip": gamma_flip,
        "dex_regime": dex_regime,
        "dex_neutral_level": dex_neutral,
        "total_net_gex_cr": round(net_gex_cr, 2),
        "total_net_dex_cr": round(net_dex_cr, 2),
        "bid_confluence": bid_confluence,
        "ask_confluence": ask_confluence,
        "microstructure_wall_conviction": conviction,
        "wall_bias": wall_bias,
        "synthesis": synthesis,
    }
