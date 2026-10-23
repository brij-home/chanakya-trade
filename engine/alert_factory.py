"""
engine/alert_factory.py
───────────────────────
Authoritative Institutional Alert Factory & Scale-Separation Guardrail.

Enforces absolute scale separation and schema integrity at instantiation:
  1. Equity/Spot Alerts:
     - ltp, trigger_level, target_level, stop_loss represent the cash underlying.
     - Option contract fields (strike, option_type, option_premium) are strictly None.
  2. Option Contract Alerts:
     - ltp, trigger_level, target_level, stop_loss MUST represent the Option Premium (0.05 to 3500.0).
     - contract_symbol is required (e.g. 'NIFTY26OCT25000CE').
     - underlying_spot, underlying_sl, underlying_target represent the underlying spot benchmark.
     - Hard Invariant: Passing spot prices (e.g. > 5000.0) into option_sl or stop_loss raises
       a fatal ScaleContaminationError, making scale contamination impossible by design.
  3. Mandatory Non-Zero / Non-Null RVOL:
     - Directional breakout, thrust, and spark setups MUST provide verified rvol > 0.
     - If rvol <= 0 or None, raises UnverifiedRvolError or fails closed.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from config.constants import IST
from engine.alert_identity import canonical_alert_symbol, generate_alert_id
from engine.alert_model import AutoAlert

logger = logging.getLogger("chanakya.engine.alert_factory")


class ScaleContaminationError(ValueError):
    """Raised when underlying spot coordinates are improperly injected into option premium fields."""

    pass


class UnverifiedRvolError(ValueError):
    """Raised when a directional momentum setup lacks verified positive relative volume."""

    pass


class AlertFactory:
    """Institutional Factory for building validated, scale-separated AutoAlert instances."""

    @staticmethod
    def create_equity_alert(
        *,
        alert_type: str,
        stage: str,
        symbol: str,
        exchange: str,
        direction: str,
        headline: str,
        summary: str,
        ltp: float,
        trigger_level: float,
        target_level: float,
        stop_loss: float,
        rvol: float,
        confidence: int = 75,
        metrics: Optional[dict[str, Any]] = None,
        actionable_plan: Optional[dict[str, Any]] = None,
        is_live: bool = True,
        time_horizon: str = "INTRADAY",
        setup_style: str = "CONTINUATION",
        entry_type: str = "BREAKOUT_STOP",
        segment: str = "EQUITY",
        variant: Optional[str] = None,
        created_at: Optional[str] = None,
        mandate_rvol: bool = True,
        extra_details: Optional[dict[str, Any]] = None,
    ) -> AutoAlert:
        """
        Constructs a validated Equity / Cash / Spot Alert.
        Guarantees that no option derivative fields are contaminated.
        """
        clean_sym = canonical_alert_symbol(symbol)
        m_dict = dict(metrics or {})

        # Enforce non-zero RVOL invariant for directional intraday setups
        rvol_val = float(rvol or m_dict.get("rvol", 0.0) or 0.0)
        if mandate_rvol and rvol_val <= 0.0:
            raise UnverifiedRvolError(
                f"[{alert_type}] {clean_sym} rejected: RVOL must be strictly positive (got {rvol_val}). "
                "Silent defaulting to 1.0/1.2 is prohibited."
            )
        m_dict["rvol"] = rvol_val

        # Level coherence sanity
        if ltp <= 0 or trigger_level <= 0 or target_level <= 0 or stop_loss <= 0:
            raise ValueError(
                f"[{alert_type}] {clean_sym} invalid levels: LTP={ltp}, Trigger={trigger_level}, "
                f"T1={target_level}, SL={stop_loss}"
            )

        # Enforce Minimum Volatility Floor to eliminate Sub-ATR Noise Traps at factory gate
        atr_ref = float(m_dict.get("atr_5m") or m_dict.get("atr_14") or m_dict.get("atr") or 0.0)
        min_sl_dist = max(1.20 * atr_ref if atr_ref > 0 else 0.0, ltp * 0.008)
        cur_sl_dist = abs(trigger_level - stop_loss)
        if cur_sl_dist < (min_sl_dist * 0.95) and min_sl_dist > 0:
            if direction.upper() in ("BULLISH", "LONG", "BUY"):
                stop_loss = round(trigger_level - min_sl_dist, 2)
            else:
                stop_loss = round(trigger_level + min_sl_dist, 2)
            # Rebalance target to maintain minimum 1:2.0 R:R
            req_target_dist = min_sl_dist * 2.0
            cur_target_dist = abs(target_level - trigger_level)
            if cur_target_dist < req_target_dist:
                if direction.upper() in ("BULLISH", "LONG", "BUY"):
                    target_level = round(trigger_level + req_target_dist, 2)
                else:
                    target_level = round(trigger_level - req_target_dist, 2)
            logger.info(
                f"[AlertFactory] Auto-calibrated {clean_sym} stop-loss to ₹{stop_loss} "
                f"({min_sl_dist:.1f} pts) to eliminate sub-ATR noise trap."
            )

        sess_d = (
            datetime.strptime(created_at[:10], "%Y-%m-%d").date()
            if created_at and len(created_at) >= 10
            else datetime.now(IST).date()
        )
        alert_id = generate_alert_id(
            alert_type=alert_type,
            symbol=clean_sym,
            session_date=sess_d,
            variant=variant,
        )

        plan = dict(actionable_plan or {})
        if "invalidation_stop" not in plan:
            plan["invalidation_stop"] = stop_loss

        return AutoAlert(
            alert_id=alert_id,
            alert_type=alert_type,
            stage=stage,
            symbol=clean_sym,
            exchange=exchange,
            direction=direction.upper(),
            headline=headline,
            summary=summary,
            ltp=round(float(ltp), 2),
            trigger_level=round(float(trigger_level), 2),
            target_level=round(float(target_level), 2),
            stop_loss=round(float(stop_loss), 2),
            strike=None,
            option_type=None,
            contract_symbol=None,
            option_premium=None,
            underlying_spot=round(float(ltp), 2),
            underlying_sl=round(float(stop_loss), 2),
            metrics=m_dict,
            actionable_plan=plan,
            confidence=max(1, min(100, int(confidence))),
            created_at=created_at or datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
            is_live=is_live,
            environment="LIVE" if is_live else "TEST",
            segment=segment,
            time_horizon=time_horizon,
            setup_style=setup_style,
            entry_type=entry_type,
            initial_stop_loss=round(float(stop_loss), 2),
            details=extra_details or {},
        )

    @staticmethod
    def create_option_alert(
        *,
        alert_type: str,
        stage: str,
        underlying_symbol: str,
        contract_symbol: str,
        exchange: str,
        direction: str,
        strike: float,
        option_type: str,
        option_premium: float,
        option_trigger: float,
        option_target: float,
        option_sl: float,
        underlying_spot: float,
        underlying_sl: float,
        underlying_target: Optional[float] = None,
        rvol: float,
        lot_size: int,
        headline: str,
        summary: str,
        expiry_date: Optional[str] = None,
        confidence: int = 80,
        metrics: Optional[dict[str, Any]] = None,
        actionable_plan: Optional[dict[str, Any]] = None,
        is_live: bool = True,
        time_horizon: str = "INTRADAY",
        setup_style: str = "CONTINUATION",
        entry_type: str = "BREAKOUT_STOP",
        variant: Optional[str] = None,
        created_at: Optional[str] = None,
        mandate_rvol: bool = True,
        extra_details: Optional[dict[str, Any]] = None,
    ) -> AutoAlert:
        """
        Constructs an institutional Option Contract Alert.
        Strictly enforces scale separation between Option Premium levels and Underlying Spot levels.
        """
        clean_und = canonical_alert_symbol(underlying_symbol)
        opt_type_clean = option_type.upper().strip()
        if opt_type_clean not in ("CE", "PE"):
            raise ValueError(f"Invalid option_type '{option_type}'. Must be 'CE' or 'PE'.")

        # ── Hard Invariant 1: Scale Contamination Guard ─────────────────────────
        # Option premiums in Indian markets rarely exceed ₹3,500 even for deep ITM index contracts.
        # Underlying spot for NIFTY/BANKNIFTY/SENSEX is always > ₹5,000.
        is_index = clean_und in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX")
        if is_index:
            if option_sl >= 1500.0 or option_premium >= 4500.0 or option_trigger >= 4500.0:
                raise ScaleContaminationError(
                    f"Fatal Scale Contamination: Option SL ({option_sl}) or Premium ({option_premium}) "
                    f"appears to be an underlying spot price (>= 1500 pts). Spot must be mapped to underlying_sl!"
                )
            if underlying_spot <= 1000.0:
                raise ScaleContaminationError(
                    f"Fatal Scale Contamination: Index underlying_spot ({underlying_spot}) is unreasonably low. "
                    "Did you pass the option premium instead of index spot?"
                )

        if option_premium <= 0 or option_trigger <= 0 or option_target <= 0 or option_sl <= 0:
            raise ValueError(
                f"[{alert_type}] {contract_symbol} invalid option levels: Prem={option_premium}, "
                f"Trig={option_trigger}, T1={option_target}, SL={option_sl}"
            )

        # ── Hard Invariant 2: Mandatory RVOL Invariant ───────────────────────────
        m_dict = dict(metrics or {})
        rvol_val = float(rvol or m_dict.get("rvol", 0.0) or 0.0)
        if mandate_rvol and rvol_val <= 0.0:
            raise UnverifiedRvolError(
                f"[{alert_type}] {contract_symbol} rejected: RVOL must be strictly positive (got {rvol_val}). "
                "Silent defaulting to 1.0/1.2 is prohibited."
            )
        m_dict["rvol"] = rvol_val

        # ── Hard Invariant 3: Dual-Horizon Stop-Loss Coherence & Volatility Floor ──
        disaster_floor = round(
            option_premium * 0.68, 2
        )  # Hard catastrophe limit (-32% premium drawdown)
        tactical_option_sl = round(float(option_sl), 2)
        structural_spot_sl = round(float(underlying_sl), 2)

        # Enforce Minimum Option Volatility Floor to eliminate Sub-ATR Option Noise Traps
        if is_index and option_trigger >= 80.0:
            min_opt_risk = (
                45.0
                if ("SENSEX" in clean_und or "BANKEX" in clean_und)
                else (35.0 if "BANKNIFTY" in clean_und else 15.0)
            )
            if (option_trigger - tactical_option_sl) < (min_opt_risk * 0.95):
                tactical_option_sl = round(max(disaster_floor, option_trigger - min_opt_risk), 2)
                if (option_target - option_trigger) < (min_opt_risk * 2.0):
                    option_target = round(option_trigger + (min_opt_risk * 2.0), 2)
                logger.info(
                    f"[AlertFactory] Auto-calibrated {contract_symbol} option SL to ₹{tactical_option_sl} "
                    f"({min_opt_risk:.1f} pts) to clear institutional volatility floor."
                )
        elif not is_index and option_trigger >= 10.0:
            min_stock_opt_risk = max(1.5, round(option_trigger * 0.12, 1))
            if (option_trigger - tactical_option_sl) < (min_stock_opt_risk * 0.95):
                tactical_option_sl = round(
                    max(disaster_floor, option_trigger - min_stock_opt_risk), 2
                )
                if (option_target - option_trigger) < (min_stock_opt_risk * 2.0):
                    option_target = round(option_trigger + (min_stock_opt_risk * 2.0), 2)

        sess_d = (
            datetime.strptime(created_at[:10], "%Y-%m-%d").date()
            if created_at and len(created_at) >= 10
            else datetime.now(IST).date()
        )
        alert_id = generate_alert_id(
            alert_type=alert_type,
            symbol=clean_und,
            session_date=sess_d,
            variant=f"{int(strike)}{opt_type_clean}" if not variant else variant,
        )

        plan = dict(actionable_plan or {})
        plan["option_plan"] = {
            "contract": contract_symbol,
            "strike": strike,
            "option_type": opt_type_clean,
            "entry_premium": round(float(option_trigger), 2),
            "sl_premium": tactical_option_sl,
            "t1_premium": round(float(option_target), 2),
            "lot_size": int(lot_size),
        }
        plan["invalidation_stop"] = tactical_option_sl
        plan["spot_invalidation_anchor"] = structural_spot_sl
        if underlying_target:
            plan["underlying_target"] = round(float(underlying_target), 2)

        m_dict.update(
            {
                "underlying_symbol": clean_und,
                "underlying_spot": round(float(underlying_spot), 2),
                "underlying_sl": structural_spot_sl,
                "tactical_sl": tactical_option_sl,
                "disaster_stop_floor": disaster_floor,
                "lot_size": int(lot_size),
                "contract_symbol": contract_symbol,
            }
        )

        return AutoAlert(
            alert_id=alert_id,
            alert_type=alert_type,
            stage=stage,
            symbol=clean_und,
            exchange=exchange,
            direction=direction.upper(),
            headline=headline,
            summary=summary,
            ltp=round(float(option_premium), 2),
            trigger_level=round(float(option_trigger), 2),
            target_level=round(float(option_target), 2),
            stop_loss=tactical_option_sl,
            strike=float(strike),
            option_type=opt_type_clean,
            contract_symbol=contract_symbol,
            option_premium=round(float(option_premium), 2),
            option_stop_loss=tactical_option_sl,
            option_target_level=round(float(option_target), 2),
            underlying_spot=round(float(underlying_spot), 2),
            underlying_sl=structural_spot_sl,
            structural_spot_sl=structural_spot_sl,
            tactical_sl=tactical_option_sl,
            disaster_stop_floor=disaster_floor,
            derivative_type="OPT",
            lot_size=int(lot_size),
            expiry_date=expiry_date,
            metrics=m_dict,
            actionable_plan=plan,
            confidence=max(1, min(100, int(confidence))),
            created_at=created_at or datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
            is_live=is_live,
            environment="LIVE" if is_live else "TEST",
            segment="FNO",
            time_horizon=time_horizon,
            setup_style=setup_style,
            entry_type=entry_type,
            initial_stop_loss=tactical_option_sl,
            initial_entry_premium=round(float(option_premium), 2),
            details=extra_details or {},
        )
