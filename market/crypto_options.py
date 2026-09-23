"""
market/crypto_options.py
────────────────────────
24x7 Crypto Options Chain & Volatility Surface Engine via Deribit.

Deribit is the global institutional benchmark for cryptocurrency options
(holding >85% of global BTC & ETH options market share).

Zero API key or authentication required (uses Deribit's open public REST API).

Computes:
  1. Real-time Options Chain across all strikes & expiries
  2. Max Pain Strike (settlement magnet for option sellers)
  3. Put-Call Ratio (PCR) by Open Interest and 24h Volume
  4. At-the-Money Implied Volatility (ATM IV) & Skew
  5. Dealer Gamma Exposure (GEX) inflection zones

Usage:
    from market.crypto_options import get_crypto_options_summary

    summary = get_crypto_options_summary("BTC")
    print(f"Max Pain: ${summary['max_pain']:,} | PCR: {summary['pcr_oi']:.2f}")
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from market.http_pool import get_shared_client

logger = logging.getLogger(__name__)

DERIBIT_BOOK_SUMMARY_URL = "https://www.deribit.com/api/v2/public/get_book_summary_by_currency"

_OPTIONS_CACHE_LOCK = threading.Lock()
_OPTIONS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_OPTIONS_CACHE_TTL = 60.0  # 60s cache


@dataclass
class DeribitOptionContract:
    instrument_name: str
    currency: str
    expiry: str
    strike: float
    option_type: str  # "CE" | "PE"
    mark_price_crypto: float
    mark_price_usd: float
    underlying_price: float
    iv: float
    open_interest: float
    volume_24h: float
    bid_usd: Optional[float] = None
    ask_usd: Optional[float] = None


def parse_deribit_instrument(name: str) -> Optional[tuple[str, str, float, str]]:
    """
    Parse 'BTC-26SEP26-80000-C' -> ('BTC', '26SEP26', 80000.0, 'CE').
    """
    parts = name.strip().split("-")
    if len(parts) != 4:
        return None
    curr, expiry, strike_str, opt_char = parts
    try:
        strike = float(strike_str)
        opt_type = "CE" if opt_char.upper().startswith("C") else "PE"
        return curr.upper(), expiry.upper(), strike, opt_type
    except ValueError:
        return None


def calculate_max_pain(contracts: list[DeribitOptionContract]) -> float:
    """
    Calculate the Max Pain price where option writers face the least payout.
    Pain(S) = sum(max(0, S - strike_c) * OI_c) + sum(max(0, strike_p - S) * OI_p)
    """
    if not contracts:
        return 0.0

    strikes = sorted(list({c.strike for c in contracts if c.strike > 0}))
    if not strikes:
        return 0.0

    min_pain = float("inf")
    best_strike = strikes[0]

    for s in strikes:
        total_pain = 0.0
        for c in contracts:
            if c.option_type == "CE":
                if s > c.strike:
                    total_pain += (s - c.strike) * c.open_interest
            else:  # PE
                if s < c.strike:
                    total_pain += (c.strike - s) * c.open_interest

        if total_pain < min_pain:
            min_pain = total_pain
            best_strike = s

    return best_strike


def calculate_deribit_gex(
    contracts: list[DeribitOptionContract],
    underlying_spot: float,
) -> dict[str, Any]:
    """
    Calculate Dealer Gamma Exposure (GEX) across Deribit options surface.
    GEX estimates the dollar change in dealer hedging needs per 1% spot move.

    Formula per contract:
      d1 = [ln(S/K) + (r + 0.5 * sigma^2) * T] / [sigma * sqrt(T)]
      Gamma = [exp(-0.5 * d1^2) / sqrt(2*pi)] / [S * sigma * sqrt(T)]
      Dollar Gamma = Gamma * S^2 * 0.01 * OI

    Net GEX = Call GEX - Put GEX
      - Positive Gamma (> 0): Dealers mean-revert / pin toward Max Pain.
      - Negative Gamma (< 0): Dealers trend-follow / amplify volatility and breakouts.
    """
    import math

    if underlying_spot <= 0 or not contracts:
        return {
            "net_gex_usd": 0.0,
            "call_gex_usd": 0.0,
            "put_gex_usd": 0.0,
            "gamma_regime": "NEUTRAL",
            "gex_flip_strike": 0.0,
        }

    now = datetime.now(timezone.utc)
    strike_gex: dict[float, float] = defaultdict(float)
    total_call_gex = 0.0
    total_put_gex = 0.0

    for c in contracts:
        if c.strike <= 0 or c.iv <= 0 or c.open_interest <= 0:
            continue
        try:
            exp_dt = datetime.strptime(c.expiry.upper(), "%d%b%y").replace(tzinfo=timezone.utc)
            t_days = max(0.25, (exp_dt - now).total_seconds() / 86400.0)
            t_years = t_days / 365.25
        except Exception:
            t_years = 7.0 / 365.25

        sigma = max(0.10, min(3.0, c.iv / 100.0))
        r = 0.04

        try:
            d1 = (math.log(underlying_spot / c.strike) + (r + 0.5 * sigma * sigma) * t_years) / (
                sigma * math.sqrt(t_years)
            )
            pdf_d1 = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
            gamma = pdf_d1 / (underlying_spot * sigma * math.sqrt(t_years))
        except (ValueError, ZeroDivisionError, OverflowError):
            continue

        dollar_gamma = gamma * (underlying_spot**2) * 0.01 * c.open_interest

        if c.option_type == "CE":
            total_call_gex += dollar_gamma
            strike_gex[c.strike] += dollar_gamma
        else:
            total_put_gex += dollar_gamma
            strike_gex[c.strike] -= dollar_gamma

    net_gex = total_call_gex - total_put_gex
    regime = "POSITIVE_GAMMA_PIN" if net_gex >= 0 else "NEGATIVE_GAMMA_ACCELERATION"

    sorted_strikes = sorted(strike_gex.keys())
    cum_gex = 0.0
    flip_strike = underlying_spot
    for s in sorted_strikes:
        cum_gex += strike_gex[s]
        if cum_gex >= 0:
            flip_strike = s
            break

    return {
        "net_gex_usd": round(net_gex, 2),
        "call_gex_usd": round(total_call_gex, 2),
        "put_gex_usd": round(total_put_gex, 2),
        "gamma_regime": regime,
        "gex_flip_strike": round(flip_strike, 2),
    }


def get_crypto_options_summary(
    currency: str = "BTC", force_refresh: bool = False
) -> dict[str, Any]:
    """
    Fetch and compute institutional 24x7 options metrics for BTC or ETH.
    """
    curr = currency.upper().replace("USDT", "").replace("USD", "").strip()
    if curr not in ("BTC", "ETH", "SOL"):
        curr = "BTC"

    now_ts = time.time()
    with _OPTIONS_CACHE_LOCK:
        if not force_refresh and curr in _OPTIONS_CACHE:
            cached_ts, cached_data = _OPTIONS_CACHE[curr]
            if now_ts - cached_ts < _OPTIONS_CACHE_TTL:
                return cached_data

    params = {"currency": curr, "kind": "option"}
    try:
        client = get_shared_client()
        resp = client.get(DERIBIT_BOOK_SUMMARY_URL, params=params, timeout=8.0)
        if resp.status_code != 200:
            logger.warning(f"Deribit options API returned {resp.status_code}: {resp.text[:200]}")
            return {"status": "UNAVAILABLE", "currency": curr, "error": f"HTTP {resp.status_code}"}
        raw_data = resp.json().get("result", [])
    except Exception as e:
        logger.error(f"Failed to fetch Deribit options for {curr}: {e}")
        return {"status": "UNAVAILABLE", "currency": curr, "error": str(e)}

    if not raw_data:
        return {"status": "NO_DATA", "currency": curr, "contracts_count": 0}

    contracts: list[DeribitOptionContract] = []
    underlying_spot = 0.0

    for item in raw_data:
        inst_name = item.get("instrument_name", "")
        parsed = parse_deribit_instrument(inst_name)
        if not parsed:
            continue
        c_curr, expiry, strike, opt_type = parsed

        spot = float(item.get("underlying_price", 0.0) or 0.0)
        if spot > 0:
            underlying_spot = spot

        mark_crypto = float(item.get("mark_price", 0.0) or 0.0)
        mark_usd = mark_crypto * spot if spot > 0 else 0.0
        iv = float(item.get("mark_iv", 0.0) or 0.0)
        oi = float(item.get("open_interest", 0.0) or 0.0)
        vol = float(item.get("volume", 0.0) or 0.0)

        bid_usd = float(item.get("bid_price", 0.0) or 0.0) * spot if item.get("bid_price") else None
        ask_usd = float(item.get("ask_price", 0.0) or 0.0) * spot if item.get("ask_price") else None

        contracts.append(
            DeribitOptionContract(
                instrument_name=inst_name,
                currency=c_curr,
                expiry=expiry,
                strike=strike,
                option_type=opt_type,
                mark_price_crypto=mark_crypto,
                mark_price_usd=round(mark_usd, 2),
                underlying_price=spot,
                iv=round(iv, 2),
                open_interest=round(oi, 2),
                volume_24h=round(vol, 2),
                bid_usd=round(bid_usd, 2) if bid_usd else None,
                ask_usd=round(ask_usd, 2) if ask_usd else None,
            )
        )

    if not contracts:
        return {"status": "NO_VALID_CONTRACTS", "currency": curr}

    # Group by expiry to find nearest active expiries
    by_expiry: dict[str, list[DeribitOptionContract]] = defaultdict(list)
    for c in contracts:
        by_expiry[c.expiry].append(c)

    # Sort expiries by total OI
    sorted_expiries = sorted(
        by_expiry.keys(), key=lambda exp: sum(c.open_interest for c in by_expiry[exp]), reverse=True
    )
    nearest_expiry = sorted_expiries[0] if sorted_expiries else ""
    nearest_contracts = by_expiry.get(nearest_expiry, contracts)

    # 1. Total Metrics
    call_oi = sum(c.open_interest for c in contracts if c.option_type == "CE")
    put_oi = sum(c.open_interest for c in contracts if c.option_type == "PE")
    call_vol = sum(c.volume_24h for c in contracts if c.option_type == "CE")
    put_vol = sum(c.volume_24h for c in contracts if c.option_type == "PE")

    pcr_oi = round(put_oi / call_oi, 3) if call_oi > 0 else 1.0
    pcr_vol = round(put_vol / call_vol, 3) if call_vol > 0 else 1.0

    # 2. Max Pain Strike (calculated on nearest primary expiry)
    max_pain = calculate_max_pain(nearest_contracts)

    # 3. ATM Implied Volatility
    atm_contracts = sorted(contracts, key=lambda c: abs(c.strike - underlying_spot))[:6]
    valid_ivs = [c.iv for c in atm_contracts if c.iv > 0]
    atm_iv = round(sum(valid_ivs) / len(valid_ivs), 2) if valid_ivs else 50.0

    # 4. Sentiment Verdict
    if pcr_oi >= 1.3:
        pcr_sentiment = "BULLISH_EXHAUSTION_EXTREME"
        pcr_note = (
            f"PCR {pcr_oi:.2f} heavily skewed to puts (hedging extreme / floor accumulation)."
        )
    elif pcr_oi >= 1.0:
        pcr_sentiment = "MILD_BULLISH"
        pcr_note = f"PCR {pcr_oi:.2f} indicates put demand supporting spot floor."
    elif pcr_oi <= 0.6:
        pcr_sentiment = "BEARISH_GREED_EXTREME"
        pcr_note = f"PCR {pcr_oi:.2f} calls overheated (complacency warning)."
    else:
        pcr_sentiment = "NEUTRAL"
        pcr_note = f"PCR {pcr_oi:.2f} in balanced equilibrium."

    # 4. Dealer Gamma Exposure (GEX)
    gex = calculate_deribit_gex(contracts, underlying_spot)

    result = {
        "status": "ONLINE",
        "currency": curr,
        "underlying_spot": round(underlying_spot, 2),
        "contracts_count": len(contracts),
        "primary_expiry": nearest_expiry,
        "max_pain": max_pain,
        "max_pain_distance_pct": round(((max_pain - underlying_spot) / underlying_spot) * 100, 2)
        if underlying_spot > 0
        else 0.0,
        "pcr_open_interest": pcr_oi,
        "pcr_volume": pcr_vol,
        "pcr_sentiment": pcr_sentiment,
        "pcr_note": pcr_note,
        "atm_implied_volatility_pct": atm_iv,
        "total_call_oi": round(call_oi, 2),
        "total_put_oi": round(put_oi, 2),
        "net_gex_usd": gex["net_gex_usd"],
        "call_gex_usd": gex["call_gex_usd"],
        "put_gex_usd": gex["put_gex_usd"],
        "gamma_regime": gex["gamma_regime"],
        "gex_flip_strike": gex["gex_flip_strike"],
        "available_expiries": list(by_expiry.keys())[:10],
        "as_of": datetime.now(timezone.utc).isoformat(),
    }

    with _OPTIONS_CACHE_LOCK:
        _OPTIONS_CACHE[curr] = (now_ts, result)

    return result


def get_crypto_options_snapshot(
    currency: str = "BTC",
    expiry: Optional[str] = None,
) -> tuple[list[Any], Optional[float], list[str], dict[str, Any]]:
    """
    Unified options snapshot returning (contracts, live_spot_price, available_expiries, source_info)
    for Deribit crypto options (BTC, ETH, SOL) formatted in canonical OptionsContract schema.
    """
    from brokers.base import OptionsContract

    curr = currency.upper().replace("USDT", "").replace("USD", "").strip()
    if curr not in ("BTC", "ETH", "SOL"):
        curr = "BTC"

    params = {"currency": curr, "kind": "option"}
    raw_data = []
    try:
        client = get_shared_client()
        resp = client.get(DERIBIT_BOOK_SUMMARY_URL, params=params, timeout=8.0)
        if resp.status_code == 200:
            raw_data = resp.json().get("result", [])
        else:
            logger.warning(f"Deribit API returned HTTP {resp.status_code}")
    except Exception as e:
        logger.error(f"Failed to fetch Deribit snapshot for {curr}: {e}")

    now_utc = datetime.now(timezone.utc).isoformat()
    now_ist = datetime.now().strftime("%I:%M:%S %p IST")

    if not raw_data:
        spot = 0.0
        try:
            from market.crypto_pipeline import get_crypto_ticker

            t = get_crypto_ticker(f"{curr}USDT")
            spot = float(t.get("price", 0.0))
        except Exception:
            pass
        return (
            [],
            spot,
            [],
            {
                "provider": "DERIBIT",
                "source": "DERIBIT_REST",
                "data_state": "UNAVAILABLE",
                "is_realtime": False,
                "is_market_open": True,
                "as_of": now_utc,
                "as_of_display": f"{now_ist} (Deribit 24x7)",
                "source_label": "Deribit 24x7",
            },
        )

    contracts_by_exp: dict[str, list[OptionsContract]] = defaultdict(list)
    underlying_spot = 0.0

    for item in raw_data:
        inst_name = item.get("instrument_name", "")
        parsed = parse_deribit_instrument(inst_name)
        if not parsed:
            continue
        c_curr, raw_exp, strike, opt_type = parsed

        spot = float(item.get("underlying_price", 0.0) or 0.0)
        if spot > 0:
            underlying_spot = spot

        mark_crypto = float(item.get("mark_price", 0.0) or 0.0)
        mark_usd = mark_crypto * spot if spot > 0 else 0.0
        iv = float(item.get("mark_iv", 0.0) or 0.0)
        oi = float(item.get("open_interest", 0.0) or 0.0)
        vol = float(item.get("volume", 0.0) or 0.0)

        bid_usd = float(item.get("bid_price", 0.0) or 0.0) * spot if item.get("bid_price") else None
        ask_usd = float(item.get("ask_price", 0.0) or 0.0) * spot if item.get("ask_price") else None

        iso_exp = raw_exp
        try:
            iso_exp = datetime.strptime(raw_exp.upper(), "%d%b%y").strftime("%Y-%m-%d")
        except Exception:
            pass

        contract = OptionsContract(
            symbol=inst_name,
            underlying=curr,
            expiry=iso_exp,
            strike=strike,
            option_type=opt_type,
            last_price=round(mark_usd, 2),
            oi=int(oi),
            oi_change=0,
            volume=int(vol),
            iv=round(iv, 2),
            bid=round(bid_usd, 2) if bid_usd else None,
            ask=round(ask_usd, 2) if ask_usd else None,
            lot_size=1,
            exchange="DERIBIT",
        )
        contracts_by_exp[iso_exp].append(contract)

    sorted_expiries = sorted(contracts_by_exp.keys())
    active_exp = (
        expiry
        if (expiry and expiry in contracts_by_exp)
        else (sorted_expiries[0] if sorted_expiries else "")
    )
    selected_contracts = contracts_by_exp.get(active_exp, [])

    source_info = {
        "provider": "DERIBIT",
        "source": "DERIBIT_PUBLIC_REST",
        "data_state": "LIVE",
        "is_realtime": True,
        "is_market_open": True,
        "as_of": now_utc,
        "as_of_display": f"{now_ist} (Deribit 24x7)",
        "source_label": "Deribit 24x7 Surface",
    }

    return selected_contracts, underlying_spot, sorted_expiries, source_info
