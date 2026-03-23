"""Convert Markdown text to Slack Block Kit blocks.

Ported from https://github.com/magifd2/md-to-slack (MIT License).

Supported elements:
  H1 / H2          → header block (plain_text)
  H3–H6            → section block (*bold*)
  Paragraph        → section block (mrkdwn)
  Ordered list     → section block (1. item)
  Unordered list   → section block (• / ◦ bullets)
  Blockquote       → section block (> prefix)
  Fenced code      → section block (``` fence)
  Horizontal rule  → divider block
  Inline bold      → *text*
  Inline italic    → _text_
  Strikethrough    → ~text~
  Inline code      → `text`
  Link             → <url|text>
"""

import re
from typing import Any

# Slack section block text limit
_MAX_SECTION_CHARS = 2900


def md_to_slack_blocks(markdown: str) -> list[dict[str, Any]]:
    """Convert a Markdown string to a list of Slack Block Kit block dicts."""
    blocks: list[dict[str, Any]] = []
    lines = markdown.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i]

        # ── Fenced code block ─────────────────────────────────────────
        if line.startswith("```"):
            code_lines: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code_lines.append(lines[i])
                i += 1
            code = "\n".join(code_lines)
            blocks.append(_section(f"```\n{code}\n```"))
            i += 1  # skip closing fence
            continue

        # ── Horizontal rule ───────────────────────────────────────────
        if re.match(r"^(-{3,}|\*{3,}|_{3,})\s*$", line):
            blocks.append({"type": "divider"})
            i += 1
            continue

        # ── Heading ───────────────────────────────────────────────────
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            if level <= 2:
                blocks.append({
                    "type": "header",
                    "text": {"type": "plain_text", "text": text, "emoji": True},
                })
            else:
                blocks.append(_section(f"*{_inline_md(text)}*"))
            i += 1
            continue

        # ── Blockquote ────────────────────────────────────────────────
        if line.startswith(">"):
            quote_lines: list[str] = []
            while i < len(lines) and lines[i].startswith(">"):
                quote_lines.append(lines[i][1:].lstrip())
                i += 1
            mrkdwn = "\n".join(f"> {_inline_md(l)}" for l in quote_lines)
            blocks.append(_section(mrkdwn))
            continue

        # ── List ──────────────────────────────────────────────────────
        if re.match(r"^\s*[-*+]\s", line) or re.match(r"^\s*\d+\.\s", line):
            list_lines: list[str] = []
            while i < len(lines) and _is_list_line(lines[i]):
                list_lines.append(lines[i])
                i += 1
            blocks.append(_section(_render_list(list_lines)))
            continue

        # ── Blank line ────────────────────────────────────────────────
        if not line.strip():
            i += 1
            continue

        # ── Paragraph ─────────────────────────────────────────────────
        para_lines: list[str] = []
        while i < len(lines) and lines[i].strip() and not _is_block_start(lines[i]):
            para_lines.append(lines[i])
            i += 1
        if para_lines:
            blocks.append(_section(_inline_md(" ".join(para_lines))))

    return blocks


# ── Internal helpers ──────────────────────────────────────────────────────────

def _is_list_line(line: str) -> bool:
    return bool(
        re.match(r"^\s*[-*+]\s", line)
        or re.match(r"^\s*\d+\.\s", line)
        or (line.startswith("  ") and line.strip())
    )


def _is_block_start(line: str) -> bool:
    return bool(
        re.match(r"^#{1,6}\s", line)
        or re.match(r"^(-{3,}|\*{3,}|_{3,})\s*$", line)
        or re.match(r"^\s*[-*+]\s", line)
        or re.match(r"^\s*\d+\.\s", line)
        or line.startswith("```")
        or line.startswith(">")
    )


def _render_list(lines: list[str]) -> str:
    parts: list[str] = []
    for line in lines:
        indent = len(line) - len(line.lstrip())
        depth = indent // 2
        pad = "  " * depth

        m = re.match(r"^\s*(\d+)\.\s+(.*)", line)
        if m:
            parts.append(f"{pad}{m.group(1)}. {_inline_md(m.group(2))}")
            continue

        m = re.match(r"^\s*[-*+]\s+(.*)", line)
        if m:
            bullet = "•" if depth == 0 else "◦"
            parts.append(f"{pad}{bullet} {_inline_md(m.group(1))}")
    return "\n".join(parts)


def _inline_md(text: str) -> str:
    """Convert inline Markdown syntax to Slack mrkdwn.

    Conversion table:
      Markdown **text**  → Slack *text*  (bold)
      Markdown __text__  → Slack *text*  (bold)
      Markdown ~~text~~  → Slack ~text~  (strikethrough)
      Markdown [l](url)  → Slack <url|l> (link)

    Single *text* and _text_ are passed through unchanged because:
      - LLMs frequently output Slack-native mrkdwn (*bold*, _italic_)
      - Slack already renders *text* as bold and _text_ as italic in
        section block mrkdwn, so no conversion is needed.
    """
    # Links: [label](url) → <url|label>
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"<\2|\1>", text)
    # Markdown double-star/underscore bold → Slack single-star bold
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    text = re.sub(r"__(.+?)__", r"*\1*", text)
    # Strikethrough: ~~text~~ → ~text~
    text = re.sub(r"~~(.+?)~~", r"~\1~", text)
    # Single *text* and _text_ left as-is (already valid Slack mrkdwn)
    return text


def _section(text: str) -> dict[str, Any]:
    return {
        "type": "section",
        "text": {"type": "mrkdwn", "text": text[:_MAX_SECTION_CHARS]},
    }
