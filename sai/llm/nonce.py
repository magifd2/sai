"""Nonce-based XML encapsulation for prompt injection defense.

A cryptographically random nonce is generated per-request.
User input is wrapped in a tag whose name includes the nonce,
making it impossible for an attacker to craft a closing tag
to escape the user content section.

Example:
    nonce  = "a3f9c2e8b1d47f6c"
    role   = "message"
    result = <user-input-a3f9c2e8b1d47f6c-message>
               ...user text...
             </user-input-a3f9c2e8b1d47f6c-message>
"""

import re
import secrets


def generate() -> str:
    """Generate a 16-byte (32-char hex) cryptographically random nonce."""
    return secrets.token_hex(16)


def wrap(content: str, nonce: str, role: str = "message") -> str:
    """Wrap untrusted content in a nonce-tagged XML element."""
    tag = f"user-input-{nonce}-{role}"
    return f"<{tag}>\n{content}\n</{tag}>"


def wrap_context(content: str, nonce: str) -> str:
    """Wrap semi-trusted RAG context in a nonce-tagged element."""
    tag = f"context-{nonce}"
    return f"<{tag}>\n{content}\n</{tag}>"


def strip_nonce_tags(text: str, nonce: str) -> str:
    """Remove any XML tags containing the nonce from LLM output."""
    pattern = re.compile(
        rf"</?[^>]*{re.escape(nonce)}[^>]*>",
        re.IGNORECASE,
    )
    return pattern.sub("", text).strip()


def validate_present(prompt: str, nonce: str) -> bool:
    """Verify the nonce appears in the prompt before sending to LLM."""
    return nonce in prompt
