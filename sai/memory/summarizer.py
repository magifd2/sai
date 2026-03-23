"""LLM-based batch summarization for memory aging (HOT → WARM)."""

from ..llm.client import LLMClient
from ..llm import nonce as nonce_mod, prompts
from ..utils.logging import get_logger
from .models import MemoryRecord

logger = get_logger(__name__)


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

        summary = await self._llm.chat(messages, nonce=request_nonce)
        return summary
