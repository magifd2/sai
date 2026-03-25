"""Tests for Application event deduplication and stale-event guard."""

import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from sai.app import Application
from sai.slack.events import SlackEvent, SlackEventType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(**kwargs) -> Application:
    """Return an Application with every dependency mocked out."""
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


def _make_event(
    ts: str = "1000000000.000001",
    channel_id: str = "C123",
    event_type: SlackEventType = SlackEventType.APP_MENTION,
    user_id: str = "U123",
) -> SlackEvent:
    return SlackEvent(
        event_type=event_type,
        user_id=user_id,
        channel_id=channel_id,
        text="hello",
        ts=ts,
        received_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# _is_duplicate_event — dedup guard unit tests
# ---------------------------------------------------------------------------

def test_first_event_not_duplicate():
    app = _make_app()
    assert not app._is_duplicate_event(_make_event())


def test_same_event_is_duplicate():
    app = _make_app()
    event = _make_event()
    app._is_duplicate_event(event)
    assert app._is_duplicate_event(event)


def test_different_channel_not_duplicate():
    app = _make_app()
    app._is_duplicate_event(_make_event(channel_id="C001"))
    assert not app._is_duplicate_event(_make_event(channel_id="C002"))


def test_different_ts_not_duplicate():
    app = _make_app()
    app._is_duplicate_event(_make_event(ts="1000000000.000001"))
    assert not app._is_duplicate_event(_make_event(ts="1000000000.000002"))


def test_app_mention_and_message_same_ts_not_duplicate():
    """
    Slack sends both a 'message' and an 'app_mention' for the same post.
    They share the same ts, but must NOT deduplicate each other.
    """
    app = _make_app()
    message_event = _make_event(ts="1000000000.000001", event_type=SlackEventType.MESSAGE)
    mention_event = _make_event(ts="1000000000.000001", event_type=SlackEventType.APP_MENTION)

    # message arrives first
    assert not app._is_duplicate_event(message_event)
    # app_mention with same ts must still pass
    assert not app._is_duplicate_event(mention_event)


def test_ttl_eviction_allows_reprocessing():
    """After TTL expiry, the same event should no longer be considered duplicate."""
    app = _make_app()
    app._seen_events_ttl = 1.0

    event_old = _make_event(ts="1000000000.000001")
    event_trigger = _make_event(ts="1000000000.000002")

    app._is_duplicate_event(event_old)

    # Back-date the stored monotonic time past the TTL
    key_old = f"1000000000.000001#C123#{SlackEventType.APP_MENTION.value}"
    app._seen_events[key_old] = time.monotonic() - 2.0

    # A new event triggers eviction
    app._is_duplicate_event(event_trigger)

    assert key_old not in app._seen_events
    # Old event can now be processed again
    assert not app._is_duplicate_event(event_old)


# ---------------------------------------------------------------------------
# Stale event guard — via handle_event
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stale_event_dropped():
    """Events older than startup_time - grace must be silently dropped."""
    app = _make_app()
    app._startup_wall_time = time.time()
    app._stale_event_grace_s = 30.0

    # ts is 60 s before startup → stale
    stale_ts = f"{app._startup_wall_time - 60.0:.6f}"
    event = _make_event(ts=stale_ts)

    await app.handle_event(event)

    app._acl.check.assert_not_called()


@pytest.mark.asyncio
async def test_event_within_grace_window_not_dropped():
    """Events within the grace window must pass the stale guard."""
    app = _make_app()
    app._startup_wall_time = time.time()
    app._stale_event_grace_s = 30.0

    # ts is 10 s before startup → within grace
    fresh_ts = f"{app._startup_wall_time - 10.0:.6f}"
    event = _make_event(ts=fresh_ts)

    # Deny at ACL to stop processing early without needing full mock chain
    acl_result = MagicMock()
    acl_result.allowed = False
    app._acl.check = AsyncMock(return_value=acl_result)
    app._cache.get_user = AsyncMock(return_value=None)

    await app.handle_event(event)

    app._acl.check.assert_called_once()


@pytest.mark.asyncio
async def test_unparseable_ts_passes_stale_guard():
    """An event with an unparseable ts must not be dropped by the stale guard."""
    app = _make_app()
    event = _make_event(ts="not-a-number")

    acl_result = MagicMock()
    acl_result.allowed = False
    app._acl.check = AsyncMock(return_value=acl_result)
    app._cache.get_user = AsyncMock(return_value=None)

    await app.handle_event(event)

    app._acl.check.assert_called_once()


# ---------------------------------------------------------------------------
# Duplicate memory storage guard — _handle_message get_by_ts check
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_message_skips_duplicate_ts():
    """
    When a record with the same ts already exists in memory (because the
    'message' event was processed first), _handle_message must return early
    without inserting a second record.
    """
    app = _make_app()

    # Simulate existing record returned by get_by_ts
    app._memory.get_by_ts = AsyncMock(return_value=MagicMock())
    app._memory.save = AsyncMock()
    app._cache.get_channel = AsyncMock()

    event = _make_event(ts="1000000000.000001", event_type=SlackEventType.MESSAGE)
    # Provide a real user object mock
    user = MagicMock()

    await app._handle_message(event, user)

    # save must NOT have been called
    app._memory.save.assert_not_called()
    app._cache.get_channel.assert_not_called()


@pytest.mark.asyncio
async def test_handle_message_stores_when_ts_absent():
    """
    When no record exists for the ts, _handle_message must proceed to store.
    (Stops early at cache.get_channel to avoid requiring full mock chain.)
    """
    app = _make_app()

    app._memory.get_by_ts = AsyncMock(return_value=None)
    app._cache.get_channel = AsyncMock(return_value=MagicMock(name="general"))

    # Stop early at embedding to avoid the full pipeline
    from unittest.mock import patch
    with patch.object(app, "_memory") as mock_mem, \
         patch.object(app, "_cache") as mock_cache:
        mock_mem.get_by_ts = AsyncMock(return_value=None)
        mock_mem.save = AsyncMock()
        mock_cache.get_channel = AsyncMock(return_value=MagicMock(name="general"))
        # Raise after get_channel to stop without needing full embedding stack
        mock_cache.get_channel.side_effect = StopAsyncIteration

        event = _make_event(ts="1000000000.000001", event_type=SlackEventType.MESSAGE)
        user = MagicMock()

        with pytest.raises(StopAsyncIteration):
            await app._handle_message(event, user)

        # get_by_ts was called and returned None → proceeded past the guard
        mock_mem.get_by_ts.assert_called_once_with(event.ts, event.channel_id)
