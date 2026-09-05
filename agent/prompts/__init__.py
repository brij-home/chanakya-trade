"""
agent/prompts
─────────────
Structured prompt templates for trading agents, councils, personas, and output channels.
"""

from __future__ import annotations

from agent.prompts.base_prompt import _IST, _market_status, build_system_prompt
from agent.prompts.channel_hints import (
    _DEFAULT_CHANNEL,
    CHANNEL_FORMATS,
    get_channel_hint,
)
from agent.prompts.command_prompts import (
    ANALYZE_STOCK_PROMPT,
    MORNING_BRIEF_PROMPT,
    STRATEGY_BUILDER_PROMPT,
    STRATEGY_BUILDER_SIMPLE_PROMPT,
    STRATEGY_PROMPT,
)
from agent.prompts.council_templates import (
    AGGRESSIVE_DEBATER_PROMPT,
    BEAR_REBUTTAL_PROMPT,
    BEAR_RESEARCHER_OPENING_PROMPT,
    BEAR_RESEARCHER_PROMPT,
    BULL_REBUTTAL_PROMPT,
    BULL_RESEARCHER_PROMPT,
    CONSERVATIVE_DEBATER_PROMPT,
    FACILITATOR_PROMPT,
    NEUTRAL_DEBATER_PROMPT,
    NEWS_SENTIMENT_PROMPT,
    SYNTHESIS_PROMPT,
)
from agent.prompts.persona_templates import (
    PERSONA_BASE_GUIDANCE,
    PERSONA_RESPONSE_FORMAT,
)

__all__ = [
    "_IST",
    "_market_status",
    "build_system_prompt",
    "MORNING_BRIEF_PROMPT",
    "ANALYZE_STOCK_PROMPT",
    "STRATEGY_PROMPT",
    "STRATEGY_BUILDER_PROMPT",
    "STRATEGY_BUILDER_SIMPLE_PROMPT",
    "CHANNEL_FORMATS",
    "get_channel_hint",
    "_DEFAULT_CHANNEL",
    "BULL_RESEARCHER_PROMPT",
    "BEAR_RESEARCHER_OPENING_PROMPT",
    "BEAR_RESEARCHER_PROMPT",
    "BULL_REBUTTAL_PROMPT",
    "BEAR_REBUTTAL_PROMPT",
    "FACILITATOR_PROMPT",
    "SYNTHESIS_PROMPT",
    "AGGRESSIVE_DEBATER_PROMPT",
    "CONSERVATIVE_DEBATER_PROMPT",
    "NEUTRAL_DEBATER_PROMPT",
    "NEWS_SENTIMENT_PROMPT",
    "PERSONA_BASE_GUIDANCE",
    "PERSONA_RESPONSE_FORMAT",
]
