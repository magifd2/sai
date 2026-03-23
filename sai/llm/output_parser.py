"""Robust LLM output parsing for unstable / non-JSON-mode local models.

Local LLMs frequently wrap structured output in markdown code blocks,
prefix it with explanation text, include trailing commas, or return
partial responses. This module provides defensive extraction and
retry-with-correction helpers.

Key utilities:
  extract_json(text)      — strip code fences / prose, parse JSON
  extract_int(text)       — pull the first integer from noisy text
  is_empty(text)          — detect blank / whitespace-only responses
  retry_structured(...)   — call LLM, parse, retry with correction prompt
"""

import json
import re
from typing import Any, Awaitable, Callable, Optional, TypeVar

from ..utils.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

# ── Patterns ────────────────────────────────────────────────────────────────

# ```json ... ``` or ``` ... ```
_CODE_FENCE_RE = re.compile(
    r"```(?:json|JSON)?\s*\n?(.*?)```",
    re.DOTALL,
)

# Inline code: `{...}`
_INLINE_CODE_RE = re.compile(r"`([^`]+)`", re.DOTALL)

# Trailing commas before } or ]  (common LLM mistake)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")

# First integer (possibly surrounded by prose)
_FIRST_INT_RE = re.compile(r"\b(\d+)\b")

# "none" variants
_NONE_RE = re.compile(r"\b(none|n/?a|no match|nothing|null)\b", re.I)


# ── Core extraction helpers ──────────────────────────────────────────────────

def extract_json(text: str) -> Optional[Any]:
    """
    Attempt to extract and parse a JSON value from LLM output.

    Tries in order:
      1. Direct parse (model returned clean JSON)
      2. Extract from ```json ... ``` code fence
      3. Find first {...} or [...] substring and parse it
      4. Fix trailing commas and retry the above
      5. json-repair: auto-correct malformed JSON (missing quotes, extra commas, etc.)

    Returns the parsed Python object or None if all attempts fail.
    """
    for attempt_fn in (
        _try_direct,
        _try_code_fence,
        _try_first_brace_block,
    ):
        result = attempt_fn(text)
        if result is not None:
            return result

    # Fix trailing commas and retry
    fixed = _fix_trailing_commas(text)
    if fixed != text:
        for attempt_fn in (_try_direct, _try_code_fence, _try_first_brace_block):
            result = attempt_fn(fixed)
            if result is not None:
                logger.debug("output_parser.json_recovered_after_comma_fix")
                return result

    # Last resort: json-repair (handles missing quotes, unclosed brackets, etc.)
    result = _try_json_repair(text)
    if result is not None:
        logger.debug("output_parser.json_recovered_via_repair", snippet=text[:80])
        return result

    logger.warning("output_parser.json_extract_failed", snippet=text[:120])
    return None


def extract_int(text: str, max_value: int) -> Optional[int]:
    """
    Extract a valid integer from potentially noisy LLM output.

    Handles:
      - Clean "3"
      - Prefixed "Answer: 3"
      - Verbose "I would select option 3 because..."
      - "none" / "N/A" variants → returns None

    Returns None if text signals no match or no valid integer found.
    """
    stripped = text.strip()

    if _NONE_RE.search(stripped):
        return None

    # Fast path: pure integer
    try:
        val = int(stripped)
        if 1 <= val <= max_value:
            return val
        return None
    except ValueError:
        pass

    # Find the first integer token in the text
    m = _FIRST_INT_RE.search(stripped)
    if m:
        val = int(m.group(1))
        if 1 <= val <= max_value:
            logger.debug(
                "output_parser.int_extracted_from_prose",
                raw_snippet=stripped[:60],
                extracted=val,
            )
            return val

    return None


def is_empty(text: str) -> bool:
    """Return True if the LLM response is blank or whitespace-only."""
    return not text or not text.strip()


# ── Retry-with-correction ────────────────────────────────────────────────────

async def retry_structured(
    call_fn: Callable[[], "Awaitable[str]"],
    parse_fn: Callable[[str], Optional[T]],
    correction_call_fn: Callable[[str], "Awaitable[str]"],
    max_attempts: int = 3,
    label: str = "structured",
) -> Optional[T]:
    """
    Call an LLM, parse the result, and retry with a correction prompt
    if parsing fails.

    Args:
        call_fn:            async callable that performs the initial LLM call,
                            returns raw text
        parse_fn:           callable that parses raw text → T or None
        correction_call_fn: async callable that takes the failed raw response
                            and returns a corrected raw text (uses a
                            "please fix this" follow-up prompt)
        max_attempts:       total attempts including initial call
        label:              label for log messages

    Returns the first successfully parsed value, or None if all attempts fail.
    """
    raw = await call_fn()

    for attempt in range(1, max_attempts + 1):
        if is_empty(raw):
            logger.warning(
                "output_parser.empty_response",
                label=label,
                attempt=attempt,
            )
        else:
            result = parse_fn(raw)
            if result is not None:
                if attempt > 1:
                    logger.info(
                        "output_parser.recovered_on_retry",
                        label=label,
                        attempt=attempt,
                    )
                return result
            logger.warning(
                "output_parser.parse_failed",
                label=label,
                attempt=attempt,
                raw_snippet=raw[:120],
            )

        if attempt < max_attempts:
            raw = await correction_call_fn(raw)

    logger.error(
        "output_parser.all_attempts_failed",
        label=label,
        max_attempts=max_attempts,
    )
    return None


# ── Internal helpers ─────────────────────────────────────────────────────────

def _try_direct(text: str) -> Optional[Any]:
    try:
        return json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        return None


def _try_code_fence(text: str) -> Optional[Any]:
    m = _CODE_FENCE_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _try_first_brace_block(text: str) -> Optional[Any]:
    """Find the first {...} or [...] block and attempt to parse it."""
    for open_ch, close_ch in (('{', '}'), ('[', ']')):
        start = text.find(open_ch)
        if start == -1:
            continue
        # Walk forward to find the matching close
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        return json.loads(candidate)
                    except (json.JSONDecodeError, ValueError):
                        break
    return None


def _fix_trailing_commas(text: str) -> str:
    return _TRAILING_COMMA_RE.sub(r"\1", text)


def _try_json_repair(text: str) -> Optional[Any]:
    """Use json-repair to recover malformed JSON (missing quotes, etc.)."""
    try:
        from json_repair import repair_json  # type: ignore[import-untyped]
        repaired = repair_json(text, return_objects=True)
        # repair_json returns "" or None for hopeless input
        if repaired not in (None, "", [], {}):
            return repaired
    except Exception:
        pass
    return None


