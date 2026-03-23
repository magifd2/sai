"""Convert LLM output (Slack mrkdwn + structural Markdown) to Slack Block Kit blocks.

The LLM is instructed to output Slack mrkdwn directly, so most inline
formatting (*bold*, _italic_, `code`, • bullets, etc.) passes through
unchanged.  This converter only handles structural elements that need to
become distinct Block Kit block types:

  ## / #   → header block   (plain_text, no mrkdwn)
  | table | → table block   (native Slack table; max 1 per message, 100 rows)
  ``` fence → section block (mrkdwn code fence)
  ---       → divider block

Everything else is accumulated as raw mrkdwn text and emitted as section
blocks (split at blank lines to stay within Slack's 3000-char limit).
"""

import re
from typing import Any

# Slack section block character limit
_MAX_SECTION_CHARS = 2900


# ── Public API ────────────────────────────────────────────────────────────────

def md_to_slack_blocks(text: str) -> list[dict[str, Any]]:
    """Convert LLM mrkdwn output to a list of Slack Block Kit block dicts."""
    blocks: list[dict[str, Any]] = []
    lines = text.splitlines()
    mrkdwn_buf: list[str] = []   # accumulated mrkdwn lines not yet emitted
    i = 0

    def flush_mrkdwn() -> None:
        """Emit buffered mrkdwn lines as one or more section blocks."""
        if not mrkdwn_buf:
            return
        # Split on blank lines to keep each section under the char limit
        chunk_lines: list[str] = []
        for ln in mrkdwn_buf:
            if not ln.strip() and chunk_lines:
                _emit_section(blocks, "\n".join(chunk_lines))
                chunk_lines = []
            else:
                chunk_lines.append(ln)
        if chunk_lines:
            _emit_section(blocks, "\n".join(chunk_lines))
        mrkdwn_buf.clear()

    while i < len(lines):
        line = lines[i]

        # ── Fenced code block ─────────────────────────────────────────
        if line.startswith("```"):
            flush_mrkdwn()
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
            flush_mrkdwn()
            blocks.append({"type": "divider"})
            i += 1
            continue

        # ── Heading (# or ##) ─────────────────────────────────────────
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            flush_mrkdwn()
            text_content = m.group(2).strip()
            blocks.append({
                "type": "header",
                "text": {"type": "plain_text", "text": text_content, "emoji": True},
            })
            i += 1
            continue

        # ── Table ─────────────────────────────────────────────────────
        if line.startswith("|"):
            flush_mrkdwn()
            table_lines: list[str] = []
            while i < len(lines) and lines[i].startswith("|"):
                table_lines.append(lines[i])
                i += 1
            table_block = _render_table(table_lines)
            if table_block:
                blocks.append(table_block)
            continue

        # ── Everything else: accumulate as mrkdwn ─────────────────────
        mrkdwn_buf.append(_normalize_mrkdwn(line))
        i += 1

    flush_mrkdwn()
    return blocks


def split_blocks_for_slack(blocks: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Split a blocks list into multiple payloads, each with at most one table block.

    Slack allows only one table block per message.  When the converted output
    contains more than one table, this function partitions the blocks so that
    each partition ends with (at most) one table.  The caller should post each
    partition as a separate message in the same thread.

    Example: [p, t1, p, t2, p] → [[p, t1], [p, t2], [p]]
    """
    if sum(1 for b in blocks if b.get("type") == "table") <= 1:
        return [blocks] if blocks else []

    partitions: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for block in blocks:
        current.append(block)
        if block.get("type") == "table":
            partitions.append(current)
            current = []
    if current:
        partitions.append(current)
    return partitions


# ── Internal helpers ──────────────────────────────────────────────────────────

def _section(text: str) -> dict[str, Any]:
    return {
        "type": "section",
        "text": {"type": "mrkdwn", "text": text[:_MAX_SECTION_CHARS]},
    }


def _emit_section(blocks: list[dict[str, Any]], text: str) -> None:
    """Append section block(s) for text, splitting if it exceeds the char limit."""
    text = text.strip()
    if not text:
        return
    while len(text) > _MAX_SECTION_CHARS:
        # Find last newline within the limit to avoid splitting mid-line
        cut = text.rfind("\n", 0, _MAX_SECTION_CHARS)
        if cut == -1:
            cut = _MAX_SECTION_CHARS
        blocks.append(_section(text[:cut]))
        text = text[cut:].lstrip("\n")
    if text:
        blocks.append(_section(text))


def _parse_table_row(line: str) -> list[str]:
    """Split a Markdown table row into cell strings."""
    line = line.strip().strip("|")
    return [cell.strip() for cell in line.split("|")]


def _is_separator_row(line: str) -> bool:
    """Return True if the line is a table separator (e.g. |---|---|)."""
    return bool(re.match(r"^\|[-| :]+\|?\s*$", line))


def _render_table(lines: list[str]) -> dict[str, Any] | None:
    """Convert Markdown table rows to a Slack native table block.

    Constraints (Slack API):
      - Only one table block is allowed per message.
      - Maximum 100 rows and 20 columns.
    """
    rows: list[list] = []
    for line in lines:
        if _is_separator_row(line):
            continue
        cells = _parse_table_row(line)
        if not any(cells):
            continue
        rows.append([{"type": "raw_text", "text": _strip_mrkdwn(cell)} for cell in cells[:20]])
        if len(rows) >= 100:
            break

    if not rows:
        return None

    return {"type": "table", "rows": rows}


def _normalize_mrkdwn(line: str) -> str:
    """Normalize Markdown inline syntax to Slack mrkdwn in a single line.

    LLMs trained on Markdown often ignore Slack mrkdwn instructions and
    output **double-asterisk** bold or ~~tilde~~ strikethrough.  Convert
    these to their Slack equivalents so Slack renders them correctly.
    """
    # **bold** → *bold*  (must run before single-* check)
    line = re.sub(r"\*\*(.+?)\*\*", r"*\1*", line)
    # __bold__ → *bold*
    line = re.sub(r"__(.+?)__", r"*\1*", line)
    # ~~strike~~ → ~strike~
    line = re.sub(r"~~(.+?)~~", r"~\1~", line)
    # Markdown list bullets (-) → Slack Unicode bullets (• / ◦ for nested)
    # Only `-` is converted; `*` is intentionally excluded because it is also
    # used as the bold/italic marker in Slack mrkdwn and cannot be safely
    # distinguished from a bullet at the start of a line.
    def _bullet(m: re.Match) -> str:
        indent = len(m.group(1))
        bullet = "◦" if indent >= 2 else "•"
        return f"{m.group(1)}{bullet} {m.group(2)}"
    line = re.sub(r"^(\s*)-\s+(.+)", _bullet, line)
    return line


def _strip_mrkdwn(text: str) -> str:
    """Strip mrkdwn inline markup to produce plain text for raw_text cells."""
    text = re.sub(r"\*(.+?)\*", r"\1", text)            # *bold*
    text = re.sub(r"_(.+?)_", r"\1", text)              # _italic_
    text = re.sub(r"~(.+?)~", r"\1", text)              # ~strike~
    text = re.sub(r"`(.+?)`", r"\1", text)              # `code`
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # [label](url)
    text = re.sub(r"<[^|>]+\|([^>]+)>", r"\1", text)   # <url|label>
    return text.strip()
