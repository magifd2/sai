"""Tests for message_changed and message_deleted event handling."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from sai.app import Application
from sai.memory.models import MemoryRecord, MemoryState
from sai.slack.events import SlackEvent, SlackEventType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(**kwargs) -> Application:
    defaults = dict(
        slack_client=MagicMock(),
        cache=MagicMock(),
        llm=MagicMock(),
        acl=MagicMock(),
        rate_limiter=MagicMock(),
        retriever=MagicMock(),
        memory_repo=MagicMock(),
        embedding_repo=MagicMock(),
        command_log_repo=MagicMock(),
        command_registry=MagicMock(),
        planner=MagicMock(),
        command_executor=MagicMock(),
        pin_reactions=[],
    )
    defaults.update(kwargs)
    return Application(**defaults)


def _make_record(
    state: MemoryState = MemoryState.HOT,
    ts: str = "1000000000.000001",
    channel_id: str = "C123",
    embedding_id: str = "emb-001",
    thread_ts: str = None,
) -> MemoryRecord:
    return MemoryRecord(
        id="rec-001",
        user_id="U123",
        user_name="alice",
        channel_id=channel_id,
        channel_name="general",
        ts=ts,
        thread_ts=thread_ts,
        created_at=datetime.now(timezone.utc),
        content="original content",
        state=state,
        embedding_id=embedding_id,
    )


def _make_changed_event(
    original_ts: str = "1000000000.000001",
    new_text: str = "edited content",
    channel_id: str = "C123",
) -> SlackEvent:
    return SlackEvent(
        event_type=SlackEventType.MESSAGE_CHANGED,
        user_id="U123",
        channel_id=channel_id,
        text=new_text,
        ts="1000000001.000001",
        received_at=datetime.now(timezone.utc),
        original_ts=original_ts,
    )


def _make_deleted_event(
    original_ts: str = "1000000000.000001",
    channel_id: str = "C123",
) -> SlackEvent:
    return SlackEvent(
        event_type=SlackEventType.MESSAGE_DELETED,
        user_id="U123",
        channel_id=channel_id,
        text="",
        ts="1000000002.000001",
        received_at=datetime.now(timezone.utc),
        original_ts=original_ts,
    )


# ---------------------------------------------------------------------------
# _handle_message_changed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_message_changed_adds_annotation_record():
    """An edit annotation HOT record is stored when the original is in memory."""
    app = _make_app()
    original = _make_record(state=MemoryState.HOT)

    app._memory.get_by_ts = AsyncMock(return_value=original)
    app._memory.save = AsyncMock()
    app._cache.get_channel = AsyncMock(return_value=MagicMock(channel_name="general"))
    app._retriever.index = AsyncMock()

    user = MagicMock(user_name="alice")
    event = _make_changed_event(new_text="edited content")

    await app._handle_message_changed(event, user)

    app._memory.save.assert_called_once()
    saved: MemoryRecord = app._memory.save.call_args[0][0]
    assert saved.state == MemoryState.HOT
    assert "edited content" in saved.content
    assert "alice" in saved.content
    assert saved.channel_id == "C123"


@pytest.mark.asyncio
async def test_message_changed_preserves_thread_ts():
    """Annotation record inherits thread_ts from the original record."""
    app = _make_app()
    original = _make_record(state=MemoryState.HOT, thread_ts="9000000000.000001")

    app._memory.get_by_ts = AsyncMock(return_value=original)
    app._memory.save = AsyncMock()
    app._cache.get_channel = AsyncMock(return_value=MagicMock(channel_name="general"))
    app._retriever.index = AsyncMock()

    user = MagicMock(user_name="alice")
    await app._handle_message_changed(_make_changed_event(), user)

    saved: MemoryRecord = app._memory.save.call_args[0][0]
    assert saved.thread_ts == "9000000000.000001"


@pytest.mark.asyncio
async def test_message_changed_ignores_unknown_original():
    """If the original message is not in memory, no annotation is stored."""
    app = _make_app()
    app._memory.get_by_ts = AsyncMock(return_value=None)
    app._memory.save = AsyncMock()

    user = MagicMock(user_name="alice")
    await app._handle_message_changed(_make_changed_event(), user)

    app._memory.save.assert_not_called()


@pytest.mark.asyncio
async def test_message_changed_no_original_ts_ignored():
    """Event without original_ts is silently ignored."""
    app = _make_app()
    app._memory.get_by_ts = AsyncMock()
    app._memory.save = AsyncMock()

    event = _make_changed_event()
    event.original_ts = None
    user = MagicMock()

    await app._handle_message_changed(event, user)

    app._memory.get_by_ts.assert_not_called()
    app._memory.save.assert_not_called()


# ---------------------------------------------------------------------------
# _handle_message_deleted
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_message_deleted_hot_record_removed():
    """HOT records are deleted from memory and their embedding is removed."""
    app = _make_app()
    original = _make_record(state=MemoryState.HOT, embedding_id="emb-001")

    app._memory.get_by_ts = AsyncMock(return_value=original)
    app._memory.delete = AsyncMock()
    app._embeddings.delete = AsyncMock()

    await app._handle_message_deleted(_make_deleted_event())

    app._embeddings.delete.assert_called_once_with("emb-001")
    app._memory.delete.assert_called_once_with("rec-001")


@pytest.mark.asyncio
async def test_message_deleted_pinned_record_removed():
    """PINNED records are also deleted — the delete intent takes priority."""
    app = _make_app()
    original = _make_record(state=MemoryState.PINNED, embedding_id="emb-002")

    app._memory.get_by_ts = AsyncMock(return_value=original)
    app._memory.delete = AsyncMock()
    app._embeddings.delete = AsyncMock()

    await app._handle_message_deleted(_make_deleted_event())

    app._embeddings.delete.assert_called_once_with("emb-002")
    app._memory.delete.assert_called_once_with("rec-001")


@pytest.mark.asyncio
async def test_message_deleted_warm_record_left_intact():
    """WARM (already summarized) records are not deleted."""
    app = _make_app()
    original = _make_record(state=MemoryState.WARM)

    app._memory.get_by_ts = AsyncMock(return_value=original)
    app._memory.delete = AsyncMock()
    app._embeddings.delete = AsyncMock()

    await app._handle_message_deleted(_make_deleted_event())

    app._memory.delete.assert_not_called()
    app._embeddings.delete.assert_not_called()


@pytest.mark.asyncio
async def test_message_deleted_cold_record_left_intact():
    """COLD (already summarized) records are not deleted."""
    app = _make_app()
    original = _make_record(state=MemoryState.COLD)

    app._memory.get_by_ts = AsyncMock(return_value=original)
    app._memory.delete = AsyncMock()
    app._embeddings.delete = AsyncMock()

    await app._handle_message_deleted(_make_deleted_event())

    app._memory.delete.assert_not_called()
    app._embeddings.delete.assert_not_called()


@pytest.mark.asyncio
async def test_message_deleted_no_embedding_id_skips_embedding_delete():
    """If the record has no embedding_id, embedding deletion is skipped gracefully."""
    app = _make_app()
    original = _make_record(state=MemoryState.HOT, embedding_id=None)

    app._memory.get_by_ts = AsyncMock(return_value=original)
    app._memory.delete = AsyncMock()
    app._embeddings.delete = AsyncMock()

    await app._handle_message_deleted(_make_deleted_event())

    app._embeddings.delete.assert_not_called()
    app._memory.delete.assert_called_once_with("rec-001")


@pytest.mark.asyncio
async def test_message_deleted_not_in_memory_ignored():
    """If the original is not in memory, no deletion occurs."""
    app = _make_app()
    app._memory.get_by_ts = AsyncMock(return_value=None)
    app._memory.delete = AsyncMock()
    app._embeddings.delete = AsyncMock()

    await app._handle_message_deleted(_make_deleted_event())

    app._memory.delete.assert_not_called()


@pytest.mark.asyncio
async def test_message_deleted_no_original_ts_ignored():
    """Event without original_ts is silently ignored."""
    app = _make_app()
    app._memory.get_by_ts = AsyncMock()

    event = _make_deleted_event()
    event.original_ts = None

    await app._handle_message_deleted(event)

    app._memory.get_by_ts.assert_not_called()
