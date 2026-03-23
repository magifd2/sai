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
