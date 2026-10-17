"""
engine/synthetic_sl.py
──────────────────────
Institutional Synthetic Spot-Anchored Stop Loss Engine.

Protects Index and Stock F&O derivative trades from:
  1. Freak Option Spikes & Level 2 Order Book Vacuums:
     Sudden 200-400ms illiquid option contract wicks that dip below nominal
     option stop levels while the underlying spot index/stock remains completely
     healthy and holds above its structural support/resistance.
  2. Sub-Bar False Whipsaws:
     Prevents premature stop-outs by verifying that the underlying spot thesis
     anchor is genuinely breached on a structural level rather than an isolated
     derivative premium anomaly.
  3. Decisive Spot-Breach Invalidation:
     If the underlying spot price genuinely violates the structural thesis level
     (e.g., Bank Nifty breaks below PDL or demand order block), invalidates the
     trade immediately to prevent catastrophic Vega/Delta losses even if the
     option premium is temporarily suspended by inflated IV.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from engine.alert_identity import canonical_alert_symbol

logger = logging.getLogger("chanakya.engine.synthetic_sl")

# Benchmark Index roots recognized in Indian derivative markets
INDEX_ROOTS = ("BANKNIFTY", "MIDCPNIFTY", "FINNIFTY", "SENSEX", "BANKEX", "NIFTY")


@dataclass
class SyntheticSLEvaluation:
    """Result of synthetic spot-anchored stop loss analysis."""

    is_invalidated: bool
    rejection_reason: Optional[str]
    is_freak_wick_shielded: bool
    shield_reason: Optional[str]
    live_spot: float
    spot_anchor: float
    spot_distance_pct: float
    option_drawdown_pct: float
    underlying_symbol: str


def _safe_get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def extract_underlying_symbol(alert: Any) -> str:
    """
    Extracts canonical underlying symbol (e.g. 'NIFTY', 'BANKNIFTY', 'RELIANCE')
    from an AutoAlert, contract symbol, or dictionary payload safely.
    """
    # 1. Direct explicit property
    und = _safe_get(alert, "underlying_symbol")
    if und:
        return canonical_alert_symbol(str(und))

    # 2. Check metrics / actionable_plan
    metrics = _safe_get(alert, "metrics") or {}
    if isinstance(metrics, dict) and metrics.get("underlying_symbol"):
        return canonical_alert_symbol(str(metrics["underlying_symbol"]))

    act_plan = _safe_get(alert, "actionable_plan") or {}
    if isinstance(act_plan, dict) and act_plan.get("underlying_symbol"):
        return canonical_alert_symbol(str(act_plan["underlying_symbol"]))

    # 3. Canonical symbol from alert.symbol or contract_symbol
    raw_sym = str(_safe_get(alert, "symbol") or "")
    clean = canonical_alert_symbol(raw_sym) if raw_sym else ""

    # Check if clean is an index or starts with index root (e.g. BANKNIFTY26SEP56000CE)
    for root in INDEX_ROOTS:
        if clean == root or (clean and clean.startswith(root)):
            return root

    # Check contract_symbol (e.g. RELIANCE26OCT2800CE)
    c_sym = str(_safe_get(alert, "contract_symbol") or "")
    if c_sym:
        clean_c = canonical_alert_symbol(c_sym)
        for root in INDEX_ROOTS:
            if clean_c == root or clean_c.startswith(root):
                return root
        # Extract stock ticker from standard Indian derivative contract format
        import re

        m_stock = re.match(r"^([A-Z0-9_\-]+?)\d{2}[A-Z]{3}", clean_c)
        if m_stock:
            return m_stock.group(1)

    # Fallback to cleaned alert symbol
    if clean:
        parts = clean.split()
        if parts:
            return parts[0].replace(".NS", "").replace(".BO", "")
    return ""


def extract_spot_invalidation_anchor(alert: Any) -> Optional[float]:
    """
    Extracts the underlying structural stop-loss level (spot invalidation anchor)
    across all standard alert payload locations, trade plans, and sniper plans.
    Guarantees the returned anchor is in underlying spot domain, never an option premium.
    """
    import re

    def _parse_float(val: Any) -> Optional[float]:
        if val is None:
            return None
        try:
            if isinstance(val, (int, float)):
                f = float(val)
                return f if f > 0 else None
            m = re.findall(r"[\d.]+", str(val).replace(",", ""))
            if m and float(m[0]) > 0:
                return float(m[0])
        except (ValueError, TypeError) as e_suppressed:
            logger.debug(f"[engine.synthetic_sl] Non-fatal exception suppressed: {e_suppressed}")
        return None

    metrics = _safe_get(alert, "metrics") or {}
    act_plan = _safe_get(alert, "actionable_plan") or {}

    spot_val = _parse_float(
        _safe_get(alert, "underlying_spot")
        or (metrics.get("spot") if isinstance(metrics, dict) else None)
        or (metrics.get("underlying_spot") if isinstance(metrics, dict) else None)
        or (act_plan.get("underlying_spot") if isinstance(act_plan, dict) else None)
    )

    def _is_valid_spot_anchor(val: Optional[float]) -> bool:
        if not val or val <= 0:
            return False
        # If reference spot is known, the anchor MUST be within 25% of spot (structural pivot domain),
        # not a fractional derivative option premium (e.g. 5.06 vs spot 193.7).
        if spot_val and spot_val > 0:
            return (abs(val - spot_val) / spot_val) <= 0.25
        return True

    # 1. Direct attributes
    for key in (
        "underlying_sl",
        "structural_spot_sl",
        "spot_anchor",
        "spot_invalidation_anchor",
        "spot_invalidation",
    ):
        v = _parse_float(_safe_get(alert, key))
        if _is_valid_spot_anchor(v):
            return v

    # 2. Check nested trade_plan, sniper_plan, option_plan (primary institutional spot homes)
    if isinstance(act_plan, dict):
        tp = act_plan.get("trade_plan") or {}
        if isinstance(tp, dict):
            for key in ("invalidation_stop", "underlying_sl", "stop_loss", "structural_spot_sl"):
                v = _parse_float(tp.get(key))
                if _is_valid_spot_anchor(v):
                    return v

        sp = act_plan.get("sniper_plan") or {}
        if isinstance(sp, dict):
            for key in ("structural_invalidation", "invalidation_stop", "underlying_sl"):
                v = _parse_float(sp.get(key))
                if _is_valid_spot_anchor(v):
                    return v

        op = act_plan.get("option_plan") or {}
        if isinstance(op, dict):
            for key in ("underlying_sl", "structural_spot_sl", "spot_anchor"):
                v = _parse_float(op.get(key))
                if _is_valid_spot_anchor(v):
                    return v

        for key in (
            "underlying_sl",
            "structural_spot_sl",
            "spot_sl",
            "invalidation_sl",
            "spot_invalidation_anchor",
        ):
            v = _parse_float(act_plan.get(key))
            if _is_valid_spot_anchor(v):
                return v

    # 3. Metrics dictionary
    if isinstance(metrics, dict):
        for key in (
            "spot_invalidation_anchor",
            "underlying_sl",
            "structural_spot_sl",
            "spot_anchor",
            "spot_invalidation",
            "underlying_stop_loss",
            "invalidation_level",
        ):
            v = _parse_float(metrics.get(key))
            if _is_valid_spot_anchor(v):
                return v

    # 4. Fallback: derive structural spot anchor from spot_val, trigger/SL and delta if available
    if spot_val and spot_val > 0:
        trigger_level = _parse_float(
            _safe_get(alert, "trigger_level")
            or _safe_get(alert, "option_premium")
            or _safe_get(alert, "entry")
            or (act_plan.get("entry") if isinstance(act_plan, dict) else None)
        )
        stop_loss = _parse_float(
            _safe_get(alert, "stop_loss")
            or (act_plan.get("stop_loss") if isinstance(act_plan, dict) else None)
        )
        if trigger_level and stop_loss and trigger_level > 0 and stop_loss > 0:
            delta = _parse_float(
                metrics.get("delta") if isinstance(metrics, dict) else None
            ) or _parse_float(_safe_get(alert, "delta"))
            if delta and delta > 0.05 and delta <= 1.0:
                opt_risk = abs(trigger_level - stop_loss)
                if opt_risk > 0:
                    direction = str(_safe_get(alert, "direction") or "").upper()
                    option_type = str(_safe_get(alert, "option_type") or "").upper()
                    c_sym = str(_safe_get(alert, "contract_symbol") or "").upper()
                    is_pe = (
                        direction in ("BEARISH", "SHORT", "SELL")
                        or option_type == "PE"
                        or c_sym.endswith("PE")
                    )
                    derived_anchor = (
                        round(spot_val + (opt_risk / delta), 2)
                        if is_pe
                        else round(spot_val - (opt_risk / delta), 2)
                    )
                    if _is_valid_spot_anchor(derived_anchor):
                        return derived_anchor

    # Fallback to any direct anchor if no spot_val was available for validation
    for key in ("invalidation_level", "initial_invalidation_stop"):
        v = _parse_float(
            _safe_get(alert, key) or (act_plan.get(key) if isinstance(act_plan, dict) else None)
        )
        if _is_valid_spot_anchor(v):
            return v

    return None


def fetch_live_underlying_spot(underlying_symbol: str) -> Optional[float]:
    """
    Fetches the real-time spot price of the underlying index or equity.
    """
    if not underlying_symbol:
        return None

    clean = canonical_alert_symbol(underlying_symbol)
    try:
        from market.quotes import get_ltp, get_quote

        # For benchmark indices, query canonical instrument
        is_bse = clean in ("SENSEX", "BANKEX")
        exch = "BSE" if is_bse else "NSE"
        inst = f"{exch}:{clean}"

        q = get_ltp(inst)
        if q and q > 0:
            return float(q)

        q_alt = get_ltp(clean)
        if q_alt and q_alt > 0:
            return float(q_alt)

        # Fallback to get_quote
        quotes = get_quote([inst])
        q_obj = quotes.get(inst) or quotes.get(clean)
        if q_obj:
            p = (
                getattr(q_obj, "last_price", 0.0)
                or getattr(q_obj, "price", 0.0)
                or getattr(q_obj, "ltp", 0.0)
            )
            if float(p) > 0:
                return float(p)
    except Exception as e:
        logger.debug(f"[SyntheticSL] Failed fetching live spot for {underlying_symbol}: {e}")

    return None


def extract_dte(alert: Any) -> Optional[int]:
    """Extracts Days to Expiry (DTE) from alert metadata or calculates from expiry date."""
    metrics = _safe_get(alert, "metrics", {}) or {}
    if isinstance(metrics, dict) and "dte" in metrics and metrics["dte"] is not None:
        try:
            return int(metrics["dte"])
        except (ValueError, TypeError) as e_suppressed:
            logger.debug(f"[engine.synthetic_sl] Non-fatal exception suppressed: {e_suppressed}")
    if hasattr(alert, "dte") and getattr(alert, "dte") is not None:
        try:
            return int(getattr(alert, "dte"))
        except (ValueError, TypeError) as e_suppressed:
            logger.debug(f"[engine.synthetic_sl] Non-fatal exception suppressed: {e_suppressed}")
    exp_details = _safe_get(alert, "expiry_details", {}) or {}
    if isinstance(exp_details, dict) and exp_details.get("dte") is not None:
        try:
            return int(exp_details["dte"])
        except (ValueError, TypeError) as e_suppressed:
            logger.debug(f"[engine.synthetic_sl] Non-fatal exception suppressed: {e_suppressed}")
    exp_date = _safe_get(alert, "expiry_date", "") or ""
    if exp_date:
        try:
            from datetime import datetime
            from config.constants import IST_ZONE as IST

            exp_clean = str(exp_date).strip()[:10]
            for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
                try:
                    exp_dt = datetime.strptime(exp_clean, fmt).date()
                    ref_dt_str = (
                        _safe_get(alert, "triggered_at") or _safe_get(alert, "created_at") or ""
                    )
                    ref_date = None
                    if ref_dt_str and len(str(ref_dt_str).strip()) >= 10:
                        try:
                            ref_date = datetime.strptime(
                                str(ref_dt_str).strip()[:10], "%Y-%m-%d"
                            ).date()
                        except Exception as e_suppressed:
                            logger.debug(
                                f"[engine.synthetic_sl] Non-fatal exception suppressed: {e_suppressed}"
                            )
                    now_date = ref_date or datetime.now(IST).date()
                    return max(0, (exp_dt - now_date).days)
                except ValueError:
                    continue
        except Exception as e_suppressed:
            logger.debug(f"[engine.synthetic_sl] Non-fatal exception suppressed: {e_suppressed}")
    return None


def evaluate_synthetic_spot_sl(
    alert: Any,
    current_option_ltp: float,
    current_spot_override: Optional[float] = None,
) -> SyntheticSLEvaluation:
    """
    Evaluates synthetic spot-anchored stop loss for option setups.

    Decision Matrix:
      1. SPOT BREACHED:
         If live spot breaches the thesis anchor (with a 0.05% noise tolerance),
         return is_invalidated=True. Real structural failure.
      2. 0-DTE / DE-RISKED BREAKEVEN PROTECTION:
         - On 0-DTE expiry contracts, theta decay is irreversible: freak wick shielding
           is strictly capped at 18% drawdown; if nominal SL is breached, exit immediately.
         - On de-risked trades (T0.5 / T1 / Breakeven locked), ratcheted stop protects
           against round-tripping profit into a loss.
      3. FREAK OPTION WICK (SPOT INTACT):
         If option premium dropped below nominal SL on standard multi-day options, but live spot
         is still holding its structural level and option drawdown is within survivable bounds,
         shield the position (is_invalidated=False, is_freak_wick_shielded=True).
      4. CATASTROPHIC OPTION DRAWDOWN:
         If option premium collapsed beyond maximum risk threshold, invalidate even if spot is
         barely holding to prevent total premium wipeout.
    """
    und_sym = extract_underlying_symbol(alert)
    spot_anchor = extract_spot_invalidation_anchor(alert)

    # Determine live underlying spot
    live_spot = 0.0
    if current_spot_override and current_spot_override > 0:
        live_spot = float(current_spot_override)
    else:
        fetched_spot = fetch_live_underlying_spot(und_sym)
        if fetched_spot and fetched_spot > 0:
            live_spot = fetched_spot
        else:
            live_spot = float(
                _safe_get(alert, "underlying_spot", 0.0)
                or (_safe_get(alert, "metrics", {}) or {}).get("spot", 0.0)
                or (_safe_get(alert, "metrics", {}) or {}).get("underlying_spot", 0.0)
                or (_safe_get(alert, "actionable_plan", {}) or {}).get("underlying_spot", 0.0)
                or 0.0
            )

    # Determine option entry price
    opt_entry = float(
        _safe_get(alert, "option_premium", 0.0)
        or _safe_get(alert, "trigger_level", 0.0)
        or (_safe_get(alert, "metrics", {}) or {}).get("option_entry_premium", 0.0)
        or (_safe_get(alert, "actionable_plan", {}) or {}).get("entry_price", 0.0)
        or _safe_get(alert, "ltp", 0.0)
        or 0.0
    )

    opt_drawdown = 0.0
    if opt_entry > 0 and current_option_ltp > 0:
        opt_drawdown = max(0.0, (opt_entry - current_option_ltp) / opt_entry)

    # If spot anchor is missing, cannot perform synthetic spot analysis
    if not spot_anchor or spot_anchor <= 0 or live_spot <= 0:
        return SyntheticSLEvaluation(
            is_invalidated=False,
            rejection_reason=None,
            is_freak_wick_shielded=False,
            shield_reason=None,
            live_spot=live_spot,
            spot_anchor=spot_anchor or 0.0,
            spot_distance_pct=0.0,
            option_drawdown_pct=round(opt_drawdown * 100.0, 2),
            underlying_symbol=und_sym,
        )

    # Determine trade direction
    direction = str(_safe_get(alert, "direction", "BULLISH") or "BULLISH").upper()
    opt_type = str(_safe_get(alert, "option_type", "") or "").upper()
    is_bullish = (opt_type == "CE") or (direction in ("BULLISH", "BUY", "LONG"))

    # Noise buffer: 0.05% on spot to filter single tick noise
    noise_buffer = spot_anchor * 0.0005

    if is_bullish:
        # Bullish (Call / Long): Spot support is below entry.
        # Breached if live_spot drops below (spot_anchor - noise_buffer)
        spot_distance_pct = ((live_spot - spot_anchor) / spot_anchor) * 100.0
        spot_is_holding = live_spot >= (spot_anchor - noise_buffer)
        spot_breached = live_spot < (spot_anchor - noise_buffer)
    else:
        # Bearish (Put / Short): Spot resistance is above entry.
        # Breached if live_spot rallies above (spot_anchor + noise_buffer)
        spot_distance_pct = ((spot_anchor - live_spot) / spot_anchor) * 100.0
        spot_is_holding = live_spot <= (spot_anchor + noise_buffer)
        spot_breached = live_spot > (spot_anchor + noise_buffer)

    # Nominal option stop loss level
    nominal_sl = float(_safe_get(alert, "stop_loss", 0.0) or 0.0)
    option_sl_hit = (nominal_sl > 0) and (current_option_ltp < nominal_sl)

    # Case 1: Spot genuinely breached thesis anchor
    if spot_breached:
        breach_desc = "below support" if is_bullish else "above resistance"
        reason = (
            f"Underlying {und_sym} spot breached thesis invalidation anchor {breach_desc} "
            f"(Live ₹{live_spot:,.1f} vs SL ₹{spot_anchor:,.1f}, {spot_distance_pct:+.2f}%). "
            f"Structural thesis failed."
        )
        logger.info(
            f"[SyntheticSL] Decisive spot invalidation for {_safe_get(alert, 'symbol')}: {reason}"
        )
        return SyntheticSLEvaluation(
            is_invalidated=True,
            rejection_reason=reason,
            is_freak_wick_shielded=False,
            shield_reason=None,
            live_spot=live_spot,
            spot_anchor=spot_anchor,
            spot_distance_pct=round(spot_distance_pct, 2),
            option_drawdown_pct=round(opt_drawdown * 100.0, 2),
            underlying_symbol=und_sym,
        )

    # Determine DTE & 0-DTE status
    dte = extract_dte(alert)
    is_0dte = (dte == 0) if dte is not None else False

    # Determine whether position has achieved profit milestones / de-risked
    achieved_m = getattr(alert, "achieved_milestones", None) or []
    curr_stage = str(_safe_get(alert, "stage", "") or "").upper()
    curr_target_status = str(_safe_get(alert, "target_status", "") or "").upper()
    has_derisked = (
        any(
            m in achieved_m
            for m in (
                "T0_5_ACHIEVED",
                "DE_RISK_0_5R",
                "BREAKEVEN_LOCKED",
                "T1_ACHIEVED",
                "TARGET_ACHIEVED",
                "RUNNER",
                "RUNNER_EXIT",
            )
        )
        or curr_stage
        in (
            "T0_5_ACHIEVED",
            "DE_RISK_0_5R",
            "BREAKEVEN_LOCKED",
            "T1_ACHIEVED",
            "TRAILING_UPDATE",
            "RUNNER_EXIT",
        )
        or curr_target_status in ("T0_5_ACHIEVED", "T1_ACHIEVED", "TARGET_ACHIEVED")
    )

    # Dynamic survivable drawdown floor:
    # 1. 0-DTE Expiry Day: Rapid gamma and theta decay mean an option cannot absorb deep dips.
    #    Cap max tolerable drawdown at 18% (or 0.85x designed risk).
    # 2. De-risked position (T0.5 / T1 banked): Cannot be allowed to round-trip into loss.
    #    Cap at 5% below entry (scratch/breakeven tolerance).
    # 3. Normal multi-day swing/monthly option: defaults to 32%, up to 42% for wide setups.
    designed_risk_ratio = (
        ((opt_entry - nominal_sl) / opt_entry) if (opt_entry > nominal_sl > 0) else 0.25
    )
    if is_0dte:
        catastrophic_dd_threshold = min(0.18, max(0.12, designed_risk_ratio * 0.85))
    elif has_derisked:
        catastrophic_dd_threshold = 0.05
    else:
        catastrophic_dd_threshold = max(0.32, min(0.42, designed_risk_ratio * 1.25))

    # Case 2: De-risked / Breakeven Gate (Enforced regardless of nominal SL)
    if has_derisked and opt_entry > 0 and current_option_ltp < (opt_entry * 0.98):
        reason = (
            f"Breakeven Protection Triggered: De-risked trade fell below entry "
            f"(Option LTP ₹{current_option_ltp:.1f} < Entry ₹{opt_entry:.1f}, Drawdown -{opt_drawdown * 100:.1f}%). "
            f"Ratcheted breakeven stop enforced to prevent profitable setup from decaying into loss."
        )
        logger.info(f"[SyntheticSL] {reason}")
        return SyntheticSLEvaluation(
            is_invalidated=True,
            rejection_reason=reason,
            is_freak_wick_shielded=False,
            shield_reason=None,
            live_spot=live_spot,
            spot_anchor=spot_anchor,
            spot_distance_pct=round(spot_distance_pct, 2),
            option_drawdown_pct=round(opt_drawdown * 100.0, 2),
            underlying_symbol=und_sym,
        )

    # Case 3: Catastrophic Option Drawdown (Excessive premium destruction)
    if opt_drawdown >= catastrophic_dd_threshold and opt_drawdown > 0:
        is_0dte_risk = is_0dte and (option_sl_hit or opt_drawdown >= 0.18)
        if is_0dte_risk:
            reason = (
                f"0-DTE Theta Invalidation: Option premium collapsed "
                f"(Option LTP ₹{current_option_ltp:.1f}, Drawdown -{opt_drawdown * 100:.1f}% >= {catastrophic_dd_threshold * 100:.0f}%). "
                f"0-DTE theta decay and gamma risk strictly prohibit synthetic spot shielding."
            )
        else:
            reason = (
                f"Option premium suffered deep catastrophic drawdown (-{opt_drawdown * 100:.1f}%), "
                f"exceeding {catastrophic_dd_threshold * 100:.0f}% risk floor (LTP ₹{current_option_ltp:.1f} vs Entry ₹{opt_entry:.1f}). "
                f"Position halted to protect capital."
            )
        logger.info(f"[SyntheticSL] {reason}")
        return SyntheticSLEvaluation(
            is_invalidated=True,
            rejection_reason=reason,
            is_freak_wick_shielded=False,
            shield_reason=None,
            live_spot=live_spot,
            spot_anchor=spot_anchor,
            spot_distance_pct=round(spot_distance_pct, 2),
            option_drawdown_pct=round(opt_drawdown * 100.0, 2),
            underlying_symbol=und_sym,
        )

    # Case 4: Nominal Option SL Hit while spot is holding
    if option_sl_hit and spot_is_holding:
        # Strict 0-DTE Gate: If nominal SL is breached on 0-DTE, even if drawdown is below threshold,
        # any drop > 3% below nominal SL fails closed immediately
        if is_0dte and (current_option_ltp < (nominal_sl * 0.97) or opt_drawdown >= 0.18):
            reason = (
                f"0-DTE Theta Invalidation: Option premium collapsed below nominal SL "
                f"(Option LTP ₹{current_option_ltp:.1f} < SL ₹{nominal_sl:.1f}, Drawdown -{opt_drawdown * 100:.1f}%). "
                f"0-DTE theta decay and gamma risk strictly prohibit synthetic spot shielding."
            )
            logger.info(f"[SyntheticSL] {reason}")
            return SyntheticSLEvaluation(
                is_invalidated=True,
                rejection_reason=reason,
                is_freak_wick_shielded=False,
                shield_reason=None,
                live_spot=live_spot,
                spot_anchor=spot_anchor,
                spot_distance_pct=round(spot_distance_pct, 2),
                option_drawdown_pct=round(opt_drawdown * 100.0, 2),
                underlying_symbol=und_sym,
            )

        # Standard Multi-day Option Freak Wick Shielding
        shield_msg = (
            f"Synthetic Spot Guard: Shielded {und_sym} from momentary option premium freak dip "
            f"(Option LTP ₹{current_option_ltp:.1f} < SL ₹{nominal_sl:.1f}, Drawdown -{opt_drawdown * 100:.1f}%). "
            f"Underlying spot is completely intact at ₹{live_spot:,.1f} ({spot_distance_pct:+.2f}% headroom above ₹{spot_anchor:,.1f})."
        )
        logger.info(f"[SyntheticSL] {shield_msg}")
        return SyntheticSLEvaluation(
            is_invalidated=False,
            rejection_reason=None,
            is_freak_wick_shielded=True,
            shield_reason=shield_msg,
            live_spot=live_spot,
            spot_anchor=spot_anchor,
            spot_distance_pct=round(spot_distance_pct, 2),
            option_drawdown_pct=round(opt_drawdown * 100.0, 2),
            underlying_symbol=und_sym,
        )

    # Normal holding
    return SyntheticSLEvaluation(
        is_invalidated=False,
        rejection_reason=None,
        is_freak_wick_shielded=False,
        shield_reason=None,
        live_spot=live_spot,
        spot_anchor=spot_anchor,
        spot_distance_pct=round(spot_distance_pct, 2),
        option_drawdown_pct=round(opt_drawdown * 100.0, 2),
        underlying_symbol=und_sym,
    )
