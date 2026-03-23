"""LLM-based batch summarization for memory aging (HOT → WARM)."""

from ..llm.client import ChatMessage, LLMClient
from ..llm import nonce as nonce_mod, prompts
from ..llm.output_parser import is_empty
from ..utils.logging import get_logger
from .models import MemoryRecord

logger = get_logger(__name__)

_MIN_SUMMARY_CHARS = 20   # summaries shorter than this are treated as failures
_MAX_SUMMARIZE_ATTEMPTS = 2


class Summarizer:
    def __init__(self, llm: LLMClient, workspace_name: str = "workspace") -> None:
        self._llm = llm
        self._workspace_name = workspace_name

    async def summarize_batch(self, records: list[MemoryRecord]) -> str:
        """
        Summarize a batch of memory records into a single WARM summary string.

        Records are formatted as:
            [YYYY-MM-DD HH:MM] @username: message
        then wrapped with a nonce for injection protection.

        If the LLM returns an empty or suspiciously short response, retries
        once with a reminder. Falls back to a plain concatenation as last resort.
        """
        if not records:
            return ""

        lines = []
        for r in sorted(records, key=lambda x: x.created_at):
            ts_str = r.created_at.strftime("%Y-%m-%d %H:%M")
            lines.append(f"[{ts_str}] @{r.user_name}: {r.content}")
        records_text = "\n".join(lines)

        request_nonce = nonce_mod.generate()
        messages = prompts.build_summarize_prompt(
            records_text=records_text,
            request_nonce=request_nonce,
            workspace_name=self._workspace_name,
        )

        logger.debug(
            "summarizer.summarize",
            record_count=len(records),
            nonce=request_nonce[:8] + "...",
        )

        for attempt in range(1, _MAX_SUMMARIZE_ATTEMPTS + 1):
            summary = await self._llm.chat(messages, nonce=request_nonce)

            if not is_empty(summary) and len(summary.strip()) >= _MIN_SUMMARY_CHARS:
                return summary.strip()

            logger.warning(
                "summarizer.bad_response",
                attempt=attempt,
                length=len(summary),
                snippet=summary[:60],
            )

            if attempt < _MAX_SUMMARIZE_ATTEMPTS:
                # Append a correction turn and retry
                messages = messages + [
                    ChatMessage(role="assistant", content=summary),
                    ChatMessage(
                        role="user",
                        content=(
                            "Your summary appears to be empty or incomplete. "
                            "Please provide a proper summary of the conversation records."
                        ),
                    ),
                ]

        # Last resort: plain concatenation (never loses data)
        logger.error("summarizer.fallback_to_concat", record_count=len(records))
        return records_text
