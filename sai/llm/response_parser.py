"""LLM response post-processing.

Strips model-specific internal tags before returning text to callers:
  - <think>...</think>        (some reasoning models)
  - <reasoning>...</reasoning>
  - <reflection>...</reflection>
  - Nonce-tagged wrappers (in case the model echoes them)

Also provides a strict integer parser for command selection responses.
"""

import re
from typing import Optional

# Patterns for internal model tags (non-greedy, DOTALL for multiline content)
#
# Covered families:
#   DeepSeek / Qwen style : <think>...</think>  or <thinking>...</thinking>
#   Mistral style         : [THINK]...[/THINK]  (square-bracket variant)
#   Anthropic style       : <reasoning>...</reasoning>
#   Generic               : <reflection>, <scratchpad>
_INTERNAL_TAG_PATTERNS: list[re.Pattern] = [
    # Angle-bracket variants
    re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE),
    re.compile(r"<thinking>.*?</thinking>", re.DOTALL | re.IGNORECASE),
    re.compile(r"<reasoning>.*?</reasoning>", re.DOTALL | re.IGNORECASE),
    re.compile(r"<reflection>.*?</reflection>", re.DOTALL | re.IGNORECASE),
    re.compile(r"<scratchpad>.*?</scratchpad>", re.DOTALL | re.IGNORECASE),
    # Mistral square-bracket variants  [THINK]...[/THINK]
    re.compile(r"\[THINK\].*?\[/THINK\]", re.DOTALL | re.IGNORECASE),
    re.compile(r"\[THINKING\].*?\[/THINKING\]", re.DOTALL | re.IGNORECASE),
    re.compile(r"\[REASONING\].*?\[/REASONING\]", re.DOTALL | re.IGNORECASE),
]


def strip_internal_tags(text: str) -> str:
    """Remove model-internal reasoning tags from LLM output."""
    for pat in _INTERNAL_TAG_PATTERNS:
        text = pat.sub("", text)
    return text.strip()


def clean_response(text: str, nonce: Optional[str] = None) -> str:
    """
    Full response cleanup pipeline:
      1. Strip internal reasoning tags
      2. Strip nonce tags if a nonce is provided
    """
    text = strip_internal_tags(text)
    if nonce:
        from .nonce import strip_nonce_tags
        text = strip_nonce_tags(text, nonce)
    return text


def parse_command_index(text: str, max_index: int) -> Optional[int]:
    """
    Parse a strict integer from a command selection response.

    Accepts: "3", "  3  ", "3\n"
    Rejects: "none", "3 because...", anything non-numeric

    Returns None if the response is "none" or unparseable.
    Returns None if the index is out of range [1, max_index].
    """
    stripped = text.strip().lower()
    if stripped in ("none", "0", "n/a", "-"):
        return None
    try:
        idx = int(stripped)
    except ValueError:
        return None
    if 1 <= idx <= max_index:
        return idx
    return None
