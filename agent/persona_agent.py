"""
agent/persona_agent.py
──────────────────────
Run a named investor persona analysis on a stock symbol.

Flow (with LLM):
  1. Fetch pre-computed data: technicals + fundamentals + macro snapshot
  2. Build a compact data brief
  3. Call LLM with persona's system_prompt + data brief
  4. Parse response → PersonaSignal
  5. Return PersonaSignal

Flow (no LLM — deterministic fallback):
  Same data fetch, then score each dimension using simple rules,
  apply persona weights, map to verdict.

Public API:
  run_persona_analysis(persona_id, symbol, exchange, registry, llm_provider) -> PersonaSignal
  run_debate(symbol, exchange, registry, llm_provider) -> list[PersonaSignal]
  parse_persona_response(text, persona_id) -> PersonaSignal
"""

from __future__ import annotations

import re
from typing import Any

from agent.personas import get_persona, list_personas
from agent.schemas import PersonaSignal


# ── Response parser ───────────────────────────────────────────


def parse_persona_response(text: str, persona_id: str) -> PersonaSignal:
    """
    Parse an LLM response into a PersonaSignal.

    Handles:
      - Full structured responses
      - Partial responses (missing some fields)
      - Empty or error responses (returns UNAVAILABLE with 0% confidence)

    Expected loose format in the response:
        VERDICT: BUY
        CONFIDENCE: 72
        RATIONALE:
        - Strong moat in telecom
        - ROE below threshold
        KEY_METRICS:
        ROE: 8% (need >15%)
        D/E: 0.4
    """
    if not text or not text.strip():
        return PersonaSignal(
            persona=persona_id,
            verdict="UNAVAILABLE",
            confidence=0,
            rationale=["Insufficient data for analysis"],
            key_metrics={},
        )

    verdict = "UNAVAILABLE"
    confidence = 0
    rationale: list[str] = []
    key_metrics: dict[str, str] = {}

    # ── Verdict ──────────────────────────────────────────────
    verdict_match = re.search(
        r"VERDICT\s*[:=]\s*(STRONG_BUY|STRONG_SELL|BUY|SELL|HOLD|UNAVAILABLE)",
        text,
        re.IGNORECASE,
    )
    if verdict_match:
        verdict_raw = verdict_match.group(1).upper().replace(" ", "_")
        # Normalise: "STRONG BUY" → "STRONG_BUY"
        valid = {"STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL", "UNAVAILABLE"}
        if verdict_raw in valid:
            verdict = verdict_raw

    # ── Confidence ────────────────────────────────────────────
    conf_match = re.search(r"CONFIDENCE\s*[:=]\s*(\d+)", text, re.IGNORECASE)
    if conf_match:
        try:
            confidence = max(0, min(100, int(conf_match.group(1))))
        except ValueError:
            pass

    # A response without a machine-readable verdict or confidence is not an
    # auditable recommendation. Keep its commentary, but make it non-actionable.
    if not verdict_match or not conf_match or verdict == "UNAVAILABLE":
        verdict = "UNAVAILABLE" if not verdict_match else verdict
        confidence = 0

    # ── Rationale (bullet points) ─────────────────────────────
    rationale_section = re.search(
        r"RATIONALE\s*[:=]?\s*\n(.*?)(?=KEY_METRICS|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if rationale_section:
        lines = rationale_section.group(1).strip().splitlines()
        for line in lines:
            line = line.strip().lstrip("-•*").strip()
            if line:
                rationale.append(line)

    # Fall back: find any bullet points in the text
    if not rationale:
        bullets = re.findall(r"^[\s]*[-•*]\s+(.+)$", text, re.MULTILINE)
        rationale = [b.strip() for b in bullets if b.strip()][:6]

    # Guarantee at least one rationale item
    if not rationale:
        rationale = ["The model did not provide an auditable rationale."]

    # ── Key metrics ───────────────────────────────────────────
    metrics_section = re.search(
        r"KEY_METRICS\s*[:=]?\s*\n(.*?)$",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if metrics_section:
        lines = metrics_section.group(1).strip().splitlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # "ROE: 8%" or "ROE = 8%"
            kv = re.match(r"^([^:=]+?)\s*[:=]\s*(.+)$", line)
            if kv:
                key_metrics[kv.group(1).strip()] = kv.group(2).strip()

    return PersonaSignal(
        persona=persona_id,
        verdict=verdict,
        confidence=confidence,
        rationale=rationale,
        key_metrics=key_metrics,
    )


# ── Data fetcher ──────────────────────────────────────────────


def _fetch_data_brief(
    symbol: str,
    exchange: str,
    registry: Any,
) -> dict[str, Any]:
    """
    Fetch technical, fundamental, and macro data for the symbol.

    Returns a dict with all available data. Empty / default values used
    when registry is None or a tool raises an exception.
    """
    brief: dict[str, Any] = {
        "symbol": symbol,
        "exchange": exchange,
        "technicals": {},
        "fundamentals": {},
        "macro": {},
        "news": [],
        "fii_dii": {},
        "options": {},
    }

    if registry is None:
        return brief

    def _safe_call(tool_name: str, **kwargs) -> Any:
        try:
            fn = registry.get_fn(tool_name)
            if fn is None:
                return None
            return fn(**kwargs)
        except Exception:
            return None

    # Technical snapshot
    tech = _safe_call("technical_analyse", symbol=symbol, exchange=exchange)
    if tech:
        t_dict = tech if isinstance(tech, dict) else (tech.as_dict() if hasattr(tech, "as_dict") else vars(tech))
        if "verdict" in t_dict and "trend" not in t_dict:
            t_dict["trend"] = t_dict["verdict"]
        if "rsi" in t_dict and "RSI" not in t_dict:
            t_dict["RSI"] = t_dict["rsi"]
        brief["technicals"] = t_dict

    # Fundamental snapshot
    fund = _safe_call("fundamental_analyse", symbol=symbol)
    if fund:
        f_dict = fund if isinstance(fund, dict) else (fund.as_dict() if hasattr(fund, "as_dict") else vars(fund))
        brief["fundamentals"] = f_dict

    # Forensic snapshot
    forensic = _safe_call("audit_forensics", symbol=symbol)
    if forensic:
        brief["forensics"] = (
            forensic
            if isinstance(forensic, dict)
            else (forensic.as_dict() if hasattr(forensic, "as_dict") else vars(forensic))
        )

    # FII/DII data
    fii = _safe_call("get_fii_dii_data")
    if fii:
        if isinstance(fii, dict):
            brief["fii_dii"] = fii
        elif isinstance(fii, list) and len(fii) > 0:
            first = fii[0]
            brief["fii_dii"] = first if isinstance(first, dict) else (first.as_dict() if hasattr(first, "as_dict") else (vars(first) if hasattr(first, "__dict__") else {"raw": str(first)}))
        elif hasattr(fii, "as_dict"):
            brief["fii_dii"] = fii.as_dict()
        elif hasattr(fii, "__dict__"):
            brief["fii_dii"] = vars(fii)

    # Market snapshot
    macro = _safe_call("get_market_snapshot")
    if macro:
        if isinstance(macro, dict):
            brief["macro"] = macro
        elif hasattr(macro, "as_dict"):
            brief["macro"] = macro.as_dict()
        elif hasattr(macro, "__dict__"):
            brief["macro"] = vars(macro)
        if hasattr(macro, "vix") and macro.vix and "india_vix" not in brief["macro"]:
            brief["macro"]["india_vix"] = getattr(macro.vix, "ltp", None) or getattr(macro.vix, "price", None)

    # Options snapshot
    pcr_data = _safe_call("get_pcr", underlying=symbol)
    if pcr_data is None:
        pcr_data = _safe_call("get_pcr", symbol=symbol)
    if pcr_data is not None:
        if isinstance(pcr_data, dict):
            brief["options"] = pcr_data
            if "pcr" in pcr_data and "pcr" not in brief["technicals"]:
                brief["technicals"]["pcr"] = pcr_data["pcr"]
        elif isinstance(pcr_data, (int, float)):
            brief["options"] = {"pcr": float(pcr_data)}
            if "pcr" not in brief["technicals"]:
                brief["technicals"]["pcr"] = float(pcr_data)
        elif hasattr(pcr_data, "__dict__"):
            brief["options"] = vars(pcr_data)
            if hasattr(pcr_data, "pcr") and "pcr" not in brief["technicals"]:
                brief["technicals"]["pcr"] = getattr(pcr_data, "pcr")

    # News
    news = _safe_call("get_stock_news", symbol=symbol)
    if news and isinstance(news, list):
        brief["news"] = news[:5]  # limit to 5 headlines

    return brief


def _build_prompt(symbol: str, exchange: str, brief: dict[str, Any]) -> str:
    """Build a compact data brief string for the LLM prompt."""
    lines = [
        "=== Stock Analysis Request ===",
        f"Symbol: {symbol} | Exchange: {exchange}",
        "",
    ]

    tech = brief.get("technicals", {})
    if tech:
        lines.append("--- Technical Data ---")
        for k, v in list(tech.items())[:10]:
            lines.append(f"  {k}: {v}")
        lines.append("")

    fund = brief.get("fundamentals", {})
    if fund:
        lines.append("--- Fundamentals ---")
        for k, v in list(fund.items())[:15]:
            lines.append(f"  {k}: {v}")
        lines.append("")

    forensic = brief.get("forensics", {})
    if forensic:
        lines.append("--- Forensic & Governance Audit ---")
        for k, v in list(forensic.items())[:12]:
            lines.append(f"  {k}: {v}")
        lines.append("")

    macro = brief.get("macro", {})
    if macro:
        lines.append("--- Macro Data ---")
        for k, v in list(macro.items())[:8]:
            lines.append(f"  {k}: {v}")
        lines.append("")

    fii = brief.get("fii_dii", {})
    if fii:
        lines.append("--- FII/DII Flows ---")
        for k, v in list(fii.items())[:5]:
            lines.append(f"  {k}: {v}")
        lines.append("")

    news = brief.get("news", [])
    if news:
        lines.append("--- Recent News ---")
        for headline in news[:3]:
            lines.append(f"  • {headline}")
        lines.append("")

    lines += [
        "=== MANDATORY INSTRUCTION FOR AI PERSONA ===",
        "1. You MUST ALWAYS evaluate the stock strictly based on the provided technical, fundamental, and forensic metrics.",
        "2. Do not invent unavailable data. If the evidence is insufficient, return UNAVAILABLE with CONFIDENCE: 0 and state what is missing.",
        "3. Always output valid structured output matching the format below.",
        "",
        "=== Required Output Format ===",
        "VERDICT: <STRONG_BUY|BUY|HOLD|SELL|STRONG_SELL|UNAVAILABLE>",
        "CONFIDENCE: <0-100>",
        "RATIONALE:",
        "- <checklist item 1>",
        "- <checklist item 2>",
        "- <checklist item 3>",
        "KEY_METRICS:",
        "<metric name>: <value and context>",
        "",
        "Then provide 2-3 sentences of reasoning in neutral, original analyst language. "
        "Do not claim to be, speak as, or imitate any named person.",
    ]

    return "\n".join(lines)


# ── Rule-based fallback scorer ────────────────────────────────


def _score_dimension(dimension: str, brief: dict[str, Any]) -> float | None:
    """
    Score a single dimension 0–100 using simple heuristics on available data.

    Returns None when the dimension has no evidence.  A neutral-looking score
    is still a fabricated recommendation when no underlying data was supplied.
    """
    tech = brief.get("technicals", {})
    fund = brief.get("fundamentals", {})
    macro = brief.get("macro", {})
    fii = brief.get("fii_dii", {})

    if dimension == "fundamentals":
        forensic = brief.get("forensics", {})
        if not any(
            value is not None
            for value in (
                fund.get("roe"),
                fund.get("ROE"),
                fund.get("debt_equity"),
                fund.get("de"),
                fund.get("D/E"),
                fund.get("pe"),
                fund.get("PE"),
                fund.get("fcf_yield"),
                fund.get("FCF_yield"),
                fund.get("score"),
                fund.get("verdict"),
                forensic.get("piotroski_score"),
                forensic.get("altman_zone"),
                forensic.get("promoter_pledge_pct"),
            )
        ):
            return None
        score = 50.0
        roe = fund.get("roe") or fund.get("ROE")
        if roe is not None:
            try:
                roe = float(roe)
                score += 15 if roe > 15 else (-10 if roe < 8 else 5)
            except (TypeError, ValueError):
                pass

        de = fund.get("debt_equity") or fund.get("de") or fund.get("D/E")
        if de is not None:
            try:
                de = float(de)
                score += 10 if de < 0.5 else (-10 if de > 1.5 else 0)
            except (TypeError, ValueError):
                pass

        pe = fund.get("pe") or fund.get("PE")
        if pe is not None:
            try:
                pe = float(pe)
                score += 10 if pe < 15 else (-10 if pe > 40 else 0)
            except (TypeError, ValueError):
                pass

        fcf_yield = fund.get("fcf_yield") or fund.get("FCF_yield")
        if fcf_yield is not None:
            try:
                fcf_yield = float(fcf_yield)
                score += 10 if fcf_yield > 5 else (-5 if fcf_yield < 2 else 0)
            except (TypeError, ValueError):
                pass

        f_score = fund.get("score")
        if f_score is not None:
            try:
                fs = float(f_score)
                score = (score + fs) / 2.0
            except (TypeError, ValueError):
                pass

        # Forensic indicators
        if forensic:
            piotroski = forensic.get("piotroski_score")
            if piotroski is not None:
                try:
                    p = float(piotroski)
                    score += 15 if p >= 7 else (-15 if p <= 4 else 0)
                except (TypeError, ValueError):
                    pass
            altman = forensic.get("altman_zone")
            if altman:
                if "SAFE" in str(altman).upper():
                    score += 10
                elif "DISTRESS" in str(altman).upper():
                    score -= 20
            pledge = forensic.get("promoter_pledge_pct")
            if pledge is not None:
                try:
                    pl = float(pledge)
                    score += 5 if pl < 5 else (-15 if pl > 20 else 0)
                except (TypeError, ValueError):
                    pass

        return max(0.0, min(100.0, score))

    elif dimension == "technicals":
        if not any(
            value is not None
            for value in (
                tech.get("rsi"),
                tech.get("RSI"),
                tech.get("trend"),
                tech.get("price_trend"),
                tech.get("verdict"),
                tech.get("score"),
            )
        ):
            return None
        score = 50.0
        rsi = tech.get("rsi") if tech.get("rsi") is not None else tech.get("RSI")
        if rsi is not None:
            try:
                rsi = float(rsi)
                if rsi < 30:
                    score += 20  # oversold → buy signal
                elif rsi > 70:
                    score -= 15  # overbought → cautious
                elif 40 <= rsi <= 60:
                    score += 5  # neutral zone
            except (TypeError, ValueError):
                pass

        trend = tech.get("trend") or tech.get("price_trend") or tech.get("verdict")
        if trend:
            trend_str = str(trend).upper()
            if "BULL" in trend_str or "UP" in trend_str:
                score += 10
            elif "BEAR" in trend_str or "DOWN" in trend_str:
                score -= 10

        t_score = tech.get("score")
        if t_score is not None:
            try:
                ts = float(t_score)
                score = (score + ts) / 2.0
            except (TypeError, ValueError):
                pass

        return max(0.0, min(100.0, score))

    elif dimension == "macro":
        if not any(
            value is not None
            for value in (
                fii.get("net"),
                fii.get("fii_net"),
                fii.get("FII_net"),
                macro.get("india_vix"),
                macro.get("VIX"),
                macro.get("vix"),
            )
        ):
            return None
        score = 50.0
        # FII flows
        fii_net = fii.get("net") or fii.get("fii_net") or fii.get("FII_net")
        if fii_net is not None:
            try:
                fii_net = float(fii_net)
                score += 15 if fii_net > 0 else (-10 if fii_net < 0 else 0)
            except (TypeError, ValueError):
                pass

        # Market regime
        vix = macro.get("india_vix") or macro.get("VIX") or macro.get("vix")
        if vix is not None:
            try:
                vix = float(vix)
                score += 10 if vix < 15 else (-15 if vix > 25 else 0)
            except (TypeError, ValueError):
                pass

        return max(0.0, min(100.0, score))

    elif dimension == "sentiment":
        if not brief.get("news"):
            return None
        # Article volume is attention, not sentiment. The raw provider payload
        # has no verified polarity score, so it must not create a bullish signal.
        return None

    elif dimension == "options":
        opt = brief.get("options", {})
        pcr_val = (
            opt.get("pcr")
            if opt.get("pcr") is not None
            else (tech.get("pcr") if tech.get("pcr") is not None else tech.get("put_call_ratio"))
        )
        if pcr_val is None:
            if opt.get("atm_iv") is not None or opt.get("gex") is not None or opt.get("iv") is not None:
                pcr_val = 1.0
            else:
                return None
        score = 50.0
        try:
            pcr = float(pcr_val)
            # PCR > 1.5 → bullish contrarian signal; PCR < 0.5 → bearish contrarian
            if pcr > 1.5:
                score += 15
            elif 0 < pcr < 0.5:
                score -= 10
            elif pcr >= 0.5:
                score += 5
        except (TypeError, ValueError):
            pass
        return max(0.0, min(100.0, score))

    return None


def _rule_based_signal(
    persona_id: str,
    brief: dict[str, Any],
) -> PersonaSignal:
    """
    Deterministic rule-based signal using persona weights × dimension scores.

    No LLM required.
    """
    from agent.personas import get_persona

    persona = get_persona(persona_id)

    weighted_sum = 0.0
    applied_weight = 0.0
    checklist_results: list[str] = []
    key_metrics: dict[str, str] = {}

    for dimension, weight in persona.weights.items():
        dim_score = _score_dimension(dimension, brief)
        if dim_score is None:
            checklist_results.append(f"— {dimension.title()}: unavailable (no verified evidence)")
            key_metrics[dimension.title()] = "UNAVAILABLE"
            continue
        weighted_sum += dim_score * weight
        applied_weight += weight

        # Produce a checklist entry for each dimension
        level = "strong" if dim_score >= 65 else ("weak" if dim_score <= 40 else "neutral")
        symbol_map = {"strong": "✓", "neutral": "~", "weak": "✗"}
        checklist_results.append(
            f"{symbol_map[level]} {dimension.title()} score: {dim_score:.0f}/100 ({level})"
        )
        key_metrics[dimension.title()] = f"{dim_score:.0f}/100"

    # Add persona-specific checklist items
    for item in persona.checklist[:3]:
        checklist_results.append(f"~ {item} (data insufficient for precise check)")

    if applied_weight <= 0:
        return PersonaSignal(
            persona=persona_id,
            verdict="UNAVAILABLE",
            confidence=0,
            rationale=checklist_results[:6]
            or ["No verified evidence was available for this analysis."],
            key_metrics=key_metrics,
        )

    # Normalize only over dimensions with actual evidence.
    score = weighted_sum / applied_weight
    if score >= 80:
        verdict = "STRONG_BUY"
    elif score >= 65:
        verdict = "BUY"
    elif score >= 40:
        verdict = "HOLD"
    elif score >= 25:
        verdict = "SELL"
    else:
        verdict = "STRONG_SELL"

    coverage = min(1.0, applied_weight)
    confidence = max(0, min(90, int(score * coverage)))

    return PersonaSignal(
        persona=persona_id,
        verdict=verdict,
        confidence=confidence,
        rationale=checklist_results[:6],
        key_metrics=key_metrics,
    )


# ── LLM caller ────────────────────────────────────────────────


def _call_llm(
    system_prompt: str,
    user_message: str,
    llm_provider: Any,
) -> str:
    """Call the LLM provider with system + user message. Returns response text."""
    try:
        # Try the standard call interface used by the platform
        if hasattr(llm_provider, "call"):
            return llm_provider.call(
                system=system_prompt,
                message=user_message,
            )
        # Fallback: direct chat method
        if hasattr(llm_provider, "chat"):
            return llm_provider.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ]
            )
        # Generic: try __call__
        if callable(llm_provider):
            return str(llm_provider(system_prompt, user_message))
    except Exception as exc:
        # Any LLM failure → return empty (caller will use rule-based fallback)
        return f"LLM call failed: {exc}"
    return ""


# ── Public API ────────────────────────────────────────────────


def run_persona_analysis(
    persona_id: str,
    symbol: str,
    exchange: str = "NSE",
    registry: Any = None,
    llm_provider: Any = None,
) -> PersonaSignal:
    """
    Run a single persona analysis on a symbol.

    Parameters
    ----------
    persona_id:    One of 'buffett', 'jhunjhunwala', 'lynch', 'soros', 'munger'
    symbol:        Stock ticker, e.g. 'RELIANCE'
    exchange:      'NSE' or 'BSE'
    registry:      ToolRegistry for live data; if None, analysis uses empty data
    llm_provider:  LLM provider instance; if None, uses deterministic fallback

    Returns
    -------
    PersonaSignal
    """
    # Validate persona (raises ValueError for unknown ids)
    persona = get_persona(persona_id)

    # 1. Initialize ToolRegistry and LLM Provider if explicitly requested as 'auto'
    if llm_provider == "auto":
        if registry is None:
            try:
                from agent.tools import build_registry

                registry = build_registry()
            except Exception:
                registry = None
        try:
            from agent.core import get_provider

            llm_provider = get_provider(registry=registry)
        except Exception:
            llm_provider = None

    # 2. Fetch data
    brief = _fetch_data_brief(symbol, exchange, registry)

    # A fluent LLM response is not a substitute for the evidence its framework
    # needs. Require the persona's most heavily weighted dimension before an
    # LLM may emit a directional verdict; otherwise fail closed.
    primary_dimension = max(persona.weights, key=persona.weights.get)
    if _score_dimension(primary_dimension, brief) is None:
        return PersonaSignal(
            persona=persona_id,
            verdict="UNAVAILABLE",
            confidence=0,
            rationale=[
                f"{primary_dimension.title()} evidence is unavailable; this framework cannot form a verified conclusion."
            ],
            key_metrics={primary_dimension.title(): "UNAVAILABLE"},
        )

    # 3. LLM path
    if llm_provider is not None:
        prompt = _build_prompt(symbol, exchange, brief)
        safe_system_prompt = (
            "You are an original investment-research assistant applying a published "
            "analytical framework. The reference text below is methodology only: never "
            "claim to be, impersonate, or imitate the named person. Use neutral analyst "
            "language and return UNAVAILABLE when the supplied evidence is insufficient.\n\n"
            + persona.system_prompt
        )
        response_text = _call_llm(
            system_prompt=safe_system_prompt,
            user_message=prompt,
            llm_provider=llm_provider,
        )
        if response_text and not any(
            err in response_text.lower()
            for err in (
                "llm call failed",
                "gemini error",
                "503 unavailable",
                "resource_exhausted",
                "[gemini error",
                "i do not have access",
                "would you like me to",
                "please provide",
                "cannot evaluate",
                "insufficient financial data",
            )
        ):
            sig = parse_persona_response(response_text, persona_id)
            if sig and sig.rationale and not any("error" in r.lower() for r in sig.rationale):
                sig.key_metrics["Analysis Engine"] = (
                    f"AI Multi-Agent ({getattr(llm_provider, 'model', 'LLM')})"
                )
                return sig
        # Fall through to rule-based if LLM failed or refused

    # 3. Rule-based fallback
    try:
        from engine.telemetry import record_event, EVENT_QUANT_FALLBACK

        record_event(
            event_type=EVENT_QUANT_FALLBACK,
            component="persona_agent",
            action_taken=f"Switched to deterministic rule-based quantitative signal for {persona_id}",
            reason="LLM provider offline, throttling, or returned empty/error response",
            details={"persona": persona_id, "symbol": symbol, "exchange": exchange},
            severity="WARNING",
        )
    except Exception:
        pass

    sig = _rule_based_signal(persona_id, brief)
    sig.key_metrics["Analysis Engine"] = "Quantitative Engine (Deterministic Fallback)"
    return sig


def run_debate(
    symbol: str,
    exchange: str = "NSE",
    registry: Any = None,
    llm_provider: Any = None,
) -> list[PersonaSignal]:
    """
    Run all defined personas and return their signals.

    Parameters
    ----------
    symbol:       Stock ticker
    exchange:     'NSE' or 'BSE'
    registry:     ToolRegistry for live data
    llm_provider: LLM provider; if None uses deterministic fallback for all

    Returns
    -------
    list[PersonaSignal] — one per persona, in stable order
    """
    if registry is None:
        try:
            from agent.tools import build_registry

            registry = build_registry()
        except Exception:
            registry = None

    personas = list_personas()
    signals: list[PersonaSignal] = []

    for persona in personas:
        signal = run_persona_analysis(
            persona_id=persona.id,
            symbol=symbol,
            exchange=exchange,
            registry=registry,
            llm_provider=llm_provider,
        )
        signals.append(signal)

    return signals


# ── Council Ensembles ─────────────────────────────────────────

COUNCIL_PRESETS: dict[str, list[str]] = {
    "breakout": ["minervini", "wyckoff", "oneil", "forensic"],
    "options_sniper": ["smc", "taleb", "simons"],
    "multibagger": ["kedia", "buffett", "munger", "jhunjhunwala", "forensic"],
    "macro_regime": ["soros", "jhunjhunwala", "simons", "forensic"],
    "core_value": ["buffett", "munger", "lynch", "forensic"],
}


def run_council(
    council_name: str,
    symbol: str,
    exchange: str = "NSE",
    registry: Any = None,
    llm_provider: Any = None,
) -> dict[str, Any]:
    """
    Run a specialized council ensemble of personas and synthesize a consensus recommendation.
    """
    c_key = council_name.lower().replace("-", "_").replace(" ", "_")
    persona_ids = COUNCIL_PRESETS.get(c_key)
    if not persona_ids:
        valid = ", ".join(sorted(COUNCIL_PRESETS))
        raise ValueError(f"Unknown council '{council_name}'. Choose one of: {valid}.")

    # Build platform tool registry once for all council members
    if registry is None:
        try:
            from agent.tools import build_registry

            registry = build_registry()
        except Exception:
            registry = None

    signals = [
        run_persona_analysis(pid, symbol, exchange, registry, llm_provider) for pid in persona_ids
    ]

    verdict_scores = {
        "STRONG_BUY": 100,
        "BUY": 75,
        "HOLD": 50,
        "SELL": 25,
        "STRONG_SELL": 0,
    }
    available_signals = [s for s in signals if s.verdict != "UNAVAILABLE" and s.confidence > 0]
    if not available_signals:
        return {
            "council": council_name,
            "symbol": symbol.upper(),
            "exchange": exchange.upper(),
            "consensus_verdict": "UNAVAILABLE",
            "consensus_score": None,
            "signals": signals,
            "member_count": len(signals),
            "available_member_count": 0,
            "reason": "No council member had enough verified evidence to form a recommendation.",
            "actionable": False,
        }

    total_score = sum(verdict_scores[s.verdict] * (s.confidence / 100.0) for s in available_signals)
    weight_sum = sum(s.confidence / 100.0 for s in available_signals)
    consensus_score = total_score / weight_sum

    if consensus_score >= 80:
        consensus_verdict = "STRONG_BUY"
    elif consensus_score >= 65:
        consensus_verdict = "BUY"
    elif consensus_score >= 40:
        consensus_verdict = "HOLD"
    elif consensus_score >= 25:
        consensus_verdict = "SELL"
    else:
        consensus_verdict = "STRONG_SELL"

    return {
        "council": council_name,
        "symbol": symbol.upper(),
        "exchange": exchange.upper(),
        "consensus_verdict": consensus_verdict,
        "consensus_score": round(consensus_score, 1),
        "signals": signals,
        "member_count": len(signals),
        "available_member_count": len(available_signals),
        # Councils are research aids, never authority to pre-fill or submit a trade.
        "actionable": False,
    }


def print_council_verdict(res: dict[str, Any]) -> None:
    """Print high-density Rich visualization of council signals."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()

    v_color = {
        "STRONG_BUY": "bold green",
        "BUY": "green",
        "HOLD": "yellow",
        "SELL": "red",
        "STRONG_SELL": "bold red",
    }.get(res["consensus_verdict"], "cyan")

    table = Table(
        title=f"🏛️ Council: {res['council'].upper()} — {res['symbol']} ({res['exchange']})",
        border_style="cyan",
    )
    table.add_column("Persona", style="bold white", width=22)
    table.add_column("Verdict", width=14)
    table.add_column("Confidence", justify="right", width=12)
    table.add_column("Key Rationale / Checklist", style="dim")

    for s in res["signals"]:
        pv_color = "green" if "BUY" in s.verdict else ("red" if "SELL" in s.verdict else "yellow")
        rationale_snip = s.rationale[0] if s.rationale else "No rationale provided"
        table.add_row(
            s.persona.title(),
            f"[{pv_color}]{s.verdict}[/{pv_color}]",
            f"{s.confidence}%",
            rationale_snip,
        )

    summary_text = (
        f"Consensus Verdict: [{v_color}]{res['consensus_verdict']}[/{v_color}]  "
        f"(Conviction Score: [bold]{res['consensus_score']}/100[/bold])\n"
        f"Council Members: {res['member_count']} Specialist Personas Polled"
    )

    console.print(table)
    console.print(
        Panel(
            summary_text,
            title="🎯 Council Decision Synthesis",
            border_style="green" if "BUY" in res["consensus_verdict"] else "yellow",
        )
    )
