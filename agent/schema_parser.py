"""
agent/schema_parser.py
──────────────────────
Parses synthesis LLM free text → SynthesisOutput (Pydantic model).

Two-path strategy:
  1. JSON path  — if text contains '{', attempt json.loads() + model_validate()
  2. Text path  — line-by-line parsing of the canonical synthesis format
  3. Fallback   — on any failure, return SynthesisOutput() with safe defaults

Never raises — always returns a valid SynthesisOutput.
"""

from __future__ import annotations
import logging

logger = logging.getLogger("agent.schema_parser")


import json
import re

from pydantic import ValidationError

from agent.schemas import SynthesisOutput

# Valid verdict tokens — longest first to avoid STRONG_BUY matching BUY
_VERDICT_TOKENS = ("STRONG_BUY", "STRONG_SELL", "BUY", "SELL", "HOLD")
_VALID_VERDICTS = set(_VERDICT_TOKENS)

# Keys in the TRADE RECOMMENDATION block
_REC_KEY_MAP = {
    "strategy": "strategy",
    "entry": "entry",
    "entry level": "entry",
    "stop-loss": "stop_loss",
    "stop_loss": "stop_loss",
    "stop loss": "stop_loss",
    "target": "target",
    "target 1": "target",
    "target 2": "target_2",
    "r:r ratio": "risk_reward",
    "r:r": "risk_reward",
    "risk_reward": "risk_reward",
    "position": "position",
}


def _extract_json_block(text: str) -> str | None:
    """
    Extract the first JSON object from text.
    Returns the raw JSON string or None if not found.
    Handles JSON embedded in prose, and returns candidate substring even if truncated.
    """
    start = text.find("{")
    if start == -1:
        return None
    # Walk forward to find the matching closing brace
    depth = 0
    for i, ch in enumerate(text[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    # If text ended before depth reached 0 (e.g. truncated JSON), return candidate from start
    return text[start:]


def _defensive_repair_json(json_str: str) -> dict | None:
    """
    Defensively parses JSON with repair for cut-off strings, unclosed brackets/braces,
    markdown wrapping, or falling back to regex field extraction.
    """
    # 1. Strip markdown fences if present
    cleaned = re.sub(r"^```(?:json)?\s*", "", json_str.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    # 2. Direct attempt
    try:
        return json.loads(cleaned)
    except Exception as e_suppressed:
        logger.debug(f"[agent.schema_parser] Non-fatal exception suppressed: {e_suppressed}")

    # 3. Defensive structural repair for truncated JSON
    work = cleaned
    # Trim trailing incomplete punctuation
    work = re.sub(r",\s*$", "", work)
    work = re.sub(r":\s*$", "", work)

    # Balance unclosed string quotes
    in_str = False
    esc = False
    for ch in work:
        if ch == "\\" and not esc:
            esc = True
            continue
        if ch == '"' and not esc:
            in_str = not in_str
        esc = False

    if in_str:
        work += '"'

    # Remove trailing incomplete key like , "key" or "key":
    work = re.sub(r',\s*"[^"]*"\s*:\s*$', "", work)
    work = re.sub(r',\s*"[^"]*"\s*$', "", work)

    # Balance brackets and braces
    open_brackets = work.count("[") - work.count("]")
    if open_brackets > 0:
        work += "]" * open_brackets

    open_braces = work.count("{") - work.count("}")
    if open_braces > 0:
        work += "}" * open_braces

    try:
        return json.loads(work)
    except Exception as e_suppressed:
        logger.debug(f"[agent.schema_parser] Non-fatal exception suppressed: {e_suppressed}")

    # 4. Regex extraction fallback
    fields: dict = {}
    m = re.search(r'"verdict"\s*:\s*"([^"]+)"', cleaned, re.IGNORECASE)
    if m:
        fields["verdict"] = _parse_verdict(m.group(1))

    m = re.search(r'"confidence"\s*:\s*(\d+)', cleaned, re.IGNORECASE)
    if m:
        try:
            fields["confidence"] = _clamp_confidence(int(m.group(1)))
        except ValueError as e_suppressed:
            logger.debug(f"[agent.schema_parser] Non-fatal exception suppressed: {e_suppressed}")

    m = re.search(r'"winner"\s*:\s*"([^"]+)"', cleaned, re.IGNORECASE)
    if m:
        fields["winner"] = _parse_winner(m.group(1))

    for k in ("strategy", "entry", "stop_loss", "target", "risk_reward", "position"):
        m = re.search(rf'"{k}"\s*:\s*"([^"]*)"', cleaned, re.IGNORECASE)
        if m:
            fields[k] = m.group(1)

    if fields:
        return fields

    return None


def _clamp_confidence(value: int) -> int:
    """Clamp confidence to valid range 0-100."""
    return max(0, min(100, value))


def _parse_winner(value: str) -> str:
    """Map a winner string to BULL / BEAR / NEUTRAL."""
    upper = value.upper()
    if "BULL" in upper:
        return "BULL"
    if "BEAR" in upper:
        return "BEAR"
    return "NEUTRAL"


def _parse_verdict(value: str) -> str:
    """Map a verdict string to a valid verdict token, defaulting to HOLD."""
    upper = value.upper().strip()
    for v in _VERDICT_TOKENS:
        if v in upper:
            return v
    return "HOLD"


def _parse_text_path(text: str) -> SynthesisOutput:
    """
    Line-by-line parser for the canonical synthesis text format.
    Returns SynthesisOutput with fields filled from the text (defaults for missing).
    """
    verdict = "HOLD"
    confidence = 50
    winner = "NEUTRAL"
    strategy = ""
    entry = ""
    stop_loss = ""
    target = ""
    risk_reward = ""
    position = ""
    rationale: list[str] = []
    risks: list[str] = []

    # State for section tracking
    in_trade_rec = False
    in_rationale = False
    in_risks = False

    for line in text.splitlines():
        stripped = line.strip().strip("*").strip()  # remove markdown bold markers
        upper = stripped.upper()

        # ── Top-level fields ──────────────────────────────────────────────────
        # Match "VERDICT: ..." anywhere on the line (handles "Final VERDICT: BUY")
        if "VERDICT:" in upper:
            val = re.split(r"(?i)verdict:", stripped, maxsplit=1)[1].strip()
            verdict = _parse_verdict(val)
            in_trade_rec = in_rationale = in_risks = False
            continue

        if upper.startswith("CONFIDENCE:"):
            raw = stripped.split(":", 1)[1].strip().rstrip("%").strip()
            try:
                confidence = _clamp_confidence(int(raw))
            except (ValueError, IndexError) as e_suppressed:
                logger.debug(
                    f"[agent.schema_parser] Non-fatal exception suppressed: {e_suppressed}"
                )
            continue

        if upper.startswith("WINNER:"):
            val = stripped.split(":", 1)[1].strip()
            winner = _parse_winner(val)
            continue

        # ── TRADE RECOMMENDATION block ────────────────────────────────────────
        if "TRADE RECOMMENDATION" in upper:
            in_trade_rec = True
            in_rationale = in_risks = False
            continue

        if in_trade_rec:
            # Each sub-line is "Key  : value" — the canonical format uses " : " as separator
            # (with spaces), which lets keys like "R:R Ratio" contain colons without conflict.
            if " : " in stripped:
                key_raw, _, val = stripped.partition(" : ")
                key = key_raw.strip().lower()
                val = val.strip()
                field_name = _REC_KEY_MAP.get(key)
            elif ":" in stripped and not stripped.startswith("-"):
                # Fallback: plain "key: value" without space padding
                key_raw, _, val = stripped.partition(":")
                key = key_raw.strip().lower()
                val = val.strip()
                field_name = _REC_KEY_MAP.get(key)
            else:
                field_name = None
            if field_name is not None:
                if field_name == "strategy":
                    strategy = val
                elif field_name == "entry":
                    entry = val
                elif field_name == "stop_loss":
                    stop_loss = val
                elif field_name == "target":
                    target = val
                elif field_name == "risk_reward":
                    risk_reward = val
                elif field_name == "position":
                    position = val
            # Blank line ends the trade rec block
            if not stripped:
                in_trade_rec = False
            continue

        # ── RATIONALE section ─────────────────────────────────────────────────
        if re.search(r"\bRATIONALE\b", upper) or re.search(r"\bWHY\b", upper):
            in_rationale = True
            in_risks = in_trade_rec = False
            continue

        if in_rationale:
            if stripped.startswith("- ") and len(rationale) < 5:
                rationale.append(stripped[2:].strip())
            elif stripped and not stripped.startswith("-"):
                # Non-bullet, non-empty line ends the section
                in_rationale = False
            continue

        # ── RISKS section ─────────────────────────────────────────────────────
        if re.search(r"\bRISK", upper):
            in_risks = True
            in_rationale = in_trade_rec = False
            continue

        if in_risks:
            if stripped.startswith("- ") and len(risks) < 5:
                risks.append(stripped[2:].strip())
            elif stripped and not stripped.startswith("-"):
                in_risks = False
            continue

        # ── Standalone Strategy: line (outside TRADE RECOMMENDATION block) ────
        if upper.startswith("STRATEGY:") and not strategy:
            strategy = stripped.split(":", 1)[1].strip()

    # ── Keyword fallback: if still HOLD, scan full text for a verdict token ───
    if verdict == "HOLD":
        upper_text = text.upper()
        for token in _VERDICT_TOKENS:
            if token in upper_text:
                verdict = token
                break

    return SynthesisOutput(
        verdict=verdict,
        confidence=confidence,
        winner=winner,
        strategy=strategy,
        entry=entry,
        stop_loss=stop_loss,
        target=target,
        risk_reward=risk_reward,
        position=position,
        rationale=rationale,
        risks=risks,
    )


def parse_synthesis_output(text: str) -> SynthesisOutput:
    """
    Parse synthesis LLM text → SynthesisOutput.

    Strategy:
      1. JSON path  — if text contains '{', extract JSON block and model_validate()
      2. Text path  — line-by-line parsing of canonical synthesis format
      3. Fallback   — on any error, return SynthesisOutput() with safe defaults

    Never raises. Always returns a valid SynthesisOutput.
    """
    if not text:
        return SynthesisOutput()

    # ── Path 1: JSON ──────────────────────────────────────────────────────────
    if "{" in text:
        json_str = _extract_json_block(text)
        if json_str:
            data = _defensive_repair_json(json_str)
            if data and isinstance(data, dict):
                try:
                    # Sanitize fields to match SynthesisOutput schema constraints
                    if "confidence" in data and isinstance(data["confidence"], (int, float)):
                        data["confidence"] = _clamp_confidence(int(data["confidence"]))
                    if "verdict" in data and isinstance(data["verdict"], str):
                        data["verdict"] = _parse_verdict(data["verdict"])
                    if "winner" in data and isinstance(data["winner"], str):
                        data["winner"] = _parse_winner(data["winner"])
                    return SynthesisOutput.model_validate(data)
                except (ValidationError, Exception) as e_suppressed:
                    # JSON validation failed — fall through to text path
                    logger.debug(
                        f"[agent.schema_parser] Non-fatal exception suppressed: {e_suppressed}"
                    )

    # ── Path 2: Text ──────────────────────────────────────────────────────────
    try:
        return _parse_text_path(text)
    except Exception as e_suppressed:
        logger.debug(f"[agent.schema_parser] Non-fatal exception suppressed: {e_suppressed}")

    # ── Path 3: Fallback ──────────────────────────────────────────────────────
    return SynthesisOutput()
