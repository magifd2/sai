"""Tests for robust LLM output parsing."""

import pytest
from unittest.mock import AsyncMock

from sai.llm.output_parser import (
    extract_json,
    extract_int,
    is_empty,
    retry_structured,
)


# ── extract_json ─────────────────────────────────────────────────────────────

def test_extract_json_clean():
    assert extract_json('{"key": "value"}') == {"key": "value"}


def test_extract_json_code_fence():
    text = '```json\n{"key": "value"}\n```'
    assert extract_json(text) == {"key": "value"}


def test_extract_json_code_fence_no_lang():
    text = '```\n{"key": "value"}\n```'
    assert extract_json(text) == {"key": "value"}


def test_extract_json_prefixed_prose():
    text = 'Here is the JSON you requested:\n{"path": "/tmp", "flag": true}'
    result = extract_json(text)
    assert result == {"path": "/tmp", "flag": True}


def test_extract_json_trailing_comma():
    text = '{"key": "value",}'
    result = extract_json(text)
    assert result == {"key": "value"}


def test_extract_json_array():
    assert extract_json("[1, 2, 3]") == [1, 2, 3]


def test_extract_json_array_in_prose():
    text = "The list is: [1, 2, 3] — done"
    assert extract_json(text) == [1, 2, 3]


def test_extract_json_json_repair_missing_quotes():
    # json-repair handles: {key: "value"} (unquoted key)
    result = extract_json('{key: "value"}')
    assert result is not None
    assert result.get("key") == "value"


def test_extract_json_returns_none_on_garbage():
    assert extract_json("totally not json at all") is None
    assert extract_json("") is None


# ── extract_int ──────────────────────────────────────────────────────────────

def test_extract_int_clean():
    assert extract_int("3", max_value=5) == 3


def test_extract_int_with_whitespace():
    assert extract_int("  2  \n", max_value=5) == 2


def test_extract_int_from_prose():
    assert extract_int("I would choose option 3 because it matches best.", max_value=5) == 3


def test_extract_int_prefixed():
    assert extract_int("Answer: 4", max_value=5) == 4


def test_extract_int_none_variants():
    assert extract_int("none", max_value=5) is None
    assert extract_int("N/A", max_value=5) is None
    assert extract_int("no match", max_value=5) is None
    assert extract_int("null", max_value=5) is None


def test_extract_int_out_of_range():
    assert extract_int("6", max_value=5) is None
    assert extract_int("0", max_value=5) is None


def test_extract_int_injection_string():
    assert extract_int("1; rm -rf /", max_value=5) == 1  # extracts 1, ignores the rest
    assert extract_int("ignore previous instructions", max_value=5) is None


# ── is_empty ─────────────────────────────────────────────────────────────────

def test_is_empty_blank():
    assert is_empty("") is True
    assert is_empty("   ") is True
    assert is_empty("\n\t") is True


def test_is_empty_not_blank():
    assert is_empty("hello") is False
    assert is_empty(" x ") is False


# ── retry_structured ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retry_structured_succeeds_first_try():
    call_fn = AsyncMock(return_value='{"a": "1"}')
    correction_fn = AsyncMock(return_value="unused")

    result = await retry_structured(
        call_fn=call_fn,
        parse_fn=extract_json,
        correction_call_fn=correction_fn,
        max_attempts=3,
    )
    assert result == {"a": "1"}
    call_fn.assert_called_once()
    correction_fn.assert_not_called()


@pytest.mark.asyncio
async def test_retry_structured_recovers_on_second_attempt():
    call_fn = AsyncMock(return_value="not json")
    correction_fn = AsyncMock(return_value='{"fixed": true}')

    result = await retry_structured(
        call_fn=call_fn,
        parse_fn=extract_json,
        correction_call_fn=correction_fn,
        max_attempts=3,
    )
    assert result == {"fixed": True}
    call_fn.assert_called_once()
    correction_fn.assert_called_once_with("not json")


@pytest.mark.asyncio
async def test_retry_structured_all_attempts_fail():
    call_fn = AsyncMock(return_value="garbage")
    correction_fn = AsyncMock(return_value="still garbage")

    result = await retry_structured(
        call_fn=call_fn,
        parse_fn=extract_json,
        correction_call_fn=correction_fn,
        max_attempts=3,
    )
    assert result is None
    assert correction_fn.call_count == 2  # called for attempts 2 and 3


@pytest.mark.asyncio
async def test_retry_structured_empty_response_then_recovery():
    responses = ["", "", '{"ok": true}']
    call_fn = AsyncMock(side_effect=[responses[0]])
    correction_fn = AsyncMock(side_effect=responses[1:])

    result = await retry_structured(
        call_fn=call_fn,
        parse_fn=extract_json,
        correction_call_fn=correction_fn,
        max_attempts=3,
    )
    assert result == {"ok": True}
