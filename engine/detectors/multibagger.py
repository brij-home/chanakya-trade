"""
engine/detectors/multibagger.py
───────────────────────────────
Institutional Multibagger & Generational Wealth Discovery Detector.

Scans the high-growth compounder universe (NIFTY Total Market, Mid/Smallcap leaders,
Stage 2 breakout candidates) using Minervini SEPA 8-point Trend Template, Stan Weinstein
4-Stage Markup classifier, Volatility Contraction Pattern (VCP) tightness, and fundamental
forensic safety (Beneish M-Score, ROCE > 15%, Debt/Equity).

Generates high-conviction STAGE_1_TO_2_EXPANSION and MULTIBAGGER alerts with 6–24 Month
horizon ETAs, wide structural trailing floors (50-day/200-day SMA), and zero premature 2R booking.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from analysis.multibagger import MultibaggerReport, scan_multibagger_opportunity
from analysis.universe import THEMATIC_PRESETS
from engine.alert_identity import canonical_alert_symbol, generate_alert_id
from engine.alert_model import AutoAlert

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

_CORE_MULTIBAGGER_UNIVERSE = [
    "TRENT",
    "DIXON",
    "HAL",
    "BEL",
    "BSE",
    "MCX",
    "MAZDOCK",
    "COCHINSHIP",
    "GRSE",
    "BDL",
    "POLYCAB",
    "KEI",
    "RRKABEL",
    "PERSISTENT",
    "COFORGE",
    "KPITTECH",
    "MAXHEALTH",
    "MANKIND",
    "CHOLAFIN",
    "SUZLON",
    "INOXWIND",
    "IREDA",
    "SOLARINDS",
    "DATAPATTNS",
    "CYIENTDLM",
    "AETHER",
    "RADICO",
    "MEDANTA",
    "KAYNES",
    "TITAGARH",
    "PREMIERENE",
    "WAAREEENER",
    "ZENTEC",
    "SWANENERGY",
]


def get_multibagger_universe() -> list[str]:
    """Returns curated deduplicated universe of institutional compounder candidates."""
    syms: set[str] = set(_CORE_MULTIBAGGER_UNIVERSE)
    for k in ("multibagger_hunters", "bse_high_growth", "multibagger_all_horizons"):
        p_syms = THEMATIC_PRESETS.get(k, {}).get("symbols", [])
        for s in p_syms:
            clean = canonical_alert_symbol(s)
            if clean and not clean.startswith("^"):
                syms.add(clean)
    return sorted(list(syms))


def detect_multibagger_breakouts(
    universe: Optional[list[str]] = None,
    df_cache: Optional[dict[str, pd.DataFrame]] = None,
    quotes_map: Optional[dict[str, Any]] = None,
    min_conviction: int = 65,
    top_n: int = 10,
    session_dt: Optional[datetime] = None,
) -> list[AutoAlert]:
    """
    Scans universe for institutional Multibagger and Stage 1-to-2 Expansion opportunities.
    Returns qualified AutoAlert instances with MULTIBAGGER / LONG_TERM horizon metadata.
    """
    now_dt = session_dt or datetime.now(IST)
    now_iso = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")
    session_date = now_dt.date()

    target_symbols = universe or get_multibagger_universe()
    alerts: list[AutoAlert] = []

    # Check market open status
    from market.calendar import is_market_open

    mkt_open = is_market_open("NSE", ref_dt=now_dt)

    import concurrent.futures

    def _eval_single(sym: str) -> Optional[AutoAlert]:
        clean_sym = canonical_alert_symbol(sym)
        if not clean_sym:
            return None

        try:
            df = df_cache.get(clean_sym) if df_cache else None
            report: MultibaggerReport = scan_multibagger_opportunity(
                clean_sym, df=df, exchange="NSE"
            )

            if report.ltp <= 0 or report.multibagger_score < min_conviction:
                return None

            # Qualification rules:
            # 1. Forensic safety must be clean
            if not report.forensic_safe:
                return None

            # 2. Must be in Stage 2 Markup, VCP breakout coiling, or Stage 1 Wyckoff accumulation
            is_stage_2 = report.weinstein_stage == "STAGE_2_MARKUP"
            is_vcp = report.vcp_detected
            is_minervini = report.trend_template_passed >= 6
            is_superperformer = report.category in ("STAGE_2_SUPERPERFORMER", "VCP_BREAKOUT")

            if not (is_stage_2 or is_vcp or is_minervini or is_superperformer):
                # Must meet at least one structural catalyst
                return None

            # Determine horizon and ETA:
            # - MULTIBAGGER (6–24 Months): Top-tier Stage 2 Superperformers with score >= 85
            # - LONG_TERM (1–6 Months): Multi-quarter fundamental compounders
            # - SWING_MID (1–4 Weeks): Stan Weinstein Stage 2 markup expansion / RRG momentum swings
            # - SWING_SHORT (2–5 Sessions): High-speed compression / VCP breakouts
            if (report.category == "STAGE_2_SUPERPERFORMER" and report.multibagger_score >= 85) or (
                report.best_horizon == "LONG_TERM" and report.multibagger_score >= 85
            ):
                time_horizon = "MULTIBAGGER"
                eta_label = "6–24 Months"
                ticket = report.long_term_ticket or report.execution_ticket
                alert_type = "MULTIBAGGER"
            elif report.best_horizon == "LONG_TERM" or (
                report.multibagger_score >= 70 and not is_stage_2
            ):
                time_horizon = "LONG_TERM"
                eta_label = "1–6 Months"
                ticket = report.long_term_ticket or report.execution_ticket
                alert_type = "STAGE_1_TO_2_EXPANSION"
            elif report.best_horizon == "MID_TERM" or is_stage_2:
                time_horizon = "SWING_MID"
                eta_label = "1–4 Weeks"
                ticket = report.mid_term_ticket or report.execution_ticket
                alert_type = "STAGE_1_TO_2_EXPANSION" if is_stage_2 else "SQUEEZE_BREAKOUT"
            else:
                time_horizon = "SWING_SHORT"
                eta_label = "2–5 Sessions"
                ticket = report.short_term_ticket or report.execution_ticket
                alert_type = "PATTERN_COILING"

            ltp = report.ltp
            entry_p = float(ticket.get("entry_price") or ltp)
            if time_horizon == "MULTIBAGGER":
                sl = float(ticket.get("stop_loss") or round(ltp * 0.85, 1))
                tgt1 = float(ticket.get("target_1") or round(ltp * 1.50, 1))
                tgt2 = float(ticket.get("target_2") or round(ltp * 2.00, 1))
                tgt_moon = float(ticket.get("target_runner") or round(ltp * 3.00, 1))
                profit_rule = (
                    "Ride multi-quarter earnings expansion through routine 15%–20% market corrections. "
                    "Trail core investment strictly on weekly closes above the 40-Week (200-Day) Moving Average. "
                    "Liquidate or downsize only if: (1) Forensic audit flags accounting manipulation, "
                    "(2) ROCE falls sustainably below 15%, or (3) Stock enters Stage 3 Institutional Distribution."
                )
            elif time_horizon == "LONG_TERM":
                sl = float(ticket.get("stop_loss") or round(ltp * 0.88, 1))
                tgt1 = float(ticket.get("target_1") or round(ltp * 1.35, 1))
                tgt2 = float(ticket.get("target_2") or round(ltp * 1.65, 1))
                tgt_moon = float(ticket.get("target_runner") or round(ltp * 2.20, 1))
                profit_rule = (
                    "Ride multi-month structural trend. Trail stop-loss below the rising 100-Day / 20-Week EMA. "
                    "Scale out 30% at T1 (+35%), 40% at T2 (+65%), and let 30% runner compound toward T3."
                )
            elif time_horizon == "SWING_MID":
                sl = float(ticket.get("stop_loss") or round(ltp * 0.92, 1))
                tgt1 = float(ticket.get("target_1") or round(ltp * 1.20, 1))
                tgt2 = float(ticket.get("target_2") or round(ltp * 1.35, 1))
                tgt_moon = float(ticket.get("target_runner") or round(ltp * 1.60, 1))
                profit_rule = (
                    "Institutional swing trade. Scale out 50% at T1 (+20%) and move stop-loss to Breakeven. "
                    "Trail remaining 50% along the rising 20-Day EMA until exhaustion or T2."
                )
            else:
                sl = float(ticket.get("stop_loss") or round(ltp * 0.96, 1))
                tgt1 = float(ticket.get("target_1") or round(ltp * 1.08, 1))
                tgt2 = float(ticket.get("target_2") or round(ltp * 1.15, 1))
                tgt_moon = float(ticket.get("target_runner") or round(ltp * 1.25, 1))
                profit_rule = (
                    "Fast swing momentum. Take 50% off at T1 (+8%), trail stop-loss to entry price, "
                    "and close out full position by 5th session."
                )

            entry_rg = f"₹{entry_p:,.1f} – ₹{round(entry_p * 1.025, 1):,.1f}"
            no_chase_val = round(entry_p * 1.04, 1)

            # Build institutional headline
            if time_horizon == "MULTIBAGGER":
                headline = f"🚀 MULTIBAGGER COMPOUNDER: {clean_sym} @ ₹{ltp:,.1f} (Score {report.multibagger_score}/100)"
            elif time_horizon == "LONG_TERM":
                headline = f"🏛️ LONG-TERM COMPOUNDER: {clean_sym} @ ₹{ltp:,.1f} (Score {report.multibagger_score}/100)"
            elif is_stage_2:
                headline = f"📈 STAGE 2 SWING BREAKOUT: {clean_sym} @ ₹{ltp:,.1f} (Score {report.multibagger_score}/100)"
            elif is_vcp:
                headline = f"🎯 VCP PIVOT BREAKOUT: {clean_sym} @ ₹{ltp:,.1f} (Pivot ₹{report.vcp_pivot_price:,.1f})"
            else:
                headline = f"⚡ QUALITY COMPOUNDER: {clean_sym} @ ₹{ltp:,.1f} (Score {report.multibagger_score}/100)"

            summary = (
                f"{report.summary} Entry: {entry_rg}. Invalidation SL: ₹{sl:,.1f}. "
                f"T1: ₹{tgt1:,.1f} | T2: ₹{tgt2:,.1f}. {profit_rule}"
            )

            # Generate deterministic alert ID (Rule 17)
            alert_id = generate_alert_id(
                clean_sym,
                alert_type,
                session_date=session_date,
                variant="compounder",
            )

            is_test = (
                (os.environ.get("CHANAKYA_TESTING") == "1")
                or (os.environ.get("DEPLOY_MODE") == "test")
                or ("PYTEST_CURRENT_TEST" in os.environ)
            )

            stage_val = "IGNITED" if (is_superperformer and mkt_open) else "EARLY_WARNING"
            provenance_env = "TEST" if is_test else ("LIVE" if mkt_open else "EOD_SCAN")
            mkt_status = "LIVE" if mkt_open else "SESSION_CLOSED"

            return AutoAlert(
                alert_id=alert_id,
                alert_type=alert_type,
                stage=stage_val,
                symbol=clean_sym,
                exchange="NSE",
                direction="BULLISH",
                headline=headline,
                summary=summary,
                ltp=ltp,
                trigger_level=entry_p,
                target_level=tgt1,
                stop_loss=sl,
                underlying_spot=ltp,
                segment="EQUITY",
                confidence=report.multibagger_score,
                time_horizon=time_horizon,
                eta_label=eta_label,
                no_chase_boundary=no_chase_val,
                setup_style="MULTIBAGGER_MOMENTUM" if is_stage_2 else "COMPOUNDER_GROWTH",
                created_at=now_iso,
                is_live=not is_test,
                environment=provenance_env,
                market_status=mkt_status,
                metrics={
                    "multibagger_score": report.multibagger_score,
                    "category": report.category,
                    "weinstein_stage": report.weinstein_stage,
                    "trend_template_passed": report.trend_template_passed,
                    "vcp_detected": report.vcp_detected,
                    "sector_name": report.sector,
                    "sector_tailwind": report.sector_tailwind_score,
                    "best_horizon": report.best_horizon,
                    "forensic_safe": report.forensic_safe,
                    "cfai_pct": report.cfai_pct,
                    "catalyst_notes": report.catalyst_notes,
                },
                actionable_plan={
                    "action": "BUY",
                    "segment": "EQUITY",
                    "entry_range": entry_rg,
                    "recommended_entry": entry_p,
                    "stop_loss": f"₹{sl:,.1f}",
                    "target": f"₹{tgt1:,.1f}",
                    "target_2": f"₹{tgt2:,.1f}",
                    "target_runner": f"₹{tgt_moon:,.1f}",
                    "risk_reward": ticket.get("risk_reward_ratio", "1:4.5"),
                    "profit_rule": profit_rule,
                    "when_to_buy": f"Buy on volume breakout in range {entry_rg}",
                    "when_to_wait": f"DO NOT CHASE if price exceeds ₹{no_chase_val:,.1f}",
                    "time_horizon": time_horizon,
                    "eta": eta_label,
                },
            )

        except Exception as e:
            logger.debug(f"[MultibaggerDetector] Error evaluating {clean_sym}: {e}")
            return None

    if len(target_symbols) <= 2:
        for sym in target_symbols:
            al = _eval_single(sym)
            if al:
                alerts.append(al)
    else:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(8, len(target_symbols))
        ) as executor:
            futures = [executor.submit(_eval_single, s) for s in target_symbols]
            for fut in concurrent.futures.as_completed(futures):
                try:
                    al = fut.result()
                    if al:
                        alerts.append(al)
                except Exception as ex:
                    logger.debug(f"[MultibaggerDetector] Future error: {ex}")

    # Sort descending by multibagger conviction score
    alerts.sort(key=lambda a: a.confidence, reverse=True)
    return alerts[:top_n]
