"""
Alert target milestone tracking, invalidation evaluation, and decisive trailing stop calculation.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from engine.alert_expiry import is_alert_option_premium_level
from engine.alert_model import INDEX_WEEKLY_EXPIRY_WEEKDAY

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))


def evaluate_alert_invalidation(
    alert: Any,
    current_ltp: Optional[float] = None,
    current_vwap: Optional[float] = None,
) -> Optional[str]:
    """
    Evaluates if an active AutoAlert has become invalidated.
    Returns the specific invalidation reason string if invalidated, or None if still valid.
    """
    if getattr(alert, "is_invalidated", False) or getattr(alert, "stage", "") == "INVALIDATED":
        return None

    exch = (getattr(alert, "exchange", "NSE") or "NSE").upper()

    # 0. Session Cutoff & Time-Stop Horizon Invalidation
    is_test_runner = (
        (getattr(alert, "environment", "LIVE") == "TEST")
        or (not getattr(alert, "is_live", True))
        or (os.environ.get("CHANAKYA_TESTING") == "1")
        or (os.environ.get("DEPLOY_MODE") == "test")
        or ("PYTEST_CURRENT_TEST" in os.environ)
    ) and not getattr(alert, "_force_test_expiry", False)

    created_str = getattr(alert, "created_at", "")
    created_dt = None
    if created_str:
        clean_ts = created_str.replace(" IST", "").strip()[:19]
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                created_dt = datetime.strptime(clean_ts, fmt).replace(tzinfo=IST)
                break
            except ValueError:
                pass

    if not is_test_runner and created_dt:
        now_ist = datetime.now(IST)
        th = (getattr(alert, "time_horizon", "INTRADAY") or "INTRADAY").upper()

        # 0a. Hard Intraday Cutoff (15:15 IST NSE/BSE/NFO, 23:15 IST MCX; Crypto is 24x7 rolling)
        if th == "INTRADAY" and not getattr(alert, "expiry_date", None):
            exch = (getattr(alert, "exchange", "NSE") or "NSE").upper()
            cutoff_reached = False
            if exch in ("CRYPTO", "BINANCE", "DERIBIT"):
                # Crypto is 24x7; intraday alerts have a 24-hour rolling expiry window
                elapsed_sec = (now_ist - created_dt).total_seconds()
                if elapsed_sec >= 86400:
                    return "24x7 Crypto session expired (24h rolling limit reached). Trade closed."
            elif created_dt.date() < now_ist.date():
                cutoff_reached = True
            elif exch == "MCX":
                cutoff_reached = now_ist.hour > 23 or (now_ist.hour == 23 and now_ist.minute >= 15)
            else:
                cutoff_reached = now_ist.hour > 15 or (now_ist.hour == 15 and now_ist.minute >= 15)
            if cutoff_reached:
                cutoff_time = "23:15" if exch == "MCX" else "15:15"
                return f"Intraday session expired ({cutoff_time} IST cutoff reached). Trade closed."

        # 0b. Time-Stop for unignited EARLY_WARNING setups (default 60 mins for intraday)
        if getattr(alert, "stage", "") == "EARLY_WARNING":
            elapsed_sec = (now_ist - created_dt).total_seconds()
            ttl_sec = getattr(alert, "ttl_seconds", None) or (3600 if th == "INTRADAY" else 86400 * 5)
            if elapsed_sec >= ttl_sec:
                mins = int(ttl_sec / 60)
                return f"Time-Stop expired: Setup did not trigger within {mins}-minute momentum window."

    is_option = is_alert_option_premium_level(alert)

    session_low: Optional[float] = None
    session_high: Optional[float] = None

    # Determine current LTP if not provided
    if current_ltp is None or current_ltp <= 0:
        lookup_sym = ""
        try:
            from market.quotes import get_quote, get_ltp

            if is_option:
                lookup_sym = getattr(alert, "contract_symbol", None) or (
                    f"{alert.exchange}:{alert.symbol}" if ":" not in alert.symbol else alert.symbol
                )
            else:
                lookup_sym = (
                    f"{alert.exchange}:{alert.symbol}" if ":" not in alert.symbol else alert.symbol
                )
            q = get_quote(lookup_sym)
            q_obj = q.get(lookup_sym) or (list(q.values())[0] if q else None)
            if q_obj:
                current_ltp = getattr(q_obj, "last_price", None) or getattr(q_obj, "price", None)
                session_low = getattr(q_obj, "low", None)
                session_high = getattr(q_obj, "high", None)
            else:
                current_ltp = get_ltp(lookup_sym)
        except Exception:
            try:
                from market.quotes import get_ltp
                current_ltp = get_ltp(lookup_sym) if lookup_sym else None
            except Exception:
                current_ltp = None

    if current_ltp is None or current_ltp <= 0:
        return None  # Cannot evaluate without live price quote

    # 1. Stop-Loss Invalidation
    if alert.stop_loss and alert.stop_loss > 0:
        if is_option:
            # Check if option writing / selling position:
            act = str((alert.actionable_plan or {}).get("action", "")).upper()
            is_option_sell = act in ("SELL", "WRITE", "SHORT")
            if not is_option_sell and alert.stop_loss > 0 and alert.target_level > 0:
                ref_entry = alert.option_premium or alert.ltp
                if ref_entry and alert.stop_loss > ref_entry and alert.target_level < ref_entry:
                    is_option_sell = True

            if is_option_sell:
                # Option writing / selling (Short CE / Short PE):
                # Stop-loss is above entry. Breached IF AND ONLY IF premium surges above SL + noise margin.
                opt_noise_margin = (
                    max(0.10, min(1.0, alert.stop_loss * 0.025)) if alert.stop_loss > 0 else 0.10
                )
                if current_ltp > (alert.stop_loss + opt_noise_margin):
                    opt_desc = (
                        "Call"
                        if (alert.option_type == "CE" or alert.direction == "BULLISH")
                        else "Put"
                    )
                    return (
                        f"Option premium surged to ₹{current_ltp:.1f} "
                        f"(breached stop-loss ₹{alert.stop_loss:.1f}). {opt_desc} writing thesis invalidated."
                    )
            else:
                # Option buying (Long CE / Long PE):
                # The stop-loss on the option premium is breached IF AND ONLY IF premium drops below SL - noise margin.
                opt_noise_margin = (
                    max(0.10, min(1.0, alert.stop_loss * 0.025)) if alert.stop_loss > 0 else 0.10
                )
                if current_ltp < (alert.stop_loss - opt_noise_margin):
                    # Dual Validation Guard against Noise & Spread Whipsaws:
                    # If underlying spot support is known (e.g. spot_invalidation_anchor) and underlying
                    # spot price is still holding above support (for CE) or below support (for PE),
                    # suppress premature invalidation unless option drawdown has genuinely breached the -28% risk floor.
                    metrics_dict = alert.metrics if isinstance(alert.metrics, dict) else {}
                    spot_anchor = metrics_dict.get("spot_invalidation_anchor")
                    underlying_spot = alert.underlying_spot or metrics_dict.get("spot")
                    opt_entry = alert.option_premium or alert.trigger_level or 0.0

                    if spot_anchor and underlying_spot and opt_entry > 0:
                        is_ce = (alert.option_type == "CE" or alert.direction == "BULLISH")
                        spot_holding = (underlying_spot >= spot_anchor) if is_ce else (underlying_spot <= spot_anchor)
                        opt_drawdown = (opt_entry - current_ltp) / opt_entry if opt_entry > 0 else 0.0
                        if spot_holding and opt_drawdown < 0.28:
                            # Underlying structure is completely intact! Suppress premature stop-out.
                            return None

                    opt_desc = (
                        "Call"
                        if (alert.option_type == "CE" or alert.direction == "BULLISH")
                        else "Put"
                    )
                    return (
                        f"Option premium collapsed to ₹{current_ltp:.1f} "
                        f"(breached stop-loss ₹{alert.stop_loss:.1f}). {opt_desc} gamma thesis invalidated."
                    )
        else:
            # Non-option instruments (Equities / Futures / Crypto)
            curr_sym = "$" if exch in ("CRYPTO", "BINANCE", "DERIBIT") else "₹"
            if exch in ("CRYPTO", "BINANCE", "DERIBIT"):
                # Tight, institutional noise margin for crypto assets
                vol_noise_margin = (
                    max(0.01, min(1.0, alert.stop_loss * 0.0001))
                    if alert.stop_loss > 0
                    else 0.01
                )
            else:
                # Dynamic Volatility Noise Margin (0.15x ATR or 0.25% floor)
                # Prevents premature panic invalidations on single-tick 10-paise / sub-cent micro-chop.
                atr_val = 0.0
                if alert.metrics and isinstance(alert.metrics, dict):
                    atr_val = float(alert.metrics.get("atr_14d") or alert.metrics.get("atr") or 0.0)
                if atr_val <= 0 and alert.stop_loss > 0:
                    atr_val = alert.stop_loss * 0.012

                vol_noise_margin = (
                    max(0.05, min(alert.stop_loss * 0.003, 0.15 * atr_val))
                    if alert.stop_loss > 0
                    else 0.10
                )

            is_live_alert = getattr(alert, "is_live", True) and getattr(alert, "environment", "") != "TEST"
            if alert.direction == "BEARISH":
                # For short positions, stop loss is above entry
                ref_entry = alert.ltp or alert.trigger_level or 0.0
                if alert.stop_loss > ref_entry:
                    if current_ltp > (alert.stop_loss + vol_noise_margin):
                        return (
                            f"Price surged to {curr_sym}{current_ltp:,.1f} "
                            f"(breached stop-loss {curr_sym}{alert.stop_loss:,.1f}). Bearish thesis invalidated."
                        )
                    if session_high and session_high > (alert.stop_loss + vol_noise_margin) and is_live_alert:
                        return (
                            f"Session high surged to {curr_sym}{session_high:,.1f} "
                            f"(breached stop-loss ceiling {curr_sym}{alert.stop_loss:,.1f}). Bearish thesis invalidated."
                        )
                else:
                    if current_ltp < (alert.stop_loss - vol_noise_margin):
                        return (
                            f"Price dropped to {curr_sym}{current_ltp:,.1f} "
                            f"(breached stop-loss {curr_sym}{alert.stop_loss:,.1f}). Bearish thesis invalidated."
                        )
                    if session_low and session_low < (alert.stop_loss - vol_noise_margin) and is_live_alert:
                        return (
                            f"Session low dropped to {curr_sym}{session_low:,.1f} "
                            f"(breached stop-loss floor {curr_sym}{alert.stop_loss:,.1f}). Bearish thesis invalidated."
                        )
            else:
                # Bullish / Neutral long positions
                if current_ltp < (alert.stop_loss - vol_noise_margin):
                    return (
                        f"Price dropped to {curr_sym}{current_ltp:,.1f} "
                        f"(breached stop-loss {curr_sym}{alert.stop_loss:,.1f}). Bullish thesis invalidated."
                    )
                if session_low and session_low < (alert.stop_loss - vol_noise_margin) and is_live_alert:
                    return (
                        f"Session low plunged to {curr_sym}{session_low:,.1f} "
                        f"(breached stop-loss floor {curr_sym}{alert.stop_loss:,.1f}). Bullish thesis invalidated."
                    )

    # 2. Detector-Specific Structural Breakdown
    if alert.alert_type == "SQUEEZE_BREAKOUT":
        if alert.trigger_level > 0 and current_ltp < (alert.trigger_level * 0.965):
            retreat_pct = round(
                ((alert.trigger_level - current_ltp) / alert.trigger_level) * 100, 1
            )
            return (
                f"Price retreated {retreat_pct}% below breakout pivot ₹{alert.trigger_level:,.1f} "
                f"(LTP ₹{current_ltp:,.1f}). Squeeze compression lost momentum."
            )
        sma20 = alert.metrics.get("sma20") if alert.metrics else None
        if sma20:
            # Add dynamic noise margin (minimum 0.08% or 0.20 pts) to prevent single-tick 20-paise invalidations on indices
            sma_noise_margin = max(0.20, sma20 * 0.0008)
            if current_ltp < (sma20 - sma_noise_margin):
                return f"Price broke down below 20-SMA base support ₹{sma20:,.1f} (LTP ₹{current_ltp:,.1f}). Squeeze invalidated."

    elif alert.alert_type == "CIRCUIT_WARNING":
        upper_circuit = alert.trigger_level or (
            alert.metrics.get("upper_circuit", 0.0) if alert.metrics else 0.0
        )
        if upper_circuit > 0:
            dist_to_uc = ((upper_circuit - current_ltp) / upper_circuit) * 100.0
            if dist_to_uc > 3.0:
                return (
                    f"Price backed off {dist_to_uc:.1f}% from upper circuit ceiling ₹{upper_circuit:,.1f} "
                    f"(LTP ₹{current_ltp:,.1f}). Circuit lock threat subsided."
                )

    elif alert.alert_type == "GAMMA_BLAST":
        # Ensure underlying spot price is used for VWAP comparison, not option premium
        underlying_price = None
        if is_option:
            underlying_price = getattr(alert, "underlying_spot", None) or (
                alert.metrics.get("spot") if alert.metrics else None
            )
            if not underlying_price or underlying_price <= 0:
                try:
                    from market.quotes import get_ltp

                    underlying_price = get_ltp(
                        f"NSE:{alert.symbol}" if ":" not in alert.symbol else alert.symbol
                    )
                except Exception:
                    underlying_price = None
        else:
            underlying_price = current_ltp

        if underlying_price and underlying_price > 0 and current_vwap and current_vwap > 0:
            if alert.direction == "BULLISH" and underlying_price < (current_vwap * 0.992):
                return (
                    f"Underlying broke below intraday VWAP ₹{current_vwap:,.1f} "
                    f"(Spot ₹{underlying_price:,.1f}). Long gamma setup invalidated."
                )
            elif alert.direction == "BEARISH" and underlying_price > (current_vwap * 1.008):
                return (
                    f"Underlying reclaimed above intraday VWAP ₹{current_vwap:,.1f} "
                    f"(Spot ₹{underlying_price:,.1f}). Short gamma setup invalidated."
                )

    return None


@dataclass
class TargetTrailingEvaluation:
    new_milestone: Optional[str] = (
        None  # "T1_ACHIEVED" | "TARGET_ACHIEVED" | "TRAILING_UPDATE" | None
    )
    target_status: str = "PENDING"
    should_trail: bool = False
    trailing_decision: str = "DO_NOT_TRAIL_HOLD_STOP"
    recommended_stop: float = 0.0
    trailing_rationale: str = ""
    locked_profit_pts: float = 0.0
    locked_profit_pct: float = 0.0
    r_multiple: float = 0.0
    pnl_pct: float = 0.0
    is_superperforming: bool = False
    strike_roll_recommendation: Optional[dict[str, Any]] = None
    should_roll_strike: bool = False

    @property
    def is_t1_hit(self) -> bool:
        return self.new_milestone in ("T1_ACHIEVED", "TARGET_ACHIEVED", "T0_5_ACHIEVED")

    @property
    def is_target_hit(self) -> bool:
        return self.new_milestone in ("TARGET_ACHIEVED", "T2_ACHIEVED", "FINAL_ACHIEVED")

    @property
    def trailing_ratcheted(self) -> bool:
        return self.new_milestone == "TRAILING_UPDATE" or self.should_trail

    @property
    def new_trailing_stop(self) -> float:
        return self.recommended_stop

    @property
    def action_decision(self) -> str:
        return self.trailing_decision

    @property
    def rationale(self) -> str:
        return self.trailing_rationale


def calculate_strike_roll_recommendation(
    alert: Any,
    current_ltp: float,
    pnl_pct: float,
    is_bullish: bool,
) -> Optional[dict[str, Any]]:
    """
    Computes institutional strike roll recommendation when an option hits T2 / Final target.
    Prevents holding deep ITM options with delta ~ 1.0, wide bid-ask spread, and low liquidity.
    Suggests rolling to an active liquid ATM strike.
    """
    sym = (
        (getattr(alert, "symbol", "") or "")
        .replace("NSE:", "")
        .replace("NFO:", "")
        .replace("BSE:", "")
        .strip()
        .upper()
    )
    cur_strike = getattr(alert, "strike", None)
    opt_type = getattr(alert, "option_type", None)
    if not cur_strike or not opt_type:
        return None

    # Underlying spot price reference
    spot = getattr(alert, "underlying_spot", None)
    if not spot or spot <= 0:
        metrics = getattr(alert, "metrics", {}) or {}
        spot = metrics.get("spot")
    if not spot or spot <= 0:
        return None

    # Strike step determination
    step = 50.0
    if sym in ("BANKNIFTY", "SENSEX", "BANKEX"):
        step = 100.0
    elif sym == "FINNIFTY":
        step = 50.0
    elif sym == "MIDCPNIFTY":
        step = 25.0
    elif sym == "NIFTY":
        step = 50.0
    else:
        # Stock options strike step heuristic
        if spot >= 5000:
            step = 100.0
        elif spot >= 2500:
            step = 50.0
        elif spot >= 1000:
            step = 20.0
        elif spot >= 500:
            step = 10.0
        elif spot >= 200:
            step = 5.0
        else:
            step = 2.5

    # Compute fresh ATM strike
    atm_strike = round(spot / step) * step

    # If current strike is already near ATM (e.g. within 0.5 step), rolling is not needed
    if abs(cur_strike - atm_strike) < (step * 0.5):
        return None

    action_type = "ROLL_UP" if is_bullish else "ROLL_DOWN"
    roll_target_strike = atm_strike

    # Attempt to derive new contract symbol if possible
    exp_date = getattr(alert, "expiry_date", None)
    cur_contract = getattr(alert, "contract_symbol", "")
    new_contract = None
    if cur_contract and str(int(cur_strike)) in cur_contract:
        new_contract = cur_contract.replace(str(int(cur_strike)), str(int(roll_target_strike)))

    action_desc = "up" if is_bullish else "down"
    return {
        "action": action_type,
        "current_strike": cur_strike,
        "recommended_strike": roll_target_strike,
        "recommended_contract": new_contract,
        "underlying_spot": spot,
        "expiry_date": exp_date,
        "pnl_pct": round(pnl_pct, 1),
        "reason": (
            f"Lock in deep ITM option gains (+{pnl_pct:.1f}%). "
            f"Roll {action_desc} to liquid ATM {int(roll_target_strike)} {opt_type} "
            f"to restore gamma leverage and avoid wide bid-ask slippage."
        ),
        "status": "RECOMMENDED",
    }


def evaluate_alert_targets_and_trailing(
    alert: Any,
    current_ltp: Optional[float] = None,
    current_volume_ratio: Optional[float] = None,
) -> Optional[TargetTrailingEvaluation]:
    """
    Evaluates an active AutoAlert against current market price to determine:
      1. Target milestones reached (Target 1 / 2R Breakeven vs Final Target).
      2. Clear, decisive trailing stop recommendation: WHETHER TO TRAIL OR NOT.
      3. Exact price level to trail stop loss to and profit locked.
    """
    if getattr(alert, "is_invalidated", False) or getattr(alert, "stage", "") in (
        "INVALIDATED",
        "COMPLETED",
    ):
        return None

    is_option = is_alert_option_premium_level(alert)

    if current_ltp is None or current_ltp <= 0:
        try:
            from market.quotes import get_ltp

            if is_option:
                lookup_sym = getattr(alert, "contract_symbol", None) or (
                    f"{alert.exchange}:{alert.symbol}" if ":" not in alert.symbol else alert.symbol
                )
            else:
                lookup_sym = (
                    f"{alert.exchange}:{alert.symbol}" if ":" not in alert.symbol else alert.symbol
                )
            current_ltp = get_ltp(lookup_sym)
        except Exception:
            current_ltp = None

    if current_ltp is None or current_ltp <= 0:
        return None

    if is_option:
        # Check if option buyer or option writer/seller:
        act = str((getattr(alert, "actionable_plan", None) or {}).get("action", "")).upper()
        is_option_sell = act in ("SELL", "WRITE", "SHORT")
        if not is_option_sell and alert.stop_loss and alert.target_level:
            ref_entry = getattr(alert, "option_premium", None) or alert.ltp
            if ref_entry and alert.stop_loss > ref_entry and alert.target_level < ref_entry:
                is_option_sell = True

        # For option buyers, payoff is upward (is_bullish = True, profit on premium expansion).
        # For option writers/sellers, payoff is downward (is_bullish = False, profit on premium decay).
        is_bullish = not is_option_sell

        # Canonical entry resolution for options:
        entry = None
        plan = getattr(alert, "actionable_plan", None)
        if plan:
            rec_entry = plan.get("recommended_entry", "")
            m = re.search(r"[\d,]+(?:\.\d+)?", str(rec_entry))
            if m:
                try:
                    entry = float(m.group(0).replace(",", ""))
                except ValueError:
                    pass
            if not entry and plan.get("entry_range"):
                matches = re.findall(r"[\d,]+(?:\.\d+)?", str(plan["entry_range"]))
                if len(matches) >= 2:
                    try:
                        entry = round(
                            (
                                float(matches[0].replace(",", ""))
                                + float(matches[1].replace(",", ""))
                            )
                            / 2.0,
                            2,
                        )
                    except ValueError:
                        pass
                elif len(matches) == 1:
                    try:
                        entry = float(matches[0].replace(",", ""))
                    except ValueError:
                        pass
        if not entry and getattr(alert, "option_premium", None) and alert.option_premium > 0:
            entry = alert.option_premium
        if not entry:
            if (
                alert.ltp
                and alert.ltp > 0
                and (not getattr(alert, "strike", None) or alert.ltp != alert.strike)
            ):
                entry = alert.ltp
            elif alert.stop_loss and alert.stop_loss > 0:
                entry = round(alert.stop_loss * 1.4, 2)
            else:
                entry = current_ltp
    else:
        entry = None
        plan = getattr(alert, "actionable_plan", None)
        if plan and (plan.get("instrument_type") == "OPTION" or plan.get("preferred_vehicle") == "DEFINED_RISK_OPTION"):
            fut_ref = plan.get("futures_reference")
            if fut_ref and isinstance(fut_ref, dict) and fut_ref.get("entry"):
                entry = float(fut_ref["entry"])
            else:
                entry = alert.trigger_level or alert.ltp or current_ltp
        elif plan:
            rec_entry = plan.get("recommended_entry", "")
            m = re.search(r"[\d,]+(?:\.\d+)?", str(rec_entry))
            if m:
                try:
                    entry = float(m.group(0).replace(",", ""))
                except ValueError:
                    pass
            if not entry and plan.get("entry_range"):
                matches = re.findall(r"[\d,]+(?:\.\d+)?", str(plan["entry_range"]))
                if len(matches) >= 2:
                    try:
                        entry = round(
                            (
                                float(matches[0].replace(",", ""))
                                + float(matches[1].replace(",", ""))
                            )
                            / 2.0,
                            2,
                        )
                    except ValueError:
                        pass
                elif len(matches) == 1:
                    try:
                        entry = float(matches[0].replace(",", ""))
                    except ValueError:
                        pass
        if not entry and getattr(alert, "trigger_level", None) and alert.trigger_level > 0:
            entry = alert.trigger_level
        if not entry:
            entry = alert.ltp if alert.ltp > 0 else current_ltp
        is_bullish = alert.direction.upper() != "BEARISH"

    # Reference stop loss
    stop = None
    plan = getattr(alert, "actionable_plan", None)
    if not is_option and plan and (plan.get("instrument_type") == "OPTION" or plan.get("preferred_vehicle") == "DEFINED_RISK_OPTION"):
        fut_ref = plan.get("futures_reference")
        if fut_ref and isinstance(fut_ref, dict) and fut_ref.get("stop_loss"):
            stop = float(fut_ref["stop_loss"])
        elif alert.stop_loss and alert.stop_loss > 0:
            stop = alert.stop_loss
    elif plan and plan.get("stop_loss"):
        m_sl = re.search(r"[\d,]+(?:\.\d+)?", str(plan["stop_loss"]))
        if m_sl:
            try:
                stop = float(m_sl.group(0).replace(",", ""))
            except ValueError:
                pass
    if not stop and alert.stop_loss and alert.stop_loss > 0:
        stop = alert.stop_loss
    if not stop:
        stop = round(entry * 0.98 if is_bullish else entry * 1.02, 2)

    # Sanity guard against unit-scale corruption (e.g. comparing spot price ₹1,442 against option entry ₹16)
    if entry > 0 and current_ltp > 0:
        ratio = current_ltp / entry
        if not is_option and (ratio > 2.5 or ratio < 0.4):
            logger.warning(
                f"[AlertEvaluator] Spot/futures price scale mismatch for {getattr(alert, 'symbol', '')} "
                f"({getattr(alert, 'alert_id', '')}): current_ltp={current_ltp} vs entry={entry}. Suppressing false evaluation."
            )
            return None
        elif is_option and (ratio > 10.0 or ratio < 0.05):
            logger.warning(
                f"[AlertEvaluator] Option premium price scale mismatch for {getattr(alert, 'symbol', '')} "
                f"({getattr(alert, 'alert_id', '')}): current_ltp={current_ltp} vs entry={entry}. Suppressing false evaluation."
            )
            return None

    initial_risk = max(0.01, abs(entry - stop))

    # PnL & R-multiple
    if is_bullish:
        pnl_pts = current_ltp - entry
        pnl_pct = (pnl_pts / entry) * 100 if entry > 0 else 0.0
        r_multiple = pnl_pts / initial_risk
    else:
        pnl_pts = entry - current_ltp
        pnl_pct = (pnl_pts / entry) * 100 if entry > 0 else 0.0
        r_multiple = pnl_pts / initial_risk

    # Target levels resolution
    plan_t0_5 = None
    plan_t1 = None
    plan_t2 = None
    plan_t3 = None
    if plan and isinstance(plan, dict):
        if not is_option and (plan.get("instrument_type") == "OPTION" or plan.get("preferred_vehicle") == "DEFINED_RISK_OPTION"):
            fut_ref = plan.get("futures_reference")
            if fut_ref and isinstance(fut_ref, dict):
                if fut_ref.get("target_1"):
                    plan_t1 = float(fut_ref["target_1"])
                if fut_ref.get("target_2"):
                    plan_t2 = float(fut_ref["target_2"])
        if is_option:
            opt_plan = plan.get("option_plan")
            if isinstance(opt_plan, dict):
                if opt_plan.get("t0_5_premium"):
                    plan_t0_5 = float(opt_plan["t0_5_premium"])
                if opt_plan.get("t1_premium"):
                    plan_t1 = float(opt_plan["t1_premium"])
                if opt_plan.get("t2_premium"):
                    plan_t2 = float(opt_plan["t2_premium"])
                if opt_plan.get("t3_premium"):
                    plan_t3 = float(opt_plan["t3_premium"])

        trade_plan = plan.get("trade_plan")
        if isinstance(trade_plan, dict):
            if trade_plan.get("target_0_5") and not plan_t0_5:
                plan_t0_5 = float(trade_plan["target_0_5"])
            if trade_plan.get("target_1") and not plan_t1:
                plan_t1 = float(trade_plan["target_1"])
            if trade_plan.get("target_2") and not plan_t2:
                plan_t2 = float(trade_plan["target_2"])
            if trade_plan.get("target_3") and not plan_t3:
                plan_t3 = float(trade_plan["target_3"])

        if "target_0_5" in plan and not plan_t0_5:
            m_t0_5 = re.search(r"[\d,]+(?:\.\d+)?", str(plan["target_0_5"]))
            if m_t0_5:
                plan_t0_5 = float(m_t0_5.group(0).replace(",", ""))

        if "target_1" in plan and not plan_t1:
            m_t1 = re.search(r"[\d,]+(?:\.\d+)?", str(plan["target_1"]))
            if m_t1:
                plan_t1 = float(m_t1.group(0).replace(",", ""))
        elif "target" in plan and not plan_t1:
            m_t1 = re.search(r"[\d,]+(?:\.\d+)?", str(plan["target"]))
            if m_t1:
                plan_t1 = float(m_t1.group(0).replace(",", ""))

        if "target_2" in plan and not plan_t2:
            m_t2 = re.search(r"[\d,]+(?:\.\d+)?", str(plan["target_2"]))
            if m_t2:
                plan_t2 = float(m_t2.group(0).replace(",", ""))

        if "target_3" in plan and not plan_t3:
            m_t3 = re.search(r"[\d,]+(?:\.\d+)?", str(plan["target_3"]))
            if m_t3:
                plan_t3 = float(m_t3.group(0).replace(",", ""))

    # Sanity filter for options to prevent spot price pollution
    if is_option and entry > 0:
        if plan_t0_5 and plan_t0_5 > entry * 10:
            plan_t0_5 = None
        if plan_t1 and plan_t1 > entry * 10:
            plan_t1 = None
        if plan_t2 and plan_t2 > entry * 10:
            plan_t2 = None
        if plan_t3 and plan_t3 > entry * 10:
            plan_t3 = None

    valid_alert_tgt = None
    if getattr(alert, "target_level", 0) and alert.target_level > 0:
        raw_tgt = float(alert.target_level)
        if is_option and entry > 0:
            if is_bullish and entry < raw_tgt <= entry * 10:
                valid_alert_tgt = raw_tgt
            elif not is_bullish and 0.05 <= raw_tgt < entry:
                valid_alert_tgt = raw_tgt
        elif not is_option:
            valid_alert_tgt = raw_tgt

    if plan_t3:
        target_final = plan_t3
    elif plan_t2 and not plan_t1:
        target_final = plan_t2
    elif valid_alert_tgt and valid_alert_tgt > (plan_t2 or 0):
        target_final = valid_alert_tgt
    elif plan_t2:
        target_final = plan_t2
    elif valid_alert_tgt:
        target_final = valid_alert_tgt
    elif is_option:
        # For options, if target_2 was not specified, compute a distinct 3.0R final target
        target_final = round(
            entry + (initial_risk * 3.0) if is_bullish else max(0.05, entry - (initial_risk * 3.0)),
            2,
        )
    else:
        target_final = round(
            entry + (initial_risk * 3.0) if is_bullish else entry - (initial_risk * 3.0),
            2,
        )

    if plan_t1:
        t1_level = plan_t1
    elif is_bullish:
        t1_level = round(entry + (initial_risk * 1.8), 2)
        if target_final > entry:
            t1_level = min(t1_level, round(entry + (target_final - entry) * 0.5, 2))
    else:
        t1_level = round(entry - (initial_risk * 1.8), 2)
        if target_final < entry:
            t1_level = max(t1_level, round(entry - (entry - target_final) * 0.5, 2))

    t0_5_level = plan_t0_5
    if not t0_5_level:
        if is_option and entry > 0:
            t0_5_level = round(entry * 1.16 if is_bullish else max(0.05, entry * 0.84), 2)
        elif is_bullish:
            t0_5_level = round(entry + (initial_risk * 1.0), 2)
        else:
            t0_5_level = round(entry - (initial_risk * 1.0), 2)

    # Ensure t0_5_level sits strictly between entry and t1_level
    if is_bullish:
        if not (entry < t0_5_level < t1_level):
            t0_5_level = round(entry + (t1_level - entry) * 0.5, 2) if t1_level > entry else None
    else:
        if not (t1_level < t0_5_level < entry):
            t0_5_level = round(entry - (entry - t1_level) * 0.5, 2) if t1_level < entry else None

    t2_level = plan_t2
    if not t2_level and target_final != t1_level:
        if is_bullish and target_final > t1_level:
            t2_level = round(t1_level + (target_final - t1_level) * 0.5, 2)
        elif not is_bullish and target_final < t1_level:
            t2_level = round(t1_level - (t1_level - target_final) * 0.5, 2)

    achieved = set(getattr(alert, "achieved_milestones", None) or [])

    # Volume / Momentum check for extension
    vol_ratio = current_volume_ratio or (
        alert.metrics.get("vol_oi_ratio", alert.metrics.get("rvol", 1.0)) if alert.metrics else 1.0
    )
    conf = getattr(alert, "confidence", 75)
    is_superperforming = (vol_ratio >= 2.0) or (conf >= 88 and r_multiple >= 2.5)

    # Hard Profitability Invariant: A target milestone (T1, T2 or Final) CAN NEVER be reached
    # if the position is sitting at or below entry price (loss or breakeven).
    if is_bullish:
        if current_ltp <= entry or pnl_pts <= 0 or t1_level <= entry:
            is_final_hit = False
            is_t2_hit = False
            is_t1_hit = False
            is_t0_5_hit = False
        else:
            is_final_hit = current_ltp >= target_final
            is_t2_hit = bool(t2_level and current_ltp >= t2_level and t2_level > t1_level)
            is_t1_hit = current_ltp >= t1_level
            is_t0_5_hit = bool(t0_5_level and current_ltp >= t0_5_level and t0_5_level < t1_level)
    else:
        if current_ltp >= entry or pnl_pts <= 0 or t1_level >= entry:
            is_final_hit = False
            is_t2_hit = False
            is_t1_hit = False
            is_t0_5_hit = False
        else:
            is_final_hit = current_ltp <= target_final
            is_t2_hit = bool(t2_level and current_ltp <= t2_level and t2_level < t1_level)
            is_t1_hit = current_ltp <= t1_level
            is_t0_5_hit = bool(t0_5_level and current_ltp <= t0_5_level and t0_5_level > t1_level)

    # Exchange High/Low & Dirty Tick Sanity Filter:
    # Discard unverified phantom spikes where current_ltp violates the day's exchange high/low.
    # Primarily guards option contracts against broker token cross-pollution or unverified feed spikes.
    day_high = float(getattr(alert, "high", 0.0) or (getattr(alert, "metrics", {}) or {}).get("high", 0.0) or 0.0)
    day_low = float(getattr(alert, "low", 0.0) or (getattr(alert, "metrics", {}) or {}).get("low", 0.0) or 0.0)

    if is_t1_hit or is_t2_hit or is_final_hit:
        try:
            if is_option and (day_high <= 0 or day_low <= 0) and not os.environ.get("CHANAKYA_TESTING"):
                lookup_sym = getattr(alert, "contract_symbol", None) or (
                    f"{alert.exchange}:{alert.symbol}"
                    if ":" not in getattr(alert, "symbol", "")
                    else getattr(alert, "symbol", "")
                )
                from market.quotes import get_ohlc
                ohlc = get_ohlc(lookup_sym)
                if ohlc and isinstance(ohlc, dict):
                    day_high = day_high or float(ohlc.get("high") or 0.0)
                    day_low = day_low or float(ohlc.get("low") or 0.0)

            is_coherent = (entry <= 0) or (0.4 * entry <= day_high <= 2.5 * entry)

            if is_bullish and day_high > 0 and is_coherent:
                if current_ltp > day_high * 1.02:
                    logger.warning(
                        f"[AlertEvaluator] Discarded phantom dirty tick for {alert.symbol}: "
                        f"current_ltp={current_ltp} exceeds exchange day_high={day_high} by >2%."
                    )
                    current_ltp = day_high
                    pnl_pts = current_ltp - entry
                    pnl_pct = (pnl_pts / entry) * 100 if entry > 0 else 0.0
                    r_multiple = pnl_pts / initial_risk
                    is_t1_hit = current_ltp >= t1_level
                    is_t2_hit = bool(t2_level and current_ltp >= t2_level and t2_level > t1_level)
                    is_final_hit = current_ltp >= target_final
            elif not is_bullish and day_low > 0 and is_coherent:
                if current_ltp < day_low * 0.98:
                    logger.warning(
                        f"[AlertEvaluator] Discarded phantom dirty tick for {alert.symbol}: "
                        f"current_ltp={current_ltp} below exchange day_low={day_low} by >2%."
                    )
                    current_ltp = day_low
                    pnl_pts = entry - current_ltp
                    pnl_pct = (pnl_pts / entry) * 100 if entry > 0 else 0.0
                    r_multiple = pnl_pts / initial_risk
                    is_t1_hit = current_ltp <= t1_level
                    is_t2_hit = bool(t2_level and current_ltp <= t2_level and t2_level < t1_level)
                    is_final_hit = current_ltp <= target_final
        except Exception as e:
            logger.debug(f"[AlertEvaluator] OHLC sanity check error: {e}")

    # 1. Final Target (T3 or Primary Target) Hit
    if is_final_hit and pnl_pts > 0 and "TARGET_ACHIEVED" not in achieved:
        roll_rec = (
            calculate_strike_roll_recommendation(alert, current_ltp, pnl_pct, is_bullish)
            if is_option
            else None
        )
        if is_superperforming:
            # Superperforming momentum: do NOT exit all, trail runner with Chandelier ATR
            if is_bullish:
                rec_stop = max(t1_level, round(current_ltp - (initial_risk * 1.5), 2))
                locked_pts = rec_stop - entry
            else:
                rec_stop = min(t1_level, round(current_ltp + (initial_risk * 1.5), 2))
                locked_pts = entry - rec_stop

            locked_pct = round((locked_pts / entry) * 100, 2)
            rationale = (
                f"Primary target ₹{target_final:,.2f} reached (+{pnl_pct:.1f}%, +{r_multiple:.1f}R) with runaway volume ({vol_ratio:.1f}x). "
                f"DECISION: TRAIL STOP-LOSS TO ₹{rec_stop:,.2f} (Chandelier ATR Trail). "
                f"DO NOT FULLY EXIT RUNNER — Heavy institutional flow is extending breakout. Let runners ride!"
            )
            if roll_rec:
                rationale += f" | 🔄 OPTION ROLL: {roll_rec['reason']}"
            return TargetTrailingEvaluation(
                new_milestone="TARGET_ACHIEVED",
                target_status="TARGET_ACHIEVED",
                should_trail=True,
                trailing_decision="TRAIL_DYNAMIC_ATR",
                recommended_stop=rec_stop,
                trailing_rationale=rationale,
                locked_profit_pts=round(locked_pts, 2),
                locked_profit_pct=locked_pct,
                r_multiple=round(r_multiple, 2),
                pnl_pct=round(pnl_pct, 2),
                is_superperforming=True,
                strike_roll_recommendation=roll_rec,
                should_roll_strike=bool(roll_rec),
            )
        else:
            # Normal target hit: resistance reached, book full profit! Do not trail.
            rec_stop = current_ltp
            locked_pts = pnl_pts
            locked_pct = round(pnl_pct, 2)
            rationale = (
                f"Final target ₹{target_final:,.2f} reached (+{pnl_pct:.1f}%, +{r_multiple:.1f}R). "
                f"DECISION: FULL PROFIT BOOKING RECOMMENDED. Close all open positions at market. "
                f"DO NOT TRAIL FURTHER — high probability of mean-reversion exhaustion at major resistance."
            )
            if roll_rec:
                rationale += f" | 🔄 OPTION ROLL: {roll_rec['reason']}"
            return TargetTrailingEvaluation(
                new_milestone="TARGET_ACHIEVED",
                target_status="TARGET_ACHIEVED",
                should_trail=False,
                trailing_decision="BOOK_FULL_PROFIT_NO_TRAIL",
                recommended_stop=rec_stop,
                trailing_rationale=rationale,
                locked_profit_pts=round(locked_pts, 2),
                locked_profit_pct=locked_pct,
                r_multiple=round(r_multiple, 2),
                pnl_pct=round(pnl_pct, 2),
                is_superperforming=False,
                strike_roll_recommendation=roll_rec,
                should_roll_strike=bool(roll_rec),
            )

    # 2. Target 2 (T2) Check - intermediate expansion milestone
    if (
        is_t2_hit
        and pnl_pts > 0
        and t2_level
        and (target_final > t2_level if is_bullish else target_final < t2_level)
        and "T2_ACHIEVED" not in achieved
        and "TARGET_ACHIEVED" not in achieved
    ):
        # T2 reached -> Trail SL to T1 level (Guarantees T1 profit locked)
        roll_rec = (
            calculate_strike_roll_recommendation(alert, current_ltp, pnl_pct, is_bullish)
            if is_option
            else None
        )
        rec_stop = t1_level
        locked_pts = abs(rec_stop - entry)
        locked_pct = round((locked_pts / entry) * 100, 2) if entry > 0 else 0.0
        rationale = (
            f"Target 2 reached at ₹{current_ltp:,.2f} (+{pnl_pct:.1f}%, +{r_multiple:.1f}R). "
            f"DECISION: TRAIL STOP-LOSS TO T1 (₹{rec_stop:,.2f}) LOCKING +{locked_pct:.1f}% PROFIT. "
            f"Hold runner position for Final Target (₹{target_final:,.2f})."
        )
        if roll_rec:
            rationale += f" | 🔄 OPTION ROLL: {roll_rec['reason']}"
        return TargetTrailingEvaluation(
            new_milestone="T2_ACHIEVED",
            target_status="T2_ACHIEVED",
            should_trail=True,
            trailing_decision="TRAIL_LOCK_T1",
            recommended_stop=rec_stop,
            trailing_rationale=rationale,
            locked_profit_pts=round(locked_pts, 2),
            locked_profit_pct=locked_pct,
            r_multiple=round(r_multiple, 2),
            pnl_pct=round(pnl_pct, 2),
            is_superperforming=is_superperforming,
            strike_roll_recommendation=roll_rec,
            should_roll_strike=bool(roll_rec),
        )

    # 3. Target 1 (T1) Check - Strictly requires positive PnL and genuine milestone achievement
    if (
        is_t1_hit
        and pnl_pts > 0
        and r_multiple >= 0.5
        and "T1_ACHIEVED" not in achieved
        and "T2_ACHIEVED" not in achieved
        and "TARGET_ACHIEVED" not in achieved
    ):
        # T1 reached -> Book 50% & Trail SL to Breakeven (+0.2% buffer)
        be_stop = round(entry * 1.002 if is_bullish else entry * 0.998, 2)
        rec_stop = be_stop
        locked_pts = abs(rec_stop - entry)
        locked_pct = 0.2
        next_tgt = t2_level or target_final
        rationale = (
            f"Target 1 reached at ₹{current_ltp:,.2f} (+{pnl_pct:.1f}%, +{r_multiple:.1f}R). "
            f"DECISION: BOOK 50% PARTIAL PROFIT NOW & TRAIL STOP-LOSS TO BREAKEVEN (₹{rec_stop:,.2f}). "
            f"Trade is now 100% risk-free. Hold remaining 50% runner for Target 2 (₹{next_tgt:,.2f})."
        )
        return TargetTrailingEvaluation(
            new_milestone="T1_ACHIEVED",
            target_status="T1_ACHIEVED",
            should_trail=True,
            trailing_decision="BOOK_50_TRAIL_BREAKEVEN",
            recommended_stop=rec_stop,
            trailing_rationale=rationale,
            locked_profit_pts=round(locked_pts, 2),
            locked_profit_pct=locked_pct,
            r_multiple=round(r_multiple, 2),
            pnl_pct=round(pnl_pct, 2),
            is_superperforming=is_superperforming,
        )

    # 4. Target 0.5 (T0.5 / Scale 1) Check - De-risks trades early at +1.0R / +16%
    if (
        is_t0_5_hit
        and pnl_pts > 0
        and r_multiple >= 0.4
        and "T0_5_ACHIEVED" not in achieved
        and "T1_ACHIEVED" not in achieved
        and "T2_ACHIEVED" not in achieved
        and "TARGET_ACHIEVED" not in achieved
    ):
        be_stop = round(entry * 1.002 if is_bullish else entry * 0.998, 2)
        rec_stop = be_stop
        locked_pts = abs(rec_stop - entry)
        locked_pct = 0.2
        next_tgt = t1_level or target_final
        rationale = (
            f"Target 0.5 (Scale 1) reached at ₹{current_ltp:,.2f} (+{pnl_pct:.1f}%, +{r_multiple:.1f}R). "
            f"DECISION: SCALE 35% PARTIAL PROFIT & TRAIL STOP-LOSS TO BREAKEVEN (₹{rec_stop:,.2f}). "
            f"Trade is now de-risked to 100% free trade. Hold remaining 65% runner for Target 1 (₹{next_tgt:,.2f})."
        )
        return TargetTrailingEvaluation(
            new_milestone="T0_5_ACHIEVED",
            target_status="T0_5_ACHIEVED",
            should_trail=True,
            trailing_decision="SCALE_35_TRAIL_BREAKEVEN",
            recommended_stop=rec_stop,
            trailing_rationale=rationale,
            locked_profit_pts=round(locked_pts, 2),
            locked_profit_pct=locked_pct,
            r_multiple=round(r_multiple, 2),
            pnl_pct=round(pnl_pct, 2),
            is_superperforming=is_superperforming,
        )

    # 5. Trailing Stop Ratchet Higher (Dynamic Trail)
    if (
        getattr(alert, "should_trail", False)
        and getattr(alert, "trailing_stop", None)
        and alert.trailing_stop > 0
        and getattr(alert, "stage", "") != "COMPLETED"
    ):
        if is_bullish:
            higher_trail = round(max(alert.trailing_stop, current_ltp - (initial_risk * 1.8)), 2)
            min_dist = 0.5 if is_option else 2.0
            if (
                higher_trail >= round(alert.trailing_stop * 1.0075, 2)
                and (higher_trail - alert.trailing_stop) >= min_dist
            ):
                locked_pts = higher_trail - entry
                locked_pct = round((locked_pts / entry) * 100, 2)
                unit_str = "pts" if is_option else "/sh"
                rationale = (
                    f"Price expanded to ₹{current_ltp:,.2f}. "
                    f"DECISION: RATCHET TRAILING STOP HIGHER from ₹{alert.trailing_stop:,.2f} to ₹{higher_trail:,.2f}. "
                    f"Guaranteed locked profit increased to +₹{locked_pts:,.2f} {unit_str} (+{locked_pct:.1f}%)."
                )
                return TargetTrailingEvaluation(
                    new_milestone="TRAILING_UPDATE",
                    target_status=getattr(alert, "target_status", None) or "T1_ACHIEVED",
                    should_trail=True,
                    trailing_decision="TRAIL_DYNAMIC_ATR",
                    recommended_stop=higher_trail,
                    trailing_rationale=rationale,
                    locked_profit_pts=round(locked_pts, 2),
                    locked_profit_pct=locked_pct,
                    r_multiple=round(r_multiple, 2),
                    pnl_pct=round(pnl_pct, 2),
                    is_superperforming=is_superperforming,
                )
        else:
            lower_trail = round(min(alert.trailing_stop, current_ltp + (initial_risk * 1.8)), 2)
            if (
                lower_trail <= round(alert.trailing_stop * 0.9925, 2)
                and (alert.trailing_stop - lower_trail) >= 2.0
            ):
                locked_pts = entry - lower_trail
                locked_pct = round((locked_pts / entry) * 100, 2)
                rationale = (
                    f"Price dropped to ₹{current_ltp:,.2f}. "
                    f"DECISION: RATCHET TRAILING STOP LOWER from ₹{alert.trailing_stop:,.2f} to ₹{lower_trail:,.2f}. "
                    f"Guaranteed locked profit increased to +₹{locked_pts:,.2f}/sh (+{locked_pct:.1f}%)."
                )
                return TargetTrailingEvaluation(
                    new_milestone="TRAILING_UPDATE",
                    target_status=getattr(alert, "target_status", None) or "T1_ACHIEVED",
                    should_trail=True,
                    trailing_decision="TRAIL_DYNAMIC_ATR",
                    recommended_stop=lower_trail,
                    trailing_rationale=rationale,
                    locked_profit_pts=round(locked_pts, 2),
                    locked_profit_pct=locked_pct,
                    r_multiple=round(r_multiple, 2),
                    pnl_pct=round(pnl_pct, 2),
                    is_superperforming=is_superperforming,
                )

    # 4. Early Sub-Target Phase (< 1.5R)
    if r_multiple < 1.5:
        rationale = (
            f"Payoff is +{r_multiple:.1f}R (+{pnl_pct:.1f}%). "
            f"DECISION: DO NOT TRAIL YET. Maintain initial Stop Loss at ₹{stop:,.2f}. "
            f"Premature trailing in early stage causes whipsaws and unnecessary shakeouts."
        )
        return TargetTrailingEvaluation(
            new_milestone=None,
            target_status=getattr(alert, "target_status", None) or "PENDING",
            should_trail=False,
            trailing_decision="DO_NOT_TRAIL_HOLD_STOP",
            recommended_stop=stop,
            trailing_rationale=rationale,
            locked_profit_pts=0.0,
            locked_profit_pct=0.0,
            r_multiple=round(r_multiple, 2),
            pnl_pct=round(pnl_pct, 2),
            is_superperforming=False,
        )

    return None


@dataclass
class InFlightWarningEvaluation:
    triggered: bool = False
    warning_type: str = ""  # "DANGER_ZONE" | "THETA_STAGNATION"
    reason: str = ""
    coaching_decision: str = ""  # "SCRATCH_OR_TIGHTEN_STOP" | "EXIT_STAGNANT_OPTION"
    current_ltp: float = 0.0
    entry_price: float = 0.0
    stop_loss: float = 0.0
    risk_consumed_pct: float = 0.0
    pnl_pct: float = 0.0
    headline: str = ""
    summary: str = ""


def evaluate_alert_in_flight_decay(
    alert: Any,
    current_ltp: Optional[float] = None,
    current_vwap: Optional[float] = None,
) -> Optional[InFlightWarningEvaluation]:
    """
    Proactively evaluates active trade setups to detect:
      1. Danger Zone Proximity: >= 70% of risk budget consumed or within <= 1.5% of Stop-Loss.
      2. Theta Decay Stagnation: Options positions open >= 15 minutes with no momentum (P&L <= 0%).

    Empowers the trader with high-priority advisory friction to scratch at breakeven
    or tighten stops BEFORE suffering a full 100% loss.
    """
    if (
        getattr(alert, "is_invalidated", False)
        or getattr(alert, "stage", "") in ("INVALIDATED", "COMPLETED", "IN_FLIGHT_WARNING", "EARLY_WARNING")
        or getattr(alert, "in_flight_warning_sent", False)
        or getattr(alert, "target_status", "")
        in ("T1_ACHIEVED", "FINAL_ACHIEVED", "TARGET_ACHIEVED")
        or "T1_ACHIEVED" in (getattr(alert, "achieved_milestones", []) or [])
        or (not getattr(alert, "triggered_at", None) and getattr(alert, "stage", "") not in ("IGNITED", "TRAILING_UPDATE"))
    ):
        return None

    exch = (getattr(alert, "exchange", "NSE") or "NSE").upper()
    is_test = (getattr(alert, "environment", "LIVE") == "TEST") or (
        not getattr(alert, "is_live", True)
    )
    is_test_runner = (
        is_test
        or (os.environ.get("CHANAKYA_TESTING") == "1")
        or (os.environ.get("DEPLOY_MODE") == "test")
        or ("PYTEST_CURRENT_TEST" in os.environ)
    )

    # In live trading, in-flight decay and danger zones ONLY evaluate during active market sessions
    if not is_test_runner:
        from market.calendar import is_market_open

        if not is_market_open(exch):
            return None

    is_option = is_alert_option_premium_level(alert)

    # 1. Resolve current quote LTP if not passed
    if current_ltp is None or current_ltp <= 0:
        try:
            from market.quotes import get_ltp

            if is_option:
                lookup_sym = getattr(alert, "contract_symbol", None) or (
                    f"{alert.exchange}:{alert.symbol}" if ":" not in alert.symbol else alert.symbol
                )
            else:
                lookup_sym = (
                    f"{alert.exchange}:{alert.symbol}" if ":" not in alert.symbol else alert.symbol
                )
            current_ltp = get_ltp(lookup_sym)
        except Exception:
            current_ltp = None

    if current_ltp is None or current_ltp <= 0:
        return None

    is_test = (getattr(alert, "environment", "LIVE") == "TEST") or (
        not getattr(alert, "is_live", True)
    )
    env_tag = "[TEST]" if is_test else "[REAL/LIVE]"

    # 2. Extract Entry Price
    entry = None
    if is_option:
        entry = (
            getattr(alert, "option_premium", None)
            or getattr(alert, "trigger_level", None)
            or getattr(alert, "ltp", None)
        )
    else:
        plan = getattr(alert, "actionable_plan", None)
        if plan and plan.get("recommended_entry"):
            m_ent = re.findall(r"[\d,]+(?:\.\d+)?", str(plan["recommended_entry"]))
            if len(m_ent) >= 2:
                try:
                    entry = round(
                        (float(m_ent[0].replace(",", "")) + float(m_ent[1].replace(",", ""))) / 2.0,
                        2,
                    )
                except ValueError:
                    pass
            elif len(m_ent) == 1:
                try:
                    entry = float(m_ent[0].replace(",", ""))
                except ValueError:
                    pass
        if not entry and getattr(alert, "trigger_level", None) and alert.trigger_level > 0:
            entry = alert.trigger_level
        if not entry:
            entry = alert.ltp if getattr(alert, "ltp", 0) > 0 else current_ltp

    if not entry or entry <= 0:
        entry = current_ltp

    # 3. Extract Stop Loss
    stop = None
    plan = getattr(alert, "actionable_plan", None)
    if plan and plan.get("stop_loss"):
        m_sl = re.search(r"[\d,]+(?:\.\d+)?", str(plan["stop_loss"]))
        if m_sl:
            try:
                stop = float(m_sl.group(0).replace(",", ""))
            except ValueError:
                pass
    if not stop and getattr(alert, "stop_loss", None) and alert.stop_loss > 0:
        stop = alert.stop_loss

    is_bullish = str(getattr(alert, "direction", "BULLISH")).upper() != "BEARISH"
    act_str = str((plan or {}).get("action", "")).upper()
    is_option_sell = is_option and (
        act_str in ("SELL", "WRITE", "SHORT")
        or (stop and entry and stop > entry and getattr(alert, "target_level", 0) < entry)
    )

    # 4. Compute Risk Budget & Payoff
    if is_option and not is_option_sell:
        initial_risk = max(0.1, (entry - stop)) if stop and entry > stop else max(0.1, entry * 0.25)
        pnl_pts = current_ltp - entry
        pnl_pct = (pnl_pts / entry) * 100 if entry > 0 else 0.0
        risk_consumed_pts = entry - current_ltp
        risk_consumed_pct = (risk_consumed_pts / initial_risk) * 100 if initial_risk > 0 else 0.0
        dist_to_sl_pct = (
            ((current_ltp - stop) / current_ltp) * 100 if (stop and current_ltp > 0) else 999.0
        )
    elif is_option_sell:
        initial_risk = max(0.1, (stop - entry)) if stop and stop > entry else max(0.1, entry * 0.35)
        pnl_pts = entry - current_ltp
        pnl_pct = (pnl_pts / entry) * 100 if entry > 0 else 0.0
        risk_consumed_pts = current_ltp - entry
        risk_consumed_pct = (risk_consumed_pts / initial_risk) * 100 if initial_risk > 0 else 0.0
        dist_to_sl_pct = (
            ((stop - current_ltp) / current_ltp) * 100 if (stop and current_ltp > 0) else 999.0
        )
    elif is_bullish:
        initial_risk = (
            max(0.01, (entry - stop)) if stop and entry > stop else max(0.01, entry * 0.02)
        )
        pnl_pts = current_ltp - entry
        pnl_pct = (pnl_pts / entry) * 100 if entry > 0 else 0.0
        risk_consumed_pts = entry - current_ltp
        risk_consumed_pct = (risk_consumed_pts / initial_risk) * 100 if initial_risk > 0 else 0.0
        dist_to_sl_pct = (
            ((current_ltp - stop) / current_ltp) * 100 if (stop and current_ltp > 0) else 999.0
        )
    else:
        initial_risk = (
            max(0.01, (stop - entry)) if stop and stop > entry else max(0.01, entry * 0.02)
        )
        pnl_pts = entry - current_ltp
        pnl_pct = (pnl_pts / entry) * 100 if entry > 0 else 0.0
        risk_consumed_pts = current_ltp - entry
        risk_consumed_pct = (risk_consumed_pts / initial_risk) * 100 if initial_risk > 0 else 0.0
        dist_to_sl_pct = (
            ((stop - current_ltp) / current_ltp) * 100 if (stop and current_ltp > 0) else 999.0
        )

    # 5. Trigger A: Danger Zone Warning (>= 70% Risk Consumed OR within 1.5% of SL)
    # INVARIANT: Danger Zone STRICTLY applies to positions in an active LOSS.
    # A position in profit (pnl_pts >= 0, pnl_pct >= 0, or risk_consumed_pct <= 0) can NEVER be in the Danger Zone!
    is_in_loss = (pnl_pts < 0.0) or (pnl_pct < 0.0) or (risk_consumed_pct > 0.0)
    is_profitable = (pnl_pts >= 0.0) and (pnl_pct >= 0.0) and (risk_consumed_pct <= 0.0)

    if stop and is_in_loss and not is_profitable:
        # Trigger if >= 70% of risk budget is eroded, OR if within 1.5% of SL with >= 50% risk consumed
        is_danger = (risk_consumed_pct >= 70.0) or (
            (0.0 < dist_to_sl_pct <= 1.5) and (risk_consumed_pct >= 50.0)
        )
        if is_danger:
            eff_consumed = max(50.0, min(99.0, risk_consumed_pct))
            headline = f"⚠️ {env_tag} IN-FLIGHT WARNING: {alert.symbol} (Danger Zone: {eff_consumed:.0f}% Risk Consumed)"
            summary = (
                f"LTP ₹{current_ltp:,.2f} is within {dist_to_sl_pct:.1f}% of Stop-Loss (₹{stop:,.2f}). "
                f"{eff_consumed:.0f}% of risk budget is eroded (P&L: {pnl_pct:+.1f}%). "
                f"DECISION: SCRATCH POSITION AT MARKET OR TIGHTEN STOP TO PREVENT FULL CAPITAL LOSS."
            )
            return InFlightWarningEvaluation(
                triggered=True,
                warning_type="DANGER_ZONE",
                reason=f"DANGER ZONE: {eff_consumed:.0f}% risk budget consumed. LTP ₹{current_ltp:,.2f} near SL ₹{stop:,.2f}",
                coaching_decision="SCRATCH_OR_TIGHTEN_STOP",
                current_ltp=current_ltp,
                entry_price=entry,
                stop_loss=stop,
                risk_consumed_pct=round(eff_consumed, 1),
                pnl_pct=round(pnl_pct, 1),
                headline=headline,
                summary=summary,
            )

    # 6. Trigger B: In-Flight Theta Decay & Stagnation (Option Greeks-Aware Horizon)
    is_deriv_alert = bool(
        is_option
        or getattr(alert, "option_type", None)
        or getattr(alert, "contract_symbol", None)
        or getattr(alert, "alert_type", "")
        in ("OPTIONS_MOMENTUM", "GAMMA_BLAST", "OPTIONS_MOMENTUM_BREAKOUT")
    )
    if is_deriv_alert and not is_option_sell:
        created_dt = None
        clean_ts = (
            (
                getattr(alert, "original_call_time", None)
                or getattr(alert, "triggered_at", None)
                or getattr(alert, "created_at", "")
                or ""
            )
            .replace(" IST", "")
            .strip()[:19]
        )
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                created_dt = datetime.strptime(clean_ts, fmt).replace(tzinfo=IST)
                break
            except ValueError:
                pass

        if created_dt:
            now_dt = datetime.now(IST)
            if is_test_runner:
                elapsed_secs = (now_dt - created_dt).total_seconds()
            else:
                from market.calendar import get_trading_minutes_elapsed

                elapsed_secs = (
                    get_trading_minutes_elapsed(created_dt, now_dt, exchange=exch) * 60.0
                )

            # Detect 0DTE (Same-Day Expiry) status
            is_0dte = False
            clean_sym = str(getattr(alert, "symbol", "")).upper()
            exp_type = str(getattr(alert, "expiry_type", "")).upper()
            exp_raw = getattr(alert, "expiry_date", None) or (
                alert.metrics.get("expiry_date") if isinstance(alert.metrics, dict) else None
            )
            has_future_exp = False
            if exp_raw:
                for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d%b%Y"):
                    try:
                        exp_d = datetime.strptime(str(exp_raw).strip(), fmt).date()
                        if exp_d == now_dt.date():
                            is_0dte = True
                        elif exp_d > now_dt.date():
                            has_future_exp = True
                        break
                    except ValueError:
                        pass

            if not is_0dte and not has_future_exp and exp_type != "MONTHLY":
                if (
                    clean_sym in INDEX_WEEKLY_EXPIRY_WEEKDAY
                    and INDEX_WEEKLY_EXPIRY_WEEKDAY[clean_sym] == now_dt.weekday()
                ):
                    is_0dte = True
                elif getattr(alert, "dte", None) == 0 or getattr(alert, "is_0dte", False):
                    is_0dte = True

            # Dynamic Greeks-Aware Decay Horizon
            # On 0DTE after 13:30 IST, gamma flip and rapid theta acceleration demand an 8-minute exit window.
            # On 0DTE morning/midday, compress to 10 minutes. Standard weekly/monthly is 15 minutes.
            is_afternoon_0dte = is_0dte and (
                now_dt.hour > 13 or (now_dt.hour == 13 and now_dt.minute >= 30)
            )
            if is_afternoon_0dte:
                stagnation_threshold_secs = 480.0  # 8 minutes
                decay_profile = "0DTE_AFTERNOON_THETA_CLIFF"
            elif is_0dte:
                stagnation_threshold_secs = 600.0  # 10 minutes
                decay_profile = "0DTE_INTRADAY_DECAY"
            else:
                stagnation_threshold_secs = 900.0  # 15 minutes
                decay_profile = "THETA_STAGNATION"

            max_gain = float(getattr(alert, "max_potential_gain_pct", 0.0) or 0.0)
            pnl_stagnant = (pnl_pct <= 0.0) if is_0dte else (pnl_pct <= -2.0)

            if elapsed_secs >= stagnation_threshold_secs and pnl_stagnant and max_gain < 10.0:
                elapsed_mins = int(elapsed_secs // 60)
                extra_vwap = ""
                if (
                    current_vwap
                    and getattr(alert, "underlying_spot", None)
                    and alert.underlying_spot < current_vwap
                ):
                    extra_vwap = f" Spot ₹{alert.underlying_spot:,.1f} trapped below intraday VWAP ₹{current_vwap:,.1f}."

                if is_afternoon_0dte:
                    headline = f"⏳ {env_tag} IN-FLIGHT WARNING: {alert.symbol} (0DTE Theta Cliff: {elapsed_mins}m No Progress)"
                    summary = (
                        f"0DTE option position active for {elapsed_mins}m post-13:30 IST with zero momentum (P&L: {pnl_pct:+.1f}%).{extra_vwap} "
                        f"Rapid afternoon pin-risk & gamma collapse underway. "
                        f"DECISION: EXIT 0DTE OPTION IMMEDIATELY TO AVOID PIN-RISK PREMIUM EVAPORATION."
                    )
                    decision_action = "EXIT_0DTE_OPTION_IMMEDIATELY"
                elif is_0dte:
                    headline = f"⏳ {env_tag} IN-FLIGHT WARNING: {alert.symbol} (0DTE Decay: {elapsed_mins}m No Progress)"
                    summary = (
                        f"0DTE option position active for {elapsed_mins}m on expiry day with zero momentum (P&L: {pnl_pct:+.1f}%).{extra_vwap} "
                        f"Intraday theta decay accelerating before afternoon session. "
                        f"DECISION: SCRATCH / EXIT AT BREAKEVEN BEFORE AFTERNOON THETA ACCELERATION."
                    )
                    decision_action = "EXIT_0DTE_STAGNANT_OPTION"
                else:
                    headline = f"⏳ {env_tag} IN-FLIGHT WARNING: {alert.symbol} (Theta Stagnation: {elapsed_mins}m No Progress)"
                    summary = (
                        f"Option position active for {elapsed_mins}m without upside momentum (P&L: {pnl_pct:+.1f}%).{extra_vwap} "
                        f"Accelerating theta decay threatens capital. "
                        f"DECISION: SCRATCH / EXIT AT MARKET BEFORE THETA EROSION REACHES STOP-LOSS."
                    )
                    decision_action = "EXIT_STAGNANT_OPTION"

                return InFlightWarningEvaluation(
                    triggered=True,
                    warning_type=decay_profile,
                    reason=f"{decay_profile}: {elapsed_mins}m elapsed without momentum (P&L: {pnl_pct:+.1f}%).",
                    coaching_decision=decision_action,
                    current_ltp=current_ltp,
                    entry_price=entry,
                    stop_loss=stop or 0.0,
                    risk_consumed_pct=round(risk_consumed_pct, 1),
                    pnl_pct=round(pnl_pct, 1),
                    headline=headline,
                    summary=summary,
                )

    # 7. Trigger C: Institutional VWAP Band Reversion Alert (±1.0σ Band Breach)
    # Detects when underlying asset breaks below the intraday Volume-Weighted Standard Deviation floor,
    # confirming institutional order flow abandonment BEFORE nominal Stop-Loss is breached.
    spot_price = None
    if is_option:
        spot_price = getattr(alert, "underlying_spot", None) or (
            alert.metrics.get("spot") if isinstance(alert.metrics, dict) else None
        )
        if not spot_price or spot_price <= 0:
            try:
                from market.quotes import get_ltp

                lookup = f"NSE:{alert.symbol}" if ":" not in alert.symbol else alert.symbol
                spot_price = get_ltp(lookup)
            except Exception:
                pass
    else:
        spot_price = current_ltp

    effective_vwap = current_vwap
    if not effective_vwap or effective_vwap <= 0:
        if isinstance(alert.metrics, dict) and alert.metrics.get("vwap"):
            try:
                effective_vwap = float(alert.metrics["vwap"])
            except (ValueError, TypeError):
                pass
        if not effective_vwap or effective_vwap <= 0:
            try:
                from market.quotes import get_quote

                lookup = f"NSE:{alert.symbol}" if ":" not in alert.symbol else alert.symbol
                q_res = get_quote([lookup])
                if q_res and getattr(q_res.get(lookup), "vwap", 0):
                    effective_vwap = float(q_res[lookup].vwap)
            except Exception:
                pass

    if spot_price and spot_price > 0 and effective_vwap and effective_vwap > 0:
        vwap_std = 0.0
        if isinstance(alert.metrics, dict):
            vwap_std = float(
                alert.metrics.get("vwap_std") or alert.metrics.get("vwap_sigma") or 0.0
            )
        if vwap_std <= 0:
            atr_val = float(
                (alert.metrics or {}).get("atr") or (alert.metrics or {}).get("atr_14d") or 0.0
            )
            vwap_std = (atr_val * 0.50) if atr_val > 0 else (effective_vwap * 0.006)

        if is_bullish:
            lower_band = round(effective_vwap - vwap_std, 2)
            if spot_price < lower_band:
                dev_pct = round(((effective_vwap - spot_price) / effective_vwap) * 100, 2)
                headline = f"⚠️ {env_tag} IN-FLIGHT WARNING: {alert.symbol} (VWAP -1.0σ Institutional Band Breakdown)"
                summary = (
                    f"Price ₹{spot_price:,.2f} crossed below intraday VWAP -1.0σ band (₹{lower_band:,.2f}, VWAP ₹{effective_vwap:,.2f}, -{dev_pct:.1f}%). "
                    f"Institutional order flow distribution confirmed before nominal Stop-Loss (₹{stop:,.2f}) is hit. "
                    f"DECISION: SCRATCH POSITION AT MARKET OR TIGHTEN STOP TO VWAP LOWER BAND (₹{lower_band:,.2f})."
                )
                return InFlightWarningEvaluation(
                    triggered=True,
                    warning_type="VWAP_BAND_BREAKDOWN",
                    reason=f"VWAP BAND BREAKDOWN: Price ₹{spot_price:,.2f} broke below -1.0σ band (₹{lower_band:,.2f}).",
                    coaching_decision="SCRATCH_OR_TIGHTEN_TO_VWAP",
                    current_ltp=current_ltp,
                    entry_price=entry,
                    stop_loss=stop or 0.0,
                    risk_consumed_pct=round(risk_consumed_pct, 1),
                    pnl_pct=round(pnl_pct, 1),
                    headline=headline,
                    summary=summary,
                )
        else:
            upper_band = round(effective_vwap + vwap_std, 2)
            if spot_price > upper_band:
                dev_pct = round(((spot_price - effective_vwap) / effective_vwap) * 100, 2)
                headline = f"⚠️ {env_tag} IN-FLIGHT WARNING: {alert.symbol} (VWAP +1.0σ Institutional Band Breakout)"
                summary = (
                    f"Price ₹{spot_price:,.2f} surged above intraday VWAP +1.0σ band (₹{upper_band:,.2f}, VWAP ₹{effective_vwap:,.2f}, +{dev_pct:.1f}%). "
                    f"Bearish thesis invalidated by institutional buying surge before nominal Stop-Loss (₹{stop:,.2f}) is hit. "
                    f"DECISION: SCRATCH POSITION AT MARKET OR TIGHTEN STOP TO VWAP UPPER BAND (₹{upper_band:,.2f})."
                )
                return InFlightWarningEvaluation(
                    triggered=True,
                    warning_type="VWAP_BAND_BREAKDOWN",
                    reason=f"VWAP BAND BREAKOUT: Price ₹{spot_price:,.2f} broke above +1.0σ band (₹{upper_band:,.2f}).",
                    coaching_decision="SCRATCH_OR_TIGHTEN_TO_VWAP",
                    current_ltp=current_ltp,
                    entry_price=entry,
                    stop_loss=stop or 0.0,
                    risk_consumed_pct=round(risk_consumed_pct, 1),
                    pnl_pct=round(pnl_pct, 1),
                    headline=headline,
                    summary=summary,
                )

    return None
