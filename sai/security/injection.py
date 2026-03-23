"""Prompt injection detection.

Detects common injection patterns in user input.
Results are used by Sanitizer to block or flag requests.
"""

import re
from dataclasses import dataclass, field

from ..utils.logging import get_logger

logger = get_logger(__name__)

# Patterns that indicate jailbreak / instruction override attempts
_JAILBREAK_PATTERNS: list[re.Pattern] = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?", re.I),
    re.compile(r"(forget|disregard)\s+(all\s+)?(previous|prior|above)", re.I),
    re.compile(r"your\s+(new\s+)?system\s+prompt\s+is", re.I),
    re.compile(r"pretend\s+(you\s+are|to\s+be)", re.I),
    re.compile(r"you\s+are\s+now\s+(a|an|the)\s+", re.I),
    re.compile(r"do\s+anything\s+now", re.I),  # DAN
    re.compile(r"jailbreak", re.I),
    re.compile(r"<\s*system\s*>", re.I),       # literal <system> tag injection
    re.compile(r"<\s*\/?\s*user\s*>", re.I),   # literal <user> tag injection
    re.compile(r"<\s*\/?\s*assistant\s*>", re.I),
]

# Suspicious Unicode: zero-width characters, directional overrides
_SUSPICIOUS_UNICODE_RE = re.compile(
    r"[\u200b\u200c\u200d\u200e\u200f\u202a-\u202e\u2060\ufeff\u00ad]"
)


@dataclass
class InjectionReport:
    detected: bool
    patterns_matched: list[str] = field(default_factory=list)
    has_suspicious_unicode: bool = False


def detect(text: str) -> InjectionReport:
    """Scan text for injection indicators. Does not modify the input."""
    matched = []

    for pat in _JAILBREAK_PATTERNS:
        m = pat.search(text)
        if m:
            matched.append(m.group(0))

    has_unicode = bool(_SUSPICIOUS_UNICODE_RE.search(text))

    detected = bool(matched) or has_unicode

    if detected:
        logger.warning(
            "injection.detected",
            patterns=matched,
            has_suspicious_unicode=has_unicode,
            snippet=text[:100],
        )

    return InjectionReport(
        detected=detected,
        patterns_matched=matched,
        has_suspicious_unicode=has_unicode,
    )
