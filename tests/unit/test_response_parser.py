"""Tests for LLM response parser including model-specific tag stripping."""

import pytest
from sai.llm.response_parser import strip_internal_tags, parse_command_index, clean_response


def test_strip_think_tags():
    text = "<think>internal reasoning here</think>\nActual answer"
    assert strip_internal_tags(text) == "Actual answer"


def test_strip_thinking_tags():
    text = "<thinking>\nMultiline\nthinking\n</thinking>\nResponse"
    assert strip_internal_tags(text) == "Response"


def test_strip_reasoning_tags():
    text = "<reasoning>some reasoning</reasoning>The answer is 42"
    assert strip_internal_tags(text) == "The answer is 42"


def test_strip_mistral_square_bracket_tags():
    """Mistral-style [THINK]...[/THINK] tags must be stripped."""
    text = "[THINK]Let me think about this...[/THINK]\nHere is my answer."
    assert strip_internal_tags(text) == "Here is my answer."


def test_strip_mistral_thinking_square():
    text = "[THINKING]reasoning here[/THINKING]Result"
    assert strip_internal_tags(text) == "Result"


def test_strip_mistral_case_insensitive():
    text = "[think]lower case[/think]answer"
    assert strip_internal_tags(text) == "answer"


def test_strip_multiline_think():
    text = "<think>\nline1\nline2\nline3\n</think>\nFinal answer"
    assert strip_internal_tags(text) == "Final answer"


def test_no_tags_unchanged():
    text = "Plain response with no tags"
    assert strip_internal_tags(text) == text


def test_parse_command_index_valid():
    assert parse_command_index("3", max_index=5) == 3
    assert parse_command_index("  1  ", max_index=5) == 1
    assert parse_command_index("5\n", max_index=5) == 5


def test_parse_command_index_none():
    assert parse_command_index("none", max_index=5) is None
    assert parse_command_index("N/A", max_index=5) is None
    assert parse_command_index("0", max_index=5) is None


def test_parse_command_index_out_of_range():
    assert parse_command_index("6", max_index=5) is None
    assert parse_command_index("-1", max_index=5) is None


def test_parse_command_index_injection_rejected():
    """LLM injection in command selection must be rejected."""
    assert parse_command_index("1; rm -rf /", max_index=5) is None
    assert parse_command_index("ignore previous", max_index=5) is None
    assert parse_command_index("3 because it matches best", max_index=5) is None
