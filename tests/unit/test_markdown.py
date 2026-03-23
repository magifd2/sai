"""Tests for Markdown → Slack Block Kit converter."""

from sai.slack.markdown import md_to_slack_blocks, _inline_md


# ── _inline_md ────────────────────────────────────────────────────────────────

def test_inline_bold():
    assert _inline_md("**bold**") == "*bold*"
    assert _inline_md("__bold__") == "*bold*"


def test_inline_italic():
    assert _inline_md("_italic_") == "_italic_"


def test_inline_strikethrough():
    assert _inline_md("~~del~~") == "~del~"


def test_inline_link():
    assert _inline_md("[label](https://example.com)") == "<https://example.com|label>"


def test_inline_combined():
    result = _inline_md("**bold** and _italic_ and ~~strike~~")
    assert "*bold*" in result
    assert "_italic_" in result
    assert "~strike~" in result


# ── md_to_slack_blocks ────────────────────────────────────────────────────────

def test_h1_becomes_header_block():
    blocks = md_to_slack_blocks("# Hello")
    assert blocks[0]["type"] == "header"
    assert blocks[0]["text"]["text"] == "Hello"


def test_h2_becomes_header_block():
    blocks = md_to_slack_blocks("## Hello")
    assert blocks[0]["type"] == "header"


def test_h3_becomes_section_bold():
    blocks = md_to_slack_blocks("### Sub")
    assert blocks[0]["type"] == "section"
    assert "*Sub*" in blocks[0]["text"]["text"]


def test_paragraph_becomes_section():
    blocks = md_to_slack_blocks("Hello world")
    assert blocks[0]["type"] == "section"
    assert blocks[0]["text"]["text"] == "Hello world"


def test_horizontal_rule_becomes_divider():
    blocks = md_to_slack_blocks("---")
    assert blocks[0]["type"] == "divider"


def test_unordered_list():
    md = "- item one\n- item two"
    blocks = md_to_slack_blocks(md)
    assert blocks[0]["type"] == "section"
    text = blocks[0]["text"]["text"]
    assert "• item one" in text
    assert "• item two" in text


def test_ordered_list():
    md = "1. first\n2. second"
    blocks = md_to_slack_blocks(md)
    text = blocks[0]["text"]["text"]
    assert "1. first" in text
    assert "2. second" in text


def test_code_block():
    md = "```python\nprint('hello')\n```"
    blocks = md_to_slack_blocks(md)
    assert blocks[0]["type"] == "section"
    assert "```" in blocks[0]["text"]["text"]
    assert "print('hello')" in blocks[0]["text"]["text"]


def test_blockquote():
    blocks = md_to_slack_blocks("> some quote")
    assert blocks[0]["type"] == "section"
    assert blocks[0]["text"]["text"].startswith("> ")


def test_mixed_document():
    md = "# Title\n\nParagraph text.\n\n---\n\n- a\n- b"
    blocks = md_to_slack_blocks(md)
    types = [b["type"] for b in blocks]
    assert "header" in types
    assert "section" in types
    assert "divider" in types


def test_empty_input():
    assert md_to_slack_blocks("") == []


def test_text_truncated_at_limit():
    long_text = "x" * 3000
    blocks = md_to_slack_blocks(long_text)
    assert len(blocks[0]["text"]["text"]) <= 2900
