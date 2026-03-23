"""Memory lifecycle management: HOT → WARM → COLD → ARCHIVE.

PINNED records are never transitioned and never archived.

State machine:
  HOT    (< hot_max_age_hours)   : original message stored
  WARM   (< warm_max_age_days)   : LLM-summarized batch
  COLD   (>= warm_max_age_days)  : marked for archival
  ARCHIVE                        : moved to memory_archive table
  PINNED                         : permanent, never transitions
"""

import json
from datetime import timedelta
from typing import TYPE_CHECKING

from ..db.repositories.memory import MemoryRepository
from ..db.repositories.embedding import EmbeddingRepository
from ..utils.ids import new_id
from ..utils.logging import get_logger
from ..utils.time import utcnow, to_unix
from .models import MemoryRecord, MemoryState
from .summarizer import Summarizer

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class LifecycleManager:
    def __init__(
        self,
        memory_repo: MemoryRepository,
        embedding_repo: EmbeddingRepository,
        summarizer: Summarizer,
        hot_max_age_hours: int = 24,
        warm_max_age_days: int = 7,
    ) -> None:
        self._memory = memory_repo
        self._embeddings = embedding_repo
        self._summarizer = summarizer
        self._hot_max_age_hours = hot_max_age_hours
        self._warm_max_age_days = warm_max_age_days

    async def run_aging(self) -> dict[str, int]:
        """
        Run one aging cycle. Returns counts of transitioned records.
        Called by the background scheduler.
        """
        stats = {"hot_to_warm": 0, "warm_to_cold": 0}
        stats["hot_to_warm"] = await self._age_hot_to_warm()
        stats["warm_to_cold"] = await self._mark_warm_to_cold()
        logger.info("lifecycle.aging_done", **stats)
        return stats

    async def run_archive(self) -> int:
        """Archive all COLD records. Returns count archived."""
        count = await self._archive_cold()
        logger.info("lifecycle.archive_done", archived=count)
        return count

    # ------------------------------------------------------------------
    # HOT → WARM
    # ------------------------------------------------------------------

    async def _age_hot_to_warm(self) -> int:
        cutoff = to_unix(utcnow() - timedelta(hours=self._hot_max_age_hours))
        records = await self._memory.find_older_than(MemoryState.HOT, cutoff)
        if not records:
            return 0

        # Group by (user_id, channel_id) for contextual summarization
        groups: dict[tuple[str, str], list[MemoryRecord]] = {}
        for r in records:
            key = (r.user_id, r.channel_id)
            groups.setdefault(key, []).append(r)

        total = 0
        for (user_id, channel_id), batch in groups.items():
            await self._summarize_and_replace(user_id, channel_id, batch)
            total += len(batch)

        return total

    async def _summarize_and_replace(
        self,
        user_id: str,
        channel_id: str,
        records: list[MemoryRecord],
    ) -> None:
        """Replace a batch of HOT records with a single WARM summary."""
        summary_text = await self._summarizer.summarize_batch(records)
        if not summary_text:
            return

        # Use the oldest record's metadata for the summary
        oldest = min(records, key=lambda r: r.created_at)

        warm_record = MemoryRecord(
            id=new_id(),
            user_id=user_id,
            user_name=oldest.user_name,
            channel_id=channel_id,
            channel_name=oldest.channel_name,
            ts=oldest.ts,
            created_at=oldest.created_at,
            content=summary_text,
            state=MemoryState.WARM,
            is_summary=True,
            summary_of=[r.id for r in records],
        )
        await self._memory.save(warm_record)

        # Delete original HOT records and their embeddings
        old_ids = [r.id for r in records]
        embedding_ids = [r.embedding_id for r in records if r.embedding_id]
        if embedding_ids:
            await self._embeddings.delete_many(embedding_ids)
        await self._memory.delete_many(old_ids)

        logger.debug(
            "lifecycle.hot_to_warm",
            user_id=user_id,
            channel_id=channel_id,
            source_count=len(records),
            warm_id=warm_record.id,
        )

    # ------------------------------------------------------------------
    # WARM → COLD
    # ------------------------------------------------------------------

    async def _mark_warm_to_cold(self) -> int:
        cutoff = to_unix(utcnow() - timedelta(days=self._warm_max_age_days))
        records = await self._memory.find_older_than(MemoryState.WARM, cutoff)
        for r in records:
            await self._memory.update_state(r.id, MemoryState.COLD)
        return len(records)

    # ------------------------------------------------------------------
    # COLD → ARCHIVE
    # ------------------------------------------------------------------

    async def _archive_cold(self) -> int:
        records = await self._memory.find_by_state(MemoryState.COLD)
        count = 0
        for r in records:
            # Remove embedding first
            if r.embedding_id:
                await self._embeddings.delete(r.embedding_id)
            await self._memory.archive(r)
            count += 1
        return count
