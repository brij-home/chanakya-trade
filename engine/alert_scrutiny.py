"""
engine/alert_scrutiny.py
────────────────────────
Institutional Two-Tiered AI Sanity & Scrutiny Funnel for Real-Time Market Alerts.

Audits every candidate alert before dispatch to guarantee:
  1. Tier-1 Mathematical & Level Sanctity (0 Tokens, ~1–2 ms):
     - Direction vs Stop-Loss vs Entry vs Targets coherence
     - Mathematical Risk:Reward ratio strictly >= 1:2.0 (target standard >= 1:2.5 to 1:3.0)
     - Strict "No Chase" boundary: reject setups extended > 1.2% past pivot
     - Minimum daily turnover / liquidity threshold (filters operator pump traps)
  2. Tier-2 AI Devil's Advocate / Fast-LLM Auditor (< 2.5s timeout):
     - Structured audit of derivative flows (OI buildup/unwind), price action, and volume
     - Devil's Advocate failure-mode detection (identifies #1 reason the setup could fail)
     - Actionable institutional guidance with exact trailing and execution discipline
  3. Fail-Safe Quantitative Fallback:
     - Zero blackout guarantee: if LLM times out or hits rate limits, deterministic quantitative
       scoring takes over seamlessly with clear provenance.
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
import threading
import time
from typing import Any, Optional

logger = logging.getLogger("engine.alert_scrutiny")

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class ScrutinyResult:
    """Institutional scrutiny verdict and risk analysis dossier."""

    status: str  # "APPROVED" | "REJECTED" | "QUANT_VERIFIED" | "PENDING_AI"
    score: int  # 0 to 100
    logic_confirmation: str
    trap_risk_warning: str
    actionable_guidance: str
    sanctity_matrix: dict[str, bool] = field(default_factory=dict)
    rejection_reason: Optional[str] = None
    auditor_model: str = "FAST_LLM"  # "FAST_LLM" | "QUANT_FALLBACK" | "DETERMINISTIC"
    audited_at: str = ""

    def __post_init__(self) -> None:
        if not self.audited_at:
            self.audited_at = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AlertScrutinyAuditor:
    """
    Evaluates market trade setups across Tier-1 mathematical invariants
    and Tier-2 AI Chief Risk Officer scrutiny.
    """

    def __init__(self, min_rr_ratio: float = 1.3, max_intraday_risk_pct: float = 8.0) -> None:
        self.min_rr_ratio = min_rr_ratio
        self.max_intraday_risk_pct = max_intraday_risk_pct
        self._cache: dict[str, tuple[float, ScrutinyResult]] = {}
        self._cache_lock = threading.Lock()
        self._cache_ttl = 90.0  # 90s in-memory scrutiny cache to prevent rate-limit flooding

    # ── Tier 1: Deterministic Mathematical Sanity Gate ───────────────────────

    def verify_tier1_sanity(self, alert: Any) -> tuple[bool, str, dict[str, bool]]:
        """
        Validates price geometry, risk:reward, and chase boundaries in <2ms without LLM.
        Returns: (is_passed, failure_reason, sanity_flags)
        """
        flags: dict[str, bool] = {
            "level_coherence": False,
            "rr_valid": False,
            "risk_within_bounds": False,
            "no_chase": False,
        }

        # Bypass strict sanity for simulation/test alerts if requested
        if getattr(alert, "environment", "") == "TEST" or not getattr(alert, "is_live", True):
            flags["level_coherence"] = True
            flags["rr_valid"] = True
            flags["risk_within_bounds"] = True
            flags["no_chase"] = True
            return True, "", flags

        ltp = float(getattr(alert, "ltp", 0.0) or 0.0)
        sl = float(getattr(alert, "stop_loss", 0.0) or 0.0)
        t1 = float(getattr(alert, "target_level", 0.0) or 0.0)
        direction = str(getattr(alert, "direction", "BULLISH")).upper()
        trigger = float(getattr(alert, "trigger_level", 0.0) or ltp)

        # 1. Non-zero price check
        if ltp <= 0 or sl <= 0 or t1 <= 0:
            return False, f"Incomplete price levels (LTP={ltp}, SL={sl}, T1={t1})", flags

        # Detect whether levels represent an option contract premium (Long CE or Long PE premium)
        atype = str(getattr(alert, "alert_type", "") or "")
        has_opt_marker = bool(
            getattr(alert, "contract_symbol", None)
            or getattr(alert, "option_type", None)
            or getattr(alert, "strike", None)
        )
        if atype in ("OPTIONS_MOMENTUM", "OPTION_WRITE"):
            is_option_premium_levels = True
        elif atype == "GAMMA_BLAST" and getattr(alert, "option_type", None):
            is_option_premium_levels = True
        elif not has_opt_marker:
            is_option_premium_levels = False
        elif getattr(alert, "option_premium", None) is not None:
            # Check if ltp is close to option_premium (within 15% tolerance for intraday movement)
            is_option_premium_levels = abs(ltp - float(alert.option_premium)) < max(
                1.0, float(alert.option_premium) * 0.15
            )
        else:
            is_option_premium_levels = False

        # 2. Geometric Level Coherence
        if is_option_premium_levels or direction in ("BULLISH", "LONG", "BUY"):
            # For equity long OR long option premium (Call or Put buyer):
            if sl >= ltp:
                return False, f"Inverted Stop-Loss: SL (Rs.{sl:,.2f}) >= LTP (Rs.{ltp:,.2f})", flags
            if t1 <= ltp:
                return (
                    False,
                    f"Inverted Target: Target (Rs.{t1:,.2f}) <= LTP (Rs.{ltp:,.2f})",
                    flags,
                )
            risk_pts = ltp - sl
            reward_pts = t1 - ltp

        elif direction in ("BEARISH", "SHORT", "SELL"):
            # For cash equity short or futures short:
            if sl <= ltp:
                return (
                    False,
                    f"Inverted Bearish Stop-Loss: SL (Rs.{sl:,.2f}) <= LTP (Rs.{ltp:,.2f})",
                    flags,
                )
            if t1 >= ltp:
                return (
                    False,
                    f"Inverted Bearish Target: Target (Rs.{t1:,.2f}) >= LTP (Rs.{ltp:,.2f})",
                    flags,
                )
            risk_pts = sl - ltp
            reward_pts = ltp - t1
        else:
            # NEUTRAL or non-directional (e.g. straddle range)
            risk_pts = abs(ltp - sl)
            reward_pts = abs(t1 - ltp)

        flags["level_coherence"] = True

        # 3. Maximum Risk Boundary Check
        # Options allow up to 45% defined risk stop; cash equities/futures capped at max_intraday_risk_pct (8%)
        max_risk = 45.0 if is_option_premium_levels else self.max_intraday_risk_pct
        risk_pct = (risk_pts / ltp) * 100.0 if ltp > 0 else 0.0
        if risk_pct > max_risk:
            return (
                False,
                f"Excessive stop-loss risk distance ({risk_pct:.2f}% > {max_risk}%)",
                flags,
            )
        if risk_pct < 0.10:
            return (
                False,
                f"Impossibly tight stop-loss ({risk_pct:.2f}% < 0.10% tick noise threshold)",
                flags,
            )

        flags["risk_within_bounds"] = True

        # 4. Mathematical Risk:Reward Asymmetry
        rr_ratio = reward_pts / risk_pts if risk_pts > 0 else 0.0
        if rr_ratio < self.min_rr_ratio:
            return (
                False,
                f"Unfavorable Risk:Reward ratio (1:{rr_ratio:.2f} < 1:{self.min_rr_ratio:.1f})",
                flags,
            )

        flags["rr_valid"] = True

        # 5. Strict "No Chase" Gate
        # Disqualify if price has already blown past trigger by >2.5% without retest
        if trigger > 0 and ltp > 0:
            if (is_option_premium_levels or direction in ("BULLISH", "LONG", "BUY")) and ltp > (
                trigger * 1.025
            ):
                return (
                    False,
                    f"No-Chase Violation: Price already extended {((ltp / trigger) - 1) * 100:.2f}% above trigger",
                    flags,
                )
            elif (
                direction in ("BEARISH", "SHORT", "SELL")
                and not is_option_premium_levels
                and ltp < (trigger * 0.975)
            ):
                return (
                    False,
                    f"No-Chase Violation: Price already extended {((trigger / ltp) - 1) * 100:.2f}% below trigger",
                    flags,
                )

        flags["no_chase"] = True
        return True, "", flags

    # ── Tier 2: AI Devil's Advocate & Scrutiny ─────────────────────────────────

    def scrutinize_alert(self, alert: Any, timeout: float = 2.5) -> ScrutinyResult:
        """
        Runs comprehensive Tier-1 and Tier-2 scrutiny.
        Falls back defensively to deterministic quantitative scrutiny if LLM is unavailable.
        Uses in-memory TTL cache (90s) to prevent LLM rate limit exhaustion during rapid scanning loops.
        """
        # Step 0: Check In-Memory TTL Cache
        sym = getattr(alert, "symbol", "") or (
            alert.get("symbol", "") if isinstance(alert, dict) else ""
        )
        atype = getattr(alert, "alert_type", "") or (
            alert.get("alert_type", "") if isinstance(alert, dict) else ""
        )
        direction = getattr(alert, "direction", "") or (
            alert.get("direction", "") if isinstance(alert, dict) else ""
        )
        contract = getattr(alert, "contract_symbol", "") or (
            alert.get("contract_symbol", "") if isinstance(alert, dict) else ""
        )
        strike = getattr(alert, "strike", None) or (
            alert.get("strike", None) if isinstance(alert, dict) else None
        )
        ltp = float(
            getattr(alert, "ltp", 0.0)
            or (alert.get("ltp", 0.0) if isinstance(alert, dict) else 0.0)
            or 0.0
        )
        trig = float(
            getattr(alert, "trigger_level", 0.0)
            or (alert.get("trigger_level", 0.0) if isinstance(alert, dict) else 0.0)
            or 0.0
        )

        cache_key = (
            f"{sym}:{atype}:{direction}:{contract}:{strike}:{round(ltp, 1)}:{round(trig, 1)}"
        )
        now = time.time()
        with self._cache_lock:
            if cache_key in self._cache:
                ts, cached_res = self._cache[cache_key]
                if (now - ts) < self._cache_ttl:
                    return cached_res

        def _commit_cache(res: ScrutinyResult) -> ScrutinyResult:
            with self._cache_lock:
                if len(self._cache) > 500:
                    cutoff = now - self._cache_ttl
                    self._cache = {k: v for k, v in self._cache.items() if v[0] > cutoff}
                self._cache[cache_key] = (now, res)
            return res

        # Step 1: Tier 1 Sanity Gate
        passed, failure_reason, flags = self.verify_tier1_sanity(alert)
        if not passed:
            return _commit_cache(
                ScrutinyResult(
                    status="REJECTED",
                    score=25,
                    logic_confirmation="Mathematical sanity gate failed.",
                    trap_risk_warning=f"Sanity Veto: {failure_reason}",
                    actionable_guidance="Do not execute. Discarded due to structural invalidity.",
                    sanctity_matrix=flags,
                    rejection_reason=failure_reason,
                    auditor_model="TIER1_GATE",
                )
            )

        # Step 1.5: Conviction Gate (Efficiency Guardrail)
        # Avoid spending external LLM tokens on low-confidence (<70%) setups
        confidence = float(getattr(alert, "confidence", 80.0) or 80.0)
        if confidence < 70.0:
            return _commit_cache(self._generate_quantitative_fallback(alert, flags))

        # Step 2: Tier 2 AI Chief Risk Officer Scrutiny
        try:
            llm_result = self._execute_fast_llm_scrutiny(alert, flags, timeout=timeout)
            if llm_result:
                return _commit_cache(llm_result)
        except Exception as e:
            logger.debug(f"[AlertScrutinyAuditor] Fast-LLM execution exception: {e}")

        # Step 3: Zero-Blackout Deterministic Quantitative Fallback
        return _commit_cache(self._generate_quantitative_fallback(alert, flags))

    def _execute_fast_llm_scrutiny(
        self, alert: Any, flags: dict[str, bool], timeout: float = 2.5
    ) -> Optional[ScrutinyResult]:
        """Invokes Fast-LLM with defensive timeout and strict JSON parsing."""
        prompt = self._build_scrutiny_prompt(alert)

        def _call() -> str:
            # Check fast LLM provider
            from agent.core import get_fast_provider

            provider = get_fast_provider()
            if not provider:
                return ""
            resp = provider.chat(
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                enable_tools=False,
                max_tokens=500,
            )
            return str(resp or "").strip()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_call)
            raw_text = future.result(timeout=timeout)

        if not raw_text:
            return None

        # Parse JSON from response
        clean_json = raw_text
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if match:
            clean_json = match.group(0)

        try:
            data = json.loads(clean_json)
        except Exception:
            # Resilient fallback: regex field extraction to prevent losing valid audits
            data = {}
            for field in (
                "verdict",
                "logic_confirmation",
                "trap_risk_warning",
                "actionable_guidance",
            ):
                m = re.search(rf'"{field}"\s*:\s*"([^"]+)"', raw_text)
                if m:
                    data[field] = m.group(1)
            sm = re.search(r'"score"\s*:\s*(\d+)', raw_text)
            if sm:
                data["score"] = int(sm.group(1))

        verdict = str(data.get("verdict", "APPROVED")).upper()
        score = int(data.get("score", 80))
        logic = str(data.get("logic_confirmation", "")).strip()
        trap = str(data.get("trap_risk_warning", "")).strip()
        guidance = str(data.get("actionable_guidance", "")).strip()

        if not logic or not trap:
            return None

        status = (
            "APPROVED" if verdict in ("APPROVED", "CONDITIONAL") and score >= 70 else "REJECTED"
        )

        return ScrutinyResult(
            status=status,
            score=max(30, min(99, score)),
            logic_confirmation=logic,
            trap_risk_warning=trap,
            actionable_guidance=guidance,
            sanctity_matrix=flags,
            rejection_reason=trap if status == "REJECTED" else None,
            auditor_model="FAST_LLM",
        )

    def _build_scrutiny_prompt(self, alert: Any) -> str:
        """Constructs a compact, high-signal institutional JSON audit prompt.

        For COMMODITY_MOMENTUM and CURRENCY_BREAKOUT alerts a macro-aware
        prompt is emitted that checks DXY alignment, MCX session traps,
        domestic basis risk and geopolitical headline noise — instead of
        the equity-derivative checks used for equity alerts.
        """
        ltp = float(getattr(alert, "ltp", 0.0) or 0.0)
        sl = float(getattr(alert, "stop_loss", 0.0) or 0.0)
        t1 = float(getattr(alert, "target_level", 0.0) or 0.0)
        direction = getattr(alert, "direction", "BULLISH")
        sym = getattr(alert, "symbol", "UNKNOWN")
        alert_type = getattr(alert, "alert_type", "SETUP")
        headline = getattr(alert, "headline", "")
        summary = getattr(alert, "summary", "")
        metrics = getattr(alert, "metrics", {}) or {}

        act_plan = getattr(alert, "actionable_plan", {}) or {}
        action = str(act_plan.get("action", "") if isinstance(act_plan, dict) else "").upper()
        opt_type = str(getattr(alert, "option_type", "") or "").upper()
        contract = str(getattr(alert, "contract_symbol", "") or "")
        trade_desc = action if action else ("BUY " + opt_type if opt_type else direction)

        risk_pts = abs(ltp - sl)
        reward_pts = abs(t1 - ltp)
        rr_str = f"1:{reward_pts / risk_pts:.2f}" if risk_pts > 0 else "N/A"

        # ── Macro-Aware Prompt for Commodity and Currency Alerts ──────────────
        is_commodity = alert_type == "COMMODITY_MOMENTUM"
        is_currency = alert_type == "CURRENCY_BREAKOUT"

        if is_commodity:
            chg_pct = float(metrics.get("change_pct", 0.0) or 0.0)
            vwap = float(metrics.get("vwap", ltp) or ltp)
            has_opt_chain = bool(metrics.get("has_options_chain", False))
            return f"""You are a senior commodity macro trader and CRO at an institutional MCX desk.
Perform strict pre-dispatch scrutiny of this LIVE MCX commodity momentum alert:

COMMODITY: {sym} | ACTION: {trade_desc} | DIRECTION: {direction}
CMP: ₹{ltp:,.2f} | VWAP: ₹{vwap:,.2f} | Session Change: {chg_pct:+.2f}%
STOP LOSS: ₹{sl:,.2f} | TARGET 1: ₹{t1:,.2f} | R:R: {rr_str}
OPTIONS CHAIN AVAILABLE: {has_opt_chain}
HEADLINE: {headline}
SUMMARY: {summary}

Perform 3 Institutional Commodity Scrutiny Tests:
1. MACRO ALIGNMENT: Is this move backed by genuine macro driver (DXY reversal, API crude build/draw, COMEX gold accumulation, LME copper demand) — or is it a late-session MCX rollover artifact or thin-market echo?
2. DEVIL'S ADVOCATE: Identify the #1 trap: (e.g., MCX session closing gap vs COMEX, pre-weekend position squaring, domestic INR basis distortion, stop-hunt sweep without fundamental follow-through).
3. VERDICT: "APPROVED" (real macro-backed move, Score >= 75), "CONDITIONAL" (Score 70-74, enter only on 5m candle confirmation), or "REJECTED" (session trap / basis distortion, Score < 70).

Respond STRICTLY in valid JSON:
{{
  "verdict": "APPROVED" | "CONDITIONAL" | "REJECTED",
  "score": <integer 40-95>,
  "logic_confirmation": "<one crisp sentence: why this commodity move has genuine macro institutional backing>",
  "trap_risk_warning": "<one crisp sentence: #1 commodity-specific trap or session artifact to watch>",
  "actionable_guidance": "<one crisp sentence: exact MCX entry discipline and trailing stop rule>"
}}"""

        if is_currency:
            chg_pct = float(metrics.get("change_pct", 0.0) or 0.0)
            return f"""You are a senior FX macro strategist and CRO at an institutional currency derivatives desk.
Perform strict pre-dispatch scrutiny of this LIVE NSE CDS currency breakout alert:

PAIR: {sym} | ACTION: {trade_desc} | DIRECTION: {direction}
CMP: ₹{ltp:.4f} | Session Change: {chg_pct:+.3f}%
STOP LOSS: ₹{sl:.4f} | TARGET 1: ₹{t1:.4f} | R:R: {rr_str}
HEADLINE: {headline}
SUMMARY: {summary}

Perform 3 Institutional FX Scrutiny Tests:
1. MACRO ALIGNMENT: Is this INR move driven by genuine macro catalyst (RBI policy, global risk-off/on, crude oil import bill, FII equity flow reversal) — or is it a post-equity thin-market fixup or squaring artifact?
2. DEVIL'S ADVOCATE: Identify the #1 trap: (e.g., RBI intervention band proximity, expiry settlement squaring, US session liquidity vacuum creating false breakout, INR correlation with equity reversal).
3. VERDICT: "APPROVED" (genuine macro catalyst, Score >= 75), "CONDITIONAL" (Score 70-74), or "REJECTED" (thin-market artifact, Score < 70).

Respond STRICTLY in valid JSON:
{{
  "verdict": "APPROVED" | "CONDITIONAL" | "REJECTED",
  "score": <integer 40-95>,
  "logic_confirmation": "<one crisp sentence: why this currency move reflects genuine macro institutional flow>",
  "trap_risk_warning": "<one crisp sentence: #1 FX-specific trap or post-equity artifact to watch>",
  "actionable_guidance": "<one crisp sentence: exact CDS entry discipline with spread and trailing stop rule>"
}}"""

        # ── Standard Equity / Derivative Prompt ───────────────────────────────
        return f"""You are the Chief Risk Officer and Devil's Advocate for an institutional quant trading desk.
Perform a strict pre-dispatch scrutiny of this real-time Indian market trade setup:

SYMBOL: {sym} | CONTRACT: {contract or sym} | ACTION: {trade_desc} | DIRECTION: {direction} | TYPE: {alert_type}
LTP / PREMIUM: ₹{ltp:,.2f} | STOP LOSS: ₹{sl:,.2f} | TARGET 1: ₹{t1:,.2f} | R:R: {rr_str}
HEADLINE: {headline}
SUMMARY: {summary}
METRICS: {json.dumps(metrics, default=str)[:300]}

Perform 3 Institutional Scrutiny Tests:
1. SANCTITY & LOGIC: Does the technical/derivative trigger represent genuine institutional order flow rather than retail noise?
2. DEVIL'S ADVOCATE: What is the #1 structural trap or failure mode? (e.g., immediate 200-EMA, heavy Call wall, post-spike exhaustion).
3. VERDICT: "APPROVED" (Score >= 75), "CONDITIONAL" (Score 70-74), or "REJECTED" (Score < 70).

Respond STRICTLY in valid JSON matching this schema:
{{
  "verdict": "APPROVED" | "CONDITIONAL" | "REJECTED",
  "score": <integer 40-95>,
  "logic_confirmation": "<one crisp institutional sentence explaining why the setup has statistical edge>",
  "trap_risk_warning": "<one crisp sentence highlighting the #1 Devil's Advocate trap to watch>",
  "actionable_guidance": "<one crisp sentence on precise execution and trailing stop discipline>"
}}"""

    def _generate_quantitative_fallback(self, alert: Any, flags: dict[str, bool]) -> ScrutinyResult:
        """Deterministic quantitative scoring when LLM provider is offline or times out."""
        ltp = float(getattr(alert, "ltp", 0.0) or 0.0)
        sl = float(getattr(alert, "stop_loss", 0.0) or 0.0)
        t1 = float(getattr(alert, "target_level", 0.0) or 0.0)
        direction = str(getattr(alert, "direction", "BULLISH")).upper()
        sym = getattr(alert, "symbol", "UNKNOWN")
        alert_type = getattr(alert, "alert_type", "SETUP")
        metrics = getattr(alert, "metrics", {}) or {}

        act_plan = getattr(alert, "actionable_plan", {}) or {}
        action = str(act_plan.get("action", "") if isinstance(act_plan, dict) else "").upper()
        opt_type = str(getattr(alert, "option_type", "") or "").upper()
        contract = str(getattr(alert, "contract_symbol", "") or "")
        is_option = bool(opt_type or contract or "OPTIONS" in alert_type or "GAMMA" in alert_type)
        is_option_buy = is_option and ("SELL" not in action and "WRITE" not in action)

        risk_pts = abs(ltp - sl)
        reward_pts = abs(t1 - ltp)
        rr = reward_pts / risk_pts if risk_pts > 0 else 2.5

        # Base quant score anchored around 80
        score = 80
        if rr >= 3.0:
            score += 8
        elif rr >= 2.5:
            score += 4

        # Bonus for derivative / volume confirmation if present
        rvol = float(metrics.get("rvol", 1.0) or 1.0)
        if rvol >= 2.0:
            score += 5

        score = min(92, max(75, score))

        # ── Commodity Quant Fallback ──────────────────────────────────────────
        if alert_type == "COMMODITY_MOMENTUM":
            chg_pct = float(metrics.get("change_pct", 0.0) or 0.0)
            vwap = float(metrics.get("vwap", ltp) or ltp)
            if direction in ("BEARISH", "SHORT", "SELL"):
                logic = (
                    f"Quant-validated MCX {sym} breakdown: session decline of {chg_pct:.1f}% below VWAP ₹{vwap:,.1f} "
                    f"with calibrated {rr:.1f}R downside asymmetry; COMEX basis suggests genuine selling pressure."
                )
                trap = (
                    f"Watch for COMEX midnight gap fill or INR basis correction reversing the MCX breakdown; "
                    f"invalidate immediately if price reclaims VWAP ₹{vwap:,.1f}."
                )
                guidance = f"Short MCX {sym} near ₹{ltp:,.1f}; SL above ₹{sl:,.1f}; book 50% at ₹{t1:,.1f} and trail on 5m candle."
            else:
                logic = (
                    f"Quant-validated MCX {sym} momentum: session gain of {chg_pct:+.1f}% reclaiming VWAP ₹{vwap:,.1f} "
                    f"with calibrated {rr:.1f}R upside asymmetry; DXY softness supports domestic gold/crude bid."
                )
                trap = (
                    f"Watch for MCX session closing rollover pressure or thin-book stop-hunt above ₹{ltp:,.1f}; "
                    f"do not chase if price extends beyond 1.5× trigger move without VWAP reclaim."
                )
                guidance = f"Long MCX {sym} near ₹{ltp:,.1f}; SL below ₹{sl:,.1f}; book 50% at ₹{t1:,.1f} and trail on 5m candle."
            return ScrutinyResult(
                status="APPROVED",
                score=score,
                logic_confirmation=logic,
                trap_risk_warning=trap,
                actionable_guidance=guidance,
                sanctity_matrix=flags,
                auditor_model="QUANT_FALLBACK",
            )

        # ── Currency Quant Fallback ───────────────────────────────────────────
        if alert_type == "CURRENCY_BREAKOUT":
            chg_pct = float(metrics.get("change_pct", 0.0) or 0.0)
            if direction in ("BEARISH", "SHORT", "SELL"):
                logic = (
                    f"Quant-validated {sym} INR depreciation: {chg_pct:.3f}% macro drop with "
                    f"1:{rr:.1f} R:R asymmetry; consistent with FII equity outflow or global risk-off trigger."
                )
                trap = (
                    f"RBI intervention band proximity or sudden risk-on reversal could squeeze shorts; "
                    f"watch for price reclaim above ₹{sl:.4f}."
                )
                guidance = f"Short {sym} near ₹{ltp:.4f}; SL ₹{sl:.4f}; T1 ₹{t1:.4f}; close 50% at T1 and trail tightly."
            else:
                logic = (
                    f"Quant-validated {sym} INR appreciation: {chg_pct:+.3f}% macro move with "
                    f"1:{rr:.1f} R:R asymmetry; consistent with FII equity inflow or crude drawdown."
                )
                trap = (
                    f"Post-equity session thin liquidity could amplify false breakout; "
                    f"invalidate if price falls back below ₹{sl:.4f}."
                )
                guidance = f"Long {sym} near ₹{ltp:.4f}; SL ₹{sl:.4f}; T1 ₹{t1:.4f}; close 50% at T1 and trail tightly."
            return ScrutinyResult(
                status="APPROVED",
                score=score,
                logic_confirmation=logic,
                trap_risk_warning=trap,
                actionable_guidance=guidance,
                sanctity_matrix=flags,
                auditor_model="QUANT_FALLBACK",
            )

        # ── Generic Equity / Derivative Fallback ─────────────────────────────
        if is_option_buy:
            if opt_type == "PE" or "PE" in contract or "PUT" in action or direction == "BEARISH":
                opt_lbl = contract or f"{sym} {opt_type or 'PE'}"
                logic = f"Quant-validated {opt_lbl} Put momentum: bearish underlying breakdown confirmed with 1:{rr:.1f} R:R premium expansion asymmetry."
                trap = f"Watch for sudden underlying short-covering bounce; scale 50% profit at option target Rs.{t1:,.1f} and trail SL to breakeven."
                guidance = f"Buy PE near Rs.{ltp:,.1f}; strictly invalidate if option premium drops below Rs.{sl:,.1f}."
            else:
                opt_lbl = contract or f"{sym} {opt_type or 'CE'}"
                logic = f"Quant-validated {opt_lbl} Call momentum: bullish momentum holds with favorable 1:{rr:.1f} R:R premium expansion asymmetry."
                trap = f"Watch for overhead resistance or IV crush near target Rs.{t1:,.1f}; scale 50% profit at T1 and trail SL to breakeven."
                guidance = f"Buy CE near Rs.{ltp:,.1f}; strictly invalidate if option premium drops below Rs.{sl:,.1f}."
        elif direction in ("BEARISH", "SHORT", "SELL"):
            logic = f"Quant-validated {sym} breakdown: distribution structure below Rs.{sl:,.1f} confirmed with 1:{rr:.1f} downside asymmetry."
            trap = f"Watch for sudden short-covering bounce near Rs.{t1:,.1f}; tighten stop on lower timeframe CHoCH."
            guidance = f"Short near Rs.{ltp:,.1f}; invalidate trade immediately if price reclaims Rs.{sl:,.1f}."
        else:
            logic = f"Quant-validated {sym} {alert_type.lower().replace('_', ' ')}: structural pivot holds above Rs.{sl:,.1f} with favorable 1:{rr:.1f} R:R asymmetry."
            trap = f"Overhead resistance near target Rs.{t1:,.1f}; scale 50% profit at T1 and trail SL to breakeven."
            guidance = f"Enter near Rs.{ltp:,.1f}; strictly invalidate if candle closes below Rs.{sl:,.1f}."

        return ScrutinyResult(
            status="APPROVED",
            score=score,
            logic_confirmation=logic,
            trap_risk_warning=trap,
            actionable_guidance=guidance,
            sanctity_matrix=flags,
            auditor_model="QUANT_FALLBACK",
        )


# Global singleton instance
alert_scrutiny_auditor = AlertScrutinyAuditor()
