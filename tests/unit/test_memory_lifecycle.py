"""Tests for memory state lifecycle transitions."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

from sai.memory.models import MemoryRecord, MemoryState
from sai.memory.lifecycle import LifecycleManager
from sai.db.repositories.memory import MemoryRepository
from sai.db.repositories.embedding import EmbeddingRepository
from sai.utils.ids import new_id
from sai.utils.time import utcnow


def make_record(state: MemoryState, age_hours: float = 0.0) -> MemoryRecord:
    created = utcnow() - timedelta(hours=age_hours)
    return MemoryRecord(
        id=new_id(),
        user_id="U123",
        user_name="alice",
        channel_id="C456",
        ts=str(created.timestamp()),
        created_at=created,
        content="Test message content",
        state=state,
    )


@pytest.fixture
def mock_summarizer():
    summarizer = MagicMock()
    summarizer.summarize_batch = AsyncMock(return_value="Summary of batch")
    return summarizer


@pytest.fixture
def lifecycle(memory_repo, embedding_repo, mock_summarizer):
    return LifecycleManager(
        memory_repo=memory_repo,
        embedding_repo=embedding_repo,
        summarizer=mock_summarizer,
        hot_max_age_hours=24,
        warm_max_age_days=7,
    )


@pytest.mark.asyncio
async def test_hot_record_not_aged_when_fresh(lifecycle, memory_repo):
    record = make_record(MemoryState.HOT, age_hours=1)
    await memory_repo.save(record)

    stats = await lifecycle.run_aging()
    assert stats["hot_to_warm"] == 0

    # Record should still be HOT
    fetched = await memory_repo.get_by_id(record.id)
    assert fetched is not None
    assert fetched.state == MemoryState.HOT


@pytest.mark.asyncio
async def test_hot_record_aged_to_warm(lifecycle, memory_repo, mock_summarizer):
    record = make_record(MemoryState.HOT, age_hours=25)
    await memory_repo.save(record)

    stats = await lifecycle.run_aging()
    assert stats["hot_to_warm"] == 1

    # Original HOT record should be gone
    fetched = await memory_repo.get_by_id(record.id)
    assert fetched is None

    # A WARM summary record should exist
    warm_records = await memory_repo.find_by_state(MemoryState.WARM)
    assert len(warm_records) == 1
    assert warm_records[0].is_summary


@pytest.mark.asyncio
async def test_warm_record_marked_cold(lifecycle, memory_repo):
    record = make_record(MemoryState.WARM, age_hours=24 * 8)  # 8 days old
    await memory_repo.save(record)

    stats = await lifecycle.run_aging()
    assert stats["warm_to_cold"] == 1

    fetched = await memory_repo.get_by_id(record.id)
    assert fetched.state == MemoryState.COLD


@pytest.mark.asyncio
async def test_cold_record_archived(lifecycle, memory_repo):
    record = make_record(MemoryState.COLD, age_hours=24 * 10)
    await memory_repo.save(record)

    count = await lifecycle.run_archive()
    assert count == 1

    # Should be gone from active memory
    fetched = await memory_repo.get_by_id(record.id)
    assert fetched is None


@pytest.mark.asyncio
async def test_pinned_record_never_aged(lifecycle, memory_repo):
    """PINNED records must never be transitioned by the lifecycle manager."""
    record = make_record(MemoryState.PINNED, age_hours=24 * 30)  # 30 days old
    record = record.model_copy(update={"pinned_at": utcnow(), "pinned_by": "U999", "pin_reaction": "pushpin"})
    await memory_repo.save(record)

    await lifecycle.run_aging()
    await lifecycle.run_archive()

    fetched = await memory_repo.get_by_id(record.id)
    assert fetched is not None
    assert fetched.state == MemoryState.PINNED
