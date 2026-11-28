"""
agent/async_catalyst_and_postmortem.py
──────────────────────────────────────
Re-targeted Asynchronous LLM & Structured Intelligence Tasks (Non-Critical Path).

Architectural Invariant (Pillar 5):
  - Zero LLMs in the critical path of intraday index/option triggers.
  - Deploy structured NLP / async LLM strictly to:
      1. Unstructured Catalyst Filing Tagging (NSE filings, RBI/SEBI circulars) with
         explicit `untrusted_source=True` and `execution_permission=False`.
      2. End-of-Day (EOD) 5W Post-Mortem Audit across WHY, WHEN, WHERE, WHO dimensions
         and `StageTelemetryStore` forward-path attribution.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional, Sequence

from config.constants import IST

logger = logging.getLogger("agent.async_catalyst_and_postmortem")

ALLOWED_CATALYST_TAGS: tuple[str, ...] = (
    "ORDER_WIN",
    "EARNINGS_BEAT",
    "EARNINGS_MISS",
    "BUYBACK",
    "GUIDANCE_CUT",
    "REGULATORY_NOTICE",
    "MANAGEMENT_CHANGE",
    "MERGER_DEMERGER",
    "NEUTRAL_ROUTINE",
)


@dataclass(frozen=True)
class CatalystTag:
    symbol: str
    tag: str
    direction_bias: str  # "BULLISH" | "BEARISH" | "NEUTRAL" | "VOLATILITY"
    confidence: float
    first_seen_at: str
    headline: str
    rationale: str
    provenance: str  # "DETERMINISTIC_PARSER" | "ASYNC_LLM_VALIDATED"
    untrusted_source: bool = True
    execution_permission: bool = False  # Strictly isolated from OMS / order execution

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _deterministic_classify_catalyst(text: str) -> tuple[str, str, float, str]:
    """Deterministic zero-latency corporate filing classifier."""
    low = (text or "").lower()
    if any(
        k in low for k in ("order win", "letter of award", "loa ", "bagged order", "contract worth")
    ):
        return "ORDER_WIN", "BULLISH", 0.78, "Detected order win / LOA keyword pattern"
    if any(k in low for k in ("buyback", "buy-back", "share repurchase")):
        return "BUYBACK", "BULLISH", 0.76, "Detected buyback announcement"
    if any(
        k in low
        for k in ("guidance cut", "lowered outlook", "revenue warning", "margin contraction")
    ):
        return "GUIDANCE_CUT", "BEARISH", 0.75, "Detected guidance cut / margin warning"
    if any(
        k in low for k in ("sebi", "rbi ", "show cause", "penalty", "inspection", "ban", "circular")
    ):
        return "REGULATORY_NOTICE", "VOLATILITY", 0.72, "Detected regulatory / SEBI / RBI notice"
    if any(
        k in low for k in ("profit jumps", "beat estimates", "pat up", "record profit", "strong q")
    ):
        return "EARNINGS_BEAT", "BULLISH", 0.74, "Detected earnings beat / PAT surge"
    if any(k in low for k in ("net loss", "profit drops", "pat down", "missed estimates")):
        return "EARNINGS_MISS", "BEARISH", 0.74, "Detected earnings miss / profit drop"
    if any(k in low for k in ("resignation", "cfo resign", "ceo resign", "appointed md")):
        return "MANAGEMENT_CHANGE", "VOLATILITY", 0.65, "Detected key management transition"
    if any(k in low for k in ("demerger", "merger", "amalgamation", "scheme of arrangement")):
        return "MERGER_DEMERGER", "VOLATILITY", 0.68, "Detected M&A / demerger scheme"
    return "NEUTRAL_ROUTINE", "NEUTRAL", 0.50, "Routine exchange filing"


def parse_corporate_catalyst_filing(
    symbol: str,
    text: str,
    *,
    first_seen_at: Optional[str] = None,
    llm_classifier: Optional[Callable[[str, str], Optional[dict[str, Any]]]] = None,
) -> CatalystTag:
    """Schema-validated catalyst tagger isolating untrusted external filings from order execution."""
    clean_sym = re.sub(
        r"[^A-Z0-9&-]", "", str(symbol or "").upper().replace("NSE:", "").replace("BSE:", "")
    )
    seen_ts = first_seen_at or datetime.now(IST).isoformat()
    safe_headline = re.sub(r"\s+", " ", str(text or ""))[:180].strip()

    tag, bias, conf, why = _deterministic_classify_catalyst(text)
    provenance = "DETERMINISTIC_PARSER"

    if llm_classifier is not None:
        try:
            raw_res = llm_classifier(clean_sym, safe_headline)
            if isinstance(raw_res, dict):
                cand_tag = str(raw_res.get("tag", "") or "").upper().strip()
                cand_bias = str(raw_res.get("direction_bias", "") or "").upper().strip()
                cand_conf = float(raw_res.get("confidence", conf) or conf)
                if cand_tag in ALLOWED_CATALYST_TAGS and cand_bias in (
                    "BULLISH",
                    "BEARISH",
                    "NEUTRAL",
                    "VOLATILITY",
                ):
                    tag = cand_tag
                    bias = cand_bias
                    conf = max(0.1, min(0.99, cand_conf))
                    why = str(raw_res.get("rationale", why) or why)[:160]
                    provenance = "ASYNC_LLM_VALIDATED"
        except Exception as exc_llm:
            logger.debug(
                f"[AsyncCatalyst] Optional LLM classifier fallback for {clean_sym}: {exc_llm}"
            )

    return CatalystTag(
        symbol=clean_sym,
        tag=tag,
        direction_bias=bias,
        confidence=round(float(conf), 2),
        first_seen_at=seen_ts,
        headline=safe_headline,
        rationale=why,
        provenance=provenance,
        untrusted_source=True,
        execution_permission=False,
    )


@dataclass
class EOD5WPostMortemReport:
    session_date: str
    total_setups: int
    wins: int
    losses: int
    unfulfilled: int
    net_r: float
    win_rate_pct: Optional[float]
    why_top_driver: str
    when_best_window: str
    where_best_anchor: str
    who_trapped_side: str
    degradation_watch: list[str] = field(default_factory=list)
    telemetry_summary: dict[str, Any] = field(default_factory=dict)
    narrative_summary: str = ""
    provenance: str = "EOD_5W_POSTMORTEM"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def synthesize_eod_5w_postmortem(
    alerts: Sequence[Any],
    *,
    session_date: Optional[str] = None,
    telemetry_summary: Optional[dict[str, Any]] = None,
    llm_synthesizer: Optional[Callable[[dict[str, Any]], Optional[str]]] = None,
) -> EOD5WPostMortemReport:
    """Synthesize EOD 5W Post-Mortem attribution across WHY/WHEN/WHERE/WHO & stage telemetry."""
    from engine.alert_postmortem_runner import extract_5w_dimensions, generate_session_scorecard

    s_date = session_date or datetime.now(IST).strftime("%Y-%m-%d")
    scorecard = generate_session_scorecard(list(alerts), session_date=s_date)

    why_counts: dict[str, list[float]] = {}
    when_counts: dict[str, list[float]] = {}
    where_counts: dict[str, list[float]] = {}
    who_counts: dict[str, list[float]] = {}

    for a in alerts:
        why, when, where, who = extract_5w_dimensions(a)
        r_val = float(getattr(a, "realized_r", 0.0) or getattr(a, "net_r", 0.0) or 0.0)
        why_counts.setdefault(why, []).append(r_val)
        when_counts.setdefault(when, []).append(r_val)
        where_counts.setdefault(where, []).append(r_val)
        who_counts.setdefault(who, []).append(r_val)

    def _top_key(buckets: dict[str, list[float]], fallback: str) -> str:
        if not buckets:
            return fallback
        return max(buckets.items(), key=lambda kv: (sum(kv[1]), len(kv[1])))[0]

    why_top = _top_key(why_counts, "NO_SETUPS")
    when_best = _top_key(when_counts, "NONE")
    where_best = _top_key(where_counts, "NONE")
    who_trap = _top_key(who_counts, "NONE")

    degrade_watch = [
        k for k, vals in why_counts.items() if len(vals) >= 3 and (sum(vals) / len(vals)) < -0.25
    ]

    wins = int(scorecard.get("wins", 0) or 0)
    losses = int(scorecard.get("losses", 0) or 0)
    total = int(scorecard.get("total_setups", len(alerts)) or 0)
    net_r = float(scorecard.get("net_realized_r", 0.0) or 0.0)
    wr = float(scorecard["win_rate_pct"]) if scorecard.get("win_rate_pct") is not None else None

    if telemetry_summary is None:
        try:
            from engine.meta_labeler import stage_telemetry_store

            telemetry_summary = stage_telemetry_store.summary()
        except Exception:
            telemetry_summary = {}

    narrative = (
        f"Session {s_date}: {total} setups ({wins}W/{losses}L, net {net_r:+.2f}R). "
        f"Lead WHY={why_top}, WHEN={when_best}, WHERE={where_best}, WHO={who_trap}."
    )
    if llm_synthesizer is not None:
        try:
            ext_text = llm_synthesizer(
                {"scorecard": scorecard, "why_top": why_top, "when_best": when_best}
            )
            if isinstance(ext_text, str) and ext_text.strip():
                narrative = ext_text.strip()[:400]
        except Exception as exc_llm:
            logger.debug(f"[AsyncPostMortem] LLM narrative fallback: {exc_llm}")

    return EOD5WPostMortemReport(
        session_date=s_date,
        total_setups=total,
        wins=wins,
        losses=losses,
        unfulfilled=int(scorecard.get("unfulfilled", 0) or 0),
        net_r=round(net_r, 2),
        win_rate_pct=round(wr, 1) if wr is not None else None,
        why_top_driver=why_top,
        when_best_window=when_best,
        where_best_anchor=where_best,
        who_trapped_side=who_trap,
        degradation_watch=sorted(degrade_watch),
        telemetry_summary=dict(telemetry_summary),
        narrative_summary=narrative,
    )
