"""Tests for Slack mrkdwn → Block Kit converter."""

from sai.slack.markdown import md_to_slack_blocks, split_blocks_for_slack


# ── Structural elements ───────────────────────────────────────────────────────

def test_h1_becomes_header_block():
    blocks = md_to_slack_blocks("# Hello")
    assert blocks[0]["type"] == "header"
    assert blocks[0]["text"]["text"] == "Hello"


def test_h2_becomes_header_block():
    blocks = md_to_slack_blocks("## Hello")
    assert blocks[0]["type"] == "header"


def test_h3_becomes_header_block():
    # All heading levels map to header blocks in the simplified converter
    blocks = md_to_slack_blocks("### Sub")
    assert blocks[0]["type"] == "header"
    assert blocks[0]["text"]["text"] == "Sub"


def test_paragraph_becomes_section():
    blocks = md_to_slack_blocks("Hello world")
    assert blocks[0]["type"] == "section"
    assert blocks[0]["text"]["text"] == "Hello world"


def test_horizontal_rule_becomes_divider():
    blocks = md_to_slack_blocks("---")
    assert blocks[0]["type"] == "divider"


def test_code_block():
    md = "```\necho hello\n```"
    blocks = md_to_slack_blocks(md)
    assert blocks[0]["type"] == "section"
    assert "```" in blocks[0]["text"]["text"]
    assert "echo hello" in blocks[0]["text"]["text"]


def test_empty_input():
    assert md_to_slack_blocks("") == []


# ── mrkdwn passthrough ────────────────────────────────────────────────────────

def test_slack_mrkdwn_bold_passthrough():
    blocks = md_to_slack_blocks("*bold text*")
    assert blocks[0]["text"]["text"] == "*bold text*"


def test_slack_mrkdwn_bullets_passthrough():
    md = "• item one\n• item two"
    blocks = md_to_slack_blocks(md)
    text = blocks[0]["text"]["text"]
    assert "• item one" in text
    assert "• item two" in text


def test_slack_mrkdwn_inline_code_passthrough():
    md = "引数 `timezone` を指定します"
    blocks = md_to_slack_blocks(md)
    assert "`timezone`" in blocks[0]["text"]["text"]


def test_blank_line_splits_sections():
    md = "first paragraph\n\nsecond paragraph"
    blocks = md_to_slack_blocks(md)
    assert len(blocks) == 2
    assert blocks[0]["text"]["text"] == "first paragraph"
    assert blocks[1]["text"]["text"] == "second paragraph"


def test_mixed_document():
    md = "## Title\n\nParagraph text.\n\n---\n\n• a\n• b"
    blocks = md_to_slack_blocks(md)
    types = [b["type"] for b in blocks]
    assert "header" in types
    assert "section" in types
    assert "divider" in types


# ── Table ─────────────────────────────────────────────────────────────────────

def test_table_becomes_table_block():
    md = "| コマンド | 概要 |\n|----------|------|\n| ping | 疎通確認 |\n| status | 状態確認 |"
    blocks = md_to_slack_blocks(md)
    assert blocks[0]["type"] == "table"
    rows = blocks[0]["rows"]
    assert len(rows) == 3   # header + 2 data rows (separator skipped)
    assert rows[0][0]["text"] == "コマンド"
    assert rows[1][0]["text"] == "ping"
    assert rows[1][1]["text"] == "疎通確認"


def test_table_strips_mrkdwn_markup():
    md = "| *名前* | `値` |\n|---|---|\n| *foo* | `bar` |"
    blocks = md_to_slack_blocks(md)
    assert blocks[0]["type"] == "table"
    assert blocks[0]["rows"][0][0]["text"] == "名前"
    assert blocks[0]["rows"][1][1]["text"] == "bar"


# ── split_blocks_for_slack ────────────────────────────────────────────────────

def test_split_single_table_no_split():
    blocks = [{"type": "section"}, {"type": "table"}, {"type": "section"}]
    result = split_blocks_for_slack(blocks)
    assert result == [blocks]


def test_split_two_tables():
    b = [
        {"type": "section", "id": 1},
        {"type": "table", "id": 2},
        {"type": "section", "id": 3},
        {"type": "table", "id": 4},
        {"type": "section", "id": 5},
    ]
    result = split_blocks_for_slack(b)
    assert len(result) == 3
    assert result[0] == [b[0], b[1]]
    assert result[1] == [b[2], b[3]]
    assert result[2] == [b[4]]


def test_split_empty():
    assert split_blocks_for_slack([]) == []


def test_text_truncated_at_limit():
    long_text = "x" * 3000
    blocks = md_to_slack_blocks(long_text)
    assert len(blocks[0]["text"]["text"]) <= 2900
