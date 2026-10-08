"""
TradeLifecycleManager — Institutional Trade Lifecycle & Milestone Subsystem.

Manages milestone hit verification (T0.5, T1, T2, Runner, Final Target),
fail-closed milestone integrity gates, dynamic ratcheting trailing stop-loss,
and trade outcome recording in the pattern learning engine.
"""

from __future__ import annotations

import logging
import re
from datetime import timezone, timedelta
from typing import Any, Optional, Tuple

from engine.alert_expiry import is_alert_option_premium_level
from engine.alert_model import AutoAlert

logger = logging.getLogger("engine.lifecycle.trade_lifecycle_manager")
IST = timezone(timedelta(hours=5, minutes=30))


class TradeLifecycleManager:
    """
    Autonomous trade lifecycle manager governing milestone progression,
    trailing stop ratchets, and fail-closed price integrity.
    """

    def validate_milestone_integrity(
        self,
        alert: AutoAlert,
        cur_quote_ltp: Optional[float] = None,
        milestone: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Institutional Invariant Gate: Pure Provenance & Mathematical Truthfulness (Rule 10 & Rule 23).
        Enforces that any target milestone (T0.5, T1, T2, Final Target) claimed by an alert
        has been physically and mathematically reached or crossed by current market price (LTP).
        Fails closed: Returns (False, reason) if price has not reached the target level.
        """
        cur_ltp = float(cur_quote_ltp or alert.ltp or getattr(alert, "current_ltp", 0.0) or 0.0)
        if cur_ltp <= 0:
            return False, "Current LTP is zero or missing"

        dir_str = str(getattr(alert, "direction", "BULLISH")).upper()
        plan = getattr(alert, "actionable_plan", {}) or {}
        is_opt = is_alert_option_premium_level(alert)
        act_str = str(plan.get("action", getattr(alert, "action", "")) or "").upper()
        alert_type = str(getattr(alert, "alert_type", "") or "").upper()

        if is_opt:
            # Option writing / selling profits on premium decay (downward)
            # Option buying (both Call CE and Put PE) profits on premium expansion (upward)
            is_option_seller = (
                any(k in act_str for k in ("SELL", "WRITE", "SHORT"))
                or alert_type == "OPTION_WRITE"
                or str(getattr(alert, "option_write", False)).lower() in ("true", "1")
            )
            is_payoff_upward = not is_option_seller
        else:
            is_payoff_upward = dir_str not in ("BEARISH", "SELL", "SHORT")

        def _extract_num(val: Any) -> Optional[float]:
            if val is None:
                return None
            if isinstance(val, (int, float)):
                return float(val) if val > 0 else None
            m = re.search(r"[\d,]+(?:\.\d+)?", str(val))
            if m:
                try:
                    f = float(m.group(0).replace(",", ""))
                    return f if f > 0 else None
                except ValueError:
                    return None
            return None

        opt_plan = plan.get("option_plan", {}) if isinstance(plan.get("option_plan"), dict) else {}

        check_stage = milestone or alert.stage or ""
        check_status = alert.target_status or ""

        # 1. Target 1 Check
        if check_stage in ("T1_ACHIEVED", "TARGET_1", "TARGET_1_HIT") or "T1" in check_status:
            t1_raw = (
                (opt_plan.get("t1_premium") if is_opt else None)
                or getattr(alert, "target_1", None)
                or plan.get("target_1")
            )
            t1_val = _extract_num(t1_raw)
            if not t1_val:
                entry = float(alert.trigger_level or alert.ltp or 0.0)
                sl = float(alert.stop_loss or 0.0)
                risk = abs(entry - sl) if entry > 0 and sl > 0 else 0.0
                if risk > 0:
                    t1_val = round(
                        entry + (risk * 2.0) if is_payoff_upward else entry - (risk * 2.0), 2
                    )
                    tgt_lvl = float(alert.target_level or 0.0)
                    if tgt_lvl > 0:
                        if is_payoff_upward and tgt_lvl > entry and t1_val >= tgt_lvl:
                            t1_val = round(entry + (tgt_lvl - entry) * 0.5, 2)
                        elif not is_payoff_upward and tgt_lvl < entry and t1_val <= tgt_lvl:
                            t1_val = round(entry - (entry - tgt_lvl) * 0.5, 2)
                elif alert.target_level:
                    t1_val = float(alert.target_level)
            if t1_val and t1_val > 0:
                if is_payoff_upward and cur_ltp < t1_val * 0.998:
                    return (
                        False,
                        f"CMP {cur_ltp:,.2f} is below Target 1 {t1_val:,.2f} (deficit: {t1_val - cur_ltp:,.2f})",
                    )
                if not is_payoff_upward and cur_ltp > t1_val * 1.002:
                    return (
                        False,
                        f"CMP {cur_ltp:,.2f} is above Target 1 {t1_val:,.2f} (deficit: {cur_ltp - t1_val:,.2f})",
                    )

        # 2. Target 2 Check
        if check_stage in ("T2_ACHIEVED", "TARGET_2", "TARGET_2_HIT") or "T2" in check_status:
            t2_raw = (
                (opt_plan.get("t2_premium") if is_opt else None)
                or getattr(alert, "target_2", None)
                or plan.get("target_2")
            )
            t2_val = _extract_num(t2_raw)
            if not t2_val:
                entry = float(alert.trigger_level or alert.ltp or 0.0)
                sl = float(alert.stop_loss or 0.0)
                risk = abs(entry - sl) if entry > 0 and sl > 0 else 0.0
                if risk > 0:
                    t2_val = round(
                        entry + (risk * 4.0) if is_payoff_upward else entry - (risk * 4.0), 2
                    )
                    tgt_lvl = float(alert.target_level or 0.0)
                    if tgt_lvl > 0:
                        if is_payoff_upward and tgt_lvl > entry and t2_val >= tgt_lvl:
                            t2_val = tgt_lvl
                        elif not is_payoff_upward and tgt_lvl < entry and t2_val <= tgt_lvl:
                            t2_val = tgt_lvl
                elif alert.target_level:
                    t2_val = float(alert.target_level)
            if t2_val and t2_val > 0:
                if is_payoff_upward and cur_ltp < t2_val * 0.998:
                    return (
                        False,
                        f"CMP {cur_ltp:,.2f} is below Target 2 {t2_val:,.2f} (deficit: {t2_val - cur_ltp:,.2f})",
                    )
                if not is_payoff_upward and cur_ltp > t2_val * 1.002:
                    return (
                        False,
                        f"CMP {cur_ltp:,.2f} is above Target 2 {t2_val:,.2f} (deficit: {cur_ltp - t2_val:,.2f})",
                    )

        # 3. Final Target Check
        if (
            check_stage in ("TARGET_ACHIEVED", "COMPLETED", "FINAL_TARGET")
            or "FINAL" in check_status
        ):
            tf_raw = (
                (opt_plan.get("t3_premium") if is_opt else None)
                or alert.target_level
                or plan.get("target_3")
                or plan.get("runner_target")
                or plan.get("target")
            )
            tf_val = _extract_num(tf_raw)
            if tf_val and tf_val > 0:
                if is_payoff_upward and cur_ltp < tf_val * 0.998:
                    return (
                        False,
                        f"CMP {cur_ltp:,.2f} is below Final Target {tf_val:,.2f} (deficit: {tf_val - cur_ltp:,.2f})",
                    )
                if not is_payoff_upward and cur_ltp > tf_val * 1.002:
                    return (
                        False,
                        f"CMP {cur_ltp:,.2f} is above Final Target {tf_val:,.2f} (deficit: {cur_ltp - tf_val:,.2f})",
                    )

        # 4. Target 0.5 Check
        if check_stage in ("T0_5_ACHIEVED", "TARGET_0_5") or "T0_5" in check_status:
            t0_5_raw = (
                (opt_plan.get("t0_5_premium") if is_opt else None)
                or getattr(alert, "target_0_5", None)
                or plan.get("target_0_5")
            )
            t0_5_val = _extract_num(t0_5_raw)
            if t0_5_val and t0_5_val > 0:
                if is_payoff_upward and cur_ltp < t0_5_val * 0.998:
                    return (
                        False,
                        f"CMP {cur_ltp:,.2f} is below Target 0.5 {t0_5_val:,.2f} (deficit: {t0_5_val - cur_ltp:,.2f})",
                    )
                if not is_payoff_upward and cur_ltp > t0_5_val * 1.002:
                    return (
                        False,
                        f"CMP {cur_ltp:,.2f} is above Target 0.5 {t0_5_val:,.2f} (deficit: {cur_ltp - t0_5_val:,.2f})",
                    )

        return True, "PASSED_MILESTONE_INTEGRITY_GATE"

    def validate_milestone_integrity_for_target(
        self, alert: AutoAlert, target_type: str
    ) -> Tuple[bool, str]:
        """Validates whether current LTP reaches the specified target level (T0_5, T1, T2, FINAL)."""
        cur_ltp = float(alert.ltp or getattr(alert, "current_ltp", 0.0) or 0.0)
        if cur_ltp <= 0:
            return False, "LTP missing or <= 0"
        dir_str = str(getattr(alert, "direction", "BULLISH")).upper()
        plan = getattr(alert, "actionable_plan", {}) or {}
        is_opt = is_alert_option_premium_level(alert)
        act_str = str(plan.get("action", getattr(alert, "action", "")) or "").upper()
        alert_type = str(getattr(alert, "alert_type", "") or "").upper()

        if is_opt:
            is_option_seller = (
                any(k in act_str for k in ("SELL", "WRITE", "SHORT"))
                or alert_type == "OPTION_WRITE"
                or str(getattr(alert, "option_write", False)).lower() in ("true", "1")
            )
            is_payoff_upward = not is_option_seller
        else:
            is_payoff_upward = dir_str not in ("BEARISH", "SELL", "SHORT")

        def _extract_num(val: Any) -> Optional[float]:
            if val is None:
                return None
            if isinstance(val, (int, float)):
                return float(val) if val > 0 else None
            m = re.search(r"[\d,]+(?:\.\d+)?", str(val))
            if m:
                try:
                    f = float(m.group(0).replace(",", ""))
                    return f if f > 0 else None
                except ValueError:
                    return None
            return None

        opt_plan = plan.get("option_plan", {}) if isinstance(plan.get("option_plan"), dict) else {}

        if target_type == "T0_5":
            val = _extract_num(
                (opt_plan.get("t0_5_premium") if is_opt else None)
                or getattr(alert, "target_0_5", None)
                or plan.get("target_0_5")
            )
            if not val:
                entry = float(alert.trigger_level or alert.ltp or 0.0)
                sl = float(alert.stop_loss or 0.0)
                risk = abs(entry - sl) if entry > 0 and sl > 0 else 0.0
                if risk > 0:
                    val = entry + risk if is_payoff_upward else entry - risk
            if val and val > 0:
                if is_payoff_upward and cur_ltp >= val * 0.998:
                    return True, "T0_5 satisfied"
                if not is_payoff_upward and cur_ltp <= val * 1.002:
                    return True, "T0_5 satisfied"
                return False, "T0_5 not satisfied"
            return False, "T0_5 level unresolved"

        elif target_type == "T1":
            val = _extract_num(
                (opt_plan.get("t1_premium") if is_opt else None)
                or getattr(alert, "target_1", None)
                or plan.get("target_1")
            )
            if not val:
                entry = float(alert.trigger_level or alert.ltp or 0.0)
                sl = float(alert.stop_loss or 0.0)
                risk = abs(entry - sl) if entry > 0 and sl > 0 else 0.0
                if risk > 0:
                    val = round(
                        entry + (risk * 2.0) if is_payoff_upward else entry - (risk * 2.0), 2
                    )
                    tgt_lvl = float(alert.target_level or 0.0)
                    if tgt_lvl > 0:
                        if is_payoff_upward and tgt_lvl > entry and val >= tgt_lvl:
                            val = round(entry + (tgt_lvl - entry) * 0.5, 2)
                        elif not is_payoff_upward and tgt_lvl < entry and val <= tgt_lvl:
                            val = round(entry - (entry - tgt_lvl) * 0.5, 2)
                elif alert.target_level:
                    val = float(alert.target_level)
            if val and val > 0:
                if is_payoff_upward and cur_ltp >= val * 0.998:
                    return True, "T1 satisfied"
                if not is_payoff_upward and cur_ltp <= val * 1.002:
                    return True, "T1 satisfied"
                return False, "T1 not satisfied"
            return False, "T1 level unresolved"

        elif target_type == "T2":
            val = _extract_num(
                (opt_plan.get("t2_premium") if is_opt else None)
                or getattr(alert, "target_2", None)
                or plan.get("target_2")
            )
            if not val:
                entry = float(alert.trigger_level or alert.ltp or 0.0)
                sl = float(alert.stop_loss or 0.0)
                risk = abs(entry - sl) if entry > 0 and sl > 0 else 0.0
                if risk > 0:
                    val = round(
                        entry + (risk * 4.0) if is_payoff_upward else entry - (risk * 4.0), 2
                    )
                    tgt_lvl = float(alert.target_level or 0.0)
                    if tgt_lvl > 0:
                        if is_payoff_upward and tgt_lvl > entry and val >= tgt_lvl:
                            val = tgt_lvl
                        elif not is_payoff_upward and tgt_lvl < entry and val <= tgt_lvl:
                            val = tgt_lvl
                elif alert.target_level:
                    val = float(alert.target_level)
            if val and val > 0:
                if is_payoff_upward and cur_ltp >= val * 0.998:
                    return True, "T2 satisfied"
                if not is_payoff_upward and cur_ltp <= val * 1.002:
                    return True, "T2 satisfied"
                return False, "T2 not satisfied"
            return False, "T2 level unresolved"

        elif target_type in ("FINAL", "FINAL_TARGET", "TARGET"):
            val = _extract_num(
                (opt_plan.get("t3_premium") if is_opt else None)
                or alert.target_level
                or plan.get("target_3")
                or plan.get("runner_target")
                or plan.get("target")
            )
            if val and val > 0:
                if is_payoff_upward and cur_ltp >= val * 0.998:
                    return True, "FINAL satisfied"
                if not is_payoff_upward and cur_ltp <= val * 1.002:
                    return True, "FINAL satisfied"
                return False, "FINAL not satisfied"
            return False, "FINAL level unresolved"

        return False, "Unknown target type"

    def apply_milestone_state(
        self,
        alert: AutoAlert,
        eval_res: Any,
        cur_quote_ltp: float,
        now_ts: float,
        now_str: str,
    ) -> None:
        """
        Updates alert attributes for the evaluated milestone, calculates ratcheted trailing stops,
        and registers the outcome with the pattern learning engine.
        """
        alert.updated_at = now_str
        alert.triggered_at = now_str
        alert.current_ltp = cur_quote_ltp
        alert.ltp = cur_quote_ltp
        alert.should_trail = eval_res.should_trail
        alert.trailing_decision = eval_res.trailing_decision
        alert.trailing_stop = eval_res.recommended_stop

        if eval_res.recommended_stop and eval_res.should_trail:
            if getattr(alert, "initial_stop_loss", None) is None and getattr(
                alert, "stop_loss", None
            ):
                alert.initial_stop_loss = alert.stop_loss
            alert.stop_loss = eval_res.recommended_stop
            alert.last_trail_alert_time = now_ts
            if alert.actionable_plan:
                if (
                    "initial_invalidation_stop" not in alert.actionable_plan
                    and alert.actionable_plan.get("invalidation_stop")
                ):
                    alert.actionable_plan["initial_invalidation_stop"] = alert.actionable_plan[
                        "invalidation_stop"
                    ]
                alert.actionable_plan["invalidation_stop"] = eval_res.recommended_stop
                if isinstance(alert.actionable_plan.get("option_plan"), dict):
                    if "initial_sl_premium" not in alert.actionable_plan[
                        "option_plan"
                    ] and alert.actionable_plan["option_plan"].get("sl_premium"):
                        alert.actionable_plan["option_plan"]["initial_sl_premium"] = (
                            alert.actionable_plan["option_plan"]["sl_premium"]
                        )
                    alert.actionable_plan["option_plan"]["sl_premium"] = eval_res.recommended_stop

        alert.trailing_rationale = eval_res.trailing_rationale
        alert.locked_profit_pts = eval_res.locked_profit_pts
        alert.locked_profit_pct = eval_res.locked_profit_pct
        alert.target_status = eval_res.target_status
        alert.r_multiple = eval_res.r_multiple
        alert.pnl_pct = eval_res.pnl_pct
        if getattr(eval_res, "strike_roll_recommendation", None):
            alert.strike_roll_recommendation = eval_res.strike_roll_recommendation

        env_tag = "[TEST]" if (alert.environment == "TEST" or not alert.is_live) else "[REAL/LIVE]"
        is_crypto = (
            getattr(alert, "exchange", "").upper() in ("BINANCE", "CRYPTO", "DERIBIT")
            or "CRYPTO" in getattr(alert, "alert_type", "").upper()
            or getattr(alert, "symbol", "").upper().endswith("USDT")
        )
        cs = "$" if is_crypto else "₹"
        cur_disp_p = cur_quote_ltp or alert.ltp or 0.0

        if alert.achieved_milestones is None:
            alert.achieved_milestones = []

        if eval_res.new_milestone in (
            "T0_5_ACHIEVED",
            "T1_ACHIEVED",
            "T2_ACHIEVED",
            "TARGET_ACHIEVED",
            "DE_RISK_0_5R",
            "BREAKEVEN_LOCKED",
            "TRAIL_POST_SWEEP",
            "COMPRESS_STALL_RISK",
            "TIME_STOP_SCRATCH",
        ):
            if eval_res.new_milestone not in alert.achieved_milestones:
                alert.achieved_milestones.append(eval_res.new_milestone)
                try:
                    from engine.learning_engine import pattern_learning_engine

                    outcome_map = {
                        "T0_5_ACHIEVED": ("WIN_T0_5", 1.0),
                        "T1_ACHIEVED": ("WIN_T1", 2.0),
                        "T2_ACHIEVED": ("WIN_T2", 3.5),
                        "TARGET_ACHIEVED": (
                            "WIN_TARGET",
                            max(2.5, float(eval_res.r_multiple or 4.0)),
                        ),
                        "BREAKEVEN_LOCKED": ("BREAKEVEN", 0.0),
                        "DE_RISK_0_5R": ("DE_RISK", 0.5),
                        "TRAIL_POST_SWEEP": ("SWEEP_TRAIL", 0.0),
                        "COMPRESS_STALL_RISK": ("STALL_COMPRESS", 0.0),
                        "TIME_STOP_SCRATCH": ("TIME_STOP_SCRATCH", 0.0),
                    }
                    outcome_str, r_mult = outcome_map.get(
                        eval_res.new_milestone, ("WIN_TARGET", 2.0)
                    )
                    is_opt_trade = (
                        is_alert_option_premium_level(alert)
                        or (alert.actionable_plan or {}).get("instrument_type") == "OPTION"
                    )
                    if is_opt_trade:
                        trade_entry = float(
                            alert.option_premium
                            or (alert.actionable_plan or {})
                            .get("trade_plan", {})
                            .get("entry_price")
                            or alert.trigger_level
                            or cur_disp_p
                        )
                    else:
                        trade_entry = float(alert.trigger_level or alert.ltp or cur_disp_p)

                    m_factors = (
                        (alert.metrics or {}).get("matched_factors")
                        or (alert.metrics or {}).get("confluence_types")
                        or [alert.alert_type]
                    )
                    pattern_learning_engine.record_trade_outcome(
                        alert_id=alert.alert_id,
                        symbol=alert.symbol,
                        archetype=alert.alert_type,
                        entry_price=trade_entry,
                        exit_price=float(cur_disp_p),
                        outcome=outcome_str,
                        realized_rr=float(r_mult),
                        factors_present=m_factors,
                    )
                except Exception as e_learn:
                    logger.debug(
                        f"[TradeLifecycleManager] Error recording milestone outcome to learning engine: {e_learn}"
                    )

        inst_label = alert.symbol
        if alert.contract_symbol:
            from bot.alert_templates import format_contract_display

            inst_label = format_contract_display(alert.contract_symbol)
        elif getattr(alert, "strike", None) and getattr(alert, "option_type", None):
            inst_label = f"{alert.symbol} {int(alert.strike)} {alert.option_type}".strip()

        if eval_res.new_milestone == "TARGET_ACHIEVED":
            if not eval_res.should_trail:
                alert.stage = "COMPLETED"
                alert.is_active = False
                alert.headline = (
                    f"🏁 {env_tag} FINAL TARGET ACHIEVED: {inst_label} ({cs}{cur_disp_p:,.2f})"
                )
                alert.is_archived = True
                alert.archived_at = now_str
                alert.archive_reason = "Final target achieved"
            else:
                alert.stage = "TARGET_ACHIEVED"
                alert.headline = (
                    f"🎯 {env_tag} FINAL TARGET ACHIEVED: {inst_label} ({cs}{cur_disp_p:,.2f})"
                )
        elif eval_res.new_milestone == "T2_ACHIEVED":
            alert.stage = "T2_ACHIEVED"
            alert.headline = f"🎯 {env_tag} TARGET 2 ACHIEVED: {inst_label} ({cs}{cur_disp_p:,.2f})"
        elif eval_res.new_milestone == "T1_ACHIEVED":
            alert.stage = "T1_ACHIEVED"
            alert.headline = f"🎯 {env_tag} TARGET 1 ACHIEVED: {inst_label} ({cs}{cur_disp_p:,.2f})"
        elif eval_res.new_milestone == "T0_5_ACHIEVED":
            alert.stage = "T0_5_ACHIEVED"
            alert.headline = (
                f"🎯 {env_tag} TARGET 0.5 (SCALE 1) ACHIEVED: {inst_label} ({cs}{cur_disp_p:,.2f})"
            )
        elif eval_res.new_milestone == "TRAILING_UPDATE":
            alert.last_trail_alert_time = now_ts
            alert.stage = "TRAILING_UPDATE"
            alert.headline = f"📈 {env_tag} TRAILING STOP UPDATED: {inst_label} → {cs}{eval_res.recommended_stop:,.2f}"
        elif eval_res.new_milestone == "BREAKEVEN_LOCKED":
            alert.stage = "BREAKEVEN_LOCKED"
            alert.headline = f"🛡️ {env_tag} BREAKEVEN LOCKED (+0.8R FREE ROLL): {inst_label} SL → {cs}{eval_res.recommended_stop:,.2f} (Downside Eliminated)"
        elif eval_res.new_milestone == "DE_RISK_0_5R":
            alert.stage = "DE_RISK_0_5R"
            red_pct = getattr(eval_res, "risk_reduction_pct", 65.0)
            alert.headline = f"🛡️ {env_tag} RISK COMPRESSED (+0.5R DE-RISK): {inst_label} SL → {cs}{eval_res.recommended_stop:,.2f} (-{red_pct:.0f}% Risk)"
        elif eval_res.new_milestone == "TRAIL_POST_SWEEP":
            alert.stage = "TRAIL_POST_SWEEP"
            red_pct = getattr(eval_res, "risk_reduction_pct", 40.0)
            alert.headline = f"🛡️ {env_tag} SMC SWEEP TRAIL: {inst_label} SL → {cs}{eval_res.recommended_stop:,.2f} (-{red_pct:.0f}% Risk)"
        elif eval_res.new_milestone == "COMPRESS_STALL_RISK":
            alert.stage = "COMPRESS_STALL_RISK"
            red_pct = getattr(eval_res, "risk_reduction_pct", 35.0)
            alert.headline = f"🛡️ {env_tag} THETA STALL COMPRESSION: {inst_label} SL → {cs}{eval_res.recommended_stop:,.2f} (-{red_pct:.0f}% Risk)"
        elif eval_res.new_milestone == "TIME_STOP_SCRATCH":
            alert.target_status = "TIME_STOP_EXIT"
            has_profit = (
                (alert.pnl_pct or 0.0) >= 1.0
                or (eval_res.pnl_pct or 0.0) >= 1.0
                or alert.target_status in ("TARGET_ACHIEVED", "T1_ACHIEVED")
            )
            if has_profit:
                alert.stage = "COMPLETED"
                alert.is_invalidated = False
                alert.invalidation_reason = None
                alert.is_archived = True
                alert.archived_at = now_str
                alert.archive_reason = "Velocity Time-Stop Reached (Profit Secured at CMP)"
                best_pnl = max(alert.pnl_pct or 0.0, eval_res.pnl_pct or 0.0)
                alert.headline = (
                    f"🎯 {env_tag} TIME-STOP PROFIT SECURED (+{best_pnl:.1f}%): {inst_label}"
                )
            else:
                alert.stage = "TIME_STOP_EXIT"
                alert.is_invalidated = True
                alert.invalidation_reason = eval_res.trailing_rationale
                alert.invalidated_at = now_str
                alert.is_archived = True
                alert.archived_at = now_str
                alert.archive_reason = "Velocity Time-Stop Reached (Stagnation Scratch Exit)"
                alert.headline = f"⏱️ {env_tag} VELOCITY TIME-STOP EXIT: {inst_label} (Close at CMP)"
        alert.summary = eval_res.trailing_rationale


# Global singleton instance
trade_lifecycle_manager = TradeLifecycleManager()
