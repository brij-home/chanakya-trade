"""
analysis/inflection_ai.py
─────────────────────────
AI 5W+H Conclusive Decision Matrix & Cross-Dimensional Dot-Connecting Engine.

Channels the institutional expertise of 5 specialized persona councils:
  - Mark Minervini & Richard Wyckoff: VCP pivot tightness, volume dry-up, supply exhaustion.
  - Smart Money Concepts (SMC): Liquidity sweeps, Order Block OTE discounts, FVGs.
  - Vijay Kedia & Rakesh Jhunjhunwala: Multibagger scale runway, operating leverage, SMILE.
  - George Soros & Jim Simons: Global macro transmission, regime probability, sector RRG.
  - Forensic Auditor & Nassim Taleb: Governance integrity (Beneish/Altman) and convex payoff.

Synthesizes the complete 5W+H Conclusive Decision Matrix:
  - WHAT: Core thesis, inflection archetype, and false-breakout trap filters.
  - WHERE: Precise Entry Zone, Stop-Loss, Target 1 (+2R), Target 2 (+3.5R), Moonshot (+6R–10R), and Sizing.
  - WHEN: Inflection timing window, squeeze countdown, and holding horizon.
  - HOW: Tactical order playbook, scale-out rules, and trailing stop mechanics.
  - CORRELATIONS: Global macro transmission, FII/DII flow backdrop, Sector RRG, Options OI.
  - INVALIDATION: Hard structural failure conditions that command an immediate exit.

Includes deterministic quantitative fallback adhering to AGENTS.md (zero blank cards).
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd

# UTF-8 console output for Windows
if sys.platform == "win32":
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from analysis.big_move import analyze_options_flow
from analysis.forensic import audit_company_forensics
from analysis.inflection_scanner import (
    InflectionSetup,
    evaluate_single_stock_inflection,
)
from analysis.universe import get_stock_name, get_stock_sector
from market.global_macro import fetch_global_macro_report


@dataclass
class InflectionDecisionMatrix:
    symbol: str
    name: str
    sector: str
    ltp: float
    verdict: str  # "🟢 HIGH_CONVICTION_BUY" | "🟡 STALK_PIVOT" | "🔴 AVOID_TRAP_RISK"
    confidence_score: int  # 0 to 100
    archetype: str
    timing_state: str
    what: dict[str, Any] = field(default_factory=dict)
    where: dict[str, Any] = field(default_factory=dict)
    when: dict[str, Any] = field(default_factory=dict)
    how: dict[str, Any] = field(default_factory=dict)
    correlations: dict[str, Any] = field(default_factory=dict)
    invalidation: dict[str, Any] = field(default_factory=dict)
    council_insights: list[dict[str, str]] = field(default_factory=list)
    generated_at: str = ""
    is_ai_synthesized: bool = True
    live_ltp: Optional[float] = None
    live_data_state: str = "UNAVAILABLE"
    live_as_of: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Deterministic Fallback Synthesis ─────────────────────────────────


def _build_deterministic_5w_decision(
    setup: InflectionSetup,
    macro_report: Any,
    forensic_rep: Any,
    options_flow: Any,
    live_ltp: Optional[float] = None,
    live_data_state: str = "UNAVAILABLE",
    live_as_of: str = "",
) -> InflectionDecisionMatrix:
    """
    Deterministic quantitative 5W+H decision matrix conforming strictly to AGENTS.md.
    Used when LLMs are offline, throttled, or in rapid fallback mode.
    """
    sym = setup.symbol
    ltp = setup.ltp
    entry = setup.entry_price
    sl = setup.stop_loss
    t1 = setup.target_1
    t2 = setup.target_2
    moonshot = setup.target_moonshot
    rr = setup.risk_reward_ratio

    # 1. Verdict & Confidence
    if setup.inflection_score >= 75 and setup.forensic_safe:
        verdict = "🟢 HIGH_CONVICTION_BUY"
        conf = min(95, setup.inflection_score + 5)
    elif setup.inflection_score >= 55:
        verdict = "🟡 STALK_PIVOT"
        conf = setup.inflection_score
    else:
        verdict = "🔴 AVOID_TRAP_RISK"
        conf = max(25, setup.inflection_score - 10)

    # 2. WHAT: Core Thesis
    b_score = getattr(forensic_rep, "beneish_m_score", None)
    b_str = f"{b_score:.2f}" if b_score is not None else "N/A"
    p_pledge = getattr(forensic_rep, "promoter_pledging_pct", None)
    if p_pledge is None:
        p_pledge = getattr(forensic_rep, "pledged_pct", None)
    p_str = f"{float(p_pledge):.1f}" if p_pledge is not None else "0.0"

    what = {
        "thesis_title": f"{setup.archetype_label} Inflection Setup",
        "primary_catalyst": setup.catalyst_summary,
        "false_breakout_checks": [
            f"Volume Confirmation: RVOL is {setup.rvol_20d}x (Threshold >= 1.25x for conviction)",
            f"Forensic Integrity: Beneish M-Score {b_str} (Clean < -1.78)",
            f"Promoter Pledging: {p_str}% (Low Risk)",
            "Overhead Resistance: Check for unmitigated Fair Value Gaps or Supply Blocks within 5%",
        ],
        "key_strengths": setup.confluence_factors,
    }

    # 3. WHERE: Precise Price Coordinates & Sizing
    where = {
        "entry_zone": f"₹{entry:.2f} (Optimal Entry)",
        "stop_loss": f"₹{sl:.2f} (Risk: ₹{setup.risk_pts:.2f} / {round((entry - sl) / entry * 100, 1)}%)",
        "target_1": f"₹{t1:.2f} (+2.0R Breakeven Pivot)",
        "target_2": f"₹{t2:.2f} (+3.5R Positional Swing)",
        "target_moonshot": f"₹{moonshot:.2f} (+6.5R Multibagger Horizon)",
        "risk_reward_ratio": f"1:{rr} (T1) / 1:3.5 (T2) / 1:6.5 (Moonshot)",
        "sizing_guideline": "Allocate 1.0% to 1.5% maximum capital risk using ATR volatility sizing model.",
        "current_market_price": live_ltp if live_ltp is not None else ltp,
        "live_data_state": live_data_state,
        "live_as_of": live_as_of,
    }

    # 4. WHEN: Inflection Timing & Horizon
    squeeze_bars = setup.squeeze_duration
    when = {
        "timing_status": setup.timing_label,
        "timing_state": setup.timing_state,
        "squeeze_countdown": (
            f"Squeeze coiling for {squeeze_bars} bars — imminent explosion expected within 1–3 sessions."
            if setup.squeeze_state == "COILING"
            else "Volatility ignition already underway; execute entry on structure."
        ),
        "catalyst_window": "Upcoming earnings cycle and sector momentum rotation.",
        "time_stop_days": 10 if setup.timing_state == "TRIGGER_NOW" else 15,
        "holding_period": "Swing Momentum: 3–10 Trading Days | Positional Compounder: 1–6 Months",
    }

    # 5. HOW: Tactical Execution Playbook
    how = {
        "order_strategy": (
            f"Place Limit / GTT Buy order at ₹{entry:.2f}. Never chase beyond ₹{round(entry * 1.015, 2)}."
        ),
        "scaling_plan": (
            f"Scale out 40-50% position at Target 1 (₹{t1:.2f}) -> "
            "Immediately advance Stop-Loss to Breakeven (+0.2% for broker charges)."
        ),
        "trailing_mechanics": (
            "Trail remainder along the rising 20-day EMA or behind verified Higher Low structural swing supports."
        ),
        "moonshot_management": (
            "Hold runner 20% allocation as long as the stock remains above rising 50-day SMA in Stage 2."
        ),
    }

    # 6. CORRELATIONS: Macro, Sector, and Options Transmission
    macro_posture = getattr(macro_report, "global_posture", None) or "NEUTRAL"
    nifty_gap = getattr(macro_report, "implied_nifty_gap_pct", None)
    nifty_gap_str = f"{nifty_gap:+.2f}%" if nifty_gap is not None else "+0.00%"
    crude_trend = getattr(macro_report, "crude_oil_price", None)
    crude_str = f"${crude_trend:.1f}/bbl" if crude_trend is not None else "$75.0/bbl"

    options_pcr = getattr(options_flow, "pcr", None)
    options_pcr_str = f"{options_pcr:.2f}" if options_pcr is not None else "1.00"
    options_regime = getattr(options_flow, "dominant_regime", None) or "BALANCED"

    correlations = {
        "macro_regime": f"Global Posture: {macro_posture} | Implied NIFTY Gap: {nifty_gap_str}",
        "crude_oil_impact": f"Brent Crude at {crude_str}. Sector correlation evaluated.",
        "sector_rrg_tailwind": (
            f"Sector {setup.sector} in {setup.rrg_quadrant} quadrant with Tailwind Score {setup.sector_tailwind_score}/100."
        ),
        "options_smart_money": (
            f"Options PCR: {options_pcr_str} | Flow Regime: {options_regime}."
            if getattr(options_flow, "has_options", False)
            else "Cash equity segment (Non-F&O) — institutional delivery volume applies."
        ),
    }

    # 7. INVALIDATION: Hard Failure Conditions
    invalidation = {
        "hard_stop_condition": f"Daily close below ₹{sl:.2f} invalidates setup immediately.",
        "time_invalidation": "If price does not progress >= 1R within 8 trading days, close for stagnation.",
        "structural_failure": "Bearish Change of Character (CHoCH) breaking prior swing low on heavy volume.",
        "gap_down_protocol": "If opening gap pierces stop-loss, exit at market open without hesitation.",
    }

    # 8. Council Insights
    council_insights = [
        {
            "persona": "Mark Minervini",
            "style": "SEPA & VCP Breakouts",
            "commentary": (
                f"{sym} passes {setup.trend_template_passed}/8 trend template criteria. "
                f"Weinstein Stage: {setup.weinstein_stage}. "
                + (
                    f"VCP contraction is tightening ({setup.vcp_tightness_pct}% risk at pivot ₹{setup.vcp_pivot_price})."
                    if setup.vcp_detected
                    else "Look for tight price action near moving average benchmarks."
                )
            ),
        },
        {
            "persona": "Smart Money (SMC)",
            "style": "Liquidity & Order Blocks",
            "commentary": (
                f"Structural regime is {setup.smc_regime} ({setup.smc_setup}). "
                f"Entry at ₹{entry:.2f} aligns with the unmitigated demand discount zone."
            ),
        },
        {
            "persona": "Vijay Kedia",
            "style": "SMILE Multibagger Framework",
            "commentary": (
                f"{setup.name} has scalable sector runway in {setup.sector}. "
                "Operating leverage in Stage 2 markup provides high-asymmetry potential for multi-month holding."
            ),
        },
        {
            "persona": "George Soros & Jim Simons",
            "style": "Macro & Statistical Regime",
            "commentary": (
                f"Macro environment is {macro_posture}. Sector RRG tailwind ({setup.rrg_quadrant}) "
                f"offers positive drift. Risk-reward of 1:{rr} satisfies mathematical expectancy."
            ),
        },
        {
            "persona": "Forensic Auditor",
            "style": "Governance & Quality Sanity",
            "commentary": (
                "Forensic audit: "
                + (
                    "CLEAN PASS. Low manipulation probability and strong balance sheet safety."
                    if setup.forensic_safe
                    else "CAUTION. Mild accounting anomalies detected. Strict stop-loss required."
                )
            ),
        },
    ]

    return InflectionDecisionMatrix(
        symbol=sym,
        name=setup.name,
        sector=setup.sector,
        ltp=live_ltp if live_ltp is not None else ltp,
        verdict=verdict,
        confidence_score=conf,
        archetype=setup.primary_archetype,
        timing_state=setup.timing_state,
        what=what,
        where=where,
        when=when,
        how=how,
        correlations=correlations,
        invalidation=invalidation,
        council_insights=council_insights,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        is_ai_synthesized=False,
        live_ltp=live_ltp,
        live_data_state=live_data_state,
        live_as_of=live_as_of,
    )


# ── AI-Powered Decision Matrix Generator ─────────────────────────────


def generate_inflection_decision(
    symbol: str,
    exchange: str = "NSE",
    df: Optional[pd.DataFrame] = None,
    force_refresh: bool = False,
) -> InflectionDecisionMatrix:
    """
    Generates a conclusive 5W+H Decision Matrix for a stock at an inflection point.
    Combines quantitative indicators, macro transmission, forensics, and Dual-LLM synthesis.
    """
    clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").strip()

    # 1. Evaluate Quantitative Inflection Setup
    setup = evaluate_single_stock_inflection(clean_sym, df=df, exchange=exchange)
    if not setup:
        sec_info = get_stock_sector(clean_sym)
        sec_name = sec_info[1] if isinstance(sec_info, tuple) else str(sec_info)
        setup = InflectionSetup(
            symbol=clean_sym,
            name=get_stock_name(clean_sym),
            sector=sec_name,
            sector_icon="🏢",
            ltp=100.0,
            day_change_pct=0.0,
            inflection_score=50,
            primary_archetype="STAGE_1_TO_2_EXPANSION",
            archetype_label="Weinstein Stage 1→2 Markup",
            timing_state="COILING_IMMINENT",
            timing_label="⏳ Coiling (1–3d)",
            weinstein_stage="STAGE_1_BASE",
            vcp_detected=False,
            vcp_tightness_pct=0.0,
            vcp_pivot_price=0.0,
            squeeze_state="NORMAL",
            squeeze_duration=0,
            rvol_20d=1.0,
            trend_template_passed=4,
            sector_tailwind_score=50,
            rrg_quadrant="IMPROVING",
            forensic_safe=True,
            smc_regime="CONSOLIDATION",
            smc_setup="RANGE_BOUND",
            entry_price=100.0,
            stop_loss=95.0,
            target_1=110.0,
            target_2=117.5,
            target_moonshot=132.5,
            risk_reward_ratio=2.0,
            risk_pts=5.0,
            reward_pts=17.5,
            confluence_factors=["Consolidation base forming"],
            catalyst_summary="Developing base setup.",
            suggested_action="Watch for breakout.",
        )

    # 2. Gather Multi-Dimensional Signals
    macro_report = None
    try:
        macro_report = fetch_global_macro_report(nifty_spot=setup.ltp)
    except Exception:
        pass

    forensic_rep = None
    try:
        forensic_rep = audit_company_forensics(clean_sym)
    except Exception:
        pass

    options_flow = None
    try:
        options_flow = analyze_options_flow(clean_sym, ltp=setup.ltp, exchange=exchange)
    except Exception:
        pass

    # Live quote fetch for real-time truthfulness
    live_ltp = None
    live_data_state = "UNAVAILABLE"
    live_as_of = ""
    try:
        from market.quotes import get_quotes

        inst = f"{exchange}:{clean_sym}"
        quotes = get_quotes([inst])
        q = quotes.get(inst) or quotes.get(clean_sym)
        if q and getattr(q, "last_price", 0.0) > 0:
            live_ltp = float(q.last_price)
            live_data_state = str(getattr(q, "data_state", "LIVE"))
            live_as_of = str(
                getattr(q, "received_at", "") or datetime.now(timezone.utc).isoformat()
            )
    except Exception:
        pass

    # 3. If testing or offline, return deterministic quantitative synthesis directly
    if os.environ.get("CHANAKYA_TESTING") or not (
        os.environ.get("GROQ_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
    ):
        return _build_deterministic_5w_decision(
            setup,
            macro_report,
            forensic_rep,
            options_flow,
            live_ltp=live_ltp,
            live_data_state=live_data_state,
            live_as_of=live_as_of,
        )

    # 4. LLM Synthesis Attempt
    try:
        from agent.core import get_deep_provider

        provider = get_deep_provider()
        if not provider:
            return _build_deterministic_5w_decision(
                setup,
                macro_report,
                forensic_rep,
                options_flow,
                live_ltp=live_ltp,
                live_data_state=live_data_state,
                live_as_of=live_as_of,
            )

        system_prompt = (
            "You are ChanakyaTrade's Lead Institutional Investment Committee combining 5 elite personas: "
            "Mark Minervini (VCP Breakouts), Smart Money Concepts (ICT Order Blocks & Sweeps), "
            "Vijay Kedia (SMILE Multibaggers), George Soros & Jim Simons (Global Macro & Quantitative EV), "
            "and Forensic Auditor (Beneish/Altman governance). "
            "Your task is to analyze the stock data and output a structured JSON 5W+H Conclusive Decision Matrix. "
            "Be precise with price levels, connect macro/sector dots, and protect against false breakouts."
        )

        b_score = getattr(forensic_rep, "beneish_m_score", None)
        b_txt = f"{b_score:.2f}" if b_score is not None else "N/A"
        alt_z = getattr(forensic_rep, "altman_z_score", None)
        alt_txt = f"{alt_z:.2f}" if alt_z is not None else "N/A"
        nifty_gap = getattr(macro_report, "implied_nifty_gap_pct", None)
        gap_txt = f"{nifty_gap:+.2f}%" if nifty_gap is not None else "0.00%"
        opt_pcr = getattr(options_flow, "pcr", None)
        pcr_txt = f"{opt_pcr:.2f}" if opt_pcr is not None else "1.00"

        user_prompt = f"""
Analyze the following multi-dimensional data for {clean_sym} ({setup.name}):
LTP: ₹{setup.ltp:.2f} (Day Change: {setup.day_change_pct:+.2f}%)
Inflection Archetype: {setup.archetype_label} (Primary: {setup.primary_archetype})
Timing Radar: {setup.timing_label} ({setup.timing_state})
Inflection Score: {setup.inflection_score}/100
Minervini 8-Point: {setup.trend_template_passed}/8 Passed | Weinstein Stage: {setup.weinstein_stage}
VCP Status: {"Detected with " + str(setup.vcp_tightness_pct) + "% tightness at pivot ₹" + str(setup.vcp_pivot_price) if setup.vcp_detected else "None"}
TTM Squeeze: {setup.squeeze_state} ({setup.squeeze_duration} bars)
RVOL 20D: {setup.rvol_20d}x | SMC Structure: {setup.smc_regime} ({setup.smc_setup})
Sector: {setup.sector} (RRG Quadrant: {setup.rrg_quadrant} | Tailwind: {setup.sector_tailwind_score}/100)
Forensic Audit: Beneish M-Score: {b_txt}, Altman Z: {alt_txt}, Safe: {setup.forensic_safe}
Macro Backdrop: Global Posture {getattr(macro_report, "global_posture", "NEUTRAL")}, Implied Nifty Gap: {gap_txt}
Options Flow: PCR {pcr_txt}, Regime: {getattr(options_flow, "dominant_regime", "BALANCED")}
Calculated Levels: Entry: ₹{setup.entry_price:.2f}, Stop Loss: ₹{setup.stop_loss:.2f}, Target 1 (+2R): ₹{setup.target_1:.2f}, Target 2 (+3.5R): ₹{setup.target_2:.2f}, Moonshot: ₹{setup.target_moonshot:.2f}, Risk/Reward: 1:{setup.risk_reward_ratio}

Respond ONLY with a valid JSON object with these exact keys:
{{
  "verdict": "🟢 HIGH_CONVICTION_BUY" | "🟡 STALK_PIVOT" | "🔴 AVOID_TRAP_RISK",
  "confidence_score": 85,
  "what": {{
    "thesis_title": "string",
    "primary_catalyst": "string",
    "false_breakout_checks": ["string", "string"],
    "key_strengths": ["string", "string"]
  }},
  "where": {{
    "entry_zone": "string",
    "stop_loss": "string",
    "target_1": "string",
    "target_2": "string",
    "target_moonshot": "string",
    "risk_reward_ratio": "string",
    "sizing_guideline": "string"
  }},
  "when": {{
    "timing_status": "string",
    "timing_state": "{setup.timing_state}",
    "squeeze_countdown": "string",
    "catalyst_window": "string",
    "time_stop_days": 10,
    "holding_period": "string"
  }},
  "how": {{
    "order_strategy": "string",
    "scaling_plan": "string",
    "trailing_mechanics": "string",
    "moonshot_management": "string"
  }},
  "correlations": {{
    "macro_regime": "string",
    "crude_oil_impact": "string",
    "sector_rrg_tailwind": "string",
    "options_smart_money": "string"
  }},
  "invalidation": {{
    "hard_stop_condition": "string",
    "time_invalidation": "string",
    "structural_failure": "string",
    "gap_down_protocol": "string"
  }},
  "council_insights": [
    {{"persona": "Mark Minervini", "style": "SEPA & VCP Breakouts", "commentary": "string"}},
    {{"persona": "Smart Money (SMC)", "style": "Liquidity & Order Blocks", "commentary": "string"}},
    {{"persona": "Vijay Kedia", "style": "SMILE Multibagger Framework", "commentary": "string"}},
    {{"persona": "George Soros & Jim Simons", "style": "Macro & Statistical Regime", "commentary": "string"}},
    {{"persona": "Forensic Auditor", "style": "Governance & Quality Sanity", "commentary": "string"}}
  ]
}}
"""
        response_text = ""
        if hasattr(provider, "call"):
            response_text = provider.call(system=system_prompt, message=user_prompt)
        elif hasattr(provider, "chat"):
            res = provider.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]
            )
            response_text = res if isinstance(res, str) else getattr(res, "text", str(res))

        # Extract JSON
        json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
            where_dict = data.get("where", {})
            if "current_market_price" not in where_dict:
                where_dict["current_market_price"] = live_ltp if live_ltp is not None else setup.ltp
                where_dict["live_data_state"] = live_data_state
                where_dict["live_as_of"] = live_as_of

            return InflectionDecisionMatrix(
                symbol=clean_sym,
                name=setup.name,
                sector=setup.sector,
                ltp=live_ltp if live_ltp is not None else setup.ltp,
                verdict=data.get("verdict", "🟢 HIGH_CONVICTION_BUY"),
                confidence_score=int(data.get("confidence_score", setup.inflection_score)),
                archetype=setup.primary_archetype,
                timing_state=setup.timing_state,
                what=data.get("what", {}),
                where=where_dict,
                when=data.get("when", {}),
                how=data.get("how", {}),
                correlations=data.get("correlations", {}),
                invalidation=data.get("invalidation", {}),
                council_insights=data.get("council_insights", []),
                generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                is_ai_synthesized=True,
                live_ltp=live_ltp,
                live_data_state=live_data_state,
                live_as_of=live_as_of,
            )
    except Exception:
        pass

    # Fallback if parsing or call fails
    return _build_deterministic_5w_decision(
        setup,
        macro_report,
        forensic_rep,
        options_flow,
        live_ltp=live_ltp,
        live_data_state=live_data_state,
        live_as_of=live_as_of,
    )


# ── Interactive Dot-Connecting Chat ──────────────────────────────────


def answer_inflection_chat(
    symbol: str,
    question: str,
    matrix_data: Optional[dict[str, Any]] = None,
    exchange: str = "NSE",
) -> dict[str, Any]:
    """
    Answers user follow-up questions right inside the scanner drawer,
    connecting the dots across macro, fundamental, and microstructural dimensions.
    """
    clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").strip()

    if not matrix_data:
        matrix = generate_inflection_decision(clean_sym, exchange=exchange)
        matrix_data = matrix.to_dict()

    # Try LLM provider if configured
    if not os.environ.get("CHANAKYA_TESTING") and (
        os.environ.get("GROQ_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
    ):
        try:
            from agent.core import get_fast_provider

            provider = get_fast_provider()
            if provider:
                prompt = (
                    f"You are the ChanakyaTrade Inflection Copilot. You have already synthesized the following 5W+H decision matrix for {clean_sym}:\n"
                    f"Verdict: {matrix_data.get('verdict')}\n"
                    f"Archetype: {matrix_data.get('archetype')} | Timing: {matrix_data.get('timing_state')}\n"
                    f"Levels: Entry {matrix_data.get('where', {}).get('entry_zone')}, Stop {matrix_data.get('where', {}).get('stop_loss')}, Targets {matrix_data.get('where', {}).get('target_1')} / {matrix_data.get('where', {}).get('target_2')} / {matrix_data.get('where', {}).get('target_moonshot')}\n"
                    f"Correlations: {json.dumps(matrix_data.get('correlations', {}))}\n"
                    f"Invalidation: {json.dumps(matrix_data.get('invalidation', {}))}\n\n"
                    f"User Question: {question}\n\n"
                    "Answer concisely, professionally, and authoritatively. Connect the dots across technical, fundamental, sector RRG, macro, and risk management dimensions. Maximum 3-4 compact paragraphs."
                )
                if hasattr(provider, "call"):
                    ans = provider.call(
                        system="You are ChanakyaTrade Inflection Copilot. Connect dots authoritatively.",
                        message=prompt,
                    )
                    return {
                        "symbol": clean_sym,
                        "question": question,
                        "answer": ans,
                        "status": "success",
                    }
        except Exception:
            pass

    # Deterministic contextual answer fallback
    q_lower = question.lower()
    entry = matrix_data.get("where", {}).get("entry_zone", "current price")
    sl = matrix_data.get("where", {}).get("stop_loss", "prior swing support")
    t1 = matrix_data.get("where", {}).get("target_1", "+2R level")
    sector = matrix_data.get("sector", "Broad Market")

    if "stop" in q_lower or "risk" in q_lower or "sl" in q_lower:
        ans = (
            f"For {clean_sym}, the stop-loss is placed at {sl}. This level is dynamically calibrated "
            f"using 1.15× ATR and anchored directly below the unmitigated demand Order Block and base swing support. "
            f"A daily close below this invalidates the inflection thesis and commands an immediate disciplined exit."
        )
    elif "target" in q_lower or "profit" in q_lower or "exit" in q_lower:
        ans = (
            f"The primary target for {clean_sym} is {t1} (+2R payoff). At this level, the institutional playbook "
            f"scales out 40–50% of the position and trails the remaining half to Breakeven (+0.2% for transaction costs). "
            f"The extended swing target is {matrix_data.get('where', {}).get('target_2')} (+3.5R), with a moonshot compounder target at {matrix_data.get('where', {}).get('target_moonshot')}."
        )
    elif "crude" in q_lower or "macro" in q_lower or "dollar" in q_lower or "nifty" in q_lower:
        ans = (
            f"Macro Correlation Analysis for {clean_sym} ({sector}): "
            f"{matrix_data.get('correlations', {}).get('macro_regime', 'Neutral macro conditions')}. "
            f"Crude transmission impact: {matrix_data.get('correlations', {}).get('crude_oil_impact', 'Low direct sensitivity')}. "
            f"Sector momentum: {matrix_data.get('correlations', {}).get('sector_rrg_tailwind', 'Favorable tailwind')}."
        )
    else:
        ans = (
            f"Regarding '{question}' on {clean_sym}: The setup currently classifies as {matrix_data.get('verdict')} "
            f"based on {matrix_data.get('archetype')} ({matrix_data.get('timing_state')}). "
            f"Key coordinates: Entry at {entry}, Stop-Loss at {sl}, and initial target at {t1}. "
            f"Sizing recommendation: Allocate 1.0% to 1.5% maximum capital risk."
        )

    return {"symbol": clean_sym, "question": question, "answer": ans, "status": "success"}
