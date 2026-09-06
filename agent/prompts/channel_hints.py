"""
agent/prompts/channel_hints.py
──────────────────────────────
Channel-aware formatting hints (CLI, Electron, API, WhatsApp).
"""

from __future__ import annotations

CHANNEL_FORMATS: dict[str, dict] = {
    "cli": {
        "max_width": 80,
        "use_emoji": True,
        "use_tables": True,
        "verbosity": "full",
    },
    "electron": {
        "max_width": 120,
        "use_emoji": True,
        "use_tables": True,
        "verbosity": "full",
        "hint": "Output will be rendered as markdown in a chat UI.",
    },
    "api": {
        "max_width": 0,  # no limit
        "use_emoji": False,
        "use_tables": False,
        "verbosity": "concise",
        "hint": "Return structured data, minimal prose.",
    },
    "whatsapp": {
        "max_width": 60,
        "use_emoji": True,
        "use_tables": False,
        "verbosity": "brief",
        "hint": "Plain text only. No markdown. Keep under 200 words.",
    },
}

# Default channel when none is specified
_DEFAULT_CHANNEL = "cli"


def get_channel_hint(channel: str = "cli") -> str:
    """
    Return a prompt suffix that tailors the LLM output for the given channel.

    Args:
        channel: One of 'cli', 'electron', 'api', 'whatsapp'.
                 Unknown channels default to 'cli' format.

    Returns:
        A non-empty string to append to any synthesis prompt.
    """
    fmt = CHANNEL_FORMATS.get(channel.lower(), CHANNEL_FORMATS[_DEFAULT_CHANNEL])

    parts = ["OUTPUT FORMAT:"]

    # Custom hint for channels that have one
    if fmt.get("hint"):
        parts.append(fmt["hint"])

    # Width constraint
    if fmt.get("max_width", 0) > 0:
        parts.append(f"Limit line width to {fmt['max_width']} characters.")

    # Verbosity guidance
    verbosity = fmt.get("verbosity", "full")
    if verbosity == "brief":
        parts.append("Be very brief — 3-5 bullet points maximum.")
    elif verbosity == "concise":
        parts.append("Be concise — avoid long prose, prefer structured output.")
    elif verbosity == "full":
        parts.append("Full detail is appropriate for this channel.")

    # Tables / markdown
    if not fmt.get("use_tables", True):
        parts.append("Do NOT use markdown tables or formatting.")
    else:
        parts.append("Markdown tables and formatting are supported.")

    # Emoji
    if not fmt.get("use_emoji", True):
        parts.append("Do not use emoji.")

    return " ".join(parts)
