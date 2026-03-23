"""Input sanitization: clean user text before LLM injection.

Performed in order:
  1. Strip suspicious Unicode (zero-width chars, directional overrides)
  2. Expand Slack link tokens (<url|label> → label, <url> → url)
  3. Remove remaining XML/HTML-like tags (prevents tag injection)
  4. Truncate to max_chars
  5. Detect jailbreak patterns (via injection module)
"""

import re
from dataclasses import dataclass, field

from ..security.injection import detect, InjectionReport

# Zero-width / invisible / directional Unicode
_INVISIBLE_RE = re.compile(
    r"[\u200b\u200c\u200d\u200e\u200f\u202a-\u202e\u2060\ufeff\u00ad]"
)

# Slack mrkdwn special sequences that must be expanded before tag stripping:
#   <url|label>  → label   (auto-linked URL with display text)
#   <url>        → url     (bare auto-linked URL)
#   <@UID>       → @UID    (user mention — keep readable)
#   <#CID|name>  → #name   (channel mention)
_SLACK_LINK_RE = re.compile(r"<([^|>]+)\|([^>]*)>")   # <url|label>
# Bare Slack tokens: only URLs (http/https/ftp), user mentions <@U…>, channel
# mentions <#C…>, and special tokens <!…>.  Plain XML/HTML tags like <script>
# are intentionally excluded so they fall through to the tag stripper below.
_SLACK_BARE_RE = re.compile(
    r"<((?:https?|ftp)://[^>]+|@[A-Z0-9]+|#[A-Z0-9]+(?:\|[^>]*)?|![^>]+)>",
    re.IGNORECASE,
)

# Liberal XML/HTML tag removal (up to 200 chars between < and >)
_TAG_RE = re.compile(r"<[^>]{0,200}>")


@dataclass
class SanitizedText:
    clean: str
    warnings: list[str] = field(default_factory=list)
    blocked: bool = False
    injection_report: InjectionReport | None = None


def sanitize(
    text: str,
    max_chars: int = 2000,
    block_on_injection: bool = True,
) -> SanitizedText:
    """
    Sanitize user input before use in an LLM prompt.

    Returns a SanitizedText with the cleaned string and any warnings.
    If block_on_injection=True and injection is detected, blocked=True is set.
    """
    warnings: list[str] = []

    # 1. Strip invisible Unicode
    cleaned = _INVISIBLE_RE.sub("", text)
    if cleaned != text:
        warnings.append("stripped_invisible_unicode")

    # 2. Expand Slack mrkdwn link/mention tokens before tag removal so that
    #    auto-linked URLs like <http://example.com|example.com> become
    #    "example.com" rather than being wiped by the tag stripper.
    expanded = _SLACK_LINK_RE.sub(r"\2", cleaned)   # <url|label> → label
    expanded = _SLACK_BARE_RE.sub(r"\1", expanded)  # <url> → url, <@U…> → @U…
    if expanded != cleaned:
        warnings.append("expanded_slack_links")
    cleaned = expanded

    # 3. Remove remaining XML/HTML tags
    cleaned_no_tags = _TAG_RE.sub("", cleaned)
    if cleaned_no_tags != cleaned:
        warnings.append("stripped_xml_tags")
    cleaned = cleaned_no_tags

    # 3. Truncate
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars]
        warnings.append(f"truncated_to_{max_chars}_chars")

    # 4. Injection detection
    report = detect(cleaned)
    blocked = False
    if report.detected:
        warnings.append("injection_patterns_detected")
        if block_on_injection:
            blocked = True

    return SanitizedText(
        clean=cleaned,
        warnings=warnings,
        blocked=blocked,
        injection_report=report,
    )
