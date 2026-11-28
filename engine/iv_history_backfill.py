"""
engine/iv_history_backfill.py
─────────────────────────────
Authentic Historical Constant-Tenor IV Surface Reconstructor (Fyers Prime Active Contracts).

Solves Safety Contract #26 & #31 honestly when expired F&O contract endpoints are unavailable
(e.g., `fyers-apiv3 == 3.1.16` lacks `fno_historical_data`):
  1. Uses Fyers daily OHLC bars on currently listed active monthly CE/PE option contracts
     plus causal underlying daily spot closes (`<= session_date`).
  2. Recovers implied forward via Put-Call Parity when liquid CE & PE closes both exist
     at a near-ATM strike (`F = K + exp(r*T) * (C - P)`), falling back to carry-adjusted
     Black-76 forward otherwise, and inverts exact Black-76 option prices to annualized IV
     via deterministic bounded bisection.
  3. Rejects non-positive / sub-intrinsic / deep OTM-ITM / illiquid outliers (`< 3%` or `> 250%`),
     computes constant-30D variance via `interpolate_constant_tenor_variance()` and causal
     Yang-Zhang RV up to `session_date` only, and persists with
     `source_provenance="FYERS_ACTIVE_MONTHLY_BS_IV"` using `overwrite_existing=False` so live
     captured option-chain sessions are never overwritten.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
import logging
import math
import re
from typing import Any, Optional

import pandas as pd

from engine.iv_surface import (
    build_iv_surface_snapshot,
    compute_realized_volatility_yang_zhang,
    load_historical_30d_ivs,
    record_iv_observation,
)

logger = logging.getLogger("chanakya.iv_history_backfill")


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black76_option_price(
    forward: float,
    strike: float,
    dte_days: float,
    sigma: float,
    *,
    option_type: str = "CE",
    risk_free_rate: float = 0.065,
) -> float:
    """Compute exact unrounded Black-76 European option price from decimal sigma."""
    if forward <= 0 or strike <= 0 or dte_days <= 0 or sigma <= 0:
        is_call = str(option_type).upper().strip() in ("CE", "CALL", "C")
        intrinsic = max(0.0, forward - strike) if is_call else max(0.0, strike - forward)
        return intrinsic * math.exp(-risk_free_rate * max(0.0, dte_days) / 365.0)

    t_years = float(dte_days) / 365.0
    sqrt_t = math.sqrt(t_years)
    df = math.exp(-risk_free_rate * t_years)
    d1 = (math.log(forward / strike) + 0.5 * sigma * sigma * t_years) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    is_call = str(option_type).upper().strip() in ("CE", "CALL", "C")
    if is_call:
        return max(0.0, df * (forward * _norm_cdf(d1) - strike * _norm_cdf(d2)))
    return max(0.0, df * (strike * _norm_cdf(-d2) - forward * _norm_cdf(-d1)))


def implied_volatility_black76(
    market_price: float,
    forward: float,
    strike: float,
    dte_days: float,
    *,
    option_type: str = "CE",
    risk_free_rate: float = 0.065,
    min_sigma: float = 0.02,
    max_sigma: float = 3.00,
    tol: float = 1e-5,
) -> Optional[float]:
    """Invert exact Black-76 price to decimal annualized IV via bounded bisection.

    Returns `None` fail-closed if `market_price` violates discounted intrinsic arbitrage bounds
    or fails to bracket within `[min_sigma, max_sigma]`.
    """
    if (
        not math.isfinite(market_price)
        or not math.isfinite(forward)
        or not math.isfinite(strike)
        or not math.isfinite(dte_days)
        or market_price <= 0
        or forward <= 0
        or strike <= 0
        or dte_days < 1
    ):
        return None

    t_years = float(dte_days) / 365.0
    df = math.exp(-risk_free_rate * t_years)
    is_call = str(option_type).upper().strip() in ("CE", "CALL", "C")
    disc_intrinsic = df * (max(0.0, forward - strike) if is_call else max(0.0, strike - forward))
    if market_price <= disc_intrinsic + 0.02:
        return None

    low = float(min_sigma)
    high = float(max_sigma)
    p_low = black76_option_price(
        forward, strike, dte_days, low, option_type=option_type, risk_free_rate=risk_free_rate
    )
    p_high = black76_option_price(
        forward, strike, dte_days, high, option_type=option_type, risk_free_rate=risk_free_rate
    )
    if market_price < p_low or market_price > p_high:
        return None

    for _ in range(60):
        mid = 0.5 * (low + high)
        p_mid = black76_option_price(
            forward, strike, dte_days, mid, option_type=option_type, risk_free_rate=risk_free_rate
        )
        if abs(p_mid - market_price) < tol or (high - low) < 1e-6:
            return round(mid, 6)
        if p_mid < market_price:
            low = mid
        else:
            high = mid
    return round(0.5 * (low + high), 6)


def implied_volatility_bs(
    market_price: float,
    spot: float,
    strike: float,
    dte_days: float,
    *,
    option_type: str = "CE",
    risk_free_rate: float = 0.065,
    dividend_yield: float = 0.012,
) -> Optional[float]:
    """Invert spot-referenced European Black-Scholes price to decimal annualized IV."""
    if spot <= 0 or dte_days < 1:
        return None
    forward = spot * math.exp((risk_free_rate - dividend_yield) * (float(dte_days) / 365.0))
    return implied_volatility_black76(
        market_price,
        forward,
        strike,
        dte_days,
        option_type=option_type,
        risk_free_rate=risk_free_rate,
    )


def _round_strike_preference(strike: float, spot_anchor: float) -> tuple[int, float]:
    """Prefer exchange anchor round strikes (500/1000 for indices, 50/100 for stocks) that trade earlier."""
    if spot_anchor >= 30000:
        step_major, step_minor = 1000, 500
    elif spot_anchor >= 10000:
        step_major, step_minor = 500, 100
    elif spot_anchor >= 2000:
        step_major, step_minor = 100, 50
    elif spot_anchor >= 500:
        step_major, step_minor = 50, 20
    else:
        step_major, step_minor = 20, 10

    k_int = int(round(strike))
    if abs(strike - k_int) < 1e-4:
        if k_int % step_major == 0:
            tier = 0
        elif k_int % step_minor == 0:
            tier = 1
        else:
            tier = 2
    else:
        tier = 3
    return (tier, abs(strike - spot_anchor))


def select_historical_monthly_contracts(
    underlying: str,
    spot_series: pd.Series,
    *,
    listed_contracts: Optional[list[Any]] = None,
    max_expiries: int = 2,
    strikes_per_expiry: int = 4,
    as_of_date: Optional[date] = None,
) -> list[Any]:
    """Choose active monthly CE/PE pairs spanning the recent spot range with round-strike liquidity."""
    from engine.alert_identity import canonical_alert_symbol
    from market.contract_selection import get_listed_contracts

    clean = canonical_alert_symbol(underlying).upper()
    contracts = (
        listed_contracts
        if listed_contracts is not None
        else get_listed_contracts(clean, as_of=None)
    )
    ref_day = as_of_date or date.today()
    opt_contracts = [
        c
        for c in contracts
        if getattr(c, "option_type", "") in ("CE", "PE")
        and getattr(c, "strike", None) is not None
        and float(c.strike) > 0
        and getattr(c, "expiry", None) is not None
        and c.expiry > ref_day
    ]
    if not opt_contracts:
        return []

    by_exp: dict[date, list[Any]] = defaultdict(list)
    for c in opt_contracts:
        by_exp[c.expiry].append(c)

    # Prefer true monthly expiries (final expiry of its calendar month: next week crosses month end)
    sorted_exps = sorted(by_exp.keys())
    monthly_exps = [e for e in sorted_exps if (e + timedelta(days=7)).month != e.month]
    chosen_exps = (monthly_exps if len(monthly_exps) >= max_expiries else sorted_exps)[
        :max_expiries
    ]

    clean_spot = pd.to_numeric(spot_series, errors="coerce").dropna()
    if clean_spot.empty:
        return []
    spot_last = float(clean_spot.iloc[-1])
    spot_med = float(clean_spot.median())
    spot_q25 = float(clean_spot.quantile(0.25))
    spot_q75 = float(clean_spot.quantile(0.75))
    anchors = [spot_last, spot_med, spot_q75, spot_q25]

    selected: list[Any] = []
    for exp in chosen_exps:
        exp_rows = by_exp[exp]
        by_strike: dict[float, dict[str, Any]] = defaultdict(dict)
        for c in exp_rows:
            by_strike[float(c.strike)][c.option_type] = c

        paired_strikes = [k for k, pair in by_strike.items() if "CE" in pair and "PE" in pair]
        if not paired_strikes:
            continue

        chosen_strikes: list[float] = []
        seen: set[float] = set()
        for anc in anchors:
            ranked = sorted(
                (k for k in paired_strikes if k not in seen),
                key=lambda k, a=anc: _round_strike_preference(k, a),
            )
            if ranked:
                k_pick = ranked[0]
                chosen_strikes.append(k_pick)
                seen.add(k_pick)
            if len(chosen_strikes) >= strikes_per_expiry:
                break

        if len(chosen_strikes) < strikes_per_expiry:
            rem = sorted(
                (k for k in paired_strikes if k not in seen),
                key=lambda k: _round_strike_preference(k, spot_med),
            )
            chosen_strikes.extend(rem[: strikes_per_expiry - len(chosen_strikes)])

        for k_pick in chosen_strikes:
            pair = by_strike[k_pick]
            selected.append(pair["CE"])
            selected.append(pair["PE"])

    return selected


def _bars_to_date_close_map(
    bars: list[dict[str, Any]],
) -> dict[date, tuple[float, float, Optional[float]]]:
    """Map calendar session_date -> (close_price, volume, provider_iv) from Fyers candle dicts."""
    out: dict[date, tuple[float, float, Optional[float]]] = {}
    for row in bars or []:
        dt_val = row.get("date")
        if dt_val is None:
            continue
        if isinstance(dt_val, datetime):
            d = dt_val.date()
        elif isinstance(dt_val, date):
            d = dt_val
        else:
            try:
                d = pd.Timestamp(dt_val).date()
            except Exception:
                continue
        close_px = float(row.get("close") or 0.0)
        vol = float(row.get("volume") or 0.0)
        raw_iv = row.get("implied_volatility")
        prov_iv: Optional[float] = None
        if raw_iv is not None:
            try:
                iv_f = float(raw_iv)
                if math.isfinite(iv_f) and 3.0 <= iv_f <= 250.0:
                    prov_iv = round(iv_f, 4)
            except (TypeError, ValueError):
                prov_iv = None
        if close_px > 0:
            out[d] = (close_px, max(0.0, vol), prov_iv)
    return out


def _solve_expiry_atm_iv_for_date(
    target_date: date,
    spot_close: float,
    expiry: date,
    strike_bars: dict[float, dict[str, dict[date, tuple[float, float, Optional[float]]]]],
    *,
    risk_free_rate: float = 0.065,
    dividend_yield: float = 0.012,
) -> Optional[float]:
    """Solve near-ATM implied volatility (in percent) for one `(target_date, expiry)` slice."""
    dte = (expiry - target_date).days
    if dte < 2 or spot_close <= 0:
        return None

    t_years = float(dte) / 365.0
    exp_rt = math.exp(risk_free_rate * t_years)
    # Sort available strikes closest to spot within ±15% moneyness band
    candidate_strikes = sorted(
        (k for k in strike_bars if abs(k - spot_close) / spot_close <= 0.15),
        key=lambda k: abs(k - spot_close),
    )
    if not candidate_strikes:
        return None

    # Infer implied forward from best liquid CE+PE put-call parity strike when sane
    implied_forward: Optional[float] = None
    for k in candidate_strikes:
        sides = strike_bars[k]
        ce_entry = sides.get("CE", {}).get(target_date)
        pe_entry = sides.get("PE", {}).get(target_date)
        if ce_entry and pe_entry and ce_entry[0] > 0 and pe_entry[0] > 0:
            f_cand = k + exp_rt * (ce_entry[0] - pe_entry[0])
            if 0.90 * spot_close <= f_cand <= 1.12 * spot_close:
                implied_forward = f_cand
                break

    if implied_forward is None:
        implied_forward = spot_close * math.exp((risk_free_rate - dividend_yield) * t_years)

    solved_vols: list[float] = []
    for k in candidate_strikes[:2]:
        sides = strike_bars[k]
        for opt_type in ("CE", "PE"):
            entry = sides.get(opt_type, {}).get(target_date)
            if not entry:
                continue
            close_px, vol, prov_iv = entry
            if close_px <= 0:
                continue
            # Prefer traded contracts unless spot close itself has valid non-zero print
            if vol <= 0 and prov_iv is None and abs(k - spot_close) / spot_close > 0.06:
                continue
            sigma_dec = implied_volatility_black76(
                close_px,
                implied_forward,
                k,
                dte,
                option_type=opt_type,
                risk_free_rate=risk_free_rate,
            )
            if sigma_dec is not None and 0.03 <= sigma_dec <= 2.50:
                solved_vols.append(sigma_dec * 100.0)
            elif prov_iv is not None and abs(k - spot_close) / spot_close <= 0.08:
                solved_vols.append(prov_iv)
        if solved_vols:
            break

    if not solved_vols:
        return None
    return round(sum(solved_vols) / len(solved_vols), 4)


def _parse_expired_option_contract_symbol(
    symbol: str,
    underlying: str,
    expiry: date,
) -> Optional[tuple[float, str]]:
    """Parse Fyers expired monthly option ticker (`EXCH:SYMYYMMMSTRIKECE|PE`) safely."""
    exp_tag = expiry.strftime("%y%b").upper()
    pat = re.compile(rf"^[^:]+:{re.escape(underlying.upper())}{exp_tag}(\d+(?:\.\d+)?)(CE|PE)$")
    m = pat.match(str(symbol or "").strip().upper())
    if not m:
        return None
    return float(m.group(1)), m.group(2)


def _pick_30d_bracket_pair(
    sess_date: date,
    solved_pairs: list[tuple[date, float]],
) -> tuple[tuple[date, float], Optional[tuple[date, float]]]:
    """Pick the tightest near/next expiry pair straddling 30D (or shortest two valid expiries)."""
    if len(solved_pairs) == 1:
        return solved_pairs[0], None
    le30 = [p for p in solved_pairs if (p[0] - sess_date).days <= 30]
    gt30 = [p for p in solved_pairs if (p[0] - sess_date).days > 30]
    if le30 and gt30:
        return le30[-1], gt30[0]
    return solved_pairs[0], solved_pairs[1]


def _resolve_fyers_underlying(clean: str) -> tuple[str, str]:
    """Resolve canonical Fyers spot/index underlying symbol and exchange prefix."""
    from brokers.fyers import _to_fyers_symbol

    ex = "BSE" if clean in ("SENSEX", "BANKEX") else "NSE"
    fyers_sym = _to_fyers_symbol(
        clean
        if clean in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX")
        else f"{ex}:{clean}"
    )
    ex_prefix = fyers_sym.split(":", 1)[0] if ":" in fyers_sym else ex
    return fyers_sym, ex_prefix


def _fetch_expired_monthly_iv_grid(
    clean: str,
    broker: Any,
    spot_work: pd.DataFrame,
    start_d: date,
    end_d: date,
    *,
    max_expiries: int = 3,
    strikes_per_expiry: int = 3,
) -> tuple[
    dict[date, dict[float, dict[str, dict[date, tuple[float, float, Optional[float]]]]]], int
]:
    """Fetch expired monthly F&O bars + Greeks via Fyers Prime (`fyers-apiv3 >= 3.2`)."""
    out: dict[date, dict[float, dict[str, dict[date, tuple[float, float, Optional[float]]]]]] = (
        defaultdict(lambda: defaultdict(dict))
    )
    if not hasattr(broker, "get_expired_fno_history"):
        return out, 0

    fyers = getattr(broker, "_get_fyers", lambda: None)()
    if (
        fyers is None
        or not hasattr(fyers, "expiry_dates")
        or not hasattr(fyers, "history_underlying_symbols")
        or not hasattr(fyers, "fno_historical_data")
    ):
        return out, 0

    try:
        fyers_und, ex_spot = _resolve_fyers_underlying(clean)
    except Exception:
        return out, 0

    fno_exchange = "BFO" if (clean in ("SENSEX", "BANKEX") or ex_spot == "BSE") else "NFO"
    yesterday_d = date.today() - timedelta(days=1)
    safe_range_to = min(end_d - timedelta(days=1), yesterday_d)
    if safe_range_to < start_d:
        return out, 0
    try:
        resp_exp = fyers.expiry_dates(
            {
                "symbol": fyers_und,
                "date_format": 1,
                "range_from": start_d.strftime("%Y-%m-%d"),
                "range_to": safe_range_to.strftime("%Y-%m-%d"),
            }
        )
        data_blk = (resp_exp or {}).get("data") or {}
        raw_opt_exps = (
            (data_blk.get("expiry_dates") or {}).get("options") or data_blk.get("expiry") or []
        )
    except Exception as exc:
        logger.debug(f"[IVBackfill] expiry_dates failed for {clean}: {exc}")
        return out, 0

    parsed_exps: set[date] = set()
    for raw_e in raw_opt_exps or []:
        try:
            d_e = date.fromisoformat(str(raw_e)[:10])
            if start_d <= d_e < end_d and (d_e + timedelta(days=7)).month != d_e.month:
                parsed_exps.add(d_e)
        except Exception:
            continue

    expired_monthlies = sorted(parsed_exps)[-max_expiries:]
    if not expired_monthlies:
        return out, 0

    fetched = 0
    for exp_d in expired_monthlies:
        exp_start = max(start_d, exp_d - timedelta(days=60))
        sub_spot = spot_work[(spot_work.index.date >= exp_start) & (spot_work.index.date <= exp_d)]
        if sub_spot.empty:
            continue
        spot_med = float(sub_spot["close"].median())
        spot_last = float(sub_spot["close"].iloc[-1])

        try:
            sym_resp = fyers.history_underlying_symbols(
                {"symbol": fyers_und, "expiry_date": exp_d.isoformat()}
            )
            opt_syms = (sym_resp or {}).get("data", {}).get("contracts", {}).get("options", [])
        except Exception as exc:
            logger.debug(f"[IVBackfill] history_underlying_symbols failed {clean} {exp_d}: {exc}")
            continue

        by_strike: dict[float, dict[str, str]] = defaultdict(dict)
        for s_item in opt_syms or []:
            parsed = _parse_expired_option_contract_symbol(str(s_item), clean, exp_d)
            if parsed:
                k_val, opt_type = parsed
                by_strike[k_val][opt_type] = str(s_item)

        paired = [k for k, pair in by_strike.items() if "CE" in pair and "PE" in pair]
        if not paired:
            continue

        picked_strikes: list[float] = []
        seen_k: set[float] = set()
        for anc in (spot_last, spot_med, 0.5 * (spot_last + spot_med)):
            cands = sorted(
                (k for k in paired if k not in seen_k),
                key=lambda k, a=anc: _round_strike_preference(k, a),
            )
            if cands:
                picked_strikes.append(cands[0])
                seen_k.add(cands[0])
            if len(picked_strikes) >= strikes_per_expiry:
                break

        for k_pick in picked_strikes:
            for opt_type in ("CE", "PE"):
                contract_sym = by_strike[k_pick][opt_type]
                try:
                    bars = broker.get_expired_fno_history(
                        contract_sym,
                        exchange=fno_exchange,
                        interval="D",
                        from_date=exp_start,
                        to_date=exp_d,
                        include_oi=True,
                        include_greeks=True,
                    )
                    date_map = _bars_to_date_close_map(bars)
                    if date_map:
                        out[exp_d][float(k_pick)][opt_type] = date_map
                        fetched += 1
                except Exception as exc:
                    logger.debug(
                        f"[IVBackfill] Expired F&O history fetch failed for {contract_sym}: {exc}"
                    )

    return out, fetched


def _fetch_spot_daily_bars(symbol: str, broker: Any, lookback_days: int) -> Optional[pd.DataFrame]:
    """Load daily spot OHLCV from historical_warehouse, falling back to live broker if needed."""
    from engine.alert_identity import canonical_alert_symbol
    from engine.historical_warehouse import historical_warehouse

    clean = canonical_alert_symbol(symbol).upper()
    df = historical_warehouse.load_bars(clean, interval="day")
    if df is not None and not df.empty and len(df) >= max(30, lookback_days // 2):
        return df

    if broker is None:
        return df

    try:
        fyers_sym, ex = _resolve_fyers_underlying(clean)
        end_d = date.today()
        start_d = end_d - timedelta(days=max(120, lookback_days + 45))
        raw = broker.get_historical_data(fyers_sym, ex, "day", from_date=start_d, to_date=end_d)
        if raw:
            hdf = pd.DataFrame(raw)
            hdf["date"] = pd.to_datetime(hdf["date"])
            hdf = hdf.set_index("date").sort_index()
            if hdf.index.tzinfo is not None:
                hdf.index = hdf.index.tz_localize(None)
            return hdf
    except Exception as exc:
        logger.debug(f"[IVBackfill] Spot daily fetch fallback failed for {clean}: {exc}")
    return df


def backfill_symbol_iv_history(
    symbol: str,
    broker: Any = None,
    *,
    lookback_days: int = 90,
    target_min_sessions: int = 25,
    overwrite_existing: bool = False,
    spot_df: Optional[pd.DataFrame] = None,
    listed_contracts: Optional[list[Any]] = None,
    strikes_per_expiry: int = 3,
    force: bool = False,
) -> dict[str, Any]:
    """Reconstruct historical constant-30D IV observations from active monthly Fyers option bars.

    Guarantees Safety Contract #26/#31 compliance:
      - Zero synthetic IV or RV-as-IV substitution.
      - Strict `as_of = session_date` causality on both spot RV window and option DTE.
      - Live captured rows (`overwrite_existing=False`) are never overwritten.
    """
    from config.constants import IST
    from engine.alert_identity import canonical_alert_symbol

    clean = canonical_alert_symbol(symbol).upper()
    existing_count = len(load_historical_30d_ivs(clean, limit=252))
    if not force and existing_count >= target_min_sessions:
        return {
            "symbol": clean,
            "status": "SKIPPED_SUFFICIENT_DEPTH",
            "existing_sessions": existing_count,
            "persisted_sessions": 0,
            "total_sessions": existing_count,
        }

    if broker is None:
        from brokers.session import get_data_broker

        broker = get_data_broker()

    if broker is None or not getattr(broker, "has_token", lambda: True)():
        return {
            "symbol": clean,
            "status": "UNAVAILABLE_NO_BROKER",
            "existing_sessions": existing_count,
            "persisted_sessions": 0,
            "total_sessions": existing_count,
        }

    df_spot = (
        spot_df if spot_df is not None else _fetch_spot_daily_bars(clean, broker, lookback_days)
    )
    if df_spot is None or df_spot.empty:
        return {
            "symbol": clean,
            "status": "UNAVAILABLE_NO_SPOT_BARS",
            "existing_sessions": existing_count,
            "persisted_sessions": 0,
            "total_sessions": existing_count,
        }

    spot_work = df_spot.copy()
    if spot_work.index.tzinfo is not None:
        spot_work.index = spot_work.index.tz_localize(None)
    spot_work = spot_work.sort_index()
    # Deduplicate same calendar session date (00:00 vs 05:30 IST rows from mixed writers)
    spot_work = spot_work.assign(_sess_date=spot_work.index.date).drop_duplicates(
        subset=["_sess_date"], keep="last"
    )
    spot_work = spot_work.drop(columns=["_sess_date"])

    end_d = date.today()
    start_d = end_d - timedelta(days=max(30, int(lookback_days)))
    window_df = spot_work[spot_work.index.date >= start_d]
    if window_df.empty:
        window_df = spot_work.tail(60)

    exchange_str = "BSE" if clean in ("SENSEX", "BANKEX") else "NSE"
    # 1. Primary path: expired monthly contracts via Fyers Prime fno_historical_data (OI + Greeks)
    grid, expired_fetched = _fetch_expired_monthly_iv_grid(
        clean,
        broker,
        spot_work,
        start_d,
        end_d,
        max_expiries=3,
        strikes_per_expiry=max(2, min(4, strikes_per_expiry)),
    )

    # 2. Active monthly contracts via Fyers historical_data (covers current forward tenors)
    selected_contracts = select_historical_monthly_contracts(
        clean,
        window_df["close"],
        listed_contracts=listed_contracts,
        max_expiries=2,
        strikes_per_expiry=strikes_per_expiry,
        as_of_date=end_d,
    )
    active_fetched = 0
    for c in selected_contracts:
        try:
            bars = broker.get_historical_data(
                c.symbol,
                exchange_str,
                "day",
                from_date=start_d,
                to_date=end_d,
            )
            date_map = _bars_to_date_close_map(bars)
            if date_map:
                grid[c.expiry][float(c.strike)][c.option_type] = date_map
                active_fetched += 1
        except Exception as exc:
            logger.debug(f"[IVBackfill] Bar fetch failed for {c.symbol}: {exc}")

    fetched_contracts = expired_fetched + active_fetched
    if not grid:
        return {
            "symbol": clean,
            "status": (
                "UNAVAILABLE_NO_ACTIVE_CONTRACTS"
                if not selected_contracts
                else "UNAVAILABLE_NO_OPTION_BARS"
            ),
            "existing_sessions": existing_count,
            "persisted_sessions": 0,
            "total_sessions": existing_count,
            "fetched_contracts": fetched_contracts,
        }

    is_index = clean in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX")
    div_yield = 0.012 if is_index else 0.008
    sorted_exps = sorted(grid.keys())
    provenance_tag = (
        "FYERS_EXPIRED_PLUS_ACTIVE_BS_IV" if expired_fetched > 0 else "FYERS_ACTIVE_MONTHLY_BS_IV"
    )

    # Evaluate chronologically per daily spot session (live days protected by overwrite_existing=False)
    prior_ivs: list[float] = []
    persisted = 0
    solved_days = 0
    for ts, row in window_df.iterrows():
        sess_date = ts.date() if hasattr(ts, "date") else pd.Timestamp(ts).date()
        spot_close = float(row.get("close") or 0.0)
        if spot_close <= 0:
            continue

        valid_exps = [e for e in sorted_exps if (e - sess_date).days >= 2]
        if not valid_exps:
            continue

        solved_pairs: list[tuple[date, float]] = []
        for exp_cand in valid_exps:
            iv_cand = _solve_expiry_atm_iv_for_date(
                sess_date,
                spot_close,
                exp_cand,
                grid[exp_cand],
                dividend_yield=div_yield,
            )
            if iv_cand is not None:
                solved_pairs.append((exp_cand, iv_cand))

        if not solved_pairs:
            continue

        (exp1, iv1), second_pair = _pick_30d_bracket_pair(sess_date, solved_pairs)
        exp2, iv2 = second_pair if second_pair is not None else (None, None)

        # Strictly causal realized volatility using ONLY spot bars <= sess_date
        causal_spot = spot_work[spot_work.index.date <= sess_date]
        rv_20 = compute_realized_volatility_yang_zhang(causal_spot, window=20, in_percent=True)

        snap_dt = datetime.combine(sess_date, datetime.min.time(), tzinfo=IST).replace(
            hour=15, minute=30
        )
        snap = build_iv_surface_snapshot(
            symbol=clean,
            near_atm_iv=iv1,
            near_dte=(exp1 - sess_date).days,
            next_atm_iv=iv2,
            next_dte=(exp2 - sess_date).days if (exp2 is not None and iv2 is not None) else None,
            historical_30d_ivs=prior_ivs,
            now_dt=snap_dt,
            near_expiry=exp1.isoformat(),
            next_expiry=exp2.isoformat() if (exp2 is not None and iv2 is not None) else None,
            realized_vol_20d=rv_20,
            source_provenance=provenance_tag,
        )
        if snap.status == "AVAILABLE" and snap.atm_iv_30d is not None:
            solved_days += 1
            prior_ivs.append(float(snap.atm_iv_30d))
            if record_iv_observation(
                snap,
                session_date=sess_date.isoformat(),
                overwrite_existing=overwrite_existing,
            ):
                persisted += 1

    total_after = len(load_historical_30d_ivs(clean, limit=252))
    return {
        "symbol": clean,
        "status": "COMPLETED" if solved_days > 0 else "INSUFFICIENT_LIQUID_STRIKES",
        "provenance": provenance_tag,
        "expired_contracts": expired_fetched,
        "active_contracts": active_fetched,
        "fetched_contracts": fetched_contracts,
        "solved_days": solved_days,
        "existing_sessions": existing_count,
        "persisted_sessions": persisted,
        "total_sessions": total_after,
    }


def backfill_priority_iv_universe(
    symbols: Optional[list[str]] = None,
    broker: Any = None,
    *,
    lookback_days: int = 90,
    target_min_sessions: int = 25,
) -> dict[str, Any]:
    """Bounded backfill across core index and top stock F&O symbols."""
    targets = symbols or [
        "NIFTY",
        "BANKNIFTY",
        "SENSEX",
        "RELIANCE",
        "HDFCBANK",
        "ICICIBANK",
    ]
    results: dict[str, Any] = {}
    total_persisted = 0
    for sym in targets:
        res = backfill_symbol_iv_history(
            sym,
            broker=broker,
            lookback_days=lookback_days,
            target_min_sessions=target_min_sessions,
            overwrite_existing=False,
        )
        results[sym] = res
        total_persisted += int(res.get("persisted_sessions") or 0)
    return {
        "status": "COMPLETED",
        "provenance": "FYERS_ACTIVE_MONTHLY_BS_IV",
        "total_persisted": total_persisted,
        "symbols": results,
    }
