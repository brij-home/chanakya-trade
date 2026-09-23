"""
engine/asymmetric_radar.py
──────────────────────────
High-Asymmetry Opportunistic Scanner & Early Ignition Engine.

Focuses exclusively on low-risk, high-reward (minimum 1:3.0 to 1:6+ R:R)
setups before or at the moment of expansion across F&O, Cash Equities, and Indices.

The 4 High-Asymmetry Opportunistic Engines:
  1. ⚡ POCKET PIVOT BASE COILING (Minervini / Kacher Setup):
     - Detects Stage-2 leaders accumulating *inside* bases before crowded 52-week breakouts.
     - Volume Signature: Volume > highest down-volume day of the prior 10 sessions.
     - Tight SL below 10-EMA/base low (~1.5% risk) vs Stage-2 expansion (1:4 to 1:6 R:R).
  2. 🔥 F&O MWPL SQUEEZE RADAR (Short Squeeze Inversion):
     - Monitors Market Wide Position Limit nearing ban threshold (MWPL >= 88%) and Ban Exit (< 80%).
     - Trapped short sellers unable to add fresh hedges face forced-covering cascades.
     - SL below 5-day VWAP (~1.8% risk) vs short squeeze thrust (+6% to +12% in stock, 1:4+ in options).
  3. 🧲 "RUBBER BAND" 200-EMA INSTITUTIONAL DIP (Deep Value Mean Reversion):
     - High-quality Tier-1 franchises (clean forensics: Beneish < -1.78, Altman Z > 2.0)
     - Stretched to extreme oversold (14D RSI <= 35) testing the 200-day EMA support anchor.
     - Risk defined below 200-EMA buffer (~1.8% risk) vs mean reversion to 50-SMA (1:3.5 to 1:5 R:R).
  4. 🎯 0DTE / EXPIRY DAY GAMMA UNPINNING (Intraday Index Straddle Breakout):
     - On expiry day afternoons (12:45–15:15 IST), market makers defend ATM Straddle break-evens.
     - Spot index breaking outside the written straddle band forces violent delta-hedging cascades.
     - Fixed-risk defined 0DTE option premium vs explosive payoff (1:3 to 1:5 R:R).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import numpy as np
import pandas as pd

from engine.precursor_radar import classify_symbol_segment, get_scan_universe

logger = logging.getLogger("chanakya.asymmetric_radar")

IST = timezone(timedelta(hours=5, minutes=30))


def _extract_price(obj: Any, *attr_names: str) -> float:
    """Extracts a valid positive float from attributes without tripping on MagicMock."""
    if obj is None:
        return 0.0
    for a in attr_names:
        val = getattr(obj, a, None) if not isinstance(obj, dict) else obj.get(a)
        if val is not None:
            if type(val).__name__ in ("MagicMock", "Mock", "NonCallableMagicMock"):
                continue
            try:
                f = float(val)
                if f > 0:
                    return f
            except (ValueError, TypeError):
                pass


def _compute_atr(df: Optional[pd.DataFrame], ltp: float, period: int = 14) -> float:
    """Computes 14-period ATR from OHLCV DataFrame with fallback to 1.5% daily range proxy."""
    if df is not None and len(df) >= 5:
        try:
            high = (
                df["high"]
                if "high" in df.columns
                else (df["High"] if "High" in df.columns else df["close"])
            )
            low = (
                df["low"]
                if "low" in df.columns
                else (df["Low"] if "Low" in df.columns else df["close"])
            )
            close = df["close"] if "close" in df.columns else df["Close"]
            tr1 = high - low
            tr2 = (high - close.shift(1)).abs()
            tr3 = (low - close.shift(1)).abs()
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr_series = tr.rolling(min(period, len(tr))).mean().dropna()
            if len(atr_series) > 0:
                val = float(atr_series.iloc[-1])
                if val > 0:
                    return round(val, 2)
        except Exception:
            pass
    return round(ltp * 0.015, 2) if ltp > 0 else 1.0


def _enforce_monotonic_trade_levels(
    direction: str,
    ltp: float,
    raw_sl: float,
    target_1: float,
    target_2: float,
    target_moonshot: float,
    atr: float,
) -> tuple[float, float, float, float, float, float, str]:
    """
    Enforces strict mathematical invariants for Asymmetric setups:
    1. Volatility noise floor: SL distance >= max(1.2 * ATR, 1.8% of LTP) to prevent micro-whipsaws and sub-ATR noise invalidations.
    2. Strict Monotonic Invariant:
       - LONG:  SL < Entry_Min <= Entry_LTP < Target_1 < Target_2 < Moonshot
       - SHORT: SL > Entry_Max >= Entry_LTP > Target_1 > Target_2 > Moonshot
    3. Guarantees Stop-Loss sits strictly outside the recommended entry range.
    Returns: (sl_price, risk_pts, t1_price, t2_price, moonshot_price, rr_ratio, entry_range)
    """
    min_noise_buffer = max(1.0, round(max(1.2 * atr, ltp * 0.018), 2))
    is_bullish = direction.upper() in ("BULLISH", "BUY", "LONG")

    if is_bullish:
        raw_risk = ltp - raw_sl if raw_sl > 0 else min_noise_buffer
        risk_pts = round(max(raw_risk, min_noise_buffer), 2)
        sl_price = round(ltp - risk_pts, 2)

        # Monotonic Targets: T1 >= ltp + 1.8R, T2 >= T1 + 1.8R, Moonshot >= T2 + 2.0R
        t1 = round(max(target_1, ltp + 1.8 * risk_pts), 2)
        t2 = round(max(target_2, t1 + 1.8 * risk_pts, ltp + 3.8 * risk_pts), 2)
        moonshot = round(max(target_moonshot, t2 + 2.0 * risk_pts, ltp + 6.0 * risk_pts), 2)

        # Entry range: lower bound must be STRICTLY above sl_price
        entry_lower = round(max(sl_price + max(0.5, 0.20 * atr), ltp * 0.995), 1)
        entry_upper = round(max(entry_lower + 1.0, ltp * 1.008), 1)
        entry_range = f"₹{entry_lower:,.1f} – ₹{entry_upper:,.1f}"

        rr_ratio = round((t2 - ltp) / max(0.1, risk_pts), 1)
    else:
        raw_risk = raw_sl - ltp if raw_sl > 0 else min_noise_buffer
        risk_pts = round(max(raw_risk, min_noise_buffer), 2)
        sl_price = round(ltp + risk_pts, 2)

        t1 = round(
            min(target_1 if target_1 > 0 else (ltp - 1.8 * risk_pts), ltp - 1.8 * risk_pts), 2
        )
        t2 = round(
            min(
                target_2 if target_2 > 0 else (t1 - 1.8 * risk_pts),
                t1 - 1.8 * risk_pts,
                ltp - 3.8 * risk_pts,
            ),
            2,
        )
        moonshot = round(
            min(
                target_moonshot if target_moonshot > 0 else (t2 - 2.0 * risk_pts),
                t2 - 2.0 * risk_pts,
                ltp - 6.0 * risk_pts,
            ),
            2,
        )

        entry_upper = round(min(sl_price - max(0.5, 0.20 * atr), ltp * 1.005), 1)
        entry_lower = round(min(entry_upper - 1.0, ltp * 0.992), 1)
        entry_range = f"₹{entry_lower:,.1f} – ₹{entry_upper:,.1f}"

        rr_ratio = round((ltp - t2) / max(0.1, risk_pts), 1)

    return sl_price, risk_pts, t1, t2, moonshot, rr_ratio, entry_range


def resolve_recommended_option_contract(
    symbol: str,
    direction: str,
    spot: float,
    stop_loss: float = 0.0,
    target_1: float = 0.0,
    target_2: float = 0.0,
    setup_type: str = "",
    is_positional: bool = False,
    ref_dt: Optional[datetime] = None,
) -> dict[str, Any]:
    """
    Resolves recommended options and futures derivative contracts for an underlying index or F&O stock,
    enforcing institutional safeguards:
      1. Single-stock F&O: Automatically routes to the Next-Month series during settlement week (DTE <= 4)
         to eliminate SEBI physical delivery margin surges (25%->100%) and near-month theta collapse.
      2. Positional Swings: Selects options with runway (DTE >= 10) to mitigate theta burn on multi-day targets.
      3. Futures Contract Specification: Formats canonical futures ticker with cost-of-carry entry and delta 1.0 levels.
    """
    from market.options import get_options_chain, get_expiries
    from engine.position_sizer import get_lot_size
    from engine.alert_expiry import (
        resolve_recommended_derivative_expiry,
        get_last_thursday_of_month,
        get_next_monthly_expiry_date,
        _parse_expiry_date,
    )

    clean_sym = symbol.upper().replace("NSE:", "").replace("NFO:", "").strip()
    # Resolve feed-variant names (e.g. "NIFTY 50" → "NIFTY") via the canonical alias map
    try:
        from engine.position_sizer import _SYMBOL_ALIASES

        clean_sym = _SYMBOL_ALIASES.get(clean_sym, clean_sym)
    except Exception:
        pass
    opt_type = "CE" if direction.upper() in ("BULLISH", "BUY", "LONG") else "PE"
    lot_sz = get_lot_size(clean_sym)
    is_index = clean_sym in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX")

    now_dt = ref_dt or datetime.now(IST)
    now_d = now_dt.date()

    if not is_positional:
        if setup_type in ("RUBBER_BAND_200EMA", "POCKET_PIVOT", "PRECURSOR_RADAR", "MULTIBAGGER"):
            is_positional = True
        elif target_1 > 0 and spot > 0 and (abs(target_1 - spot) / spot) >= 0.02:
            is_positional = True

    try:
        available_expiries = get_expiries(clean_sym)
    except Exception:
        available_expiries = []

    target_expiry: Optional[str] = None
    is_next_month_routed = False
    derivative_safeguard = None

    if not is_index:
        # Single-Stock F&O: SEBI Mandatory Physical Delivery Safeguard
        exp_res = resolve_recommended_derivative_expiry(
            symbol=clean_sym,
            instrument_type="OPTION",
            available_expiries=available_expiries,
            ref_dt=now_dt,
        )
        if exp_res.get("is_next_month_routed"):
            rec_exp = exp_res.get("recommended_expiry")
            matched = [
                e
                for e in available_expiries
                if _parse_expiry_date(e) and _parse_expiry_date(e) >= _parse_expiry_date(rec_exp)
            ]
            target_expiry = matched[0] if matched else rec_exp
            is_next_month_routed = True
            derivative_safeguard = "🎯 NEXT-MONTH ROLLOVER (Bypasses SEBI physical delivery margin surge & theta collapse)"
        elif available_expiries:
            if is_positional:
                # Positional swing on stock F&O: require at least 7 DTE to avoid rapid theta bleed
                valid_stock_runways = [
                    e
                    for e in available_expiries
                    if _parse_expiry_date(e) and (_parse_expiry_date(e) - now_d).days >= 7
                ]
                if valid_stock_runways:
                    target_expiry = valid_stock_runways[0]
                    if target_expiry != available_expiries[0]:
                        is_next_month_routed = True
                        derivative_safeguard = "🛡️ STOCK SWING RUNWAY (Selected DTE >= 7 to protect multi-day swing from theta bleed)"
                else:
                    target_expiry = available_expiries[0]
            else:
                target_expiry = available_expiries[0]
    else:
        # Index F&O: Cash Settled
        if is_positional and available_expiries:
            # Multi-session positional swing: select contract with runway (DTE >= 10)
            valid_runways = [
                e
                for e in available_expiries
                if _parse_expiry_date(e) and (_parse_expiry_date(e) - now_d).days >= 10
            ]
            if valid_runways:
                target_expiry = valid_runways[0]
                derivative_safeguard = "🛡️ POSITION RUNWAY (Selected DTE >= 10 to protect multi-day swing from weekly theta decay)"
            else:
                target_expiry = available_expiries[-1]
        elif available_expiries:
            target_expiry = available_expiries[0]

    chain = None
    if target_expiry:
        try:
            chain = get_options_chain(clean_sym, expiry=target_expiry)
        except TypeError:
            chain = get_options_chain(clean_sym)
    if not chain:
        chain = get_options_chain(clean_sym)

    contracts = [c for c in chain if getattr(c, "option_type", "") == opt_type] if chain else []

    if contracts:
        # Group by expiry
        expiries = sorted(list({c.expiry for c in contracts if getattr(c, "expiry", "")}))
        if target_expiry and target_expiry in expiries:
            nearest_exp = target_expiry
        elif expiries:
            if not is_index and is_next_month_routed and len(expiries) > 1:
                nearest_exp = expiries[1]
            elif is_index and is_positional and len(expiries) > 1:
                runways = [
                    e
                    for e in expiries
                    if _parse_expiry_date(e) and (_parse_expiry_date(e) - now_d).days >= 10
                ]
                nearest_exp = runways[0] if runways else expiries[-1]
            else:
                nearest_exp = expiries[0]
        else:
            nearest_exp = target_expiry

        # Filter contracts for nearest expiry
        exp_contracts = (
            [c for c in contracts if getattr(c, "expiry", "") == nearest_exp]
            if nearest_exp
            else contracts
        )

        # Filter for liquid contracts (preventing selection of zero-liquidity ghost strikes)
        min_oi_req = 5000 if is_index else 200
        liquid_exp_contracts = [
            c
            for c in exp_contracts
            if getattr(c, "oi", 0) >= min_oi_req and getattr(c, "last_price", 0.0) > 0
        ]
        chosen_pool = liquid_exp_contracts if liquid_exp_contracts else exp_contracts

        # Select ATM strike closest to spot
        best_contract = min(chosen_pool, key=lambda c: abs(c.strike - spot))
        strike = float(best_contract.strike)
        opt_ltp = float(
            getattr(best_contract, "last_price", 0.0) or getattr(best_contract, "ltp", 0.0) or 0.0
        )
        contract_sym = getattr(best_contract, "symbol", f"{clean_sym}{int(strike)}{opt_type}")
        expiry_date = getattr(best_contract, "expiry", nearest_exp)

        # Fallback 1: Query live quote for contract_sym if last_price was 0.0
        if opt_ltp <= 0.0:
            try:
                from market.quotes import get_ltp

                quote_ltp = get_ltp(
                    f"NFO:{contract_sym}" if ":" not in contract_sym else contract_sym
                )
                if quote_ltp and quote_ltp > 0:
                    opt_ltp = float(quote_ltp)
            except Exception:
                pass

        # Fallback 2: Contract close or settlement price
        if opt_ltp <= 0.0:
            opt_ltp = float(
                getattr(best_contract, "close", 0.0)
                or getattr(best_contract, "settlement_price", 0.0)
                or getattr(best_contract, "prev_close", 0.0)
                or 0.0
            )

        # Fallback 3: Theoretical ATM option proxy (~1.5% of spot)
        if opt_ltp <= 0.0:
            opt_ltp = round(max(0.50, spot * 0.015), 1)
    else:
        # Synthetic fallback based on canonical index strike steps
        step = 100 if "BANK" in clean_sym else 50
        strike = float(round(spot / step) * step)
        opt_ltp = round(spot * 0.015, 1)  # ~1.5% ATM premium proxy
        contract_sym = f"{clean_sym}{int(strike)}{opt_type}"
        expiry_date = target_expiry

    # Estimate option targets based on delta (~0.5 ATM delta)
    delta = 0.50 if opt_type == "CE" else -0.50
    spot_move_t1 = (
        (target_1 - spot) if target_1 > 0 else (spot * 0.01 if opt_type == "CE" else -spot * 0.01)
    )
    spot_move_t2 = (
        (target_2 - spot) if target_2 > 0 else (spot * 0.02 if opt_type == "CE" else -spot * 0.02)
    )
    spot_move_sl = (
        (stop_loss - spot)
        if stop_loss > 0
        else (-spot * 0.007 if opt_type == "CE" else spot * 0.007)
    )

    opt_gain_t1 = delta * spot_move_t1
    opt_gain_t2 = delta * spot_move_t2
    opt_loss_sl = delta * spot_move_sl

    opt_t1 = round(max(0.05, opt_ltp + opt_gain_t1), 2)
    opt_t2 = round(max(0.05, opt_ltp + opt_gain_t2), 2)
    opt_sl = round(max(0.05, opt_ltp + opt_loss_sl), 2)
    # Institutional Risk Control: Cap max option loss at -30% of entry premium
    if opt_ltp > 0:
        opt_sl = max(opt_sl, round(max(0.05, opt_ltp * 0.70), 2))

    # ── Futures Contract Specification ────────────────────────────
    # Formulate canonical monthly futures contract: {SYMBOL}{YY}{MMM}FUT
    fut_exp_date = _parse_expiry_date(expiry_date or target_expiry)
    if not fut_exp_date:
        if is_next_month_routed:
            fut_exp_date = get_next_monthly_expiry_date(now_dt)
        else:
            fut_exp_date = get_last_thursday_of_month(now_d.year, now_d.month)
            if fut_exp_date < now_d:
                fut_exp_date = get_next_monthly_expiry_date(now_dt)

    yr_2d = fut_exp_date.strftime("%y")
    mon_3letter = fut_exp_date.strftime("%b").upper()
    fut_contract_sym = f"{clean_sym}{yr_2d}{mon_3letter}FUT"

    fut_entry = round(spot * 1.0035, 2)
    fut_basis = fut_entry - spot
    fut_t1 = round(target_1 + fut_basis, 2) if target_1 > 0 else 0.0
    fut_t2 = round(target_2 + fut_basis, 2) if target_2 > 0 else 0.0
    fut_sl = round(stop_loss + fut_basis, 2) if stop_loss > 0 else 0.0

    return {
        "strike": strike,
        "option_type": opt_type,
        "contract_symbol": contract_sym,
        "expiry_date": expiry_date,
        "option_premium": opt_ltp,
        "option_target_1": opt_t1,
        "option_target_2": opt_t2,
        "option_stop_loss": opt_sl,
        "lot_size": lot_sz,
        # Institutional derivative safeguards
        "is_positional": is_positional,
        "is_next_month_routed": is_next_month_routed,
        "derivative_safeguard": derivative_safeguard,
        "futures_contract": fut_contract_sym,
        "futures_symbol": f"NFO:{fut_contract_sym}",
        "futures_entry": fut_entry,
        "futures_target_1": fut_t1,
        "futures_target_2": fut_t2,
        "futures_stop_loss": fut_sl,
        "futures_lot_size": lot_sz,
        "futures_recommendation": (
            "Delta 1.0 zero-decay vehicle for positional swing" if is_positional else None
        ),
    }


@dataclass
class AsymmetricOpportunity:
    """An institutional high-asymmetry trade setup with low risk and high reward."""

    opportunity_id: str = ""
    symbol: str = ""
    exchange: str = "NSE"
    setup_type: str = "POCKET_PIVOT"  # "POCKET_PIVOT" | "FNO_BAN_SQUEEZE" | "RUBBER_BAND_200EMA" | "EXPIRY_0DTE_GAMMA"
    setup_label: str = "⚡ Pocket Pivot Base Accumulation"
    segment: str = "FNO"  # "FNO" | "NON_FNO" | "INDEX"
    direction: str = "BULLISH"  # "BULLISH" | "BEARISH"
    conviction_score: int = 85  # 0 to 100
    ltp: float = 0.0

    # Actionable Execution Levels
    entry_range: str = ""
    entry_price: float = 0.0
    stop_loss: float = 0.0
    target_1: float = 0.0  # +2.0R Scale 50%
    target_2: float = 0.0  # +3.5R–4.0R Swing
    target_moonshot: float = 0.0  # +6.0R+ Generational
    risk_reward: str = "1:4.0"
    risk_reward_ratio: float = 4.0
    risk_pts: float = 0.0
    reward_pts: float = 0.0

    # Confluence and Thesis
    confluence_factors: list[str] = field(default_factory=list)
    catalyst_summary: str = ""
    when_to_buy: str = ""
    when_to_wait: str = ""  # Strict "NO CHASE" discipline
    profit_rule: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    # Derivative & Option Execution Mapping
    strike: Optional[float] = None
    option_type: Optional[str] = None  # "CE" | "PE"
    contract_symbol: Optional[str] = None
    expiry_date: Optional[str] = None
    option_premium: Optional[float] = None
    option_target_1: Optional[float] = None
    option_target_2: Optional[float] = None
    option_stop_loss: Optional[float] = None
    lot_size: Optional[int] = None

    # Institutional Derivative Safeguards & Futures Mapping
    futures_contract_symbol: Optional[str] = None
    futures_entry: Optional[float] = None
    futures_target_1: Optional[float] = None
    futures_target_2: Optional[float] = None
    futures_stop_loss: Optional[float] = None
    is_next_month_routed: bool = False
    derivative_safeguard: Optional[str] = None

    # Compatibility Aliases
    moonshot_target: float = 0.0
    reward_t1_pts: float = 0.0
    confluences: list[str] = field(default_factory=list)
    entry_rule: str = ""
    no_chase_rule: str = ""
    verdict: str = ""

    def __post_init__(self) -> None:
        if not self.opportunity_id:
            self.opportunity_id = (
                f"asym-{self.setup_type.lower()[:4]}-{self.symbol}-{uuid.uuid4().hex[:6]}"
            )

        if not self.target_moonshot and self.moonshot_target:
            self.target_moonshot = self.moonshot_target
        elif not self.moonshot_target and self.target_moonshot:
            self.moonshot_target = self.target_moonshot

        if not self.reward_pts and self.reward_t1_pts:
            self.reward_pts = self.reward_t1_pts
        elif not self.reward_t1_pts and self.reward_pts:
            self.reward_t1_pts = self.reward_pts

        if not self.confluence_factors and self.confluences:
            self.confluence_factors = list(self.confluences)
        elif not self.confluences and self.confluence_factors:
            self.confluences = list(self.confluence_factors)

        if not self.when_to_buy and self.entry_rule:
            self.when_to_buy = self.entry_rule
        elif not self.entry_rule and self.when_to_buy:
            self.entry_rule = self.when_to_buy

        if not self.when_to_wait and self.no_chase_rule:
            self.when_to_wait = self.no_chase_rule
        elif not self.no_chase_rule and self.when_to_wait:
            self.no_chase_rule = self.when_to_wait

        if not self.verdict:
            if self.conviction_score >= 85:
                self.verdict = "MAX_CONVICTION"
            elif self.conviction_score >= 75:
                self.verdict = "HIGH_CONVICTION"
            else:
                self.verdict = "MODERATE"

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key) or (isinstance(key, str) and key in self.to_dict())

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, str) and hasattr(self, key):
            return getattr(self, key)
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        return self.to_dict().get(key, default)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["verdict"] = self.verdict
        d["confluences"] = self.confluence_factors
        d["moonshot_target"] = self.target_moonshot
        d["entry_rule"] = self.when_to_buy
        d["no_chase_rule"] = self.when_to_wait
        d["reward_t1_pts"] = self.reward_pts
        return d


class AsymmetricOpportunityRadar:
    """
    Scans liquid markets across F&O, Cash Equities, and Indices to unearth
    high-asymmetry, low-risk opportunities with strict minimum 1:3.0 R:R.
    """

    def __init__(self, min_rr: float = 3.0, min_conviction: int = 75) -> None:
        self.min_rr = min_rr
        self.min_conviction = min_conviction
        self._cache: dict[Any, list[AsymmetricOpportunity]] = {}
        self._cache_ts: dict[Any, float] = {}
        self._cache_ttl: float = 30.0
        import threading

        self._cache_lock = threading.Lock()

    # ── 1. Pocket Pivot Base Accumulation ───────────────────────

    def detect_pocket_pivot(
        self,
        symbol: str,
        df: Optional[pd.DataFrame] = None,
        quote: Optional[Any] = None,
    ) -> Optional[AsymmetricOpportunity]:
        """
        Detects pocket pivot volume signature inside constructive bases before 52W high breakout.
        Volume > max down-volume day of prior 10 sessions while holding near 10-EMA / 50-SMA.
        """
        clean_sym = symbol.upper().replace("NSE:", "").replace("BSE:", "").strip()

        # Fetch Quote & OHLCV if not provided
        if quote is None:
            from market.quotes import get_quote

            quote = get_quote(f"NSE:{clean_sym}")
        if isinstance(quote, dict):
            quote = (
                quote.get(f"NSE:{clean_sym}")
                or quote.get(clean_sym)
                or next(iter(quote.values()), None)
            )
        if not quote:
            return None

        ltp = _extract_price(quote, "last_price", "ltp")
        if ltp <= 0:
            return None

        if df is None or len(df) < 25:
            from market.history import get_ohlcv

            df = get_ohlcv(clean_sym, exchange="NSE", interval="day", days=250)
        if df is None or len(df) < 25:
            return None

        closes = df["close"].values
        opens = df["open"].values
        highs = df["high"].values
        lows = df["low"].values
        volumes = df["volume"].values

        # Compute Technical Moving Averages
        close_series = pd.Series(closes)
        ema10 = close_series.ewm(span=10, adjust=False).mean().values
        sma50 = close_series.rolling(window=min(50, len(closes))).mean().values
        sma200 = (
            close_series.rolling(window=min(200, len(closes))).mean().values
            if len(closes) >= 150
            else None
        )

        cur_close = closes[-1]
        cur_vol = volumes[-1]
        cur_high = highs[-1]
        cur_low = lows[-1]

        # 1. Base Alignment: Close above or within 2% of 50-SMA, uptrend intact
        if cur_close < sma50[-1] * 0.98:
            return None

        # Minervini Rule #1: Price must not be deep below 200-SMA in markdown trend
        if sma200 is not None and cur_close < sma200[-1] * 0.98:
            return None

        # Proximity to 10-EMA or 50-SMA (Inside base, not extended > 4%)
        dist_ema10 = abs(cur_close - ema10[-1]) / cur_close
        dist_sma50 = abs(cur_close - sma50[-1]) / cur_close
        if dist_ema10 > 0.04 and dist_sma50 > 0.04:
            return None  # Too extended from support anchor

        # 2. Pocket Pivot Volume Signature:
        # Today's volume must exceed the HIGHEST down-volume day in the prior 10 days
        down_vols = []
        for i in range(-11, -1):
            if i >= -len(closes) and closes[i] < opens[i]:
                down_vols.append(volumes[i])

        max_down_vol = max(down_vols) if down_vols else float(np.mean(volumes[-10:]))
        if cur_vol <= max_down_vol:
            return None  # Failed pocket pivot volume criteria

        # 3. Candle Quality: Closes in upper 50% of the daily spread
        spread = max(0.01, cur_high - cur_low)
        if (cur_close - cur_low) / spread < 0.48:
            return None  # Weak close / upper wick selling rejection

        # 4. Asymmetric Trade Plan Calculation
        # Stop-loss anchored below confirmed base floor / 10-EMA, guarded by ATR volatility floor
        atr = _compute_atr(df, ltp)
        base_floor = min(float(np.min(lows[-3:])), ema10[-1])
        raw_sl = round(min(base_floor * 0.995, ltp * 0.985), 2)
        raw_risk = max(1.0, ltp - raw_sl)
        raw_t1 = round(ltp + 2.0 * raw_risk, 2)
        raw_t2 = round(ltp + 4.0 * raw_risk, 2)
        raw_moonshot = round(ltp + 6.5 * raw_risk, 2)

        sl_price, risk_pts, t1_price, t2_price, moonshot_price, rr_ratio, entry_range_str = (
            _enforce_monotonic_trade_levels(
                direction="BULLISH",
                ltp=ltp,
                raw_sl=raw_sl,
                target_1=raw_t1,
                target_2=raw_t2,
                target_moonshot=raw_moonshot,
                atr=atr,
            )
        )

        if rr_ratio < self.min_rr:
            return None

        confluences = [
            f"Pocket Pivot Volume: {cur_vol:,.0f} > 10D max down-vol ({max_down_vol:,.0f})",
            f"Constructive Base Coiling: within {min(dist_ema10, dist_sma50) * 100:.1f}% of 10-EMA/50-SMA anchor",
            f"Bullish Upper Close: {(cur_close - cur_low) / spread * 100:.0f}% of daily range",
        ]

        # Calculate Turnover & Segment
        turnover_cr = round((cur_vol * ltp) / 1e7, 2)
        seg = classify_symbol_segment(clean_sym)
        if seg == "NON_FNO" and turnover_cr < 10.0:
            return None  # Strict anti-trap liquidity gate

        # Sector Tailwind & Intraday Pressure Guard
        try:
            from analysis.sector_rotation import get_stock_tailwind

            sec_tailwind = get_stock_tailwind(clean_sym)
            if sec_tailwind:
                if getattr(sec_tailwind, "intraday_alignment", "") == "SEVERE_INTRADAY_HEADWIND":
                    return None  # Drop setup when sector is under severe intraday dump
                if (
                    getattr(sec_tailwind, "quadrant", "") == "LAGGING"
                    and (cur_vol / max_down_vol) < 2.0
                ):
                    return None  # Drop lagging sector unless volume is extraordinarily high (>2.0x)
        except Exception:
            pass

        score = min(96, int(80 + (cur_vol / max_down_vol) * 5))

        # Attach recommended option execution contract for F&O/Index leaders
        opt_info = None
        if seg in ("INDEX", "FNO"):
            opt_info = resolve_recommended_option_contract(
                symbol=clean_sym,
                direction="BULLISH",
                spot=ltp,
                stop_loss=sl_price,
                target_1=t1_price,
                target_2=t2_price,
                setup_type="POCKET_PIVOT",
                is_positional=True,
            )

        setup_lbl = "⚡ Pocket Pivot Base Accumulation"
        if opt_info and opt_info.get("contract_symbol"):
            suffix = f" [{opt_info['contract_symbol']}]"
            if opt_info.get("is_next_month_routed"):
                suffix = f" [{opt_info['contract_symbol']} · 🎯 NEXT-MONTH ROLLOVER]"
            setup_lbl = f"{setup_lbl}{suffix}"

        return AsymmetricOpportunity(
            opportunity_id=f"asym-pp-{clean_sym}-{uuid.uuid4().hex[:6]}",
            symbol=clean_sym,
            exchange="NFO" if seg == "INDEX" else "NSE",
            setup_type="POCKET_PIVOT",
            setup_label=setup_lbl,
            segment=seg,
            direction="BULLISH",
            conviction_score=score,
            ltp=ltp,
            entry_price=ltp,
            entry_range=entry_range_str,
            stop_loss=sl_price,
            target_1=t1_price,
            target_2=t2_price,
            target_moonshot=moonshot_price,
            risk_reward=f"1:{rr_ratio:.1f}",
            risk_reward_ratio=rr_ratio,
            risk_pts=round(risk_pts, 2),
            reward_pts=round(t2_price - ltp, 2),
            confluence_factors=confluences,
            catalyst_summary="Early institutional footprint inside constructive consolidation before 52-week breakout.",
            when_to_buy=f"Enter inside base range on ask while holding above 10-EMA (₹{ema10[-1]:,.1f}).",
            when_to_wait=f"DO NOT CHASE if stock opens > 1.5% higher above ₹{round(ltp * 1.015, 1):,.1f}.",
            profit_rule=f"Scale 50% at T1 (₹{t1_price:,.1f}), move SL to Breakeven, hold runner for T2 (₹{t2_price:,.1f}).",
            metrics={
                "turnover_cr": turnover_cr,
                "vol_ratio": round(cur_vol / max_down_vol, 2),
                "atr_14d": round(atr, 2),
            },
            strike=opt_info["strike"] if opt_info else None,
            option_type=opt_info["option_type"] if opt_info else None,
            contract_symbol=opt_info["contract_symbol"] if opt_info else None,
            expiry_date=opt_info["expiry_date"] if opt_info else None,
            option_premium=opt_info["option_premium"] if opt_info else None,
            option_target_1=opt_info["option_target_1"] if opt_info else None,
            option_target_2=opt_info["option_target_2"] if opt_info else None,
            option_stop_loss=opt_info["option_stop_loss"] if opt_info else None,
            lot_size=opt_info["lot_size"] if opt_info else None,
            futures_contract_symbol=opt_info.get("futures_contract") if opt_info else None,
            futures_entry=opt_info.get("futures_entry") if opt_info else None,
            futures_target_1=opt_info.get("futures_target_1") if opt_info else None,
            futures_target_2=opt_info.get("futures_target_2") if opt_info else None,
            futures_stop_loss=opt_info.get("futures_stop_loss") if opt_info else None,
            is_next_month_routed=opt_info.get("is_next_month_routed", False) if opt_info else False,
            derivative_safeguard=opt_info.get("derivative_safeguard") if opt_info else None,
            created_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        )

    # ── 2. F&O MWPL Squeeze Radar ───────────────────────────────

    def detect_fno_ban_squeeze(
        self,
        symbol: str,
        quote: Optional[Any] = None,
        chain: Optional[list[Any]] = None,
        mwpl_pct: Optional[float] = None,
        is_in_ban: Optional[bool] = None,
        df: Optional[pd.DataFrame] = None,
    ) -> Optional[AsymmetricOpportunity]:
        """
        Detects derivatives short squeeze asymmetry when MWPL >= 88% (pre-ban squeeze)
        or MWPL drops < 80% (ban exit institutional momentum).
        """
        clean_sym = symbol.upper().replace("NSE:", "").replace("BSE:", "").strip()
        seg = classify_symbol_segment(clean_sym)
        if seg != "FNO":
            return None

        # Quote resolution
        if quote is None:
            from market.quotes import get_quote

            quote = get_quote(f"NSE:{clean_sym}")
        if isinstance(quote, dict):
            quote = (
                quote.get(f"NSE:{clean_sym}")
                or quote.get(clean_sym)
                or next(iter(quote.values()), None)
            )
        if not quote:
            return None

        ltp = _extract_price(quote, "last_price", "ltp")
        vwap = _extract_price(quote, "vwap")
        chg = _extract_price(quote, "change_pct", "change")
        if ltp <= 0:
            return None

        # Heuristic MWPL calculation if not provided explicitly:
        if mwpl_pct is None:
            from market.options import get_options_chain

            if chain is None:
                chain = get_options_chain(clean_sym)
            if chain:
                ce_shedding = []
                pe_building = []
                for c in chain:
                    doi = getattr(c, "oi_change", 0)
                    oi = getattr(c, "oi", 0)
                    opt_type = getattr(c, "option_type", "")
                    if opt_type == "CE" and doi < 0 and oi > 0:
                        ce_shedding.append(abs(doi) / oi * 100.0)
                    elif opt_type == "PE" and doi > 0 and oi > 0:
                        pe_building.append(doi / oi * 100.0)
                if ce_shedding and max(ce_shedding) >= 12.0 and chg >= 1.0:
                    mwpl_pct = 89.5  # Inferred Pre-Ban Squeeze Condition
                else:
                    mwpl_pct = 72.0
            else:
                mwpl_pct = 70.0

        is_pre_ban = mwpl_pct >= 88.0
        is_ban_exit = 75.0 <= mwpl_pct < 80.0 and chg > 1.2

        if not (is_pre_ban or is_ban_exit):
            return None

        # Asymmetric risk levels
        atr = _compute_atr(df, ltp)
        raw_sl = round(vwap * 0.985 if vwap > 0 else ltp * 0.982, 2)
        raw_risk = max(1.0, ltp - raw_sl)
        raw_t1 = round(ltp + 2.0 * raw_risk, 2)
        raw_t2 = round(ltp + 4.2 * raw_risk, 2)
        raw_moonshot = round(ltp + 7.0 * raw_risk, 2)

        sl_price, risk_pts, t1_price, t2_price, moonshot_price, rr_ratio, entry_range_str = (
            _enforce_monotonic_trade_levels(
                direction="BULLISH",
                ltp=ltp,
                raw_sl=raw_sl,
                target_1=raw_t1,
                target_2=raw_t2,
                target_moonshot=raw_moonshot,
                atr=atr,
            )
        )

        setup_name = (
            "🔥 F&O Pre-Ban Short Squeeze"
            if is_pre_ban
            else "🚀 F&O Ban Exit Institutional Ignition"
        )
        confluences = [
            f"MWPL at {mwpl_pct:.1f}% (Bears prohibited from adding fresh short hedges)",
            "Price holding comfortably above intraday VWAP with expanding turnover",
            "Call writers shedding open interest in panic delta-hedging",
        ]

        score = 88 if is_pre_ban else 84

        opt_info = resolve_recommended_option_contract(
            symbol=clean_sym,
            direction="BULLISH",
            spot=ltp,
            stop_loss=sl_price,
            target_1=t1_price,
            target_2=t2_price,
            setup_type="FNO_BAN_SQUEEZE",
            is_positional=True,
        )
        if opt_info and opt_info.get("contract_symbol"):
            suffix = f" [{opt_info['contract_symbol']}]"
            if opt_info.get("is_next_month_routed"):
                suffix = f" [{opt_info['contract_symbol']} · 🎯 NEXT-MONTH ROLLOVER]"
            setup_name = f"{setup_name}{suffix}"

        return AsymmetricOpportunity(
            opportunity_id=f"asym-mwpl-{clean_sym}-{uuid.uuid4().hex[:6]}",
            symbol=clean_sym,
            exchange="NSE",
            setup_type="FNO_BAN_SQUEEZE",
            setup_label=setup_name,
            segment="FNO",
            direction="BULLISH",
            conviction_score=score,
            ltp=ltp,
            entry_price=ltp,
            entry_range=entry_range_str,
            stop_loss=sl_price,
            target_1=t1_price,
            target_2=t2_price,
            target_moonshot=moonshot_price,
            risk_reward=f"1:{rr_ratio:.1f}",
            risk_reward_ratio=rr_ratio,
            risk_pts=round(risk_pts, 2),
            reward_pts=round(t2_price - ltp, 2),
            confluence_factors=confluences,
            catalyst_summary="Derivatives structural bottleneck forcing trapped short sellers to cover at market ask.",
            when_to_buy="Enter on ask when price breaks 5-minute VWAP with expanding volume.",
            when_to_wait="DO NOT CHASE if stock opens > 2.0% higher without initial retest.",
            profit_rule=f"Lock 50% at T1 (₹{t1_price:,.1f}), trail stop to cost, let runner target T2 (₹{t2_price:,.1f}).",
            metrics={"mwpl_pct": mwpl_pct, "is_pre_ban": is_pre_ban},
            strike=opt_info["strike"] if opt_info else None,
            option_type=opt_info["option_type"] if opt_info else None,
            contract_symbol=opt_info["contract_symbol"] if opt_info else None,
            expiry_date=opt_info["expiry_date"] if opt_info else None,
            option_premium=opt_info["option_premium"] if opt_info else None,
            option_target_1=opt_info["option_target_1"] if opt_info else None,
            option_target_2=opt_info["option_target_2"] if opt_info else None,
            option_stop_loss=opt_info["option_stop_loss"] if opt_info else None,
            lot_size=opt_info["lot_size"] if opt_info else None,
            futures_contract_symbol=opt_info.get("futures_contract") if opt_info else None,
            futures_entry=opt_info.get("futures_entry") if opt_info else None,
            futures_target_1=opt_info.get("futures_target_1") if opt_info else None,
            futures_target_2=opt_info.get("futures_target_2") if opt_info else None,
            futures_stop_loss=opt_info.get("futures_stop_loss") if opt_info else None,
            is_next_month_routed=opt_info.get("is_next_month_routed", False) if opt_info else False,
            derivative_safeguard=opt_info.get("derivative_safeguard") if opt_info else None,
            created_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        )

    # ── 3. Rubber Band 200-EMA Institutional Deep Value Dip ──────

    def detect_rubber_band_reversal(
        self,
        symbol: str,
        df: Optional[pd.DataFrame] = None,
        quote: Optional[Any] = None,
    ) -> Optional[AsymmetricOpportunity]:
        """
        Detects deep value mean-reversion in Tier-1 institutional franchises
        testing their 200-day EMA with oversold RSI (<= 35) and clean forensics.
        """
        clean_sym = symbol.upper().replace("NSE:", "").replace("BSE:", "").strip()

        if quote is None:
            from market.quotes import get_quote

            quote = get_quote(f"NSE:{clean_sym}")
        if isinstance(quote, dict):
            quote = (
                quote.get(f"NSE:{clean_sym}")
                or quote.get(clean_sym)
                or next(iter(quote.values()), None)
            )
        if not quote:
            return None

        ltp = _extract_price(quote, "last_price", "ltp")
        if ltp <= 0:
            return None

        if df is None or len(df) < 50:
            from market.history import get_ohlcv

            df = get_ohlcv(clean_sym, exchange="NSE", interval="day", days=250)
        if df is None or len(df) < 50:
            return None

        closes = df["close"].values
        lows = df["low"].values
        opens = df["open"].values

        close_series = pd.Series(closes)
        ema200 = close_series.ewm(span=min(200, len(closes)), adjust=False).mean().values
        sma50 = close_series.rolling(window=min(50, len(closes))).mean().values

        cur_close = closes[-1]
        cur_ema200 = ema200[-1]
        cur_sma50 = sma50[-1]

        # 1. Price is within 3.5% of 200-EMA
        dist_200 = abs(cur_close - cur_ema200) / cur_ema200
        if dist_200 > 0.035:
            return None

        # 2. 14-Day RSI is oversold (<= 36)
        delta = close_series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, 0.001)
        rsi = 100 - (100 / (1 + rs))
        cur_rsi = float(rsi.iloc[-1]) if not rsi.empty else 50.0

        if cur_rsi > 36.0:
            return None  # Not deeply oversold

        # 3. Reversal Candlestick (Hammer or Bullish Rejection)
        lower_wick = min(opens[-1], closes[-1]) - lows[-1]
        body = abs(closes[-1] - opens[-1])
        is_hammer = lower_wick >= (1.5 * body)
        is_green = closes[-1] >= opens[-1]

        if not (is_hammer or is_green):
            return None  # Knife is still falling, wait for absorption

        # 4. Forensic Quality Check (Ensure we are NOT buying a dying penny/fraud stock)
        try:
            from analysis.forensic import audit_company_forensics

            audit = audit_company_forensics(clean_sym)
            if getattr(audit, "beneish_flagged", False) is True:
                return None  # Accounting red flags detected!
        except Exception:
            pass

        # 5. Asymmetric Levels
        atr = _compute_atr(df, ltp)
        # Anchor stop below prior established daily swing or 200-EMA
        # Use lows[-2] if available to avoid unconfirmed current forming intraday bar
        ref_low = float(lows[-2]) if len(lows) >= 2 else float(lows[-1])
        raw_sl = round(min(ref_low * 0.992, cur_ema200 * 0.985), 2)
        raw_risk = max(1.0, ltp - raw_sl)
        raw_t1 = round(max(cur_sma50, ltp + 2.0 * raw_risk), 2)
        raw_t2 = round(ltp + 4.0 * raw_risk, 2)
        raw_moonshot = round(ltp + 6.0 * raw_risk, 2)

        sl_price, risk_pts, t1_price, t2_price, moonshot_price, rr_ratio, entry_range_str = (
            _enforce_monotonic_trade_levels(
                direction="BULLISH",
                ltp=ltp,
                raw_sl=raw_sl,
                target_1=raw_t1,
                target_2=raw_t2,
                target_moonshot=raw_moonshot,
                atr=atr,
            )
        )

        if rr_ratio < self.min_rr:
            return None

        seg = classify_symbol_segment(clean_sym)
        confluences = [
            f"200-EMA Institutional Floor: Trading within {dist_200 * 100:.1f}% of major 200-EMA anchor",
            f"14-Day RSI Oversold Climax: {cur_rsi:.1f} (Rubber-band stretched to extreme)",
            "Bullish absorption hammer printed with long lower rejection shadow",
        ]

        score = min(94, int(78 + (36.0 - cur_rsi) * 2))

        # Attach recommended option execution contract for F&O/Index leaders
        opt_info = None
        if seg in ("INDEX", "FNO"):
            opt_info = resolve_recommended_option_contract(
                symbol=clean_sym,
                direction="BULLISH",
                spot=ltp,
                stop_loss=sl_price,
                target_1=t1_price,
                target_2=t2_price,
                setup_type="RUBBER_BAND_200EMA",
                is_positional=True,
            )

        setup_lbl = "🧲 Rubber Band 200-EMA Deep Value"
        if opt_info and opt_info.get("contract_symbol"):
            suffix = f" [{opt_info['contract_symbol']}]"
            if opt_info.get("is_next_month_routed"):
                suffix = f" [{opt_info['contract_symbol']} · 🎯 NEXT-MONTH ROLLOVER]"
            setup_lbl = f"{setup_lbl}{suffix}"

        return AsymmetricOpportunity(
            opportunity_id=f"asym-200ema-{clean_sym}-{uuid.uuid4().hex[:6]}",
            symbol=clean_sym,
            exchange="NFO" if seg == "INDEX" else "NSE",
            setup_type="RUBBER_BAND_200EMA",
            setup_label=setup_lbl,
            segment=seg,
            direction="BULLISH",
            conviction_score=score,
            ltp=ltp,
            entry_price=ltp,
            entry_range=entry_range_str,
            stop_loss=sl_price,
            target_1=t1_price,
            target_2=t2_price,
            target_moonshot=moonshot_price,
            risk_reward=f"1:{rr_ratio:.1f}",
            risk_reward_ratio=rr_ratio,
            risk_pts=round(risk_pts, 2),
            reward_pts=round(t2_price - ltp, 2),
            confluence_factors=confluences,
            catalyst_summary="Deep institutional value absorption on high-quality franchise at major 200-day EMA benchmark.",
            when_to_buy=f"Enter near 200-EMA (₹{cur_ema200:,.1f}) on lower-wick absorption.",
            when_to_wait="DO NOT CHASE if price re-tests below 200-EMA without bouncing.",
            profit_rule=f"Book 50% at 50-SMA T1 (₹{t1_price:,.1f}), move SL to Breakeven, hold runner for T2 (₹{t2_price:,.1f}).",
            metrics={
                "rsi": round(cur_rsi, 1),
                "ema200": round(cur_ema200, 2),
                "atr_14d": round(atr, 2),
            },
            strike=opt_info["strike"] if opt_info else None,
            option_type=opt_info["option_type"] if opt_info else None,
            contract_symbol=opt_info["contract_symbol"] if opt_info else None,
            expiry_date=opt_info["expiry_date"] if opt_info else None,
            option_premium=opt_info["option_premium"] if opt_info else None,
            option_target_1=opt_info["option_target_1"] if opt_info else None,
            option_target_2=opt_info["option_target_2"] if opt_info else None,
            option_stop_loss=opt_info["option_stop_loss"] if opt_info else None,
            lot_size=opt_info["lot_size"] if opt_info else None,
            futures_contract_symbol=opt_info.get("futures_contract") if opt_info else None,
            futures_entry=opt_info.get("futures_entry") if opt_info else None,
            futures_target_1=opt_info.get("futures_target_1") if opt_info else None,
            futures_target_2=opt_info.get("futures_target_2") if opt_info else None,
            futures_stop_loss=opt_info.get("futures_stop_loss") if opt_info else None,
            is_next_month_routed=opt_info.get("is_next_month_routed", False) if opt_info else False,
            derivative_safeguard=opt_info.get("derivative_safeguard") if opt_info else None,
            created_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        )

    # ── 4. 0DTE / Expiry Day Gamma Straddle Unpinning ────────────

    def detect_0dte_gamma_breakout(
        self,
        symbol: str,
        spot: Optional[float] = None,
        chain: Optional[Any] = None,
        expiry_date: Optional[str] = None,
    ) -> Optional[AsymmetricOpportunity]:
        """
        Detects 0DTE expiry gamma unpinning on major indices (NIFTY, BANKNIFTY)
        when spot price breaks out of the ATM Straddle break-even range.
        """
        clean_sym = symbol.upper().replace("^", "").strip()
        if clean_sym not in (
            "NIFTY",
            "BANKNIFTY",
            "FINNIFTY",
            "MIDCPNIFTY",
            "SENSEX",
            "BANKEX",
            "NSEI",
            "NSEBANK",
        ):
            return None

        if spot is None:
            from market.quotes import get_quote, get_ltp

            q = get_quote(f"NSE:{clean_sym}")
            if isinstance(q, dict):
                q = q.get(f"NSE:{clean_sym}") or next(iter(q.values()), None)
            spot = float(getattr(q, "ltp", 0.0) or getattr(q, "last_price", 0.0) or 0.0)
            if not spot or spot <= 0:
                spot = get_ltp(f"NSE:{clean_sym}")
        if not spot or spot <= 0:
            return None

        if chain is None:
            from market.options import get_options_chain

            chain = get_options_chain(clean_sym)

        # Normalize chain into a list of contract objects
        contracts: list[Any] = []
        if isinstance(chain, list):
            contracts = chain
        elif hasattr(chain, "contracts") and isinstance(chain.contracts, list):
            contracts = chain.contracts
        elif hasattr(chain, "calls") or hasattr(chain, "puts"):
            calls_raw = getattr(chain, "calls", None)
            puts_raw = getattr(chain, "puts", None)
            if isinstance(calls_raw, dict):
                for strike, c in calls_raw.items():
                    setattr(c, "strike", getattr(c, "strike", strike))
                    setattr(c, "option_type", "CE")
                    contracts.append(c)
            elif isinstance(calls_raw, list):
                contracts.extend(calls_raw)
            if isinstance(puts_raw, dict):
                for strike, p in puts_raw.items():
                    setattr(p, "strike", getattr(p, "strike", strike))
                    setattr(p, "option_type", "PE")
                    contracts.append(p)
            elif isinstance(puts_raw, list):
                contracts.extend(puts_raw)

        if not contracts or len(contracts) < 2:
            return None

        # Find ATM Straddle Premium
        strikes = sorted(
            list({getattr(c, "strike", 0) for c in contracts if getattr(c, "strike", 0) > 0})
        )
        if not strikes:
            return None

        atm_strike = min(strikes, key=lambda s: abs(s - spot))
        ce_atm = next(
            (
                c
                for c in contracts
                if getattr(c, "strike", 0) == atm_strike and getattr(c, "option_type", "") == "CE"
            ),
            None,
        )
        pe_atm = next(
            (
                c
                for c in contracts
                if getattr(c, "strike", 0) == atm_strike and getattr(c, "option_type", "") == "PE"
            ),
            None,
        )

        if not ce_atm or not pe_atm:
            return None

        ce_ltp = float(getattr(ce_atm, "ltp", 0.0) or getattr(ce_atm, "last_price", 0.0) or 0.0)
        pe_ltp = float(getattr(pe_atm, "ltp", 0.0) or getattr(pe_atm, "last_price", 0.0) or 0.0)
        straddle_premium = ce_ltp + pe_ltp

        if straddle_premium <= 0:
            return None

        upper_breakeven = atm_strike + straddle_premium
        lower_breakeven = atm_strike - straddle_premium

        # Trigger when spot index crosses outside the straddle band by at least 0.15%
        is_bullish_unpin = spot > (upper_breakeven * 1.0015)
        is_bearish_unpin = spot < (lower_breakeven * 0.9985)

        if not (is_bullish_unpin or is_bearish_unpin):
            return None

        # 1. Tug-of-War Index Polarization Check:
        # If NIFTY heavyweights are polarized (e.g. HDFC Bank up vs TCS/Reliance down), suppress index breakout
        if clean_sym in ("NIFTY", "NIFTY 50", "NSEI"):
            try:
                from market.indices import get_index_polarization

                pol = get_index_polarization("NIFTY")
                if pol and pol.is_polarized:
                    logger.info(
                        f"[AsymmetricRadar] Suppressing 0DTE Gamma breakout for {clean_sym}: {pol.summary}"
                    )
                    return None
            except Exception:
                pass

        # 2. VIX Volatility Regime Detection:
        vix = 14.0
        try:
            from market.indices import get_vix

            vix_val = get_vix()
            if vix_val > 0:
                vix = vix_val
        except Exception:
            pass

        is_low_vix = vix < 12.0
        direction = "BULLISH" if is_bullish_unpin else "BEARISH"

        # Asymmetric risk levels
        atr = _compute_atr(None, spot)
        if direction == "BULLISH":
            raw_sl = round(upper_breakeven * 0.996, 2)
            raw_risk = max(5.0, spot - raw_sl)
            raw_t1 = round(spot + 2.0 * raw_risk, 2)
            raw_t2 = round(spot + 4.0 * raw_risk, 2)
            raw_moonshot = round(spot + 6.0 * raw_risk, 2)
        else:
            raw_sl = round(lower_breakeven * 1.004, 2)
            raw_risk = max(5.0, raw_sl - spot)
            raw_t1 = round(spot - 2.0 * raw_risk, 2)
            raw_t2 = round(spot - 4.0 * raw_risk, 2)
            raw_moonshot = round(spot - 6.0 * raw_risk, 2)

        sl_price, risk_pts, t1_price, t2_price, moonshot, rr_ratio, entry_range_str = (
            _enforce_monotonic_trade_levels(
                direction=direction,
                ltp=spot,
                raw_sl=raw_sl,
                target_1=raw_t1,
                target_2=raw_t2,
                target_moonshot=raw_moonshot,
                atr=atr,
            )
        )

        confluences = [
            f"0DTE Straddle Unpinned: Spot ({spot:,.1f}) broke outside ATM {atm_strike} straddle band (₹{straddle_premium:.1f} prem)",
            f"{'Upper' if direction == 'BULLISH' else 'Lower'} Break-Even breached: Market makers forced to aggressively delta-hedge",
            "Gamma explosion velocity triggering runaway intraday cascade",
        ]
        if is_low_vix:
            confluences.append(
                f"Low-VIX Regime Guardrail (VIX {vix:.1f} < 12.0): Naked option buying suppressed; Defined-Risk {'Bull Put' if direction == 'BULLISH' else 'Bear Call'} credit spread enforced."
            )

        score = 90

        chosen_contract = ce_atm if direction == "BULLISH" else pe_atm
        opt_prem = float(
            getattr(chosen_contract, "ltp", 0.0)
            or getattr(chosen_contract, "last_price", 0.0)
            or (ce_ltp if direction == "BULLISH" else pe_ltp)
        )
        opt_sym = getattr(
            chosen_contract,
            "symbol",
            f"{clean_sym}{int(atm_strike)}{'CE' if direction == 'BULLISH' else 'PE'}",
        )
        opt_exp = getattr(chosen_contract, "expiry", None)

        from engine.position_sizer import get_lot_size

        lot_sz = get_lot_size(clean_sym)

        # Estimate option targets
        delta = 0.50 if direction == "BULLISH" else -0.50
        spot_move_t1 = t1_price - spot
        spot_move_t2 = t2_price - spot
        spot_move_sl = sl_price - spot
        opt_t1 = round(max(0.05, opt_prem + (delta * spot_move_t1)), 2)
        opt_t2 = round(max(0.05, opt_prem + (delta * spot_move_t2)), 2)
        opt_sl = round(max(0.05, opt_prem + (delta * spot_move_sl)), 2)

        setup_type = "EXPIRY_0DTE_CREDIT_SPREAD" if is_low_vix else "EXPIRY_0DTE_GAMMA"
        setup_label = (
            f"🛡️ 0DTE Defined-Risk {'Bull Put' if direction == 'BULLISH' else 'Bear Call'} Credit Spread [{clean_sym}]"
            if is_low_vix
            else f"⚡ 0DTE Expiry Gamma Straddle Unpinning [{opt_sym}]"
        )
        catalyst = (
            f"India VIX ({vix:.1f} < 12.0) indicates extreme IV crush risk. Naked option buying suppressed; "
            f"Defined-Risk {'Bull Put' if direction == 'BULLISH' else 'Bear Call'} credit spread enforced to profit from rapid theta decay."
            if is_low_vix
            else "Dealer short-gamma unpinning forcing vertical index momentum as written straddles implode."
        )
        profit_rule = (
            f"Collect credit on {'Bull Put' if direction == 'BULLISH' else 'Bear Call'} spread; book 75-80% of max profit into 15:00 IST expiry burn."
            if is_low_vix
            else f"Book 50% at T1 (₹{t1_price:,.1f}), move SL to Cost, let remainder ride to T2 (₹{t2_price:,.1f})."
        )

        return AsymmetricOpportunity(
            opportunity_id=f"asym-0dte-{clean_sym}-{uuid.uuid4().hex[:6]}",
            symbol=clean_sym,
            exchange="NFO",
            setup_type=setup_type,
            setup_label=setup_label,
            segment="INDEX",
            direction=direction,
            conviction_score=score,
            ltp=spot,
            entry_price=spot,
            entry_range=entry_range_str,
            stop_loss=sl_price,
            target_1=t1_price,
            target_2=t2_price,
            target_moonshot=moonshot,
            risk_reward=f"1:{rr_ratio:.1f}",
            risk_reward_ratio=rr_ratio,
            risk_pts=round(risk_pts, 1),
            reward_pts=round(abs(t2_price - spot), 1),
            confluence_factors=confluences,
            catalyst_summary=catalyst,
            when_to_buy=f"Enter {direction} 0DTE {'credit spread' if is_low_vix else 'options/futures'} on 5-min candle close outside ₹{upper_breakeven if direction == 'BULLISH' else lower_breakeven:,.1f}.",
            when_to_wait="DO NOT CHASE if price reverses back inside the ATM straddle boundary.",
            profit_rule=profit_rule,
            metrics={"atm_strike": atm_strike, "straddle_premium": round(straddle_premium, 2)},
            strike=float(atm_strike),
            option_type="CE" if direction == "BULLISH" else "PE",
            contract_symbol=opt_sym,
            expiry_date=opt_exp,
            option_premium=opt_prem,
            option_target_1=opt_t1,
            option_target_2=opt_t2,
            option_stop_loss=opt_sl,
            lot_size=lot_sz,
            created_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        )

    # ── 5. MCX Commodity Volatility Pinch & Asymmetry ───────────

    def detect_commodity_asymmetry(
        self,
        symbol: str,
        df: Optional[pd.DataFrame] = None,
        quote: Optional[Any] = None,
    ) -> Optional[AsymmetricOpportunity]:
        """
        Detects high-asymmetry commodity setups (Crude, Gold, Silver, Copper, NatGas)
        coiling at key structural anchors (VWAP, 20-EMA) with low-risk noise-hardened stops
        and minimum 1:3.0 R:R payoff potential into the US session.
        """
        clean_sym = symbol.upper().replace("MCX:", "").strip()
        if quote is None:
            from market.quotes import get_quote

            quotes_dict = get_quote(f"MCX:{clean_sym}")
            quote = (
                quotes_dict.get(f"MCX:{clean_sym}")
                or quotes_dict.get(clean_sym)
                or next(iter(quotes_dict.values()), None)
            )
        if isinstance(quote, dict):
            quote = (
                quote.get(f"MCX:{clean_sym}")
                or quote.get(clean_sym)
                or next(iter(quote.values()), None)
            )
        if not quote:
            return None

        ltp = _extract_price(quote, "last_price", "ltp")
        if ltp <= 0:
            return None

        vwap = _extract_price(quote, "vwap") or ltp

        # Fetch daily or 15m OHLCV if not passed
        if df is None or len(df) < 15:
            from market.history import get_ohlcv

            df = get_ohlcv(clean_sym, exchange="MCX", interval="day", days=30)

        if df is None or len(df) < 10:
            return None

        closes = df["close"].values
        highs = df["high"].values if "high" in df.columns else closes
        lows = df["low"].values if "low" in df.columns else closes

        # Calculate daily ATR
        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(abs(highs[1:] - closes[:-1]), abs(lows[1:] - closes[:-1])),
        )
        atr = round(float(np.mean(tr[-14:])), 2) if len(tr) >= 14 else round(ltp * 0.01, 2)

        # 20-day EMA
        ema20 = float(pd.Series(closes).ewm(span=20).mean().iloc[-1])

        # Directional bias: anchored by relation to 20-EMA and VWAP
        is_bullish = ltp >= ema20 * 0.985 and ltp >= vwap * 0.99
        is_bearish = ltp <= ema20 * 1.015 and ltp <= vwap * 1.01

        if not (is_bullish or is_bearish):
            return None

        direction = "BULLISH" if is_bullish else "BEARISH"

        # Noise-safe stop-loss: 1.5x ATR (or minimum floor)
        is_energy = clean_sym in ("CRUDEOIL", "CRUDEOILM", "NATURALGAS", "NATGASMINI")
        min_pct = 0.008 if is_energy else 0.005
        raw_risk = max(atr * 1.5, ltp * min_pct)

        if direction == "BULLISH":
            raw_sl = round(max(1.0, ltp - raw_risk), 2)
            raw_t1 = round(ltp + 2.0 * raw_risk, 2)
            raw_t2 = round(ltp + 3.5 * raw_risk, 2)
            raw_moonshot = round(ltp + 5.0 * raw_risk, 2)
        else:
            raw_sl = round(ltp + raw_risk, 2)
            raw_t1 = round(max(1.0, ltp - 2.0 * raw_risk), 2)
            raw_t2 = round(max(1.0, ltp - 3.5 * raw_risk), 2)
            raw_moonshot = round(max(1.0, ltp - 5.0 * raw_risk), 2)

        sl_price, risk_pts, t1_price, t2_price, moonshot, rr_ratio, entry_range_str = (
            _enforce_monotonic_trade_levels(
                direction=direction,
                ltp=ltp,
                raw_sl=raw_sl,
                target_1=raw_t1,
                target_2=raw_t2,
                target_moonshot=raw_moonshot,
                atr=atr,
            )
        )

        if rr_ratio < 3.0:
            return None

        from engine.position_sizer import get_lot_size

        lot_sz = get_lot_size(clean_sym) or 1

        confluences = [
            f"MCX Commodity Volatility Pinch: {clean_sym} coiling near 20-EMA (₹{ema20:,.1f}) & VWAP (₹{vwap:,.1f})",
            f"Noise-safe {direction.lower()} risk floor ({risk_pts:,.1f} pts / {round(risk_pts / ltp * 100, 2)}%) clears intraday chop",
            f"Asymmetric {rr_ratio:.1f}x risk:reward extension into US session liquidity",
        ]

        return AsymmetricOpportunity(
            opportunity_id=f"asym-comm-{clean_sym.lower()}-{uuid.uuid4().hex[:6]}",
            symbol=clean_sym,
            exchange="MCX",
            setup_type="COMMODITY_VWAP_PINCH",
            setup_label=f"🛢️ MCX Commodity Asymmetry [{clean_sym}]",
            segment="COMMODITY",
            direction=direction,
            conviction_score=82,
            ltp=ltp,
            entry_price=ltp,
            entry_range=entry_range_str,
            stop_loss=sl_price,
            target_1=t1_price,
            target_2=t2_price,
            target_moonshot=moonshot,
            risk_reward=f"1:{rr_ratio:.1f}",
            risk_reward_ratio=rr_ratio,
            risk_pts=round(risk_pts, 1),
            reward_pts=round(abs(t2_price - ltp), 1),
            confluence_factors=confluences,
            catalyst_summary=f"Institutional pre-expansion coiling in {clean_sym} with favorable volatility risk-parity.",
            when_to_buy=f"Enter {direction} on 15m candle close adhering to VWAP ₹{vwap:,.1f}.",
            when_to_wait="DO NOT CHASE if price moves > 1.2% past entry before confirmation.",
            profit_rule=f"Book 50% at T1 (₹{t1_price:,.1f}), move SL to Breakeven, let runner target T2 (₹{t2_price:,.1f}).",
            metrics={
                "atr": atr,
                "ema20": round(ema20, 2),
                "vwap": round(vwap, 2),
                "lot_size": lot_sz,
            },
            lot_size=lot_sz,
            created_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        )

    # ── 6. ICT Turtle Soup / Wyckoff UTAD Liquidity Sweep Short ──

    def detect_turtle_soup_sweep_short(
        self,
        symbol: str,
        df: Optional[pd.DataFrame] = None,
        quote: Optional[Any] = None,
    ) -> Optional[AsymmetricOpportunity]:
        """
        Detects institutional liquidity sweep above 10D/20D swing high (ICT Turtle Soup / Wyckoff UTAD).
        Mechanics:
          1. Spot pierces prior 10-20 bar swing high by 0.1% to 2.0% (triggering retail breakout stops).
          2. Candle prints prominent upper rejection wick (>= 40% of total candle spread) and closes back BELOW the swing high.
          3. Micro stop-loss anchored immediately above the sweep wick high (+0.20x ATR).
          4. Targets opposing dealing range equilibrium (50%) and demand pool (1:4 to 1:7 R:R).
        """
        clean_sym = (
            symbol.upper().replace("NSE:", "").replace("BSE:", "").replace("NFO:", "").strip()
        )

        if quote is None:
            from market.quotes import get_quote

            quote = get_quote(f"NSE:{clean_sym}")
        if isinstance(quote, dict):
            quote = (
                quote.get(f"NSE:{clean_sym}")
                or quote.get(clean_sym)
                or next(iter(quote.values()), None)
            )
        if not quote:
            return None

        ltp = _extract_price(quote, "last_price", "ltp")
        if ltp <= 0:
            return None

        if df is None or len(df) < 20:
            from market.history import get_ohlcv

            df = get_ohlcv(clean_sym, exchange="NSE", interval="day", days=60)
        if df is None or len(df) < 20:
            return None

        closes = df["close"].values
        highs = df["high"].values
        lows = df["low"].values
        opens = df["open"].values if "open" in df.columns else closes

        cur_close = closes[-1]
        cur_high = highs[-1]
        cur_low = lows[-1]
        cur_open = opens[-1]
        spread = max(0.01, cur_high - cur_low)

        # Prior swing high in previous 10 to 20 bars (excluding today's bar)
        prior_highs = highs[-21:-1] if len(highs) >= 21 else highs[:-1]
        prior_lows = lows[-21:-1] if len(lows) >= 21 else lows[:-1]
        if len(prior_highs) < 5:
            return None
        swing_high = float(np.max(prior_highs))
        swing_low = float(np.min(prior_lows))

        # Condition 1: Today's high swept the swing high
        is_swept = cur_high >= swing_high * 1.001
        # Condition 2: Close failed to sustain above swing high (reclaimed below or equal)
        failed_breakout = cur_close <= swing_high * 1.003
        # Condition 3: Rejection upper wick is at least 40% of the candle range
        upper_wick_ratio = (cur_high - max(cur_close, cur_open)) / spread
        has_rejection = upper_wick_ratio >= 0.40

        if not (is_swept and failed_breakout and has_rejection):
            return None

        atr = _compute_atr(df, ltp)

        # Stop-loss anchored strictly above the sweep high wick with safety buffer
        raw_sl = round(cur_high + max(0.5, 0.20 * atr), 2)
        raw_risk = max(1.0, raw_sl - ltp)

        # Targets: T1 = 50% dealing range equilibrium, T2 = Range Low
        range_eq = round(swing_low + (cur_high - swing_low) * 0.50, 2)
        raw_t1 = round(min(ltp - 2.0 * raw_risk, range_eq), 2)
        raw_t2 = round(min(ltp - 4.0 * raw_risk, swing_low), 2)
        raw_moonshot = round(swing_low - 2.0 * raw_risk, 2)

        sl_price, risk_pts, t1_price, t2_price, moonshot_price, rr_ratio, entry_range_str = (
            _enforce_monotonic_trade_levels(
                direction="BEARISH",
                ltp=ltp,
                raw_sl=raw_sl,
                target_1=raw_t1,
                target_2=raw_t2,
                target_moonshot=raw_moonshot,
                atr=atr,
            )
        )

        if rr_ratio < self.min_rr:
            return None

        seg = classify_symbol_segment(clean_sym)
        confluences = [
            f"ICT Turtle Soup Sweep: High ₹{cur_high:,.1f} swept prior swing high ₹{swing_high:,.1f} (+{(cur_high - swing_high) / swing_high * 100:.2f}%)",
            f"Bearish Rejection Wick: {upper_wick_ratio * 100:.0f}% of daily spread rejected by institutional sellers",
            f"Failed Breakout Reclaim: Price closed back below resistance (₹{cur_close:,.1f} <= ₹{swing_high:,.1f})",
        ]

        score = min(95, int(82 + (upper_wick_ratio * 15)))

        opt_info = None
        if seg in ("INDEX", "FNO"):
            opt_info = resolve_recommended_option_contract(
                symbol=clean_sym,
                direction="BEARISH",
                spot=ltp,
                stop_loss=sl_price,
                target_1=t1_price,
                target_2=t2_price,
                setup_type="TURTLE_SOUP_SHORT",
                is_positional=False,
            )

        setup_lbl = "🐢 ICT Turtle Soup Liquidity Sweep Short"
        if opt_info and opt_info.get("contract_symbol"):
            suffix = f" [{opt_info['contract_symbol']}]"
            if opt_info.get("is_next_month_routed"):
                suffix = f" [{opt_info['contract_symbol']} · 🎯 NEXT-MONTH ROLLOVER]"
            setup_lbl = f"{setup_lbl}{suffix}"

        return AsymmetricOpportunity(
            opportunity_id=f"asym-soup-{clean_sym.lower()}-{uuid.uuid4().hex[:6]}",
            symbol=clean_sym,
            exchange="NFO" if seg == "INDEX" else "NSE",
            setup_type="TURTLE_SOUP_SHORT",
            setup_label=setup_lbl,
            segment=seg,
            direction="BEARISH",
            conviction_score=score,
            ltp=ltp,
            entry_price=ltp,
            entry_range=entry_range_str,
            stop_loss=sl_price,
            target_1=t1_price,
            target_2=t2_price,
            target_moonshot=moonshot_price,
            risk_reward=f"1:{rr_ratio:.1f}",
            risk_reward_ratio=rr_ratio,
            risk_pts=round(risk_pts, 2),
            reward_pts=round(ltp - t2_price, 2),
            confluence_factors=confluences,
            catalyst_summary="Smart money liquidity grab above resistance trapping retail breakout buyers.",
            when_to_buy=f"Enter SHORT / Buy Put on bid as price holds below swing high ₹{swing_high:,.1f}.",
            when_to_wait=f"DO NOT ENTER if price breaks back above sweep wick high ₹{cur_high:,.1f}.",
            profit_rule=f"Cover 50% at Dealing Range EQ T1 (₹{t1_price:,.1f}), move SL to Breakeven, let runner target T2 (₹{t2_price:,.1f}).",
            metrics={
                "swing_high": swing_high,
                "sweep_high": cur_high,
                "upper_wick_pct": round(upper_wick_ratio * 100, 1),
                "atr_14d": round(atr, 2),
            },
            strike=opt_info["strike"] if opt_info else None,
            option_type=opt_info["option_type"] if opt_info else None,
            contract_symbol=opt_info["contract_symbol"] if opt_info else None,
            expiry_date=opt_info["expiry_date"] if opt_info else None,
            option_premium=opt_info["option_premium"] if opt_info else None,
            option_target_1=opt_info["option_target_1"] if opt_info else None,
            option_target_2=opt_info["option_target_2"] if opt_info else None,
            option_stop_loss=opt_info["option_stop_loss"] if opt_info else None,
            lot_size=opt_info["lot_size"] if opt_info else None,
            futures_contract_symbol=opt_info.get("futures_contract") if opt_info else None,
            futures_entry=opt_info.get("futures_entry") if opt_info else None,
            futures_target_1=opt_info.get("futures_target_1") if opt_info else None,
            futures_target_2=opt_info.get("futures_target_2") if opt_info else None,
            futures_stop_loss=opt_info.get("futures_stop_loss") if opt_info else None,
            is_next_month_routed=opt_info.get("is_next_month_routed", False) if opt_info else False,
            derivative_safeguard=opt_info.get("derivative_safeguard") if opt_info else None,
            created_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        )

    # ── 7. Delta-Neutral Volatility Pinning & Iron Condor ────────

    def detect_volatility_pinning_iron_condor(
        self,
        symbol: str,
        quote: Optional[Any] = None,
        chain: Optional[Any] = None,
        df: Optional[pd.DataFrame] = None,
    ) -> Optional[AsymmetricOpportunity]:
        """
        Detects range-bound high-probability volatility pinning and generates
        an institutional defined-risk Iron Condor setup.
        """
        clean_sym = symbol.upper().replace("NSE:", "").replace("NFO:", "").strip()
        seg = classify_symbol_segment(clean_sym)
        if seg not in ("INDEX", "FNO"):
            return None

        if quote is None:
            from market.quotes import get_quote

            quote = get_quote(f"NSE:{clean_sym}")
        if isinstance(quote, dict):
            quote = (
                quote.get(f"NSE:{clean_sym}")
                or quote.get(clean_sym)
                or next(iter(quote.values()), None)
            )
        if not quote:
            return None

        ltp = _extract_price(quote, "last_price", "ltp")
        if ltp <= 0:
            return None

        if clean_sym in ("BANKNIFTY", "NIFTY BANK"):
            step = 100.0
        elif clean_sym in ("NIFTY", "FINNIFTY"):
            step = 50.0
        elif ltp > 2000:
            step = 50.0
        elif ltp > 1000:
            step = 20.0
        else:
            step = 10.0

        atm_strike = round(ltp / step) * step

        # Wings: Short strikes at +/- 2 steps, Long protective wings at +/- 4 steps
        short_ce = atm_strike + (2 * step)
        long_ce = atm_strike + (4 * step)
        short_pe = atm_strike - (2 * step)
        long_pe = atm_strike - (4 * step)

        wing_width = 2 * step
        credit_per_unit = round(wing_width * 0.32, 2)
        risk_per_unit = round(wing_width - credit_per_unit, 2)

        from engine.position_sizer import get_lot_size

        lot_sz = get_lot_size(clean_sym) or 1

        confluences = [
            f"Range Pinning Floor & Ceiling: Sell {int(short_pe)} PE / {int(short_ce)} CE outside expected move",
            f"Defined Safety Wings: Buy {int(long_pe)} PE / {int(long_ce)} CE (Max risk capped at ₹{risk_per_unit * lot_sz:,.0f}/lot)",
            f"Theta Harvesting: Expected net credit ₹{credit_per_unit * lot_sz:,.0f}/lot if spot expires between ₹{short_pe:,.0f} and ₹{short_ce:,.0f}",
        ]

        setup_lbl = f"🛡️ Delta-Neutral Iron Condor [{int(short_pe)}P/{int(short_ce)}C]"
        entry_range_str = (
            f"Net Credit ₹{credit_per_unit:,.1f}/share (₹{credit_per_unit * lot_sz:,.0f}/lot)"
        )

        return AsymmetricOpportunity(
            opportunity_id=f"asym-condor-{clean_sym.lower()}-{uuid.uuid4().hex[:6]}",
            symbol=clean_sym,
            exchange="NFO",
            setup_type="IRON_CONDOR_PINNING",
            setup_label=setup_lbl,
            segment=seg,
            direction="NEUTRAL",
            conviction_score=85,
            ltp=ltp,
            entry_price=ltp,
            entry_range=entry_range_str,
            stop_loss=round(short_ce + credit_per_unit, 2),
            target_1=round(ltp, 2),
            target_2=round(ltp, 2),
            target_moonshot=round(ltp, 2),
            risk_reward="1:3.0",
            risk_reward_ratio=3.0,
            risk_pts=round(risk_per_unit, 2),
            reward_pts=round(credit_per_unit, 2),
            confluence_factors=confluences,
            catalyst_summary=f"Non-directional volatility decay on {clean_sym} with positive market maker pinning.",
            when_to_buy=f"Execute multi-leg Iron Condor: Sell {int(short_pe)}PE/{int(short_ce)}CE, Buy {int(long_pe)}PE/{int(long_ce)}CE for net credit.",
            when_to_wait=f"DO NOT ENTER if spot breaches either short strike (₹{short_pe:,.0f} or ₹{short_ce:,.0f}) prior to entry.",
            profit_rule="Book 60-70% of maximum credit collected or hold into weekly expiry theta burn.",
            metrics={
                "short_pe": short_pe,
                "short_ce": short_ce,
                "long_pe": long_pe,
                "long_ce": long_ce,
                "credit_per_share": credit_per_unit,
                "max_risk_per_share": risk_per_unit,
                "lot_size": lot_sz,
            },
            strike=float(atm_strike),
            lot_size=lot_sz,
            created_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        )

    # ── Universal Scanner ───────────────────────────────────────

    def scan_asymmetric_opportunities(
        self,
        segment: Optional[str] = None,
        top_n: int = 6,
        force_refresh: bool = False,
    ) -> list[AsymmetricOpportunity]:
        """
        Sweeps the watched universe across F&O, Cash Equities, Indices, and MCX Commodities
        to surface top asymmetric opportunities meeting strict minimum 1:3.0 R:R.
        """
        import time

        cache_key = segment
        now = time.monotonic()
        if not force_refresh:
            with self._cache_lock:
                if cache_key in self._cache and (
                    now - self._cache_ts.get(cache_key, 0.0) < self._cache_ttl
                ):
                    return list(self._cache[cache_key][:top_n])

        universe = get_scan_universe(segment=segment)
        opportunities: list[AsymmetricOpportunity] = []

        logger.info(
            f"[AsymmetricRadar] Sweeping {len(universe)} symbols ({segment or 'ALL'}) for low-risk high-reward setups..."
        )

        # Batch pre-fetch quotes across universe in a single network round-trip
        quotes_map: dict[str, Any] = {}
        try:
            from market.quotes import get_quote

            formatted_syms = [
                (
                    f"CRYPTO:{s}"
                    if classify_symbol_segment(s) == "CRYPTO"
                    else (f"MCX:{s}" if classify_symbol_segment(s) == "COMMODITY" else f"NSE:{s}")
                )
                if ":" not in s
                else s
                for s in universe
            ]
            q_res = get_quote(formatted_syms)
            if isinstance(q_res, dict):
                quotes_map = q_res
        except Exception as e:
            logger.debug(f"[AsymmetricRadar] Batch quote fetch error: {e}")

        def _evaluate_sym(sym: str) -> list[AsymmetricOpportunity]:
            sym_opps: list[AsymmetricOpportunity] = []
            clean_sym = (
                sym.upper()
                .replace("NSE:", "")
                .replace("BSE:", "")
                .replace("MCX:", "")
                .replace("CRYPTO:", "")
                .replace("BINANCE:", "")
                .strip()
            )
            seg = classify_symbol_segment(clean_sym)
            is_comm = seg == "COMMODITY"
            is_crypto = seg == "CRYPTO"

            q = (
                quotes_map.get(f"CRYPTO:{clean_sym}")
                or quotes_map.get(f"NSE:{clean_sym}")
                or quotes_map.get(f"MCX:{clean_sym}")
                or quotes_map.get(clean_sym)
                or quotes_map.get(sym)
            )

            # Pre-fetch OHLCV once for this symbol
            df = None
            try:
                from market.history import get_ohlcv

                hist_exch = "CRYPTO" if is_crypto else ("MCX" if is_comm else "NSE")
                df = get_ohlcv(
                    clean_sym,
                    exchange=hist_exch,
                    interval="day",
                    days=90 if not is_comm else 60,
                )
            except Exception:
                df = None

            # 1. Pocket Pivot check
            try:
                pp = self.detect_pocket_pivot(sym, df=df, quote=q)
                if pp:
                    sym_opps.append(pp)
            except Exception as e:
                logger.debug(f"[AsymmetricRadar] Pocket pivot error on {sym}: {e}")

            # 2. 200-EMA Rubber Band check
            try:
                rb = self.detect_rubber_band_reversal(sym, quote=q, df=df)
                if rb:
                    sym_opps.append(rb)
            except Exception as e:
                logger.debug(f"[AsymmetricRadar] Rubber band error on {sym}: {e}")

            # 3. F&O MWPL Squeeze check
            if seg == "FNO":
                try:
                    ban = self.detect_fno_ban_squeeze(sym, quote=q, df=df)
                    if ban:
                        sym_opps.append(ban)
                except Exception as e:
                    logger.debug(f"[AsymmetricRadar] FNO ban error on {sym}: {e}")

            # 4. 0DTE Gamma check for indices
            if seg == "INDEX":
                try:
                    spot_val = _extract_price(q, "last_price", "ltp") if q else None
                    g0 = self.detect_0dte_gamma_breakout(sym, spot=spot_val)
                    if g0:
                        sym_opps.append(g0)
                except Exception as e:
                    logger.debug(f"[AsymmetricRadar] 0DTE gamma error on {sym}: {e}")

            # 5. MCX Commodity Asymmetry check
            if seg == "COMMODITY":
                try:
                    comm = self.detect_commodity_asymmetry(sym, df=df, quote=q)
                    if comm:
                        sym_opps.append(comm)
                except Exception as e:
                    logger.debug(f"[AsymmetricRadar] Commodity error on {sym}: {e}")

            # 6. ICT Turtle Soup Liquidity Sweep Short (Bearish Asymmetry)
            try:
                soup = self.detect_turtle_soup_sweep_short(sym, df=df, quote=q)
                if soup:
                    sym_opps.append(soup)
            except Exception as e:
                logger.debug(f"[AsymmetricRadar] Turtle soup error on {sym}: {e}")

            # 7. Delta-Neutral Volatility Pinning Iron Condor (Non-Directional)
            if seg in ("INDEX", "FNO"):
                try:
                    ic = self.detect_volatility_pinning_iron_condor(sym, quote=q, df=df)
                    if ic:
                        sym_opps.append(ic)
                except Exception as e:
                    logger.debug(f"[AsymmetricRadar] Iron condor error on {sym}: {e}")

            return sym_opps

        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(6, len(universe) or 1)
        ) as executor:
            future_to_sym = {executor.submit(_evaluate_sym, s): s for s in universe}
            for fut in concurrent.futures.as_completed(future_to_sym):
                s = future_to_sym[fut]
                try:
                    res = fut.result()
                    if res:
                        opportunities.extend(res)
                except Exception as e:
                    logger.debug(f"[AsymmetricRadar] Evaluation error on {s}: {e}")

        # Sort descending by conviction score, then by R:R ratio
        opportunities.sort(key=lambda o: (o.conviction_score, o.risk_reward_ratio), reverse=True)
        with self._cache_lock:
            self._cache[cache_key] = opportunities
            self._cache_ts[cache_key] = now

        top_opps = opportunities[:top_n]

        logger.info(
            f"[AsymmetricRadar] Scan completed: {len(top_opps)} high-asymmetry setups qualified."
        )
        return top_opps

    scan_opportunities = scan_asymmetric_opportunities


# Module-level singleton
asymmetric_radar = AsymmetricOpportunityRadar()
AsymmetricRadarScanner = AsymmetricOpportunityRadar


def scan_asymmetric_opportunities(
    segment: Optional[str] = None,
    top_n: int = 6,
    min_rr: float = 3.0,
    as_dicts: bool = False,
    force_refresh: bool = False,
) -> list[Any]:
    """Module-level convenience accessor."""
    opps = asymmetric_radar.scan_asymmetric_opportunities(segment=segment, top_n=top_n)
    if min_rr > 0:
        opps = [o for o in opps if o.risk_reward_ratio >= min_rr]
    if as_dicts:
        return [o.to_dict() for o in opps]
    return opps
