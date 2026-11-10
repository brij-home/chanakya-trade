"""Listed-contract selection shared by subscription planners.

No price defaults, calendar symbol construction or inferred strike increments.
Subscription eligibility does not establish contract liquidity or execution safety.
"""

from dataclasses import dataclass
from datetime import datetime, date
import logging
import math
from typing import Any, Mapping

from config.constants import IST
from market.instruments import canonical_symbol
from market.rule_schedule import derivative_close

logger = logging.getLogger(__name__)
GRID_QUOTE_MAX_AGE_SECONDS = 10.0


@dataclass(frozen=True)
class ListedContract:
    symbol: str
    underlying: str
    expiry: date
    option_type: str
    strike: float | None
    lot_size: int
    tick_size: float
    token: str


@dataclass(frozen=True)
class ActiveContractResolution:
    contract: ListedContract | None
    is_valid: bool
    rejection_reason: str | None = None
    row: dict[str, Any] | None = None


def validate_master_contract_row(
    row: Any,
    *,
    key: str | None = None,
    expected_exchange: str | None = None,
    expected_underlying: str | None = None,
    as_of: datetime,
) -> ActiveContractResolution:
    """Validate a raw instrument master row against exchange tradability invariants."""
    if as_of.tzinfo is None:
        raise ValueError("Contract selection requires an aware reference timestamp")
    now = as_of.astimezone(IST)
    if not isinstance(row, dict):
        return ActiveContractResolution(None, False, "ROW_NOT_DICT")

    symbol = str(row.get("symTicker") or key or "").strip()
    if not symbol:
        return ActiveContractResolution(None, False, "EMPTY_SYMBOL_TICKER")

    if key and row.get("symTicker") and row.get("symTicker") != key:
        return ActiveContractResolution(
            None, False, f"KEY_SYMBOL_MISMATCH: key={key}, symTicker={row.get('symTicker')}"
        )

    # Validate venue/exchange
    if ":" not in symbol:
        return ActiveContractResolution(None, False, f"MALFORMED_SYMBOL_NO_VENUE: {symbol}")
    symbol_venue = symbol.split(":", 1)[0].upper()
    if symbol_venue not in {"NSE", "BSE"}:
        return ActiveContractResolution(None, False, f"UNSUPPORTED_EXCHANGE: {symbol_venue}")
    if expected_exchange:
        norm_expected = {"NFO": "NSE", "BFO": "BSE"}.get(
            expected_exchange.upper(), expected_exchange.upper()
        )
        if symbol_venue != norm_expected:
            return ActiveContractResolution(
                None, False, f"EXCHANGE_MISMATCH: expected {norm_expected}, got {symbol_venue}"
            )

    # Validate underlying
    from engine.option_resolver import is_index_symbol

    raw_und = row.get("underSym") or row.get("exSymbol")
    if not raw_und:
        return ActiveContractResolution(None, False, "MISSING_UNDERLYING")
    clean_und = canonical_symbol(str(raw_und))
    if expected_underlying and clean_und != canonical_symbol(expected_underlying):
        return ActiveContractResolution(
            None,
            False,
            f"UNDERLYING_MISMATCH: expected {expected_underlying}, got {clean_und}",
        )

    # Validate trade status
    trade_status = row.get("tradeStatus")
    if trade_status not in (1, "1"):
        return ActiveContractResolution(None, False, f"INACTIVE_TRADE_STATUS: {trade_status}")

    # Validate token
    token = str(row.get("fyToken") or "").strip()
    if not token or token == "0":
        return ActiveContractResolution(None, False, "MISSING_OR_ZERO_TOKEN")

    # Validate expiry and cutoff
    try:
        expiry_val = row["expiryDate"]
        if isinstance(expiry_val, bool) or not str(expiry_val).strip():
            return ActiveContractResolution(None, False, "INVALID_EXPIRY_DATE")
        expiry = datetime.fromtimestamp(float(expiry_val), IST).date()
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return ActiveContractResolution(None, False, "UNPARSEABLE_EXPIRY_DATE")

    cutoff = derivative_close(expiry, expiring_index=is_index_symbol(clean_und))
    if expiry < now.date() or (expiry == now.date() and now.time() >= cutoff):
        return ActiveContractResolution(
            None, False, f"EXPIRED_OR_PAST_CUTOFF: expiry={expiry}, cutoff={cutoff}"
        )

    # Validate lot size (strictly non-bool, positive finite integer)
    lot_val = row.get("minLotSize")
    if isinstance(lot_val, bool):
        return ActiveContractResolution(None, False, "BOOL_LOT_SIZE_REJECTED")
    try:
        lot = float(lot_val)
    except (TypeError, ValueError):
        return ActiveContractResolution(None, False, f"INVALID_LOT_SIZE: {lot_val}")
    if not math.isfinite(lot) or not lot.is_integer() or lot <= 0:
        return ActiveContractResolution(None, False, f"NON_POSITIVE_OR_FRACTIONAL_LOT: {lot_val}")

    # Validate tick size (strictly non-bool, positive finite)
    tick_val = row.get("tickSize")
    if isinstance(tick_val, bool):
        return ActiveContractResolution(None, False, "BOOL_TICK_SIZE_REJECTED")
    try:
        tick = float(tick_val)
    except (TypeError, ValueError):
        return ActiveContractResolution(None, False, f"INVALID_TICK_SIZE: {tick_val}")
    if not math.isfinite(tick) or tick <= 0:
        return ActiveContractResolution(None, False, f"NON_POSITIVE_OR_NONFINITE_TICK: {tick_val}")

    # Validate option type & strike
    option_type = str(row.get("optType") or "").upper().strip()
    if option_type in {"CE", "PE"}:
        strike_val = row.get("strikePrice")
        if isinstance(strike_val, bool):
            return ActiveContractResolution(None, False, "BOOL_STRIKE_REJECTED")
        try:
            strike = float(strike_val)
        except (TypeError, ValueError):
            return ActiveContractResolution(None, False, f"INVALID_STRIKE: {strike_val}")
        if not math.isfinite(strike) or strike <= 0 or not symbol.endswith(option_type):
            return ActiveContractResolution(
                None,
                False,
                f"STRIKE_OR_SYMBOL_MISMATCH: strike={strike_val}, symbol={symbol}",
            )
    elif option_type in {"XX", ""} and symbol.endswith("FUT"):
        strike = None
        option_type = "FUT"
    else:
        return ActiveContractResolution(None, False, f"INVALID_OPTION_TYPE: {option_type}")

    contract = ListedContract(
        symbol=symbol,
        underlying=clean_und,
        expiry=expiry,
        option_type=option_type,
        strike=strike,
        lot_size=int(lot),
        tick_size=tick,
        token=token,
    )
    return ActiveContractResolution(contract=contract, is_valid=True, row=row)


def contracts_from_master(
    records: Mapping[str, Any], underlying: str, *, exchange: str, as_of: datetime
) -> list[ListedContract]:
    """Read exact rows, excluding malformed, suspended, mismatched or expired contracts."""
    clean = canonical_symbol(underlying)
    result = []
    for key, row in records.items():
        res = validate_master_contract_row(
            row,
            key=key,
            expected_exchange=exchange,
            expected_underlying=clean,
            as_of=as_of,
        )
        if res.is_valid and res.contract:
            result.append(res.contract)
    return sorted(result, key=lambda c: (c.expiry, c.strike or 0, c.option_type, c.symbol))


def resolve_active_contract(
    symbol: str,
    *,
    as_of: datetime | None = None,
    require_fresh: bool = True,
    expected_underlying: str | None = None,
    expected_venue: str | None = None,
) -> ActiveContractResolution:
    """Authoritative active listed contract resolver across NSE/BSE derivatives.

    Validates that a symbol corresponds to a currently listed, active, unexpired contract
    with valid token, whole positive lot size, positive tick, and matching underlying.
    """
    if not symbol or not isinstance(symbol, str):
        return ActiveContractResolution(None, False, "EMPTY_OR_INVALID_SYMBOL")

    clean_sym = symbol.strip()
    if ":" in clean_sym:
        prefix, bare = clean_sym.split(":", 1)
    else:
        prefix, bare = "", clean_sym

    canonical_expected = None
    if expected_venue:
        canonical_expected = {"NFO": "NSE", "BFO": "BSE"}.get(
            expected_venue.upper(), expected_venue.upper()
        )

    if prefix:
        canonical_prefix = {"NFO": "NSE", "BFO": "BSE"}.get(prefix.upper(), prefix.upper())
        if canonical_expected and canonical_prefix != canonical_expected:
            return ActiveContractResolution(
                None,
                False,
                f"VENUE_MISMATCH: prefix '{prefix}' conflicts with expected venue '{expected_venue}'",
            )
        venue = canonical_prefix
    elif canonical_expected:
        venue = canonical_expected
    else:
        bare_upper = bare.upper()
        if bare_upper.startswith(("SENSEX", "BANKEX")):
            venue = "BSE"
        else:
            venue = "NSE"

    if venue not in {"NSE", "BSE"}:
        return ActiveContractResolution(None, False, f"UNSUPPORTED_EXCHANGE: {venue}")

    canonical_ticker = f"{venue}:{bare}"
    ref_time = as_of or datetime.now(IST)
    if ref_time.tzinfo is None:
        raise ValueError("Contract resolution requires an aware reference timestamp")

    from market.symbol_master import get_symbol_info

    try:
        row = get_symbol_info(canonical_ticker, require_fresh=require_fresh)
        if not row and clean_sym != canonical_ticker:
            row = get_symbol_info(clean_sym, require_fresh=require_fresh)
    except RuntimeError as exc:
        return ActiveContractResolution(None, False, f"DEGRADED_OR_UNAVAILABLE_MASTER: {exc}")
    except Exception as exc:
        return ActiveContractResolution(None, False, f"MASTER_LOOKUP_ERROR: {exc}")

    if not row or not isinstance(row, dict):
        return ActiveContractResolution(None, False, f"CONTRACT_NOT_FOUND: {canonical_ticker}")

    # Use row with default symTicker if missing
    row_with_key = dict(row)
    row_with_key.setdefault("symTicker", canonical_ticker)

    # Verify exact contract ticker equality (E04)
    bare_clean = bare.upper()
    row_ticker = str(row_with_key.get("symTicker", "")).split(":")[-1].upper()
    if row_ticker and bare_clean != row_ticker:
        return ActiveContractResolution(
            None,
            False,
            f"CONTRACT_TICKER_MISMATCH: requested '{canonical_ticker}' != master '{row_with_key.get('symTicker')}'",
        )

    return validate_master_contract_row(
        row_with_key,
        key=row_with_key.get("symTicker", canonical_ticker),
        expected_exchange=venue,
        expected_underlying=expected_underlying,
        as_of=ref_time,
    )


@dataclass(frozen=True)
class ProvenanceValidationResult:
    is_valid: bool
    rejection_reason: str | None = None
    as_of: datetime | None = None
    age_seconds: float | None = None
    provider: str | None = None
    observation_time: datetime | None = None
    receipt_time: datetime | None = None
    is_receipt_only: bool = False
    observation_age_seconds: float | None = None


def validate_options_snapshot_provenance(
    source_info: Any,
    *,
    as_of: datetime | None = None,
    max_age_seconds: float = 15.0,
) -> ProvenanceValidationResult:
    """Validate snapshot provenance against strict live market evidence contracts."""
    if not isinstance(source_info, dict):
        return ProvenanceValidationResult(False, "SOURCE_INFO_NOT_DICT")

    # 1. Source check: strictly BROKER_REST for actionable live enrichment
    source = str(source_info.get("source") or "").upper().strip()
    if source != "BROKER_REST":
        return ProvenanceValidationResult(False, f"UNTRUSTED_SOURCE: {source}")

    # 2. Data state check
    data_state = str(source_info.get("data_state") or "").upper().strip()
    if data_state != "LIVE":
        return ProvenanceValidationResult(False, f"NON_LIVE_DATA_STATE: {data_state}")

    # 3. Realtime and market-open flags
    if source_info.get("is_realtime") is not True:
        return ProvenanceValidationResult(False, "NOT_REALTIME")
    if source_info.get("is_market_open") is not True:
        return ProvenanceValidationResult(False, "MARKET_NOT_OPEN")

    # 4. Provider identity and simulation exclusion
    provider = str(source_info.get("provider") or "").upper().strip()
    if not provider or provider in {"UNKNOWN", "NONE"}:
        return ProvenanceValidationResult(False, "MISSING_OR_UNKNOWN_PROVIDER")
    if any(
        marker in provider
        for marker in ("MOCK", "TEST", "SYNTHETIC", "SIMULATED", "SIMULATION", "PAPER")
    ):
        return ProvenanceValidationResult(False, f"SIMULATED_OR_MOCK_PROVIDER: {provider}")

    # 5. Timestamp validation
    raw_as_of = source_info.get("as_of")
    if not raw_as_of:
        return ProvenanceValidationResult(False, "MISSING_AS_OF_TIMESTAMP")

    if isinstance(raw_as_of, datetime):
        source_time = raw_as_of
    else:
        try:
            source_time = datetime.fromisoformat(str(raw_as_of).replace("Z", "+00:00"))
        except (TypeError, ValueError, OverflowError):
            return ProvenanceValidationResult(False, f"UNPARSEABLE_AS_OF_TIMESTAMP: {raw_as_of}")

    # Strict rejection of naive timestamps
    if source_time.tzinfo is None:
        return ProvenanceValidationResult(False, f"NAIVE_TIMESTAMP_REJECTED: {raw_as_of}")

    from datetime import timezone

    ref_time = as_of or datetime.now(timezone.utc)
    if ref_time.tzinfo is None:
        raise ValueError("as_of reference time must be timezone-aware")

    source_utc = source_time.astimezone(timezone.utc)
    ref_utc = ref_time.astimezone(timezone.utc)
    age_seconds = (ref_utc - source_utc).total_seconds()

    CLOCK_SKEW_TOLERANCE_SECONDS = 0.5
    if not math.isfinite(age_seconds):
        return ProvenanceValidationResult(False, "NON_FINITE_AGE")
    if age_seconds < -CLOCK_SKEW_TOLERANCE_SECONDS:
        return ProvenanceValidationResult(
            False,
            f"FUTURE_AS_OF_TIMESTAMP: age={age_seconds:.2f}s exceeds {CLOCK_SKEW_TOLERANCE_SECONDS}s tolerance",
        )
    if age_seconds > max_age_seconds:
        return ProvenanceValidationResult(
            False, f"STALE_SNAPSHOT: as_of age={age_seconds:.2f}s > {max_age_seconds}s"
        )

    obs_time = None
    obs_age_sec = None
    is_receipt_only = True
    if source_info.get("observation_time"):
        raw_obs = source_info["observation_time"]
        if isinstance(raw_obs, datetime):
            obs_dt = raw_obs
        else:
            try:
                obs_dt = datetime.fromisoformat(str(raw_obs).replace("Z", "+00:00"))
            except (TypeError, ValueError, OverflowError):
                return ProvenanceValidationResult(False, f"MALFORMED_OBSERVATION_TIME: {raw_obs}")
        if obs_dt.tzinfo is None:
            return ProvenanceValidationResult(False, f"NAIVE_OBSERVATION_TIME_REJECTED: {raw_obs}")
        obs_utc = obs_dt.astimezone(timezone.utc)
        obs_age = (ref_utc - obs_utc).total_seconds()
        if not math.isfinite(obs_age):
            return ProvenanceValidationResult(False, "NON_FINITE_OBSERVATION_AGE")
        if obs_age < -CLOCK_SKEW_TOLERANCE_SECONDS:
            return ProvenanceValidationResult(
                False,
                f"FUTURE_OBSERVATION_TIME: age={obs_age:.2f}s exceeds {CLOCK_SKEW_TOLERANCE_SECONDS}s tolerance",
            )
        if obs_age > max_age_seconds:
            return ProvenanceValidationResult(
                False, f"STALE_OBSERVATION_TIME: age={obs_age:.2f}s > {max_age_seconds}s"
            )
        obs_time = obs_dt
        obs_age_sec = obs_age
        is_receipt_only = False

    rcpt_time = None
    if source_info.get("receipt_time"):
        raw_rcpt = source_info["receipt_time"]
        if isinstance(raw_rcpt, datetime):
            rcpt_dt = raw_rcpt
        else:
            try:
                rcpt_dt = datetime.fromisoformat(str(raw_rcpt).replace("Z", "+00:00"))
            except (TypeError, ValueError, OverflowError):
                return ProvenanceValidationResult(False, f"MALFORMED_RECEIPT_TIME: {raw_rcpt}")
        if rcpt_dt.tzinfo is None:
            return ProvenanceValidationResult(False, f"NAIVE_RECEIPT_TIME_REJECTED: {raw_rcpt}")
        rcpt_utc = rcpt_dt.astimezone(timezone.utc)
        rcpt_age = (ref_utc - rcpt_utc).total_seconds()
        if not math.isfinite(rcpt_age):
            return ProvenanceValidationResult(False, "NON_FINITE_RECEIPT_AGE")
        if rcpt_age < -CLOCK_SKEW_TOLERANCE_SECONDS:
            return ProvenanceValidationResult(
                False,
                f"FUTURE_RECEIPT_TIME: age={rcpt_age:.2f}s exceeds {CLOCK_SKEW_TOLERANCE_SECONDS}s tolerance",
            )
        if rcpt_age > max_age_seconds:
            return ProvenanceValidationResult(
                False, f"STALE_RECEIPT_TIME: age={rcpt_age:.2f}s > {max_age_seconds}s"
            )
        if obs_time is not None:
            skew = (obs_utc - rcpt_utc).total_seconds()
            if skew > CLOCK_SKEW_TOLERANCE_SECONDS:
                return ProvenanceValidationResult(
                    False, f"OUT_OF_ORDER_RECEIPT_PRECEDES_OBSERVATION: skew={skew:.2f}s"
                )
        rcpt_time = rcpt_dt
    else:
        rcpt_time = source_time

    return ProvenanceValidationResult(
        is_valid=True,
        as_of=source_time,
        age_seconds=age_seconds,
        provider=provider,
        observation_time=obs_time,
        receipt_time=rcpt_time,
        is_receipt_only=is_receipt_only,
        observation_age_seconds=obs_age_sec,
    )


def get_listed_contracts(
    underlying: str, *, exchange: str | None = None, as_of: datetime | None = None
) -> list[ListedContract]:
    from market.symbol_master import load_master
    from market.indices import INDEX_INSTRUMENTS

    clean = canonical_symbol(underlying)
    instrument = INDEX_INSTRUMENTS.get(clean, "")
    venue = exchange or (instrument.split(":")[0] if instrument else "NSE")
    venue = {"NFO": "NSE", "BFO": "BSE"}.get(venue.upper(), venue.upper())
    if venue not in {"NSE", "BSE"}:
        return []
    try:
        records = load_master(f"{venue}_FO", offline_fallback=False)
        return contracts_from_master(
            records, clean, exchange=venue, as_of=as_of or datetime.now(IST)
        )
    except (RuntimeError, ValueError, OSError) as exc:
        logger.warning(
            "[ContractSelection] Listed contracts unavailable for %s/%s: %s", venue, clean, exc
        )
        return []


def fresh_underlying_price(
    quote: Any, *, as_of: datetime, max_age_seconds: float = GRID_QUOTE_MAX_AGE_SECONDS
) -> float | None:
    """Require explicit live provenance and nonfuture receipt evidence, even in PAPER."""
    try:
        price = float(quote.last_price)
        received = datetime.fromisoformat(quote.received_at.replace("Z", "+00:00"))
        if received.tzinfo is None or as_of.tzinfo is None:
            return None
        age = (as_of - received).total_seconds()
        if str(quote.data_state).upper() != "LIVE" or str(quote.source).upper() not in {
            "STREAM",
            "REST",
            "CACHE",
        }:
            return None
        provider = str(quote.provider).upper()
        if provider in {"", "UNKNOWN"} or any(
            marker in provider for marker in ("MOCK", "TEST", "SYNTHETIC", "SIMULATED")
        ):
            return None
        # Allow up to 250ms of execution jitter / sub-second clock skew between evaluation as_of and quote receipt
        if (
            not math.isfinite(price)
            or price <= 0
            or not math.isfinite(age)
            or not -0.25 <= age <= max_age_seconds
        ):
            return None
        return price
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def paired_option_grid(
    contracts: list[ListedContract], spot: float, *, strikes_per_side: int, max_expiries: int = 2
) -> list[str]:
    """Select nearest actual strike and neighbors where both CE and PE are listed."""
    if not math.isfinite(spot) or spot <= 0 or strikes_per_side < 0 or max_expiries < 1:
        return []
    if len({(c.underlying, c.symbol.split(":")[0]) for c in contracts}) > 1:
        return []
    expiries: dict[date, dict[float, dict[str, ListedContract]]] = {}
    for contract in contracts:
        if contract.option_type in {"CE", "PE"} and contract.strike is not None:
            expiries.setdefault(contract.expiry, {}).setdefault(contract.strike, {})[
                contract.option_type
            ] = contract
    result = []
    used_expiries = 0
    for expiry, rows in sorted(expiries.items()):
        strikes = sorted(
            s
            for s, sides in rows.items()
            if {"CE", "PE"} <= sides.keys()
            and sides["CE"].lot_size == sides["PE"].lot_size
            and sides["CE"].tick_size == sides["PE"].tick_size
        )
        if not strikes:
            continue
        atm = min(range(len(strikes)), key=lambda i: (abs(strikes[i] - spot), strikes[i]))
        for strike in strikes[max(0, atm - strikes_per_side) : atm + strikes_per_side + 1]:
            result.extend((rows[strike]["CE"].symbol, rows[strike]["PE"].symbol))
        used_expiries += 1
        if used_expiries >= max_expiries:
            break
    return list(dict.fromkeys(result))


def get_subscription_option_grid(
    underlying: str,
    *,
    strikes_per_side: int = 8,
    max_expiries: int = 2,
    as_of: datetime | None = None,
    spot: float | None = None,
) -> list[str]:
    from market.indices import INDEX_INSTRUMENTS
    from market.quotes import get_quote

    clean = canonical_symbol(underlying)
    instrument = INDEX_INSTRUMENTS.get(
        clean, underlying if ":" in underlying else f"NSE:{clean}-EQ"
    )
    try:
        now = as_of or datetime.now(IST)
        from market.calendar import is_market_open

        effective_max_age = 120.0 if is_market_open("NSE", ref_dt=now) else 300.0

        if spot is None or spot <= 0:
            quotes = get_quote([instrument], ws_only=True)
            quote = (
                quotes.get(instrument)
                or quotes.get(clean)
                or quotes.get(underlying)
                or (list(quotes.values())[0] if quotes else None)
            )
            spot = fresh_underlying_price(
                quote, as_of=as_of or datetime.now(IST), max_age_seconds=effective_max_age
            )
            if spot is None:
                # Fallback to general get_quote if WebSocket cache has not populated yet
                quotes = get_quote([instrument], ws_only=False)
                quote = (
                    quotes.get(instrument)
                    or quotes.get(clean)
                    or quotes.get(underlying)
                    or (list(quotes.values())[0] if quotes else None)
                )
                spot = fresh_underlying_price(
                    quote, as_of=as_of or datetime.now(IST), max_age_seconds=effective_max_age
                )
        if spot is None:
            logger.info(
                "[ContractSelection] Option grid held for %s: no fresh live underlying quote", clean
            )
            return []
        contracts = get_listed_contracts(clean, as_of=as_of)
        return paired_option_grid(
            contracts, spot, strikes_per_side=strikes_per_side, max_expiries=max_expiries
        )
    except Exception as exc:
        logger.warning("[ContractSelection] Option grid unavailable for %s: %s", clean, exc)
        return []


# ── MCX commodity contracts ───────────────────────────────────────────────────
# MCX option symbols embed the expiry month (e.g. CRUDEOIL26NOV6500CE). Building
# that suffix from a calendar guess and an assumed spot produces plausible but
# unlisted contracts, which the broker rejects and which poison subscription and
# depth state. Commodity selection therefore reads the published master only and
# fails closed when the master or a fresh underlying quote is unavailable.

COMMODITY_EXCHANGE = "MCX"


def _master_expiry_date(row: Mapping[str, Any]) -> date | None:
    raw = row.get("expiryDate")
    if raw is None or isinstance(raw, bool) or not str(raw).strip():
        return None
    try:
        return datetime.fromtimestamp(float(raw), IST).date()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _positive_finite(raw: Any) -> float | None:
    if isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return value


def _commodity_option_from_row(
    row: Any,
    *,
    key: str | None,
    underlying: str,
    as_of: datetime,
) -> ListedContract | None:
    """Validate one MCX option row. Same-day expiry is excluded from new grids."""
    if not isinstance(row, dict):
        return None
    symbol = str(row.get("symTicker") or key or "").strip()
    if not symbol.startswith(f"{COMMODITY_EXCHANGE}:"):
        return None
    if key and row.get("symTicker") and row["symTicker"] != key:
        return None
    if canonical_symbol(str(row.get("underSym") or "")) != underlying:
        return None
    if row.get("tradeStatus") not in (1, "1"):
        return None
    option_type = str(row.get("optType") or "").upper()
    if option_type not in {"CE", "PE"} or not symbol.endswith(option_type):
        return None
    strike = _positive_finite(row.get("strikePrice"))
    lot = _positive_finite(row.get("minLotSize"))
    tick = _positive_finite(row.get("tickSize"))
    token = str(row.get("fyToken") or "").strip()
    expiry = _master_expiry_date(row)
    if strike is None or lot is None or tick is None or not token or token == "0":
        return None
    if expiry is None or expiry <= as_of.date():
        return None
    if not lot.is_integer():
        return None
    return ListedContract(
        symbol=symbol,
        underlying=underlying,
        expiry=expiry,
        option_type=option_type,
        strike=strike,
        lot_size=int(lot),
        tick_size=tick,
        token=token,
    )


def get_commodity_option_contracts(
    underlying: str, *, as_of: datetime | None = None, records: Mapping[str, Any] | None = None
) -> list[ListedContract]:
    """Listed, active MCX option contracts for one underlying (no fabrication)."""
    clean = canonical_symbol(underlying)
    now = as_of or datetime.now(IST)
    if now.tzinfo is None:
        raise ValueError("Commodity contract selection requires an aware timestamp")
    if records is None:
        from market.symbol_master import load_master

        try:
            records = load_master("MCX_COM", offline_fallback=False)
        except (RuntimeError, ValueError, OSError) as exc:
            logger.warning("[ContractSelection] MCX master unavailable for %s: %s", clean, exc)
            return []
    contracts = []
    for key, row in records.items():
        contract = _commodity_option_from_row(row, key=key, underlying=clean, as_of=now)
        if contract is not None:
            contracts.append(contract)
    return sorted(contracts, key=lambda c: (c.expiry, c.strike or 0.0, c.option_type, c.symbol))


def front_month_commodity_future(
    underlying: str, *, as_of: datetime | None = None, records: Mapping[str, Any] | None = None
) -> str | None:
    """Nearest unexpired MCX futures ticker for an underlying, from the master."""
    clean = canonical_symbol(underlying)
    now = as_of or datetime.now(IST)
    if now.tzinfo is None:
        raise ValueError("Commodity contract selection requires an aware timestamp")
    if records is None:
        from market.symbol_master import load_master

        try:
            records = load_master("MCX_COM", offline_fallback=False)
        except (RuntimeError, ValueError, OSError) as exc:
            logger.warning("[ContractSelection] MCX master unavailable for %s: %s", clean, exc)
            return None
    candidates: list[tuple[date, str]] = []
    for key, row in records.items():
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symTicker") or key or "").strip()
        if not symbol.startswith(f"{COMMODITY_EXCHANGE}:") or not symbol.endswith("FUT"):
            continue
        if canonical_symbol(str(row.get("underSym") or "")) != clean:
            continue
        if row.get("tradeStatus") not in (1, "1"):
            continue
        token = str(row.get("fyToken") or "").strip()
        expiry = _master_expiry_date(row)
        if not token or token == "0" or expiry is None or expiry < now.date():
            continue
        candidates.append((expiry, symbol))
    if not candidates:
        return None
    return min(candidates)[1]


def get_commodity_option_grid(
    underlying: str,
    *,
    strikes_per_side: int = 2,
    max_expiries: int = 1,
    as_of: datetime | None = None,
) -> list[str]:
    """Paired CE/PE strikes around a fresh front-month quote, master-listed only."""
    from market.quotes import get_quote

    clean = canonical_symbol(underlying)
    now = as_of or datetime.now(IST)
    if now.tzinfo is None or strikes_per_side < 0 or max_expiries < 1:
        return []
    try:
        from market.symbol_master import load_master

        records = load_master("MCX_COM", offline_fallback=False)
    except (RuntimeError, ValueError, OSError) as exc:
        logger.warning("[ContractSelection] MCX master unavailable for %s: %s", clean, exc)
        return []
    contracts = get_commodity_option_contracts(clean, as_of=now, records=records)
    if not contracts:
        return []
    future = front_month_commodity_future(clean, as_of=now, records=records)
    if future is None:
        logger.info("[ContractSelection] %s option grid held: no listed front-month future", clean)
        return []
    quote = get_quote([future]).get(future)
    spot = fresh_underlying_price(quote, as_of=now)
    if spot is None:
        logger.info(
            "[ContractSelection] %s option grid held: no fresh live front-month quote", clean
        )
        return []
    return paired_option_grid(
        contracts, spot, strikes_per_side=strikes_per_side, max_expiries=max_expiries
    )
